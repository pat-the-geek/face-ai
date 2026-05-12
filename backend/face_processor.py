"""Détection + alignement facial — pipeline P2.

Pour chaque image téléchargée :
1. Lecture via OpenCV
2. Détection des 468 landmarks 3D via MediaPipe Face Mesh (refine_landmarks=True)
3. Calcul des angles yaw/pitch/roll par heuristiques sur les positions
4. Classification de pose : front | left | right (seuil ±15° sur yaw, spec §5.2)
5. Alignement géométrique : rotation pour horizontaliser yeux, scale pour
   ramener l'écart inter-oculaire à EYE_DISTANCE_TARGET, crop CROP_SIZE×CROP_SIZE
   centré sur le nez (spec §5.3)
6. Persistance : `face_analysis` row + `images.aligned_path` + `analysis_status`
"""
from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from sqlalchemy import select

from config import CROP_OFFSET_Y, CROP_SIZE, EYE_DISTANCE_TARGET, STATIC_DIR
from database import FaceAnalysis, Image, SessionLocal

log = logging.getLogger("face_processor")

LEFT_EYE_LANDMARKS = (33, 133)
RIGHT_EYE_LANDMARKS = (362, 263)
NOSE_TIP_LANDMARK = 1
CHIN_LANDMARK = 152

POSE_THRESHOLD_DEG = 15.0
MIN_EYE_DISTANCE_PX = 25  # en-dessous, l'alignement à 80px target produit du blur


@dataclass
class FaceLandmarks:
    left_eye: tuple[float, float]
    right_eye: tuple[float, float]
    nose: tuple[float, float]
    yaw: float
    pitch: float
    roll: float
    confidence: float
    eye_distance_px: int
    # v024 : mesh MediaPipe complet (478 points source en pixels, x/y).
    # Sera transformé par `align_face` via la matrice d'alignement pour
    # être stocké dans `face_analysis.landmarks_blob` sur l'image alignée.
    mesh_xy: np.ndarray | None = None


@dataclass
class ProcessResult:
    status: str
    detail: str | None = None


_thread_local = threading.local()


def _get_mesh():
    """FaceMesh singleton thread-local — évite ~150 ms de re-init par image.

    `mp.solutions.face_mesh.FaceMesh` n'est pas thread-safe mais est
    raisonnable au sein d'un même thread. Le worker a un thread dédié
    `analyze` qui appelle `process_image` séquentiellement, donc un seul
    mesh suffit côté worker. Pour `/analyze/{id}` côté API (un appel par
    requête HTTP, FastAPI sync), idem 1 mesh par thread uvicorn.
    """
    if not hasattr(_thread_local, "mesh"):
        _thread_local.mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
        )
    return _thread_local.mesh


def _get_face_detector():
    """FaceDetection singleton thread-local — modèle léger (~5 Mo) pour
    **compter** les visages, distinct du FaceMesh utilisé pour
    l'alignement. On garde les deux séparés pour ne pas modifier le
    chemin d'alignement existant (max_num_faces=1) tout en obtenant
    l'info "combien de visages dans la scène" pour qualifier les flagged
    multi-personnes (cf. v025).

    `model_selection=1` = modèle "full range" jusqu'à ~5m, mieux pour
    photos de presse plein cadre que le "short range" (0).
    """
    if not hasattr(_thread_local, "face_detector"):
        _thread_local.face_detector = mp.solutions.face_detection.FaceDetection(
            model_selection=1,
            min_detection_confidence=0.5,
        )
    return _thread_local.face_detector


def count_faces(image_bgr: np.ndarray) -> int:
    """Compte les visages détectés dans l'image source.

    Indépendant de detect_landmarks (qui force max_num_faces=1). Renvoie
    0 si rien détecté ou si la détection échoue silencieusement.
    """
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    result = _get_face_detector().process(rgb)
    if not result.detections:
        return 0
    return len(result.detections)


def _avg_xy(landmarks, indices, w: int, h: int) -> tuple[float, float]:
    xs = [landmarks[i].x for i in indices]
    ys = [landmarks[i].y for i in indices]
    return (sum(xs) / len(xs) * w, sum(ys) / len(ys) * h)


def _estimate_yaw(left_eye_x: float, right_eye_x: float, nose_x: float) -> float:
    """Heuristique : décalage du nez par rapport au centre des yeux,
    normalisé par l'écart inter-oculaire. Calibré pour donner ~30° à mi-profil."""
    eye_center = (left_eye_x + right_eye_x) / 2
    eye_dist = abs(right_eye_x - left_eye_x)
    if eye_dist < 1:
        return 0.0
    offset = (nose_x - eye_center) / eye_dist
    return offset * 60.0


def _estimate_pitch(landmarks) -> float:
    nose_z = landmarks[NOSE_TIP_LANDMARK].z
    chin_z = landmarks[CHIN_LANDMARK].z
    return (nose_z - chin_z) * 100.0


def _estimate_roll(left_eye: tuple[float, float], right_eye: tuple[float, float]) -> float:
    dx = right_eye[0] - left_eye[0]
    dy = right_eye[1] - left_eye[1]
    return math.degrees(math.atan2(dy, dx))


def detect_landmarks(image_bgr: np.ndarray) -> FaceLandmarks | None:
    h, w = image_bgr.shape[:2]
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    result = _get_mesh().process(rgb)

    if not result.multi_face_landmarks:
        return None

    landmarks = result.multi_face_landmarks[0].landmark
    left_eye = _avg_xy(landmarks, LEFT_EYE_LANDMARKS, w, h)
    right_eye = _avg_xy(landmarks, RIGHT_EYE_LANDMARKS, w, h)
    nose = (
        landmarks[NOSE_TIP_LANDMARK].x * w,
        landmarks[NOSE_TIP_LANDMARK].y * h,
    )

    eye_distance = math.hypot(
        right_eye[0] - left_eye[0], right_eye[1] - left_eye[1]
    )

    # v024 : capture le mesh complet (478 points avec refine_landmarks)
    # en coordonnées pixel source. La matrice d'alignement les
    # transformera plus tard pour stockage sur l'image alignée.
    mesh_xy = np.array(
        [(lm.x * w, lm.y * h) for lm in landmarks],
        dtype=np.float32,
    )

    return FaceLandmarks(
        left_eye=left_eye,
        right_eye=right_eye,
        nose=nose,
        yaw=_estimate_yaw(left_eye[0], right_eye[0], nose[0]),
        pitch=_estimate_pitch(landmarks),
        roll=_estimate_roll(left_eye, right_eye),
        confidence=0.95,
        eye_distance_px=int(eye_distance),
        mesh_xy=mesh_xy,
    )


def classify_pose(yaw: float) -> str:
    if yaw <= -POSE_THRESHOLD_DEG:
        return "left"
    if yaw >= POSE_THRESHOLD_DEG:
        return "right"
    return "front"


def align_face(
    image_bgr: np.ndarray, lm: FaceLandmarks
) -> tuple[np.ndarray, np.ndarray]:
    """Retourne `(image_alignée, matrice_M)`. La matrice 2×3 sert à
    transformer d'autres points (ex. le mesh 478 landmarks) du repère
    source vers le repère aligné — cf. v024."""
    eye_center = (
        (lm.left_eye[0] + lm.right_eye[0]) / 2,
        (lm.left_eye[1] + lm.right_eye[1]) / 2,
    )
    scale = EYE_DISTANCE_TARGET / lm.eye_distance_px if lm.eye_distance_px > 0 else 1.0

    M = cv2.getRotationMatrix2D(eye_center, lm.roll, scale)

    target_eye_y = CROP_SIZE * CROP_OFFSET_Y
    target_eye_center_x = CROP_SIZE / 2.0
    M[0, 2] += target_eye_center_x - eye_center[0]
    M[1, 2] += target_eye_y - eye_center[1]

    aligned = cv2.warpAffine(
        image_bgr,
        M,
        (CROP_SIZE, CROP_SIZE),
        borderMode=cv2.BORDER_REPLICATE,
    )
    return aligned, M


def transform_landmarks_to_aligned(mesh_xy: np.ndarray, M: np.ndarray) -> np.ndarray:
    """Applique la matrice d'alignement aux landmarks source pour les
    avoir dans le repère de l'image alignée (300×300).

    Retourne les points normalisés 0..1 sur les coordonnées CROP_SIZE.
    cv2.transform attend `(N, 1, 2)` puis renvoie `(N, 1, 2)`.
    """
    pts = mesh_xy.reshape(-1, 1, 2).astype(np.float32)
    transformed = cv2.transform(pts, M).reshape(-1, 2)
    # Normalise 0..1 pour stockage portable (le viewer SVG re-multiplie)
    return (transformed / CROP_SIZE).astype(np.float32)


def _purge_image(db, image_row: Image) -> None:
    """Supprime l'enregistrement Image + le fichier original sur disque.

    La spec actuelle (§5.4) impose que la DB ne conserve **que** des portraits
    valides. On efface plutôt que de marquer un statut d'échec.
    """
    local = Path(image_row.local_path) if image_row.local_path else None
    aligned = Path(image_row.aligned_path) if image_row.aligned_path else None
    db.delete(image_row)  # cascade supprime aussi face_analysis
    db.commit()
    if local and local.exists():
        local.unlink()
    if aligned and aligned.exists():
        aligned.unlink()


def process_image(image_id: int) -> ProcessResult:
    db = SessionLocal()
    try:
        image_row = db.get(Image, image_id)
        if image_row is None:
            return ProcessResult(status="failed", detail="image not found")
        if not image_row.local_path:
            _purge_image(db, image_row)
            return ProcessResult(status="purged", detail="no local_path")

        path = Path(image_row.local_path)
        if not path.exists():
            _purge_image(db, image_row)
            return ProcessResult(status="purged", detail="file missing")

        image_bgr = cv2.imread(str(path))
        if image_bgr is None:
            _purge_image(db, image_row)
            return ProcessResult(status="purged", detail="not a readable image")

        h, w = image_bgr.shape[:2]
        image_row.width_px = w
        image_row.height_px = h

        if image_row.face_analysis is not None:
            db.delete(image_row.face_analysis)
            db.flush()

        lm = detect_landmarks(image_bgr)

        if lm is None:
            _purge_image(db, image_row)
            return ProcessResult(status="purged", detail="no face detected")

        if lm.eye_distance_px < MIN_EYE_DISTANCE_PX:
            _purge_image(db, image_row)
            return ProcessResult(
                status="purged",
                detail=f"face too small (eye_distance={lm.eye_distance_px}px)",
            )

        aligned_dir = STATIC_DIR / "aligned"
        aligned_dir.mkdir(parents=True, exist_ok=True)
        aligned_path = aligned_dir / f"{image_id}.jpg"
        aligned, M = align_face(image_bgr, lm)
        cv2.imwrite(
            str(aligned_path),
            aligned,
            [int(cv2.IMWRITE_JPEG_QUALITY), 90],
        )

        # v024 : projette le mesh 478 points dans le repère aligné et
        # sérialise en float32. ~3.7 Ko/image. Si la détection n'a pas
        # capturé le mesh (rare), on stocke NULL et l'UI fallback aux
        # 3 points historiques.
        landmarks_blob = None
        if lm.mesh_xy is not None and lm.mesh_xy.size:
            normalized = transform_landmarks_to_aligned(lm.mesh_xy, M)
            landmarks_blob = normalized.tobytes()

        # v025 : compte les visages avant alignement (modèle séparé,
        # n'altère pas le pipeline d'alignement single-face). Au pire 1
        # par construction puisque detect_landmarks a réussi — mais
        # FaceDetection peut détecter des visages plus petits/de profil
        # que FaceMesh manque. >1 = composition multi-personnes.
        faces_in_image = count_faces(image_bgr)

        image_row.aligned_path = str(aligned_path)
        image_row.analysis_status = "done"
        db.add(
            FaceAnalysis(
                image_id=image_id,
                face_detected=True,
                pose=classify_pose(lm.yaw),
                confidence=lm.confidence,
                yaw=lm.yaw,
                pitch=lm.pitch,
                roll=lm.roll,
                eye_distance_px=lm.eye_distance_px,
                left_eye_x=lm.left_eye[0],
                left_eye_y=lm.left_eye[1],
                right_eye_x=lm.right_eye[0],
                right_eye_y=lm.right_eye[1],
                nose_x=lm.nose[0],
                nose_y=lm.nose[1],
                landmarks_blob=landmarks_blob,
                face_count=max(1, faces_in_image),
            )
        )
        db.commit()
        return ProcessResult(status="done")
    finally:
        db.close()


def purge_invalid() -> dict[str, int]:
    """Nettoie l'historique selon §5.4. Idempotent.

    Trois familles de cas couvertes :
    1. Téléchargements en `scrape_status='failed'` (statut hérité avant §5.4)
    2. Analyses en `analysis_status` ∈ {'no_face', 'failed'} (statut hérité)
    3. **Incohérence DB↔disque** : `local_path` renseigné mais le fichier
       a disparu (seeds cassés, suppression manuelle, volume remonté à vide).
       La règle §5.4 implique que l'enregistrement DB ne survit pas au fichier.
    """
    counts = {
        "failed_scrape": 0,
        "no_face_or_failed_analysis": 0,
        "missing_file": 0,
        "files_removed": 0,
    }
    db = SessionLocal()
    try:
        rows = db.execute(
            select(Image).where(Image.scrape_status == "failed")
        ).scalars().all()
        for img in rows:
            had_file = bool(img.local_path) and Path(img.local_path).exists()
            _purge_image(db, img)
            counts["failed_scrape"] += 1
            if had_file:
                counts["files_removed"] += 1

        rows = db.execute(
            select(Image).where(Image.analysis_status.in_(["no_face", "failed"]))
        ).scalars().all()
        for img in rows:
            had_file = bool(img.local_path) and Path(img.local_path).exists()
            _purge_image(db, img)
            counts["no_face_or_failed_analysis"] += 1
            if had_file:
                counts["files_removed"] += 1

        # Incohérence DB↔disque : le fichier a disparu après ingestion
        rows = db.execute(
            select(Image).where(Image.local_path.is_not(None))
        ).scalars().all()
        for img in rows:
            if not Path(img.local_path).exists():
                _purge_image(db, img)
                counts["missing_file"] += 1
    finally:
        db.close()
    return counts


def backfill_landmarks(limit: int | None = None) -> dict[str, int]:
    """Rétro-extrait le mesh 478 points pour les images analysées avant v024.

    Re-run MediaPipe FaceMesh sur l'image **alignée** stockée (300×300),
    pas sur la source — on n'a pas la matrice d'alignement historique.
    L'image alignée étant 300×300 normalisée, les coords renvoyées sont
    directement dans le repère final, on normalise juste 0..1 pour le
    stockage portable.

    Coût : ~150 ms par image (le mesh cache thread-local accélère).
    À 500 images = ~75 s. Idempotent — saute celles qui ont déjà
    `landmarks_blob`.

    Cas d'usage : après migration v024, ré-enrichir l'historique pour
    que LandmarkOverlay affiche le mesh complet sur toutes les images.
    """
    db = SessionLocal()
    try:
        pairs = db.execute(
            select(Image, FaceAnalysis)
            .join(FaceAnalysis, FaceAnalysis.image_id == Image.id)
            .where(
                Image.aligned_path.is_not(None),
                FaceAnalysis.landmarks_blob.is_(None),
            )
            .order_by(Image.id)
            .limit(limit if limit else 10000)
        ).all()
    finally:
        db.close()

    counts = {"total": len(pairs), "filled": 0, "skipped": 0, "missing_file": 0}
    for img, fa in pairs:
        try:
            aligned = cv2.imread(img.aligned_path)
            if aligned is None:
                counts["missing_file"] += 1
                continue
            lm = detect_landmarks(aligned)
            if lm is None or lm.mesh_xy is None or not lm.mesh_xy.size:
                counts["skipped"] += 1
                continue
            # Image alignée déjà en 300×300 → mesh_xy en pixels 0..300.
            # Normalisation 0..1 pour stockage portable.
            normalized = (lm.mesh_xy / CROP_SIZE).astype(np.float32)
            db2 = SessionLocal()
            try:
                fa_row = db2.get(FaceAnalysis, fa.id)
                if fa_row is not None:
                    fa_row.landmarks_blob = normalized.tobytes()
                    db2.commit()
                    counts["filled"] += 1
            finally:
                db2.close()
        except Exception:
            log.exception("backfill_landmarks failed for image %s", img.id)
            counts["skipped"] += 1

    log.info("backfill_landmarks : %s", counts)
    return counts


def backfill_face_counts(limit: int | None = None) -> dict[str, int]:
    """Rétro-compte les visages des images analysées avant v025.

    Re-lit l'image **source** (`Image.local_path`) — pas l'alignée, qui
    a été cropée sur un seul visage et masque le contexte multi-personnes.
    Idempotent : saute les `FaceAnalysis` qui ont déjà `face_count`.

    Coût : ~30 ms par image (FaceDetection plus léger que FaceMesh).
    Sur 600 images ≈ 20 s. Sur 30k ≈ 15 min, à lancer une fois post-migration.
    """
    db = SessionLocal()
    try:
        pairs = db.execute(
            select(Image, FaceAnalysis)
            .join(FaceAnalysis, FaceAnalysis.image_id == Image.id)
            .where(
                Image.local_path.is_not(None),
                FaceAnalysis.face_count.is_(None),
            )
            .order_by(Image.id)
            .limit(limit if limit else 100000)
        ).all()
    finally:
        db.close()

    counts = {"total": len(pairs), "filled": 0, "skipped": 0, "missing_file": 0}
    for img, fa in pairs:
        try:
            local = Path(img.local_path)
            if not local.exists():
                counts["missing_file"] += 1
                continue
            image_bgr = cv2.imread(str(local))
            if image_bgr is None:
                counts["skipped"] += 1
                continue
            n = count_faces(image_bgr)
            db2 = SessionLocal()
            try:
                fa_row = db2.get(FaceAnalysis, fa.id)
                if fa_row is not None:
                    # Garde-fou : si detect_landmarks a marché, il y a au
                    # moins 1 visage. FaceDetection peut être plus strict
                    # et renvoyer 0 sur un visage de profil — ne pas
                    # écraser à 0 dans ce cas.
                    fa_row.face_count = max(1, n)
                    db2.commit()
                    counts["filled"] += 1
            finally:
                db2.close()
        except Exception:
            log.exception("backfill_face_counts failed for image %s", img.id)
            counts["skipped"] += 1

    log.info("backfill_face_counts : %s", counts)
    return counts


def process_pending(limit: int = 100) -> dict[str, int]:
    db = SessionLocal()
    try:
        ids = [
            r[0]
            for r in db.execute(
                select(Image.id)
                .where(
                    Image.scrape_status == "downloaded",
                    Image.analysis_status == "pending",
                )
                .limit(limit)
            )
        ]
    finally:
        db.close()

    counts: dict[str, int] = {"done": 0, "purged": 0, "failed": 0}
    for image_id in ids:
        r = process_image(image_id)
        counts[r.status] = counts.get(r.status, 0) + 1
    return counts


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="FACE.ai face processor")
    parser.add_argument("--reprocess-pending", action="store_true")
    parser.add_argument("--purge-invalid", action="store_true",
                        help="Migration : supprime images héritées en failed/no_face")
    parser.add_argument("--backfill-face-count", action="store_true",
                        help="Migration v025 : compte les visages des images existantes")
    parser.add_argument("--image-id", type=int)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    if args.image_id is not None:
        r = process_image(args.image_id)
        print(f"image {args.image_id}: status={r.status} detail={r.detail}")
    elif args.purge_invalid:
        r = purge_invalid()
        print(f"purgées : {r}")
    elif args.backfill_face_count:
        r = backfill_face_counts(limit=args.limit if args.limit != 100 else None)
        print(f"backfill face_count : {r}")
    elif args.reprocess_pending:
        r = process_pending(limit=args.limit)
        print(f"résultats : {r}")
    else:
        parser.print_help()

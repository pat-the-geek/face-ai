"""Estimation âge + genre **depuis le visage** (bloc B1).

Élargissement de périmètre assumé (cf. CLAUDE.md §1.5 / décision propriétaire
2026-05-30) : on infère des attributs sur l'image, distincts des champs Wikidata
factuels de l'entité. `face_analysis.est_age` / `est_gender` sont des estimations
du modèle, pas des faits — à présenter comme tels côté UI/MCP.

Implémentation : on charge InsightFace `buffalo_s` avec le module `genderage`
(le pack contient `genderage.onnx`), distinct de `identity.py` qui se limite à
detection+recognition pour ne pas perturber le centroïde d'identité. Les deux
apps cohabitent en mémoire ; coût marginal acceptable à l'échelle du corpus
(quelques milliers d'images, CPU).

La passe `compute_missing_attributes` est idempotente et défensive vis-à-vis des
courses avec `analyze_loop` (même posture que `identity_audit`).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import cv2
from sqlalchemy import select
from sqlalchemy.orm.exc import StaleDataError

# Configuration AVANT l'import insightface (sinon téléchargement dans ~/)
os.environ.setdefault("INSIGHTFACE_HOME", "/models/insightface")

from insightface.app import FaceAnalysis  # noqa: E402

from database import FaceAnalysis as FaceAnalysisRow  # éviter collision de nom
from database import Image, SessionLocal

MODEL_NAME = "buffalo_s"

log = logging.getLogger("face_attributes")
_app: FaceAnalysis | None = None


def _get_app() -> FaceAnalysis:
    global _app
    if _app is None:
        log.info("chargement InsightFace %s (detection+genderage)…", MODEL_NAME)
        _app = FaceAnalysis(
            name=MODEL_NAME,
            providers=["CPUExecutionProvider"],
            allowed_modules=["detection", "genderage"],
        )
        _app.prepare(ctx_id=0, det_size=(640, 640))
        log.info("InsightFace genderage prêt")
    return _app


def estimate_age_gender(image_path: Path) -> tuple[float, str] | None:
    """Retourne `(age, gender)` du visage le plus proéminent, ou None.

    `gender` ∈ {'M','F'}. On lit l'image **source** (même choix qu'ArcFace :
    détection + alignement interne InsightFace) et on prend le plus grand bbox
    en cas de composition multi-personnes.
    """
    img = cv2.imread(str(image_path))
    if img is None:
        return None
    faces = _get_app().get(img)
    if not faces:
        return None
    faces.sort(
        key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
        reverse=True,
    )
    face = faces[0]
    age = getattr(face, "age", None)
    # InsightFace expose `sex` ('M'/'F') et/ou `gender` (0=F,1=M) selon version.
    sex = getattr(face, "sex", None)
    if sex not in ("M", "F"):
        gender_int = getattr(face, "gender", None)
        sex = "M" if gender_int == 1 else "F" if gender_int == 0 else None
    if age is None or sex is None:
        return None
    return float(age), sex


def compute_missing_attributes(limit: int = 20) -> dict:
    """Estime âge/genre pour les images analysées sans `est_age`.

    Sélection : images `analysis_status='done'` avec une `FaceAnalysis` dont
    `est_age` est NULL et un `local_path` présent. Idempotent. Défensif face
    aux suppressions concurrentes (workflow audit P9, cleanup) → `skipped`.
    """
    db = SessionLocal()
    try:
        rows = db.execute(
            select(Image.id)
            .join(FaceAnalysisRow, FaceAnalysisRow.image_id == Image.id)
            .where(
                Image.local_path.is_not(None),
                Image.analysis_status == "done",
                FaceAnalysisRow.est_age.is_(None),
            )
            .limit(limit)
        ).all()
        image_ids = [r[0] for r in rows]
    finally:
        db.close()

    counts = {"done": 0, "no_face": 0, "skipped": 0, "missing_file": 0}
    for image_id in image_ids:
        db = SessionLocal()
        try:
            img = db.get(Image, image_id)
            if not img or not img.local_path or img.face_analysis is None:
                counts["skipped"] += 1
                continue
            path = Path(img.local_path)
            if not path.exists():
                counts["missing_file"] += 1
                continue
            result = estimate_age_gender(path)
            if result is None:
                # RetinaFace ne voit pas de visage humain ici — on n'écrit rien
                # (la purge éventuelle est du ressort d'identity_audit).
                counts["no_face"] += 1
                continue
            age, gender = result
            img.face_analysis.est_age = round(age, 1)
            img.face_analysis.est_gender = gender
            try:
                db.commit()
            except StaleDataError:
                db.rollback()
                counts["skipped"] += 1
                continue
            counts["done"] += 1
        finally:
            db.close()
    return counts


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Estimation âge/genre faciale (B1)")
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Estime âge/genre pour toutes les images sans est_age",
    )
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.backfill:
        total = {"done": 0, "no_face": 0, "skipped": 0, "missing_file": 0}
        while True:
            r = compute_missing_attributes(limit=args.limit)
            for k, v in r.items():
                total[k] = total.get(k, 0) + v
            if r["done"] == 0:
                break
            log.info("cumul : %s", total)
        print(f"backfill âge/genre terminé : {total}")
    else:
        parser.print_help()

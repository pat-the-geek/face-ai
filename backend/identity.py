"""Vérification d'identité faciale via InsightFace ArcFace (spec §11.2).

Pipeline distinct du pHash de `embeddings.py` — ne le remplace pas.

| Outil  | Question répondue                              | Distance typique mêmePersonne | Verdict     |
|--------|------------------------------------------------|-------------------------------|-------------|
| pHash  | "Est-ce la même image redistribuée ?"          | ~0.0–0.05                     | doublon     |
| ArcFace| "Est-ce la même personne ?"                    | ~0.3–0.5                      | identité    |

ArcFace permet d'auditer l'association produite par le scraper :
1. Le scraper associe une image à une entité via la caption (`auto`).
2. Le worker calcule l'embedding ArcFace 512-dim.
3. On agrège tous les embeddings d'une entité en un **centroïde d'identité**
   (moyenne L2-renormalisée).
4. Pour chaque image, distance cosine au centroïde de son entité.
   Sous seuil → `confirmed`. Au-dessus → `flagged` (caption trompeuse,
   photo de groupe mal attribuée, etc.) — à examiner en P9.

Stockage : 2048 octets/image (512 floats×4) — ~60 MB pour 30k images.

**Limite connue (à raffiner)** : le centroïde inclut l'image qu'on évalue.
Pour les entités à très peu d'images (≤2), ça biaise vers la confirmation.
À ≥3 images l'effet devient marginal.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import cv2
import numpy as np

# Configuration AVANT l'import insightface — sinon il télécharge dans ~/
os.environ.setdefault("INSIGHTFACE_HOME", "/models/insightface")

from insightface.app import FaceAnalysis  # noqa: E402

MODEL_NAME = "buffalo_s"  # ~16 MB : RetinaFace + ArcFace (compromis taille/perf)
IDENTITY_THRESHOLD = 0.55  # cosine distance ; au-dessus → flagged

log = logging.getLogger("identity")
_app: FaceAnalysis | None = None


def _get_app() -> FaceAnalysis:
    global _app
    if _app is None:
        log.info("chargement InsightFace %s…", MODEL_NAME)
        # `allowed_modules` limite à détection + reconnaissance (skip genre/âge)
        _app = FaceAnalysis(
            name=MODEL_NAME,
            providers=["CPUExecutionProvider"],
            allowed_modules=["detection", "recognition"],
        )
        _app.prepare(ctx_id=0, det_size=(640, 640))
        log.info("InsightFace prêt")
    return _app


def compute_identity(image_path: Path) -> np.ndarray | None:
    """Embedding 512-dim L2-normalisé du visage le plus proéminent, ou None.

    On lit l'image originale plutôt que l'image alignée : InsightFace fait sa
    propre détection + alignement interne (RetinaFace + 5-point similarity
    transform), généralement plus précise que notre alignement géométrique
    par MediaPipe sur cette tâche.
    """
    img = cv2.imread(str(image_path))
    if img is None:
        return None
    faces = _get_app().get(img)
    if not faces:
        return None
    # En cas de plusieurs visages, on prend celui avec le plus grand bbox
    faces.sort(key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]), reverse=True)
    return faces[0].normed_embedding.astype(np.float32)


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """1 − dot(a, b) pour des vecteurs L2-normalisés."""
    return float(1.0 - np.dot(a, b))


def serialize(emb: np.ndarray) -> bytes:
    return emb.astype(np.float32).tobytes()


def deserialize(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype=np.float32)

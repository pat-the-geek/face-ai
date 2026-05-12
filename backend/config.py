import os
from pathlib import Path

DB_PATH = Path(os.getenv("FACE_AI_DB", "./data/face_ai.db"))
STATIC_DIR = Path(os.getenv("FACE_AI_STATIC", "./static"))
ENV = os.getenv("ENV", "development")

DATABASE_URL = f"sqlite:///{DB_PATH}"

EYE_DISTANCE_TARGET = 80
CROP_SIZE = 300
CROP_OFFSET_Y = 0.35

# Intégration WUDD.ai (spec §8, mode pull)
WUDD_BASE_URL = os.getenv("WUDD_BASE_URL", "http://100.72.122.51:5050")
WUDD_PULL_LIMIT = int(os.getenv("WUDD_PULL_LIMIT", "200"))
WUDD_USER_AGENT = "FACE.ai/1.0 (contact@ok-ia.ch)"

# Pull articles WUDD par batch (roadmap court terme)
# Avec ces valeurs, ~120 entités traitées par jour (5 × 24 cycles).
# Refresh d'une entité au plus tôt après 30 jours pour entretien.
WUDD_BATCH_ENTITIES_PER_CYCLE = int(os.getenv("WUDD_BATCH_ENTITIES_PER_CYCLE", "5"))
WUDD_BATCH_CYCLE_MINUTES = int(os.getenv("WUDD_BATCH_CYCLE_MINUTES", "60"))
WUDD_BATCH_ARTICLES_PER_ENTITY = int(os.getenv("WUDD_BATCH_ARTICLES_PER_ENTITY", "50"))
WUDD_BATCH_REFRESH_DAYS = int(os.getenv("WUDD_BATCH_REFRESH_DAYS", "30"))
WUDD_BATCH_FAVORITES_REFRESH_DAYS = int(
    os.getenv("WUDD_BATCH_FAVORITES_REFRESH_DAYS", "7")
)

# Garde-fous auto_merge_by_qid (incident 2026-05-11 : 3 entités absorbées dans
# Altman via QID corrompu). Le canonical ne peut grossir au-delà de ce ratio
# sans confirmation humaine ; et tout score Wikidata < ce seuil refuse la
# fusion auto (un label inexact = trop d'incertitude pour une opération
# irréversible). Les conflits refusés restent visibles via
# `GET /admin/merge-conflicts`.
MERGE_MAX_GROWTH_RATIO = float(os.getenv("MERGE_MAX_GROWTH_RATIO", "1.5"))
MERGE_MIN_WIKIDATA_SCORE = float(os.getenv("MERGE_MIN_WIKIDATA_SCORE", "1.0"))

# DDG picker — élargissement de périmètre vs spec §1.5 (corpus maîtrisé WUDD).
# Désactivé par défaut. Activer explicitement via env `FACE_AI_ENABLE_DDG=true`
# si on accepte d'ingérer des images hors-corpus avec validation manuelle.
# Cf. CLAUDE.md sur la posture éthique du projet.
ENABLE_DDG = os.getenv("FACE_AI_ENABLE_DDG", "false").lower() == "true"
DDG_RATE_LIMIT_HOURS = int(os.getenv("DDG_RATE_LIMIT_HOURS", "24"))

# Fusion par centroïde ArcFace — exige un nombre minimum d'images des
# DEUX côtés pour que le centroïde soit considéré comme fiable. À 1
# image, le centroïde est juste l'image elle-même ; un faux match
# (Mark Hamill avec 1 photo de Trump dans une publication) peut
# matcher accidentellement avec un autre centroïde. Le seuil 5 (~1
# semaine de présence média typique) est calibré empiriquement.
# Seuil auto-merge resserré à 0.20 (de 0.30) : plus strict pour
# éviter les faux positifs sur frères/sosies/vieillissement.
CENTROID_MIN_IMAGES = int(os.getenv("CENTROID_MIN_IMAGES", "5"))
CENTROID_AUTO_DISTANCE = float(os.getenv("CENTROID_AUTO_DISTANCE", "0.20"))
CENTROID_SUGGEST_DISTANCE = float(os.getenv("CENTROID_SUGGEST_DISTANCE", "0.45"))

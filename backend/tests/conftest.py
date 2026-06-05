"""Configuration pytest commune.

Stratégie d'isolation :
- 1 base SQLite temporaire par session
- Migrations Alembic appliquées une fois
- Cleanup explicite des tables entre tests via fixture autouse `_clean_tables`

Cela évite la complexité du `reload(database)` (les imports SQLAlchemy
cachent l'engine) tout en garantissant l'absence de fuite entre tests.

⚠️ **Isolation production — incident 2026-06-02.** `FACE_AI_DB` DOIT être
redirigé AVANT que `database.py` ne soit importé, sinon l'engine SQLAlchemy
se câble sur la **vraie** DB `/data/face_ai.db` et la fixture `_clean_tables`
**efface le corpus de production**. C'est arrivé : un fichier de test avec
`import notifications` au top-level a importé `database` (→ engine prod) dès la
**collecte** pytest, avant que la fixture de session ne s'exécute. La parade :
on fixe l'env **au niveau module de ce conftest** (importé par pytest avant
tout module de test) + un garde-fou `_assert_test_db` qui ABORTE si l'engine
pointe ailleurs que la DB temporaire. Ne PAS importer database/api au
top-level d'un test (utiliser des imports différés dans les fonctions)."""
import os
import tempfile
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────
# Étape critique : redirige la DB AU NIVEAU MODULE (avant collecte des
# tests, donc avant tout `import database`). Un fixture serait trop tard.
# Ne PAS importer database/api/etc. au top-level du conftest.
# ─────────────────────────────────────────────────────────────────

_TEST_WORKSPACE = Path(tempfile.mkdtemp(prefix="face_ai_test_"))
_TEST_DB = _TEST_WORKSPACE / "face_ai_test.db"
_TEST_STATIC = _TEST_WORKSPACE / "static"
(_TEST_STATIC / "originals").mkdir(parents=True, exist_ok=True)
(_TEST_STATIC / "aligned").mkdir(parents=True, exist_ok=True)

os.environ["FACE_AI_DB"] = str(_TEST_DB)
os.environ["FACE_AI_STATIC"] = str(_TEST_STATIC)


def _assert_test_db() -> None:
    """Garde-fou : refuse de tourner si l'engine n'est pas sur la DB de test.

    Empêche de rejouer l'incident 2026-06-02 (effacement du corpus prod par
    `_clean_tables`). Si un module a importé `database` avant la redirection
    de l'env, l'engine pointe sur la prod → on ABORTE la session entière."""
    import database

    bound = str(database.engine.url)
    if str(_TEST_DB) not in bound:
        pytest.exit(
            f"ISOLATION ROMPUE : l'engine SQLAlchemy est câblé sur '{bound}' "
            f"au lieu de la DB de test '{_TEST_DB}'. Un test importe sans doute "
            f"database/api/un module métier au top-level (avant conftest). "
            f"REFUS de tourner pour ne pas effacer la prod.",
            returncode=3,
        )


@pytest.fixture(scope="session", autouse=True)
def _isolate_runtime():
    _assert_test_db()  # avant toute migration / tout test

    from alembic import command
    from alembic.config import Config

    cfg = Config("/app/alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{_TEST_DB}")
    command.upgrade(cfg, "head")

    yield {"db": _TEST_DB, "static": _TEST_STATIC}


@pytest.fixture(autouse=True)
def _clean_tables():
    """Supprime toutes les rows entre chaque test, dans l'ordre des FK."""
    yield
    from database import (
        Article,
        ArticleEntity,
        Entity,
        EntityAlias,
        EntityCooccurrence,
        EntityGdeltCoverage,
        FaceAnalysis,
        Image,
        SessionLocal,
        WorkerEvent,
    )

    s = SessionLocal()
    try:
        s.query(FaceAnalysis).delete()
        s.query(Image).delete()
        s.query(EntityAlias).delete()
        s.query(ArticleEntity).delete()
        s.query(EntityCooccurrence).delete()
        s.query(EntityGdeltCoverage).delete()
        s.query(Entity).delete()
        s.query(Article).delete()
        s.query(WorkerEvent).delete()
        # Vide aussi l'index FTS5 (les triggers le font normalement, ceinture+bretelle)
        s.execute(__import__("sqlalchemy").text("DELETE FROM entities_fts"))
        s.commit()
    finally:
        s.close()


@pytest.fixture
def db():
    """Session SQLAlchemy ouverte, fermée à la fin du test."""
    from database import SessionLocal

    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def client():
    """TestClient FastAPI."""
    from fastapi.testclient import TestClient

    from api import app

    return TestClient(app)


@pytest.fixture
def static_dir():
    """Répertoire static temporaire pour stocker les fichiers test."""
    return Path(os.environ["FACE_AI_STATIC"])

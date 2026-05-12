"""Configuration pytest commune.

Stratégie d'isolation :
- 1 base SQLite temporaire par session (`tmp_path_factory.mktemp(...)`)
- Migrations Alembic appliquées une fois
- Cleanup explicite des tables entre tests via fixture autouse `_clean_tables`

Cela évite la complexité du `reload(database)` (les imports SQLAlchemy
caches l'engine) tout en garantissant l'absence de fuite entre tests.

L'isolation production : les variables d'env `FACE_AI_DB` et `FACE_AI_STATIC`
sont écrasées AVANT tout import de `config`/`database`.
"""
import os
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────
# Étape critique : redirige la DB AVANT que database.py soit importé
# Ne PAS importer database/api/etc. au top-level du conftest.
# ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
def _isolate_runtime(tmp_path_factory):
    workspace = tmp_path_factory.mktemp("face_ai_test")
    test_db = workspace / "face_ai_test.db"
    static_dir = workspace / "static"
    (static_dir / "originals").mkdir(parents=True)
    (static_dir / "aligned").mkdir(parents=True)

    os.environ["FACE_AI_DB"] = str(test_db)
    os.environ["FACE_AI_STATIC"] = str(static_dir)

    # Import différé après set env
    from alembic import command
    from alembic.config import Config

    cfg = Config("/app/alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{test_db}")
    command.upgrade(cfg, "head")

    yield {"db": test_db, "static": static_dir}


@pytest.fixture(autouse=True)
def _clean_tables():
    """Supprime toutes les rows entre chaque test, dans l'ordre des FK."""
    yield
    from database import (
        Article,
        ArticleEntity,
        Entity,
        EntityAlias,
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

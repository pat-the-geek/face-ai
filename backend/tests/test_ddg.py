"""Tests DDG picker — search + ingest + flag env + endpoints.

Pas d'appel réel à DDG : on mocke `DDGS().images()` et le download
binaire. Cible : flag env, idempotence, traçabilité source_provider,
404/403/400 sur les bords.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest


def _enable_ddg(monkeypatch):
    monkeypatch.setattr("config.ENABLE_DDG", True)
    monkeypatch.setattr("ddg_search.search_images.__globals__", {
        **__import__("ddg_search").search_images.__globals__,
    })  # no-op, juste pour montrer qu'on ne touche pas au global state


def _seed_entity(db, slug="sam-altman", name="Altman, Sam"):
    from database import Entity

    e = Entity(name=name, slug=slug, first_seen=datetime(2024, 1, 1))
    db.add(e)
    db.flush()
    return e


# ── ddg_search module ───────────────────────────────────────────────


class TestSearchImages:
    def test_filters_invalid_urls(self, monkeypatch):
        from ddg_search import search_images

        class FakeDDGS:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def images(self, **kwargs):
                return [
                    {"image": "https://example.com/a.jpg", "title": "A"},
                    {"image": "/relative.jpg", "title": "B"},
                    {"image": "", "title": "C"},
                    {"image": None, "title": "D"},
                    {"image": "https://example.com/e.jpg", "title": "E"},
                ]

        monkeypatch.setattr("ddgs.DDGS", FakeDDGS)

        results = search_images("Sam Altman", limit=10)
        assert len(results) == 2
        assert results[0]["image_url"] == "https://example.com/a.jpg"

    def test_returns_empty_on_exception(self, monkeypatch):
        """DDG peut casser (refonte API, rate limit) — on retourne []."""
        from ddg_search import search_images

        class FakeDDGS:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def images(self, **kwargs):
                raise RuntimeError("DDG indisponible")

        monkeypatch.setattr("ddgs.DDGS", FakeDDGS)
        assert search_images("query") == []


class TestIngestImage:
    def test_creates_image_with_ddg_provider(self, db, monkeypatch, static_dir):
        from database import Image
        from ddg_search import ingest_image

        e = _seed_entity(db)
        db.commit()

        monkeypatch.setattr(
            "ddg_search._download",
            lambda url: (b"fakejpegbytes" * 100, 200),
        )

        r = ingest_image(
            e.id,
            "https://example.com/altman.jpg",
            title="Sam Altman speaks",
            source_page="https://reuters.com/article",
        )
        assert r["status"] == "ok"

        img = db.scalar(db.query(Image).filter_by(entity_id=e.id).statement)
        assert img is not None
        assert img.source_provider == "ddg"
        assert img.source_url == "https://example.com/altman.jpg"
        assert img.caption == "Sam Altman speaks"
        assert "DuckDuckGo" in img.copyright_text
        assert img.article_id is None
        assert img.local_path  # fichier écrit sur disque

    def test_idempotent_already_ingested(self, db, monkeypatch):
        """Re-ingérer la même URL renvoie l'existant sans re-download."""
        from ddg_search import ingest_image

        e = _seed_entity(db)
        db.commit()

        download_calls = [0]

        def counting_download(url):
            download_calls[0] += 1
            return (b"x" * 100, 200)

        monkeypatch.setattr("ddg_search._download", counting_download)

        r1 = ingest_image(e.id, "https://ex.com/a.jpg")
        r2 = ingest_image(e.id, "https://ex.com/a.jpg")
        assert r1["status"] == "ok"
        assert r2["status"] == "already_ingested"
        assert r2["image_id"] == r1["image_id"]
        assert download_calls[0] == 1

    def test_handles_download_failure(self, db, monkeypatch):
        from ddg_search import ingest_image

        e = _seed_entity(db)
        db.commit()
        monkeypatch.setattr("ddg_search._download", lambda url: (None, 404))

        r = ingest_image(e.id, "https://ex.com/broken.jpg")
        assert r["status"] == "download_failed"
        assert r["http_status"] == 404

    def test_missing_entity(self, db, monkeypatch):
        from ddg_search import ingest_image

        monkeypatch.setattr("ddg_search._download", lambda url: (b"x", 200))
        assert ingest_image(99999, "https://ex.com/x.jpg")["status"] == "missing_entity"


# ── can_use_ddg garde-fou ───────────────────────────────────────────


class TestCanUseDdg:
    def test_disabled_by_default(self, db, monkeypatch):
        from ddg_search import can_use_ddg

        monkeypatch.setattr("config.ENABLE_DDG", False)
        e = _seed_entity(db)
        db.commit()

        ok, reason = can_use_ddg(e)
        assert ok is False
        assert "disabled" in reason.lower()

    def test_allowed_when_enabled(self, db, monkeypatch):
        from ddg_search import can_use_ddg

        monkeypatch.setattr("config.ENABLE_DDG", True)
        e = _seed_entity(db)
        db.commit()

        ok, reason = can_use_ddg(e)
        assert ok is True
        assert reason is None


# ── Endpoints API ───────────────────────────────────────────────────


class TestSearchDdgEndpoint:
    def test_returns_candidates(self, client, db, monkeypatch):
        monkeypatch.setattr("config.ENABLE_DDG", True)
        _seed_entity(db, slug="sam-altman", name="Altman, Sam")
        db.commit()

        monkeypatch.setattr(
            "ddg_search.search_images",
            lambda query, limit: [
                {
                    "image_url": "https://ex.com/altman.jpg",
                    "thumbnail": "https://ex.com/thumb.jpg",
                    "title": "Sam Altman",
                    "source_page": "https://reuters.com",
                    "width": 800,
                    "height": 600,
                }
            ],
        )

        r = client.post("/entities/sam-altman/search-ddg?limit=5")
        assert r.status_code == 200
        body = r.json()
        assert body["query"] == "Sam Altman"  # converti depuis canonique
        assert body["count"] == 1
        assert body["candidates"][0]["image_url"] == "https://ex.com/altman.jpg"

    def test_403_when_disabled(self, client, db, monkeypatch):
        monkeypatch.setattr("config.ENABLE_DDG", False)
        _seed_entity(db)
        db.commit()

        r = client.post("/entities/sam-altman/search-ddg")
        assert r.status_code == 403
        assert "disabled" in r.json()["detail"].lower()

    def test_404_unknown_slug(self, client, monkeypatch):
        monkeypatch.setattr("config.ENABLE_DDG", True)
        r = client.post("/entities/inconnu/search-ddg")
        assert r.status_code == 404


class TestIngestDdgImageEndpoint:
    def test_ingests_url(self, client, db, monkeypatch, static_dir):
        from database import Image

        monkeypatch.setattr("config.ENABLE_DDG", True)
        e = _seed_entity(db)
        db.commit()
        monkeypatch.setattr(
            "ddg_search._download",
            lambda url: (b"jpegbytes" * 200, 200),
        )

        r = client.post(
            "/entities/sam-altman/ingest-ddg-image",
            json={
                "url": "https://ex.com/altman.jpg",
                "title": "Sam Altman",
                "source_page": "https://reuters.com/x",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"

        img = db.scalar(db.query(Image).filter_by(entity_id=e.id).statement)
        assert img.source_provider == "ddg"

    def test_400_invalid_url(self, client, db, monkeypatch):
        monkeypatch.setattr("config.ENABLE_DDG", True)
        _seed_entity(db)
        db.commit()

        r = client.post(
            "/entities/sam-altman/ingest-ddg-image",
            json={"url": "/relative/path.jpg"},
        )
        assert r.status_code == 400

    def test_403_when_disabled(self, client, db, monkeypatch):
        monkeypatch.setattr("config.ENABLE_DDG", False)
        _seed_entity(db)
        db.commit()

        r = client.post(
            "/entities/sam-altman/ingest-ddg-image",
            json={"url": "https://ex.com/x.jpg"},
        )
        assert r.status_code == 403

    def test_502_on_download_failure(self, client, db, monkeypatch):
        monkeypatch.setattr("config.ENABLE_DDG", True)
        _seed_entity(db)
        db.commit()
        monkeypatch.setattr("ddg_search._download", lambda url: (None, 404))

        r = client.post(
            "/entities/sam-altman/ingest-ddg-image",
            json={"url": "https://ex.com/broken.jpg"},
        )
        assert r.status_code == 502

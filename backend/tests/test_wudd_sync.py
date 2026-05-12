"""Tests wudd_sync.py — orchestration du pull entités PERSON depuis WUDD.

Mocks : `fetch_persons` (HTTP) et `_download_image` (téléchargement
Wikimedia). On vérifie les transitions d'action `created` / `image_added` /
`noop` / `failed` et l'idempotence du pull.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


def _wudd_person(value, mentions=10, image_url=None):
    from wudd_client import WuddPerson

    return WuddPerson(
        value=value,
        mentions=mentions,
        image_url=image_url,
    )


class TestSyncPersons:
    def test_creates_new_entity_with_image(self, db, monkeypatch, static_dir):
        from wudd_sync import sync_persons

        person = _wudd_person(
            "Sam Altman", mentions=89,
            image_url="https://commons.wikimedia.org/x.jpg",
        )
        monkeypatch.setattr("wudd_sync.fetch_persons", lambda limit=None: [person])
        monkeypatch.setattr("wudd_sync._download_image", lambda url: b"fakejpegbytes")

        counts = sync_persons()
        assert counts["created"] == 1
        assert counts["fetched"] == 1
        assert counts["failed"] == 0

        # Vérifie que l'entité existe avec son image
        from database import Entity, Image
        e = db.scalar(db.query(Entity).filter_by(slug="sam-altman").statement)
        assert e is not None
        assert e.wudd_mentions == 89
        images = db.query(Image).filter_by(entity_id=e.id).all()
        assert len(images) == 1
        assert images[0].source_url == person.image_url

    def test_idempotent_second_pull_is_noop(self, db, monkeypatch):
        from wudd_sync import sync_persons

        person = _wudd_person(
            "Sam Altman", mentions=89,
            image_url="https://commons.wikimedia.org/x.jpg",
        )
        monkeypatch.setattr("wudd_sync.fetch_persons", lambda limit=None: [person])
        monkeypatch.setattr("wudd_sync._download_image", lambda url: b"fakejpeg")

        sync_persons()  # 1er pull → created
        counts = sync_persons()  # 2e → entité existe + image existe → noop
        assert counts["created"] == 0
        assert counts["image_added"] == 0
        assert counts["noop"] == 1

    def test_image_added_on_existing_entity_without_image(self, db, monkeypatch):
        """Si une entité existe sans image et que WUDD propose maintenant
        une image, on bascule en 'image_added'."""
        from database import Entity
        from wudd_sync import sync_persons

        e = Entity(name="Altman, Sam", slug="sam-altman")
        db.add(e)
        db.commit()

        person = _wudd_person(
            "Sam Altman", mentions=89,
            image_url="https://commons.wikimedia.org/x.jpg",
        )
        monkeypatch.setattr("wudd_sync.fetch_persons", lambda limit=None: [person])
        monkeypatch.setattr("wudd_sync._download_image", lambda url: b"fakejpeg")

        counts = sync_persons()
        assert counts["image_added"] == 1
        assert counts["created"] == 0

    def test_skips_image_when_download_fails(self, db, monkeypatch):
        """Téléchargement Wikimedia raté → entité créée mais sans image,
        action reste 'created'."""
        from wudd_sync import sync_persons

        person = _wudd_person(
            "Sam Altman", mentions=89,
            image_url="https://commons.wikimedia.org/broken.jpg",
        )
        monkeypatch.setattr("wudd_sync.fetch_persons", lambda limit=None: [person])
        monkeypatch.setattr("wudd_sync._download_image", lambda url: None)

        counts = sync_persons()
        assert counts["created"] == 1
        assert counts["image_added"] == 0

        from database import Entity, Image
        e = db.scalar(db.query(Entity).filter_by(slug="sam-altman").statement)
        assert db.query(Image).filter_by(entity_id=e.id).count() == 0

    def test_empty_pull_returns_zeros(self, monkeypatch):
        from wudd_sync import sync_persons

        monkeypatch.setattr("wudd_sync.fetch_persons", lambda limit=None: [])
        counts = sync_persons()
        assert counts == {
            "fetched": 0, "created": 0, "image_added": 0, "noop": 0, "failed": 0,
        }

    def test_skips_empty_value(self, db, monkeypatch):
        """WUDD pourrait renvoyer un value vide — on le marque failed sans crasher."""
        from wudd_sync import sync_persons

        person = _wudd_person("", mentions=0)
        monkeypatch.setattr("wudd_sync.fetch_persons", lambda limit=None: [person])

        counts = sync_persons()
        assert counts["failed"] == 1
        assert counts["created"] == 0

    def test_handles_not_person_tombstone(self, db, monkeypatch):
        """Une entité bloquée par tombstone not_person (purge antérieure) →
        get_or_create_entity renvoie None, on noop sans recréer."""
        from database import Entity
        from wudd_sync import sync_persons

        # Tombstone existante côté FACE.ai
        tomb = Entity(
            name="OpenAI", slug="openai",
            wikidata_status="not_person",
        )
        db.add(tomb)
        db.commit()

        person = _wudd_person("OpenAI", mentions=50, image_url=None)
        monkeypatch.setattr("wudd_sync.fetch_persons", lambda limit=None: [person])

        counts = sync_persons()
        assert counts["noop"] == 1
        assert counts["created"] == 0

    def test_caches_mentions_count(self, db, monkeypatch):
        """`person.mentions` est cachée dans `entity.wudd_mentions` pour
        le tri batch (sans cette dénormalisation, le `select_next_batch`
        devrait re-fetch WUDD à chaque cycle)."""
        from database import Entity
        from wudd_sync import sync_persons

        person = _wudd_person("Sam Altman", mentions=1234)
        monkeypatch.setattr("wudd_sync.fetch_persons", lambda limit=None: [person])
        monkeypatch.setattr("wudd_sync._download_image", lambda url: b"x")

        sync_persons()

        e = db.scalar(db.query(Entity).filter_by(slug="sam-altman").statement)
        assert e.wudd_mentions == 1234

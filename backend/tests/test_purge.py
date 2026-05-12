"""Tests de la règle §5.4 — la DB ne contient que des portraits valides.

Couvre purge_invalid (cleanup de l'historique) et _purge_image (helper bas niveau).
"""
from pathlib import Path

import pytest


def _make_image(db, **overrides):
    """Helper : crée une entité + une image, retourne l'image."""
    from database import Entity, Image

    entity = db.query(Entity).filter_by(slug="test-entity").first()
    if not entity:
        entity = Entity(name="Test, Entity", slug="test-entity")
        db.add(entity)
        db.flush()

    defaults = {
        "entity_id": entity.id,
        "source_url": "https://example.com/test.jpg",
        "scrape_status": "downloaded",
        "analysis_status": "done",
    }
    defaults.update(overrides)
    img = Image(**defaults)
    db.add(img)
    db.commit()
    return img


class TestPurgeInvalid:
    def test_purges_failed_scrape(self, db):
        from face_processor import purge_invalid

        _make_image(db, scrape_status="failed", analysis_status="pending")
        counts = purge_invalid()
        assert counts["failed_scrape"] == 1

    def test_purges_no_face(self, db):
        from face_processor import purge_invalid

        _make_image(db, analysis_status="no_face")
        counts = purge_invalid()
        assert counts["no_face_or_failed_analysis"] == 1

    def test_purges_failed_analysis(self, db):
        from face_processor import purge_invalid

        _make_image(db, analysis_status="failed")
        counts = purge_invalid()
        assert counts["no_face_or_failed_analysis"] == 1

    def test_purges_missing_file(self, db):
        from face_processor import purge_invalid

        _make_image(
            db,
            local_path="/tmp/definitely_does_not_exist_123456.jpg",
        )
        counts = purge_invalid()
        assert counts["missing_file"] == 1

    def test_keeps_valid_images(self, db, static_dir):
        """Une image avec fichier réel et statuts OK n'est PAS purgée."""
        from database import Image
        from face_processor import purge_invalid

        # Crée un fichier réel dans static_dir
        fake_image = static_dir / "originals" / "valid.jpg"
        fake_image.write_bytes(b"fake jpeg")

        _make_image(db, local_path=str(fake_image))
        purge_invalid()

        assert db.query(Image).count() == 1
        # Le fichier sur disque est aussi conservé
        assert fake_image.exists()

    def test_removes_files_for_purged_images(self, db, static_dir):
        from face_processor import purge_invalid

        fake_image = static_dir / "originals" / "doomed.jpg"
        fake_image.write_bytes(b"fake")
        _make_image(
            db,
            local_path=str(fake_image),
            analysis_status="no_face",
        )

        counts = purge_invalid()
        assert counts["files_removed"] == 1
        assert not fake_image.exists()

    def test_idempotent(self, db):
        """Appeler purge_invalid 2× ne casse rien."""
        from face_processor import purge_invalid

        _make_image(db, analysis_status="no_face")
        purge_invalid()
        # 2e appel sur DB déjà nettoyée
        counts = purge_invalid()
        assert counts == {
            "failed_scrape": 0,
            "no_face_or_failed_analysis": 0,
            "missing_file": 0,
            "files_removed": 0,
        }


class TestPurgeImageCascade:
    def test_purge_image_removes_face_analysis(self, db):
        """_purge_image doit cascader vers face_analysis (cascade ORM)."""
        from database import FaceAnalysis
        from face_processor import _purge_image

        img = _make_image(db)
        db.add(FaceAnalysis(image_id=img.id, face_detected=True, pose="front"))
        db.commit()

        assert db.query(FaceAnalysis).count() == 1
        _purge_image(db, img)
        assert db.query(FaceAnalysis).count() == 0

    def test_purge_image_removes_files(self, db, static_dir):
        from face_processor import _purge_image

        original = static_dir / "originals" / "x.jpg"
        aligned = static_dir / "aligned" / "x.jpg"
        original.write_bytes(b"a")
        aligned.write_bytes(b"b")

        img = _make_image(db, local_path=str(original), aligned_path=str(aligned))
        _purge_image(db, img)
        assert not original.exists()
        assert not aligned.exists()

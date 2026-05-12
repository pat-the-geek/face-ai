"""Tests dedup.py — pHash + score de diversité (spec §11).

Couvre les 3 fonctions publiques sans dépendre du fichier image réel :
les hashes sont injectés directement comme bytes dans `Image.embedding`,
ce qui isole `dedup_entity` / `dedup_all_entities` de l'I/O image.
`compute_missing_embeddings` est testé via mock de `compute_embedding`.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest


def _img(db, entity_id, idx, embedding=None, scraped_at=None, aligned=True):
    """Helper : crée une Image avec scrape_status downloaded."""
    from database import Image

    img = Image(
        entity_id=entity_id,
        source_url=f"https://ex.com/{idx}.jpg",
        local_path=f"/tmp/originals/{idx}.jpg",
        aligned_path=f"/tmp/aligned/{idx}.jpg" if aligned else None,
        scrape_status="downloaded",
        analysis_status="done",
        embedding=embedding,
        scraped_at=scraped_at or datetime(2024, 6, 1, 12, idx % 60),
    )
    db.add(img)
    db.flush()
    return img


# Hashes pHash factices, distance Hamming contrôlée
H_A = bytes([0b00000000] * 8)               # 0 bits à 1
H_A_DUP = bytes([0b00000001] + [0b00000000] * 7)  # 1 bit de diff = dist 1/64 ≈ 0.016
H_B = bytes([0b11111111] * 8)               # 64 bits → distance 1.0 vs H_A


class TestDedupEntity:
    """Cas central : dedup_entity marque les doublons et calcule la diversité."""

    def test_no_op_with_less_than_2_images(self, db):
        from database import Entity
        from dedup import dedup_entity

        e = Entity(name="X, Y", slug="x-y")
        db.add(e)
        db.flush()
        _img(db, e.id, 0, embedding=H_A)
        db.commit()

        r = dedup_entity(e.id)
        assert r == {"checked": 1, "marked": 0, "diversity": None}

    def test_marks_duplicates_below_threshold(self, db):
        from database import Entity, Image
        from dedup import dedup_entity

        e = Entity(name="X, Y", slug="x-y")
        db.add(e)
        db.flush()
        img_a = _img(db, e.id, 0, embedding=H_A,
                     scraped_at=datetime(2024, 1, 1))
        img_dup = _img(db, e.id, 1, embedding=H_A_DUP,
                       scraped_at=datetime(2024, 1, 2))
        db.commit()
        ids = (img_a.id, img_dup.id)

        r = dedup_entity(e.id)
        assert r["marked"] == 1

        db.expire_all()
        a = db.get(Image, ids[0])
        dup = db.get(Image, ids[1])
        # plus ancienne = canonical, plus récente = doublon
        assert a.is_duplicate is False
        assert dup.is_duplicate is True
        assert dup.duplicate_of == a.id

    def test_no_duplicates_when_far_apart(self, db):
        """Si distance >> seuil, rien n'est marqué."""
        from database import Entity, Image
        from dedup import dedup_entity

        e = Entity(name="X, Y", slug="x-y")
        db.add(e)
        db.flush()
        a = _img(db, e.id, 0, embedding=H_A)
        b = _img(db, e.id, 1, embedding=H_B)  # dist 1.0
        db.commit()
        ids = (a.id, b.id)

        r = dedup_entity(e.id)
        assert r["marked"] == 0

        db.expire_all()
        for iid in ids:
            assert db.get(Image, iid).is_duplicate is False

    def test_diversity_score_with_unique_images(self, db):
        """diversity_score = moyenne des distances pairwise sur uniques."""
        from database import Entity
        from dedup import dedup_entity

        e = Entity(name="X, Y", slug="x-y")
        db.add(e)
        db.flush()
        _img(db, e.id, 0, embedding=H_A)
        _img(db, e.id, 1, embedding=H_B)
        db.commit()

        r = dedup_entity(e.id)
        # Une seule paire (A, B), dist 1.0
        assert r["diversity"] == pytest.approx(1.0, abs=0.01)

    def test_idempotent(self, db):
        """Relancer dedup ne crée pas de chaîne de doublons (reset puis ré-écrit)."""
        from database import Entity, Image
        from dedup import dedup_entity

        e = Entity(name="X, Y", slug="x-y")
        db.add(e)
        db.flush()
        a = _img(db, e.id, 0, embedding=H_A,
                 scraped_at=datetime(2024, 1, 1))
        b = _img(db, e.id, 1, embedding=H_A_DUP,
                 scraped_at=datetime(2024, 1, 2))
        db.commit()

        r1 = dedup_entity(e.id)
        r2 = dedup_entity(e.id)
        assert r1["marked"] == r2["marked"] == 1

        db.expire_all()
        dup = db.get(Image, b.id)
        assert dup.duplicate_of == a.id

    def test_canonical_chain_protection(self, db):
        """A et B presque identiques, C presque identique à B : B est
        marqué doublon de A, C doublon de A (pas de B) — la chaîne est
        coupée, on pointe toujours sur le canonical le plus ancien."""
        from database import Entity, Image
        from dedup import dedup_entity

        e = Entity(name="X, Y", slug="x-y")
        db.add(e)
        db.flush()
        a = _img(db, e.id, 0, embedding=H_A,
                 scraped_at=datetime(2024, 1, 1))
        b = _img(db, e.id, 1,
                 embedding=bytes([0b00000001] + [0] * 7),
                 scraped_at=datetime(2024, 1, 2))
        c = _img(db, e.id, 2,
                 embedding=bytes([0b00000011] + [0] * 7),
                 scraped_at=datetime(2024, 1, 3))
        db.commit()

        dedup_entity(e.id)

        db.expire_all()
        assert db.get(Image, a.id).is_duplicate is False
        assert db.get(Image, b.id).is_duplicate is True
        assert db.get(Image, b.id).duplicate_of == a.id
        # c doit pointer sur a (canonical), pas sur b (qui est lui-même doublon)
        assert db.get(Image, c.id).is_duplicate is True
        assert db.get(Image, c.id).duplicate_of == a.id


class TestDedupAllEntities:
    def test_visits_each_entity_with_embedding(self, db):
        from database import Entity
        from dedup import dedup_all_entities

        e1 = Entity(name="A, X", slug="a-x")
        e2 = Entity(name="B, Y", slug="b-y")
        e3 = Entity(name="C, Z", slug="c-z")  # sans image embedded
        db.add_all([e1, e2, e3])
        db.flush()
        _img(db, e1.id, 0, embedding=H_A)
        _img(db, e1.id, 1, embedding=H_A_DUP)
        _img(db, e2.id, 0, embedding=H_A)
        _img(db, e2.id, 1, embedding=H_B)  # uniques
        db.commit()

        summary = dedup_all_entities()
        assert summary["entities"] == 2  # e3 ignorée
        assert summary["marked_total"] == 1  # uniquement le doublon dans e1

    def test_empty_corpus(self, db):
        from dedup import dedup_all_entities

        assert dedup_all_entities() == {"entities": 0, "marked_total": 0}


class TestComputeMissingEmbeddings:
    def test_skips_images_without_aligned_path(self, db, monkeypatch):
        """Une image sans `aligned_path` n'est pas embeddée."""
        from database import Entity
        from dedup import compute_missing_embeddings

        e = Entity(name="X, Y", slug="x-y")
        db.add(e)
        db.flush()
        _img(db, e.id, 0, aligned=False)
        db.commit()

        # Pas besoin de mock — la query exclut aligned_path IS NULL
        assert compute_missing_embeddings(limit=10) == 0

    def test_uses_compute_embedding_to_fill(self, db, monkeypatch, tmp_path):
        """Pour chaque image alignée sans embedding, on appelle
        compute_embedding et on stocke le résultat."""
        from database import Entity, Image
        from dedup import compute_missing_embeddings

        e = Entity(name="X, Y", slug="x-y")
        db.add(e)
        db.flush()
        img = _img(db, e.id, 0)
        img_id = img.id
        db.commit()

        fake_hash = bytes([42] * 8)
        monkeypatch.setattr("dedup.compute_embedding", lambda path: fake_hash)

        n = compute_missing_embeddings(limit=10)
        assert n == 1

        db.expire_all()
        refreshed = db.get(Image, img_id)
        assert refreshed.embedding == fake_hash

    def test_compute_embedding_failure_skips(self, db, monkeypatch):
        """Si compute_embedding renvoie None (image illisible), pas de crash."""
        from database import Entity
        from dedup import compute_missing_embeddings

        e = Entity(name="X, Y", slug="x-y")
        db.add(e)
        db.flush()
        _img(db, e.id, 0)
        db.commit()

        monkeypatch.setattr("dedup.compute_embedding", lambda path: None)

        n = compute_missing_embeddings(limit=10)
        assert n == 0  # rien ne progresse

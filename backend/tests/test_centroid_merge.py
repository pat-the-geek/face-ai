"""Tests `centroid_merge.py` — détection de paires proches par
distance ArcFace, et garde-fou auto-merge.

On utilise des centroïdes synthétiques (vecteurs L2-normalisés) pour
contrôler précisément les distances.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest


def _make_centroid(seed_value):
    """Vecteur 512-dim factice L2-normalisé. `seed_value` change
    légèrement le vecteur pour qu'on puisse calibrer la distance."""
    rng = np.random.default_rng(seed_value)
    v = rng.standard_normal(512).astype(np.float32)
    return v / np.linalg.norm(v)


def _seed_entity_with_centroid(
    db, slug, name, centroid, image_count=10, qid=None,
):
    from database import Entity
    from identity import serialize

    e = Entity(
        name=name,
        slug=slug,
        wikidata_qid=qid,
        identity_centroid=serialize(centroid),
        identity_count=image_count,
        image_count=image_count,
        first_seen=datetime(2024, 1, 1),
    )
    db.add(e)
    db.flush()
    return e


class TestFindCandidatePairs:
    def test_returns_close_pair(self, db):
        """Deux entités avec centroïdes quasi-identiques sont détectées
        comme candidates (distance < 0.30 → auto-merge possible)."""
        from centroid_merge import find_candidate_pairs

        # Centroïde A
        c_a = _make_centroid(42)
        # Centroïde B : très proche (mix 95% A + 5% bruit, renormalisé)
        c_b_raw = c_a * 0.95 + _make_centroid(7) * 0.05
        c_b = c_b_raw / np.linalg.norm(c_b_raw)

        # 20 vs 3 → growth ratio (20+3)/20 = 1.15 ≤ 1.5 → auto-merge OK
        # ≥ 5 images chaque côté pour passer le seuil CENTROID_MIN_IMAGES.
        _seed_entity_with_centroid(db, "a", "A, X", c_a, image_count=20)
        _seed_entity_with_centroid(db, "b", "B, Y", c_b, image_count=5)
        db.commit()

        pairs = find_candidate_pairs()
        assert len(pairs) == 1
        p = pairs[0]
        assert p.canonical_slug == "a"  # plus d'images
        assert p.duplicate_slug == "b"
        assert p.distance < 0.10  # quasi-identiques
        assert p.can_auto is True
        assert p.block_reason is None

    def test_skips_distant_pairs(self, db):
        """Paire dont la distance dépasse le seuil = pas dans le résultat."""
        from centroid_merge import find_candidate_pairs

        c_a = _make_centroid(1)
        c_b = _make_centroid(999)  # très différent

        _seed_entity_with_centroid(db, "a", "A, X", c_a)
        _seed_entity_with_centroid(db, "b", "B, Y", c_b)
        db.commit()

        pairs = find_candidate_pairs()
        assert pairs == []

    def test_skips_same_qid_pairs(self, db):
        """Paires partageant un QID sont déjà gérées par auto_merge_by_qid."""
        from centroid_merge import find_candidate_pairs

        c = _make_centroid(42)
        c2 = c * 0.99 + _make_centroid(0) * 0.01
        c2 = c2 / np.linalg.norm(c2)

        _seed_entity_with_centroid(db, "a", "A, X", c, qid="Q1")
        _seed_entity_with_centroid(db, "b", "B, Y", c2, qid="Q1")
        db.commit()

        assert find_candidate_pairs() == []

    def test_blocks_high_growth_ratio(self, db):
        """Si fusion ferait grossir le canonical de plus de 50%, refusé."""
        from centroid_merge import find_candidate_pairs

        c_a = _make_centroid(42)
        c_b = c_a * 0.97 + _make_centroid(11) * 0.03
        c_b = c_b / np.linalg.norm(c_b)

        # Canonical 10 images, duplicate 8 → ratio (10+8)/10 = 1.8 > 1.5
        _seed_entity_with_centroid(db, "canon", "A, X", c_a, image_count=10)
        _seed_entity_with_centroid(db, "dup", "B, Y", c_b, image_count=8)
        db.commit()

        pairs = find_candidate_pairs()
        assert len(pairs) == 1
        assert pairs[0].can_auto is False
        assert "growth_ratio" in pairs[0].block_reason

    def test_suggests_when_distance_above_auto_threshold(self, db):
        """Distance > 0.30 (mais ≤ 0.45) → suggéré pour décision manuelle.

        On force la distance via le mock du module : `cosine_distance`
        retourne 0.40 (juste au-dessus du seuil auto 0.30, sous le seuil
        suggestion 0.45). Le garde-fou doit refuser l'auto.
        """
        from centroid_merge import find_candidate_pairs

        c_a = _make_centroid(42)
        c_b = _make_centroid(7)

        # Sizes 20/3 → growth ratio OK ; donc seule la distance peut bloquer
        # ≥ 5 images chaque côté pour passer le seuil CENTROID_MIN_IMAGES.
        _seed_entity_with_centroid(db, "a", "A, X", c_a, image_count=20)
        _seed_entity_with_centroid(db, "b", "B, Y", c_b, image_count=5)
        db.commit()

        # Patch cosine_distance pour retourner 0.40
        import centroid_merge as cm
        original = cm.cosine_distance
        cm.cosine_distance = lambda a, b: 0.40
        try:
            pairs = find_candidate_pairs()
        finally:
            cm.cosine_distance = original

        assert len(pairs) == 1
        assert pairs[0].can_auto is False
        assert "distance" in pairs[0].block_reason

    def test_ignores_entities_without_centroid(self, db):
        from database import Entity
        from centroid_merge import find_candidate_pairs

        c = _make_centroid(1)
        _seed_entity_with_centroid(db, "with-c", "A, X", c)
        # Entité sans centroïde
        e = Entity(
            name="No, Centroid", slug="no-c",
            first_seen=datetime(2024, 1, 1),
        )
        db.add(e)
        db.commit()

        # Une seule entité avec centroïde → 0 paires possibles
        assert find_candidate_pairs() == []

    def test_ignores_not_person_tombstones(self, db):
        """Les tombstones ne sont jamais des candidates de fusion."""
        from centroid_merge import find_candidate_pairs

        c_a = _make_centroid(42)
        c_b = c_a * 0.99 + _make_centroid(0) * 0.01
        c_b = c_b / np.linalg.norm(c_b)

        _seed_entity_with_centroid(db, "real", "A, X", c_a)
        # Tombstone
        tomb = _seed_entity_with_centroid(db, "tomb", "B, Y", c_b)
        tomb.wikidata_status = "not_person"
        db.commit()

        assert find_candidate_pairs() == []

    def test_ignores_entities_below_min_images(self, db):
        """Centroïdes calculés à partir de < CENTROID_MIN_IMAGES (5 par
        défaut) ne sont pas fiables : observé live, Mark Hamill (1 img)
        matchait Trump à d=0.20. Le seuil exclut ces faux positifs."""
        from centroid_merge import find_candidate_pairs

        c_a = _make_centroid(42)
        c_b = c_a * 0.99 + _make_centroid(0) * 0.01
        c_b = c_b / np.linalg.norm(c_b)

        # Canon = beaucoup d'images (fiable), dup = 1 image (centroïde
        # = juste l'image, non fiable)
        _seed_entity_with_centroid(db, "many", "A, X", c_a, image_count=20)
        _seed_entity_with_centroid(db, "few", "B, Y", c_b, image_count=1)
        db.commit()

        # Avec le seuil par défaut (5), la paire est exclue
        assert find_candidate_pairs() == []

        # Avec `min_images=0`, la paire est incluse (utile pour tests)
        assert len(find_candidate_pairs(min_images=0)) == 1

    def test_pairs_sorted_by_distance(self, db):
        """Les paires les plus proches sortent en premier."""
        from centroid_merge import find_candidate_pairs

        c_a = _make_centroid(42)
        # 3 vecteurs à distance croissante
        c_b = (c_a * 0.99 + _make_centroid(0) * 0.01); c_b /= np.linalg.norm(c_b)
        c_c = (c_a * 0.90 + _make_centroid(1) * 0.10); c_c /= np.linalg.norm(c_c)
        c_d = (c_a * 0.75 + _make_centroid(2) * 0.25); c_d /= np.linalg.norm(c_d)

        _seed_entity_with_centroid(db, "a", "A, X", c_a, image_count=20)
        _seed_entity_with_centroid(db, "b", "B, Y", c_b, image_count=5)
        _seed_entity_with_centroid(db, "c", "C, Z", c_c, image_count=5)
        _seed_entity_with_centroid(db, "d", "D, W", c_d, image_count=5)
        db.commit()

        pairs = find_candidate_pairs()
        distances = [p.distance for p in pairs]
        assert distances == sorted(distances)


class TestAutoMergeByCentroid:
    def test_merges_safe_pair(self, db):
        from database import Entity
        from centroid_merge import auto_merge_by_centroid

        c_a = _make_centroid(42)
        c_b = c_a * 0.995 + _make_centroid(0) * 0.005
        c_b = c_b / np.linalg.norm(c_b)

        # canon=20, dup=5 → seuil min_images=5 OK, ratio (20+5)/20=1.25 < 1.5
        canon = _seed_entity_with_centroid(db, "canon", "A, X", c_a, image_count=20)
        dup = _seed_entity_with_centroid(db, "dup", "B, Y", c_b, image_count=5)
        db.commit()
        canon_id, dup_id = canon.id, dup.id

        summary = auto_merge_by_centroid()
        assert summary["merged"] == 1
        assert summary["blocked"] == 0

        db.expire_all()
        assert db.get(Entity, canon_id) is not None
        # Duplicate fusionné dans canonical
        assert db.get(Entity, dup_id) is None

    def test_blocks_growth_ratio(self, db):
        from database import Entity
        from centroid_merge import auto_merge_by_centroid

        c_a = _make_centroid(42)
        c_b = c_a * 0.99 + _make_centroid(0) * 0.01
        c_b = c_b / np.linalg.norm(c_b)

        # 10 canon + 8 dup → 1.8 > 1.5
        canon = _seed_entity_with_centroid(db, "canon", "A, X", c_a, image_count=10)
        dup = _seed_entity_with_centroid(db, "dup", "B, Y", c_b, image_count=8)
        db.commit()
        canon_id, dup_id = canon.id, dup.id

        summary = auto_merge_by_centroid()
        assert summary["merged"] == 0
        assert summary["blocked"] == 1

        # Les 2 entités existent toujours
        db.expire_all()
        assert db.get(Entity, dup_id) is not None


class TestEndpoints:
    def test_centroid_merge_candidates_endpoint(self, client, db):
        c_a = _make_centroid(42)
        c_b = c_a * 0.995 + _make_centroid(0) * 0.005
        c_b = c_b / np.linalg.norm(c_b)

        _seed_entity_with_centroid(db, "canon", "A, X", c_a, image_count=20)
        _seed_entity_with_centroid(db, "dup", "B, Y", c_b, image_count=5)
        db.commit()

        r = client.get("/admin/centroid-merge-candidates")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 1
        p = data["pairs"][0]
        assert p["canonical"]["slug"] == "canon"
        assert p["duplicate"]["slug"] == "dup"
        assert p["can_auto"] is True

    def test_centroid_auto_merge_endpoint(self, client, db):
        from database import Entity

        c_a = _make_centroid(42)
        c_b = c_a * 0.999 + _make_centroid(0) * 0.001
        c_b = c_b / np.linalg.norm(c_b)

        canon = _seed_entity_with_centroid(db, "c1", "A, X", c_a, image_count=20)
        dup = _seed_entity_with_centroid(db, "d1", "B, Y", c_b, image_count=6)
        db.commit()
        dup_id = dup.id

        r = client.post("/admin/centroid-auto-merge")
        body = r.json()
        assert body["merged"] >= 1

        db.expire_all()
        assert db.get(Entity, dup_id) is None

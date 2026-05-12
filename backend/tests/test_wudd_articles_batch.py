"""Tests wudd_articles_batch.py — priorisation et orchestration du pull batch.

Mocks : `sync_articles_for_person` pour éviter les vrais appels WUDD.
Cible : la logique de sélection (3 passes en cascade), le marquage
`last_articles_synced_at` post-cycle, le statut agrégé.
"""
from __future__ import annotations

from datetime import datetime, timedelta


def _seed_entity(db, slug, name, *,
                 is_favorite=False, mentions=0,
                 last_synced=None, aliases=None):
    from database import Entity, EntityAlias

    e = Entity(
        name=name,
        slug=slug,
        is_favorite=is_favorite,
        wudd_mentions=mentions,
        last_articles_synced_at=last_synced,
    )
    db.add(e)
    db.flush()
    for alias in aliases or []:
        db.add(EntityAlias(entity_id=e.id, alias=alias, source="wudd.ai"))
    db.flush()
    return e


class TestSelectNextBatch:
    def test_favorites_come_first(self, db):
        """Pass 1 : favoris jamais sync prioritaires sur top mentions."""
        from wudd_articles_batch import select_next_batch

        _seed_entity(db, "top-mentioned", "X, Top", mentions=999)
        _seed_entity(db, "favorite", "Y, Fav", is_favorite=True, mentions=10)
        db.commit()

        batch = select_next_batch(1)
        assert len(batch) == 1
        assert batch[0][2] == "favorite"

    def test_top_mentions_when_no_favorite(self, db):
        """Pass 2 : top mentions parmi jamais sync."""
        from wudd_articles_batch import select_next_batch

        _seed_entity(db, "low", "L, Low", mentions=5)
        _seed_entity(db, "high", "H, High", mentions=999)
        _seed_entity(db, "mid", "M, Mid", mentions=50)
        db.commit()

        batch = select_next_batch(2)
        slugs = [b[2] for b in batch]
        # Trié par mentions desc
        assert slugs == ["high", "mid"]

    def test_skips_already_recent_favorites(self, db):
        """Un favori sync il y a 1 jour ne ressort pas (seuil par défaut 7 j)."""
        from wudd_articles_batch import select_next_batch

        recent = datetime.utcnow() - timedelta(days=1)
        _seed_entity(
            db, "recent-fav", "R, Fresh",
            is_favorite=True, last_synced=recent,
        )
        _seed_entity(db, "to-sync", "T, ToSync", mentions=100)
        db.commit()

        batch = select_next_batch(2)
        slugs = [b[2] for b in batch]
        assert "recent-fav" not in slugs
        assert "to-sync" in slugs

    def test_falls_back_to_stale_refresh(self, db):
        """Pass 3 : si pas de favoris ni de jamais-sync, prend les périmés."""
        from wudd_articles_batch import select_next_batch

        old = datetime.utcnow() - timedelta(days=45)  # > 30 j
        recent = datetime.utcnow() - timedelta(days=5)
        _seed_entity(db, "stale-1", "A, Stale", last_synced=old)
        _seed_entity(db, "recent-1", "B, Fresh", last_synced=recent)
        db.commit()

        batch = select_next_batch(2)
        slugs = [b[2] for b in batch]
        assert "stale-1" in slugs
        # `recent-1` ne ressort pas
        assert "recent-1" not in slugs

    def test_uses_alias_for_natural_name(self, db):
        """Quand un alias WUDD existe, on l'utilise comme value (la forme
        que WUDD attend). Sinon on rétro-convertit le canonique."""
        from wudd_articles_batch import select_next_batch

        _seed_entity(
            db, "altman", "Altman, Sam",
            mentions=999, aliases=["Sam Altman"],
        )
        db.commit()
        batch = select_next_batch(1)
        assert batch[0][1] == "Sam Altman"

    def test_canonical_inversion_without_alias(self, db):
        from wudd_articles_batch import select_next_batch

        _seed_entity(db, "musk", "Musk, Elon", mentions=999)
        db.commit()
        batch = select_next_batch(1)
        # Pas d'alias → conversion 'Last, First' → 'First Last'
        assert batch[0][1] == "Elon Musk"

    def test_caps_at_requested_n(self, db):
        from wudd_articles_batch import select_next_batch

        for i in range(10):
            _seed_entity(db, f"e{i}", f"E, {i}", mentions=100 - i)
        db.commit()
        assert len(select_next_batch(3)) == 3


class TestRunBatch:
    def test_marks_last_articles_synced_at(self, db, monkeypatch):
        """Après chaque entité traitée, on pose le timestamp pour ne pas
        retomber dessus au cycle suivant."""
        from database import Entity
        from wudd_articles_batch import run_batch

        e = _seed_entity(db, "x", "X, Test", is_favorite=True, mentions=50)
        db.commit()
        eid = e.id

        monkeypatch.setattr(
            "wudd_articles_batch.sync_articles_for_person",
            lambda v, limit=50: {
                "articles_new": 2,
                "articles_already": 1,
                "images_downloaded": 5,
            },
        )

        summary = run_batch(count=1)
        assert summary["selected"] == 1
        assert summary["entities_processed"] == 1
        assert summary["articles_new"] == 2
        assert summary["images_downloaded"] == 5

        db.expire_all()
        refreshed = db.get(Entity, eid)
        assert refreshed.last_articles_synced_at is not None

    def test_aggregates_across_entities(self, db, monkeypatch):
        from wudd_articles_batch import run_batch

        _seed_entity(db, "a", "A, X", mentions=999)
        _seed_entity(db, "b", "B, Y", mentions=500)
        db.commit()

        monkeypatch.setattr(
            "wudd_articles_batch.sync_articles_for_person",
            lambda v, limit=50: {
                "articles_new": 3,
                "articles_already": 0,
                "images_downloaded": 7,
            },
        )

        summary = run_batch(count=2)
        assert summary["entities_processed"] == 2
        assert summary["articles_new"] == 6
        assert summary["images_downloaded"] == 14

    def test_handles_sync_exception(self, db, monkeypatch):
        """Si une entité plante, le batch continue et l'erreur est loguée
        dans `details`."""
        from wudd_articles_batch import run_batch

        _seed_entity(db, "a", "A, Crash", mentions=999)
        _seed_entity(db, "b", "B, Ok", mentions=500)
        db.commit()

        calls = [0]

        def flaky(value, limit=50):
            calls[0] += 1
            if calls[0] == 1:
                raise RuntimeError("WUDD down")
            return {"articles_new": 1, "articles_already": 0, "images_downloaded": 1}

        monkeypatch.setattr("wudd_articles_batch.sync_articles_for_person", flaky)

        summary = run_batch(count=2)
        assert summary["entities_processed"] == 1  # une seule a réussi
        # Le détail contient une entrée d'erreur
        errors = [d for d in summary["details"] if "error" in d]
        assert len(errors) == 1

    def test_empty_batch_zero_summary(self, db, monkeypatch):
        from wudd_articles_batch import run_batch

        monkeypatch.setattr(
            "wudd_articles_batch.sync_articles_for_person", lambda *a, **kw: {}
        )
        summary = run_batch(count=5)
        assert summary["selected"] == 0
        assert summary["entities_processed"] == 0


class TestStatus:
    def test_counts_ever_and_never_synced(self, db):
        from wudd_articles_batch import status

        _seed_entity(db, "s1", "S, 1", last_synced=datetime.utcnow())
        _seed_entity(db, "n1", "N, 1")
        _seed_entity(db, "n2", "N, 2")
        db.commit()

        s = status()
        assert s["total_entities"] == 3
        assert s["ever_synced"] == 1
        assert s["never_synced"] == 2

    def test_favorites_to_refresh_includes_never_synced(self, db):
        from wudd_articles_batch import status

        _seed_entity(db, "fav", "Fav, X", is_favorite=True)
        _seed_entity(db, "non-fav", "Reg, Y")
        db.commit()

        s = status()
        assert s["favorites_to_refresh"] == 1

    def test_stale_above_30_days(self, db):
        from wudd_articles_batch import status

        old = datetime.utcnow() - timedelta(days=45)
        recent = datetime.utcnow() - timedelta(days=5)
        _seed_entity(db, "stale", "S, X", last_synced=old)
        _seed_entity(db, "fresh", "F, Y", last_synced=recent)
        db.commit()

        s = status()
        assert s["stale_to_refresh"] == 1

    def test_config_keys_present(self, db):
        from wudd_articles_batch import status

        s = status()
        cfg = s["config"]
        assert "entities_per_cycle" in cfg
        assert "articles_per_entity" in cfg
        assert "favorites_refresh_days" in cfg
        assert "refresh_days" in cfg

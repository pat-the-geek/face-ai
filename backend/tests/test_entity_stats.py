"""Tests entity_stats.py — source de vérité des compteurs dénormalisés.

Couvre :
- Comptage de base images / unique_images / article_count
- Exclusion des is_duplicate du unique_image_count
- Comptage d'articles distincts (un article lié 2 fois ne compte pas double)
- Backfill `first_seen` à partir de `min(Article.scraped_at)` quand null
- `recompute_all` itère sur toutes les entités
"""
from __future__ import annotations

from datetime import date, datetime


def _seed_entity(db, slug="x-y", name="X, Y", first_seen=None):
    from database import Entity

    e = Entity(name=name, slug=slug, first_seen=first_seen)
    db.add(e)
    db.flush()
    return e


def _seed_article(db, idx, scraped_at=None):
    from database import Article

    a = Article(
        url=f"https://ex.com/{idx}",
        title=f"art{idx}",
        published_at=date(2024, 6, 1),
        scraped_at=scraped_at or datetime(2024, 6, 1, 12, 0),
    )
    db.add(a)
    db.flush()
    return a


def _seed_image(db, entity_id, idx, is_duplicate=False, article_id=None):
    from database import Image

    img = Image(
        entity_id=entity_id,
        article_id=article_id,
        source_url=f"https://ex.com/img-{idx}",
        scrape_status="downloaded",
        is_duplicate=is_duplicate,
    )
    db.add(img)
    db.flush()
    return img


class TestRecomputeCounts:
    def test_zero_for_empty_entity(self, db):
        from entity_stats import recompute_counts

        e = _seed_entity(db)
        db.commit()

        r = recompute_counts(e.id)
        assert r == {"image_count": 0, "unique_image_count": 0, "article_count": 0}

    def test_image_count_includes_duplicates(self, db):
        from database import Entity
        from entity_stats import recompute_counts

        e = _seed_entity(db)
        _seed_image(db, e.id, 0, is_duplicate=False)
        _seed_image(db, e.id, 1, is_duplicate=True)
        _seed_image(db, e.id, 2, is_duplicate=False)
        db.commit()

        r = recompute_counts(e.id)
        assert r["image_count"] == 3  # tous comptés
        assert r["unique_image_count"] == 2  # exclut is_duplicate

        db.expire_all()
        refreshed = db.get(Entity, e.id)
        assert refreshed.image_count == 3
        assert refreshed.unique_image_count == 2

    def test_article_count_distinct(self, db):
        """Un article lié 2 fois à la même entité ne compte qu'une fois."""
        from database import ArticleEntity
        from entity_stats import recompute_counts

        e = _seed_entity(db)
        a1 = _seed_article(db, 0)
        a2 = _seed_article(db, 1)
        db.add_all([
            ArticleEntity(article_id=a1.id, entity_id=e.id),
            ArticleEntity(article_id=a2.id, entity_id=e.id),
        ])
        db.commit()

        r = recompute_counts(e.id)
        assert r["article_count"] == 2

    def test_backfill_first_seen_when_null(self, db):
        """`first_seen` null se voit remplir par min(Article.scraped_at)."""
        from database import ArticleEntity, Entity
        from entity_stats import recompute_counts

        e = _seed_entity(db, first_seen=None)
        a_old = _seed_article(db, 0, scraped_at=datetime(2024, 1, 1, 10, 0))
        a_new = _seed_article(db, 1, scraped_at=datetime(2024, 6, 1, 10, 0))
        db.add_all([
            ArticleEntity(article_id=a_old.id, entity_id=e.id),
            ArticleEntity(article_id=a_new.id, entity_id=e.id),
        ])
        db.commit()

        recompute_counts(e.id)
        db.expire_all()
        refreshed = db.get(Entity, e.id)
        assert refreshed.first_seen == datetime(2024, 1, 1, 10, 0)

    def test_first_seen_not_overwritten_when_already_set(self, db):
        """Si first_seen est déjà rempli, on ne le change pas (priorité à
        la valeur posée par le scraper au moment de la création)."""
        from database import ArticleEntity, Entity
        from entity_stats import recompute_counts

        existing = datetime(2023, 1, 1, 10, 0)
        e = _seed_entity(db, first_seen=existing)
        # Article antérieur qui aurait pu écraser
        a = _seed_article(db, 0, scraped_at=datetime(2022, 1, 1, 10, 0))
        from database import ArticleEntity as AE
        db.add(AE(article_id=a.id, entity_id=e.id))
        db.commit()

        recompute_counts(e.id)
        db.expire_all()
        refreshed = db.get(Entity, e.id)
        assert refreshed.first_seen == existing  # inchangé

    def test_returns_summary_dict(self, db):
        from entity_stats import recompute_counts

        e = _seed_entity(db)
        _seed_image(db, e.id, 0)
        db.commit()

        r = recompute_counts(e.id)
        assert set(r.keys()) == {"image_count", "unique_image_count", "article_count"}
        assert r["image_count"] == 1


class TestRecomputeAll:
    def test_visits_every_entity(self, db):
        from entity_stats import recompute_all

        e1 = _seed_entity(db, slug="a", name="A, X")
        e2 = _seed_entity(db, slug="b", name="B, Y")
        _seed_image(db, e1.id, 0)
        _seed_image(db, e1.id, 1, is_duplicate=True)
        _seed_image(db, e2.id, 2)
        db.commit()

        summary = recompute_all()
        assert summary["entities"] == 2
        assert summary["total_images"] == 3
        assert summary["total_unique"] == 2

    def test_empty_corpus(self, db):
        from entity_stats import recompute_all

        assert recompute_all() == {
            "entities": 0,
            "total_images": 0,
            "total_unique": 0,
            "total_articles": 0,
        }

    def test_idempotent(self, db):
        """Appeler recompute_all 2 fois donne le même résultat."""
        from entity_stats import recompute_all

        e = _seed_entity(db)
        _seed_image(db, e.id, 0)
        db.commit()

        r1 = recompute_all()
        r2 = recompute_all()
        assert r1 == r2

"""Tests bibliography.py — liste d'articles + export Markdown dossier.

Points de vigilance couverts :
- pagination & tri (récents d'abord) ;
- comptage des images de l'entité (pas le total de l'article) ;
- portrait public : Wikimedia prioritaire, repli source_url, jamais /static ;
- export Markdown EXCLUT les attributs sensibles RGPD art. 9.
"""
from __future__ import annotations

from datetime import date


def _entity(db, slug="jane-doe", name="Doe, Jane", **kw):
    from database import Entity

    e = Entity(name=name, slug=slug, wikidata_status="done", **kw)
    db.add(e)
    db.flush()
    return e


def _article(db, url, title="t", published=None, domain="lemonde.fr"):
    from database import Article

    a = Article(url=url, title=title, published_at=published, source_domain=domain)
    db.add(a)
    db.flush()
    return a


def _link(db, article, entity):
    from database import ArticleEntity

    db.add(ArticleEntity(article_id=article.id, entity_id=entity.id))
    db.flush()


def _image(db, article, entity, source_url="https://ex.com/p.jpg", quality=None):
    from database import FaceAnalysis, Image

    img = Image(
        article_id=article.id,
        entity_id=entity.id,
        source_url=source_url,
        scrape_status="downloaded",
        analysis_status="done",
        is_duplicate=False,
        association_status="auto",
    )
    db.add(img)
    db.flush()
    if quality is not None:
        db.add(FaceAnalysis(image_id=img.id, quality_score=quality))
        db.flush()
    return img


class TestEntityArticles:
    def test_pagination_and_recent_first(self, db):
        from bibliography import entity_articles

        e = _entity(db)
        a_old = _article(db, "https://ex.com/1", "old", date(2024, 1, 1))
        a_new = _article(db, "https://ex.com/2", "new", date(2026, 1, 1))
        _link(db, a_old, e)
        _link(db, a_new, e)
        db.commit()

        res = entity_articles(e.id, limit=1, offset=0)
        assert res["total"] == 2
        assert res["articles"][0]["title"] == "new"  # récent d'abord
        page2 = entity_articles(e.id, limit=1, offset=1)
        assert page2["articles"][0]["title"] == "old"

    def test_image_count_is_entity_specific(self, db):
        from bibliography import entity_articles

        e1 = _entity(db, "e1", "E, One")
        e2 = _entity(db, "e2", "E, Two")
        art = _article(db, "https://ex.com/shared", "shared", date(2025, 1, 1))
        _link(db, art, e1)
        _link(db, art, e2)
        _image(db, art, e1)  # 1 image de e1
        _image(db, art, e2)  # 1 image de e2
        _image(db, art, e2)  # +1 image de e2
        db.commit()

        assert entity_articles(e1.id)["articles"][0]["images"] == 1
        assert entity_articles(e2.id)["articles"][0]["images"] == 2

    def test_empty_entity(self, db):
        from bibliography import entity_articles

        e = _entity(db)
        db.commit()
        res = entity_articles(e.id)
        assert res["total"] == 0
        assert res["articles"] == []


class TestPublicPortrait:
    def test_prefers_wikimedia(self, db):
        from bibliography import public_portrait_url

        e = _entity(db, wiki_thumbnail_url="https://upload.wikimedia.org/x.jpg")
        art = _article(db, "https://ex.com/a")
        _image(db, e and art, e, source_url="https://press.com/p.jpg")
        db.commit()
        assert public_portrait_url(db, e) == "https://upload.wikimedia.org/x.jpg"

    def test_falls_back_to_best_source_url(self, db):
        from bibliography import public_portrait_url

        e = _entity(db, wiki_thumbnail_url=None)
        art = _article(db, "https://ex.com/a")
        _image(db, art, e, source_url="https://press.com/low.jpg", quality=0.2)
        _image(db, art, e, source_url="https://press.com/high.jpg", quality=0.9)
        db.commit()
        # meilleure qualité d'abord
        assert public_portrait_url(db, e) == "https://press.com/high.jpg"

    def test_none_when_no_image_no_wiki(self, db):
        from bibliography import public_portrait_url

        e = _entity(db, wiki_thumbnail_url=None)
        db.commit()
        assert public_portrait_url(db, e) is None


class TestEntityMarkdown:
    def test_excludes_sensitive_art9_fields(self, db):
        from bibliography import entity_markdown

        e = _entity(
            db,
            name="Doe, Jane",
            wiki_summary="Résumé public.",
            occupations="actrice",
            religion="catholicisme",
            ethnic_group="groupe X",
            sexual_orientation="bisexualité",
            medical_condition="condition Y",
        )
        db.commit()
        md = entity_markdown(e.id)
        assert "# Jane Doe" in md
        assert "Résumé public." in md
        assert "actrice" in md
        # art. 9 strictement absents
        for forbidden in ("catholicisme", "groupe X", "bisexualité", "condition Y"):
            assert forbidden not in md

    def test_includes_portrait_and_bibliography(self, db):
        from bibliography import entity_markdown

        e = _entity(db, wiki_thumbnail_url="https://upload.wikimedia.org/x.jpg")
        art = _article(db, "https://ex.com/a", "Un titre", date(2025, 6, 1))
        _link(db, art, e)
        db.commit()
        md = entity_markdown(e.id)
        assert "![Jane Doe](https://upload.wikimedia.org/x.jpg)" in md
        assert "## Bibliographie (1 article(s))" in md
        assert "[Un titre](https://ex.com/a)" in md
        assert "2025-06-01" in md

    def test_none_for_missing_entity(self, db):
        from bibliography import entity_markdown

        assert entity_markdown(999999) is None

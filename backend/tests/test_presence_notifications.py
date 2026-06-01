"""Tests v030 — part de présence, sources, et helpers de notification.

Les notifications réseau (Discord) et le rendu PIL/Ollama ne sont pas testés
en CI (effets de bord externes) ; on couvre la logique DB pure : agrégats de
présence, ventilation des sources, grille heatmap, données de fiche.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta


def _entity(db, slug, name, **kw):
    from database import Entity

    e = Entity(name=name, slug=slug, first_seen=datetime(2024, 1, 1), **kw)
    db.add(e)
    db.flush()
    return e


def _article(db, idx, published_at, domain="lemonde.fr"):
    from database import Article

    a = Article(
        url=f"https://ex.com/a-{idx}",
        title=f"art {idx}",
        published_at=published_at,
        source_domain=domain,
    )
    db.add(a)
    db.flush()
    return a


def _link(db, article, entity):
    from database import ArticleEntity

    db.add(ArticleEntity(article_id=article.id, entity_id=entity.id))
    db.flush()


def _image(db, entity, idx, *, article=None, agency=None):
    from database import Image

    img = Image(
        entity_id=entity.id,
        article_id=article.id if article else None,
        source_url=f"https://ex.com/img-{entity.slug}-{idx}.jpg",
        scrape_status="downloaded",
        association_status="confirmed",
        photo_agency=agency,
    )
    db.add(img)
    db.flush()
    return img


class TestShareOfVoice:
    def test_share_trend_and_ranking(self, db):
        from presence import compute_share_of_voice

        today = date.today()
        a = _entity(db, "a", "A")
        b = _entity(db, "b", "B")
        # A : 3 articles fenêtre courante, 1 fenêtre précédente → trend down/up
        for i in range(3):
            art = _article(db, f"a{i}", today - timedelta(days=2))
            _link(db, art, a)
        art_prev = _article(db, "aprev", today - timedelta(days=40))
        _link(db, art_prev, a)
        # B : 1 article courant, 0 avant → "new"
        artb = _article(db, "b0", today - timedelta(days=1))
        _link(db, artb, b)
        db.commit()

        res = compute_share_of_voice(window_days=30, limit=10)
        names = [e["name"] for e in res["entities"]]
        assert names[0] == "A"  # 3 > 1
        a_row = next(e for e in res["entities"] if e["name"] == "A")
        b_row = next(e for e in res["entities"] if e["name"] == "B")
        assert a_row["articles"] == 3
        assert a_row["prev_articles"] == 1
        assert a_row["trend"] in {"up", "down", "flat"}
        assert b_row["trend"] == "new"
        assert res["total_mentions"] == 4

    def test_excludes_not_person(self, db):
        from presence import compute_share_of_voice

        today = date.today()
        bad = _entity(db, "bad", "Bad", wikidata_status="not_person")
        art = _article(db, "x", today - timedelta(days=1))
        _link(db, art, bad)
        db.commit()

        res = compute_share_of_voice(window_days=30)
        assert all(e["slug"] != "bad" for e in res["entities"])

    def test_endpoint(self, client, db):
        today = date.today()
        e = _entity(db, "c", "C")
        _link(db, _article(db, "c0", today), e)
        db.commit()
        r = client.get("/corpus/share-of-voice?window_days=30&limit=5")
        assert r.status_code == 200
        assert r.json()["entities"][0]["slug"] == "c"


class TestEntitySources:
    def test_agency_and_domain_breakdown(self, db):
        from presence import entity_sources

        e = _entity(db, "src", "Src")
        art1 = _article(db, "s1", date.today(), domain="lemonde.fr")
        art2 = _article(db, "s2", date.today(), domain="rts.ch")
        _image(db, e, 0, article=art1, agency="Getty Images")
        _image(db, e, 1, article=art1, agency="Getty Images")
        _image(db, e, 2, article=art2, agency=None)
        db.commit()

        res = entity_sources(e.id)
        assert res["total_images"] == 3
        assert res["credited_images"] == 2
        assert res["uncredited_images"] == 1
        assert res["agencies"][0]["agency"] == "Getty Images"
        assert res["agencies"][0]["count"] == 2
        domains = {d["domain"] for d in res["domains"]}
        assert {"lemonde.fr", "rts.ch"} <= domains

    def test_endpoint_404_unknown(self, client):
        assert client.get("/entities/nope/sources").status_code == 404


class TestNotificationHelpers:
    def test_first_and_years(self):
        import notifications as N

        assert N._first("a|b|c") == "a"
        assert N._first(None) is None
        assert N._years(date(2000, 1, 1), date(2026, 1, 1)) == 26
        assert N._years(date(2000, 6, 1), date(2026, 1, 1)) == 25

    def test_heatmap_grid_shape(self, db):
        import notifications as N

        e = _entity(db, "h", "H")
        _link(db, _article(db, "h0", date.today()), e)
        db.commit()
        grid = N._heatmap_grid(db, e.id)
        assert grid["total"] >= 1
        assert all(len(col) == 7 for col in grid["grid"])

    def test_entity_card_data_lists(self, db):
        import notifications as N

        e = _entity(db, "d", "D", occupations="acteur|réalisateur", nationalities="France")
        db.commit()
        subtitle, reperes, corpus, facts = N._entity_card_data(db, e)
        assert "acteur" in subtitle
        assert any("Présence" in c for c in corpus)
        assert isinstance(facts, list)

    def test_send_discord_no_webhook(self):
        import notifications as N

        # Sans webhook configuré → renvoie False sans appel réseau.
        assert N.send_discord("test") is False

    def test_cycle_disabled_when_no_webhook(self):
        from notifications import run_notify_cycle

        assert run_notify_cycle() == {"skipped": "disabled"}

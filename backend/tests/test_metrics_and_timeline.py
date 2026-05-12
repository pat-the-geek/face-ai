"""Tests pour les endpoints `/metrics` (Prometheus) et
`/entities/{slug}/timeline` (heatmap), + filtre source_provider sur /flagged.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta


def _seed_entity(db, slug="sam-altman", name="Altman, Sam"):
    from database import Entity

    e = Entity(name=name, slug=slug, first_seen=datetime(2024, 1, 1))
    db.add(e)
    db.flush()
    return e


def _seed_image(db, entity, idx=0, provider="wudd", status="confirmed"):
    from database import Image

    img = Image(
        entity_id=entity.id,
        source_url=f"https://ex.com/img-{idx}.jpg",
        scrape_status="downloaded",
        association_status=status,
        source_provider=provider,
    )
    db.add(img)
    db.flush()
    return img


# ── /metrics ────────────────────────────────────────────────────────


class TestMetricsEndpoint:
    def test_returns_prometheus_format(self, client, db):
        e = _seed_entity(db)
        _seed_image(db, e, 0, provider="wudd")
        _seed_image(db, e, 1, provider="ddg", status="flagged")
        db.commit()

        r = client.get("/metrics")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/plain")

        body = r.text
        # Compteurs de base
        assert "face_ai_entities_total 1" in body
        assert "face_ai_images_total 2" in body
        assert "face_ai_images_flagged 1" in body
        # Ratio = 1/2 = 0.5
        assert "face_ai_images_flagged_ratio 0.500000" in body
        # Labels source_provider
        assert 'face_ai_images_by_provider{provider="wudd"} 1' in body
        assert 'face_ai_images_by_provider{provider="ddg"} 1' in body

    def test_includes_worker_metrics(self, client, db):
        from worker_metrics import record_event, record_success

        record_success("analyze", {"done": 1})
        record_event("merge_ok")

        r = client.get("/metrics")
        assert 'face_ai_worker_successes{loop="analyze"} 1' in r.text
        assert 'face_ai_worker_events_24h{kind="merge_ok"} 1' in r.text

    def test_empty_db_zero_values(self, client):
        r = client.get("/metrics")
        assert r.status_code == 200
        assert "face_ai_entities_total 0" in r.text
        assert "face_ai_images_total 0" in r.text
        assert "face_ai_images_flagged_ratio 0.000000" in r.text


# ── /entities/{slug}/timeline ───────────────────────────────────────


def _seed_article(db, idx, published, sources=None):
    from database import Article

    a = Article(
        url=f"https://ex.com/article-{idx}",
        title=f"art {idx}",
        published_at=published,
    )
    db.add(a)
    db.flush()
    return a


class TestEntityTimeline:
    def test_returns_grouped_days(self, client, db):
        from database import ArticleEntity

        e = _seed_entity(db)
        today = date.today()

        # 2 articles le même jour J-10, 1 article J-20, 1 article J-100
        a1 = _seed_article(db, 1, today - timedelta(days=10))
        a2 = _seed_article(db, 2, today - timedelta(days=10))
        a3 = _seed_article(db, 3, today - timedelta(days=20))
        a4 = _seed_article(db, 4, today - timedelta(days=100))
        for art in (a1, a2, a3, a4):
            db.add(ArticleEntity(article_id=art.id, entity_id=e.id))
        db.commit()

        r = client.get("/entities/sam-altman/timeline")
        assert r.status_code == 200
        data = r.json()
        assert data["total_articles"] == 4
        assert data["total_days"] == 3
        assert data["max_count"] == 2

        # Tri par date ascendant, format ISO
        dates = [d["date"] for d in data["days"]]
        assert dates == sorted(dates)
        # Le pic 2 doit correspondre au jour J-10
        peak_day = [d for d in data["days"] if d["count"] == 2][0]
        assert peak_day["date"] == (today - timedelta(days=10)).isoformat()

    def test_window_excludes_old_articles(self, client, db):
        """> 365 jours = hors fenêtre."""
        from database import ArticleEntity

        e = _seed_entity(db)
        today = date.today()
        # Article daté de 400 jours en arrière — exclu
        a_old = _seed_article(db, 1, today - timedelta(days=400))
        # Article daté d'hier — inclus
        a_recent = _seed_article(db, 2, today - timedelta(days=1))
        for art in (a_old, a_recent):
            db.add(ArticleEntity(article_id=art.id, entity_id=e.id))
        db.commit()

        r = client.get("/entities/sam-altman/timeline")
        data = r.json()
        assert data["total_articles"] == 1
        assert data["days"][0]["date"] == (today - timedelta(days=1)).isoformat()

    def test_empty_timeline_when_no_articles(self, client, db):
        _seed_entity(db)
        db.commit()
        r = client.get("/entities/sam-altman/timeline")
        data = r.json()
        assert data["total_articles"] == 0
        assert data["total_days"] == 0
        assert data["max_count"] == 0
        assert data["days"] == []

    def test_404_unknown_slug(self, client):
        r = client.get("/entities/inconnu/timeline")
        assert r.status_code == 404

    def test_404_not_person_tombstone(self, client, db):
        from database import Entity

        e = Entity(
            name="OpenAI", slug="openai",
            wikidata_status="not_person",
            first_seen=datetime(2024, 1, 1),
        )
        db.add(e)
        db.commit()
        r = client.get("/entities/openai/timeline")
        assert r.status_code == 404

    def test_ignores_articles_without_published_at(self, client, db):
        from database import Article, ArticleEntity

        e = _seed_entity(db)
        # Article sans date publication
        a = Article(
            url="https://ex.com/no-date",
            title="no date",
            published_at=None,
        )
        db.add(a)
        db.flush()
        db.add(ArticleEntity(article_id=a.id, entity_id=e.id))
        db.commit()

        r = client.get("/entities/sam-altman/timeline")
        data = r.json()
        assert data["total_articles"] == 0


# ── /flagged?source_provider= ───────────────────────────────────────


class TestFlaggedSourceProviderFilter:
    def test_filters_to_ddg_only(self, client, db):
        e = _seed_entity(db)
        _seed_image(db, e, 0, provider="wudd", status="flagged")
        _seed_image(db, e, 1, provider="ddg", status="flagged")
        _seed_image(db, e, 2, provider="ddg", status="flagged")
        db.commit()

        # Sans filtre : 3
        r = client.get("/flagged")
        assert r.json()["total"] == 3

        # Avec filtre ddg : 2
        r = client.get("/flagged?source_provider=ddg")
        body = r.json()
        assert body["total"] == 2
        assert all(f["source_provider"] == "ddg" for f in body["flagged"])

    def test_ddg_images_come_first_without_filter(self, client, db):
        """Sans filtre, les images non-wudd doivent remonter en haut de
        queue (audit renforcé)."""
        e = _seed_entity(db)
        _seed_image(db, e, 0, provider="wudd", status="flagged")
        _seed_image(db, e, 1, provider="ddg", status="flagged")
        db.commit()

        r = client.get("/flagged")
        flagged = r.json()["flagged"]
        # DDG en premier
        assert flagged[0]["source_provider"] == "ddg"
        assert flagged[1]["source_provider"] == "wudd"

    def test_source_provider_exposed_on_each_row(self, client, db):
        e = _seed_entity(db)
        _seed_image(db, e, 0, provider="manual", status="flagged")
        db.commit()

        body = client.get("/flagged").json()
        assert body["flagged"][0]["source_provider"] == "manual"

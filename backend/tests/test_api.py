"""Tests des endpoints REST. Pas de réseau, pas de fichiers réels (mocks où nécessaire)."""
from datetime import date, datetime

import pytest


def _seed_two_entities(db):
    """Crée Sam Altman + Elon Musk avec aliases, articles, images et face_analysis."""
    from database import (
        Article,
        ArticleEntity,
        Entity,
        EntityAlias,
        FaceAnalysis,
        Image,
    )

    altman = Entity(
        name="Altman, Sam",
        slug="sam-altman",
        first_seen=datetime(2024, 1, 15),
        article_count=1,
        image_count=2,
        unique_image_count=2,
    )
    musk = Entity(
        name="Musk, Elon",
        slug="elon-musk",
        article_count=1,
        image_count=1,
        unique_image_count=1,
    )
    db.add_all([altman, musk])
    db.flush()

    db.add_all(
        [
            EntityAlias(entity_id=altman.id, alias="Sam Altman"),
            EntityAlias(entity_id=altman.id, alias="Samuel H. Altman"),
            EntityAlias(entity_id=musk.id, alias="Elon Musk"),
        ]
    )

    article = Article(
        url="https://wudd.ai/articles/test1",
        title="Article test",
        published_at=date(2024, 3, 1),
        source_domain="wudd.ai",
    )
    db.add(article)
    db.flush()

    db.add_all(
        [
            ArticleEntity(article_id=article.id, entity_id=altman.id),
            ArticleEntity(article_id=article.id, entity_id=musk.id),
        ]
    )

    img1 = Image(
        article_id=article.id,
        entity_id=altman.id,
        source_url="https://example.com/altman1.jpg",
        local_path="/tmp/inexistant.jpg",
        aligned_path="/tmp/inexistant_aligned.jpg",
        scrape_status="downloaded",
        analysis_status="done",
        association_status="confirmed",
    )
    img2 = Image(
        article_id=article.id,
        entity_id=altman.id,
        source_url="https://example.com/altman2.jpg",
        local_path="/tmp/inexistant2.jpg",
        scrape_status="downloaded",
        analysis_status="done",
        association_status="auto",
    )
    img3 = Image(
        article_id=article.id,
        entity_id=musk.id,
        source_url="https://example.com/musk1.jpg",
        local_path="/tmp/inexistant3.jpg",
        scrape_status="downloaded",
        analysis_status="done",
    )
    db.add_all([img1, img2, img3])
    db.flush()

    db.add_all(
        [
            FaceAnalysis(image_id=img1.id, face_detected=True, pose="front", yaw=-2.0, eye_distance_px=80),
            FaceAnalysis(image_id=img2.id, face_detected=True, pose="left", yaw=-25.0, eye_distance_px=78),
            FaceAnalysis(image_id=img3.id, face_detected=True, pose="right", yaw=20.0, eye_distance_px=85),
        ]
    )
    db.commit()
    return altman, musk, article


# ── /health ─────────────────────────────────────────────────────────


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# ── /entities (liste, filtres, pagination) ──────────────────────────


def test_entities_empty(client):
    r = client.get("/entities")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["entities"] == []


def test_entities_list(client, db):
    _seed_two_entities(db)
    r = client.get("/entities")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert {e["slug"] for e in body["entities"]} == {"sam-altman", "elon-musk"}


def test_entities_letter_filter(client, db):
    _seed_two_entities(db)
    r = client.get("/entities?letter=A")
    body = r.json()
    assert body["total"] == 1
    assert body["entities"][0]["slug"] == "sam-altman"


def test_entities_letter_filter_unknown(client, db):
    _seed_two_entities(db)
    r = client.get("/entities?letter=Z")
    assert r.json()["total"] == 0


# ── /entities/letters (distribution) ────────────────────────────────


def test_letters_distribution(client, db):
    _seed_two_entities(db)
    body = client.get("/entities/letters").json()
    assert body["total"] == 2
    assert body["letters"]["A"] == 1
    assert body["letters"]["M"] == 1


# ── /entities/{slug} ────────────────────────────────────────────────


def test_entity_detail(client, db):
    _seed_two_entities(db)
    r = client.get("/entities/sam-altman")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Altman, Sam"
    assert "Samuel H. Altman" in body["aliases"]


def test_entity_404(client):
    r = client.get("/entities/inconnu")
    assert r.status_code == 404


# ── /entities/search (FTS5) ─────────────────────────────────────────


class TestSearch:
    def test_search_by_name(self, client, db):
        _seed_two_entities(db)
        body = client.get("/entities/search?q=altman").json()
        slugs = [r["slug"] for r in body["results"]]
        assert "sam-altman" in slugs

    def test_search_by_alias(self, client, db):
        _seed_two_entities(db)
        # "Samuel H. Altman" est un alias → doit retrouver Sam Altman
        body = client.get("/entities/search?q=samuel").json()
        slugs = [r["slug"] for r in body["results"]]
        assert "sam-altman" in slugs

    def test_search_prefix(self, client, db):
        _seed_two_entities(db)
        # Le builder ajoute un wildcard de préfixe → "alt" trouve "altman"
        body = client.get("/entities/search?q=alt").json()
        slugs = [r["slug"] for r in body["results"]]
        assert "sam-altman" in slugs

    def test_search_empty_query_rejected(self, client):
        r = client.get("/entities/search?q=")
        assert r.status_code == 422  # Pydantic min_length

    def test_search_no_results(self, client, db):
        _seed_two_entities(db)
        body = client.get("/entities/search?q=zzznoresult").json()
        assert body["results"] == []


# ── /entities/{slug}/images avec filtres ────────────────────────────


class TestEntityImages:
    def test_all_images(self, client, db):
        _seed_two_entities(db)
        body = client.get("/entities/sam-altman/images").json()
        assert body["total"] == 2
        assert body["filtered"] == 2

    def test_filter_by_pose(self, client, db):
        _seed_two_entities(db)
        body = client.get("/entities/sam-altman/images?pose=front").json()
        assert body["filtered"] == 1
        assert body["images"][0]["face"]["pose"] == "front"

    def test_filter_pose_no_match(self, client, db):
        _seed_two_entities(db)
        body = client.get("/entities/sam-altman/images?pose=right").json()
        assert body["filtered"] == 0


# ── POST /entities/{slug}/collect ───────────────────────────────────


class TestCollectEntity:
    """Force un pull WUDD ciblé sur l'entité affichée (bouton UI)."""

    def test_collect_converts_canonical_name_to_natural(self, client, db, monkeypatch):
        """`Altman, Sam` côté FACE.ai → `Sam Altman` côté WUDD."""
        _seed_two_entities(db)

        called_with: dict = {}

        def fake_sync(value, limit=200):
            called_with["value"] = value
            called_with["limit"] = limit
            return {
                "person": value,
                "articles_fetched": 0,
                "articles_new": 0,
                "articles_already": 0,
                "images_downloaded": 0,
                "images_ignored": 0,
                "images_failed": 0,
            }

        monkeypatch.setattr("wudd_articles_sync.sync_articles_for_person", fake_sync)

        r = client.post("/entities/sam-altman/collect")
        assert r.status_code == 200
        assert called_with["value"] == "Sam Altman"
        assert r.json()["person_searched"] == "Sam Altman"

    def test_collect_respects_limit_param(self, client, db, monkeypatch):
        _seed_two_entities(db)

        captured: dict = {}

        def fake_sync(value, limit=200):
            captured["limit"] = limit
            return {
                "person": value,
                "articles_fetched": 0,
                "articles_new": 0,
                "articles_already": 0,
                "images_downloaded": 0,
                "images_ignored": 0,
                "images_failed": 0,
            }

        monkeypatch.setattr("wudd_articles_sync.sync_articles_for_person", fake_sync)
        client.post("/entities/sam-altman/collect?limit=500")
        assert captured["limit"] == 500

    def test_collect_marks_last_articles_synced_at(self, client, db, monkeypatch):
        """Après une collecte, last_articles_synced_at est posé — le
        batch_loop ne re-traitera pas immédiatement."""
        from database import Entity

        _seed_two_entities(db)

        monkeypatch.setattr(
            "wudd_articles_sync.sync_articles_for_person",
            lambda value, limit=200: {
                "person": value,
                "articles_fetched": 0,
                "articles_new": 0,
                "articles_already": 0,
                "images_downloaded": 0,
                "images_ignored": 0,
                "images_failed": 0,
            },
        )

        r = client.post("/entities/sam-altman/collect")
        assert r.status_code == 200
        db.expire_all()
        altman = db.scalar(
            db.query(Entity).filter_by(slug="sam-altman").statement
        )
        assert altman.last_articles_synced_at is not None

    def test_collect_returns_summary(self, client, db, monkeypatch):
        _seed_two_entities(db)

        monkeypatch.setattr(
            "wudd_articles_sync.sync_articles_for_person",
            lambda value, limit=200: {
                "person": value,
                "articles_fetched": 12,
                "articles_new": 8,
                "articles_already": 4,
                "images_downloaded": 27,
                "images_ignored": 3,
                "images_failed": 0,
            },
        )

        body = client.post("/entities/sam-altman/collect").json()
        assert body["slug"] == "sam-altman"
        assert body["articles_new"] == 8
        assert body["images_downloaded"] == 27
        assert body["articles_already"] == 4

    def test_collect_unknown_404(self, client):
        r = client.post("/entities/personne-inconnue/collect")
        assert r.status_code == 404

    def test_collect_rejects_limit_out_of_bounds(self, client, db):
        _seed_two_entities(db)
        # 0 et > 2000 doivent être refusés par Query(ge=1, le=2000)
        assert client.post("/entities/sam-altman/collect?limit=0").status_code == 422
        assert client.post("/entities/sam-altman/collect?limit=3000").status_code == 422

    def test_collect_handles_name_without_comma(self, client, db, monkeypatch):
        """Une entité au nom sans virgule (ex. mononyme « Madonna »)
        est passée telle quelle à WUDD."""
        from database import Entity

        e = Entity(name="Madonna", slug="madonna", first_seen=datetime(2024, 1, 1))
        db.add(e)
        db.commit()

        captured: dict = {}

        def fake_sync(value, limit=200):
            captured["value"] = value
            return {
                "person": value,
                "articles_fetched": 0,
                "articles_new": 0,
                "articles_already": 0,
                "images_downloaded": 0,
                "images_ignored": 0,
                "images_failed": 0,
            }

        monkeypatch.setattr("wudd_articles_sync.sync_articles_for_person", fake_sync)
        client.post("/entities/madonna/collect")
        assert captured["value"] == "Madonna"


# ── GET /articles, /articles/{id} ───────────────────────────────────


class TestListArticles:
    def test_returns_seeded_articles(self, client, db):
        _seed_two_entities(db)
        body = client.get("/articles").json()
        assert body["total"] == 1
        assert body["articles"][0]["url"] == "https://wudd.ai/articles/test1"

    def test_includes_counts(self, client, db):
        _seed_two_entities(db)
        body = client.get("/articles").json()
        item = body["articles"][0]
        # L'article seed est lié à 2 entités et a 3 images (cf. _seed_two_entities)
        assert item["entity_count"] == 2
        assert item["image_count"] >= 1

    def test_filter_by_entity_slug(self, client, db):
        _seed_two_entities(db)
        body = client.get("/articles?entity_slug=sam-altman").json()
        assert body["total"] == 1
        # Filtre négatif sur entité inconnue
        body = client.get("/articles?entity_slug=inconnu").json()
        assert body["total"] == 0

    def test_filter_by_source_domain(self, client, db):
        _seed_two_entities(db)
        body = client.get("/articles?source_domain=wudd.ai").json()
        assert body["total"] == 1
        body = client.get("/articles?source_domain=lemonde.fr").json()
        assert body["total"] == 0

    def test_pagination(self, client, db):
        _seed_two_entities(db)
        body = client.get("/articles?limit=10&offset=0").json()
        assert len(body["articles"]) <= 10


class TestGetArticle:
    def test_returns_full_detail(self, client, db):
        from database import Article

        _seed_two_entities(db)
        art = db.scalar(db.query(Article).statement)

        body = client.get(f"/articles/{art.id}").json()
        assert body["url"] == "https://wudd.ai/articles/test1"
        assert body["title"] == "Article test"
        # Entités liées
        slugs = sorted(e["slug"] for e in body["entities"])
        assert slugs == ["elon-musk", "sam-altman"]
        # Images
        assert isinstance(body["images"], list)
        assert len(body["images"]) >= 1

    def test_404_unknown(self, client):
        r = client.get("/articles/99999")
        assert r.status_code == 404


# ── DELETE /entities/{slug} (droit d'opposition) ────────────────────


class TestDeleteEntity:
    def test_delete_existing(self, client, db):
        _seed_two_entities(db)
        r = client.delete("/entities/sam-altman")
        assert r.status_code == 200
        body = r.json()
        assert body["slug"] == "sam-altman"
        assert body["images_removed"] == 2
        assert body["aliases_removed"] == 2
        assert body["article_links_removed"] == 1

    def test_delete_cascades_to_face_analysis(self, client, db):
        from database import FaceAnalysis

        _seed_two_entities(db)
        client.delete("/entities/sam-altman")
        # Les face_analysis des images d'Altman doivent avoir disparu
        # (les images de Musk en ont une, qui doit subsister)
        remaining = db.query(FaceAnalysis).count()
        assert remaining == 1

    def test_delete_updates_fts(self, client, db):
        _seed_two_entities(db)
        client.delete("/entities/sam-altman")
        # La recherche ne doit plus retourner Altman (trigger FTS5 a fait son job)
        body = client.get("/entities/search?q=altman").json()
        slugs = [r["slug"] for r in body["results"]]
        assert "sam-altman" not in slugs

    def test_delete_unknown_404(self, client):
        r = client.delete("/entities/inconnu")
        assert r.status_code == 404

    def test_delete_does_not_remove_other_entities(self, client, db):
        _seed_two_entities(db)
        client.delete("/entities/sam-altman")
        # Musk subsiste
        body = client.get("/entities/elon-musk").json()
        assert body["slug"] == "elon-musk"

    def test_delete_orphan_articles_count(self, client, db):
        """Article partagé Altman+Musk → 0 orphelin après delete d'un seul."""
        _seed_two_entities(db)
        body = client.delete("/entities/sam-altman").json()
        assert body["orphan_articles"] == 0
        # Mais après le 2e delete, l'article devient orphelin
        body = client.delete("/entities/elon-musk").json()
        assert body["orphan_articles"] == 1

"""Tests wudd_articles_sync.py — orchestration ingestion d'articles WUDD.

Mocks : `fetch_articles_for_person` et `_download_to_memory`. On ne fait pas
de scraping HTML (les images sont fournies par WUDD dans le payload).
"""
from __future__ import annotations


WUDD_ARTICLE_TEMPLATE = {
    "URL": "https://lemonde.fr/article-1",
    "Titre": "Sam Altman annonce un nouveau modèle",
    "Date de publication": "Sat, 09 May 2026 21:30:19 GMT",
    "Sources": ["lemonde.fr"],
    "Images": [
        {
            "url": "https://lemonde.fr/img/altman.jpg",
            "alt": "Sam Altman sur scène",
            "title": "Sam Altman speaking",
            "width": 800,
            "height": 600,
        }
    ],
    "entities": {
        "PERSON": ["Sam Altman"],
    },
}


class TestParsePublicationDate:
    def test_rfc2822_format(self):
        from datetime import date
        from wudd_articles_sync import _parse_publication_date

        assert _parse_publication_date(
            "Sat, 09 May 2026 21:30:19 GMT"
        ) == date(2026, 5, 9)

    def test_iso_format(self):
        from datetime import date
        from wudd_articles_sync import _parse_publication_date

        assert _parse_publication_date("2026-03-15") == date(2026, 3, 15)
        assert _parse_publication_date("2026-03-15T12:00:00") == date(2026, 3, 15)

    def test_none_and_empty(self):
        from wudd_articles_sync import _parse_publication_date

        assert _parse_publication_date(None) is None
        assert _parse_publication_date("") is None

    def test_invalid_returns_none(self):
        from wudd_articles_sync import _parse_publication_date

        assert _parse_publication_date("not-a-date") is None


class TestToCandidate:
    def test_valid_url(self):
        from wudd_articles_sync import _to_candidate

        c = _to_candidate({
            "url": "https://ex.com/x.jpg",
            "alt": "alt",
            "title": "title",
        })
        assert c is not None
        assert c.src == "https://ex.com/x.jpg"
        assert c.alt == "alt"
        assert c.caption == "title"

    def test_caption_falls_back_to_alt(self):
        """Quand `title` est vide, le `caption` reprend l'`alt`."""
        from wudd_articles_sync import _to_candidate

        c = _to_candidate({"url": "https://ex.com/x.jpg", "alt": "alt"})
        assert c.caption == "alt"

    def test_invalid_url_returns_none(self):
        from wudd_articles_sync import _to_candidate

        assert _to_candidate({"url": ""}) is None
        assert _to_candidate({"url": "/relative/path.jpg"}) is None
        assert _to_candidate({"url": None}) is None


class TestIngestArticle:
    def test_creates_article_entity_and_image(self, db, monkeypatch, static_dir):
        from wudd_articles_sync import ingest_article

        monkeypatch.setattr(
            "wudd_articles_sync._download_to_memory",
            lambda url: (b"fakejpegbytes", 200),
        )

        result = ingest_article(WUDD_ARTICLE_TEMPLATE)
        assert result["status"] == "ok"
        assert result["images_downloaded"] == 1
        assert result["images_failed"] == 0

        from database import Article, Entity, Image
        article = db.scalar(
            db.query(Article).filter_by(url=WUDD_ARTICLE_TEMPLATE["URL"]).statement
        )
        assert article is not None
        assert article.source_domain == "lemonde.fr"

        e = db.scalar(db.query(Entity).filter_by(slug="sam-altman").statement)
        assert e is not None
        images = db.query(Image).filter_by(entity_id=e.id).all()
        assert len(images) == 1
        assert images[0].source_url == WUDD_ARTICLE_TEMPLATE["Images"][0]["url"]

    def test_idempotent_second_call(self, db, monkeypatch):
        """Le même article ré-ingéré → status='article_already_ingested',
        pas de re-download."""
        from wudd_articles_sync import ingest_article

        calls = [0]

        def counting_download(url):
            calls[0] += 1
            return (b"x", 200)

        monkeypatch.setattr("wudd_articles_sync._download_to_memory", counting_download)

        r1 = ingest_article(WUDD_ARTICLE_TEMPLATE)
        r2 = ingest_article(WUDD_ARTICLE_TEMPLATE)

        assert r1["status"] == "ok"
        assert r2["status"] == "article_already_ingested"
        assert calls[0] == 1  # un seul download au 1er passage

    def test_skips_no_url(self, db):
        from wudd_articles_sync import ingest_article

        r = ingest_article({"Titre": "no url", "entities": {"PERSON": ["X"]}})
        assert r["status"] == "skip_no_url"

    def test_skips_no_person(self, db):
        from wudd_articles_sync import ingest_article

        r = ingest_article({
            "URL": "https://ex.com/no-person",
            "entities": {"PERSON": []},
        })
        assert r["status"] == "skip_no_person"

    def test_skips_not_person_entities(self, db, monkeypatch):
        """Si toutes les PERSON du payload sont des tombstones not_person,
        l'article peut quand même être ingéré côté Article, mais sans liens
        et donc sans images attribuables."""
        from database import Entity
        from wudd_articles_sync import ingest_article

        # Pré-marquer "OpenAI" en not_person
        tomb = Entity(name="OpenAI", slug="openai", wikidata_status="not_person")
        db.add(tomb)
        db.commit()

        monkeypatch.setattr(
            "wudd_articles_sync._download_to_memory", lambda url: (b"x", 200),
        )

        article = dict(WUDD_ARTICLE_TEMPLATE)
        article["URL"] = "https://lemonde.fr/openai-only"
        article["entities"] = {"PERSON": ["OpenAI"]}
        result = ingest_article(article)
        assert result["status"] == "ok"
        # 0 image attribuée car la seule entité est tombstone
        assert result["images_downloaded"] == 0
        assert result["images_ignored"] == 1


class TestSyncArticlesForPerson:
    def test_aggregates_summary(self, db, monkeypatch):
        from wudd_articles_sync import sync_articles_for_person

        article_2 = dict(WUDD_ARTICLE_TEMPLATE, URL="https://lemonde.fr/art-2")
        articles = [WUDD_ARTICLE_TEMPLATE, article_2]
        monkeypatch.setattr(
            "wudd_articles_sync.fetch_articles_for_person",
            lambda v, limit=20: articles,
        )
        monkeypatch.setattr(
            "wudd_articles_sync._download_to_memory",
            lambda url: (b"jpg", 200),
        )

        summary = sync_articles_for_person("Sam Altman", limit=10)
        assert summary["articles_fetched"] == 2
        assert summary["articles_new"] == 2
        assert summary["articles_already"] == 0
        assert summary["images_downloaded"] == 2

    def test_counts_already_ingested(self, db, monkeypatch):
        from wudd_articles_sync import ingest_article, sync_articles_for_person

        monkeypatch.setattr(
            "wudd_articles_sync._download_to_memory", lambda url: (b"x", 200),
        )
        # Pré-ingestion
        ingest_article(WUDD_ARTICLE_TEMPLATE)

        # 2e pass via sync : doit voir "article_already"
        monkeypatch.setattr(
            "wudd_articles_sync.fetch_articles_for_person",
            lambda v, limit=20: [WUDD_ARTICLE_TEMPLATE],
        )

        summary = sync_articles_for_person("Sam Altman", limit=5)
        assert summary["articles_already"] == 1
        assert summary["articles_new"] == 0

    def test_empty_response_returns_zero_summary(self, monkeypatch):
        from wudd_articles_sync import sync_articles_for_person

        monkeypatch.setattr(
            "wudd_articles_sync.fetch_articles_for_person",
            lambda v, limit=20: [],
        )
        summary = sync_articles_for_person("Inconnu", limit=10)
        assert summary["articles_fetched"] == 0
        assert summary["articles_new"] == 0
        assert summary["images_downloaded"] == 0

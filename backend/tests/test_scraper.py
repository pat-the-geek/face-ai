"""Tests du scraper avec mocks `requests.get`.

Couvre :
- `extract_images` (parsing BeautifulSoup, URL absolue, figcaption)
- `associate_image` (matching par caption / alt / alias)
- `process_article` end-to-end avec mocks HTTP — vérifie en particulier
  que la règle §5.4 (pas d'enregistrement DB pour download raté) est
  bien respectée.
"""
from unittest.mock import MagicMock

import pytest


def _mock_response(status_code=200, content=b"", headers=None, text=""):
    m = MagicMock()
    m.status_code = status_code
    m.headers = headers or {}
    m.text = text
    m.content = content
    m.iter_content = lambda chunk_size=8192: iter(
        [content[i : i + chunk_size] for i in range(0, len(content), chunk_size)]
    )
    return m


# ─────────────────────────────────────────────────────────────────
# extract_images (BeautifulSoup parsing)
# ─────────────────────────────────────────────────────────────────


class TestExtractImages:
    def test_parses_figure_with_caption(self):
        from scraper import extract_images
        from tests.fixtures.article_html import ARTICLE_HTML

        candidates = extract_images(
            ARTICLE_HTML, base_url="https://example.com/article"
        )
        # 4 images valides : altman1, musk1, photo, relative
        # Les data: URLs sont skippées
        srcs = [c.src for c in candidates]
        assert "https://cdn.example.com/altman1.jpg" in srcs
        assert "https://cdn.example.com/musk1.jpg" in srcs
        assert "https://cdn.example.com/photo.jpg" in srcs
        # URL relative résolue contre base_url
        assert "https://example.com/static/relative.jpg" in srcs
        # data: URL ignorée
        assert not any(s.startswith("data:") for s in srcs)

    def test_extracts_caption_from_figcaption(self):
        from scraper import extract_images
        from tests.fixtures.article_html import ARTICLE_HTML

        candidates = extract_images(ARTICLE_HTML, base_url="https://example.com")
        altman = next(
            c for c in candidates if "altman1.jpg" in c.src
        )
        assert altman.caption == "Sam Altman lors de la conférence"
        assert altman.alt == "portrait"

    def test_extracts_alt(self):
        from scraper import extract_images
        from tests.fixtures.article_html import ARTICLE_HTML

        candidates = extract_images(ARTICLE_HTML, base_url="https://example.com")
        musk = next(c for c in candidates if "musk1.jpg" in c.src)
        assert musk.alt == "Elon Musk au Forum"
        assert musk.caption is None  # pas de figcaption parent

    def test_empty_page(self):
        from scraper import extract_images
        from tests.fixtures.article_html import ARTICLE_HTML_EMPTY

        assert (
            extract_images(ARTICLE_HTML_EMPTY, base_url="https://example.com") == []
        )


# ─────────────────────────────────────────────────────────────────
# associate_image — matching texte → entité
# ─────────────────────────────────────────────────────────────────


class TestAssociateImage:
    def _make_entity(self, db, name, slug, aliases=()):
        from database import Entity, EntityAlias

        e = Entity(name=name, slug=slug)
        db.add(e)
        db.flush()
        for a in aliases:
            db.add(EntityAlias(entity_id=e.id, alias=a))
        db.commit()
        # Force le chargement des aliases tant que la session est ouverte
        _ = list(e.aliases)
        return e

    def test_matches_canonical_in_alt(self, db):
        from scraper import ImageCandidate, associate_image

        altman = self._make_entity(db, "Altman, Sam", "sam-altman")
        # alt contient "Sam Altman" → match via la forme First-Last dérivée
        cand = ImageCandidate(src="x", alt="Sam Altman souriant", caption=None)
        assert associate_image(cand, [altman]) is altman

    def test_matches_alias_in_caption(self, db):
        from scraper import ImageCandidate, associate_image

        e = self._make_entity(
            db, "Macron, Emmanuel", "emmanuel-macron",
            aliases=["Macron"]
        )
        cand = ImageCandidate(src="x", alt="", caption="Macron au sommet")
        assert associate_image(cand, [e]) is e

    def test_no_match_returns_none(self, db):
        from scraper import ImageCandidate, associate_image

        altman = self._make_entity(db, "Altman, Sam", "sam-altman")
        cand = ImageCandidate(src="x", alt="paysage de montagne", caption=None)
        assert associate_image(cand, [altman]) is None

    def test_first_match_wins(self, db):
        """Une caption mentionnant 2 entités → la 1re dans la liste l'emporte."""
        from scraper import ImageCandidate, associate_image

        altman = self._make_entity(db, "Altman, Sam", "sam-altman")
        musk = self._make_entity(db, "Musk, Elon", "elon-musk")
        cand = ImageCandidate(
            src="x", alt="", caption="Sam Altman et Elon Musk débattent"
        )
        # Avec [altman, musk] → altman gagne
        assert associate_image(cand, [altman, musk]) is altman
        # Avec [musk, altman] → musk gagne
        assert associate_image(cand, [musk, altman]) is musk


# ─────────────────────────────────────────────────────────────────
# process_article — pipeline complet avec mocks
# ─────────────────────────────────────────────────────────────────


class TestProcessArticle:
    def _install_scraper_mock(
        self,
        monkeypatch,
        article_url: str,
        article_html: str,
        image_responses: dict,
    ):
        """Routeur HTTP par URL exacte.

        Match strict par égalité plutôt que par substring : sinon une URL
        d'image résolue contre `base_url=https://wudd.ai/...` (ex.
        `<img src="/static/relative.jpg">`) serait faussement reconnue
        comme l'article. Reproduit fidèlement le routing par hostname réel.
        """

        def router(url, params=None, headers=None, timeout=None, stream=False):
            if url == article_url:
                return _mock_response(status_code=200, text=article_html)
            if url in image_responses:
                return image_responses[url]
            return _mock_response(status_code=404)

        monkeypatch.setattr("scraper.requests.get", router)

    def test_creates_article_and_entity(self, db, monkeypatch):
        from database import Article, Entity, Image
        from scraper import EntityInput, ScrapeInput, process_article
        from tests.fixtures.article_html import ARTICLE_HTML

        # Image valide pour altman1, 404 sur les autres
        # (1 byte — passe la validation taille mais cv2 ne pourra pas la lire,
        # ce qui n'est pas le cas testé ici puisque process_article ne lit pas
        # l'image, ça reste de la responsabilité de face_processor)
        valid_jpg = b"\xff\xd8\xff\xe0fake"  # début JPEG
        article_url = "https://wudd.ai/articles/test"
        self._install_scraper_mock(
            monkeypatch,
            article_url,
            ARTICLE_HTML,
            {
                "https://cdn.example.com/altman1.jpg": _mock_response(
                    status_code=200, content=valid_jpg
                ),
                # `<img src="/static/relative.jpg">` est résolue contre
                # `article_url`, donc l'URL absolue partage le hostname article.
                "https://wudd.ai/static/relative.jpg": _mock_response(
                    status_code=200, content=valid_jpg
                ),
                # Tous les autres → 404 par défaut
            },
        )

        result = process_article(
            ScrapeInput(
                article_url=article_url,
                article_title="Test",
                entities=[EntityInput(name="Sam Altman")],
            )
        )
        assert result.status == "ok"
        assert result.images_found == 4  # 4 images extraites de l'HTML
        # 2 ont matché Sam Altman par caption ou alt
        # et seulement les ones dont le download a réussi sont en DB

        # Vérifier l'entité créée canonisée
        altman = db.query(Entity).filter_by(slug="sam-altman").first()
        assert altman is not None
        assert altman.name == "Altman, Sam"
        assert "Sam Altman" in [a.alias for a in altman.aliases]

        # Article persisté
        article = db.query(Article).filter_by(
            url="https://wudd.ai/articles/test"
        ).first()
        assert article is not None
        assert article.source_domain == "wudd.ai"

    def test_failed_download_leaves_no_db_record(self, db, monkeypatch):
        """Spec §5.4 : URL d'image cassée → AUCUNE trace en DB."""
        from database import Image
        from scraper import EntityInput, ScrapeInput, process_article
        from tests.fixtures.article_html import ARTICLE_HTML

        article_url = "https://wudd.ai/articles/test-broken"
        # Toutes les images en 404
        self._install_scraper_mock(monkeypatch, article_url, ARTICLE_HTML, {})

        result = process_article(
            ScrapeInput(
                article_url=article_url,
                article_title="Test",
                entities=[EntityInput(name="Sam Altman")],
            )
        )
        assert result.status == "ok"
        # 4 images trouvées mais 0 téléchargée → 0 en DB
        assert result.images_downloaded == 0
        assert db.query(Image).count() == 0

    def test_already_scraped_short_circuits(self, db, monkeypatch):
        from database import Article
        from scraper import EntityInput, ScrapeInput, process_article

        # Pré-existe
        existing = Article(
            url="https://wudd.ai/articles/test-existing",
            title="déjà là",
            source_domain="wudd.ai",
        )
        db.add(existing)
        db.commit()

        # Aucune requête HTTP ne devrait être faite — on patch quand même
        call_count = [0]

        def fake_get(*a, **kw):
            call_count[0] += 1
            return _mock_response(text="")

        monkeypatch.setattr("scraper.requests.get", fake_get)

        result = process_article(
            ScrapeInput(
                article_url="https://wudd.ai/articles/test-existing",
                article_title="?",
                entities=[EntityInput(name="X")],
            )
        )
        assert result.status == "already_scraped"
        # Aucun fetch HTML, aucun téléchargement
        assert call_count[0] == 0

    def test_html_fetch_failure(self, db, monkeypatch):
        from scraper import EntityInput, ScrapeInput, process_article

        # fetch_html retourne None → status html_fetch_failed
        monkeypatch.setattr("scraper.fetch_html", lambda url: None)

        result = process_article(
            ScrapeInput(
                article_url="https://wudd.ai/articles/no-html",
                article_title="?",
                entities=[EntityInput(name="X")],
            )
        )
        assert result.status == "html_fetch_failed"

    def test_recompute_counts_called_after_ingestion(self, db, monkeypatch):
        from database import Entity
        from scraper import EntityInput, ScrapeInput, process_article
        from tests.fixtures.article_html import ARTICLE_HTML

        valid_jpg = b"\xff\xd8\xff\xe0fake"
        article_url = "https://wudd.ai/articles/test-counts"
        self._install_scraper_mock(
            monkeypatch,
            article_url,
            ARTICLE_HTML,
            {
                "https://cdn.example.com/altman1.jpg": _mock_response(
                    status_code=200, content=valid_jpg
                ),
            },
        )

        process_article(
            ScrapeInput(
                article_url=article_url,
                article_title="Test",
                entities=[EntityInput(name="Sam Altman")],
            )
        )

        altman = db.query(Entity).filter_by(slug="sam-altman").first()
        assert altman is not None
        # recompute_counts devrait avoir mis image_count à 1 et article_count à 1
        assert altman.image_count == 1
        assert altman.article_count == 1

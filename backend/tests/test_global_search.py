"""Tests pour `GET /search` — recherche full-text globale (FTS5).

Couvre :
- FTS5 entités élargie (v018) : occupations, employer, wiki_summary
- FTS5 articles (v019) : titre + source_domain
- FTS5 images (v020) : caption + alt_text + copyright_text
- Snippets HTML (`<mark>`)
- Filtrage par scope
- Insensibilité aux accents (tokenizer unicode61 remove_diacritics 2)
- Triggers : INSERT/UPDATE/DELETE maintiennent l'index en sync
"""
from datetime import date


def _seed(db):
    """Mini-corpus pour tester les 3 FTS sans dépendre de la prod."""
    from database import Article, ArticleEntity, Entity, Image

    e1 = Entity(
        name="Bengio, Yoshua",
        slug="yoshua-bengio",
        occupations="informaticien|chercheur",
        employer="Université de Montréal",
        nationalities="canadien|français",
        wiki_summary=(
            "Yoshua Bengio est un chercheur en intelligence artificielle, "
            "pionnier de l'apprentissage profond. Lauréat du prix Turing en 2018."
        ),
    )
    e2 = Entity(
        name="Altman, Sam",
        slug="sam-altman",
        occupations="entrepreneur|investisseur",
        employer="OpenAI",
        wiki_summary="Sam Altman, PDG d'OpenAI, ancien président de Y Combinator.",
    )
    db.add_all([e1, e2])
    db.flush()

    a1 = Article(
        url="https://ex.com/1",
        title="OpenAI annonce une levée record",
        published_at=date(2024, 6, 1),
        source_domain="lemonde.fr",
    )
    a2 = Article(
        url="https://ex.com/2",
        title="Le golf de Mar-a-Lago accueille Trump",
        published_at=date(2024, 7, 1),
        source_domain="blick.ch",
    )
    db.add_all([a1, a2])
    db.flush()
    db.add_all(
        [
            ArticleEntity(article_id=a1.id, entity_id=e2.id),
            ArticleEntity(article_id=a2.id, entity_id=e1.id),
        ]
    )

    db.add_all(
        [
            Image(
                entity_id=e2.id,
                article_id=a1.id,
                source_url="https://ex.com/img1",
                aligned_path="/tmp/aligned/1.jpg",
                caption="Sam Altman au sommet AI de Davos",
                alt_text="portrait costume cravate",
                copyright_text="AP Photo / John Doe",
            ),
            Image(
                entity_id=e1.id,
                article_id=a2.id,
                source_url="https://ex.com/img2",
                aligned_path="/tmp/aligned/2.jpg",
                caption="Yoshua Bengio à Montréal",
                alt_text="",
                copyright_text="Reuters",
            ),
        ]
    )
    db.commit()
    return e1, e2, a1, a2


class TestEntitySearchExtended:
    """Recherche par bio (occupations, employer, summary) — v018."""

    def test_by_occupation(self, client, db):
        _seed(db)
        r = client.get("/search?q=chercheur&scope=entities").json()
        slugs = [e["slug"] for e in r["entities"]]
        assert "yoshua-bengio" in slugs

    def test_by_employer(self, client, db):
        _seed(db)
        r = client.get("/search?q=openai&scope=entities").json()
        slugs = [e["slug"] for e in r["entities"]]
        assert "sam-altman" in slugs

    def test_by_summary_full_text(self, client, db):
        _seed(db)
        # 'turing' n'apparaît ni dans le nom ni les occupations — uniquement
        # dans le résumé Wikipedia.
        r = client.get("/search?q=turing&scope=entities").json()
        slugs = [e["slug"] for e in r["entities"]]
        assert "yoshua-bengio" in slugs

    def test_snippet_marks_match(self, client, db):
        _seed(db)
        r = client.get("/search?q=openai&scope=entities").json()
        hits = [h for h in r["entities"] if h["slug"] == "sam-altman"]
        assert hits
        assert "<mark>" in hits[0]["snippet"]
        assert "OpenAI" in hits[0]["snippet"] or "openai" in hits[0]["snippet"].lower()


class TestArticleSearch:
    """Recherche dans les titres et sources d'articles — v019."""

    def test_by_title(self, client, db):
        """Note tokenizer : `_build_fts_query` retire les non-alphanum, et
        FTS5 unicode61 découpe sur tirets/ponctuation. Un terme composé
        avec tirets ne match donc pas en tant qu'expression. Pour tester
        un titre, on cherche un token unique présent dans le titre."""
        _seed(db)
        r = client.get("/search?q=Lago&scope=articles").json()
        titles = [a["title"] for a in r["articles"]]
        assert any("Mar-a-Lago" in (t or "") for t in titles)

    def test_by_source_domain(self, client, db):
        _seed(db)
        r = client.get("/search?q=lemonde&scope=articles").json()
        titles = [a["title"] for a in r["articles"]]
        assert "OpenAI annonce une levée record" in titles

    def test_article_carries_entity_link(self, client, db):
        """Chaque hit article doit pointer sur une entité associée."""
        _seed(db)
        r = client.get("/search?q=openai&scope=articles").json()
        for a in r["articles"]:
            if a["title"] == "OpenAI annonce une levée record":
                assert a["entity_slug"] == "sam-altman"
                assert a["entity_name"] == "Altman, Sam"
                break
        else:
            raise AssertionError("article OpenAI absent des résultats")


class TestImageSearch:
    """Recherche dans les captions et alt_text — v020."""

    def test_by_caption(self, client, db):
        _seed(db)
        r = client.get("/search?q=davos&scope=images").json()
        captions = [i["caption"] for i in r["images"]]
        assert any("Davos" in (c or "") for c in captions)

    def test_by_alt_text(self, client, db):
        _seed(db)
        r = client.get("/search?q=cravate&scope=images").json()
        captions = [i["caption"] for i in r["images"]]
        assert "Sam Altman au sommet AI de Davos" in captions

    def test_by_copyright(self, client, db):
        _seed(db)
        r = client.get("/search?q=reuters&scope=images").json()
        captions = [i["caption"] for i in r["images"]]
        assert any("Bengio" in (c or "") for c in captions)

    def test_image_carries_entity_link_and_aligned_url(self, client, db):
        _seed(db)
        r = client.get("/search?q=montreal&scope=images").json()
        hit = next((i for i in r["images"] if "Bengio" in (i["caption"] or "")), None)
        assert hit is not None
        assert hit["entity_slug"] == "yoshua-bengio"
        assert hit["aligned_url"] == f"/static/aligned/{hit['image_id']}.jpg"


class TestScopeFiltering:
    def test_scope_all_returns_three_lists(self, client, db):
        _seed(db)
        r = client.get("/search?q=openai&scope=all").json()
        assert "entities" in r and "articles" in r and "images" in r
        # OpenAI dans entities (Altman) + articles (titre) + images (alt? non, mais caption AI)
        assert len(r["entities"]) >= 1
        assert len(r["articles"]) >= 1

    def test_scope_entities_only(self, client, db):
        _seed(db)
        r = client.get("/search?q=openai&scope=entities").json()
        assert len(r["entities"]) >= 1
        assert r["articles"] == []
        assert r["images"] == []

    def test_invalid_scope_rejected(self, client):
        r = client.get("/search?q=x&scope=invalid")
        assert r.status_code == 422  # FastAPI validation pattern

    def test_totals_returned(self, client, db):
        _seed(db)
        r = client.get("/search?q=openai&scope=all").json()
        assert "totals" in r
        assert r["totals"]["entities"] >= 1


class TestDiacriticsInsensitive:
    """Le tokenizer unicode61 remove_diacritics 2 normalise les accents."""

    def test_match_without_accents(self, client, db):
        _seed(db)
        # 'Montreal' sans accent doit matcher 'Montréal' dans le seed
        r = client.get("/search?q=montreal&scope=entities").json()
        slugs = [e["slug"] for e in r["entities"]]
        assert "yoshua-bengio" in slugs

    def test_match_with_accents(self, client, db):
        _seed(db)
        r = client.get("/search?q=Montréal&scope=entities").json()
        slugs = [e["slug"] for e in r["entities"]]
        assert "yoshua-bengio" in slugs


class TestPrefixCompletion:
    def test_short_prefix_completes(self, client, db):
        _seed(db)
        # 'cherch' → 'chercheur'
        r = client.get("/search?q=cherch&scope=entities").json()
        slugs = [e["slug"] for e in r["entities"]]
        assert "yoshua-bengio" in slugs


class TestTriggerMaintenance:
    """Les triggers maintiennent l'index FTS5 en sync."""

    def test_update_summary_reflects_in_search(self, client, db):
        from database import Entity

        _seed(db)
        # Ajouter une bio à une entité qui n'avait pas le mot 'physicien'
        e = db.scalar(
            db.query(Entity).filter_by(slug="sam-altman").statement
        )
        e.wiki_summary = "Sam Altman, ex-élève en physique à Stanford."
        db.commit()

        r = client.get("/search?q=physique&scope=entities").json()
        slugs = [e["slug"] for e in r["entities"]]
        assert "sam-altman" in slugs

    def test_alias_move_updates_both_fts_rows(self, client, db):
        """Régression du bug observé pendant la restauration de l'incident
        2026-05-11 : déplacer un alias via `UPDATE entity_aliases SET
        entity_id = …` laissait la colonne FTS aliases stale des deux
        côtés (trigger v018 ne se déclenchait que sur UPDATE OF alias).
        Le trigger `entity_aliases_fts_au_eid` (v022) couvre maintenant ce cas.
        """
        from database import Entity, EntityAlias

        e1 = Entity(name="Source, X", slug="source-x")
        e2 = Entity(name="Target, Y", slug="target-y")
        db.add_all([e1, e2])
        db.flush()
        a = EntityAlias(entity_id=e1.id, alias="Marqueur123", source="test")
        db.add(a)
        db.commit()

        # Au départ, recherche `Marqueur123` matche source-x
        r = client.get("/search?q=Marqueur123&scope=entities").json()
        assert any(e["slug"] == "source-x" for e in r["entities"])
        assert not any(e["slug"] == "target-y" for e in r["entities"])

        # Déplacer l'alias vers target-y via UPDATE entity_id (le pattern
        # qu'on avait utilisé dans le script de démerge unmerge_incident_…)
        a.entity_id = e2.id
        db.commit()

        # Maintenant Marqueur123 doit matcher target-y et plus source-x
        r = client.get("/search?q=Marqueur123&scope=entities").json()
        slugs = [e["slug"] for e in r["entities"]]
        assert "target-y" in slugs
        assert "source-x" not in slugs

    def test_delete_entity_removes_from_index(self, client, db):
        """Le trigger `entities_fts_ad` retire la row FTS5 quand on
        supprime l'entité. On utilise l'endpoint REST qui fait le cascade
        manuel des ArticleEntity (cf. CLAUDE.md : ondelete CASCADE n'est
        pas activé côté SQLite, il faut le faire dans le code Python)."""
        _seed(db)
        # Sanity : Altman matche 'openai'
        r = client.get("/search?q=openai&scope=entities").json()
        assert any(e["slug"] == "sam-altman" for e in r["entities"])

        del_resp = client.delete("/entities/sam-altman")
        assert del_resp.status_code == 200

        r = client.get("/search?q=openai&scope=entities").json()
        assert not any(e["slug"] == "sam-altman" for e in r["entities"])

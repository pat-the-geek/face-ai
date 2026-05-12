"""Tests pour le périmètre PERSON exclusif (spec §1.5, CLAUDE.md).

Couvre :
- `wikidata.enrich_entity` détecte P31 ≠ Q5 et retourne 'not_person'
- `entity_cleanup.purge_non_person` supprime cascade tout en gardant tombstone
- `scraper.get_or_create_entity` refuse les tombstones (retourne None)
- API filtre les not_person sur tous les endpoints utilisateur
- MCP idem
"""
from datetime import date, datetime
from unittest.mock import patch


def _make_entity(db, **kw):
    """Helper : crée une entité avec valeurs par défaut sensées pour les tests."""
    from database import Entity

    defaults = {
        "name": "Test, Sujet",
        "slug": "test-sujet",
        "first_seen": datetime(2024, 1, 1),
    }
    defaults.update(kw)
    e = Entity(**defaults)
    db.add(e)
    db.flush()
    db.commit()
    return e


def _make_tombstone(db, slug="dead-entity"):
    """Crée une entité avec le tombstone `not_person`."""
    from database import Entity

    e = Entity(
        name="Park, Apple",
        slug=slug,
        wikidata_qid="Q1232101",  # QID fictif pour "Apple Park"
        wikidata_status="not_person",
        first_seen=datetime(2024, 1, 1),
    )
    db.add(e)
    db.commit()
    return e


class TestWikidataP31Check:
    """`wikidata.enrich_entity` doit détecter les non-humains via P31."""

    def test_q5_human_passes_check(self, db):
        """Une entité dont P31=[Q5] est qualifiée 'done', pas 'not_person'."""
        from wikidata import enrich_entity

        e = _make_entity(db, name="Bengio, Yoshua", slug="bengio-test")

        # Stub Wikidata : wbsearchentities renvoie un QID,
        # rest v1 statements renvoie P31=[Q5]
        with patch("wikidata._search_qid") as mock_search, patch(
            "wikidata._get_statements"
        ) as mock_stmts, patch("wikidata._get_wiki_summary", return_value=None), patch(
            "wikidata._resolve_labels", return_value={}
        ):
            mock_search.return_value = ("Q92614", "Yoshua Bengio", 1.0)
            mock_stmts.return_value = {
                "P31": [{"value": {"content": "Q5"}}],
                "P569": [],
                "P106": [],
            }
            status = enrich_entity(e.id)

        assert status == "done"

    def test_non_human_returns_not_person(self, db):
        """Une entité dont P31 ne contient pas Q5 → 'not_person'."""
        from database import Entity
        from wikidata import enrich_entity

        e = _make_entity(db, name="Park, Apple", slug="apple-park-test")

        with patch("wikidata._search_qid") as mock_search, patch(
            "wikidata._get_statements"
        ) as mock_stmts:
            mock_search.return_value = ("Q1232101", "Apple Park", 1.0)
            # P31=[Q486972] = "human settlement", PAS Q5
            mock_stmts.return_value = {
                "P31": [{"value": {"content": "Q486972"}}]
            }
            status = enrich_entity(e.id)

        assert status == "not_person"
        db.refresh(e)
        assert e.wikidata_status == "not_person"

    def test_mixed_p31_with_q5_passes(self, db):
        """Si P31 contient Q5 ET d'autres types, on accepte (cas réel
        Wikidata qualifie souvent en {Q5, individu historique})."""
        from wikidata import enrich_entity

        e = _make_entity(db, name="Test, Mixed", slug="mixed-test")

        with patch("wikidata._search_qid") as mock_search, patch(
            "wikidata._get_statements"
        ) as mock_stmts, patch("wikidata._get_wiki_summary", return_value=None), patch(
            "wikidata._resolve_labels", return_value={}
        ):
            mock_search.return_value = ("Q999", "Test", 1.0)
            mock_stmts.return_value = {
                "P31": [
                    {"value": {"content": "Q5"}},
                    {"value": {"content": "Q215627"}},  # individu historique
                ],
            }
            status = enrich_entity(e.id)

        assert status == "done"

    def test_no_p31_does_not_purge(self, db):
        """Si P31 est absent (entités Wikidata mal qualifiées), on ne
        purge pas — on continue l'enrichissement normal (statut 'done').
        Le risque inverse (faux négatif) est préférable à un faux purge."""
        from wikidata import enrich_entity

        e = _make_entity(db, name="Test, NoP31", slug="nop31-test")

        with patch("wikidata._search_qid") as mock_search, patch(
            "wikidata._get_statements"
        ) as mock_stmts, patch("wikidata._get_wiki_summary", return_value=None), patch(
            "wikidata._resolve_labels", return_value={}
        ):
            mock_search.return_value = ("Q999", "Test", 1.0)
            mock_stmts.return_value = {"P569": []}  # pas de P31 du tout
            status = enrich_entity(e.id)

        assert status == "done"


class TestEntityCleanupPurge:
    """`purge_non_person` supprime cascade et laisse tombstone."""

    def test_purge_removes_images_and_links(self, db, static_dir):
        from database import Article, ArticleEntity, Entity, Image
        from entity_cleanup import purge_non_person

        e = _make_entity(db, name="X, Y", slug="x-y", wikidata_qid="Q999")
        article = Article(
            url="https://ex.com/1", title="t", published_at=date(2024, 6, 1)
        )
        db.add(article)
        db.flush()
        db.add(ArticleEntity(article_id=article.id, entity_id=e.id))
        # Fichier image réel pour vérifier la suppression disque
        local = static_dir / "originals" / f"{e.id}.jpg"
        local.write_bytes(b"fake")
        aligned = static_dir / "aligned" / f"{e.id}.jpg"
        aligned.write_bytes(b"fake")
        db.add(
            Image(
                entity_id=e.id,
                article_id=article.id,
                source_url="https://ex.com/img",
                local_path=str(local),
                aligned_path=str(aligned),
            )
        )
        db.commit()

        r = purge_non_person(e.id)
        assert r["status"] == "purged"
        assert r["images_removed"] == 1
        assert r["files_removed"] == 2

        # Plus aucune image, plus aucun lien
        assert db.query(Image).filter_by(entity_id=e.id).count() == 0
        assert db.query(ArticleEntity).filter_by(entity_id=e.id).count() == 0
        # Fichiers disque effacés
        assert not local.exists()
        assert not aligned.exists()

    def test_purge_leaves_tombstone(self, db):
        """Le row Entity survit avec wikidata_status='not_person' — bloque
        la recréation au prochain pull WUDD."""
        from database import Entity
        from entity_cleanup import purge_non_person

        e = _make_entity(
            db, name="Z, Z", slug="z-z", wikidata_qid="Q999", is_favorite=True
        )
        e.wiki_summary = "résumé qui devra disparaître"
        e.occupations = "actor|director"
        db.commit()

        purge_non_person(e.id)
        db.refresh(e)
        assert e.wikidata_status == "not_person"
        assert e.image_count == 0
        assert e.is_favorite is False
        # Bio vidée pour ne pas polluer FTS5 (v018 indexe summary/occupations)
        assert e.wiki_summary is None
        assert e.occupations is None

    def test_purge_idempotent(self, db):
        """Re-purger un tombstone existant ne plante pas."""
        from entity_cleanup import purge_non_person

        e = _make_tombstone(db)
        r = purge_non_person(e.id)
        assert r["status"] == "purged"


class TestScraperRefusesNotPerson:
    """`scraper.get_or_create_entity` retourne None si tombstone existe."""

    def test_returns_none_for_tombstone(self, db):
        from scraper import get_or_create_entity

        _make_tombstone(db, slug="park-apple")

        # Même slug → doit retourner None
        result = get_or_create_entity(db, "Park, Apple", source_domain="x.com")
        assert result is None

    def test_creates_normal_entity(self, db):
        """Régression : pour un nom non-tombstone, on crée normalement."""
        from scraper import get_or_create_entity

        e = get_or_create_entity(db, "Smith, John", source_domain="x.com")
        assert e is not None
        # `canonicalize_name("Smith, John")` → ("Smith, John", "smith-john")
        assert e.slug == "smith-john"


class TestAPIFiltersNotPerson:
    """L'API doit filtrer les tombstones de toutes les vues utilisateur."""

    def test_entity_list_excludes_tombstone(self, client, db):
        _make_entity(db, name="Valid, Person", slug="valid-person")
        _make_tombstone(db, slug="ghost-1")

        body = client.get("/entities").json()
        slugs = [e["slug"] for e in body["entities"]]
        assert "valid-person" in slugs
        assert "ghost-1" not in slugs
        # Total exclut aussi les tombstones
        assert body["total"] == 1

    def test_entity_detail_returns_404_for_tombstone(self, client, db):
        _make_tombstone(db, slug="ghost-2")
        r = client.get("/entities/ghost-2")
        assert r.status_code == 404

    def test_entity_images_returns_404_for_tombstone(self, client, db):
        _make_tombstone(db, slug="ghost-3")
        r = client.get("/entities/ghost-3/images")
        assert r.status_code == 404

    def test_search_excludes_tombstone(self, client, db):
        """FTS5 doit aussi filtrer — sinon le tombstone reste découvrable
        par /entities/search ou /search global."""
        _make_tombstone(db, slug="ghost-park")  # name="Park, Apple"
        r = client.get("/entities/search?q=park").json()
        slugs = [e["slug"] for e in r["results"]]
        assert "ghost-park" not in slugs

    def test_global_search_excludes_tombstone(self, client, db):
        _make_tombstone(db, slug="ghost-park-2")
        r = client.get("/search?q=park&scope=entities").json()
        slugs = [e["slug"] for e in r["entities"]]
        assert "ghost-park-2" not in slugs

    def test_favorite_refused_for_tombstone(self, client, db):
        _make_tombstone(db, slug="ghost-fav")
        r = client.put("/entities/ghost-fav/favorite")
        assert r.status_code == 404

    def test_merge_refused_with_tombstone(self, client, db):
        """On ne peut pas merger une entité valide dans un tombstone ni
        l'inverse — le tombstone est invisible côté API."""
        _make_entity(db, name="Valid, X", slug="valid-x")
        _make_tombstone(db, slug="ghost-merge")
        r = client.post("/entities/valid-x/merge?source=ghost-merge")
        assert r.status_code == 404


class TestDuplicateFinderSkipsNotPerson:
    """`find_candidates` ne propose pas de fusion sur des tombstones."""

    def test_same_qid_excludes_tombstones(self, db):
        """Deux entités au même QID dont l'une est tombstone → 0 groupe
        (rien à fusionner, le tombstone reste fantôme)."""
        from duplicate_finder import find_candidates

        _make_entity(db, name="Valid, A", slug="valid-a", wikidata_qid="Q42")
        _make_tombstone(db, slug="ghost-q42")
        # ghost-q42 a aussi Q1232101, mais imposons Q42 pour reproduire
        from database import Entity

        ghost = db.scalar(__import__("sqlalchemy").select(Entity).where(Entity.slug == "ghost-q42"))
        ghost.wikidata_qid = "Q42"
        db.commit()

        r = find_candidates()
        # Pas de groupe same_qid puisque le tombstone est exclu
        same_qid_q42 = [g for g in r["same_qid"] if g["qid"] == "Q42"]
        assert len(same_qid_q42) == 0

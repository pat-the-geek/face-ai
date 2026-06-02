"""Tests entity_cleanup.py — fonctions non couvertes par test_not_person.

`test_not_person` couvre déjà le chemin `purge_non_person` via le workflow
enrich → not_person. Ici on cible les helpers de re-check rétro-actif
(`find_done_entities_to_recheck`, `purge_all_non_persons`,
`find_orphan_articles`) qui sont utilisés par l'endpoint admin et le CLI.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta


def _seed_entity(db, slug, name, status="done", qid="Q42", **kw):
    from database import Entity

    e = Entity(
        name=name, slug=slug, wikidata_status=status, wikidata_qid=qid, **kw,
    )
    db.add(e)
    db.flush()
    return e


def _add_image(db, entity, article_url="https://ex.com/img-art"):
    from database import Article, ArticleEntity, Image

    art = db.scalar(
        __import__("sqlalchemy").select(Article).where(Article.url == article_url)
    )
    if art is None:
        art = Article(url=article_url, title="art", published_at=date(2024, 1, 1))
        db.add(art)
        db.flush()
    db.add(ArticleEntity(article_id=art.id, entity_id=entity.id))
    img = Image(
        article_id=art.id,
        entity_id=entity.id,
        source_url="https://ex.com/p.jpg",
        scrape_status="downloaded",
        analysis_status="done",
    )
    db.add(img)
    db.flush()
    return img


class TestFindDoneEntitiesToRecheck:
    def test_returns_only_done_with_qid(self, db):
        from entity_cleanup import find_done_entities_to_recheck

        e_done_qid = _seed_entity(db, "x-y", "X, Y", status="done", qid="Q1")
        _seed_entity(db, "no-qid", "No, Qid", status="done", qid=None)
        _seed_entity(db, "pending", "P, Ending", status="pending", qid="Q2")
        _seed_entity(db, "not-found", "Not, Found", status="not_found", qid="Q3")
        _seed_entity(db, "not-person", "Not, Person", status="not_person", qid="Q4")
        db.commit()

        ids = find_done_entities_to_recheck()
        assert ids == [e_done_qid.id]

    def test_empty_when_no_match(self, db):
        from entity_cleanup import find_done_entities_to_recheck

        _seed_entity(db, "pending", "Pending, X", status="pending")
        db.commit()
        assert find_done_entities_to_recheck() == []


class TestPurgeAllNonPersons:
    def test_calls_enrich_and_purges_not_person(self, db, monkeypatch):
        """Un seul cycle : enrich renvoie not_person → on purge."""
        from entity_cleanup import purge_all_non_persons

        e = _seed_entity(db, "chatgpt", "ChatGPT", status="done", qid="Q115564437")
        db.commit()
        eid = e.id

        def fake_enrich(entity_id):
            # Simule la bascule en not_person côté DB (le vrai code le fait)
            from database import Entity, SessionLocal
            s = SessionLocal()
            try:
                ent = s.get(Entity, entity_id)
                ent.wikidata_status = "not_person"
                s.commit()
            finally:
                s.close()
            return "not_person"

        monkeypatch.setattr("wikidata.enrich_entity", fake_enrich)
        # Bypass le sleep 1s pour le test
        monkeypatch.setattr("time.sleep", lambda *_: None)

        summary = purge_all_non_persons()
        assert summary["checked"] == 1
        assert summary["purged"] == 1
        assert summary["still_person"] == 0
        assert summary["errors"] == 0
        assert len(summary["details"]) == 1

        # L'entité est maintenant en not_person (tombstone)
        from database import Entity
        db.expire_all()
        refreshed = db.get(Entity, eid)
        assert refreshed.wikidata_status == "not_person"

    def test_still_person_when_p31_passes(self, db, monkeypatch):
        """Si enrich renvoie 'done', l'entité reste — on incrémente still_person."""
        from entity_cleanup import purge_all_non_persons

        e = _seed_entity(db, "real-person", "Person, Real", status="done", qid="Q42")
        db.commit()
        eid = e.id

        monkeypatch.setattr("wikidata.enrich_entity", lambda eid: "done")
        monkeypatch.setattr("time.sleep", lambda *_: None)

        summary = purge_all_non_persons()
        assert summary["checked"] == 1
        assert summary["purged"] == 0
        assert summary["still_person"] == 1

        from database import Entity
        db.expire_all()
        assert db.get(Entity, eid).wikidata_status == "done"

    def test_limit_caps_processing(self, db, monkeypatch):
        from entity_cleanup import purge_all_non_persons

        for i in range(5):
            _seed_entity(db, f"e{i}", f"E, {i}", status="done", qid=f"Q{i}")
        db.commit()

        call_count = [0]

        def counting_enrich(eid):
            call_count[0] += 1
            return "done"

        monkeypatch.setattr("wikidata.enrich_entity", counting_enrich)
        monkeypatch.setattr("time.sleep", lambda *_: None)

        summary = purge_all_non_persons(limit=2)
        assert summary["checked"] == 2
        assert call_count[0] == 2

    def test_handles_enrich_exception(self, db, monkeypatch):
        """Si enrich lève, on compte une erreur mais on continue le batch."""
        from entity_cleanup import purge_all_non_persons

        _seed_entity(db, "e1", "E, 1", qid="Q1")
        _seed_entity(db, "e2", "E, 2", qid="Q2")
        db.commit()

        calls = [0]

        def flaky_enrich(eid):
            calls[0] += 1
            if calls[0] == 1:
                raise RuntimeError("Wikidata timeout simulé")
            return "done"

        monkeypatch.setattr("wikidata.enrich_entity", flaky_enrich)
        monkeypatch.setattr("time.sleep", lambda *_: None)

        summary = purge_all_non_persons()
        assert summary["errors"] == 1
        # Le second a quand même été traité
        assert summary["checked"] == 1
        assert summary["still_person"] == 1


class TestCleanupOrphanEntities:
    def _old(self):
        return datetime.utcnow() - timedelta(days=60)

    def test_finds_not_found_without_images_old(self, db):
        from entity_cleanup import find_orphan_entities

        _seed_entity(
            db, "orphan", "Orphan, X", status="not_found", qid=None,
            wikidata_synced_at=self._old(),
        )
        db.commit()
        orphans = find_orphan_entities(days=30)
        assert [o.slug for o in orphans] == ["orphan"]

    def test_excludes_entity_with_images(self, db):
        from entity_cleanup import find_orphan_entities

        e = _seed_entity(
            db, "has-photo", "Photo, Has", status="not_found", qid=None,
            wikidata_synced_at=self._old(),
        )
        _add_image(db, e)
        db.commit()
        # not_found + portrait = vraie personne absente de Wikidata → on garde
        assert find_orphan_entities(days=30) == []

    def test_null_entity_id_image_does_not_hide_orphans(self, db):
        """Régression : une image à entity_id NULL ne doit pas masquer les
        orphelins (piège SQL `NOT IN (…, NULL)`). Bug attrapé en live 2026-06-02."""
        from database import Article, Image
        from entity_cleanup import find_orphan_entities

        _seed_entity(
            db, "orphan", "Orphan, X", status="not_found", qid=None,
            wikidata_synced_at=self._old(),
        )
        # Image orpheline non associée (entity_id NULL) — cas réel (ingestion
        # en attente d'association).
        art = Article(url="https://ex.com/n", title="n", published_at=date(2024, 1, 1))
        db.add(art)
        db.flush()
        db.add(Image(article_id=art.id, entity_id=None, source_url="https://x/p.jpg",
                     scrape_status="downloaded", analysis_status="pending"))
        db.commit()
        assert [o.slug for o in find_orphan_entities(days=30)] == ["orphan"]

    def test_excludes_recent_not_found(self, db):
        from entity_cleanup import find_orphan_entities

        _seed_entity(
            db, "recent", "Recent, X", status="not_found", qid=None,
            wikidata_synced_at=datetime.utcnow() - timedelta(days=2),
        )
        db.commit()
        assert find_orphan_entities(days=30) == []

    def test_excludes_done_and_pending(self, db):
        from entity_cleanup import find_orphan_entities

        _seed_entity(db, "done", "Done, X", status="done", wikidata_synced_at=self._old())
        _seed_entity(db, "pending", "Pending, X", status="pending", qid=None)
        db.commit()
        assert find_orphan_entities(days=30) == []

    def test_null_synced_at_treated_as_old(self, db):
        from entity_cleanup import find_orphan_entities

        _seed_entity(
            db, "legacy", "Legacy, X", status="not_found", qid=None,
            wikidata_synced_at=None,
        )
        db.commit()
        assert [o.slug for o in find_orphan_entities(days=30)] == ["legacy"]

    def test_dry_run_lists_without_deleting(self, db):
        from database import Entity
        from entity_cleanup import cleanup_orphan_entities

        _seed_entity(
            db, "orphan", "Orphan, X", status="not_found", qid=None,
            wikidata_synced_at=self._old(),
        )
        db.commit()
        res = cleanup_orphan_entities(days=30, dry_run=True)
        assert res["dry_run"] is True
        assert res["count"] == 1
        assert res["entities"][0]["slug"] == "orphan"
        db.expire_all()
        assert db.scalar(__import__("sqlalchemy").select(Entity).where(Entity.slug == "orphan")) is not None

    def test_cleanup_deletes_row_and_links(self, db):
        from database import ArticleEntity, Entity, EntityAlias
        from entity_cleanup import cleanup_orphan_entities

        e = _seed_entity(
            db, "orphan", "Orphan, X", status="not_found", qid=None,
            wikidata_synced_at=self._old(),
        )
        db.add(EntityAlias(entity_id=e.id, alias="Orphan"))
        # Lien article SANS image (donc reste orphelin) — doit être supprimé
        from database import Article
        art = Article(url="https://ex.com/o", title="o", published_at=date(2024, 1, 1))
        db.add(art)
        db.flush()
        db.add(ArticleEntity(article_id=art.id, entity_id=e.id))
        db.commit()
        eid = e.id

        res = cleanup_orphan_entities(days=30, dry_run=False)
        assert res["count"] == 1
        db.expire_all()
        assert db.get(Entity, eid) is None
        from sqlalchemy import select
        assert db.scalar(select(ArticleEntity).where(ArticleEntity.entity_id == eid)) is None
        assert db.scalar(select(EntityAlias).where(EntityAlias.entity_id == eid)) is None


class TestFindOrphanArticles:
    def test_counts_articles_without_entity_link(self, db):
        from database import Article, ArticleEntity
        from entity_cleanup import find_orphan_articles

        e = _seed_entity(db, "x-y", "X, Y")
        linked = Article(
            url="https://ex.com/a", title="linked",
            published_at=date(2024, 6, 1),
        )
        orphan_1 = Article(
            url="https://ex.com/orphan1", title="orphan 1",
            published_at=date(2024, 6, 1),
        )
        orphan_2 = Article(
            url="https://ex.com/orphan2", title="orphan 2",
            published_at=date(2024, 6, 1),
        )
        db.add_all([linked, orphan_1, orphan_2])
        db.flush()
        db.add(ArticleEntity(article_id=linked.id, entity_id=e.id))
        db.commit()

        assert find_orphan_articles() == 2

    def test_zero_when_all_linked(self, db):
        from database import Article, ArticleEntity
        from entity_cleanup import find_orphan_articles

        e = _seed_entity(db, "x-y", "X, Y")
        a = Article(
            url="https://ex.com/a", title="linked",
            published_at=date(2024, 6, 1),
        )
        db.add(a)
        db.flush()
        db.add(ArticleEntity(article_id=a.id, entity_id=e.id))
        db.commit()

        assert find_orphan_articles() == 0

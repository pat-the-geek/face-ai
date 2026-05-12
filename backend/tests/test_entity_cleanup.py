"""Tests entity_cleanup.py — fonctions non couvertes par test_not_person.

`test_not_person` couvre déjà le chemin `purge_non_person` via le workflow
enrich → not_person. Ici on cible les helpers de re-check rétro-actif
(`find_done_entities_to_recheck`, `purge_all_non_persons`,
`find_orphan_articles`) qui sont utilisés par l'endpoint admin et le CLI.
"""
from __future__ import annotations

from datetime import date, datetime


def _seed_entity(db, slug, name, status="done", qid="Q42", **kw):
    from database import Entity

    e = Entity(
        name=name, slug=slug, wikidata_status=status, wikidata_qid=qid, **kw,
    )
    db.add(e)
    db.flush()
    return e


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

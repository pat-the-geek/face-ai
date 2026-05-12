"""Tests des cycles worker (helpers `_run_*_cycle`).

Les `*_loop()` eux-mêmes ne sont pas testés (boucles infinies, juste un
boilerplate `while True: cycle(); sleep()`). Tout l'intérêt est dans
les helpers unitaires qu'on mocke ici.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_metrics():
    from worker_metrics import reset_for_tests
    reset_for_tests()
    yield
    reset_for_tests()


# ── analyze ─────────────────────────────────────────────────────────


class TestAnalyzeCycle:
    def test_runs_and_records_success(self, monkeypatch):
        from worker import _run_analyze_cycle
        from worker_metrics import get_status

        monkeypatch.setattr(
            "worker.process_pending",
            lambda limit=20: {"done": 3, "purged": 1, "failed": 0},
        )
        result = _run_analyze_cycle()
        assert result == {"done": 3, "purged": 1, "failed": 0}

        s = get_status()
        assert s["loops"]["analyze"]["successes_24h"] == 1
        assert s["loops"]["analyze"]["errors_24h"] == 0

    def test_records_error_on_exception(self, monkeypatch):
        from worker import _run_analyze_cycle
        from worker_metrics import get_status

        def boom(limit=20):
            raise RuntimeError("processeur planté")

        monkeypatch.setattr("worker.process_pending", boom)
        result = _run_analyze_cycle()
        assert result == {}

        s = get_status()
        assert s["loops"]["analyze"]["errors_24h"] == 1


# ── enrich ──────────────────────────────────────────────────────────


class TestEnrichCycle:
    def test_processes_pending_entities(self, db, monkeypatch):
        from datetime import datetime
        from database import Entity
        from worker import _run_enrich_cycle

        for i in range(3):
            db.add(Entity(
                name=f"E, {i}", slug=f"e-{i}",
                wikidata_status="pending",
                first_seen=datetime(2024, 1, 1),
            ))
        db.commit()

        monkeypatch.setattr("worker.enrich_entity", lambda eid: "done")
        # bypass le sleep inter-requête (1s)
        monkeypatch.setattr("time.sleep", lambda *_: None)

        result = _run_enrich_cycle()
        assert result["processed"] == 3
        assert result["not_person"] == 0

    def test_purges_not_person_results(self, db, monkeypatch):
        """Si enrich_entity renvoie 'not_person', on purge + record event."""
        from datetime import datetime
        from database import Entity
        from worker import _run_enrich_cycle
        from worker_metrics import get_status

        db.add(Entity(
            name="Fake, Person", slug="fake-person",
            wikidata_status="pending",
            first_seen=datetime(2024, 1, 1),
        ))
        db.commit()

        purge_calls = []

        def fake_purge(eid):
            purge_calls.append(eid)
            return {"status": "purged", "name": "Fake", "qid": "Q1",
                    "images_removed": 0}

        monkeypatch.setattr("worker.enrich_entity", lambda eid: "not_person")
        monkeypatch.setattr("entity_cleanup.purge_non_person", fake_purge)
        monkeypatch.setattr("time.sleep", lambda *_: None)

        result = _run_enrich_cycle()
        assert result["not_person"] == 1
        assert len(purge_calls) == 1

        s = get_status()
        assert s["events_24h"]["not_person_purged"] == 1

    def test_records_error_on_exception(self, monkeypatch):
        from worker import _run_enrich_cycle
        from worker_metrics import get_status

        # Casse au niveau du SessionLocal SELECT pending
        def broken_execute(*args, **kwargs):
            raise RuntimeError("DB plantée")

        from database import SessionLocal
        real_session = SessionLocal

        class BrokenSession:
            def __init__(self):
                self._real = real_session()

            def execute(self, *a, **kw):
                raise RuntimeError("DB plantée")

            def close(self):
                self._real.close()

        monkeypatch.setattr("worker.SessionLocal", BrokenSession)

        result = _run_enrich_cycle()
        assert result["processed"] == 0
        s = get_status()
        assert s["loops"]["enrich"]["errors_24h"] == 1


# ── dedup ───────────────────────────────────────────────────────────


class TestDedupCycle:
    def test_runs_dedup_when_new_embeddings(self, monkeypatch):
        from worker import _run_dedup_cycle

        monkeypatch.setattr("worker.compute_missing_embeddings", lambda limit=20: 3)
        monkeypatch.setattr(
            "worker.dedup_all_entities",
            lambda: {"entities": 5, "marked_total": 1},
        )
        result = _run_dedup_cycle()
        assert result["embeddings"] == 3
        assert result["marked_total"] == 1

    def test_skips_dedup_when_no_new_embeddings(self, monkeypatch):
        """Si aucun embedding nouveau, on ne re-dedup pas."""
        from worker import _run_dedup_cycle

        called = [0]

        def counting_dedup():
            called[0] += 1
            return {"entities": 0, "marked_total": 0}

        monkeypatch.setattr("worker.compute_missing_embeddings", lambda limit=20: 0)
        monkeypatch.setattr("worker.dedup_all_entities", counting_dedup)

        _run_dedup_cycle()
        assert called[0] == 0  # pas appelé


# ── identity ────────────────────────────────────────────────────────


class TestIdentityCycle:
    def test_audits_only_if_state_changed(self, monkeypatch):
        from worker import _run_identity_cycle

        audit_calls = [0]

        def counting_audit():
            audit_calls[0] += 1
            return {"entities": 0, "confirmed": 0, "flagged": 0}

        monkeypatch.setattr(
            "worker.compute_missing_identities",
            lambda limit=20: {"done": 0, "purged": 0, "skipped": 5},
        )
        monkeypatch.setattr("worker.audit_all_entities", counting_audit)

        _run_identity_cycle()
        assert audit_calls[0] == 0  # 100% skipped → pas de re-audit

    def test_audits_when_done(self, monkeypatch):
        from worker import _run_identity_cycle

        monkeypatch.setattr(
            "worker.compute_missing_identities",
            lambda limit=20: {"done": 3, "purged": 0, "skipped": 0},
        )
        called = [0]
        monkeypatch.setattr(
            "worker.audit_all_entities",
            lambda: (called.__setitem__(0, called[0] + 1) or {"entities": 1, "confirmed": 1, "flagged": 0}),
        )

        _run_identity_cycle()
        assert called[0] == 1


# ── merge ───────────────────────────────────────────────────────────


class TestMergeCycle:
    def test_records_merge_ok_event(self, monkeypatch):
        from worker import _run_merge_cycle
        from worker_metrics import get_status

        monkeypatch.setattr(
            "worker.auto_merge_by_qid",
            lambda: {"merged": 2, "blocked": 0, "details": [], "blocks": []},
        )
        _run_merge_cycle()

        s = get_status()
        assert s["events_24h"]["merge_ok"] == 2

    def test_records_merge_blocked_event(self, monkeypatch):
        from worker import _run_merge_cycle
        from worker_metrics import get_status

        monkeypatch.setattr(
            "worker.auto_merge_by_qid",
            lambda: {"merged": 0, "blocked": 1, "details": [],
                     "blocks": [{"reason": "growth_ratio"}]},
        )
        _run_merge_cycle()

        s = get_status()
        assert s["events_24h"]["merge_blocked"] == 1
        assert "merge_ok" not in s["events_24h"]


# ── wudd_sync ───────────────────────────────────────────────────────


class TestWuddSyncCycle:
    def test_runs_and_records(self, monkeypatch):
        from worker import _run_wudd_sync_cycle
        from worker_metrics import get_status

        monkeypatch.setattr(
            "worker.wudd_sync_persons",
            lambda: {"fetched": 100, "created": 5, "image_added": 3, "noop": 92, "failed": 0},
        )
        result = _run_wudd_sync_cycle()
        assert result["created"] == 5

        s = get_status()
        assert s["loops"]["wudd_sync"]["successes_24h"] == 1


# ── wudd_articles_batch ─────────────────────────────────────────────


class TestWuddArticlesBatchCycle:
    def test_runs_and_records(self, monkeypatch):
        from worker import _run_wudd_articles_batch_cycle
        from worker_metrics import get_status

        monkeypatch.setattr(
            "worker.wudd_articles_run_batch",
            lambda: {
                "selected": 5,
                "entities_processed": 4,
                "articles_new": 25,
                "articles_already": 8,
                "images_downloaded": 15,
                "details": [],
            },
        )
        result = _run_wudd_articles_batch_cycle()
        assert result["entities_processed"] == 4

        s = get_status()
        assert s["loops"]["wudd_articles_batch"]["successes_24h"] == 1
        # `details` ne doit pas figurer dans le summary stocké (verbeux)
        assert "details" not in s["loops"]["wudd_articles_batch"]["last_summary"]


# ── backup ──────────────────────────────────────────────────────────


class TestBackupCycle:
    def test_runs_and_records(self, monkeypatch):
        from worker import _run_backup_cycle
        from worker_metrics import get_status

        monkeypatch.setattr(
            "worker.make_backup",
            lambda: {
                "date": "2026-05-14",
                "created": [{"kind": "daily", "path": "/x.gz", "size": 1000}],
                "rotated": {},
            },
        )
        result = _run_backup_cycle()
        assert len(result["created"]) == 1

        s = get_status()
        assert s["loops"]["backup"]["successes_24h"] == 1
        assert s["loops"]["backup"]["last_summary"] == {"created": 1}

    def test_handles_exception(self, monkeypatch):
        from worker import _run_backup_cycle
        from worker_metrics import get_status

        def boom():
            raise OSError("disk full")

        monkeypatch.setattr("worker.make_backup", boom)
        result = _run_backup_cycle()
        assert result == {"created": []}

        s = get_status()
        assert s["loops"]["backup"]["errors_24h"] == 1


# ── Error paths sur les cycles restants ─────────────────────────────


class TestCycleErrorPaths:
    """Couvre les branches `except` pour chaque cycle worker."""

    def test_dedup_records_error(self, monkeypatch):
        from worker import _run_dedup_cycle
        from worker_metrics import get_status

        monkeypatch.setattr(
            "worker.compute_missing_embeddings",
            lambda limit=20: (_ for _ in ()).throw(RuntimeError("dedup boom")),
        )
        _run_dedup_cycle()
        s = get_status()
        assert s["loops"]["dedup"]["errors_24h"] == 1

    def test_identity_records_error(self, monkeypatch):
        from worker import _run_identity_cycle
        from worker_metrics import get_status

        def boom(limit=20):
            raise RuntimeError("identity boom")

        monkeypatch.setattr("worker.compute_missing_identities", boom)
        _run_identity_cycle()
        s = get_status()
        assert s["loops"]["identity"]["errors_24h"] == 1

    def test_merge_records_error(self, monkeypatch):
        from worker import _run_merge_cycle
        from worker_metrics import get_status

        def boom():
            raise RuntimeError("merge boom")

        monkeypatch.setattr("worker.auto_merge_by_qid", boom)
        result = _run_merge_cycle()
        assert result == {"merged": 0, "blocked": 0}
        s = get_status()
        assert s["loops"]["merge"]["errors_24h"] == 1

    def test_wudd_sync_records_error(self, monkeypatch):
        from worker import _run_wudd_sync_cycle
        from worker_metrics import get_status

        def boom():
            raise RuntimeError("wudd sync boom")

        monkeypatch.setattr("worker.wudd_sync_persons", boom)
        result = _run_wudd_sync_cycle()
        assert result == {}
        s = get_status()
        assert s["loops"]["wudd_sync"]["errors_24h"] == 1

    def test_wudd_articles_batch_records_error(self, monkeypatch):
        from worker import _run_wudd_articles_batch_cycle
        from worker_metrics import get_status

        def boom():
            raise RuntimeError("wudd batch boom")

        monkeypatch.setattr("worker.wudd_articles_run_batch", boom)
        result = _run_wudd_articles_batch_cycle()
        assert result == {"entities_processed": 0}
        s = get_status()
        assert s["loops"]["wudd_articles_batch"]["errors_24h"] == 1


# ── main() boot ─────────────────────────────────────────────────────


class TestMain:
    """Couvre le path de démarrage. On mocke `threading.Thread` pour ne
    pas réellement lancer les loops, et on casse la boucle d'idle avec
    une exception qu'on intercepte."""

    def test_main_starts_all_loops(self, monkeypatch):
        import worker

        # Track threads créés
        created = []

        class FakeThread:
            def __init__(self, target, daemon, name):
                created.append(name)
                self.target = target
                self.daemon = daemon
                self.name = name

            def start(self):
                # Ne pas exécuter le target (= boucle infinie)
                pass

        monkeypatch.setattr("worker.threading.Thread", FakeThread)

        # Casse `while True: time.sleep(3600)` pour ne pas bloquer le test
        sleep_calls = [0]

        def short_sleep(secs):
            sleep_calls[0] += 1
            if sleep_calls[0] >= 1:
                raise KeyboardInterrupt()

        monkeypatch.setattr("worker.time.sleep", short_sleep)

        with pytest.raises(KeyboardInterrupt):
            worker.main()

        assert set(created) == {
            "analyze", "enrich", "dedup", "identity",
            "merge", "wudd_sync", "wudd_articles_batch", "backup",
        }

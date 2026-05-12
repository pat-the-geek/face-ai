"""Tests du module worker_metrics (persistance DB depuis v021).

L'API et le worker tournent dans des process Docker distincts, donc les
métriques sont stockées dans la table `worker_events`. Les tests vérifient
les agrégations et le comportement de fenêtre glissante.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest


@pytest.fixture(autouse=True)
def _reset_metrics():
    from worker_metrics import reset_for_tests

    reset_for_tests()
    yield
    reset_for_tests()


def _insert_event(kind: str, loop_name: str | None, summary: str | None, ts: datetime):
    """Insert direct pour contrôler le timestamp (sinon CURRENT_TIMESTAMP)."""
    from database import SessionLocal, WorkerEvent

    db = SessionLocal()
    try:
        db.add(WorkerEvent(ts=ts, kind=kind, loop_name=loop_name, summary=summary))
        db.commit()
    finally:
        db.close()


class TestRecord:
    def test_success_creates_loop_entry(self):
        from worker_metrics import get_status, record_success

        record_success("analyze", {"done": 3})
        s = get_status()
        assert "analyze" in s["loops"]
        assert s["loops"]["analyze"]["successes_24h"] == 1
        assert s["loops"]["analyze"]["last_summary"] == {"done": 3}
        assert s["loops"]["analyze"]["last_success_at"] is not None
        assert s["loops"]["analyze"]["last_error_at"] is None

    def test_error_keeps_last_success(self):
        """Un échec n'efface pas la trace du dernier succès."""
        from worker_metrics import get_status, record_error, record_success

        record_success("merge", {"merged": 0})
        record_error("merge")
        s = get_status()
        assert s["loops"]["merge"]["last_success_at"] is not None
        assert s["loops"]["merge"]["last_error_at"] is not None
        assert s["loops"]["merge"]["errors_24h"] == 1
        assert s["loops"]["merge"]["successes_24h"] == 1

    def test_event_counter(self):
        from worker_metrics import get_status, record_event

        record_event("merge_ok")
        record_event("merge_ok")
        record_event("merge_blocked")
        s = get_status()
        assert s["events_24h"]["merge_ok"] == 2
        assert s["events_24h"]["merge_blocked"] == 1


class TestSlidingWindow:
    def test_events_older_than_24h_are_evicted_from_counts(self):
        """Un event de plus de 24h ne compte plus dans successes_24h
        mais reste visible comme `last_success_at` (signature historique)."""
        from worker_metrics import get_status

        now = datetime.utcnow()
        _insert_event("success", "analyze", None, now - timedelta(hours=25))
        s = get_status()
        assert s["loops"]["analyze"]["successes_24h"] == 0
        assert s["loops"]["analyze"]["last_success_at"] is not None

    def test_events_within_window_counted(self):
        from worker_metrics import get_status

        now = datetime.utcnow()
        _insert_event("merge_ok", None, None, now - timedelta(hours=23))
        s = get_status()
        assert s["events_24h"]["merge_ok"] == 1

    def test_last_summary_is_latest_success(self):
        """`last_summary` reflète le DERNIER cycle, pas un cycle ancien."""
        import json
        from worker_metrics import get_status

        now = datetime.utcnow()
        _insert_event("success", "merge",
                     json.dumps({"merged": 5}), now - timedelta(hours=2))
        _insert_event("success", "merge",
                     json.dumps({"merged": 0}), now - timedelta(minutes=2))
        s = get_status()
        assert s["loops"]["merge"]["last_summary"] == {"merged": 0}


class TestApiEndpoint:
    def test_worker_status_endpoint_shape(self, client):
        from worker_metrics import record_event, record_success

        record_success("analyze", {"done": 1})
        record_event("merge_ok")
        r = client.get("/admin/worker-status")
        assert r.status_code == 200
        data = r.json()
        assert "loops" in data
        assert "events_24h" in data
        assert "db" in data
        assert "total_images" in data["db"]
        assert "flagged_ratio" in data["db"]
        assert data["loops"]["analyze"]["successes_24h"] == 1
        assert data["events_24h"]["merge_ok"] == 1

    def test_db_ratios_with_flagged_images(self, client, db):
        """flagged_ratio reflète l'état DB réel."""
        from datetime import datetime

        from database import Entity, Image

        e = Entity(name="X, Y", slug="x-y", first_seen=datetime.utcnow())
        db.add(e)
        db.flush()
        for status in ("auto", "auto", "flagged", "flagged"):
            db.add(Image(
                entity_id=e.id,
                source_url=f"https://ex.com/{status}-{id(status)}",
                scrape_status="downloaded",
                association_status=status,
            ))
        db.commit()

        r = client.get("/admin/worker-status")
        data = r.json()
        assert data["db"]["total_images"] == 4
        assert data["db"]["flagged_images"] == 2
        assert data["db"]["flagged_ratio"] == 0.5

    def test_worker_status_cross_process_visibility(self, client):
        """L'enjeu du refactor v021 : un event écrit par un process est
        bien visible depuis un autre. Ici on simule en insérant
        directement en DB puis en lisant via l'endpoint API."""
        now = datetime.utcnow()
        _insert_event("success", "wudd_sync", '{"created": 0}', now)
        _insert_event("merge_blocked", None, None, now)

        r = client.get("/admin/worker-status")
        data = r.json()
        assert data["loops"]["wudd_sync"]["successes_24h"] == 1
        assert data["events_24h"]["merge_blocked"] == 1

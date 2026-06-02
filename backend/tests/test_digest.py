"""Tests du digest hebdomadaire (v031).

On ne teste pas l'envoi réseau Discord ni Ollama (effets de bord externes) :
on couvre la mise en forme du texte (dérivé du share of voice) et la logique
de planification/dédup de `maybe_send_digest`.
"""
from __future__ import annotations

import pytest

# ⚠️ NE PAS importer `notifications` au top-level : il importe `database`, ce
# qui câblerait l'engine sur la prod si conftest n'avait pas (depuis l'incident
# 2026-06-02) déjà redirigé FACE_AI_DB. Import différé via la fixture ci-dessous
# par sécurité (convention du repo + ceinture/bretelles).


@pytest.fixture
def N():
    import notifications

    return notifications


_SOV = {
    "window_days": 7,
    "from": "2026-05-26",
    "to": "2026-06-02",
    "total_mentions": 100,
    "entities": [
        {"name": "Musk, Elon", "slug": "musk-elon", "articles": 40, "share_pct": 40.0, "trend": "up"},
        {"name": "Trump, Donald", "slug": "trump-donald", "articles": 30, "share_pct": 30.0, "trend": "down"},
        {"name": "Newcomer, X", "slug": "newcomer-x", "articles": 10, "share_pct": 10.0, "trend": "new"},
    ],
}


def _disable_llm(monkeypatch, N):
    monkeypatch.setattr(N.config, "OLLAMA_SYNTHESIS_ENABLED", False)


class TestDigestText:
    def test_formats_ranking_and_newcomers(self, monkeypatch, N):
        _disable_llm(monkeypatch, N)
        monkeypatch.setattr(
            "presence.compute_share_of_voice", lambda **kw: _SOV
        )
        txt = N._digest_text()
        assert "Veille hebdo FACE.ai" in txt
        assert "100 mentions" in txt
        assert "▲ Musk, Elon — 40.0%" in txt
        assert "▼ Trump, Donald — 30.0%" in txt
        # Nouvel entrant : symbole ✦ + tag 🆕 + ligne dédiée
        assert "✦ Newcomer, X" in txt
        assert "🆕 Nouveaux entrants : Newcomer, X" in txt

    def test_none_when_no_mentions(self, monkeypatch, N):
        _disable_llm(monkeypatch, N)
        empty = {"total_mentions": 0, "entities": [], "from": "x", "to": "y"}
        monkeypatch.setattr("presence.compute_share_of_voice", lambda **kw: empty)
        assert N._digest_text() is None


class TestMaybeSendDigest:
    def test_skipped_when_disabled(self, monkeypatch, N):
        monkeypatch.setattr(N.config, "NOTIFY_DIGEST_ENABLED", False)
        assert N.maybe_send_digest() == {"skipped": "disabled"}

    def test_force_sends_regardless_of_schedule(self, monkeypatch, N):
        monkeypatch.setattr(N.config, "NOTIFY_DIGEST_ENABLED", False)
        sent = {}
        monkeypatch.setattr(
            N, "send_weekly_digest", lambda: sent.setdefault("called", True) or True
        )
        res = N.maybe_send_digest(force=True)
        assert res["sent"] is True
        assert res["forced"] is True
        assert sent.get("called")

    def test_not_scheduled_wrong_day(self, monkeypatch, N):
        monkeypatch.setattr(N.config, "NOTIFY_DIGEST_ENABLED", True)

        class _Now:
            @staticmethod
            def utcnow():
                import datetime as _dt
                # 2026-06-03 = mercredi (weekday 2), 8h
                return _dt.datetime(2026, 6, 3, 8, 0, 0)

        monkeypatch.setattr(N.config, "NOTIFY_DIGEST_DAY", 0)  # lundi
        monkeypatch.setattr(N.config, "NOTIFY_DIGEST_HOUR", 8)
        monkeypatch.setattr(N, "datetime", _Now)
        assert N.maybe_send_digest() == {"skipped": "not_scheduled"}

    def test_dedup_same_week(self, monkeypatch, N):
        monkeypatch.setattr(N.config, "NOTIFY_DIGEST_ENABLED", True)

        import datetime as _dt

        class _Now:
            @staticmethod
            def utcnow():
                return _dt.datetime(2026, 6, 1, 8, 0, 0)  # lundi 8h

        monkeypatch.setattr(N.config, "NOTIFY_DIGEST_DAY", 0)
        monkeypatch.setattr(N.config, "NOTIFY_DIGEST_HOUR", 8)
        monkeypatch.setattr(N, "datetime", _Now)
        # État : déjà envoyé cette semaine ISO
        week = N._iso_week_key()
        monkeypatch.setattr(N, "_load_state", lambda: {"last_digest_week": week})
        res = N.maybe_send_digest()
        assert res["skipped"] == "already_sent"

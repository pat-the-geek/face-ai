"""Tests des scénarios de notification OSINT non sensibles (E/F/G, v030).

On stub le réseau (`send_discord`) et le rendu de fiche (`_send_entity_card`)
pour tester uniquement la logique de détection + dédup. Imports différés
(convention test-isolation-prod-db).
"""
import json
from datetime import date


def _mk_entity(**kw):
    from database import Entity

    base = dict(wikidata_status="done")
    base.update(kw)
    return Entity(**base)


def test_media_tone_scenario(db, monkeypatch):
    import notifications as N
    from database import EntityGdeltCoverage

    sent = []
    monkeypatch.setattr(N, "_send_entity_card", lambda *a, **k: sent.append(k) or True)

    e = _mk_entity(name="Crise, Test", slug="crise-test")
    db.add(e)
    db.commit()
    db.add(
        EntityGdeltCoverage(
            entity_id=e.id,
            period_start=date(2026, 5, 1),
            period_end=date(2026, 5, 31),
            article_count=120,
            avg_tone=-8.5,  # < seuil -5
            top_countries=json.dumps([{"country": "US", "count": 40}]),
        )
    )
    # Snapshot positif → ne doit PAS déclencher
    e2 = _mk_entity(name="Calme, Test", slug="calme-test")
    db.add(e2)
    db.commit()
    db.add(
        EntityGdeltCoverage(
            entity_id=e2.id, period_end=date(2026, 5, 31),
            article_count=120, avg_tone=2.0, top_countries="[]",
        )
    )
    db.commit()

    assert N._notify_media_tone(db) == 1
    # Dédup : 2e passage ne renvoie rien
    assert N._notify_media_tone(db) == 0


def test_parliament_scenario(db, monkeypatch):
    import notifications as N

    monkeypatch.setattr(N, "_send_entity_card", lambda *a, **k: True)

    e = _mk_entity(
        name="Rossi, Mario", slug="rossi-mario",
        is_swiss_parliament_member=True,
        parliament_ch_data=json.dumps({"party": "PS", "canton": "VD"}),
    )
    db.add(e)
    db.commit()

    assert N._notify_new_parliament(db) == 1
    assert N._notify_new_parliament(db) == 0  # dédup


def test_new_country_scenario(db, monkeypatch):
    import notifications as N

    calls = []
    monkeypatch.setattr(N, "send_discord", lambda content, **k: calls.append(content) or True)
    # État neuf à chaque test
    monkeypatch.setattr(N, "_load_state", lambda: {})
    saved = {}
    monkeypatch.setattr(N, "_save_state", lambda s: saved.update(s))

    db.add(_mk_entity(name="A, B", slug="a-b", country_code="FR", country_name="France"))
    db.commit()

    # 1er passage : init silencieuse (known_countries=None → enregistre, 0 notif)
    assert N._notify_new_countries(db) == 0
    assert "FR" in saved["known_countries"]

    # Nouveau pays + état connu = {FR} → notifie CH
    monkeypatch.setattr(N, "_load_state", lambda: {"known_countries": ["FR"]})
    db.add(_mk_entity(name="C, D", slug="c-d", country_code="CH", country_name="Suisse"))
    db.commit()
    assert N._notify_new_countries(db) == 1
    assert any("Suisse" in c for c in calls)

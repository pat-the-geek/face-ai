"""Tests enrichissement OSINT + filtre pays (v030).

Convention d'isolation (cf. conftest / mémoire test-isolation-prod-db) : aucun
import de `database`/`api`/modules métier au top-level — tout est différé dans
les fonctions.
"""
import json


# ── Helpers purs (pas de DB) ────────────────────────────────────────────────

def test_country_code_to_flag():
    from osint_common import country_code_to_flag

    assert country_code_to_flag("CH") == "🇨🇭"
    assert country_code_to_flag("fr") == "🇫🇷"
    assert country_code_to_flag("US") == "🇺🇸"
    # Repli sur drapeau blanc pour codes invalides
    assert country_code_to_flag(None) == "🏳️"
    assert country_code_to_flag("X") == "🏳️"
    assert country_code_to_flag("123") == "🏳️"


def test_normalize_person_name():
    from osint_common import normalize_person_name

    assert normalize_person_name("Trump, Donald") == "donald trump"
    assert normalize_person_name("Zelensky, Volodymyr") == "volodymyr zelensky"
    # Accents repliés, mononyme inchangé
    assert normalize_person_name("Chalamet, Timothée") == "timothee chalamet"
    assert normalize_person_name("Madonna") == "madonna"
    assert normalize_person_name(None) == ""


def test_best_fuzzy_match():
    from osint_common import best_fuzzy_match, name_matches

    candidates = ["Donald Trump", "Joe Biden", "Emmanuel Macron"]
    idx, score = best_fuzzy_match("Trump, Donald", candidates, threshold=90)
    assert idx == 0 and score >= 90
    # En-dessous du seuil → pas de match
    idx2, _ = best_fuzzy_match("Xavier Niel", candidates, threshold=90)
    assert idx2 is None
    assert name_matches("Macron, Emmanuel", "Emmanuel Macron")
    assert not name_matches("Macron, Emmanuel", "Joe Biden")


# ── Fixtures de seed ────────────────────────────────────────────────────────

def _seed(db):
    from database import Entity

    rows = [
        Entity(
            name="Trump, Donald", slug="trump-donald", wikidata_status="done",
            country_code="US", country_name="États-Unis", article_count=10,
            sanctions_status="pep", is_swiss_parliament_member=False, icij_match=False,
        ),
        Entity(
            name="Macron, Emmanuel", slug="macron-emmanuel", wikidata_status="done",
            country_code="FR", country_name="France", article_count=8,
        ),
        Entity(
            name="Rossi, Mario", slug="rossi-mario", wikidata_status="done",
            country_code="CH", country_name="Suisse", article_count=3,
            is_swiss_parliament_member=True,
            parliament_ch_data=json.dumps({"party": "PS", "canton": "VD", "active": True}),
        ),
        # Tombstone : ne doit jamais ressortir
        Entity(
            name="OpenAI", slug="openai", wikidata_status="not_person",
            country_code="US",
        ),
    ]
    db.add_all(rows)
    db.commit()


# ── Filtre pays ─────────────────────────────────────────────────────────────

def test_country_stats(db):
    from osint_lookup import get_country_stats

    _seed(db)
    stats = get_country_stats()
    codes = {s["code"]: s for s in stats}
    # US a 1 entité PERSON (le tombstone OpenAI exclu)
    assert codes["US"]["count"] == 1
    assert codes["US"]["flag"] == "🇺🇸"
    assert codes["FR"]["name"] == "France"
    assert "openai" not in [s.get("name") for s in stats]


def test_list_entities_by_country(db):
    from osint_lookup import list_entities_by_country

    _seed(db)
    res = list_entities_by_country("ch")
    assert res["count"] == 1
    assert res["results"][0]["slug"] == "rossi-mario"
    assert res["results"][0]["country_flag"] == "🇨🇭"


def test_api_countries_and_filter(client, db):
    _seed(db)
    # /entities/countries
    countries = client.get("/entities/countries").json()
    by_code = {c["code"]: c for c in countries}
    assert by_code["US"]["count"] == 1 and by_code["US"]["flag"] == "🇺🇸"

    # /entities?country=FR
    r = client.get("/entities", params={"country": "FR"}).json()
    assert r["total"] == 1
    assert r["entities"][0]["slug"] == "macron-emmanuel"
    assert r["entities"][0]["country_flag"] == "🇫🇷"

    # /entities/letters?country=US ne compte que les US (tombstone exclu)
    letters = client.get("/entities/letters", params={"country": "US"}).json()
    assert letters["total"] == 1


# ── OSINT read endpoints ────────────────────────────────────────────────────

def test_sanctions_endpoint(client, db):
    _seed(db)
    r = client.get("/entities/trump-donald/sanctions")
    assert r.status_code == 200
    assert r.json()["sanctions_status"] == "pep"
    # 404 sur tombstone
    assert client.get("/entities/openai/sanctions").status_code == 404


def test_parliament_endpoint(client, db):
    _seed(db)
    data = client.get("/entities/rossi-mario/parliament").json()
    assert data["is_swiss_parliament_member"] is True
    assert data["party"] == "PS"
    assert data["canton"] == "VD"


def test_media_coverage_absent(client, db):
    _seed(db)
    data = client.get("/entities/macron-emmanuel/media-coverage").json()
    assert data["available"] is False


def test_portrait_history_empty(client, db):
    _seed(db)
    data = client.get("/entities/trump-donald/portrait-history").json()
    assert data["count"] == 0


# ── Conformité : frontière LAN — les surfaces hors LAN n'exposent jamais
#    les données OSINT sensibles (RGPD art. 9/10). Garde-fou durable. ───────


def test_markdown_export_excludes_sensitive_osint(db):
    """L'export Markdown (copiable hors LAN) ne doit JAMAIS contenir les
    statuts OpenSanctions/PEP ni les matches ICIJ, même quand ils sont posés
    sur l'entité. Empêche une régression future (ajout incident d'un champ)."""
    import bibliography
    from database import Entity

    e = Entity(
        name="Risky, Person", slug="risky-person", wikidata_status="done",
        country_code="RU", country_name="Russie",
        sanctions_status="sanctioned",
        sanctions_detail=json.dumps(
            {"topics": ["sanction"], "datasets": ["us_ofac_sdn"]}
        ),
        icij_match=True,
        icij_detail=json.dumps(
            [{"name": "SECRET OFFSHORE LTD", "dataset": "Panama Papers"}]
        ),
    )
    db.add(e)
    db.commit()

    md = (bibliography.entity_markdown(e.id) or "").lower()
    assert "risky" in md  # sanity : l'entité est bien rendue
    for forbidden in ("sanction", "ofac", "panama", "offshore", "icij", "pep"):
        assert forbidden not in md, f"fuite art. 9/10 hors LAN : '{forbidden}'"

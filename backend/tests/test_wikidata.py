"""Tests des fonctions Wikidata + Wikipedia avec mocks HTTP.

Aucun appel réseau réel — toutes les réponses viennent de
`tests/fixtures/wikidata_responses.py`.
"""
from unittest.mock import MagicMock

import pytest


def _mock_response(status_code=200, json_data=None, headers=None):
    m = MagicMock()
    m.status_code = status_code
    m.headers = headers or {}
    m.json.return_value = json_data if json_data is not None else {}
    return m


def _route(url, params=None, headers=None, timeout=None):
    """Routeur de mock paramétrable via la closure `_routes`.

    Cette fonction est patched dans `wikidata.requests.get` ; elle inspecte
    l'URL (et les params action= pour distinguer wbsearchentities/wbgetentities)
    pour décider quelle fixture renvoyer.
    """
    # Volontairement vide ; chaque test installe son propre routeur via patch
    raise NotImplementedError("test setup error: routeur non installé")


# ─────────────────────────────────────────────────────────────────
# _search_qid (Action API wbsearchentities)
# ─────────────────────────────────────────────────────────────────


class TestSearchQid:
    def test_finds_with_exact_label(self, monkeypatch):
        from tests.fixtures.wikidata_responses import SEARCH_ALTMAN_FR
        from wikidata import _search_qid

        monkeypatch.setattr(
            "wikidata.requests.get",
            lambda *a, **kw: _mock_response(json_data=SEARCH_ALTMAN_FR),
        )
        result = _search_qid("Sam Altman", lang="fr")
        assert result == ("Q7407093", "Sam Altman", 1.0)

    def test_score_0_7_when_label_differs(self, monkeypatch):
        from tests.fixtures.wikidata_responses import SEARCH_ALTMAN_FR_INEXACT
        from wikidata import _search_qid

        monkeypatch.setattr(
            "wikidata.requests.get",
            lambda *a, **kw: _mock_response(json_data=SEARCH_ALTMAN_FR_INEXACT),
        )
        # On cherche "Sam Altman" mais le label est "Samuel Altman" → 0.7
        result = _search_qid("Sam Altman")
        assert result is not None
        assert result[2] == 0.7

    def test_no_results_returns_none(self, monkeypatch):
        from tests.fixtures.wikidata_responses import SEARCH_EMPTY
        from wikidata import _search_qid

        monkeypatch.setattr(
            "wikidata.requests.get",
            lambda *a, **kw: _mock_response(json_data=SEARCH_EMPTY),
        )
        assert _search_qid("Personne Inconnue") is None

    def test_http_error_returns_none(self, monkeypatch):
        from wikidata import _search_qid

        monkeypatch.setattr(
            "wikidata.requests.get",
            lambda *a, **kw: _mock_response(status_code=500),
        )
        assert _search_qid("Sam") is None

    def test_429_respects_retry_after(self, monkeypatch):
        """Le retry doit attendre Retry-After puis retenter (best effort)."""
        from tests.fixtures.wikidata_responses import SEARCH_ALTMAN_FR
        from wikidata import _search_qid

        call_count = [0]

        def fake_get(*a, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return _mock_response(status_code=429, headers={"Retry-After": "1"})
            return _mock_response(json_data=SEARCH_ALTMAN_FR)

        # On patch aussi sleep pour ne pas vraiment attendre
        monkeypatch.setattr("wikidata.requests.get", fake_get)
        monkeypatch.setattr("wikidata.time.sleep", lambda s: None)
        result = _search_qid("Sam Altman")
        assert result is not None
        assert call_count[0] == 2


# ─────────────────────────────────────────────────────────────────
# _get_wiki_summary
# ─────────────────────────────────────────────────────────────────


class TestWikiSummary:
    def test_returns_summary(self, monkeypatch):
        from tests.fixtures.wikidata_responses import SUMMARY_ALTMAN_FR
        from wikidata import _get_wiki_summary

        monkeypatch.setattr(
            "wikidata.requests.get",
            lambda *a, **kw: _mock_response(json_data=SUMMARY_ALTMAN_FR),
        )
        result = _get_wiki_summary("Sam Altman", lang="fr")
        assert result is not None
        assert "entrepreneur" in result["extract"]

    def test_filters_disambiguation(self, monkeypatch):
        from tests.fixtures.wikidata_responses import SUMMARY_DISAMBIG
        from wikidata import _get_wiki_summary

        monkeypatch.setattr(
            "wikidata.requests.get",
            lambda *a, **kw: _mock_response(json_data=SUMMARY_DISAMBIG),
        )
        # Une page d'homonymie ne doit jamais être utilisée comme summary
        assert _get_wiki_summary("John Smith") is None

    def test_404_returns_none(self, monkeypatch):
        from wikidata import _get_wiki_summary

        monkeypatch.setattr(
            "wikidata.requests.get",
            lambda *a, **kw: _mock_response(status_code=404),
        )
        assert _get_wiki_summary("Personne") is None


# ─────────────────────────────────────────────────────────────────
# _get_statements + extracteurs
# ─────────────────────────────────────────────────────────────────


class TestStatements:
    def test_extract_qids_for_property(self):
        from tests.fixtures.wikidata_responses import STATEMENTS_ALTMAN
        from wikidata import _statement_qids

        # P106 = occupation, 2 valeurs dans la fixture
        qids = _statement_qids(STATEMENTS_ALTMAN, "P106")
        assert qids == ["Q5482740", "Q131524"]

    def test_extract_qids_missing_property(self):
        from tests.fixtures.wikidata_responses import STATEMENTS_ALTMAN
        from wikidata import _statement_qids

        # P570 (date décès) absent → liste vide, pas d'erreur
        assert _statement_qids(STATEMENTS_ALTMAN, "P570") == []

    def test_extract_times(self):
        from datetime import date

        from tests.fixtures.wikidata_responses import STATEMENTS_ALTMAN
        from wikidata import _statement_times

        dates = _statement_times(STATEMENTS_ALTMAN, "P569")
        assert dates == [date(1985, 4, 22)]

    def test_extract_times_handles_corrupted(self):
        """Date corrompue dans les statements → liste vide, pas d'exception."""
        from tests.fixtures.wikidata_responses import STATEMENTS_BADLY_FORMED
        from wikidata import _statement_times

        # Ne crash pas
        assert _statement_times(STATEMENTS_BADLY_FORMED, "P569") == []

    def test_extract_qids_skips_non_string_content(self):
        from tests.fixtures.wikidata_responses import STATEMENTS_BADLY_FORMED
        from wikidata import _statement_qids

        # P19 a un value sans content, P27 a content=None → liste vide
        assert _statement_qids(STATEMENTS_BADLY_FORMED, "P19") == []
        assert _statement_qids(STATEMENTS_BADLY_FORMED, "P27") == []


# ─────────────────────────────────────────────────────────────────
# _resolve_labels (batch)
# ─────────────────────────────────────────────────────────────────


class TestResolveLabels:
    def test_resolves_fr_with_en_fallback(self, monkeypatch):
        from tests.fixtures.wikidata_responses import LABELS_ALTMAN_BATCH
        from wikidata import _resolve_labels

        monkeypatch.setattr(
            "wikidata.requests.get",
            lambda *a, **kw: _mock_response(json_data=LABELS_ALTMAN_BATCH),
        )
        labels = _resolve_labels(
            ["Q1297", "Q30", "Q5482740", "Q131524", "Q21708200"], lang="fr"
        )
        assert labels["Q1297"] == "Chicago"
        assert labels["Q30"] == "États-Unis"
        # Q21708200 n'a pas de label FR → fallback EN "OpenAI"
        assert labels["Q21708200"] == "OpenAI"

    def test_empty_input(self):
        from wikidata import _resolve_labels

        assert _resolve_labels([]) == {}

    def test_chunking_50(self, monkeypatch):
        """Batch >50 → plusieurs appels HTTP."""
        from wikidata import _resolve_labels

        call_count = [0]

        def fake_get(*a, **kw):
            call_count[0] += 1
            return _mock_response(json_data={"entities": {}})

        monkeypatch.setattr("wikidata.requests.get", fake_get)
        # 120 QIDs → 3 appels (50, 50, 20)
        _resolve_labels([f"Q{i}" for i in range(120)])
        assert call_count[0] == 3


# ─────────────────────────────────────────────────────────────────
# enrich_entity — pipeline complet en intégration
# ─────────────────────────────────────────────────────────────────


class TestEnrichEntityIntegration:
    """Test du pipeline 3-temps : QID → summary → statements + labels.

    On installe un routeur HTTP qui dispatch selon l'URL/params réels.
    """

    def _install_router(self, monkeypatch):
        from tests.fixtures.wikidata_responses import (
            LABELS_ALTMAN_BATCH,
            SEARCH_ALTMAN_FR,
            STATEMENTS_ALTMAN,
            SUMMARY_ALTMAN_FR,
        )

        def router(url, params=None, headers=None, timeout=None):
            if "wikidata.org/w/api.php" in url:
                action = (params or {}).get("action")
                if action == "wbsearchentities":
                    return _mock_response(json_data=SEARCH_ALTMAN_FR)
                if action == "wbgetentities":
                    return _mock_response(json_data=LABELS_ALTMAN_BATCH)
            if "wikidata.org/w/rest.php" in url and "/statements" in url:
                return _mock_response(json_data=STATEMENTS_ALTMAN)
            if "wikipedia.org/api/rest_v1/page/summary" in url:
                return _mock_response(json_data=SUMMARY_ALTMAN_FR)
            return _mock_response(status_code=404)

        monkeypatch.setattr("wikidata.requests.get", router)

    def test_full_enrichment(self, db, monkeypatch):
        from database import Entity
        from wikidata import enrich_entity

        self._install_router(monkeypatch)

        e = Entity(name="Altman, Sam", slug="sam-altman")
        db.add(e)
        db.commit()
        eid = e.id

        result = enrich_entity(eid)
        assert result == "done"

        db.refresh(e)
        assert e.wikidata_qid == "Q7407093"
        assert e.wikidata_status == "done"
        assert "entrepreneur" in (e.wiki_summary or "")
        assert e.wiki_url == "https://fr.wikipedia.org/wiki/Sam_Altman"
        # Bio
        from datetime import date

        assert e.birth_date == date(1985, 4, 22)
        assert e.birth_place == "Chicago"
        assert e.nationalities == "États-Unis"
        assert "entrepreneur" in (e.occupations or "")
        assert e.employer == "OpenAI"

    def test_not_found_when_qid_missing(self, db, monkeypatch):
        from database import Entity
        from tests.fixtures.wikidata_responses import SEARCH_EMPTY
        from wikidata import enrich_entity

        monkeypatch.setattr(
            "wikidata.requests.get",
            lambda *a, **kw: _mock_response(json_data=SEARCH_EMPTY),
        )
        e = Entity(name="Inconnue, Personne", slug="personne-inconnue")
        db.add(e)
        db.commit()
        eid = e.id

        assert enrich_entity(eid) == "not_found"
        db.refresh(e)
        assert e.wikidata_status == "not_found"
        assert e.wikidata_qid is None

    def test_score_backfilled_for_preset_qid_with_exact_label(self, db, monkeypatch):
        """Si une entité a un QID préfixé manuellement mais pas de score
        (cas démerge humain), enrich_entity doit récupérer le label
        Wikidata et écrire `wikidata_score = 1.0` quand il matche.

        Sans ça, le garde-fou anti-fusion (qui exige score >= 1.0) rejette
        l'entité pour toujours — effet de bord observé après l'incident
        2026-05-11. Cf. wikidata.py:enrich_entity backfill.
        """
        from database import Entity
        from wikidata import enrich_entity

        # Fixture : wbgetentities renvoie un label exact pour Q7407093
        def router(url, params=None, headers=None, timeout=None):
            from tests.fixtures.wikidata_responses import (
                STATEMENTS_ALTMAN,
                SUMMARY_ALTMAN_FR,
            )

            if "rest.php" in url:
                return _mock_response(json_data=STATEMENTS_ALTMAN)
            if "rest_v1/page/summary" in url:
                return _mock_response(json_data=SUMMARY_ALTMAN_FR)
            if "api.php" in url:
                action = (params or {}).get("action")
                ids = (params or {}).get("ids", "")
                # Notre _get_wikidata_label appelle wbgetentities sur Q7407093
                if action == "wbgetentities" and "Q7407093" in ids:
                    return _mock_response(json_data={
                        "entities": {
                            "Q7407093": {
                                "labels": {"fr": {"value": "Sam Altman"}}
                            }
                        }
                    })
                # Sinon batch labels statements
                return _mock_response(json_data={"entities": {}})
            return _mock_response(status_code=404)

        monkeypatch.setattr("wikidata.requests.get", router)

        e = Entity(
            name="Altman, Sam",
            slug="sam-altman",
            wikidata_qid="Q7407093",
            wikidata_score=None,  # préfixé sans score
        )
        db.add(e)
        db.commit()
        eid = e.id

        enrich_entity(eid)
        db.refresh(e)
        # Label Wikidata "Sam Altman" == search_name "Sam Altman" → 1.0
        assert e.wikidata_score == 1.0

    def test_score_backfill_keeps_07_when_label_mismatch(self, db, monkeypatch):
        """Si le label Wikidata ne matche pas exactement le search_name,
        score = 0.7 (signal de prudence pour le garde-fou)."""
        from database import Entity
        from wikidata import enrich_entity

        def router(url, params=None, headers=None, timeout=None):
            from tests.fixtures.wikidata_responses import (
                STATEMENTS_ALTMAN,
                SUMMARY_ALTMAN_FR,
            )

            if "rest.php" in url:
                return _mock_response(json_data=STATEMENTS_ALTMAN)
            if "rest_v1/page/summary" in url:
                return _mock_response(json_data=SUMMARY_ALTMAN_FR)
            if "api.php" in url:
                if (params or {}).get("action") == "wbgetentities":
                    return _mock_response(json_data={
                        "entities": {
                            "Q7407093": {
                                "labels": {"fr": {"value": "Samuel Altman"}}
                            }
                        }
                    })
                return _mock_response(json_data={"entities": {}})
            return _mock_response(status_code=404)

        monkeypatch.setattr("wikidata.requests.get", router)

        e = Entity(
            name="Altman, Sam",
            slug="sam-altman",
            wikidata_qid="Q7407093",
            wikidata_score=None,
        )
        db.add(e)
        db.commit()
        eid = e.id

        enrich_entity(eid)
        db.refresh(e)
        # "Samuel Altman" != "Sam Altman" → 0.7
        assert e.wikidata_score == 0.7

    def test_idempotent_skips_qid_search_when_known(self, db, monkeypatch):
        """Si l'entité a déjà un QID, on ne re-cherche pas — on rafraîchit."""
        from database import Entity
        from wikidata import enrich_entity

        e = Entity(
            name="Altman, Sam",
            slug="sam-altman",
            wikidata_qid="Q7407093",  # déjà connu
        )
        db.add(e)
        db.commit()
        eid = e.id

        call_log = []

        def router(url, params=None, headers=None, timeout=None):
            call_log.append((url, (params or {}).get("action")))
            from tests.fixtures.wikidata_responses import (
                LABELS_ALTMAN_BATCH,
                STATEMENTS_ALTMAN,
                SUMMARY_ALTMAN_FR,
            )

            if "rest.php" in url:
                return _mock_response(json_data=STATEMENTS_ALTMAN)
            if "rest_v1/page/summary" in url:
                return _mock_response(json_data=SUMMARY_ALTMAN_FR)
            if "api.php" in url:
                return _mock_response(json_data=LABELS_ALTMAN_BATCH)
            return _mock_response(status_code=404)

        monkeypatch.setattr("wikidata.requests.get", router)
        enrich_entity(eid)
        # Aucune requête wbsearchentities ne doit avoir été faite
        actions = [a for _, a in call_log]
        assert "wbsearchentities" not in actions

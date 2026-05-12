"""Tests wudd_client.py — client HTTP pour l'API WUDD.

Pas de réseau réel : on patche `requests.get` avec un mock contrôlable
qui reproduit les réponses observées en pratique côté WUDD (champs `value`,
`mentions`, `image`, `articles`, etc.).
"""
from __future__ import annotations

from unittest.mock import MagicMock


def _mock_response(status_code=200, json_data=None, raise_on_call=None):
    """Helper : construit un mock `requests.Response`."""
    mock = MagicMock()
    mock.status_code = status_code
    if raise_on_call:
        mock.json.side_effect = raise_on_call
    else:
        mock.json.return_value = json_data if json_data is not None else {}
    return mock


# ── fetch_persons ────────────────────────────────────────────────────


class TestFetchPersons:
    def test_parses_normal_response(self, monkeypatch):
        from wudd_client import fetch_persons

        payload = {
            "returned": 2,
            "total": 6300,
            "entities": [
                {
                    "type": "PERSON",
                    "value": "Sam Altman",
                    "mentions": 89,
                    "image": {
                        "url": "https://commons.wikimedia.org/x.jpg",
                        "width": 800,
                        "height": 600,
                    },
                },
                {
                    "type": "PERSON",
                    "value": "Elon Musk",
                    "mentions": 1234,
                    "image": None,
                },
            ],
        }
        monkeypatch.setattr(
            "wudd_client.requests.get",
            lambda *a, **kw: _mock_response(json_data=payload),
        )

        persons = fetch_persons(limit=10)
        assert len(persons) == 2
        assert persons[0].value == "Sam Altman"
        assert persons[0].mentions == 89
        assert persons[0].image_url == "https://commons.wikimedia.org/x.jpg"
        assert persons[0].image_width == 800
        assert persons[1].image_url is None

    def test_filters_non_person_entities(self, monkeypatch):
        """Si WUDD renvoie par erreur un type ≠ PERSON, on l'écarte."""
        from wudd_client import fetch_persons

        payload = {
            "entities": [
                {"type": "PERSON", "value": "Sam Altman", "mentions": 89, "image": None},
                {"type": "ORG", "value": "OpenAI", "mentions": 500, "image": None},
                {"type": "LOC", "value": "France", "mentions": 200, "image": None},
            ],
        }
        monkeypatch.setattr(
            "wudd_client.requests.get",
            lambda *a, **kw: _mock_response(json_data=payload),
        )

        persons = fetch_persons()
        values = [p.value for p in persons]
        assert values == ["Sam Altman"]

    def test_passes_limit_to_query(self, monkeypatch):
        from wudd_client import fetch_persons

        captured: dict = {}

        def fake_get(url, params=None, headers=None, timeout=None):
            captured["params"] = params
            return _mock_response(json_data={"entities": []})

        monkeypatch.setattr("wudd_client.requests.get", fake_get)
        fetch_persons(limit=42)
        assert captured["params"]["limit"] == "42"
        assert captured["params"]["type"] == "PERSON"
        assert captured["params"]["images"] == "true"
        assert captured["params"]["sort"] == "mentions"

    def test_uses_config_limit_when_none(self, monkeypatch):
        """`limit=None` → `WUDD_PULL_LIMIT` (config)."""
        from wudd_client import fetch_persons

        captured: dict = {}

        def fake_get(url, params=None, headers=None, timeout=None):
            captured["params"] = params
            return _mock_response(json_data={"entities": []})

        monkeypatch.setattr("wudd_client.requests.get", fake_get)
        monkeypatch.setattr("wudd_client.WUDD_PULL_LIMIT", 137)
        fetch_persons()
        assert captured["params"]["limit"] == "137"

    def test_http_error_returns_empty(self, monkeypatch):
        from wudd_client import fetch_persons

        monkeypatch.setattr(
            "wudd_client.requests.get",
            lambda *a, **kw: _mock_response(status_code=500),
        )
        assert fetch_persons() == []

    def test_network_error_returns_empty(self, monkeypatch):
        import requests as req

        from wudd_client import fetch_persons

        def boom(*a, **kw):
            raise req.ConnectionError("WUDD unreachable")

        monkeypatch.setattr("wudd_client.requests.get", boom)
        assert fetch_persons() == []

    def test_bad_json_returns_empty(self, monkeypatch):
        from wudd_client import fetch_persons

        monkeypatch.setattr(
            "wudd_client.requests.get",
            lambda *a, **kw: _mock_response(raise_on_call=ValueError("not json")),
        )
        assert fetch_persons() == []

    def test_sends_user_agent(self, monkeypatch):
        from wudd_client import fetch_persons

        captured: dict = {}

        def fake_get(url, params=None, headers=None, timeout=None):
            captured["headers"] = headers
            return _mock_response(json_data={"entities": []})

        monkeypatch.setattr("wudd_client.requests.get", fake_get)
        fetch_persons()
        assert "FACE.ai" in captured["headers"]["User-Agent"]


# ── fetch_articles_for_person ────────────────────────────────────────


class TestFetchArticlesForPerson:
    def test_returns_articles_list(self, monkeypatch):
        from wudd_client import fetch_articles_for_person

        payload = [
            {"URL": "https://example.com/1", "Titre": "Art 1"},
            {"URL": "https://example.com/2", "Titre": "Art 2"},
        ]
        monkeypatch.setattr(
            "wudd_client.requests.get",
            lambda *a, **kw: _mock_response(json_data=payload),
        )

        articles = fetch_articles_for_person("Sam Altman", limit=10)
        assert len(articles) == 2
        assert articles[0]["URL"] == "https://example.com/1"

    def test_truncates_to_limit(self, monkeypatch):
        """WUDD renvoie max_articles=2000 mais on tronque côté client à `limit`."""
        from wudd_client import fetch_articles_for_person

        payload = [{"URL": f"https://ex.com/{i}"} for i in range(50)]
        monkeypatch.setattr(
            "wudd_client.requests.get",
            lambda *a, **kw: _mock_response(json_data=payload),
        )

        articles = fetch_articles_for_person("X", limit=10)
        assert len(articles) == 10

    def test_uses_max_articles_param(self, monkeypatch):
        """Côté WUDD le param de limite est `max_articles`, PAS `limit`."""
        from wudd_client import fetch_articles_for_person

        captured: dict = {}

        def fake_get(url, params=None, headers=None, timeout=None):
            captured["params"] = params
            return _mock_response(json_data=[])

        monkeypatch.setattr("wudd_client.requests.get", fake_get)
        fetch_articles_for_person("Sam Altman", limit=5)
        assert captured["params"]["max_articles"] == "2000"
        assert captured["params"]["match_mode"] == "aggregate"
        assert captured["params"]["value"] == "Sam Altman"
        # `limit` ne doit PAS être envoyé à WUDD (silencieusement ignoré)
        assert "limit" not in captured["params"]

    def test_dict_response_unwraps_articles_key(self, monkeypatch):
        """WUDD peut renvoyer soit list directe, soit dict avec clé articles."""
        from wudd_client import fetch_articles_for_person

        payload = {"articles": [{"URL": "https://ex.com/1"}]}
        monkeypatch.setattr(
            "wudd_client.requests.get",
            lambda *a, **kw: _mock_response(json_data=payload),
        )
        assert len(fetch_articles_for_person("X", limit=10)) == 1

    def test_http_error_returns_empty(self, monkeypatch):
        from wudd_client import fetch_articles_for_person

        monkeypatch.setattr(
            "wudd_client.requests.get",
            lambda *a, **kw: _mock_response(status_code=404),
        )
        assert fetch_articles_for_person("X") == []

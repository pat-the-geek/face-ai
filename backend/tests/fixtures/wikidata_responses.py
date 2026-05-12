"""Réponses Wikimedia minimales pour les tests offline.

La spec §17 exige : "Wikimedia tests must use JSON fixtures — never hit the
live API in CI". Ces structures reproduisent la *shape* exacte des réponses
réelles, avec juste assez de champs pour exercer le parsing.

Conventions :
- `SEARCH_*` : Action API `wbsearchentities`
- `STATEMENTS_*` : REST v1 `entities/items/{qid}/statements`
- `LABELS_*` : Action API `wbgetentities&props=labels`
- `SUMMARY_*` : REST v1 `page/summary`
"""

# ── Action API : wbsearchentities ───────────────────────────────────

SEARCH_ALTMAN_FR = {
    "search": [
        {
            "id": "Q7407093",
            "label": "Sam Altman",
            "description": "entrepreneur américain",
        },
    ],
    "success": 1,
}

SEARCH_ALTMAN_FR_INEXACT = {
    # Le label diffère de la requête → score 0.7 attendu
    "search": [
        {
            "id": "Q12345",
            "label": "Samuel Altman",
            "description": "homonyme",
        },
    ],
    "success": 1,
}

SEARCH_EMPTY = {"search": [], "success": 1}


# ── REST v1 : entities/items/{qid}/statements ───────────────────────

STATEMENTS_ALTMAN = {
    "P569": [
        {"value": {"content": {"time": "+1985-04-22T00:00:00Z"}}},
    ],
    "P19": [{"value": {"content": "Q1297"}}],  # Chicago
    "P27": [{"value": {"content": "Q30"}}],  # États-Unis
    "P106": [
        {"value": {"content": "Q5482740"}},  # programmeur
        {"value": {"content": "Q131524"}},  # entrepreneur
    ],
    "P108": [{"value": {"content": "Q21708200"}}],  # OpenAI
}

STATEMENTS_EMPTY = {}

STATEMENTS_BADLY_FORMED = {
    # Date corrompue, QID manquant → ne doit pas crasher
    "P569": [{"value": {"content": {"time": "+invalid"}}}],
    "P19": [{"value": {}}],  # pas de content
    "P27": [{"value": {"content": None}}],
}


# ── Action API : wbgetentities (résolution batch de labels) ─────────

LABELS_ALTMAN_BATCH = {
    "entities": {
        "Q1297": {"labels": {"fr": {"value": "Chicago"}}},
        "Q30": {"labels": {"fr": {"value": "États-Unis"}}},
        "Q5482740": {"labels": {"fr": {"value": "programmeur"}}},
        "Q131524": {"labels": {"fr": {"value": "entrepreneur"}}},
        # Pas de label FR → fallback EN
        "Q21708200": {"labels": {"en": {"value": "OpenAI"}}},
    },
    "success": 1,
}


# ── REST v1 : page/summary ──────────────────────────────────────────

SUMMARY_ALTMAN_FR = {
    "type": "standard",
    "title": "Sam Altman",
    "extract": "Sam Altman, né le 22 avril 1985 à Chicago, est un entrepreneur américain.",
    "content_urls": {
        "desktop": {"page": "https://fr.wikipedia.org/wiki/Sam_Altman"},
    },
    "thumbnail": {
        "source": "https://upload.wikimedia.org/.../330px-Sam_Altman.jpg",
        "width": 330,
        "height": 440,
    },
    "originalimage": {
        "source": "https://upload.wikimedia.org/.../Sam_Altman.jpg",
        "width": 1216,
        "height": 1620,
    },
}

SUMMARY_DISAMBIG = {
    "type": "disambiguation",
    "title": "John Smith",
    "extract": "John Smith peut désigner...",
}

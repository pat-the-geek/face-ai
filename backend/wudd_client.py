"""Client HTTP pour l'API d'export WUDD.ai (spec §8, mode pull).

WUDD.ai expose `GET /api/entities/export` qui renvoie la liste des entités
NER avec, pour chaque entité PERSON, l'URL Wikimedia mise en cache côté WUDD.

Documentation : https://github.com/pat-the-geek/WUDD.ai/blob/main/docs/ENTITIES.md
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterator

import requests

from config import WUDD_BASE_URL, WUDD_PULL_LIMIT, WUDD_USER_AGENT

log = logging.getLogger("wudd_client")
HTTP_TIMEOUT = 20


@dataclass
class WuddPerson:
    """Une entité PERSON telle qu'exposée par WUDD.ai."""

    value: str  # forme naturelle "Donald Trump", non canonicalisée
    mentions: int
    image_url: str | None
    image_width: int | None = None
    image_height: int | None = None


def fetch_persons(limit: int | None = None) -> list[WuddPerson]:
    """Récupère les PERSON entities depuis WUDD, triées par mentions desc.

    `limit` : None → utilise `WUDD_PULL_LIMIT` (config). Max API = 5000.
    """
    effective_limit = limit if limit is not None else WUDD_PULL_LIMIT
    url = f"{WUDD_BASE_URL}/api/entities/export"
    params = {
        "type": "PERSON",
        "images": "true",
        "limit": str(effective_limit),
        "sort": "mentions",
    }
    try:
        r = requests.get(
            url,
            params=params,
            headers={"User-Agent": WUDD_USER_AGENT, "Accept": "application/json"},
            timeout=HTTP_TIMEOUT,
        )
    except requests.RequestException as e:
        log.error("WUDD export fetch failed: %s", e)
        return []

    if r.status_code != 200:
        log.error("WUDD export HTTP %d", r.status_code)
        return []

    try:
        data = r.json()
    except ValueError as e:
        log.error("WUDD export not JSON: %s", e)
        return []

    persons: list[WuddPerson] = []
    for ent in data.get("entities", []):
        if ent.get("type") != "PERSON":
            continue
        img = ent.get("image") or {}
        persons.append(
            WuddPerson(
                value=ent.get("value", "").strip(),
                mentions=int(ent.get("mentions", 0) or 0),
                image_url=img.get("url") if isinstance(img, dict) else None,
                image_width=img.get("width") if isinstance(img, dict) else None,
                image_height=img.get("height") if isinstance(img, dict) else None,
            )
        )
    log.info(
        "WUDD pull : %d/%d PERSON entities (total côté amont : %d)",
        len(persons),
        data.get("returned", -1),
        data.get("total", -1),
    )
    return persons


def fetch_articles_for_person(value: str, limit: int = 50) -> list[dict]:
    """Articles WUDD mentionnant une PERSON donnée.

    Retourne la liste brute des articles tels qu'exposés par WUDD :
    chaque article a `URL`, `Titre`, `Date de publication`, `Sources`,
    `Images` (liste pré-extraite avec url/alt/width/height) et
    `entities.PERSON` (liste des personnes mentionnées).

    L'avantage de cette voie vs scraper la page HTML d'origine : les images
    sont déjà extraites + filtrées par WUDD, et on a le contexte sémantique
    (autres PERSON mentionnées) pour la résolution des associations.

    **Détails côté WUDD** (cf. `viewer/routes/entities.py::api_entities_articles`) :
    - Le param de limite serveur s'appelle `max_articles` (pas `limit`),
      défaut 300, cap absolu 2000.
    - Le `match_mode` par défaut est `canonical` qui regroupe les variantes
      d'une même entité (ex. "Sam Altman" et "Altman" peuvent être agrégés).
      On explicite `aggregate` pour récupérer le maximum d'articles connus
      sur cette personne, indépendamment de la forme exacte de référence.
    """
    url = f"{WUDD_BASE_URL}/api/entities/articles"
    # `max_articles` côté WUDD plafonne à 2000 ; on demande ce maximum pour
    # récupérer tout, puis on tronque côté client à `limit`.
    params = {
        "value": value,
        "type": "PERSON",
        "max_articles": "2000",
        "match_mode": "aggregate",
    }
    try:
        r = requests.get(
            url,
            params=params,
            headers={"User-Agent": WUDD_USER_AGENT, "Accept": "application/json"},
            timeout=HTTP_TIMEOUT,
        )
    except requests.RequestException as e:
        log.error("WUDD articles fetch failed for %s : %s", value, e)
        return []

    if r.status_code != 200:
        log.error("WUDD articles HTTP %d for %s", r.status_code, value)
        return []

    try:
        data = r.json()
    except ValueError as e:
        log.error("WUDD articles not JSON: %s", e)
        return []

    articles = data if isinstance(data, list) else (data.get("articles") or [])
    return articles[:limit]

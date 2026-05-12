"""Enrichissement Wikidata + Wikipedia (spec §9).

Pour chaque entité, on résout en trois temps :
1. **QID Wikidata** via Action API `wbsearchentities` — l'identifiant stable
2. **Summary + thumbnail Wikipedia** via REST v1 `page/summary` — le contenu humain
3. **Statements biographiques** via REST v1 `entities/items/{qid}/statements`
   (date naissance/décès, occupations, employer, lieu naissance, nationalités)
   puis résolution batch des QIDs imbriqués en labels via Action API
   `wbgetentities&props=labels` (1 appel par tranche de 50 QIDs).

La spec §9.1 précise que l'Action API et le REST v1 ont des shapes de réponse
différentes ; on n'utilise volontairement chaque API que pour ce qu'elle fait
le mieux.

Politesse :
- User-Agent obligatoire `FACE.ai/1.0 (contact@ok-ia.ch)` (spec §9.4)
- Délai inter-requête côté worker (1 s par défaut), pas de parallélisme ici
- Respect du `Retry-After` sur 429 (best effort)
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime
from urllib.parse import quote

import requests

from database import Entity, SessionLocal

USER_AGENT = "FACE.ai/1.0 (contact@ok-ia.ch)"
HTTP_TIMEOUT = 15
LANG_CHAIN = ("fr", "en")

# Propriétés Wikidata (spec §9.3)
PROP_INSTANCE_OF = "P31"
PROP_DATE_OF_BIRTH = "P569"
PROP_DATE_OF_DEATH = "P570"
PROP_PLACE_OF_BIRTH = "P19"
PROP_PLACE_OF_DEATH = "P20"
PROP_COUNTRY_CITIZENSHIP = "P27"
PROP_OCCUPATION = "P106"
PROP_EMPLOYER = "P108"

# QIDs valides pour `instance of` côté FACE.ai. Le périmètre est strictement
# "personne réelle" (cf. spec §1.5 et CLAUDE.md — veille interne sur des
# personnalités publiques apparaissant dans la presse).
#
# - Q5 = être humain (cas standard, ~99 %)
# - Q95074 = personnage de fiction → REJETÉ explicitement
# - Q43229 = organisation → REJETÉ
# - Q41710 = ethnie → REJETÉ
# - Q4830453 = entreprise → REJETÉ (cas WUDD typique : "OpenAI" mal classé)
# - Q486972 = établissement humain → REJETÉ (cas "Mar-a-Lago", "Apple Park")
#
# On accepte uniquement Q5. Si une entité a P31={Q5, autre}, elle reste valide
# (cas rare où Wikidata qualifie aussi en "individu historique", etc.).
PERSON_QIDS = frozenset({"Q5"})

WIKIDATA_TIME_RX = re.compile(r"^[+-](\d{4})-(\d{2})-(\d{2})")

log = logging.getLogger("wikidata")


def _http_get_json(url: str, params: dict | None = None) -> dict | None:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=HTTP_TIMEOUT)
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", "5"))
            log.warning(f"429 sur {url} → wait {wait}s")
            time.sleep(min(wait, 60))
            r = requests.get(url, params=params, headers=headers, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            return None
        return r.json()
    except (requests.RequestException, ValueError):
        return None


def _search_qid(name: str, lang: str = "fr") -> tuple[str, str, float] | None:
    """Action API wbsearchentities. Retourne (qid, label, score) ou None.

    Score :
    - 1.0 si label exact (insensible à la casse)
    - 0.7 sinon (premier résultat raisonnable)
    """
    data = _http_get_json(
        "https://www.wikidata.org/w/api.php",
        {
            "action": "wbsearchentities",
            "format": "json",
            "search": name,
            "language": lang,
            "type": "item",
            "limit": 5,
        },
    )
    if not data:
        return None
    results = data.get("search", []) or []
    if not results:
        return None
    first = results[0]
    qid = first.get("id")
    label = first.get("label") or ""
    if not qid:
        return None
    score = 1.0 if label.lower() == name.lower() else 0.7
    return qid, label, score


def _get_wiki_summary(title: str, lang: str = "fr") -> dict | None:
    """Wikipedia REST v1 page/summary. Filtre les pages d'homonymie."""
    encoded = quote(title.replace(" ", "_"), safe="")
    data = _http_get_json(
        f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{encoded}"
    )
    if not data:
        return None
    if data.get("type") == "disambiguation":
        return None
    return data


def _get_statements(qid: str) -> dict:
    """Wikidata REST v1 — statements bruts d'un item.

    Retourne un dict {propertyId: [statement, ...]} où chaque statement contient
    `value.content` qui est soit un string (QID, date sérialisée) soit un dict.
    """
    data = _http_get_json(
        f"https://www.wikidata.org/w/rest.php/wikibase/v1/entities/items/{qid}/statements"
    )
    return data or {}


def _parse_wikidata_time(raw: dict | str | None) -> date | None:
    """'+1985-04-22T00:00:00Z' → date(1985, 4, 22). Tolère les dates partielles."""
    if isinstance(raw, dict):
        time_str = raw.get("time", "")
    elif isinstance(raw, str):
        time_str = raw
    else:
        return None
    m = WIKIDATA_TIME_RX.match(time_str)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 1 or mo < 1 or d < 1:
        return None
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def _statement_qids(statements: dict, prop: str) -> list[str]:
    """Extrait les QIDs cités par une propriété (ex. P106 occupation)."""
    out: list[str] = []
    for s in statements.get(prop, []) or []:
        value = (s.get("value") or {}).get("content")
        if isinstance(value, str) and value.startswith("Q"):
            out.append(value)
    return out


def _statement_times(statements: dict, prop: str) -> list[date]:
    """Extrait les dates non-nulles d'une propriété date (ex. P569)."""
    out: list[date] = []
    for s in statements.get(prop, []) or []:
        d = _parse_wikidata_time((s.get("value") or {}).get("content"))
        if d:
            out.append(d)
    return out


def _get_wikidata_label(qid: str, lang: str = "fr") -> str | None:
    """Récupère le label Wikidata principal d'un QID.

    Utilisé quand `enrich_entity` doit calculer un `wikidata_score` pour
    un QID préfixé manuellement (cas démerge ou backfill humain).
    """
    labels = _resolve_labels([qid], lang=lang)
    return labels.get(qid)


def _resolve_labels(qids: list[str], lang: str = "fr") -> dict[str, str]:
    """Résout les labels FR (fallback EN) pour une liste de QIDs en batch."""
    if not qids:
        return {}
    out: dict[str, str] = {}
    # Action API wbgetentities accepte 50 IDs par appel
    for i in range(0, len(qids), 50):
        chunk = qids[i : i + 50]
        data = _http_get_json(
            "https://www.wikidata.org/w/api.php",
            {
                "action": "wbgetentities",
                "format": "json",
                "ids": "|".join(chunk),
                "props": "labels",
                "languages": f"{lang}|en",
            },
        )
        if not data:
            continue
        for qid, ent in (data.get("entities") or {}).items():
            labels = ent.get("labels", {}) or {}
            label = (labels.get(lang) or {}).get("value") or (
                labels.get("en") or {}
            ).get("value")
            if label:
                out[qid] = label
    return out


def enrich_entity(entity_id: int) -> str:
    """Enrichit une entité. Retourne le statut écrit ('done', 'not_found', 'failed').

    Idempotent : peut être ré-appelé. Si le QID est déjà connu, on resaute la
    recherche et on rafraîchit juste le summary.
    """
    db = SessionLocal()
    try:
        entity = db.get(Entity, entity_id)
        if entity is None:
            return "failed"

        # Format canonique "Last, First" → forme naturelle "First Last"
        if "," in entity.name:
            parts = [p.strip() for p in entity.name.split(",", 1)]
            search_name = f"{parts[1]} {parts[0]}" if len(parts) == 2 else entity.name
        else:
            search_name = entity.name

        qid_label = None
        if not entity.wikidata_qid:
            for lang in LANG_CHAIN:
                hit = _search_qid(search_name, lang=lang)
                if hit:
                    qid, label, score = hit
                    entity.wikidata_qid = qid
                    entity.wikidata_score = score
                    qid_label = label
                    break

        if not entity.wikidata_qid:
            entity.wikidata_status = "not_found"
            entity.wikidata_synced_at = datetime.utcnow()
            db.commit()
            return "not_found"

        # Backfill `wikidata_score` pour les QID préfixés sans score (cas
        # démerge humain ou import depuis snapshot). Sans ça, le garde-fou
        # `entity_merge._check_auto_merge_safe` refuse ces entités même
        # quand elles sont légitimes (cf. effet de bord observé après la
        # restauration de l'incident 2026-05-11).
        if entity.wikidata_score is None:
            for lang in LANG_CHAIN:
                label = _get_wikidata_label(entity.wikidata_qid, lang=lang)
                if label:
                    entity.wikidata_score = (
                        1.0 if label.lower() == search_name.lower() else 0.7
                    )
                    qid_label = label
                    break

        # **Garde-fou type=PERSON** (rejette les faux PERSON WUDD).
        # On vérifie P31 (`instance of`) AVANT de continuer l'enrichissement.
        # Si l'entité Wikidata n'est pas qualifiée d'être humain (Q5), c'est
        # un faux positif côté NER WUDD ("Apple Park", "OpenAI", "Mar-a-Lago"
        # taggés PERSON par erreur). On marque pour purge — l'enrichissement
        # complet (bio, summary) est inutile sur une entité qui va disparaître.
        statements = _get_statements(entity.wikidata_qid)
        instance_qids = _statement_qids(statements, PROP_INSTANCE_OF)
        if instance_qids and not (set(instance_qids) & PERSON_QIDS):
            log.info(
                "not_person : %s (QID=%s, instance_of=%s)",
                entity.name,
                entity.wikidata_qid,
                instance_qids,
            )
            entity.wikidata_status = "not_person"
            entity.wikidata_synced_at = datetime.utcnow()
            db.commit()
            return "not_person"

        # Cherche Wikipedia avec le label Wikidata d'abord, fallback search_name
        title_candidates = [c for c in (qid_label, search_name) if c]
        for title in title_candidates:
            for lang in LANG_CHAIN:
                summary = _get_wiki_summary(title, lang=lang)
                if summary:
                    entity.wiki_summary = summary.get("extract")
                    entity.wiki_url = (
                        (summary.get("content_urls") or {})
                        .get("desktop", {})
                        .get("page")
                    )
                    thumb = summary.get("thumbnail") or {}
                    entity.wiki_thumbnail_url = thumb.get("source")
                    break
            if entity.wiki_summary:
                break

        # 3. Statements biographiques (spec §9.3)
        # `statements` est déjà chargé ci-dessus (étape de validation P31).
        if statements:
            birth_dates = _statement_times(statements, PROP_DATE_OF_BIRTH)
            death_dates = _statement_times(statements, PROP_DATE_OF_DEATH)
            entity.birth_date = birth_dates[0] if birth_dates else None
            entity.death_date = death_dates[0] if death_dates else None

            birth_place_qids = _statement_qids(statements, PROP_PLACE_OF_BIRTH)
            death_place_qids = _statement_qids(statements, PROP_PLACE_OF_DEATH)
            nationality_qids = _statement_qids(statements, PROP_COUNTRY_CITIZENSHIP)
            occupation_qids = _statement_qids(statements, PROP_OCCUPATION)
            employer_qids = _statement_qids(statements, PROP_EMPLOYER)

            all_qids = list(
                dict.fromkeys(  # déduplique en préservant l'ordre
                    birth_place_qids
                    + death_place_qids
                    + nationality_qids
                    + occupation_qids
                    + employer_qids
                )
            )
            labels = _resolve_labels(all_qids, lang="fr")

            entity.birth_place = labels.get(birth_place_qids[0]) if birth_place_qids else None
            entity.death_place = labels.get(death_place_qids[0]) if death_place_qids else None
            entity.nationalities = (
                "|".join(filter(None, (labels.get(q) for q in nationality_qids)))
                or None
            )
            entity.occupations = (
                "|".join(filter(None, (labels.get(q) for q in occupation_qids)))
                or None
            )
            entity.employer = labels.get(employer_qids[0]) if employer_qids else None

        entity.wikidata_status = "done"
        entity.wikidata_synced_at = datetime.utcnow()
        db.commit()
        return "done"
    finally:
        db.close()

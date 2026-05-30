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
PROP_COORDINATE = "P625"  # coordonnée géographique (sur l'item lieu, pas la personne)

# Enrichissement factuel étendu (v027, bloc A — intérêt légitime art. 6.1.f)
PROP_GENDER = "P21"
PROP_POLITICAL_PARTY = "P102"
PROP_POSITION_HELD = "P39"
PROP_AWARD = "P166"
PROP_NOTABLE_WORK = "P800"

# Attributs sensibles RGPD art. 9 (v027, bloc B — décision propriétaire
# 2026-05-30, cf. database.py / migration v027). Issus de Wikidata public.
PROP_ETHNIC_GROUP = "P172"
PROP_RELIGION = "P140"
PROP_SEXUAL_ORIENTATION = "P91"
PROP_MEDICAL_CONDITION = "P1050"

# Centroïdes (lat, lng) par label FR de pays — repli quand le lieu de naissance
# précis (P625 du P19) est inconnu. Indexé sur les labels Wikidata FR stockés
# dans `entities.nationalities` (P27). Couvre les pays courants du corpus presse ;
# un pays absent ici n'est simplement pas géolocalisé via nationalité (la personne
# peut quand même l'être via sa ville de naissance). Valeurs = centre géographique
# approximatif, suffisant pour un point sur une carte du monde.
COUNTRY_CENTROIDS: dict[str, tuple[float, float]] = {
    "États-Unis": (39.8, -98.6),
    "France": (46.6, 2.4),
    "Royaume-Uni": (54.0, -2.0),
    "Allemagne": (51.2, 10.4),
    "Suisse": (46.8, 8.2),
    "Italie": (42.8, 12.6),
    "Espagne": (40.2, -3.7),
    "Canada": (56.1, -106.3),
    "Chine": (35.9, 104.2),
    "Japon": (36.2, 138.3),
    "Russie": (61.5, 105.3),
    "Inde": (22.6, 78.9),
    "Brésil": (-14.2, -51.9),
    "Australie": (-25.3, 133.8),
    "Belgique": (50.5, 4.5),
    "Pays-Bas": (52.1, 5.3),
    "Suède": (60.1, 18.6),
    "Norvège": (60.5, 8.5),
    "Danemark": (56.3, 9.5),
    "Autriche": (47.5, 14.6),
    "Irlande": (53.4, -8.2),
    "Portugal": (39.4, -8.2),
    "Grèce": (39.1, 21.8),
    "Pologne": (51.9, 19.1),
    "Mexique": (23.6, -102.6),
    "Argentine": (-38.4, -63.6),
    "Israël": (31.0, 34.9),
    "Afrique du Sud": (-30.6, 22.9),
    "Corée du Sud": (35.9, 127.8),
    "Turquie": (39.0, 35.2),
    "Égypte": (26.8, 30.8),
    "Arabie saoudite": (23.9, 45.1),
    "Émirats arabes unis": (23.4, 53.8),
    "Nouvelle-Zélande": (-40.9, 174.9),
    "Finlande": (61.9, 25.7),
    "Ukraine": (48.4, 31.2),
    "Hongrie": (47.2, 19.5),
    "République tchèque": (49.8, 15.5),
    "Roumanie": (45.9, 25.0),
    "Singapour": (1.35, 103.8),
    "Iran": (32.4, 53.7),
    "Pakistan": (30.4, 69.3),
    "Indonésie": (-0.8, 113.9),
    "Thaïlande": (15.9, 100.99),
    "Viêt Nam": (14.1, 108.3),
    "Viêt Nam du Sud": (14.1, 108.3),
    "Nigeria": (9.1, 8.7),
    "Kenya": (-0.02, 37.9),
    "Maroc": (31.8, -7.1),
    "Chili": (-35.7, -71.5),
    "Colombie": (4.6, -74.3),
    "Pérou": (-9.2, -75.0),
    "Venezuela": (6.4, -66.6),
    "Cuba": (21.5, -77.8),
    "Luxembourg": (49.8, 6.1),
    "Croatie": (45.1, 15.2),
    "Serbie": (44.0, 21.0),
    "Slovaquie": (48.7, 19.7),
    "Slovénie": (46.2, 15.0),
    "Bulgarie": (42.7, 25.5),
    "Liban": (33.9, 35.9),
    "Taïwan": (23.7, 121.0),
    "République de Chine (Taïwan)": (23.7, 121.0),
    "Philippines": (12.9, 121.8),
    "Malaisie": (4.2, 101.98),
    "Écosse": (56.5, -4.2),
    "Pays de Galles": (52.3, -3.8),
    "Angleterre": (52.4, -1.5),
    "Tchécoslovaquie": (49.8, 15.5),
    "Union soviétique": (61.5, 105.3),
    "Empire russe": (61.5, 105.3),
    "Royaume d'Italie": (42.8, 12.6),
    "Allemagne de l'Ouest": (51.2, 10.4),
    "République fédérale d'Allemagne": (51.2, 10.4),
    # ── Extension de couverture (réduit les entités non placées) ──
    "Tchéquie": (49.8, 15.5),
    "Birmanie": (21.9, 95.96),
    "Myanmar": (21.9, 95.96),
    "Corée du Nord": (40.3, 127.5),
    "Bangladesh": (23.7, 90.4),
    "Sri Lanka": (7.9, 80.8),
    "Népal": (28.4, 84.1),
    "Afghanistan": (33.9, 67.7),
    "Irak": (33.2, 43.7),
    "Syrie": (34.8, 38.997),
    "Jordanie": (30.6, 36.2),
    "Qatar": (25.4, 51.2),
    "Koweït": (29.3, 47.5),
    "Bahreïn": (26.1, 50.6),
    "Oman": (21.5, 55.9),
    "Yémen": (15.6, 48.0),
    "Algérie": (28.0, 1.7),
    "Tunisie": (33.9, 9.6),
    "Libye": (26.3, 17.2),
    "Soudan": (12.9, 30.2),
    "Soudan du Sud": (7.0, 30.0),
    "Éthiopie": (9.1, 40.5),
    "Ghana": (7.9, -1.0),
    "Côte d'Ivoire": (7.5, -5.5),
    "Sénégal": (14.5, -14.5),
    "Cameroun": (5.7, 12.7),
    "Tanzanie": (-6.4, 34.9),
    "Ouganda": (1.4, 32.3),
    "Zimbabwe": (-19.0, 29.2),
    "Zambie": (-13.1, 27.8),
    "Angola": (-11.2, 17.9),
    "Mozambique": (-18.7, 35.5),
    "Rwanda": (-1.9, 29.9),
    "Mali": (17.6, -4.0),
    "Madagascar": (-18.8, 46.9),
    "République démocratique du Congo": (-4.0, 21.8),
    "Équateur": (-1.8, -78.2),
    "Bolivie": (-16.3, -63.6),
    "Paraguay": (-23.4, -58.4),
    "Uruguay": (-32.5, -55.8),
    "Guatemala": (15.8, -90.2),
    "Costa Rica": (9.7, -83.8),
    "Panama": (8.5, -80.8),
    "République dominicaine": (18.7, -70.2),
    "Jamaïque": (18.1, -77.3),
    "Haïti": (19.1, -72.3),
    "Honduras": (15.2, -86.2),
    "Salvador": (13.8, -88.9),
    "Nicaragua": (12.9, -85.2),
    "Islande": (64.96, -19.0),
    "Estonie": (58.6, 25.0),
    "Lettonie": (56.9, 24.6),
    "Lituanie": (55.2, 23.9),
    "Biélorussie": (53.7, 27.95),
    "Moldavie": (47.4, 28.4),
    "Géorgie": (42.3, 43.4),
    "Arménie": (40.1, 45.0),
    "Azerbaïdjan": (40.1, 47.6),
    "Kazakhstan": (48.0, 66.9),
    "Ouzbékistan": (41.4, 64.6),
    "Mongolie": (46.9, 103.8),
    "Cambodge": (12.6, 104.99),
    "Laos": (19.9, 102.5),
    "Brunei": (4.5, 114.7),
    "Chypre": (35.1, 33.4),
    "Malte": (35.9, 14.4),
    "Monaco": (43.7, 7.4),
    "Liechtenstein": (47.2, 9.6),
    "Andorre": (42.5, 1.6),
    "Saint-Marin": (43.9, 12.5),
    "Macédoine du Nord": (41.6, 21.7),
    "Albanie": (41.2, 20.2),
    "Bosnie-Herzégovine": (43.9, 17.7),
    "Monténégro": (42.7, 19.4),
    "Kosovo": (42.6, 20.9),
    "Empire ottoman": (39.0, 35.2),
    "Yougoslavie": (44.0, 21.0),
}

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


def _statement_coordinate(statements: dict, prop: str) -> tuple[float, float] | None:
    """Extrait la 1re coordonnée (lat, lng) d'une propriété P625.

    Le `value.content` d'un statement P625 est un dict
    `{latitude, longitude, precision, globe}`. On ignore les coordonnées hors
    Terre (globe ≠ Q2) — rare mais Wikidata référence aussi des lieux lunaires.
    """
    for s in statements.get(prop, []) or []:
        content = (s.get("value") or {}).get("content")
        if not isinstance(content, dict):
            continue
        globe = content.get("globe") or ""
        if globe and not globe.endswith("Q2"):
            continue
        lat, lng = content.get("latitude"), content.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            return (float(lat), float(lng))
    return None


def _resolve_entity_geo(entity: Entity, statements: dict) -> None:
    """Renseigne `entity.latitude/longitude/geo_source` (vue carte, v026).

    Priorité : coordonnées précises de la ville de naissance (P19 → P625), sinon
    repli sur le centroïde du pays de nationalité (P27, label déjà résolu dans
    `entity.nationalities`). Aucun des deux → champs laissés NULL (entité non
    affichée sur la carte). `statements` = statements de la *personne* déjà
    chargés ; la résolution de la ville déclenche un appel réseau supplémentaire
    (statements du lieu).
    """
    entity.latitude = None
    entity.longitude = None
    entity.geo_source = None

    birth_place_qids = _statement_qids(statements, PROP_PLACE_OF_BIRTH)
    if birth_place_qids:
        coord = _statement_coordinate(
            _get_statements(birth_place_qids[0]), PROP_COORDINATE
        )
        if coord:
            entity.latitude, entity.longitude = coord
            entity.geo_source = "city"
            return

    for label in (entity.nationalities or "").split("|"):
        centroid = COUNTRY_CENTROIDS.get(label.strip())
        if centroid:
            entity.latitude, entity.longitude = centroid
            entity.geo_source = "country"
            return


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


def _pipe_join(qids: list[str], labels: dict[str, str]) -> str | None:
    """Joint les labels résolus d'une liste de QIDs en chaîne pipe-separated.

    Préserve l'ordre Wikidata, déduplique, ignore les QIDs non résolus.
    Retourne None si rien (cohérent avec le stockage NULL en DB).
    """
    seen: list[str] = []
    for q in qids:
        label = labels.get(q)
        if label and label not in seen:
            seen.append(label)
    return "|".join(seen) or None


# Propriétés à valeurs multiples → colonnes pipe-separated. (entity_attr, prop)
_MULTI_VALUE_PROPS = (
    ("political_party", PROP_POLITICAL_PARTY),
    ("positions_held", PROP_POSITION_HELD),
    ("awards", PROP_AWARD),
    ("notable_works", PROP_NOTABLE_WORK),
    ("ethnic_group", PROP_ETHNIC_GROUP),
    ("religion", PROP_RELIGION),
    ("medical_condition", PROP_MEDICAL_CONDITION),
)
# Propriétés à valeur unique → premier label résolu. (entity_attr, prop)
_SINGLE_VALUE_PROPS = (
    ("gender", PROP_GENDER),
    ("sexual_orientation", PROP_SEXUAL_ORIENTATION),
)


def _extended_qids(statements: dict) -> dict[str, list[str]]:
    """QIDs cités par chaque propriété étendue (v027), indexés par attribut."""
    out: dict[str, list[str]] = {}
    for attr, prop in (*_MULTI_VALUE_PROPS, *_SINGLE_VALUE_PROPS):
        out[attr] = _statement_qids(statements, prop)
    return out


def _apply_extended_enrichment(
    entity: Entity, ext_qids: dict[str, list[str]], labels: dict[str, str]
) -> None:
    """Écrit les colonnes v027 (blocs A + B) sur l'entité depuis les labels résolus.

    Réutilisable par `enrich_entity` (chemin nominal) et `backfill_enrichment`
    (rattrapage défensif sans re-recherche ni fusion).
    """
    for attr, _prop in _MULTI_VALUE_PROPS:
        setattr(entity, attr, _pipe_join(ext_qids.get(attr, []), labels))
    for attr, _prop in _SINGLE_VALUE_PROPS:
        qids = ext_qids.get(attr, [])
        setattr(entity, attr, labels.get(qids[0]) if qids else None)


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
            # v027 : propriétés étendues (blocs A + B). QIDs résolus dans le
            # même batch de labels que la bio historique (1 appel réseau).
            ext_qids = _extended_qids(statements)

            all_qids = list(
                dict.fromkeys(  # déduplique en préservant l'ordre
                    birth_place_qids
                    + death_place_qids
                    + nationality_qids
                    + occupation_qids
                    + employer_qids
                    + [q for qids in ext_qids.values() for q in qids]
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

            # v027 : champs étendus (genre, parti, fonctions, prix, œuvres +
            # attributs sensibles art. 9). Écrits depuis le même batch labels.
            _apply_extended_enrichment(entity, ext_qids, labels)

            # Position géographique pour la vue carte (v026). Après le bloc bio
            # car `entity.nationalities` doit être renseigné pour le repli pays.
            _resolve_entity_geo(entity, statements)

        entity.wikidata_status = "done"
        entity.wikidata_synced_at = datetime.utcnow()
        db.commit()
        return "done"
    finally:
        db.close()


def backfill_coordinates(rate_limit: float = 1.0) -> dict:
    """Renseigne latitude/longitude/geo_source pour les entités déjà enrichies.

    Pour l'historique pré-v026 : itère les entités `wikidata_status='done'` sans
    coordonnée, rejoue `_resolve_entity_geo` (re-fetch des statements via le QID
    déjà connu — pas de re-recherche, pas de fusion, défensif vis-à-vis du
    garde-fou auto-merge gelé). Rate-limité (politesse Wikidata).
    """
    db = SessionLocal()
    try:
        rows = (
            db.query(Entity)
            .filter(
                Entity.wikidata_status == "done",
                Entity.wikidata_qid.isnot(None),
                Entity.latitude.is_(None),
            )
            .all()
        )
        total = len(rows)
        by_city = by_country = 0
        log.info("backfill-coordinates : %d entités à traiter", total)
        for i, entity in enumerate(rows, 1):
            statements = _get_statements(entity.wikidata_qid)
            _resolve_entity_geo(entity, statements)
            if entity.geo_source == "city":
                by_city += 1
            elif entity.geo_source == "country":
                by_country += 1
            db.commit()
            if i % 25 == 0 or i == total:
                log.info(
                    "  %d/%d (ville=%d, pays=%d)", i, total, by_city, by_country
                )
            time.sleep(rate_limit)
        result = {
            "total": total,
            "city": by_city,
            "country": by_country,
            "unresolved": total - by_city - by_country,
        }
        log.info("backfill-coordinates terminé : %s", result)
        return result
    finally:
        db.close()


def backfill_enrichment(rate_limit: float = 1.0, limit: int | None = None) -> dict:
    """Renseigne les colonnes v027 (blocs A + B) sur les entités déjà enrichies.

    Pour l'historique pré-v027 : itère les entités `wikidata_status='done'` avec
    un QID connu et dont les nouveaux champs sont encore vides (on teste `gender`
    comme sentinelle), re-fetch les statements via le QID **déjà connu** puis
    rejoue uniquement la résolution + l'écriture des nouvelles colonnes.

    Défensif comme `backfill_coordinates` : aucune re-recherche de QID, aucune
    fusion — le garde-fou auto-merge gelé (incident 2026-05-11) n'est pas touché.
    Rate-limité (politesse Wikidata).
    """
    db = SessionLocal()
    try:
        q = db.query(Entity).filter(
            Entity.wikidata_status == "done",
            Entity.wikidata_qid.isnot(None),
            Entity.gender.is_(None),
        )
        if limit:
            q = q.limit(limit)
        rows = q.all()
        total = len(rows)
        filled = 0
        log.info("backfill-enrichment : %d entités à traiter", total)
        for i, entity in enumerate(rows, 1):
            statements = _get_statements(entity.wikidata_qid)
            if statements:
                ext_qids = _extended_qids(statements)
                flat = [q for qids in ext_qids.values() for q in qids]
                labels = _resolve_labels(list(dict.fromkeys(flat)), lang="fr")
                _apply_extended_enrichment(entity, ext_qids, labels)
                if any(
                    getattr(entity, attr)
                    for attr, _ in (*_MULTI_VALUE_PROPS, *_SINGLE_VALUE_PROPS)
                ):
                    filled += 1
            db.commit()
            if i % 25 == 0 or i == total:
                log.info("  %d/%d (renseignées=%d)", i, total, filled)
            time.sleep(rate_limit)
        result = {"total": total, "filled": filled}
        log.info("backfill-enrichment terminé : %s", result)
        return result
    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Outils Wikidata FACE.ai")
    parser.add_argument(
        "--backfill-coordinates",
        action="store_true",
        help="Renseigne lat/lng/geo_source des entités enrichies sans coordonnée (v026)",
    )
    parser.add_argument(
        "--backfill-enrichment",
        action="store_true",
        help="Renseigne les champs v027 (genre, parti, prix, attributs sensibles…) "
        "des entités déjà enrichies, sans re-recherche ni fusion",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limite le nombre d'entités traitées (défaut : toutes)",
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=1.0,
        help="Délai inter-requête en secondes (défaut 1.0)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.backfill_coordinates:
        backfill_coordinates(rate_limit=args.rate_limit)
    elif args.backfill_enrichment:
        backfill_enrichment(rate_limit=args.rate_limit, limit=args.limit)
    else:
        parser.print_help()

#!/usr/bin/env python3
"""P1A — OpenSanctions (PEP, sanctions, criminels). Open data CC BY-NC.

Télécharge le dataset fusionné `default` (FtM JSON Lines), indexe les entités
de schéma Person par nom normalisé, puis croise avec les entités FACE.ai
(personnes publiques déjà dans le corpus). Pose `sanctions_status`
('sanctioned'/'pep'/'clean'/'unknown') + `sanctions_detail` JSON.

PÉRIMÈTRE : uniquement des PERSONNES PUBLIQUES du corpus, données OPEN SOURCE
reprises telles quelles (aucune inférence). Catégorie RGPD art. 9/10 — cf.
CLAUDE.md (décision périmètre 2026-06-05). Usage interne LAN.

GARDE-FOU ANTI-HOMONYMIE : le match par nom seul confond les homonymes
(Tim Burton réalisateur vs un PEP du même nom). Après le match par nom, on
**corrobore** avec l'année de naissance (±`OSINT_SANCTIONS_BIRTHYEAR_TOLERANCE`)
et/ou le pays de l'entité (déjà enrichis via Wikidata) :
- conflit explicite de naissance OU de pays → match **rejeté** (homonyme) ;
- corroboré (naissance ou pays concordant) → écrit, `verification` = 'birthdate'/'country' ;
- aucune donnée pour corroborer → `verification` = 'unverified' (écrit mais
  signalé), ou ignoré si `FACE_AI_SANCTIONS_REQUIRE_CORROBORATION=true`.

Matching : nom normalisé exact (rapide, O(1)) puis repli rapidfuzz au seuil
config. Idempotent : ré-écrit `sanctions_status`/`detail` à chaque passage.

Usage :
    docker compose exec api python scripts/ingest_opensanctions.py
    docker compose exec api python scripts/ingest_opensanctions.py --file /data/os_default.json
    docker compose exec api python scripts/ingest_opensanctions.py --strict  # ignore les non corroborés

Cron (hebdomadaire) :
    0 2 * * 1  docker compose exec -T api python scripts/ingest_opensanctions.py
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (  # noqa: E402
    OPENSANCTIONS_URL,
    OSINT_FUZZY_THRESHOLD,
    OSINT_SANCTIONS_BIRTHYEAR_TOLERANCE,
    OSINT_SANCTIONS_MAX_CANDIDATES,
    OSINT_SANCTIONS_REQUIRE_CORROBORATION,
)
from database import SessionLocal  # noqa: E402
from osint_common import (  # noqa: E402
    get_logger,
    iter_corpus_persons,
    make_session,
    normalize_person_name,
)

log = get_logger("opensanctions")

SANCTION_TOPICS = {"sanction", "sanction.linked", "crime", "debarment", "wanted"}
PEP_TOPICS = {"role.pep", "role.rca", "poi"}


def _status_from_topics(topics: list[str]) -> str:
    tset = set(topics or [])
    if tset & SANCTION_TOPICS:
        return "sanctioned"
    if any(t.startswith("role.pep") or t in PEP_TOPICS for t in tset):
        return "pep"
    return "pep"  # présent dans `default` sans topic clair → PEP par défaut prudent


def _parse_birth_years(values) -> frozenset:
    """Années (int) extraites des valeurs FtM birthDate (ex. '1958-08-25')."""
    out = set()
    for v in values or []:
        m = re.match(r"(\d{4})", str(v))
        if m:
            out.add(int(m.group(1)))
    return frozenset(out)


def _parse_countries(props: dict) -> frozenset:
    """Codes pays ISO alpha-2 (majuscule) depuis country + nationality FtM."""
    out = set()
    for key in ("country", "nationality"):
        for v in props.get(key) or []:
            s = str(v).strip().upper()
            if len(s) == 2 and s.isalpha():
                out.add(s)
    return frozenset(out)


# ── Garde-fou : corroboration biographique ──────────────────────────────────

def _classify(cand: dict, ent_year, ent_country, tol: int):
    """Niveau de corroboration d'un candidat vs l'entité.

    Retourne (rang, verification) ou None si **conflit explicite** (homonyme) :
    - 2 'birthdate' : années de naissance concordantes (±tol),
    - 1 'country'   : pays concordant (quand pas de naissance comparable),
    - 0 'unverified': aucune donnée des deux côtés pour trancher.
    `None` : la naissance OU le pays se contredisent → ce candidat est écarté.
    """
    if ent_year and cand["birth_years"]:
        if any(abs(ent_year - y) <= tol for y in cand["birth_years"]):
            return 2, "birthdate"
        return None  # conflit de naissance → homonyme
    if ent_country and cand["countries"]:
        if ent_country in cand["countries"]:
            return 1, "country"
        return None  # conflit de pays
    return 0, "unverified"


def _select_candidate(cands, ent_year, ent_country, tol, require_corrob):
    """Choisit le meilleur candidat corroboré. Retourne (cand|None, verification).

    verification ∈ {'birthdate','country','unverified','homonym_rejected',
    'unverified_skipped'}.
    """
    best, best_rank, best_ver = None, -1, None
    saw_conflict = False
    for c in cands:
        res = _classify(c, ent_year, ent_country, tol)
        if res is None:
            saw_conflict = True
            continue
        rank, ver = res
        if rank > best_rank:
            best, best_rank, best_ver = c, rank, ver
    if best is None:
        return None, ("homonym_rejected" if saw_conflict else "no_candidate")
    if best_ver == "unverified" and require_corrob:
        return None, "unverified_skipped"
    return best, best_ver


def _iter_lines(args, session):
    if args.file:
        with open(args.file, "r", encoding="utf-8") as fh:
            for line in fh:
                yield line
    else:
        log.info("Téléchargement streaming %s …", OPENSANCTIONS_URL)
        with session.get(OPENSANCTIONS_URL, stream=True, timeout=120) as r:
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if line:
                    yield line


def _build_index(args, session) -> dict[str, list[dict]]:
    """normalized_name → liste de candidats (schéma Person), avec naissance/pays."""
    index: dict[str, list[dict]] = {}
    count = 0
    for line in _iter_lines(args, session):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("schema") != "Person":
            continue
        props = rec.get("properties") or {}
        names = list(props.get("name") or []) + list(props.get("alias") or [])
        if not names:
            continue
        topics = props.get("topics") or []
        cand = {
            "status": _status_from_topics(topics),
            "datasets": rec.get("datasets") or [],
            "topics": topics,
            "caption": rec.get("caption") or names[0],
            "birth_years": _parse_birth_years(props.get("birthDate")),
            "countries": _parse_countries(props),
        }
        for nm in names:
            key = normalize_person_name(nm)
            if not key:
                continue
            lst = index.setdefault(key, [])
            if len(lst) < OSINT_SANCTIONS_MAX_CANDIDATES:
                lst.append(cand)
        count += 1
        if count % 50000 == 0:
            log.info("  %d persons indexés (%d clés)", count, len(index))
    log.info("Index : %d persons, %d clés normalisées.", count, len(index))
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", help="dataset FtM JSON Lines local (sinon download)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-fuzzy", action="store_true", help="exact match seulement")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="ignore les matches non corroborés (sinon écrits comme 'unverified')",
    )
    args = parser.parse_args()
    require_corrob = OSINT_SANCTIONS_REQUIRE_CORROBORATION or args.strict
    tol = OSINT_SANCTIONS_BIRTHYEAR_TOLERANCE

    session = make_session()
    index = _build_index(args, session)
    if not index:
        log.error("Index OpenSanctions vide — abandon (corpus non modifié).")
        return
    keys = list(index)

    try:
        from rapidfuzz import process, fuzz
        has_fuzzy = not args.no_fuzzy
    except ImportError:  # pragma: no cover
        has_fuzzy = False

    db = SessionLocal()
    now = datetime.utcnow()
    counts = {"sanctioned": 0, "pep": 0, "clean": 0}
    guard = {"homonym_rejected": 0, "unverified_skipped": 0, "unverified": 0}
    try:
        persons = list(iter_corpus_persons(db))
        if args.limit:
            persons = persons[: args.limit]
        for entity in persons:
            qnorm = normalize_person_name(entity.name)
            cands = index.get(qnorm)
            name_score = 100.0 if cands else 0.0
            if cands is None and has_fuzzy and qnorm:
                m = process.extractOne(
                    qnorm, keys, scorer=fuzz.token_sort_ratio,
                    score_cutoff=OSINT_FUZZY_THRESHOLD,
                )
                if m:
                    cands = index[m[0]]
                    name_score = m[1]

            ent_year = entity.birth_date.year if entity.birth_date else None
            ent_country = (entity.country_code or "").upper() or None

            status = "clean"
            detail = {"datasets": [], "topics": [], "last_checked": now.isoformat()}
            if cands:
                chosen, verification = _select_candidate(
                    cands, ent_year, ent_country, tol, require_corrob
                )
                if chosen is not None:
                    status = chosen["status"]
                    detail = {
                        "datasets": chosen["datasets"],
                        "topics": chosen["topics"],
                        "caption": chosen["caption"],
                        "name_score": name_score,
                        "verification": verification,
                        "last_checked": now.isoformat(),
                    }
                    counts[status] = counts.get(status, 0) + 1
                    if verification == "unverified":
                        guard["unverified"] += 1
                    log.info(
                        "match: %s → %s (%s, nom %.0f) %s",
                        entity.name, status, verification, name_score, chosen["topics"],
                    )
                else:
                    # match par nom mais rejeté par le garde-fou → clean + trace
                    guard[verification] = guard.get(verification, 0) + 1
                    counts["clean"] += 1
                    detail["rejected"] = verification
                    log.info(
                        "rejet garde-fou: %s (%s, naissance=%s pays=%s)",
                        entity.name, verification, ent_year, ent_country,
                    )
            else:
                counts["clean"] += 1

            entity.sanctions_status = status
            entity.sanctions_detail = json.dumps(detail, ensure_ascii=False)
            entity.sanctions_synced_at = now
            db.commit()
        log.info("Terminé : statuts %s | garde-fou %s", counts, guard)
    finally:
        db.close()


if __name__ == "__main__":
    main()

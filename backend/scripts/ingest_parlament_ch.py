#!/usr/bin/env python3
"""P1C — Parlement suisse (parlament.ch), open government data.

Synchronise les parlementaires (Conseil national + Conseil des États) avec les
entités FACE.ai correspondantes : parti, canton, conseil, mandat actif. Pose
`is_swiss_parliament_member`, `parliament_ch_id`, `parliament_ch_data` (JSON), et
en repli `country_code='CH'` / `country_name='Suisse'`. Données OPEN SOURCE,
personnes publiques (élus). Matching par fuzzy nom (rapidfuzz, seuil config).

Idempotent : ré-exécutable, ré-écrit les mêmes champs. Photos officielles
ingérées via le pipeline standard si l'API expose une URL d'image.

Usage :
    docker compose exec api python scripts/ingest_parlament_ch.py
    docker compose exec api python scripts/ingest_parlament_ch.py --no-photos --limit 50

Cron (mensuel) :
    0 3 1 * *  docker compose exec -T api python scripts/ingest_parlament_ch.py
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import PARLAMENT_CH_BASE_URL, OSINT_FUZZY_THRESHOLD  # noqa: E402
from database import SessionLocal  # noqa: E402
from osint_common import (  # noqa: E402
    best_fuzzy_match,
    get_logger,
    ingest_external_image,
    iter_corpus_persons,
    make_session,
)

log = get_logger("parlament_ch")


def _odata_rows(session, entity_set: str, filter_str: str | None = None) -> list[dict]:
    """Récupère toutes les lignes d'un EntitySet OData (pagination nextLink).

    Le service parlament.ch est OData v3 (`d.results` + `d.__next`). Les lignes
    sont **dupliquées par langue** (DE/FR/IT/RM) → on filtre via `filter_str`
    (ex. `Language eq 'FR' and Active eq true`). On passe les paramètres en
    dict (requests gère l'URL-encoding) ; le `__next` est déjà une URL absolue.
    """
    params = {"$format": "json"}
    if filter_str:
        params["$filter"] = filter_str
    url = f"{PARLAMENT_CH_BASE_URL}/{entity_set}"
    rows: list[dict] = []
    seen = set()
    while url and url not in seen:
        seen.add(url)
        try:
            r = session.get(url, params=params if "?" not in url else None, timeout=40)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("OData %s : %s", url, exc)
            break
        if "value" in data:  # v4
            rows.extend(data.get("value") or [])
            url = data.get("@odata.nextLink")
        else:  # v3
            d = data.get("d") or {}
            rows.extend(d.get("results") or [])
            url = d.get("__next")  # URL absolue, paramètres déjà inclus
        log.info("  %s : %d lignes cumulées", entity_set, len(rows))
    return rows


def _full_name(row: dict) -> str:
    first = (row.get("FirstName") or row.get("GivenName") or "").strip()
    last = (row.get("LastName") or row.get("OfficialName") or row.get("FamilyName") or "").strip()
    return f"{first} {last}".strip()


def _council_label(row: dict) -> str | None:
    council = row.get("CouncilName") or row.get("CouncilAbbreviation")
    return council if isinstance(council, str) else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="limite d'entités traitées")
    parser.add_argument("--no-photos", action="store_true", help="ne pas ingérer les photos")
    parser.add_argument(
        "--entity-set",
        default="MemberCouncil",
        help="EntitySet OData à lire (MemberCouncil par défaut)",
    )
    parser.add_argument(
        "--all-members",
        action="store_true",
        help="inclure aussi les anciens membres (défaut : actifs seulement)",
    )
    args = parser.parse_args()

    session = make_session()
    # Filtre langue FR (sinon ×4 DE/FR/IT/RM) + membres actifs par défaut.
    filt = "Language eq 'FR'"
    if not args.all_members:
        filt += " and Active eq true"
    log.info("Lecture parlament.ch (%s, filtre: %s)…", args.entity_set, filt)
    councillors = _odata_rows(session, args.entity_set, filter_str=filt)
    if not councillors:
        log.error("Aucune donnée parlament.ch — abandon.")
        return
    log.info("%d parlementaires récupérés.", len(councillors))

    # Index nom normalisé → row (pour matching rapide via best_fuzzy_match)
    names = [_full_name(r) for r in councillors]

    db = SessionLocal()
    matched = photos = 0
    try:
        persons = list(iter_corpus_persons(db))
        if args.limit:
            persons = persons[: args.limit]
        for entity in persons:
            idx, score = best_fuzzy_match(
                entity.name, names, threshold=OSINT_FUZZY_THRESHOLD
            )
            if idx is None:
                continue
            row = councillors[idx]
            data = {
                "party": row.get("PartyName") or row.get("PartyAbbreviation"),
                "canton": row.get("CantonName") or row.get("CantonAbbreviation"),
                "council": _council_label(row),
                "active": bool(row.get("Active", True)),
                "role": row.get("ParlGroupFunctionText") or row.get("Function"),
                "parl_group": row.get("ParlGroupName"),
                "matched_name": names[idx],
                "match_score": score,
            }
            entity.parliament_ch_data = json.dumps(data, ensure_ascii=False)
            entity.is_swiss_parliament_member = True
            pid = row.get("PersonNumber") or row.get("ID")
            if isinstance(pid, int):
                entity.parliament_ch_id = pid
            # Repli pays (l'API connaît le canton → CH)
            if not entity.country_code:
                entity.country_code = "CH"
                entity.country_name = "Suisse"
            db.commit()
            matched += 1
            log.info("match: %s ↔ %s (%.0f) parti=%s canton=%s",
                     entity.name, names[idx], score, data["party"], data["canton"])

            if not args.no_photos:
                photo_url = (
                    row.get("PictureUrl") or row.get("Picture") or row.get("ImageUrl")
                )
                if isinstance(photo_url, str) and photo_url.startswith("http"):
                    res = ingest_external_image(
                        entity.id,
                        photo_url,
                        source_provider="parlament_ch",
                        caption=f"Photo officielle parlament.ch — {entity.name}",
                        copyright_text="Services du Parlement suisse (open data)",
                        session=session,
                    )
                    if res.get("status") == "ok":
                        photos += 1
        log.info(
            "Terminé : %d/%d entités matchées, %d photos ingérées.",
            matched,
            len(persons),
            photos,
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()

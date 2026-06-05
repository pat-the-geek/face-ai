#!/usr/bin/env python3
"""P3A — GLEIF : organisations légales liées. API REST v1 publique (open data).

Recherche le nom de chaque entité FACE.ai dans les LEI records GLEIF et stocke
les correspondances (LEI, legalName, pays, statut) dans `gleif_data` JSON.

⚠ Limite assumée : GLEIF est **centré organisation** — il n'expose pas de
relation « personne → mandat ». Une recherche par nom de personne ne matche donc
que si une entité légale porte ce nom (homonyme « John Smith Ltd ») ou si la
personne EST une raison sociale. On fuzzy-match `legalName` au nom de la personne
(seuil config) pour ne garder que les rapprochements crédibles ; le plus souvent
le résultat sera vide, et c'est correct (on n'invente pas de lien).

Open data, personnes publiques. Idempotent : ré-écrit `gleif_data`.

Usage :
    docker compose exec api python scripts/ingest_gleif.py --limit 100

Cron (mensuel) :
    0 3 5 * *  docker compose exec -T api python scripts/ingest_gleif.py --limit 200
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import GLEIF_API_URL, OSINT_FUZZY_THRESHOLD  # noqa: E402
from database import SessionLocal  # noqa: E402
from osint_common import (  # noqa: E402
    get_logger,
    iter_corpus_persons,
    make_session,
    name_matches,
    normalize_person_name,
)

log = get_logger("gleif")


def _natural_name(name: str) -> str:
    if "," in name:
        last, _, first = name.partition(",")
        return f"{first.strip()} {last.strip()}"
    return name


def _search_lei(session, name: str) -> list[dict]:
    try:
        r = session.get(
            f"{GLEIF_API_URL}/lei-records",
            params={"filter[entity.legalName]": name, "page[size]": 10},
            timeout=30,
        )
        if r.status_code != 200:
            return []
        return (r.json() or {}).get("data") or []
    except Exception as exc:  # noqa: BLE001
        log.warning("GLEIF %s : %s", name, exc)
        return []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--rate-limit", type=float, default=1.0)
    args = parser.parse_args()

    session = make_session()
    db = SessionLocal()
    matched = 0
    now = datetime.utcnow()
    try:
        persons = list(iter_corpus_persons(db))[: args.limit]
        log.info("%d entités à rechercher dans GLEIF.", len(persons))
        for entity in persons:
            natural = _natural_name(entity.name)
            records = _search_lei(session, natural)
            links = []
            for rec in records:
                attrs = (rec.get("attributes") or {}).get("entity") or {}
                legal_name = (attrs.get("legalName") or {}).get("name") or ""
                if legal_name and name_matches(
                    natural, legal_name, threshold=OSINT_FUZZY_THRESHOLD
                ):
                    links.append(
                        {
                            "lei": rec.get("id"),
                            "legalName": legal_name,
                            "country": (attrs.get("legalAddress") or {}).get("country"),
                            "status": attrs.get("status"),
                        }
                    )
            entity.gleif_data = json.dumps(links, ensure_ascii=False) if links else None
            entity.gleif_synced_at = now
            db.commit()
            if links:
                matched += 1
                log.info("match: %s → %d LEI", entity.name, len(links))
            time.sleep(args.rate_limit)
        log.info("Terminé : %d/%d entités avec lien GLEIF.", matched, len(persons))
    finally:
        db.close()


if __name__ == "__main__":
    main()

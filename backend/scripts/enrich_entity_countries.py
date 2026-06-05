#!/usr/bin/env python3
"""Rétro-alimentation pays (v030, fonctionnalité transversale).

Renseigne `entities.country_code` (ISO 3166-1 alpha-2) + `country_name` (FR)
pour les entités ayant un `wikidata_qid` mais pas encore de pays, via Wikidata
P27 (citoyenneté) → P297 (code ISO). Données OPEN SOURCE, personnes publiques.

Le repli « entités parlement.ch → CH » est appliqué directement par
`ingest_parlament_ch.py` (qui connaît le canton), pas ici.

Usage :
    docker compose exec api python scripts/enrich_entity_countries.py
    docker compose exec api python scripts/enrich_entity_countries.py --limit 100

Cron (mensuel, après l'enrichissement Wikidata) :
    0 4 1 * *  docker compose exec -T api python scripts/enrich_entity_countries.py
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from osint_common import get_logger  # noqa: E402
from wikidata import backfill_countries  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--rate-limit", type=float, default=1.0)
    args = parser.parse_args()

    log = get_logger("countries")
    log.info("Démarrage enrich_entity_countries (limit=%s)", args.limit)
    result = backfill_countries(rate_limit=args.rate_limit, limit=args.limit)
    log.info("Terminé : %s", result)


if __name__ == "__main__":
    main()

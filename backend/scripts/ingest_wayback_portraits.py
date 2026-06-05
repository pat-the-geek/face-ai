#!/usr/bin/env python3
"""P2B — Wayback Machine : chronologie des portraits archivés. Open, sans auth.

Pour les entités ayant une URL de portrait connue (miniature Wikipédia/Commons),
interroge la Wayback CDX API pour lister les captures historiques (1 par an via
`collapse=timestamp:4`), télécharge un échantillon et l'ingère avec
`source_provider='wayback_machine'` + `images.capture_year`. Le pipeline standard
détecte/aligne ; on obtient une évolution visuelle dans le temps.

Données OPEN SOURCE (archives publiques), personnes publiques. Politeness 2 s.
Idempotent : dédup par `source_url` (URL Wayback unique par capture).

Usage :
    docker compose exec api python scripts/ingest_wayback_portraits.py --limit 30
    docker compose exec api python scripts/ingest_wayback_portraits.py --slug musk-elon

Cron (mensuel) :
    0 4 15 * *  docker compose exec -T api python scripts/ingest_wayback_portraits.py --limit 50
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import WAYBACK_CDX_URL, WAYBACK_RATE_LIMIT_SECONDS  # noqa: E402
from database import Entity, SessionLocal  # noqa: E402
from osint_common import (  # noqa: E402
    get_logger,
    ingest_external_image,
    iter_corpus_persons,
    make_session,
)
from sqlalchemy import select  # noqa: E402

log = get_logger("wayback")


def _portrait_seed_url(entity: Entity) -> str | None:
    """URL de portrait de référence à suivre dans le temps."""
    return entity.wiki_thumbnail_url or None


def _cdx_captures(session, url: str, per_year: bool = True) -> list[tuple[str, str]]:
    """Retourne [(timestamp, original)] des captures 200, 1 par an si per_year."""
    params = {
        "url": url,
        "output": "json",
        "fl": "timestamp,original,statuscode",
        "filter": "statuscode:200",
    }
    if per_year:
        params["collapse"] = "timestamp:4"
    try:
        r = session.get(WAYBACK_CDX_URL, params=params, timeout=30)
        r.raise_for_status()
        rows = r.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("CDX %s : %s", url, exc)
        return []
    if not rows or len(rows) < 2:
        return []
    # rows[0] = header
    return [(row[0], row[1]) for row in rows[1:] if len(row) >= 2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", help="une seule entité par slug")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument(
        "--max-per-entity", type=int, default=8, help="captures max par entité"
    )
    args = parser.parse_args()

    session = make_session()
    db = SessionLocal()
    ingested = entities_done = 0
    try:
        if args.slug:
            e = db.scalar(select(Entity).where(Entity.slug == args.slug))
            persons = [e] if e else []
        else:
            persons = [e for e in iter_corpus_persons(db) if _portrait_seed_url(e)]
            persons = persons[: args.limit]
        log.info("%d entités avec portrait de référence à suivre.", len(persons))

        for entity in persons:
            seed = _portrait_seed_url(entity)
            if not seed:
                continue
            captures = _cdx_captures(session, seed)
            time.sleep(WAYBACK_RATE_LIMIT_SECONDS)
            any_for_entity = False
            for ts, original in captures[: args.max_per_entity]:
                year = int(ts[:4]) if len(ts) >= 4 and ts[:4].isdigit() else None
                # `id_` → contenu brut sans la barre Wayback
                wb_url = f"https://web.archive.org/web/{ts}id_/{original}"
                res = ingest_external_image(
                    entity.id,
                    wb_url,
                    source_provider="wayback_machine",
                    caption=f"Wayback {year} — {entity.name}",
                    copyright_text=f"Internet Archive / capture {ts}",
                    capture_year=year,
                    session=session,
                )
                if res.get("status") == "ok":
                    ingested += 1
                    any_for_entity = True
                    log.info("ingest: %s ← %s (%s)", entity.name, year, original)
                time.sleep(WAYBACK_RATE_LIMIT_SECONDS)
            if any_for_entity:
                entities_done += 1
        log.info(
            "Terminé : %d captures ingérées sur %d entités.", ingested, entities_done
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()

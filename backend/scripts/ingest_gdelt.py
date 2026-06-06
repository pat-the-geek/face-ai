#!/usr/bin/env python3
"""P2A — GDELT : couverture médiatique mondiale. API DOC 2.0 publique (open).

Pour une sélection d'entités (favoris + plus actives par défaut), interroge
GDELT sur N jours : volume d'articles, tonalité moyenne, pays sources dominants.
Écrit un snapshot dans `entity_gdelt_coverage`. Agrégat de couverture, pas de
contenu — open data, personnes publiques.

Respecte ~1 req/sec (config GDELT_RATE_LIMIT_SECONDS). Idempotent au sens où on
empile des snapshots horodatés (le lecteur prend le plus récent).

Usage :
    docker compose exec api python scripts/ingest_gdelt.py --limit 50
    docker compose exec api python scripts/ingest_gdelt.py --slug trump-donald --days 30

Cron (hebdomadaire) :
    0 6 * * 1  docker compose exec -T api python scripts/ingest_gdelt.py --limit 100
"""
import argparse
import json
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (  # noqa: E402
    GDELT_API_URL,
    GDELT_DEFAULT_DAYS,
    GDELT_RATE_LIMIT_SECONDS,
)
from database import Entity, EntityGdeltCoverage, SessionLocal  # noqa: E402
from osint_common import get_logger, make_session  # noqa: E402
from sqlalchemy import select  # noqa: E402

log = get_logger("gdelt")


def _query_name(entity: Entity) -> str:
    """Forme "First Last" entre guillemets pour la requête GDELT."""
    if "," in entity.name:
        last, _, first = entity.name.partition(",")
        return f'"{first.strip()} {last.strip()}"'
    return f'"{entity.name}"'


def _fetch_artlist(session, query: str, days: int) -> list[dict]:
    start = (datetime.utcnow() - timedelta(days=days)).strftime("%Y%m%d%H%M%S")
    try:
        r = session.get(
            GDELT_API_URL,
            params={
                "query": query,
                "mode": "artlist",
                "maxrecords": 250,
                "format": "json",
                "STARTDATETIME": start,
                "sort": "datedesc",
            },
            timeout=30,
        )
        if r.status_code != 200 or not r.text.strip():
            return []
        return (r.json() or {}).get("articles") or []
    except Exception as exc:  # noqa: BLE001
        log.warning("artlist %s : %s", query, exc)
        return []


def _fetch_avg_tone(session, query: str, days: int) -> float | None:
    """Tonalité moyenne via mode=tonechart (distribution de bins de ton)."""
    start = (datetime.utcnow() - timedelta(days=days)).strftime("%Y%m%d%H%M%S")
    try:
        r = session.get(
            GDELT_API_URL,
            params={
                "query": query,
                "mode": "tonechart",
                "format": "json",
                "STARTDATETIME": start,
            },
            timeout=30,
        )
        if r.status_code != 200 or not r.text.strip():
            return None
        bins = (r.json() or {}).get("tonechart") or []
        total = sum(b.get("count", 0) for b in bins)
        if not total:
            return None
        weighted = sum(b.get("bin", 0) * b.get("count", 0) for b in bins)
        return round(weighted / total, 3)
    except Exception as exc:  # noqa: BLE001
        log.warning("tonechart %s : %s", query, exc)
        return None


def _select_entities(db, args) -> list[Entity]:
    if args.slug:
        e = db.scalar(select(Entity).where(Entity.slug == args.slug))
        return [e] if e else []
    stmt = select(Entity).where(
        (Entity.wikidata_status.is_(None)) | (Entity.wikidata_status != "not_person")
    )
    if args.favorites_only:
        stmt = stmt.where(Entity.is_favorite.is_(True))
    stmt = stmt.order_by(Entity.is_favorite.desc(), Entity.article_count.desc())
    if args.limit:
        stmt = stmt.limit(args.limit)
    return list(db.scalars(stmt))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", help="une seule entité par slug")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--days", type=int, default=GDELT_DEFAULT_DAYS)
    parser.add_argument("--favorites-only", action="store_true")
    args = parser.parse_args()

    session = make_session()
    db = SessionLocal()
    done = 0
    try:
        entities = _select_entities(db, args)
        log.info("%d entités à interroger (GDELT, %d j).", len(entities), args.days)
        period_end = date.today()
        period_start = period_end - timedelta(days=args.days)
        for entity in entities:
            query = _query_name(entity)
            articles = _fetch_artlist(session, query, args.days)
            time.sleep(GDELT_RATE_LIMIT_SECONDS)
            avg_tone = _fetch_avg_tone(session, query, args.days)
            time.sleep(GDELT_RATE_LIMIT_SECONDS)

            countries = Counter(
                a.get("sourcecountry") for a in articles if a.get("sourcecountry")
            )
            snap = EntityGdeltCoverage(
                entity_id=entity.id,
                period_start=period_start,
                period_end=period_end,
                article_count=len(articles),
                avg_tone=avg_tone,
                top_countries=json.dumps(
                    [{"country": c, "count": n} for c, n in countries.most_common(8)],
                    ensure_ascii=False,
                ),
            )
            db.add(snap)
            db.commit()
            done += 1
            log.info(
                "gdelt: %s → %d articles, ton=%s, pays=%s",
                entity.name,
                len(articles),
                avg_tone,
                [c for c, _ in countries.most_common(3)],
            )
        log.info("Terminé : %d snapshots GDELT écrits.", done)
    finally:
        db.close()


if __name__ == "__main__":
    main()

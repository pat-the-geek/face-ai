"""Part de présence (share of voice) + cartographie des sources (v030).

Deux agrégats *dérivés du seul corpus* (posture §1.5 inchangée) :

- **`compute_share_of_voice`** : classement des entités les plus présentes
  dans la presse sur une fenêtre glissante, avec leur **part** (% des mentions
  totales) et la **tendance** vs la fenêtre précédente. C'est la métrique reine
  de la veille — « qui domine / qui monte / qui descend ».

- **`entity_sources`** : répartition des images d'une entité par **agence**
  (`photo_agency`) et par **domaine de presse** (`Article.source_domain`).
  Complète `behavioral_profile.dominant_sources` (qui ne donne que le top 3
  domaines) avec la ventilation complète + les agences.

Module volontairement léger (database + sqlalchemy uniquement) pour être
importable aussi bien par l'API que par le serveur MCP sans tirer la vision.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, or_, select

from config import SHARE_OF_VOICE_WINDOW_DAYS
from database import Article, ArticleEntity, Entity, Image, SessionLocal

NOT_PERSON = "not_person"


def _person_filter():
    return (Entity.wikidata_status.is_(None)) | (Entity.wikidata_status != NOT_PERSON)


def _counts_in_window(db, start: date, end: date) -> dict[int, int]:
    """Articles distincts par entité PERSON sur [start, end] (via published_at)."""
    rows = db.execute(
        select(
            ArticleEntity.entity_id,
            func.count(func.distinct(ArticleEntity.article_id)),
        )
        .join(Article, Article.id == ArticleEntity.article_id)
        .join(Entity, Entity.id == ArticleEntity.entity_id)
        .where(
            Article.published_at.is_not(None),
            Article.published_at >= start,
            Article.published_at <= end,
            _person_filter(),
        )
        .group_by(ArticleEntity.entity_id)
    ).all()
    return {eid: n for eid, n in rows}


def compute_share_of_voice(window_days: int | None = None, limit: int = 20) -> dict:
    """Classement par part de présence presse sur une fenêtre glissante.

    `share_pct` = part de l'entité dans le total des mentions (articles ×
    entités) de la fenêtre. `trend` compare à la fenêtre précédente de même
    durée : `up`/`down`/`flat`, ou `new` quand l'entité était absente avant.
    """
    window_days = SHARE_OF_VOICE_WINDOW_DAYS if window_days is None else window_days
    db = SessionLocal()
    try:
        to_date = date.today()
        cur_start = to_date - timedelta(days=window_days - 1)
        prev_end = cur_start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=window_days - 1)

        cur = _counts_in_window(db, cur_start, to_date)
        prev = _counts_in_window(db, prev_start, prev_end)
        total = sum(cur.values())

        base = {
            "window_days": window_days,
            "from": cur_start.isoformat(),
            "to": to_date.isoformat(),
            "prev_from": prev_start.isoformat(),
            "prev_to": prev_end.isoformat(),
            "total_mentions": total,
        }
        if not cur:
            return {**base, "entities": []}

        ent_rows = db.execute(
            select(Entity.id, Entity.slug, Entity.name, Entity.is_favorite).where(
                Entity.id.in_(list(cur.keys()))
            )
        ).all()
        meta = {e.id: e for e in ent_rows}

        items = []
        for eid, n in cur.items():
            e = meta.get(eid)
            if e is None:
                continue
            p = prev.get(eid, 0)
            if p == 0:
                delta_pct, trend = None, "new"
            else:
                delta_pct = round(100 * (n - p) / p, 1)
                trend = "up" if n > p else "down" if n < p else "flat"
            items.append(
                {
                    "slug": e.slug,
                    "name": e.name,
                    "is_favorite": bool(e.is_favorite),
                    "articles": n,
                    "share_pct": round(100 * n / total, 2) if total else 0.0,
                    "prev_articles": p,
                    "delta_pct": delta_pct,
                    "trend": trend,
                }
            )
        items.sort(key=lambda x: (x["articles"], x["share_pct"]), reverse=True)
        return {**base, "entities": items[:limit]}
    finally:
        db.close()


def entity_sources(entity_id: int) -> dict:
    """Ventilation des images d'une entité par agence + domaine de presse."""
    db = SessionLocal()
    try:
        total = (
            db.scalar(
                select(func.count())
                .select_from(Image)
                .where(Image.entity_id == entity_id)
            )
            or 0
        )

        agency_rows = db.execute(
            select(Image.photo_agency, func.count())
            .where(Image.entity_id == entity_id, Image.photo_agency.is_not(None))
            .group_by(Image.photo_agency)
            .order_by(func.count().desc())
        ).all()

        domain_rows = db.execute(
            select(Article.source_domain, func.count(func.distinct(Image.id)))
            .join(Image, Image.article_id == Article.id)
            .where(Image.entity_id == entity_id, Article.source_domain.is_not(None))
            .group_by(Article.source_domain)
            .order_by(func.count(func.distinct(Image.id)).desc())
        ).all()

        def pct(n: int) -> float:
            return round(100 * n / total, 1) if total else 0.0

        agencies = [
            {"agency": a, "count": c, "pct": pct(c)} for a, c in agency_rows
        ]
        domains = [
            {"domain": d, "count": c, "pct": pct(c)} for d, c in domain_rows[:15]
        ]
        credited = sum(a["count"] for a in agencies)
        return {
            "total_images": total,
            "credited_images": credited,
            "uncredited_images": max(0, total - credited),
            "agencies": agencies,
            "domains": domains,
        }
    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Part de présence / sources")
    parser.add_argument("--share", action="store_true", help="Part de présence")
    parser.add_argument("--window", type=int, default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--sources", type=str, default=None, help="slug d'entité")
    args = parser.parse_args()

    if args.share:
        print(json.dumps(compute_share_of_voice(args.window, args.limit), ensure_ascii=False, indent=2))
    elif args.sources:
        db = SessionLocal()
        try:
            eid = db.scalar(select(Entity.id).where(Entity.slug == args.sources))
        finally:
            db.close()
        print(
            json.dumps(entity_sources(eid), ensure_ascii=False, indent=2)
            if eid
            else f"entité '{args.sources}' introuvable"
        )
    else:
        parser.print_help()

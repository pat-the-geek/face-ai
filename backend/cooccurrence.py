"""Graphe de cooccurrence éditoriale (A5) + profil comportemental (B4).

**A5 — matérialisation.** `compare_entities` (MCP) calcule la cooccurrence d'une
*paire* à la volée. Pour un graphe complet (centralité, top partenaires) ce
calcul par paire ne scale pas. On matérialise donc les arêtes dans
`entity_cooccurrence` (paires a<b avec `shared_articles >= COOCCURRENCE_MIN_SHARED`)
via `recompute_cooccurrence`, à relancer périodiquement (worker dedup ou manuel).

**B4 — profil comportemental.** Élargissement assumé (cf. CLAUDE.md §1.5 /
décision propriétaire 2026-05-30), mais borné au **corpus** : on ne lie aucun
signal externe. `behavioral_profile` résume des signaux *dérivés de nos propres
données* — centralité dans le réseau de cooccurrence, volatilité de visibilité,
ratio d'attributions suspectes, sources éditoriales dominantes. Aucune inférence
hors corpus (pas de tracking, pas de scoring de personnalité).
"""
from __future__ import annotations

import logging
import statistics
from collections import defaultdict

from sqlalchemy import delete, func, or_, select, text

from config import COOCCURRENCE_MIN_SHARED
from database import (
    Article,
    Entity,
    EntityCooccurrence,
    Image,
    SessionLocal,
)

log = logging.getLogger("cooccurrence")


def recompute_cooccurrence(min_shared: int | None = None) -> dict:
    """Reconstruit entièrement la table `entity_cooccurrence`. Idempotent.

    Self-join sur `article_entities` (convention a<b pour ne stocker chaque
    paire qu'une fois), agrégation du nombre d'articles distincts partagés,
    filtre `>= min_shared` et exclusion des tombstones `not_person`.
    """
    threshold = COOCCURRENCE_MIN_SHARED if min_shared is None else min_shared
    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                """
                SELECT ae1.entity_id AS a, ae2.entity_id AS b,
                       COUNT(DISTINCT ae1.article_id) AS n
                  FROM article_entities ae1
                  JOIN article_entities ae2
                    ON ae1.article_id = ae2.article_id
                   AND ae1.entity_id < ae2.entity_id
                  JOIN entities e1 ON e1.id = ae1.entity_id
                  JOIN entities e2 ON e2.id = ae2.entity_id
                 WHERE COALESCE(e1.wikidata_status,'') != 'not_person'
                   AND COALESCE(e2.wikidata_status,'') != 'not_person'
                 GROUP BY ae1.entity_id, ae2.entity_id
                HAVING n >= :threshold
                """
            ),
            {"threshold": threshold},
        ).all()

        db.execute(delete(EntityCooccurrence))
        db.bulk_insert_mappings(
            EntityCooccurrence,
            [
                {"entity_a_id": r.a, "entity_b_id": r.b, "shared_articles": r.n}
                for r in rows
            ],
        )
        db.commit()
        result = {"edges": len(rows), "min_shared": threshold}
        log.info("recompute_cooccurrence : %s", result)
        return result
    finally:
        db.close()


def top_cooccurrences(entity_id: int, limit: int = 10) -> list[dict]:
    """Top partenaires de cooccurrence d'une entité (les deux orientations).

    Retourne `[{slug, name, shared_articles, is_favorite}]` trié décroissant.
    Lit la table matérialisée — rapide même sur un grand corpus.
    """
    db = SessionLocal()
    try:
        rows = db.execute(
            select(
                EntityCooccurrence.entity_a_id,
                EntityCooccurrence.entity_b_id,
                EntityCooccurrence.shared_articles,
            ).where(
                or_(
                    EntityCooccurrence.entity_a_id == entity_id,
                    EntityCooccurrence.entity_b_id == entity_id,
                )
            )
        ).all()
        partners = [
            (b if a == entity_id else a, n) for a, b, n in rows
        ]
        partners.sort(key=lambda p: p[1], reverse=True)
        partners = partners[:limit]
        if not partners:
            return []
        ids = [p[0] for p in partners]
        ent_rows = db.execute(
            select(Entity.id, Entity.slug, Entity.name, Entity.is_favorite).where(
                Entity.id.in_(ids)
            )
        ).all()
        by_id = {e.id: e for e in ent_rows}
        out = []
        for pid, n in partners:
            e = by_id.get(pid)
            if e is None:
                continue
            out.append(
                {
                    "slug": e.slug,
                    "name": e.name,
                    "shared_articles": n,
                    "is_favorite": bool(e.is_favorite),
                }
            )
        return out
    finally:
        db.close()


def behavioral_profile(entity_id: int) -> dict | None:
    """Profil comportemental dérivé du corpus (B4) pour une entité.

    Signaux :
    - `network_degree` : nombre de partenaires de cooccurrence (centralité de
      degré dans le graphe matérialisé).
    - `top_partners` : 5 plus fortes cooccurrences.
    - `visibility_volatility` : coefficient de variation (écart-type / moyenne)
      du nombre d'images par mois — élevé = présence en pics, bas = présence
      régulière.
    - `peak_month` : mois le plus actif.
    - `flagged_ratio` : part d'images en `flagged`/`human_flagged` (qualité
      d'attribution).
    - `dominant_sources` : 3 domaines de presse les plus présents.
    - `active_months` : nombre de mois distincts avec ≥1 image.
    """
    db = SessionLocal()
    try:
        entity = db.get(Entity, entity_id)
        if entity is None or entity.wikidata_status == "not_person":
            return None

        # Volatilité de visibilité — images par mois (via published_at).
        month_rows = db.execute(
            select(Article.published_at, func.count(Image.id))
            .join(Image, Image.article_id == Article.id)
            .where(
                Image.entity_id == entity_id,
                Article.published_at.is_not(None),
            )
            .group_by(Article.published_at)
        ).all()
        by_month: dict[str, int] = defaultdict(int)
        for d, n in month_rows:
            by_month[d.strftime("%Y-%m")] += n
        counts = list(by_month.values())
        if len(counts) >= 2:
            mean = statistics.mean(counts)
            vol = round(statistics.pstdev(counts) / mean, 3) if mean else None
        else:
            vol = None
        peak_month = max(by_month.items(), key=lambda kv: kv[1])[0] if by_month else None

        # Ratio d'attributions suspectes.
        total_images = (
            db.scalar(
                select(func.count()).select_from(Image).where(Image.entity_id == entity_id)
            )
            or 0
        )
        flagged = (
            db.scalar(
                select(func.count())
                .select_from(Image)
                .where(
                    Image.entity_id == entity_id,
                    Image.association_status.in_(("flagged", "human_flagged")),
                )
            )
            or 0
        )
        flagged_ratio = round(flagged / total_images, 3) if total_images else None

        # Sources dominantes.
        source_rows = db.execute(
            select(Article.source_domain, func.count(func.distinct(Image.id)))
            .join(Image, Image.article_id == Article.id)
            .where(Image.entity_id == entity_id, Article.source_domain.is_not(None))
            .group_by(Article.source_domain)
            .order_by(func.count(func.distinct(Image.id)).desc())
            .limit(3)
        ).all()
        dominant_sources = [{"domain": r[0], "images": r[1]} for r in source_rows]

        partners = top_cooccurrences(entity_id, limit=5)
        # Degré complet (toutes arêtes, pas seulement le top 5).
        degree = (
            db.scalar(
                select(func.count())
                .select_from(EntityCooccurrence)
                .where(
                    or_(
                        EntityCooccurrence.entity_a_id == entity_id,
                        EntityCooccurrence.entity_b_id == entity_id,
                    )
                )
            )
            or 0
        )

        return {
            "slug": entity.slug,
            "name": entity.name,
            "network_degree": degree,
            "top_partners": partners,
            "visibility_volatility": vol,
            "peak_month": peak_month,
            "active_months": len(by_month),
            "flagged_ratio": flagged_ratio,
            "dominant_sources": dominant_sources,
            "interpretation_note": (
                "Signaux dérivés du seul corpus FACE.ai/WUDD (aucune source "
                "externe). volatility = écart-type/moyenne des images mensuelles : "
                "élevé → présence en pics événementiels, bas → présence régulière."
            ),
        }
    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Cooccurrence + profil comportemental")
    parser.add_argument(
        "--recompute", action="store_true", help="Reconstruit entity_cooccurrence"
    )
    parser.add_argument("--min-shared", type=int, default=None)
    parser.add_argument("--profile", type=str, default=None, help="slug d'entité à profiler")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.recompute:
        print(recompute_cooccurrence(min_shared=args.min_shared))
    elif args.profile:
        db = SessionLocal()
        try:
            eid = db.scalar(select(Entity.id).where(Entity.slug == args.profile))
        finally:
            db.close()
        if eid is None:
            print(f"entité '{args.profile}' introuvable")
        else:
            import json

            print(json.dumps(behavioral_profile(eid), ensure_ascii=False, indent=2))
    else:
        parser.print_help()

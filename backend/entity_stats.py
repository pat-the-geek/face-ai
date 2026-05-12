"""Recalcul des compteurs dénormalisés par entité.

`entities.image_count`, `entities.unique_image_count` et `entities.article_count`
sont des champs dénormalisés (par souci de perf — recompter à chaque GET serait
prohibitif sur 16k–30k entités). Cette source de vérité est maintenue ici :

- `recompute_counts(entity_id)` : recalcule les 3 compteurs pour une entité.
  Appelée par `dedup.dedup_entity` (à la fin de chaque cycle de déduplication,
  les is_duplicate viennent de changer) et par le scraper après ingestion.
- `recompute_all()` : passage one-shot sur toutes les entités. À utiliser pour
  rattraper l'historique ou en cas de doute. Idempotent.
"""
from __future__ import annotations

import logging

from sqlalchemy import func, select, update

from database import Article, ArticleEntity, Entity, Image, SessionLocal

log = logging.getLogger("entity_stats")


def recompute_counts(entity_id: int) -> dict:
    """Met à jour image_count, unique_image_count, article_count d'une entité.

    Backfill `first_seen` si null : pour les entités héritées (seed, fixtures,
    pré-v007 où le champ n'était pas systématiquement renseigné), on remonte
    à `min(Article.scraped_at)` des articles liés. Évite l'incohérence
    `first_seen=null` mais `date_range.from` non-null côté MCP.
    """
    db = SessionLocal()
    try:
        image_count = db.scalar(
            select(func.count())
            .select_from(Image)
            .where(Image.entity_id == entity_id)
        ) or 0
        unique_image_count = db.scalar(
            select(func.count())
            .select_from(Image)
            .where(
                Image.entity_id == entity_id,
                Image.is_duplicate.is_(False),
            )
        ) or 0
        article_count = db.scalar(
            select(func.count(func.distinct(ArticleEntity.article_id)))
            .where(ArticleEntity.entity_id == entity_id)
        ) or 0

        values = {
            "image_count": image_count,
            "unique_image_count": unique_image_count,
            "article_count": article_count,
        }

        entity = db.get(Entity, entity_id)
        if entity is not None and entity.first_seen is None:
            backfill = db.scalar(
                select(func.min(Article.scraped_at))
                .select_from(Article)
                .join(ArticleEntity, ArticleEntity.article_id == Article.id)
                .where(ArticleEntity.entity_id == entity_id)
            )
            if backfill is not None:
                values["first_seen"] = backfill

        db.execute(
            update(Entity).where(Entity.id == entity_id).values(**values)
        )
        db.commit()
        return {
            "image_count": image_count,
            "unique_image_count": unique_image_count,
            "article_count": article_count,
        }
    finally:
        db.close()


def recompute_all() -> dict:
    """Passage sur toutes les entités. Retourne un résumé."""
    db = SessionLocal()
    try:
        ids = [row[0] for row in db.execute(select(Entity.id))]
    finally:
        db.close()

    summary = {"entities": 0, "total_images": 0, "total_unique": 0, "total_articles": 0}
    for entity_id in ids:
        r = recompute_counts(entity_id)
        summary["entities"] += 1
        summary["total_images"] += r["image_count"]
        summary["total_unique"] += r["unique_image_count"]
        summary["total_articles"] += r["article_count"]
    return summary


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Recalcul des compteurs entités")
    parser.add_argument("--recompute-all", action="store_true")
    parser.add_argument("--entity-id", type=int)
    args = parser.parse_args()

    if args.entity_id:
        print(recompute_counts(args.entity_id))
    elif args.recompute_all:
        print(recompute_all())
    else:
        parser.print_help()

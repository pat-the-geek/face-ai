"""Nettoyage des données de test/démo laissées en base.

Filtre par préfixe de caption — convention adoptée pour les images injectées
manuellement à des fins de démonstration de feature (ex. injecter une mauvaise
association pour montrer le workflow audit P9).

Préfixes reconnus :
- Convention principale (crochet) : `[TEST`, `[P9`, `[demo`, `[probe`
- Cas hérités sans crochet : caption commençant par `Test ` (espace après —
  évite de matcher "Testament", "Testostérone", etc.) — détecté en post-test
  MCP, l'article "Test purge image cassée" traînait avec ce préfixe.
- Article-side : nettoie aussi les articles dont l'`url` contient
  `wudd.ai/articles/test-` (notre pattern d'URL pour les tests scraper).

Usage : `docker compose exec api python cleanup_demo_data.py [--dry-run]`
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import or_, select

from database import Article, ArticleEntity, Image, SessionLocal
from face_processor import _purge_image

DEMO_CAPTION_PREFIXES = ("[TEST", "[P9", "[demo", "[probe", "Test ")
DEMO_ARTICLE_URL_PATTERNS = ("%wudd.ai/articles/test-%",)


def find_demo_images() -> list[Image]:
    db = SessionLocal()
    try:
        clauses = [Image.caption.like(f"{p}%") for p in DEMO_CAPTION_PREFIXES]
        return list(
            db.execute(select(Image).where(or_(*clauses))).scalars().all()
        )
    finally:
        db.close()


def find_demo_articles() -> list[Article]:
    db = SessionLocal()
    try:
        clauses = [Article.url.like(p) for p in DEMO_ARTICLE_URL_PATTERNS]
        return list(
            db.execute(select(Article).where(or_(*clauses))).scalars().all()
        )
    finally:
        db.close()


def cleanup(dry_run: bool = False) -> dict:
    img_candidates = find_demo_images()
    art_candidates = find_demo_articles()
    purged_images: list[int] = []
    purged_articles: list[int] = []

    for img in img_candidates:
        if dry_run:
            print(f"  would purge image #{img.id}  caption={img.caption!r}")
            continue
        db = SessionLocal()
        try:
            row = db.get(Image, img.id)
            if row:
                _purge_image(db, row)
                purged_images.append(img.id)
        finally:
            db.close()

    for art in art_candidates:
        if dry_run:
            print(f"  would purge article #{art.id}  url={art.url!r}")
            continue
        db = SessionLocal()
        try:
            row = db.get(Article, art.id)
            if not row:
                continue
            # Cascade manuelle : images de cet article + liens article_entities
            for img in list(row.images):
                _purge_image(db, img)
            db.execute(
                ArticleEntity.__table__.delete().where(
                    ArticleEntity.article_id == row.id
                )
            )
            db.delete(row)
            db.commit()
            purged_articles.append(art.id)
        finally:
            db.close()

    return {
        "found_images": len(img_candidates),
        "found_articles": len(art_candidates),
        "purged_images": purged_images,
        "purged_articles": purged_articles,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = cleanup(dry_run=args.dry_run)
    print(result)

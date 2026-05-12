"""Ingestion des articles WUDD → images contextuelles FACE.ai (spec §8).

Complément de `wudd_sync.py` : au lieu de prendre uniquement les portraits
Wikimedia cachés par WUDD, on récupère les **articles** mentionnant chaque
PERSON et on ingère leurs images **déjà extraites côté WUDD**.

Avantages vs ré-scraping HTML :
- WUDD a déjà fait le travail d'extraction (`Images` champ avec url/alt/dim)
- On garde le contexte sémantique : `entities.PERSON` liste les autres
  personnes mentionnées dans l'article, ce qui aide pour les associations
- Pas de double dépendance HTTP fragile (CDN qui bloque les bots, paywall…)

Pipeline par article :
1. Get-or-create `Article` (URL unique, idempotent — ré-appel = no-op)
2. Pour chaque PERSON de `entities.PERSON` : get-or-create `Entity`, lien
   article↔entité
3. Pour chaque image extraite par WUDD :
   a. Tente l'association via caption/alt (`scraper.associate_image`)
   b. Si pas de match ET l'article ne mentionne qu'une seule PERSON,
      associe à elle (laisse l'audit ArcFace décider en aval)
   c. Sinon : ignore (image générique de l'article)
4. Télécharge en RAM (règle §5.4 : pas d'enregistrement DB si raté)

Le worker existant prend ensuite le relais : analyse faciale, identité,
dedup, audit. Les associations douteuses finissent en `flagged` dans /audit.
"""
from __future__ import annotations

import logging
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from sqlalchemy import select

from config import STATIC_DIR
from database import (
    Article,
    ArticleEntity,
    Entity,
    Image,
    SessionLocal,
)
from entity_stats import recompute_counts
from scraper import (
    ImageCandidate,
    _download_to_memory,
    _guess_extension,
    associate_image,
    get_or_create_entity,
)
from wudd_client import fetch_articles_for_person

log = logging.getLogger("wudd_articles_sync")


def _parse_publication_date(raw: str | None):
    """Tolère le RFC 2822 ('Sat, 09 May 2026 21:30:19 GMT') et l'ISO court."""
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).date()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(raw[:10]).date()
    except ValueError:
        return None


def _to_candidate(img: dict) -> ImageCandidate | None:
    """Adapte une image WUDD au format que `associate_image` attend."""
    url = (img.get("url") or "").strip()
    if not url or not url.startswith(("http://", "https://")):
        return None
    return ImageCandidate(
        src=url,
        alt=img.get("alt"),
        # WUDD n'expose pas de figcaption distinct ; l'alt fait office des deux
        caption=img.get("title") or img.get("alt"),
    )


def ingest_article(article_payload: dict) -> dict:
    """Ingère un article WUDD complet. Retourne un compte-rendu."""
    article_url = article_payload.get("URL")
    if not article_url:
        return {"status": "skip_no_url"}

    person_names = (article_payload.get("entities") or {}).get("PERSON", []) or []
    person_names = [n for n in person_names if n and isinstance(n, str)]
    if not person_names:
        return {"status": "skip_no_person"}

    db = SessionLocal()
    try:
        # 1. Article (idempotent via URL unique)
        existing_article = db.scalar(
            select(Article).where(Article.url == article_url)
        )
        if existing_article is None:
            domain = urlparse(article_url).hostname or ""
            article = Article(
                url=article_url,
                title=article_payload.get("Titre"),
                published_at=_parse_publication_date(
                    article_payload.get("Date de publication")
                ),
                source_domain=domain,
            )
            db.add(article)
            db.flush()
            article_already = False
        else:
            article = existing_article
            article_already = True

        # 2. Entités + liens — skippe les noms déjà identifiés comme non-PERSON
        entities: list[Entity] = []
        touched_eids: set[int] = set()
        for raw_name in person_names:
            entity = get_or_create_entity(
                db, raw_name, source_domain=article.source_domain
            )
            if entity is None:
                # Tombstone not_person — pas de lien, pas d'association.
                # L'article peut quand même être ingéré (autres PERSON
                # mentionnés). C'est le sens du `continue`.
                continue
            entities.append(entity)
            touched_eids.add(entity.id)
            link = db.scalar(
                select(ArticleEntity).where(
                    ArticleEntity.article_id == article.id,
                    ArticleEntity.entity_id == entity.id,
                )
            )
            if link is None:
                db.add(
                    ArticleEntity(article_id=article.id, entity_id=entity.id)
                )
        # Force le chargement aliases pour `associate_image`
        for e in entities:
            _ = list(e.aliases)
        db.commit()

        article_id = article.id

        if article_already:
            # Si on revoit le même article, on se contente de garantir les liens
            # entité↔article (faits ci-dessus) et on n'ingère pas re-les images
            # (déjà fait ; l'audit ArcFace continue son travail).
            return {
                "status": "article_already_ingested",
                "article_id": article_id,
                "entities": len(entities),
            }

        # 3. Images
        candidates = [
            c
            for c in (_to_candidate(img) for img in article_payload.get("Images") or [])
            if c is not None
        ]
        downloaded = ignored = failed = 0
        single_person_fallback = entities[0] if len(entities) == 1 else None

        for cand in candidates:
            entity = associate_image(cand, entities)
            if entity is None and single_person_fallback is not None:
                entity = single_person_fallback
            if entity is None:
                ignored += 1
                continue

            data, http_status = _download_to_memory(cand.src)
            if data is None:
                failed += 1
                continue

            img = Image(
                article_id=article_id,
                entity_id=entity.id,
                source_url=cand.src,
                caption=cand.caption,
                alt_text=cand.alt,
                scrape_status="downloaded",
                http_status=http_status,
                association_status="auto",
            )
            db.add(img)
            db.flush()

            ext = _guess_extension(cand.src)
            dest = STATIC_DIR / "originals" / f"{img.id}{ext}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            img.local_path = str(dest)
            downloaded += 1

        db.commit()
    finally:
        db.close()

    for eid in touched_eids:
        recompute_counts(eid)

    return {
        "status": "ok",
        "article_id": article_id,
        "entities": len(person_names),
        "images_found": len(candidates),
        "images_downloaded": downloaded,
        "images_ignored": ignored,
        "images_failed": failed,
    }


def sync_articles_for_person(value: str, limit: int = 20) -> dict:
    """Pull les N derniers articles WUDD mentionnant une PERSON, et les ingère."""
    articles = fetch_articles_for_person(value, limit=limit)
    summary = {
        "person": value,
        "articles_fetched": len(articles),
        "articles_new": 0,
        "articles_already": 0,
        "images_downloaded": 0,
        "images_ignored": 0,
        "images_failed": 0,
    }
    for article in articles:
        result = ingest_article(article)
        if result["status"] == "ok":
            summary["articles_new"] += 1
            summary["images_downloaded"] += result.get("images_downloaded", 0)
            summary["images_ignored"] += result.get("images_ignored", 0)
            summary["images_failed"] += result.get("images_failed", 0)
        elif result["status"] == "article_already_ingested":
            summary["articles_already"] += 1
    log.info("WUDD articles sync %s : %s", value, summary)
    return summary


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--person", required=True, help="Nom WUDD (ex. 'Sam Altman')")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    print(sync_articles_for_person(args.person, limit=args.limit))

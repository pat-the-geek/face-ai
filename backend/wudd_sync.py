"""Synchronisation pull WUDD → FACE.ai (spec §8).

Pour chaque PERSON entity exposée par WUDD :
1. Canonicaliser le nom ("Donald Trump" → "Trump, Donald", slug `donald-trump`)
2. Get-or-create l'entité FACE.ai (avec l'alias original côté `entity_aliases`)
3. Si une `image_url` est fournie ET pas déjà en base → télécharge et persiste
4. Recompute_counts puis laisse le worker enchaîner :
   - face_processor : alignement + landmarks (purge si pas de visage utilisable)
   - identity_audit : embedding ArcFace + audit centroïde
   - dedup : pHash
   - wikidata : enrichissement bio

Idempotent : les entités déjà connues ne sont pas re-créées, les images déjà
téléchargées (même `source_url`) sont silencieusement ignorées.
"""
from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse

import requests

from sqlalchemy import select

from config import STATIC_DIR, WUDD_USER_AGENT
from database import Entity, Image, SessionLocal
from entity_stats import recompute_counts
from scraper import canonicalize_name, get_or_create_entity
from wudd_client import WuddPerson, fetch_persons

log = logging.getLogger("wudd_sync")
IMAGE_TIMEOUT = 15
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def _download_image(url: str) -> bytes | None:
    try:
        r = requests.get(
            url,
            headers={"User-Agent": WUDD_USER_AGENT},
            timeout=IMAGE_TIMEOUT,
            stream=True,
        )
    except requests.RequestException as e:
        log.warning("download failed %s : %s", url[:80], e)
        return None
    if r.status_code != 200:
        return None
    chunks: list[bytes] = []
    total = 0
    for chunk in r.iter_content(chunk_size=8192):
        total += len(chunk)
        if total > MAX_IMAGE_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks) if total > 0 else None


def _ingest_one(person: WuddPerson) -> str:
    """Traite une entité. Retourne 'created', 'image_added', 'noop' ou 'failed'."""
    if not person.value:
        return "failed"

    db = SessionLocal()
    try:
        # Détecte si l'entité existe AVANT pour distinguer création vs noop
        canonical, slug = canonicalize_name(person.value)
        was_present = (
            db.scalar(select(Entity.id).where(Entity.slug == slug)) is not None
        )
        entity = get_or_create_entity(db, person.value, source_domain="wudd.ai")
        if entity is None:
            # Tombstone not_person — on n'ingère pas l'image proposée par
            # WUDD pour ce nom. Le pull retombe sur l'entité fantôme et
            # repart sans toucher.
            log.info("WUDD pull skip not_person : %s", person.value)
            return "noop"
        # Force le chargement aliases avant de fermer la session
        _ = list(entity.aliases)
        eid = entity.id
        # Cache local du nombre de mentions WUDD pour le tri batch
        if person.mentions and entity.wudd_mentions != person.mentions:
            entity.wudd_mentions = person.mentions
            db.commit()
        action = "noop" if was_present else "created"

        if person.image_url:
            existing = db.scalar(
                Image.__table__.select().where(
                    Image.source_url == person.image_url
                )
            )
            if existing is None:
                data = _download_image(person.image_url)
                if data is None:
                    log.warning(
                        "image WUDD non récupérée pour %s", person.value
                    )
                else:
                    img = Image(
                        entity_id=eid,
                        source_url=person.image_url,
                        caption=f"Portrait Wikimedia importé via WUDD.ai",
                        copyright_text="© Wikimedia Commons (via WUDD.ai)",
                        scrape_status="downloaded",
                        analysis_status="pending",
                        association_status="auto",
                    )
                    db.add(img)
                    db.commit()
                    ext = ".jpg"
                    parsed = urlparse(person.image_url).path.lower()
                    for cand in (".jpg", ".jpeg", ".png", ".webp"):
                        if parsed.endswith(cand):
                            ext = ".jpg" if cand == ".jpeg" else cand
                            break
                    dest = STATIC_DIR / "originals" / f"{img.id}{ext}"
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
                    img.local_path = str(dest)
                    db.commit()
                    # Une nouvelle entité avec image reste 'created' ; une
                    # entité existante qui gagne une image bascule 'image_added'
                    if action != "created":
                        action = "image_added"
    except Exception:
        log.exception("ingest %s failed", person.value)
        return "failed"
    finally:
        db.close()

    # recompute_counts ouvre sa propre session
    if action != "failed":
        recompute_counts(eid)
    return action


def sync_persons(limit: int | None = None) -> dict[str, int]:
    """Pull une page d'entités WUDD et les ingère. Idempotent."""
    persons = fetch_persons(limit=limit)
    counts = {
        "fetched": len(persons),
        "created": 0,
        "image_added": 0,
        "noop": 0,
        "failed": 0,
    }
    for p in persons:
        action = _ingest_one(p)
        counts[action] = counts.get(action, 0) + 1
    log.info("WUDD sync : %s", counts)
    return counts


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    print(sync_persons(limit=args.limit))

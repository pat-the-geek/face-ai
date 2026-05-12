"""Scraper d'articles WUDD.ai → DB FACE.ai.

Reçoit en entrée un article WUDD avec sa liste d'entités PERSON. Télécharge
la page HTML, extrait les images, et associe chaque image à la première
entité dont le nom (ou un alias) apparaît dans la caption ou l'attribut alt.

Limites P0 :
- Une image n'est associée qu'à une seule entité (`images.entity_id`). Pour
  les photos de groupe, la spec §19 prévoit la correction manuelle en P9.
- La canonisation de nom est heuristique ("dernier mot = nom de famille")
  et ne fusionne pas les variantes au-delà du slug exact. La logique de
  fusion fine (Macron / Emmanuel Macron) est un point ouvert §19.
"""
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from slugify import slugify
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from config import STATIC_DIR
from database import (
    Article,
    ArticleEntity,
    Entity,
    EntityAlias,
    Image,
    SessionLocal,
)

USER_AGENT = "FACE.ai/1.0 (contact@ok-ia.ch)"
HTTP_TIMEOUT = 10
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_RETRIES = 3
BACKOFF_BASE = 0.5


@dataclass
class EntityInput:
    name: str
    type: str = "PERSON"


@dataclass
class ScrapeInput:
    article_url: str
    article_title: str | None = None
    entities: list[EntityInput] = field(default_factory=list)


@dataclass
class ScrapeResult:
    article_id: int | None
    status: str
    images_found: int = 0
    images_downloaded: int = 0
    images_ignored: int = 0
    images_failed: int = 0


@dataclass
class ImageCandidate:
    src: str
    alt: str | None
    caption: str | None


def canonicalize_name(raw: str) -> tuple[str, str]:
    """('Sam Altman') → ('Altman, Sam', 'sam-altman')."""
    parts = raw.strip().split()
    if len(parts) >= 2:
        last = parts[-1]
        first = " ".join(parts[:-1])
        canonical = f"{last}, {first}"
        slug = slugify(f"{first} {last}")
    else:
        canonical = raw.strip()
        slug = slugify(canonical) or "unknown"
    return canonical, slug


def get_or_create_entity(
    db: Session, raw_name: str, source_domain: str | None
) -> Entity | None:
    """Récupère ou crée une entité.

    Ordre de résolution :
    1. Slug exact (forme canonique du raw_name)
    2. **Alias existant pour `raw_name`** — crucial post-merge : si on a
       déjà fusionné "Zuckerberg" dans "Zuckerberg, Mark", "Zuckerberg" est
       devenu un alias. Sans ce check, le prochain pull "Zuckerberg" depuis
       WUDD recréerait une nouvelle entité, défaisant la fusion.
    3. Création.

    **Retourne `None`** si l'entité existante a été identifiée comme
    non-personne (`wikidata_status='not_person'`). Le caller doit dans ce
    cas ignorer cette mention — pas de lien article_entities, pas d'image
    téléchargée. Le tombstone reste en DB pour bloquer la recréation aux
    pulls WUDD ultérieurs.
    """
    canonical, slug = canonicalize_name(raw_name)
    entity = db.scalar(
        select(Entity).options(joinedload(Entity.aliases)).where(Entity.slug == slug)
    )
    if entity is None:
        # Cherche dans les aliases : peut-être que ce raw_name a été
        # rattaché à une autre entité par fusion.
        alias_row = db.scalar(
            select(EntityAlias).where(EntityAlias.alias == raw_name)
        )
        if alias_row is not None:
            entity = db.scalar(
                select(Entity)
                .options(joinedload(Entity.aliases))
                .where(Entity.id == alias_row.entity_id)
            )
        if entity is None:
            entity = Entity(name=canonical, slug=slug, first_seen=datetime.utcnow())
            db.add(entity)
            db.flush()

    # Garde-fou périmètre PERSON : si l'entité a déjà été identifiée comme
    # non-personne par Wikidata (P31 ≠ Q5) et purgée, on refuse de
    # réutiliser ce slug. Le caller doit ignorer le retour None.
    if entity.wikidata_status == "not_person":
        return None

    if raw_name != canonical and raw_name != entity.name:
        existing = db.scalar(
            select(EntityAlias).where(
                EntityAlias.entity_id == entity.id,
                EntityAlias.alias == raw_name,
            )
        )
        if existing is None:
            db.add(
                EntityAlias(
                    entity_id=entity.id, alias=raw_name, source=source_domain
                )
            )
            db.flush()
    return entity


def get_or_create_article(
    db: Session, url: str, title: str | None
) -> tuple[Article, bool]:
    article = db.scalar(select(Article).where(Article.url == url))
    if article is not None:
        return article, False
    domain = urlparse(url).hostname or ""
    article = Article(url=url, title=title, source_domain=domain)
    db.add(article)
    db.flush()
    return article, True


def fetch_html(url: str) -> str | None:
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            return r.text
        except requests.RequestException:
            if attempt == MAX_RETRIES - 1:
                return None
            time.sleep(BACKOFF_BASE * (2**attempt))
    return None


def extract_images(html: str, base_url: str) -> list[ImageCandidate]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[ImageCandidate] = []
    seen: set[str] = set()
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if not src:
            continue
        absolute_url = urljoin(base_url, src)
        if not absolute_url.startswith(("http://", "https://")):
            continue
        if absolute_url in seen:
            continue
        seen.add(absolute_url)

        caption = None
        figure = img.find_parent("figure")
        if figure is not None:
            figcaption = figure.find("figcaption")
            if figcaption is not None:
                caption = figcaption.get_text(strip=True)

        candidates.append(
            ImageCandidate(
                src=absolute_url, alt=img.get("alt"), caption=caption
            )
        )
    return candidates


def _name_variants(entity: Entity) -> list[str]:
    variants = [entity.name]
    if "," in entity.name:
        last, first = [p.strip() for p in entity.name.split(",", 1)]
        variants.append(f"{first} {last}")
    variants.extend(a.alias for a in entity.aliases)
    return [v for v in variants if v]


def associate_image(
    image: ImageCandidate, entities: list[Entity]
) -> Entity | None:
    haystack = " ".join(filter(None, [image.alt or "", image.caption or ""])).lower()
    if not haystack.strip():
        return None
    for entity in entities:
        for variant in _name_variants(entity):
            if variant.lower() in haystack:
                return entity
    return None


def _guess_extension(url: str) -> str:
    path = urlparse(url).path.lower()
    for ext in (".jpeg", ".jpg", ".png", ".gif", ".webp"):
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    return ".jpg"


def _download_to_memory(url: str) -> tuple[bytes | None, int | None]:
    """Télécharge en RAM (≤ 5 MB par contrat). Retourne (bytes|None, http_status|None).

    Aucune écriture disque ici — l'appelant ne crée le fichier que si la donnée
    passe les vérifications ultérieures (cohérent avec la règle "on oublie les
    téléchargements ratés ou inutilisables").
    """
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(
                url, headers=headers, timeout=HTTP_TIMEOUT, stream=True
            )
            status = r.status_code
            if status >= 400:
                return None, status

            content_length = r.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_IMAGE_BYTES:
                return None, status

            chunks: list[bytes] = []
            total = 0
            for chunk in r.iter_content(chunk_size=8192):
                total += len(chunk)
                if total > MAX_IMAGE_BYTES:
                    return None, status
                chunks.append(chunk)
            return b"".join(chunks), status
        except requests.RequestException:
            if attempt == MAX_RETRIES - 1:
                return None, None
            time.sleep(BACKOFF_BASE * (2**attempt))
    return None, None


def process_article(payload: ScrapeInput) -> ScrapeResult:
    db = SessionLocal()
    try:
        article, created = get_or_create_article(
            db, payload.article_url, payload.article_title
        )
        if not created:
            return ScrapeResult(article_id=article.id, status="already_scraped")

        entities: list[Entity] = []
        for ent in payload.entities:
            if ent.type != "PERSON":
                continue
            e = get_or_create_entity(
                db, ent.name, source_domain=article.source_domain
            )
            if e is None:
                # Entité déjà identifiée comme non-personne (tombstone
                # `wikidata_status='not_person'`). On l'ignore — pas de
                # lien article, pas de scraping d'image pour ce nom.
                continue
            entities.append(e)
            link = db.scalar(
                select(ArticleEntity).where(
                    ArticleEntity.article_id == article.id,
                    ArticleEntity.entity_id == e.id,
                )
            )
            if link is None:
                db.add(
                    ArticleEntity(article_id=article.id, entity_id=e.id)
                )
        db.commit()

        for e in entities:
            db.refresh(e)
            _ = e.aliases  # force le chargement avant de quitter le scope

        html = fetch_html(payload.article_url)
        if html is None:
            return ScrapeResult(
                article_id=article.id, status="html_fetch_failed"
            )

        candidates = extract_images(html, payload.article_url)

        downloaded = ignored = failed = 0
        for cand in candidates:
            entity = associate_image(cand, entities)
            if entity is None:
                ignored += 1
                continue

            data, http_status = _download_to_memory(cand.src)
            if data is None:
                # Lien cassé / timeout / trop gros → on oublie, pas d'enregistrement
                failed += 1
                continue

            img = Image(
                article_id=article.id,
                entity_id=entity.id,
                source_url=cand.src,
                caption=cand.caption,
                alt_text=cand.alt,
                scrape_status="downloaded",
                http_status=http_status,
            )
            db.add(img)
            db.flush()

            ext = _guess_extension(cand.src)
            dest = STATIC_DIR / "originals" / f"{img.id}{ext}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            img.local_path = str(dest)
            downloaded += 1

        touched_entity_ids = [e.id for e in entities]
        db.commit()
        article_id = article.id
    finally:
        db.close()

    # Recalcul des compteurs après commit (recompute_counts ouvre sa propre session)
    from entity_stats import recompute_counts
    for eid in touched_entity_ids:
        recompute_counts(eid)

    return ScrapeResult(
        article_id=article_id,
        status="ok",
        images_found=len(candidates),
        images_downloaded=downloaded,
        images_ignored=ignored,
        images_failed=failed,
    )

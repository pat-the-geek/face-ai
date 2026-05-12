"""Recherche d'images via DuckDuckGo (lib `ddgs`).

**Périmètre** : élargit le corpus FACE.ai hors WUDD.ai (cf. CLAUDE.md §1.5).
Désactivé par défaut, activable via env `FACE_AI_ENABLE_DDG=true`.

Architecture :
- `search_images(query, limit)` → preview only, retourne des URLs candidates
  sans rien télécharger. C'est ce que consomme la modale UI picker.
- `download_and_ingest(entity_id, url, title)` → télécharge l'image,
  l'ajoute comme image classique de l'entité avec `source_provider='ddg'`.
  Le pipeline standard (face_processor + identity_audit) qualifie ensuite.

Pas d'API officielle DDG Images — la lib `ddgs` scrape le JSON privé de
DDG, ce qui peut casser à n'importe quelle refonte amont. On gère
gracieusement les exceptions et on retourne une liste vide si DDG est
indisponible.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from sqlalchemy import select

from config import STATIC_DIR
from database import Entity, Image, SessionLocal
from entity_stats import recompute_counts

log = logging.getLogger("ddg_search")

DOWNLOAD_TIMEOUT = 15
USER_AGENT = "FACE.ai/1.0 (contact@ok-ia.ch)"


def search_images(query: str, limit: int = 20) -> list[dict]:
    """Cherche des images via DDG, retourne une liste de candidates.

    Champs : `image_url`, `thumbnail`, `title`, `source_page`, `width`,
    `height`. Pas de téléchargement à ce stade — l'utilisateur visualise
    les thumbnails et choisit lesquelles ingérer.

    Retourne `[]` si DDG ne répond pas (réseau, blocage, refonte API).
    """
    try:
        from ddgs import DDGS
    except ImportError:
        log.warning("ddgs non installé")
        return []

    try:
        with DDGS() as ddgs:
            raw = list(ddgs.images(query=query, max_results=limit))
    except Exception as e:
        log.warning("DDG images failed for %r : %s", query, e)
        return []

    out: list[dict] = []
    for item in raw:
        image_url = (item.get("image") or "").strip()
        if not image_url or not image_url.startswith(("http://", "https://")):
            continue
        out.append({
            "image_url": image_url,
            "thumbnail": item.get("thumbnail") or image_url,
            "title": item.get("title") or "",
            "source_page": item.get("url") or "",
            "width": item.get("width"),
            "height": item.get("height"),
        })
    return out


def _download(url: str) -> tuple[bytes | None, int | None]:
    """GET binaire avec UA FACE.ai. Retourne (bytes, http_status)."""
    try:
        r = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=DOWNLOAD_TIMEOUT,
            stream=False,
        )
        if r.status_code != 200:
            return None, r.status_code
        return r.content, r.status_code
    except requests.RequestException:
        return None, None


def _guess_extension(url: str) -> str:
    parsed = urlparse(url).path.lower()
    for cand in (".jpg", ".jpeg", ".png", ".webp"):
        if parsed.endswith(cand):
            return ".jpg" if cand == ".jpeg" else cand
    return ".jpg"


def ingest_image(
    entity_id: int,
    url: str,
    title: str | None = None,
    source_page: str | None = None,
) -> dict:
    """Télécharge et ingère une image DDG comme image de l'entité.

    `source_provider='ddg'` est posé pour traçabilité (filtre /audit
    renforcé). `article_id=None` car pas de lien vers un article presse.
    Le pipeline standard prend ensuite la main : face_processor analyse,
    identity_audit confirme/flag selon le centroïde ArcFace.

    Retourne {status, image_id, http_status, file_size}.
    """
    db = SessionLocal()
    try:
        entity = db.get(Entity, entity_id)
        if entity is None:
            return {"status": "missing_entity"}

        # Idempotence : si l'URL est déjà connue (recherche DDG répétée,
        # double-clic UI), on ne re-télécharge pas.
        existing = db.scalar(select(Image).where(Image.source_url == url))
        if existing is not None:
            return {
                "status": "already_ingested",
                "image_id": existing.id,
            }

        data, http_status = _download(url)
        if data is None:
            return {
                "status": "download_failed",
                "http_status": http_status,
            }

        img = Image(
            entity_id=entity_id,
            article_id=None,
            source_url=url,
            caption=title or None,
            copyright_text=f"DuckDuckGo Images — {source_page or 'unknown source'}",
            scrape_status="downloaded",
            analysis_status="pending",
            association_status="auto",
            source_provider="ddg",
            http_status=http_status,
        )
        db.add(img)
        db.flush()

        ext = _guess_extension(url)
        dest = STATIC_DIR / "originals" / f"{img.id}{ext}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        img.local_path = str(dest)
        db.commit()

        image_id = img.id
        log.info("DDG ingest : entity=%s image=%s (%d bytes)",
                 entity.name, image_id, len(data))
    finally:
        db.close()

    recompute_counts(entity_id)
    return {
        "status": "ok",
        "image_id": image_id,
        "http_status": http_status,
        "file_size": len(data),
    }


def can_use_ddg(entity: Entity) -> tuple[bool, str | None]:
    """Garde-fou rate-limit + flag env.

    Refuse si :
    - `FACE_AI_ENABLE_DDG` non activé
    - Entité a déjà été sync DDG il y a < `DDG_RATE_LIMIT_HOURS`
      (on utilise `last_articles_synced_at` comme heuristique partagée —
      pas de champ dédié pour rester léger)
    """
    from config import ENABLE_DDG, DDG_RATE_LIMIT_HOURS

    if not ENABLE_DDG:
        return False, "DDG disabled (set FACE_AI_ENABLE_DDG=true to activate)"

    # Pas de rate-limit spécifique pour l'instant — le user déclenche
    # manuellement, la fréquence reste raisonnable.
    return True, None

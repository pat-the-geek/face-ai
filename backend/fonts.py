"""Téléchargement lazy + cache des polices pour l'export.

Les .ttf sont récupérés au premier appel depuis des CDN GitHub stables et
mis en cache dans `/models/fonts/`. Si le download échoue (offline, URL morte,
container fraîchement créé sans réseau), on tombe sur la police par défaut
de PIL — l'export reste fonctionnel, juste avec une typographie générique.

L'identité visuelle FACE.ai est :
- Cormorant Garamond italic — titres
- EB Garamond — texte courant
- Space Mono — métadonnées, footer
"""
from __future__ import annotations

import logging
from pathlib import Path

import requests
from PIL import ImageFont

FONT_DIR = Path("/models/fonts")
USER_AGENT = "FACE.ai/1.0 (contact@ok-ia.ch)"

# Source : repo officiel google/fonts. Cormorant et EB Garamond sont des
# **variable fonts** (axe `wght`), nom de fichier avec crochets URL-encodés.
# PIL ≥ 9.x gère les variable fonts ; on prend le poids par défaut.
FONT_URLS = {
    "cormorant_italic": "https://github.com/google/fonts/raw/main/ofl/cormorantgaramond/CormorantGaramond-Italic%5Bwght%5D.ttf",
    "eb_garamond": "https://github.com/google/fonts/raw/main/ofl/ebgaramond/EBGaramond%5Bwght%5D.ttf",
    "space_mono": "https://github.com/google/fonts/raw/main/ofl/spacemono/SpaceMono-Regular.ttf",
}

log = logging.getLogger("fonts")
_cache: dict[tuple[str, int], ImageFont.ImageFont] = {}


def _ensure_font(name: str) -> Path | None:
    """Garantit la présence du .ttf dans le cache, le télécharge si besoin."""
    path = FONT_DIR / f"{name}.ttf"
    if path.exists():
        return path
    url = FONT_URLS.get(name)
    if not url:
        return None
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        if r.status_code != 200:
            log.warning("font %s : HTTP %d", name, r.status_code)
            return None
        path.write_bytes(r.content)
        log.info("font %s téléchargée (%d KB)", name, len(r.content) // 1024)
        return path
    except requests.RequestException as e:
        log.warning("font %s : %s", name, e)
        return None


def get_font(name: str, size: int):
    """Retourne une police PIL avec fallback silencieux."""
    key = (name, size)
    if key in _cache:
        return _cache[key]

    path = _ensure_font(name)
    if path:
        try:
            font = ImageFont.truetype(str(path), size)
        except OSError as e:
            log.warning("ImageFont.truetype %s : %s", name, e)
            font = ImageFont.load_default()
    else:
        font = ImageFont.load_default()

    _cache[key] = font
    return font

"""Export JPG d'une planche composite (spec §11.6).

Image bitmap unique avec :
- En-tête : nom (Cormorant italic 64) + sous-titre (dates · occupation · nationalité)
- Filet horizontal de séparation
- Grille 4 colonnes des portraits alignés (uniques uniquement, hors flagged)
- Pied de page : `FACE.ai · veille interne · {date}` à gauche, compte à droite

Format JPG quality 92, ~150 DPI équivalent. Largeur fixe 1240 px,
hauteur calculée en fonction du nombre d'images (max 24).
"""
from __future__ import annotations

import io
import logging
import math
from datetime import date
from pathlib import Path

from PIL import Image as PILImage
from PIL import ImageDraw

from database import Entity
from fonts import get_font

log = logging.getLogger("export")

# Layout
COLS = 4
CELL_PX = 280
GAP_PX = 20
MARGIN_PX = 60
HEADER_HEIGHT = 220
FOOTER_HEIGHT = 60
MAX_IMAGES = 24

# Palette FACE.ai (cohérente avec tokens.css mode galerie)
BG_COLOR = (248, 246, 240)
INK_COLOR = (26, 24, 20)
MUTED_COLOR = (138, 130, 120)
DIVIDER_COLOR = (220, 215, 208)


def render_entity_jpg(entity: Entity, image_paths: list[Path]) -> bytes:
    """Construit la planche et retourne les bytes JPEG."""
    image_paths = [p for p in image_paths if p.exists()][:MAX_IMAGES]
    n = len(image_paths)
    rows = math.ceil(n / COLS) if n else 0

    width = MARGIN_PX * 2 + COLS * CELL_PX + (COLS - 1) * GAP_PX
    height = (
        MARGIN_PX
        + HEADER_HEIGHT
        + rows * CELL_PX
        + max(0, rows - 1) * GAP_PX
        + FOOTER_HEIGHT
        + MARGIN_PX
    )

    canvas = PILImage.new("RGB", (width, height), color=BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    title_font = get_font("cormorant_italic", 64)
    sub_font = get_font("eb_garamond", 20)
    mono_font = get_font("space_mono", 13)

    # Header — nom
    draw.text((MARGIN_PX, MARGIN_PX), entity.name, fill=INK_COLOR, font=title_font)

    # Sous-titre : dates · occupation · nationalité
    subtitle_parts: list[str] = []
    if entity.birth_date:
        s = entity.birth_date.strftime("%Y")
        if entity.death_date:
            s += "—" + entity.death_date.strftime("%Y")
        subtitle_parts.append(s)
    if entity.occupations:
        subtitle_parts.append(entity.occupations.split("|", 1)[0])
    if entity.nationalities:
        subtitle_parts.append(entity.nationalities.split("|", 1)[0])
    if subtitle_parts:
        subtitle = " · ".join(subtitle_parts)
        draw.text(
            (MARGIN_PX, MARGIN_PX + 90),
            subtitle,
            fill=MUTED_COLOR,
            font=sub_font,
        )

    # Filet horizontal
    line_y = MARGIN_PX + HEADER_HEIGHT - 20
    draw.line(
        [(MARGIN_PX, line_y), (width - MARGIN_PX, line_y)],
        fill=DIVIDER_COLOR,
        width=1,
    )

    # Grille des portraits
    grid_y0 = MARGIN_PX + HEADER_HEIGHT
    for i, path in enumerate(image_paths):
        r, c = divmod(i, COLS)
        x = MARGIN_PX + c * (CELL_PX + GAP_PX)
        y = grid_y0 + r * (CELL_PX + GAP_PX)
        try:
            thumb = (
                PILImage.open(path)
                .convert("RGB")
                .resize((CELL_PX, CELL_PX), PILImage.LANCZOS)
            )
            canvas.paste(thumb, (x, y))
        except (OSError, ValueError) as e:
            log.warning("export skip image %s : %s", path, e)
            # Carré gris foncé en placeholder discret
            draw.rectangle(
                [(x, y), (x + CELL_PX, y + CELL_PX)],
                fill=DIVIDER_COLOR,
            )

    # Footer
    footer_y = grid_y0 + rows * (CELL_PX + GAP_PX) + 10
    if rows == 0:
        footer_y = grid_y0 + 10
    footer_left = f"FACE.ai · veille interne · {date.today().isoformat()}"
    footer_right = f"{n} portrait{'s' if n != 1 else ''}"
    draw.text((MARGIN_PX, footer_y), footer_left, fill=MUTED_COLOR, font=mono_font)
    bbox = draw.textbbox((0, 0), footer_right, font=mono_font)
    draw.text(
        (width - MARGIN_PX - (bbox[2] - bbox[0]), footer_y),
        footer_right,
        fill=MUTED_COLOR,
        font=mono_font,
    )

    out = io.BytesIO()
    canvas.save(out, format="JPEG", quality=92, optimize=True)
    return out.getvalue()

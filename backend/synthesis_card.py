"""Fiche de veille typographiée (v030) — l'image jointe aux notifications.

Discord ne permet ni police ni titres de chapitre dans un message texte. On
**rend donc la synthèse comme une image** : carte composée avec l'identité
visuelle FACE.ai (Cormorant italic pour le nom, EB Garamond pour le corps,
Space Mono pour les titres de chapitre et métadonnées — cf. export §11.6),
portrait annoté des landmarks en médaillon, barre d'accent colorée par
scénario, et chapitres « SYNTHÈSE / REPÈRES / CORPUS & MÉDIAS ».

`render_synthesis_card` ne dépend que de Pillow + fonts.get_font (mêmes que
l'export). Hauteur calculée dynamiquement selon le texte. Renvoie des bytes
JPEG, ou None si le rendu échoue (l'appelant retombe alors sur du texte).
"""
from __future__ import annotations

import io
import logging
from datetime import date
from pathlib import Path

from fonts import get_font

log = logging.getLogger("synthesis_card")

WIDTH = 1000
MARGIN = 56
ACCENT_W = 14
PORTRAIT = 280
GAP = 28

BG = (248, 246, 240)
INK = (26, 24, 20)
MUTED = (138, 130, 120)
DIVIDER = (220, 215, 208)


HEAT_CELL = 11
HEAT_GAP = 3
HEAT_STEP = HEAT_CELL + HEAT_GAP
HEAT_EMPTY = (236, 232, 225)
HEAT_ZERO = (226, 221, 213)


def _blend(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def _wrap(draw, text, font, max_w):
    """Découpe `text` en lignes tenant dans `max_w` px."""
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        cur = ""
        for word in paragraph.split():
            trial = (cur + " " + word).strip()
            if draw.textlength(trial, font=font) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
    return lines


def _portrait_thumb(portrait_path, landmarks_blob, size):
    """Vignette carrée du portrait, landmarks dessinés si dispo. None si KO."""
    if not portrait_path:
        return None
    try:
        import cv2
        import numpy as np
        from PIL import Image as PILImage

        img = cv2.imread(str(portrait_path))
        if img is None:
            return None
        if landmarks_blob:
            pts = np.frombuffer(landmarks_blob, dtype=np.float32).reshape(-1, 2)
            h, w = img.shape[:2]
            for x, y in pts:
                cv2.circle(
                    img, (int(x * w), int(y * h)), 1, (90, 220, 255), -1, cv2.LINE_AA
                )
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        return PILImage.fromarray(rgb).resize((size, size), PILImage.LANCZOS)
    except Exception:
        log.exception("vignette portrait échec (%s)", portrait_path)
        return None


def render_synthesis_card(
    *,
    name: str,
    subtitle: str | None,
    badge: str,
    accent_rgb: tuple[int, int, int],
    portrait_path: str | None,
    landmarks_blob: bytes | None,
    synthesis_text: str | None,
    reperes: list[str] | None,
    corpus: list[str] | None,
    heatmap: dict | None = None,
    footer_right: str = "",
) -> bytes | None:
    try:
        from PIL import Image as PILImage
        from PIL import ImageDraw

        name_font = get_font("cormorant_italic", 58)
        sub_font = get_font("eb_garamond", 22)
        badge_font = get_font("space_mono", 16)
        chapter_font = get_font("space_mono", 15)
        body_font = get_font("eb_garamond", 22)
        fact_font = get_font("space_mono", 14)
        footer_font = get_font("space_mono", 12)

        # Canvas de mesure jetable (Pillow exige un draw pour textlength/wrap).
        meas = ImageDraw.Draw(PILImage.new("RGB", (10, 10)))
        content_w = WIDTH - 2 * MARGIN
        text_x = MARGIN + PORTRAIT + GAP
        text_w = WIDTH - text_x - MARGIN

        # ── pré-calcul des blocs de chapitre ──────────────────────────
        chapters = []  # (titre, lignes, font, line_h)
        if synthesis_text:
            chapters.append(
                ("SYNTHÈSE", _wrap(meas, synthesis_text, body_font, content_w), body_font, 30)
            )
        if reperes:
            rl = []
            for r in reperes:
                rl += _wrap(meas, r, fact_font, content_w)
            chapters.append(("REPÈRES", rl, fact_font, 22))
        if corpus:
            cl = []
            for c in corpus:
                cl += _wrap(meas, c, fact_font, content_w)
            chapters.append(("CORPUS & MÉDIAS", cl, fact_font, 22))

        # Heatmap d'activité presse (grille semaines × 7 jours), si fournie.
        heat_grid = heatmap.get("grid") if heatmap else None
        heat_h = 0
        if heat_grid:
            heat_h = 28 + 7 * HEAT_STEP + 18

        # ── calcul de hauteur ─────────────────────────────────────────
        top_block = max(PORTRAIT, 150)
        y = MARGIN + top_block + 24  # après portrait + filet
        for _title, lines, _font, lh in chapters:
            y += 30  # titre de chapitre + espace
            y += len(lines) * lh
            y += 18  # marge bas de chapitre
        y += heat_h
        height = y + 50  # footer

        canvas = PILImage.new("RGB", (WIDTH, height), color=BG)
        draw = ImageDraw.Draw(canvas)

        # Barre d'accent verticale (scénario)
        draw.rectangle([(0, 0), (ACCENT_W, height)], fill=accent_rgb)

        # Portrait
        thumb = _portrait_thumb(portrait_path, landmarks_blob, PORTRAIT)
        if thumb is not None:
            canvas.paste(thumb, (MARGIN, MARGIN))
        else:
            draw.rectangle(
                [(MARGIN, MARGIN), (MARGIN + PORTRAIT, MARGIN + PORTRAIT)],
                fill=DIVIDER,
            )

        # Badge scénario + nom + sous-titre (à droite du portrait)
        ty = MARGIN + 6
        draw.text((text_x, ty), badge.upper(), fill=accent_rgb, font=badge_font)
        ty += 30
        draw.text((text_x, ty), name, fill=INK, font=name_font)
        ty += 66
        if subtitle:
            for ln in _wrap(meas, subtitle, sub_font, text_w)[:2]:
                draw.text((text_x, ty), ln, fill=MUTED, font=sub_font)
                ty += 28

        # Filet sous le bloc d'en-tête
        line_y = MARGIN + top_block + 8
        draw.line([(MARGIN, line_y), (WIDTH - MARGIN, line_y)], fill=DIVIDER, width=1)

        # Chapitres
        y = MARGIN + top_block + 24
        for title, lines, font, lh in chapters:
            draw.text((MARGIN, y), title, fill=accent_rgb, font=chapter_font)
            y += 28
            for ln in lines:
                draw.text((MARGIN, y), ln, fill=INK if font is body_font else (70, 64, 56), font=font)
                y += lh
            y += 18

        # Heatmap d'activité presse
        if heat_grid:
            label = heatmap.get("label") or "ACTIVITÉ PRESSE · 12 MOIS"
            hmax = max(1, heatmap.get("max") or 1)
            draw.text((MARGIN, y), label.upper(), fill=accent_rgb, font=chapter_font)
            y += 28
            for j, col in enumerate(heat_grid):
                cx = MARGIN + j * HEAT_STEP
                for r, val in enumerate(col):
                    cy = y + r * HEAT_STEP
                    if val < 0:
                        color = HEAT_EMPTY
                    elif val == 0:
                        color = HEAT_ZERO
                    else:
                        color = _blend(HEAT_ZERO, accent_rgb, 0.25 + 0.75 * min(1.0, val / hmax))
                    draw.rectangle(
                        [(cx, cy), (cx + HEAT_CELL, cy + HEAT_CELL)], fill=color
                    )
            y += 7 * HEAT_STEP + 18

        # Footer
        fy = height - 40
        footer_left = f"FACE.ai · veille interne · {date.today().isoformat()}"
        draw.text((MARGIN, fy), footer_left, fill=MUTED, font=footer_font)
        if footer_right:
            bbox = draw.textbbox((0, 0), footer_right, font=footer_font)
            draw.text(
                (WIDTH - MARGIN - (bbox[2] - bbox[0]), fy),
                footer_right,
                fill=MUTED,
                font=footer_font,
            )

        out = io.BytesIO()
        canvas.save(out, format="JPEG", quality=90, optimize=True)
        return out.getvalue()
    except Exception:
        log.exception("rendu fiche de synthèse échec")
        return None

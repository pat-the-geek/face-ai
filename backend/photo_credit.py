"""Résolution de l'agence / crédit photo d'une image (bloc A4).

Le champ `images.copyright_text` est très lacunaire (souvent NULL) et hétérogène
(« © Getty Images », « REUTERS/Carlos Barria », « Keystone-ATS », un nom de
photographe seul…). On normalise vers une **agence canonique** quand un marqueur
connu apparaît dans le copyright, la caption ou le domaine de l'URL source —
sinon NULL (on n'invente pas de crédit, cohérent avec §1.5).

Usage : `parse_agency(copyright_text, source_url, caption) -> str | None`.
Appelé dans `face_processor.process_image` (chokepoint unique par image valide)
et rattrapable sur l'historique via `--backfill`.

Le but est la **traçabilité des sources visuelles** (dimension musée/forensique
assumée), pas une attribution juridique exhaustive.
"""
from __future__ import annotations

import logging
import re

from sqlalchemy import select

from database import Image, SessionLocal

log = logging.getLogger("photo_credit")

# Agence canonique → motifs (recherchés en minuscules, bornés par \b quand le
# motif est court/ambigu pour éviter les faux positifs). Ordre = priorité :
# la première agence qui matche gagne. Wikimedia en dernier (catch-all corpus
# d'enrichissement). Les domaines d'agences sont aussi captés via l'URL.
_AGENCY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Getty Images", (r"getty", r"gettyimages")),
    ("Reuters", (r"\breuters\b", r"reuters\.com")),
    ("AFP", (r"\bafp\b", r"agence france-presse", r"afp\.com")),
    ("Associated Press", (r"\bap photo\b", r"associated press", r"\bap\b/")),
    ("Bloomberg", (r"\bbloomberg\b",)),
    ("EPA", (r"\bepa\b", r"european pressphoto")),
    ("dpa", (r"\bdpa\b", r"picture alliance", r"picture-alliance")),
    ("Keystone-ATS", (r"keystone", r"keystone-ats", r"\bats\b", r"\bsda\b")),
    ("Shutterstock", (r"shutterstock",)),
    ("NurPhoto", (r"nurphoto",)),
    ("Imago", (r"\bimago\b",)),
    ("Anadolu", (r"anadolu",)),
    ("Xinhua", (r"xinhua",)),
    ("Magnum Photos", (r"magnum photos", r"magnumphotos")),
    ("Sipa", (r"\bsipa\b", r"sipa press")),
    ("Abaca", (r"\babaca\b",)),
    ("Hans Lucas", (r"hans lucas", r"hanslucas")),
    ("ANSA", (r"\bansa\b",)),
    ("EFE", (r"\befe\b",)),
    ("AP", (r"\bassociated\b",)),
    ("Wikimedia Commons", (r"wikimedia", r"wikipedia", r"creative commons", r"\bcc by")),
)

_COMPILED = tuple(
    (name, re.compile("|".join(motifs))) for name, motifs in _AGENCY_PATTERNS
)


def parse_agency(
    copyright_text: str | None,
    source_url: str | None = None,
    caption: str | None = None,
) -> str | None:
    """Retourne l'agence canonique détectée, ou None.

    Concatène copyright + caption + domaine d'URL en un seul texte minuscule et
    teste les motifs dans l'ordre de priorité. Le copyright pèse le plus (c'est
    sa vocation) mais beaucoup de sources mettent le crédit en fin de caption.
    """
    haystack = " ".join(
        part for part in (copyright_text, caption, source_url) if part
    ).lower()
    if not haystack.strip():
        return None
    for name, rx in _COMPILED:
        if rx.search(haystack):
            return name
    return None


def backfill_photo_agency(limit: int | None = None) -> dict[str, int]:
    """Renseigne `images.photo_agency` pour l'historique (v028).

    Traite les images dont `photo_agency` est NULL. Idempotent : une image sans
    marqueur reconnaissable reste NULL et sera re-tentée à un prochain run (coût
    négligeable, pas de réseau).
    """
    db = SessionLocal()
    try:
        q = select(Image).where(Image.photo_agency.is_(None))
        if limit:
            q = q.limit(limit)
        rows = db.execute(q).scalars().all()
        counts = {"total": len(rows), "resolved": 0}
        for img in rows:
            agency = parse_agency(img.copyright_text, img.source_url, img.caption)
            if agency:
                img.photo_agency = agency
                counts["resolved"] += 1
        db.commit()
        log.info("backfill_photo_agency : %s", counts)
        return counts
    finally:
        db.close()


def agency_distribution() -> dict[str, int]:
    """Répartition globale des agences résolues — pour la démographie corpus."""
    db = SessionLocal()
    try:
        from sqlalchemy import func

        rows = db.execute(
            select(Image.photo_agency, func.count())
            .where(Image.photo_agency.is_not(None))
            .group_by(Image.photo_agency)
            .order_by(func.count().desc())
        ).all()
        return {r[0]: r[1] for r in rows}
    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Crédit photo / agence (A4)")
    parser.add_argument(
        "--backfill", action="store_true", help="Résout photo_agency des images existantes"
    )
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.backfill:
        r = backfill_photo_agency(limit=args.limit)
        print(f"backfill agence : {r}")
    else:
        parser.print_help()

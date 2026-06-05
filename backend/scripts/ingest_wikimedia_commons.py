#!/usr/bin/env python3
"""P1B — Wikimedia Commons : portraits libres supplémentaires.

Pour chaque entité ayant un `wikidata_qid`, récupère l'image P18 (Wikidata) et,
en option, les fichiers de la catégorie Commons P373, puis les ingère avec
`source_provider='wikimedia_commons'`. Données OPEN SOURCE (licences libres
Commons), personnes publiques. Le pipeline standard (face_processor +
identity_audit) qualifie ; §5.4 purge si pas de visage exploitable.

Idempotent : `ingest_external_image` déduplique par `source_url`, et la
déduplication pHash visuelle (dedup.py) absorbe les ré-encodages.

Usage :
    docker compose exec api python scripts/ingest_wikimedia_commons.py --limit 50
    docker compose exec api python scripts/ingest_wikimedia_commons.py --with-category

Cron (hebdomadaire) :
    0 5 * * 1  docker compose exec -T api python scripts/ingest_wikimedia_commons.py
"""
import argparse
import sys
import time
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import SessionLocal  # noqa: E402
from osint_common import (  # noqa: E402
    get_logger,
    ingest_external_image,
    iter_corpus_persons,
    make_session,
)
from wikidata import (  # noqa: E402
    PROP_ISO_3166_1_ALPHA2,  # noqa: F401  (garde le module aligné)
    _get_statements,
    _statement_string,
)

log = get_logger("wikimedia_commons")

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
PROP_IMAGE = "P18"
PROP_COMMONS_CATEGORY = "P373"


def _commons_file_url(session, filename: str) -> str | None:
    """Résout l'URL directe d'un fichier Commons via imageinfo."""
    title = filename if filename.startswith("File:") else f"File:{filename}"
    try:
        r = session.get(
            COMMONS_API,
            params={
                "action": "query",
                "titles": title,
                "prop": "imageinfo",
                "iiprop": "url",
                "format": "json",
            },
            timeout=20,
        )
        r.raise_for_status()
        pages = (r.json().get("query") or {}).get("pages") or {}
        for page in pages.values():
            info = (page.get("imageinfo") or [{}])[0]
            url = info.get("url")
            if url:
                return url
    except Exception as exc:  # noqa: BLE001
        log.warning("imageinfo %s : %s", filename, exc)
    return None


def _category_files(session, category: str, limit: int) -> list[str]:
    """Liste les fichiers d'une catégorie Commons (filetype image)."""
    cat = category if category.startswith("Category:") else f"Category:{category}"
    try:
        r = session.get(
            COMMONS_API,
            params={
                "action": "query",
                "list": "categorymembers",
                "cmtitle": cat,
                "cmtype": "file",
                "cmlimit": min(limit, 50),
                "format": "json",
            },
            timeout=20,
        )
        r.raise_for_status()
        members = (r.json().get("query") or {}).get("categorymembers") or []
        return [m["title"] for m in members if m.get("title")]
    except Exception as exc:  # noqa: BLE001
        log.warning("categorymembers %s : %s", category, exc)
        return []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="limite d'entités")
    parser.add_argument(
        "--with-category",
        action="store_true",
        help="ingérer aussi les fichiers de la catégorie Commons P373",
    )
    parser.add_argument(
        "--category-max",
        type=int,
        default=5,
        help="max de fichiers de catégorie par entité (défaut 5)",
    )
    parser.add_argument("--rate-limit", type=float, default=0.5)
    args = parser.parse_args()

    session = make_session()
    db = SessionLocal()
    ingested = entities_done = 0
    try:
        persons = [e for e in iter_corpus_persons(db, require_qid=True)]
        if args.limit:
            persons = persons[: args.limit]
        log.info("%d entités avec QID à traiter.", len(persons))
        for entity in persons:
            statements = _get_statements(entity.wikidata_qid)
            if not statements:
                continue
            filenames: list[str] = []
            p18 = _statement_string(statements, PROP_IMAGE)
            if p18:
                filenames.append(p18)
            if args.with_category:
                cat = _statement_string(statements, PROP_COMMONS_CATEGORY)
                if cat:
                    filenames.extend(
                        _category_files(session, cat, args.category_max)
                    )
            any_for_entity = False
            for fname in filenames:
                url = _commons_file_url(session, fname)
                if not url:
                    continue
                res = ingest_external_image(
                    entity.id,
                    url,
                    source_provider="wikimedia_commons",
                    caption=f"Wikimedia Commons — {fname}",
                    copyright_text=f"Wikimedia Commons / {fname}",
                    session=session,
                )
                if res.get("status") == "ok":
                    ingested += 1
                    any_for_entity = True
                    log.info("ingest: %s ← %s", entity.name, fname)
                time.sleep(args.rate_limit)
            if any_for_entity:
                entities_done += 1
        log.info(
            "Terminé : %d images ingérées sur %d entités.", ingested, entities_done
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()

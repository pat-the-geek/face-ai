#!/usr/bin/env python3
"""P3B — ICIJ Offshore Leaks (Panama/Pandora/Bahamas/Offshore). Open data.

Vérifie la présence de chaque entité FACE.ai (personnes publiques du corpus)
dans les bases ICIJ et stocke un flag `icij_match` + `icij_detail` JSON.

Deux modes :
- `--csv DIR` (recommandé, fiable) : croise avec un export CSV officiel ICIJ
  (data.icij.org : `nodes-officers.csv` / `nodes-entities.csv`). Indexe les
  `Officer` par nom normalisé, fuzzy-match au seuil config.
- défaut (API web) : interroge l'endpoint de recherche public par nom. Best
  effort — ICIJ n'offre pas d'API contractuelle stable, on échoue gracieusement
  si la réponse n'est pas exploitable (corpus non modifié).

⚠ Données publiques mais sensibles (RGPD art. 9/10, présomption d'innocence) —
usage interne/journalistique. Cf. CLAUDE.md (décision périmètre 2026-06-05).
Idempotent : ré-écrit `icij_match`/`detail`.

Usage :
    docker compose exec api python scripts/ingest_icij.py --csv /data/icij
    docker compose exec api python scripts/ingest_icij.py --limit 50

Cron (mensuel) :
    0 4 5 * *  docker compose exec -T api python scripts/ingest_icij.py --csv /data/icij
"""
import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import ICIJ_API_URL, OSINT_FUZZY_THRESHOLD  # noqa: E402
from database import SessionLocal  # noqa: E402
from osint_common import (  # noqa: E402
    get_logger,
    iter_corpus_persons,
    make_session,
    normalize_person_name,
)

log = get_logger("icij")


def _natural_name(name: str) -> str:
    if "," in name:
        last, _, first = name.partition(",")
        return f"{first.strip()} {last.strip()}"
    return name


def _build_csv_index(csv_dir: Path) -> dict[str, list[dict]]:
    """Indexe les officers ICIJ par nom normalisé → [{name, dataset, ...}]."""
    index: dict[str, list[dict]] = {}
    for fname in ("nodes-officers.csv", "nodes-entities.csv"):
        path = csv_dir / fname
        if not path.exists():
            continue
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                name = row.get("name") or row.get("Name") or ""
                key = normalize_person_name(name)
                if not key:
                    continue
                index.setdefault(key, []).append(
                    {
                        "name": name,
                        "dataset": row.get("sourceID") or row.get("source"),
                        "jurisdiction": row.get("jurisdiction_description")
                        or row.get("countries"),
                        "node_id": row.get("node_id") or row.get("n.node_id"),
                    }
                )
        log.info("Indexé %s (%d clés cumulées).", fname, len(index))
    return index


def _api_search(session, name: str) -> list[dict]:
    try:
        r = session.get(
            f"{ICIJ_API_URL}/search",
            params={"q": name, "cat": 1},
            timeout=30,
        )
        if r.status_code != 200 or not r.text.strip():
            return []
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("ICIJ API %s : %s", name, exc)
        return []
    results = data.get("results") or data.get("data") or []
    out = []
    for rec in results if isinstance(results, list) else []:
        out.append(
            {
                "name": rec.get("name"),
                "dataset": rec.get("sourceID") or rec.get("dataset"),
                "jurisdiction": rec.get("jurisdiction") or rec.get("countries"),
                "node_id": rec.get("node_id") or rec.get("id"),
            }
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", help="répertoire des CSV ICIJ (mode fiable)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--rate-limit", type=float, default=1.0)
    args = parser.parse_args()

    session = make_session()
    csv_index = None
    if args.csv:
        csv_index = _build_csv_index(Path(args.csv))
        if not csv_index:
            log.error("Aucun CSV ICIJ exploitable dans %s — abandon.", args.csv)
            return

    from rapidfuzz import process, fuzz  # noqa: E402

    db = SessionLocal()
    matched = 0
    now = datetime.utcnow()
    try:
        persons = list(iter_corpus_persons(db))
        if args.limit:
            persons = persons[: args.limit]
        keys = list(csv_index) if csv_index else []
        for entity in persons:
            natural = _natural_name(entity.name)
            qnorm = normalize_person_name(natural)
            hits: list[dict] = []
            if csv_index is not None:
                if qnorm in csv_index:
                    hits = csv_index[qnorm]
                elif keys:
                    m = process.extractOne(
                        qnorm, keys, scorer=fuzz.token_sort_ratio,
                        score_cutoff=OSINT_FUZZY_THRESHOLD,
                    )
                    if m:
                        hits = csv_index[m[0]]
            else:
                hits = _api_search(session, natural)
                time.sleep(args.rate_limit)

            entity.icij_match = bool(hits)
            entity.icij_detail = (
                json.dumps(hits[:20], ensure_ascii=False) if hits else None
            )
            entity.icij_synced_at = now
            db.commit()
            if hits:
                matched += 1
                log.info("ICIJ match: %s → %d connexions", entity.name, len(hits))
        log.info("Terminé : %d/%d entités avec match ICIJ.", matched, len(persons))
    finally:
        db.close()


if __name__ == "__main__":
    main()

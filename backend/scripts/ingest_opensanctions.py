#!/usr/bin/env python3
"""P1A — OpenSanctions (PEP, sanctions, criminels). Open data CC BY-NC.

Télécharge le dataset fusionné `default` (FtM JSON Lines), indexe les entités
de schéma Person par nom normalisé, puis croise avec les entités FACE.ai
(personnes publiques déjà dans le corpus). Pose `sanctions_status`
('sanctioned'/'pep'/'clean'/'unknown') + `sanctions_detail` JSON.

PÉRIMÈTRE : uniquement des PERSONNES PUBLIQUES du corpus, données OPEN SOURCE
reprises telles quelles (aucune inférence). Catégorie RGPD art. 9/10 — cf.
CLAUDE.md (décision périmètre 2026-06-05). Usage interne LAN.

Matching : nom normalisé exact (rapide, O(1)) puis repli rapidfuzz au seuil
config sur les noms du dataset. Les entités sans correspondance sont marquées
`clean` (vérifiées, non listées) — uniquement si l'index a bien été chargé.

Idempotent : ré-écrit `sanctions_status`/`detail` à chaque passage.

Usage :
    docker compose exec api python scripts/ingest_opensanctions.py
    docker compose exec api python scripts/ingest_opensanctions.py --file /data/os_default.json

Cron (hebdomadaire) :
    0 2 * * 1  docker compose exec -T api python scripts/ingest_opensanctions.py
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import OPENSANCTIONS_URL, OSINT_FUZZY_THRESHOLD  # noqa: E402
from database import SessionLocal  # noqa: E402
from osint_common import (  # noqa: E402
    get_logger,
    iter_corpus_persons,
    make_session,
    normalize_person_name,
)

log = get_logger("opensanctions")

SANCTION_TOPICS = {"sanction", "sanction.linked", "crime", "debarment", "wanted"}
PEP_TOPICS = {"role.pep", "role.rca", "poi"}


def _status_from_topics(topics: list[str]) -> str:
    tset = set(topics or [])
    if tset & SANCTION_TOPICS:
        return "sanctioned"
    if any(t.startswith("role.pep") or t in PEP_TOPICS for t in tset):
        return "pep"
    return "pep"  # présent dans `default` sans topic clair → PEP par défaut prudent


def _iter_lines(args, session):
    """Itère les lignes JSON du dataset (fichier local ou stream HTTP)."""
    if args.file:
        with open(args.file, "r", encoding="utf-8") as fh:
            for line in fh:
                yield line
    else:
        log.info("Téléchargement streaming %s …", OPENSANCTIONS_URL)
        with session.get(OPENSANCTIONS_URL, stream=True, timeout=120) as r:
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if line:
                    yield line


def _build_index(args, session) -> dict[str, dict]:
    """normalized_name → {status, datasets, topics, caption}. Schéma Person only."""
    index: dict[str, dict] = {}
    count = 0
    for line in _iter_lines(args, session):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("schema") != "Person":
            continue
        props = rec.get("properties") or {}
        names = list(props.get("name") or [])
        names += list(props.get("alias") or [])
        if not names:
            continue
        topics = props.get("topics") or []
        summary = {
            "status": _status_from_topics(topics),
            "datasets": rec.get("datasets") or [],
            "topics": topics,
            "caption": rec.get("caption") or names[0],
        }
        for nm in names:
            key = normalize_person_name(nm)
            if key:
                # garde le plus "fort" (sanctioned > pep) en cas de collision
                prev = index.get(key)
                if prev is None or (
                    summary["status"] == "sanctioned" and prev["status"] != "sanctioned"
                ):
                    index[key] = summary
        count += 1
        if count % 50000 == 0:
            log.info("  %d persons indexés (%d clés)", count, len(index))
    log.info("Index construit : %d persons, %d clés normalisées.", count, len(index))
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", help="dataset FtM JSON Lines local (sinon download)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--no-fuzzy",
        action="store_true",
        help="désactive le repli rapidfuzz (exact match seulement)",
    )
    args = parser.parse_args()

    session = make_session()
    index = _build_index(args, session)
    if not index:
        log.error("Index OpenSanctions vide — abandon (corpus non modifié).")
        return
    keys = list(index)

    try:
        from rapidfuzz import process, fuzz
        has_fuzzy = not args.no_fuzzy
    except ImportError:  # pragma: no cover
        has_fuzzy = False

    db = SessionLocal()
    now = datetime.utcnow()
    counts = {"sanctioned": 0, "pep": 0, "clean": 0}
    try:
        persons = list(iter_corpus_persons(db))
        if args.limit:
            persons = persons[: args.limit]
        for entity in persons:
            qnorm = normalize_person_name(entity.name)
            hit = index.get(qnorm)
            score = 100.0 if hit else 0.0
            if hit is None and has_fuzzy and qnorm:
                m = process.extractOne(
                    qnorm, keys, scorer=fuzz.token_sort_ratio,
                    score_cutoff=OSINT_FUZZY_THRESHOLD,
                )
                if m:
                    hit = index[m[0]]
                    score = m[1]
            if hit:
                entity.sanctions_status = hit["status"]
                entity.sanctions_detail = json.dumps(
                    {
                        "datasets": hit["datasets"],
                        "topics": hit["topics"],
                        "caption": hit["caption"],
                        "score": score,
                        "last_checked": now.isoformat(),
                    },
                    ensure_ascii=False,
                )
                counts[hit["status"]] = counts.get(hit["status"], 0) + 1
                log.info("match: %s → %s (%.0f) %s",
                         entity.name, hit["status"], score, hit["topics"])
            else:
                entity.sanctions_status = "clean"
                entity.sanctions_detail = json.dumps(
                    {"datasets": [], "topics": [], "last_checked": now.isoformat()},
                    ensure_ascii=False,
                )
                counts["clean"] += 1
            entity.sanctions_synced_at = now
            db.commit()
        log.info("Terminé : %s", counts)
    finally:
        db.close()


if __name__ == "__main__":
    main()

"""Worker FACE.ai — orchestre l'analyse faciale et l'enrichissement Wikimedia.

Deux boucles indépendantes en threads séparés :

- **analyze_loop** : exécute `face_processor.process_pending` sur les images
  fraîchement scrapées (`analysis_status='pending'`). Polling 30 s.

- **enrich_loop** : pour les entités sans `wikidata_status='done'`, appelle
  `wikidata.enrich_entity`. Politesse : 1 s entre 2 appels Wikipedia/Wikidata,
  10 entités par cycle max. Polling 60 s.

Les deux boucles utilisent leurs propres sessions SQLAlchemy ; SQLite est
configuré avec `check_same_thread=False` côté `database.py`.
"""
from __future__ import annotations

import logging
import threading
import time

from sqlalchemy import select

from database import Entity, SessionLocal
from config import WUDD_BATCH_CYCLE_MINUTES
from backup import make_backup
from dedup import compute_missing_embeddings, dedup_all_entities
from entity_merge import auto_merge_by_qid
from face_processor import process_pending
from identity_audit import audit_all_entities, compute_missing_identities
from wikidata import enrich_entity
from worker_metrics import record_error, record_event, record_success
from wudd_articles_batch import run_batch as wudd_articles_run_batch
from wudd_sync import sync_persons as wudd_sync_persons

ANALYSIS_POLL_SECONDS = 30
ENRICH_POLL_SECONDS = 60
ENRICH_CYCLE_BATCH = 10
ENRICH_INTER_REQUEST_DELAY = 1.0
DEDUP_POLL_SECONDS = 45
IDENTITY_POLL_SECONDS = 60
# WUDD sync : 30 min — la liste change lentement (nouvelles entités au fil
# des articles ingérés par WUDD), pas besoin de poll agressif.
WUDD_SYNC_POLL_SECONDS = 1800
# Merge : 2 min, déclenche l'auto-fusion par QID dès qu'enrich_loop a
# attribué de nouveaux Wikidata QID identiques à 2 entités.
MERGE_POLL_SECONDS = 120
# Backup : 24h. Le worker vérifie chaque jour si un snapshot du jour existe
# déjà (cf. `backup.make_backup` idempotent). En cas de redémarrage juste
# après minuit, on a quand même le snapshot.
BACKUP_POLL_SECONDS = 86400

log = logging.getLogger("worker")


# ─────────────────────────────────────────────────────────────────
# Cycles unitaires extraits — chaque `_run_*_cycle()` est testable
# directement avec des mocks. Les `*_loop()` ci-dessous se contentent
# d'enrouler un cycle dans un `while True` + sleep.
# ─────────────────────────────────────────────────────────────────


def _run_analyze_cycle() -> dict:
    try:
        counts = process_pending(limit=20)
        if any(counts.values()):
            log.info("analyse: %s", counts)
        record_success("analyze", counts)
        return counts
    except Exception:
        log.exception("analyse erreur")
        record_error("analyze")
        return {}


def analyze_loop() -> None:
    while True:
        _run_analyze_cycle()
        time.sleep(ANALYSIS_POLL_SECONDS)


def _run_enrich_cycle() -> dict:
    cycle_summary = {"processed": 0, "not_person": 0}
    try:
        db = SessionLocal()
        try:
            ids = [
                row[0]
                for row in db.execute(
                    select(Entity.id)
                    .where(Entity.wikidata_status == "pending")
                    .limit(ENRICH_CYCLE_BATCH)
                )
            ]
        finally:
            db.close()

        for entity_id in ids:
            status = enrich_entity(entity_id)
            log.info("entité id=%s → wikidata_status=%s", entity_id, status)
            cycle_summary["processed"] += 1
            # Garde-fou périmètre PERSON : cf. entity_cleanup.purge_non_person.
            if status == "not_person":
                from entity_cleanup import purge_non_person

                r = purge_non_person(entity_id)
                log.info("purge not_person : %s", r)
                cycle_summary["not_person"] += 1
                record_event("not_person_purged")
            time.sleep(ENRICH_INTER_REQUEST_DELAY)
        record_success("enrich", cycle_summary)
        return cycle_summary
    except Exception:
        log.exception("enrich erreur")
        record_error("enrich")
        return cycle_summary


def enrich_loop() -> None:
    while True:
        _run_enrich_cycle()
        time.sleep(ENRICH_POLL_SECONDS)


def _run_dedup_cycle() -> dict:
    cycle_summary: dict = {"embeddings": 0}
    try:
        n = compute_missing_embeddings(limit=20)
        cycle_summary["embeddings"] = n
        if n > 0:
            log.info("embeddings calculés: %d", n)
            summary = dedup_all_entities()
            cycle_summary.update(summary)
            log.info("dedup: %s", summary)
        record_success("dedup", cycle_summary)
        return cycle_summary
    except Exception:
        log.exception("dedup erreur")
        record_error("dedup")
        return cycle_summary


def dedup_loop() -> None:
    while True:
        _run_dedup_cycle()
        time.sleep(DEDUP_POLL_SECONDS)


def _run_identity_cycle() -> dict:
    cycle_summary: dict = {}
    try:
        counts = compute_missing_identities(limit=20)
        cycle_summary["identities"] = counts
        if any(counts.values()):
            log.info("identités: %s", counts)
        # On ne ré-audite que si quelque chose a changé en DB.
        if counts.get("done") or counts.get("purged"):
            summary = audit_all_entities()
            cycle_summary["audit"] = summary
            log.info("audit identité: %s", summary)
        record_success("identity", cycle_summary)
        return cycle_summary
    except Exception:
        log.exception("identity erreur")
        record_error("identity")
        return cycle_summary


def identity_loop() -> None:
    while True:
        _run_identity_cycle()
        time.sleep(IDENTITY_POLL_SECONDS)


def _run_merge_cycle() -> dict:
    try:
        summary = auto_merge_by_qid()
        if summary["merged"] or summary.get("blocked"):
            log.info("auto-merge QID : %s", summary)
        # Événements rares — précisément ceux à surveiller après
        # l'incident 2026-05-11.
        for _ in range(summary.get("merged", 0)):
            record_event("merge_ok")
        for _ in range(summary.get("blocked", 0)):
            record_event("merge_blocked")
        record_success("merge", summary)
        return summary
    except Exception:
        log.exception("merge_loop erreur")
        record_error("merge")
        return {"merged": 0, "blocked": 0}


def merge_loop() -> None:
    while True:
        _run_merge_cycle()
        time.sleep(MERGE_POLL_SECONDS)


def _run_wudd_articles_batch_cycle() -> dict:
    try:
        summary = wudd_articles_run_batch()
        if summary["entities_processed"]:
            log.info("wudd articles batch : %s", {
                k: v for k, v in summary.items() if k != "details"
            })
        record_success("wudd_articles_batch", {
            k: v for k, v in summary.items() if k != "details"
        })
        return summary
    except Exception:
        log.exception("wudd_articles_batch_loop erreur")
        record_error("wudd_articles_batch")
        return {"entities_processed": 0}


def wudd_articles_batch_loop() -> None:
    """Pull WUDD articles par lots prioritisés (favoris d'abord, puis top mentions).

    Stratégie validée : éviter les pics de charge. ~120 entités/jour à la
    cadence par défaut (5 entités × 24 cycles d'1 h).
    """
    cycle_seconds = WUDD_BATCH_CYCLE_MINUTES * 60
    while True:
        _run_wudd_articles_batch_cycle()
        time.sleep(cycle_seconds)


def _run_wudd_sync_cycle() -> dict:
    try:
        counts = wudd_sync_persons()
        if counts.get("created", 0) or counts.get("image_added", 0):
            log.info("wudd sync : %s", counts)
        record_success("wudd_sync", counts)
        return counts
    except Exception:
        log.exception("wudd sync erreur")
        record_error("wudd_sync")
        return {}


def wudd_sync_loop() -> None:
    while True:
        _run_wudd_sync_cycle()
        time.sleep(WUDD_SYNC_POLL_SECONDS)


def _run_backup_cycle() -> dict:
    try:
        summary = make_backup()
        log.info("backup : %s", summary)
        record_success("backup", {"created": len(summary["created"])})
        return summary
    except Exception:
        log.exception("backup erreur")
        record_error("backup")
        return {"created": []}


def backup_loop() -> None:
    """Snapshot quotidien de la DB. Idempotent — overwrite si déjà présent
    pour aujourd'hui (utile quand le worker redémarre en milieu de journée
    après une ingestion conséquente)."""
    while True:
        _run_backup_cycle()
        time.sleep(BACKUP_POLL_SECONDS)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    log.info(
        "worker démarré — analyse %ss, enrich %ss, dedup %ss, identity %ss, "
        "merge %ss, wudd %ss, articles batch %s min",
        ANALYSIS_POLL_SECONDS,
        ENRICH_POLL_SECONDS,
        DEDUP_POLL_SECONDS,
        IDENTITY_POLL_SECONDS,
        MERGE_POLL_SECONDS,
        WUDD_SYNC_POLL_SECONDS,
        WUDD_BATCH_CYCLE_MINUTES,
    )

    threads = [
        threading.Thread(target=analyze_loop, daemon=True, name="analyze"),
        threading.Thread(target=enrich_loop, daemon=True, name="enrich"),
        threading.Thread(target=dedup_loop, daemon=True, name="dedup"),
        threading.Thread(target=identity_loop, daemon=True, name="identity"),
        threading.Thread(target=merge_loop, daemon=True, name="merge"),
        threading.Thread(target=wudd_sync_loop, daemon=True, name="wudd_sync"),
        threading.Thread(
            target=wudd_articles_batch_loop,
            daemon=True,
            name="wudd_articles_batch",
        ),
        threading.Thread(target=backup_loop, daemon=True, name="backup"),
    ]
    for t in threads:
        t.start()

    # Garde le main vivant ; SIGTERM viendra de Docker
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()

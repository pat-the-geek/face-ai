"""Métriques d'observabilité des boucles worker (persistées en DB).

Pourquoi DB et pas singleton in-memory : l'API et le worker tournent dans
**deux containers Docker distincts** (2 process Python). Un dict in-process
n'est pas visible depuis l'API, donc on persiste chaque événement dans la
table `worker_events` (v021).

Pourquoi : l'incident du 2026-05-11 (fusion catastrophique 3 entités → Altman)
n'a laissé aucune trace observable côté admin. Le worker tournait, les logs
défilaient, et personne ne pouvait dire « 3 fusions inattendues il y a 4 min ».
On expose ici :

- **per-loop** : `last_success_at`, `last_error_at`, sliding windows de
  succès / erreurs sur 24h, dernier résumé de cycle
- **global** : compteurs cumulés sur 24h pour les événements rares (merges,
  purges not_person) — leur explosion soudaine est le signal d'alerte
  typique

Rotation : un cleanup tourne en best-effort à chaque `record_*` (proba 1/100)
pour supprimer les events > 7 jours. Évite une boucle de rotation dédiée.
"""
from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, desc, func, select

from database import SessionLocal, WorkerEvent

log = logging.getLogger("worker_metrics")

_WINDOW = timedelta(hours=24)
_RETENTION = timedelta(days=7)
_ROTATE_PROBABILITY = 0.01  # ~1% des écritures déclenchent un cleanup


def _maybe_rotate() -> None:
    """Best-effort : supprime les events au-delà de la rétention.

    Probabiliste pour ne pas faire un DELETE à chaque écriture (un cycle
    worker écrit ~10 events/min ; on rotate ~1 fois toutes les 1000 events).
    """
    if random.random() > _ROTATE_PROBABILITY:
        return
    cutoff = datetime.utcnow() - _RETENTION
    db = SessionLocal()
    try:
        db.execute(delete(WorkerEvent).where(WorkerEvent.ts < cutoff))
        db.commit()
    except Exception:
        log.exception("rotate worker_events erreur")
    finally:
        db.close()


def _record(kind: str, loop_name: str | None, summary: Any | None) -> None:
    db = SessionLocal()
    try:
        db.add(WorkerEvent(
            ts=datetime.utcnow(),
            kind=kind,
            loop_name=loop_name,
            summary=json.dumps(summary, default=str) if summary is not None else None,
        ))
        db.commit()
    except Exception:
        # On ne veut JAMAIS faire planter une boucle worker à cause d'une
        # écriture de métrique. Logguer et oublier.
        log.exception("record worker event erreur")
    finally:
        db.close()
    _maybe_rotate()


def record_success(loop_name: str, summary: Any | None = None) -> None:
    """À appeler en fin de cycle réussi, qu'il ait fait ou non du travail."""
    _record("success", loop_name, summary)


def record_error(loop_name: str) -> None:
    _record("error", loop_name, None)


def record_event(event_name: str, count: int = 1) -> None:
    """Événement métier (`merge_ok`, `merge_blocked`, `not_person_purged`)."""
    for _ in range(count):
        _record(event_name, None, None)


def get_status() -> dict:
    """Snapshot complet pour l'endpoint admin.

    Une seule transaction lit toutes les agrégations 24h pour rester rapide
    même quand worker_events grossit (10k events sur 24h max en charge).
    """
    now = datetime.utcnow()
    window_start = now - _WINDOW
    db = SessionLocal()
    try:
        # Boucles : pour chaque loop_name, compte success/error sur 24h
        # + dernière exécution réussie/erreur + dernier summary.
        loop_names = [
            r[0]
            for r in db.execute(
                select(WorkerEvent.loop_name)
                .where(WorkerEvent.loop_name.is_not(None))
                .where(WorkerEvent.kind.in_(("success", "error")))
                .group_by(WorkerEvent.loop_name)
            )
        ]
        loops_out: dict[str, dict] = {}
        for name in loop_names:
            successes_24h = db.scalar(
                select(func.count())
                .select_from(WorkerEvent)
                .where(WorkerEvent.loop_name == name)
                .where(WorkerEvent.kind == "success")
                .where(WorkerEvent.ts >= window_start)
            ) or 0
            errors_24h = db.scalar(
                select(func.count())
                .select_from(WorkerEvent)
                .where(WorkerEvent.loop_name == name)
                .where(WorkerEvent.kind == "error")
                .where(WorkerEvent.ts >= window_start)
            ) or 0
            last_success = db.execute(
                select(WorkerEvent.ts, WorkerEvent.summary)
                .where(WorkerEvent.loop_name == name)
                .where(WorkerEvent.kind == "success")
                .order_by(desc(WorkerEvent.ts))
                .limit(1)
            ).first()
            last_error = db.execute(
                select(WorkerEvent.ts)
                .where(WorkerEvent.loop_name == name)
                .where(WorkerEvent.kind == "error")
                .order_by(desc(WorkerEvent.ts))
                .limit(1)
            ).first()
            loops_out[name] = {
                "last_success_at": (
                    last_success[0].isoformat() + "Z" if last_success else None
                ),
                "last_error_at": (
                    last_error[0].isoformat() + "Z" if last_error else None
                ),
                "successes_24h": successes_24h,
                "errors_24h": errors_24h,
                "last_summary": (
                    json.loads(last_success[1])
                    if last_success and last_success[1] else None
                ),
            }

        # Événements métier (non-success/error)
        event_rows = db.execute(
            select(WorkerEvent.kind, func.count())
            .where(WorkerEvent.kind.notin_(("success", "error")))
            .where(WorkerEvent.ts >= window_start)
            .group_by(WorkerEvent.kind)
        ).all()
        events_out = {kind: int(n) for kind, n in event_rows}

        return {
            "now": now.isoformat() + "Z",
            "loops": loops_out,
            "events_24h": events_out,
        }
    finally:
        db.close()


def reset_for_tests() -> None:
    """Vide la table worker_events. Pour les tests uniquement."""
    db = SessionLocal()
    try:
        db.execute(delete(WorkerEvent))
        db.commit()
    finally:
        db.close()

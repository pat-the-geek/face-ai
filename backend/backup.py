"""Snapshot quotidien de `face_ai.db` avec rotation hiérarchique.

Pourquoi : l'incident du 2026-05-11 (fusion catastrophique 3 entités → Altman)
n'a été récupérable que grâce à un `cp` manuel pré-restauration. Sans backup
quotidien, une corruption silencieuse passée inaperçue pendant > 1 cycle
worker aurait été impossible à annuler proprement.

Stratégie :
- `sqlite3 .backup` API native (online-safe, pas de WAL flush requis,
  pas de file lock côté écrivains)
- gzip pour le stockage (les DB SQLite compressent ~5×)
- Rotation : 7 quotidiens + 4 hebdomadaires + 12 mensuels = 23 fichiers max
  - daily-YYYY-MM-DD.db.gz (7 derniers jours)
  - weekly-YYYY-Www.db.gz (4 dernières semaines ISO)
  - monthly-YYYY-MM.db.gz (12 derniers mois)

Idempotent : `make_backup` overwrite si le fichier du jour existe déjà.
La rotation utilise la date du nom de fichier comme source de vérité,
pas `os.stat` — robuste aux changements d'horloge système.
"""
from __future__ import annotations

import gzip
import logging
import re
import shutil
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from config import DB_PATH

log = logging.getLogger("backup")

BACKUP_DIR = DB_PATH.parent / "backups"

KEEP_DAILY = 7
KEEP_WEEKLY = 4
KEEP_MONTHLY = 12

_RX = {
    "daily": re.compile(r"^daily-(\d{4}-\d{2}-\d{2})\.db\.gz$"),
    "weekly": re.compile(r"^weekly-(\d{4})-W(\d{2})\.db\.gz$"),
    "monthly": re.compile(r"^monthly-(\d{4}-\d{2})\.db\.gz$"),
}


def _today() -> date:
    return date.today()


def _backup_paths(d: date) -> dict[str, Path]:
    """Calcule les chemins des 3 backups potentiels pour une date donnée.

    Le weekly est créé uniquement le lundi (ISO weekday 1), le monthly le 1er
    du mois. Le daily est créé tous les jours.
    """
    iso_year, iso_week, iso_weekday = d.isocalendar()
    paths = {"daily": BACKUP_DIR / f"daily-{d.isoformat()}.db.gz"}
    if iso_weekday == 1:
        paths["weekly"] = BACKUP_DIR / f"weekly-{iso_year}-W{iso_week:02d}.db.gz"
    if d.day == 1:
        paths["monthly"] = BACKUP_DIR / f"monthly-{d.strftime('%Y-%m')}.db.gz"
    return paths


def _snapshot_db(target: Path) -> int:
    """Snapshot online via `sqlite3 .backup` puis gzip.

    Retourne la taille compressée en octets.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_raw = target.with_suffix(".db.tmp")
    src = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(tmp_raw))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    try:
        with open(tmp_raw, "rb") as fin, gzip.open(target, "wb", compresslevel=6) as fout:
            shutil.copyfileobj(fin, fout)
    finally:
        tmp_raw.unlink(missing_ok=True)
    return target.stat().st_size


def _parse_existing(kind: str) -> list[tuple[date, Path]]:
    """Liste les backups d'un type, triés par date décroissante."""
    if not BACKUP_DIR.exists():
        return []
    rx = _RX[kind]
    out: list[tuple[date, Path]] = []
    for p in BACKUP_DIR.iterdir():
        m = rx.match(p.name)
        if not m:
            continue
        try:
            if kind == "daily":
                d = date.fromisoformat(m.group(1))
            elif kind == "weekly":
                d = date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
            else:  # monthly
                d = date.fromisoformat(m.group(1) + "-01")
        except ValueError:
            continue
        out.append((d, p))
    out.sort(key=lambda t: t[0], reverse=True)
    return out


def _rotate() -> dict[str, int]:
    """Supprime les backups au-delà de la fenêtre de rétention.

    Retourne un compte par type : `{daily: N, weekly: N, monthly: N}`.
    """
    keep = {"daily": KEEP_DAILY, "weekly": KEEP_WEEKLY, "monthly": KEEP_MONTHLY}
    removed = {"daily": 0, "weekly": 0, "monthly": 0}
    for kind, k in keep.items():
        existing = _parse_existing(kind)
        for _, path in existing[k:]:
            try:
                path.unlink()
                removed[kind] += 1
            except OSError:
                log.warning("backup : impossible de supprimer %s", path)
    return removed


def make_backup(today: date | None = None) -> dict:
    """Crée les backups dus aujourd'hui + applique la rotation.

    Idempotent : si le fichier du jour existe déjà, il est overwrité (snapshot
    plus récent gagne — utile en cas de relance manuelle après ingestion).
    """
    d = today or _today()
    paths = _backup_paths(d)
    created: list[dict] = []
    for kind, target in paths.items():
        size = _snapshot_db(target)
        created.append({"kind": kind, "path": str(target), "size": size})
        log.info("backup : %s (%d octets)", target.name, size)
    rotated = _rotate()
    return {
        "date": d.isoformat(),
        "created": created,
        "rotated": rotated,
    }


def restore_backup(filename: str) -> dict:
    """Restaure un snapshot SQLite.

    Étapes :
    1. Snapshot de l'état COURANT en `pre-restore-YYYY-MM-DD-HHMMSS.db.gz`
       (rollback possible si la restauration tombe à côté)
    2. Décompression du fichier demandé dans un tmp
    3. Vérification que c'est bien une DB SQLite valide (premier `magic`
       byte + ouverture en lecture seule)
    4. Atomic rename : remplace `face_ai.db` par le contenu décompressé
    5. **Important** : SQLAlchemy ne recharge pas l'engine — l'API et le
       worker doivent être redémarrés manuellement après ça
       (`docker compose restart api worker`). On le signale dans la
       réponse.

    Refuse :
    - fichier hors `BACKUP_DIR` (path traversal)
    - fichier inexistant
    - fichier qui décompresse en moins de 1 Kio (= corrompu)
    """
    target = BACKUP_DIR / filename
    try:
        # Empêche `../../etc/passwd.gz`
        target.resolve().relative_to(BACKUP_DIR.resolve())
    except ValueError:
        raise ValueError(f"backup hors du répertoire autorisé : {filename}")
    if not target.exists():
        raise FileNotFoundError(f"backup introuvable : {filename}")

    # 1. Snapshot pré-restauration de l'état courant
    pre_restore = BACKUP_DIR / (
        f"pre-restore-{datetime.now().strftime('%Y-%m-%d-%H%M%S')}.db.gz"
    )
    pre_restore_size = _snapshot_db(pre_restore)

    # 2. Décompression dans un tmp
    tmp_db = DB_PATH.with_suffix(".db.restoring")
    with gzip.open(target, "rb") as fin, open(tmp_db, "wb") as fout:
        shutil.copyfileobj(fin, fout)

    # 3. Vérification : on essaie d'ouvrir en lecture seule
    if tmp_db.stat().st_size < 1024:
        tmp_db.unlink(missing_ok=True)
        raise ValueError(f"backup décompressé < 1 Kio, probablement corrompu : {filename}")
    try:
        conn = sqlite3.connect(f"file:{tmp_db}?mode=ro", uri=True)
        conn.execute("PRAGMA integrity_check").fetchone()
        conn.close()
    except sqlite3.DatabaseError as e:
        tmp_db.unlink(missing_ok=True)
        raise ValueError(f"backup invalide : {e}")

    # 4. Atomic replace
    tmp_db.replace(DB_PATH)

    log.info("restore : %s → %s (pré-snapshot : %s)", target.name, DB_PATH, pre_restore.name)

    return {
        "restored_from": str(target),
        "pre_restore_snapshot": str(pre_restore),
        "pre_restore_size": pre_restore_size,
        "warning": (
            "L'API et le worker doivent être redémarrés manuellement "
            "(docker compose restart api worker) pour que l'engine "
            "SQLAlchemy recharge la nouvelle DB."
        ),
    }


def list_backups() -> dict:
    """Inventaire des backups présents, par type."""
    out: dict = {}
    for kind in ("daily", "weekly", "monthly"):
        out[kind] = [
            {
                "date": d.isoformat(),
                "path": str(p),
                "size": p.stat().st_size if p.exists() else None,
            }
            for d, p in _parse_existing(kind)
        ]
    return out


if __name__ == "__main__":
    import json

    print(json.dumps(make_backup(), indent=2))

"""Tests du module backup.

Cible : verrouiller le comportement de rotation et l'idempotence. Le
snapshot SQLite lui-même est testé via création d'une vraie DB de test
(la fixture `_isolate_runtime` redirige `FACE_AI_DB` vers un tmp).
"""
from __future__ import annotations

import gzip
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch


def _list_backup_names(backup_dir: Path, kind: str | None = None) -> list[str]:
    if not backup_dir.exists():
        return []
    names = sorted(p.name for p in backup_dir.iterdir())
    if kind is None:
        return names
    return [n for n in names if n.startswith(f"{kind}-")]


class TestSnapshot:
    def test_creates_daily_snapshot(self, tmp_path, monkeypatch):
        """Snapshot quotidien créé et gzippé proprement."""
        # Setup : redirige BACKUP_DIR vers tmp
        from backup import BACKUP_DIR
        backup_root = tmp_path / "backups"
        monkeypatch.setattr("backup.BACKUP_DIR", backup_root)

        from backup import make_backup

        result = make_backup(today=date(2026, 5, 14))  # un mercredi (pas weekly/monthly)
        assert len(result["created"]) == 1
        assert result["created"][0]["kind"] == "daily"
        assert result["created"][0]["size"] > 0

        # Le fichier doit exister et être un gzip valide
        target = Path(result["created"][0]["path"])
        assert target.exists()
        with gzip.open(target, "rb") as f:
            magic = f.read(16)
        assert magic.startswith(b"SQLite format 3")  # snapshot DB valide

    def test_monday_creates_weekly(self, tmp_path, monkeypatch):
        """Lundi → daily + weekly."""
        monkeypatch.setattr("backup.BACKUP_DIR", tmp_path / "backups")
        from backup import make_backup

        result = make_backup(today=date(2026, 5, 11))  # un lundi
        kinds = {c["kind"] for c in result["created"]}
        assert kinds == {"daily", "weekly"}

    def test_first_of_month_creates_monthly(self, tmp_path, monkeypatch):
        """1er du mois → daily + monthly (+ weekly si lundi)."""
        monkeypatch.setattr("backup.BACKUP_DIR", tmp_path / "backups")
        from backup import make_backup

        # 2026-06-01 est un lundi → 3 backups
        result = make_backup(today=date(2026, 6, 1))
        kinds = {c["kind"] for c in result["created"]}
        assert kinds == {"daily", "weekly", "monthly"}

    def test_idempotent_overwrite(self, tmp_path, monkeypatch):
        """Relancer le même jour overwrite le snapshot (pas de doublon)."""
        monkeypatch.setattr("backup.BACKUP_DIR", tmp_path / "backups")
        from backup import make_backup

        d = date(2026, 5, 14)
        make_backup(today=d)
        make_backup(today=d)
        files = list((tmp_path / "backups").iterdir())
        assert len(files) == 1
        assert files[0].name == "daily-2026-05-14.db.gz"


class TestRotation:
    def test_daily_rotation_keeps_7(self, tmp_path, monkeypatch):
        """Au-delà de 7 dailies, les plus anciens sont supprimés."""
        monkeypatch.setattr("backup.BACKUP_DIR", tmp_path / "backups")
        from backup import make_backup

        for i in range(10):
            make_backup(today=date(2026, 1, 1) + timedelta(days=i))

        dailies = _list_backup_names(tmp_path / "backups", "daily")
        assert len(dailies) == 7
        # Les 7 plus récents (5 au 10 janvier)
        assert dailies[0] == "daily-2026-01-04.db.gz"
        assert dailies[-1] == "daily-2026-01-10.db.gz"

    def test_weekly_rotation_keeps_4(self, tmp_path, monkeypatch):
        """Au-delà de 4 weeklies, les plus anciens sont supprimés."""
        monkeypatch.setattr("backup.BACKUP_DIR", tmp_path / "backups")
        from backup import make_backup

        # 6 lundis consécutifs
        first_monday = date(2026, 1, 5)  # lundi
        for w in range(6):
            make_backup(today=first_monday + timedelta(weeks=w))

        weeklies = _list_backup_names(tmp_path / "backups", "weekly")
        assert len(weeklies) == 4
        # Les 4 weeks ISO les plus récentes (W04..W07 de 2026)
        assert weeklies[0] == "weekly-2026-W04.db.gz"
        assert weeklies[-1] == "weekly-2026-W07.db.gz"

    def test_monthly_rotation_keeps_12(self, tmp_path, monkeypatch):
        """Au-delà de 12 monthlies, les plus anciens sont supprimés."""
        monkeypatch.setattr("backup.BACKUP_DIR", tmp_path / "backups")
        from backup import make_backup

        # 14 mois consécutifs (1er du mois)
        for m in range(14):
            year = 2025 + (m // 12)
            month = (m % 12) + 1
            make_backup(today=date(year, month, 1))

        monthlies = _list_backup_names(tmp_path / "backups", "monthly")
        assert len(monthlies) == 12

    def test_different_kinds_dont_interfere(self, tmp_path, monkeypatch):
        """Daily/weekly/monthly comptent séparément, pas dans un même seau."""
        monkeypatch.setattr("backup.BACKUP_DIR", tmp_path / "backups")
        from backup import make_backup

        # Un 1er du mois lundi → 3 backups en un coup
        make_backup(today=date(2026, 6, 1))
        all_files = _list_backup_names(tmp_path / "backups")
        assert len(all_files) == 3
        assert any("daily-" in f for f in all_files)
        assert any("weekly-" in f for f in all_files)
        assert any("monthly-" in f for f in all_files)


class TestListBackups:
    def test_empty_when_no_backup_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr("backup.BACKUP_DIR", tmp_path / "nonexistent")
        from backup import list_backups

        assert list_backups() == {"daily": [], "weekly": [], "monthly": []}

    def test_returns_sorted_descending(self, tmp_path, monkeypatch):
        """Le plus récent en premier — pratique pour l'UI."""
        monkeypatch.setattr("backup.BACKUP_DIR", tmp_path / "backups")
        from backup import list_backups, make_backup

        make_backup(today=date(2026, 5, 14))
        make_backup(today=date(2026, 5, 15))
        make_backup(today=date(2026, 5, 13))

        result = list_backups()
        assert [b["date"] for b in result["daily"]] == [
            "2026-05-15", "2026-05-14", "2026-05-13",
        ]


class TestRestore:
    """Tests isolés sur une DB tmp pour ne pas perturber la DB de test
    partagée par conftest (SQLAlchemy garde un engine ouvert dessus)."""

    @staticmethod
    def _isolated_setup(tmp_path, monkeypatch):
        """Crée une DB SQLite indépendante + redirige `backup.BACKUP_DIR`
        et `backup.DB_PATH` vers ce sandbox."""
        import sqlite3
        backup_dir = tmp_path / "backups"
        sandbox_db = tmp_path / "sandbox.db"
        # DB minimale mais valide
        conn = sqlite3.connect(str(sandbox_db))
        conn.execute("CREATE TABLE _seed (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO _seed (name) VALUES ('original')")
        conn.commit()
        conn.close()
        monkeypatch.setattr("backup.BACKUP_DIR", backup_dir)
        monkeypatch.setattr("backup.DB_PATH", sandbox_db)
        return sandbox_db

    def test_restore_replaces_db(self, tmp_path, monkeypatch):
        """La restauration écrase la DB sandbox avec le contenu du backup."""
        sandbox = self._isolated_setup(tmp_path, monkeypatch)
        from backup import make_backup, restore_backup
        import sqlite3

        # 1. Snapshot de l'état initial
        make_backup(today=date(2026, 5, 14))
        backup_name = "daily-2026-05-14.db.gz"

        # 2. Modifier la DB (ajouter du contenu) pour que le restore se voie
        conn = sqlite3.connect(str(sandbox))
        conn.execute("CREATE TABLE _post_backup_marker (x INTEGER)")
        conn.commit()
        conn.close()

        # 3. Restaurer → le marker post-backup disparaît
        result = restore_backup(backup_name)
        assert "pre_restore_snapshot" in result
        assert "warning" in result

        conn = sqlite3.connect(str(sandbox))
        markers = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='_post_backup_marker'"
        ).fetchall()
        seeds = conn.execute("SELECT name FROM _seed").fetchall()
        conn.close()
        assert markers == []  # post-backup marker absent
        assert seeds == [("original",)]  # seed initial restauré

    def test_restore_unknown_filename_404(self, tmp_path, monkeypatch):
        self._isolated_setup(tmp_path, monkeypatch)
        from backup import restore_backup

        import pytest

        with pytest.raises(FileNotFoundError):
            restore_backup("daily-2099-12-31.db.gz")

    def test_restore_rejects_path_traversal(self, tmp_path, monkeypatch):
        """Empêche les accès en dehors de BACKUP_DIR."""
        self._isolated_setup(tmp_path, monkeypatch)
        from backup import restore_backup

        import pytest

        with pytest.raises(ValueError, match="hors du r"):
            restore_backup("../../../etc/passwd.gz")

    def test_restore_rejects_corrupted_backup(self, tmp_path, monkeypatch):
        """Un fichier trop petit (< 1 Kio décompressé) est rejeté."""
        self._isolated_setup(tmp_path, monkeypatch)
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir(exist_ok=True)

        import gzip
        fake_path = backup_dir / "daily-2026-05-14.db.gz"
        with gzip.open(fake_path, "wb") as f:
            f.write(b"bad-data")

        from backup import restore_backup
        import pytest
        with pytest.raises(ValueError, match="corrompu|invalide"):
            restore_backup("daily-2026-05-14.db.gz")

    def test_restore_creates_pre_restore_snapshot(self, tmp_path, monkeypatch):
        """Avant de restaurer, on snapshot l'état courant pour rollback."""
        self._isolated_setup(tmp_path, monkeypatch)
        from backup import make_backup, restore_backup

        make_backup(today=date(2026, 5, 14))
        result = restore_backup("daily-2026-05-14.db.gz")
        snap_path = Path(result["pre_restore_snapshot"])
        assert snap_path.exists()
        assert snap_path.name.startswith("pre-restore-")


class TestApiEndpoints:
    def test_backup_now_creates_snapshot(self, tmp_path, monkeypatch, client):
        monkeypatch.setattr("backup.BACKUP_DIR", tmp_path / "backups")
        r = client.post("/admin/backup-now")
        assert r.status_code == 200
        data = r.json()
        assert data["created"]
        assert (tmp_path / "backups").exists()

    def test_list_endpoint(self, tmp_path, monkeypatch, client):
        monkeypatch.setattr("backup.BACKUP_DIR", tmp_path / "backups")
        from backup import make_backup

        make_backup(today=date(2026, 5, 14))
        r = client.get("/admin/backups")
        assert r.status_code == 200
        data = r.json()
        assert len(data["daily"]) == 1

    def test_restore_endpoint_404_on_missing(self, tmp_path, monkeypatch, client):
        monkeypatch.setattr("backup.BACKUP_DIR", tmp_path / "backups")
        r = client.post("/admin/restore-backup?filename=daily-2099-12-31.db.gz")
        assert r.status_code == 404

    def test_restore_endpoint_400_on_bad_path(self, tmp_path, monkeypatch, client):
        monkeypatch.setattr("backup.BACKUP_DIR", tmp_path / "backups")
        r = client.post("/admin/restore-backup?filename=../etc/passwd.gz")
        assert r.status_code == 400

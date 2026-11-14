"""Uji backup dan restore (butuh PostgreSQL uji: FITZONE_TEST_DB=1 dan PG_ADMIN_USER/PG_ADMIN_PASSWORD)."""
import json
import os
from datetime import datetime, timedelta

import pytest

from etl import backup, config, db, run_pipeline

pytestmark = pytest.mark.skipif(os.getenv("FITZONE_TEST_DB") != "1", reason="set FITZONE_TEST_DB=1")


@pytest.fixture(autouse=True)
def folder_uji(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(config, "DATA_LAKE_DIR", tmp_path / "lake")
    (tmp_path / "lake" / "raw" / "source=gym_csv").mkdir(parents=True)
    (tmp_path / "lake" / "raw" / "source=gym_csv" / "a.csv").write_text("x,y\n1,2\n")
    run_pipeline.init_db()


def jumlah(sql):
    conn = db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchone()[0]
    finally:
        conn.close()


def test_backup_lengkap_dan_uji_restore_lulus():
    hasil = backup.run_all()
    assert hasil["status"] == "LULUS"
    f = backup.BACKUP_DIR / hasil["folder"]
    m = json.loads((f / "manifest.json").read_text())
    assert (f / backup.DUMP_FILE).exists() and (f / backup.RAW_FILE).exists()
    assert m["files"][backup.RAW_FILE]["n_files"] == 1
    assert "dw.dim_member" in m["table_counts"]
    assert jumlah(f"SELECT restore_status FROM etl_audit.backup_log WHERE folder='{hasil['folder']}'") == "LULUS"


def test_backup_rusak_terdeteksi():
    folder = backup.backup_database()
    backup.backup_raw(folder)
    with open(backup.BACKUP_DIR / folder / backup.DUMP_FILE, "ab") as fh:
        fh.write(b"rusak")
    with pytest.raises(RuntimeError, match="checksum"):
        backup.verify_restore(folder)
    assert jumlah(f"SELECT status FROM etl_audit.backup_log WHERE folder='{folder}'") == "FAILED"


def test_restore_wajib_konfirmasi():
    folder = backup.backup_database()
    with pytest.raises(SystemExit):
        backup.restore(folder, config.DW_NAME, ya=False)


def test_retensi_7_hari_dan_mingguan():
    now = datetime(2026, 11, 14, 12, 0)
    for d in (0, 1, 3, 6, 8, 9, 10, 15, 16, 40):
        (backup.BACKUP_DIR / (now - timedelta(days=d)).strftime(backup.FOLDER_FMT)).mkdir(parents=True)
    dihapus = backup.apply_retention(now)
    sisa = backup.list_folders()
    assert len([f for f in sisa if now - datetime.strptime(f, backup.FOLDER_FMT) <= timedelta(days=7)]) == 4
    assert (now - timedelta(days=40)).strftime(backup.FOLDER_FMT) in dihapus
    assert now.strftime(backup.FOLDER_FMT) in sisa

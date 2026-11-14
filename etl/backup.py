"""Backup dan Disaster Recovery FitZone.

Yang dibackup setiap hari (DAG fitzone_backup_daily, pukul 01:00 WIB):
  1. Database data warehouse  -> pg_dump format custom  (fitzone_dw.dump)
  2. Data Lake raw + model ML -> arsip tar.gz            (data_lake_raw.tar.gz)
  3. manifest.json            -> sha256, ukuran, jumlah baris setiap tabel saat backup

Lokasi : folder backups/<YYYYMMDD_HHMMSS>/ (dipasang ke container). Salinan kedua opsional ke
         BACKUP_OFFSITE_DIR (misalnya hard disk eksternal / folder yang disinkron ke cloud).
Retensi: semua backup 7 hari terakhir + 1 backup per minggu selama 4 minggu.
Uji    : setiap backup langsung di-restore ke database sementara fitzone_restore_test, jumlah baris
         setiap tabel dibandingkan dengan manifest, lalu database sementara dihapus.

Perintah:
  python -m etl.backup run                       # backup + uji restore + retensi (sama dengan DAG)
  python -m etl.backup list                      # daftar backup
  python -m etl.backup verify  [--folder NAMA]   # uji restore backup tertentu (default terbaru)
  python -m etl.backup restore --folder NAMA --target fitzone_dw --ya   # pemulihan sungguhan
"""
import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import tarfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import psycopg2

from etl import config, db

log = logging.getLogger("fitzone.backup")

BACKUP_DIR = Path(os.getenv("BACKUP_DIR") or (config.PROJECT_ROOT / "backups"))
OFFSITE_DIR = Path(os.environ["BACKUP_OFFSITE_DIR"]) if os.getenv("BACKUP_OFFSITE_DIR") else None
RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS") or 7)
WEEKLY_KEEP = int(os.getenv("BACKUP_WEEKLY_KEEP") or 4)
RESTORE_TEST_DB = "fitzone_restore_test"
DUMP_FILE = "fitzone_dw.dump"
RAW_FILE = "data_lake_raw.tar.gz"
FOLDER_FMT = "%Y%m%d_%H%M%S"


# ------------------------------------------------------------------ koneksi admin
def _admin_env() -> dict:
    env = dict(os.environ)
    env.update(PGHOST=str(config.DW_HOST), PGPORT=str(config.DW_PORT),
               PGUSER=os.getenv("PG_ADMIN_USER") or "postgres")
    if os.getenv("PG_ADMIN_PASSWORD"):
        env["PGPASSWORD"] = os.environ["PG_ADMIN_PASSWORD"]
    return env


def _admin_connect(dbname: str):
    e = _admin_env()
    conn = psycopg2.connect(host=e["PGHOST"], port=e["PGPORT"], user=e["PGUSER"],
                            password=e.get("PGPASSWORD"), dbname=dbname, connect_timeout=10)
    conn.autocommit = True
    return conn


_BIN_CACHE: dict = {}


def _pg_bin(name: str) -> str:
    """Pilih pg_dump/pg_restore yang versinya SAMA dengan server.

    Image Airflow bisa membawa beberapa versi klien (misalnya 16 dan 17). Dump dari klien 17
    berisi perintah (SET transaction_timeout) yang tidak dikenal server 16, sehingga restore gagal.
    """
    if name in _BIN_CACHE:
        return _BIN_CACHE[name]
    pilihan = name
    if os.getenv("PG_BIN_DIR"):
        pilihan = str(Path(os.environ["PG_BIN_DIR"]) / name)
    else:
        try:
            conn = _admin_connect("postgres")
            major = conn.server_version // 10000
            conn.close()
            kandidat = Path(f"/usr/lib/postgresql/{major}/bin/{name}")
            if kandidat.exists():
                pilihan = str(kandidat)
            else:
                log.warning("Klien %s versi %s tidak ditemukan, memakai %s dari PATH", name, major, name)
        except Exception as exc:  # server belum bisa dihubungi: pakai dari PATH
            log.warning("Tidak bisa membaca versi server (%s), memakai %s dari PATH", exc, name)
    _BIN_CACHE[name] = pilihan
    return pilihan


def _run(cmd: list[str]):
    cmd = [_pg_bin(cmd[0]) if cmd[0] in ("pg_dump", "pg_restore") else cmd[0], *cmd[1:]]
    log.info("Menjalankan %s", cmd[0])
    res = subprocess.run(cmd, env=_admin_env(), capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"{cmd[0]} gagal: {res.stderr.strip()[:800]}")
    return res


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def table_counts(dbname: str) -> dict:
    """Jumlah baris setiap tabel di schema stg, dw, etl_audit (dipakai untuk membandingkan restore)."""
    conn = _admin_connect(dbname)
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT schemaname, tablename FROM pg_tables
                           WHERE schemaname IN ('stg','dw','etl_audit') ORDER BY 1, 2""")
            tabel = cur.fetchall()
            hasil = {}
            for s, t in tabel:
                if (s, t) == ("etl_audit", "backup_log"):
                    continue  # tabel ini terus berubah saat backup berjalan
                cur.execute(f'SELECT COUNT(*) FROM "{s}"."{t}"')
                hasil[f"{s}.{t}"] = cur.fetchone()[0]
            return hasil
    finally:
        conn.close()


# ------------------------------------------------------------------ log ke database
def _ensure_log():
    with db.transaction() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS etl_audit.backup_log (
                backup_id       SERIAL PRIMARY KEY,
                folder          TEXT NOT NULL UNIQUE,
                started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                finished_at     TIMESTAMPTZ,
                status          TEXT NOT NULL DEFAULT 'RUNNING',
                db_dump_mb      NUMERIC(10,2),
                raw_archive_mb  NUMERIC(10,2),
                n_tables        INT,
                total_rows      BIGINT,
                restore_status  TEXT,
                restore_sec     NUMERIC(10,2),
                deleted_old     INT,
                notes           TEXT
            )""")
        cur.execute("""DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dashboard_ro') THEN
                GRANT SELECT ON etl_audit.backup_log TO dashboard_ro;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='bi_analyst') THEN
                GRANT SELECT ON etl_audit.backup_log TO bi_analyst;
            END IF; END $$""")


def _log(folder: str, **fields):
    _ensure_log()
    with db.transaction() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO etl_audit.backup_log (folder) VALUES (%s) ON CONFLICT (folder) DO NOTHING",
                    (folder,))
        if fields:
            sets = ", ".join(f"{k} = %s" for k in fields)
            cur.execute(f"UPDATE etl_audit.backup_log SET {sets} WHERE folder = %s", (*fields.values(), folder))


# ------------------------------------------------------------------ langkah backup
def backup_database(now: datetime | None = None) -> str:
    """pg_dump database DWH ke folder baru. Mengembalikan nama folder."""
    now = now or datetime.now()
    folder = now.strftime(FOLDER_FMT)
    target = BACKUP_DIR / folder
    target.mkdir(parents=True, exist_ok=False)
    _log(folder)
    try:
        t0 = time.perf_counter()
        counts = table_counts(config.DW_NAME)
        _run(["pg_dump", "--format=custom", "--compress=6", "--dbname", config.DW_NAME,
              "--file", str(target / DUMP_FILE)])
        dump = target / DUMP_FILE
        manifest = {
            "folder": folder,
            "created_at": now.isoformat(timespec="seconds"),
            "database": config.DW_NAME,
            "pg_dump_sec": round(time.perf_counter() - t0, 2),
            "files": {DUMP_FILE: {"bytes": dump.stat().st_size, "sha256": _sha256(dump)}},
            "table_counts": counts,
        }
        (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        _log(folder, db_dump_mb=round(dump.stat().st_size / 1e6, 2), n_tables=len(counts),
             total_rows=sum(counts.values()))
        log.info("Backup database %s: %d tabel, %d baris, %.2f MB", folder, len(counts),
                 sum(counts.values()), dump.stat().st_size / 1e6)
        return folder
    except Exception as exc:
        _log(folder, status="FAILED", finished_at=datetime.now(), notes=f"pg_dump: {exc}"[:1000])
        raise


def backup_raw(folder: str) -> Path:
    """Arsipkan Data Lake raw (file sumber asli) dan model ML ke tar.gz."""
    target = BACKUP_DIR / folder
    arsip = target / RAW_FILE
    try:
        n_file = 0
        with tarfile.open(arsip, "w:gz", compresslevel=6) as tar:
            for sub in ("raw", "models"):
                src = config.DATA_LAKE_DIR / sub
                if src.exists():
                    tar.add(src, arcname=f"data_lake/{sub}")
                    n_file += sum(1 for p in src.rglob("*") if p.is_file())
        m = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        m["files"][RAW_FILE] = {"bytes": arsip.stat().st_size, "sha256": _sha256(arsip), "n_files": n_file}
        (target / "manifest.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
        _log(folder, raw_archive_mb=round(arsip.stat().st_size / 1e6, 2))
        log.info("Backup Data Lake %s: %d file, %.2f MB", folder, n_file, arsip.stat().st_size / 1e6)
        if OFFSITE_DIR:
            shutil.copytree(target, OFFSITE_DIR / folder, dirs_exist_ok=True)
            log.info("Salinan kedua disimpan di %s", OFFSITE_DIR / folder)
        return arsip
    except Exception as exc:
        _log(folder, status="FAILED", finished_at=datetime.now(), notes=f"arsip raw: {exc}"[:1000])
        raise


def _drop_db(name: str):
    conn = _admin_connect("postgres")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (name,))
            cur.execute(f'DROP DATABASE IF EXISTS "{name}"')
    finally:
        conn.close()


def verify_restore(folder: str | None = None) -> dict:
    """Uji restore: cek checksum, restore dump ke database sementara, bandingkan jumlah baris."""
    folder = folder or latest_folder()
    target = BACKUP_DIR / folder
    m = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    t0 = time.perf_counter()
    masalah = []
    try:
        for nama, info in m["files"].items():
            if _sha256(target / nama) != info["sha256"]:
                masalah.append(f"checksum {nama} tidak cocok")
        if (target / RAW_FILE).exists():
            with tarfile.open(target / RAW_FILE, "r:gz") as tar:
                n = sum(1 for x in tar.getmembers() if x.isfile())
            if n != m["files"][RAW_FILE]["n_files"]:
                masalah.append(f"arsip raw berisi {n} file, manifest {m['files'][RAW_FILE]['n_files']}")
        _drop_db(RESTORE_TEST_DB)
        conn = _admin_connect("postgres")
        with conn.cursor() as cur:
            cur.execute(f'CREATE DATABASE "{RESTORE_TEST_DB}"')
        conn.close()
        _run(["pg_restore", "--exit-on-error", "--dbname", RESTORE_TEST_DB, str(target / DUMP_FILE)])
        hasil = table_counts(RESTORE_TEST_DB)
        for tabel, n in m["table_counts"].items():
            if hasil.get(tabel) != n:
                masalah.append(f"{tabel}: backup {n}, hasil restore {hasil.get(tabel)}")
    except Exception as exc:
        masalah.append(str(exc)[:800])
    finally:
        try:
            _drop_db(RESTORE_TEST_DB)
        except Exception:
            pass
    detik = round(time.perf_counter() - t0, 2)
    status = "LULUS" if not masalah else "GAGAL"
    _log(folder, restore_status=status, restore_sec=detik,
         status="SUCCESS" if not masalah else "FAILED", finished_at=datetime.now(),
         notes="; ".join(masalah)[:1000] or None)
    log.info("Uji restore %s: %s dalam %.1f detik %s", folder, status, detik, masalah or "")
    if masalah:
        raise RuntimeError("Uji restore GAGAL: " + "; ".join(masalah))
    return {"folder": folder, "status": status, "restore_sec": detik, "tables": len(m["table_counts"])}


def apply_retention(now: datetime | None = None) -> list[str]:
    """Hapus backup lama: simpan semua 7 hari terakhir + backup terakhir tiap minggu selama 4 minggu."""
    now = now or datetime.now()
    folders = sorted(list_folders())
    simpan = set(folders[-1:])                       # backup terbaru selalu disimpan
    per_minggu = {}
    for f in folders:
        t = datetime.strptime(f, FOLDER_FMT)
        if now - t <= timedelta(days=RETENTION_DAYS):
            simpan.add(f)
        if now - t <= timedelta(weeks=WEEKLY_KEEP):
            per_minggu[t.isocalendar()[:2]] = f      # yang terakhir di minggu itu
    simpan.update(per_minggu.values())
    dihapus = [f for f in folders if f not in simpan]
    for f in dihapus:
        shutil.rmtree(BACKUP_DIR / f)
    if folders:
        _log(folders[-1], deleted_old=len(dihapus))
    log.info("Retensi: %d backup disimpan, %d dihapus %s", len(folders) - len(dihapus), len(dihapus), dihapus)
    return dihapus


def restore(folder: str, target_db: str, ya: bool = False, dengan_raw: bool = True):
    """Pemulihan sungguhan (Disaster Recovery). Menimpa isi database target dan folder Data Lake raw."""
    if not ya:
        raise SystemExit("Restore akan MENIMPA data. Ulangi dengan --ya bila sudah yakin.")
    src = BACKUP_DIR / folder
    verify = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    if _sha256(src / DUMP_FILE) != verify["files"][DUMP_FILE]["sha256"]:
        raise RuntimeError("Checksum dump tidak cocok, restore dibatalkan")
    conn = _admin_connect("postgres")
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
        if not cur.fetchone():
            cur.execute(f'CREATE DATABASE "{target_db}"')
    conn.close()
    _run(["pg_restore", "--clean", "--if-exists", "--dbname", target_db, str(src / DUMP_FILE)])
    log.info("Database %s dipulihkan dari %s", target_db, folder)
    if dengan_raw and (src / RAW_FILE).exists():
        with tarfile.open(src / RAW_FILE, "r:gz") as tar:
            anggota = []
            for x in tar.getmembers():
                if x.name.startswith("data_lake/"):
                    x.name = x.name[len("data_lake/"):]
                    anggota.append(x)
            tar.extractall(config.DATA_LAKE_DIR, members=anggota, filter="data")
        log.info("Data Lake raw dan model dipulihkan ke %s", config.DATA_LAKE_DIR)
    hasil = table_counts(target_db)
    beda = {t: (n, hasil.get(t)) for t, n in verify["table_counts"].items() if hasil.get(t) != n}
    log.info("Cek setelah restore: %s", "semua jumlah baris cocok" if not beda else f"berbeda {beda}")
    return beda


# ------------------------------------------------------------------ bantu
def list_folders() -> list[str]:
    if not BACKUP_DIR.exists():
        return []
    out = []
    for p in BACKUP_DIR.iterdir():
        try:
            datetime.strptime(p.name, FOLDER_FMT)
            if p.is_dir():
                out.append(p.name)
        except ValueError:
            continue
    return sorted(out)


def latest_folder() -> str:
    ok = [f for f in list_folders() if (BACKUP_DIR / f / "manifest.json").exists()]
    if not ok:
        raise FileNotFoundError(f"Belum ada backup di {BACKUP_DIR}")
    return ok[-1]


def run_all() -> dict:
    folder = backup_database()
    backup_raw(folder)
    hasil = verify_restore(folder)
    hasil["dihapus"] = apply_retention()
    return hasil


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s - %(message)s")
    p = argparse.ArgumentParser(description="Backup dan restore FitZone")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run")
    sub.add_parser("list")
    v = sub.add_parser("verify")
    v.add_argument("--folder")
    r = sub.add_parser("restore")
    r.add_argument("--folder", required=True)
    r.add_argument("--target", default=config.DW_NAME)
    r.add_argument("--ya", action="store_true")
    r.add_argument("--tanpa-raw", action="store_true")
    a = p.parse_args()
    if a.cmd == "run":
        print(run_all())
    elif a.cmd == "list":
        for f in list_folders():
            mf = BACKUP_DIR / f / "manifest.json"
            if mf.exists():
                m = json.loads(mf.read_text(encoding="utf-8"))
                mb = sum(x["bytes"] for x in m["files"].values()) / 1e6
                print(f"{f}  {mb:8.2f} MB  {len(m['table_counts'])} tabel  "
                      f"{sum(m['table_counts'].values()):,} baris")
            else:
                print(f"{f}  (tidak lengkap)")
    elif a.cmd == "verify":
        print(verify_restore(a.folder))
    elif a.cmd == "restore":
        print(restore(a.folder, a.target, a.ya, not a.tanpa_raw) or "Restore selesai, jumlah baris cocok")


if __name__ == "__main__":
    main()

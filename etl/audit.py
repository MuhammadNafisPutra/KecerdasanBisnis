"""Pencatatan batch di etl_audit.etl_log dan baris ditolak di etl_audit.etl_reject.

Koneksi audit memakai autocommit, sehingga catatan tetap tersimpan walaupun
transaksi load dibatalkan (rollback).
"""
import json
import logging
import math
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg2.extras

from etl import config, db

log = logging.getLogger("fitzone.audit")


def start_batch(source_name: str, stage: str = "ingest") -> int:
    conn = db.connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO etl_audit.etl_log (source_name, stage, status) "
                "VALUES (%s, %s, 'RUNNING') RETURNING batch_id",
                (source_name, stage))
            batch_id = cur.fetchone()[0]
    finally:
        conn.close()
    log.info("Batch %s dimulai (%s)", batch_id, source_name)
    return batch_id


def update_batch(batch_id: int, **fields):
    """Perbarui kolom etl_log. Kolom 'notes' ditambahkan (append), tidak ditimpa."""
    if not fields:
        return
    sets, values = [], []
    for key, value in fields.items():
        if key == "notes":
            sets.append("notes = CONCAT_WS(' | ', notes, %s)")
        else:
            sets.append(f"{key} = %s")
        values.append(value)
    if fields.get("status") in ("SUCCESS", "FAILED", "SKIPPED"):
        sets.append("finished_at = now()")
    values.append(batch_id)
    conn = db.connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE etl_audit.etl_log SET {', '.join(sets)} WHERE batch_id = %s", values)
    finally:
        conn.close()


def fail_batch(batch_id: int, stage: str, error: BaseException):
    msg = f"{type(error).__name__}: {error}"[:2000]
    log.error("Batch %s GAGAL di tahap %s: %s", batch_id, stage, msg)
    try:
        update_batch(batch_id, status="FAILED", stage=stage, error_message=msg)
    except Exception as exc:  # database mati: jangan menutupi error asli
        log.error("Tidak bisa menulis status FAILED ke etl_log: %s", exc)


def get_batch(batch_id: int) -> dict:
    conn = db.connect(autocommit=True)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM etl_audit.etl_log WHERE batch_id = %s", (batch_id,))
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError(f"batch_id {batch_id} tidak ada di etl_log")
    return dict(row)


def last_success_checksum(source_name: str):
    conn = db.connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT source_checksum FROM etl_audit.etl_log "
                "WHERE source_name = %s AND status = 'SUCCESS' AND source_checksum IS NOT NULL "
                "ORDER BY batch_id DESC LIMIT 1", (source_name,))
            row = cur.fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def _clean(value):
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def write_rejects(batch_id: int, source_name: str, rejects: list[dict]):
    """rejects: list dict berisi source_row_no, reject_reason, raw_record (dict)."""
    if not rejects:
        return
    rows = [
        (batch_id, source_name, r.get("source_row_no"), r["reject_reason"],
         json.dumps({k: _clean(v) for k, v in (r.get("raw_record") or {}).items()}, default=str))
        for r in rejects
    ]
    conn = db.connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM etl_audit.etl_reject WHERE batch_id = %s", (batch_id,))
            db.insert_rows(cur, "etl_audit.etl_reject",
                           ["batch_id", "source_name", "source_row_no", "reject_reason", "raw_record"],
                           rows)
    finally:
        conn.close()
    log.warning("Batch %s: %d baris ditolak dicatat di etl_reject", batch_id, len(rows))


# ---------------------------------------------------------------- durasi per tahap

_stage_log_ready = False


def _ensure_stage_log():
    """Database lama (dibuat sebelum tabel etl_stage_log ada) diperbarui otomatis sekali per proses."""
    global _stage_log_ready
    if _stage_log_ready:
        return
    conn = db.connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('etl_audit.v_durasi_tahap')")
            if cur.fetchone()[0] is None:
                cur.execute((config.SQL_DIR / "02_audit.sql").read_text(encoding="utf-8"))
    finally:
        conn.close()
    _stage_log_ready = True


def peak_mem_mb() -> float | None:
    """Puncak memori (RSS) proses ini dalam MB. Hanya tersedia di Linux/Mac (container Airflow)."""
    try:
        import resource
    except ImportError:          # Windows
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / 1024 / (1024 if sys.platform == "darwin" else 1), 1)


@contextmanager
def stage_timer(batch_id: int, stage: str):
    """Ukur lama satu tahap dan simpan ke etl_stage_log, juga bila tahap gagal.

        with audit.stage_timer(batch_id, "load") as t:
            ...
            t["rows"] = jumlah_baris
    """
    info = {"rows": None}
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    status = "SUCCESS"
    try:
        yield info
    except BaseException as exc:
        status = "SKIPPED" if type(exc).__name__ == "SkipBatch" else "FAILED"
        raise
    finally:
        duration = time.perf_counter() - t0
        try:
            _ensure_stage_log()
            conn = db.connect(autocommit=True)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO etl_audit.etl_stage_log (batch_id, stage, status, rows_processed, "
                        "started_at, finished_at, duration_sec, peak_mem_mb) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        (batch_id, stage, status, info["rows"], started, datetime.now(timezone.utc),
                         round(duration, 3), peak_mem_mb()))
            finally:
                conn.close()
        except Exception as exc:  # pencatatan durasi tidak boleh menggagalkan pipeline
            log.warning("Durasi tahap %s batch %s tidak tercatat: %s", stage, batch_id, exc)
        log.info("Batch %s tahap %s: %s dalam %.2f detik", batch_id, stage, status, duration)


def timed(stage: str):
    """Dekorator untuk fungsi tahap dengan argumen pertama batch_id.
    Jumlah baris diambil dari nilai kembali (int, atau dict berisi rows_read)."""
    def deco(fn):
        import functools

        @functools.wraps(fn)
        def wrapper(batch_id, *args, **kwargs):
            with stage_timer(batch_id, stage) as t:
                result = fn(batch_id, *args, **kwargs)
                if isinstance(result, int):
                    t["rows"] = result
                elif isinstance(result, dict):
                    t["rows"] = result.get("rows_read")
                return result
        return wrapper
    return deco

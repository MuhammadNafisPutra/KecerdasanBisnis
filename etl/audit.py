"""Pencatatan batch di etl_audit.etl_log dan baris ditolak di etl_audit.etl_reject.

Koneksi audit memakai autocommit, sehingga catatan tetap tersimpan walaupun
transaksi load dibatalkan (rollback).
"""
import json
import logging
import math

import psycopg2.extras

from etl import db

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

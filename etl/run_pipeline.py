"""Menjalankan pipeline tanpa Airflow (dari terminal VS Code), misalnya untuk uji dan demo.

    python -m etl.run_pipeline init-db          # buat schema, tabel, seed, mart
    python -m etl.run_pipeline member           # CSV -> Data Lake -> staging -> DWH
    python -m etl.run_pipeline who              # WHO API -> Data Lake -> staging -> DWH
    python -m etl.run_pipeline all
    python -m etl.run_pipeline replay member 12 # proses ulang batch 12 dari raw zone (tanpa ambil ulang)
    python -m etl.run_pipeline status           # 10 batch terakhir

Di Airflow, retry diatur oleh DAG. Di sini retry dilakukan oleh fungsi run_with_retry.
"""
import argparse
import logging
import sys
import time

from etl import config, db, ingest, member, notify, who

log = logging.getLogger("fitzone.run")


def setup_logging():
    (config.PROJECT_ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(config.PROJECT_ROOT / "logs" / "etl.log", encoding="utf-8")])


# Error yang tidak perlu dicoba ulang (masalah data, bukan gangguan sementara)
NO_RETRY = (member.QualityGateError, member.ReconciliationError, ingest.SkipBatch, FileNotFoundError, ValueError)


def run_with_retry(fn, *args, retries=None, delay=None):
    retries = config.RETRY_COUNT if retries is None else retries
    delay = config.RETRY_DELAY_SEC if delay is None else delay
    for attempt in range(1, retries + 2):
        try:
            return fn(*args)
        except NO_RETRY:
            raise
        except Exception as exc:
            if attempt > retries:
                raise
            log.warning("%s gagal (percobaan %d/%d): %s. Coba lagi %d detik lagi.",
                        fn.__name__, attempt, retries + 1, exc, delay)
            time.sleep(delay)


def init_db():
    files = sorted(p for p in config.SQL_DIR.glob("0[1-8]_*.sql"))
    with db.transaction() as conn, conn.cursor() as cur:
        for f in files:
            log.info("Menjalankan %s", f.name)
            cur.execute(f.read_text(encoding="utf-8"))
    log.info("Database siap (%d file SQL)", len(files))


def process(source: str, batch_id: int):
    mod = member if source == "member" else who
    run_with_retry(getattr(mod, f"stage_{source}"), batch_id)
    getattr(mod, f"transform_{source}")(batch_id)
    run_with_retry(getattr(mod, f"load_{source}"), batch_id)


def run_source(source: str, retries=None, delay=None) -> bool:
    fn = ingest.ingest_member if source == "member" else ingest.ingest_who
    try:
        batch_id = run_with_retry(fn, retries=retries, delay=delay)
        process(source, batch_id)
        log.info("Pipeline %s SELESAI (batch %s)", source, batch_id)
        return True
    except ingest.SkipBatch as exc:
        log.info("Pipeline %s dilewati: %s", source, exc)
        return True
    except Exception as exc:
        notify.send_alert(f"Pipeline {source} GAGAL", f"{type(exc).__name__}: {exc}")
        log.error("Pipeline %s GAGAL: %s", source, exc)
        return False


def show_status():
    conn = db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT batch_id, source_name, stage, status, rows_read, rows_loaded, rows_rejected, "
                        "duration_sec, COALESCE(error_message, '') FROM etl_audit.v_ringkasan_etl "
                        "ORDER BY batch_id DESC LIMIT 10")
            print(f"{'batch':>5} {'sumber':<12} {'tahap':<9} {'status':<8} {'baca':>7} {'muat':>7} "
                  f"{'tolak':>5} {'detik':>6}  error")
            for r in cur.fetchall():
                print(f"{r[0]:>5} {r[1]:<12} {r[2] or '':<9} {r[3]:<8} {r[4] or 0:>7} {r[5] or 0:>7} "
                      f"{r[6] or 0:>5} {r[7] or 0:>6}  {r[8][:60]}")
    finally:
        conn.close()


def main(argv=None):
    setup_logging()
    p = argparse.ArgumentParser(description="Pipeline ETL PT FitZone Nusantara")
    p.add_argument("command", choices=["init-db", "member", "who", "all", "replay", "status"])
    p.add_argument("source", nargs="?", choices=["member", "who"])
    p.add_argument("batch_id", nargs="?", type=int)
    p.add_argument("--retries", type=int, default=None)
    p.add_argument("--retry-delay", type=int, default=None, help="detik (bawaan 300)")
    a = p.parse_args(argv)

    if a.command == "init-db":
        init_db()
        return 0
    if a.command == "status":
        show_status()
        return 0
    if a.command == "replay":
        if not (a.source and a.batch_id):
            p.error("replay butuh sumber dan batch_id, contoh: replay member 12")
        process(a.source, a.batch_id)
        return 0
    sources = ["member", "who"] if a.command == "all" else [a.command]
    ok = all([run_source(s, a.retries, a.retry_delay) for s in sources])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

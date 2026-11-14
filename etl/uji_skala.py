"""Uji skala pipeline: data member diperbanyak 1x, 10x, 100x, 1000x lalu diukur waktu dan memori tiap tahap.

Jalankan di DATABASE TERPISAH agar data demo tidak berubah. Sekali saja, buat databasenya:

    docker compose exec postgres createdb -U db_admin -O etl_user fitzone_bench

Lalu (di dalam container Airflow, karena pengukuran memori butuh Linux):

    docker compose exec airflow-scheduler python -m etl.uji_skala
    docker compose exec airflow-scheduler python -m etl.uji_skala --skala 1 10 100 --tanpa-ml

Cara memperbanyak data: salinan ke-0 adalah file asli; salinan lain diberi variasi kecil
(berat +-2 kg dengan BMI dihitung ulang, durasi +-0,1 jam dengan kalori menyesuaikan,
air +-0,2 L, lemak +-1 poin). Tanpa variasi, aturan "baris ganda dihapus" akan membuang
salinan dan quality gate menghentikan batch. Data hasil perbanyakan adalah DATA SINTETIS
untuk uji beban, bukan data member baru.

PENTING: angka akurasi model (MAE/R2) pada skala 10x ke atas TIDAK BERMAKNA. Salinan dari member
yang sama bisa masuk ke data latih dan data uji sekaligus (kebocoran data), sehingga R2 tampak
hampir 1. Uji skala hanya mengukur waktu dan memori; akurasi model memakai hasil data asli (1x).

Setiap skala dijalankan di proses terpisah sehingga puncak memori tidak tercampur.
Hasil: data/uji_skala/hasil_uji_skala.csv dan hasil_uji_skala.md
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from etl import config, db

BENCH_DB = "fitzone_bench"
OUT_DIR = config.PROJECT_ROOT / "data" / "uji_skala"


# ---------------------------------------------------------------- pembuat data
def perbanyak(src: pd.DataFrame, kali: int, seed: int = 42) -> pd.DataFrame:
    """Gandakan data `kali` kali. Salinan pertama = data asli tanpa perubahan."""
    if kali == 1:
        return src.copy()
    rng = np.random.default_rng(seed)
    n = len(src)
    out = pd.concat([src] * kali, ignore_index=True)
    var = np.arange(len(out)) >= n                       # baris salinan (bukan asli)
    m = int(var.sum())

    def ubah(col, delta, lo, hi, nd):
        out.loc[var, col] = np.clip(out.loc[var, col] + rng.uniform(-delta, delta, m), lo, hi).round(nd)

    dur_lama = out.loc[var, "Session_Duration (hours)"].to_numpy()
    ubah("Weight (kg)", 2.0, 30, 250, 1)
    ubah("Session_Duration (hours)", 0.1, 0.5, 2.0, 2)
    ubah("Water_Intake (liters)", 0.2, 1.5, 3.7, 1)
    ubah("Fat_Percentage", 1.0, 10, 35, 1)
    rasio = out.loc[var, "Session_Duration (hours)"].to_numpy() / dur_lama
    out.loc[var, "Calories_Burned"] = (out.loc[var, "Calories_Burned"] * rasio).round(1)
    out.loc[var, "BMI"] = (out.loc[var, "Weight (kg)"] / out.loc[var, "Height (m)"] ** 2).round(2)
    return out


def _ukuran_mb(path: Path) -> float:
    if path.is_file():
        return round(path.stat().st_size / 1e6, 2)
    return round(sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) / 1e6, 2) if path.exists() else 0.0


# ---------------------------------------------------------------- satu skala (proses anak)
def jalankan_satu(kali: int, tanpa_ml: bool) -> None:
    """Dijalankan di proses terpisah. Semua tahap mencatat durasi ke etl_stage_log."""
    from etl import ingest, member, ml

    b = ingest.ingest_member()
    member.stage_member(b)
    member.transform_member(b)
    member.load_member(b)
    if not tanpa_ml:
        ml.train_model()


# ---------------------------------------------------------------- pengendali
def _lingkungan(lake: Path) -> dict:
    env = dict(os.environ)
    env.update({"DW_NAME": BENCH_DB, "DATA_LAKE_DIR": str(lake), "SOURCE_DIR": str(lake / "source"),
                "EXPECTED_MEMBER_ROWS": "0", "PYTHONPATH": str(config.PROJECT_ROOT)})
    return env


def _cek_database():
    config.DW_NAME = BENCH_DB
    try:
        db.connect().close()
    except Exception as exc:
        sys.exit(f"Database uji '{BENCH_DB}' belum bisa dipakai ({str(exc).strip()}).\n"
                 f"Buat dulu: docker compose exec postgres createdb -U db_admin -O etl_user {BENCH_DB}")


def _batch_terakhir() -> int:
    return int(db.read_df("SELECT COALESCE(MAX(batch_id), 0) AS b FROM etl_audit.etl_log").iloc[0, 0])


def _ambil_hasil(sejak: int) -> dict:
    """Hasil semua batch dengan batch_id > sejak (batch yang dibuat oleh skala ini)."""
    sql = """
        SELECT s.stage, s.status, s.rows_processed, s.duration_sec, s.peak_mem_mb
        FROM etl_audit.etl_stage_log s
        WHERE s.batch_id > %(b)s ORDER BY s.stage_log_id"""
    df = db.read_df(sql, {"b": sejak})
    hasil = {}
    for r in df.itertuples():
        hasil[f"{r.stage}_sec"] = float(r.duration_sec)
        hasil[f"{r.stage}_status"] = r.status
        if r.peak_mem_mb is not None:
            hasil["peak_mem_mb"] = max(hasil.get("peak_mem_mb", 0), float(r.peak_mem_mb))
    ml_run = db.read_df("""SELECT model_name, n_train + n_test AS n_sampel FROM dw.ml_model_run
                           WHERE is_champion AND batch_id > %(b)s""", {"b": sejak})
    if len(ml_run):
        hasil.update(ml_champion=ml_run.iloc[0].model_name, ml_n_sampel=int(ml_run.iloc[0].n_sampel))
    dims = db.read_df("SELECT COUNT(*) FROM dw.dim_member")
    hasil["baris_dwh"] = int(dims.iloc[0, 0])
    size = db.read_df("""SELECT ROUND(SUM(pg_total_relation_size(c.oid)) / 1e6, 2) AS mb
                         FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                         WHERE n.nspname = 'dw' AND c.relkind IN ('r', 'm')""")
    hasil["dwh_mb"] = float(size.iloc[0, 0] or 0)
    return hasil


def _markdown(df: pd.DataFrame) -> str:
    """Tabel markdown sederhana (tanpa paket tambahan)."""
    def sel(v):
        return "" if v is None or (isinstance(v, float) and np.isnan(v)) else str(v)
    baris = ["| " + " | ".join(df.columns) + " |", "|" + "---|" * len(df.columns)]
    baris += ["| " + " | ".join(sel(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join(baris)


def main(argv=None):
    p = argparse.ArgumentParser(description="Uji skala pipeline FitZone")
    p.add_argument("--skala", type=int, nargs="+", default=[1, 10, 100, 1000])
    p.add_argument("--tanpa-ml", action="store_true", help="lewati training model")
    p.add_argument("--simpan-lake", action="store_true", help="jangan hapus data lake uji setelah selesai")
    p.add_argument("--satu", type=int, help=argparse.SUPPRESS)       # dipakai proses anak
    a = p.parse_args(argv)

    if a.satu:
        import logging
        logging.basicConfig(level=logging.WARNING)
        jalankan_satu(a.satu, a.tanpa_ml)
        return 0

    sumber = config.SOURCE_DIR / config.MEMBER_FILE
    asli = pd.read_csv(sumber)
    lake = config.DATA_LAKE_DIR / "_uji_skala"
    _cek_database()

    from etl import run_pipeline
    print(f"Menyiapkan database {BENCH_DB} ...")
    run_pipeline.init_db()
    with db.transaction() as conn, conn.cursor() as cur:   # database uji: mulai dari kosong
        cur.execute("TRUNCATE etl_audit.etl_log, dw.fact_workout_session, dw.fact_body_measurement, "
                    "dw.dim_member RESTART IDENTITY CASCADE")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    baris_hasil = []
    for kali in a.skala:
        shutil.rmtree(lake, ignore_errors=True)
        (lake / "source").mkdir(parents=True)
        t0 = time.perf_counter()
        df = perbanyak(asli, kali)
        csv = lake / "source" / config.MEMBER_FILE
        df.to_csv(csv, index=False)
        gen_sec = time.perf_counter() - t0
        print(f"\n== {kali}x: {len(df):,} baris, CSV {_ukuran_mb(csv)} MB (dibuat {gen_sec:.1f} s)", flush=True)

        sejak = _batch_terakhir()
        t0 = time.perf_counter()
        proc = subprocess.run([sys.executable, "-m", "etl.uji_skala", "--satu", str(kali)]
                              + (["--tanpa-ml"] if a.tanpa_ml else []),
                              env=_lingkungan(lake), cwd=config.PROJECT_ROOT,
                              capture_output=True, text=True)
        wall = time.perf_counter() - t0
        hasil = {"skala": f"{kali}x", "baris": len(df), "csv_mb": _ukuran_mb(csv),
                 "parquet_mb": _ukuran_mb(lake / "curated"), "wall_sec": round(wall, 2)}
        if proc.returncode == 0:
            hasil["status"] = "SUKSES"
        elif proc.returncode in (-9, 137):
            hasil["status"] = "GAGAL: kehabisan memori (proses dihentikan sistem)"
        else:
            pesan = (proc.stderr.strip().splitlines() or ["?"])[-1]
            hasil["status"] = f"GAGAL: {pesan[:150]}"
        hasil.update(_ambil_hasil(sejak))
        if proc.returncode != 0:
            hasil["baris_dwh"] = None                      # DWH masih berisi skala sebelumnya
            (OUT_DIR / f"error_{kali}x.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
        etl = sum(hasil.get(f"{s}_sec", 0) for s in ("ingest", "stage", "transform", "load"))
        hasil["etl_sec"] = round(etl, 2)
        hasil["baris_per_detik"] = round(len(df) / etl) if etl else None
        baris_hasil.append(hasil)
        print("   " + ", ".join(f"{k}={v}" for k, v in hasil.items() if k.endswith(("_sec", "_mb", "status"))),
              flush=True)
        if not a.simpan_lake:
            shutil.rmtree(lake, ignore_errors=True)

    tabel = pd.DataFrame(baris_hasil)
    urut = ["skala", "baris", "baris_dwh", "status", "csv_mb", "parquet_mb", "dwh_mb", "ingest_sec",
            "stage_sec", "transform_sec", "load_sec", "etl_sec", "baris_per_detik", "ml_load_data_sec",
            "ml_train_sec", "ml_write_sec", "ml_n_sampel", "ml_champion", "peak_mem_mb", "wall_sec"]
    tabel = tabel[[c for c in urut if c in tabel.columns]]
    tabel.to_csv(OUT_DIR / "hasil_uji_skala.csv", index=False)
    (OUT_DIR / "hasil_uji_skala.md").write_text(
        "# Hasil uji skala pipeline FitZone\n\n"
        f"Diuji: {time.strftime('%Y-%m-%d %H:%M')} | database: {BENCH_DB} | "
        f"ML_MAX_TRAIN_ROWS={config.ML_MAX_TRAIN_ROWS} | ML_N_JOBS={config.ML_N_JOBS}\n\n"
        "Data 10x/100x/1000x adalah data sintetis (salinan data asli dengan variasi kecil). "
        "Uji ini mengukur waktu dan memori; akurasi model memakai hasil data asli (1x) karena "
        "salinan menimbulkan kebocoran data latih-uji.\n\n"
        "Kolom: *_sec = detik per tahap; etl_sec = ingest+stage+transform+load; "
        "ml_n_sampel = baris yang dipakai melatih (dibatasi ML_MAX_TRAIN_ROWS); "
        "peak_mem_mb = puncak memori proses.\n\n"
        + _markdown(tabel) + "\n", encoding="utf-8")
    print(f"\nHasil disimpan: {OUT_DIR / 'hasil_uji_skala.csv'}")
    print(tabel.to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Kumpulkan bukti eksekusi seluruh proses pipeline ke satu folder.

Jalankan di container Airflow (database dan Data Lake sudah terpasang di sana):
    docker exec fitzone_airflow_scheduler python -m etl.bukti

Hasil: data/bukti/<tanggal_jam>/ berisi file teks per proses (ingestion, Data Lake, ETL, quality gate,
data warehouse, lineage, orkestrasi Airflow, ML, backup) dan RINGKASAN.md. Isinya diambil langsung dari
database, Data Lake, dan Airflow, sehingga menjadi bukti bahwa proses benar-benar dijalankan.
Folder data/ ada di laptop (volume ./data), jadi hasilnya langsung bisa dibuka di VS Code.
"""
import json
import os
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

import pandas as pd

from etl import config, db

WIB = ZoneInfo("Asia/Jakarta")               # zona waktu yang sama dengan jadwal Airflow
OUT = config.PROJECT_ROOT / "data" / "bukti" / datetime.now(WIB).strftime("%Y%m%d_%H%M%S")
pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)
pd.set_option("display.max_colwidth", 60)

ringkasan: list[str] = []


def tulis(nama: str, judul: str, isi: str):
    (OUT / nama).write_text(f"# {judul}\n# Diambil: {datetime.now(WIB):%Y-%m-%d %H:%M:%S} WIB\n\n{isi}\n",
                            encoding="utf-8")


def tabel(sql: str, params=None) -> str:
    try:
        df = db.read_df(sql, params)
        for c in df.select_dtypes("float").columns:   # 973.0 -> 973 bila kolom berisi bilangan bulat
            if (df[c].dropna() % 1 == 0).all():
                df[c] = df[c].astype("Int64")
        return "(tidak ada baris)" if df.empty else df.astype(object).where(df.notna(), "-").to_string(index=False)
    except Exception as e:  # satu bagian gagal tidak menghentikan bagian lain
        return f"GAGAL dibaca: {e}"


def cmd(args: list[str]) -> str:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=120)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return f"GAGAL menjalankan {' '.join(args)}: {e}"


def pohon(root: Path, maks: int = 400) -> str:
    if not root.exists():
        return f"{root} tidak ditemukan"
    baris, total = [], 0
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if p.is_file():
            total += p.stat().st_size
            baris.append(f"{'  ' * (len(rel.parts) - 1)}{p.name}  ({p.stat().st_size / 1024:,.1f} KB)")
        else:
            baris.append(f"{'  ' * (len(rel.parts) - 1)}{p.name}/")
    potong = "" if len(baris) <= maks else f"\n... {len(baris) - maks} entri lagi tidak ditampilkan"
    return f"{root.relative_to(config.PROJECT_ROOT) if root.is_relative_to(config.PROJECT_ROOT) else root}  total {total / 1024 / 1024:,.2f} MB\n" + "\n".join(baris[:maks]) + potong


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    # 1. Sumber data dan ingestion
    src = config.SOURCE_DIR / config.MEMBER_FILE
    isi = f"File sumber member: {src}\n"
    if src.exists():
        df = pd.read_csv(src)
        isi += f"Ukuran {src.stat().st_size / 1024:,.1f} KB, {len(df)} baris, {df.shape[1]} kolom\n\n"
        isi += "5 baris pertama (kolom ditampilkan menurun):\n"
        t = df.head().T
        t.columns = [f"baris {i + 1}" for i in range(len(t.columns))]
        isi += t.to_string()
    isi += "\n\nCatatan ingestion per batch (etl_audit.etl_log):\n"
    isi += tabel("SELECT batch_id, source_name AS sumber, status, rows_read AS baris_dibaca, "
                 "to_char(started_at, 'YYYY-MM-DD HH24:MI') AS mulai, left(source_checksum, 12) AS sha256_awal "
                 "FROM etl_audit.etl_log ORDER BY batch_id DESC LIMIT 15")
    tulis("01_sumber_dan_ingestion.txt", "Sumber data dan ingestion", isi)
    ringkasan.append("01 Sumber data dan ingestion: file CSV member dan riwayat ingestion per batch")

    # 2. Data Lake
    isi = pohon(config.RAW_DIR) + "\n\n" + pohon(config.CURATED_DIR) + "\n\n" + pohon(config.MODEL_DIR)
    manifest = sorted(config.RAW_DIR.rglob("manifest.json"))
    if manifest:
        isi += f"\n\nContoh manifest ({manifest[-1].relative_to(config.PROJECT_ROOT)}):\n{manifest[-1].read_text(encoding='utf-8')[:3000]}"
    who = sorted(config.RAW_DIR.rglob("*.json"))
    who = [p for p in who if p.name != "manifest.json"]
    if who:
        try:
            rec = json.loads(who[-1].read_text(encoding="utf-8"))
            rec = rec.get("value", rec)
            contoh = rec[0] if isinstance(rec, list) and rec else rec
            isi += f"\n\nContoh 1 record JSON WHO ({who[-1].name}):\n{json.dumps(contoh, indent=2)[:2000]}"
        except Exception as e:
            isi += f"\n\nContoh JSON WHO gagal dibaca: {e}"
    tulis("02_data_lake.txt", "Struktur Data Lake (raw, curated, models)", isi)
    ringkasan.append(f"02 Data Lake: {len(manifest)} manifest di raw zone, file curated dan model")

    # 3. ETL per batch dan durasi tahap
    isi = "Ringkasan batch ETL (etl_audit.v_ringkasan_etl):\n"
    isi += tabel("SELECT batch_id, source_name AS sumber, stage AS tahap, status, rows_read AS dibaca, "
                 "rows_loaded AS dimuat, rows_rejected AS ditolak, to_char(started_at, 'YYYY-MM-DD HH24:MI') "
                 "AS mulai, duration_sec AS detik FROM etl_audit.v_ringkasan_etl ORDER BY batch_id DESC LIMIT 30")
    isi += "\n\nDurasi per tahap (etl_audit.v_durasi_tahap):\n"
    isi += tabel("SELECT batch_id, source_name AS sumber, ingest_sec AS ingest, stage_sec AS stage, "
                 "transform_sec AS transform, load_sec AS load, ml_sec AS ml, total_sec AS total, "
                 "peak_mem_mb AS memori_mb FROM etl_audit.v_durasi_tahap ORDER BY batch_id DESC LIMIT 20")
    tulis("03_etl_batch.txt", "Eksekusi ETL per batch", isi)
    st = db.read_df("SELECT status, COUNT(*) n FROM etl_audit.etl_log GROUP BY status")
    ringkasan.append("03 ETL: " + ", ".join(f"{r.status} {r.n}" for r in st.itertuples()))

    # 4. Data quality
    isi = "Baris yang ditolak quality gate (etl_audit.etl_reject), per sumber:\n"
    isi += tabel("SELECT source_name, COUNT(*) AS jumlah FROM etl_audit.etl_reject GROUP BY source_name")
    isi += "\n\nContoh baris ditolak:\n" + tabel("SELECT reject_id, batch_id, source_name, source_row_no, reject_reason FROM etl_audit.etl_reject ORDER BY reject_id DESC LIMIT 10")
    isi += "\n\nAnomali detak jantung yang ditandai (Avg_BPM > Max_BPM), tetap dimuat:\n"
    isi += tabel("SELECT COUNT(*) AS baris_anomali FROM dw.fact_workout_session WHERE bpm_anomaly_flag = 1")
    isi += "\n\nRekonsiliasi jumlah baris sumber vs data warehouse:\n"
    isi += tabel("SELECT (SELECT COUNT(*) FROM dw.fact_workout_session) AS fact_workout_session, "
                 "(SELECT COUNT(*) FROM dw.fact_body_measurement) AS fact_body_measurement, "
                 "(SELECT COUNT(*) FROM dw.dim_member) AS dim_member")
    tulis("04_data_quality.txt", "Data quality gate dan validasi", isi)
    ringkasan.append("04 Data quality: baris ditolak, anomali BPM, rekonsiliasi jumlah baris")

    # 5. Data warehouse dan data mart
    isi = "Jumlah baris setiap tabel dan view:\n"
    obj = db.read_df("SELECT table_schema, table_name, table_type FROM information_schema.tables "
                     "WHERE table_schema IN ('staging','dw','etl_audit') ORDER BY 1, 2")
    mv = db.read_df("SELECT schemaname AS table_schema, matviewname AS table_name, 'MATERIALIZED VIEW' "
                    "AS table_type FROM pg_matviews WHERE schemaname IN ('staging','dw','etl_audit')")
    obj = pd.concat([obj, mv], ignore_index=True)
    jumlah = []
    for r in obj.itertuples():
        try:
            n = int(db.read_df(f'SELECT COUNT(*) n FROM "{r.table_schema}"."{r.table_name}"').n[0])
        except Exception:
            n = None
        jumlah.append(n)
    obj["jumlah_baris"] = jumlah
    isi += obj.to_string(index=False)
    tulis("05_data_warehouse.txt", "Data warehouse, data mart, dan staging", isi)
    ringkasan.append(f"05 Data warehouse: {len(obj)} tabel/view di schema staging, dw, etl_audit")

    # 6. Lineage
    isi = "Setiap baris fakta menyimpan load_batch_id yang menunjuk ke etl_log:\n"
    isi += tabel("SELECT f.session_key, f.member_key, f.load_batch_id, l.source_name AS sumber, "
                 "left(l.source_checksum, 12) AS sha256_awal FROM dw.fact_workout_session f "
                 "JOIN etl_audit.etl_log l ON l.batch_id = f.load_batch_id ORDER BY f.session_key LIMIT 5")
    isi += "\n\nLokasi file raw untuk batch tersebut:\n"
    isi += tabel("SELECT DISTINCT l.batch_id, regexp_replace(l.raw_path, '^/opt/airflow/', '') AS raw_path "
                 "FROM etl_audit.etl_log l JOIN dw.fact_workout_session f ON f.load_batch_id = l.batch_id")
    tulis("06_lineage.txt", "Data lineage dari data warehouse ke file raw", isi)
    ringkasan.append("06 Lineage: baris fakta -> batch etl_log -> file raw + checksum")

    # 7. Orkestrasi Airflow
    isi = "Daftar DAG:\n" + cmd(["airflow", "dags", "list", "-o", "plain"])
    for dag in ("fitzone_member_daily", "fitzone_who_monthly", "fitzone_backup_daily"):
        isi += f"\n\nRiwayat run {dag}:\n"
        teks = cmd(["airflow", "dags", "list-runs", "-d", dag, "-o", "json"])
        try:
            runs = pd.DataFrame(json.loads(teks[teks.index("["):teks.rindex("]") + 1]))
            mulai = pd.to_datetime(runs.start_date, utc=True)
            selesai = pd.to_datetime(runs.end_date, utc=True)
            runs = pd.DataFrame({
                "jenis": runs.run_id.str.split("__").str[0],
                "status": runs.state,
                "mulai (WIB)": mulai.dt.tz_convert(WIB).dt.strftime("%Y-%m-%d %H:%M"),
                "durasi_detik": (selesai - mulai).dt.total_seconds().round(1),
            })
            isi += runs.head(10).fillna("-").to_string(index=False)
        except Exception:
            isi += teks
    tulis("07_airflow.txt", "Orkestrasi Apache Airflow (DAG dan riwayat run)", isi)
    ringkasan.append("07 Airflow: daftar DAG dan riwayat run ketiga DAG utama")

    # 8. Machine learning
    isi = "Evaluasi model (dw.mart_ml_evaluasi):\n" + tabel(
        "SELECT model_name AS model, model_role AS peran, n_train, n_test, cv_mae_mean AS cv_mae, "
        "test_mae, test_rmse, test_r2, mae_lebih_baik_pct AS lebih_baik_pct, is_champion AS terpilih "
        "FROM dw.mart_ml_evaluasi ORDER BY test_mae")
    met = sorted(config.MODEL_DIR.rglob("metrics.json"))
    if met:
        teks = met[-1].read_text(encoding="utf-8").splitlines()
        lebih = "" if len(teks) <= 45 else f"\n... ({len(teks) - 45} baris lagi, lihat file aslinya)"
        rel = met[-1].relative_to(config.PROJECT_ROOT)
        isi += f"\n\nmetrics.json ({rel}), 45 baris pertama:\n" + "\n".join(teks[:45]) + lebih
    isi += "\n\nJumlah prediksi per status (data uji):\n"
    isi += tabel("SELECT status_prediksi, COUNT(*) AS jumlah FROM dw.mart_ml_prediksi_lemak WHERE split = 'uji' "
                 "GROUP BY 1 ORDER BY 1")
    tulis("08_machine_learning.txt", "Training dan evaluasi model", isi)
    ringkasan.append("08 Machine learning: metrik semua model, metrics.json, status prediksi")

    # 9. Backup dan disaster recovery
    isi = "Riwayat backup (etl_audit.backup_log):\n"
    isi += tabel("SELECT folder, to_char(started_at, 'YYYY-MM-DD HH24:MI') AS mulai, status, db_dump_mb, "
                 "raw_archive_mb, n_tables AS tabel, total_rows AS baris, restore_status AS uji_restore, "
                 "restore_sec FROM etl_audit.backup_log ORDER BY started_at DESC LIMIT 15")
    isi += "\n\n" + pohon(Path(os.getenv("BACKUP_DIR") or (config.PROJECT_ROOT / "backups")), maks=80)
    tulis("09_backup.txt", "Backup harian dan uji restore", isi)
    ringkasan.append("09 Backup: riwayat backup, hasil uji restore, isi folder backups")

    (OUT / "RINGKASAN.md").write_text(
        f"# Bukti eksekusi pipeline FitZone\n\nDiambil {datetime.now(WIB):%Y-%m-%d %H:%M:%S} WIB dari database "
        f"{config.DW_NAME}, Data Lake, dan Airflow.\n\n" + "\n".join(f"- {s}" for s in ringkasan) + "\n",
        encoding="utf-8")
    print(f"Bukti tersimpan di {OUT}")
    for s in ringkasan:
        print(" -", s)


if __name__ == "__main__":
    main()

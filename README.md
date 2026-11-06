# Pipeline Big Data PT FitZone Nusantara

Proyek UAS Kecerdasan Bisnis / Big Data — Muhammad Nafis Putra (2410817210021).

Pipeline end-to-end yang menggabungkan **data internal** (ekspor CSV kebiasaan latihan member)
dan **data eksternal** (WHO Global Health Observatory API) ke dalam Data Lake dan Data Warehouse
PostgreSQL, diorkestrasi dengan Apache Airflow.

## Arsitektur

```
 CSV ekspor member (harian) ─┐
                             ├─> [Ingestion] ─> Data Lake RAW ─> Staging (stg) ─> [Transform + Quality Gate]
 WHO GHO API, JSON (bulanan)─┘     checksum,      file asli +      PostgreSQL         aturan 1-16, etl_reject
                                   retry 3x       manifest.json                              │
                                                                                             v
            Dashboard <── Data Mart (dw.mart_*) <── Data Warehouse (star schema, dw) <── Data Lake CURATED
            Model ML  <──┘                           rekonsiliasi, 1 transaksi            (parquet)
                         Orkestrasi: Airflow DAG  ·  Audit: etl_audit.etl_log / etl_reject
```

| Lapisan | Lokasi | Isi |
|---|---|---|
| Raw zone | `data_lake/raw/source=<sumber>/ingest_date=<tgl>/batch_id=<n>/` | File asli (CSV / JSON API) + `manifest.json`, tidak pernah diubah |
| Staging | schema `stg` | Salinan raw per batch, semua kolom teks |
| Curated zone | `data_lake/curated/<entitas>/batch_id=<n>/data.parquet` | Data bersih setelah transform |
| Data Warehouse | schema `dw` | 7 dimensi, 3 fakta (star schema) |
| Data Mart | `dw.mart_*` | Retensi & pemula, program & pemasaran, benchmark WHO, WHO per negara |
| Audit | schema `etl_audit` | Log batch, baris ditolak, ringkasan ETL |

## Struktur folder

```
dags/        DAG Airflow (member harian 02:00, WHO bulanan tgl 1 03:00)
etl/         kode pipeline: ingest, member, who, audit, lake, notify, run_pipeline
sql/         DDL: peran, schema, audit, staging, dimensi, fakta, seed, mart, hak akses
docker/      skrip inisialisasi PostgreSQL
data/source/ letakkan file CSV member di sini (tidak di-upload ke GitHub bila rahasia)
data_lake/   raw dan curated zone (dibuat oleh pipeline)
scripts/     cek WHO API, backup database
tests/       uji aturan transform dan uji pipeline ke database
```

## Kebutuhan

- Windows 10/11 dengan **Docker Desktop** (WSL2), RAM 8 GB ke atas (diuji untuk 12 GB)
- Python 3.11 (untuk menjalankan tes dan skrip di VS Code; opsional)

Agar Docker tidak memakai seluruh RAM, buat file `C:\Users\<nama>\.wslconfig`:

```ini
[wsl2]
memory=6GB
processors=4
```

lalu jalankan `wsl --shutdown` dan buka ulang Docker Desktop.

## Cara menjalankan

```powershell
# 1. Siapkan konfigurasi dan isi kata sandi
copy .env.example .env
notepad .env

# 2. Letakkan file sumber
#    data\source\gym_members_exercise_tracking.csv

# 3. Build dan jalankan (pertama kali sekitar 5-10 menit)
docker compose build
docker compose up -d
docker compose ps          # tunggu airflow-webserver "healthy"

# 4. Buka Airflow: http://localhost:8090 (login sesuai AIRFLOW_ADMIN_USER / PASSWORD di .env)
#    Aktifkan DAG fitzone_member_daily dan fitzone_who_monthly, lalu klik "Trigger DAG".
```

Saat volume database masih kosong, container PostgreSQL otomatis membuat database `airflow`,
peran (`etl_user`, `bi_analyst`, `dashboard_ro`), schema, tabel, seed, dan data mart.
Bila skrip SQL diubah dan ingin dibuat ulang dari nol: `docker compose down -v` (menghapus isi database lokal).

### Menjalankan tanpa Airflow (terminal VS Code)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
# Di .env (untuk akses dari laptop ke container): DW_HOST=localhost

python -m etl.run_pipeline member          # CSV -> Data Lake -> DWH
python -m etl.run_pipeline who             # WHO API -> Data Lake -> DWH
python -m etl.run_pipeline status          # 10 batch terakhir
python -m etl.run_pipeline replay member 5 # proses ulang batch 5 dari raw zone
python scripts\cek_who_api.py              # cek jumlah record WHO per indikator
```

## Pemeriksaan hasil (untuk konsultasi / demo)

```powershell
docker exec -it fitzone_postgres psql -U etl_user -d fitzone_dw
```

```sql
-- Log batch: status, jumlah baris, error
SELECT batch_id, source_name, stage, status, rows_read, rows_loaded, rows_rejected, duration_sec
FROM etl_audit.v_ringkasan_etl ORDER BY batch_id DESC;

-- Rekonsiliasi member (harus sama dengan jumlah baris bersih)
SELECT (SELECT COUNT(*) FROM dw.dim_member) AS dim_member,
       (SELECT COUNT(*) FROM dw.fact_workout_session) AS fact_session,
       (SELECT COUNT(*) FROM dw.fact_body_measurement) AS fact_body;

-- Data WHO: jumlah baris dan negara
SELECT COUNT(*) AS baris, COUNT(DISTINCT country_key) AS negara FROM dw.fact_who_benchmark;

-- Benchmark member vs Indonesia (tahun WHO terbaru)
SELECT * FROM dw.mart_benchmark_who ORDER BY who_code, gender;
```

## Penanganan kegagalan

| Kejadian | Penanganan |
|---|---|
| File CSV tidak ada / korup / kolom berubah / kosong | Batch FAILED di tahap ingest, DWH tidak berubah |
| File sama dengan batch sukses terakhir (checksum) | Batch SKIPPED |
| WHO API timeout / HTTP error / respons kosong / struktur berubah | Retry 3x jeda 5 menit, lalu FAILED; data WHO lama tetap dipakai |
| Baris ditolak > 5% | Quality gate menghentikan batch sebelum load, baris dicatat di `etl_reject` |
| Error saat load / rekonsiliasi tidak cocok | Rollback satu transaksi, DWH tetap berisi batch valid terakhir |
| Pemulihan | `replay` memproses ulang dari raw/curated zone tanpa mengambil ulang sumber |
| Notifikasi | Email lewat SMTP bila diisi di `.env`; selalu tercatat di log Airflow |

## Pengujian

```powershell
pytest -q                                   # uji aturan transform (tanpa database)

# Uji pipeline ke database KHUSUS UJI (tabel akan dikosongkan!)
$env:FITZONE_TEST_DB="1"; pytest -q tests\test_pipeline_db.py
```

Data uji di `tests/fixtures.py` dibuat acak (bukan data perusahaan).

## Backup

```powershell
powershell -ExecutionPolicy Bypass -File scripts\backup_dw.ps1
```

## Sumber data

- Data internal: ekspor CSV kebiasaan latihan member (973 baris, 15 kolom).
- Data eksternal: [WHO Global Health Observatory OData API](https://www.who.int/data/gho/info/gho-odata-api) —
  indikator `NCD_BMI_30A`, `NCD_BMI_25A`, `NCD_BMI_MEAN`, `NCD_PAA` untuk semua negara.

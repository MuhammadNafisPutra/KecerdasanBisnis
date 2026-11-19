# Bukti eksekusi pipeline FitZone

Diambil 2026-11-15 19:30:34 WIB dari database fitzone_dw, Data Lake, dan Airflow.

- 01 Sumber data dan ingestion: file CSV member dan riwayat ingestion per batch
- 02 Data Lake: 2 manifest di raw zone, file curated dan model
- 03 ETL: SUCCESS 3, SKIPPED 4
- 04 Data quality: baris ditolak, anomali BPM, rekonsiliasi jumlah baris
- 05 Data warehouse: 24 tabel/view di schema staging, dw, etl_audit
- 06 Lineage: baris fakta -> batch etl_log -> file raw + checksum
- 07 Airflow: daftar DAG dan riwayat run ketiga DAG utama
- 08 Machine learning: metrik semua model, metrics.json, status prediksi
- 09 Backup: riwayat backup, hasil uji restore, isi folder backups

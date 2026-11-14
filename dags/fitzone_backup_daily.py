"""DAG backup harian (Disaster Recovery).

Jadwal : setiap hari pukul 01:00 WIB (sebelum pipeline member pukul 02:00, saat sistem sepi).
Alur   : backup_database -> backup_data_lake -> uji_restore -> hapus_backup_lama
Lokasi : ./backups/<YYYYMMDD_HHMMSS>/  (fitzone_dw.dump, data_lake_raw.tar.gz, manifest.json)
Retensi: 7 hari terakhir + 1 backup per minggu selama 4 minggu.
"""
from datetime import timedelta

from airflow import DAG
from airflow.decorators import task

from fitzone_common import DEFAULT_ARGS, START

args = {**DEFAULT_ARGS, "retries": 1, "retry_delay": timedelta(minutes=10)}

with DAG(
    dag_id="fitzone_backup_daily",
    description="Backup harian database DWH dan Data Lake raw, dengan uji restore otomatis",
    schedule="0 1 * * *",
    start_date=START,
    catchup=False,
    max_active_runs=1,
    default_args=args,
    tags=["fitzone", "backup", "disaster-recovery"],
) as dag:

    @task
    def backup_database() -> str:
        from etl import backup
        return backup.backup_database()

    @task
    def backup_data_lake(folder: str) -> str:
        from etl import backup
        backup.backup_raw(folder)
        return folder

    @task(retries=0)
    def uji_restore(folder: str) -> dict:
        from etl import backup
        return backup.verify_restore(folder)

    @task(retries=0)  # hanya jalan bila uji restore LULUS: backup lama tidak dihapus saat backup baru gagal
    def hapus_backup_lama() -> list:
        from etl import backup
        return backup.apply_retention()

    hasil = uji_restore(backup_data_lake(backup_database()))
    hasil >> hapus_backup_lama()

"""DAG harian data member: CSV ekspor -> Data Lake raw -> staging -> transform -> DWH -> mart.

Jadwal: setiap hari 02:00 WIB (setelah backup 01:00).
Alur  : ingest >> stage >> transform >> load
- ingest    : retry 3x jeda 5 menit; file sama dengan batch sukses terakhir -> SKIPPED
- transform : TIDAK di-retry (error data/quality gate tidak hilang dengan dicoba ulang)
- load      : satu transaksi + rekonsiliasi + refresh materialized view
"""
from airflow import DAG
from airflow.decorators import task
from airflow.exceptions import AirflowSkipException

from fitzone_common import DEFAULT_ARGS, START

with DAG(
    dag_id="fitzone_member_daily",
    description="Pipeline harian data member PT FitZone Nusantara",
    schedule="0 2 * * *",
    start_date=START,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["fitzone", "member", "etl"],
) as dag:

    @task
    def ingest() -> int:
        from etl import ingest as ing
        try:
            return ing.ingest_member()
        except ing.SkipBatch as exc:
            raise AirflowSkipException(str(exc))

    @task
    def stage(batch_id: int) -> int:
        from etl import member
        member.stage_member(batch_id)
        return batch_id

    @task(retries=0)
    def transform(batch_id: int) -> int:
        from etl import member
        member.transform_member(batch_id)
        return batch_id

    @task
    def load(batch_id: int) -> int:
        from etl import member
        return member.load_member(batch_id)

    load(transform(stage(ingest())))

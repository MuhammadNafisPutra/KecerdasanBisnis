"""DAG bulanan data WHO GHO API: API -> Data Lake raw (JSON) -> staging -> transform -> upsert DWH.

Jadwal: tanggal 1 setiap bulan pukul 03:00 WIB.
Bila API gagal (timeout, HTTP error, respons kosong, struktur berubah): retry 3x jeda 5 menit,
lalu batch FAILED dan fact_who_benchmark tetap berisi data terakhir yang valid.
"""
from airflow import DAG
from airflow.decorators import task

from fitzone_common import DEFAULT_ARGS, START

with DAG(
    dag_id="fitzone_who_monthly",
    description="Pipeline bulanan data pembanding WHO GHO",
    schedule="0 3 1 * *",
    start_date=START,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["fitzone", "who", "api", "etl"],
) as dag:

    @task
    def ingest() -> int:
        from etl import ingest as ing
        return ing.ingest_who()

    @task
    def stage(batch_id: int) -> int:
        from etl import who
        who.stage_who(batch_id)
        return batch_id

    @task(retries=0)
    def transform(batch_id: int) -> int:
        from etl import who
        who.transform_who(batch_id)
        return batch_id

    @task
    def load(batch_id: int) -> int:
        from etl import who
        return who.load_who(batch_id)

    load(transform(stage(ingest())))

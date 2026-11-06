"""Pengaturan bersama DAG FitZone: retry, callback kegagalan, zona waktu."""
from datetime import timedelta

import pendulum

from etl import notify

TZ = pendulum.timezone("Asia/Jakarta")
START = pendulum.datetime(2026, 11, 1, tz=TZ)


def on_failure(context):
    """Callback: dipanggil Airflow saat task gagal setelah semua retry habis."""
    ti = context["task_instance"]
    notify.send_alert(
        f"{ti.dag_id}.{ti.task_id} GAGAL",
        f"Run: {context.get('run_id')}\nPercobaan: {ti.try_number}\n"
        f"Error: {context.get('exception')}\nLog: {ti.log_url}")


def on_retry(context):
    ti = context["task_instance"]
    notify.send_alert(f"{ti.dag_id}.{ti.task_id} dicoba ulang",
                      f"Percobaan {ti.try_number} gagal: {context.get('exception')}")


DEFAULT_ARGS = {
    "owner": "tim_bi",
    "retries": 3,                              # coba ulang 3 kali
    "retry_delay": timedelta(minutes=5),       # jeda 5 menit
    "on_failure_callback": on_failure,
    "on_retry_callback": on_retry,
    "execution_timeout": timedelta(minutes=30),
}

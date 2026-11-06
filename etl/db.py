"""Koneksi PostgreSQL dan fungsi bantu kecil."""
from contextlib import contextmanager

import psycopg2
import psycopg2.extras

from etl import config


def connect(autocommit: bool = False):
    conn = psycopg2.connect(
        host=config.DW_HOST,
        port=config.DW_PORT,
        dbname=config.DW_NAME,
        user=config.DW_USER,
        password=config.DW_PASSWORD or None,
        connect_timeout=10,
        application_name="fitzone_etl",
    )
    conn.autocommit = autocommit
    return conn


@contextmanager
def transaction():
    """Satu transaksi: commit bila sukses, rollback seluruh perubahan bila ada error."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def read_df(sql: str, params=None):
    """Jalankan SELECT dan kembalikan pandas DataFrame."""
    import pandas as pd

    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=cols)
    finally:
        conn.close()


def insert_rows(cur, table: str, columns: list[str], rows: list[tuple], page_size: int = 1000):
    """Insert banyak baris sekaligus (execute_values) agar cepat untuk data besar."""
    if not rows:
        return
    cols = ", ".join(f'"{c}"' for c in columns)
    psycopg2.extras.execute_values(
        cur, f"INSERT INTO {table} ({cols}) VALUES %s", rows, page_size=page_size)

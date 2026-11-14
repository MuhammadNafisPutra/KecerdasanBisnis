"""Koneksi dashboard ke data warehouse. Memakai role dashboard_ro (hanya baca mart)."""
import os

import pandas as pd
import psycopg2
import streamlit as st

TTL_DETIK = 3600  # cache 1 jam (sesuai rancangan UTS)


def _params() -> dict:
    return {
        "host": os.getenv("DW_HOST", "localhost"),
        "port": int(os.getenv("DW_PORT", "5432")),
        "dbname": os.getenv("DW_NAME", "fitzone_dw"),
        "user": os.getenv("DASHBOARD_USER", "dashboard_ro"),
        "password": os.getenv("DASHBOARD_PASSWORD", ""),
        "connect_timeout": 10,
    }


@st.cache_data(ttl=TTL_DETIK, show_spinner=False)
def query(sql: str) -> pd.DataFrame:
    """Jalankan SELECT dan kembalikan DataFrame. Hasil di-cache 1 jam."""
    with psycopg2.connect(**_params()) as conn, conn.cursor() as cur:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


def tersedia() -> tuple[bool, str]:
    try:
        with psycopg2.connect(**_params()) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
        return True, ""
    except Exception as exc:  # tampilkan pesan ramah, bukan stack trace
        return False, str(exc).splitlines()[0]

"""Uji integrasi pipeline ke PostgreSQL sungguhan memakai data uji buatan.

Hanya berjalan bila FITZONE_TEST_DB=1 (agar tidak menyentuh database demo tanpa sengaja).
Gunakan database KHUSUS UJI, karena tes ini mengosongkan tabel DWH dan etl_audit.

    set FITZONE_TEST_DB=1         (Windows)  /  export FITZONE_TEST_DB=1  (Linux/Mac)
    pytest -q tests/test_pipeline_db.py
"""
import os

import pytest

from etl import audit, config, db, ingest, member, who
from etl import run_pipeline
from tests.fixtures import dumps, make_country_payload, make_member_df, make_who_payload

pytestmark = pytest.mark.skipif(os.getenv("FITZONE_TEST_DB") != "1", reason="set FITZONE_TEST_DB=1")


@pytest.fixture(autouse=True)
def lingkungan_uji(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SOURCE_DIR", tmp_path / "source")
    monkeypatch.setattr(config, "RAW_DIR", tmp_path / "lake" / "raw")
    monkeypatch.setattr(config, "CURATED_DIR", tmp_path / "lake" / "curated")
    monkeypatch.setattr(config, "WHO_INDICATORS", ["NCD_BMI_30A", "NCD_BMI_MEAN"])
    config.SOURCE_DIR.mkdir(parents=True)
    run_pipeline.init_db()
    with db.transaction() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE dw.fact_workout_session, dw.fact_body_measurement, dw.dim_member, "
                    "dw.fact_who_benchmark, etl_audit.etl_reject, etl_audit.etl_log RESTART IDENTITY CASCADE")
    yield


def tulis_csv(df):
    df.to_csv(config.SOURCE_DIR / config.MEMBER_FILE, index=False)


def jalankan_member():
    b = ingest.ingest_member()
    member.stage_member(b)
    member.transform_member(b)
    member.load_member(b)
    return b


def hitung(sql):
    conn = db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchone()[0]
    finally:
        conn.close()


def test_member_end_to_end_dan_rekonsiliasi():
    tulis_csv(make_member_df(973))
    b = jalankan_member()
    assert audit.get_batch(b)["status"] == "SUCCESS"
    assert hitung("SELECT COUNT(*) FROM dw.fact_workout_session") == 973
    assert hitung("SELECT COUNT(*) FROM dw.fact_body_measurement") == 973
    assert hitung("SELECT COUNT(*) FROM dw.mart_retensi_pemula") == 973
    # data mentah tersimpan di raw zone apa adanya
    raw = list(config.RAW_DIR.rglob(config.MEMBER_FILE))
    assert len(raw) == 1 and raw[0].read_bytes() == (config.SOURCE_DIR / config.MEMBER_FILE).read_bytes()


def test_file_sama_dilewati_dan_jalan_ulang_tidak_menggandakan():
    tulis_csv(make_member_df(50))
    jalankan_member()
    with pytest.raises(ingest.SkipBatch):
        ingest.ingest_member()
    tulis_csv(make_member_df(60, seed=8))           # ekspor baru
    jalankan_member()
    assert hitung("SELECT COUNT(*) FROM dw.fact_workout_session") == 60


def test_quality_gate_menghentikan_batch_dan_dwh_tidak_berubah():
    tulis_csv(make_member_df(100))
    jalankan_member()
    df = make_member_df(100, seed=9)
    df.loc[:9, "Age"] = "abc"                        # 10% ditolak > batas 5%
    tulis_csv(df)
    b = ingest.ingest_member()
    member.stage_member(b)
    with pytest.raises(member.QualityGateError):
        member.transform_member(b)
    info = audit.get_batch(b)
    assert info["status"] == "FAILED" and info["stage"] == "transform"
    assert hitung(f"SELECT COUNT(*) FROM etl_audit.etl_reject WHERE batch_id = {b}") == 10
    # DWH masih berisi batch valid sebelumnya
    assert hitung("SELECT COUNT(*) FROM dw.fact_workout_session") == 100


def test_kolom_hilang_gagal_di_ingest():
    tulis_csv(make_member_df(10).drop(columns=["BMI"]))
    with pytest.raises(ValueError, match="kolom hilang"):
        ingest.ingest_member()


def test_load_gagal_rollback(monkeypatch):
    tulis_csv(make_member_df(30))
    jalankan_member()
    tulis_csv(make_member_df(40, seed=3))
    b = ingest.ingest_member()
    member.stage_member(b)
    member.transform_member(b)

    def rusak(*a, **k):
        raise RuntimeError("koneksi database terputus (simulasi)")
    with monkeypatch.context() as m:
        m.setattr(member.db, "insert_rows", rusak)
        with pytest.raises(RuntimeError):
            member.load_member(b)
    assert audit.get_batch(b)["status"] == "FAILED"
    assert hitung("SELECT COUNT(*) FROM dw.fact_workout_session") == 30      # rollback: data lama utuh
    member.load_member(b)                     # pemulihan: muat ulang dari curated, tanpa ambil ulang sumber
    assert audit.get_batch(b)["status"] == "SUCCESS"
    assert hitung("SELECT COUNT(*) FROM dw.fact_workout_session") == 40


def _fake_fetch(url, params=None):
    if url.endswith("DimensionValues"):
        return dumps(make_country_payload())
    code = url.rsplit("/", 1)[1]
    return dumps(make_who_payload(code, base=23 if code == "NCD_BMI_MEAN" else 15))


def test_who_end_to_end_upsert(monkeypatch):
    monkeypatch.setattr(ingest, "_fetch_json", _fake_fetch)
    tulis_csv(make_member_df(80))
    jalankan_member()
    for _ in range(2):                                # dijalankan 2x: upsert, tidak menggandakan
        b = ingest.ingest_who()
        who.stage_who(b)
        who.transform_who(b)
        who.load_who(b)
    # 2 indikator x 3 negara x 15 tahun x 2 gender (SEX_BTSX dan baris kawasan dibuang)
    assert hitung("SELECT COUNT(*) FROM dw.fact_who_benchmark") == 2 * 3 * 15 * 2
    assert hitung("SELECT COUNT(*) FROM dw.dim_country") == 3
    assert hitung("SELECT country_name FROM dw.dim_country WHERE country_code='IDN'") == "Indonesia"
    # 2 indikator yang diambil x 2 gender punya nilai WHO tahun 2024
    assert hitung("SELECT COUNT(*) FROM dw.mart_benchmark_who WHERE who_year = 2024") == 4


def test_who_api_gagal_dicatat(monkeypatch):
    def gagal(url, params=None):
        raise ConnectionError("WHO API timeout (simulasi)")
    monkeypatch.setattr(ingest, "_fetch_json", gagal)
    with pytest.raises(ConnectionError):
        run_pipeline.run_with_retry(ingest.ingest_who, retries=2, delay=0)
    statuses = [r for r in [audit.get_batch(i)["status"] for i in (1, 2, 3)]]
    assert statuses == ["FAILED", "FAILED", "FAILED"]   # 1 percobaan + 2 retry, semuanya tercatat

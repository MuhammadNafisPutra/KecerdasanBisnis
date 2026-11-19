"""Ambil screenshot otomatis halaman Airflow, dashboard, dan WHO API untuk laporan.

Jalankan di laptop (Docker harus menyala), dari folder proyek:
    pip install playwright
    python scripts/ambil_screenshot.py            # semua screenshot
    python scripts/ambil_screenshot.py s09 s13    # hanya screenshot tertentu

Memakai browser Microsoft Edge yang sudah terpasang di Windows, jadi tidak perlu mengunduh browser lain.
Username dan password Airflow dibaca dari file .env (AIRFLOW_ADMIN_USER, AIRFLOW_ADMIN_PASSWORD).
Hasil disimpan ke folder UAS/gambar_laporan (di luar repository) dengan nama s02, s05-s09, s13, s15-s22.
Satu screenshot yang gagal tidak menghentikan yang lain.
"""
import sys
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT.parents[1] / "gambar_laporan"
if not OUT.exists():
    OUT = ROOT / "data" / "screenshot"
OUT.mkdir(parents=True, exist_ok=True)

AIRFLOW = "http://localhost:8090"
DASHBOARD = "http://localhost:8501"
RUN_PERTAMA = quote("scheduled__2026-11-04T19:00:00+00:00", safe="")
WHO_API = "https://ghoapi.azureedge.net/api/NCD_BMI_30A?$filter=SpatialDim eq 'IDN'"


def baca_env() -> dict:
    env = {}
    f = ROOT / ".env"
    if f.exists():
        for baris in f.read_text(encoding="utf-8").splitlines():
            if "=" in baris and not baris.strip().startswith("#"):
                k, v = baris.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


hasil = []
PILIHAN = sys.argv[1:]          # contoh: python scripts/ambil_screenshot.py s09 s13  (kosong = semua)


def simpan(page, nama, tunggu_ms=2500, penuh=False):
    page.wait_for_timeout(tunggu_ms)
    path = OUT / nama
    page.screenshot(path=str(path), full_page=penuh)
    hasil.append(f"OK    {nama}")
    print("dibuat", path)


def coba(nama, fungsi):
    try:
        fungsi()
    except Exception as e:  # lanjut ke screenshot berikutnya
        hasil.append(f"GAGAL {nama}: {str(e).splitlines()[0][:120]}")
        print("GAGAL", nama, e)


def run_sukses_terakhir(page, dag):
    """Ambil run_id run sukses terbaru lewat REST API Airflow (memakai sesi login yang sama)."""
    r = page.request.get(f"{AIRFLOW}/api/v1/dags/{dag}/dagRuns",
                         params={"state": "success", "order_by": "-execution_date", "limit": "1"})
    runs = r.json().get("dag_runs", []) if r.ok else []
    return quote(runs[0]["dag_run_id"], safe="") if runs else None


def dipilih(nama):
    return not PILIHAN or any(nama.startswith(p) for p in PILIHAN)


def airflow(page, env):
    page.goto(f"{AIRFLOW}/login/")
    if page.locator("input[name=username]").count():
        page.fill("input[name=username]", env.get("AIRFLOW_ADMIN_USER", "admin"))
        page.fill("input[name=password]", env.get("AIRFLOW_ADMIN_PASSWORD", ""))
        page.locator("input[type=submit], button[type=submit]").first.click()
        page.wait_for_load_state("networkidle")
    if "/login" in page.url:
        raise RuntimeError("login Airflow gagal, cek AIRFLOW_ADMIN_PASSWORD di .env")

    who = run_sukses_terakhir(page, "fitzone_who_monthly")
    bak = run_sukses_terakhir(page, "fitzone_backup_daily")
    langkah = [
        ("s05_airflow_dags.png", f"{AIRFLOW}/home"),
        ("s06_dag_member_graph.png",
         f"{AIRFLOW}/dags/fitzone_member_daily/grid?dag_run_id={RUN_PERTAMA}&tab=graph"),
        ("s07_dag_member_grid.png", f"{AIRFLOW}/dags/fitzone_member_daily/grid"),
        ("s08_log_transform.png",
         f"{AIRFLOW}/dags/fitzone_member_daily/grid?dag_run_id={RUN_PERTAMA}&task_id=transform&tab=logs"),
        ("s09_dag_who_graph.png", f"{AIRFLOW}/dags/fitzone_who_monthly/grid?tab=graph"
                                  + (f"&dag_run_id={who}" if who else "")),
        ("s13_dag_backup_grid.png", f"{AIRFLOW}/dags/fitzone_backup_daily/grid?tab=graph"
                                    + (f"&dag_run_id={bak}" if bak else "")),
        ("s22_idempoten.png", f"{AIRFLOW}/dags/fitzone_member_daily/grid?tab=graph"),
    ]
    for nama, url in langkah:
        if not dipilih(nama):
            continue
        def ambil(nama=nama, url=url):
            page.goto(url)
            page.wait_for_load_state("networkidle")
            simpan(page, nama, tunggu_ms=4000)
        coba(nama, ambil)


def dashboard(page):
    page.goto(DASHBOARD)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(6000)
    halaman = [
        ("s15_ringkasan.png", "Ringkasan Eksekutif"),
        ("s16_retensi.png", "Retensi & Pemula"),
        ("s17_program.png", "Program & Pemasaran"),
        ("s18_who.png", "Benchmark WHO"),
        ("s19_ml.png", "Prediksi Lemak Tubuh (ML)"),
        ("s20_etl.png", "Kualitas Data & ETL"),
    ]
    for nama, judul in halaman:
        if not dipilih(nama):
            continue
        def ambil(nama=nama, judul=judul):
            page.locator("section[data-testid=stSidebar]").get_by_text(judul, exact=True).click()
            page.wait_for_load_state("networkidle")
            simpan(page, nama, tunggu_ms=6000)
        coba(nama, ambil)

    def filter_pemula():
        page.locator("section[data-testid=stSidebar]").get_by_text("Ringkasan Eksekutif", exact=True).click()
        page.wait_for_timeout(4000)
        level = page.locator("div[data-testid=stMultiSelect]").nth(3)   # urutan: gender, latihan, usia, level
        level.click()
        page.get_by_role("option", name="Pemula").click()
        page.keyboard.press("Escape")
        page.wait_for_load_state("networkidle")
        simpan(page, "s21_filter.png", tunggu_ms=6000)
    if dipilih("s21_filter.png"):
        coba("s21_filter.png", filter_pemula)


def who_api(page):
    if not dipilih("s02_who_api.png"):
        return

    def ambil():
        page.goto(WHO_API, timeout=90000)
        simpan(page, "s02_who_api.png", tunggu_ms=1500)
    coba("s02_who_api.png", ambil)


def main():
    env = baca_env()
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="msedge")
        except Exception:
            browser = p.chromium.launch()     # bila Edge tidak ada: python -m playwright install chromium
        page = browser.new_page(viewport={"width": 1440, "height": 1700}, device_scale_factor=1.5)
        page.set_default_timeout(45000)
        coba("airflow", lambda: airflow(page, env))
        if any(dipilih(f"s{n}") for n in range(15, 22)):
            dashboard(page)
        who_api(page)
        browser.close()
    print("\nRingkasan:")
    print("\n".join(hasil))
    print(f"\nFolder hasil: {OUT}")
    if any(h.startswith("GAGAL") for h in hasil):
        sys.exit(1)


if __name__ == "__main__":
    main()

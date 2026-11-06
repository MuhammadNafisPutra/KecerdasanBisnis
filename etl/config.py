"""Pengaturan pipeline. Semua nilai bisa diubah lewat variabel lingkungan (.env)."""
import os
from pathlib import Path

try:  # saat dijalankan di VS Code, baca .env otomatis; di Docker nilai sudah dari env_file
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return default if value is None or value.strip() == "" else value.strip()


PROJECT_ROOT = Path(_env("PROJECT_ROOT", str(Path(__file__).resolve().parents[1])))
SQL_DIR = PROJECT_ROOT / "sql"

# Data Lake (raw zone dan curated zone)
DATA_LAKE_DIR = Path(_env("DATA_LAKE_DIR", str(PROJECT_ROOT / "data_lake")))
RAW_DIR = DATA_LAKE_DIR / "raw"
CURATED_DIR = DATA_LAKE_DIR / "curated"

# Sumber internal: folder tempat file ekspor CSV diletakkan
SOURCE_DIR = Path(_env("SOURCE_DIR", str(PROJECT_ROOT / "data" / "source")))
MEMBER_FILE = _env("MEMBER_FILE", "gym_members_exercise_tracking.csv")

# Sumber eksternal: WHO Global Health Observatory OData API
WHO_BASE_URL = _env("WHO_BASE_URL", "https://ghoapi.azureedge.net/api")
WHO_INDICATORS = [x.strip() for x in _env(
    "WHO_INDICATORS", "NCD_BMI_30A,NCD_BMI_25A,NCD_BMI_MEAN,NCD_PAA").split(",") if x.strip()]
WHO_COUNTRIES = [x.strip().upper() for x in _env("WHO_COUNTRIES", "").split(",") if x.strip()]
WHO_TIMEOUT_SEC = int(_env("WHO_TIMEOUT_SEC", "60"))

# Koneksi data warehouse
DW_HOST = _env("DW_HOST", "localhost")
DW_PORT = int(_env("DW_PORT", "5432"))
DW_NAME = _env("DW_NAME", "fitzone_dw")
DW_USER = _env("DW_USER", "etl_user")
DW_PASSWORD = _env("DW_PASSWORD", "")

# Aturan ETL
REJECT_THRESHOLD = float(_env("REJECT_THRESHOLD", "0.05"))      # quality gate 5%
EXPECTED_MEMBER_ROWS = int(_env("EXPECTED_MEMBER_ROWS", "0"))   # 0 = tidak dipaksa
RETRY_COUNT = int(_env("RETRY_COUNT", "3"))
RETRY_DELAY_SEC = int(_env("RETRY_DELAY_SEC", "300"))           # 5 menit

# Nama sumber (dipakai di etl_log dan Data Lake)
SRC_MEMBER = "gym_csv"
SRC_WHO = "who_gho_api"

# Notifikasi email (opsional)
SMTP_HOST = _env("SMTP_HOST")
SMTP_PORT = int(_env("SMTP_PORT", "587"))
SMTP_USER = _env("SMTP_USER")
SMTP_PASSWORD = _env("SMTP_PASSWORD")
ALERT_EMAIL_TO = _env("ALERT_EMAIL_TO")

"""Data Lake berbasis folder.

raw zone     : data_lake/raw/source=<sumber>/ingest_date=<YYYY-MM-DD>/batch_id=<n>/<file asli>
               + manifest.json (checksum, ukuran, jumlah record, waktu ambil, URL sumber)
curated zone : data_lake/curated/<entitas>/batch_id=<n>/data.parquet

Raw tidak pernah diubah setelah ditulis, sehingga data bisa diaudit dan diproses ulang
(misalnya setelah transform gagal atau saat pemulihan bencana).
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from etl import config


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def raw_batch_dir(source: str, batch_id: int, ingest_dt: datetime | None = None) -> Path:
    ingest_dt = ingest_dt or datetime.now(timezone.utc).astimezone()
    return config.RAW_DIR / f"source={source}" / f"ingest_date={ingest_dt:%Y-%m-%d}" / f"batch_id={batch_id}"


def write_raw(batch_dir: Path, filename: str, data: bytes) -> Path:
    batch_dir.mkdir(parents=True, exist_ok=True)
    path = batch_dir / filename
    path.write_bytes(data)
    return path


def write_manifest(batch_dir: Path, manifest: dict) -> Path:
    manifest = {"written_at": datetime.now(timezone.utc).isoformat(), **manifest}
    path = batch_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def read_manifest(batch_dir: Path) -> dict:
    return json.loads((batch_dir / "manifest.json").read_text(encoding="utf-8"))


def find_raw_batch(source: str, batch_id: int) -> Path:
    matches = list((config.RAW_DIR / f"source={source}").glob(f"ingest_date=*/batch_id={batch_id}"))
    if not matches:
        raise FileNotFoundError(f"Data raw untuk {source} batch {batch_id} tidak ditemukan di Data Lake")
    return matches[0]


def curated_path(entity: str, batch_id: int) -> Path:
    return config.CURATED_DIR / entity / f"batch_id={batch_id}" / "data.parquet"


def write_curated(entity: str, batch_id: int, df: pd.DataFrame) -> Path:
    path = curated_path(entity, batch_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def read_curated(entity: str, batch_id: int) -> pd.DataFrame:
    path = curated_path(entity, batch_id)
    if not path.exists():
        raise FileNotFoundError(f"Data curated {entity} batch {batch_id} tidak ada: {path}")
    return pd.read_parquet(path)

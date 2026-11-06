"""Tahap Data Ingestion: sumber -> Data Lake raw zone.

Data disimpan apa adanya (byte asli file CSV / respons JSON API) beserta manifest,
lalu dicatat di etl_log (checksum dan lokasi raw untuk lineage).
"""
import hashlib
import io
import json
import logging

import pandas as pd
import requests

from etl import audit, config, lake
from etl.schemas import MEMBER_COLUMNS, WHO_REQUIRED_FIELDS

log = logging.getLogger("fitzone.ingest")


class SkipBatch(Exception):
    """Tidak ada data baru (file sama dengan batch sukses terakhir). Bukan error."""


# ---------------------------------------------------------------- data member (CSV)
def ingest_member() -> int:
    batch_id = audit.start_batch(config.SRC_MEMBER, "ingest")
    try:
        src = config.SOURCE_DIR / config.MEMBER_FILE
        if not src.exists():
            raise FileNotFoundError(f"file tidak ditemukan: {src}")
        data = src.read_bytes()
        checksum = lake.sha256_bytes(data)

        # Cek file bisa dibaca dan strukturnya benar (file korup / kolom berubah -> gagal)
        try:
            df = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False)
        except Exception as exc:
            raise ValueError(f"file CSV korup atau tidak bisa dibaca: {exc}") from exc
        missing = [c for c in MEMBER_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"struktur file berubah, kolom hilang: {missing}")
        if len(df) == 0:
            raise ValueError("file CSV kosong (0 baris)")
        if config.EXPECTED_MEMBER_ROWS and len(df) != config.EXPECTED_MEMBER_ROWS:
            raise ValueError(f"jumlah baris {len(df)} tidak sama dengan yang diharapkan "
                             f"{config.EXPECTED_MEMBER_ROWS}")

        if checksum == audit.last_success_checksum(config.SRC_MEMBER):
            audit.update_batch(batch_id, status="SKIPPED", source_checksum=checksum, rows_read=len(df),
                               notes="file sama dengan batch sukses terakhir; tidak ada data baru")
            raise SkipBatch(f"Batch {batch_id}: file tidak berubah, batch dilewati")

        bdir = lake.raw_batch_dir(config.SRC_MEMBER, batch_id)
        lake.write_raw(bdir, src.name, data)
        lake.write_manifest(bdir, {
            "source": config.SRC_MEMBER, "batch_id": batch_id, "file": src.name,
            "sha256": checksum, "size_bytes": len(data), "rows": len(df), "columns": list(df.columns),
        })
        audit.update_batch(batch_id, stage="ingest", source_checksum=checksum,
                           raw_path=str(bdir), rows_read=len(df))
        log.info("Batch %s: %d baris member disimpan ke raw zone %s", batch_id, len(df), bdir)
        return batch_id
    except SkipBatch:
        raise
    except Exception as exc:
        audit.fail_batch(batch_id, "ingest", exc)
        raise


# ---------------------------------------------------------------- data WHO (API)
def _fetch_json(url: str, params: dict | None = None) -> bytes:
    resp = requests.get(url, params=params, timeout=config.WHO_TIMEOUT_SEC,
                        headers={"User-Agent": "fitzone-etl/1.0", "Accept": "application/json"})
    resp.raise_for_status()                       # HTTP error -> exception -> retry oleh Airflow
    json.loads(resp.content)                      # respons bukan JSON -> exception
    return resp.content


def _country_filter() -> dict | None:
    if not config.WHO_COUNTRIES:
        return None                               # semua negara
    return {"$filter": " or ".join(f"SpatialDim eq '{c}'" for c in config.WHO_COUNTRIES)}


def ingest_who() -> int:
    batch_id = audit.start_batch(config.SRC_WHO, "ingest")
    try:
        bdir = lake.raw_batch_dir(config.SRC_WHO, batch_id)
        counts, digests = {}, []
        for code in config.WHO_INDICATORS:
            url = f"{config.WHO_BASE_URL}/{code}"
            content = _fetch_json(url, _country_filter())
            values = json.loads(content).get("value")
            if not isinstance(values, list) or not values:
                raise ValueError(f"respons WHO kosong untuk indikator {code}")
            missing = WHO_REQUIRED_FIELDS - set(values[0].keys())
            if missing:
                raise ValueError(f"struktur respons WHO berubah ({code}), field hilang: {sorted(missing)}")
            lake.write_raw(bdir, f"{code}.json", content)
            counts[code] = len(values)
            digests.append(lake.sha256_bytes(content))
            log.info("WHO %s: %d record", code, len(values))

        # Nama negara (tidak wajib: bila gagal, nama negara diisi kode negara)
        note = ""
        try:
            content = _fetch_json(f"{config.WHO_BASE_URL}/DIMENSION/COUNTRY/DimensionValues")
            lake.write_raw(bdir, "DIM_COUNTRY.json", content)
        except Exception as exc:
            note = f"daftar nama negara gagal diambil ({type(exc).__name__}); nama negara = kode"
            log.warning(note)

        checksum = hashlib.sha256("".join(digests).encode()).hexdigest()
        lake.write_manifest(bdir, {
            "source": config.SRC_WHO, "batch_id": batch_id, "base_url": config.WHO_BASE_URL,
            "indicators": config.WHO_INDICATORS, "countries": config.WHO_COUNTRIES or "ALL",
            "records_per_indicator": counts, "sha256_combined": checksum,
        })
        audit.update_batch(batch_id, stage="ingest", source_checksum=checksum, raw_path=str(bdir),
                           rows_read=sum(counts.values()),
                           notes=f"record per indikator: {counts}" + (f"; {note}" if note else ""))
        return batch_id
    except Exception as exc:
        audit.fail_batch(batch_id, "ingest", exc)
        raise

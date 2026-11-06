"""Pipeline data WHO GHO: raw zone (JSON) -> staging -> transform (curated) -> upsert ke DWH.

Aturan transform WHO (lanjutan aturan 13-16 dokumen desain):
 13 hanya negara (SpatialDimType = COUNTRY) dan gender SEX_MLE/SEX_FMLE -> Male/Female
    (SEX_BTSX = gabungan kedua gender dan data kawasan/global dibuang saat staging)
 14 pilih dan ganti nama kolom: NumericValue->value, Low->low, High->high, TimeDim->year
    hanya kelompok umur dewasa (Dim2 kosong atau AGEGROUP_YEARS18-PLUS)
 15 validasi tipe dan rentang: persen 0-100, rata-rata BMI 10-60; kunci ganda ditolak
 16 kolom audit
"""
import json
import logging

import pandas as pd
import psycopg2.extras

from etl import audit, config, db, lake
from etl.member import QualityGateError, ReconciliationError
from etl.schemas import WHO_ALLOWED_DIM2, WHO_SEX_CODES

log = logging.getLogger("fitzone.who")
ENTITY = "who_clean"
ENTITY_COUNTRY = "who_country"
SEX_TO_GENDER = {"SEX_MLE": "Male", "SEX_FMLE": "Female"}

STG_COLS = ["indicator_code", "spatial_dim_type", "spatial_dim", "parent_location_code", "parent_location",
            "time_dim", "dim1", "dim2", "numeric_value", "low", "high", "value_text", "date_modified"]
JSON_FIELDS = ["IndicatorCode", "SpatialDimType", "SpatialDim", "ParentLocationCode", "ParentLocation",
               "TimeDim", "Dim1", "Dim2", "NumericValue", "Low", "High", "Value", "Date"]


def _txt(v):
    return None if v is None else str(v)


def parse_raw_who(bdir) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Baca semua file indikator di folder raw batch. Hasil: (record, negara, statistik filter)."""
    manifest = lake.read_manifest(bdir)
    records, stats = [], {"raw_records": 0, "dropped_not_country": 0, "dropped_sex_other": 0}
    for code in manifest["indicators"]:
        values = json.loads((bdir / f"{code}.json").read_text(encoding="utf-8"))["value"]
        stats["raw_records"] += len(values)
        for v in values:
            if v.get("SpatialDimType") != "COUNTRY":
                stats["dropped_not_country"] += 1
                continue
            if v.get("Dim1") not in WHO_SEX_CODES:
                stats["dropped_sex_other"] += 1
                continue
            records.append([_txt(v.get(f)) for f in JSON_FIELDS])
    df = pd.DataFrame(records, columns=STG_COLS)

    countries = pd.DataFrame(columns=["country_code", "country_name"])
    dim_file = bdir / "DIM_COUNTRY.json"
    if dim_file.exists():
        vals = json.loads(dim_file.read_text(encoding="utf-8")).get("value", [])
        countries = pd.DataFrame([{"country_code": d.get("Code"), "country_name": d.get("Title")}
                                  for d in vals if d.get("Code")])
    return df, countries, stats


def stage_who(batch_id: int) -> int:
    try:
        bdir = lake.find_raw_batch(config.SRC_WHO, batch_id)
        df, countries, stats = parse_raw_who(bdir)
        with db.transaction() as conn, conn.cursor() as cur:
            cur.execute("TRUNCATE stg.stg_who_gho, stg.stg_who_country")
            db.insert_rows(cur, "stg.stg_who_gho", STG_COLS + ["load_batch_id"],
                           [tuple(r) + (batch_id,) for r in df.itertuples(index=False, name=None)])
            db.insert_rows(cur, "stg.stg_who_country", ["country_code", "country_name", "load_batch_id"],
                           [tuple(r) + (batch_id,) for r in countries.itertuples(index=False, name=None)])
        audit.update_batch(batch_id, stage="stage", notes=f"staging: {len(df)} baris, filter {stats}")
        log.info("Batch %s: %d baris WHO masuk staging (%s)", batch_id, len(df), stats)
        return len(df)
    except Exception as exc:
        audit.fail_batch(batch_id, "stage", exc)
        raise


def transform_who_df(stg: pd.DataFrame, units: dict) -> tuple[pd.DataFrame, list[dict], dict]:
    df = stg.copy().reset_index(drop=True)
    df["row_no"] = df.index + 1
    rows_read = len(df)

    # Aturan 14: hanya kelompok umur dewasa. Bila suatu indikator hanya punya SATU kode umur
    # (kode berbeda dari dugaan), kode itu diterima agar data tidak terbuang diam-diam.
    dim2 = df["dim2"].fillna("")
    allowed = dim2.isin(WHO_ALLOWED_DIM2)
    single_code = dim2.groupby(df["indicator_code"]).transform("nunique") == 1
    other_age = ~(allowed | single_code)
    n_other_age = int(other_age.sum())
    age_codes = sorted(set(dim2[~other_age]))
    df = df.loc[~other_age].copy()

    reasons = {int(r): [] for r in df["row_no"]}

    def flag(mask, reason):
        for r in df.loc[mask, "row_no"]:
            reasons[int(r)].append(reason)

    df["year"] = pd.to_numeric(df["time_dim"], errors="coerce")
    df["value"] = pd.to_numeric(df["numeric_value"], errors="coerce")
    df["low"] = pd.to_numeric(df["low"], errors="coerce")
    df["high"] = pd.to_numeric(df["high"], errors="coerce")
    flag(df["year"].isna() | (df["year"] % 1 != 0), "tahun tidak valid")
    flag(df["value"].isna(), "NumericValue kosong atau bukan angka")
    flag(df["year"].notna() & ((df["year"] < 1950) | (df["year"] > 2100)), "tahun di luar rentang 1950-2100")

    # Aturan 15: rentang menurut satuan indikator
    unit = df["indicator_code"].map(units).fillna("")
    pct = unit.eq("%")
    bmi = unit.eq("kg/m2")
    flag(pct & df["value"].notna() & ((df["value"] < 0) | (df["value"] > 100)), "persen di luar 0-100")
    flag(bmi & df["value"].notna() & ((df["value"] < 10) | (df["value"] > 60)), "rata-rata BMI di luar 10-60")
    flag(df["spatial_dim"].fillna("").str.len() == 0, "kode negara kosong")

    key = ["indicator_code", "dim1", "spatial_dim", "time_dim"]
    flag(df.duplicated(subset=key, keep=False), "kunci ganda (indikator, gender, negara, tahun)")

    rejected = {r for r, rs in reasons.items() if rs}
    rejects = [{"source_row_no": r, "reject_reason": "; ".join(reasons[r]),
                "raw_record": df.loc[df["row_no"] == r, STG_COLS].iloc[0].to_dict()}
               for r in sorted(rejected)]
    clean = df.loc[~df["row_no"].isin(rejected)].copy()
    clean["year"] = clean["year"].astype("int64")
    clean["gender"] = clean["dim1"].map(SEX_TO_GENDER)
    clean = clean.rename(columns={"spatial_dim": "country_code", "parent_location_code": "who_region_code",
                                  "parent_location": "who_region_name"})
    clean = clean[["indicator_code", "gender", "country_code", "who_region_code", "who_region_name",
                   "year", "value", "low", "high"]].reset_index(drop=True)

    stats = {
        "rows_read": rows_read,
        "dropped_other_age_group": n_other_age,
        "age_codes_used": age_codes,
        "rows_rejected": len(rejects),
        "rows_clean": len(clean),
        "countries": int(clean["country_code"].nunique()),
        "indicators": int(clean["indicator_code"].nunique()),
        "year_min": int(clean["year"].min()) if len(clean) else None,
        "year_max": int(clean["year"].max()) if len(clean) else None,
        "reject_ratio": round(len(rejects) / rows_read, 4) if rows_read else 0.0,
    }
    return clean, rejects, stats


def transform_who(batch_id: int) -> dict:
    try:
        stg = db.read_df(f"SELECT {', '.join(STG_COLS)} FROM stg.stg_who_gho WHERE load_batch_id = %(b)s",
                         {"b": batch_id})
        countries = db.read_df(
            "SELECT country_code, country_name FROM stg.stg_who_country WHERE load_batch_id = %(b)s",
            {"b": batch_id})
        units = dict(db.read_df("SELECT who_code, unit FROM dw.dim_indicator").values)
        if stg.empty:
            raise ValueError(f"staging WHO kosong untuk batch {batch_id}")

        clean, rejects, stats = transform_who_df(stg, units)
        if clean.empty:
            raise ValueError(f"tidak ada baris WHO yang lolos transform; periksa struktur respons: {stats}")
        audit.write_rejects(batch_id, config.SRC_WHO, rejects)
        audit.update_batch(batch_id, stage="transform", rows_rejected=stats["rows_rejected"],
                           notes=f"transform: {stats}")
        if stats["reject_ratio"] > config.REJECT_THRESHOLD:
            raise QualityGateError(f"{stats['rows_rejected']} dari {stats['rows_read']} baris WHO ditolak "
                                   f"({stats['reject_ratio']:.1%}) melebihi batas {config.REJECT_THRESHOLD:.0%}")

        # Tabel negara: kode dari data + nama dari dimensi COUNTRY (bila tersedia)
        ctry = (clean[["country_code", "who_region_code", "who_region_name"]]
                .drop_duplicates("country_code")
                .merge(countries.drop_duplicates("country_code"), on="country_code", how="left"))
        ctry["country_name"] = ctry["country_name"].fillna(ctry["country_code"])
        lake.write_curated(ENTITY_COUNTRY, batch_id, ctry)
        path = lake.write_curated(ENTITY, batch_id, clean)
        audit.update_batch(batch_id, curated_path=str(path))
        return stats
    except Exception as exc:
        audit.fail_batch(batch_id, "transform", exc)
        raise


def load_who(batch_id: int) -> int:
    """Upsert: tahun baru ditambah, tahun lama diperbarui bila WHO merevisi data."""
    try:
        df = lake.read_curated(ENTITY, batch_id)
        ctry = lake.read_curated(ENTITY_COUNTRY, batch_id)
        with db.transaction() as conn, conn.cursor() as cur:
            # Indikator baru (di luar seed) ditambahkan otomatis
            for code in sorted(set(df["indicator_code"])):
                cur.execute("INSERT INTO dw.dim_indicator (who_code, indicator_name, unit, load_batch_id, "
                            "source_name) VALUES (%s, %s, '-', %s, %s) ON CONFLICT (who_code) DO NOTHING",
                            (code, code.lower(), batch_id, config.SRC_WHO))

            psycopg2.extras.execute_values(cur, """
                INSERT INTO dw.dim_country (country_code, country_name, who_region_code, who_region_name,
                                            load_batch_id, source_name)
                VALUES %s
                ON CONFLICT (country_code) DO UPDATE SET
                    country_name    = COALESCE(EXCLUDED.country_name, dw.dim_country.country_name),
                    who_region_code = COALESCE(EXCLUDED.who_region_code, dw.dim_country.who_region_code),
                    who_region_name = COALESCE(EXCLUDED.who_region_name, dw.dim_country.who_region_name),
                    load_batch_id   = EXCLUDED.load_batch_id,
                    loaded_at       = now()
            """, [(r.country_code, r.country_name, r.who_region_code, r.who_region_name, batch_id,
                   config.SRC_WHO) for r in ctry.itertuples(index=False)])

            cur.execute("SELECT who_code, indicator_key FROM dw.dim_indicator")
            ind = dict(cur.fetchall())
            cur.execute("SELECT gender_name, gender_key FROM dw.dim_gender")
            gen = dict(cur.fetchall())
            cur.execute("SELECT country_code, country_key FROM dw.dim_country")
            cty = dict(cur.fetchall())

            def num(x):
                return None if pd.isna(x) else float(x)

            rows = [(ind[r.indicator_code], gen[r.gender], cty[r.country_code], int(r.year),
                     float(r.value), num(r.low), num(r.high), batch_id, config.SRC_WHO)
                    for r in df.itertuples(index=False)]
            psycopg2.extras.execute_values(cur, """
                INSERT INTO dw.fact_who_benchmark (indicator_key, gender_key, country_key, year,
                                                   value, low, high, load_batch_id, source_name)
                VALUES %s
                ON CONFLICT (indicator_key, gender_key, country_key, year) DO UPDATE SET
                    value = EXCLUDED.value, low = EXCLUDED.low, high = EXCLUDED.high,
                    load_batch_id = EXCLUDED.load_batch_id, loaded_at = now()
            """, rows, page_size=2000)

            # Rekonsiliasi: semua baris batch ini harus ada (baru atau diperbarui)
            cur.execute("SELECT COUNT(*) FROM dw.fact_who_benchmark WHERE load_batch_id = %s", (batch_id,))
            n = cur.fetchone()[0]
            if n != len(df):
                raise ReconciliationError(f"jumlah baris WHO tidak cocok: curated={len(df)}, dwh={n}")

        audit.update_batch(batch_id, status="SUCCESS", stage="load", rows_loaded=len(df),
                           notes=f"rekonsiliasi OK: {n} baris, {len(ctry)} negara")
        log.info("Batch %s: %d baris WHO di-upsert", batch_id, len(df))
        return len(df)
    except Exception as exc:
        audit.fail_batch(batch_id, "load", exc)
        raise

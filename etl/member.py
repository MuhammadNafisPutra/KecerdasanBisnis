"""Pipeline data member: raw zone -> staging -> transform (curated zone) -> load ke DWH.

Aturan transform mengikuti dokumen desain (aturan 1-12 dan 16):
 1 ganti nama kolom              7 tandai Avg_BPM > Max_BPM (bpm_anomaly_flag)
 2 nilai kosong -> ditolak       8 hitung ulang BMI, tandai selisih > 0,1
 3 baris ganda -> dihapus        9 kategori BMI (acuan WHO) dari BMI hitung ulang
 4 tipe data                     10 kelompok usia
 5 standardisasi teks + nilai    11 label level pengalaman (di dim_experience_level)
   yang diizinkan                12 member_key 1..N
 6 validasi rentang nilai        16 kolom audit
Baris yang ditolak (aturan 2, 4, 5, 6) dicatat di etl_reject dan dihitung pada quality gate.
"""
import logging

import numpy as np
import pandas as pd

from etl import audit, config, db, lake
from etl.schemas import (ALLOWED_GENDER, ALLOWED_WORKOUT, MEMBER_COLUMNS, MEMBER_FLOAT_COLS,
                         MEMBER_INT_COLS, MEMBER_RENAME)

log = logging.getLogger("fitzone.member")
ENTITY = "member_clean"


class QualityGateError(Exception):
    """Baris ditolak melebihi batas: batch dihentikan sebelum load."""


class ReconciliationError(Exception):
    """Jumlah baris di DWH tidak sama dengan data curated."""


# Aturan 6: (kolom, min, max). Batas dari dokumen desain + batas wajar untuk kolom lain.
RANGE_RULES = [
    ("age", 18, 100),
    ("fat_percentage", 3, 60),
    ("session_duration_hours", 0.01, 6),          # > 0 dan paling lama 6 jam
    ("weight_kg", 30, 250),
    ("height_m", 1.2, 2.3),
    ("max_bpm", 30, 230),
    ("avg_bpm", 30, 230),
    ("resting_bpm", 30, 120),
    ("calories_burned", 1, 5000),
    ("water_intake_liters", 0, 10),
    ("workout_frequency_days_week", 1, 7),
    ("experience_level", 1, 3),
    ("bmi", 10, 70),
]


def _age_group(age: int) -> str:
    if age < 30:
        return "18-29"
    if age < 40:
        return "30-39"
    if age < 50:
        return "40-49"
    return "50+"


def _bmi_category(bmi: float) -> str:
    if bmi < 18.5:
        return "Underweight"
    if bmi < 25.0:
        return "Normal"
    if bmi < 30.0:
        return "Overweight"
    return "Obese"


# ---------------------------------------------------------------- transform murni (bisa dites)
def transform_member_df(stg: pd.DataFrame) -> tuple[pd.DataFrame, list[dict], dict]:
    """stg: kolom asli (teks) + source_row_no. Hasil: (data bersih, daftar reject, statistik)."""
    df = stg.copy()
    for col in MEMBER_COLUMNS:
        df[col] = df[col].fillna("").astype(str).str.strip()
    raw_records = df.set_index("source_row_no")[MEMBER_COLUMNS].to_dict("index")
    rows_read = len(df)

    # Aturan 3: hapus baris ganda (seluruh kolom data sama), simpan baris pertama
    dup_mask = df.duplicated(subset=MEMBER_COLUMNS, keep="first")
    n_duplicates = int(dup_mask.sum())
    df = df.loc[~dup_mask]

    # Aturan 1: ganti nama kolom
    df = df.rename(columns=MEMBER_RENAME)
    reasons = {int(r): [] for r in df["source_row_no"]}

    def flag(mask: pd.Series, reason: str):
        for row_no in df.loc[mask, "source_row_no"]:
            reasons[int(row_no)].append(reason)

    # Aturan 2: nilai kosong
    for col in MEMBER_RENAME.values():
        flag(df[col] == "", f"nilai kosong: {col}")

    # Aturan 4: tipe data
    for col in MEMBER_INT_COLS + MEMBER_FLOAT_COLS:
        parsed = pd.to_numeric(df[col].where(df[col] != ""), errors="coerce")
        flag((df[col] != "") & parsed.isna(), f"tipe data bukan angka: {col}")
        if col in MEMBER_INT_COLS:
            flag(parsed.notna() & (parsed % 1 != 0), f"tipe data bukan bilangan bulat: {col}")
        df[col] = parsed

    # Aturan 5: standardisasi teks dan nilai yang diizinkan
    gender_map = {g.lower(): g for g in ALLOWED_GENDER}
    workout_map = {w.lower(): w for w in ALLOWED_WORKOUT}
    df["gender"] = df["gender"].str.lower().map(gender_map).fillna(df["gender"])
    df["workout_type"] = df["workout_type"].str.lower().map(workout_map).fillna(df["workout_type"])
    flag((df["gender"] != "") & ~df["gender"].isin(ALLOWED_GENDER), "gender di luar daftar (Male/Female)")
    flag((df["workout_type"] != "") & ~df["workout_type"].isin(ALLOWED_WORKOUT),
         "workout_type di luar daftar (Cardio/Strength/HIIT/Yoga)")

    # Aturan 6: rentang nilai
    for col, lo, hi in RANGE_RULES:
        flag(df[col].notna() & ((df[col] < lo) | (df[col] > hi)), f"di luar rentang {col} [{lo}, {hi}]")
    flag(df["resting_bpm"].notna() & df["avg_bpm"].notna() & (df["resting_bpm"] >= df["avg_bpm"]),
         "resting_bpm harus lebih kecil dari avg_bpm")

    rejected_rows = {r for r, rs in reasons.items() if rs}
    rejects = [{"source_row_no": r, "reject_reason": "; ".join(reasons[r]),
                "raw_record": raw_records[r]} for r in sorted(rejected_rows)]
    clean = df.loc[~df["source_row_no"].isin(rejected_rows)].copy()

    for col in MEMBER_INT_COLS:
        clean[col] = clean[col].astype("int64")

    # Aturan 7: Avg_BPM > Max_BPM ditandai, tidak dihapus
    clean["bpm_anomaly_flag"] = (clean["avg_bpm"] > clean["max_bpm"]).astype("int64")

    # Aturan 8: hitung ulang BMI
    bmi_exact = clean["weight_kg"] / clean["height_m"] ** 2
    clean["bmi_recalc"] = bmi_exact.round(2)
    clean["bmi_diff"] = (clean["bmi"] - bmi_exact).abs()
    clean["bmi_mismatch_flag"] = (clean["bmi_diff"] > 0.1).astype("int64")

    # Aturan 9 dan 10: kategori BMI (dari BMI hitung ulang) dan kelompok usia
    clean["bmi_category"] = clean["bmi_recalc"].map(_bmi_category)
    clean["age_group"] = clean["age"].map(_age_group)

    # Aturan 12: member_key berurutan menurut nomor baris sumber
    clean = clean.sort_values("source_row_no").reset_index(drop=True)
    clean["member_key"] = np.arange(1, len(clean) + 1, dtype="int64")

    stats = {
        "rows_read": rows_read,
        "duplicates_removed": n_duplicates,
        "rows_rejected": len(rejects),
        "rows_clean": len(clean),
        "bpm_anomaly": int(clean["bpm_anomaly_flag"].sum()),
        "bmi_mismatch": int(clean["bmi_mismatch_flag"].sum()),
        "bmi_max_diff": round(float(clean["bmi_diff"].max()), 4) if len(clean) else None,
        "reject_ratio": round(len(rejects) / rows_read, 4) if rows_read else 0.0,
    }
    return clean.drop(columns=["bmi_diff"]), rejects, stats


# ---------------------------------------------------------------- tahap pipeline
def stage_member(batch_id: int) -> int:
    """Raw zone -> stg.stg_gym_members (dikosongkan dulu, lalu diisi ulang)."""
    try:
        bdir = lake.find_raw_batch(config.SRC_MEMBER, batch_id)
        manifest = lake.read_manifest(bdir)
        df = pd.read_csv(bdir / manifest["file"], dtype=str, keep_default_na=False)
        df.insert(0, "source_row_no", np.arange(1, len(df) + 1))
        rows = [tuple(r) + (batch_id,) for r in df[["source_row_no"] + MEMBER_COLUMNS]
                .astype(object).itertuples(index=False, name=None)]
        with db.transaction() as conn, conn.cursor() as cur:
            cur.execute("TRUNCATE stg.stg_gym_members")
            db.insert_rows(cur, "stg.stg_gym_members",
                           ["source_row_no"] + MEMBER_COLUMNS + ["load_batch_id"], rows)
        audit.update_batch(batch_id, stage="stage")
        log.info("Batch %s: %d baris masuk staging", batch_id, len(rows))
        return len(rows)
    except Exception as exc:
        audit.fail_batch(batch_id, "stage", exc)
        raise


def transform_member(batch_id: int) -> dict:
    """Staging -> aturan transform -> quality gate -> curated zone (parquet)."""
    try:
        cols = ", ".join(f'"{c}"' for c in ["source_row_no"] + MEMBER_COLUMNS)
        stg = db.read_df(
            f"SELECT {cols} FROM stg.stg_gym_members WHERE load_batch_id = %(b)s ORDER BY source_row_no",
            {"b": batch_id})
        if stg.empty:
            raise ValueError(f"staging kosong untuk batch {batch_id}")

        clean, rejects, stats = transform_member_df(stg)
        audit.write_rejects(batch_id, config.SRC_MEMBER, rejects)
        audit.update_batch(batch_id, stage="transform", rows_rejected=stats["rows_rejected"],
                           notes=f"transform: {stats}")

        if stats["reject_ratio"] > config.REJECT_THRESHOLD:
            raise QualityGateError(
                f"{stats['rows_rejected']} dari {stats['rows_read']} baris ditolak "
                f"({stats['reject_ratio']:.1%}) melebihi batas {config.REJECT_THRESHOLD:.0%}; "
                f"data warehouse tidak diubah")

        path = lake.write_curated(ENTITY, batch_id, clean)
        audit.update_batch(batch_id, curated_path=str(path))
        log.info("Batch %s: transform selesai %s", batch_id, stats)
        return stats
    except Exception as exc:
        audit.fail_batch(batch_id, "transform", exc)
        raise


def _lookup(cur, sql: str) -> dict:
    cur.execute(sql)
    return dict(cur.fetchall())


def load_member(batch_id: int) -> int:
    """Curated -> dim_member + 2 tabel fakta dalam SATU transaksi, rekonsiliasi, refresh mart."""
    try:
        df = lake.read_curated(ENTITY, batch_id)
        with db.transaction() as conn, conn.cursor() as cur:
            gender = _lookup(cur, "SELECT gender_name, gender_key FROM dw.dim_gender")
            workout = _lookup(cur, "SELECT workout_type_name, workout_type_key FROM dw.dim_workout_type")
            level = _lookup(cur, "SELECT level_code, experience_key FROM dw.dim_experience_level")
            bmi_cat = _lookup(cur, "SELECT category_name, bmi_category_key FROM dw.dim_bmi_category")

            df["gender_key"] = df["gender"].map(gender)
            df["workout_type_key"] = df["workout_type"].map(workout)
            df["experience_key"] = df["experience_level"].map(level)
            df["bmi_category_key"] = df["bmi_category"].map(bmi_cat)
            key_cols = ["gender_key", "workout_type_key", "experience_key", "bmi_category_key"]
            missing = df[key_cols].isna().any(axis=1)
            if missing.any():
                # Key dimensi tidak ditemukan: baris ditolak, tidak dimuat
                bad = df.loc[missing]
                audit.write_rejects(batch_id, config.SRC_MEMBER, [
                    {"source_row_no": int(r.source_row_no), "reject_reason": "key dimensi tidak ditemukan",
                     "raw_record": r._asdict()} for r in bad.itertuples(index=False)])
                df = df.loc[~missing].copy()
                df["member_key"] = np.arange(1, len(df) + 1)
            for c in key_cols:
                df[c] = df[c].astype("int64")

            # Muat ulang penuh: data sumber tidak punya ID/tanggal, baris baru tidak bisa dikenali
            cur.execute("TRUNCATE dw.fact_workout_session, dw.fact_body_measurement, dw.dim_member "
                        "RESTART IDENTITY")
            src = config.SRC_MEMBER

            def rows(cols):
                return [tuple(v.item() if hasattr(v, "item") else v for v in r) + (batch_id, src)
                        for r in df[cols].itertuples(index=False, name=None)]

            dim_cols = ["member_key", "source_row_no", "age", "age_group", "height_m"]
            db.insert_rows(cur, "dw.dim_member", dim_cols + ["load_batch_id", "source_name"], rows(dim_cols))

            fws_cols = ["member_key", "gender_key", "workout_type_key", "experience_key",
                        "session_duration_hours", "calories_burned", "workout_frequency_days_week",
                        "water_intake_liters", "max_bpm", "avg_bpm", "resting_bpm", "bpm_anomaly_flag"]
            db.insert_rows(cur, "dw.fact_workout_session", fws_cols + ["load_batch_id", "source_name"],
                           rows(fws_cols))

            fbm_cols = ["member_key", "gender_key", "bmi_category_key", "weight_kg", "bmi",
                        "bmi_recalc", "fat_percentage", "bmi_mismatch_flag"]
            db.insert_rows(cur, "dw.fact_body_measurement", fbm_cols + ["load_batch_id", "source_name"],
                           rows(fbm_cols))

            # Rekonsiliasi SEBELUM commit: bila tidak cocok, seluruh perubahan dibatalkan
            counts = {}
            for table in ("dw.dim_member", "dw.fact_workout_session", "dw.fact_body_measurement"):
                cur.execute(f"SELECT COUNT(*) FROM {table} WHERE load_batch_id = %s", (batch_id,))
                counts[table] = cur.fetchone()[0]
            if any(n != len(df) for n in counts.values()):
                raise ReconciliationError(f"jumlah baris tidak cocok: curated={len(df)}, dwh={counts}")

            cur.execute("REFRESH MATERIALIZED VIEW dw.mart_retensi_pemula")
            cur.execute("REFRESH MATERIALIZED VIEW dw.mart_program_pemasaran")

        audit.update_batch(batch_id, status="SUCCESS", stage="load", rows_loaded=len(df),
                           notes=f"rekonsiliasi OK: {counts}")
        log.info("Batch %s: %d member dimuat ke DWH, mart disegarkan", batch_id, len(df))
        return len(df)
    except Exception as exc:
        audit.fail_batch(batch_id, "load", exc)
        raise

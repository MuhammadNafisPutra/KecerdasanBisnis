"""Data uji buatan (BUKAN data perusahaan) untuk menguji aturan ETL tanpa file asli.

Struktur kolom sama dengan file ekspor member dan respons WHO GHO API,
tetapi nilainya dibuat acak dengan seed tetap agar hasil tes selalu sama.
"""
import json

import numpy as np
import pandas as pd

from etl.schemas import MEMBER_COLUMNS


def make_member_df(n: int = 200, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    gender = rng.choice(["Male", "Female"], n)
    height = rng.uniform(1.5, 2.0, n).round(2)
    weight = rng.uniform(45, 125, n).round(1)
    max_bpm = rng.integers(160, 200, n)
    avg_bpm = rng.integers(120, 170, n)
    df = pd.DataFrame({
        "Age": rng.integers(18, 60, n),
        "Gender": gender,
        "Weight (kg)": weight,
        "Height (m)": height,
        "Max_BPM": max_bpm,
        "Avg_BPM": avg_bpm,
        "Resting_BPM": rng.integers(50, 75, n),
        "Session_Duration (hours)": rng.uniform(0.5, 2.0, n).round(2),
        "Calories_Burned": rng.uniform(300, 1800, n).round(1),
        "Workout_Type": rng.choice(["Cardio", "Strength", "HIIT", "Yoga"], n),
        "Fat_Percentage": rng.uniform(10, 35, n).round(1),
        "Water_Intake (liters)": rng.uniform(1.5, 3.7, n).round(1),
        "Workout_Frequency (days/week)": rng.integers(2, 6, n),
        "Experience_Level": rng.integers(1, 4, n),
        "BMI": (weight / height ** 2).round(2),
    })
    return df[MEMBER_COLUMNS].astype(str)


def make_stg(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.insert(0, "source_row_no", range(1, len(out) + 1))
    return out


def make_who_payload(code: str, countries=("IDN", "MYS", "SGP"), years=range(2010, 2025),
                     base: float = 20.0) -> dict:
    """Meniru struktur respons GHO: termasuk SEX_BTSX dan baris kawasan yang harus dibuang."""
    values = []
    for c in countries:
        for y in years:
            for sex in ("SEX_MLE", "SEX_FMLE", "SEX_BTSX"):
                v = base + (y - 2010) * 0.3 + (2 if sex == "SEX_FMLE" else 0)
                values.append({
                    "IndicatorCode": code, "SpatialDimType": "COUNTRY", "SpatialDim": c,
                    "ParentLocationCode": "SEAR" if c == "IDN" else "WPR",
                    "ParentLocation": "South-East Asia" if c == "IDN" else "Western Pacific",
                    "TimeDimType": "YEAR", "TimeDim": y, "Dim1Type": "SEX", "Dim1": sex,
                    "Dim2Type": "AGEGROUP", "Dim2": "AGEGROUP_YEARS18-PLUS",
                    "Value": f"{v:.1f}", "NumericValue": round(v, 3),
                    "Low": round(v - 1, 3), "High": round(v + 1, 3), "Date": "2026-05-01T00:00:00+02:00",
                })
    values.append({"IndicatorCode": code, "SpatialDimType": "REGION", "SpatialDim": "SEAR",
                   "TimeDim": 2024, "Dim1": "SEX_MLE", "Dim2": "AGEGROUP_YEARS18-PLUS",
                   "NumericValue": 10.0})
    return {"@odata.context": "test", "value": values}


def make_country_payload(countries=("IDN", "MYS", "SGP")) -> dict:
    names = {"IDN": "Indonesia", "MYS": "Malaysia", "SGP": "Singapore"}
    return {"value": [{"Code": c, "Title": names.get(c, c)} for c in countries]}


def dumps(payload: dict) -> bytes:
    return json.dumps(payload).encode()

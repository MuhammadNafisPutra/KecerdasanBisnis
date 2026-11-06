"""Uji aturan transform (tanpa database). Jalankan: pytest -q"""
import pandas as pd

from etl.member import transform_member_df
from etl.who import transform_who_df
from tests.fixtures import make_member_df, make_stg

UNITS = {"NCD_BMI_30A": "%", "NCD_BMI_25A": "%", "NCD_BMI_MEAN": "kg/m2", "NCD_PAA": "%"}


def test_data_bersih_semua_lolos():
    clean, rejects, stats = transform_member_df(make_stg(make_member_df(100)))
    assert stats["rows_read"] == 100 and stats["rows_rejected"] == 0
    assert list(clean["member_key"]) == list(range(1, 101))
    assert stats["bmi_mismatch"] == 0


def test_nilai_kosong_tipe_salah_dan_rentang_ditolak():
    df = make_member_df(20)
    df.loc[0, "Age"] = ""                     # aturan 2
    df.loc[1, "Calories_Burned"] = "abc"      # aturan 4
    df.loc[2, "Age"] = "25.5"                 # aturan 4 (bukan bilangan bulat)
    df.loc[3, "Gender"] = "Unknown"           # aturan 5
    df.loc[4, "Age"] = "150"                  # aturan 6
    df.loc[5, "Resting_BPM"] = "200"          # aturan 6 (resting >= avg)
    clean, rejects, stats = transform_member_df(make_stg(df))
    assert stats["rows_rejected"] == 6
    assert sorted(r["source_row_no"] for r in rejects) == [1, 2, 3, 4, 5, 6]
    assert "nilai kosong: age" in rejects[0]["reject_reason"]
    assert len(clean) == 14


def test_standardisasi_teks():
    df = make_member_df(3)
    df.loc[0, "Gender"] = " male "
    df.loc[1, "Workout_Type"] = "hiit"
    clean, rejects, _ = transform_member_df(make_stg(df))
    assert not rejects
    assert clean.loc[0, "gender"] == "Male" and clean.loc[1, "workout_type"] == "HIIT"


def test_baris_ganda_dihapus_bukan_ditolak():
    df = make_member_df(10)
    df = pd.concat([df, df.iloc[[0, 1]]], ignore_index=True)
    clean, rejects, stats = transform_member_df(make_stg(df))
    assert stats["duplicates_removed"] == 2 and stats["rows_rejected"] == 0 and len(clean) == 10


def test_flag_bpm_dan_bmi():
    df = make_member_df(5)
    df.loc[0, "Avg_BPM"], df.loc[0, "Max_BPM"] = "180", "170"   # aturan 7
    df.loc[1, "BMI"] = "40.00"                                  # aturan 8
    clean, rejects, stats = transform_member_df(make_stg(df))
    assert not rejects
    assert stats["bpm_anomaly"] == 1 and stats["bmi_mismatch"] == 1


def test_kategori_bmi_dan_kelompok_usia():
    df = make_member_df(4)
    df["Height (m)"] = "2.00"
    df["Weight (kg)"] = ["70.0", "96.0", "116.0", "130.0"]      # BMI 17,5 / 24 / 29 / 32,5
    df["BMI"] = ["17.50", "24.00", "29.00", "32.50"]
    df["Age"] = ["18", "30", "49", "50"]
    clean, _, _ = transform_member_df(make_stg(df))
    assert list(clean["bmi_category"]) == ["Underweight", "Normal", "Overweight", "Obese"]
    assert list(clean["age_group"]) == ["18-29", "30-39", "40-49", "50+"]


def _who_stg(rows):
    cols = ["indicator_code", "spatial_dim_type", "spatial_dim", "parent_location_code", "parent_location",
            "time_dim", "dim1", "dim2", "numeric_value", "low", "high", "value_text", "date_modified"]
    return pd.DataFrame(rows, columns=cols)


def test_who_validasi_dan_kunci_ganda():
    base = ["NCD_BMI_30A", "COUNTRY", "IDN", "SEAR", "SEA", "2024", "SEX_MLE", "AGEGROUP_YEARS18-PLUS",
            "7.0", "6", "8", "7.0", None]
    rows = [
        base,
        base[:6] + ["SEX_FMLE"] + base[7:],
        base[:5] + ["2023"] + base[6:8] + ["150"] + base[9:],        # persen > 100 -> ditolak
        base[:5] + ["2022"] + base[6:7] + ["AGEGROUP_YEARS20-24"] + base[8:],   # umur lain -> dibuang
        base[:2] + ["MYS"] + base[3:5] + ["2024"] + base[6:],
        base[:2] + ["MYS"] + base[3:5] + ["2024"] + base[6:],        # kunci ganda -> keduanya ditolak
    ]
    clean, rejects, stats = transform_who_df(_who_stg(rows), UNITS)
    assert stats["dropped_other_age_group"] == 1
    assert stats["rows_rejected"] == 3
    assert set(clean["gender"]) == {"Male", "Female"} and len(clean) == 2

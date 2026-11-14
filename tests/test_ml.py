"""Uji modul ML tanpa database: validasi data latih, evaluasi baseline vs kandidat, bentuk prediksi."""
import numpy as np
import pandas as pd
import pytest

from etl import ml


def data_latih(n=300, seed=1):
    """Data buatan dengan pola tak-linear sederhana, agar model pohon bisa mengalahkan baseline."""
    rng = np.random.default_rng(seed)
    exp = rng.integers(1, 4, n)
    dur = rng.uniform(0.5, 2.0, n)
    gender = rng.choice(["Male", "Female"], n)
    fat = 34 - 6 * (exp == 3) - 4 * (dur > 1.4) + 4 * (gender == "Female") + rng.normal(0, 1, n)
    return pd.DataFrame({
        "member_key": np.arange(1, n + 1), "data_batch_id": 1,
        "age": rng.integers(18, 60, n), "height_m": rng.uniform(1.5, 2.0, n),
        "weight_kg": rng.uniform(45, 120, n), "experience_level": exp,
        "session_duration_hours": dur, "workout_frequency_days_week": rng.integers(2, 6, n),
        "calories_burned": rng.uniform(300, 1800, n), "water_intake_liters": rng.uniform(1.5, 3.7, n),
        "max_bpm": rng.integers(160, 200, n), "avg_bpm": rng.integers(120, 170, n),
        "resting_bpm": rng.integers(50, 75, n), "gender": gender,
        "workout_type": rng.choice(["Cardio", "Strength", "HIIT", "Yoga"], n),
        "fat_percentage": fat.round(1),
    })


def test_validasi_kolom_hilang():
    with pytest.raises(ValueError, match="kolom data latih tidak ada"):
        ml.validate_training_df(data_latih().drop(columns=["gender"]))


def test_validasi_data_terlalu_sedikit():
    with pytest.raises(ValueError, match="terlalu sedikit"):
        ml.validate_training_df(data_latih(50), min_rows=100)


def test_validasi_buang_baris_kosong():
    df = data_latih()
    df.loc[0, "weight_kg"] = None
    assert len(ml.validate_training_df(df)) == len(df) - 1


def test_evaluasi_baseline_vs_kandidat():
    df = ml.validate_training_df(data_latih())
    results, champ, pipe, pred = ml.evaluate_models(df, seed=42, cv_folds=3, test_size=0.2, n_jobs=1)

    assert {r["model_name"] for r in results} == {"linear_regression", "random_forest", "gradient_boosting"}
    assert sum(r["is_champion"] for r in results) == 1
    assert [r["model_role"] for r in results].count("baseline") == 1
    for r in results:
        assert np.isfinite([r["cv_mae_mean"], r["test_mae"], r["test_rmse"], r["test_r2"]]).all()
        assert r["n_train"] + r["n_test"] == len(df)
        assert abs(sum(r["feature_importance"].values()) - 1) < 1e-3

    base = next(r for r in results if r["model_role"] == "baseline")
    best = next(r for r in results if r["is_champion"])
    assert champ != "linear_regression"            # pola tak-linear: model pohon lebih baik
    assert best["test_mae"] < base["test_mae"]

    assert len(pred) == len(df)
    assert (pred["split"] == "uji").sum() == results[0]["n_test"]
    assert np.allclose(pred["residual"], pred["actual"] - pred["predicted"], atol=0.011)
    assert len(pipe.predict(df[ml.FEATURES].head(5))) == 5


def test_kategori_baru_tidak_error():
    df = ml.validate_training_df(data_latih())
    _, _, pipe, _ = ml.evaluate_models(df, seed=42, cv_folds=3, n_jobs=1)
    baru = df[ml.FEATURES].head(2).copy()
    baru["workout_type"] = "Pilates"               # jenis latihan yang belum pernah dilihat model
    assert len(pipe.predict(baru)) == 2

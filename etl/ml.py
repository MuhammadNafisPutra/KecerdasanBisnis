"""Machine Learning: prediksi persentase lemak tubuh member (regresi) dari kebiasaan latihan.

Alur train_model():
  DWH (fakta + dimensi batch member terakhir)
    -> (data > ML_MAX_TRAIN_ROWS: ambil sampel acak) -> bagi data latih 80% / uji 20%
    -> latih baseline (Linear Regression) + kandidat (Random Forest, Gradient Boosting)
    -> validasi silang 5 lipat pada data latih, pilih champion = MAE validasi silang terkecil
    -> gerbang kualitas: R2 uji champion >= ML_MIN_R2
    -> simpan model ke Data Lake (models/), metrik ke dw.ml_model_run, prediksi ke dw.ml_prediction
       dalam SATU transaksi (gagal = rollback, prediksi lama tetap dipakai dashboard)

Fitur hanya kebiasaan latihan dan data tubuh dasar. fat_percentage adalah target dan
BMI tidak dipakai (BMI diturunkan dari berat dan tinggi, yang sudah menjadi fitur).
"""
import json
import logging
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import KFold, cross_validate, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from etl import audit, config, db

log = logging.getLogger("fitzone.ml")

TARGET = "fat_percentage"
NUM_FEATURES = [
    "age", "height_m", "weight_kg", "experience_level", "session_duration_hours",
    "workout_frequency_days_week", "calories_burned", "water_intake_liters",
    "max_bpm", "avg_bpm", "resting_bpm",
]
CAT_FEATURES = ["gender", "workout_type"]
FEATURES = NUM_FEATURES + CAT_FEATURES

# Data latih diambil dari star schema batch member terakhir (bukan dari CSV),
# sehingga model selalu memakai data yang sudah lolos aturan ETL dan rekonsiliasi.
SQL_TRAINING = """
SELECT m.member_key, s.load_batch_id AS data_batch_id,
       m.age, m.height_m, b.weight_kg, e.level_code AS experience_level,
       s.session_duration_hours, s.workout_frequency_days_week, s.calories_burned,
       s.water_intake_liters, s.max_bpm, s.avg_bpm, s.resting_bpm,
       g.gender_name AS gender, w.workout_type_name AS workout_type,
       b.fat_percentage
FROM dw.fact_workout_session s
JOIN dw.fact_body_measurement b ON b.member_key = s.member_key
JOIN dw.dim_member m            ON m.member_key = s.member_key
JOIN dw.dim_gender g            ON g.gender_key = s.gender_key
JOIN dw.dim_experience_level e  ON e.experience_key = s.experience_key
JOIN dw.dim_workout_type w      ON w.workout_type_key = s.workout_type_key
ORDER BY m.member_key
"""


class ModelQualityError(Exception):
    """Model champion tidak memenuhi gerbang kualitas; hasil tidak diterbitkan."""


# ---------------------------------------------------------------- bagian murni (tanpa database)

def _preprocess(scale: bool) -> ColumnTransformer:
    num = StandardScaler() if scale else "passthrough"
    return ColumnTransformer([
        ("num", num, NUM_FEATURES),
        ("cat", OneHotEncoder(handle_unknown="ignore", drop="if_binary"), CAT_FEATURES),
    ])


def build_models(seed: int | None = None, n_jobs: int | None = None) -> dict:
    """Nama model -> (peran, pipeline). Baseline sengaja sederhana sebagai pembanding."""
    seed = config.ML_RANDOM_STATE if seed is None else seed
    n_jobs = config.ML_N_JOBS if n_jobs is None else n_jobs
    return {
        "linear_regression": ("baseline", Pipeline([
            ("prep", _preprocess(scale=True)), ("model", LinearRegression())])),
        "random_forest": ("kandidat", Pipeline([
            ("prep", _preprocess(scale=False)),
            ("model", RandomForestRegressor(n_estimators=300, min_samples_leaf=2,
                                            random_state=seed, n_jobs=n_jobs))])),
        "gradient_boosting": ("kandidat", Pipeline([
            ("prep", _preprocess(scale=False)),
            ("model", GradientBoostingRegressor(n_estimators=300, learning_rate=0.05, max_depth=3,
                                                random_state=seed))])),
    }


def validate_training_df(df: pd.DataFrame, min_rows: int | None = None) -> pd.DataFrame:
    min_rows = config.ML_MIN_ROWS if min_rows is None else min_rows
    missing = [c for c in FEATURES + [TARGET, "member_key"] if c not in df.columns]
    if missing:
        raise ValueError(f"kolom data latih tidak ada: {missing}")
    df = df.copy()
    for c in NUM_FEATURES + [TARGET]:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    df = df.dropna(subset=FEATURES + [TARGET])
    if len(df) < min_rows:
        raise ValueError(f"data latih terlalu sedikit: {len(df)} baris (minimum {min_rows})")
    return df


def _importance(name: str, pipe: Pipeline) -> dict:
    """Kontribusi fitur: feature_importances_ untuk model pohon, |koefisien| untuk regresi linear."""
    names = [n.split("__", 1)[1] for n in pipe.named_steps["prep"].get_feature_names_out()]
    model = pipe.named_steps["model"]
    raw = model.feature_importances_ if hasattr(model, "feature_importances_") else np.abs(model.coef_)
    total = float(np.sum(raw)) or 1.0
    pairs = sorted(zip(names, raw / total), key=lambda x: -x[1])
    return {n: round(float(v), 4) for n, v in pairs}


def evaluate_models(df: pd.DataFrame, seed: int | None = None, cv_folds: int | None = None,
                    test_size: float | None = None, n_jobs: int | None = None, max_rows: int | None = None):
    """Latih dan evaluasi semua model. Mengembalikan (hasil per model, nama champion, pipeline champion,
    DataFrame prediksi champion untuk semua baris)."""
    seed = config.ML_RANDOM_STATE if seed is None else seed
    cv_folds = config.ML_CV_FOLDS if cv_folds is None else cv_folds
    test_size = config.ML_TEST_SIZE if test_size is None else test_size

    max_rows = config.ML_MAX_TRAIN_ROWS if max_rows is None else max_rows
    X, y = df[FEATURES], df[TARGET]
    # Data sangat besar: model dilatih dan dievaluasi pada sampel acak agar waktu dan memori
    # tetap terkendali; prediksi tetap dibuat untuk SEMUA baris.
    pool = df.index if len(df) <= max_rows else df.sample(max_rows, random_state=seed).index
    idx_train, idx_test = train_test_split(pool, test_size=test_size, random_state=seed)
    cv = KFold(n_splits=cv_folds, shuffle=True, random_state=seed)

    results, fitted = [], {}
    for name, (role, pipe) in build_models(seed, n_jobs).items():
        scores = cross_validate(pipe, X.loc[idx_train], y.loc[idx_train], cv=cv,
                                scoring=("neg_mean_absolute_error", "r2"))
        t0 = time.perf_counter()
        pipe.fit(X.loc[idx_train], y.loc[idx_train])
        train_sec = time.perf_counter() - t0

        t0 = time.perf_counter()
        pred_test = pipe.predict(X.loc[idx_test])
        predict_ms_per_1k = (time.perf_counter() - t0) * 1000 * 1000 / max(len(idx_test), 1)

        y_test = y.loc[idx_test]
        results.append({
            "model_name": name, "model_role": role,
            "n_rows": len(df), "n_train": len(idx_train), "n_test": len(idx_test),
            "n_features": len(pipe.named_steps["prep"].get_feature_names_out()),
            "cv_folds": cv_folds,
            "cv_mae_mean": float(-scores["test_neg_mean_absolute_error"].mean()),
            "cv_mae_std": float(scores["test_neg_mean_absolute_error"].std()),
            "cv_r2_mean": float(scores["test_r2"].mean()),
            "test_mae": float(mean_absolute_error(y_test, pred_test)),
            "test_rmse": float(np.sqrt(mean_squared_error(y_test, pred_test))),
            "test_r2": float(r2_score(y_test, pred_test)),
            "train_sec": train_sec, "predict_ms_per_1k": predict_ms_per_1k,
            "params": {k: v for k, v in pipe.named_steps["model"].get_params().items()
                       if isinstance(v, (int, float, str, bool, type(None)))},
            "feature_importance": _importance(name, pipe),
            "is_champion": False,
        })
        fitted[name] = pipe

    champion = min(results, key=lambda r: r["cv_mae_mean"])
    champion["is_champion"] = True
    pipe = fitted[champion["model_name"]]

    pred = pd.DataFrame({
        "member_key": df["member_key"].astype(int),
        "split": np.where(df.index.isin(idx_test), "uji",
                          np.where(df.index.isin(idx_train), "latih", "di_luar_sampel")),
        "actual": y.round(2),
        "predicted": pipe.predict(X).round(2),
    }, index=df.index)
    pred["residual"] = (pred["actual"] - pred["predicted"]).round(2)
    return results, champion["model_name"], pipe, pred


# ---------------------------------------------------------------- bagian dengan database / Data Lake

def ensure_schema():
    """Buat tabel dan view ML bila belum ada (database lama tidak perlu dibuat ulang)."""
    with db.transaction() as conn, conn.cursor() as cur:
        cur.execute((config.SQL_DIR / "09_ml.sql").read_text(encoding="utf-8"))


def load_training_data() -> pd.DataFrame:
    return db.read_df(SQL_TRAINING)


def _save_model(batch_id: int, name: str, pipe: Pipeline, results: list[dict]) -> str:
    folder = config.MODEL_DIR / TARGET / f"batch_id={batch_id}"
    folder.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipe, folder / "model.joblib")
    (folder / "metrics.json").write_text(json.dumps(
        {"champion": name, "features": FEATURES, "target": TARGET, "results": results},
        indent=2, default=str), encoding="utf-8")
    return str(folder / "model.joblib")


def train_model() -> dict:
    """Satu batch training. Dicatat di etl_log dengan source_name 'ml_fat_model'."""
    ensure_schema()
    batch_id = audit.start_batch(config.SRC_ML, stage="train")
    try:
        with audit.stage_timer(batch_id, "ml_load_data") as t:
            df = validate_training_df(load_training_data())
            t["rows"] = len(df)
        data_batch_ids = df["data_batch_id"].unique()
        if len(data_batch_ids) != 1:
            raise ValueError(f"data latih berasal dari lebih dari satu batch: {list(data_batch_ids)}")
        data_batch_id = int(data_batch_ids[0])
        audit.update_batch(batch_id, rows_read=len(df))

        with audit.stage_timer(batch_id, "ml_train") as t:
            results, champ_name, pipe, pred = evaluate_models(df)
            t["rows"] = results[0]["n_train"] + results[0]["n_test"]   # baris yang dipakai melatih
        champ = next(r for r in results if r["is_champion"])
        base = next(r for r in results if r["model_role"] == "baseline")
        summary = " ; ".join(f"{r['model_name']} MAE={r['test_mae']:.2f} R2={r['test_r2']:.3f}" for r in results)
        log.info("Batch %s: %s -> champion %s", batch_id, summary, champ_name)

        if champ["test_r2"] < config.ML_MIN_R2:
            raise ModelQualityError(
                f"R2 uji champion {champ_name} = {champ['test_r2']:.3f} < batas {config.ML_MIN_R2}")

        audit.update_batch(batch_id, stage="evaluate")
        model_path = _save_model(batch_id, champ_name, pipe, results)

        with audit.stage_timer(batch_id, "ml_write") as t, db.transaction() as conn, conn.cursor() as cur:
            t["rows"] = len(pred)
            run_ids = {}
            for r in results:
                cur.execute("""
                    INSERT INTO dw.ml_model_run (batch_id, data_batch_id, target, model_name, model_role,
                        is_champion, n_rows, n_train, n_test, n_features, cv_folds, cv_mae_mean, cv_mae_std,
                        cv_r2_mean, test_mae, test_rmse, test_r2, train_sec, predict_ms_per_1k, params,
                        feature_importance, model_path)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING run_id""",
                    (batch_id, data_batch_id, TARGET, r["model_name"], r["model_role"], r["is_champion"],
                     r["n_rows"], r["n_train"], r["n_test"], r["n_features"], r["cv_folds"],
                     r["cv_mae_mean"], r["cv_mae_std"], r["cv_r2_mean"], r["test_mae"], r["test_rmse"],
                     r["test_r2"], r["train_sec"], r["predict_ms_per_1k"], json.dumps(r["params"]),
                     json.dumps(r["feature_importance"]), model_path if r["is_champion"] else None))
                run_ids[r["model_name"]] = cur.fetchone()[0]

            champ_run = run_ids[champ_name]
            rows = [(champ_run, int(p.member_key), data_batch_id, p.split, float(p.actual),
                     float(p.predicted), float(p.residual)) for p in pred.itertuples(index=False)]
            db.insert_rows(cur, "dw.ml_prediction",
                           ["run_id", "member_key", "data_batch_id", "split", "actual", "predicted", "residual"],
                           rows)
            cur.execute("SELECT COUNT(*) FROM dw.ml_prediction WHERE run_id = %s", (champ_run,))
            if cur.fetchone()[0] != len(df):
                raise ValueError("jumlah prediksi tersimpan tidak sama dengan data latih")

        improve = 100 * (base["test_mae"] - champ["test_mae"]) / base["test_mae"]
        audit.update_batch(batch_id, status="SUCCESS", stage="load", rows_loaded=len(pred),
                           curated_path=model_path,
                           notes=f"champion {champ_name}, MAE {improve:.1f}% lebih baik dari baseline | {summary}")
        return {"batch_id": batch_id, "champion": champ_name, "results": results,
                "mae_improvement_pct": improve}
    except Exception as exc:
        audit.fail_batch(batch_id, "train", exc)
        raise

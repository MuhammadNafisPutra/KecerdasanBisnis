-- Hasil Machine Learning: prediksi persentase lemak tubuh (regresi).
-- Dijalankan sebagai etl_user (pemilik). Aman dijalankan berulang (IF NOT EXISTS / OR REPLACE),
-- dan juga dijalankan otomatis oleh etl/ml.py sebelum training, sehingga database lama ikut diperbarui.

-- Satu baris per model per training. Setiap training melatih baseline + kandidat,
-- lalu model dengan MAE validasi silang terkecil ditandai sebagai champion.
CREATE TABLE IF NOT EXISTS dw.ml_model_run (
    run_id              BIGSERIAL PRIMARY KEY,
    batch_id            BIGINT  NOT NULL REFERENCES etl_audit.etl_log (batch_id),  -- batch training
    data_batch_id       BIGINT  NOT NULL,          -- batch member yang dipakai sebagai data latih (lineage)
    target              TEXT    NOT NULL DEFAULT 'fat_percentage',
    model_name          TEXT    NOT NULL,          -- linear_regression / random_forest / gradient_boosting
    model_role          TEXT    NOT NULL CHECK (model_role IN ('baseline', 'kandidat')),
    is_champion         BOOLEAN NOT NULL DEFAULT FALSE,
    n_rows              INTEGER NOT NULL,
    n_train             INTEGER NOT NULL,
    n_test              INTEGER NOT NULL,
    n_features          INTEGER NOT NULL,
    cv_folds            SMALLINT NOT NULL,
    cv_mae_mean         NUMERIC(8,4) NOT NULL,     -- validasi silang pada data latih
    cv_mae_std          NUMERIC(8,4) NOT NULL,
    cv_r2_mean          NUMERIC(8,4) NOT NULL,
    test_mae            NUMERIC(8,4) NOT NULL,     -- data uji (hold-out 20%)
    test_rmse           NUMERIC(8,4) NOT NULL,
    test_r2             NUMERIC(8,4) NOT NULL,
    train_sec           NUMERIC(10,3) NOT NULL,    -- lama fit pada data latih
    predict_ms_per_1k   NUMERIC(10,3) NOT NULL,    -- lama prediksi per 1.000 baris
    params              JSONB,
    feature_importance  JSONB,
    model_path          TEXT,                      -- file model di Data Lake (hanya champion)
    trained_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ml_run_batch ON dw.ml_model_run (batch_id);

-- Prediksi champion untuk setiap member. member_key sengaja tanpa foreign key karena dim_member
-- dimuat ulang penuh setiap batch; kecocokan dijaga lewat data_batch_id.
CREATE TABLE IF NOT EXISTS dw.ml_prediction (
    prediction_id   BIGSERIAL PRIMARY KEY,
    run_id          BIGINT  NOT NULL REFERENCES dw.ml_model_run (run_id) ON DELETE CASCADE,
    member_key      INTEGER NOT NULL,
    data_batch_id   BIGINT  NOT NULL,
    split           TEXT    NOT NULL CHECK (split IN ('latih', 'uji', 'di_luar_sampel')),
    actual          NUMERIC(5,2) NOT NULL,
    predicted       NUMERIC(5,2) NOT NULL,
    residual        NUMERIC(6,2) NOT NULL,        -- aktual - prediksi (positif = lemak lebih tinggi dari perkiraan)
    CONSTRAINT uq_ml_pred UNIQUE (run_id, member_key)
);
-- Database yang dibuat sebelum ada pilihan 'di_luar_sampel' (data besar dilatih pada sampel)
ALTER TABLE dw.ml_prediction DROP CONSTRAINT IF EXISTS ml_prediction_split_check;
ALTER TABLE dw.ml_prediction ADD CONSTRAINT ml_prediction_split_check
    CHECK (split IN ('latih', 'uji', 'di_luar_sampel'));

-- Mart evaluasi: semua model pada training sukses terakhir + perbaikan terhadap baseline
CREATE OR REPLACE VIEW dw.mart_ml_evaluasi AS
WITH terakhir AS (
    SELECT MAX(batch_id) AS batch_id FROM dw.ml_model_run WHERE is_champion
), runs AS (
    SELECT r.* FROM dw.ml_model_run r JOIN terakhir t ON t.batch_id = r.batch_id
), base AS (
    SELECT test_mae FROM runs WHERE model_role = 'baseline' LIMIT 1
)
SELECT r.batch_id, r.data_batch_id, r.model_name, r.model_role, r.is_champion,
       r.n_rows, r.n_train, r.n_test, r.n_features, r.cv_folds,
       r.cv_mae_mean, r.cv_mae_std, r.cv_r2_mean,
       r.test_mae, r.test_rmse, r.test_r2,
       ROUND(100 * (b.test_mae - r.test_mae) / NULLIF(b.test_mae, 0), 1) AS mae_lebih_baik_pct,
       r.train_sec, r.predict_ms_per_1k, r.feature_importance, r.trained_at
FROM runs r CROSS JOIN base b;

-- Mart prediksi: prediksi champion terakhir, hanya untuk member dari batch data yang sama
CREATE OR REPLACE VIEW dw.mart_ml_prediksi_lemak AS
WITH champ AS (
    SELECT run_id, data_batch_id, model_name FROM dw.ml_model_run
    WHERE is_champion ORDER BY batch_id DESC LIMIT 1
)
SELECT p.member_key,
       g.gender_name                    AS gender,
       m.age_group,
       e.level_name                     AS experience_name,
       w.workout_type_name              AS workout_type,
       c.category_name                  AS bmi_category,
       s.workout_frequency_days_week,
       s.session_duration_hours,
       p.split,
       p.actual                         AS fat_actual,
       p.predicted                      AS fat_predicted,
       p.residual,
       CASE WHEN p.residual >=  3 THEN 'Di atas perkiraan'
            WHEN p.residual <= -3 THEN 'Di bawah perkiraan'
            ELSE 'Sesuai perkiraan' END AS status_prediksi,
       ch.model_name,
       p.data_batch_id
FROM dw.ml_prediction p
JOIN champ ch                    ON ch.run_id = p.run_id
JOIN dw.fact_workout_session s   ON s.member_key = p.member_key AND s.load_batch_id = p.data_batch_id
JOIN dw.fact_body_measurement b  ON b.member_key = p.member_key AND b.load_batch_id = p.data_batch_id
JOIN dw.dim_member m             ON m.member_key = p.member_key
JOIN dw.dim_gender g             ON g.gender_key = s.gender_key
JOIN dw.dim_experience_level e   ON e.experience_key = s.experience_key
JOIN dw.dim_workout_type w       ON w.workout_type_key = s.workout_type_key
JOIN dw.dim_bmi_category c       ON c.bmi_category_key = b.bmi_category_key;

-- Hak akses (etl_user pemilik objek, jadi boleh memberi hak)
GRANT SELECT ON dw.ml_model_run, dw.ml_prediction TO bi_analyst;
GRANT SELECT ON dw.mart_ml_evaluasi, dw.mart_ml_prediksi_lemak TO bi_analyst, dashboard_ro;

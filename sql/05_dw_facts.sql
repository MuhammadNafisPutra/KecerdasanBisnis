-- Tabel fakta. Grain:
--   fact_workout_session  : satu baris kebiasaan latihan per member per batch muat
--   fact_body_measurement : satu baris hasil pengukuran tubuh per member per batch muat
--   fact_who_benchmark    : satu baris per indikator, gender, negara, dan tahun

CREATE TABLE IF NOT EXISTS dw.fact_workout_session (
    session_key                  BIGSERIAL PRIMARY KEY,
    member_key                   INTEGER  NOT NULL REFERENCES dw.dim_member (member_key),
    gender_key                   SMALLINT NOT NULL REFERENCES dw.dim_gender (gender_key),
    workout_type_key             SMALLINT NOT NULL REFERENCES dw.dim_workout_type (workout_type_key),
    experience_key               SMALLINT NOT NULL REFERENCES dw.dim_experience_level (experience_key),
    session_duration_hours       NUMERIC(4,2) NOT NULL,
    calories_burned              NUMERIC(7,1) NOT NULL,
    workout_frequency_days_week  SMALLINT NOT NULL,
    water_intake_liters          NUMERIC(4,2) NOT NULL,
    max_bpm                      SMALLINT NOT NULL,
    avg_bpm                      SMALLINT NOT NULL,
    resting_bpm                  SMALLINT NOT NULL,
    bpm_anomaly_flag             SMALLINT NOT NULL DEFAULT 0 CHECK (bpm_anomaly_flag IN (0, 1)),
    load_batch_id                BIGINT NOT NULL,
    loaded_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_name                  TEXT NOT NULL DEFAULT 'gym_csv',
    CONSTRAINT uq_fws_member UNIQUE (member_key)
);

CREATE TABLE IF NOT EXISTS dw.fact_body_measurement (
    measurement_key    BIGSERIAL PRIMARY KEY,
    member_key         INTEGER  NOT NULL REFERENCES dw.dim_member (member_key),
    gender_key         SMALLINT NOT NULL REFERENCES dw.dim_gender (gender_key),
    bmi_category_key   SMALLINT NOT NULL REFERENCES dw.dim_bmi_category (bmi_category_key),
    weight_kg          NUMERIC(5,1) NOT NULL,
    bmi                NUMERIC(5,2) NOT NULL,      -- nilai BMI asli dari sumber
    bmi_recalc         NUMERIC(5,2) NOT NULL,      -- berat / tinggi^2 (dasar kategori BMI)
    fat_percentage     NUMERIC(4,1) NOT NULL,
    bmi_mismatch_flag  SMALLINT NOT NULL DEFAULT 0 CHECK (bmi_mismatch_flag IN (0, 1)),
    load_batch_id      BIGINT NOT NULL,
    loaded_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_name        TEXT NOT NULL DEFAULT 'gym_csv',
    CONSTRAINT uq_fbm_member UNIQUE (member_key)
);

CREATE TABLE IF NOT EXISTS dw.fact_who_benchmark (
    benchmark_key   BIGSERIAL PRIMARY KEY,
    indicator_key   SMALLINT NOT NULL REFERENCES dw.dim_indicator (indicator_key),
    gender_key      SMALLINT NOT NULL REFERENCES dw.dim_gender (gender_key),
    country_key     INTEGER  NOT NULL REFERENCES dw.dim_country (country_key),
    year            SMALLINT NOT NULL,
    value           NUMERIC(8,3) NOT NULL,
    low             NUMERIC(8,3),
    high            NUMERIC(8,3),
    load_batch_id   BIGINT NOT NULL,
    loaded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_name     TEXT NOT NULL DEFAULT 'who_gho_api',
    CONSTRAINT uq_who_benchmark UNIQUE (indicator_key, gender_key, country_key, year)
);

-- Indeks foreign key untuk query analitik
CREATE INDEX IF NOT EXISTS ix_fws_gender      ON dw.fact_workout_session (gender_key);
CREATE INDEX IF NOT EXISTS ix_fws_workout     ON dw.fact_workout_session (workout_type_key);
CREATE INDEX IF NOT EXISTS ix_fws_experience  ON dw.fact_workout_session (experience_key);
CREATE INDEX IF NOT EXISTS ix_fbm_gender      ON dw.fact_body_measurement (gender_key);
CREATE INDEX IF NOT EXISTS ix_fbm_bmi_cat     ON dw.fact_body_measurement (bmi_category_key);
CREATE INDEX IF NOT EXISTS ix_fwb_country     ON dw.fact_who_benchmark (country_key);
CREATE INDEX IF NOT EXISTS ix_fwb_batch       ON dw.fact_who_benchmark (load_batch_id);

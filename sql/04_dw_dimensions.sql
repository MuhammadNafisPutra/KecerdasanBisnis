-- Tabel dimensi (star schema). Setiap tabel memakai surrogate key sebagai primary key
-- dan kolom audit (load_batch_id, loaded_at, source_name).

CREATE TABLE IF NOT EXISTS dw.dim_gender (
    gender_key     SMALLSERIAL PRIMARY KEY,
    gender_name    TEXT NOT NULL UNIQUE,        -- Male / Female
    who_sex_code   TEXT NOT NULL UNIQUE,        -- SEX_MLE / SEX_FMLE (conformed: member dan WHO)
    load_batch_id  BIGINT,
    loaded_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_name    TEXT NOT NULL DEFAULT 'seed'
);

CREATE TABLE IF NOT EXISTS dw.dim_workout_type (
    workout_type_key   SMALLSERIAL PRIMARY KEY,
    workout_type_name  TEXT NOT NULL UNIQUE,    -- Cardio / Strength / HIIT / Yoga
    load_batch_id      BIGINT,
    loaded_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_name        TEXT NOT NULL DEFAULT 'seed'
);

CREATE TABLE IF NOT EXISTS dw.dim_experience_level (
    experience_key  SMALLSERIAL PRIMARY KEY,
    level_code      SMALLINT NOT NULL UNIQUE,   -- 1 / 2 / 3
    level_name      TEXT NOT NULL,              -- Pemula / Menengah / Mahir
    load_batch_id   BIGINT,
    loaded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_name     TEXT NOT NULL DEFAULT 'seed'
);

CREATE TABLE IF NOT EXISTS dw.dim_bmi_category (
    bmi_category_key  SMALLSERIAL PRIMARY KEY,
    category_name     TEXT NOT NULL UNIQUE,     -- Underweight / Normal / Overweight / Obese
    min_bmi           NUMERIC(5,2),             -- batas bawah (inklusif), NULL = tanpa batas
    max_bmi           NUMERIC(5,2),             -- batas atas (eksklusif), NULL = tanpa batas
    sort_order        SMALLINT NOT NULL,
    load_batch_id     BIGINT,
    loaded_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_name       TEXT NOT NULL DEFAULT 'seed'
);

CREATE TABLE IF NOT EXISTS dw.dim_indicator (
    indicator_key   SMALLSERIAL PRIMARY KEY,
    who_code        TEXT NOT NULL UNIQUE,       -- kode indikator WHO GHO
    indicator_name  TEXT NOT NULL,              -- nama pendek: obesity_pct, dst.
    unit            TEXT NOT NULL,              -- % atau kg/m2
    description     TEXT,
    load_batch_id   BIGINT,
    loaded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_name     TEXT NOT NULL DEFAULT 'seed'
);

CREATE TABLE IF NOT EXISTS dw.dim_country (
    country_key       SERIAL PRIMARY KEY,
    country_code      TEXT NOT NULL UNIQUE,     -- kode ISO3 dari WHO (SpatialDim)
    country_name      TEXT,
    who_region_code   TEXT,                     -- ParentLocationCode, misal SEAR
    who_region_name   TEXT,                     -- ParentLocation
    load_batch_id     BIGINT,
    loaded_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_name       TEXT NOT NULL DEFAULT 'who_gho_api'
);

-- Data member tidak punya ID dan tanggal: member_key dibuat 1..N setiap muat (SCD tipe 1).
CREATE TABLE IF NOT EXISTS dw.dim_member (
    member_key      INTEGER PRIMARY KEY,
    source_row_no   INTEGER NOT NULL,           -- nomor baris di file sumber (lineage)
    age             SMALLINT NOT NULL,
    age_group       TEXT NOT NULL,              -- 18-29 / 30-39 / 40-49 / 50+
    height_m        NUMERIC(4,2) NOT NULL,
    load_batch_id   BIGINT NOT NULL,
    loaded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_name     TEXT NOT NULL DEFAULT 'gym_csv'
);

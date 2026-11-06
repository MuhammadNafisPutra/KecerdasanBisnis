-- Staging: data diambil dari raw zone apa adanya (semua kolom teks),
-- ditambah nomor baris sumber dan nomor batch. Dikosongkan dan diisi ulang setiap batch.

CREATE TABLE IF NOT EXISTS stg.stg_gym_members (
    source_row_no                  INTEGER NOT NULL,
    "Age"                          TEXT,
    "Gender"                       TEXT,
    "Weight (kg)"                  TEXT,
    "Height (m)"                   TEXT,
    "Max_BPM"                      TEXT,
    "Avg_BPM"                      TEXT,
    "Resting_BPM"                  TEXT,
    "Session_Duration (hours)"     TEXT,
    "Calories_Burned"              TEXT,
    "Workout_Type"                 TEXT,
    "Fat_Percentage"               TEXT,
    "Water_Intake (liters)"        TEXT,
    "Workout_Frequency (days/week)" TEXT,
    "Experience_Level"             TEXT,
    "BMI"                          TEXT,
    load_batch_id                  BIGINT NOT NULL,
    loaded_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_name                    TEXT NOT NULL DEFAULT 'gym_csv'
);

-- Data WHO GHO: semua indikator dan negara yang diambil, hanya gender laki-laki/perempuan
CREATE TABLE IF NOT EXISTS stg.stg_who_gho (
    indicator_code        TEXT NOT NULL,
    spatial_dim_type      TEXT,
    spatial_dim           TEXT,
    parent_location_code  TEXT,
    parent_location       TEXT,
    time_dim              TEXT,
    dim1                  TEXT,
    dim2                  TEXT,
    numeric_value         TEXT,
    low                   TEXT,
    high                  TEXT,
    value_text            TEXT,
    date_modified         TEXT,
    load_batch_id         BIGINT NOT NULL,
    loaded_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_name           TEXT NOT NULL DEFAULT 'who_gho_api'
);

-- Daftar nama negara dari dimensi COUNTRY WHO GHO
CREATE TABLE IF NOT EXISTS stg.stg_who_country (
    country_code     TEXT NOT NULL,
    country_name     TEXT,
    load_batch_id    BIGINT NOT NULL,
    loaded_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_name      TEXT NOT NULL DEFAULT 'who_gho_api'
);

-- Data mart: view/materialized view di atas star schema, dibaca dashboard dan model ML.
-- Materialized view disegarkan oleh pipeline setelah load dan rekonsiliasi berhasil.

-- 1) Retensi dan Pemula: satu baris per member, tanpa identitas
DROP MATERIALIZED VIEW IF EXISTS dw.mart_retensi_pemula;
CREATE MATERIALIZED VIEW dw.mart_retensi_pemula AS
SELECT
    m.member_key,
    g.gender_name                         AS gender,
    m.age,
    m.age_group,
    e.level_code                          AS experience_level,
    e.level_name                          AS experience_name,
    w.workout_type_name                   AS workout_type,
    s.workout_frequency_days_week,
    s.session_duration_hours,
    ROUND(s.session_duration_hours * 60 * s.workout_frequency_days_week, 0) AS weekly_minutes,
    s.calories_burned,
    s.water_intake_liters,
    s.resting_bpm,
    s.avg_bpm,
    s.max_bpm,
    s.bpm_anomaly_flag,
    b.weight_kg,
    m.height_m,
    b.bmi_recalc                          AS bmi,
    c.category_name                       AS bmi_category,
    c.sort_order                          AS bmi_category_order,
    b.fat_percentage,
    (s.workout_frequency_days_week >= 3)  AS is_rutin_3x,
    s.load_batch_id
FROM dw.fact_workout_session s
JOIN dw.fact_body_measurement b  ON b.member_key = s.member_key        -- drill-across lewat dim_member
JOIN dw.dim_member m             ON m.member_key = s.member_key
JOIN dw.dim_gender g             ON g.gender_key = s.gender_key
JOIN dw.dim_experience_level e   ON e.experience_key = s.experience_key
JOIN dw.dim_workout_type w       ON w.workout_type_key = s.workout_type_key
JOIN dw.dim_bmi_category c       ON c.bmi_category_key = b.bmi_category_key;

CREATE UNIQUE INDEX ux_mart_retensi_member ON dw.mart_retensi_pemula (member_key);

-- 2) Program dan Pemasaran: kalori per jam dan kelompok lama sesi
DROP MATERIALIZED VIEW IF EXISTS dw.mart_program_pemasaran;
CREATE MATERIALIZED VIEW dw.mart_program_pemasaran AS
SELECT
    m.member_key,
    g.gender_name                    AS gender,
    m.age_group,
    e.level_name                     AS experience_name,
    w.workout_type_name              AS workout_type,
    c.category_name                  AS bmi_category,
    s.session_duration_hours,
    CASE
        WHEN s.session_duration_hours < 1.0  THEN '< 1 jam'
        WHEN s.session_duration_hours <= 1.5 THEN '1 - 1,5 jam'
        ELSE '> 1,5 jam'
    END                              AS duration_group,
    s.calories_burned,
    ROUND(s.calories_burned / s.session_duration_hours, 1) AS calories_per_hour,
    s.workout_frequency_days_week,
    b.fat_percentage,
    s.load_batch_id
FROM dw.fact_workout_session s
JOIN dw.fact_body_measurement b  ON b.member_key = s.member_key
JOIN dw.dim_member m             ON m.member_key = s.member_key
JOIN dw.dim_gender g             ON g.gender_key = s.gender_key
JOIN dw.dim_experience_level e   ON e.experience_key = s.experience_key
JOIN dw.dim_workout_type w       ON w.workout_type_key = s.workout_type_key
JOIN dw.dim_bmi_category c       ON c.bmi_category_key = b.bmi_category_key;

CREATE UNIQUE INDEX ux_mart_program_member ON dw.mart_program_pemasaran (member_key);

-- 3) Benchmark WHO: nilai member vs Indonesia (IDN) pada tahun WHO terbaru per indikator dan gender.
--    Kurang aktif fisik member = menit latihan per minggu < 150 (perkiraan: hanya latihan di gym).
CREATE OR REPLACE VIEW dw.mart_benchmark_who AS
WITH member_metric AS (
    SELECT
        g.gender_name,
        g.gender_key,
        COUNT(*)                                                         AS n_member,
        ROUND(100.0 * AVG((b.bmi_recalc >= 30)::INT), 2)                  AS obesity_pct,
        ROUND(100.0 * AVG((b.bmi_recalc >= 25)::INT), 2)                  AS overweight_pct,
        ROUND(AVG(b.bmi_recalc), 2)                                      AS mean_bmi,
        ROUND(100.0 * AVG(((s.session_duration_hours * 60
                            * s.workout_frequency_days_week) < 150)::INT), 2) AS insufficient_activity_pct
    FROM dw.fact_body_measurement b
    JOIN dw.fact_workout_session s ON s.member_key = b.member_key
    JOIN dw.dim_gender g           ON g.gender_key = b.gender_key
    GROUP BY g.gender_name, g.gender_key
),
who_latest AS (
    SELECT DISTINCT ON (f.indicator_key, f.gender_key)
        f.indicator_key, f.gender_key, f.year, f.value, f.low, f.high
    FROM dw.fact_who_benchmark f
    JOIN dw.dim_country co ON co.country_key = f.country_key
    WHERE co.country_code = 'IDN'
    ORDER BY f.indicator_key, f.gender_key, f.year DESC
)
SELECT
    i.who_code,
    i.indicator_name,
    i.unit,
    mm.gender_name                          AS gender,
    mm.n_member,
    CASE i.indicator_name
        WHEN 'obesity_pct'               THEN mm.obesity_pct
        WHEN 'overweight_pct'            THEN mm.overweight_pct
        WHEN 'mean_bmi'                  THEN mm.mean_bmi
        WHEN 'insufficient_activity_pct' THEN mm.insufficient_activity_pct
    END                                     AS member_value,
    w.year                                  AS who_year,
    ROUND(w.value, 2)                       AS who_value,
    ROUND(w.low, 2)                         AS who_low,
    ROUND(w.high, 2)                        AS who_high,
    ROUND(CASE i.indicator_name
        WHEN 'obesity_pct'               THEN mm.obesity_pct
        WHEN 'overweight_pct'            THEN mm.overweight_pct
        WHEN 'mean_bmi'                  THEN mm.mean_bmi
        WHEN 'insufficient_activity_pct' THEN mm.insufficient_activity_pct
    END - w.value, 2)                       AS selisih_member_minus_who
FROM member_metric mm
CROSS JOIN dw.dim_indicator i
LEFT JOIN who_latest w ON w.indicator_key = i.indicator_key AND w.gender_key = mm.gender_key;

-- 4) WHO per negara pada tahun terbaru (untuk membandingkan Indonesia dengan negara/kawasan lain)
CREATE OR REPLACE VIEW dw.mart_who_country_latest AS
SELECT DISTINCT ON (f.indicator_key, f.gender_key, f.country_key)
    i.who_code,
    i.indicator_name,
    i.unit,
    g.gender_name       AS gender,
    co.country_code,
    co.country_name,
    co.who_region_code,
    co.who_region_name,
    f.year,
    f.value,
    f.low,
    f.high
FROM dw.fact_who_benchmark f
JOIN dw.dim_indicator i ON i.indicator_key = f.indicator_key
JOIN dw.dim_gender g    ON g.gender_key = f.gender_key
JOIN dw.dim_country co  ON co.country_key = f.country_key
ORDER BY f.indicator_key, f.gender_key, f.country_key, f.year DESC;

-- 5) Ringkasan ETL untuk halaman Kualitas Data dan ETL
CREATE OR REPLACE VIEW etl_audit.v_ringkasan_etl AS
SELECT
    l.batch_id,
    l.source_name,
    l.stage,
    l.status,
    l.rows_read,
    l.rows_loaded,
    l.rows_rejected,
    l.started_at,
    l.finished_at,
    ROUND(EXTRACT(EPOCH FROM (l.finished_at - l.started_at))::NUMERIC, 1) AS duration_sec,
    l.error_message,
    l.notes,
    (SELECT COUNT(*) FROM etl_audit.etl_reject r WHERE r.batch_id = l.batch_id) AS reject_rows_logged
FROM etl_audit.etl_log l;

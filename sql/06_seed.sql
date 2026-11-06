-- Data acuan dimensi (seed). Aman dijalankan ulang (ON CONFLICT DO NOTHING).

INSERT INTO dw.dim_gender (gender_name, who_sex_code) VALUES
    ('Male', 'SEX_MLE'),
    ('Female', 'SEX_FMLE')
ON CONFLICT (gender_name) DO NOTHING;

INSERT INTO dw.dim_workout_type (workout_type_name) VALUES
    ('Cardio'), ('Strength'), ('HIIT'), ('Yoga')
ON CONFLICT (workout_type_name) DO NOTHING;

INSERT INTO dw.dim_experience_level (level_code, level_name) VALUES
    (1, 'Pemula'), (2, 'Menengah'), (3, 'Mahir')
ON CONFLICT (level_code) DO NOTHING;

-- Batas kategori BMI acuan WHO: <18,5 | 18,5-24,9 | 25,0-29,9 | >=30
INSERT INTO dw.dim_bmi_category (category_name, min_bmi, max_bmi, sort_order) VALUES
    ('Underweight', NULL,  18.5, 1),
    ('Normal',      18.5,  25.0, 2),
    ('Overweight',  25.0,  30.0, 3),
    ('Obese',       30.0,  NULL, 4)
ON CONFLICT (category_name) DO NOTHING;

INSERT INTO dw.dim_indicator (who_code, indicator_name, unit, description) VALUES
    ('NCD_BMI_30A',  'obesity_pct',               '%',     'Persentase orang dewasa dengan BMI >= 30'),
    ('NCD_BMI_25A',  'overweight_pct',            '%',     'Persentase orang dewasa dengan BMI >= 25'),
    ('NCD_BMI_MEAN', 'mean_bmi',                  'kg/m2', 'Rata-rata BMI orang dewasa'),
    ('NCD_PAA',      'insufficient_activity_pct', '%',     'Persentase orang dewasa 18+ yang kurang aktif secara fisik')
ON CONFLICT (who_code) DO NOTHING;

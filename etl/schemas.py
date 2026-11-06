"""Struktur data sumber yang diharapkan (dipakai untuk validasi saat ingestion dan transform)."""

# 15 kolom file ekspor member (nama asli dari sumber)
MEMBER_COLUMNS = [
    "Age", "Gender", "Weight (kg)", "Height (m)", "Max_BPM", "Avg_BPM", "Resting_BPM",
    "Session_Duration (hours)", "Calories_Burned", "Workout_Type", "Fat_Percentage",
    "Water_Intake (liters)", "Workout_Frequency (days/week)", "Experience_Level", "BMI",
]

# Aturan transform no. 1: nama kolom huruf kecil, tanpa spasi dan satuan
MEMBER_RENAME = {
    "Age": "age",
    "Gender": "gender",
    "Weight (kg)": "weight_kg",
    "Height (m)": "height_m",
    "Max_BPM": "max_bpm",
    "Avg_BPM": "avg_bpm",
    "Resting_BPM": "resting_bpm",
    "Session_Duration (hours)": "session_duration_hours",
    "Calories_Burned": "calories_burned",
    "Workout_Type": "workout_type",
    "Fat_Percentage": "fat_percentage",
    "Water_Intake (liters)": "water_intake_liters",
    "Workout_Frequency (days/week)": "workout_frequency_days_week",
    "Experience_Level": "experience_level",
    "BMI": "bmi",
}

MEMBER_INT_COLS = ["age", "max_bpm", "avg_bpm", "resting_bpm",
                   "workout_frequency_days_week", "experience_level"]
MEMBER_FLOAT_COLS = ["weight_kg", "height_m", "session_duration_hours", "calories_burned",
                     "fat_percentage", "water_intake_liters", "bmi"]

ALLOWED_GENDER = {"Male", "Female"}
ALLOWED_WORKOUT = {"Cardio", "Strength", "HIIT", "Yoga"}

# Field wajib pada setiap record respons WHO GHO API
WHO_REQUIRED_FIELDS = {"IndicatorCode", "SpatialDimType", "SpatialDim", "TimeDim", "Dim1", "NumericValue"}
WHO_SEX_CODES = {"SEX_MLE", "SEX_FMLE"}
# Kelompok umur yang dipakai (dewasa). NULL/kosong = indikator tanpa pembagian umur.
WHO_ALLOWED_DIM2 = {"", "AGEGROUP_YEARS18-PLUS"}

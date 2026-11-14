-- Tabel audit ETL: satu baris per batch per sumber, dan baris yang ditolak.
CREATE TABLE IF NOT EXISTS etl_audit.etl_log (
    batch_id         BIGSERIAL PRIMARY KEY,
    source_name      TEXT        NOT NULL,              -- gym_csv / who_gho_api
    stage            TEXT,                              -- tahap terakhir: ingest/stage/transform/load
    status           TEXT        NOT NULL DEFAULT 'RUNNING'
                     CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED', 'SKIPPED')),
    rows_read        INTEGER,
    rows_loaded      INTEGER,
    rows_rejected    INTEGER,
    source_checksum  TEXT,                              -- SHA-256 file sumber, deteksi file duplikat
    raw_path         TEXT,                              -- lokasi data mentah di Data Lake (lineage)
    curated_path     TEXT,                              -- lokasi data bersih di Data Lake (lineage)
    started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at      TIMESTAMPTZ,
    error_message    TEXT,
    notes            TEXT
);

CREATE TABLE IF NOT EXISTS etl_audit.etl_reject (
    reject_id      BIGSERIAL PRIMARY KEY,
    batch_id       BIGINT      NOT NULL REFERENCES etl_audit.etl_log (batch_id),
    source_name    TEXT        NOT NULL,
    source_row_no  INTEGER,
    reject_reason  TEXT        NOT NULL,
    raw_record     JSONB,
    rejected_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_etl_reject_batch ON etl_audit.etl_reject (batch_id);
CREATE INDEX IF NOT EXISTS ix_etl_log_source_status ON etl_audit.etl_log (source_name, status);

-- Durasi setiap tahap per batch (ingest, stage, transform, load, train_model) untuk evaluasi performa.
CREATE TABLE IF NOT EXISTS etl_audit.etl_stage_log (
    stage_log_id   BIGSERIAL PRIMARY KEY,
    batch_id       BIGINT      NOT NULL REFERENCES etl_audit.etl_log (batch_id),
    stage          TEXT        NOT NULL,
    status         TEXT        NOT NULL CHECK (status IN ('SUCCESS', 'FAILED', 'SKIPPED')),
    rows_processed INTEGER,
    started_at     TIMESTAMPTZ NOT NULL,
    finished_at    TIMESTAMPTZ NOT NULL,
    duration_sec   NUMERIC(12,3) NOT NULL,
    peak_mem_mb    NUMERIC(10,1)                       -- puncak memori proses sampai tahap ini (Linux)
);
CREATE INDEX IF NOT EXISTS ix_etl_stage_log_batch ON etl_audit.etl_stage_log (batch_id);

-- Ringkasan durasi per tahap (satu baris per batch) untuk slide/laporan performa
CREATE OR REPLACE VIEW etl_audit.v_durasi_tahap AS
SELECT s.batch_id,
       l.source_name,
       l.status                                                         AS batch_status,
       MAX(s.rows_processed)                                            AS rows_max,
       SUM(s.duration_sec) FILTER (WHERE s.stage = 'ingest')            AS ingest_sec,
       SUM(s.duration_sec) FILTER (WHERE s.stage = 'stage')             AS stage_sec,
       SUM(s.duration_sec) FILTER (WHERE s.stage = 'transform')         AS transform_sec,
       SUM(s.duration_sec) FILTER (WHERE s.stage = 'load')              AS load_sec,
       SUM(s.duration_sec) FILTER (WHERE s.stage LIKE 'ml_%')           AS ml_sec,
       SUM(s.duration_sec)                                              AS total_sec,
       MAX(s.peak_mem_mb)                                               AS peak_mem_mb,
       MIN(s.started_at)                                                AS started_at
FROM etl_audit.etl_stage_log s
JOIN etl_audit.etl_log l ON l.batch_id = s.batch_id
GROUP BY s.batch_id, l.source_name, l.status;

GRANT SELECT ON etl_audit.etl_stage_log, etl_audit.v_durasi_tahap TO bi_analyst;
GRANT SELECT ON etl_audit.v_durasi_tahap TO dashboard_ro;

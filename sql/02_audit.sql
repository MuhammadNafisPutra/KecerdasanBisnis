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

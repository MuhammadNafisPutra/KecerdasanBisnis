-- Schema lapisan data di PostgreSQL
--   stg       : staging, salinan data dari raw zone (Data Lake) per batch
--   dw        : data warehouse dimensional (star schema) dan data mart
--   etl_audit : catatan proses (log batch dan baris ditolak)
-- Raw zone dan curated zone ada di Data Lake (folder data_lake/), bukan di database.
CREATE SCHEMA IF NOT EXISTS stg;
CREATE SCHEMA IF NOT EXISTS dw;
CREATE SCHEMA IF NOT EXISTS etl_audit;

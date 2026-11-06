-- Hak akses baca. Dijalankan sebagai admin setelah objek dibuat oleh etl_user.
--   bi_analyst   : baca stg, dw, etl_audit
--   dashboard_ro : hanya baca data mart (dw.mart_*) dan etl_audit.v_ringkasan_etl

GRANT USAGE ON SCHEMA stg, dw, etl_audit TO bi_analyst;
GRANT SELECT ON ALL TABLES IN SCHEMA stg, dw, etl_audit TO bi_analyst;

GRANT USAGE ON SCHEMA dw, etl_audit TO dashboard_ro;
GRANT SELECT ON dw.mart_retensi_pemula,
                dw.mart_program_pemasaran,
                dw.mart_benchmark_who,
                dw.mart_who_country_latest TO dashboard_ro;
GRANT SELECT ON etl_audit.v_ringkasan_etl TO dashboard_ro;

-- Catatan: view mart_benchmark_who, mart_who_country_latest, dan v_ringkasan_etl
-- dimiliki etl_user, sehingga dashboard_ro dapat membacanya tanpa hak ke tabel dasar.

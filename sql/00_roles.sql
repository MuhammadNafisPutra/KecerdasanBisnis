-- Peran database. Dijalankan sebagai admin (db_admin).
-- Kata sandi dikirim lewat variabel psql (-v), tidak ditulis di file.
--   etl_user     : pemilik objek DWH, dipakai pipeline ETL
--   bi_analyst   : baca semua schema (Data Analyst / Tim BI)
--   dashboard_ro : hanya baca data mart dan ringkasan ETL

SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'etl_user', :'etl_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'etl_user') \gexec

SELECT format('CREATE ROLE bi_analyst LOGIN PASSWORD %L', :'bi_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bi_analyst') \gexec

SELECT format('CREATE ROLE dashboard_ro LOGIN PASSWORD %L', :'dash_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dashboard_ro') \gexec

-- etl_user boleh membuat schema di database ini (menjadi pemilik objek DWH)
SELECT format('GRANT CREATE, CONNECT ON DATABASE %I TO %I', :'db_name', :'etl_user') \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO bi_analyst, dashboard_ro', :'db_name') \gexec

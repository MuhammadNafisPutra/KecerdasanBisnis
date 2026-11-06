#!/bin/bash
# Dijalankan otomatis SEKALI oleh image postgres saat volume masih kosong.
# Urutan: buat peran -> buat objek DWH sebagai etl_user (pemilik) -> beri hak baca.
set -euo pipefail

echo ">> Membuat peran database"
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -v etl_user="$DW_USER" -v etl_pw="$DW_PASSWORD" \
  -v bi_pw="$BI_PASSWORD" -v dash_pw="$DASHBOARD_PASSWORD" \
  -v db_name="$POSTGRES_DB" \
  -f /sql/00_roles.sql

echo ">> Membuat schema dan tabel sebagai $DW_USER"
for f in /sql/0[1-7]_*.sql; do
  echo "   - $f"
  psql -v ON_ERROR_STOP=1 -U "$DW_USER" -d "$POSTGRES_DB" -f "$f"
done

echo ">> Memberi hak akses baca"
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /sql/08_grants.sql
echo ">> Selesai"

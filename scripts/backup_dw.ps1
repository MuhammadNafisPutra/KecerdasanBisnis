# Backup data warehouse (Windows PowerShell). Jalankan dari folder proyek:
#   powershell -ExecutionPolicy Bypass -File scripts\backup_dw.ps1
# Hasil: backups\fitzone_dw_<tanggal>.dump (format custom pg_dump, bisa dipulihkan dengan pg_restore)
# Restore:
#   docker exec -i fitzone_postgres pg_restore -U db_admin -d fitzone_dw --clean --if-exists < backups\<file>.dump

$ErrorActionPreference = "Stop"
$envFile = Get-Content .env | Where-Object { $_ -match "^\s*[^#].*=" }
$cfg = @{}
foreach ($line in $envFile) { $k, $v = $line -split "=", 2; $cfg[$k.Trim()] = $v.Trim() }

New-Item -ItemType Directory -Force -Path backups | Out-Null
$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$out = "backups\fitzone_dw_$stamp.dump"

docker exec fitzone_postgres pg_dump -U $cfg["PG_ADMIN_USER"] -d $cfg["DW_NAME"] -Fc -f /tmp/backup.dump
docker cp fitzone_postgres:/tmp/backup.dump $out
docker exec fitzone_postgres rm /tmp/backup.dump

# Simpan 7 backup terakhir saja
Get-ChildItem backups\fitzone_dw_*.dump | Sort-Object LastWriteTime -Descending | Select-Object -Skip 7 | Remove-Item
Write-Host "Backup selesai: $out ($([math]::Round((Get-Item $out).Length / 1KB)) KB)"

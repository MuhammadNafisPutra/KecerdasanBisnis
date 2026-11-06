"""Cek cepat WHO GHO API sebelum menjalankan pipeline (jalankan di laptop: python scripts/cek_who_api.py).

Menampilkan jumlah record, negara, rentang tahun, dan kode gender/umur per indikator.
Angka ini dipakai sebagai angka ASLI untuk bagian Volume/Variety di laporan.
"""
import collections

import requests

BASE = "https://ghoapi.azureedge.net/api"
INDIKATOR = ["NCD_BMI_30A", "NCD_BMI_25A", "NCD_BMI_MEAN", "NCD_PAA"]

total = 0
for kode in INDIKATOR:
    r = requests.get(f"{BASE}/{kode}", timeout=90)
    r.raise_for_status()
    data = r.json()["value"]
    total += len(data)
    negara = {d["SpatialDim"] for d in data if d.get("SpatialDimType") == "COUNTRY"}
    tahun = [d["TimeDim"] for d in data if d.get("TimeDim")]
    print(f"\n{kode}: {len(data):,} record | {len(negara)} negara | tahun {min(tahun)}-{max(tahun)} "
          f"| ukuran {len(r.content) / 1e6:.1f} MB")
    print("  SpatialDimType:", dict(collections.Counter(d.get("SpatialDimType") for d in data)))
    print("  Dim1 (gender) :", dict(collections.Counter(d.get("Dim1") for d in data)))
    print("  Dim2 (umur)   :", dict(collections.Counter(d.get("Dim2") for d in data).most_common(5)))

print(f"\nTOTAL record mentah semua indikator: {total:,}")

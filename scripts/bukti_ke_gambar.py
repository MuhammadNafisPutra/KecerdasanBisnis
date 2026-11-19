"""Ubah file teks bukti eksekusi (hasil python -m etl.bukti) menjadi gambar PNG untuk laporan dan PPT.

Pemakaian:
    python scripts/bukti_ke_gambar.py                 # folder bukti terbaru di data/bukti
    python scripts/bukti_ke_gambar.py data/bukti/XXXX # folder tertentu

Hasil: <folder bukti>/gambar/01_sumber_dan_ingestion.png, dan seterusnya.
Butuh Pillow (pip install pillow).
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
TINTA = "#16181d"
ORANYE = "#e4572e"
KERTAS = "#fbfaf7"
TEKS = "#1f1f1e"
TEKS2 = "#6b6a66"
UKURAN = 26          # ukuran huruf isi (px); gambar disimpan besar agar tajam saat dicetak


def font(nama_list, ukuran):
    for nama in nama_list:
        try:
            return ImageFont.truetype(nama, ukuran)
        except OSError:
            continue
    return ImageFont.load_default()


MONO = font(["DejaVuSansMono.ttf", "consola.ttf", "cour.ttf", "Menlo.ttc"], UKURAN)
JUDUL = font(["DejaVuSans-Bold.ttf", "segoeuib.ttf", "arialbd.ttf"], 34)
KECIL = font(["DejaVuSans.ttf", "segoeui.ttf", "arial.ttf"], 22)


def render(txt: Path, out: Path):
    baris = txt.read_text(encoding="utf-8").splitlines()
    judul = baris[0].lstrip("# ").strip() if baris else txt.stem
    waktu = baris[1].lstrip("# ").strip() if len(baris) > 1 else ""
    isi = baris[2:]
    while isi and not isi[0].strip():
        isi = isi[1:]

    lebar_char = MONO.getbbox("M")[2]
    tinggi_baris = int(UKURAN * 1.45)
    pad = 40
    lebar = max(1100, pad * 2 + lebar_char * max((len(b) for b in isi), default=40))
    kepala = 120
    tinggi = kepala + pad + tinggi_baris * len(isi) + pad

    img = Image.new("RGB", (lebar, tinggi), KERTAS)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, lebar, kepala], fill=TINTA)
    d.rectangle([0, kepala - 6, lebar, kepala], fill=ORANYE)
    d.text((pad, 24), judul, font=JUDUL, fill="white")
    d.text((pad, 72), f"{waktu}  ·  {txt.name}", font=KECIL, fill="#c9c7c0")

    y = kepala + pad
    for b in isi:
        warna = TEKS
        s = b.strip()
        if s.endswith(":") and not s.startswith(("{", "\"")):
            warna = ORANYE                          # baris keterangan bagian
        elif s.startswith("GAGAL"):
            warna = "#b3261e"
        d.text((pad, y), b, font=MONO, fill=warna)
        y += tinggi_baris
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, optimize=True)


def main():
    if len(sys.argv) > 1:
        folder = Path(sys.argv[1])
    else:
        semua = sorted((ROOT / "data" / "bukti").glob("*/"))
        if not semua:
            sys.exit("Belum ada folder bukti. Jalankan dulu: python -m etl.bukti")
        folder = semua[-1]
    for txt in sorted(folder.glob("0*.txt")):
        out = folder / "gambar" / f"{txt.stem}.png"
        render(txt, out)
        print("dibuat", out)


if __name__ == "__main__":
    main()

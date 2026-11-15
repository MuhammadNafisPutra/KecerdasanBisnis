"""Buat grafik hasil uji skala untuk laporan/PPT (jalankan di laptop: python scripts/grafik_uji_skala.py).

Membaca data/uji_skala/hasil_uji_skala.csv, menulis 3 file PNG di folder yang sama:
  1_waktu_vs_data.png   waktu ETL dan waktu training ML per ukuran data (dua panel, sumbu biasa)
  2_porsi_tahap.png     porsi waktu tiap tahap ETL (mencari bottleneck)
  3_memori.png          puncak memori dibanding batas memori container Airflow

Warna mengikuti identitas FitZone: tinta #16181d, aksen oranye #e4572e, abu-abu untuk pembanding.
Angka memakai format Indonesia (koma desimal, titik ribuan).
"""
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

DIR = Path(__file__).resolve().parents[1] / "data" / "uji_skala"
BATAS_CONTAINER_MB = 1536                     # mem_limit airflow-scheduler di docker-compose.yml

TINTA = "#16181d"
ORANYE = "#e4572e"
ABU = ["#d9d7d0", "#b4b2aa", "#85837c"]       # ingest, stage, transform
TEKS2 = "#52514e"


def n(v, d=0):
    """Angka format Indonesia."""
    s = f"{v:,.{d}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def label_skala(r):
    return f"{r.skala}\n{n(r.baris)} baris"


def rapikan(ax, sumbu_y=True):
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#c9c7c0")
    ax.tick_params(axis="both", length=0, colors=TEKS2)
    if sumbu_y:
        ax.yaxis.grid(True, color="#ebeae6", lw=1)
        ax.set_axisbelow(True)


df = pd.read_csv(DIR / "hasil_uji_skala.csv")
ok = df[df["status"] == "SUKSES"].copy()
gagal = df[df["status"] != "SUKSES"]
ok["ml_sec"] = ok["ml_train_sec"]           # waktu melatih model, sama dengan Tabel 4.8 laporan
label = [label_skala(r) for r in ok.itertuples()]

plt.rcParams.update({"font.size": 12, "font.family": "DejaVu Sans", "axes.titlesize": 13})

# 1) Waktu proses: dua panel terpisah agar tiap angka terbaca tanpa skala log
fig, axes = plt.subplots(1, 2, figsize=(9, 4.6))
for ax, kol, judul, warna in [(axes[0], "etl_sec", "ETL (ingest sampai load)", TINTA),
                              (axes[1], "ml_sec", "Training model ML", ORANYE)]:
    v = ok[kol].tolist()
    bar = ax.bar(label, v, color=warna, width=0.6)
    for b, x in zip(bar, v):
        ax.text(b.get_x() + b.get_width() / 2, x, f"{n(x, 1)} detik", ha="center", va="bottom",
                fontsize=11, color=TINTA, fontweight="bold")
    ax.set_title(judul, loc="left", color=TINTA, fontweight="bold")
    ax.set_ylim(0, max(v) * 1.18)
    ax.set_ylabel("Detik", color=TEKS2)
    rapikan(ax)
fig.suptitle("Waktu proses pipeline per ukuran data", x=0.02, ha="left", fontsize=15, fontweight="bold",
             color=TINTA)
fig.text(0.02, 0.895, "Training model memakan waktu jauh lebih lama daripada ETL pada semua ukuran data",
         fontsize=11, color=TEKS2)
fig.tight_layout(rect=(0, 0, 1, 0.88))
fig.savefig(DIR / "1_waktu_vs_data.png", dpi=200, facecolor="white")
plt.close(fig)

# 2) Porsi waktu tiap tahap ETL
tahap = ["ingest", "stage", "transform", "load"]
nama_tahap = {"ingest": "Ingest", "stage": "Staging", "transform": "Transform", "load": "Load ke DWH"}
warna_tahap = dict(zip(tahap, ABU + [ORANYE]))
detik = ok.set_index("skala")[[f"{t}_sec" for t in tahap]]
porsi = detik.div(detik.sum(axis=1), axis=0) * 100
fig, ax = plt.subplots(figsize=(9, 4.4))
ylab = [label_skala(r).replace("\n", " · ") for r in ok.itertuples()]
kiri = [0.0] * len(porsi)
for t in tahap:
    v = porsi[f"{t}_sec"].tolist()
    ax.barh(ylab, v, left=kiri, color=warna_tahap[t], height=0.6, label=nama_tahap[t],
            edgecolor="white", linewidth=1.5)
    for i, (x, l) in enumerate(zip(v, kiri)):
        if x >= 8:
            ax.text(l + x / 2, i, f"{n(x)}%", ha="center", va="center", fontsize=11,
                    color="white" if t in ("transform", "load") else TINTA, fontweight="bold")
    kiri = [a + b for a, b in zip(kiri, v)]
ax.invert_yaxis()
ax.set_xlim(0, 100)
ax.set_xlabel("Persentase waktu ETL (%)", color=TEKS2)
ax.legend(ncol=4, frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0), fontsize=11)
rapikan(ax, sumbu_y=False)
fig.suptitle("Tahap load makin dominan saat data membesar", x=0.02, ha="left", fontsize=15,
             fontweight="bold", color=TINTA)
fig.text(0.02, 0.895, "Porsi waktu tiap tahap ETL terhadap total waktu ETL", fontsize=11, color=TEKS2)
fig.tight_layout(rect=(0, 0, 1, 0.88))
fig.savefig(DIR / "2_porsi_tahap.png", dpi=200, facecolor="white")
plt.close(fig)

# 3) Puncak memori; ukuran yang gagal tidak digambar sebagai batang karena puncaknya tidak terukur
fig, ax = plt.subplots(figsize=(9, 4.8))
semua = df.copy()
lab_semua = [label_skala(r) for r in semua.itertuples()]
nilai = [r.peak_mem_mb if r.status == "SUKSES" else 0 for r in semua.itertuples()]
bar = ax.bar(lab_semua, nilai, color=TINTA, width=0.6)
for b, r in zip(bar, semua.itertuples()):
    x = b.get_x() + b.get_width() / 2
    if r.status == "SUKSES":
        ax.text(x, r.peak_mem_mb, f"{n(r.peak_mem_mb)} MB", ha="center", va="bottom", fontsize=11,
                fontweight="bold", color=TINTA)
    else:
        ax.text(x, BATAS_CONTAINER_MB * 0.45, "GAGAL\nkehabisan memori\nsaat transform", ha="center",
                va="center", fontsize=11, fontweight="bold", color=ORANYE)
ax.axhline(BATAS_CONTAINER_MB, color=ORANYE, ls="--", lw=1.5)
ax.text(-0.4, BATAS_CONTAINER_MB * 1.02, f"Batas memori container: {n(BATAS_CONTAINER_MB)} MB",
        color=ORANYE, fontsize=11, va="bottom")
ax.set_ylim(0, BATAS_CONTAINER_MB * 1.15)
ax.set_ylabel("Puncak memori (MB)", color=TEKS2)
rapikan(ax)
terbesar = ok.iloc[-1]
ax.set_title(f"Pipeline berjalan sampai {terbesar.skala} ({n(terbesar.baris)} baris)", loc="left",
             fontsize=15, fontweight="bold", color=TINTA, pad=26)
ax.text(0, 1.03, "Puncak memori proses pipeline per ukuran data", transform=ax.transAxes, fontsize=11,
        color=TEKS2)
fig.tight_layout()
fig.savefig(DIR / "3_memori.png", dpi=200, facecolor="white")
plt.close(fig)

print("Grafik tersimpan di", DIR)

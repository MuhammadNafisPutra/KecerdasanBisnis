"""Buat grafik hasil uji skala untuk laporan/PPT (jalankan di laptop: python scripts/grafik_uji_skala.py).

Membaca data/uji_skala/hasil_uji_skala.csv, menulis 3 file PNG di folder yang sama:
  1_waktu_vs_data.png   waktu ETL dan ML terhadap jumlah baris (skala log)
  2_porsi_tahap.png     porsi waktu tiap tahap ETL (mencari bottleneck)
  3_memori.png          puncak memori dibanding batas container Airflow
"""
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

DIR = Path(__file__).resolve().parents[1] / "data" / "uji_skala"
BATAS_CONTAINER_MB = 1536                     # mem_limit airflow-scheduler di docker-compose.yml
WARNA = {"ingest": "#9ec5e8", "stage": "#4a90c8", "transform": "#e8a23a", "load": "#c8553d",
         "etl": "#1f4e79", "ml": "#7a5195"}

df = pd.read_csv(DIR / "hasil_uji_skala.csv")
ok = df[df["status"] == "SUKSES"].copy()
ok["ml_sec"] = ok[[c for c in ("ml_load_data_sec", "ml_train_sec", "ml_write_sec") if c in ok]].sum(axis=1)

plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})

# 1) Waktu vs jumlah data
fig, ax = plt.subplots(figsize=(7.5, 4.5))
ax.plot(ok["baris"], ok["etl_sec"], "o-", color=WARNA["etl"], lw=2, label="ETL (ingest → load)")
if ok["ml_sec"].gt(0).any():
    ax.plot(ok["baris"], ok["ml_sec"], "s--", color=WARNA["ml"], lw=2, label="Training ML")
ax.set_xscale("log"); ax.set_yscale("log")
ax.set_xlabel("Jumlah baris member (skala log)"); ax.set_ylabel("Detik (skala log)")
for r in ok.itertuples():
    ax.annotate(f"{r.skala}\n{r.etl_sec:.1f} s", (r.baris, r.etl_sec), textcoords="offset points",
                xytext=(0, -12), ha="center", va="top", fontsize=9, color=WARNA["etl"])
ax.set_title("Waktu proses terhadap volume data", loc="left", fontweight="bold")
ax.legend(frameon=False); ax.grid(alpha=0.3, which="major")
fig.tight_layout(); fig.savefig(DIR / "1_waktu_vs_data.png", dpi=200); plt.close(fig)

# 2) Porsi waktu tiap tahap ETL
tahap = ["ingest", "stage", "transform", "load"]
porsi = ok.set_index("skala")[[f"{t}_sec" for t in tahap]]
porsi = porsi.div(porsi.sum(axis=1), axis=0) * 100
fig, ax = plt.subplots(figsize=(7.5, 4.5))
kiri = pd.Series(0.0, index=porsi.index)
for t in tahap:
    v = porsi[f"{t}_sec"]
    ax.barh(porsi.index, v, left=kiri, color=WARNA[t], label=t)
    for i, (x, w) in enumerate(zip(kiri, v)):
        if w >= 7:
            ax.text(x + w / 2, i, f"{w:.0f}%", ha="center", va="center", fontsize=9,
                    color="white" if t in ("stage", "load") else "black")
    kiri += v
ax.invert_yaxis(); ax.set_xlim(0, 100); ax.set_xlabel("% waktu ETL")
ax.set_title("Porsi waktu per tahap ETL", loc="left", fontweight="bold")
ax.legend(ncol=4, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.15))
fig.tight_layout(); fig.savefig(DIR / "2_porsi_tahap.png", dpi=200); plt.close(fig)

# 3) Puncak memori
if "peak_mem_mb" in df and df["peak_mem_mb"].notna().any():
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    warna = ["#1f4e79" if s == "SUKSES" else "#c8553d" for s in df["status"]]
    ax.bar(df["skala"], df["peak_mem_mb"].fillna(0), color=warna)
    ax.axhline(BATAS_CONTAINER_MB, color="#c8553d", ls="--", lw=1.5)
    ax.text(-0.4, BATAS_CONTAINER_MB * 1.03, f"batas container {BATAS_CONTAINER_MB} MB", color="#c8553d", fontsize=9)
    for i, v in enumerate(df["peak_mem_mb"]):
        if pd.notna(v):
            ax.text(i, v, f"{v:,.0f} MB", ha="center", va="bottom", fontsize=9)
    ax.set_ylabel("Puncak memori (MB)")
    ax.set_title("Puncak memori proses pipeline", loc="left", fontweight="bold")
    fig.tight_layout(); fig.savefig(DIR / "3_memori.png", dpi=200); plt.close(fig)

print("Grafik disimpan di", DIR)

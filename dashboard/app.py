"""Dashboard BI PT FitZone Nusantara. Membaca hanya data mart di PostgreSQL (role dashboard_ro).

Dirancang agar mudah dibaca orang awam:
- tiap halaman dibuka dengan pertanyaan bisnis yang dijawab halaman itu;
- kartu angka utama disertai penjelasan singkat dalam bahasa sehari-hari;
- tiap grafik diikuti temuan dan rekomendasi yang angkanya dihitung
  otomatis dari data, sehingga tetap benar saat filter diubah atau data diperbarui;
- keterangan cara membaca grafik ditulis langsung pada subjudul grafik.

Identitas visual mengikuti logo FitZone: tinta #16181d, kertas #f4f3ef, aksen oranye #e4572e.
Warna kategori urutan tetap yang lolos uji buta warna (oranye, biru, aqua);
satu hal yang disorot diberi warna, sisanya abu-abu; selisih kecil memakai dot plot.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from pathlib import Path

from PIL import Image

import db

LOGO = Path(__file__).parent / "assets" / "logo.png"

st.set_page_config(page_title="FitZone BI", page_icon=Image.open(LOGO) if LOGO.exists() else None,
                   layout="wide")

# ---------------------------------------------------------------- palet
BIRU = "#2a78d6"
TINTA = "#16181d"     # warna gelap logo
KERTAS = "#f4f3ef"    # warna terang logo
ORANYE = "#e4572e"    # oranye logo
AQUA = "#1baf7a"
KUNING = "#eda100"
MERAH_MUDA = "#e87ba4"
ABU = "#c3c2b7"
ABU_TUA = "#8a8984"
TEKS = "#0b0b0b"
TEKS2 = "#52514e"
GRID = "#ebeae6"
SURFACE = "rgba(0,0,0,0)"   # transparan: grafik menyatu dengan latar halaman

HALAMAN = [
    "Ringkasan Eksekutif",
    "Retensi & Pemula",
    "Program & Pemasaran",
    "Benchmark WHO",
    "Prediksi Lemak Tubuh (ML)",
    "Kualitas Data & ETL",
]
FILTER_KOLOM = {
    "Jenis kelamin": "gender",
    "Jenis latihan": "workout_type",
    "Kelompok usia": "age_group",
    "Level pengalaman": "experience_name",
    "Kategori BMI": "bmi_category",
}
URUT_LEVEL = ["Pemula", "Menengah", "Mahir"]
URUT_DURASI = ["< 1 jam", "1 - 1,5 jam", "> 1,5 jam"]
URUT_BMI = ["Underweight", "Normal", "Overweight", "Obese"]
BMI_ID = {"Underweight": "Kurus", "Normal": "Normal", "Overweight": "Gemuk", "Obese": "Obesitas"}
GENDER_ID = {"Male": "Laki-laki", "Female": "Perempuan", "Both sexes": "Semua"}

st.markdown(
    """
    <style>
      .block-container {padding-top: 3.2rem;}
      .judul h1 {font-size: 1.6rem; margin: 0 0 2px 0; padding: 0; color: #0b0b0b;}
      .judul .tanya {font-size: 0.95rem; color: #0b0b0b; margin: 0 0 4px 0;}
      .judul .ket {font-size: 0.85rem; color: #52514e; margin: 0 0 4px 0; max-width: 980px;}
      .kpi-grid {display: grid; gap: 10px; margin: 16px 0 18px 0;}
      .kpi {background: #fff; border: 1px solid #e3e2dd; border-radius: 8px; padding: 10px 14px;}
      .kpi .lab {font-size: 0.8rem; color: #52514e;}
      .kpi .val {font-size: 1.45rem; font-weight: 600; color: #0b0b0b; margin: 2px 0;}
      .kpi .sub {font-size: 0.76rem; color: #6b6a66; line-height: 1.3;}
      .temuan {border: 1px solid #e3e2dd; border-radius: 8px; padding: 12px 18px; background: #fff;
               margin-bottom: 8px;}
      .temuan ol {margin: 0; padding-left: 18px;}
      .temuan li {font-size: 0.9rem; color: #1f1f1e; line-height: 1.5; margin: 3px 0;}
      .kotak {font-size: 0.88rem; line-height: 1.55; color: #2b2b29; margin: 2px 0 8px 0;}
      .merek {display: flex; align-items: center; gap: 12px; margin: -8px 0 18px 0;}
      .merek img {width: 52px; height: 52px; border-radius: 6px;}
      .merek .nama {font-size: 1.25rem; font-weight: 700; letter-spacing: 0.02em; color: #f4f3ef;}
      .merek .sub {font-size: 0.78rem; color: #a9a7a0; letter-spacing: 0.04em;}
      .judul {margin-bottom: 6px;}
      .kpi .val {color: #16181d;}
      .bagian {font-size: 1.05rem; font-weight: 600; margin: 22px 0 8px 0; color: #0b0b0b;}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------- format angka Indonesia
def n(v, d=0) -> str:
    """Angka format Indonesia: titik pemisah ribuan, koma desimal."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    s = f"{v:,.{d}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def pct(v, d=1) -> str:
    return f"{n(v, d)}%"


# ---------------------------------------------------------------- komponen teks
def hero(judul, pertanyaan, ket=""):
    st.markdown(f"<div class='judul'><h1>{judul}</h1><p class='tanya'>Pertanyaan bisnis: {pertanyaan}</p>"
                f"<p class='ket'>{ket}</p></div>", unsafe_allow_html=True)


def kpi(kartu: list):
    """kartu: list of (ikon, label, nilai, penjelasan, warna); ikon dan warna tidak dipakai."""
    isi = "".join(f"<div class='kpi'><div class='lab'>{lab}</div><div class='val'>{val}</div>"
                  f"<div class='sub'>{sub}</div></div>" for _, lab, val, sub, _ in kartu)
    st.markdown(f"<div class='kpi-grid' style='grid-template-columns:repeat({len(kartu)},1fr)'>{isi}</div>",
                unsafe_allow_html=True)


def temuan(daftar: list):
    """daftar: list of (judul, isi, warna)."""
    isi = "".join(f"<li><b>{jdl}.</b> {teks}</li>" for jdl, teks, _ in daftar)
    st.markdown(f"<div class='temuan'><ol>{isi}</ol></div>", unsafe_allow_html=True)


def kotak(jenis, teks):
    label = {"artinya": "Temuan", "saran": "Rekomendasi", "awas": "Perlu perhatian"}[jenis]
    st.markdown(f"<div class='kotak'><b>{label}.</b> {teks}</div>", unsafe_allow_html=True)


def bagian(teks):
    st.markdown(f"<div class='bagian'>{teks}</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------- bantu grafik
def _gaya(fig, judul, sub=None, xlabel="", ylabel="", tinggi=360, legend=False):
    teks = f"<b>{judul}</b>"
    if sub:
        teks += f"<br><span style='font-size:12px;color:{TEKS2}'>{sub}</span>"
    fig.update_layout(
        title=dict(text=teks, x=0, xanchor="left", font=dict(size=15, color=TEKS)),
        height=tinggi, margin=dict(l=80, r=30, t=80 if sub else 55, b=60),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE, separators=",.",
        font=dict(family="Inter, Segoe UI, sans-serif", size=12, color=TEKS2),
        showlegend=legend, hovermode="closest", bargap=0.35,
        hoverlabel=dict(bgcolor="white", font_size=13, bordercolor=GRID),
        legend=dict(orientation="h", y=-0.34 if xlabel else -0.18, yanchor="top", x=0,
                    font=dict(color=TEKS2)),
    )
    fig.update_xaxes(title=xlabel, showgrid=False, linecolor=GRID, tickfont=dict(color=TEKS2),
                     zeroline=False, automargin=True)
    fig.update_yaxes(title=ylabel, gridcolor=GRID, linecolor=GRID, tickfont=dict(color=TEKS2),
                     zeroline=False, automargin=True)
    try:
        fig.update_layout(barcornerradius=4)
    except ValueError:  # plotly lama
        pass
    return fig


def tampil(fig):
    st.plotly_chart(fig, config={"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]})


def batang(series, judul, sub=None, sorot=None, warna=None, des=0, satuan="", ylabel="",
           horizontal=False, urut=None, tinggi=340, warna_per=None, label=None, hover_satuan=None):
    """Batang. `sorot` = kunci yang diberi warna (sisanya abu-abu); `warna_per` = warna per kunci;
    `label` = teks di atas batang (default: nilai + satuan)."""
    s = series.copy()
    if urut is not None:
        s = s.reindex([u for u in urut if u in s.index])
    x = [str(i) for i in s.index]
    y = [float(v) for v in s.values]
    if warna_per:
        warna_bar = [warna_per.get(k, ABU) for k in x]
    elif sorot is None:
        warna_bar = [warna or TINTA] * len(x)
    else:
        sorot = set(sorot) if isinstance(sorot, (list, tuple, set)) else {sorot}
        warna_bar = [(warna or ORANYE) if k in sorot else ABU for k in x]
    teks = label if label is not None else [f"{n(v, des)}{satuan}" for v in y]
    hs = hover_satuan if hover_satuan is not None else satuan
    if horizontal:
        fig = go.Figure(go.Bar(y=x, x=y, orientation="h", marker_color=warna_bar, text=teks,
                               textposition="outside", cliponaxis=False,
                               hovertemplate="<b>%{y}</b><br>%{x:,." + str(des) + "f}" + hs + "<extra></extra>"))
        fig.update_yaxes(autorange="reversed", showgrid=False)
        fig.update_xaxes(showgrid=True, gridcolor=GRID, showticklabels=False, range=[0, max(y) * 1.22])
    else:
        fig = go.Figure(go.Bar(x=x, y=y, marker_color=warna_bar, text=teks, textposition="outside",
                               cliponaxis=False,
                               hovertemplate="<b>%{x}</b><br>%{y:,." + str(des) + "f}" + hs + "<extra></extra>"))
        fig.update_yaxes(range=[0, max(y) * 1.2] if y else None)
    fig.update_traces(textfont=dict(color=TEKS, size=13))
    return _gaya(fig, judul, sub, ylabel=ylabel, tinggi=tinggi)


def dot_plot(series, judul, satuan="", des=0, tinggi=320):
    """Cleveland dot plot dengan sumbu diperbesar dan garis rata-rata, untuk nilai yang berdekatan."""
    s = series.astype(float).sort_values()
    rata = float(s.mean())
    lo, hi = float(s.min()), float(s.max())
    pad = max((hi - lo) * 0.6, abs(rata) * 0.01, 0.5)
    fig = go.Figure()
    for k, v in s.items():
        fig.add_trace(go.Scatter(x=[rata, v], y=[k, k], mode="lines", line=dict(color=ABU, width=3),
                                 hoverinfo="skip"))
    warna = [ORANYE if v == hi else (AQUA if v == lo else TINTA) for v in s.values]
    teks = [f"{n(v, des)}{satuan} ({'+' if v >= rata else '−'}{n(abs(v - rata), des)})" for v in s.values]
    fig.add_trace(go.Scatter(
        x=s.values, y=list(s.index), mode="markers+text",
        marker=dict(size=15, color=warna, line=dict(color="white", width=2)), text=teks,
        textposition=["middle left" if v < rata else "middle right" for v in s.values],
        textfont=dict(color=TEKS, size=12), cliponaxis=False,
        hovertemplate="<b>%{y}</b><br>%{x:,." + str(des) + "f}" + satuan + "<extra></extra>"))
    fig.add_vline(x=rata, line_dash="dot", line_color=ABU_TUA,
                  annotation_text=f"rata-rata {n(rata, des)}{satuan}", annotation_position="top",
                  annotation_font=dict(color=TEKS2, size=11))
    fig.update_xaxes(range=[lo - pad * 2.4, hi + pad * 2.4], showgrid=True, gridcolor=GRID)
    fig.update_yaxes(showgrid=False)
    sub = (f"Selisih tertinggi dan terendah {n(hi - lo, des)}{satuan} "
           f"({pct(100 * (hi - lo) / rata)} dari rata-rata)")
    return _gaya(fig, judul, sub, tinggi=tinggi)


def garis(x, y, judul, sub=None, satuan="", des=1, xlabel="", ylabel="", tinggi=340):
    fig = go.Figure(go.Scatter(
        x=x, y=y, mode="lines+markers+text", line=dict(color=TINTA, width=3),
        marker=dict(size=11, color=ORANYE, line=dict(color="white", width=2)),
        fill="tozeroy", fillcolor="rgba(22,24,30,0.05)",
        text=[f"{n(v, des)}{satuan}" for v in y], textposition="top center",
        textfont=dict(color=TEKS, size=13), cliponaxis=False,
        hovertemplate="<b>%{x}</b><br>%{y:,." + str(des) + "f}" + satuan + "<extra></extra>"))
    lo, hi = min(y), max(y)
    fig.update_yaxes(range=[max(0, lo - (hi - lo) * 0.6), hi + (hi - lo) * 0.35])
    fig.update_xaxes(range=[-0.35, len(x) - 0.65])
    if len(y) >= 2 and y[0]:
        beda = y[-1] - y[0]
        arah = "turun" if beda < 0 else "naik"
        fig.add_annotation(x=1, y=1.0 if beda < 0 else 0.02, xref="paper", yref="paper", xanchor="right",
                           yanchor="top" if beda < 0 else "bottom",
                           showarrow=False, align="right",
                           text=f"{x[0]} → {x[-1]}<br>" + f"<b>{arah} {n(abs(beda), des)} poin</b><br>({pct(100 * abs(beda) / y[0], 0)})",
                           font=dict(color=ORANYE, size=12), bgcolor="rgba(0,0,0,0)", borderpad=4)
    return _gaya(fig, judul, sub, xlabel=xlabel, ylabel=ylabel, tinggi=tinggi)


def terapkan_filter(df: pd.DataFrame, pilihan: dict) -> pd.DataFrame:
    for kolom, nilai in pilihan.items():
        if nilai and kolom in df.columns:
            df = df[df[kolom].isin(nilai)]
    return df


# ---------------------------------------------------------------- sidebar & data
ok, pesan = db.tersedia()
if not ok:
    st.error("Dashboard tidak dapat terhubung ke data warehouse. Pastikan container postgres berjalan "
             "dan DASHBOARD_PASSWORD di file .env benar.")
    st.caption(f"Detail: {pesan}")
    st.stop()

if LOGO.exists():
    import base64
    _logo64 = base64.b64encode(LOGO.read_bytes()).decode()
    st.sidebar.markdown(
        f"<div class='merek'><img src='data:image/png;base64,{_logo64}'/>"
        "<div><div class='nama'>FitZone</div><div class='sub'>Business Intelligence</div></div></div>",
        unsafe_allow_html=True)
else:
    st.sidebar.markdown("## FitZone BI")
halaman = st.sidebar.radio("Halaman", HALAMAN)

retensi = db.query("SELECT * FROM dw.mart_retensi_pemula")
program = db.query("SELECT * FROM dw.mart_program_pemasaran")
pred = db.query("SELECT * FROM dw.mart_ml_prediksi_lemak")
for df_ in (retensi, program, pred):
    for c in df_.columns:
        if df_[c].dtype == object and c not in FILTER_KOLOM.values() and c not in (
                "split", "status_prediksi", "model_name", "duration_group"):
            try:
                df_[c] = pd.to_numeric(df_[c])
            except (ValueError, TypeError):
                pass

st.sidebar.markdown("---")
st.sidebar.markdown("**Saring data member**")
pilihan = {}
for label, kolom in FILTER_KOLOM.items():
    sumber = retensi if kolom in retensi.columns else program
    opsi = sorted(sumber[kolom].dropna().unique().tolist())
    pilihan[kolom] = st.sidebar.multiselect(label, opsi, placeholder="Semua")
aktif = [f"{k}: {', '.join(map(str, v))}" for k, v in zip(FILTER_KOLOM, pilihan.values()) if v]
if st.sidebar.button("Muat ulang data"):
    st.cache_data.clear()
    st.rerun()
st.sidebar.caption("Kosongkan filter untuk melihat semua member. Filter tidak berlaku untuk halaman "
                   "WHO dan ETL. Data diperbarui otomatis tiap 1 jam.")
r = terapkan_filter(retensi, pilihan)
p = terapkan_filter(program, pilihan)
pr = terapkan_filter(pred, pilihan)


def info_filter():
    if aktif:
        st.info("Filter aktif → " + " · ".join(aktif) + f" ({n(len(r))} member)")


def kosong(df) -> bool:
    if df.empty:
        st.warning("Tidak ada member yang sesuai dengan filter. Kurangi pilihan filter di sisi kiri.")
        return True
    return False


# ================================================================ halaman
if halaman == "Ringkasan Eksekutif":
    hero("Ringkasan Eksekutif", "Bagaimana kondisi kebugaran member FitZone saat ini?",
         "Data simulasi dari Kaggle (bukan data member asli). Arahkan kursor ke grafik untuk melihat angka "
         "detail.")
    info_filter()
    if not kosong(r):
        gemuk = r.bmi_category.isin(["Overweight", "Obese"]).mean() * 100
        obes = (r.bmi >= 30).mean() * 100
        kpi([
            ("", "Jumlah member", n(len(r)), "member aktif di data warehouse", BIRU),
            ("", "Rata-rata lemak tubuh", pct(r.fat_percentage.mean()),
             "rata-rata seluruh member", ORANYE),
            ("", "Kalori per sesi", f"{n(r.calories_burned.mean())} kkal",
             "rata-rata per sesi latihan", AQUA),
            ("", "Frekuensi latihan", f"{n(r.workout_frequency_days_week.mean(), 1)} hari",
             "rata-rata hari latihan per minggu", BIRU),
            ("", "Member BMI ≥ 30", pct(obes),
             "kategori obesitas menurut BMI", ORANYE),
        ])

        fq = r.groupby("workout_frequency_days_week").fat_percentage.mean()
        lv = r.groupby("experience_name").fat_percentage.mean()
        pemula = r[r.experience_level == 1]
        belum = int((pemula.workout_frequency_days_week < 3).sum())
        bagian("Temuan utama")
        tem = []
        if len(fq) >= 2:
            tem.append(("Frekuensi latihan",
                        f"Rata-rata lemak tubuh turun dari {pct(fq.iloc[0])} pada {int(fq.index[0])} hari "
                        f"per minggu menjadi {pct(fq.iloc[-1])} pada {int(fq.index[-1])} hari per minggu.", BIRU))
        tem.append(("Pemula",
                    f"{n(belum)} dari {n(len(pemula))} pemula "
                    f"({pct(100 * belum / max(len(pemula), 1))}) berlatih kurang dari 3 hari per minggu dan "
                    "menjadi kelompok yang paling berisiko berhenti.", ORANYE))
        if {"Pemula", "Mahir"} <= set(lv.index):
            tem.append(("Level pengalaman",
                        f"Rata-rata lemak tubuh member mahir {pct(lv['Mahir'])}, jauh di bawah pemula "
                        f"({pct(lv['Pemula'])}).", AQUA))
        tem.append(("BMI",
                    f"{pct(obes)} member memiliki BMI minimal 30. Pada member laki-laki, BMI tinggi "
                    "lebih banyak disebabkan massa otot, sehingga persentase lemak tubuh lebih tepat dipakai "
                    "sebagai ukuran utama.", ORANYE))
        temuan(tem)

        bagian("Detail")
        a, b = st.columns(2)
        with a, st.container(border=True):
            tampil(garis([f"{int(i)} hari" for i in fq.index], list(fq.values),
                         "Lemak tubuh turun saat member berlatih lebih sering",
                         "Rata-rata % lemak tubuh menurut jumlah hari latihan per minggu",
                         satuan="%", ylabel="% lemak tubuh", xlabel="Hari latihan per minggu"))
            if len(fq) >= 3:
                turun = fq.diff().iloc[1:]
                tajam = turun.idxmin()
                kotak("artinya", f"Lemak tubuh member yang berlatih 2 dan 3 hari per minggu hampir sama. "
                                 f"Penurunan terbesar terjadi pada {int(tajam)} hari per minggu, yaitu "
                                 f"{n(abs(turun.min()), 1)} poin.")
                kotak("saran", "Member yang baru berlatih 2-3 hari per minggu diarahkan untuk menambah "
                               "frekuensi latihan secara bertahap.")
        with b, st.container(border=True):
            s = r.groupby("bmi_category").size().reindex([u for u in URUT_BMI if u in r.bmi_category.unique()])
            tot = s.sum()
            s.index = [BMI_ID.get(i, i) for i in s.index]
            tampil(batang(s, "Sebaran member menurut kategori BMI",
                          "Kurus < 18,5 · Normal 18,5–24,9 · Gemuk 25–29,9 · Obesitas ≥ 30",
                          warna_per={"Kurus": ABU, "Normal": AQUA, "Gemuk": KUNING, "Obesitas": ORANYE},
                          label=[f"{n(v)} ({pct(100 * v / tot, 0)})" for v in s.values],
                          ylabel="Jumlah member", hover_satuan=" member"))
            kotak("artinya", f"{pct(100 * s.get('Normal', 0) / tot, 0)} member berada pada kategori normal dan "
                             f"{pct(gemuk, 0)} berada di atas normal. BMI tidak membedakan massa otot dan lemak.")
            kotak("saran", "BMI dipakai sebagai skrining awal, sedangkan persentase lemak tubuh dipakai "
                           "sebagai KPI utama kebugaran member.")
        c, d = st.columns(2)
        with c, st.container(border=True):
            tampil(batang(lv, "Lemak tubuh menurut level pengalaman",
                          "Oranye = level dengan hasil terbaik", urut=URUT_LEVEL, sorot="Mahir", des=1,
                          satuan="%", ylabel="% lemak tubuh"))
            if {"Pemula", "Menengah", "Mahir"} <= set(lv.index):
                kotak("artinya", f"Lemak tubuh pemula ({pct(lv['Pemula'])}) dan menengah ({pct(lv['Menengah'])}) "
                                 f"hampir sama, sedangkan member mahir jauh lebih rendah ({pct(lv['Mahir'])}).")
                kotak("saran", "Program progresi yang menambah lama sesi seiring naiknya level member.")
        with d, st.container(border=True):
            s = r.workout_type.value_counts().sort_values(ascending=False)
            tampil(batang(s, "Jumlah peminat per jenis latihan", "Diurutkan dari yang terbanyak",
                          horizontal=True, tinggi=300, satuan=" member",
                          sorot=s.index[0], hover_satuan=" member"))
            kotak("artinya", f"{s.index[0]} paling banyak diikuti ({n(s.iloc[0])} member). Selisihnya dengan "
                             f"{s.index[-1]} hanya {n(s.iloc[0] - s.iloc[-1])} member, sehingga minat terhadap "
                             "keempat jenis latihan relatif merata.")

elif halaman == "Retensi & Pemula":
    hero("Retensi & Pemula", "Apakah member baru (pemula) sudah berlatih secara rutin?",
         "Data tidak memiliki tanggal bergabung maupun status berhenti, sehingga retensi diukur dari "
         "keteraturan latihan. Member disebut rutin bila berlatih minimal 3 hari per minggu.")
    info_filter()
    if not kosong(r):
        pemula = r[r.experience_level == 1]
        belum = int((pemula.workout_frequency_days_week < 3).sum())
        wm = r.weekly_minutes.astype(float)
        kurang = int((wm < 150).sum())
        kpi([
            ("", "Member pemula", n(len(pemula)), f"{pct(100 * len(pemula) / len(r))} dari semua member", BIRU),
            ("", "Pemula belum rutin", n(belum),
             f"{pct(100 * belum / max(len(pemula), 1))} pemula berlatih kurang dari 3 hari", ORANYE),
            ("", "Member rutin", pct(100 * r.is_rutin_3x.astype(bool).mean()),
             "member yang berlatih minimal 3 hari per minggu", AQUA),
            ("", "Menit latihan per minggu", n(wm.mean()), "rata-rata; anjuran WHO minimal 150 menit", BIRU),
        ])
        a, b = st.columns(2)
        with a, st.container(border=True):
            s = r.groupby("experience_name").is_rutin_3x.apply(lambda x: x.astype(bool).mean() * 100)
            tampil(batang(s, "Persentase member yang sudah rutin, per level",
                          "Rutin = berlatih minimal 3 hari per minggu",
                          urut=URUT_LEVEL, sorot="Pemula", warna=ORANYE, des=1, satuan="%",
                          ylabel="% member rutin"))
            if "Pemula" in s.index:
                lain = ", ".join(f"{k.lower()} {pct(v)}" for k, v in s.items() if k != "Pemula")
                kotak("artinya", f"Baru {pct(s['Pemula'])} pemula yang rutin berlatih ({lain}). Sebanyak "
                                 f"{n(belum)} pemula belum rutin dan paling berisiko berhenti.")
                kotak("saran", "Program pendampingan 8 minggu untuk pemula dengan target minimal 3 sesi per "
                               "minggu dan pengingat jadwal.")
        with b, st.container(border=True):
            t = r.groupby(["workout_frequency_days_week", "experience_name"]).size().unstack(fill_value=0)
            fig = go.Figure()
            for lvl, w in zip(URUT_LEVEL, [ORANYE, BIRU, AQUA]):
                if lvl in t.columns:
                    fig.add_trace(go.Bar(name=lvl, x=[f"{int(i)} hari" for i in t.index], y=t[lvl],
                                         marker_color=w, text=[str(int(v)) if v > 0 else "" for v in t[lvl]],
                                         textposition="outside", cliponaxis=False, textfont=dict(color=TEKS),
                                         hovertemplate=f"<b>{lvl}</b><br>" + "%{x}/minggu: %{y} member<extra></extra>"))
            fig.add_vrect(x0=-0.5, x1=1.5 if len(t.index) > 1 else 0.5, fillcolor=ORANYE, opacity=0.06,
                          line_width=0, annotation_text="zona belum rutin", annotation_position="top left",
                          annotation_font=dict(color=ORANYE, size=11))
            fig.update_layout(barmode="group", bargroupgap=0.08)
            fig.update_yaxes(range=[0, float(t.values.max()) * 1.28])
            tampil(_gaya(fig, "Frekuensi latihan per minggu menurut level",
                         "Jumlah member per frekuensi latihan, dipisah per level", ylabel="Jumlah member",
                         xlabel="Hari latihan per minggu", legend=True))
            kotak("artinya", "Pemula berlatih 2-3 hari per minggu, sedangkan member menengah dan mahir "
                             "berlatih 3-5 hari per minggu.")
        c, d = st.columns(2)
        with c, st.container(border=True):
            fig = go.Figure()
            fig.add_trace(go.Histogram(x=wm[wm < 150], xbins=dict(start=0, end=150, size=30),
                                       marker_color=ORANYE, name="Di bawah anjuran (< 150 menit)",
                                       hovertemplate="%{x} menit: %{y} member<extra></extra>"))
            fig.add_trace(go.Histogram(x=wm[wm >= 150], xbins=dict(start=150, end=wm.max() + 30, size=30),
                                       marker_color=TINTA, name="Memenuhi anjuran (≥ 150 menit)",
                                       hovertemplate="%{x} menit: %{y} member<extra></extra>"))
            fig.add_vline(x=150, line_dash="dash", line_color=TEKS, line_width=1.5,
                          annotation_text="← batas WHO 150 menit", annotation_position="top right",
                          annotation_font=dict(color=TEKS, size=11))
            fig.update_layout(barmode="overlay", bargap=0.08)
            tampil(_gaya(fig, "Total menit latihan per minggu",
                         f"{n(kurang)} member ({pct(100 * kurang / len(r))}) belum memenuhi anjuran WHO",
                         xlabel="Menit latihan per minggu", ylabel="Jumlah member", legend=True))
            kotak("artinya", f"{pct(100 - 100 * kurang / len(r))} member sudah memenuhi anjuran WHO, sedangkan "
                             f"{n(kurang)} member masih berlatih kurang dari 150 menit per minggu. Angka ini hanya "
                             "menghitung latihan di gym.")
        with d, st.container(border=True):
            s = r.groupby("experience_name").session_duration_hours.mean() * 60
            tampil(batang(s, "Rata-rata lama satu sesi latihan, per level",
                          "Dalam menit",
                          urut=URUT_LEVEL, sorot="Pemula", warna=ORANYE, satuan=" menit", ylabel="Menit per sesi"))
            if {"Pemula", "Mahir"} <= set(s.index):
                kotak("artinya", f"Rata-rata satu sesi pemula {n(s['Pemula'])} menit, sedangkan member mahir "
                                 f"{n(s['Mahir'])} menit.")
                kotak("saran", "Lama sesi pemula dinaikkan bertahap, tidak langsung disamakan dengan sesi "
                               "member mahir.")

elif halaman == "Program & Pemasaran":
    hero("Program & Pemasaran", "Program latihan seperti apa yang paling efektif untuk dipromosikan?",
         "Hasil latihan berupa kalori terbakar dan lemak tubuh dibandingkan menurut lama sesi dan jenis kelas.")
    info_filter()
    if not kosong(p):
        dur = p.groupby("duration_group").calories_burned.mean().reindex(URUT_DURASI).dropna()
        cph = p.groupby("workout_type").calories_per_hour.mean()
        kpi([
            ("", "Kalori per jam", f"{n(p.calories_per_hour.mean())} kkal", "rata-rata semua jenis latihan", ORANYE),
            ("", "Efek sesi panjang",
             f"{n(dur.iloc[-1] / dur.iloc[0], 1)}x" if len(dur) >= 2 else "-",
             "kalori sesi > 1,5 jam dibanding sesi < 1 jam", BIRU),
            ("", "Kalori/jam tertinggi", str(cph.idxmax()),
             f"{n(cph.max())} kkal per jam, selisih {n(cph.max() - cph.min())} kkal dengan yang terendah", AQUA),
            ("", "Rata-rata lemak tubuh", pct(p.fat_percentage.mean()), "rata-rata member pada filter ini", BIRU),
        ])
        bagian("Pengaruh lama sesi")
        a, b = st.columns(2)
        with a, st.container(border=True):
            tampil(batang(dur, "Kalori terbakar per sesi, menurut lama sesi",
                          "Rata-rata kkal per sesi", sorot="> 1,5 jam", satuan=" kkal", ylabel="kkal per sesi"))
            if len(dur) >= 2:
                kotak("artinya", f"Kalori per sesi naik dari {n(dur.iloc[0])} kkal pada sesi di bawah 1 jam "
                                 f"menjadi {n(dur.iloc[-1])} kkal pada sesi lebih dari 1,5 jam.")
        with b, st.container(border=True):
            s = p.groupby("duration_group").fat_percentage.mean()
            tampil(batang(s, "Lemak tubuh menurut lama sesi", "Rata-rata persentase lemak tubuh",
                          urut=URUT_DURASI, sorot="> 1,5 jam", des=1, satuan="%", ylabel="% lemak tubuh"))
            s2 = s.reindex(URUT_DURASI).dropna()
            if len(s2) >= 2:
                kotak("artinya", f"Member dengan sesi lebih dari 1,5 jam memiliki rata-rata lemak {pct(s2.iloc[-1])}, "
                                 f"sedangkan sesi yang lebih pendek sekitar {pct(s2.iloc[:-1].mean())}. Kelompok sesi "
                                 "panjang didominasi member mahir.")
        kotak("saran", "Paket layanan disusun berdasarkan lama sesi, misalnya paket 60 menit dan 90 menit.")

        bagian("Perbandingan jenis latihan")
        c, d = st.columns(2)
        with c, st.container(border=True):
            tampil(dot_plot(cph, "Kalori per jam, per jenis latihan", satuan=" kkal"))
        with d, st.container(border=True):
            tampil(dot_plot(p.groupby("workout_type").fat_percentage.mean(), "Lemak tubuh, per jenis latihan",
                            satuan="%", des=1))
        kotak("artinya", f"Kalori per jam keempat jenis latihan hampir sama ({n(cph.min())}-{n(cph.max())} kkal), "
                         "begitu pula rata-rata lemak tubuhnya. Perbedaan hasil datang dari lama sesi, bukan dari "
                         "jenis kelas.")
        kotak("saran", "Materi pemasaran tidak mengklaim satu kelas paling membakar kalori. Member memilih "
                       "kelas sesuai preferensi.")
        bagian("Ringkasan per jenis latihan")
        tabel = p.groupby("workout_type").agg(
            member=("member_key", "count"), kalori_per_jam=("calories_per_hour", "mean"),
            durasi_jam=("session_duration_hours", "mean"), frekuensi=("workout_frequency_days_week", "mean"),
            lemak_pct=("fat_percentage", "mean"),
        ).astype(float).sort_values("kalori_per_jam", ascending=False)
        tabel.index.name = "Jenis latihan"
        st.dataframe(tabel, column_config={
            "member": st.column_config.NumberColumn("Jumlah member", format="%d"),
            "kalori_per_jam": st.column_config.ProgressColumn(
                "Kalori per jam", format="%.0f kkal", min_value=0, max_value=float(tabel.kalori_per_jam.max())),
            "durasi_jam": st.column_config.NumberColumn("Lama sesi (jam)", format="%.2f"),
            "frekuensi": st.column_config.NumberColumn("Hari/minggu", format="%.1f"),
            "lemak_pct": st.column_config.NumberColumn("Lemak tubuh", format="%.1f%%"),
        })

elif halaman == "Benchmark WHO":
    hero("Benchmark WHO", "Bagaimana kondisi member dibanding masyarakat Indonesia dan dunia?",
         "Angka pembanding berasal dari WHO Global Health Observatory pada tahun terbaru yang tersedia. "
         "Member gym bukan sampel acak penduduk, sehingga perbandingan ini bersifat indikatif.")
    bm = db.query("SELECT * FROM dw.mart_benchmark_who ORDER BY indicator_name, gender")
    nama = {"obesity_pct": "Obesitas (BMI ≥ 30)", "overweight_pct": "Kelebihan berat badan (BMI ≥ 25)",
            "mean_bmi": "Rata-rata BMI", "insufficient_activity_pct": "Kurang aktif fisik"}
    satuan_ind = {"mean_bmi": ""}
    bagian("Member FitZone vs penduduk dewasa Indonesia")
    indikator = st.selectbox("Pilih indikator", list(nama), format_func=lambda x: nama[x])
    stn = satuan_ind.get(indikator, "%")
    sub = bm[bm.indicator_name == indikator].dropna(subset=["who_value"])
    if sub.empty:
        st.info("Belum ada data WHO untuk indikator ini.")
    else:
        gx = [GENDER_ID.get(g, g) for g in sub.gender]
        mv = sub.member_value.astype(float).tolist()
        wv = sub.who_value.astype(float).tolist()
        th = int(sub.who_year.iloc[0])
        with st.container(border=True):
            fig = go.Figure([
                go.Bar(name="Member FitZone", x=gx, y=mv, marker_color=ORANYE,
                       text=[f"{n(v, 1)}{stn}" for v in mv], textposition="outside", cliponaxis=False,
                       hovertemplate="<b>Member FitZone</b> · %{x}<br>%{y:,.1f}" + stn + "<extra></extra>"),
                go.Bar(name=f"Penduduk Indonesia (WHO {th})", x=gx, y=wv, marker_color=TINTA,
                       text=[f"{n(v, 1)}{stn}" for v in wv], textposition="outside", cliponaxis=False,
                       hovertemplate="<b>Indonesia</b> · %{x}<br>%{y:,.1f}" + stn + "<extra></extra>"),
            ])
            fig.update_layout(barmode="group", bargroupgap=0.08)
            fig.update_yaxes(range=[0, max(mv + wv) * 1.22])
            fig.update_traces(textfont=dict(color=TEKS, size=13))
            tampil(_gaya(fig, nama[indikator], "Member FitZone dibanding penduduk dewasa Indonesia",
                         legend=True, ylabel=nama[indikator] + (" (%)" if stn else "")))
            kalimat = []
            for g, m_, w_ in zip(gx, mv, wv):
                arah = "lebih tinggi" if m_ > w_ else "lebih rendah"
                kalimat.append(f"{g.lower()} {n(m_, 1)}{stn} terhadap {n(w_, 1)}{stn}, "
                               f"{n(abs(m_ - w_), 1)} poin {arah}")
            kotak("artinya", "Member FitZone dibanding penduduk Indonesia: " + "; ".join(kalimat) + ".")
            if indikator in ("obesity_pct", "overweight_pct", "mean_bmi"):
                kotak("saran", "Angka BMI member laki-laki yang tinggi lebih banyak dipengaruhi massa otot. "
                               "Persentase lemak tubuh tetap menjadi KPI utama, sedangkan angka WHO dipakai "
                               "sebagai konteks.")
        with st.expander("Lihat tabel angka"):
            st.dataframe(sub.assign(gender=gx)[["gender", "n_member", "member_value", "who_value", "who_low",
                                                "who_high", "selisih_member_minus_who"]],
                         hide_index=True, column_config={
                             "gender": "Jenis kelamin", "n_member": "Jumlah member", "member_value": "Member",
                             "who_value": "Indonesia (WHO)", "who_low": "Batas bawah WHO",
                             "who_high": "Batas atas WHO", "selisih_member_minus_who": "Selisih"})

    bagian("Posisi Indonesia di antara negara lain")
    ct_all = db.query("SELECT * FROM dw.mart_who_country_latest")
    if ct_all.empty:
        st.info("Data negara WHO belum tersedia.")
        st.stop()
    c1, c2 = st.columns(2)
    ind_who = c1.selectbox("Indikator WHO", sorted(ct_all.indicator_name.unique()), key="who_ind",
                           format_func=lambda x: nama.get(x, x))
    jk = c2.selectbox("Jenis kelamin", sorted(ct_all.gender.unique()), key="who_jk",
                      format_func=lambda g: GENDER_ID.get(g, g))
    stn2 = satuan_ind.get(ind_who, "%")
    ct = ct_all[(ct_all.indicator_name == ind_who) & (ct_all.gender == jk)].copy()
    if ct.empty:
        st.info("Data negara untuk kombinasi ini tidak tersedia.")
    else:
        ct["value"] = ct["value"].astype(float)
        ct = ct.sort_values("value", ascending=False).reset_index(drop=True)
        idn = ct[ct.country_code == "IDN"]
        median = float(ct.value.median())
        if not idn.empty:
            rank = idn.index[0] + 1
            vi = float(idn.value.iloc[0])
            kpi([
                ("", "Peringkat Indonesia", f"{rank} dari {len(ct)}", "peringkat 1 = angka tertinggi di dunia", BIRU),
                ("", "Angka Indonesia", f"{n(vi, 1)}{stn2}", f"data tahun {int(idn.year.iloc[0])}", ORANYE),
                ("", "Nilai tengah dunia", f"{n(median, 1)}{stn2}", "median seluruh negara", ABU_TUA),
            ])
        top = pd.concat([ct.head(10), idn]).drop_duplicates("country_code")
        warna = [ORANYE if c == "IDN" else ABU for c in top.country_code]
        with st.container(border=True):
            fig = go.Figure(go.Bar(
                y=top.country_name, x=top.value, orientation="h", marker_color=warna,
                text=[f"{n(v, 1)}{stn2}" for v in top.value], textposition="outside", cliponaxis=False,
                textfont=dict(color=TEKS), hovertemplate="<b>%{y}</b><br>%{x:,.1f}" + stn2 + "<extra></extra>"))
            fig.add_vline(x=median, line_dash="dot", line_color=TEKS2, annotation_text="nilai tengah dunia",
                          annotation_position="top", annotation_font=dict(color=TEKS2, size=11))
            fig.update_yaxes(autorange="reversed", showgrid=False)
            fig.update_xaxes(showgrid=True, gridcolor=GRID, range=[0, top.value.max() * 1.18])
            tampil(_gaya(fig, f"{nama.get(ind_who, ind_who)}: 10 negara tertinggi dan Indonesia "
                              f"({GENDER_ID.get(jk, jk)})",
                         "Garis titik-titik = nilai tengah seluruh negara", tinggi=460))
            if not idn.empty:
                posisi = ("di atas" if vi > median else "di bawah") if abs(vi - median) > 0.05 else "sama dengan"
                kotak("artinya", f"Indonesia berada di peringkat {rank} dari {len(ct)} negara dengan nilai "
                                 f"{n(vi, 1)}{stn2}, {posisi} nilai tengah dunia ({n(median, 1)}{stn2}).")

elif halaman == "Prediksi Lemak Tubuh (ML)":
    hero("Prediksi Lemak Tubuh (ML)", "Seberapa akurat model memperkirakan persentase lemak tubuh member?",
         "Model memperkirakan persentase lemak tubuh dari data latihan member, seperti lama sesi, level "
         "pengalaman, dan berat badan. Member yang lemak tubuhnya jauh di atas perkiraan menjadi prioritas "
         "pendampingan trainer.")
    ev = db.query("SELECT * FROM dw.mart_ml_evaluasi ORDER BY test_mae")
    if ev.empty or pred.empty:
        st.warning("Belum ada hasil model. Jalankan tugas train_model di Airflow terlebih dahulu.")
    else:
        for c in ("test_mae", "test_rmse", "test_r2", "cv_mae_mean", "cv_r2_mean", "mae_lebih_baik_pct",
                  "train_sec"):
            ev[c] = pd.to_numeric(ev[c], errors="coerce")
        champ = ev[ev.is_champion].iloc[0]
        base = ev[ev.model_role == "baseline"].iloc[0]
        nama_model = {"linear_regression": "Linear Regression (baseline)", "random_forest": "Random Forest",
                      "gradient_boosting": "Gradient Boosting"}
        nm_champ = nama_model.get(champ.model_name, champ.model_name)
        uji = pr[pr.split == "uji"].copy()
        for c in ("fat_actual", "fat_predicted", "residual"):
            if c in uji:
                uji[c] = uji[c].astype(float)
        tepat = 100 * (uji.residual.abs() < 3).mean() if not uji.empty else float("nan")
        kpi([
            ("", "Model terpilih", nm_champ, "MAE validasi silang paling kecil", BIRU),
            ("", "Rata-rata selisih (MAE)", f"{n(champ.test_mae, 2)} poin",
             f"baseline {n(base.test_mae, 2)} poin", AQUA),
            ("", "Variasi yang dijelaskan (R²)", pct(100 * champ.test_r2, 1),
             f"baseline {pct(100 * base.test_r2, 1)}", BIRU),
            ("", "Di atas perkiraan", n((uji.residual >= 3).sum()) if not uji.empty else "-",
             f"dari {n(len(uji))} member uji, lemak lebih dari 3 poin di atas perkiraan", ORANYE),
        ])
        kotak("artinya", f"{nm_champ} menghasilkan MAE {n(champ.test_mae, 2)} poin, "
                         f"{n(champ.mae_lebih_baik_pct, 1)}% lebih baik dari baseline Linear Regression. "
                         f"Sebanyak {pct(tepat, 0)} prediksi pada data uji meleset kurang dari 3 poin.")
        bagian("Perbandingan model")
        a, b = st.columns(2)
        with a, st.container(border=True):
            s = ev.set_index(ev.model_name.map(lambda m: nama_model.get(m, m))).test_mae.sort_values()
            tampil(batang(s, "MAE tiap model", "Rata-rata selisih prediksi; makin kecil makin baik",
                          sorot=nm_champ, des=2, satuan=" poin", horizontal=True, tinggi=300))
        with b, st.container(border=True):
            s = ev.set_index(ev.model_name.map(lambda m: nama_model.get(m, m))).test_r2.sort_values(
                ascending=False) * 100
            tampil(batang(s, "R² tiap model", "Porsi variasi lemak tubuh yang dijelaskan model; makin besar makin baik",
                          sorot=nm_champ, des=1, satuan="%", horizontal=True, tinggi=300))
        with st.expander("Lihat tabel evaluasi lengkap"):
            tab = ev[["model_name", "model_role", "cv_mae_mean", "cv_r2_mean", "test_mae", "test_rmse", "test_r2",
                      "mae_lebih_baik_pct", "train_sec", "is_champion"]].copy()
            tab["model_name"] = tab.model_name.map(lambda m: nama_model.get(m, m))
            st.dataframe(tab, hide_index=True, column_config={
                "model_name": "Model", "model_role": "Peran", "cv_mae_mean": "MAE validasi silang",
                "cv_r2_mean": "R² validasi silang", "test_mae": "MAE uji", "test_rmse": "RMSE uji",
                "test_r2": "R² uji", "mae_lebih_baik_pct": "Lebih baik dari baseline (%)",
                "train_sec": "Waktu latih (detik)", "is_champion": "Terpilih"})
        if uji.empty:
            st.info("Tidak ada data uji pada filter ini.")
        else:
            bagian(f"Hasil prediksi pada {n(len(uji))} member data uji")
            c, d = st.columns(2)
            warna_status = {"Sesuai perkiraan": BIRU, "Di atas perkiraan": ORANYE, "Di bawah perkiraan": AQUA}
            with c, st.container(border=True):
                fig = go.Figure()
                lo = float(min(uji.fat_actual.min(), uji.fat_predicted.min())) - 1
                hi = float(max(uji.fat_actual.max(), uji.fat_predicted.max())) + 1
                fig.add_trace(go.Scatter(x=[lo, hi, hi, lo], y=[lo - 3, hi - 3, hi + 3, lo + 3], fill="toself",
                                         fillcolor="rgba(42,120,214,0.07)", line=dict(width=0), mode="lines",
                                         showlegend=False, hoverinfo="skip"))
                fig.add_trace(go.Scatter(x=[lo, hi], y=[lo, hi], mode="lines", name="Prediksi tepat",
                                         line=dict(color=ABU_TUA, dash="dot", width=1.5), hoverinfo="skip"))
                for status, w in warna_status.items():
                    g = uji[uji.status_prediksi == status]
                    if g.empty:
                        continue
                    fig.add_trace(go.Scatter(
                        x=g.fat_actual, y=g.fat_predicted, mode="markers", name=f"{status} ({len(g)})",
                        marker=dict(color=w, size=9, opacity=0.85, line=dict(color="white", width=1.5)),
                        customdata=g[["member_key", "gender", "workout_type", "residual"]].values,
                        hovertemplate="<b>Member %{customdata[0]}</b> (%{customdata[1]}, %{customdata[2]})<br>"
                                      "Aktual %{x:.1f}% · prediksi %{y:.1f}%<br>"
                                      "Selisih %{customdata[3]:+.1f} poin<extra></extra>"))
                tampil(_gaya(fig, "Lemak tubuh aktual dan prediksi",
                             "Satu titik mewakili satu member; pita biru menandai selisih kurang dari 3 poin",
                             xlabel="Lemak tubuh aktual (%)", ylabel="Prediksi (%)", tinggi=450, legend=True))
            with d, st.container(border=True):
                fig = go.Figure()
                res = uji.residual
                for nm_, mask, w in [("Di bawah perkiraan", res <= -3, AQUA),
                                     ("Sesuai perkiraan", (res > -3) & (res < 3), BIRU),
                                     ("Di atas perkiraan", res >= 3, ORANYE)]:
                    fig.add_trace(go.Histogram(x=res[mask], name=f"{nm_} ({int(mask.sum())})", marker_color=w,
                                               xbins=dict(start=np.floor(res.min()), end=np.ceil(res.max()),
                                                          size=1),
                                               hovertemplate="Selisih %{x} poin: %{y} member<extra></extra>"))
                fig.update_layout(barmode="overlay", bargap=0.08)
                for x in (-3, 3):
                    fig.add_vline(x=x, line_dash="dot", line_color=ABU_TUA)
                fig.add_annotation(x=0, y=1.02, yref="paper", text="sesuai perkiraan", showarrow=False,
                                   font=dict(color=BIRU, size=11))
                tampil(_gaya(fig, "Sebaran selisih prediksi",
                             "Selisih = lemak aktual dikurangi prediksi",
                             xlabel="Selisih (poin %)", ylabel="Jumlah member", tinggi=450, legend=True))
                atas = int((res >= 3).sum())
                kotak("artinya", f"{n(atas)} dari {n(len(uji))} member uji ({pct(100 * atas / len(uji))}) memiliki "
                                 "lemak tubuh lebih dari 3 poin di atas perkiraan. Hasil member tersebut lebih buruk "
                                 "dari yang wajar untuk kebiasaan latihannya.")
            fi = champ.feature_importance
            if isinstance(fi, dict) and fi:
                label = {"session_duration_hours": "Lama sesi", "experience_level": "Level pengalaman",
                         "gender_Male": "Jenis kelamin", "weight_kg": "Berat badan",
                         "water_intake_liters": "Asupan air", "max_bpm": "Detak jantung maks",
                         "avg_bpm": "Detak jantung rata-rata", "age": "Usia", "height_m": "Tinggi badan",
                         "resting_bpm": "Detak jantung istirahat", "calories_burned": "Kalori",
                         "workout_frequency_days_week": "Frekuensi latihan"}
                s = pd.Series(fi).astype(float).sort_values(ascending=False)
                total = s.sum()
                s = (s.head(8) / total * 100)
                s.index = [label.get(i, i.replace("workout_type_", "Jenis: ")) for i in s.index]
                with st.container(border=True):
                    tampil(batang(s, "Feature importance model terpilih",
                                  "Persentase kontribusi tiap fitur terhadap prediksi",
                                  sorot=list(s.index[:3]), des=1, satuan="%", horizontal=True, tinggi=360))
                    kotak("artinya", f"{s.index[0]}, {s.index[1].lower()}, dan {s.index[2].lower()} menyumbang "
                                     f"{pct(s.iloc[:3].sum(), 0)} kontribusi. Fitur-fitur ini saling berkorelasi, "
                                     "sehingga tidak dapat dibaca sebagai hubungan sebab-akibat.")
            bagian("Daftar prioritas pendampingan trainer")
            prio = uji[uji.residual >= 3].sort_values("residual", ascending=False)
            kotak("saran", "Trainer memakai daftar member berstatus Di atas perkiraan setiap minggu untuk "
                           "konsultasi prioritas, misalnya terkait pola makan dan teknik latihan.")
            prio = prio.assign(gender=prio.gender.map(lambda g: GENDER_ID.get(g, g)))
            st.dataframe(prio[["member_key", "gender", "age_group", "experience_name", "workout_type",
                               "fat_actual", "fat_predicted", "residual"]], hide_index=True, column_config={
                "member_key": "Member", "gender": "Jenis kelamin", "age_group": "Kelompok usia",
                "experience_name": "Level", "workout_type": "Jenis latihan",
                "fat_actual": st.column_config.NumberColumn("Lemak aktual", format="%.1f%%"),
                "fat_predicted": st.column_config.NumberColumn("Prediksi", format="%.1f%%"),
                "residual": st.column_config.NumberColumn("Selisih (poin)", format="%+.1f")})

else:  # Kualitas Data & ETL
    hero("Kualitas Data & ETL", "Apakah data yang tampil di dashboard sudah tervalidasi dan terbaru?",
         "Pipeline ETL dijalankan Apache Airflow untuk mengambil data CSV member dan API WHO, memvalidasi, "
         "lalu memuatnya ke data warehouse. Halaman ini memantau hasil setiap batch dan backup harian.")
    etl = db.query("SELECT * FROM etl_audit.v_ringkasan_etl ORDER BY batch_id DESC, started_at DESC")
    if etl.empty:
        st.info("Belum ada riwayat ETL.")
    else:
        sukses = int((etl.status == "SUCCESS").sum())
        gagal = int((etl.status == "FAILED").sum())
        tolak = int(pd.to_numeric(etl.rows_rejected).fillna(0).sum())
        kpi([
            ("", "Total proses", n(len(etl)), "batch yang tercatat di etl_log", BIRU),
            ("", "Tingkat keberhasilan", pct(100 * sukses / len(etl), 0), f"{n(sukses)} proses berhasil", AQUA),
            ("", "Proses gagal", n(gagal), "dicoba ulang otomatis hingga 3 kali", ORANYE),
            ("", "Baris data ditolak", n(tolak), "tidak lolos validasi, disimpan di etl_reject", ABU_TUA),
        ])
        if gagal:
            g = etl[etl.status == "FAILED"].iloc[0]
            kotak("awas", f"Batch gagal terakhir berasal dari sumber {g.source_name} pada tahap {g.stage}. "
                          f"Pesan: {str(g.error_message)[:160]}. Data warehouse tetap memakai data valid terakhir.")
        a, b = st.columns(2)
        status_id = {"SUCCESS": "Berhasil", "FAILED": "Gagal", "RUNNING": "Berjalan"}
        with a, st.container(border=True):
            s = etl.status.value_counts()
            s.index = [status_id.get(i, i) for i in s.index]
            tampil(batang(s, "Hasil proses ETL", "Jumlah proses menurut status",
                          warna_per={"Berhasil": AQUA, "Gagal": ORANYE, "Berjalan": BIRU},
                          ylabel="Jumlah proses", satuan=" proses"))
        with b, st.container(border=True):
            sumber_id = {"gym_csv": "CSV member gym", "who_gho_api": "API WHO", "ml_fat_model": "Model ML"}
            t = etl.groupby("source_name").rows_loaded.max().fillna(0).astype(float)
            t.index = [sumber_id.get(i, i) for i in t.index]
            tampil(batang(t, "Jumlah baris data yang dimuat per sumber", "Proses terbesar tiap sumber",
                          horizontal=True, tinggi=300, satuan=" baris"))
        with st.expander("Lihat riwayat 40 proses terbaru"):
            st.dataframe(etl[["batch_id", "source_name", "stage", "status", "rows_read", "rows_loaded",
                              "rows_rejected", "duration_sec", "started_at", "error_message"]].head(40),
                         hide_index=True, column_config={
                             "batch_id": "Batch", "source_name": "Sumber", "stage": "Tahap", "status": "Status",
                             "rows_read": "Baris dibaca", "rows_loaded": "Baris dimuat",
                             "rows_rejected": "Baris ditolak", "duration_sec": "Durasi (detik)",
                             "started_at": "Mulai", "error_message": "Pesan error"})
    dur = db.query("SELECT * FROM etl_audit.v_durasi_tahap ORDER BY batch_id DESC LIMIT 20")
    if not dur.empty:
        d = dur.sort_values("batch_id")
        idx = "Batch " + d.batch_id.astype(str) + "<br>" + d.source_name
        tahap = [("ingest_sec", "Ambil data", BIRU), ("stage_sec", "Staging", ORANYE),
                 ("transform_sec", "Pembersihan", AQUA), ("load_sec", "Muat ke gudang data", KUNING),
                 ("ml_sec", "Latih model", MERAH_MUDA)]
        with st.container(border=True):
            fig = go.Figure()
            for kol, nm_, w in tahap:
                fig.add_trace(go.Bar(name=nm_, x=idx.tolist(), y=pd.to_numeric(d[kol]).fillna(0).tolist(),
                                     marker_color=w, marker_line=dict(color=KERTAS, width=1),
                                     hovertemplate="%{x}<br>" + nm_ + ": %{y:.2f} detik<extra></extra>"))
            fig.update_layout(barmode="stack")
            tampil(_gaya(fig, "Waktu yang dibutuhkan tiap proses", "Dalam detik, dipecah per tahap",
                         ylabel="Detik", tinggi=420, legend=True))
            total = d[[t[0] for t in tahap]].apply(pd.to_numeric).fillna(0).sum(axis=1)
            kotak("artinya", f"Batch terlama selesai dalam {n(total.max(), 1)} detik.")
    bagian("Backup harian dan uji restore")
    try:
        bk = db.query("SELECT folder, started_at, status, db_dump_mb, raw_archive_mb, n_tables, total_rows, "
                      "restore_status, restore_sec, deleted_old, notes FROM etl_audit.backup_log "
                      "ORDER BY started_at DESC LIMIT 20")
    except Exception:
        bk = pd.DataFrame()
    if bk.empty:
        st.info("Belum ada riwayat backup. Jalankan DAG fitzone_backup_daily di Airflow.")
    else:
        t = bk.iloc[0]
        nilai = lambda v, dflt=0: dflt if pd.isna(v) else v
        ok_bk = str(t.status) == "SUCCESS"
        rs = str(nilai(t.restore_status, "-"))
        ok_rs = rs == "LULUS"
        kpi([
            ("", "Backup terakhir", str(t.started_at)[:16], "terjadwal setiap pukul 01.00", BIRU),
            ("", "Status backup", status_id.get(str(t.status), str(t.status)),
             f"{n(nilai(t.n_tables))} tabel, {n(nilai(t.total_rows))} baris", AQUA if ok_bk else ORANYE),
            ("", "Uji restore", "Lulus" if ok_rs else ("Gagal" if rs == "GAGAL" else rs),
             f"restore selesai dalam {n(float(nilai(t.restore_sec)), 1)} detik" if ok_rs
             else "restore percobaan belum berhasil", AQUA if ok_rs else ORANYE),
            ("", "Ukuran backup", f"{n(float(nilai(t.db_dump_mb)) + float(nilai(t.raw_archive_mb)), 1)} MB",
             "database + arsip data mentah", ABU_TUA),
        ])
        if ok_bk and ok_rs:
            kotak("artinya", "Backup database dan data mentah dibuat setiap pukul 01.00, lalu diuji dengan "
                             "restore ke database percobaan.")
        else:
            kotak("awas", "Backup atau uji restore terakhir gagal. Catatan: "
                          f"{str(nilai(t.notes, '-'))[:200]}. Periksa log DAG fitzone_backup_daily di Airflow.")
        with st.expander("Lihat riwayat backup"):
            st.dataframe(bk, hide_index=True)

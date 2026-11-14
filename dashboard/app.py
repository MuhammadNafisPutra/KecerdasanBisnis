"""Dashboard BI PT FitZone Nusantara. Membaca hanya data mart di PostgreSQL (role dashboard_ro).
Grafik memakai Plotly (interaktif: hover, zoom, geser, unduh PNG)."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import db

st.set_page_config(page_title="FitZone BI", page_icon="🏋️", layout="wide")

WARNA = "#1f6f8b"
WARNA2 = "#e07a1f"
WARNA3 = "#8a8a8a"
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


def _rapikan(fig, judul, xlabel="", ylabel="", tinggi=340):
    fig.update_layout(
        title=dict(text=judul, font=dict(size=14), x=0),
        xaxis_title=xlabel, yaxis_title=ylabel, height=tinggi,
        margin=dict(l=10, r=10, t=50, b=10), hovermode="closest",
    )
    return fig


def fig_bar(series: pd.Series, judul: str, xlabel: str = "", ylabel: str = "", horizontal=False,
            warna=WARNA, fmt=".0f"):
    """Grafik batang interaktif. fmt memakai format d3, contoh '.0f' atau '.1f'."""
    fmt = fmt.replace("{:", "").replace("}", "")  # terima gaya lama '{:.1f}'
    x = [str(i) for i in series.index]
    y = [float(v) for v in series.values]
    if horizontal:
        fig = go.Figure(go.Bar(y=x, x=y, orientation="h", marker_color=warna, text=y,
                               texttemplate="%{text:" + fmt + "}", textposition="outside",
                               hovertemplate="%{y}: %{x:" + fmt + "}<extra></extra>"))
        fig.update_yaxes(autorange="reversed")
    else:
        fig = go.Figure(go.Bar(x=x, y=y, marker_color=warna, text=y,
                               texttemplate="%{text:" + fmt + "}", textposition="outside",
                               hovertemplate="%{x}: %{y:" + fmt + "}<extra></extra>"))
    fig.update_traces(cliponaxis=False)
    return _rapikan(fig, judul, xlabel, ylabel)


def tampil(fig):
    st.plotly_chart(fig, config={"displaylogo": False})


def terapkan_filter(df: pd.DataFrame, pilihan: dict) -> pd.DataFrame:
    for kolom, nilai in pilihan.items():
        if nilai and kolom in df.columns:
            df = df[df[kolom].isin(nilai)]
    return df


# ---------------------------------------------------------------- sidebar
ok, pesan = db.tersedia()
if not ok:
    st.error("Dashboard tidak dapat terhubung ke data warehouse. Pastikan container postgres berjalan "
             "dan DASHBOARD_PASSWORD di file .env benar.")
    st.caption(f"Detail: {pesan}")
    st.stop()

st.sidebar.title("FitZone BI")
halaman = st.sidebar.radio("Halaman", HALAMAN)

retensi = db.query("SELECT * FROM dw.mart_retensi_pemula")
program = db.query("SELECT * FROM dw.mart_program_pemasaran")
pred = db.query("SELECT * FROM dw.mart_ml_prediksi_lemak")

st.sidebar.markdown("---")
st.sidebar.subheader("Filter (data member)")
pilihan = {}
for label, kolom in FILTER_KOLOM.items():
    sumber = retensi if kolom in retensi.columns else program
    opsi = sorted(sumber[kolom].dropna().unique().tolist())
    pilihan[kolom] = st.sidebar.multiselect(label, opsi)
if st.sidebar.button("Muat ulang data"):
    st.cache_data.clear()
    st.rerun()
st.sidebar.caption("Data di-cache 1 jam. Filter berlaku untuk halaman data member; "
                   "halaman WHO dan ETL tidak terpengaruh.")

r = terapkan_filter(retensi, pilihan)
p = terapkan_filter(program, pilihan)
pr = terapkan_filter(pred, pilihan)


def kosong() -> bool:
    if r.empty:
        st.warning("Tidak ada member yang sesuai dengan filter. Kurangi pilihan filter di sisi kiri.")
        return True
    return False


# ---------------------------------------------------------------- halaman
if halaman == "Ringkasan Eksekutif":
    st.title("Ringkasan Eksekutif")
    st.caption("Gambaran member PT FitZone Nusantara dari data warehouse (data simulasi Kaggle, bukan data member asli).")
    if not kosong():
        k = st.columns(5)
        k[0].metric("Jumlah member", f"{len(r):,}")
        k[1].metric("Rata-rata lemak tubuh", f"{r.fat_percentage.mean():.1f}%")
        k[2].metric("Rata-rata kalori / sesi", f"{r.calories_burned.mean():,.0f}")
        k[3].metric("Rata-rata frekuensi", f"{r.workout_frequency_days_week.mean():.1f} hari/minggu")
        k[4].metric("Member BMI ≥ 30", f"{100 * (r.bmi >= 30).mean():.1f}%")
        a, b = st.columns(2)
        with a:
            urut = r.groupby(["bmi_category", "bmi_category_order"]).size().reset_index(name="n") \
                    .sort_values("bmi_category_order").set_index("bmi_category")["n"]
            tampil(fig_bar(urut, "Member per kategori BMI", ylabel="Jumlah member"))
        with b:
            tampil(fig_bar(r.age_group.value_counts().sort_index(), "Member per kelompok usia",
                           ylabel="Jumlah member", warna=WARNA2))
        c, d = st.columns(2)
        with c:
            tampil(fig_bar(r.workout_type.value_counts(), "Member per jenis latihan", ylabel="Jumlah member"))
        with d:
            tampil(fig_bar(r.gender.value_counts(), "Member per jenis kelamin", ylabel="Jumlah member",
                           warna=WARNA3))

elif halaman == "Retensi & Pemula":
    st.title("Retensi & Pemula")
    st.caption("Tidak ada kolom tanggal atau status berhenti pada data, sehingga retensi diukur lewat "
               "keteraturan latihan (≥ 3 hari/minggu) dan level pengalaman, bukan churn.")
    if not kosong():
        pemula = r[r.experience_level == 1]
        k = st.columns(4)
        k[0].metric("Member pemula", f"{len(pemula):,}", f"{100 * len(pemula) / len(r):.1f}% dari total")
        k[1].metric("Rutin ≥ 3x/minggu (semua)", f"{100 * r.is_rutin_3x.mean():.1f}%")
        k[2].metric("Rutin ≥ 3x/minggu (pemula)",
                    f"{100 * pemula.is_rutin_3x.mean():.1f}%" if len(pemula) else "-")
        k[3].metric("Menit latihan/minggu (rata-rata)", f"{r.weekly_minutes.mean():,.0f}")
        a, b = st.columns(2)
        with a:
            s = r.groupby("experience_name").is_rutin_3x.mean().mul(100)
            tampil(fig_bar(s, "% member rutin (≥ 3x/minggu) per level", ylabel="%", fmt="{:.1f}"))
        with b:
            tampil(fig_bar(r.experience_name.value_counts().sort_index(), "Member per level pengalaman",
                           ylabel="Jumlah member", warna=WARNA2))
        c, d = st.columns(2)
        with c:
            fig = go.Figure(go.Histogram(x=r.weekly_minutes.astype(float), nbinsx=20, marker_color=WARNA,
                                         hovertemplate="%{x} menit: %{y} member<extra></extra>"))
            fig.add_vline(x=150, line_dash="dash", line_color=WARNA2, annotation_text="Batas WHO 150 menit")
            _rapikan(fig, "Sebaran menit latihan per minggu", "Menit/minggu", "Jumlah member")
            tampil(fig)
        with d:
            s = r.groupby("workout_frequency_days_week").size()
            tampil(fig_bar(s, "Member per frekuensi latihan", xlabel="Hari/minggu", ylabel="Jumlah member",
                           warna=WARNA3))

elif halaman == "Program & Pemasaran":
    st.title("Program & Pemasaran")
    if p.empty:
        st.warning("Tidak ada member yang sesuai dengan filter.")
    else:
        k = st.columns(3)
        k[0].metric("Kalori per jam (rata-rata)", f"{p.calories_per_hour.mean():,.0f}")
        top = p.groupby("workout_type").calories_per_hour.mean().sort_values(ascending=False)
        k[1].metric("Jenis latihan paling boros kalori", top.index[0], f"{top.iloc[0]:,.0f} kal/jam")
        k[2].metric("Lemak tubuh rata-rata", f"{p.fat_percentage.mean():.1f}%")
        a, b = st.columns(2)
        with a:
            tampil(fig_bar(top, "Kalori per jam menurut jenis latihan", ylabel="Kalori/jam"))
        with b:
            urut = ["< 1 jam", "1 - 1,5 jam", "> 1,5 jam"]
            s = p.groupby("duration_group").calories_burned.mean().reindex(urut).dropna()
            tampil(fig_bar(s, "Rata-rata kalori per sesi menurut lama sesi", ylabel="Kalori", warna=WARNA2))
        c, d = st.columns(2)
        with c:
            s = p.groupby("workout_type").fat_percentage.mean().sort_values()
            tampil(fig_bar(s, "Rata-rata lemak tubuh per jenis latihan (%)", ylabel="%", fmt="{:.1f}",
                           warna=WARNA3))
        with d:
            s = p.groupby("workout_type").size().sort_values(ascending=False)
            tampil(fig_bar(s, "Peminat per jenis latihan", ylabel="Jumlah member"))
        st.subheader("Ringkasan per jenis latihan")
        tabel = p.groupby("workout_type").agg(
            member=("member_key", "count"),
            kalori_per_jam=("calories_per_hour", "mean"),
            durasi_jam=("session_duration_hours", "mean"),
            frekuensi=("workout_frequency_days_week", "mean"),
            lemak_pct=("fat_percentage", "mean"),
        ).round(2).sort_values("kalori_per_jam", ascending=False)
        st.dataframe(tabel)

elif halaman == "Benchmark WHO":
    st.title("Benchmark WHO")
    st.caption("Member dibandingkan dengan angka Indonesia pada tahun WHO terbaru. Kurang aktif fisik pada "
               "member adalah perkiraan karena hanya menghitung latihan di gym.")
    bm = db.query("SELECT * FROM dw.mart_benchmark_who ORDER BY indicator_name, gender")
    nama = {"obesity_pct": "Obesitas (BMI ≥ 30), %", "overweight_pct": "Kelebihan berat (BMI ≥ 25), %",
            "mean_bmi": "Rata-rata BMI", "insufficient_activity_pct": "Kurang aktif fisik, %"}
    indikator = st.selectbox("Indikator", list(nama), format_func=lambda x: nama[x])
    sub = bm[bm.indicator_name == indikator].dropna(subset=["who_value"])
    if sub.empty:
        st.info("Belum ada data WHO untuk indikator ini.")
    else:
        fig = go.Figure([
            go.Bar(name="Member FitZone", x=sub.gender.tolist(), y=sub.member_value.astype(float).tolist(),
                   marker_color=WARNA, text=sub.member_value.astype(float).tolist(), texttemplate="%{text:.1f}"),
            go.Bar(name="Indonesia (WHO)", x=sub.gender.tolist(), y=sub.who_value.astype(float).tolist(),
                   marker_color=WARNA2, text=sub.who_value.astype(float).tolist(), texttemplate="%{text:.1f}"),
        ])
        fig.update_layout(barmode="group", legend=dict(orientation="h", y=-0.15))
        _rapikan(fig, nama[indikator])
        tampil(fig)
        st.dataframe(sub[["gender", "n_member", "member_value", "who_year", "who_value", "who_low", "who_high",
                          "selisih_member_minus_who"]], hide_index=True)
    st.subheader("Indonesia dibanding negara lain (WHO, tahun terbaru)")
    ct_all = db.query("SELECT * FROM dw.mart_who_country_latest")
    if ct_all.empty:
        st.info("Data negara WHO belum tersedia.")
        st.stop()
    ind_who = st.selectbox("Indikator WHO", sorted(ct_all.indicator_name.unique()), key="who_ind",
                           format_func=lambda x: nama.get(x, x))
    jk = st.selectbox("Jenis kelamin", sorted(ct_all.gender.unique()), key="who_jk")
    ct = ct_all[(ct_all.indicator_name == ind_who) & (ct_all.gender == jk)]
    pilih = jk
    if ct.empty:
        st.info("Data negara untuk kombinasi ini tidak tersedia.")
    else:
        ct = ct.sort_values("value", ascending=False).reset_index(drop=True)
        idn = ct[ct.country_code == "IDN"]
        if not idn.empty:
            st.metric("Peringkat Indonesia (1 = nilai tertinggi)", f"{idn.index[0] + 1} dari {len(ct)} negara",
                      f"{idn.value.iloc[0]:.2f} ({int(idn.year.iloc[0])})")
        top = pd.concat([ct.head(8), idn]).drop_duplicates("country_code")
        fig = fig_bar(top.set_index("country_name").value.astype(float), f"Negara teratas dan Indonesia ({pilih})",
                      horizontal=True, fmt="{:.1f}")
        tampil(fig)

elif halaman == "Prediksi Lemak Tubuh (ML)":
    st.title("Prediksi Lemak Tubuh (ML)")
    ev = db.query("SELECT * FROM dw.mart_ml_evaluasi ORDER BY test_mae")
    if ev.empty or pred.empty:
        st.warning("Belum ada hasil model. Jalankan tugas train_model di Airflow terlebih dahulu.")
    else:
        champ = ev[ev.is_champion].iloc[0]
        base = ev[ev.model_role == "baseline"].iloc[0]
        st.caption(f"Model terpilih: {champ.model_name}. Dipilih karena galat rata-rata (MAE) validasi silang "
                   "paling kecil. Model ini memperkirakan persentase lemak tubuh member, bukan churn.")
        k = st.columns(4)
        k[0].metric("Model terpilih", champ.model_name)
        k[1].metric("MAE uji", f"{champ.test_mae:.2f} poin %", f"{champ.mae_lebih_baik_pct:.1f}% lebih baik dari baseline")
        k[2].metric("R² uji", f"{champ.test_r2:.3f}", f"baseline {base.test_r2:.3f}")
        k[3].metric("RMSE uji", f"{champ.test_rmse:.2f}")
        st.subheader("Perbandingan model: baseline → perbaikan → terpilih")
        tab = ev[["model_name", "model_role", "cv_mae_mean", "cv_r2_mean", "test_mae", "test_rmse", "test_r2",
                  "mae_lebih_baik_pct", "train_sec", "is_champion"]].rename(columns={
            "model_name": "Model", "model_role": "Peran", "cv_mae_mean": "MAE CV", "cv_r2_mean": "R² CV",
            "test_mae": "MAE uji", "test_rmse": "RMSE uji", "test_r2": "R² uji",
            "mae_lebih_baik_pct": "MAE lebih baik (%)", "train_sec": "Waktu latih (dtk)", "is_champion": "Terpilih"})
        st.dataframe(tab, hide_index=True)
        st.caption("MAE = rata-rata selisih mutlak prediksi dan nilai asli (poin persen lemak). RMSE menghukum "
                   "selisih besar lebih berat. R² = porsi variasi yang dijelaskan model (1 = sempurna, 0 = sama "
                   "dengan menebak rata-rata).")
        uji = pr[pr.split == "uji"]
        if uji.empty:
            st.info("Tidak ada data uji pada filter ini.")
        else:
            a, b = st.columns(2)
            with a:
                lo = float(min(uji.fat_actual.min(), uji.fat_predicted.min()))
                hi = float(max(uji.fat_actual.max(), uji.fat_predicted.max()))
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=uji.fat_actual.astype(float), y=uji.fat_predicted.astype(float), mode="markers",
                    marker=dict(color=WARNA, size=7, opacity=0.7), name="Member uji",
                    customdata=uji[["member_key", "workout_type", "gender", "residual"]].values,
                    hovertemplate="Member %{customdata[0]} (%{customdata[2]}, %{customdata[1]})<br>"
                                  "Aktual %{x:.1f}% | Prediksi %{y:.1f}%<br>Selisih %{customdata[3]:.1f}"
                                  "<extra></extra>"))
                fig.add_trace(go.Scatter(x=[lo, hi], y=[lo, hi], mode="lines", name="Prediksi sempurna",
                                         line=dict(color=WARNA2, dash="dash")))
                _rapikan(fig, f"Aktual vs prediksi (data uji, n={len(uji)})", "Lemak tubuh aktual (%)",
                         "Lemak tubuh prediksi (%)", tinggi=400)
                tampil(fig)
            with b:
                fig = go.Figure(go.Histogram(x=uji.residual.astype(float), nbinsx=20, marker_color=WARNA3,
                                             hovertemplate="Selisih %{x}: %{y} member<extra></extra>"))
                fig.add_vline(x=0, line_dash="dash", line_color=WARNA2)
                _rapikan(fig, "Sebaran galat prediksi", "Selisih aktual - prediksi (poin %)", "Jumlah member",
                         tinggi=400)
                tampil(fig)
            fi = champ.feature_importance
            if isinstance(fi, dict) and fi:
                s = pd.Series(fi).astype(float).sort_values(ascending=False).head(8)
                tampil(fig_bar(s, "Fitur paling berpengaruh pada model terpilih", horizontal=True,
                               fmt="{:.3f}", warna=WARNA2))
            st.subheader("Status prediksi (ambang ±3 poin %)")
            st.dataframe(uji.status_prediksi.value_counts().rename("member").to_frame(),
                         )
            st.dataframe(uji.assign(selisih=uji.residual.abs()).sort_values("selisih", ascending=False)
                         [["member_key", "gender", "age_group", "workout_type", "fat_actual", "fat_predicted",
                           "residual", "status_prediksi"]].head(15), hide_index=True)

else:  # Kualitas Data & ETL
    st.title("Kualitas Data & ETL")
    etl = db.query("SELECT * FROM etl_audit.v_ringkasan_etl ORDER BY batch_id DESC, started_at DESC")
    if etl.empty:
        st.info("Belum ada riwayat ETL.")
    else:
        k = st.columns(4)
        k[0].metric("Total proses tercatat", f"{len(etl):,}")
        k[1].metric("Berhasil", f"{(etl.status == 'SUCCESS').sum():,}")
        k[2].metric("Gagal", f"{(etl.status == 'FAILED').sum():,}")
        k[3].metric("Baris ditolak (total)", f"{int(etl.rows_rejected.fillna(0).sum()):,}")
        a, b = st.columns(2)
        with a:
            tampil(fig_bar(etl.status.value_counts(), "Proses ETL menurut status", ylabel="Jumlah"))
        with b:
            t = etl.groupby("source_name").rows_loaded.max().fillna(0)
            tampil(fig_bar(t, "Baris termuat terbesar per sumber", ylabel="Baris", warna=WARNA2))
        st.subheader("Riwayat proses terbaru")
        st.dataframe(etl[["batch_id", "source_name", "stage", "status", "rows_read", "rows_loaded",
                          "rows_rejected", "duration_sec", "started_at", "error_message"]].head(40),
                     hide_index=True)
    dur = db.query("SELECT * FROM etl_audit.v_durasi_tahap ORDER BY batch_id DESC LIMIT 20")
    if not dur.empty:
        st.subheader("Durasi per tahap (detik)")
        d = dur.sort_values("batch_id").set_index(dur.sort_values("batch_id").batch_id.astype(str) + " " +
                                                  dur.sort_values("batch_id").source_name)
        fig = go.Figure()
        for kol, warna in [("ingest_sec", WARNA), ("stage_sec", WARNA2), ("transform_sec", WARNA3),
                           ("load_sec", "#5b9a4b"), ("ml_sec", "#8a4fa0")]:
            fig.add_trace(go.Bar(name=kol.replace("_sec", ""), x=d.index.tolist(),
                                 y=d[kol].astype(float).fillna(0).tolist(), marker_color=warna,
                                 hovertemplate="%{x}<br>" + kol.replace("_sec", "") + ": %{y:.2f} dtk<extra></extra>"))
        fig.update_layout(barmode="stack", legend=dict(orientation="h", y=-0.3))
        _rapikan(fig, "Durasi per tahap per proses", "", "Detik", tinggi=380)
        tampil(fig)
    st.subheader("Backup harian dan uji restore")
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
        k = st.columns(4)
        k[0].metric("Backup terakhir", str(t.started_at)[:16])
        k[1].metric("Status", t.status)
        nilai = lambda v, d=0: d if pd.isna(v) else v
        k[2].metric("Uji restore", nilai(t.restore_status, "-"), f"{float(nilai(t.restore_sec)):.1f} detik")
        k[3].metric("Ukuran (DB + raw)",
                    f"{float(nilai(t.db_dump_mb)) + float(nilai(t.raw_archive_mb)):.1f} MB")
        st.dataframe(bk, hide_index=True)

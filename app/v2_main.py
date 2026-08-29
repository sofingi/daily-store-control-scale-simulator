from pathlib import Path
import os
import sys
import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from database import connect, init_db, get_store_id
from service import (
    import_file, merged_daily, rebuild_quality, recompute_full_paid_media_profit,
    period_control_summary, list_sku_mapping_status, list_warehouse_skus,
    save_sku_mapping, delete_sku_mapping, mapping_suggestions,
    bulk_save_sku_mappings, batch_mapping_suggestions,
)
from period_readiness import compute_period_readiness, suggested_guardrails
from engine import Baseline, Guardrails, simulate_scale, choose_daily_action
from auto_readiness import compute_readiness

DB_PATH = Path(os.getenv("DSC_DB_PATH", str(ROOT_DIR / "data" / "daily_store_control.db"))).expanduser()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

st.set_page_config(
    page_title="Daily Store Control",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
.block-container {padding-top: 1.25rem; padding-bottom: 3rem; max-width: 1500px;}
[data-testid="stMetric"] {border:1px solid rgba(128,128,128,.18); padding:12px; border-radius:12px;}
[data-testid="stMetricLabel"] {font-weight:600;}
.status-card {padding:13px 16px;border-radius:12px;border:1px solid rgba(128,128,128,.22);margin:.25rem 0 .75rem 0;}
.muted {color:#777;font-size:.9rem;}
.section-note {padding:9px 12px;border-left:4px solid #7a7a7a;background:rgba(128,128,128,.07);border-radius:6px;}
</style>
""",
    unsafe_allow_html=True,
)

conn = connect(DB_PATH)
init_db(conn)
sid = get_store_id(conn)

SOURCE_LABELS = {
    "BUSINESS_INSIGHT": "Shopee Business Insight",
    "SHOPEE_ORDER": "Shopee Order",
    "SHOPEE_INCOME": "Shopee Income / Penghasilan",
    "BIGSELLER_HPP": "BigSeller Master HPP SKU",
    "SHOPEE_ADS_PRODUCT": "Shopee Product Ads",
    "SHOPEE_ADS_SHOP_PLUS": "Shopee Toko+",
    "SHOPEE_ADS_LIVE": "Shopee Live Ads",
    "BIGSELLER_STORE": "BigSeller Keuntungan Toko (Audit)",
    "BIGSELLER_SKU": "BigSeller Keuntungan SKU Gudang (Audit)",
}
CORE_SOURCES = [
    "BUSINESS_INSIGHT", "SHOPEE_ORDER", "SHOPEE_INCOME", "BIGSELLER_HPP",
    "SHOPEE_ADS_PRODUCT", "SHOPEE_ADS_SHOP_PLUS", "SHOPEE_ADS_LIVE",
]


def rp(x):
    return "—" if x is None or pd.isna(x) else ("Rp{:,.0f}".format(float(x)).replace(",", "."))


def pct(x):
    return "—" if x is None or pd.isna(x) else f"{float(x)*100:.2f}%"


def num(x, digits=2, suffix=""):
    if x is None or pd.isna(x):
        return "—"
    return f"{float(x):,.{digits}f}{suffix}".replace(",", "_").replace(".", ",").replace("_", ".")


def load_guardrails():
    r = conn.execute("SELECT * FROM guardrails WHERE store_id=?", (sid,)).fetchone()
    return dict(r) if r else {}


def save_guardrails(values):
    conn.execute(
        """UPDATE guardrails SET minimum_margin=?,minimum_roas=?,roas_bep=?,minimum_safety_ratio=?,
        maximum_ads_cost_pct=?,recommended_budget=?,hard_budget_limit=?,updated_at=CURRENT_TIMESTAMP WHERE store_id=?""",
        (
            values["minimum_margin"], values["minimum_roas"], values["roas_bep"],
            values["minimum_safety_ratio"], values["maximum_ads_cost_pct"],
            values["recommended_budget"], values["hard_budget_limit"], sid,
        ),
    )
    conn.commit()


def source_coverage():
    q = pd.read_sql_query(
        """SELECT source,COUNT(*) file_count,MAX(imported_at) last_import,MAX(max_date) latest_data_date,
        SUM(CASE WHEN granularity='DAILY' THEN 1 ELSE 0 END) daily_files,
        SUM(CASE WHEN granularity='PERIOD' THEN 1 ELSE 0 END) period_files
        FROM import_batches WHERE store_id=? AND status='IMPORTED' GROUP BY source""",
        conn, params=[sid],
    )
    return q


def profit_daily():
    return pd.read_sql_query(
        "SELECT * FROM daily_control_profit_v16 WHERE store_id=? ORDER BY metric_date",
        conn, params=[sid], parse_dates=["metric_date"],
    )


def quality_daily():
    return pd.read_sql_query(
        "SELECT * FROM daily_data_quality WHERE store_id=? ORDER BY metric_date",
        conn, params=[sid], parse_dates=["metric_date"],
    )


def merged_with_quality():
    df = merged_daily(conn, sid)
    q = quality_daily()
    if not df.empty and not q.empty:
        cols = [c for c in ["metric_date", "overall_status", "confidence_score", "bigseller_status"] if c in q]
        df = df.merge(q[cols], on="metric_date", how="left")
    return df


def build_baseline(df, days):
    req = ["store_gmv", "ads_spend", "ads_sales", "roas", "full_paid_media_control_profit"]
    if df.empty or any(c not in df.columns for c in req):
        return None, pd.DataFrame()
    valid = df.dropna(subset=req).sort_values("metric_date").tail(days)
    if valid.empty:
        return None, valid
    gmv = valid.store_gmv.mean()
    spend = valid.ads_spend.mean()
    sales = valid.ads_sales.mean()
    roas = sales / spend if spend else 0
    profit = valid.full_paid_media_control_profit.mean()
    contribution = (profit + spend) / gmv if gmv else 0
    conf = float(valid.confidence_score.mean()) if "confidence_score" in valid else 100.0
    final = bool((valid.overall_status == "FINAL").all()) if "overall_status" in valid else False
    return Baseline(gmv, spend, sales, roas, profit, contribution, conf, final), valid


def date_range_filter(df, start, end, col="metric_date"):
    if df.empty or col not in df:
        return df
    d = pd.to_datetime(df[col]).dt.date
    return df[(d >= start) & (d <= end)].copy()


def status_icon(status):
    return {"FINAL":"🟢", "ESTIMATED":"🟡", "PARTIAL":"🟠", "MISSING":"🔴"}.get(str(status), "⚪")


def render_import_status():
    cov = source_coverage()
    indexed = {r.source: r for _, r in cov.iterrows()} if not cov.empty else {}
    rows = []
    for src in CORE_SOURCES:
        r = indexed.get(src)
        rows.append({
            "Sumber": SOURCE_LABELS[src],
            "Status": "✅ Sudah ada" if r is not None else "❌ Belum ada",
            "Data terbaru": "—" if r is None or pd.isna(r.latest_data_date) else str(r.latest_data_date),
            "File": 0 if r is None else int(r.file_count),
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


# Load once per rerun
DF = merged_with_quality()
PROFIT = profit_daily()
PC = period_control_summary(conn, sid)
GR = load_guardrails()
PERIOD_READINESS = compute_period_readiness(
    PC, DF,
    minimum_margin=max(0.10, float(GR.get("minimum_margin", .20))),
    maximum_ads_cost_pct=float(GR.get("maximum_ads_cost_pct", .17)),
    roas_bep=float(GR.get("roas_bep", 2.52)),
    minimum_safety_ratio=float(GR.get("minimum_safety_ratio", 1.25)),
) if not PC.empty else None
GUARDRAIL_SUGGESTIONS = suggested_guardrails(PC) if not PC.empty else None

with st.sidebar:
    st.title("📊 Daily Store Control")
    st.caption("Gerabahku Jogja")
    page = st.radio(
        "Menu",
        ["Dashboard", "Import Data", "SKU Mapping", "Readiness & Simulator", "Audit & Settings"],
        label_visibility="collapsed",
    )
    st.divider()
    cov = source_coverage()
    have = set(cov.source.tolist()) if not cov.empty else set()
    core_ready = sum(s in have for s in CORE_SOURCES)
    st.metric("Core Data", f"{core_ready}/{len(CORE_SOURCES)}")
    if not PROFIT.empty:
        latestp = PROFIT.iloc[-1]
        st.caption(f"Profit terbaru: {status_icon(latestp.profit_status)} {latestp.profit_status}")
    st.caption("Profit Source of Truth: Order + Income + HPP + seluruh Paid Ads")

st.title(page)

if page == "Dashboard":
    if PROFIT.empty:
        st.info("Belum ada Independent Profit data. Buka **Import Data** dan masukkan Order, Income, Master HPP, serta Ads.")
        render_import_status()
    else:
        pmin = PROFIT.metric_date.min().date()
        pmax = PROFIT.metric_date.max().date()
        default_start = max(pmin, pmax - pd.Timedelta(days=27).to_pytimedelta())
        cdate1, cdate2 = st.columns([1,3])
        range_choice = cdate1.selectbox("Periode", ["7 Hari", "14 Hari", "28 Hari", "Semua", "Custom"], index=2)
        if range_choice == "Custom":
            dr = cdate2.date_input("Rentang tanggal", value=(default_start, pmax), min_value=pmin, max_value=pmax)
            if isinstance(dr, (tuple, list)) and len(dr) == 2:
                start, end = dr
            else:
                start, end = pmin, pmax
        else:
            days = {"7 Hari":7, "14 Hari":14, "28 Hari":28}.get(range_choice)
            start = pmin if days is None else max(pmin, pmax - pd.Timedelta(days=days-1).to_pytimedelta())
            end = pmax
            cdate2.caption(f"{start.strftime('%d %b %Y')} – {end.strftime('%d %b %Y')}")

        pf = date_range_filter(PROFIT, start, end)
        md = date_range_filter(DF, start, end) if not DF.empty else DF
        latest = pf.sort_values("metric_date").iloc[-1]

        st.markdown(
            f"<div class='status-card'><b>{status_icon(latest.profit_status)} Profit Status: {latest.profit_status}</b>"
            f"<br><span class='muted'>Settlement coverage {pct(latest.settlement_coverage)} · HPP coverage {pct(latest.hpp_coverage)} · "
            f"Estimated fee rate {pct(latest.estimated_fee_rate)}</span></div>",
            unsafe_allow_html=True,
        )

        m1,m2,m3,m4,m5,m6 = st.columns(6)
        m1.metric("Order Sales", rp(pf.order_sales.sum()))
        m2.metric("Financial Income", rp(pf.financial_income.sum()))
        m3.metric("HPP", rp(pf.hpp.sum()))
        m4.metric("Paid Ads", rp(pf.ads_spend.fillna(0).sum()))
        m5.metric("Control Profit", rp(pf.control_profit.sum()))
        sales = pf.order_sales.sum()
        margin = pf.control_profit.sum()/sales if sales else None
        m6.metric("Control Margin", pct(margin))

        st.caption("Control Profit = Shopee Financial Income − HPP − seluruh Paid Ads. BigSeller Keuntungan Toko tidak dipakai sebagai sumber profit.")

        c1,c2 = st.columns([1.45,1])
        with c1:
            st.markdown("#### Profit Trend")
            chart = pf.set_index("metric_date")[["control_profit", "profit_before_ads"]].rename(columns={"control_profit":"Control Profit", "profit_before_ads":"Profit Before Ads"})
            st.line_chart(chart, use_container_width=True)
        with c2:
            st.markdown("#### Data Finality")
            sc = pf.profit_status.value_counts().rename_axis("Status").reset_index(name="Hari")
            st.dataframe(sc, hide_index=True, use_container_width=True)
            final_days = int((pf.profit_status == "FINAL").sum())
            st.metric("FINAL days", f"{final_days}/{len(pf)}")

        if not md.empty:
            st.markdown("#### Store & Ads Pulse")
            a,b,c,d,e = st.columns(5)
            gmv = md.store_gmv.sum() if "store_gmv" in md else None
            orders = md.orders.sum() if "orders" in md else None
            visitors = md.visitors.sum() if "visitors" in md else None
            spend = md.ads_spend.sum() if "ads_spend" in md else None
            ads_sales = md.ads_sales.sum() if "ads_sales" in md else None
            roas = ads_sales/spend if spend else None
            cr = md.conversion_rate.dropna().mean() if "conversion_rate" in md and md.conversion_rate.notna().any() else None
            a.metric("BI Gross Sales", rp(gmv))
            b.metric("Orders", num(orders,0))
            c.metric("Visitors/day avg", num(visitors/len(md) if visitors is not None and len(md) else None,0))
            d.metric("ROAS", num(roas,2,"x"))
            e.metric("CR avg", pct(cr))

        st.markdown("#### Daily Detail")
        showcols = ["metric_date","order_sales","financial_income","hpp","ads_spend","control_profit","control_margin","settlement_coverage","hpp_coverage","profit_status"]
        show = pf[[c for c in showcols if c in pf]].copy().sort_values("metric_date", ascending=False)
        st.dataframe(show, hide_index=True, use_container_width=True, height=380)

elif page == "Import Data":
    st.markdown("### Import Center")
    st.caption("Pilih jenis export lalu unggah satu atau beberapa file. File duplikat dideteksi dengan hash dan tidak diimport ulang.")
    render_import_status()
    st.divider()

    source = st.selectbox("Jenis data", list(SOURCE_LABELS), format_func=lambda x: SOURCE_LABELS[x])
    hints = {
        "BUSINESS_INSIGHT":"Export Shopee Business Insight / Performa Toko.",
        "SHOPEE_ORDER":"Order.all — file part 1/2 boleh diunggah sekaligus.",
        "SHOPEE_INCOME":"Income.sudah dilepas — tanggal file adalah tanggal dana dilepas; engine join berdasarkan No. Pesanan.",
        "BIGSELLER_HPP":"Export SKU Gudang terbaru. Hanya HPP/modal yang dipakai.",
        "SHOPEE_ADS_PRODUCT":"Data Keseluruhan Iklan Shopee.",
        "SHOPEE_ADS_SHOP_PLUS":"Shop+ / Toko+ Overall Data.",
        "SHOPEE_ADS_LIVE":"Data Semua Iklan Live.",
        "BIGSELLER_STORE":"Opsional, hanya audit silang profit.",
        "BIGSELLER_SKU":"Opsional, hanya audit/fallback HPP historis.",
    }
    st.info(hints[source])
    uploads = st.file_uploader("Excel / CSV", type=["xlsx","xls","csv"], accept_multiple_files=True, key=f"upload_{source}")
    if uploads:
        st.write(f"{len(uploads)} file siap diimport.")
        if st.button("Import Semua", type="primary", use_container_width=True):
            results=[]
            for u in uploads:
                try:
                    rr = import_file(DB_PATH, u.getvalue(), u.name, source)
                    results.append({"File":u.name,"Status":"Duplikat" if rr.get("duplicate") else "Imported","Grain":rr.get("granularity","—")})
                except Exception as e:
                    results.append({"File":u.name,"Status":f"ERROR: {e}","Grain":"—"})
            recompute_full_paid_media_profit(conn, sid)
            rebuild_quality(conn, sid)
            st.dataframe(pd.DataFrame(results), hide_index=True, use_container_width=True)
            st.success("Import selesai. Profit Engine dan quality status diperbarui.")
            st.rerun()

    st.markdown("### Import History")
    hist = pd.read_sql_query(
        "SELECT imported_at,source,filename,row_count,min_date,max_date,granularity,status FROM import_batches WHERE store_id=? ORDER BY imported_at DESC LIMIT 100",
        conn, params=[sid],
    )
    if hist.empty:
        st.info("Belum ada history import.")
    else:
        hist["source"] = hist.source.map(SOURCE_LABELS).fillna(hist.source)
        st.dataframe(hist, hide_index=True, use_container_width=True, height=360)

elif page == "SKU Mapping":
    st.caption("Mapping manual disimpan di aplikasi. Nama/kode boleh berbeda; yang penting pasangan SKU Gudang dan HPP benar.")
    ms = list_sku_mapping_status(conn, sid)
    wh = list_warehouse_skus(conn, sid)
    if ms.empty:
        st.info("Import Shopee Order terlebih dahulu.")
    elif wh.empty:
        st.warning("Import BigSeller Master HPP SKU terlebih dahulu.")
    else:
        unmapped = ms[ms.mapping_status == "UNMAPPED"].copy()
        manual = ms[ms.mapping_status == "MAPPED_MANUAL"].copy()
        exact = ms[ms.mapping_status == "MAPPED_EXACT"].copy()
        total_qty = ms.qty_realized.sum()
        covered_qty = ms.loc[ms.mapping_status != "UNMAPPED", "qty_realized"].sum()
        coverage = covered_qty/total_qty if total_qty else 0
        a,b,c,d = st.columns(4)
        a.metric("SKU Toko", len(ms))
        b.metric("Exact Match", len(exact))
        c.metric("Manual Mapping", len(manual))
        d.metric("Belum Terhubung", len(unmapped), delta=f"HPP coverage {pct(coverage)}")

        if not unmapped.empty:
            st.markdown("### Belum Terhubung")
            q = st.text_input("Cari SKU / nama produk", placeholder="Contoh: PANCI-20CM atau kendil")
            u = unmapped.copy()
            if q.strip():
                qq=q.lower().strip()
                u=u[u.store_sku.astype(str).str.lower().str.contains(qq,regex=False)|u.product_name.astype(str).str.lower().str.contains(qq,regex=False)]
            st.dataframe(u[["store_sku","product_name","qty_realized","orders","sales_idr"]].rename(columns={"store_sku":"SKU Toko","product_name":"Nama Produk","qty_realized":"Qty","orders":"Order","sales_idr":"Sales"}), hide_index=True, use_container_width=True, height=300)

            st.markdown("### Mapping Massal Berbantuan Saran")
            c1,c2,c3=st.columns([1,1,2])
            topn=int(c1.number_input("SKU prioritas",1,max(1,len(unmapped)),min(20,len(unmapped)),1))
            minconf=float(c2.number_input("Preselect confidence ≥ %",0.0,100.0,85.0,1.0))/100
            if c3.button("✨ Buat Saran",use_container_width=True):
                priority=unmapped.sort_values(["qty_realized","sales_idr"],ascending=[False,False]).head(topn).store_sku.tolist()
                batch=batch_mapping_suggestions(conn,sid,priority,1)
                if not batch.empty:
                    batch=batch.copy(); batch["confidence_pct"]=(batch.confidence*100).round(1); batch["Terapkan"]=batch.confidence.ge(minconf)
                    st.session_state["v2_bulk_map"]=batch
            batch=st.session_state.get("v2_bulk_map")
            if isinstance(batch,pd.DataFrame) and not batch.empty:
                cols=["Terapkan","store_sku","product_name","qty_realized","warehouse_sku","warehouse_title","unit_hpp","confidence_pct"]
                edited=st.data_editor(batch[cols],hide_index=True,use_container_width=True,height=min(520,38*(len(batch)+1)), disabled=[c for c in cols if c!="Terapkan"])
                chosen=edited[edited.Terapkan==True]
                if st.button("🔗 Hubungkan yang Dicentang",type="primary",disabled=chosen.empty):
                    payload=[{"store_sku":r.store_sku,"warehouse_sku":r.warehouse_sku,"confidence":float(r.confidence_pct)/100,"notes":"Disetujui dari V2 Bulk Mapping"} for _,r in chosen.iterrows()]
                    n=bulk_save_sku_mappings(conn,sid,payload)
                    st.session_state.pop("v2_bulk_map",None)
                    st.success(f"{n} mapping tersimpan dan Profit Engine dihitung ulang.")
                    st.rerun()

        st.markdown("### Hubungkan / Koreksi Satu SKU")
        options=(unmapped if not unmapped.empty else ms).store_sku.tolist()
        selected=st.selectbox("SKU Toko", options)
        rr=ms[ms.store_sku==selected].iloc[0]
        st.write(f"**{rr.product_name}** · Qty {num(rr.qty_realized,0)} · Sales {rp(rr.sales_idr)}")
        sug=mapping_suggestions(conn,sid,selected,5)
        if not sug.empty:
            temp=sug.copy(); temp["confidence_pct"]=(temp.confidence*100).round(1)
            st.dataframe(temp[["warehouse_sku","warehouse_title","unit_hpp","confidence_pct"]],hide_index=True,use_container_width=True)
        f=st.text_input("Filter SKU Gudang")
        wp=wh
        if f.strip():
            ff=f.lower().strip(); wp=wh[wh.sku.astype(str).str.lower().str.contains(ff,regex=False)|wh.product_title.astype(str).str.lower().str.contains(ff,regex=False)]
        if not wp.empty:
            chosen_wh=st.selectbox("SKU Gudang",wp.sku.tolist(),format_func=lambda x:f"{x} — {str(wp[wp.sku==x].iloc[0].product_title)[:85]} — {rp(wp[wp.sku==x].iloc[0].unit_hpp)}")
            if st.button("Hubungkan SKU",type="primary"):
                conf=None
                if not sug.empty and chosen_wh in sug.warehouse_sku.tolist(): conf=float(sug[sug.warehouse_sku==chosen_wh].iloc[0].confidence)
                save_sku_mapping(conn,sid,selected,chosen_wh,confidence=conf,notes="Disetujui dari V2 SKU Mapping")
                st.success("Mapping tersimpan."); st.rerun()

        if not manual.empty:
            with st.expander("Mapping Manual Tersimpan"):
                st.dataframe(manual[["store_sku","product_name","warehouse_sku","warehouse_title","effective_hpp","confidence"]],hide_index=True,use_container_width=True)
                to_delete=st.selectbox("Hapus mapping",manual.store_sku.tolist(),key="v2_del_map")
                if st.button("🗑️ Hapus Mapping"):
                    delete_sku_mapping(conn,sid,to_delete); st.rerun()

elif page == "Readiness & Simulator":
    gr=load_guardrails()
    readiness=compute_readiness(DF,gr["minimum_margin"],gr["roas_bep"],gr["minimum_safety_ratio"],gr["maximum_ads_cost_pct"]) if not DF.empty else None
    daily_ok=bool(readiness and readiness.get("diagnostics",{}).get("profit_7d") is not None and pd.notna(readiness.get("diagnostics",{}).get("profit_7d")))
    shown=readiness if daily_ok else PERIOD_READINESS
    st.markdown("### Scale Readiness")
    if not shown:
        st.info("Data belum cukup untuk Readiness Engine.")
    elif daily_ok:
        a,b,c=st.columns(3); a.metric("Readiness",f"{shown['score']:.1f}/100"); b.metric("Recommendation",shown["recommendation"]); c.metric("Mode","DAILY")
        st.bar_chart(pd.DataFrame({"Score":shown["components"]}))
    else:
        a,b,c=st.columns(3); a.metric("Preliminary",f"{shown['score']:.1f}/100"); b.metric("Recommendation",shown["action"]); c.metric("Scale Allowed","YES" if shown["scale_allowed"] else "NO")
        st.warning("Mode PERIOD PRELIMINARY. SCALE agresif tetap terkunci sampai profit harian FINAL dan confidence memadai.")
        st.bar_chart(pd.DataFrame({"Score":shown["components"]}))

    st.divider(); st.markdown("### Scale Simulator")
    days=st.selectbox("Baseline",[7,14,30])
    baseline,valid=build_baseline(DF,days)
    if baseline is None:
        st.info("Simulator membutuhkan baseline harian lengkap.")
    else:
        guard=Guardrails(minimum_margin=gr["minimum_margin"],minimum_roas=gr["minimum_roas"],roas_bep=gr["roas_bep"],minimum_safety_ratio=gr["minimum_safety_ratio"],maximum_ads_cost_pct=gr["maximum_ads_cost_pct"],recommended_budget=gr["recommended_budget"],hard_budget_limit=gr["hard_budget_limit"])
        ch=st.radio("Perubahan budget",[10,20,30],horizontal=True,format_func=lambda x:f"+{x}%")
        out=pd.DataFrame([simulate_scale(baseline,ch/100,s,guard) for s in ["optimistic","realistic","conservative"]])
        st.dataframe(out,use_container_width=True,hide_index=True)

elif page == "Audit & Settings":
    st.markdown("### Data Coverage")
    render_import_status()
    q=quality_daily()
    if not q.empty:
        with st.expander("Daily Quality Detail"):
            st.dataframe(q,hide_index=True,use_container_width=True,height=320)

    st.markdown("### BigSeller Profit — Audit Only")
    if PC.empty:
        st.info("Belum ada BigSeller Keuntungan Toko. Tidak wajib untuk Control Profit.")
    else:
        cols=[c for c in ["period_start","period_end","realized_sales","full_paid_media_control_profit","full_paid_media_control_margin","bi_vs_bigseller_variance","bi_vs_bigseller_variance_pct"] if c in PC]
        st.dataframe(PC[cols],hide_index=True,use_container_width=True)
        st.caption("Angka BigSeller di halaman ini hanya pembanding/audit dan tidak menjadi Source of Truth profit.")

    st.markdown("### Guardrails")
    gr=load_guardrails()
    if GUARDRAIL_SUGGESTIONS:
        sg=GUARDRAIL_SUGGESTIONS
        st.caption(f"Suggested history: Min Margin {pct(sg['minimum_margin'])} · Max Ads Cost {pct(sg['maximum_ads_cost_pct'])} · ROAS BEP {sg['roas_bep']:.2f}x · Safety {sg['minimum_safety_ratio']:.2f}x")
    with st.form("v2_guardrail"):
        a,b,c=st.columns(3)
        mm=a.number_input("Min Control Margin %",0.0,100.0,float(gr["minimum_margin"]*100),.5)/100
        mr=b.number_input("Min ROAS",0.0,value=float(gr["minimum_roas"]),step=.1)
        rb=c.number_input("ROAS BEP",0.0,value=float(gr["roas_bep"]),step=.1)
        a,b,c=st.columns(3)
        sr=a.number_input("Min Safety Ratio",0.0,value=float(gr["minimum_safety_ratio"]),step=.05)
        ac=b.number_input("Max Paid Ads Cost %",0.0,100.0,float(gr["maximum_ads_cost_pct"]*100),.5)/100
        bud=c.number_input("Recommended Daily Budget",0.0,value=float(gr["recommended_budget"]),step=100000.0)
        hard=st.number_input("Hard Daily Budget Limit (0=off)",0.0,value=float(gr["hard_budget_limit"]),step=100000.0)
        if st.form_submit_button("Simpan Guardrails",type="primary"):
            save_guardrails({"minimum_margin":mm,"minimum_roas":mr,"roas_bep":rb,"minimum_safety_ratio":sr,"maximum_ads_cost_pct":ac,"recommended_budget":bud,"hard_budget_limit":hard})
            st.success("Guardrails tersimpan."); st.rerun()

    st.markdown("### Deployment Health")
    st.code(f"Database: {DB_PATH}\nApp entry: app/v2_main.py\nCore schema: OK\nTimezone: Asia/Jakarta")

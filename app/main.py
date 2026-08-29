from pathlib import Path
import json
import sys
import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from database import connect, init_db, get_store_id
from service import (
    import_file, merged_daily, rebuild_quality, recompute_full_paid_media_profit,
    period_control_summary, list_sku_mapping_status, list_warehouse_skus, save_sku_mapping, delete_sku_mapping, mapping_suggestions,
    bulk_save_sku_mappings, batch_mapping_suggestions,
)
from period_readiness import compute_period_readiness, suggested_guardrails
from engine import Baseline, Guardrails, simulate_scale, choose_daily_action
from auto_readiness import compute_readiness

DB_PATH = Path(__file__).resolve().parents[1] / 'daily_store_control.db'
st.set_page_config(page_title='Daily Store Control & Scale Simulator', page_icon='📊', layout='wide')
conn = connect(DB_PATH)
init_db(conn)
sid = get_store_id(conn)

SOURCE_LABELS = {
    'BUSINESS_INSIGHT': 'Shopee Business Insight',
    'SHOPEE_ADS_PRODUCT': 'Shopee Product Ads',
    'SHOPEE_ADS_LIVE': 'Shopee Live Ads',
    'SHOPEE_ADS_SHOP_PLUS': 'Shopee Toko+',
    'BIGSELLER_STORE': 'BigSeller Keuntungan Toko',
    'BIGSELLER_SKU': 'BigSeller Keuntungan SKU Gudang (Audit)',
    'SHOPEE_ORDER': 'Shopee Order',
    'SHOPEE_INCOME': 'Shopee Income / Penghasilan',
    'BIGSELLER_HPP': 'BigSeller Master HPP SKU',
}

st.markdown('''
<style>
.block-container {padding-top: 1.4rem; padding-bottom: 3rem;}
[data-testid="stMetric"] {border:1px solid rgba(128,128,128,.18); padding:12px; border-radius:12px;}
.small-muted {color:#7a7a7a; font-size:.88rem;}
.status-box {padding:10px 14px;border-radius:10px;margin:4px 0 12px 0;border:1px solid rgba(128,128,128,.2);}
</style>
''', unsafe_allow_html=True)


def rp(x):
    return '—' if x is None or pd.isna(x) else ('Rp{:,.0f}'.format(float(x)).replace(',', '.'))


def pct(x):
    return '—' if x is None or pd.isna(x) else f'{float(x)*100:.2f}%'


def num(x, digits=2, suffix=''):
    return '—' if x is None or pd.isna(x) else f'{float(x):,.{digits}f}{suffix}'.replace(',', '_').replace('.', ',').replace('_', '.')


def load_guardrails():
    r = conn.execute('SELECT * FROM guardrails WHERE store_id=?', (sid,)).fetchone()
    return dict(r) if r else {}


def save_guardrails(values):
    conn.execute('''UPDATE guardrails SET minimum_margin=?,minimum_roas=?,roas_bep=?,minimum_safety_ratio=?,
                    maximum_ads_cost_pct=?,recommended_budget=?,hard_budget_limit=?,updated_at=CURRENT_TIMESTAMP
                    WHERE store_id=?''', (
        values['minimum_margin'], values['minimum_roas'], values['roas_bep'],
        values['minimum_safety_ratio'], values['maximum_ads_cost_pct'],
        values['recommended_budget'], values['hard_budget_limit'], sid
    ))
    conn.commit()


def build_baseline(df, days, gr):
    req = ['store_gmv', 'ads_spend', 'ads_sales', 'roas', 'full_paid_media_control_profit']
    if df.empty or any(c not in df.columns for c in req):
        return None, pd.DataFrame()
    valid = df.dropna(subset=req).sort_values('metric_date').tail(days)
    if valid.empty:
        return None, valid
    gmv = valid.store_gmv.mean()
    spend = valid.ads_spend.mean()
    sales = valid.ads_sales.mean()
    roas = sales / spend if spend else 0
    profit = valid.full_paid_media_control_profit.mean()
    contribution = (profit + spend) / gmv if gmv else 0
    conf = float(valid.confidence_score.mean()) if 'confidence_score' in valid else 100.0
    data_final = bool((valid.overall_status == 'FINAL').all()) if 'overall_status' in valid else False
    return Baseline(gmv, spend, sales, roas, profit, contribution, conf, data_final), valid


def current_action(df):
    gr = load_guardrails()
    r = compute_readiness(df, gr['minimum_margin'], gr['roas_bep'], gr['minimum_safety_ratio'], gr['maximum_ads_cost_pct']) if not df.empty else None
    if not r:
        return None, None, None
    guard = Guardrails(
        minimum_margin=gr['minimum_margin'], minimum_roas=gr['minimum_roas'], roas_bep=gr['roas_bep'],
        minimum_safety_ratio=gr['minimum_safety_ratio'], maximum_ads_cost_pct=gr['maximum_ads_cost_pct'],
        recommended_budget=gr['recommended_budget'], hard_budget_limit=gr['hard_budget_limit'])
    baseline, used = build_baseline(df, 7, gr)
    action = choose_daily_action(baseline, r['score'], guard) if baseline else None
    return r, action, used


def source_coverage_table():
    q = pd.read_sql_query('''SELECT source, COUNT(*) file_count, MAX(imported_at) last_import,
                              MAX(max_date) latest_data_date,
                              SUM(CASE WHEN granularity='DAILY' THEN 1 ELSE 0 END) daily_files,
                              SUM(CASE WHEN granularity='PERIOD' THEN 1 ELSE 0 END) period_files
                              FROM import_batches WHERE store_id=? AND status='IMPORTED'
                              GROUP BY source ORDER BY source''', conn, params=[sid])
    if not q.empty:
        q['source_name'] = q.source.map(SOURCE_LABELS).fillna(q.source)
    return q


# Load current data
_df = merged_daily(conn, sid)
_q = pd.read_sql_query('SELECT * FROM daily_data_quality WHERE store_id=? ORDER BY metric_date', conn, params=[sid], parse_dates=['metric_date'])
if not _df.empty and not _q.empty:
    _df = _df.merge(_q[['metric_date', 'overall_status', 'confidence_score', 'bigseller_status']], on='metric_date', how='left')
_pc = period_control_summary(conn, sid)
_gr_now = load_guardrails()
_period_readiness = compute_period_readiness(
    _pc, _df,
    minimum_margin=max(0.10, float(_gr_now.get('minimum_margin', 0.20))),
    maximum_ads_cost_pct=float(_gr_now.get('maximum_ads_cost_pct', 0.17)),
    roas_bep=float(_gr_now.get('roas_bep', 2.52)),
    minimum_safety_ratio=float(_gr_now.get('minimum_safety_ratio', 1.25))
) if not _pc.empty else None
_guardrail_suggestions = suggested_guardrails(_pc) if not _pc.empty else None

st.title('Daily Store Control & Scale Simulator')
st.caption('Gerabahku Jogja · Profit-first daily control · Scale only when data and guardrails are safe')

# Compact top status
r_now, action_now, _used = current_action(_df)
if action_now:
    action_text = action_now['action']
    icon = '🚀' if action_text.startswith('SCALE') else ('🔴' if action_text.startswith('REDUCE') else ('⏳' if 'WAIT' in action_text else ('🟡' if 'HOLD' in action_text else '🟢')))
    st.markdown(f"<div class='status-box'><b>{icon} Daily Recommendation: {action_text}</b><br><span class='small-muted'>{action_now['reason']}</span></div>", unsafe_allow_html=True)
elif _period_readiness:
    pa = _period_readiness['action']
    st.markdown(f"<div class='status-box'><b>📅 Preliminary Readiness: {_period_readiness['score']:.1f}/100 · {pa}</b><br><span class='small-muted'>Mode periode: informatif saja. SCALE agresif tetap menunggu verifikasi harian dan Product Ads.</span></div>", unsafe_allow_html=True)
elif not _pc.empty:
    st.markdown("<div class='status-box'><b>📅 Period Control tersedia</b><br><span class='small-muted'>Profit periode sudah bisa direkonsiliasi, tetapi keputusan scale harian menunggu data DAILY yang lengkap.</span></div>", unsafe_allow_html=True)
else:
    st.info('Upload sumber data untuk mulai membangun Daily Control.')

with st.sidebar:
    st.header('Quick Upload')
    source = st.selectbox('Jenis export', list(SOURCE_LABELS), format_func=lambda x: SOURCE_LABELS[x], key='side_source')
    ups = st.file_uploader('Excel / CSV', type=['xlsx', 'xls', 'csv'], accept_multiple_files=True, key='side_upload')
    if ups and st.button('Import Semua', use_container_width=True, key='side_import'):
        ok = 0
        for u in ups:
            try:
                rr = import_file(DB_PATH, u.getvalue(), u.name, source)
                ok += 0 if rr.get('duplicate') else 1
                tag = 'duplikat' if rr.get('duplicate') else rr['granularity']
                st.write(f"✅ {u.name} · {tag}")
            except Exception as e:
                st.error(f'{u.name}: {e}')
        recompute_full_paid_media_profit(conn, sid)
        rebuild_quality(conn, sid)
        st.success(f'{ok} file baru diimport')
        st.rerun()
    st.divider()
    st.caption('PERIOD snapshot tidak pernah dibagi rata menjadi data harian.')


tabs = st.tabs([
    'Control Center', 'Upload & History', 'Daily Pulse', 'Trend', 'Data Coverage',
    'Period Control', 'Scale Readiness', 'Scale Simulator', 'SKU Mapping', 'Guardrails'
])

with tabs[0]:
    st.subheader('Control Center')
    if not _df.empty:
        x = _df.sort_values('metric_date').iloc[-1]
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric('Gross Sales', rp(x.get('store_gmv')))
        c2.metric('Adjusted Sales', rp(x.get('adjusted_store_sales')))
        c3.metric('Paid Spend', rp(x.get('ads_spend')))
        c4.metric('ROAS', f"{float(x.get('roas')):.2f}x" if pd.notna(x.get('roas')) else '—')
        c5.metric('Control Profit', rp(x.get('full_paid_media_control_profit')))
        c6.metric('Control Margin', pct(x.get('full_paid_media_control_margin')))
        st.caption(f"Latest daily date: {x.metric_date.strftime('%d-%m-%Y')} · Data status: {x.get('overall_status','MISSING')} · Confidence: {x.get('confidence_score',0):.0f}/100")
    else:
        st.info('Belum ada data DAILY yang dapat digabungkan.')

    if not _pc.empty:
        latest = _pc.iloc[-1]
        st.markdown('#### Latest Period Control')
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric('Realized Sales', rp(latest.get('realized_sales')))
        c2.metric('Total Paid Spend', rp(latest.get('total_paid_spend')))
        c3.metric('Full Paid Media Profit', rp(latest.get('full_paid_media_control_profit')))
        c4.metric('Control Margin', pct(latest.get('full_paid_media_control_margin')))
        c5.metric('Ads Cost %', pct(latest.get('paid_ads_cost_pct_realized')))
        st.caption(f"Periode {latest['period_start']} → {latest['period_end']}. Profit source: BigSeller Keuntungan Toko; Product Ads tidak dikurangi dua kali.")

    cov = source_coverage_table()
    st.markdown('#### Source Coverage')
    if cov.empty:
        st.info('Belum ada file yang diimport.')
    else:
        show = cov[['source_name', 'file_count', 'daily_files', 'period_files', 'latest_data_date', 'last_import']].rename(columns={
            'source_name':'Source','file_count':'Files','daily_files':'Daily','period_files':'Period','latest_data_date':'Latest Data','last_import':'Last Import'})
        st.dataframe(show, hide_index=True, use_container_width=True)

with tabs[1]:
    st.subheader('Upload Center')
    c1, c2 = st.columns([1, 2])
    with c1:
        up_source = st.selectbox('Sumber file', list(SOURCE_LABELS), format_func=lambda x: SOURCE_LABELS[x], key='center_source')
        center_files = st.file_uploader('Pilih satu atau banyak file', type=['xlsx','xls','csv'], accept_multiple_files=True, key='center_files')
        if center_files and st.button('Import & Validate', type='primary', use_container_width=True):
            messages = []
            for u in center_files:
                try:
                    rr = import_file(DB_PATH, u.getvalue(), u.name, up_source)
                    messages.append((u.name, rr))
                except Exception as e:
                    st.error(f'{u.name}: {e}')
            recompute_full_paid_media_profit(conn, sid)
            rebuild_quality(conn, sid)
            for name, rr in messages:
                st.success(f"{name}: {rr['granularity']} · {rr['period_start']} → {rr['period_end']}" + (' · DUPLICATE' if rr.get('duplicate') else ''))
                if rr.get('warnings'):
                    st.warning('; '.join(rr['warnings']))
            st.rerun()
        st.caption('Multi-upload disarankan untuk Shopee Ads harian. Hash file mencegah file identik terimport dua kali.')
    with c2:
        hist = pd.read_sql_query('''SELECT id,source,filename,granularity,min_date,max_date,row_count,status,imported_at,notes
                                    FROM import_batches WHERE store_id=? ORDER BY id DESC LIMIT 200''', conn, params=[sid])
        if hist.empty:
            st.info('Belum ada riwayat import.')
        else:
            hist['source'] = hist.source.map(SOURCE_LABELS).fillna(hist.source)
            st.dataframe(hist, hide_index=True, use_container_width=True, height=430)

with tabs[2]:
    st.subheader('Daily Pulse')
    if _df.empty:
        st.info('Belum ada data DAILY. Data PERIOD tetap tersimpan di Period Control dan tidak dipaksakan menjadi data harian.')
    else:
        dates = _df.sort_values('metric_date').metric_date.dt.date.tolist()
        chosen = st.selectbox('Tanggal', dates, index=len(dates)-1)
        x = _df[_df.metric_date.dt.date == chosen].iloc[-1]
        items = [
            ('Gross Sales', rp(x.get('store_gmv'))), ('Adjusted Sales', rp(x.get('adjusted_store_sales'))),
            ('Order', num(x.get('orders'), 0)), ('Visitor', num(x.get('visitors'), 0)),
            ('Shopee CR', pct(x.get('conversion_rate'))), ('Paid Spend', rp(x.get('ads_spend'))),
            ('Ads Sales Attribution', rp(x.get('ads_sales'))), ('ROAS', f"{float(x.get('roas')):.2f}x" if pd.notna(x.get('roas')) else '—'),
            ('ACOS', pct(x.get('acos'))), ('CPC', rp(x.get('cpc'))), ('RPM', rp(x.get('rpm'))),
            ('Control Profit', rp(x.get('full_paid_media_control_profit'))), ('Control Margin', pct(x.get('full_paid_media_control_margin'))),
        ]
        cols = st.columns(5)
        for i, (a, b) in enumerate(items):
            cols[i % 5].metric(a, b)
        st.info(f"Status: **{x.get('overall_status','MISSING')}** · Profit V1.6: **{x.get('profit_status_v16', x.get('bigseller_status','MISSING'))}** · Confidence **{x.get('confidence_score',0):.0f}/100**")
        st.caption('Ads Sales adalah attribution, bukan tambahan omzet toko.')

with tabs[3]:
    st.subheader('Trend Dashboard')
    if _df.empty:
        st.info('Belum ada data DAILY.')
    else:
        win = st.radio('Window', [7, 14, 30], horizontal=True)
        c = _df.sort_values('metric_date').tail(win).set_index('metric_date')
        charts = [
            ('Omzet', ['store_gmv', 'adjusted_store_sales']), ('Profit', ['full_paid_media_control_profit']),
            ('Margin', ['full_paid_media_control_margin']), ('ROAS', ['roas']), ('CR', ['conversion_rate']),
            ('Traffic', ['visitors']), ('Biaya Iklan', ['ads_spend'])]
        for title, cols in charts:
            use = [z for z in cols if z in c and c[z].notna().any()]
            if use:
                st.markdown(f'**{title}**')
                st.line_chart(c[use], use_container_width=True)

with tabs[4]:
    st.subheader('Data Coverage / Sync Status')
    if _q.empty:
        st.info('Belum ada coverage harian.')
    else:
        st.dataframe(_q[['metric_date','business_insight_status','ads_status','bigseller_status','overall_status','confidence_score','flags_json']], hide_index=True, use_container_width=True)
    st.markdown('''
    **Data gate V1.6:** settlement belum dilepas → `ESTIMATED`; coverage HPP/settlement rendah → `PARTIAL`; semua sumber lengkap → `FINAL`.  
    Mesin **tidak boleh memberikan rekomendasi SCALE agresif** jika status belum FINAL atau confidence terlalu rendah.
    ''')

with tabs[5]:
    st.subheader('Period Control / Reconciliation')
    if _pc.empty:
        st.info('Upload BigSeller Keuntungan Toko dan snapshot periode Ads untuk melihat rekonsiliasi.')
    else:
        latest = _pc.iloc[-1]
        st.markdown(f"#### {latest['period_start']} → {latest['period_end']}")
        a,b,c,d = st.columns(4)
        a.metric('Adjusted BI', rp(latest.get('adjusted_store_sales')))
        b.metric('Realized Sales BigSeller', rp(latest.get('realized_sales')))
        c.metric('Full Paid Media Profit', rp(latest.get('full_paid_media_control_profit')))
        d.metric('Control Margin', pct(latest.get('full_paid_media_control_margin')))
        a,b,c,d = st.columns(4)
        a.metric('Product Ads Spend', rp(latest.get('product_ads_spend')))
        b.metric('Live Ads Spend', rp(latest.get('live_ads_spend')))
        c.metric('Toko+ Spend', rp(latest.get('shop_plus_spend')))
        d.metric('Total Paid Spend', rp(latest.get('total_paid_spend')))
        src = latest.get('product_ads_source', 'UNKNOWN')
        if src == 'BIGSELLER_FALLBACK':
            st.warning('Product Ads Spend memakai fallback kolom Iklan BigSeller. Spend lengkap, tetapi ROAS/Ads Sales Product Ads belum terverifikasi dari export Shopee periode yang sama.')
        else:
            st.success('Product Ads Spend terverifikasi terhadap export Shopee Ads.')
        if pd.notna(latest.get('product_ads_variance')):
            st.success(f"Cross-check kolom Iklan BigSeller vs Product Ads Shopee: selisih {rp(latest.get('product_ads_variance'))}")
        if latest.get('bigseller_ads_reconciliation') == 'PRODUCT_PLUS_SHOP_PLUS':
            st.info('Kolom Iklan BigSeller terdeteksi mencakup Product Ads + Toko+. Toko+ tidak dikurangkan lagi dari GPMI.')
        if pd.notna(latest.get('bi_vs_bigseller_variance_pct')):
            st.caption(f"Adjusted Business Insight vs BigSeller: {pct(latest.get('bi_vs_bigseller_variance_pct'))} ({rp(latest.get('bi_vs_bigseller_variance'))}).")
        show = _pc.copy()
        st.dataframe(show, use_container_width=True, hide_index=True)
        st.caption('Snapshot bulanan/MTD tetap pada grain periode; tidak dibagi 30 untuk menciptakan profit harian palsu.')

with tabs[6]:
    st.subheader('Store Scale Readiness')
    gr = load_guardrails()
    r = compute_readiness(_df, gr['minimum_margin'], gr['roas_bep'], gr['minimum_safety_ratio'], gr['maximum_ads_cost_pct']) if not _df.empty else None
    # Daily readiness is authoritative only when profit DAILY exists. Otherwise show period preliminary.
    daily_authoritative = bool(r and r.get('diagnostics',{}).get('profit_7d') is not None and pd.notna(r.get('diagnostics',{}).get('profit_7d')))
    shown = r if daily_authoritative else _period_readiness
    if not shown:
        st.info('Readiness aktif setelah tersedia Business Insight + Shopee Order + Income + HPP + data iklan yang cukup.')
    elif daily_authoritative:
        a,b,c = st.columns(3)
        a.metric('Readiness Score', f"{shown['score']:.1f}/100")
        b.metric('Engine Status', shown['recommendation'])
        c.metric('Mode', 'DAILY')
        comp = pd.DataFrame({'Component': list(shown['components']), 'Score': list(shown['components'].values())}).set_index('Component')
        st.bar_chart(comp)
        diag = shown['diagnostics']
        c1,c2,c3,c4,c5 = st.columns(5)
        c1.metric('Margin 7D', pct(diag.get('margin_7d')))
        c2.metric('Profit/day 7D', rp(diag.get('profit_7d')))
        c3.metric('ROAS 7D', num(diag.get('roas_7d'),2,'x'))
        c4.metric('Safety Ratio', num(diag.get('safety_ratio_7d'),2,'x'))
        c5.metric('Ads Cost %', pct(diag.get('ads_cost_pct_7d')))
        if action_now:
            st.markdown(f"### Daily Recommendation: **{action_now['action']}**")
            st.write(action_now['reason'])
    else:
        a,b,c = st.columns(3)
        a.metric('Preliminary Score', f"{shown['score']:.1f}/100")
        b.metric('Recommendation', shown['action'])
        c.metric('Scale Allowed', 'NO' if not shown['scale_allowed'] else 'YES')
        st.warning('Mode PERIOD PRELIMINARY — score ini membantu membaca kondisi toko, tetapi tidak boleh menghasilkan SCALE +10/+20/+30 sebelum data harian yang dibutuhkan lengkap.')
        comp = pd.DataFrame({'Component': list(shown['components']), 'Score': list(shown['components'].values())}).set_index('Component')
        st.bar_chart(comp)
        diag=shown['diagnostics']
        c1,c2,c3,c4,c5=st.columns(5)
        c1.metric('Control Margin', pct(diag.get('control_margin')))
        c2.metric('Profit/day', rp(diag.get('profit_per_day')))
        c3.metric('Paid Ads Cost %', pct(diag.get('paid_ads_cost_pct')))
        c4.metric('CR 7D', pct(diag.get('cr_7d')))
        c5.metric('Adjusted Sales/day 7D', rp(diag.get('adjusted_sales_per_day_7d')))
        for lim in shown.get('limitations',[]):
            st.caption('• '+lim)

with tabs[7]:
    st.subheader('Scale Simulator')
    gr = load_guardrails()
    baseline_days = st.selectbox('Baseline FINAL', [7,14,30], index=0)
    baseline, valid = build_baseline(_df, baseline_days, gr)
    if baseline is None:
        st.info('Simulator membutuhkan BI + Ads + BigSeller Keuntungan Toko dalam grain DAILY. Snapshot periode tidak digunakan untuk mengarang baseline harian.')
    else:
        guard = Guardrails(
            minimum_margin=gr['minimum_margin'], minimum_roas=gr['minimum_roas'], roas_bep=gr['roas_bep'],
            minimum_safety_ratio=gr['minimum_safety_ratio'], maximum_ads_cost_pct=gr['maximum_ads_cost_pct'],
            recommended_budget=gr['recommended_budget'], hard_budget_limit=gr['hard_budget_limit'])
        st.caption(f"Baseline memakai {len(valid)} hari valid · Confidence {baseline.confidence:.1f}/100 · Data final: {baseline.data_final}")
        preset = st.radio('Kenaikan budget', ['+10%','+20%','+30%','Custom'], horizontal=True)
        change = {'+10%':10,'+20%':20,'+30%':30}.get(preset)
        if preset == 'Custom':
            change = st.slider('Custom %', -50, 100, 20, 5)
        d = change / 100
        out = pd.DataFrame([simulate_scale(baseline, d, s, guard) for s in ['optimistic','realistic','conservative']])
        display = out.copy()
        display['ads_spend'] = display.ads_spend.map(rp)
        display['ads_sales'] = display.ads_sales.map(rp)
        display['store_gmv'] = display.store_gmv.map(rp)
        display['profit'] = display.profit.map(rp)
        display['additional_profit'] = display.additional_profit.map(rp)
        display['margin'] = display.margin.map(pct)
        display['ads_cost_pct'] = display.ads_cost_pct.map(pct)
        display['roas'] = display.roas.map(lambda x:f'{x:.2f}x')
        display['safety_ratio'] = display.safety_ratio.map(lambda x:f'{x:.2f}x')
        st.dataframe(display[['scenario','ads_spend','roas','ads_sales','store_gmv','profit','margin','additional_profit','ads_cost_pct','safety_ratio','risk_level','guardrail_failures']], hide_index=True, use_container_width=True)
        st.caption('Projected Ads Sales tidak ditambahkan 1:1 ke Store GMV. Simulator memakai incrementality factor + ROAS decay per skenario.')

with tabs[8]:
    st.subheader('SKU Mapping Manager')
    st.caption('Hubungkan SKU Toko ke SKU Gudang satu kali. Nama dan kode boleh berbeda; mapping manual menjadi prioritas HPP tertinggi.')
    ms = list_sku_mapping_status(conn, sid)
    wh = list_warehouse_skus(conn, sid)
    if ms.empty:
        st.info('Belum ada Shopee Order. Import Order terlebih dahulu agar SKU Toko dapat dideteksi.')
    elif wh.empty:
        st.warning('Belum ada Master HPP BigSeller. Import BigSeller Master HPP SKU terlebih dahulu.')
    else:
        unmapped = ms[ms.mapping_status == 'UNMAPPED'].copy()
        manual = ms[ms.mapping_status == 'MAPPED_MANUAL'].copy()
        exact = ms[ms.mapping_status == 'MAPPED_EXACT'].copy()
        c1,c2,c3,c4 = st.columns(4)
        c1.metric('Belum Terhubung', f'{len(unmapped):,}'.replace(',', '.'))
        c2.metric('Mapping Manual', f'{len(manual):,}'.replace(',', '.'))
        c3.metric('Match Kode Otomatis', f'{len(exact):,}'.replace(',', '.'))
        qty_total = float(ms.qty_realized.sum()) if not ms.empty else 0
        qty_known = float(ms.loc[ms.mapping_status!='UNMAPPED','qty_realized'].sum()) if not ms.empty else 0
        coverage = qty_known/qty_total if qty_total else 0
        c4.metric('Coverage Qty HPP', pct(coverage))

        if len(unmapped):
            missing_qty=float(unmapped.qty_realized.sum())
            st.warning(f'{len(unmapped)} SKU belum terhubung mewakili {num(missing_qty,0)} qty realized. Profit pada order terkait belum boleh dianggap FINAL.')
        else:
            st.success('Semua SKU Toko yang pernah terjual sudah memiliki jalur HPP.')

        f1,f2 = st.columns([2,1])
        search = f1.text_input('Cari SKU / nama produk', placeholder='Contoh: PANCI-20 atau cobek', key='map_search').strip().lower()
        view = f2.selectbox('Tampilkan', ['Belum Terhubung','Mapping Manual','Semua SKU'], key='map_view')
        if view == 'Belum Terhubung': show = unmapped.copy()
        elif view == 'Mapping Manual': show = manual.copy()
        else: show = ms.copy()
        if search and not show.empty:
            mask=show.store_sku.astype(str).str.lower().str.contains(search,regex=False) | show.product_name.astype(str).str.lower().str.contains(search,regex=False)
            show=show[mask]
        if not show.empty:
            display_cols=['store_sku','product_name','qty_realized','orders','warehouse_sku','warehouse_title','effective_hpp','mapping_status']
            st.dataframe(show[display_cols].rename(columns={
                'store_sku':'SKU Toko','product_name':'Nama Produk Toko','qty_realized':'Qty','orders':'Order',
                'warehouse_sku':'SKU Gudang','warehouse_title':'Nama SKU Gudang','effective_hpp':'HPP','mapping_status':'Status'}),
                hide_index=True,use_container_width=True,height=330)

        if not unmapped.empty:
            st.markdown('#### Mapping Massal Berbantuan Saran')
            st.caption('Aplikasi hanya membuat saran. Tidak ada SKU yang dihubungkan sebelum Bapak mencentang Terapkan dan menekan tombol konfirmasi.')
            b1,b2,b3=st.columns([1,1,2])
            top_n=int(b1.number_input('Jumlah SKU prioritas',min_value=1,max_value=int(len(unmapped)),value=min(20,int(len(unmapped))),step=1))
            min_conf=float(b2.number_input('Tandai otomatis jika confidence ≥',min_value=0.0,max_value=100.0,value=85.0,step=1.0))/100
            if b3.button('✨ Buat Saran untuk SKU Prioritas',use_container_width=True):
                priority=unmapped.sort_values(['qty_realized','sales_idr'],ascending=[False,False]).head(top_n).store_sku.tolist()
                batch=batch_mapping_suggestions(conn,sid,priority,1)
                if batch.empty:
                    st.session_state.pop('bulk_mapping_editor',None)
                else:
                    batch=batch.copy(); batch['confidence_pct']=(batch.confidence*100).round(1)
                    batch['Terapkan']=batch.confidence.ge(min_conf)
                    st.session_state['bulk_mapping_editor']=batch
            batch=st.session_state.get('bulk_mapping_editor')
            if isinstance(batch,pd.DataFrame) and not batch.empty:
                editor_cols=['Terapkan','store_sku','product_name','qty_realized','warehouse_sku','warehouse_title','unit_hpp','confidence_pct']
                edited=st.data_editor(batch[editor_cols],hide_index=True,use_container_width=True,height=min(520,38*(len(batch)+1)),
                    disabled=['store_sku','product_name','qty_realized','warehouse_sku','warehouse_title','unit_hpp','confidence_pct'],
                    column_config={
                        'Terapkan':st.column_config.CheckboxColumn('Terapkan'),
                        'store_sku':'SKU Toko','product_name':'Nama Produk Toko','qty_realized':'Qty',
                        'warehouse_sku':'Saran SKU Gudang','warehouse_title':'Nama SKU Gudang','unit_hpp':st.column_config.NumberColumn('HPP',format='Rp %.0f'),
                        'confidence_pct':st.column_config.NumberColumn('Confidence %',format='%.1f')
                    },key='bulk_mapping_table')
                selected=edited[edited.Terapkan==True]
                st.caption(f'{len(selected)} dari {len(edited)} saran dipilih untuk dihubungkan.')
                if st.button('🔗 Hubungkan Semua yang Dicentang',type='primary',disabled=selected.empty):
                    payload=[]
                    for _,rr in selected.iterrows():
                        payload.append({'store_sku':rr.store_sku,'warehouse_sku':rr.warehouse_sku,'confidence':float(rr.confidence_pct)/100,'notes':'Disetujui dari Bulk Mapping Manager'})
                    n=bulk_save_sku_mappings(conn,sid,payload)
                    st.session_state.pop('bulk_mapping_editor',None)
                    st.success(f'{n} mapping tersimpan. HPP coverage dan Profit Engine sudah dihitung ulang.')
                    st.rerun()

            export_unmapped=unmapped[['store_sku','product_name','qty_realized','orders','sales_idr']].copy()
            st.download_button('⬇️ Download daftar Belum Terhubung (CSV)',export_unmapped.to_csv(index=False).encode('utf-8-sig'),file_name='sku_belum_terhubung.csv',mime='text/csv')

        st.markdown('#### Hubungkan / Koreksi Satu SKU')
        candidates = unmapped if not unmapped.empty else ms
        store_options = candidates.store_sku.tolist()
        if store_options:
            selected_store = st.selectbox('SKU Toko', store_options, format_func=lambda x: f"{x} — {str(candidates[candidates.store_sku==x].iloc[0].product_name)[:90]}", key='single_store_sku')
            row = ms[ms.store_sku==selected_store].iloc[0]
            a,b,c = st.columns([2,1,1])
            a.write(f'**Produk Toko:** {row.product_name}')
            b.metric('Qty Realized', num(row.qty_realized,0))
            c.metric('Sales', rp(row.sales_idr))
            sugg = mapping_suggestions(conn,sid,selected_store,5)
            if not sugg.empty:
                st.markdown('**5 saran pasangan teratas:**')
                sg=sugg.copy(); sg['confidence_pct']=sg.confidence*100
                st.dataframe(sg[['warehouse_sku','warehouse_title','unit_hpp','confidence_pct']].rename(columns={
                    'warehouse_sku':'SKU Gudang','warehouse_title':'Nama SKU Gudang','unit_hpp':'HPP','confidence_pct':'Confidence %'}),hide_index=True,use_container_width=True)
            wh_search=st.text_input('Filter pilihan SKU Gudang',placeholder='Ketik kode atau nama SKU Gudang',key='warehouse_filter').strip().lower()
            wh_pick=wh
            if wh_search:
                mask=wh.sku.astype(str).str.lower().str.contains(wh_search,regex=False)|wh.product_title.astype(str).str.lower().str.contains(wh_search,regex=False)
                wh_pick=wh[mask]
            if wh_pick.empty:
                st.warning('Tidak ada SKU Gudang yang cocok dengan filter.')
            else:
                labels={r.sku:f"{r.sku} — {str(r.product_title)[:90]} — {rp(r.unit_hpp)}" for _,r in wh_pick.iterrows()}
                default_sku = sugg.iloc[0].warehouse_sku if not sugg.empty and sugg.iloc[0].warehouse_sku in wh_pick.sku.tolist() else wh_pick.iloc[0].sku
                idx = wh_pick.sku.tolist().index(default_sku) if default_sku in wh_pick.sku.tolist() else 0
                chosen_wh = st.selectbox('Pilih SKU Gudang', wh_pick.sku.tolist(), index=idx, format_func=lambda x: labels[x],key='single_warehouse_sku')
                chosen_row=wh_pick[wh_pick.sku==chosen_wh].iloc[0]
                st.info(f'Akan dihubungkan: **{selected_store}** → **{chosen_wh}** · {chosen_row.product_title} · HPP {rp(chosen_row.unit_hpp)}')
                notes=st.text_input('Catatan (opsional)', placeholder='Contoh: varian packing kayu yang sama',key='single_mapping_note')
                if st.button('🔗 Hubungkan SKU', type='primary',key='single_map_button'):
                    conf=None
                    if not sugg.empty:
                        hit=sugg[sugg.warehouse_sku==chosen_wh]
                        if not hit.empty: conf=float(hit.iloc[0].confidence)
                    save_sku_mapping(conn,sid,selected_store,chosen_wh,notes=notes,confidence=conf)
                    st.success('Mapping tersimpan. HPP dan Profit Engine sudah dihitung ulang.')
                    st.rerun()

        if not manual.empty:
            st.markdown('#### Mapping Manual Tersimpan')
            backup=manual[['store_sku','product_name','warehouse_sku','warehouse_title','effective_hpp','confidence','notes']].copy()
            st.download_button('⬇️ Backup Mapping Manual (CSV)',backup.to_csv(index=False).encode('utf-8-sig'),file_name='backup_sku_mapping_manual.csv',mime='text/csv')
            edit_sku=st.selectbox('Pilih mapping untuk dihapus', manual.store_sku.tolist(), key='edit_mapping', format_func=lambda x:f"{x} → {manual[manual.store_sku==x].iloc[0].warehouse_sku}")
            er=manual[manual.store_sku==edit_sku].iloc[0]
            st.caption(f'{er.product_name} → {er.warehouse_title} · HPP {rp(er.effective_hpp)}')
            if st.button('🗑️ Hapus Mapping Manual'):
                delete_sku_mapping(conn,sid,edit_sku)
                st.success('Mapping dihapus. SKU kembali memakai exact-code jika tersedia; jika tidak, menjadi belum terhubung.')
                st.rerun()

with tabs[9]:
    st.subheader('Scale Guardrails')
    gr = load_guardrails()
    if _guardrail_suggestions:
        sg=_guardrail_suggestions
        st.markdown('#### Suggested from July–August history')
        c1,c2,c3,c4,c5=st.columns(5)
        c1.metric('Min Control Margin', pct(sg['minimum_margin']))
        c2.metric('Max Paid Ads Cost', pct(sg['maximum_ads_cost_pct']))
        c3.metric('ROAS BEP', f"{sg['roas_bep']:.2f}x")
        c4.metric('Min Safety Ratio', f"{sg['minimum_safety_ratio']:.2f}x")
        c5.metric('Min ROAS', f"{sg['minimum_roas']:.2f}x")
        st.caption('Saran ini tidak diterapkan otomatis. Guardrail final tetap bisa Bapak tetapkan sendiri.')
    with st.form('guardrail_form'):
        c1,c2,c3 = st.columns(3)
        minimum_margin = c1.number_input('Minimum Control Margin (%)', min_value=0.0, max_value=100.0, value=float(gr['minimum_margin']*100), step=0.5) / 100
        minimum_roas = c2.number_input('Minimum ROAS', min_value=0.0, value=float(gr['minimum_roas']), step=0.1)
        roas_bep = c3.number_input('ROAS BEP', min_value=0.0, value=float(gr['roas_bep']), step=0.1)
        c1,c2,c3 = st.columns(3)
        minimum_safety_ratio = c1.number_input('Minimum Safety Ratio', min_value=0.0, value=float(gr['minimum_safety_ratio']), step=0.05)
        maximum_ads_cost_pct = c2.number_input('Maximum Paid Ads Cost (%)', min_value=0.0, max_value=100.0, value=float(gr['maximum_ads_cost_pct']*100), step=0.5) / 100
        recommended_budget = c3.number_input('Recommended Daily Budget (Rp)', min_value=0.0, value=float(gr['recommended_budget']), step=100000.0)
        hard_budget_limit = st.number_input('Hard Daily Budget Limit (Rp, 0 = off)', min_value=0.0, value=float(gr['hard_budget_limit']), step=100000.0)
        submitted = st.form_submit_button('Save Guardrails', type='primary')
        if submitted:
            save_guardrails({
                'minimum_margin':minimum_margin, 'minimum_roas':minimum_roas, 'roas_bep':roas_bep,
                'minimum_safety_ratio':minimum_safety_ratio, 'maximum_ads_cost_pct':maximum_ads_cost_pct,
                'recommended_budget':recommended_budget, 'hard_budget_limit':hard_budget_limit})
            st.success('Guardrails tersimpan.')
            st.rerun()
    st.caption('ROAS adalah safety metric. Keputusan utama tetap profit rupiah, margin, momentum, dan kualitas data.')

from __future__ import annotations
import math
import pandas as pd

try:
    from .readiness import ReadinessInputs, readiness_score
    from .auto_readiness import clamp, ratio_score, trend_score, stability_score
except ImportError:
    from readiness import ReadinessInputs, readiness_score
    from auto_readiness import clamp, ratio_score, trend_score, stability_score


def _v(row, key, default=math.nan):
    try:
        x = row.get(key, default)
        return float(x) if pd.notna(x) else default
    except Exception:
        return default


def _period_days(row):
    try:
        a = pd.to_datetime(row['period_start']).date()
        b = pd.to_datetime(row['period_end']).date()
        return max(1, (b-a).days + 1)
    except Exception:
        return 1


def _daily_window_scores(daily_bi: pd.DataFrame):
    """Momentum/conversion/traffic from BI daily rows only. No profit is fabricated."""
    if daily_bi is None or daily_bi.empty:
        return {'conversion': 50.0, 'sales_momentum': 50.0, 'traffic_quality': 50.0,
                'cr_7d': math.nan, 'sales_7d': math.nan, 'visitors_7d': math.nan}
    d = daily_bi.sort_values('metric_date').copy()
    cur = d.tail(7)
    prev = d.iloc[max(0, len(d)-14):max(0, len(d)-7)]

    def mean(frame, col):
        if col not in frame or frame[col].dropna().empty:
            return math.nan
        return float(pd.to_numeric(frame[col], errors='coerce').mean())

    cr = mean(cur, 'conversion_rate'); cr_prev = mean(prev, 'conversion_rate')
    conv = 0.65*trend_score(cr, cr_prev) + 0.35*(stability_score(cur['conversion_rate']) if 'conversion_rate' in cur else 50)

    sales = mean(cur, 'adjusted_store_sales')
    if pd.isna(sales): sales = mean(cur, 'store_gmv')
    sales_prev = mean(prev, 'adjusted_store_sales')
    if pd.isna(sales_prev): sales_prev = mean(prev, 'store_gmv')
    orders = mean(cur, 'orders'); orders_prev = mean(prev, 'orders')
    momentum = 0.65*trend_score(sales, sales_prev) + 0.35*trend_score(orders, orders_prev)

    visitors = mean(cur, 'visitors'); visitors_prev = mean(prev, 'visitors')
    clicks = mean(cur, 'product_clicks'); clicks_prev = mean(prev, 'product_clicks')
    traffic = 0.55*trend_score(visitors, visitors_prev) + 0.45*trend_score(clicks, clicks_prev)
    return {'conversion': conv, 'sales_momentum': momentum, 'traffic_quality': traffic,
            'cr_7d': cr, 'sales_7d': sales, 'visitors_7d': visitors}


def compute_period_readiness(period_df: pd.DataFrame, daily_bi: pd.DataFrame,
                             minimum_margin: float = 0.20,
                             maximum_ads_cost_pct: float = 0.17,
                             roas_bep: float = 2.52,
                             minimum_safety_ratio: float = 1.25):
    """Preliminary readiness when profit exists only at period grain.

    It intentionally cannot emit an aggressive SCALE decision. It gives a calibrated
    readiness signal and a confidence/capability status. Product Ads ROAS must be present
    in a matching Shopee export before Ads Safety can be considered fully verified.
    """
    if period_df is None or period_df.empty:
        return None
    p = period_df.sort_values('period_end').reset_index(drop=True)
    cur = p.iloc[-1]
    prev = p.iloc[-2] if len(p) >= 2 else None
    days = _period_days(cur)
    prev_days = _period_days(prev) if prev is not None else None

    margin = _v(cur, 'full_paid_media_control_margin')
    profit = _v(cur, 'full_paid_media_control_profit')
    profit_day = profit/days if not pd.isna(profit) else math.nan
    prev_profit_day = (_v(prev, 'full_paid_media_control_profit')/prev_days) if prev is not None and prev_days else math.nan
    profit_margin = 0.65*ratio_score(margin, minimum_margin, 1.35) + 0.35*trend_score(profit_day, prev_profit_day)

    ads_pct = _v(cur, 'paid_ads_cost_pct_realized')
    ads_cost_score = 100 if not pd.isna(ads_pct) and ads_pct <= maximum_ads_cost_pct*0.80 else (
        70 if not pd.isna(ads_pct) and ads_pct <= maximum_ads_cost_pct else
        clamp(70 - ((ads_pct-maximum_ads_cost_pct)/maximum_ads_cost_pct)*120) if maximum_ads_cost_pct and not pd.isna(ads_pct) else 0)
    product_verified = bool(cur.get('product_ads_verified', False))
    channel_complete = bool(cur.get('ads_channels_complete', False))
    product_roas = _v(cur, 'product_ads_roas')
    safety_ratio = product_roas/roas_bep if roas_bep and not pd.isna(product_roas) else math.nan
    roas_score = ratio_score(safety_ratio, minimum_safety_ratio, 1.40) if not pd.isna(safety_ratio) else 50.0
    # Verified Product Ads blends efficiency safety with total paid-cost pressure.
    ads_safety = (0.55*roas_score + 0.45*ads_cost_score) if product_verified else min(65.0, ads_cost_score)

    bi = _daily_window_scores(daily_bi)

    # Completeness: exact-period BI + BigSeller = core; paid channel snapshots add confidence.
    completeness = 55.0
    if not pd.isna(_v(cur, 'adjusted_store_sales')): completeness += 15
    if not pd.isna(profit): completeness += 15
    if product_verified: completeness += 7
    if channel_complete: completeness += 8
    completeness = clamp(completeness)

    x = ReadinessInputs(
        profit_margin_score=profit_margin,
        ads_safety_score=ads_safety,
        conversion_score=bi['conversion'],
        sales_momentum_score=bi['sales_momentum'],
        traffic_quality_score=bi['traffic_quality'],
        data_completeness_score=completeness,
        data_final=False,  # period mode is informative, never equivalent to final daily control
        urgent_ads_risk=bool((not pd.isna(margin) and margin < minimum_margin) or (not pd.isna(ads_pct) and ads_pct > maximum_ads_cost_pct*1.2)),
    )
    score = readiness_score(x)

    if x.urgent_ads_risk:
        action = 'REDUCE / DEFEND PROFIT'
    elif score >= 80:
        action = 'KEEP · SCALE CANDIDATE (NEEDS DAILY VERIFICATION)'
    elif score >= 65:
        action = 'KEEP'
    elif score >= 50:
        action = 'HOLD / DEFEND PROFIT'
    else:
        action = 'REDUCE'

    return {
        'score': score,
        'action': action,
        'mode': 'PERIOD_PRELIMINARY',
        'scale_allowed': False,
        'product_ads_verified': product_verified,
        'ads_channels_complete': channel_complete,
        'components': {
            'Profit & Margin': round(profit_margin,1),
            'Ads Safety': round(ads_safety,1),
            'Conversion': round(bi['conversion'],1),
            'Sales Momentum': round(bi['sales_momentum'],1),
            'Traffic Quality': round(bi['traffic_quality'],1),
            'Data Completeness': round(completeness,1),
        },
        'diagnostics': {
            'control_margin': margin,
            'control_profit': profit,
            'profit_per_day': profit_day,
            'profit_per_day_previous': prev_profit_day,
            'paid_ads_cost_pct': ads_pct,
            'product_ads_roas': product_roas,
            'product_ads_safety_ratio': safety_ratio,
            'cr_7d': bi['cr_7d'],
            'adjusted_sales_per_day_7d': bi['sales_7d'],
            'visitors_per_day_7d': bi['visitors_7d'],
        },
        'limitations': [
            'Profit BigSeller tersedia pada grain periode, bukan harian.',
            *([] if product_verified else ['Product Ads Shopee periode yang sama belum tersedia untuk verifikasi ROAS/atribusi.']),
            'Mode periode tidak pernah mengeluarkan rekomendasi SCALE agresif.'
        ]
    }


def suggested_guardrails(period_df: pd.DataFrame):
    """Data-driven suggestions; does not overwrite saved settings."""
    if period_df is None or period_df.empty:
        return None
    p = period_df.copy()
    margins = pd.to_numeric(p.get('full_paid_media_control_margin'), errors='coerce').dropna()
    ads_pct = pd.to_numeric(p.get('paid_ads_cost_pct_realized'), errors='coerce').dropna()
    # 85% of the weakest observed healthy margin provides a buffer without anchoring to one month.
    min_margin = max(0.10, float(margins.min())*0.85) if not margins.empty else 0.15
    max_ads = min(0.25, float(ads_pct.max())*1.10) if not ads_pct.empty else 0.17

    # Break-even ROAS from pre-product-ads contribution margin when available.
    beps=[]
    if 'gp_before_product_ads' in p and 'realized_sales' in p:
        for _,r in p.iterrows():
            gp=_v(r,'gp_before_product_ads'); sales=_v(r,'realized_sales')
            cm=gp/sales if sales and not pd.isna(gp) else math.nan
            if not pd.isna(cm) and cm>0: beps.append(1/cm)
    roas_bep=max(beps) if beps else 3.0
    return {
        'minimum_margin': round(min_margin,4),
        'maximum_ads_cost_pct': round(max_ads,4),
        'roas_bep': round(roas_bep,2),
        'minimum_safety_ratio': 1.25,
        'minimum_roas': round(max(roas_bep*1.25, 4.0),2),
        'note': 'Saran berbasis histori; tidak diterapkan otomatis.'
    }

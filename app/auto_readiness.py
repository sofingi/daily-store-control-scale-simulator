from __future__ import annotations
from dataclasses import dataclass
import math
import pandas as pd

try:
    from .readiness import ReadinessInputs, readiness_score, recommendation
except ImportError:
    from readiness import ReadinessInputs, readiness_score, recommendation


def clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, float(v)))


def ratio_score(value, floor, good_multiplier=1.35):
    if value is None or pd.isna(value) or floor <= 0:
        return 0.0
    if value <= 0:
        return 0.0
    good = floor * good_multiplier
    if value >= good:
        return 100.0
    if value <= floor:
        return clamp(50.0 * value / floor)
    return 50.0 + 50.0 * (value - floor) / (good - floor)


def trend_score(current, previous, neutral=60.0):
    if previous is None or pd.isna(previous) or previous == 0 or current is None or pd.isna(current):
        return neutral
    growth = current / previous - 1
    # -20% -> 0, 0% -> 60, +20% -> 100; capped.
    if growth >= 0:
        return clamp(60 + 200 * growth)
    return clamp(60 + 300 * growth)


def stability_score(series: pd.Series, target_cv=0.15):
    s = pd.to_numeric(series, errors='coerce').dropna()
    if len(s) < 3 or s.mean() == 0:
        return 50.0
    cv = abs(s.std(ddof=0) / s.mean())
    return clamp(100 - (cv / target_cv) * 40)


def _mean(df, col):
    return float(pd.to_numeric(df[col], errors='coerce').mean()) if col in df and not df[col].dropna().empty else math.nan


def compute_readiness(df: pd.DataFrame, minimum_margin: float, roas_bep: float, minimum_safety_ratio: float, maximum_ads_cost_pct: float):
    """Transparent V1 heuristic. Expects chronological merged daily rows."""
    if df.empty:
        return None
    d = df.sort_values('metric_date').copy()
    cur = d.tail(7)
    prev = d.iloc[max(0, len(d)-14):max(0, len(d)-7)]

    margin = _mean(cur, 'full_paid_media_control_margin') if 'full_paid_media_control_margin' in cur else _mean(cur, 'control_margin')
    profit = _mean(cur, 'full_paid_media_control_profit') if 'full_paid_media_control_profit' in cur else _mean(cur, 'control_profit')
    profit_prev = (_mean(prev, 'full_paid_media_control_profit') if 'full_paid_media_control_profit' in prev else _mean(prev, 'control_profit')) if not prev.empty else math.nan
    _pcol = 'full_paid_media_control_profit' if 'full_paid_media_control_profit' in cur else 'control_profit'
    positive_profit_ratio = float((pd.to_numeric(cur.get(_pcol), errors='coerce') > 0).mean()) if _pcol in cur else 0
    margin_score = ratio_score(margin, minimum_margin, 1.40)
    p_trend = trend_score(profit, profit_prev)
    p_consistency = positive_profit_ratio * 100
    profit_margin_score = 0.55*margin_score + 0.25*p_trend + 0.20*p_consistency

    roas = _mean(cur, 'roas')
    safety = roas / roas_bep if roas_bep else 0
    gmv = _mean(cur, 'store_gmv')
    spend = _mean(cur, 'ads_spend')
    ads_pct = spend/gmv if gmv and not pd.isna(gmv) else math.nan
    roas_score = ratio_score(roas, roas_bep, 1.35)
    safety_score = ratio_score(safety, minimum_safety_ratio, 1.25)
    ads_cost_score = 100 if not pd.isna(ads_pct) and ads_pct <= maximum_ads_cost_pct*0.75 else (
        65 if not pd.isna(ads_pct) and ads_pct <= maximum_ads_cost_pct else clamp(65 - ((ads_pct-maximum_ads_cost_pct)/maximum_ads_cost_pct)*100) if maximum_ads_cost_pct else 0)
    roas_stability = stability_score(cur['roas']) if 'roas' in cur else 50
    ads_safety_score = 0.40*roas_score + 0.25*safety_score + 0.20*ads_cost_score + 0.15*roas_stability

    cr = _mean(cur, 'conversion_rate')
    cr_prev = _mean(prev, 'conversion_rate') if not prev.empty else math.nan
    conversion_score = 0.65*trend_score(cr, cr_prev) + 0.35*(stability_score(cur['conversion_rate']) if 'conversion_rate' in cur else 50)

    sales = _mean(cur, 'store_gmv')
    sales_prev = _mean(prev, 'store_gmv') if not prev.empty else math.nan
    orders = _mean(cur, 'orders')
    orders_prev = _mean(prev, 'orders') if not prev.empty else math.nan
    sales_momentum_score = 0.50*trend_score(sales, sales_prev) + 0.25*trend_score(orders, orders_prev) + 0.25*p_trend

    visitors = _mean(cur, 'visitors')
    visitors_prev = _mean(prev, 'visitors') if not prev.empty else math.nan
    rpm = _mean(cur, 'rpm')
    rpm_prev = _mean(prev, 'rpm') if not prev.empty else math.nan
    cpc = _mean(cur, 'cpc')
    cpc_prev = _mean(prev, 'cpc') if not prev.empty else math.nan
    cpc_score = 60.0 if pd.isna(cpc_prev) or not cpc_prev else clamp(60 - 200*(cpc/cpc_prev-1))
    traffic_quality_score = 0.35*trend_score(visitors, visitors_prev) + 0.35*trend_score(rpm, rpm_prev) + 0.30*cpc_score

    conf = _mean(cur, 'confidence_score')
    data_completeness_score = 0 if pd.isna(conf) else clamp(conf)

    inputs = ReadinessInputs(
        profit_margin_score=profit_margin_score,
        ads_safety_score=ads_safety_score,
        conversion_score=conversion_score,
        sales_momentum_score=sales_momentum_score,
        traffic_quality_score=traffic_quality_score,
        data_completeness_score=data_completeness_score,
        data_final=bool((cur.get('overall_status', pd.Series(['MISSING'])) == 'FINAL').all()),
        urgent_ads_risk=bool((not pd.isna(roas) and roas < roas_bep) or (not pd.isna(ads_pct) and ads_pct > maximum_ads_cost_pct*1.20)),
    )
    score = readiness_score(inputs)
    rec = recommendation(score, inputs.data_final, inputs.urgent_ads_risk)
    return {
        'score': score,
        'recommendation': rec,
        'data_final': inputs.data_final,
        'urgent_ads_risk': inputs.urgent_ads_risk,
        'components': {
            'Profit & Margin': round(profit_margin_score,1),
            'Ads Safety': round(ads_safety_score,1),
            'Conversion': round(conversion_score,1),
            'Sales Momentum': round(sales_momentum_score,1),
            'Traffic Quality': round(traffic_quality_score,1),
            'Data Completeness': round(data_completeness_score,1),
        },
        'diagnostics': {
            'margin_7d': margin, 'profit_7d': profit, 'roas_7d': roas,
            'safety_ratio_7d': safety, 'ads_cost_pct_7d': ads_pct,
            'cr_7d': cr, 'gmv_7d': sales, 'visitors_7d': visitors,
        }
    }

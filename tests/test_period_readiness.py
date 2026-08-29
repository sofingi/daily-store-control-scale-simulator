import pandas as pd
from app.period_readiness import compute_period_readiness, suggested_guardrails


def test_period_readiness_never_scales_aggressively_without_daily_profit():
    p=pd.DataFrame([
        {'period_start':'2026-07-01','period_end':'2026-07-31','realized_sales':447381878,'full_paid_media_control_profit':107163619,'full_paid_media_control_margin':0.2395,'paid_ads_cost_pct_realized':0.1427,'product_ads_verified':True,'ads_channels_complete':True,'gp_before_product_ads':177580337},
        {'period_start':'2026-08-01','period_end':'2026-08-28','realized_sales':381090338,'full_paid_media_control_profit':107437233,'full_paid_media_control_margin':0.2819,'paid_ads_cost_pct_realized':0.1474,'product_ads_verified':False,'ads_channels_complete':False,'gp_before_product_ads':169254812},
    ])
    d=pd.DataFrame({'metric_date':pd.date_range('2026-08-15', periods=14), 'adjusted_store_sales':[10e6]*7+[11e6]*7,'orders':[100]*7+[105]*7,'conversion_rate':[.018]*7+[.019]*7,'visitors':[20000]*14,'product_clicks':[6000]*14})
    r=compute_period_readiness(p,d,minimum_margin=.20,maximum_ads_cost_pct=.17)
    assert r['scale_allowed'] is False
    assert 'SCALE +' not in r['action']
    assert r['product_ads_verified'] is False


def test_guardrail_suggestions_are_profit_first():
    p=pd.DataFrame([
        {'realized_sales':447381878,'full_paid_media_control_margin':0.2395,'paid_ads_cost_pct_realized':0.1427,'gp_before_product_ads':177580337},
        {'realized_sales':381090338,'full_paid_media_control_margin':0.2819,'paid_ads_cost_pct_realized':0.1474,'gp_before_product_ads':169254812},
    ])
    g=suggested_guardrails(p)
    assert 0.19 < g['minimum_margin'] < 0.22
    assert 0.15 < g['maximum_ads_cost_pct'] < 0.18
    assert 2.0 < g['roas_bep'] < 3.0

def test_verified_product_roas_strengthens_ads_safety():
    p=pd.DataFrame([{'period_start':'2026-08-01','period_end':'2026-08-28','realized_sales':381090338,'full_paid_media_control_profit':108296485,'full_paid_media_control_margin':0.2842,'paid_ads_cost_pct_realized':0.1451,'product_ads_verified':True,'product_ads_roas':7.862,'ads_channels_complete':True,'gp_before_product_ads':169254812}])
    d=pd.DataFrame({'metric_date':pd.date_range('2026-08-15', periods=14), 'adjusted_store_sales':[10e6]*7+[11e6]*7,'orders':[100]*7+[105]*7,'conversion_rate':[.018]*7+[.019]*7,'visitors':[20000]*14,'product_clicks':[6000]*14})
    r=compute_period_readiness(p,d,minimum_margin=.20,maximum_ads_cost_pct=.17,roas_bep=2.52,minimum_safety_ratio=1.25)
    assert r['components']['Ads Safety'] > 80
    assert r['diagnostics']['product_ads_safety_ratio'] > 3

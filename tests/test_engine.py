from app.engine import Baseline, Guardrails, simulate_scale
from app.readiness import ReadinessInputs, readiness_score, recommendation

def test_ads_sales_not_added_directly_to_store_gmv():
    b = Baseline(
        store_gmv=10_000_000,
        ads_spend=1_000_000,
        ads_sales=6_000_000,
        roas=6.0,
        control_profit=2_000_000,
        contribution_margin_before_ads=0.30,
    )
    g = Guardrails()
    r = simulate_scale(b, 0.20, 'realistic', g)
    assert r['store_gmv'] < 10_000_000 + r['ads_sales']


def test_partial_data_blocks_scale():
    x = ReadinessInputs(100,100,100,100,100,100,data_final=False)
    s = readiness_score(x)
    assert s == 100.0
    assert recommendation(s, x.data_final) == 'WAIT FOR DATA SYNC'

from app.engine import choose_daily_action

def test_choose_action_waits_when_data_not_final():
    b = Baseline(10_000_000,1_000_000,8_000_000,8.0,2_000_000,.30,confidence=95,data_final=False)
    r = choose_daily_action(b,95,Guardrails(minimum_margin=.10,minimum_roas=4,roas_bep=4,minimum_safety_ratio=1.15,maximum_ads_cost_pct=.15))
    assert r['action']=='WAIT FOR DATA SYNC'

def test_choose_action_can_scale_when_guardrails_pass():
    b = Baseline(10_000_000,800_000,8_000_000,10.0,2_500_000,.60,confidence=95,data_final=True)
    r = choose_daily_action(b,90,Guardrails(minimum_margin=.10,minimum_roas=4,roas_bep=4,minimum_safety_ratio=1.15,maximum_ads_cost_pct=.15))
    assert r['action'].startswith('SCALE +')


def test_merge_hpp_sources_primary_wins_and_fallback_fills():
    import pandas as pd
    from app.profit_v16 import merge_hpp_sources
    p=pd.DataFrame([{'sku':'A','product_title':'a','unit_hpp':10,'sku_type':'MASTER'}])
    f=pd.DataFrame([{'sku':'A','product_title':'a2','unit_hpp':99,'sku_type':'FALLBACK'}, {'sku':'B','product_title':'b','unit_hpp':20,'sku_type':'FALLBACK'}])
    x=merge_hpp_sources(p,f).set_index('sku')
    assert x.loc['A','unit_hpp']==10
    assert x.loc['B','unit_hpp']==20


def test_hpp_coverage_audit_ignores_cancelled_qty():
    import pandas as pd
    from app.profit_v16 import hpp_coverage_audit
    o=pd.DataFrame([
      {'order_id':'1','order_status':'Selesai','sku':'A','product_name':'A','qty':2,'returned_qty':0},
      {'order_id':'2','order_status':'Batal','sku':'X','product_name':'X','qty':5,'returned_qty':0},
    ])
    h=pd.DataFrame([{'sku':'A','unit_hpp':10}])
    a=hpp_coverage_audit(o,h)
    assert a['qty_coverage']==1.0
    assert a['unmatched_unique_skus']==0

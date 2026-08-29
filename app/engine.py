from dataclasses import dataclass
from typing import Literal, Dict

Scenario = Literal['optimistic', 'realistic', 'conservative']

@dataclass
class Guardrails:
    minimum_margin: float = 0.10
    minimum_roas: float = 5.0
    roas_bep: float = 4.0
    minimum_safety_ratio: float = 1.15
    maximum_ads_cost_pct: float = 0.12
    recommended_budget: float = 0.0
    hard_budget_limit: float = 0.0

@dataclass
class Baseline:
    store_gmv: float
    ads_spend: float
    ads_sales: float
    roas: float
    control_profit: float
    contribution_margin_before_ads: float
    confidence: float = 100.0
    data_final: bool = True

SCENARIOS: Dict[Scenario, dict] = {
    'optimistic': {'decay': 0.25, 'incrementality': 0.80},
    'realistic': {'decay': 0.60, 'incrementality': 0.60},
    'conservative': {'decay': 1.00, 'incrementality': 0.40},
}

def safe_div(a: float, b: float, default: float = 0.0) -> float:
    return a / b if b else default


def simulate_scale(b: Baseline, budget_change_pct: float, scenario: Scenario, g: Guardrails):
    p = SCENARIOS[scenario]
    d = budget_change_pct
    new_spend = b.ads_spend * (1 + d)
    projected_roas = max(0.0, b.roas * (1 - p['decay'] * d))
    projected_ads_sales = new_spend * projected_roas
    incremental_ads_sales = projected_ads_sales - b.ads_sales
    incremental_store_gmv = max(0.0, incremental_ads_sales) * p['incrementality']
    projected_store_gmv = b.store_gmv + incremental_store_gmv
    incremental_gross_profit = incremental_store_gmv * b.contribution_margin_before_ads
    incremental_ad_cost = new_spend - b.ads_spend
    projected_profit = b.control_profit + incremental_gross_profit - incremental_ad_cost
    projected_margin = safe_div(projected_profit, projected_store_gmv)
    ads_cost_pct = safe_div(new_spend, projected_store_gmv)
    safety_ratio = safe_div(projected_roas, g.roas_bep)

    failures = []
    if projected_margin < g.minimum_margin:
        failures.append('margin')
    if projected_roas < max(g.minimum_roas, g.roas_bep):
        failures.append('roas')
    if safety_ratio < g.minimum_safety_ratio:
        failures.append('safety_ratio')
    if ads_cost_pct > g.maximum_ads_cost_pct:
        failures.append('ads_cost_pct')
    if g.hard_budget_limit > 0 and new_spend > g.hard_budget_limit:
        failures.append('hard_budget_limit')
    if not b.data_final:
        failures.append('data_not_final')

    near_threshold = (
        projected_margin < g.minimum_margin * 1.15
        or projected_roas < max(g.minimum_roas, g.roas_bep) * 1.15
        or safety_ratio < g.minimum_safety_ratio * 1.15
        or ads_cost_pct > g.maximum_ads_cost_pct / 1.15
    )

    if failures or b.confidence < 70:
        risk = 'HIGH'
    elif near_threshold or b.confidence < 85:
        risk = 'MEDIUM'
    else:
        risk = 'LOW'

    return {
        'scenario': scenario,
        'budget_change_pct': d,
        'ads_spend': new_spend,
        'roas': projected_roas,
        'ads_sales': projected_ads_sales,
        'store_gmv': projected_store_gmv,
        'profit': projected_profit,
        'margin': projected_margin,
        'additional_profit': projected_profit - b.control_profit,
        'ads_cost_pct': ads_cost_pct,
        'safety_ratio': safety_ratio,
        'risk_level': risk,
        'guardrail_failures': failures,
    }


def passes_guardrails(result: dict) -> bool:
    return not result.get('guardrail_failures') and result.get('profit', 0) > 0 and result.get('additional_profit', 0) >= 0

def choose_daily_action(b: Baseline, readiness_score: float, g: Guardrails):
    """Choose an actionable V1 recommendation from readiness + simulator.
    Never scales on non-final / low-confidence data. For scaling, the realistic
    scenario must pass all guardrails and the conservative scenario must not
    destroy profit or minimum margin.
    """
    if not b.data_final or b.confidence < 70:
        return {'action':'WAIT FOR DATA SYNC','budget_change_pct':0.0,'reason':'Data belum final / confidence rendah'}
    current_ads_cost=safe_div(b.ads_spend,b.store_gmv)
    current_safety=safe_div(b.roas,g.roas_bep)
    if b.control_profit <= 0 or b.roas < g.roas_bep or current_safety < 1.0 or current_ads_cost > g.maximum_ads_cost_pct*1.20:
        return {'action':'REDUCE','budget_change_pct':-0.10,'reason':'Guardrail profit/ads saat ini terlanggar'}
    if readiness_score < 50:
        return {'action':'REDUCE','budget_change_pct':-0.10,'reason':'Readiness < 50'}
    if readiness_score < 65:
        return {'action':'HOLD / DEFEND PROFIT','budget_change_pct':0.0,'reason':'Readiness 50–64'}
    if readiness_score < 80:
        return {'action':'KEEP','budget_change_pct':0.0,'reason':'Sehat, tetapi readiness belum cukup untuk scale'}
    best=None
    for pct in (0.10,0.20,0.30):
        real=simulate_scale(b,pct,'realistic',g)
        cons=simulate_scale(b,pct,'conservative',g)
        conservative_ok=(cons['profit']>0 and cons['margin']>=g.minimum_margin and cons['roas']>=g.roas_bep)
        if passes_guardrails(real) and conservative_ok:
            best=(pct,real,cons)
    if best:
        pct,real,cons=best
        return {'action':f'SCALE +{int(pct*100)}%','budget_change_pct':pct,'reason':'Realistic lolos guardrail; konservatif tetap profitable','realistic':real,'conservative':cons}
    return {'action':'KEEP','budget_change_pct':0.0,'reason':'Readiness tinggi, tetapi simulasi scale belum lolos guardrail'}

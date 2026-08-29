from dataclasses import dataclass

@dataclass
class ReadinessInputs:
    profit_margin_score: float
    ads_safety_score: float
    conversion_score: float
    sales_momentum_score: float
    traffic_quality_score: float
    data_completeness_score: float
    data_final: bool = True
    urgent_ads_risk: bool = False

WEIGHTS = {
    'profit_margin_score': 0.30,
    'ads_safety_score': 0.20,
    'conversion_score': 0.15,
    'sales_momentum_score': 0.15,
    'traffic_quality_score': 0.10,
    'data_completeness_score': 0.10,
}

def clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


def readiness_score(x: ReadinessInputs) -> float:
    total = sum(clamp(getattr(x, k)) * w for k, w in WEIGHTS.items())
    return round(total, 1)


def recommendation(score: float, data_final: bool, urgent_ads_risk: bool = False) -> str:
    if not data_final:
        return 'REDUCE' if urgent_ads_risk else 'WAIT FOR DATA SYNC'
    if score >= 80:
        return 'SCALE CANDIDATE'
    if score >= 65:
        return 'KEEP'
    if score >= 50:
        return 'HOLD / DEFEND PROFIT'
    return 'REDUCE'

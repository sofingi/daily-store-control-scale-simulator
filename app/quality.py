from datetime import date
from typing import Optional


def source_status(has_data: bool, metric_date: date, latest_known_date: Optional[date], suspicious: bool=False, source='GENERIC') -> str:
    if not has_data:
        return 'MISSING'
    if suspicious:
        return 'PARTIAL'
    if source == 'BIGSELLER' and latest_known_date:
        lag = (latest_known_date - metric_date).days
        if lag <= 1:
            return 'BELUM_FINAL'
    return 'FINAL'


def confidence_score(bi_status: str, ads_status: str, bs_status: str, cross_consistent: bool=True) -> float:
    weight = {'bi':30, 'ads':20, 'bs':40, 'cross':10}
    factor = {'FINAL':1.0, 'BELUM_FINAL':0.55, 'PARTIAL':0.35, 'MISSING':0.0}
    score = (
        weight['bi'] * factor.get(bi_status, 0)
        + weight['ads'] * factor.get(ads_status, 0)
        + weight['bs'] * factor.get(bs_status, 0)
        + weight['cross'] * (1.0 if cross_consistent else 0.25)
    )
    return round(score, 1)


def overall_status(bi_status: str, ads_status: str, bs_status: str) -> str:
    statuses = {bi_status, ads_status, bs_status}
    if 'MISSING' in statuses:
        return 'MISSING'
    if 'PARTIAL' in statuses:
        return 'PARTIAL'
    if bs_status == 'BELUM_FINAL' or 'BELUM_FINAL' in statuses:
        return 'BELUM_FINAL'
    return 'FINAL'

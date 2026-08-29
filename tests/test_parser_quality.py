import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from parser import read_tabular
from quality import confidence_score, overall_status


def test_business_insight_csv_parses_and_aggregates():
    csv = b'Tanggal,Omzet,Pesanan,Pengunjung\n2026-08-20,1000000,10,200\n2026-08-21,1200000,12,220\n'
    r = read_tabular(csv, 'bi.csv', 'BUSINESS_INSIGHT')
    assert len(r.dataframe) == 2
    assert float(r.dataframe.iloc[0]['store_gmv']) == 1000000
    assert round(float(r.dataframe.iloc[0]['conversion_rate']),4) == 0.05


def test_ads_sales_is_derived_not_added_to_gmv_contract():
    csv = b'Tanggal,Biaya,Penjualan,Impresi,Klik\n2026-08-20,100000,800000,10000,300\n'
    r = read_tabular(csv, 'ads.csv', 'SHOPEE_ADS')
    row = r.dataframe.iloc[0]
    assert float(row['roas']) == 8.0
    assert 'store_gmv' not in r.dataframe.columns


def test_confidence_penalizes_bigseller_not_final():
    score = confidence_score('FINAL','FINAL','BELUM_FINAL',True)
    assert score < 100
    assert overall_status('FINAL','FINAL','BELUM_FINAL') == 'BELUM_FINAL'


def test_readiness_data_gate_blocks_scale():
    from auto_readiness import compute_readiness
    df = pd.DataFrame({
        'metric_date': pd.date_range('2026-08-01', periods=14),
        'control_margin': [0.2]*14,
        'control_profit': [1000000+i*10000 for i in range(14)],
        'roas': [8.0]*14,
        'store_gmv': [5000000+i*50000 for i in range(14)],
        'ads_spend': [400000]*14,
        'conversion_rate': [0.05]*14,
        'orders': [50+i for i in range(14)],
        'visitors': [1000+i*10 for i in range(14)],
        'rpm': [80000]*14,
        'cpc': [500]*14,
        'confidence_score': [80]*14,
        'overall_status': ['FINAL']*13 + ['BELUM_FINAL'],
    })
    r = compute_readiness(df, 0.10, 4.0, 1.15, 0.12)
    assert r['score'] >= 65
    assert r['recommendation'] == 'WAIT FOR DATA SYNC'

from pathlib import Path
from app.parser import read_tabular

ROOT=Path('/mnt/data')
def b(name): return (ROOT/name).read_bytes()

def test_real_business_insight_values():
    r=read_tabular(b('gerabahkujogja.shopee-shop-stats.20260701-20260731.xlsx'),'bi.xlsx','BUSINESS_INSIGHT')
    x=r.dataframe.iloc[0]
    assert x['store_gmv']==19572225
    assert round(x['conversion_rate'],4)==0.0206
    assert x['adjusted_store_sales']==16285025

def test_real_product_ads_daily():
    r=read_tabular(b('Data+Keseluruhan+Iklan+Shopee-31_07_2026-31_07_2026.csv'),'ads.csv','SHOPEE_ADS_PRODUCT')
    x=r.dataframe.iloc[0]
    assert x['ads_spend']==2312932
    assert x['ads_sales']==17655219
    assert round(x['roas'],2)==7.63

def test_real_bigseller_store_period():
    r=read_tabular(b('Keuntungan-Toko-20260828232754849.xlsx'),'bs.xlsx','BIGSELLER_STORE')
    x=r.dataframe.iloc[0]
    assert r.granularity=='PERIOD'
    assert round(x['store_profit_reported'])==117620475
    assert round(abs(x['product_ads_in_bigseller']))==59959862
    assert round(x['gpmi'])==111024890

def test_v16_order_and_hpp_parsers():
    from app.profit_v16 import parse_shopee_orders,parse_bigseller_hpp_master,attach_hpp
    o=parse_shopee_orders(b('Order.all.20260801_20260828.xlsx'))
    h=parse_bigseller_hpp_master(b('SKU_Gudang20260820003830008_Bigseller(2).xlsx'))
    x=attach_hpp(o,h)
    assert o.order_id.nunique()==4514
    assert len(h)>2000
    assert x.hpp_known.mean()>0.90

def test_v16_income_parser_reads_broken_dimension_sheet():
    from app.profit_v16 import parse_income_detail
    x=parse_income_detail(b('Income.sudah dilepas.id.20260801_20260828.xlsx'))
    assert len(x)>8000
    assert x.order_id.nunique()>4000
    assert x['Total Penghasilan'].notna().mean()>0.99

from pathlib import Path
import pandas as pd
from app.database import connect, init_db, get_store_id, upsert_rows
from app.service import save_sku_mapping, delete_sku_mapping, list_sku_mapping_status, mapping_suggestions


def seed(tmp_path):
    db=tmp_path/'map.db'; conn=connect(db); init_db(conn); sid=get_store_id(conn)
    upsert_rows(conn,'sku_hpp_master',[{
        'store_id':sid,'sku':'WH-PANCI-20-KAYU','product_title':'[Packing Kayu] Panci Tanah Liat 20 cm 2.5 Liter',
        'unit_hpp':42000,'sku_type':'SKU Tunggal','source_batch_id':None
    },{
        'store_id':sid,'sku':'WH-COBEK-20','product_title':'Cobek Tanah Liat 20 cm',
        'unit_hpp':12000,'sku_type':'SKU Tunggal','source_batch_id':None
    }],('store_id','sku'))
    upsert_rows(conn,'order_lines_v16',[{
        'store_id':sid,'order_id':'O1','order_date':'2026-08-01','order_status':'Selesai',
        'sku':'PANCI-20CM-2.5L+KAYU','product_name':'Panci Tanah Liat 20cm 2.5L Packing Kayu',
        'qty':2,'returned_qty':0,'net_qty':2,'unit_price_idr':100000,'line_sales_idr':200000,
        'unit_hpp':None,'line_hpp':None,'hpp_known':0,'source_batch_id':None
    }],('store_id','order_id','sku','product_name','unit_price_idr'))
    return conn,sid


def test_manual_mapping_applies_hpp(tmp_path):
    conn,sid=seed(tmp_path)
    before=list_sku_mapping_status(conn,sid)
    assert before.iloc[0].mapping_status=='UNMAPPED'
    save_sku_mapping(conn,sid,'PANCI-20CM-2.5L+KAYU','WH-PANCI-20-KAYU')
    row=conn.execute("SELECT unit_hpp,line_hpp,hpp_known FROM order_lines_v16 WHERE store_id=?",(sid,)).fetchone()
    assert row['unit_hpp']==42000
    assert row['line_hpp']==84000
    assert row['hpp_known']==1
    after=list_sku_mapping_status(conn,sid)
    assert after.iloc[0].mapping_status=='MAPPED_MANUAL'


def test_delete_mapping_returns_unmapped(tmp_path):
    conn,sid=seed(tmp_path)
    save_sku_mapping(conn,sid,'PANCI-20CM-2.5L+KAYU','WH-PANCI-20-KAYU')
    delete_sku_mapping(conn,sid,'PANCI-20CM-2.5L+KAYU')
    x=list_sku_mapping_status(conn,sid)
    assert x.iloc[0].mapping_status=='UNMAPPED'


def test_suggestion_prefers_matching_variant(tmp_path):
    conn,sid=seed(tmp_path)
    s=mapping_suggestions(conn,sid,'PANCI-20CM-2.5L+KAYU',2)
    assert s.iloc[0].warehouse_sku=='WH-PANCI-20-KAYU'
    assert s.iloc[0].confidence > s.iloc[1].confidence

from app.database import connect, init_db, get_store_id, upsert_rows
from app.service import bulk_save_sku_mappings, batch_mapping_suggestions, list_sku_mapping_status


def seed(tmp_path):
    db=tmp_path/'bulk.db'; conn=connect(db); init_db(conn); sid=get_store_id(conn)
    upsert_rows(conn,'sku_hpp_master',[
        {'store_id':sid,'sku':'PE-FOAM-1MM-METERAN','product_title':'PE Foam 1mm Meteran','unit_hpp':1500,'sku_type':'SKU Tunggal','source_batch_id':None},
        {'store_id':sid,'sku':'COBEK-20CM','product_title':'Cobek Tanah Liat 20 cm','unit_hpp':12000,'sku_type':'SKU Tunggal','source_batch_id':None},
    ],('store_id','sku'))
    upsert_rows(conn,'order_lines_v16',[
        {'store_id':sid,'order_id':'O1','order_date':'2026-08-01','order_status':'Selesai','sku':'PE-FOAM-1-MM','product_name':'PE Foam 1mm Meteran','qty':2,'returned_qty':0,'net_qty':2,'unit_price_idr':5000,'line_sales_idr':10000,'unit_hpp':None,'line_hpp':None,'hpp_known':0,'source_batch_id':None},
        {'store_id':sid,'order_id':'O2','order_date':'2026-08-01','order_status':'Selesai','sku':'CBK20','product_name':'Cobek Tanah Liat Diameter 20cm','qty':1,'returned_qty':0,'net_qty':1,'unit_price_idr':30000,'line_sales_idr':30000,'unit_hpp':None,'line_hpp':None,'hpp_known':0,'source_batch_id':None},
    ],('store_id','order_id','sku','product_name','unit_price_idr'))
    return conn,sid


def test_batch_suggestions_are_read_only(tmp_path):
    conn,sid=seed(tmp_path)
    s=batch_mapping_suggestions(conn,sid,limit_per_sku=1)
    assert len(s)==2
    assert conn.execute('SELECT COUNT(*) FROM sku_store_mapping_v18').fetchone()[0]==0
    pe=s[s.store_sku=='PE-FOAM-1-MM'].iloc[0]
    assert pe.warehouse_sku=='PE-FOAM-1MM-METERAN'


def test_bulk_save_rebuilds_hpp_once_and_maps_all(tmp_path):
    conn,sid=seed(tmp_path)
    n=bulk_save_sku_mappings(conn,sid,[
        {'store_sku':'PE-FOAM-1-MM','warehouse_sku':'PE-FOAM-1MM-METERAN','confidence':.95},
        {'store_sku':'CBK20','warehouse_sku':'COBEK-20CM','confidence':.90},
    ])
    assert n==2
    st=list_sku_mapping_status(conn,sid)
    assert set(st.mapping_status)=={'MAPPED_MANUAL'}
    hpps=dict(conn.execute('SELECT sku,unit_hpp FROM order_lines_v16').fetchall())
    assert hpps['PE-FOAM-1-MM']==1500
    assert hpps['CBK20']==12000

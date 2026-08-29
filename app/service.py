from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
try:
    from .database import connect,init_db,get_store_id,upsert_rows
    from .parser import read_tabular,sha256_bytes
    from .quality import confidence_score,overall_status
    from .profit_v16 import parse_shopee_orders,parse_bigseller_hpp_master,parse_income_detail,attach_hpp,order_level_economics,daily_profit_from_orders
    from .sku_mapping import suggest_candidates
except ImportError:
    from database import connect,init_db,get_store_id,upsert_rows
    from parser import read_tabular,sha256_bytes
    from quality import confidence_score,overall_status
    from profit_v16 import parse_shopee_orders,parse_bigseller_hpp_master,parse_income_detail,attach_hpp,order_level_economics,daily_profit_from_orders
    from sku_mapping import suggest_candidates

CHANNEL={'SHOPEE_ADS_PRODUCT':'PRODUCT','SHOPEE_ADS_LIVE':'LIVE','SHOPEE_ADS_SHOP_PLUS':'SHOP_PLUS'}

def _insert_batch(conn,sid,source,filename,file_bytes,row_count=0,min_date=None,max_date=None,granularity='DAILY',notes=''):
    h=sha256_bytes(file_bytes)
    old=conn.execute('SELECT id FROM import_batches WHERE store_id=? AND file_hash=?',(sid,h)).fetchone()
    if old:return None,h
    b=conn.execute('INSERT INTO import_batches(store_id,source,filename,file_hash,row_count,min_date,max_date,granularity,notes) VALUES(?,?,?,?,?,?,?,?,?)',(sid,source,filename,h,row_count,str(min_date) if min_date else None,str(max_date) if max_date else None,granularity,notes)).lastrowid
    conn.commit(); return b,h

def _reload_hpp_on_orders(conn,sid):
    """Resolve HPP with priority: manual mapping > exact SKU code > unknown."""
    conn.execute('UPDATE order_lines_v16 SET unit_hpp=NULL,line_hpp=NULL,hpp_known=0 WHERE store_id=?',(sid,))
    conn.execute('''UPDATE order_lines_v16
        SET unit_hpp=(SELECT h.unit_hpp FROM sku_hpp_master h WHERE h.store_id=order_lines_v16.store_id AND h.sku=order_lines_v16.sku),
            hpp_known=CASE WHEN EXISTS(SELECT 1 FROM sku_hpp_master h WHERE h.store_id=order_lines_v16.store_id AND h.sku=order_lines_v16.sku AND h.unit_hpp IS NOT NULL) THEN 1 ELSE 0 END
        WHERE store_id=?''',(sid,))
    conn.execute('''UPDATE order_lines_v16
        SET unit_hpp=(SELECT h.unit_hpp FROM sku_store_mapping_v18 m JOIN sku_hpp_master h ON h.store_id=m.store_id AND h.sku=m.warehouse_sku WHERE m.store_id=order_lines_v16.store_id AND m.store_sku=order_lines_v16.sku),
            hpp_known=CASE WHEN EXISTS(SELECT 1 FROM sku_store_mapping_v18 m JOIN sku_hpp_master h ON h.store_id=m.store_id AND h.sku=m.warehouse_sku WHERE m.store_id=order_lines_v16.store_id AND m.store_sku=order_lines_v16.sku AND h.unit_hpp IS NOT NULL) THEN 1 ELSE hpp_known END
        WHERE store_id=? AND EXISTS(SELECT 1 FROM sku_store_mapping_v18 m WHERE m.store_id=order_lines_v16.store_id AND m.store_sku=order_lines_v16.sku)''',(sid,))
    conn.execute('UPDATE order_lines_v16 SET line_hpp=unit_hpp*net_qty WHERE store_id=? AND unit_hpp IS NOT NULL',(sid,))
    conn.commit()


def list_sku_mapping_status(conn,sid):
    q='''WITH sold AS (
      SELECT sku AS store_sku, MAX(product_name) product_name, SUM(net_qty) qty_realized,
             SUM(line_sales_idr) sales_idr, COUNT(DISTINCT order_id) orders
      FROM order_lines_v16 WHERE store_id=? AND COALESCE(sku,'')<>'' GROUP BY sku
    )
    SELECT sold.*, m.warehouse_sku, h.product_title AS warehouse_title, h.unit_hpp,
           m.mapping_source,m.review_status,m.confidence,m.notes,
           CASE WHEN m.warehouse_sku IS NOT NULL THEN 'MAPPED_MANUAL'
                WHEN hx.sku IS NOT NULL AND hx.unit_hpp IS NOT NULL THEN 'MAPPED_EXACT'
                ELSE 'UNMAPPED' END mapping_status,
           COALESCE(h.unit_hpp,hx.unit_hpp) effective_hpp
    FROM sold
    LEFT JOIN sku_store_mapping_v18 m ON m.store_id=? AND m.store_sku=sold.store_sku
    LEFT JOIN sku_hpp_master h ON h.store_id=? AND h.sku=m.warehouse_sku
    LEFT JOIN sku_hpp_master hx ON hx.store_id=? AND hx.sku=sold.store_sku
    ORDER BY CASE WHEN m.warehouse_sku IS NULL AND hx.sku IS NULL THEN 0 ELSE 1 END, qty_realized DESC, store_sku'''
    return pd.read_sql_query(q,conn,params=[sid,sid,sid,sid])


def list_warehouse_skus(conn,sid):
    return pd.read_sql_query('SELECT sku,product_title,unit_hpp,sku_type FROM sku_hpp_master WHERE store_id=? AND unit_hpp IS NOT NULL ORDER BY product_title,sku',conn,params=[sid])


def save_sku_mapping(conn,sid,store_sku,warehouse_sku,notes='',confidence=None,review_status='CONFIRMED'):
    target=conn.execute('SELECT sku FROM sku_hpp_master WHERE store_id=? AND sku=?',(sid,warehouse_sku)).fetchone()
    if not target: raise ValueError('SKU Gudang target tidak ditemukan di master HPP.')
    conn.execute('''INSERT INTO sku_store_mapping_v18(store_id,store_sku,warehouse_sku,mapping_source,review_status,confidence,notes)
      VALUES(?,?,?,'MANUAL',?,?,?)
      ON CONFLICT(store_id,store_sku) DO UPDATE SET warehouse_sku=excluded.warehouse_sku,mapping_source='MANUAL',review_status=excluded.review_status,confidence=excluded.confidence,notes=excluded.notes,updated_at=CURRENT_TIMESTAMP''',
      (sid,store_sku,warehouse_sku,review_status,confidence,notes))
    conn.commit(); _reload_hpp_on_orders(conn,sid); rebuild_profit_v16(conn,sid); rebuild_quality(conn,sid)


def delete_sku_mapping(conn,sid,store_sku):
    conn.execute('DELETE FROM sku_store_mapping_v18 WHERE store_id=? AND store_sku=?',(sid,store_sku)); conn.commit()
    _reload_hpp_on_orders(conn,sid); rebuild_profit_v16(conn,sid); rebuild_quality(conn,sid)




def bulk_save_sku_mappings(conn, sid, mappings):
    """Save many approved manual SKU mappings, then rebuild HPP/profit once."""
    items = [dict(x) for x in mappings]
    if not items:
        return 0
    warehouse = {r['sku'] for r in conn.execute(
        'SELECT sku FROM sku_hpp_master WHERE store_id=?', (sid,)
    ).fetchall()}
    missing = sorted({str(x.get('warehouse_sku') or '') for x in items
                      if str(x.get('warehouse_sku') or '') not in warehouse})
    if missing:
        raise ValueError('SKU Gudang target tidak ditemukan: ' + ', '.join(missing[:10]))
    rows = []
    for x in items:
        store_sku = str(x.get('store_sku') or '').strip()
        warehouse_sku = str(x.get('warehouse_sku') or '').strip()
        if not store_sku or not warehouse_sku:
            continue
        rows.append((sid, store_sku, warehouse_sku,
                     str(x.get('review_status') or 'CONFIRMED'),
                     x.get('confidence'), str(x.get('notes') or '')))
    if not rows:
        return 0
    sql = (
        "INSERT INTO sku_store_mapping_v18"
        "(store_id,store_sku,warehouse_sku,mapping_source,review_status,confidence,notes) "
        "VALUES(?,?,?,'MANUAL',?,?,?) "
        "ON CONFLICT(store_id,store_sku) DO UPDATE SET "
        "warehouse_sku=excluded.warehouse_sku,mapping_source='MANUAL',"
        "review_status=excluded.review_status,confidence=excluded.confidence,"
        "notes=excluded.notes,updated_at=CURRENT_TIMESTAMP"
    )
    conn.executemany(sql, rows)
    conn.commit()
    _reload_hpp_on_orders(conn, sid)
    rebuild_profit_v16(conn, sid)
    rebuild_quality(conn, sid)
    return len(rows)


def batch_mapping_suggestions(conn, sid, store_skus=None, limit_per_sku=1):
    """Build read-only candidate suggestions for unmapped store SKUs."""
    status = list_sku_mapping_status(conn, sid)
    status = status[status.mapping_status == 'UNMAPPED'].copy()
    if store_skus is not None:
        wanted = {str(x) for x in store_skus}
        status = status[status.store_sku.astype(str).isin(wanted)]
    wh = list_warehouse_skus(conn, sid)
    out = []
    for _, r in status.iterrows():
        sug = suggest_candidates(str(r.store_sku), str(r.product_name), wh,
                                 limit=max(1, int(limit_per_sku)))
        for rank, (_, c) in enumerate(sug.iterrows(), start=1):
            out.append({
                'store_sku': r.store_sku,
                'product_name': r.product_name,
                'qty_realized': r.qty_realized,
                'sales_idr': r.sales_idr,
                'orders': r.orders,
                'rank': rank,
                'warehouse_sku': c.warehouse_sku,
                'warehouse_title': c.warehouse_title,
                'unit_hpp': c.unit_hpp,
                'confidence': c.confidence,
            })
    return pd.DataFrame(out)

def mapping_suggestions(conn,sid,store_sku,limit=5):
    status=list_sku_mapping_status(conn,sid)
    row=status[status.store_sku==store_sku]
    if row.empty:return pd.DataFrame()
    wh=list_warehouse_skus(conn,sid)
    return suggest_candidates(store_sku,str(row.iloc[0].product_name),wh,limit=limit)

def rebuild_profit_v16(conn,sid):
    ol=pd.read_sql_query('SELECT * FROM order_lines_v16 WHERE store_id=?',conn,params=[sid])
    if ol.empty:return pd.DataFrame()
    ol['order_date']=pd.to_datetime(ol.order_date).dt.date
    # order lines already have HPP attached; normalize columns expected by engine
    ol['hpp_known']=ol.hpp_known.astype(bool)
    inc=pd.read_sql_query('SELECT order_id,order_date,release_date,total_income FROM income_order_details_v16 WHERE store_id=?',conn,params=[sid])
    if not inc.empty:
        inc['order_date_income']=pd.to_datetime(inc.order_date,errors='coerce').dt.date
        inc['release_date']=pd.to_datetime(inc.release_date,errors='coerce').dt.date
        inc['Total Penghasilan']=inc.total_income
    econ=order_level_economics(ol,[inc] if not inc.empty else [])
    ads=daily_ads_total(conn,sid)
    daily=daily_profit_from_orders(econ,ads)
    rows=[]
    for r in daily.where(pd.notna(daily),None).to_dict('records'):
        rows.append({
            'store_id':sid,'metric_date':str(r['order_date']),'order_sales':r.get('order_sales'),'financial_income':r.get('financial_income'),'hpp':r.get('hpp'),'profit_before_ads':r.get('profit_before_ads'),'ads_spend':r.get('ads_spend'),'control_profit':r.get('control_profit'),'control_margin':r.get('control_margin'),'orders':r.get('orders'),'final_orders':r.get('final_orders'),'estimated_orders':r.get('estimated_orders'),'settlement_coverage':r.get('settlement_coverage'),'hpp_coverage':r.get('hpp_coverage'),'estimated_fee_rate':r.get('estimated_fee_rate'),'profit_status':r.get('profit_status')})
    conn.execute('DELETE FROM daily_control_profit_v16 WHERE store_id=?',(sid,))
    upsert_rows(conn,'daily_control_profit_v16',rows,('store_id','metric_date'))
    return daily

def import_v16_file(db_path,file_bytes,filename,source):
    conn=connect(db_path);init_db(conn);sid=get_store_id(conn)
    h=sha256_bytes(file_bytes)
    old=conn.execute('SELECT id FROM import_batches WHERE store_id=? AND file_hash=?',(sid,h)).fetchone()
    if old:return {'source':source,'rows':0,'duplicate':True,'warnings':['File identik sudah pernah diimport'],'granularity':'DETAIL','period_start':None,'period_end':None}
    if source=='SHOPEE_ORDER':
        df=parse_shopee_orders(file_bytes); ps=df.order_date.min(); pe=df.order_date.max(); b,_=_insert_batch(conn,sid,source,filename,file_bytes,len(df),ps,pe,'ORDER_LINE')
        hpp=pd.read_sql_query('SELECT sku,unit_hpp FROM sku_hpp_master WHERE store_id=?',conn,params=[sid])
        if hpp.empty:
            df['unit_hpp']=None;df['line_hpp']=None;df['hpp_known']=False
        else:
            df=df.merge(hpp,on='sku',how='left');df['line_hpp']=df.unit_hpp*df.net_qty;df['hpp_known']=df.unit_hpp.notna()
        rows=[]
        for r in df.where(pd.notna(df),None).to_dict('records'):
            rows.append({'store_id':sid,'order_id':r['order_id'],'order_date':str(r['order_date']),'order_status':r['order_status'],'sku':r['sku'],'product_name':r['product_name'],'qty':r['qty'],'returned_qty':r['returned_qty'],'net_qty':r['net_qty'],'unit_price_idr':r['unit_price_idr'],'line_sales_idr':r['line_sales_idr'],'unit_hpp':r.get('unit_hpp'),'line_hpp':r.get('line_hpp'),'hpp_known':1 if r.get('hpp_known') else 0,'source_batch_id':b})
        upsert_rows(conn,'order_lines_v16',rows,('store_id','order_id','sku','product_name','unit_price_idr')); _reload_hpp_on_orders(conn,sid)
    elif source=='BIGSELLER_HPP':
        df=parse_bigseller_hpp_master(file_bytes); b,_=_insert_batch(conn,sid,source,filename,file_bytes,len(df),None,None,'MASTER')
        rows=[{'store_id':sid,'sku':r['sku'],'product_title':r['product_title'],'unit_hpp':r['unit_hpp'],'sku_type':r['sku_type'],'source_batch_id':b} for r in df.where(pd.notna(df),None).to_dict('records')]
        upsert_rows(conn,'sku_hpp_master',rows,('store_id','sku'));_reload_hpp_on_orders(conn,sid)
        ps=pe=None
    elif source=='SHOPEE_INCOME':
        df=parse_income_detail(file_bytes); ps=df.release_date.min() if not df.empty else None; pe=df.release_date.max() if not df.empty else None; b,_=_insert_batch(conn,sid,source,filename,file_bytes,len(df),ps,pe,'SETTLEMENT')
        if df.empty: rows=[]
        else:
            # one canonical settlement total per order+release date
            x=df.copy();x['abs_total']=x['Total Penghasilan'].abs();x=x.sort_values('abs_total').groupby(['order_id','release_date'],as_index=False).tail(1)
            rows=[{'store_id':sid,'order_id':r['order_id'],'order_date':str(r.get('order_date_income')) if r.get('order_date_income') else None,'release_date':str(r['release_date']),'total_income':r.get('Total Penghasilan'),'source_batch_id':b} for r in x.where(pd.notna(x),None).to_dict('records')]
            upsert_rows(conn,'income_order_details_v16',rows,('store_id','order_id','release_date'))
    else: raise ValueError(source)
    daily=rebuild_profit_v16(conn,sid)
    return {'source':source,'rows':len(df),'duplicate':False,'warnings':[],'granularity':'DETAIL','period_start':str(ps) if ps else None,'period_end':str(pe) if pe else None,'daily_profit_rows':len(daily)}

def import_file(db_path,file_bytes,filename,source):
    if source in {'SHOPEE_ORDER','SHOPEE_INCOME','BIGSELLER_HPP'}:
        return import_v16_file(db_path,file_bytes,filename,source)
    p=read_tabular(file_bytes,filename,source); conn=connect(db_path); init_db(conn); sid=get_store_id(conn); h=sha256_bytes(file_bytes)
    old=conn.execute('SELECT id FROM import_batches WHERE store_id=? AND file_hash=?',(sid,h)).fetchone()
    if old:return {'source':p.source,'rows':0,'duplicate':True,'warnings':['File identik sudah pernah diimport'],'detected_columns':p.detected_columns,'granularity':p.granularity,'period_start':str(p.period_start),'period_end':str(p.period_end)}
    b=conn.execute('INSERT INTO import_batches(store_id,source,filename,file_hash,row_count,min_date,max_date,granularity,notes) VALUES(?,?,?,?,?,?,?,?,?)',(sid,p.source,filename,h,len(p.dataframe),str(p.period_start) if p.period_start else None,str(p.period_end) if p.period_end else None,p.granularity,';'.join(p.warnings))).lastrowid
    d=p.dataframe.where(pd.notna(p.dataframe),None).to_dict('records')
    if p.source=='BUSINESS_INSIGHT':
        rows=[]
        for r in d:r.update(store_id=sid,metric_date=str(r['metric_date']),source_batch_id=b);rows.append(r)
        upsert_rows(conn,'daily_store_metrics',rows,('store_id','metric_date'))
    elif p.source in CHANNEL:
        ch=CHANNEL[p.source]
        if p.granularity=='DAILY':
            r=d[0];r.update(store_id=sid,metric_date=str(p.period_start),channel=ch,source_batch_id=b);upsert_rows(conn,'daily_ads_channels',[r],('store_id','metric_date','channel'))
        else:
            r=d[0]; r.update(store_id=sid,period_start=str(p.period_start),period_end=str(p.period_end),channel=ch,source_batch_id=b); upsert_rows(conn,'period_ads_snapshots',[r],('store_id','period_start','period_end','channel'))
    elif p.source in {'BIGSELLER_STORE','BIGSELLER_SKU'}:
        r=d[0]; st=p.source
        if p.granularity=='DAILY' and st=='BIGSELLER_STORE':
            r.update(store_id=sid,metric_date=str(p.period_start),source_batch_id=b); upsert_rows(conn,'daily_profit_metrics',[r],('store_id','metric_date')); recompute_full_paid_media_profit(conn,sid)
        else:
            r.update(store_id=sid,period_start=str(p.period_start),period_end=str(p.period_end),source_type=st,source_batch_id=b);upsert_rows(conn,'period_profit_snapshots',[r],('store_id','period_start','period_end','source_type'))
    conn.commit(); rebuild_quality(conn,sid)
    return {'source':p.source,'rows':len(d),'duplicate':False,'warnings':p.warnings,'detected_columns':p.detected_columns,'granularity':p.granularity,'period_start':str(p.period_start),'period_end':str(p.period_end)}

def daily_ads_total(conn,sid):
    q='''SELECT metric_date,SUM(ads_spend) ads_spend,SUM(ads_sales) ads_sales,SUM(impressions) impressions,SUM(clicks) clicks,SUM(ads_orders) ads_orders FROM daily_ads_channels WHERE store_id=? GROUP BY metric_date ORDER BY metric_date'''
    d=pd.read_sql_query(q,conn,params=[sid],parse_dates=['metric_date'])
    if not d.empty:
        d['roas']=d.ads_sales/d.ads_spend.replace(0,pd.NA);d['acos']=d.ads_spend/d.ads_sales.replace(0,pd.NA);d['cpc']=d.ads_spend/d.clicks.replace(0,pd.NA);d['ctr']=d.clicks/d.impressions.replace(0,pd.NA);d['rpm']=d.ads_sales/d.impressions.replace(0,pd.NA)*1000
    return d

def merged_daily(conn,sid):
    s=pd.read_sql_query('SELECT * FROM daily_store_metrics WHERE store_id=?',conn,params=[sid],parse_dates=['metric_date']); a=daily_ads_total(conn,sid); p=pd.read_sql_query('SELECT * FROM daily_profit_metrics WHERE store_id=?',conn,params=[sid],parse_dates=['metric_date'])
    ds=[]
    for x in (s,a,p):
        if not x.empty: ds.extend(x.metric_date.tolist())
    if not ds:return pd.DataFrame()
    base=pd.DataFrame({'metric_date':sorted(set(ds))})
    for x in (s,a,p):
        if not x.empty:
            x=x.drop(columns=[c for c in ['store_id','source_batch_id'] if c in x]);base=base.merge(x,on='metric_date',how='left')
    v16=pd.read_sql_query('SELECT * FROM daily_control_profit_v16 WHERE store_id=?',conn,params=[sid],parse_dates=['metric_date'])
    if not v16.empty:
        v16=v16.drop(columns=[c for c in ['store_id','updated_at'] if c in v16])
        # keep legacy control profit side-by-side, but V1.6 is authoritative when available
        v16=v16.rename(columns={'control_profit':'control_profit_v16','control_margin':'control_margin_v16','profit_status':'profit_status_v16','hpp':'hpp_v16','financial_income':'financial_income_v16','profit_before_ads':'profit_before_ads_v16','settlement_coverage':'settlement_coverage_v16','hpp_coverage':'hpp_coverage_v16'})
        base=base.merge(v16,on='metric_date',how='left')
        base['full_paid_media_control_profit']=base['control_profit_v16'].combine_first(base.get('full_paid_media_control_profit'))
        base['full_paid_media_control_margin']=base['control_margin_v16'].combine_first(base.get('full_paid_media_control_margin'))
    return base

def recompute_full_paid_media_profit(conn,sid):
    rows=conn.execute('SELECT * FROM daily_profit_metrics WHERE store_id=?',(sid,)).fetchall()
    for r in rows:
        d=r['metric_date']; channels={x['channel']:x['ads_spend'] or 0 for x in conn.execute('SELECT channel,ads_spend FROM daily_ads_channels WHERE store_id=? AND metric_date=?',(sid,d))}
        live=channels.get('LIVE',0); shop=channels.get('SHOP_PLUS',0)
        # store_profit_reported already includes Product Ads. GPMI additionally includes PPN iklan if present.
        base=r['gpmi'] if r['gpmi'] is not None else r['store_profit_reported']
        cp=(base-live-shop) if base is not None else None; basis=r['realized_sales']; cm=cp/basis if cp is not None and basis else None
        conn.execute('UPDATE daily_profit_metrics SET live_ads_adjustment=?,shop_plus_adjustment=?,full_paid_media_control_profit=?,full_paid_media_control_margin=? WHERE store_id=? AND metric_date=?',(live,shop,cp,cm,sid,d))
    conn.commit()

def rebuild_quality(conn,sid):
    df=merged_daily(conn,sid)
    if df.empty:return
    latest=df.metric_date.max().date()
    for _,r in df.iterrows():
        d=r.metric_date.date(); bi='FINAL' if pd.notna(r.get('store_gmv')) else 'MISSING'; ads='FINAL' if pd.notna(r.get('ads_spend')) else 'MISSING'
        v16_status=r.get('profit_status_v16') if 'profit_status_v16' in r.index else None
        if pd.notna(v16_status):
            bs={'FINAL':'FINAL','ESTIMATED':'BELUM_FINAL','PARTIAL':'PARTIAL','MISSING':'MISSING'}.get(str(v16_status),'PARTIAL')
        else:
            profit=r.get('store_profit_reported'); bs='MISSING' if pd.isna(profit) else ('BELUM_FINAL' if (latest-d).days<=1 else 'FINAL')
        cross=True; flags=[]
        if pd.notna(r.get('ads_sales')) and pd.notna(r.get('store_gmv')) and r.store_gmv and r.ads_sales>r.store_gmv*2.5:cross=False;flags.append('ADS_ATTRIBUTION_UNUSUALLY_HIGH')
        conf=confidence_score(bi,ads,bs,cross); overall=overall_status(bi,ads,bs)
        conn.execute('INSERT INTO daily_data_quality(store_id,metric_date,business_insight_status,ads_status,bigseller_status,overall_status,confidence_score,flags_json) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(store_id,metric_date) DO UPDATE SET business_insight_status=excluded.business_insight_status,ads_status=excluded.ads_status,bigseller_status=excluded.bigseller_status,overall_status=excluded.overall_status,confidence_score=excluded.confidence_score,flags_json=excluded.flags_json,updated_at=CURRENT_TIMESTAMP',(sid,d.isoformat(),bi,ads,bs,overall,conf,json.dumps(flags)))
    conn.commit()

def period_reconciliation(conn,sid):
    profits=pd.read_sql_query("SELECT * FROM period_profit_snapshots WHERE store_id=? AND source_type='BIGSELLER_STORE' ORDER BY period_end",conn,params=[sid])
    ads=pd.read_sql_query('SELECT * FROM period_ads_snapshots WHERE store_id=?',conn,params=[sid])
    if profits.empty:return profits
    out=[]
    for _,p in profits.iterrows():
        match=ads[(ads.period_start==p.period_start)&(ads.period_end==p.period_end)] if not ads.empty else pd.DataFrame()
        vals={ch:0.0 for ch in ['PRODUCT','LIVE','SHOP_PLUS']}
        sales={ch:0.0 for ch in vals}
        for _,a in match.iterrows(): vals[a.channel]=float(a.ads_spend or 0); sales[a.channel]=float(a.ads_sales or 0)
        base=p.gpmi if pd.notna(p.get('gpmi')) else p.store_profit_reported
        basis=float(p.realized_sales) if pd.notna(p.realized_sales) else 0
        product_bigseller=abs(float(p.product_ads_in_bigseller or 0))
        product_verified=bool(vals['PRODUCT'])
        # BigSeller 'Iklan' may include Product Ads + Shop+ (verified in Aug 2026 exports).
        # Detect this reconciliation before subtracting Shop+ from GPMI, otherwise Shop+ is double-counted.
        expected_product_plus_shop = vals['PRODUCT'] + vals['SHOP_PLUS']
        tol = max(5000.0, product_bigseller * 0.005)
        shop_included_in_bigseller = bool(product_verified and vals['SHOP_PLUS'] and abs(product_bigseller - expected_product_plus_shop) <= tol)
        product_only_match = bool(product_verified and abs(product_bigseller - vals['PRODUCT']) <= tol)
        # GPMI already deducts BigSeller 'Iklan' and PPN Iklan. Live Ads remains external in current exports.
        external_shop_adjustment = 0.0 if shop_included_in_bigseller else vals['SHOP_PLUS']
        full=float(base) - vals['LIVE'] - external_shop_adjustment if pd.notna(base) else None
        product_effective=vals['PRODUCT'] if product_verified else product_bigseller
        out.append({
            'period_start':p.period_start,'period_end':p.period_end,'realized_sales':p.realized_sales,
            'store_profit_reported':p.store_profit_reported,'gpmi':p.gpmi,
            'gp_before_product_ads':p.gp_before_product_ads,
            'product_ads_bigseller':product_bigseller,'product_ads_export':vals['PRODUCT'],
            'product_ads_effective':product_effective,'product_ads_verified':product_verified,
            'live_ads_spend':vals['LIVE'],'shop_plus_spend':vals['SHOP_PLUS'],
            'shop_plus_included_in_bigseller':shop_included_in_bigseller,
            'shop_plus_external_adjustment':external_shop_adjustment,
            'bigseller_ads_reconciliation':'PRODUCT_PLUS_SHOP_PLUS' if shop_included_in_bigseller else ('PRODUCT_ONLY' if product_only_match else 'UNRESOLVED'),
            'product_ads_sales':sales['PRODUCT'],
            'product_ads_roas':(sales['PRODUCT']/vals['PRODUCT']) if vals['PRODUCT'] else None,
            'product_ads_acos':(vals['PRODUCT']/sales['PRODUCT']) if sales['PRODUCT'] else None,
            'full_paid_media_control_profit':full,'full_paid_media_control_margin':full/basis if full is not None and basis else None,
            'product_ads_variance':product_bigseller-vals['PRODUCT'] if product_verified else None,
            'ads_channels_complete': all(ch in set(match.channel) for ch in ['PRODUCT','LIVE','SHOP_PLUS']) if not match.empty else False,
        })
    return pd.DataFrame(out)


def period_control_summary(conn, sid):
    """Exact-period control summaries without fabricating daily profit."""
    rec = period_reconciliation(conn, sid)
    if rec.empty:
        return rec
    sku = pd.read_sql_query(
        "SELECT * FROM period_profit_snapshots WHERE store_id=? AND source_type='BIGSELLER_SKU'",
        conn, params=[sid]
    )
    rows = []
    for _, r in rec.iterrows():
        ps, pe = str(r.period_start), str(r.period_end)
        bi = pd.read_sql_query(
            "SELECT SUM(store_gmv) gross_store_sales, SUM(cancelled_sales) cancelled_sales, "
            "SUM(adjusted_store_sales) adjusted_store_sales, SUM(orders) orders, "
            "SUM(visitors) visitors, AVG(conversion_rate) avg_cr "
            "FROM daily_store_metrics WHERE store_id=? AND metric_date BETWEEN ? AND ?",
            conn, params=[sid, ps, pe]
        ).iloc[0]
        sku_match = sku[(sku.period_start == ps) & (sku.period_end == pe)] if not sku.empty else pd.DataFrame()
        sk = sku_match.iloc[0] if not sku_match.empty else None
        realized = float(r.realized_sales) if pd.notna(r.realized_sales) else None
        full = float(r.full_paid_media_control_profit) if pd.notna(r.full_paid_media_control_profit) else None
        gross = float(bi.gross_store_sales) if pd.notna(bi.gross_store_sales) else None
        adjusted = float(bi.adjusted_store_sales) if pd.notna(bi.adjusted_store_sales) else None
        product_sp = float(r.product_ads_effective or 0) if pd.notna(r.product_ads_effective) else 0.0
        live_sp = float(r.live_ads_spend or 0) if pd.notna(r.live_ads_spend) else 0.0
        shop_sp = float(r.shop_plus_spend or 0) if pd.notna(r.shop_plus_spend) else 0.0
        total_sp = product_sp + live_sp + shop_sp
        rows.append({
            'period_start': ps,
            'period_end': pe,
            'gross_store_sales': gross,
            'cancelled_sales': float(bi.cancelled_sales) if pd.notna(bi.cancelled_sales) else None,
            'adjusted_store_sales': adjusted,
            'realized_sales': realized,
            'bi_vs_bigseller_variance': (adjusted - realized) if adjusted is not None and realized is not None else None,
            'bi_vs_bigseller_variance_pct': ((adjusted - realized) / adjusted) if adjusted else None,
            'orders_bi': float(bi.orders) if pd.notna(bi.orders) else None,
            'visitors': float(bi.visitors) if pd.notna(bi.visitors) else None,
            'avg_cr': float(bi.avg_cr) if pd.notna(bi.avg_cr) else None,
            'store_profit_reported': r.store_profit_reported,
            'gpmi': r.gpmi,
            'product_ads_spend': product_sp,
            'product_ads_verified': bool(r.product_ads_verified),
            'product_ads_source': 'SHOPEE_EXPORT' if bool(r.product_ads_verified) else 'BIGSELLER_FALLBACK',
            'gp_before_product_ads': r.gp_before_product_ads,
            'live_ads_spend': live_sp,
            'shop_plus_spend': shop_sp,
            'shop_plus_included_in_bigseller': bool(r.get('shop_plus_included_in_bigseller', False)),
            'shop_plus_external_adjustment': float(r.get('shop_plus_external_adjustment', shop_sp) or 0),
            'bigseller_ads_reconciliation': r.get('bigseller_ads_reconciliation', 'UNRESOLVED'),
            'product_ads_sales': r.get('product_ads_sales'),
            'product_ads_roas': r.get('product_ads_roas'),
            'product_ads_acos': r.get('product_ads_acos'),
            'total_paid_spend': total_sp,
            'full_paid_media_control_profit': full,
            'full_paid_media_control_margin': r.full_paid_media_control_margin,
            'paid_ads_cost_pct_realized': (total_sp / realized) if realized else None,
            'sku_profit': float(sk.sku_profit) if sk is not None and pd.notna(sk.sku_profit) else None,
            'sku_margin': float(sk.sku_margin) if sk is not None and pd.notna(sk.sku_margin) else None,
            'sku_cogs': float(sk.sku_cogs) if sk is not None and pd.notna(sk.sku_cogs) else None,
            'product_ads_variance': r.product_ads_variance,
            'ads_channels_complete': bool(r.ads_channels_complete),
        })
    return pd.DataFrame(rows)

import sqlite3
from pathlib import Path
from typing import Iterable, Mapping

SCHEMA='''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS stores(id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, timezone TEXT NOT NULL DEFAULT 'Asia/Jakarta', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS import_batches(id INTEGER PRIMARY KEY AUTOINCREMENT,store_id INTEGER NOT NULL,source TEXT NOT NULL,filename TEXT NOT NULL,file_hash TEXT,imported_at TEXT DEFAULT CURRENT_TIMESTAMP,row_count INTEGER DEFAULT 0,min_date TEXT,max_date TEXT,granularity TEXT DEFAULT 'DAILY',status TEXT DEFAULT 'IMPORTED',notes TEXT, UNIQUE(store_id,file_hash));
CREATE TABLE IF NOT EXISTS daily_store_metrics(store_id INTEGER,metric_date TEXT,store_gmv REAL,adjusted_store_sales REAL,cancelled_sales REAL,cancelled_orders REAL,returned_sales REAL,returned_orders REAL,orders REAL,visitors REAL,buyers REAL,product_clicks REAL,conversion_rate REAL,source_batch_id INTEGER,PRIMARY KEY(store_id,metric_date));
CREATE TABLE IF NOT EXISTS daily_ads_channels(store_id INTEGER,metric_date TEXT,channel TEXT,ads_spend REAL,ads_sales REAL,impressions REAL,clicks REAL,ads_orders REAL,units_sold REAL,roas REAL,acos REAL,cpc REAL,ctr REAL,rpm REAL,source_batch_id INTEGER,PRIMARY KEY(store_id,metric_date,channel));
CREATE TABLE IF NOT EXISTS period_ads_snapshots(store_id INTEGER,period_start TEXT,period_end TEXT,channel TEXT,ads_spend REAL,ads_sales REAL,impressions REAL,clicks REAL,ads_orders REAL,units_sold REAL,roas REAL,acos REAL,cpc REAL,ctr REAL,rpm REAL,source_batch_id INTEGER,PRIMARY KEY(store_id,period_start,period_end,channel));
CREATE TABLE IF NOT EXISTS daily_profit_metrics(store_id INTEGER,metric_date TEXT,store_income REAL,store_cogs REAL,store_profit_reported REAL,store_margin_reported REAL,realized_sales REAL,product_ads_in_bigseller REAL,estimated_real_omzet REAL,ads_vat REAL,gp_before_product_ads REAL,gm_before_product_ads REAL,gpmi REAL,gmmi REAL,live_ads_adjustment REAL DEFAULT 0,shop_plus_adjustment REAL DEFAULT 0,full_paid_media_control_profit REAL,full_paid_media_control_margin REAL,source_batch_id INTEGER,PRIMARY KEY(store_id,metric_date));
CREATE TABLE IF NOT EXISTS period_profit_snapshots(store_id INTEGER,period_start TEXT,period_end TEXT,source_type TEXT,store_income REAL,store_cogs REAL,store_profit_reported REAL,store_margin_reported REAL,realized_sales REAL,product_ads_in_bigseller REAL,estimated_real_omzet REAL,ads_vat REAL,gp_before_product_ads REAL,gm_before_product_ads REAL,gpmi REAL,gmmi REAL,sku_income REAL,sku_cogs REAL,sku_profit REAL,sku_margin REAL,sku_realized_sales REAL,orders REAL,units_sold REAL,source_batch_id INTEGER,PRIMARY KEY(store_id,period_start,period_end,source_type));
CREATE TABLE IF NOT EXISTS daily_data_quality(store_id INTEGER,metric_date TEXT,business_insight_status TEXT DEFAULT 'MISSING',ads_status TEXT DEFAULT 'MISSING',bigseller_status TEXT DEFAULT 'MISSING',overall_status TEXT DEFAULT 'MISSING',confidence_score REAL DEFAULT 0,flags_json TEXT DEFAULT '[]',updated_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(store_id,metric_date));
CREATE TABLE IF NOT EXISTS guardrails(store_id INTEGER PRIMARY KEY,minimum_margin REAL DEFAULT .10,minimum_roas REAL DEFAULT 5,roas_bep REAL DEFAULT 4,minimum_safety_ratio REAL DEFAULT 1.15,maximum_ads_cost_pct REAL DEFAULT .15,recommended_budget REAL DEFAULT 0,hard_budget_limit REAL DEFAULT 0,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS order_lines_v16(store_id INTEGER,order_id TEXT,order_date TEXT,order_status TEXT,sku TEXT,product_name TEXT,qty REAL,returned_qty REAL,net_qty REAL,unit_price_idr REAL,line_sales_idr REAL,unit_hpp REAL,line_hpp REAL,hpp_known INTEGER,source_batch_id INTEGER,PRIMARY KEY(store_id,order_id,sku,product_name,unit_price_idr));
CREATE TABLE IF NOT EXISTS sku_hpp_master(store_id INTEGER,sku TEXT,product_title TEXT,unit_hpp REAL,sku_type TEXT,updated_at TEXT DEFAULT CURRENT_TIMESTAMP,source_batch_id INTEGER,PRIMARY KEY(store_id,sku));
CREATE TABLE IF NOT EXISTS sku_store_mapping_v18(store_id INTEGER,store_sku TEXT,warehouse_sku TEXT,mapping_source TEXT DEFAULT 'MANUAL',review_status TEXT DEFAULT 'CONFIRMED',confidence REAL,notes TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(store_id,store_sku),FOREIGN KEY(store_id,warehouse_sku) REFERENCES sku_hpp_master(store_id,sku));
CREATE TABLE IF NOT EXISTS income_order_details_v16(store_id INTEGER,order_id TEXT,order_date TEXT,release_date TEXT,total_income REAL,source_batch_id INTEGER,PRIMARY KEY(store_id,order_id,release_date));
CREATE TABLE IF NOT EXISTS daily_control_profit_v16(store_id INTEGER,metric_date TEXT,order_sales REAL,financial_income REAL,hpp REAL,profit_before_ads REAL,ads_spend REAL,control_profit REAL,control_margin REAL,orders REAL,final_orders REAL,estimated_orders REAL,settlement_coverage REAL,hpp_coverage REAL,estimated_fee_rate REAL,profit_status TEXT,updated_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(store_id,metric_date));
'''

def connect(db_path='daily_store_control.db'):
    c=sqlite3.connect(str(db_path)); c.row_factory=sqlite3.Row; return c

def init_db(conn):
    conn.executescript(SCHEMA); conn.execute("INSERT OR IGNORE INTO stores(code,name) VALUES('GERABAHKU_JOGJA','Gerabahku Jogja')"); sid=conn.execute("SELECT id FROM stores WHERE code='GERABAHKU_JOGJA'").fetchone()[0]; conn.execute('INSERT OR IGNORE INTO guardrails(store_id) VALUES(?)',(sid,)); conn.commit()

def get_store_id(conn,code='GERABAHKU_JOGJA'): return int(conn.execute('SELECT id FROM stores WHERE code=?',(code,)).fetchone()[0])

def upsert_rows(conn,table,rows:Iterable[Mapping],key_cols):
    rows=list(rows)
    if not rows:return 0
    cols=list(rows[0]); ph=','.join('?' for _ in cols); upd=[c for c in cols if c not in key_cols]
    sql=f"INSERT INTO {table} ({','.join(cols)}) VALUES ({ph}) ON CONFLICT({','.join(key_cols)}) DO UPDATE SET "+','.join(f'{c}=excluded.{c}' for c in upd)
    conn.executemany(sql,[[r.get(c) for c in cols] for r in rows]); conn.commit(); return len(rows)

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import csv, hashlib, io, re
import pandas as pd


def _norm(s: object) -> str:
    s='' if s is None else str(s)
    s=s.strip().lower().replace('&',' dan ')
    s=re.sub(r'[\n\r\t]+',' ',s)
    s=re.sub(r'[^a-z0-9%]+','_',s)
    return re.sub(r'_+','_',s).strip('_')


def _parse_number(v):
    if v is None or (isinstance(v,float) and pd.isna(v)): return None
    if isinstance(v,(int,float)): return float(v)
    s=str(v).strip()
    if not s or s.lower() in {'nan','-','--'}: return None
    pct=s.endswith('%'); s=s.rstrip('%').strip()
    s=re.sub(r'[^0-9,.-]','',s)
    if not s: return None
    # ID locale: 19.572.225 ; 92.289,47 ; 2,06
    if ',' in s:
        if '.' in s:
            s=s.replace('.','').replace(',','.')
        else:
            s=s.replace(',','.')
    elif s.count('.') > 1 or (s.count('.')==1 and len(s.split('.')[-1])==3):
        s=s.replace('.','')
    try: x=float(s)
    except: return None
    return x/100 if pct else x


def _num(series: pd.Series) -> pd.Series:
    return series.map(_parse_number)


def _date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series,errors='coerce',dayfirst=True).dt.date


def _extract_period_from_text(text:str):
    pats=[r'Periode\s*,\s*(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})',
          r'Waktu Pesanan Dibuat:(\d{4}-\d{2}-\d{2})-(\d{4}-\d{2}-\d{2})']
    for p in pats:
        m=re.search(p,text,re.I)
        if m:
            a=pd.to_datetime(m.group(1),dayfirst='/' in m.group(1)).date()
            b=pd.to_datetime(m.group(2),dayfirst='/' in m.group(2)).date()
            return a,b
    return None,None

@dataclass
class ParseResult:
    source:str
    dataframe:pd.DataFrame
    warnings:List[str]=field(default_factory=list)
    detected_columns:Dict[str,str]=field(default_factory=dict)
    sheet_name:Optional[str]=None
    period_start:Optional[object]=None
    period_end:Optional[object]=None
    granularity:str='DAILY'

ALIASES={
 'BUSINESS_INSIGHT':{
  'metric_date':['tanggal','date'], 'store_gmv':['total_penjualan_idr','total_penjualan','omzet','gmv'],
  'orders':['total_pesanan','pesanan','orders'], 'visitors':['total_pengunjung','pengunjung','visitors'], 'buyers':['pembeli'],
  'product_clicks':['produk_diklik'], 'conversion_rate':['tingkat_konversi_pesanan'],
  'cancelled_orders':['pesanan_dibatalkan'], 'cancelled_sales':['penjualan_dibatalkan'],
  'returned_orders':['pesanan_dikembalikan'], 'returned_sales':['penjualan_dikembalikan']},
 'SHOPEE_ADS_PRODUCT':{
  'metric_date':['tanggal','date'], 'impressions':['dilihat','impresi','impressions'], 'clicks':['jumlah_klik','klik','clicks'], 'ads_orders':['konversi','pesanan','orders'], 'units_sold':['produk_terjual'],
  'ads_sales':['omzet_penjualan','penjualan','ads_sales'], 'ads_spend':['biaya','spend','ads_spend']},
 'SHOPEE_ADS_LIVE':{
  'impressions':['penonton'], 'ads_orders':['pesanan'], 'ads_sales':['omzet_penjualan'], 'ads_spend':['biaya']},
 'SHOPEE_ADS_SHOP_PLUS':{
  'impressions':['dilihat'], 'clicks':['jumlah_klik'], 'ads_orders':['konversi'], 'units_sold':['produk_terjual'],
  'ads_sales':['omzet_penjualan'], 'ads_spend':['biaya'], 'sov':['sov']},
 'BIGSELLER_STORE':{
  'store_income':['pemasukan_toko'], 'store_cogs':['modal_produk'], 'store_profit_reported':['keuntungan_kerugian'],
  'store_margin_reported':['persentase_keuntungan'], 'realized_sales':['dana_penjualan_produk'],
  'product_ads_in_bigseller':['iklan'], 'estimated_real_omzet':['est_omz_real'], 'gp_before_product_ads':['gp'],
  'gm_before_product_ads':['gm'], 'ads_vat':['ppn_iklan'], 'gpmi':['gpmi'], 'gmmi':['gmmi']},
 'BIGSELLER_SKU':{
  'sku_income':['pemasukan_sku_gudang'], 'sku_cogs':['total_modal'], 'sku_profit':['keuntungan'],
  'sku_margin':['persentase_keuntungan'], 'sku_realized_sales':['total_dana_penjualan_sku_gudang'],
  'orders':['jumlah_pesanan'], 'units_sold':['jumlah_produk_yang_terjual']},
}
ALIASES['SHOPEE_ADS']=ALIASES['SHOPEE_ADS_PRODUCT']; ALIASES['BIGSELLER']=ALIASES['BIGSELLER_STORE']


def _map_columns(cols, aliases):
    normalized={_norm(c):c for c in cols}
    out={}
    for canon,cands in aliases.items():
        for c in cands:
            if _norm(c) in normalized: out[canon]=normalized[_norm(c)]; break
    return out


def _read_csv_ragged(file_bytes:bytes):
    text=None
    for enc in ('utf-8-sig','utf-8','latin1'):
        try: text=file_bytes.decode(enc); break
        except UnicodeDecodeError: pass
    rows=list(csv.reader(io.StringIO(text or '')))
    return text or '', rows


def _choose_excel_table(file_bytes, aliases):
    xls=pd.ExcelFile(io.BytesIO(file_bytes)); best=None
    for s in xls.sheet_names:
        raw=pd.read_excel(io.BytesIO(file_bytes),sheet_name=s,header=None,dtype=object)
        for h in range(min(20,len(raw))):
            hdr=raw.iloc[h].tolist(); mp=_map_columns(hdr,aliases); score=len(mp)
            if best is None or score>best[0]:
                body=raw.iloc[h+1:].copy(); body.columns=hdr
                best=(score,s,body.dropna(how='all'),mp,raw)
    return best


def read_tabular(file_bytes:bytes, filename:str, source:str)->ParseResult:
    source=source.upper(); source={'SHOPEE_ADS':'SHOPEE_ADS_PRODUCT','BIGSELLER':'BIGSELLER_STORE'}.get(source,source)
    if source not in ALIASES: raise ValueError(f'Unsupported source: {source}')
    suffix=Path(filename).suffix.lower(); warnings=[]; ps=pe=None; sheet=None
    if suffix=='.csv':
        text,rows=_read_csv_ragged(file_bytes); ps,pe=_extract_period_from_text(text)
        best=None
        for h,row in enumerate(rows[:20]):
            mp=_map_columns(row,ALIASES[source]); score=len(mp)
            if best is None or score>best[0]: best=(score,h,row,mp)
        score,h,hdr,mapping=best
        data=[]
        for row in rows[h+1:]:
            if not any(str(x).strip() for x in row): continue
            row=row+['']*(len(hdr)-len(row)); data.append(row[:len(hdr)])
        df=pd.DataFrame(data,columns=hdr); sheet='CSV'
    elif suffix in {'.xlsx','.xls'}:
        best=_choose_excel_table(file_bytes,ALIASES[source]); score,sheet,df,mapping,raw=best
        full='\n'.join(' '.join(str(x) for x in row if pd.notna(x)) for row in raw.iloc[:5].values.tolist())
        ps,pe=_extract_period_from_text(full)
    else: raise ValueError('Only xlsx/xls/csv supported')

    out=pd.DataFrame()
    # Business Insight contains duplicate total-period header + daily header; keep only valid single dates.
    if source=='BUSINESS_INSIGHT':
        if 'metric_date' not in mapping: raise ValueError('Tanggal tidak terdeteksi')
        out['metric_date']=_date(df[mapping['metric_date']])
        for c,orig in mapping.items():
            if c!='metric_date': out[c]=_num(df[orig])
        out=out.dropna(subset=['metric_date'])
        # trust Shopee's exported CR; do not derive order/visitor.
        daily=out.groupby('metric_date',as_index=False).first()
        if 'conversion_rate' not in daily and 'orders' in daily and 'visitors' in daily:
            daily['conversion_rate']=daily['orders']/daily['visitors'].replace(0,pd.NA)
        if 'cancelled_sales' in daily: daily['adjusted_store_sales']=daily['store_gmv']-daily['cancelled_sales'].fillna(0)
        gran='DAILY'
        if len(daily): ps,pe=daily.metric_date.min(),daily.metric_date.max()
    else:
        for c,orig in mapping.items(): out[c]=_num(df[orig])
        if source.startswith('SHOPEE_ADS_'):
            if 'metric_date' in mapping:
                out['metric_date']=_date(df[mapping['metric_date']])
                out=out.dropna(subset=['metric_date'])
                sums={c:'sum' for c in ['ads_spend','ads_sales','impressions','clicks','ads_orders','units_sold'] if c in out}
                daily=out.groupby('metric_date',as_index=False).agg(sums)
                gran='DAILY'
                if len(daily): ps,pe=daily.metric_date.min(),daily.metric_date.max()
                for ix,rowx in daily.iterrows():
                    spend=rowx.get('ads_spend') or 0; sales=rowx.get('ads_sales') or 0; imp=rowx.get('impressions') or 0; clicks=rowx.get('clicks') or 0
                    daily.loc[ix,'roas']=sales/spend if spend else None; daily.loc[ix,'acos']=spend/sales if sales else None; daily.loc[ix,'cpc']=spend/clicks if clicks else None; daily.loc[ix,'ctr']=clicks/imp if imp else None; daily.loc[ix,'rpm']=sales/imp*1000 if imp else None
            else:
                sums={c:'sum' for c in ['ads_spend','ads_sales','impressions','clicks','ads_orders','units_sold'] if c in out}
                row=out.agg(sums).to_dict() if sums else {}
                spend=row.get('ads_spend') or 0; sales=row.get('ads_sales') or 0; imp=row.get('impressions') or 0; clicks=row.get('clicks') or 0
                row.update({'roas':sales/spend if spend else None,'acos':spend/sales if sales else None,'cpc':spend/clicks if clicks else None,'ctr':clicks/imp if imp else None,'rpm':sales/imp*1000 if imp else None})
                daily=pd.DataFrame([row]); gran='DAILY' if ps and pe and ps==pe else 'PERIOD'
                if gran=='DAILY': daily.insert(0,'metric_date',ps)
        elif source=='BIGSELLER_STORE':
            # prefer Total row, else first data row
            idx=0
            if 'Nama Panggilan Toko BigSeller' in df.columns:
                hits=df.index[df['Nama Panggilan Toko BigSeller'].astype(str).str.strip().eq('Total')]
                if len(hits): idx=hits[0]
            row={c:_parse_number(df.loc[idx,orig]) for c,orig in mapping.items()}
            daily=pd.DataFrame([row]); gran='DAILY' if ps and pe and ps==pe else 'PERIOD'
            if gran=='DAILY': daily.insert(0,'metric_date',ps)
        else: # BIGSELLER_SKU aggregate total row
            # total row is usually first record with Nama SKU Gudang == Total
            idx=0
            total_col=next((c for c in df.columns if _norm(c)=='nama_sku_gudang'),None)
            if total_col:
                hits=df.index[df[total_col].astype(str).str.strip().eq('Total')]
                if len(hits): idx=hits[0]
            row={c:_parse_number(df.loc[idx,orig]) for c,orig in mapping.items()}
            daily=pd.DataFrame([row]); gran='DAILY' if ps and pe and ps==pe else 'PERIOD'
            if gran=='DAILY': daily.insert(0,'metric_date',ps)

    if not mapping: warnings.append('Tidak ada kolom utama yang terdeteksi')
    return ParseResult(source,daily,warnings,mapping,sheet,ps,pe,gran)


def sha256_bytes(data:bytes)->str: return hashlib.sha256(data).hexdigest()

from __future__ import annotations
import re
from difflib import SequenceMatcher
import pandas as pd

STOP = {'gerabahku','jogja','tanah','liat','gerabah','untuk','dan','dengan','paket','produk','original'}

def _norm(s: str) -> str:
    s=(s or '').lower().replace('+kayu',' packing kayu ')
    s=re.sub(r'[^a-z0-9]+',' ',s)
    return ' '.join(x for x in s.split() if x not in STOP)

def _tokens(s: str) -> set[str]:
    return set(_norm(s).split())

def mapping_similarity(store_sku: str, product_name: str, warehouse_sku: str, warehouse_title: str) -> float:
    a=_norm(f'{store_sku} {product_name}')
    b=_norm(f'{warehouse_sku} {warehouse_title}')
    ta,tb=_tokens(a),_tokens(b)
    token= len(ta & tb)/max(1,len(ta | tb))
    seq=SequenceMatcher(None,a,b).ratio()
    score=0.58*token+0.42*seq
    # important commercial variant clues
    clues=['kayu','20cm','18cm','21cm','14cm','22cm','30cm','35cm','800ml','2l','2 5l','5pcs','6pc','10pc']
    for clue in clues:
        ina=clue in a; inb=clue in b
        if ina and inb: score += .025
        elif ina != inb: score -= .04
    return max(0.0,min(1.0,score))

def suggest_candidates(store_sku: str, product_name: str, warehouse: pd.DataFrame, limit: int=5) -> pd.DataFrame:
    if warehouse is None or warehouse.empty:
        return pd.DataFrame(columns=['warehouse_sku','warehouse_title','unit_hpp','confidence'])
    rows=[]
    for _,r in warehouse.iterrows():
        ws=str(r.get('sku') or '')
        wt=str(r.get('product_title') or '')
        score=mapping_similarity(store_sku,product_name,ws,wt)
        rows.append({'warehouse_sku':ws,'warehouse_title':wt,'unit_hpp':r.get('unit_hpp'),'confidence':score})
    out=pd.DataFrame(rows).sort_values(['confidence','warehouse_sku'],ascending=[False,True]).head(limit)
    return out.reset_index(drop=True)

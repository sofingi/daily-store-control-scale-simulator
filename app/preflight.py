from pathlib import Path
import os
import sys

APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from database import connect, init_db, get_store_id
from service import period_control_summary, list_sku_mapping_status, list_warehouse_skus

def main():
    db_path = Path(os.getenv("DSC_DB_PATH", str(ROOT_DIR / "data" / "preflight.db")))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    init_db(conn)
    sid = get_store_id(conn)
    assert sid is not None
    period_control_summary(conn, sid)
    list_sku_mapping_status(conn, sid)
    list_warehouse_skus(conn, sid)
    print(f"PREFLIGHT_OK db={db_path} store_id={sid}")

if __name__ == "__main__":
    main()

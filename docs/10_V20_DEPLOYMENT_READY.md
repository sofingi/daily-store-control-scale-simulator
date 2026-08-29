# V2.0 Deployment-Ready UI

## Source of Truth
V2 menggunakan Independent Profit Engine sebagai sumber profit utama:

`Shopee Order -> Shopee Income -> SKU Mapping -> BigSeller HPP -> All Paid Ads -> Control Profit`

BigSeller Keuntungan Toko hanya berada di halaman **Audit & Settings** dan tidak mengendalikan Control Profit.

## Navigasi V2
1. **Dashboard** — Control Profit, margin, settlement/HPP coverage, trend, Store & Ads Pulse.
2. **Import Data** — status sumber inti, upload, duplicate protection, import history.
3. **SKU Mapping** — exact mapping, manual mapping, batch suggestion dengan persetujuan manusia.
4. **Readiness & Simulator** — readiness gate dan skenario scale.
5. **Audit & Settings** — data quality, audit BigSeller, guardrails, deployment health.

## Menjalankan Lokal
```bash
pip install -r requirements.txt
streamlit run app/v2_main.py
```
atau:
```bash
./run_app.sh
```

## Docker
```bash
docker build -t daily-store-control .
docker run --rm -p 8501:8501 -v $(pwd)/data:/app/data daily-store-control
```

## Persistensi Database
Database default berada di root project: `daily_store_control.db`. Pada hosting produksi, gunakan persistent disk/volume agar mapping SKU dan histori import tidak hilang saat restart/deploy.

## Deployment Checklist
- Python 3.12 direkomendasikan.
- Install `requirements.txt`.
- Start command: `streamlit run app/v2_main.py --server.address=0.0.0.0 --server.port=$PORT`.
- Pasang persistent volume untuk `daily_store_control.db`.
- Backup database secara berkala, terutama setelah bulk SKU mapping.
- Jangan memasukkan file export toko ke repository publik.

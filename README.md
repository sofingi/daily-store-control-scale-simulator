# Daily Store Control & Scale Simulator — Gerabahku Jogja

V1.4 prototype for daily store control, data confidence, period reconciliation, scale readiness and paid-media budget simulation.

## What is implemented
- Multi-file upload for Excel/CSV exports
- Duplicate detection by file hash
- Shopee Business Insight parser (daily rows from monthly export)
- Shopee Product Ads, Live Ads, and Shop+ parsers
- BigSeller Keuntungan Toko + Keuntungan SKU Gudang parsers
- DAILY vs PERIOD grain protection (period totals are never divided into fake daily data)
- Daily Pulse and 7/14/30 day trends
- Data Coverage / Sync Status and confidence score
- Period Control reconciliation
- Scale Readiness 0–100
- Period Preliminary Readiness when BigSeller is only available at MTD/monthly grain
- Data-driven guardrail suggestions from historical periods (never auto-applied)
- Product Ads spend fallback to BigSeller when matching Shopee period export is absent, with explicit verification flag
- Scale Simulator: optimistic / realistic / conservative
- Editable Scale Guardrails
- Automatic Daily Recommendation with data gate

## Profit hierarchy
- Business Insight = store performance / traffic / gross order-created sales
- BigSeller Keuntungan SKU Gudang = SKU-level HPP and profitability
- BigSeller Keuntungan Toko = primary store-profit source
- Product Ads in BigSeller is **not deducted twice**
- Live Ads and Shop+ are separate paid-media adjustments when not included by BigSeller
- Ads Sales is attribution and is **never added to store GMV**

## Run locally
```bash
python -m pip install -r requirements.txt
python -m streamlit run app/main.py
```

## Test
```bash
pytest -q
```
Current suite: 13 tests, including real export fixtures used during development.

## Recommended daily workflow
1. Upload Business Insight monthly export when refreshed.
2. Multi-upload Product Ads daily exports.
3. Upload Live Ads and Shop+ daily exports when available.
4. Upload BigSeller Keuntungan Toko daily export when synchronization is sufficiently complete.
5. Review Data Coverage. Do not act aggressively while BigSeller is `BELUM_FINAL`, `PARTIAL`, or `MISSING`.
6. Review Daily Recommendation and Simulator only after the data gate is satisfied.

## Important
The app needs DAILY BigSeller Keuntungan Toko data for a true daily Control Profit, readiness score, and scale recommendation. Period exports remain useful in **Period Control**, but are intentionally not converted to daily profit.

See:
- `docs/01_FORMULA_DATA_MAPPING.md`
- `docs/02_DATABASE_AND_UI.md`
- `docs/03_REAL_DATA_RECONCILIATION_JULY.md`
- `docs/04_READINESS_CALIBRATION_AUGUST.md`


## V1.5 — Product Ads verified + Shop+ overlap protection
- Product Ads period export now verifies ROAS/ACOS and Ads Safety.
- Detects when BigSeller `Iklan` reconciles to Product Ads + Shop+.
- Prevents Shop+ double deduction from GPMI.
- August 1–28 preliminary readiness recalibrated to 78.9/100 (KEEP).
- 14/14 tests pass.

## V1.6 architecture update
Profit is now independent from BigSeller profit reports. Upload `Shopee Order`, `Shopee Income / Penghasilan`, `BigSeller Master HPP SKU`, Business Insight, and each Shopee Ads channel. BigSeller Keuntungan Toko/SKU remains optional audit data.

## V1.7 HPP Coverage Audit
- BigSeller is used only as HPP/cost source; store profit remains independent.
- Added secondary HPP fallback from Keuntungan SKU Gudang (Total Modal / units sold) for SKUs absent from the master snapshot.
- Added HPP coverage audit that ignores cancelled quantities and reports unmatched active SKUs.
- No guessed HPP is created for unresolved SKUs; low coverage blocks FINAL profit status.

## V1.9 — SKU Mapping Manager
V1.9 menambahkan mapping internal `SKU Toko → SKU Gudang`. Nama atau kode tidak harus sama. Mapping manual menjadi prioritas HPP tertinggi, exact-code match menjadi fallback, dan SKU yang belum terhubung tidak diberi HPP tebakan. Menu **SKU Mapping** menampilkan prioritas berdasarkan qty, saran kandidat, tombol Hubungkan, serta Ubah/Hapus Mapping. Setelah mapping disimpan, Profit Engine dan status data dihitung ulang otomatis.


## V1.9
- Bulk Mapping Manager dengan approval checkbox.
- Search/filter SKU Toko dan SKU Gudang.
- Batch save + single Profit Engine rebuild.
- Download unmapped list dan backup mapping manual.

---

## V2.0 — Deployment-Ready

Entry point utama V2:

```bash
streamlit run app/v2_main.py
```

V2 menyederhanakan aplikasi menjadi 5 menu operasional:
- Dashboard
- Import Data
- SKU Mapping
- Readiness & Simulator
- Audit & Settings

**Control Profit V2 tidak menggunakan BigSeller Keuntungan Toko sebagai sumber utama.** Source of Truth adalah Shopee Order + Shopee Income + HPP SKU + seluruh Paid Ads. BigSeller Keuntungan Toko hanya audit/cross-check.

Deployment files tersedia: `Dockerfile`, `Procfile`, `.streamlit/config.toml`, dan `run_app.sh`.
Lihat `docs/10_V20_DEPLOYMENT_READY.md`.

## V2.1 Deployment Hardening

- `DSC_DB_PATH` controls the persistent SQLite database location.
- Default local database: `data/daily_store_control.db`.
- `render.yaml` is included for Render with a persistent disk mounted at `/var/data`.
- `railway.toml` is included for Railway Docker deployment.
- `app/preflight.py` validates the database schema and core service imports without starting Streamlit.
- `run_app.sh` creates the database directory automatically and starts Streamlit on `$PORT` (default 8501).

### Local run

```bash
pip install -r requirements.txt
./run_app.sh
```

### Preflight

```bash
python app/preflight.py
python -m pytest -q
```

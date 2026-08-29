# 02 — Database & UI V1

## Database design
The database is daily-grain and source-separated. This prevents attribution mixing and keeps each source auditable.

Core tables:
- stores
- import_batches
- daily_store_metrics — Shopee Business Insight truth
- daily_ads_metrics — Shopee Ads attribution truth
- daily_profit_metrics — BigSeller profit truth + calculated control profit
- daily_data_quality — source status, overall status, confidence
- guardrails
- daily_decisions

Every imported source is linked to an import batch for traceability.

## UI V1
1. Sidebar — import source files and profit-definition setting.
2. Daily Pulse — 12 operational metrics plus data status/confidence.
3. Trend Dashboard — 7/14/30 day charts.
4. Data Coverage — source-by-source FINAL/BELUM_FINAL/PARTIAL/MISSING table.
5. Scale Simulator — baseline window, guardrails, budget change, three scenarios.

## Important V1 behavior
- Ads Sales is never added directly to store GMV.
- Control Profit is recalculated based on whether BigSeller profit already includes ads.
- BigSeller H+0/H+1 is conservatively marked BELUM_FINAL until real exports allow a better sync-finality test.
- Parser maps common column aliases but the exact Shopee/BigSeller export headers will be calibrated with real user files.

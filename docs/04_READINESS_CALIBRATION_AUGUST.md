# V1.4 Readiness Calibration — July & August 2026

## Why two readiness modes exist
The app does not fabricate daily profit from a monthly/MTD BigSeller snapshot.

- **DAILY mode**: authoritative for SCALE / KEEP / HOLD / REDUCE when daily BigSeller profit + daily ads are sufficiently complete.
- **PERIOD_PRELIMINARY mode**: useful for reading store health from exact-period BigSeller + Business Insight, but `scale_allowed = false`.

## August 1–28 reconciliation
- Business Insight Gross Sales: Rp450,623,501
- Cancelled Sales: Rp68,001,450
- Adjusted Store Sales: Rp382,622,051
- BigSeller Realized Sales: Rp381,090,338
- Variance: Rp1,531,713 (~0.40%)
- BigSeller GPMI: Rp112,107,805
- Product Ads Spend (BigSeller fallback): Rp51,483,790
- Live Ads Spend: Rp3,811,320
- Shop+ Spend: Rp859,252
- Total Paid Spend: Rp56,154,362
- Full Paid Media Control Profit: Rp107,437,233
- Full Control Margin: 28.19%
- Paid Ads Cost / Realized Sales: 14.74%

## Preliminary readiness result
Using July–August period history plus the latest 7-day Business Insight trend:

- Overall: **72.9 / 100 — KEEP**
- Profit & Margin: 93.7
- Ads Safety: 65.0 (capped because August Product Ads Shopee export is not yet verified)
- Conversion: 74.5
- Sales Momentum: 62.7
- Traffic Quality: 27.4
- Data Completeness: 85.0

This result is intentionally **not allowed to issue SCALE +10/+20/+30** because store profit is still only available at period grain and August Product Ads attribution has not yet been cross-checked from a matching Shopee export.

## Data-driven guardrail suggestions
These are suggestions only; the app does not auto-apply them.

- Minimum Control Margin: ~20.36%
- Maximum Paid Ads Cost: ~16.21%
- ROAS BEP: ~2.52x
- Minimum Safety Ratio: 1.25x
- Minimum ROAS: 4.00x

ROAS remains a safety metric; profit rupiah, control margin, momentum, and data completeness remain primary.

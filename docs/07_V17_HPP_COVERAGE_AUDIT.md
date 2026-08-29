# V1.7 HPP Coverage Audit

Period tested: order cohorts July 1-31 and August 1-28, 2026.

- Primary HPP source: BigSeller SKU master snapshot.
- Secondary HPP source: BigSeller Keuntungan SKU Gudang, used only to fill missing HPP by deriving Total Modal / units sold.
- BigSeller profit is not used as store profit.
- Cancelled orders are excluded from realized HPP coverage.

## Result

- Qty coverage after primary master: 95.56%
- Qty coverage after fallback: 95.92%
- Remaining active unmatched SKUs: 58
- Unmatched SKUs are not assigned guessed HPP.
- Daily profit cannot be FINAL if HPP coverage is below the configured finality threshold.

The remaining SKU list is exported to `data_samples/hpp_unmatched_audit_jul_aug.csv`.

# Real Data Reconciliation — July 2026

## Sources validated
- Shopee Business Insight: `Pesanan Dibuat`, daily rows 1–31 July.
- Shopee Product Ads: period and daily exports.
- Shopee Live Ads.
- Shopee Shop+ Ads.
- BigSeller Keuntungan Toko.
- BigSeller Keuntungan SKU Gudang.

## Locked rules
1. Shopee Business Insight `Total Penjualan (IDR)` is Gross Store Sales.
2. `Adjusted Store Sales = Total Penjualan - Penjualan Dibatalkan`.
3. Shopee CR uses exported `Tingkat Konversi Pesanan`; it is NOT recalculated as Orders / Visitors.
4. Ads Sales is attribution only and is never added to store omzet.
5. BigSeller Keuntungan Toko is the primary store-profit source.
6. BigSeller `Iklan` already includes Shopee Product Ads.
7. When GPMI exists, use it as profit basis because it already reflects Product Ads + PPN Iklan in the user's BigSeller custom calculation.
8. Live Ads and Shop+ are deducted from GPMI only when not already included in BigSeller.
9. Period files are stored as PERIOD snapshots; the system never spreads monthly totals across days.

## July reconciliation
- BigSeller Product Ads: Rp59,959,862
- Shopee Product Ads export: Rp59,959,865
- Variance: Rp-3
- GPMI: Rp111,024,889.78
- Live Ads: Rp3,861,271
- Shop+: Rp0
- Full Paid Media Control Profit: Rp107,163,618.78
- Realized Sales basis: Rp447,381,878
- Full Paid Media Control Margin: 23.9535%

Formula:
`Full Paid Media Control Profit = GPMI - Live Ads - Shop+ Ads`

For July:
`111,024,889.78 - 3,861,271 - 0 = 107,163,618.78`

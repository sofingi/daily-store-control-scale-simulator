# V1.6 Independent Profit Engine

## Source of truth
- Business Insight: store performance only.
- Shopee Order: order cohort, SKU, quantity, status, returns.
- Shopee Income: released settlement and marketplace deductions, joined by No. Pesanan.
- Shopee Product Ads / Shop+ / Live Ads: paid media cost by channel.
- BigSeller Master SKU: HPP only.
- BigSeller Profit reports: audit/cross-check only.

## Profit status
- FINAL: settlement coverage >=98%, HPP coverage >=98%, daily Ads available.
- ESTIMATED: settlement not fully released; historical fee rate is used for unreleased orders.
- PARTIAL: settlement coverage <70% or HPP coverage <90%.
- MISSING: core source unavailable.

## Core rules
1. Ads Sales is never added to store omzet.
2. Cancelled orders carry zero realized revenue and zero realized HPP.
3. Income is joined to orders by No. Pesanan, not by release-date period.
4. BigSeller HPP is attached at SKU line level.
5. New Shopee ad channels are additive cost channels; no dependency on BigSeller's Iklan field.
6. SCALE is blocked when profit status is PARTIAL/MISSING and is conservative when ESTIMATED.

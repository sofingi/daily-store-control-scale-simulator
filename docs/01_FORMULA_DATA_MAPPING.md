# 01 — Formula & Data Mapping Contract

## A. Canonical daily metrics

### Shopee Business Insight (store truth)
- store_gmv = daily store sales/omzet from Business Insight
- orders = daily orders
- visitors = daily unique visitors
- conversion_rate = orders / visitors
- buyers (optional)
- page_views (optional)

### Shopee Ads (attribution truth)
- ads_spend
- ads_sales
- impressions
- clicks
- ads_orders (optional)
- roas = ads_sales / ads_spend
- acos = ads_spend / ads_sales
- cpc = ads_spend / clicks
- rpm = ads_sales / impressions * 1000
- ctr = clicks / impressions

Important: ads_sales is attribution, not additive omzet. Do NOT calculate store_gmv + ads_sales.

### BigSeller Keuntungan SKU Gudang (profit truth)
- bs_revenue_basis = denominator used by BigSeller for aggregate margin; parser must reconcile against BigSeller export/UI.
- bs_cogs
- bs_profit
- bs_margin = sum(bs_profit) / sum(bs_revenue_basis)

Do not average row-level margin percentages.

### Decision metrics
Two profit layers are retained:
1. bs_profit_reported = BigSeller as-is.
2. control_profit_after_ads = bs_profit_reported - ads_spend, ONLY when the BigSeller profit definition excludes advertising cost.

If BigSeller profit already includes advertising cost, control_profit_after_ads = bs_profit_reported.

The inclusion rule is a configuration flag and must be validated against real data before production use.

control_margin = control_profit_after_ads / bs_revenue_basis

## B. Data coverage & sync status
Each daily source receives one of:
- FINAL: expected data is present and passes completeness checks.
- PARTIAL: source exists but row/value coverage is suspicious or incomplete.
- BELUM_FINAL: newest H+0/H+1 source is likely still syncing.
- MISSING: no file/data for required source.

Overall daily status:
- FINAL if mandatory sources are FINAL.
- BELUM_FINAL if Business Insight/Ads are present but BigSeller on H+0/H+1 is not final.
- PARTIAL if any mandatory historical source is incomplete.
- MISSING if a mandatory source is absent.

Hard decision gate:
- If BigSeller status != FINAL, aggressive SCALE is blocked.
- Recommended action becomes WAIT FOR DATA SYNC unless a defensive REDUCE/HOLD action is required for clear ad overspend risk.

## C. Completeness confidence score (0-100)
Suggested V1:
- Business Insight coverage: 30
- Shopee Ads coverage: 20
- BigSeller coverage: 40
- Cross-source consistency: 10

Penalty examples:
- BigSeller H+0: -25 confidence unless specifically marked finalized.
- BigSeller H+1: -15 confidence unless specifically marked finalized.
- Abrupt revenue drop >35% vs adjacent comparable days without matching Business Insight drop: flag partial.
- Date missing in mandatory source: source score = 0.

## D. Store Scale Readiness Score (0-100)
Weights:
- Profit & Margin: 30
- Ads Safety: 20
- Conversion: 15
- Sales Momentum: 15
- Traffic Quality: 10
- Data Completeness: 10

Decision score is separate from confidence. A high readiness score cannot override a failed data gate.

### Profit & Margin (30)
Inputs:
- current control margin vs minimum margin guardrail
- profit trend 7d vs prior 7d
- positive control profit consistency

### Ads Safety (20)
Inputs:
- ROAS vs minimum ROAS / ROAS BEP
- ads cost % of store_gmv
- safety_ratio
- recent ROAS volatility

### Conversion (15)
Inputs:
- CR current 7d vs previous 7d
- CR stability
- CR relative to store baseline

### Sales Momentum (15)
Inputs:
- store_gmv 7d vs prior 7d
- order growth
- profit growth

### Traffic Quality (10)
Inputs:
- visitor growth
- CR direction
- CPC / CTR / RPM efficiency

### Data Completeness (10)
Derived from completeness confidence.

## E. Guardrails
Configurable per store:
- minimum_margin
- minimum_roas
- roas_bep
- minimum_safety_ratio
- maximum_ads_cost_pct
- recommended_budget
- hard_budget_limit

Suggested Safety Ratio V1:
Safety Ratio = ROAS / ROAS_BEP
Interpretation:
- < 1.00 = below break-even
- 1.00–1.15 = thin safety
- 1.15–1.35 = acceptable
- > 1.35 = strong buffer

ROAS_BEP can be entered manually or estimated from contribution margin before ads:
ROAS_BEP = 1 / contribution_margin_before_ads
where margin is expressed as decimal.

## F. Daily Recommendation hierarchy
1. WAIT FOR DATA SYNC
   - BigSeller not FINAL and no urgent defensive risk.
2. REDUCE
   - ROAS below BEP or projected margin below floor or ads cost exceeds hard guardrail.
3. DEFEND PROFIT / HOLD
   - Profit/margin weak or unstable while ads still near safe zone.
4. KEEP
   - Healthy but readiness is not high enough to scale.
5. SCALE +10/+20/+30/custom
   - Data FINAL, readiness high, confidence high, guardrails pass, simulation remains safe.

Suggested readiness thresholds:
- 80–100: SCALE candidate
- 65–79: KEEP / small scale only
- 50–64: HOLD / DEFEND PROFIT
- <50: REDUCE / repair fundamentals

## G. Scale Simulator V1
Baseline window default: latest 7 FINAL days. User may select 7/14/30.

Budget change d = 0.10 / 0.20 / 0.30 / custom.
new_ads_spend = baseline_ads_spend * (1 + d)

Scenario ROAS decay:
- Optimistic decay coefficient: 0.25
- Realistic: 0.60
- Conservative: 1.00

projected_roas = baseline_roas * (1 - decay_coefficient * d)
projected_ads_sales = new_ads_spend * projected_roas

Incrementality factor (share of incremental ad-attributed sales that becomes incremental store sales):
- Optimistic: 0.80
- Realistic: 0.60
- Conservative: 0.40

incremental_ads_sales = projected_ads_sales - baseline_ads_sales
incremental_store_gmv = max(0, incremental_ads_sales) * incrementality_factor
projected_store_gmv = baseline_store_gmv + incremental_store_gmv

If contribution_margin_before_ads is available:
incremental_gross_profit = incremental_store_gmv * contribution_margin_before_ads
incremental_ad_cost = new_ads_spend - baseline_ads_spend
projected_control_profit = baseline_control_profit + incremental_gross_profit - incremental_ad_cost
projected_margin = projected_control_profit / projected_store_gmv
additional_profit = projected_control_profit - baseline_control_profit

Risk level:
- LOW: all projected guardrails pass with >15% buffer and confidence >=85.
- MEDIUM: guardrails pass but one metric is within 15% of threshold or confidence 70–84.
- HIGH: any projected guardrail fails, confidence <70, or data not FINAL.

The simulator is a decision aid, not a causal forecast. Scenario coefficients will later be calibrated from the store's own historical response to budget changes.

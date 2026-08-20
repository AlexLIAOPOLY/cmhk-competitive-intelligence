# CMHK Historical Indicator Backlog

- Build date: 2026-06-19
- Purpose: persistent queue of official government/regulator/public-institution historical indicators that may improve CMHK trend interpretation or forecasting context.
- Rule: backlog entries are persistent collection tasks. Some may already be partially collected in `macro_policy_metrics.csv`; additional rows may be added only after official values are parsed, source links are verified, `verification_count >= 2` is satisfied where possible, and source gaps are explicitly retained rather than estimated.

| priority | domain | source family | target grain | status | CMHK relevance |
|---|---|---|---|---|---|
| P0 | telecom_market_quality | OFCA consumer complaints | quarterly | partially_collected_current_table | Customer experience and service-quality pressure indicator for mobile and broadband competition. |
| P0 | fixed_broadband_demand | OFCA internet service subscriptions | monthly_or_quarterly | collected_current_official_pdf_with_legacy_boundary | Fixed broadband adoption and household connectivity context for CMHK convergence, enterprise and home broadband strategy. |
| P0 | telecom_market_snapshot | OFCA key communications statistics | monthly_point_in_time | collected_official_datagovhk_csv_history | Core market saturation, network adoption and operator landscape context for CMHK trend interpretation. |
| P1 | household_demand_capacity | C&SD domestic households and income | annual_and_moving_3_month | collected_official_mdt_csv_history | Household formation and income capacity explain home broadband, mobile-plan mix and consumer telecom demand. |
| P1 | population_demographics | C&SD population estimates | mid_year_and_year_end_snapshot | collected_official_mdt_csv_compact_history | Addressable market, ageing, household formation and district demand context for network and customer-base planning. |
| P1 | financial_conditions | HKMA monetary and interest-rate statistics | monthly | queued_api_collection | Financing cost, consumer and enterprise spending conditions, and valuation/discount-rate context for telecom and cloud investment cycles. |
| P1 | exchange_rate_conditions | HKMA exchange rates and interest rates | monthly_or_daily | queued_api_collection | Currency and rate conditions affect imported equipment cost, cloud infrastructure economics and enterprise spending cycles. |
| P2 | digital_policy | Digital Policy Office / OGCIO digital policy milestones | event | queued_policy_event_review | Public-sector digital demand, smart-city and enterprise cloud/telecom policy context. |

## Collection Rules

- P0 items should be tested first because they are closest to telecom-market demand or service quality.
- P1 items are macro and demographic context; they should be modeled as exogenous/context indicators rather than direct CMHK operating targets.
- P2 items are mostly policy/event context and must not be converted into numeric forecasts without a reviewed event-encoding model.
- If an official page only exposes current snapshots, keep it as a current context source until official archives are found.
- Do not scrape image-only charts into numeric rows unless the underlying official table or data file is found.
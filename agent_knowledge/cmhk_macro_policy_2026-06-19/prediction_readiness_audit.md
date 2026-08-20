# Prediction Readiness Audit

- Rows: 7580
- official_match rows: 7577
- source_gap_confirmed rows: 3
- verification_count < 2 rows: 0

## Current Readiness

- OFCA annual telecommunications indicators: ready for 10-year annual trend context and explanatory features.
- OFCA Key Communications Statistics: ready as official monthly point-in-time market-snapshot context where CSV fields are populated; blank fields are not estimated.
- OFCA internet service subscriptions: ready as fixed-broadband adoption context; post-2019 access lines and pre-2019 customer accounts are separate methodology families.
- OFCA consumer complaint statistics: ready as current official service-quality pressure context; older history remains backlog until official archives are found.
- C&SD monthly CPI/retail/labour and quarterly PCE/GDP-growth indicators: ready as macro/exogenous time-series context for forecasting explanation.
- C&SD domestic households and income: ready as official household demand-capacity context; annual and moving-three-month rows are separate grains and should be used as explanatory context, not direct CMHK operating targets.
- C&SD population estimates: ready as official addressable-market and age-mix context; mid-year and year-end rows are separate snapshots and should be used as demographic context, not direct CMHK operating targets.
- OFCA Wireless Services annual December snapshots: ready for annual mobile-market adoption and usage context, not high-frequency forecast-target fitting.
- C&SD annual household internet access indicators: ready for adoption/saturation context where official annual data exists.
- Policy / spectrum / regulatory milestones: ready for qualitative context and event-flag enrichment.
- Remaining source gap for future enrichment: OFCA 4G/5G split wireless columns and additional C&SD district/deeper demographic series can be added where official structured access is available, but no current row is estimated.

## Rules

- Use `official_value` for formal conclusions.
- Treat `source_gap_confirmed` as a disclosure boundary; do not interpolate missing policy or market statistics.
- Do not treat event rows as numeric targets unless a separate reviewed model explicitly defines event encodings.
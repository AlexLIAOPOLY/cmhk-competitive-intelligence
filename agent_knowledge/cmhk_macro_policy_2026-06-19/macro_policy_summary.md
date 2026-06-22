# CMHK Macro Policy and Institutional Indicators Summary

- Build date: 2026-06-19
- Rows: 7580
- Current coverage: OFCA official annual telecommunications indicators for FY2015/16-FY2024/25; OFCA Key Communications Statistics point-in-time CSV history for 2017-2026 where official fields are populated; OFCA Wireless Services December snapshots for 2016-2025; OFCA Internet Service Subscriptions post-2019 access-line and pre-2019 legacy customer-account snapshots; OFCA current consumer complaint statistics for 2023-2026 Q1; C&SD official monthly/quarterly/annual macro, GDP growth, labour-market, and domestic-household/income series from the latest available 10-year window; selected official policy/spectrum/5G milestones.
- Source integrity: every current row has `verification_count >= 2`; unavailable official cells remain `source_gap_confirmed` and are not estimated.

## Prediction Readiness

- C&SD monthly CPI/retail/labour rows and quarterly PCE/GDP-growth rows are suitable as macro/exogenous context for forecasting and scenario interpretation.
- OFCA annual telecom indicators are suitable for long-term annual telecom-market trend context, not high-frequency quarterly target fitting.
- OFCA internet service subscriptions are useful for fixed-broadband adoption context; post-2019 access-line rows and pre-2019 customer-account rows must not be merged into one forecast target.
- OFCA Key Communications Statistics rows are monthly point-in-time market snapshots from official data.gov.hk CSV; blank fields are not estimated or converted to zero.
- C&SD domestic-household/income rows are household demand-capacity context; annual and moving-three-month rows must be kept as separate grains.
- OFCA consumer complaint rows are service-quality and customer-experience pressure context, not direct revenue or subscriber forecast targets.
- Policy event rows are explanatory regressors/context for interpretation and scenario discussion, not numeric forecast targets.
- OFCA Wireless Services December snapshots are useful for annual mobile-market context; 4G/5G split columns remain excluded from generated rows until a safer structured source is available.

## Rows by Verification Status

- official_match: 7577
- source_gap_confirmed: 3

## Rows by Source Family

- OFCA key communications statistics: 1955
- C&SD Consumer prices: 1488
- C&SD domestic households and income: 1217
- C&SD population estimates: 820
- C&SD Retail sales: 620
- C&SD Private consumption expenditure: 410
- C&SD Labour market: 375
- OFCA telecommunications indicators: 229
- C&SD GDP and demand growth: 164
- OFCA wireless services: 150
- OFCA internet service subscriptions: 77
- OFCA consumer complaints: 28
- OFCA internet service subscriptions legacy customer accounts: 27
- C&SD Household internet access: 14
- government_regulatory_policy: 6

## Verification Status by Source Family

- OFCA key communications statistics: 1955 rows (official_match=1955)
- C&SD Consumer prices: 1488 rows (official_match=1488)
- C&SD domestic households and income: 1217 rows (official_match=1217)
- C&SD population estimates: 820 rows (official_match=820)
- C&SD Retail sales: 620 rows (official_match=620)
- C&SD Private consumption expenditure: 410 rows (official_match=410)
- C&SD Labour market: 375 rows (official_match=375)
- OFCA telecommunications indicators: 229 rows (official_match=228, source_gap_confirmed=1)
- C&SD GDP and demand growth: 164 rows (official_match=164)
- OFCA wireless services: 150 rows (official_match=148, source_gap_confirmed=2)
- OFCA internet service subscriptions: 77 rows (official_match=77)
- OFCA consumer complaints: 28 rows (official_match=28)
- OFCA internet service subscriptions legacy customer accounts: 27 rows (official_match=27)
- C&SD Household internet access: 14 rows (official_match=14)
- government_regulatory_policy: 6 rows (official_match=6)

## Largest Indicator Groups

- Consumer prices: 1488
- Domestic households and income: 1217
- Population demographics: 820
- Telecommunications Services: 809
- Retail sales: 620
- Internet Services: 536
- Television Broadcasting Services: 490
- Private consumption expenditure: 410
- Labour market: 375
- GDP and demand growth: 164
- Wireless Services: 150
- Internet Service Subscriptions: 104
- Sound Broadcasting Services: 87
- Tariffs: 40
- Telephone Network: 40
- Fibre Broadband Network Coverage: 33
- Traffic: 30
- Mobile Services: 29
- Consumer Complaints: 28
- Broadcasting: 20

## Use In 小竞AI

- Use this package when users ask about Hong Kong telecom market saturation, mobile/broadband adoption, spectrum/5G policy, telecom investment, or macro-regulatory context affecting CMHK.
- For formal conclusions, use `official_value` and read `verification_sources` before citing a row.
- Do not convert policy events into numeric forecasts unless a reviewed model explicitly encodes them as event indicators.
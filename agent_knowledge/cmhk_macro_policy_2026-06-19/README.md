# CMHK Macro Policy and Institutional Indicators (10-year target)

This package adds CMHK-relevant macro, policy, regulatory, and public-institution indicators alongside the competitor and cloud vendor metrics database.

Current build status: usable for 小竞AI RAG and forecast-context support. It contains 7,580 rows, with 7,577 official-match rows, 3 official source-gap rows, and 0 rows below `verification_count=2`.

## Scope

- Target window: 10 years where official/public data is available.
- Preferred grain: monthly or quarterly for statistical indicators; annual for policy/regulatory indicators that are only published annually; event/date grain for spectrum, licensing, subsidy, cyber/data, and smart-city policy milestones.
- Source priority: Hong Kong government departments, regulators, statutory bodies, public data portals, and official institutional publications.
- No estimation rule: missing public disclosure is recorded as `source_gap_confirmed` or kept blank, not filled by interpolation.

## Source Families Included

- OFCA key communications statistics: official data.gov.hk CSV point-in-time history covering populated fields from 2017-10 to 2026-05; 1,955 rows across 31 metrics including mobile subscriptions, mobile penetration, broadband subscriptions, household broadband penetration, operator counts, public Wi-Fi access points and fibre coverage. Blank CSV cells are not estimated.
- OFCA telecommunications indicators: fiscal-year market, adoption, tariff, revenue, traffic, investment, staff and infrastructure indicators for FY2015/16-FY2024/25.
- OFCA wireless services: December annual snapshots for 2016-2025 covering mobile subscriptions, mobile broadband subscriptions, 3G subscriptions, MVNO subscriptions, machine-type connections, mobile data usage and SMS traffic where the official PDF table can be safely parsed.
- OFCA internet service subscriptions: official PDF rows for 2019-2025 access-line snapshots and 2016-2018 legacy customer-account snapshots, kept as separate source families because OFCA changed methodology in January 2019.
- OFCA consumer complaints: official current complaint table covering 2023-2025 annual service-type complaints and 2026 Q1 complaints; older complaint history remains a backlog task until official archived tables are found.
- C&SD consumer prices: monthly Composite CPI, CPI(A), CPI(B), CPI(C) values and changes in the latest official 10-year window.
- C&SD private consumption expenditure: quarterly PCE and selected component values / year-on-year changes in chained dollars.
- C&SD GDP and demand growth: quarterly real GDP / demand-component year-on-year and quarter-to-quarter growth context.
- C&SD labour market: moving-three-month labour force and unemployment indicators for the latest official 10-year window.
- C&SD domestic households and income: official annual and moving-three-month household count, household-size, income and owner-occupier indicators covering 2016-01-31 to 2026-04-30; 1,217 rows across 10 metrics.
- C&SD population estimates: official mid-year and year-end population by sex and age-group indicators covering 2016-06-30 to 2025-12-31; 820 rows across 41 compact metrics.
- C&SD retail sales: monthly value, value index and volume index indicators.
- C&SD household internet access: annual household access level/rate where official survey data is available.
- Regulatory and infrastructure policy: selected official 5G, spectrum, SIM registration, and rural/remote coverage milestones.

## Remaining Extension Boundaries

- OFCA key communications statistics are market-level point-in-time context rows, not company-level revenue forecast targets.
- OFCA 4G/5G split columns remain excluded from the Wireless Services PDF parser because that PDF extraction splits them across continuation rows; add them only when a safer official structured source is available.
- OFCA internet service subscription access-line rows from 2019 onward and customer-account rows before 2019 are not directly comparable and must not be merged into a single forecast series.
- Additional C&SD demographic tables can be added later as enrichments where official structured access is available.
- C&SD population rows are addressable-market and demographic context, not direct CMHK operating targets.
- C&SD domestic-household moving-three-month rows are household demand-capacity context, not CMHK company operating quarters.
- OFCA consumer complaints before 2023 are not estimated; older rows should only be added from official archived OFCA complaint tables.
- Policy/event records are context rows, not numeric forecast targets.
- Missing public disclosure remains `source_gap_confirmed`; no value is estimated.

## Required Output Files

- `macro_policy_metrics.csv`
- `macro_policy_metrics.json`
- `macro_policy_summary.md`
- `household_income_reference.md`
- `population_reference.md`
- `sources.json`
- `online_verification_2026-06-19.csv`
- `prediction_readiness_audit.md`
- `historical_indicator_backlog.md`

Each row must preserve source links, evidence notes, `verification_count`, conflict/source-gap status, and `official_value` for formal use.
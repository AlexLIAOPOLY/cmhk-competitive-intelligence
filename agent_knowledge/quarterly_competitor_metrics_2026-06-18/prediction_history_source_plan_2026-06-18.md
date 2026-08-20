# Prediction History Source Plan (2026-06-18)

This file controls the next collection pass for extending the current
quarterly/semiannual package to prediction-ready history.

## Coverage Gate

- Current package after the China Telecom 2019 core-metrics batch: `quarterly_metrics.csv`, 2,578 rows.
- Coverage audit: `prediction_history_coverage_2026-06-18.csv` and `.md`.
- Target: cloud vendors need a hard 40 quarters / 10 years and must not be accepted on the 7-year minimum; source-gap or annual-only cloud periods must be documented rather than estimated, but they do not count toward the 40-quarter coverage window. Non-cloud quarterly subjects need at least 28 quarters and preferably 40 quarters; semiannual-only subjects need 20 half-year periods.
- Do not add a row to the main package unless it has row-level source evidence, `verification_sources`, `verification_count`, and a terminal status such as `official_match`, `official_conflict`, `official_only`, or `source_gap_confirmed`.

## Completed Extension Batches

- AWS 2024 Q1-Q4 added on 2026-06-18:
  - Metrics: AWS segment `revenue` / net sales and `operating_income`.
  - Periods: Q1 2024, Q2 2024, Q3 2024, Q4 2024.
  - Source roots: Amazon official quarterly results index and Amazon Q1/Q2/Q3/Q4 2024 earnings releases.
  - Result: AWS rows increased from 8 to 16; AWS distinct quarterly periods increased from 4 to 8; all new rows are `official_match` with `verification_count=2`.
- AWS 2023 Q1-Q4 added on 2026-06-18:
  - Metrics: AWS segment `revenue` / net sales and `operating_income`.
  - Periods: Q1 2023, Q2 2023, Q3 2023, Q4 2023.
  - Source roots: Amazon official quarterly results index plus Amazon Q3/Q4 2023 earnings release AWS Segment trailing tables.
  - Result: AWS rows increased from 16 to 24; AWS distinct quarterly periods increased from 8 to 12; all new rows are `official_match` with `verification_count=2`.
- AWS 2022 Q1-Q4 added on 2026-06-18:
  - Metrics: AWS segment `revenue` / net sales and `operating_income`.
  - Periods: Q1 2022, Q2 2022, Q3 2022, Q4 2022.
  - Source roots: Amazon 2022 Form 10-K AWS Segment Information plus Amazon Q3/Q4 2023 earnings release trailing AWS Segment tables.
  - Result: AWS rows increased from 24 to 32; AWS distinct quarterly periods increased from 12 to 16; all new rows are `official_match`. Q1 2022 uses official full-year AWS segment totals minus Q2-Q4 trailing table values and is marked `official_annual_minus_q2_q4_segment_reconciliation`.
- AWS 2021 Q1-Q4 added on 2026-06-18:
  - Metrics: AWS segment `revenue` / net sales and `operating_income`.
  - Periods: Q1 2021, Q2 2021, Q3 2021, Q4 2021.
  - Source roots: Amazon SEC 2021 Q1/Q2/Q3 Form 10-Q Segment Information and 2021 Form 10-K Segment Information.
  - Result: AWS rows increased from 32 to 40; AWS distinct quarterly periods increased from 16 to 20; all new rows are `official_match`. Q4 2021 uses official full-year AWS segment totals minus Q1-Q3 10-Q values and is marked `official_annual_minus_q1_q3_segment_reconciliation`.
- AWS 2020 Q1-Q4 added on 2026-06-18:
  - Metrics: AWS segment `revenue` / net sales and `operating_income`.
  - Periods: Q1 2020, Q2 2020, Q3 2020, Q4 2020.
  - Source roots: Amazon SEC 2020 Q1/Q2/Q3 Form 10-Q Segment Information and 2020 Form 10-K Segment Information.
  - Result: AWS rows increased from 40 to 48; AWS distinct quarterly periods increased from 20 to 24; all new rows are `official_match`. Q4 2020 uses official full-year AWS segment totals minus Q1-Q3 10-Q values and is marked `official_annual_minus_q1_q3_segment_reconciliation`.
- AWS 2019 Q1-Q4 added on 2026-06-18:
  - Metrics: AWS segment `revenue` / net sales and `operating_income`.
  - Periods: Q1 2019, Q2 2019, Q3 2019, Q4 2019.
  - Source roots: Amazon SEC 2019 Q1/Q2/Q3 Form 10-Q Segment Information and 2019 Form 10-K Segment Information.
  - Result: AWS rows increased from 48 to 56; AWS distinct quarterly periods increased from 24 to 28; all new rows are `official_match`. Q4 2019 uses official full-year AWS segment totals minus Q1-Q3 10-Q values and is marked `official_annual_minus_q1_q3_segment_reconciliation`.
- AWS 2018 Q1-Q4 added on 2026-06-18:
  - Metrics: AWS segment `revenue` / net sales and `operating_income`.
  - Periods: Q1 2018, Q2 2018, Q3 2018, Q4 2018.
  - Source roots: Amazon SEC 2018 Q1/Q2/Q3 Form 10-Q Segment Information and 2018 Form 10-K Segment Information.
  - Result: AWS rows increased from 56 to 64; AWS distinct quarterly periods increased from 28 to 32; all new rows are `official_match`. Q4 2018 uses official full-year AWS segment totals minus Q1-Q3 10-Q values and is marked `official_annual_minus_q1_q3_segment_reconciliation`.
- AWS 2017 Q1-Q4 added on 2026-06-18:
  - Metrics: AWS segment `revenue` / net sales and `operating_income`.
  - Periods: Q1 2017, Q2 2017, Q3 2017, Q4 2017.
  - Source roots: Amazon SEC 2017 Q1/Q2/Q3 Form 10-Q Segment Information and 2017 Form 10-K Segment Information.
  - Result: AWS rows increased from 64 to 72; AWS distinct quarterly periods increased from 32 to 36; all new rows are `official_match`. Q4 2017 uses official full-year AWS segment totals minus Q1-Q3 10-Q values and is marked `official_annual_minus_q1_q3_segment_reconciliation`.
- AWS 2016 Q1-Q4 added on 2026-06-18:
  - Metrics: AWS segment `revenue` / net sales and `operating_income`.
  - Periods: Q1 2016, Q2 2016, Q3 2016, Q4 2016.
  - Source roots: Amazon SEC 2016 Q1/Q2/Q3 Form 10-Q Segment Information and 2016 Form 10-K Segment Information.
  - Result: AWS rows increased from 72 to 80; AWS distinct quarterly periods increased from 36 to 40; all new rows are `official_match`. Q4 2016 uses official full-year AWS segment totals minus Q1-Q3 10-Q values and is marked `official_annual_minus_q1_q3_segment_reconciliation`.
- Microsoft Azure / Intelligent Cloud 2024 Q1-Q4 added on 2026-06-18:
  - Metrics: Intelligent Cloud `revenue`, Intelligent Cloud `operating_income`, and `azure_and_other_cloud_services_growth_yoy`.
  - Periods: Q1 2024, Q2 2024, Q3 2024, Q4 2024.
  - Source roots: Microsoft official FY24 Q3/Q4 and FY25 Q1/Q2 earnings release and segment revenue pages.
  - Result: Microsoft rows increased from 15 to 27; Microsoft distinct quarterly periods increased from 5 to 9; all new rows are `official_match` with `verification_count=3`.
- Microsoft Azure / Intelligent Cloud 2023 Q1-Q4 added on 2026-06-18:
  - Metrics: Intelligent Cloud `revenue`, Intelligent Cloud `operating_income`, and `azure_and_other_cloud_services_growth_yoy`.
  - Periods: Q1 2023, Q2 2023, Q3 2023, Q4 2023.
  - Source roots: Microsoft official FY23 Q3/Q4 and FY24 Q1/Q2 earnings release and segment revenue pages.
  - Result: Microsoft rows increased from 27 to 39; Microsoft distinct quarterly periods increased from 9 to 13; all new rows are `official_match` with `verification_count=3`. Q2 2023 revenue and operating income use FY2023 annual Intelligent Cloud totals minus FY23 first-nine-month Intelligent Cloud totals.
- Microsoft Azure / Intelligent Cloud 2022 Q1-Q4 added on 2026-06-18:
  - Metrics: Intelligent Cloud `revenue`, Intelligent Cloud `operating_income`, and `azure_and_other_cloud_services_growth_yoy`.
  - Periods: Q1 2022, Q2 2022, Q3 2022, Q4 2022.
  - Source roots: Microsoft official FY22 Q3/Q4 and FY23 Q1/Q2 earnings releases; Microsoft SEC FY22 Q3 10-Q and FY22 10-K for exact segment tables where the old Microsoft segment URL is unavailable.
  - Result: Microsoft rows increased from 39 to 51; Microsoft distinct quarterly periods increased from 13 to 17; all new rows are `official_match` with `verification_count=3`. Q2 2022 revenue and operating income use FY2022 annual Intelligent Cloud totals minus FY22 first-nine-month Intelligent Cloud totals.
- Microsoft Azure / Intelligent Cloud 2021 Q1-Q4 added on 2026-06-18:
  - Metrics: Intelligent Cloud `revenue`, Intelligent Cloud `operating_income`, and `azure_and_other_cloud_services_growth_yoy`.
  - Periods: Q1 2021, Q2 2021, Q3 2021, Q4 2021.
  - Source roots: Microsoft official FY21 Q3/Q4 and FY22 Q1/Q2 earnings releases; Microsoft SEC FY21 Q3 10-Q, FY21 10-K, FY22 Q1 10-Q, and FY22 Q2 10-Q for exact segment tables.
  - Result: Microsoft rows increased from 51 to 63; Microsoft distinct quarterly periods increased from 17 to 21; all new rows are `official_match` with `verification_count=3`. Q2 2021 revenue and operating income use FY2021 annual Intelligent Cloud totals minus FY21 first-nine-month Intelligent Cloud totals. Q3 2021 uses the contemporaneous FY22 Q1 Form 10-Q segment table and notes later FY23 comparison-table restatement.
- Microsoft Azure / Intelligent Cloud 2020 Q1-Q4 added on 2026-06-18:
  - Metrics: Intelligent Cloud `revenue`, Intelligent Cloud `operating_income`, and `azure_and_other_cloud_services_growth_yoy`.
  - Periods: Q1 2020, Q2 2020, Q3 2020, Q4 2020.
  - Source roots: Microsoft official FY20 Q3/Q4 and FY21 Q1/Q2 earnings releases; Microsoft SEC FY20 Q3 10-Q, FY20 10-K, FY21 Q1 10-Q, and FY21 Q2 10-Q for exact segment tables.
  - Result: Microsoft rows increased from 63 to 75; Microsoft distinct quarterly periods increased from 21 to 25; all new rows are `official_match` with `verification_count=3`. Q2 2020 revenue and operating income use FY2020 annual Intelligent Cloud totals minus FY20 first-nine-month Intelligent Cloud totals.
- Microsoft Azure / Intelligent Cloud 2019 Q1-Q4 added on 2026-06-18:
  - Metrics: Intelligent Cloud `revenue`, Intelligent Cloud `operating_income`, and `azure_and_other_cloud_services_growth_yoy`.
  - Periods: Q1 2019, Q2 2019, Q3 2019, Q4 2019.
  - Source roots: Microsoft official FY19 Q3/Q4 and FY20 Q1/Q2 earnings releases; Microsoft SEC FY19 Q3 10-Q, FY19 10-K, FY20 Q1 10-Q, and FY20 Q2 10-Q for exact segment tables.
  - Result: Microsoft rows increased from 75 to 87; Microsoft distinct quarterly periods increased from 25 to 29; all new rows are `official_match` with `verification_count=3`. Q2 2019 revenue and operating income use FY2019 annual Intelligent Cloud totals minus FY19 first-nine-month Intelligent Cloud totals.
- Microsoft Azure / Intelligent Cloud 2018 Q1-Q4 added on 2026-06-18:
  - Metrics: Intelligent Cloud `revenue`, Intelligent Cloud `operating_income`, and `azure_and_other_cloud_services_growth_yoy`.
  - Periods: Q1 2018, Q2 2018, Q3 2018, Q4 2018.
  - Source roots: Microsoft official FY18 Q3/Q4 and FY19 Q1/Q2 earnings releases; Microsoft SEC FY18 Q3 10-Q, FY18 10-K, FY19 Q1 10-Q, and FY19 Q2 10-Q for exact segment tables.
  - Result: Microsoft rows increased from 87 to 99; Microsoft distinct quarterly periods increased from 29 to 33; all new rows are `official_match` with `verification_count=3`. Q2 2018 revenue and operating income use FY2018 annual Intelligent Cloud totals minus FY18 first-nine-month Intelligent Cloud totals.
- Microsoft Azure / Intelligent Cloud 2017 Q1-Q4 added on 2026-06-18:
  - Metrics: Intelligent Cloud `revenue`, Intelligent Cloud `operating_income`, and `azure_and_other_cloud_services_growth_yoy`.
  - Periods: Q1 2017, Q2 2017, Q3 2017, Q4 2017.
  - Source roots: Microsoft official FY17 Q3/Q4 and FY18 Q1/Q2 earnings releases; Microsoft SEC FY17 Q3 10-Q, FY17 10-K, FY18 Q1 10-Q, and FY18 Q2 10-Q for exact segment tables.
  - Result: Microsoft rows increased from 99 to 111; Microsoft distinct quarterly periods increased from 33 to 37; all new rows are `official_match` with `verification_count=3`. Q2 2017 revenue and operating income use FY2017 annual Intelligent Cloud totals minus FY17 first-nine-month Intelligent Cloud totals.
- Microsoft Azure / Intelligent Cloud 2016 Q2-Q4 added on 2026-06-18:
  - Metrics: Intelligent Cloud `revenue`, Intelligent Cloud `operating_income`, and `azure_and_other_cloud_services_growth_yoy`.
  - Periods: Q2 2016, Q3 2016, Q4 2016.
  - Source roots: Microsoft official FY16 Q4 and FY17 Q1/Q2 earnings releases; Microsoft SEC FY16 10-K, FY16 Q3 10-Q, FY17 Q1 10-Q, and FY17 Q2 10-Q for exact segment tables/reconciliations.
  - Result: Microsoft rows increased from 111 to 120; Microsoft distinct quarterly periods increased from 37 to 40; all new rows are `official_match` with `verification_count=3`. Q2 2016 revenue and operating income use FY2016 annual Intelligent Cloud totals minus FY16 first-nine-month Intelligent Cloud totals.
- Google Cloud 2020 Q1-2024 Q4 added on 2026-06-18:
  - Metrics: Google Cloud `revenue`, `operating_income`, and `revenue_growth_yoy`.
  - Periods: Q1 2020 through Q4 2024. Existing Q1 2025-Q4 2025 rows remain in the package.
  - Source roots: Alphabet official SEC 10-Q quarterly segment tables and 2020-2024 Form 10-K Google Cloud segment tables; Q4 rows use annual Google Cloud segment totals minus Q1-Q3 official quarterly rows.
  - Result: package rows increased from 2,213 to 2,273; Google Cloud rows increased to 72; Google Cloud distinct quarterly periods increased to 24, covering Q1 2020-Q4 2025. All Google Cloud rows are `official_match` with `verification_count=3`. Coverage audit still marks Google Cloud `below_minimum_needs_extension` because 2016-2019 lack 16 quarters toward the cloud 40-quarter target.
  - RAG/forecast check: `retrieve_context("Google Cloud Q4 2020 revenue 3831 operating loss 1243 official annual reconciliation")`, `retrieve_context("Google Cloud Q4 2024 revenue 11955 operating income 2093 official annual reconciliation")`, and `retrieve_context("Google Cloud Q1 2020 revenue 2777 operating loss 1730 official_match")` returned the new rows. `forecast_quarterly_metric` now uses 24 Google Cloud revenue quarters from Q1 2020 to Q4 2025.
- Alibaba Cloud FY2025 Q1-FY2025 Q4 added on 2026-06-18:
  - Metrics: Cloud Intelligence Group `revenue`, `revenue_growth_yoy`, `adjusted_ebita`, and `adjusted_ebita_growth_yoy`.
  - Periods: FY2025 Q1, FY2025 Q2, FY2025 Q3, FY2025 Q4.
  - Source roots: Alibaba official IR quarterly results index, Alibaba official announcement/PDF pages where available, and Alibaba SEC 6-K exhibits for exact Cloud Intelligence Group segment text.
  - Result: package rows increased from 2,273 to 2,289; Alibaba Cloud rows increased from 16 to 32; distinct fiscal quarters increased from 4 to 8, covering FY2025 Q1-FY2026 Q4. All Alibaba Cloud rows are `official_match` with `verification_count=3`. Coverage audit still marks Alibaba Cloud `below_minimum_needs_extension` because FY2017 Q1-FY2024 Q4 are still missing toward the cloud 40-quarter target.
  - RAG/forecast check: `retrieve_context("Alibaba Cloud FY2025 Q1 revenue 26549 adjusted EBITA 2337 official SEC 6-K")`, `retrieve_context("subject Alibaba Cloud period FY2025 Q4 metric_key revenue official_value 30127")`, and `retrieve_context("Alibaba Cloud FY2025 Q4 adjusted EBITA 2420 adjusted EBITA growth 69 official SEC 6-K")` returned the new rows. `forecast_quarterly_metric` now uses 8 Alibaba Cloud revenue quarters from FY2025 Q1 to FY2026 Q4.
- Alibaba Cloud FY2024 Q1-FY2024 Q4 added on 2026-06-18:
  - Metrics: Cloud Intelligence Group `revenue`, `revenue_growth_yoy`, `adjusted_ebita`, and `adjusted_ebita_growth_yoy`.
  - Periods: FY2024 Q1, FY2024 Q2, FY2024 Q3, FY2024 Q4.
  - Source roots: Alibaba official IR quarterly results index and Alibaba SEC 6-K exhibits for exact Cloud Intelligence Group segment text; Alibaba official document/PDF links are included where available. FY2024 Q1 was subsequently normalized to the later restated segment basis using the FY2024 Q2 six-month table minus FY2024 Q2.
  - Current correction: FY2024 Q1 is now `revenue=25,065`, `adjusted_ebita=916`, `revenue_growth_yoy=2.911`, and `adjusted_ebita_growth_yoy=6.019` on the restated Cloud Intelligence Group basis after DingTalk was reclassified to All others. FY2024 Q2-Q4 remain 27,648 / 28,066 / 25,595 revenue and 1,409 / 2,364 / 1,432 adjusted EBITA.
  - Result after correction: Alibaba Cloud remains 64 rows and 16 fiscal quarters. Current Alibaba status is `official_match=56` and `source_gap_confirmed=8`; the eight source gaps are FY2023 same-basis growth metrics where old Cloud segment growth is no longer comparable. Coverage audit still marks Alibaba Cloud `below_minimum_needs_extension` because FY2017 Q1-FY2022 Q4 are still missing toward the 40-quarter cloud target.
- Alibaba Cloud FY2023 Q1-FY2023 Q4 added on 2026-06-18:
  - Metrics: restated Cloud Intelligence Group `revenue` and `adjusted_ebita`; FY2023 `revenue_growth_yoy` and `adjusted_ebita_growth_yoy` are retained as `source_gap_confirmed` rows because same-basis FY2022 quarterly comparators were not disclosed in the retained sources.
  - Periods: FY2023 Q1, FY2023 Q2, FY2023 Q3, FY2023 Q4.
  - Source roots: Alibaba FY2024 Q2/Q3/Q4 SEC 6-K exhibits and Alibaba official IR quarterly results index. These later releases reclassified DingTalk from Cloud Intelligence Group to All others and reclassified comparative figures; current FY2023 rows therefore use the restated Cloud Intelligence Group basis, not the older FY2023 Cloud segment basis.
  - Current values: FY2023 Q1 revenue 24,356 and adjusted EBITA 864; FY2023 Q2 revenue 27,035 and adjusted EBITA 981; FY2023 Q3 revenue 27,364 and adjusted EBITA 1,269; FY2023 Q4 revenue 24,742 and adjusted EBITA 987. Revenue and adjusted EBITA units are millions CNY.
  - Result: package remains 2,321 rows; Alibaba Cloud remains 64 rows and 16 fiscal quarters. FY2023 revenue and adjusted EBITA rows are `official_match`; FY2023 same-basis growth rows are `source_gap_confirmed`.

## Priority 1: Reach Minimum Window

- Mainland quarterly carriers: 中国电信 and 中国移动 meet the 10-year preferred window with Q1 2016-Q1 2026; 中国联通 covers Q1 2017-Q1 2026 value quarters and has confirmed source-gap rows for Q2-Q4 2016; 中国铁塔 still needs Q2 2016-Q4 2018 for the 10-year preferred window.
- Semiannual Hong Kong issuers:
  - HKT / csl / 1O1O, 3HK / Hutchison, SmarTone, HKBN, and i-CABLE now meet the 20 half-year preferred window.
- Cloud vendors:
  - AWS now meets the 10-year cloud vendor window with Q1 2016 through Q4 2025 official quarterly segment records.
  - Google Cloud currently covers Q1 2020 through Q4 2025 with official quarterly segment rows; 2016-2019 still need source-gap/annual-only evidence because equivalent quarterly Google Cloud operating income segment disclosure has not been found.
  - Microsoft Azure / Intelligent Cloud now meets the 10-year cloud vendor window with Q2 2016 through Q1 2026 official quarterly proxy segment records.
  - Tencent Cloud proxy needs Q1 2016 through Q4 2024 toward the hard 40-quarter target; any missing official/public proxy disclosure must be documented as source-gap evidence and kept out of coverage counts.
  - Alibaba Cloud currently covers FY2023 Q1 through FY2026 Q4; FY2017 Q1-FY2022 Q4 remain missing toward the 40-quarter cloud target.
  - Oracle Cloud currently covers FY2022 Q1 through FY2026 Q4 with official quarterly total cloud revenue rows. FY2023 Q1-FY2026 Q4 include Cloud Revenue, Cloud Infrastructure revenue, Cloud Application revenue and their growth rates; FY2022 only has total cloud revenue plus Q2-Q4 total cloud revenue growth because the official releases do not disclose same-table IaaS/SaaS absolute split metrics for all FY2022 quarters. FY2017 Q1-FY2021 Q4 remain missing toward the 40-quarter cloud target and should be kept as source-gap/older-annual-only unless matching IaaS+SaaS quarterly disclosure is found.
  - Target note: cloud source-gap/annual-only evidence documents disclosure limits but does not count toward the 40-quarter coverage window or completion status.
- Source-gap subjects: HGC and Huawei Cloud stay as source-gap records unless periodic public financial/cloud segment data is found.

## 2026-06-18 Oracle Cloud Historical Expansion

- Oracle Cloud FY2025 Q1-FY2025 Q3 added on 2026-06-18:
  - Metrics: `cloud_revenue`, `cloud_revenue_growth_yoy`, `cloud_infrastructure_revenue`, `cloud_infrastructure_revenue_growth_yoy`, `cloud_application_revenue`, and `cloud_application_revenue_growth_yoy`.
  - Periods: FY2025 Q1, FY2025 Q2, FY2025 Q3. Existing FY2025 Q4-FY2026 Q4 rows remain.
  - Source roots: Oracle official quarterly earnings releases and Oracle Investor Relations quarterly results index.
- Oracle Cloud FY2024 Q1-FY2024 Q4 added on 2026-06-18:
  - Metrics: same six official cloud revenue and growth metrics.
  - Periods: FY2024 Q1 through FY2024 Q4.
  - Source roots: Oracle official quarterly earnings releases and Oracle Investor Relations quarterly results index.
- Oracle Cloud FY2023 Q1-FY2023 Q4 added on 2026-06-18:
  - Metrics: same six official cloud revenue and growth metrics.
  - Periods: FY2023 Q1 through FY2023 Q4.
  - Source roots: Oracle official quarterly earnings releases and Oracle Investor Relations quarterly results index. Evidence notes preserve Oracle's Cerner contribution disclosures for FY2023 quarters.
- Oracle Cloud FY2022 Q1-FY2022 Q4 added on 2026-06-18:
  - Metrics: `cloud_revenue` for FY2022 Q1-Q4 and `cloud_revenue_growth_yoy` for FY2022 Q2-Q4.
  - Source boundary: FY2022 releases disclose total IaaS plus SaaS cloud revenue, but do not disclose complete same-table IaaS/SaaS absolute split metrics across all quarters, so `cloud_infrastructure_revenue` and `cloud_application_revenue` are not estimated for FY2022.
- Result: package rows increased to 2,394. Oracle Cloud rows increased from 30 to 103 and distinct quarters increased from 5 to 20, covering FY2022 Q1-FY2026 Q4. All Oracle Cloud rows are `official_match` with `verification_count=2`. Coverage audit still marks Oracle Cloud `below_minimum_needs_extension` because FY2017 Q1-FY2021 Q4 remain missing toward the 40-quarter cloud target.
- RAG/forecast check: `retrieve_context("Oracle Cloud FY2022 Q1 cloud revenue 2.5 IaaS plus SaaS official")`, `retrieve_context("Oracle Cloud FY2025 Q3 cloud infrastructure revenue 2.7 growth 49 official")`, and `retrieve_context("Oracle Cloud FY2024 Q2 SaaS revenue 3.2 cloud application revenue growth 15 official")` returned the relevant rows after Oracle cloud metric alias expansion in `rag_llm.py`. `forecast_quarterly_metric` uses 20 Oracle Cloud `cloud_revenue` quarters from FY2022 Q1 to FY2026 Q4 and generated `agent_knowledge/generated_charts/chart_2f09097f1959c39f.png`.

## 2026-06-18 Tencent Cloud / FBS Proxy Historical Expansion

- Added `Tencent Cloud / Tencent FBS proxy` official quarterly proxy rows for Q1 2019-Q1 2026.
  - Metrics: `fintech_business_services_revenue` and `fintech_business_services_revenue_growth_yoy`.
  - Source roots: Tencent official financial news earnings releases index and each official Tencent earnings release PDF.
  - Result: package rows increased to 2,445. Tencent FBS proxy rows increased from 7 to 58 and distinct quarters increased from 4 to 29, covering Q1 2019-Q1 2026. All Tencent rows are `official_match` with `verification_count=2`.
  - Disclosure boundary: Tencent states in its Q1 2019 release that it began separately disclosing FinTech and Business Services as a new segment. Do not backfill Q2 2016-Q4 2018 with older non-comparable segment lines; document the boundary/source gap instead.
- RAG/forecast check:
  - `retrieve_context("Tencent Cloud FBS proxy Q1 2019 FinTech and Business Services revenue 21789 official")` returns the exact Q1 2019 `fintech_business_services_revenue` row first.
  - `retrieve_context("Tencent Cloud / Tencent FBS proxy Q4 2024 FBS revenue 56125 official")` returns the exact Q4 2024 revenue row first.
  - `retrieve_context("Tencent FinTech and Business Services Q1 2026 FBS revenue growth 9 official")` returns the exact Q1 2026 growth row first.
  - `forecast_quarterly_metric` now uses 29 Tencent FBS revenue quarters from Q1 2019 to Q1 2026 and generated `agent_knowledge/generated_charts/chart_2302ea62d1459e3e.png`.

## 2026-06-18 Tencent FBS Pre-Disclosure Source-Gap Boundary

- Added 11 `source_gap_confirmed` disclosure-boundary rows for `Tencent Cloud / Tencent FBS proxy`, covering Q2 2016-Q4 2018.
  - Metric: `fintech_business_services_disclosure_status`.
  - Source roots: Tencent official financial news earnings releases index, Tencent Q1 2019 earnings release, and Tencent FY2018/Q4 2018 earnings release.
  - Evidence: Tencent Q1 2019 says it began separately disclosing FinTech and Business Services as a new segment in that quarter; earlier releases do not provide a comparable FBS proxy line.
  - Result: package rows increased to 2,456. Tencent now has 69 rows: 58 `official_match` value rows plus 11 `source_gap_confirmed` boundary rows. Coverage audit correctly still counts only 29 value quarters toward the hard 40-quarter cloud gate.
- RAG/forecast check:
  - `retrieve_context("Tencent FBS Q2 2016 disclosure status source gap FinTech and Business Services began separately disclosing Q1 2019")` returns the exact Q2 2016 source-gap row first.
  - `retrieve_context("Tencent Cloud FBS proxy Q4 2018 source gap older non-FBS segments not comparable")` returns the exact Q4 2018 source-gap row first.
  - `forecast_quarterly_metric` still uses only 29 Tencent FBS revenue quarters and excludes the source-gap rows.

## 2026-06-18 Google Cloud Pre-2020 Source-Gap Boundary

- Added 16 `source_gap_confirmed` disclosure-boundary rows for `Google Cloud`, covering Q1 2016-Q4 2019.
  - Metric: `cloud_quarterly_disclosure_status`.
  - Source roots: Alphabet official SEC filings index, Alphabet 2018 Form 10-K, Alphabet 2019 Form 10-K, and Alphabet 2020 Form 10-K.
  - Evidence: Alphabet 2019 Form 10-K discloses annual Google Cloud revenue for 2017, 2018, and 2019, but no quarterly Google Cloud revenue or operating income/loss segment rows. Alphabet 2018 Form 10-K places Google Cloud offerings inside Google other revenues. Alphabet 2020 Form 10-K is the first retained source with Google Cloud segment revenue and operating loss tables suitable for this quarterly segment series.
  - Result: package rows increased to 2,472. Google Cloud now has 88 rows: 72 `official_match` value rows plus 16 `source_gap_confirmed` boundary rows. Coverage audit correctly still counts only 24 value quarters toward the hard 40-quarter cloud gate.
- RAG/forecast check:
  - `retrieve_context("Google Cloud Q1 2019 source gap annual Google Cloud revenues no quarterly operating loss segment rows")` returns the exact Q1 2019 source-gap row first after `cloud_quarterly_disclosure_status` alias expansion in `rag_llm.py`.
  - `retrieve_context("Google Cloud Q1 2016 source gap Google other revenues Cloud offerings not standalone quarterly segment")` returns the exact Q1 2016 source-gap row first.
  - `forecast_quarterly_metric` still uses only 24 Google Cloud revenue quarters from Q1 2020 to Q4 2025 and excludes source-gap rows.

## 2026-06-18 Google Cloud FY2017-FY2019 Annual-Only Revenue Preservation

- Added 3 `official_only` annual rows for `Google Cloud`, covering FY2017-FY2019 revenue.
  - Metric: `revenue`; grain: `period`, not `quarter`.
  - Values: FY2017 4,056; FY2018 5,838; FY2019 8,918, all in millions USD.
  - Source roots: Alphabet official investor relations SEC filings index, Alphabet 2019 Form 10-K, and Alphabet 2020 Form 10-K.
  - Evidence: Alphabet 2019 Form 10-K discloses annual Google Cloud revenue for 2017, 2018, and 2019, but no quarterly Google Cloud revenue or operating income/loss segment rows. These rows preserve the public annual evidence and must not be split into estimated quarters.
- Result: package rows increased to 2,807. Google Cloud now has 91 rows: 72 `official_match` quarterly value rows, 16 `source_gap_confirmed` pre-2020 quarterly boundary rows, and 3 `official_only` annual revenue rows. Coverage audit correctly still counts only 24 quarterly value periods toward the hard 40-quarter cloud gate.
- RAG/forecast check:
  - `retrieve_context("Google Cloud FY 2019 annual revenue 8918 official annual only")` returns the exact FY2019 annual revenue row first after `rag_llm.py` was updated to recognize FY annual period labels.
  - `retrieve_context("Google Cloud Q1 2016 quarterly source gap annual only not estimate")` still returns the exact Q1 2016 source-gap row first.
  - `forecast_quarterly_metric.invoke('{"subject":"Google Cloud","metric_key":"revenue","horizon":4}')` still uses 24 quarterly samples from Q1 2020 to Q4 2025 and generated `agent_knowledge/generated_charts/chart_aea22a8ed1fdde48.png`; annual-only FY rows remain excluded from forecasting.

## 2026-06-18 Oracle Cloud Pre-FY2022 Source-Gap Boundary

- Added 20 `source_gap_confirmed` disclosure-boundary rows for `Oracle Cloud`, covering FY2017 Q1-FY2021 Q4.
  - Metric: `cloud_quarterly_disclosure_status`.
  - Source roots: Oracle FY2021 Q4 earnings release, Oracle FY2021 Form 10-K, Oracle FY2020 Form 10-K, and Oracle FY2022 Q1 earnings release.
  - Evidence: FY2021 and earlier Oracle sources disclose older `Cloud services and license support`, applications cloud services and license support, and infrastructure cloud services and license support lines, but not the later comparable IaaS plus SaaS `Cloud Revenue` quarterly line. The retained Oracle Cloud `cloud_revenue` sequence starts at FY2022 Q1.
  - Result: package rows increased to 2,492. Oracle Cloud now has 123 rows: 103 `official_match` value rows plus 20 `source_gap_confirmed` boundary rows. Coverage audit correctly still counts only 20 value quarters toward the hard 40-quarter cloud gate.
- RAG/forecast check:
  - `retrieve_context("Oracle Cloud FY2021 Q4 source gap Cloud services and license support not IaaS plus SaaS Cloud Revenue")` returns the exact FY2021 Q4 source-gap row first with `verification_count=4`.
  - `retrieve_context("Oracle Cloud FY2017 Q1 source gap old cloud services license support not comparable cloud revenue")` returns the exact FY2017 Q1 source-gap row first with `verification_count=4`.
  - `forecast_quarterly_metric` still uses only 20 Oracle Cloud `cloud_revenue` quarters from FY2022 Q1 to FY2026 Q4 and excludes source-gap rows.

## 2026-06-18 Alibaba Cloud Pre-Restated-CIG Source-Gap Boundary

- Added 24 `source_gap_confirmed` disclosure-boundary rows for `Alibaba Cloud`, covering FY2017 Q1-FY2022 Q4.
  - Metric: `cloud_quarterly_disclosure_status`.
  - Source roots: Alibaba quarterly results index, Alibaba June Quarter 2022 results, Alibaba September Quarter 2023 results, and Alibaba March Quarter 2024/Fiscal Year 2024 results.
  - Evidence: Alibaba's FY2022-era Cloud segment disclosures comprised Alibaba Cloud and DingTalk. Starting from the quarter ended September 30, 2023, Alibaba reclassified DingTalk from Cloud Intelligence Group to All others and reclassified comparative figures. The retained Alibaba Cloud series uses the later restated Cloud Intelligence Group basis, so FY2017-FY2022 old Cloud segment values are not mixed into the retained series.
  - Result: package rows increased to 2,516. Alibaba Cloud now has 88 rows: 56 `official_match` value rows, 8 FY2023 growth-metric `source_gap_confirmed` rows, and 24 pre-restated-CIG disclosure-boundary rows. Coverage audit correctly still counts only 16 value quarters toward the hard 40-quarter cloud gate.
- RAG/forecast check:
  - `retrieve_context("Alibaba Cloud FY2022 Q4 source gap DingTalk reclassified Cloud Intelligence Group All others")` returns the exact FY2022 Q4 source-gap row first with `verification_count=4`.
  - `retrieve_context("Alibaba Cloud FY2017 Q1 source gap old Cloud segment included DingTalk not restated CIG")` returns the exact FY2017 Q1 source-gap row first with `verification_count=4`.
  - `forecast_quarterly_metric` still uses only 16 Alibaba Cloud `revenue` quarters from FY2023 Q1 to FY2026 Q4 and excludes source-gap rows.

## 2026-06-18 Mainland Carrier Q1 2021 Core-Metrics Batch

- Added 9 `official_only` rows for Q1 2021:
  - `中国电信`: `revenue=106,873`, `ebitda=31,052`, `net_income=6,441` million CNY.
  - `中国联通`: `revenue=82,272`, `ebitda=23,640`, `net_income=3,843` million CNY.
  - `中国铁塔`: `revenue=21,151`, `ebitda=15,553`, `net_income=1,694` million CNY.
- Source roots:
  - 中国电信: 2021 Q1 announcement, 2021 interim report, and 2021 annual report.
  - 中国联通: 2021 Q1 main financial data announcement, 2021 interim report, and 2021 annual report.
  - 中国铁塔: 2021 Q1 unaudited key operating data, 2021 interim report, and 2021 annual report.
- Result: package rows increased to 2,525. 中国电信、中国联通、中国铁塔 each now count 21 value quarters from Q1 2021 to Q1 2026 toward the quarterly-window audit; their remaining 7-year minimum gaps are Q2 2019-Q4 2020. 中国移动 was completed in the following detail batch and now also starts at Q1 2021.
- RAG/forecast check:
  - `retrieve_context("中国电信 Q1 2021 operating revenues 106873 EBITDA 31052 official")` returns the Q1 2021 revenue/EBITDA rows.
  - `retrieve_context("中国联通 Q1 2021 total revenue 82272 EBITDA 23640 official")` returns the Q1 2021 revenue/EBITDA rows.
  - `retrieve_context("中国铁塔 Q1 2021 revenue 21151 EBITDA 15553 official")` returns the Q1 2021 revenue/EBITDA rows.
- `forecast_quarterly_metric` now uses 21 revenue quarters for 中国电信、中国联通、中国铁塔, Q1 2021-Q1 2026.

## 2026-06-18 中国移动 Q1 2021 详细指标补充

- 已新增 `中国移动` Q1 2021 官方季度指标 13 行，均为 `official_only` 且 `verification_count=4`。
- 新增指标：`revenue=198,429`、`operating_revenue=198,429`、`ebitda=72,100`、`net_income=24,056`、`operating_income=31,252`、`operating_cash_flow=76,272`、`capital_expenditures=-33,755`、`free_cash_flow=42,517`、`gross_profit=51,429`、`gross_margin=25.918%`、`operating_margin=15.750%`、`ebitda_margin=36.335%`、`revenue_growth_yoy=9.5%`。
- 来源为中国移动 2022 年第一季度报告巨潮原文、同文公告镜像、2021 中期报告和 2021 年报。未写入 2021-03-31 现金、资产、债务等时点指标，因为当前 retained sources 未直接披露该时点同口径资产负债表。
- 重建后 `quarterly_metrics.csv` 为 2,538 行；中国移动覆盖期数从 20 增至 21，当前覆盖 Q1 2021-Q1 2026，剩余 7 年最低窗口缺口为 Q2 2019-Q4 2020。四家内地运营商现在均为 21 个有值季度。
- RAG/forecast check:
  - `retrieve_context("中国移动 Q1 2021 营业收入 198429 EBITDA 72100 official")` returns the Q1 2021 EBITDA and revenue rows.
  - `retrieve_context("中国移动 Q1 2021 operating cash flow 76272 capital expenditures 33755 official")` returns the Q1 2021 operating cash flow row.
  - `forecast_quarterly_metric` now uses 21 中国移动 revenue quarters from Q1 2021 to Q1 2026 and excludes source-gap rows.

## 2026-06-18 中国电信 2020 核心指标补充

- 已新增 `中国电信` Q1 2020-Q4 2020 官方季度核心指标 20 行，均为 `official_only` 且 `verification_count=3`。
- 指标：`revenue`、`service_revenue`、`ebitda`、`ebitda_margin`、`net_income`。
- 新增值：
  - Q1 2020: revenue 94,793; service_revenue 92,137; EBITDA 30,161; EBITDA margin 32.735%; net_income 5,822.
  - Q2 2020: revenue 99,010; service_revenue 94,973; EBITDA 32,993; EBITDA margin 34.739%; net_income 8,127.
  - Q3 2020: revenue 98,811; service_revenue 93,758; EBITDA 29,056; EBITDA margin 30.990%; net_income 4,757.
  - Q4 2020: revenue 100,947; service_revenue 92,930; EBITDA 26,670; EBITDA margin 28.699%; net_income 2,144.
- 来源为中国电信 2020 年第一季度报告、2020 中期报告、2020 前三季度报告、2020 年报和 2020 全年业绩演示。Q1 为直接披露；Q2=H1-Q1，Q3=9M-H1，Q4=FY-9M。
- 重建后 `quarterly_metrics.csv` 为 2,558 行；中国电信覆盖期数从 21 增至 25，当前覆盖 Q1 2020-Q1 2026，剩余 7 年最低窗口缺口为 Q2 2019-Q4 2019。
- RAG/forecast check:
  - `retrieve_context("中国电信 Q2 2020 operating revenue 99010 EBITDA 32993 official")` returns the Q2 2020 EBITDA and revenue rows.
  - `retrieve_context("中国电信 Q4 2020 服务收入 92930 official")` returns the Q4 2020 `service_revenue` row after adding a dedicated `service_revenue` alias in `rag_llm.py`.
  - `forecast_quarterly_metric` now uses 25 中国电信 revenue quarters from Q1 2020 to Q1 2026 and excludes source-gap rows.

## 2026-06-18 中国电信 2019 核心指标补充

- 已新增 `中国电信` Q1 2019-Q4 2019 官方季度核心指标 20 行，均为 `official_only` 且 `verification_count=3`。
- 指标：`revenue`、`service_revenue`、`ebitda`、`ebitda_margin`、`net_income`。
- 新增值：
  - Q1 2019: revenue 96,135; service_revenue 91,531; EBITDA 30,238; EBITDA margin 33.036%; net_income 5,956.
  - Q2 2019: revenue 94,353; service_revenue 91,058; EBITDA 33,049; EBITDA margin 36.294%; net_income 7,953.
  - Q3 2019: revenue 92,338; service_revenue 88,895; EBITDA 28,686; EBITDA margin 32.270%; net_income 4,480.
  - Q4 2019: revenue 92,908; service_revenue 86,126; EBITDA 25,242; EBITDA margin 29.308%; net_income 2,128.
- 来源为中国电信 2019 年第一季度报告、2019 中期报告、2019 前三季度报告、2019 年报财务回顾，以及 2020 年第一季度/前三季度/全年业绩演示比较栏。Q1 为直接披露；Q2=H1-Q1，Q3=9M-H1，Q4=FY-9M。
- 重建后 `quarterly_metrics.csv` 为 2,578 行；中国电信覆盖期数从 25 增至 29，当前覆盖 Q1 2019-Q1 2026，已满足 7 年最低窗口，10 年偏好窗口仍缺 Q2 2016-Q4 2018 共 11 个季度。
- RAG/forecast check:
  - `retrieve_context("中国电信 Q2 2019 operating revenue 94353 EBITDA 33049 official")` returns the Q2 2019 EBITDA and revenue rows.
  - `retrieve_context("中国电信 Q4 2019 服务收入 86126 official")` returns the Q4 2019 `service_revenue` row first.
  - `forecast_quarterly_metric` now uses 29 中国电信 revenue quarters from Q1 2019 to Q1 2026 and excludes source-gap rows.

## Verified Source Entry Points

- 中国电信: `https://www.chinatelecom-h.com/en/ir/reports.php?year=2020`
- 中国移动 2020 official prior-period URLs already in `scripts/build_quarterly_metrics_knowledge.py`:
  - `https://www1.hkexnews.hk/listedco/listconews/sehk/2020/0420/2020042001250.pdf`
  - `https://doc.irasia.com/listco/hk/chinamobile/interim/2020/intrep.pdf`
  - `https://www1.hkexnews.hk/listedco/listconews/sehk/2020/1020/2020102000522.pdf`
  - `https://doc.irasia.com/listco/hk/chinamobile/annual/2020/ar2020.pdf`
- 中国铁塔: `https://ir.china-tower.com/`
- 中国联通: `https://www.chinaunicom.com.hk/en/ir/reports/ar2020.pdf`
- AWS:
  - `https://ir.aboutamazon.com/quarterly-results/default.aspx`
  - 2016 SEC 10-Q/10-K filings:
    - `https://www.sec.gov/Archives/edgar/data/1018724/000101872416000227/amzn-20160331x10q.htm`
    - `https://www.sec.gov/Archives/edgar/data/1018724/000101872416000286/amzn-20160630x10q.htm`
    - `https://www.sec.gov/Archives/edgar/data/1018724/000101872416000324/amzn-20160930x10q.htm`
    - `https://www.sec.gov/Archives/edgar/data/1018724/000101872417000011/amzn-20161231x10k.htm`
  - 2017 SEC 10-Q/10-K filings:
    - `https://www.sec.gov/Archives/edgar/data/1018724/000101872417000051/amzn-20170331x10q.htm`
    - `https://www.sec.gov/Archives/edgar/data/1018724/000101872417000100/amzn-20170630x10q.htm`
    - `https://www.sec.gov/Archives/edgar/data/1018724/000101872417000135/amzn-20170930x10q.htm`
    - `https://www.sec.gov/Archives/edgar/data/1018724/000101872418000005/amzn-20171231x10k.htm`
  - 2018 SEC 10-Q/10-K filings:
    - `https://www.sec.gov/Archives/edgar/data/1018724/000101872418000072/amzn-20180331x10q.htm`
    - `https://www.sec.gov/Archives/edgar/data/1018724/000101872418000108/amzn-20180630x10q.htm`
    - `https://www.sec.gov/Archives/edgar/data/1018724/000101872418000159/amzn-20180930x10q.htm`
    - `https://www.sec.gov/Archives/edgar/data/1018724/000101872419000004/amzn-20181231x10k.htm`
  - 2019 SEC 10-Q/10-K filings:
    - `https://www.sec.gov/Archives/edgar/data/1018724/000101872419000043/amzn-2019331x10q.htm`
    - `https://www.sec.gov/Archives/edgar/data/1018724/000101872419000071/amzn-2019630x10q.htm`
    - `https://www.sec.gov/Archives/edgar/data/1018724/000101872419000089/amzn-2019930x10q.htm`
    - `https://www.sec.gov/Archives/edgar/data/1018724/000101872420000004/amzn-20191231x10k.htm`
  - 2020 SEC 10-Q/10-K filings:
    - `https://www.sec.gov/Archives/edgar/data/1018724/000101872420000010/amzn-20200331x10q.htm`
    - `https://www.sec.gov/Archives/edgar/data/1018724/000101872420000021/amzn-20200630.htm`
    - `https://www.sec.gov/Archives/edgar/data/1018724/000101872420000030/amzn-20200930.htm`
    - `https://www.sec.gov/Archives/edgar/data/1018724/000101872421000004/amzn-20201231.htm`
  - 2021 SEC 10-Q/10-K filings:
    - `https://www.sec.gov/Archives/edgar/data/1018724/000101872421000010/amzn-20210331.htm`
    - `https://www.sec.gov/Archives/edgar/data/1018724/000101872421000020/amzn-20210630.htm`
    - `https://www.sec.gov/Archives/edgar/data/1018724/000101872421000028/amzn-20210930.htm`
    - `https://www.sec.gov/Archives/edgar/data/1018724/000101872422000005/amzn-20211231.htm`
  - 2022 Form 10-K for Q1 2022 reconciliation: `https://www.sec.gov/Archives/edgar/data/1018724/000101872423000004/amzn-20221231.htm`
  - 2023 Q3/Q4 trailing AWS Segment tables under `https://s2.q4cdn.com/299287126/files/doc_financials/2023/`
  - 2024 earnings releases under `https://s2.q4cdn.com/299287126/files/doc_financials/2024/`
  - 2025 Form 10-K for Q4 2025 reconciliation: `https://www.sec.gov/Archives/edgar/data/1018724/000101872426000004/amzn-20251231.htm`
- Microsoft Azure / Intelligent Cloud:
  - `https://www.microsoft.com/en-us/Investor/earnings`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2018-Q3/press-release-webcast`
  - `https://www.sec.gov/Archives/edgar/data/789019/000156459018009307/msft-10q_20180331.htm`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2018-Q4/press-release-webcast`
  - `https://www.sec.gov/Archives/edgar/data/789019/000156459018019062/msft-10k_20180630.htm`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2019-Q1/press-release-webcast`
  - `https://www.sec.gov/Archives/edgar/data/789019/000156459018024893/msft-10q_20180930.htm`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2019-Q2/press-release-webcast`
  - `https://www.sec.gov/Archives/edgar/data/789019/000156459019001392/msft-10q_20181231.htm`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2019-Q3/press-release-webcast`
  - `https://www.sec.gov/Archives/edgar/data/789019/000156459019012709/msft-10q_20190331.htm`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2019-Q4/press-release-webcast`
  - `https://www.sec.gov/Archives/edgar/data/789019/000156459019027952/msft-10k_20190630.htm`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2020-Q1/press-release-webcast`
  - `https://www.sec.gov/Archives/edgar/data/789019/000156459019037549/msft-10q_20190930.htm`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2020-Q2/press-release-webcast`
  - `https://www.sec.gov/Archives/edgar/data/789019/000156459020002450/msft-10q_20191231.htm`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2020-Q3/press-release-webcast`
  - `https://www.sec.gov/Archives/edgar/data/789019/000156459020019706/msft-10q_20200331.htm`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2020-Q4/press-release-webcast`
  - `https://www.sec.gov/Archives/edgar/data/789019/000156459020034944/msft-10k_20200630.htm`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2021-Q1/press-release-webcast`
  - `https://www.sec.gov/Archives/edgar/data/789019/000156459020047996/msft-10q_20200930.htm`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2021-Q2/press-release-webcast`
  - `https://www.sec.gov/Archives/edgar/data/789019/000156459021002316/msft-10q_20201231.htm`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2021-Q3/press-release-webcast`
  - `https://www.sec.gov/Archives/edgar/data/789019/000156459021020891/msft-10q_20210331.htm`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2021-Q4/press-release-webcast`
  - `https://www.sec.gov/Archives/edgar/data/789019/000156459021039151/msft-10k_20210630.htm`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2022-Q1/press-release-webcast`
  - `https://www.sec.gov/Archives/edgar/data/789019/000156459021051992/msft-10q_20210930.htm`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2022-Q2/press-release-webcast`
  - `https://www.sec.gov/Archives/edgar/data/789019/000156459022002324/msft-10q_20211231.htm`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2022-Q3/press-release-webcast`
  - `https://www.sec.gov/Archives/edgar/data/789019/000156459022015675/msft-10q_20220331.htm`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2022-Q4/press-release-webcast`
  - `https://www.sec.gov/Archives/edgar/data/789019/000156459022026876/msft-10k_20220630.htm`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2023-Q1/press-release-webcast`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2023-Q1/segment-revenues`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2023-Q2/press-release-webcast`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2023-Q2/segment-revenues`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2023-Q3/press-release-webcast`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2023-Q3/segment-revenues`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2023-Q4/press-release-webcast`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2023-Q4/segment-revenues`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2024-Q1/press-release-webcast`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2024-Q1/segment-revenues`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2024-Q2/press-release-webcast`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2024-Q2/segment-revenues`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2024-Q3/press-release-webcast`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2024-Q3/segment-revenues`
  - `https://www.microsoft.com/en-us/investor/earnings/fy-2024-q4/intelligent-cloud-performance`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2024-Q4/press-release-webcast`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2024-Q4/segment-revenues`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2025-Q1/press-release-webcast`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2025-Q1/segment-revenues`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2025-Q2/press-release-webcast`
  - `https://www.microsoft.com/en-us/Investor/earnings/FY-2025-Q2/segment-revenues`
- HKT/HKBN/SmarTone/3HK/i-CABLE: use official issuer IR pages, HKEX announcements, and annual/interim report PDFs. For semiannual rows, extract H1 directly and H2 by annual minus interim only where the report structure supports the reconciliation.

## Extraction Order

1. Microsoft/Google Cloud/Tencent/Alibaba/Oracle historical cloud rows, preserving proxy and segment definitions.
2. Mainland carriers Q2 2019-Q1 2021 core metrics.
3. Semiannual Hong Kong issuers 2016-2020 completed for the current public-official window.
4. Non-disclosing Huawei Cloud and HGC remain source-gap unless official periodic data is found.

## Acceptance Checks Per Batch

- Rebuild `quarterly_metrics.csv`, `quarterly_metrics.json`, `quarterly_metrics_summary.md`, and official verified CSV.
- Run `python3 scripts/audit_prediction_history_coverage.py`.
- Confirm `needs_official_row_crosscheck=0` for newly added rows.
- Confirm every new non-gap row has `verification_count>=2`.
- Run 小竞AI retrieval against at least one new row and one source-gap row before marking the batch done.

## 2026-06-18 中国联通 2019-2020 核心指标补充

- 已补 `中国联通` Q1 2019-Q4 2020 官方核心季度指标 40 行，全部 `official_only` 且 `verification_count=3`。指标为 `revenue`、`service_revenue`、`ebitda`、`ebitda_margin`、`net_income`。
- 2019 新增值：Q1 revenue 73,147、service_revenue 66,802、EBITDA 25,012、EBITDA margin 37.442%、net_income 3,675；Q2 revenue 71,807、service_revenue 66,155、EBITDA 24,495、EBITDA margin 37.027%、net_income 3,202；Q3 revenue 72,166、service_revenue 65,575、EBITDA 23,638、EBITDA margin 36.047%、net_income 2,946；Q4 revenue 73,395、service_revenue 65,854、EBITDA 21,213、EBITDA margin 32.212%、net_income 1,507。
- 2020 新增值：Q1 revenue 73,824、service_revenue 68,307、EBITDA 23,561、EBITDA margin 34.493%、net_income 3,166；Q2 revenue 76,573、service_revenue 70,028、EBITDA 25,891、EBITDA margin 36.972%、net_income 4,403；Q3 revenue 74,958、service_revenue 69,014、EBITDA 24,248、EBITDA margin 35.135%、net_income 3,255；Q4 revenue 78,483、service_revenue 68,465、EBITDA 20,439、EBITDA margin 29.853%、net_income 1,669。
- 来源为中国联通 2019/2020 一季度主要财务数据、中期报告/中期业绩新闻稿、前三季度主要财务数据、年报/年度业绩公告，以及后续年度比较栏。Q1 直接披露；Q2=H1-Q1，Q3=9M-H1，Q4=FY-9M。
- 重建后 `quarterly_metrics.csv` 为 2,618 行，`official_verified_metrics_2026-06-18.csv` 为 2,621 条数据行。中国联通覆盖期数从 21 增至 29，当前覆盖 Q1 2019-Q1 2026，已满足 7 年最低窗口；10 年偏好窗口仍缺 Q2 2016-Q4 2018 共 11 个季度。
- 验证：`python3 -m py_compile scripts/build_quarterly_metrics_knowledge.py`、`CMHK_QUARTERLY_METRICS_BUILD_DATE=2026-06-18 python3 scripts/build_quarterly_metrics_knowledge.py`、`python3 scripts/audit_prediction_history_coverage.py`、CSV 行级审计、`retrieve_context("中国联通 Q2 2020 operating revenue 76573 EBITDA 25891 official")`、`retrieve_context("中国联通 Q4 2019 服务收入 65854 official")` 和 `forecast_quarterly_metric.invoke('{"subject":"中国联通","metric_key":"revenue","horizon":4}')` 均通过；趋势预测现在使用 29 个季度，Q1 2019-Q1 2026，生成图表 `agent_knowledge/generated_charts/chart_3c1d6d18ca29a8be.png`。

## 2026-06-18 中国移动 2019-2020 核心指标补充

- 已补 `中国移动` Q1 2019-Q4 2020 官方核心季度指标 48 行，全部 `official_only` 且 `verification_count=3`。指标为 `operating_revenue`、`revenue`、`service_revenue`、`ebitda`、`ebitda_margin`、`net_income`。
- 2019 新增值来自中国移动官网 Operating Data：Q1 operating_revenue/revenue 185,000、service_revenue 165,900、EBITDA 72,700、EBITDA margin 39.297%、net_income 23,700；Q2 204,400、185,500、78,400、38.356%、32,400；Q3 177,300、161,600、74,400、41.963%、25,700；Q4 179,200、161,400、70,500、39.342%、24,800。
- 2020 新增值来自中国移动官网 Operating Data：Q1 operating_revenue/revenue 181,300、service_revenue 168,900、EBITDA 68,500、EBITDA margin 37.783%、net_income 23,500；Q2 208,600、189,300、77,200、37.009%、32,300；Q3 184,500、167,500、71,200、38.591%、25,800；Q4 193,700、170,000、68,200、35.209%、26,200。
- 来源为中国移动官网 2019/2020 单季度 Operating Data、2020 Q1/Q3 HKEX 经营数据公告、2019/2020 中期报告、2019 中期业绩新闻稿和 2019/2020 年报。官网直接披露单季值；中报、三季报公告和年报用于累计/全年交叉核验。
- 重建后 `quarterly_metrics.csv` 为 2,666 行，`official_verified_metrics_2026-06-18.csv` 为 2,669 条数据行。中国移动覆盖期数从 21 增至 29，当前覆盖 Q1 2019-Q1 2026，已满足 7 年最低窗口；10 年偏好窗口仍缺 Q2 2016-Q4 2018 共 11 个季度。
- 验证：`python3 -m py_compile scripts/build_quarterly_metrics_knowledge.py`、`CMHK_QUARTERLY_METRICS_BUILD_DATE=2026-06-18 python3 scripts/build_quarterly_metrics_knowledge.py`、`python3 scripts/audit_prediction_history_coverage.py`、CSV 行级审计、`retrieve_context("中国移动 Q2 2020 operating revenue 208600 EBITDA 77200 official")`、`retrieve_context("中国移动 Q4 2019 服务收入 161400 official")` 和 `forecast_quarterly_metric.invoke('{"subject":"中国移动","metric_key":"revenue","horizon":4}')` 均通过；趋势预测现在使用 29 个季度，Q1 2019-Q1 2026，生成图表 `agent_knowledge/generated_charts/chart_c2a26f3dbd00b745.png`。

## 2026-06-18 中国铁塔 2019-2020 核心指标补充

- 已补 `中国铁塔` Q1 2019-Q4 2020 官方核心季度指标 32 行，全部 `official_only` 且 `verification_count=3`。指标为 `revenue`、`ebitda`、`ebitda_margin`、`net_income`。
- 2019 新增值：Q1 revenue 18,897、EBITDA 13,590、EBITDA margin 71.916%、net_income 1,284；Q2 revenue 19,083、EBITDA 14,225、EBITDA margin 74.543%、net_income 1,264；Q3 revenue 19,061、EBITDA 13,959、EBITDA margin 73.233%、net_income 1,325；Q4 revenue 19,387、EBITDA 14,922、EBITDA margin 76.969%、net_income 1,349。
- 2020 新增值：Q1 revenue 19,690、EBITDA 14,532、EBITDA margin 73.804%、net_income 1,452；Q2 revenue 20,104、EBITDA 14,568、EBITDA margin 72.463%、net_income 1,526；Q3 revenue 20,426、EBITDA 14,919、EBITDA margin 73.039%、net_income 1,586；Q4 revenue 20,879、EBITDA 15,508、EBITDA margin 74.276%、net_income 1,864。
- 来源为中国铁塔 2019/2020 一季度未经审核主要运营数据、中期报告、前三季度未经审核主要运营数据、年度业绩公告和年报。Q1 直接披露；Q2=H1-Q1，Q3=9M-H1，Q4=FY-9M；未写入需要不稳反推的 2019 单季同比序列。
- 重建后 `quarterly_metrics.csv` 为 2,698 行，`official_verified_metrics_2026-06-18.csv` 为 2,701 条数据行。中国铁塔覆盖期数从 21 增至 29，当前覆盖 Q1 2019-Q1 2026，已满足 7 年最低窗口；10 年偏好窗口仍缺 Q2 2016-Q4 2018 共 11 个季度。四家内地运营商均已达到 29 个季度。
- 验证：`python3 -m py_compile scripts/build_quarterly_metrics_knowledge.py rag_llm.py`、`CMHK_QUARTERLY_METRICS_BUILD_DATE=2026-06-18 python3 scripts/build_quarterly_metrics_knowledge.py`、`python3 scripts/audit_prediction_history_coverage.py`、CSV 行级审计、`retrieve_context("中国铁塔 Q2 2020 revenue 20104 EBITDA 14568 official")`、`retrieve_context("中国铁塔 Q4 2019 net_income 1349 归母利润 official")` 和 `forecast_quarterly_metric.invoke('{"subject":"中国铁塔","metric_key":"revenue","horizon":4}')` 均通过；趋势预测现在使用 29 个季度，Q1 2019-Q1 2026，生成图表 `agent_knowledge/generated_charts/chart_844e3ef7a5edd8cc.png`。同步补强 `rag_llm.py` 的 `net_income` / `归母利润` 精确检索别名。

## 2026-06-18 HKT 2016-2020 半年度历史扩展

- 已补 `HKT / csl / 1O1O` H1 2016-H2 2020 官方半年度核心指标 20 行，全部 `official_only` 且 `verification_count>=2`。指标为 `revenue` 和 `ebitda`。
- 新增 revenue：H1 2016 16,388、H2 2016 17,459、H1 2017 15,649、H2 2017 17,609、H1 2018 17,022、H2 2018 18,165、H1 2019 15,109、H2 2019 17,994、H1 2020 14,606、H2 2020 17,783。新增 EBITDA：H1 2016 5,865、H2 2016 6,819、H1 2017 5,968、H2 2017 7,029、H1 2018 5,639、H2 2018 6,919、H1 2019 5,733、H2 2019 7,084、H1 2020 5,546、H2 2020 6,981。金额单位为百万港元。
- 来源为 HKT 2016-2020 HKEX 年报、年度业绩公告及后续年度年报比较栏。H1/H2 均取 Management's Discussion and Analysis / Financial Review by Segment 表披露的 Total revenue 与 Total EBITDA，不用年度值平均或估算。
- 重建后 `quarterly_metrics.csv` 为 2,718 行，`official_verified_metrics_2026-06-18.csv` 为 2,721 条数据行。覆盖审计显示 HKT 从 10 个半年度扩至 20 个半年度，覆盖 H1 2016-H2 2025，状态为 `meets_preferred_window`，无 10 年半年度缺口。
- 同步修复 `agent.py` 的趋势预测工具：半年度主体现在使用 `grain=half_year`、季节长度 2 和 H1/H2 未来期标签；季度主体仍使用季节长度 4。
- 验证：`python3 -m py_compile scripts/build_quarterly_metrics_knowledge.py agent.py`、`CMHK_QUARTERLY_METRICS_BUILD_DATE=2026-06-18 python3 scripts/build_quarterly_metrics_knowledge.py`、`python3 scripts/audit_prediction_history_coverage.py`、CSV 行级审计、`retrieve_context("HKT H1 2016 Total revenue 16388 official annual report")`、`retrieve_context("HKT H2 2020 Total EBITDA 6981 official comparative annual report")` 和 `forecast_quarterly_metric.invoke('{"subject":"HKT / csl / 1O1O","metric_key":"revenue","horizon":2}')` 均通过；HKT 预测使用 20 个半年度并生成 `agent_knowledge/generated_charts/chart_a71059b2be0d3394.png`。

## 2026-06-18 SmarTone 2016-2021 半年度历史扩展

- 已补 `SmarTone` H2 2016-H1 2021 官方半年度核心指标 20 行，全部 `official_only` 且 `verification_count=3`。指标为 `revenue` 和 `ebitda`。
- 新增 revenue：H2 2016 8,127.321、H1 2017 5,372.304、H2 2017 3,343.108、H1 2018 4,107.577、H2 2018 5,880.915、H1 2019 5,186.561、H2 2019 3,228.476、H1 2020 4,256.606、H2 2020 2,729.845、H1 2021 3,244.313。新增 EBITDA：H2 2016 1,283.048、H1 2017 1,248.571、H2 2017 1,047.691、H1 2018 1,080.027、H2 2018 1,056.187、H1 2019 939.306、H2 2019 902.483、H1 2020 1,273.853、H2 2020 1,155.374、H1 2021 1,272.651。金额单位为百万港元。
- 来源为 SmarTone Holdings 2015/16 至 2020/21 官方中期报告和年报。H1 直接取中期报告损益表或分部附注；H2 由官方年报全年值减同财年 H1 官方值复算，仅在年报和中期报告口径可勾稽时写入，不做年度平均。
- 重建后 `quarterly_metrics.csv` 为 2,738 行，`official_verified_metrics_2026-06-18.csv` 为 2,741 条数据行。覆盖审计显示 SmarTone 从 10 个半年度扩至 20 个半年度，覆盖 H2 2016-H1 2026，状态为 `meets_preferred_window`，无 10 年半年度缺口。
- 验证：`python3 -m py_compile scripts/build_quarterly_metrics_knowledge.py scripts/audit_prediction_history_coverage.py rag_llm.py agent.py web_app.py`、`CMHK_QUARTERLY_METRICS_BUILD_DATE=2026-06-18 python3 scripts/build_quarterly_metrics_knowledge.py`、`python3 scripts/audit_prediction_history_coverage.py`、CSV 行级审计、`retrieve_context("SmarTone H1 2017 Revenues 5372.304 EBITDA 1248.571 official")`、`retrieve_context("SmarTone H2 2020 EBITDA 1155.374 revenue 2729.845 official annual minus interim")`、`retrieve_context("Huawei Cloud source gap quarterly disclosure not estimating")` 和 SmarTone revenue/EBITDA 预测均通过；SmarTone 预测使用 20 个半年度并生成 `agent_knowledge/generated_charts/chart_a7c91f93c355ce96.png`、`agent_knowledge/generated_charts/chart_cac0f8e1c7caa801.png`。

## 2026-06-18 HKBN 2016-2021 半年度历史扩展

- 已补 `HKBN` H2 2016-H1 2021 官方半年度核心指标 20 行，全部 `official_only` 且 `verification_count=3`。指标为 `revenue` 和 `ebitda`。
- 新增 revenue：H2 2016 1,558.468、H1 2017 1,534.726、H2 2017 1,697.584、H1 2018 1,868.095、H2 2018 2,080.857、H1 2019 2,218.591、H2 2019 2,889.046、H1 2020 4,457.282、H2 2020 4,995.675、H1 2021 6,229.584。新增 EBITDA：H2 2016 495.121、H1 2017 480.961、H2 2017 560.289、H1 2018 593.733、H2 2018 585.855、H1 2019 723.396、H2 2019 985.952、H1 2020 1,283.359、H2 2020 1,222.084、H1 2021 1,311.817。金额单位为百万港元。
- 来源为 HKBN 官网 Financial Results 入口、FY16-FY21 官方中期业绩公告、正式中期报告、年度业绩公告和年报。H1 直接取 Financial highlights；H2 由官方年报或全年业绩公告的全年值减 H1 官方值复算，不做年度平均估算。
- 重建后 `quarterly_metrics.csv` 为 2,758 行，`official_verified_metrics_2026-06-18.csv` 为 2,761 条数据行。覆盖审计显示 HKBN 从 10 个半年度扩至 20 个半年度，覆盖 H2 2016-H1 2026，状态为 `meets_preferred_window`，无 10 年半年度缺口。
- 验证：`python3 -m py_compile scripts/build_quarterly_metrics_knowledge.py scripts/audit_prediction_history_coverage.py rag_llm.py agent.py web_app.py`、`CMHK_QUARTERLY_METRICS_BUILD_DATE=2026-06-18 python3 scripts/build_quarterly_metrics_knowledge.py`、`python3 scripts/audit_prediction_history_coverage.py`、CSV 行级审计、`retrieve_context("HKBN H1 2019 Revenue 2218.591 EBITDA 723.396 official")`、`retrieve_context("HKBN H2 2020 EBITDA 1222.084 revenue 4995.675 official annual minus interim")`、`retrieve_context("Huawei Cloud source gap quarterly disclosure not estimating")` 和 HKBN revenue/EBITDA 预测均通过；HKBN 预测使用 20 个半年度并生成 `agent_knowledge/generated_charts/chart_6637360dee4def9c.png`、`agent_knowledge/generated_charts/chart_366249f40e009ff1.png`。

## 2026-06-18 i-CABLE 2016-2020 半年度历史扩展

- 已补 `i-CABLE` H1 2016-H2 2020 官方半年度核心指标 20 行，全部 `official_only` 且 `verification_count=3`。指标为 `revenue` 和 `net_income`。
- 新增 revenue：H1 2016 709.876、H2 2016 696.492、H1 2017 641.112、H2 2017 617.318、H1 2018 587.468、H2 2018 575.842、H1 2019 571.880、H2 2019 588.957、H1 2020 524.893、H2 2020 544.084。新增 net_income：H1 2016 -134.782、H2 2016 -178.008、H1 2017 -141.137、H2 2017 -221.690、H1 2018 -253.563、H2 2018 -202.025、H1 2019 -209.600、H2 2019 -187.366、H1 2020 -176.223、H2 2020 -99.164。金额单位为百万港元。
- 来源为 i-CABLE 官方 Annual & Interim Reports 页面、2016-2020 中期报告和年报，并使用 HKEX 历史公告交叉核验可取得的年报/中报版本。H1 直接取中期报告损益表；H2 由年报全年值减 H1 官方值复算。未写入缺少稳定官方同口径的 EBITDA 历史估算。
- 重建后 `quarterly_metrics.csv` 为 2,778 行，`official_verified_metrics_2026-06-18.csv` 为 2,781 条数据行。覆盖审计显示 i-CABLE 从 10 个半年度扩至 20 个半年度，覆盖 H1 2016-H2 2025，状态为 `meets_preferred_window`，无 10 年半年度缺口。
- 验证：`python3 -m py_compile scripts/build_quarterly_metrics_knowledge.py`、`CMHK_QUARTERLY_METRICS_BUILD_DATE=2026-06-18 python3 scripts/build_quarterly_metrics_knowledge.py`、`python3 scripts/audit_prediction_history_coverage.py`、CSV 行级审计、`retrieve_context("i-CABLE H2 2020 net_income -99.164 official annual minus interim")`、`retrieve_context("i-CABLE H2 2020 revenue 544.084 annual minus interim official")`、`retrieve_context("i-CABLE H1 2018 Revenue 587.468 net_income -253.563 official")`、`retrieve_context("Huawei Cloud source gap quarterly disclosure not estimating")` 和 i-CABLE revenue/net_income 半年度预测均通过；预测使用 20 个半年度并生成 `agent_knowledge/generated_charts/chart_59d84be740cf665b.png`、`agent_knowledge/generated_charts/chart_b3e54fc1b7ab2fe1.png`。

## 2026-06-18 3HK / Hutchison 2016-2020 半年度历史扩展

- 已补 `3HK / Hutchison` H1 2016-H2 2020 官方半年度核心指标 26 行，全部 `official_only` 且 `verification_count=3`。2016-2017 因 HTHKH 出售 fixed-line 业务，采用官方 Mobile business 口径的 `revenue` 和 `ebitda`；2018-2020 采用 continuing/mobile 口径的 `revenue`、`ebitda` 和 `net_income`。
- 新增 revenue：H1 2016 3,472、H2 2016 4,860、H1 2017 3,117、H2 2017 3,635、H1 2018 4,021、H2 2018 3,891、H1 2019 2,515、H2 2019 3,067、H1 2020 1,982、H2 2020 2,563。新增 EBITDA：H1 2016 665、H2 2016 668、H1 2017 647、H2 2017 692、H1 2018 601、H2 2018 556、H1 2019 787、H2 2019 875、H1 2020 778、H2 2020 894。新增 net_income：H1 2018 198、H2 2018 206、H1 2019 188、H2 2019 241、H1 2020 146、H2 2020 215。金额单位为百万港元。
- 来源为 HTHKH 官网 2016-2020 中期报告和年报；H1 直接取中报 Highlights/MD&A/financial summary，H2 由官方全年值减 H1 官方值复算。2017 出售 fixed-line 业务造成合并口径不连续，因此新补 2016-2017 使用报告中的 Mobile business 表，避免把 discontinued/fixed-line 业务混入预测序列。
- 重建后 `quarterly_metrics.csv` 为 2,804 行，`official_verified_metrics_2026-06-18.csv` 为 2,807 条数据行。覆盖审计显示 3HK / Hutchison 从 10 个半年度扩至 20 个半年度，覆盖 H1 2016-H2 2025，状态为 `meets_preferred_window`，无 10 年半年度缺口。
- 验证：`python3 -m py_compile scripts/build_quarterly_metrics_knowledge.py`、`CMHK_QUARTERLY_METRICS_BUILD_DATE=2026-06-18 python3 scripts/build_quarterly_metrics_knowledge.py`、`python3 scripts/audit_prediction_history_coverage.py`、CSV 行级审计、`retrieve_context("3HK Hutchison H1 2016 Total revenue 3472 EBITDA 665 official mobile business")`、`retrieve_context("3HK Hutchison H2 2020 revenue 2563 EBITDA 894 net_income 215 official annual minus interim")`、`retrieve_context("Huawei Cloud source gap quarterly disclosure not estimating")` 和 3HK revenue/EBITDA 半年度预测均通过；预测使用 20 个半年度并生成 `agent_knowledge/generated_charts/chart_72726d9c92f1b9c4.png`、`agent_knowledge/generated_charts/chart_14c5aa336933d059.png`。

## 2026-06-18 中国电信 2016-2018 核心季度指标补充

- 已补 `中国电信` Q1 2016-Q4 2018 官方核心季度指标 56 行，全部 `official_only` 且 `verification_count=3`。指标为 `revenue`、`ebitda`、`net_income`；在精确 service revenue 可取得的季度另补 `service_revenue` 和 `ebitda_margin`。2016 Q2/Q3 的 service revenue 仅在中报以 RMB155.2 billion 四舍五入披露，因此不写入 service_revenue 或 EBITDA margin，避免近似值进入正式序列。
- 新增 revenue：2016Q1-Q4 为 86,426 / 90,402 / 86,988 / 88,469；2017Q1-Q4 为 91,428 / 92,690 / 90,584 / 91,527；2018Q1-Q4 为 96,613 / 96,416 / 91,942 / 92,153。新增 EBITDA：2016Q1-Q4 为 23,811 / 26,744 / 25,478 / 19,106；2017Q1-Q4 为 24,815 / 27,599 / 26,430 / 23,327；2018Q1-Q4 为 26,508 / 29,350 / 24,961 / 23,388。新增 net_income：2016Q1-Q4 为 5,119 / 6,554 / 5,870 / 461；2017Q1-Q4 为 5,348 / 7,189 / 5,965 / 115；2018Q1-Q4 为 5,698 / 7,872 / 5,464 / 2,176。金额单位为百万元人民币。
- 来源为中国电信 2016-2018 年一季度报告、中期报告、前三季度报告和年报；Q1 直接披露，Q2=H1-Q1，Q3=9M-H1，Q4=FY-9M。2018 报告采用 IFRS 15，当期 2018 值按报告披露写入；2017 比较栏只用于交叉核验，不混成另一条口径。
- 重建后 `quarterly_metrics.csv` 为 2,863 行。覆盖审计显示中国电信从 29 个季度增至 41 个季度，覆盖 Q1 2016-Q1 2026，状态升为 `meets_preferred_window`，10 年季度窗口无缺口。总体覆盖状态变为 8 个主体 `meets_preferred_window`、3 个内地运营商仍 `meets_minimum_needs_10y_extension`、4 个云厂商仍 `below_minimum_needs_extension`、2 个 source-gap 不适用。
- 验证：`python3 -m py_compile scripts/build_quarterly_metrics_knowledge.py`、`CMHK_QUARTERLY_METRICS_BUILD_DATE=2026-06-18 python3 scripts/build_quarterly_metrics_knowledge.py`、`python3 scripts/audit_prediction_history_coverage.py`、CSV 行级审计、`retrieve_context("中国电信 Q2 2016 operating revenue 90402 EBITDA 26744 official")`、`retrieve_context("中国电信 Q4 2018 service revenue 85500 EBITDA margin 27.354 official annual minus 9M")` 和 `forecast_quarterly_metric.invoke('{"subject":"中国电信","metric_key":"revenue","horizon":4}')` 均通过；预测使用 41 个季度并生成 `agent_knowledge/generated_charts/chart_fa78667839bc7914.png`。

## 2026-06-18 中国移动 2016-2018 核心季度指标补充

- 已补 `中国移动` Q1 2016-Q4 2018 官方核心季度指标 72 行，全部 `official_only` 且 `verification_count=3`。指标为 `operating_revenue`、`revenue`、`service_revenue`、`ebitda`、`ebitda_margin`、`net_income`。
- 新增 2016 年值来自中国移动官网单季度经营数据，单位为百万元人民币：Q1 revenue/operating_revenue 177,504、service_revenue 151,599、EBITDA 65,148、EBITDA margin 36.702%、net_income 23,948；Q2 192,847、173,824、69,202、35.884%、36,624；Q3 172,313、155,791、66,048、38.330%、27,487；Q4 165,757、142,208、56,279、33.952%、20,682。
- 新增 2017 年值来自中国移动官网单季度经营数据，官网单位为十亿元并已换算为百万元人民币：Q1 revenue/operating_revenue 184,000、service_revenue 160,900、EBITDA 67,100、EBITDA margin 36.467%、net_income 24,800；Q2 204,900、187,100、73,600、35.920%、37,900；Q3 180,600、167,300、70,600、39.091%、29,400；Q4 171,000、153,100、59,100、34.561%、22,200。
- 新增 2018 年值来自中国移动官网单季度经营数据，官网单位为十亿元并已换算为百万元人民币：Q1 revenue/operating_revenue 185,500、service_revenue 166,700、EBITDA 69,700、EBITDA margin 37.574%、net_income 25,800；Q2 206,300、189,400、76,200、36.937%、39,800；Q3 175,900、162,300、68,200、38.772%、29,400；Q4 169,100、152,500、61,400、36.310%、22,800。
- 来源为中国移动官网 2016/2017/2018 单季度 Operating Data、对应年度中期报告和年报。官网直接披露单季值；中报和年报用于 H1/全年累计勾稽。2017/2018 官网以十亿元一位小数披露，已按披露精度换算为百万元，不用年度精确值反推未披露小数。
- 重建后 `quarterly_metrics.csv` 为 2,935 行。覆盖审计显示中国移动从 29 个季度增至 41 个季度，覆盖 Q1 2016-Q1 2026，状态升为 `meets_preferred_window`，10 年季度窗口无缺口。总体覆盖状态变为 9 个主体 `meets_preferred_window`、2 个内地运营商仍 `meets_minimum_needs_10y_extension`、4 个云厂商仍 `below_minimum_needs_extension`、2 个 source-gap 不适用。
- 验证：`python3 -m py_compile scripts/build_quarterly_metrics_knowledge.py`、`CMHK_QUARTERLY_METRICS_BUILD_DATE=2026-06-18 python3 scripts/build_quarterly_metrics_knowledge.py`、`python3 scripts/audit_prediction_history_coverage.py`、CSV 行级审计、`retrieve_context("中国移动 Q2 2016 Operating Revenue 192847 EBITDA 69202 official")`、`retrieve_context("中国移动 Q4 2018 service revenue 152500 EBITDA margin 36.310 official")` 和 `forecast_quarterly_metric.invoke('{"subject":"中国移动","metric_key":"revenue","horizon":4}')` 均通过；预测使用 41 个季度并生成 `agent_knowledge/generated_charts/chart_b2b4cbd9071411a4.png`。

## 2026-06-18 中国联通 2017-2018 核心季度指标补充与2016披露缺口

- 已为 `中国联通` 新增/确认 2016-2018 相关记录 35 行：Q1 2017-Q4 2018 官方核心季度指标 32 行为 `official_only` 且 `verification_count=3`；Q2 2016、Q3 2016、Q4 2016 三个季度为 `source_gap_confirmed` 披露缺口行。
- 2017 新增值：Q1 revenue 69,005、service_revenue 61,426、net_income 862；Q2 revenue 69,155、service_revenue 62,684、net_income 1,558；Q3 revenue 67,618、service_revenue 63,770、net_income 1,634；Q4 revenue 69,051、service_revenue 61,135、net_income -2,224。金额单位为百万元人民币。2017 未写入 EBITDA/EBITDA margin，因为未找到可直接勾稽的官方 Q1/9M EBITDA 基数，禁止用增长率或年度平均反推。
- 2018 新增值：Q1 revenue 74,935、service_revenue 66,609、EBITDA 23,909、EBITDA margin 35.895%、net_income 3,005；Q2 revenue 74,175、service_revenue 67,811、EBITDA 21,761、EBITDA margin 32.091%、net_income 2,905；Q3 revenue 70,602、service_revenue 65,593、EBITDA 20,576、EBITDA margin 31.369%、net_income 2,870；Q4 revenue 71,168、service_revenue 63,667、EBITDA 18,664、EBITDA margin 29.315%、net_income 1,420。
- 来源为中国联通 2018 Q1/Q3 IRAsia 季度财务资料、2018 中期报告、2018 年报、2017 中期报告、2017 年报，以及 2018 年公告中的 2017 比较栏。Q1 直接披露；Q2=H1-Q1，Q3=9M-H1，Q4=FY-9M。
- 2016 边界：已核验 2016 中期报告和年报只提供 H1/FY 累计值；可找到的 2016 Q1/Q3 IRAsia 文件为运营数据或盈利预警，不是同口径正式季度财务表。由于缺少 2016 Q1 和 9M 同口径财务基数，Q2-Q4 2016 不做 H1/FY 平均、不做 YoY 反推，保留 `quarterly_financial_disclosure_status` source-gap 行。
- 重建后 `quarterly_metrics.csv` 为 2,970 行。覆盖审计显示中国联通为 37/40 个季度，覆盖 Q1 2017-Q1 2026，有值季度满足 7 年最低窗口；10 年偏好窗口剩 Q2-Q4 2016 三个 source-gap 边界，状态为 `meets_minimum_needs_10y_extension`。
- 验证：`python3 -m py_compile scripts/build_quarterly_metrics_knowledge.py rag_llm.py`、`CMHK_QUARTERLY_METRICS_BUILD_DATE=2026-06-18 python3 scripts/build_quarterly_metrics_knowledge.py`、`python3 scripts/audit_prediction_history_coverage.py`、CSV 行级审计、`retrieve_context("中国联通 Q4 2018 EBITDA 18664 EBITDA margin 29.315 official")`、`retrieve_context("中国联通 Q2 2016 披露缺口 不得估算")` 和 `forecast_quarterly_metric.invoke('{"subject":"中国联通","metric_key":"revenue","horizon":4}')` 均通过；预测使用 37 个季度并生成 `agent_knowledge/generated_charts/chart_ff58167abf073671.png`。

## 2026-06-18 中国铁塔 2017-2018 核心季度指标补充与2016披露缺口

- 已为 `中国铁塔` 新增/确认 2016-2018 相关记录 35 行：Q1 2017-Q4 2018 官方核心季度指标 32 行为 `official_only` 且 `verification_count=3`；Q2 2016、Q3 2016、Q4 2016 三个季度为 `source_gap_confirmed`。
- 2017 新增值：Q1 revenue 16,449、EBITDA 9,749、EBITDA margin 59.268%、net_income 484；Q2 revenue 16,823、EBITDA 10,158、EBITDA margin 60.382%、net_income 636；Q3 revenue 17,279、EBITDA 10,194、EBITDA margin 58.996%、net_income 561；Q4 revenue 18,114、EBITDA 10,256、EBITDA margin 56.619%、net_income 262。金额单位为百万元人民币。
- 2018 新增值：Q1 revenue 17,244、EBITDA 10,130、EBITDA margin 58.745%、net_income 380；Q2 revenue 18,091、EBITDA 10,777、EBITDA margin 59.571%、net_income 830；Q3 revenue 18,307、EBITDA 10,815、EBITDA margin 59.076%、net_income 751；Q4 revenue 18,177、EBITDA 10,051、EBITDA margin 55.295%、net_income 689。
- 来源为中国铁塔 2018 全球发售招股书、2018 中期业绩公告、2018 中期报告、2018 前三季度未经审核主要运营数据和 2018 年报。Q1 由招股书直接披露；Q2=H1-Q1，Q3=9M-H1，Q4=FY-9M；2017 使用同一批公开文件中的比较栏和招股书历史财务表。
- 2016 边界：招股书仅披露2016全年核心财务指标，未披露2016 Q1/H1/9M同口径季度基数；2018中报和年报也只给2017/2018比较口径。因此 Q2-Q4 2016 不做全年平均或倒推，保留 `quarterly_financial_disclosure_status` source-gap 行。
- 中间重建版本曾为 `quarterly_metrics.csv` 3,005 行；该记录已被后续正式重建取代。当前正式行数以 `manifest.json`、`quarterly_metrics_summary.md`、`knowledge_integrity_audit_2026-06-19.*` 和主 CSV 为准：3,013 行。覆盖审计显示中国铁塔从 29 个季度增至 37 个季度，覆盖 Q1 2017-Q1 2026；有值季度满足 7 年最低窗口，10 年偏好窗口剩 Q2-Q4 2016 三个 source-gap 边界。
- 验证：`python3 -m py_compile scripts/build_quarterly_metrics_knowledge.py rag_llm.py agent.py web_app.py scripts/audit_prediction_history_coverage.py`、`CMHK_QUARTERLY_METRICS_BUILD_DATE=2026-06-18 python3 scripts/build_quarterly_metrics_knowledge.py`、`python3 scripts/audit_prediction_history_coverage.py`、CSV 行级审计、`retrieve_context("中国铁塔 Q2 2018 revenue 18091 EBITDA 10777 official")`、`retrieve_context("中国铁塔 Q2 2016 披露缺口 不得估算")` 和 `forecast_quarterly_metric.invoke('{"subject":"中国铁塔","metric_key":"revenue","horizon":4}')` 均通过；预测使用 37 个季度并生成 `agent_knowledge/generated_charts/chart_525019f45189c949.png`。

## 2026-06-18 云厂商 40 季度 source-gap 完整性审计

- 新增 `scripts/audit_cloud_source_gap_integrity.py`，基于 `quarterly_metrics.csv` 逐一检查六个重点云厂商的 40 个目标季度，输出 `cloud_source_gap_integrity_2026-06-18.csv` 和 `cloud_source_gap_integrity_2026-06-18.md`。
- 审计口径：`forecast_value_available` 只统计 retained forecasting series 中有 `official_value` 的同口径季度行；`documented_source_gap` 只说明官方/公开披露边界已登记，不计入预测可用季度覆盖；`missing_boundary_record` 表示没有值也没有缺口证据。
- 结果：240 个目标季度均已有值或披露边界证据，`missing_boundary_record=0`。AWS 40/40、Microsoft Azure / Intelligent Cloud 40/40；Google Cloud 24 个预测值季度 + 16 个 source-gap；Alibaba Cloud 16 个预测值季度 + 24 个 source-gap；Tencent Cloud / Tencent FBS proxy 29 个预测值季度 + 11 个 source-gap；Oracle Cloud 20 个预测值季度 + 20 个 source-gap。
- RAG 检索验证：Google Cloud Q1 2018 source-gap、Alibaba Cloud FY2020 Q2 DingTalk/Cloud Intelligence Group source-gap、Tencent FBS Q4 2018 source-gap、Microsoft Azure Q2 2016 official values、Oracle FY2020 Q4 IaaS+SaaS disclosure gap 均可从 `quarterly_competitor_metrics_2026-06-18` 检索到对应 CSV/source-plan/审计行。
- 预测验证：`forecast_quarterly_metric` 已分别跑通 Microsoft Azure / Intelligent Cloud revenue、Tencent Cloud / Tencent FBS proxy fintech_business_services_revenue 和 Google Cloud revenue，生成 `chart_976bdc3779f08e31.png`、`chart_2302ea62d1459e3e.png`、`chart_aea22a8ed1fdde48.png`。source-gap 行不参与拟合。

## 2026-06-18 Google Cloud Q4 2018/Q4 2019 季度 revenue 更正

- 复核 Alphabet 官方 SEC Q4 2019 earnings exhibit 后，确认 expanded revenue disclosures 表披露 Google Cloud Q4 2018 revenue 1,709 百万美元、Q4 2019 revenue 2,614 百万美元，同时披露 FY2017/FY2018/FY2019 年度 Google Cloud revenue。
- 已将 `Google Cloud` Q4 2018 和 Q4 2019 从 source-gap 边界改为 `official_only` revenue 行，`verification_count=3`，来源为 Alphabet IR earnings index、Alphabet Q4 2019 SEC exhibit 和 Alphabet 2019 Form 10-K。Q1-Q3 2018、Q1-Q3 2019 仍为 source-gap，不拆年度值。
- 中间重建版本曾记录 `quarterly_metrics.csv` 仍为 3,005 行；该行数已过期。当前正式行数以 `manifest.json`、`quarterly_metrics_summary.md`、`knowledge_integrity_audit_2026-06-19.*` 和主 CSV 为准：3,013 行。该轮状态从 `official_only=621/source_gap_confirmed=314` 变为 `official_only=623/source_gap_confirmed=312`。Google Cloud 为 91 行：72 行 `official_match`、5 行 `official_only`、14 行 `source_gap_confirmed`。
- 覆盖审计显示 Google Cloud 有值季度从 24 增至 26，覆盖 Q4 2018、Q4 2019、Q1 2020-Q4 2025；仍缺 Q1 2016-Q3 2018 和 Q1-Q3 2019 共 14 个季度，状态仍为 `below_minimum_needs_extension`。
- RAG 验证：`retrieve_context("Google Cloud Q4 2019 revenue 2614 official expanded revenue disclosure")` 与 `retrieve_context("Google Cloud Q4 2018 revenue 1709 official expanded revenue disclosure")` 首条均命中新 official revenue 行；`retrieve_context("Google Cloud Q1 2019 source gap no estimate")` 仍命中 source-gap 行。预测验证：Google Cloud revenue 预测现在使用 26 个季度，并生成 `agent_knowledge/generated_charts/chart_9a2c96c760aca424.png`。

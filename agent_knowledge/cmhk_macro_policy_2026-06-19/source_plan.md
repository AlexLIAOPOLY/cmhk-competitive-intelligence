# Source Plan

## Current Competitor / Cloud Prediction Readiness

Current package inspected: `agent_knowledge/quarterly_competitor_metrics_2026-06-18/quarterly_metrics.csv`.

- Total rows: 3,013.
- Strict source integrity: no rows with `verification_count < 2`.
- Strong prediction-ready subjects by value-period window: China Mobile and China Telecom have 41 quarterly periods; China Unicom has 39; China Tower has 37; major Hong Kong semiannual subjects have 20 half-year periods; AWS and Microsoft Azure / Intelligent Cloud have 40 quarterly periods.
- Limited / tiered cloud prediction subjects: Google Cloud, Alibaba Cloud, Tencent Cloud / Tencent FBS proxy and Oracle Cloud have documented comparable-series boundaries; Huawei Cloud and HGC remain source-gap subjects.

Conclusion: the existing competitor/cloud dataset is sufficient for short-horizon trend/forecast use only under subject-level tiering. Formal outputs must use `official_value`, respect `source_gap_confirmed`, and avoid estimating undisclosed periods.

## Macro / Policy Dataset Collection Status

Current macro package: `agent_knowledge/cmhk_macro_policy_2026-06-19/macro_policy_metrics.csv`.

- Total rows: 7,580.
- Official-match rows: 7,577.
- Source-gap rows: 3.
- Rows with `verification_count < 2`: 0.
- Included grains: monthly OFCA key communications point-in-time snapshots, monthly C&SD CPI/retail, moving-three-month C&SD labour market and domestic household/income indicators, quarterly C&SD private consumption expenditure and GDP/demand growth indicators, annual C&SD household internet access and domestic household/income indicators, mid-year/year-end C&SD population snapshots, annual OFCA telecommunications indicators, OFCA annual internet service subscription snapshots, current OFCA annual/quarterly consumer complaint statistics, and event-grain policy milestones.
- Additional included grain: annual December OFCA Wireless Services snapshots.

### Telecommunications Demand and Infrastructure

- OFCA Key Communications Statistics
  - Included rows: 1,955 rows, all `official_match` with `verification_count=3`.
  - Included grain/window: monthly point-in-time snapshots from 2017-10 to 2026-05 where official CSV fields are populated.
  - Included metric count: 31.
  - Official CSV: https://www.ofca.gov.hk/filemanager/ofca/common/datagovhk/key_com_stat.csv
  - Data dictionary: https://www.ofca.gov.hk/filemanager/ofca/common/datagovhk/data_dict/Data_Dictionary_for_Key_Comms_Stat_EN.pdf
  - data.gov.hk dataset: https://data.gov.hk/en-data/dataset/hk-ofca-ofca-ofca-dataset-10
  - OFCA page: https://www.ofca.gov.hk/en/news_info/data_statistics/key_stat/index.html
  - Included metrics: mobile subscriptions, mobile broadband subscriptions, mobile penetration, household broadband penetration, FTTH/B penetration, telecom operator counts, public Wi-Fi access points and fibre coverage.
  - Boundary: blank CSV cells are not zeros and are not estimated; rows are market-level context and not direct company revenue forecast targets.

- OFCA Telecommunications Indicators
  - URL: https://www.ofca.gov.hk/en/news_info/data_statistics/indicators/index.html
  - Historical table: https://www.ofca.gov.hk/filemanager/ofca/en/content_297/hktelecom-indicators_summary.htm
  - Included grain/window: annual fiscal year, FY2015/16-FY2024/25.

- OFCA Wireless Services statistics
  - Source page: https://www.ofca.gov.hk/en/news_info/data_statistics/mobile_services/wireless_services/index.html
  - Official PDF: https://www.ofca.gov.hk/filemanager/ofca/en/content_108/wireless_en.pdf
  - Included rows: 150 rows, with 148 `official_match` rows and 2 `source_gap_confirmed` rows.
  - Boundary: 4G/5G split columns are excluded until a safer official structured source is available.

- OFCA Internet Service Subscriptions
  - Source page: https://www.ofca.gov.hk/en/news_info/data_statistics/internet/statistics_on_internet_service_subscriptions/index.html
  - Official PDF: https://www.ofca.gov.hk/filemanager/ofca/en/content_293/cus_isp_en.pdf
  - Included rows: 104 rows, all `official_match` with `verification_count=2`; 77 rows are post-2019 access lines and 27 rows are pre-2019 legacy customer accounts.
  - Boundary: OFCA changed methodology in January 2019 from registered customer accounts to access lines. The two source families are kept separate and must not be merged into one forecast target.

- OFCA Consumer Complaint Statistics
  - Source page: https://www.ofca.gov.hk/en/news_info/data_statistics/complaint_stat/index.html
  - Included rows: 28 rows, all `official_match` with `verification_count=2`.
  - Boundary: complaint statistics before 2023 are not estimated; older history remains a backlog item until official archived OFCA complaint tables are found.

### Macro Economy and Demand Indicators

- C&SD CPI / GDP / private consumption / labour / retail / household internet access tables are retained from official C&SD APIs or web tables for the latest available 10-year window.
- C&SD Domestic Households and Income
  - Included rows: 1,217 rows, all `official_match` with `verification_count=4`.
  - Included window: 2016-01-31 to 2026-04-30.
  - Included metric count: 10.
  - Official web table: https://www.censtatd.gov.hk/en/web_table.html?id=130-06102
  - Official component metadata: https://www.censtatd.gov.hk/data/table_130-06102_comp.json
  - Official language metadata: https://www.censtatd.gov.hk/data/en/table_130-06102_lang.json
  - Included metrics: domestic households, average household size, average household size excluding foreign domestic helpers, median monthly household income, median monthly household income excluding Chinese New Year bonus/double pay, median monthly household income excluding foreign domestic helpers, median income of economically active households, owner-occupier share, public-sector owner-occupier share and private-sector owner-occupier share.
  - Boundary: annual rows and moving-three-month rows are separate grains; C&SD special-display / unavailable cells are not estimated.
- C&SD Population Estimates
  - Included rows: 820 rows, all `official_match` with `verification_count=4`.
  - Included window: 2016-06-30 to 2025-12-31.
  - Included compact metric count: 41.
  - Official web table: https://www.censtatd.gov.hk/en/web_table.html?id=110-01001
  - Official component metadata: https://www.censtatd.gov.hk/data/table_110-01001_comp.json
  - Official language metadata: https://www.censtatd.gov.hk/data/en/table_110-01001_lang.json
  - Included cuts: total population, male/female totals, and all-sex 5-year age groups for population count and population share at mid-year and year-end reference time-points.
  - Boundary: sex-by-age cross rows are excluded from this compact CMHK macro package to avoid database bloat; no excluded values are estimated. Provisional official figures are retained with notes.
- Future enrichment candidates: district population and deeper demographic tables where official structured source pages are added.

### Policy, Regulatory, and Spectrum Milestones

- OFCA Spectrum Management and OFCA / CA official reports provide selected 5G, spectrum, SIM real-name registration, rural/remote coverage and assigned-spectrum context.
- OGCIO / Digital Policy Office / Smart City policy documents remain future qualitative extension candidates and are not mixed into the current numeric forecast targets.

## Verification Rules

- Every quantitative row must have at least two source/evidence entries when possible: direct official table/API/CSV plus official context page, release note, data dictionary, annual report, or archived official table.
- Policy event rows must preserve enactment/publication date, responsible institution, policy type, official URL, and relevance to CMHK.
- Conflicting values are retained as `official_conflict`, with `official_value` used for formal conclusions.
- Disclosure gaps are retained as `source_gap_confirmed`; they must not be estimated.
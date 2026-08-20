# Prediction History Coverage Audit (2026-06-18)

- Source package: `agent_knowledge/quarterly_competitor_metrics_2026-06-18/quarterly_metrics.csv`
- Purpose: identify the historical-period gaps before collecting prediction-ready history; cloud vendors are hard 10-year / 40-quarter targets.
- This audit is coverage control only; value correctness still depends on row-level official/public source verification.

## Status Counts

- below_minimum_with_documented_boundaries: 4
- meets_minimum_needs_10y_extension: 2
- meets_preferred_window: 9
- not_applicable_source_gap: 2

## Subject Coverage

| Subject | Grain target | Current span | Periods | Missing minimum | Missing preferred | Status |
| --- | --- | --- | ---: | ---: | ---: | --- |
| 3HK / Hutchison | half_year | H1 2016 to H2 2025 | 20 | 0 | 0 | meets_preferred_window |
| AWS | quarter | Q1 2016 to Q4 2025 | 40 | 0 | 0 | meets_preferred_window |
| Alibaba Cloud | quarter | FY2023 Q1 to FY2026 Q4 | 16 | 24 | 24 | below_minimum_with_documented_boundaries |
| Google Cloud | quarter | Q4 2018 to Q4 2025 | 26 | 14 | 14 | below_minimum_with_documented_boundaries |
| HGC | source_gap | - | 0 |  |  | not_applicable_source_gap |
| HKBN | half_year | H2 2016 to H1 2026 | 20 | 0 | 0 | meets_preferred_window |
| HKT / csl / 1O1O | half_year | H1 2016 to H2 2025 | 20 | 0 | 0 | meets_preferred_window |
| Huawei Cloud / Cloud Computing | source_gap | - | 0 |  |  | not_applicable_source_gap |
| Microsoft Azure / Intelligent Cloud | quarter | Q2 2016 to Q1 2026 | 40 | 0 | 0 | meets_preferred_window |
| Oracle Cloud | quarter | FY2022 Q1 to FY2026 Q4 | 20 | 20 | 20 | below_minimum_with_documented_boundaries |
| SmarTone | half_year | H2 2016 to H1 2026 | 20 | 0 | 0 | meets_preferred_window |
| Tencent Cloud / Tencent FBS proxy | quarter | Q1 2019 to Q1 2026 | 29 | 11 | 11 | below_minimum_with_documented_boundaries |
| i-CABLE | half_year | H1 2016 to H2 2025 | 20 | 0 | 0 | meets_preferred_window |
| 中国电信 | quarter | Q1 2016 to Q1 2026 | 41 | 0 | 0 | meets_preferred_window |
| 中国移动 | quarter | Q1 2016 to Q1 2026 | 41 | 0 | 0 | meets_preferred_window |
| 中国联通 | quarter | Q1 2017 to Q1 2026 | 37 | 0 | 3 | meets_minimum_needs_10y_extension |
| 中国铁塔 | quarter | Q1 2017 to Q1 2026 | 37 | 0 | 3 | meets_minimum_needs_10y_extension |

## Missing Periods

### Alibaba Cloud

- Missing minimum window: FY2017 Q1; FY2017 Q2; FY2017 Q3; FY2017 Q4; FY2018 Q1; FY2018 Q2; FY2018 Q3; FY2018 Q4; FY2019 Q1; FY2019 Q2; FY2019 Q3; FY2019 Q4; FY2020 Q1; FY2020 Q2; FY2020 Q3; FY2020 Q4; FY2021 Q1; FY2021 Q2; FY2021 Q3; FY2021 Q4; FY2022 Q1; FY2022 Q2; FY2022 Q3; FY2022 Q4
- Missing 10-year preferred window: FY2017 Q1; FY2017 Q2; FY2017 Q3; FY2017 Q4; FY2018 Q1; FY2018 Q2; FY2018 Q3; FY2018 Q4; FY2019 Q1; FY2019 Q2; FY2019 Q3; FY2019 Q4; FY2020 Q1; FY2020 Q2; FY2020 Q3; FY2020 Q4; FY2021 Q1; FY2021 Q2; FY2021 Q3; FY2021 Q4; FY2022 Q1; FY2022 Q2; FY2022 Q3; FY2022 Q4
- Documented boundary periods: FY2017 Q1; FY2017 Q2; FY2017 Q3; FY2017 Q4; FY2018 Q1; FY2018 Q2; FY2018 Q3; FY2018 Q4; FY2019 Q1; FY2019 Q2; FY2019 Q3; FY2019 Q4; FY2020 Q1; FY2020 Q2; FY2020 Q3; FY2020 Q4; FY2021 Q1; FY2021 Q2; FY2021 Q3; FY2021 Q4; FY2022 Q1; FY2022 Q2; FY2022 Q3; FY2022 Q4
- Undocumented missing periods: -

### Google Cloud

- Missing minimum window: Q1 2016; Q2 2016; Q3 2016; Q4 2016; Q1 2017; Q2 2017; Q3 2017; Q4 2017; Q1 2018; Q2 2018; Q3 2018; Q1 2019; Q2 2019; Q3 2019
- Missing 10-year preferred window: Q1 2016; Q2 2016; Q3 2016; Q4 2016; Q1 2017; Q2 2017; Q3 2017; Q4 2017; Q1 2018; Q2 2018; Q3 2018; Q1 2019; Q2 2019; Q3 2019
- Documented boundary periods: Q1 2016; Q2 2016; Q3 2016; Q4 2016; Q1 2017; Q2 2017; Q3 2017; Q4 2017; Q1 2018; Q2 2018; Q3 2018; Q1 2019; Q2 2019; Q3 2019
- Undocumented missing periods: -

### Oracle Cloud

- Missing minimum window: FY2017 Q1; FY2017 Q2; FY2017 Q3; FY2017 Q4; FY2018 Q1; FY2018 Q2; FY2018 Q3; FY2018 Q4; FY2019 Q1; FY2019 Q2; FY2019 Q3; FY2019 Q4; FY2020 Q1; FY2020 Q2; FY2020 Q3; FY2020 Q4; FY2021 Q1; FY2021 Q2; FY2021 Q3; FY2021 Q4
- Missing 10-year preferred window: FY2017 Q1; FY2017 Q2; FY2017 Q3; FY2017 Q4; FY2018 Q1; FY2018 Q2; FY2018 Q3; FY2018 Q4; FY2019 Q1; FY2019 Q2; FY2019 Q3; FY2019 Q4; FY2020 Q1; FY2020 Q2; FY2020 Q3; FY2020 Q4; FY2021 Q1; FY2021 Q2; FY2021 Q3; FY2021 Q4
- Documented boundary periods: FY2017 Q1; FY2017 Q2; FY2017 Q3; FY2017 Q4; FY2018 Q1; FY2018 Q2; FY2018 Q3; FY2018 Q4; FY2019 Q1; FY2019 Q2; FY2019 Q3; FY2019 Q4; FY2020 Q1; FY2020 Q2; FY2020 Q3; FY2020 Q4; FY2021 Q1; FY2021 Q2; FY2021 Q3; FY2021 Q4
- Undocumented missing periods: -

### Tencent Cloud / Tencent FBS proxy

- Missing minimum window: Q2 2016; Q3 2016; Q4 2016; Q1 2017; Q2 2017; Q3 2017; Q4 2017; Q1 2018; Q2 2018; Q3 2018; Q4 2018
- Missing 10-year preferred window: Q2 2016; Q3 2016; Q4 2016; Q1 2017; Q2 2017; Q3 2017; Q4 2017; Q1 2018; Q2 2018; Q3 2018; Q4 2018
- Documented boundary periods: Q2 2016; Q3 2016; Q4 2016; Q1 2017; Q2 2017; Q3 2017; Q4 2017; Q1 2018; Q2 2018; Q3 2018; Q4 2018
- Undocumented missing periods: -

### 中国联通

- Missing minimum window: -
- Missing 10-year preferred window: Q2 2016; Q3 2016; Q4 2016
- Documented boundary periods: Q2 2016; Q3 2016; Q4 2016
- Undocumented missing periods: -

### 中国铁塔

- Missing minimum window: -
- Missing 10-year preferred window: Q2 2016; Q3 2016; Q4 2016
- Documented boundary periods: Q2 2016; Q3 2016; Q4 2016
- Undocumented missing periods: -


## Immediate Implications

- The existing standardized carrier snapshot only proves the current 5-year window; older periods must be added from official reports, filings, or other directly verified public sources.
- Cloud vendors are the largest gap and are now treated as hard 10-year / 40-quarter targets; source-gap records document non-disclosure but do not count as coverage.
- HGC and Huawei Cloud remain source-gap records unless periodic public cloud/financial segment data is found; do not estimate missing values.

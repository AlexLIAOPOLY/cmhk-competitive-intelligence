# 全球重点十家运营商数据库质量审计

- 结论：`backlog_open`
- 明细行：843
- 有值行：608
- 来源条目：369
- 重复键：0
- 无效来源引用：0

## 全库核验等级

- `not_applicable_precommercial`: 27
- `official_derived_from_verified_quarters`: 10
- `official_derived_from_verified_rows`: 6
- `official_single_source`: 73
- `official_three_distinct_sources_verified`: 498
- `official_two_distinct_sources`: 21
- `source_gap_confirmed`: 208

## 三来源认证行（按运营商）

- AT&T: 42
- Bharti Airtel: 98
- Deutsche Telekom: 40
- NTT Group: 37
- Reliance Jio: 27
- Verizon: 39
- 中国广电: 6
- 中国电信: 64
- 中国移动: 80
- 中国联通: 65

## 缺口（含不适用）

- AT&T: 7
- Bharti Airtel: 5
- Deutsche Telekom: 7
- NTT Group: 7
- Reliance Jio: 43
- Verizon: 7
- 中国广电: 120
- 中国电信: 14
- 中国移动: 9
- 中国联通: 31

## 关键口径断点

- A formal three-source claim requires at least three distinct underlying source documents; mirrored URLs, evidence sections, and snapshots of one document count once.
- 5G package subscribers and 5G network subscribers are distinct metrics.
- China Telecom and China Unicom 5G base-station values describe a shared network and must not be added together.
- Airtel network-tower scope changes around FY2020; the narrower 194,409 and group KPI 219,546 values are documented, with group KPI retained.
- Airtel FY2019 group KPI packs report 204,356 towers while the India-mobile manufactured-capital disclosure reports 181,079; the group KPI is retained and the two scopes must not be mixed.
- Airtel FY2019 annual KPI earnings before tax is INR-17,318m, while the results-pack profit-before-tax line is INR-46,606m; both are official but use different exceptional-item definitions.
- Airtel FY2018 later comparatives recast revenue, net profit and shareholder equity, add finance lease obligations to net debt, and use a wider group-tower KPI than the India-mobile manufactured-capital section.
- Jio FY2023 reports 5G sites while FY2024 onward reports 5G cells; growth is not calculated across the break.
- Airtel latest comparative basis restates FY2023-FY2025 financials; latest official comparative basis is retained.
- Airtel FY2021 profit before tax is retained on the later four-pack comparative basis of INR22,586m; the earlier INR-42,063m loss-before-tax basis remains documented in the row note.
- Airtel FY2020 uses the IR-pack profit-before-tax basis of INR-44,819m; the annual-report KPI INR-445,711m uses a different exceptional-item definition. FY2020 total customers also changed from an earlier 423.287m to the later 422.100m basis.
- Airtel FY2022 exact comparatives explicitly exclude the consolidation impact of erstwhile Bharti Infratel/Indus Towers; FY2023 onward uses a later recast basis, so direct growth across the boundary needs a scope warning.
- Jio value of sales/services is not the same as revenue from operations; both are stored separately.
- Airtel and Jio use total_customers because their group disclosures include non-mobile categories; these rows are not mobile-subscriber counts.

缺口保留为 `source_gap_confirmed` 或 `not_applicable_precommercial`，没有插值和估算。

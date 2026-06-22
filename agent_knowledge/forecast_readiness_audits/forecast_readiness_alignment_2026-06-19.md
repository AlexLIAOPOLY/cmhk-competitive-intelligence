# Forecast Readiness Alignment Audit (2026-06-19)

- Cases checked: 8
- Passed: 8
- Failed: 0

## Cases

| Case | Subject | Metric | Expected | Actual | Samples | Status | Issues |
| --- | --- | --- | --- | --- | ---: | --- | --- |
| aws_revenue_strong_window | AWS | revenue | success | success | 40 | pass |  |
| alibaba_revenue_excludes_legacy | Alibaba Cloud | revenue | success | success | 16 | pass |  |
| alibaba_legacy_metric_rejected | Alibaba Cloud | legacy_cloud_segment_revenue_including_dingtalk | failure | failure | 4 | pass |  |
| hkt_half_year_supported | HKT / csl / 1O1O | revenue | success | success | 20 | pass |  |
| hgc_source_gap_rejected | HGC | revenue | failure | failure | 0 | pass |  |
| macro_policy_not_forecast_target | Hong Kong macro environment | retail_sales_value_index | failure | failure | 0 | pass |  |
| selected_latest_quarterly_package_allowed | AWS | revenue | success | success | 40 | pass |  |
| selected_superseded_quarterly_package_rejected | AWS | revenue | failure | failure | None | pass |  |

## Boundary Assertions

- AWS revenue remains a 40-quarter strong-window forecast series.
- Alibaba Cloud revenue uses only the post-restatement Cloud Intelligence Group revenue series; FY2022 legacy Cloud segment rows are rejected as too short/non-forecast evidence.
- HKT revenue is forecast as a half-year series, not mislabeled as quarterly.
- HGC source-gap and macro policy rows are rejected as direct numeric forecast targets.
- This audit checks tool behavior; value correctness remains covered by row-level official/source integrity audits.

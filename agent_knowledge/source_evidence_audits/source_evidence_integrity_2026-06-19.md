# Source Evidence Integrity Audit (2026-06-19)

- Datasets checked: 3
- Passed: 3
- Failed: 0

## Dataset Results

| Dataset | Status | Rows | Rows with issues | Min sources | Max sources | Issue counts |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| cmhk_macro_policy_2026-06-19 | pass | 7580 | 0 | 2 | 4 | {} |
| quarterly_competitor_metrics_2026-06-18 | pass | 3013 | 0 | 2 | 8 | {} |
| cloud_vendor_metrics_2026-06-17 | pass | 83 | 0 | 2 | 3 | {} |

## Scope

- Checks every row has a valid primary source URL, nonblank evidence text, parseable `verification_sources`, and at least as many source entries as `verification_count`.
- Confirms the primary source URL is included in `verification_sources` so formal conclusions can trace back to the cited official/public source.
- This is a structural audit of preserved source evidence. It does not replace manual webpage/PDF opening for newly collected data points.

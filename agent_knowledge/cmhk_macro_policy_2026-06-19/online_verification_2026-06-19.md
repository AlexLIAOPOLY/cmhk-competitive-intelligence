# Online Verification Audit

- Build date: 2026-06-19
- Rows checked: 7580
- Rows with verification_count < 2: 0
- source_gap_confirmed rows: 3
- Current package stage: OFCA official telecom indicators, OFCA wireless-service snapshots, C&SD official macro/GDP/labour API series, and selected official policy/spectrum events are integrated.

## Method

- Quantitative annual telecom rows are parsed from OFCA's official historical telecommunications indicators table and crosschecked against the OFCA telecommunications indicators index.
- OFCA Wireless Services annual December snapshots are parsed from the official Wireless Services PDF and crosschecked against the official statistics page.
- C&SD macro rows are parsed from official JSON API endpoints and crosschecked to their public C&SD web-table pages.
- Policy rows use official regulator/government policy documents plus an official index/context page.
- Missing cells are source gaps, not estimates.

## Source Gap Rows

| source_family | period | metric_key | metric_name | official_value | note |
|---|---:|---|---|---:|---|
| OFCA telecommunications indicators | FY2015/16 | dedicated_mobile_data_connections_with_download_speeds_higher_than_256kbps | Dedicated mobile data connections with download speeds higher than 256kbps (million) |  | Official public OFCA table retained. N/A or unavailable cells are kept as source gaps and are not estimated. |
| OFCA wireless services | 2017-12 | machine_type_connections | Machine type connections |  | Official OFCA PDF table retained. 4G/5G columns are excluded in this build because PDF extraction splits those columns across continuation rows; no excluded values are estimated. |
| OFCA wireless services | 2016-12 | machine_type_connections | Machine type connections |  | Official OFCA PDF table retained. 4G/5G columns are excluded in this build because PDF extraction splits those columns across continuation rows; no excluded values are estimated. |
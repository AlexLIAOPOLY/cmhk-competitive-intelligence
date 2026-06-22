# C&SD Population Estimates Quick Reference

- Build date: 2026-06-19
- Source family: C&SD population estimates
- Rows in source family: 820
- Mid-year snapshot rows: 410
- Year-end snapshot rows: 410
- Metric count: 41
- Official table: https://www.censtatd.gov.hk/en/web_table.html?id=110-01001
- Component metadata: https://www.censtatd.gov.hk/data/table_110-01001_comp.json
- Language metadata: https://www.censtatd.gov.hk/data/en/table_110-01001_lang.json
- Raw population MDT CSV: https://www.censtatd.gov.hk/data/MDT_76_110-01001_POP_Raw_K_1dp_per_n.csv
- Population-share MDT CSV: https://www.censtatd.gov.hk/data/MDT_76_110-01001_POP_Prop_1dp_percent_n.csv
- Formal-use fields: `official_value`, `official_unit`, `official_source_label`, `official_source_url`, `official_evidence`, `verification_sources`, `verification_count`, `verification_status`.
- Boundary: population rows are addressable-market and age-mix context for CMHK analysis, not direct CMHK revenue, ARPU, subscriber or market-share forecast targets.
- Boundary: mid-year and year-end rows are separate official snapshots. Do not average or interpolate them into quarters.
- Boundary: sex-by-age cross rows are intentionally excluded from this compact package; excluded rows are not estimated.
- Naming note: official age group `≥85` is stored as `population_age_85` in this package.

## 2025 Mid-Year Selected Values

| metric_key | metric_name | official_value | official_unit | verification_count | source_url |
|---|---|---:|---|---:|---|
| population_total | Population - Total population | 7498.9 | thousand persons | 4 | https://www.censtatd.gov.hk/en/web_table.html?id=110-01001 |
| population_sex_male | Population - Sex: Male | 3400.1 | thousand persons | 4 | https://www.censtatd.gov.hk/en/web_table.html?id=110-01001 |
| population_sex_female | Population - Sex: Female | 4098.8 | thousand persons | 4 | https://www.censtatd.gov.hk/en/web_table.html?id=110-01001 |
| population_age_65_69 | Population - Age group: 65 - 69 | 598.2 | thousand persons | 4 | https://www.censtatd.gov.hk/en/web_table.html?id=110-01001 |
| population_age_85 | Population - Age group: ≥85 | 245.2 | thousand persons | 4 | https://www.censtatd.gov.hk/en/web_table.html?id=110-01001 |

## Total Population Snapshots

| period | period_end | grain | official_value | official_unit | verification_count |
|---|---:|---|---:|---|---:|
| mid-year 2016 | 2016-06-30 | mid_year_snapshot | 7336.6 | thousand persons | 4 |
| year-end 2016 | 2016-12-31 | year_end_snapshot | 7378.1 | thousand persons | 4 |
| mid-year 2017 | 2017-06-30 | mid_year_snapshot | 7393.2 | thousand persons | 4 |
| year-end 2017 | 2017-12-31 | year_end_snapshot | 7414.8 | thousand persons | 4 |
| mid-year 2018 | 2018-06-30 | mid_year_snapshot | 7452.6 | thousand persons | 4 |
| year-end 2018 | 2018-12-31 | year_end_snapshot | 7487.7 | thousand persons | 4 |
| mid-year 2019 | 2019-06-30 | mid_year_snapshot | 7507.9 | thousand persons | 4 |
| year-end 2019 | 2019-12-31 | year_end_snapshot | 7520.5 | thousand persons | 4 |
| mid-year 2020 | 2020-06-30 | mid_year_snapshot | 7481.0 | thousand persons | 4 |
| year-end 2020 | 2020-12-31 | year_end_snapshot | 7426.7 | thousand persons | 4 |
| mid-year 2021 | 2021-06-30 | mid_year_snapshot | 7413.1 | thousand persons | 4 |
| year-end 2021 | 2021-12-31 | year_end_snapshot | 7401.5 | thousand persons | 4 |
| mid-year 2022 | 2022-06-30 | mid_year_snapshot | 7346.1 | thousand persons | 4 |
| year-end 2022 | 2022-12-31 | year_end_snapshot | 7472.6 | thousand persons | 4 |
| mid-year 2023 | 2023-06-30 | mid_year_snapshot | 7536.1 | thousand persons | 4 |
| year-end 2023 | 2023-12-31 | year_end_snapshot | 7527.9 | thousand persons | 4 |
| mid-year 2024 | 2024-06-30 | mid_year_snapshot | 7524.1 | thousand persons | 4 |
| year-end 2024 | 2024-12-31 | year_end_snapshot | 7500.6 | thousand persons | 4 |
| mid-year 2025 | 2025-06-30 | mid_year_snapshot | 7498.9 | thousand persons | 4 |
| year-end 2025 | 2025-12-31 | year_end_snapshot | 7510.8 | thousand persons | 4 |

## Latest Mid-Year Age-Group Distribution (2025-06-30)

| metric_key | age_group | population_thousand_persons | share_percent |
|---|---|---:|---:|
| population_age_0_4 | 0 - 4 | 174.1 | 2.3 |
| population_age_10_14 | 10 - 14 | 289.8 | 3.9 |
| population_age_15_19 | 15 - 19 | 278.5 | 3.7 |
| population_age_20_24 | 20 - 24 | 300.3 | 4.0 |
| population_age_25_29 | 25 - 29 | 392.9 | 5.2 |
| population_age_30_34 | 30 - 34 | 503.2 | 6.7 |
| population_age_35_39 | 35 - 39 | 563.6 | 7.5 |
| population_age_40_44 | 40 - 44 | 606.7 | 8.1 |
| population_age_45_49 | 45 - 49 | 571.1 | 7.6 |
| population_age_50_54 | 50 - 54 | 585.9 | 7.8 |
| population_age_55_59 | 55 - 59 | 567.3 | 7.6 |
| population_age_5_9 | 5 - 9 | 250.9 | 3.3 |
| population_age_60_64 | 60 - 64 | 633.0 | 8.4 |
| population_age_65_69 | 65 - 69 | 598.2 | 8.0 |
| population_age_70_74 | 70 - 74 | 458.3 | 6.1 |
| population_age_75_79 | 75 - 79 | 323.3 | 4.3 |
| population_age_80_84 | 80 - 84 | 156.6 | 2.1 |
| population_age_85 | ≥85 | 245.2 | 3.3 |
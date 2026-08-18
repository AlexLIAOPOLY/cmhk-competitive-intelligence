# 全数据库常见披露与三来源审计（2026-08-18）

## 严格口径

- 单个正式数值至少需要 3 个不同来源文档 URL。
- 同一 PDF/网页内的多个章节、标签或归档快照只计 1 个来源。
- 未达到门槛的现有值保留，但列入补证清单；未披露值不估算、不当作 0。

## 数据库结果

| 数据库 | 有值行 | 三源通过 | 待补证 | 覆盖率 | 旧计数虚高 | 状态 |
|---|---:|---:|---:|---:|---:|---|
| quarterly_competitor_metrics_2026-08-18 | 2704 | 672 | 2032 | 24.85% | 277 | backlog_open |
| cmhk_macro_policy_2026-06-19 | 7577 | 3992 | 3585 | 52.69% | 0 | backlog_open |
| global_top5_operators_2016_2025 | 394 | 348 | 46 | 88.32% | 0 | backlog_open |
| local_hk_operator_operating_metrics_2016_2025 | 172 | 0 | 172 | 0.0% | 0 | backlog_open |
| competitor_product_tariffs | 1994 | 0 | 1994 | 0.0% | 399 | backlog_open |

## 常见披露字段缺口

- `quarterly_competitor_metrics_2026-08-18`：净负债 (`net_debt`)，优先级 medium。
- `quarterly_competitor_metrics_2026-08-18`：每股股息 (`dividend_per_share`)，优先级 medium。
- `quarterly_competitor_metrics_2026-08-18`：员工数 (`employees`)，优先级 low。
- `quarterly_competitor_metrics_2026-08-18`：云经营利润 (`cloud_operating_income`)，优先级 high。
- `quarterly_competitor_metrics_2026-08-18`：云经营利润率 (`cloud_operating_margin`)，优先级 high。
- `quarterly_competitor_metrics_2026-08-18`：剩余履约义务/RPO (`remaining_performance_obligations`)，优先级 medium。
- `quarterly_competitor_metrics_2026-08-18`：云订单积压 (`cloud_backlog`)，优先级 medium。
- `quarterly_competitor_metrics_2026-08-18`：云区域数 (`cloud_regions`)，优先级 low。
- `quarterly_competitor_metrics_2026-08-18`：可用区数 (`availability_zones`)，优先级 low。
- `quarterly_competitor_metrics_2026-08-18`：数据中心数 (`data_centers`)，优先级 low。
- `global_top5_operators_2016_2025`：用户流失率 (`churn`)，优先级 medium。
- `global_top5_operators_2016_2025`：5G人口覆盖率 (`5g_population_coverage`)，优先级 medium。
- `global_top5_operators_2016_2025`：频谱持有量 (`spectrum_holdings`)，优先级 low。
- `local_hk_operator_operating_metrics_2016_2025`：户均移动流量DOU (`mobile_data_dou`)，优先级 high。
- `local_hk_operator_operating_metrics_2016_2025`：年度移动数据流量 (`annual_mobile_data_traffic`)，优先级 high。
- `local_hk_operator_operating_metrics_2016_2025`：基站总数 (`total_base_stations`)，优先级 medium。
- `local_hk_operator_operating_metrics_2016_2025`：5G基站 (`5g_base_stations`)，优先级 high。
- `local_hk_operator_operating_metrics_2016_2025`：频谱持有量 (`spectrum_holdings`)，优先级 low。
- `cmhk_macro_policy_2026-06-19`：名义GDP (`nominal_gdp`)，优先级 high。
- `cmhk_macro_policy_2026-06-19`：5G登记数 (`5g_subscriptions`)，优先级 high。
- `cmhk_macro_policy_2026-06-19`：携号转网 (`mobile_number_porting`)，优先级 medium。
- `competitor_product_tariffs`：生效日期 (`生效日期`)，优先级 high。
- `competitor_product_tariffs`：终止日期 (`终止日期`)，优先级 medium。
- `competitor_product_tariffs`：设备/路由器费用 (`设备费用_HKD`)，优先级 medium。
- `competitor_product_tariffs`：漫游覆盖地区 (`漫游覆盖`)，优先级 medium。
- `competitor_product_tariffs`：回赠/赠品 (`优惠赠品`)，优先级 low。

完整逐行补证任务见 `triple_source_backlog_2026-08-18.csv`；完整字段基线见 `common_disclosure_catalog_2026-08-18.csv`。

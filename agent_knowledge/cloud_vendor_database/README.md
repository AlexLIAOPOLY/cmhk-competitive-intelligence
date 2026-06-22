# 云厂商数据

这是给前台用户看的云厂商统一数据库入口。

## 覆盖对象

- AWS
- Microsoft Azure / Intelligent Cloud
- Google Cloud
- Alibaba Cloud
- Tencent Cloud / Tencent FBS proxy
- Huawei Cloud / Cloud Computing
- Oracle Cloud

## 主要回答什么

- 云厂商收入、利润、利润率、同比趋势。
- 哪些云厂商有季度数据，哪些只有年度或有限披露。
- 哪些数据可以预测，哪些只能做趋势说明。
- SEC、HKEX、Kaggle、FinancialReports.eu 等外部数据源能不能替代现有库。

## 使用原则

正式数值优先读取：

- `agent_knowledge/quarterly_competitor_metrics_2026-06-18/`

三年摘要可参考：

- `agent_knowledge/cloud_vendor_metrics_2026-06-17/`

外部数据源替代性判断参考：

- `agent_knowledge/external_dataset_assessment_2026-06-19/`

预测和 source-gap 边界参考：

- `agent_knowledge/quarterly_competitor_metrics_2026-06-18/cloud_source_gap_integrity_2026-06-18.md`
- `agent_knowledge/quarterly_competitor_metrics_2026-06-18/prediction_history_coverage_2026-06-18.md`

不要用外部二手数据直接替代官方值；正式结论仍使用 `official_value`、来源链接、证据说明和核验状态。


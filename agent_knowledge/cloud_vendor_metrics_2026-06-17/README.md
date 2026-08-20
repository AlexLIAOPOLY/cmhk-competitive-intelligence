# cloud_vendor_metrics_2026-06-17

重点云厂商经营数据包，供小竞 AI / Agent RAG 调用。

## 数据内容

- 覆盖 AWS、Microsoft Azure / Intelligent Cloud、Google Cloud、Alibaba Cloud、Tencent Cloud 代理口径、Huawei Cloud / Cloud Computing、Oracle Cloud。
- 覆盖 FY2023-FY2025 或各公司最近三个完整财年披露的云收入/代理分部收入、利润/毛利/调整后 EBITA、利润率和同比。
- 数据来源为官方 10-K、官方年报、官方业绩 PDF/公告。

## 文件

- `cloud_vendor_metrics_summary.md`：面向 Agent 和人工阅读的摘要。
- `cloud_vendor_metrics_2023_2025.json`：结构化数据。
- `cloud_vendor_metrics_2023_2025.csv`：逐行长表，含 `official_value`、核验状态、来源和质量说明。
- `cloud_vendor_metrics_human_readable.csv`：面向 Excel/人工查看的精简宽表，只保留核心字段。
- `sources.json`：来源清单。
- `online_verification_2026-06-17.md`：逐行核验说明。
- `online_verification_2026-06-17.csv`：逐行核验明细，区分官方直接核验和派生计算。

## Agent 使用要求

当用户询问 CMHK 需要关注的云厂商、AWS/Azure/GCP/阿里云/腾讯云/华为云/Oracle Cloud 的收入、利润、趋势、同比、同业对比、AI 云基础设施趋势时，先用 `search_local_reports` 检索本目录，再用 `read_local_reference` 读取 JSON 或摘要。

特别注意：

- Microsoft Azure 未单独披露收入，使用 Intelligent Cloud 和 Server products and cloud services 代理。
- Tencent Cloud 未单独披露收入，使用 FinTech and Business Services 代理，不能表述为腾讯云纯收入。
- Huawei Cloud 2024 数据存在最新年报重述，趋势分析时必须提示口径变化。
- Alibaba Cloud 利润指标为调整后 EBITA，非 GAAP。

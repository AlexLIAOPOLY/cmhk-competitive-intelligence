# 全球重点十家运营商 2016–2025 数据库

## 入口

- `annual_metrics.json`：主数据和元数据。
- `annual_metrics.csv`：长表。
- `sources.json`：官方来源登记。
- `coverage.csv`：逐运营商、逐年、逐指标覆盖/缺口。
- `quality_audit.json` / `quality_audit.md`：质量门禁。
- `conflicts_and_scope_breaks.json` / `.csv`：重述、冲突、推导值与口径断点。
- `summary.md`：研究对象与使用边界。

## 与原数据库的关系

中国移动、中国电信、中国联通的财务数据继续以 `quarterly_competitor_metrics_2026-06-18/quarterly_metrics.json` 为唯一事实源；中国广电及四家内地运营商的新增运营指标写入该原数据库目录的 `annual_operating_metrics_2016_2025.*`。本目录沿用历史兼容 ID `global_top5_operators_2016_2025`，内容现为十家整合视图。Airtel、Jio、Verizon、Deutsche Telekom、AT&T、NTT Group 的财务和运营记录均在本库；Comcast 未纳入。

## 重建

```bash
python3 scripts/build_global_top5_operator_database.py
```

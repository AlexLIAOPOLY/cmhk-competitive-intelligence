# 香港本地運營商非財務經營指標庫

## 入口

- `annual_metrics.json` / `.csv`：標準長表
- `full_metric_audit_2016_2025.*`：3HK、HKT、SmarTone全部指标×全部年度审计矩阵
- `coverage.csv`：逐年覆蓋、缺口原因分类及复核来源数
- `sources.json`：官方來源
- `source_inventory.md`：收集前來源盤點
- `quality_audit.*`：質量門禁
- `conflicts_and_scope_breaks.*`：重述、財年差與業務斷點

## 與現有數據庫的關係

財務事實仍以 `agent_knowledge/hk_competitor_product_tariffs/local_financial_results.json` 為準；本庫只補充客戶、5G、寬頻、網絡、ARPU、流失率等非財務經營指標。

## 重建

```bash
python3 scripts/build_local_hk_operator_operating_database.py
```

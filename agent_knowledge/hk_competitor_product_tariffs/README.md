# 香港竞对产品资费数据库

更新时间（HKT）：2026-07-13T08:54:16+08:00

## 覆盖对象

3HK / Hutchison、SmarTone、HKBN、HGC、i-CABLE。

## 文件

- `current_plans.csv/json`：当前公开套餐和产品资费。
- `historical_plans.csv/json`：2012-2026 可取得公开归档中的历史套餐（品牌覆盖年份不同）。
- `source_gaps.csv/json`：抓取或解析缺口，不能估算。
- `quality_audit.md/json`：覆盖、验证和 source-gap 审计。
- `verification_followup_audit.csv/json/md`：单源候选的二次检索结论和真实来源/解析缺口的终态说明。
- `hk_competitor_product_tariffs_human_readable.xlsx`：人读版工作簿。

## 口径

只使用公开官方页面和公开归档；`verification_count>=2` 才视为多方或多快照验证，单来源记录保留但标为需复核；多个官方来源同口径金额不一致时标为 `official_price_conflict_needs_review`，不强行合并为正式结论。

# 香港竞对产品资费 Agent 读取说明

## 数据用途

本数据集用于查询和比较香港运营商公开产品、套餐、月费、数据量、宽频速率、合约期与历史资费变化。它不是公司财务、用户数或季度经营指标数据集，不能替代财务趋势预测数据。

## Agent 读取顺序

1. 先读本文件，确认口径和边界。
2. 价格、套餐和历史比较只读取 `product_tariffs_formal_agent_records.csv`。其中每行 `record_class=formal_product_tariff`。
3. 用户问缺口、完整性、来源可得性或为何没有某套餐时，读取 `product_tariffs_source_gaps_agent_records.csv`。其中 `record_class=source_gap`，不得将其作为价格事实、趋势样本或预测输入。
4. 用户问单源候选是否复核、为何没有转为正式套餐时，读取 `product_tariffs_followup_agent_records.csv`；必须引用 `recheck_status`、`disposition` 和 `reason`。
5. 需要追溯时，优先给出同一行的 `来源URL` / `归档URL`、`来源ID`、`快照ID` 和 `证据摘录`。

## 正式口径

- HKT/csl/1O1O/NETVIGATOR 行：`核验状态=official_public_source_structured`，表示由官方公开页面、价目表或官方归档结构化；不应伪称每行已有两个独立来源。
- 3HK/SmarTone/HKBN/HGC/i-CABLE 行：正式表仅包含 `核验状态=multi_source_or_multi_snapshot_verified` 的记录。
- `月费_HKD` 是月度套餐费。`公开价格_HKD` 与 `计价单位` 用于日费或其他不能转写为月费的公开价格，严禁自行换算成月费。
- 套餐互比必须同时核对品牌、期间、产品类别、客户分段、合约期、数据量/宽频速率及附加条件。相同价格不代表同一套餐。

## 覆盖与限制

- 当前正式套餐：2005 条；来源缺口：75 条；缺口复核结论：70 条。
- HKT 历史可用范围覆盖 2007-2026；其他品牌和产品线的年份覆盖不同，不能声称每个品牌已有完整十年连续资费。
- 任何 source-gap、单源候选、不同合约期/客户分段或价格口径冲突的记录，均不能用于估算、补数或价格预测。

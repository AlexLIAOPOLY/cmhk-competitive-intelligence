# 公司合并/重组/口径跳变风险标注（2026-07-03）

本文件用于补充 `quarterly_metrics.csv` 的趋势分析边界。它不改写任何已核验数值，只给小竞 AI 和人工审核者提示：哪些主体在做趋势、预测、同比或竞品比较时，可能因为公司合并、业务组合、分部重分类、代理口径或披露边界而出现“看似跳变”的风险。

## 使用原则

- 正式数值仍以 `official_value` 为准。
- `verification_status=official_conflict` 表示标准化表和官方口径冲突，正式结论必须说明冲突并采用官方值。
- `source_gap_confirmed` 表示公开披露缺口，不得估算。
- 本文件的 `risk_level` 不是数据错误等级，而是趋势解释时需要提示的口径风险等级。
- “潜在公司动作风险”不等于已确认发生并购；如需要写成正式事件结论，必须再查官方公告或年报管理层讨论。

## 高风险主体

| 主体 | 风险原因 | 当前是否已标明 | 分析处理 |
| --- | --- | --- | --- |
| Alibaba Cloud | Cloud Intelligence Group 重列/重述，旧 Cloud segment 含钉钉等口径不可混用。 | 已在 `verification_note` / source-gap 行中标明。 | 只用重列后的同口径序列；旧口径只能作背景。 |
| Tencent Cloud / Tencent FBS proxy | 腾讯云未单独披露收入，FBS 是代理分部；2019Q1 前没有可比 FBS 序列。 | 已标代理口径和 2016-2018 source gap。 | 不能称为“腾讯云收入”；不能用旧分部补齐。 |
| Huawei Cloud / Cloud Computing | 只有年度分部披露；2025 年报对 2024 云计算收入作重分类/重述。 | 已在云厂商说明中标明。 | 不拆季度/半年度；跨年趋势必须说明重述影响。 |
| Microsoft Azure / Intelligent Cloud | Azure 不披露绝对收入，Intelligent Cloud / Server products and cloud services 是代理口径。 | 已标为官方代理分部。 | 不能写成纯 Azure 收入；比较时保留代理口径说明。 |
| HGC | 非上市主体，公开周期财务表缺失。 | 已标 `source_gap_confirmed`。 | 不做财务趋势预测；只保留 source-gap 和产品/市场情报。 |
| HKBN | 半年度披露，且 AFF/EBITDA 等指标对收购整合、业务组合和调整项较敏感。 | 已标半年度粒度、`official_conflict`、`official_only`；未单列并购字段。 | 需要结合官方年报/中报说明解释跳变，不直接用标准化表。 |

## 中风险主体

| 主体 | 风险原因 | 当前是否已标明 | 分析处理 |
| --- | --- | --- | --- |
| HKT / csl / 1O1O | 集团/品牌组合口径，半年度披露；部分指标标准化表与官方 segment 值冲突。 | 已标 half_year、official_conflict/official_only。 | 以 HKT Trust and HKT Limited 官方口径分析，不把单品牌变化当成集团跳变。 |
| 3HK / Hutchison | 集团/品牌口径和半年度披露；部分 EBITDA 等指标存在官方口径冲突。 | 已标 half_year、official_conflict/official_only。 | 使用 Hutchison Telecommunications Hong Kong Holdings Limited 官方值。 |
| i-CABLE | 半年度披露，业务结构变化或非核心损益可能影响趋势。 | 已标 half_year、official_conflict/official_only。 | 收入、EBITDA、净利润需结合官方公告说明。 |
| Google Cloud | 2020 前季度披露边界不完整，早期 annual-only 信息不可当季度训练点。 | 已标 source-gap / disclosure-boundary。 | 从同口径季度开始建模；早期年度数据只作背景。 |
| Oracle Cloud | 云收入产品线与 Cloud and license 利润口径不同；FY2022 前序列不可比。 | 已标 source-gap 和产品线/分部口径。 | 云收入与利润不要混称；FY2022 前不要估算。 |
| 中国联通 | 部分期间官方未披露同口径单季字段。 | 已标 source_gap/official_conflict。 | 不用标准化表估算缺口；只用同口径 official_value。 |
| 中国铁塔 | 官方常披露累计值或 KPI，单季同口径字段缺口较多。 | 已标大量 source_gap。 | 不拆累计值估算单季。 |

## 低到中风险主体

| 主体 | 风险原因 | 当前是否已标明 | 分析处理 |
| --- | --- | --- | --- |
| 中国移动 | 主要是标准化表与官方口径差异，不是公司合并跳变。 | 已标 official_conflict/source_gap。 | 采用 official_value，并说明口径冲突。 |
| 中国电信 | 主要是标准化表与官方口径差异。 | 已标 official_conflict/source_gap。 | 采用 official_value，并说明披露/累计口径边界。 |
| SmarTone | 主要是半年度/财年边界和标准化表冲突。 | 已标 half_year、official_conflict/official_only。 | 避免与自然季度公司直接逐季比较。 |
| AWS | 直接披露 AWS segment，跳变风险较低；部分 Q4 由全年值减前三季复算。 | 已标 annual reconciliation。 | 说明 Q4 复算口径即可。 |

## 对 AI 回答的要求

当用户要求趋势、预测或竞品比较时：

1. 如果主体在高风险或中风险表内，回答中必须说明对应口径风险。
2. 如果涉及 `official_conflict`，必须优先用 `official_value`，并说明标准化表与官方值不一致。
3. 如果涉及代理口径，不能把代理分部直接写成单一业务收入。
4. 如果涉及 `source_gap_confirmed`，必须说“公开披露缺口”，不得估算补齐。

结构化机器可读版本见：

- `corporate_action_risk_annotations_2026-07-03.csv`

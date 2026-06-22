# quarterly_competitor_metrics_2026-06-18

供小竞 AI 使用的季度/半年度竞对经营数据包。

## 文件

- `quarterly_metrics_summary.md`：数据包说明、覆盖主体、披露粒度和来源。
- `quarterly_metrics.json`：结构化数据，包含主体、期间、指标、来源和质量状态。
- `quarterly_metrics.csv`：长表，适合 Agent 做趋势、图表和筛选。
- `quarterly_metrics_human_readable.csv`：人工查看精简宽表。
- `sources.json`：来源清单。
- `official_verified_metrics_2026-06-18.csv`：已完成官方公告交叉核验的明细，包含官方值、来源链接、证据句和冲突说明。
- `online_verification_2026-06-18.md`：核验状态说明。
- `online_verification_2026-06-18.csv`：逐行核验状态。
- `prediction_history_coverage_2026-06-18.md` / `.csv`：7年/10年预测历史窗口覆盖缺口审计。
- `prediction_history_source_plan_2026-06-18.md`：下一轮补 2016-2024 历史数据的来源入口、优先级和验收门禁。

## Agent 使用要求

1. 用户问“季度”“Q1/Q2/Q3/Q4”“更小计量单位”“半年度”“最近几个季度”时，优先读取本目录。
2. 必须区分 `grain=quarter` 和 `grain=half_year`；不能把 H1/H2 说成季度。
3. `official_match` 可以作为已核验事实使用；`official_conflict` 必须采用 `official_value` 并说明标准化表与官方披露存在口径冲突；`official_only` 是官方报告独有口径。
4. `source_gap_confirmed` 表示已核验官方站点但未发现公开季度/半年度财务表，只能回答披露缺口，禁止估算财务数。
5. `official_source_registered` 表示已登记官方披露入口，但尚未从 segment/product-line 表逐项抽取数值，不能当作云业务数据结论。
6. `verification_count>=2` 才表示已用多个官方页面或披露文件复核；具体链接和证据保存在 `verification_sources`。
7. 对 `verification_status=needs_official_row_crosscheck` 的行，回答前必须再用联网搜索或本地官方来源核验关键数。
8. 云厂商分部数据不得使用母公司总表替代；如果本包只给出来源入口或母公司总表线索，必须说明不能直接作为云收入结论。
9. 回答 7年/10年覆盖、预测准备度或还缺哪些历史期间时，优先读取 `prediction_history_coverage_2026-06-18.*` 和 `prediction_history_source_plan_2026-06-18.md`。

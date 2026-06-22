# 小竞AI完整前端测试汇总

- 测试总数：60
- 通过数：60
- 缺失截图：0
- 截图目录：`tmp/xiaojing_full_goal_tests_20260619`

## 分组统计

- `database:core`：3 条，pass 3
- `database:external_assessment`：3 条，pass 3
- `database:macro`：3 条，pass 3
- `database:quarterly`：3 条，pass 3
- `database:system_audit`：3 条，pass 3
- `function:anomaly_watch`：3 条，pass 3
- `function:audit_log_lookup`：3 条，pass 3
- `function:cloud_vendor_metrics`：3 条，pass 3
- `function:database_selection`：3 条，pass 3
- `function:executive_briefing`：3 条，pass 3
- `function:forecasting`：3 条，pass 3
- `function:metric_drilldown`：3 条，pass 3
- `function:multi_database_retrieval`：3 条，pass 3
- `function:rag_retrieval`：3 条，pass 3
- `function:skill_selection`：3 条，pass 3
- `function:source_verification`：3 条，pass 3
- `function:upload`：3 条，pass 3
- `function:verification_watch`：3 条，pass 3
- `function:visualization`：3 条，pass 3
- `function:web_search`：3 条，pass 3

## 明细

| ID | 分组 | 结果 | 截图 | 备注 |
| --- | --- | --- | --- | --- |
| db_audit_01 | database:system_audit | PASS | `db_audit_01.png` |  |
| db_audit_02 | database:system_audit | PASS | `db_audit_02.png` |  |
| db_audit_03 | database:system_audit | PASS | `db_audit_03.png` |  |
| db_core_01 | database:core | PASS | `db_core_01.png` |  |
| db_core_02 | database:core | PASS | `db_core_02.png` |  |
| db_core_03 | database:core | PASS | `db_core_03.png` |  |
| db_external_01 | database:external_assessment | PASS | `db_external_01.png` |  |
| db_external_02 | database:external_assessment | PASS | `db_external_02.png` |  |
| db_external_03 | database:external_assessment | PASS | `db_external_03.png` |  |
| db_macro_01 | database:macro | PASS | `db_macro_01.png` |  |
| db_macro_02 | database:macro | PASS | `db_macro_02.png` |  |
| db_macro_03 | database:macro | PASS | `db_macro_03.png` |  |
| db_quarterly_01 | database:quarterly | PASS | `db_quarterly_01.png` |  |
| db_quarterly_02 | database:quarterly | PASS | `db_quarterly_02.png` |  |
| db_quarterly_03 | database:quarterly | PASS | `db_quarterly_03.png` |  |
| func_anomaly_01 | function:anomaly_watch | PASS | `func_anomaly_01.png` |  |
| func_anomaly_02 | function:anomaly_watch | PASS | `func_anomaly_02.png` | active datasets: quarterly_competitor_metrics_2026-06-18 |
| func_anomaly_03 | function:anomaly_watch | PASS | `func_anomaly_03.png` |  |
| func_auditlog_01 | function:audit_log_lookup | PASS | `func_auditlog_01.png` |  |
| func_auditlog_02 | function:audit_log_lookup | PASS | `func_auditlog_02.png` |  |
| func_auditlog_03 | function:audit_log_lookup | PASS | `func_auditlog_03.png` |  |
| func_cloud_01 | function:cloud_vendor_metrics | PASS | `func_cloud_01.png` | active datasets: quarterly_competitor_metrics_2026-06-18 |
| func_cloud_02 | function:cloud_vendor_metrics | PASS | `func_cloud_02.png` | active datasets: quarterly_competitor_metrics_2026-06-18 |
| func_cloud_03 | function:cloud_vendor_metrics | PASS | `func_cloud_03.png` | active datasets: external_dataset_assessment_2026-06-19,quarterly_competitor_metrics_2026-06-18 |
| func_db_select_01 | function:database_selection | PASS | `func_db_select_01_all_selected.png` |  |
| func_db_select_02 | function:database_selection | PASS | `func_db_select_02_single_quarterly.png` |  |
| func_db_select_03 | function:database_selection | PASS | `func_db_select_03_none_selected.png` |  |
| func_exec_01 | function:executive_briefing | PASS | `func_exec_01.png` | active datasets: core-company-metrics-2026-06-16,quarterly_competitor_metrics_2026-06-18 |
| func_exec_02 | function:executive_briefing | PASS | `func_exec_02.png` | active datasets: cmhk_macro_policy_2026-06-19,quarterly_competitor_metrics_2026-06-18 |
| func_exec_03 | function:executive_briefing | PASS | `func_exec_03.png` | active datasets: external_dataset_assessment_2026-06-19,system_audit_operations_2026-06-19 |
| func_forecast_01 | function:forecasting | PASS | `func_forecast_01.png` |  |
| func_forecast_02 | function:forecasting | PASS | `func_forecast_02.png` |  |
| func_forecast_03 | function:forecasting | PASS | `func_forecast_03.png` |  |
| func_metric_01 | function:metric_drilldown | PASS | `func_metric_01.png` |  |
| func_metric_02 | function:metric_drilldown | PASS | `func_metric_02.png` | active datasets: quarterly_competitor_metrics_2026-06-18 |
| func_metric_03 | function:metric_drilldown | PASS | `func_metric_03.png` |  |
| func_multi_db_01 | function:multi_database_retrieval | PASS | `func_multi_db_01.png` |  |
| func_multi_db_02 | function:multi_database_retrieval | PASS | `func_multi_db_02.png` |  |
| func_multi_db_03 | function:multi_database_retrieval | PASS | `func_multi_db_03.png` |  |
| func_rag_01 | function:rag_retrieval | PASS | `func_rag_01.png` |  |
| func_rag_02 | function:rag_retrieval | PASS | `func_rag_02.png` |  |
| func_rag_03 | function:rag_retrieval | PASS | `func_rag_03.png` |  |
| func_skill_select_01 | function:skill_selection | PASS | `func_skill_select_01_all.png` |  |
| func_skill_select_02 | function:skill_selection | PASS | `func_skill_select_02_single_forecast.png` |  |
| func_skill_select_03 | function:skill_selection | PASS | `func_skill_select_03_multi.png` |  |
| func_source_01 | function:source_verification | PASS | `func_source_01.png` |  |
| func_source_02 | function:source_verification | PASS | `func_source_02.png` |  |
| func_source_03 | function:source_verification | PASS | `func_source_03.png` |  |
| func_upload_01 | function:upload | PASS | `func_upload_01_entry_inside_menu.png` |  |
| func_upload_02 | function:upload | PASS | `func_upload_02_uploaded_dataset.png` |  |
| func_upload_03 | function:upload | PASS | `func_upload_03_retrieval_answer.png` |  |
| func_veriwatch_01 | function:verification_watch | PASS | `func_veriwatch_01.png` | active datasets: quarterly_competitor_metrics_2026-06-18,system_audit_operations_2026-06-19 |
| func_veriwatch_02 | function:verification_watch | PASS | `func_veriwatch_02.png` | active datasets: core-company-metrics-2026-06-16 |
| func_veriwatch_03 | function:verification_watch | PASS | `func_veriwatch_03.png` | active datasets: external_dataset_assessment_2026-06-19 |
| func_visual_01 | function:visualization | PASS | `func_visual_01.png` |  |
| func_visual_02 | function:visualization | PASS | `func_visual_02.png` |  |
| func_visual_03 | function:visualization | PASS | `func_visual_03.png` |  |
| func_web_01 | function:web_search | PASS | `func_web_01.png` |  |
| func_web_02 | function:web_search | PASS | `func_web_02.png` |  |
| func_web_03 | function:web_search | PASS | `func_web_03.png` | web search rate limit fallback observed |
## Final UI State

- Final visible database count after archiving the temporary upload test database: 5.
- Final database menu screenshot: `99_final_visible_5_databases.png`.
- Contact sheets: `contact_sheet_01.png` to `contact_sheet_05.png`.
- Note: one web-search test observed a web-search rate-limit fallback; the AI still completed using local evidence and the behavior is recorded in `func_web_03.png`.

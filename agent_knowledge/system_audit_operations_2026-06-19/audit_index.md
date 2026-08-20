# Audit and Operations Index

## Consolidated Purpose

This visible database consolidates quality-control and operations evidence. It does not replace the underlying audit files; it points the Agent to the right evidence source without showing every audit package as a separate front-end database.

## Detailed Evidence Sources

| Topic | Original package | Use for |
| --- | --- | --- |
| Database visibility | `agent_knowledge/agent_dataset_visibility_audits/` | Confirm which packages should be visible to 小竞AI and whether superseded/hidden packages are excluded. |
| Agent guidance and skill alignment | `agent_knowledge/agent_guidance_alignment_audits/` | Confirm Agent prompts and skills use the newest formal packages and respect superseded package rules. |
| Forecast boundary audit | `agent_knowledge/forecast_readiness_audits/` | Confirm forecasting tools exclude source-gap, legacy non-forecast rows and macro-policy event rows. |
| Goal readiness | `agent_knowledge/goal_readiness_audits/` | Confirm target-level completion evidence and requirement mapping. |
| Knowledge integrity | `agent_knowledge/knowledge_integrity_audits/` | Confirm manifest entrypoints, row counts, `official_value`, `verification_count`, source-gap values and required fields. |
| Source evidence integrity | `agent_knowledge/source_evidence_audits/` | Confirm row-level source links, evidence notes and `verification_sources`. |
| URL reachability | `agent_knowledge/source_url_reachability_audits/` | Confirm whether source URLs are reachable, restricted, timed out or failed. |
| Crawl / run logs | `agent_knowledge/crawl_run_logs/` | Inspect historical crawl runs, Feishu log references, quality summaries and local run artifacts. |

## Current Formal Data Packages

The audit packages above support, but do not replace, these formal data packages:

- `agent_knowledge/quarterly_competitor_metrics_2026-06-18/`
- `agent_knowledge/core_company_metrics_2026-06-16/`
- `agent_knowledge/cmhk_macro_policy_2026-06-19/`
- `agent_knowledge/external_dataset_assessment_2026-06-19/`

## Front-End Simplification Decision

Keep visible:

1. 主体公司近三年核心经营/财务数据
2. 竞对主体和重点云厂商季度/半年度经营数据包
3. CMHK 10年宏观政策与机构指标数据
4. 外部可下载数据集替换/增强评估
5. 系统审计与运行记录

Hide or archive from the default picker:

- Detailed audit sub-packages listed above.
- Temporary user-upload test knowledge bases.
- `cloud_vendor_metrics_2026-06-17`, because cloud-vendor formal period-level analysis should use `quarterly_competitor_metrics_2026-06-18`; the old package remains preserved as a historical concise summary.


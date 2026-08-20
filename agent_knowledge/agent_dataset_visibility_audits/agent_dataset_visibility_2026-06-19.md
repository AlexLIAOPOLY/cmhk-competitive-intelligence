# Agent Dataset Visibility Audit (2026-06-19)

- Checks: 11
- Passed: 11
- Failed: 0
- API checked: True

## Dataset Results

| Dataset | Status | Entry points | Files | RAG chunks | Issues |
| --- | --- | ---: | ---: | ---: | --- |
| cmhk_macro_policy_2026-06-19 | pass | 13 | 14 | 4 |  |
| quarterly_competitor_metrics_2026-06-18 | pass | 14 | 30 | 4 |  |
| cloud_vendor_metrics_2026-06-17 | pass | 8 | 9 | 4 |  |
| knowledge_integrity_audits | pass | 2 | 3 | 4 |  |
| forecast_readiness_audits | pass | 2 | 3 | 4 |  |
| source_evidence_audits | pass | 2 | 3 | 4 |  |
| source_url_reachability_audits | pass | 2 | 3 | 4 |  |
| goal_readiness_audits | pass | 2 | 3 | 4 |  |
| agent_guidance_alignment_audits | pass | 2 | 3 | 4 |  |
| generated_charts | pass |  |  |  |  |
| quarterly_competitor_metrics_2026-06-17 | pass |  |  |  |  |

## Scope

- Verifies the core CMHK macro, quarterly competitor/cloud, cloud vendor, and audit datasets are registered with manifests, entrypoints, readable files, and RAG hits.
- Verifies generated output folders and superseded knowledge packages are not exposed as selectable AI databases or default RAG sources.
- If the local web server is running, verifies `/api/agent-datasets` exposes the same expected dataset IDs.

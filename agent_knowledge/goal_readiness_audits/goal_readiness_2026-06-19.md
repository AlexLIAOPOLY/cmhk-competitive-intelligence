# Goal Readiness Audit (2026-06-19)

- Requirements checked: 7
- Passed: 7
- Failed: 0

## Requirement Results

| Requirement | Status | Evidence | Details |
| --- | --- | --- | --- |
| main_data_packages_preserve_required_fields_and_row_integrity | pass | main package CSVs and manifests | `{"bad_verification_sources": 0, "missing_official_value": 0, "packages": {"cloud_vendor_metrics_2026-06-17": {"bad_verification_sources": 0, "issues": [], "low_verification": 0, "manifest_id": "cloud_vendor_metrics_2026-06-17", "manifest_quality": "verified_against_official_public_sources", "missing_fields": [], "missing_official_value": 0, "rows": 83, "source_gap_with_official_value": 0}, "cmhk_macro_policy_2026-06-19": {"bad_verification_sources": 0, "issues": [], "low_verification": 0, "manifest_id": "cmhk_macro_policy_2026-06-19", "manifest_quality": "official_verified_macro_policy_build_ready_for_rag", "missing_fields": [], "missing_official_value": 0, "rows": 7580, "source_gap_with_official_value": 0}, "quarterly_competitor_metrics_2026-06-18": {"bad_verification_sources": 0, "issues": [], "low_verification": 0, "manifest_id": "quarterly_competitor_metrics_2026-06-18", "manifest_quality": "official_verified_with_documented_source_gaps", "missing_fields": [], "missing_official_value": 0, "rows": 3013, "source_gap_with_official_value": 0}}, "source_gap_with_official_value": 0, "total_rows": 10676, "verification_count_lt_2": 0}` |
| source_evidence_fields_are_complete | pass | agent_knowledge/source_evidence_audits/source_evidence_integrity_2026-06-19.csv | `{"bad_rows": 0, "rows": 3, "status_counts": {"pass": 3}}` |
| source_urls_have_no_hard_failures | pass | agent_knowledge/source_url_reachability_audits/source_url_reachability_2026-06-19.csv | `{"accepted_non_ok_statuses": ["reachable_restricted", "ssl_error"], "hard_failures": 0, "status_counts": {"ok": 571, "reachable_restricted": 133, "ssl_error": 1}, "unique_urls": 705}` |
| forecast_tool_respects_series_boundaries | pass | agent_knowledge/forecast_readiness_audits/forecast_readiness_alignment_2026-06-19.csv | `{"bad_rows": 0, "rows": 8, "status_counts": {"pass": 8}}` |
| agent_guidance_routes_quality_and_prediction_questions_through_audits | pass | agent_knowledge/agent_guidance_alignment_audits/agent_guidance_alignment_2026-06-19.csv | `{"bad_rows": 0, "rows": 5, "status_counts": {"pass": 5}}` |
| dataset_picker_and_default_rag_visibility_are_audited | pass | agent_knowledge/agent_dataset_visibility_audits/agent_dataset_visibility_2026-06-19.csv | `{"bad_rows": 0, "rows": 11, "status_counts": {"pass": 11}}` |
| xiaojing_ai_database_visibility_aligned | pass | /api/agent-datasets | `{"dataset_count": 16, "hidden_or_superseded_not_visible": ["generated_charts", "quarterly_competitor_metrics_2026-06-17"], "missing_required": [], "required_visible": ["cloud_vendor_metrics_2026-06-17", "cmhk_macro_policy_2026-06-19", "quarterly_competitor_metrics_2026-06-18"], "visible_hidden_or_superseded": []}` |

## Scope

- Maps the active CMHK knowledge-base goal to current local evidence.
- Confirms the three main packages preserve official values, verification counts, source-gap boundaries, evidence text, and parseable verification source lists.
- Pulls in the dedicated source-evidence, URL-reachability, forecast-readiness, and database-visibility audits as requirement-level evidence.
- This audit is a completion-readiness map; it does not create or estimate missing data.

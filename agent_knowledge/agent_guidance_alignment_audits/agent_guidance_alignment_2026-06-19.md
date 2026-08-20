# Agent Guidance Alignment Audit (2026-06-19)

- Checks: 5
- Passed: 5
- Failed: 0

## Check Results

| Check | Status | Evidence | Details |
| --- | --- | --- | --- |
| agent_system_prompt_requires_goal_audits | pass | agent.py | `{"missing_required_phrases": []}` |
| skill_quarterly_uses_latest_package_and_marks_old_superseded | pass | Codex/agent/skills/quarterly-competitor-metrics/SKILL.md | `{"found_forbidden_phrases": [], "missing_required_phrases": [], "unsafe_old_package_contexts": []}` |
| skill_trend-forecasting_alignment | pass | Codex/agent/skills/trend-forecasting/SKILL.md | `{"found_forbidden_phrases": [], "missing_required_phrases": []}` |
| skill_source-verification_alignment | pass | Codex/agent/skills/source-verification/SKILL.md | `{"found_forbidden_phrases": [], "missing_required_phrases": []}` |
| skill_macro-policy-context_alignment | pass | Codex/agent/skills/macro-policy-context/SKILL.md | `{"found_forbidden_phrases": [], "missing_required_phrases": []}` |

## Scope

- Verifies the Agent system prompt and key local skills route data-quality, prediction, source-verification, and macro-policy questions through goal-level audits.
- Verifies the quarterly skill points to the latest official quarterly package and only mentions the old package as superseded audit history.
- This audit prevents prompt/skill drift from bypassing source, forecast, or database visibility gates.

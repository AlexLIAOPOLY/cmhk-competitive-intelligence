from __future__ import annotations

import json
import os
import tempfile
import unittest
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import data_curation.workflow as workflow
from data_curation.schemas import CandidateFact, EvidenceTask
from data_curation.workflow import (
    _votes_from_source_pages,
    _run_company_research_agent,
    audit_quality,
    build_graph,
    extract_facts,
    plan_gaps,
    publish_results,
    run_company_research_agents,
    search_verify_facts,
    supervise_gap_actions,
    run_workflow,
)
from crawl import apply_crawl_settings, redact_sensitive
from cmhk.crawl.extractors import find_field_snippets, row_fields
from normalize_company_metrics_ai import (
    _evidence_relevance,
    _evidence_mentions_company,
    _focused_evidence,
    _official_domain_owners,
    _record_allowed_for_company,
    build_tasks,
    deterministic_extract_task,
)


class DataCurationWorkflowTests(unittest.TestCase):
    def test_source_page_reader_reuses_successful_fetch(self) -> None:
        response = Mock()
        response.url = "https://example.com/results"
        response.status_code = 200
        response.headers = {"content-type": "text/html"}
        response.text = "<html><body>Revenue HK$ 10 million</body></html>"
        response.raise_for_status.return_value = None
        fact = CandidateFact(
            id="cache-test",
            company="Example",
            metric="收入",
            value="HK$ 10 million",
            sources=["https://example.com/results"],
            row_ref="row_2",
            decision="review",
        )
        workflow._SOURCE_PAGE_CACHE.clear()
        with patch("httpx.get", return_value=response) as get:
            first_audit: list[dict] = []
            second_audit: list[dict] = []
            _votes_from_source_pages(fact, open_audit=first_audit)
            _votes_from_source_pages(fact, open_audit=second_audit)
        self.assertEqual(get.call_count, 1)
        self.assertFalse(first_audit[0]["cache_hit"])
        self.assertTrue(second_audit[0]["cache_hit"])

    def test_company_profiles_include_verified_regulator_fallbacks(self) -> None:
        self.assertIn(
            "sec.gov",
            workflow._company_research_profile("KT")["official_hosts"],
        )
        self.assertIn(
            "www1.hkexnews.hk",
            workflow._company_research_profile("中国移动")["official_hosts"],
        )
        self.assertIn(
            "saudiexchange.sa",
            workflow._company_research_profile("stc")["official_hosts"],
        )

    def test_company_agents_merge_brands_and_keep_distinct_four_database_subjects(self) -> None:
        self.assertEqual(workflow._company_fact_entities("HKT"), {"HKT", "csl", "1O1O"})
        self.assertEqual(
            workflow._company_fact_entities("3HK"),
            {"3HK", "3HK / Hutchison", "Hutchison"},
        )
        self.assertIn("站址数", workflow._company_configured_metrics("中国铁塔"))
        self.assertIn("有线电视用户", workflow._company_configured_metrics("中国广电"))
        self.assertIn("云收入", workflow._company_configured_metrics("China Mobile Cloud"))
        self.assertTrue(workflow._company_metric_is_not_applicable("HGC", "派息"))
        self.assertTrue(workflow._company_agent_metric_requires_direct_value("移动用户数"))
        self.assertFalse(workflow._company_agent_metric_requires_direct_value("企业通信"))
        self.assertFalse(workflow._company_agent_metric_requires_direct_value("数据中心"))
        self.assertEqual(
            workflow._company_agent_url_key(
                "https://CDN.HGC-INTL.com/assets/Carrier-Network-%E2%80%94-Plus.pdf/"
            ),
            "https://cdn.hgc-intl.com/assets/Carrier-Network-—-Plus.pdf",
        )

    def test_company_agent_controls_its_own_search_and_open_sequence(self) -> None:
        class ToolCallingCompanyAgent:
            def __init__(self) -> None:
                self.turn = 0

            def bind_tools(self, _tools, **_kwargs):
                return self

            def invoke(self, _messages):
                self.turn += 1
                calls = {
                    1: [{"id": "inspect", "name": "inspect_company_evidence", "args": {}}],
                    2: [{"id": "search", "name": "search_latest_official", "args": {"metric": "收入"}}],
                    3: [{
                        "id": "open",
                        "name": "open_official_pages",
                        "args": {"metric": "收入", "urls": ["https://www.sec.gov/example"]},
                    }],
                    4: [{
                        "id": "complete",
                        "name": "complete_company_research",
                        "args": {
                            "status": "verified_latest",
                            "rationale": "已回读最新官方原文",
                            "metric_statuses": [{
                                "metric": "收入",
                                "status": "verified_latest",
                                "rationale": "已取得当期官方收入值",
                            }],
                        },
                    }],
                }
                return SimpleNamespace(content="", tool_calls=calls[self.turn])

        fact = CandidateFact(
            id="aws-revenue",
            company="AWS",
            metric="收入",
            row_ref="row_50",
            value="AWS revenue 42,232 million USD",
            sources=["https://www.sec.gov/example"],
            decision="accepted",
        )
        def opened_current_source(_fact, *, extra_urls=None, open_audit=None, **_kwargs):
            self.assertEqual(_fact.sources, [])
            self.assertEqual(extra_urls, ["https://www.sec.gov/example"])
            open_audit.append({"url": extra_urls[0], "http_status": 200, "opened": True})
            return [{"url": extra_urls[0], "value": "42,232 million USD"}]

        with (
            patch("data_curation.workflow._company_configured_metrics", return_value=["收入"]),
            patch("data_curation.workflow._build_supervisor_model", return_value=ToolCallingCompanyAgent()),
            patch(
                "data_curation.workflow._public_web_search",
                return_value=([{"title": "AWS 2026 results", "url": "https://www.sec.gov/example", "snippet": "AWS revenue"}], "test"),
            ),
            patch(
                "data_curation.workflow._votes_from_source_pages",
                side_effect=opened_current_source,
            ),
        ):
            result, trace = _run_company_research_agent(
                {"run_id": "company-agent-test"}, "AWS", 50, "AWS", [fact]
            )
        self.assertEqual(result["status"], "verified_latest")
        self.assertEqual(result["search_count"], 1)
        self.assertEqual(result["evidence_count"], 1)
        self.assertEqual(result["fresh_official_open_count"], 1)
        self.assertTrue(result["metric_coverage_complete"])
        self.assertEqual(result["metric_results"][0]["status"], "verified_latest")
        self.assertEqual(
            [item.get("tool") for item in trace if item.get("phase") == "tool_call"],
            ["inspect_company_evidence", "search_latest_official", "open_official_pages", "complete_company_research"],
        )

    def test_company_agent_does_not_count_fixed_old_sources_as_latest_evidence(self) -> None:
        class ToolCallingCompanyAgent:
            def __init__(self) -> None:
                self.turn = 0

            def bind_tools(self, _tools):
                return self

            def invoke(self, _messages):
                self.turn += 1
                calls = {
                    1: [{"id": "inspect", "name": "inspect_company_evidence", "args": {}}],
                    2: [{"id": "search", "name": "search_latest_official", "args": {"metric": "收入"}}],
                    3: [{
                        "id": "open",
                        "name": "open_official_pages",
                        "args": {"metric": "收入", "urls": ["https://www.sec.gov/old-report"]},
                    }],
                    4: [{
                        "id": "complete",
                        "name": "complete_company_research",
                        "args": {
                            "status": "verified_latest",
                            "rationale": "沿用旧来源",
                            "metric_statuses": [{
                                "metric": "收入",
                                "status": "verified_latest",
                                "rationale": "沿用旧来源",
                            }],
                        },
                    }],
                    5: [{
                        "id": "complete-retry",
                        "name": "complete_company_research",
                        "args": {
                            "status": "conflict",
                            "rationale": "旧来源不能证明最新，另一指标也未搜索",
                            "metric_statuses": [
                                {
                                    "metric": "收入",
                                    "status": "verified_latest",
                                    "rationale": "模型仍声称沿用旧来源",
                                },
                                {
                                    "metric": "EBITDA",
                                    "status": "conflict",
                                    "rationale": "没有当期官方证据",
                                },
                            ],
                        },
                    }],
                }
                return SimpleNamespace(content="", tool_calls=calls[self.turn])

        fact = CandidateFact(
            id="aws-old",
            company="AWS",
            metric="收入",
            value="old value",
            sources=["https://www.sec.gov/old-report"],
            decision="accepted",
        )
        second_fact = CandidateFact(
            id="aws-unsearched-ebitda",
            company="AWS",
            metric="EBITDA",
            value="old EBITDA",
            sources=["https://www.sec.gov/old-report"],
            decision="accepted",
        )
        with (
            patch("data_curation.workflow._company_configured_metrics", return_value=["收入", "EBITDA"]),
            patch("data_curation.workflow._build_supervisor_model", return_value=ToolCallingCompanyAgent()),
            patch(
                "data_curation.workflow._public_web_search",
                return_value=([{
                    "title": "AWS results 2024",
                    "url": "https://www.sec.gov/old-report",
                    "snippet": "old annual report",
                }], "test"),
            ),
            patch("data_curation.workflow._votes_from_source_pages", return_value=[]),
        ):
            result, _trace = _run_company_research_agent(
                {"run_id": "company-agent-old-source"}, "AWS", 50, "AWS", [fact, second_fact]
            )
        self.assertEqual(result["status"], "agent_error")
        self.assertEqual(result["reason_code"], "invalid_terminal_payload")
        self.assertEqual(result["evidence_count"], 0)
        self.assertEqual(result["fresh_official_open_count"], 0)
        self.assertFalse(result["metric_coverage_complete"])
        self.assertEqual(set(result["unresolved_metrics"]), {"收入", "EBITDA"})
        self.assertEqual(
            {item["metric"]: item["status"] for item in result["metric_results"]}["EBITDA"],
            "agent_error",
        )

    def test_company_agent_forces_agent_completion_when_research_turns_omit_it(self) -> None:
        class ResearchWithoutCompletion:
            def __init__(self) -> None:
                self.turn = 0

            def bind_tools(self, _tools, **_kwargs):
                return self

            def invoke(self, _messages):
                self.turn += 1
                calls = {
                    1: [{"id": "inspect", "name": "inspect_company_evidence", "args": {}}],
                    2: [{"id": "search", "name": "search_latest_official", "args": {"metric": "收入"}}],
                    3: [{
                        "id": "open",
                        "name": "open_official_pages",
                        "args": {"metric": "收入", "urls": ["https://www.sec.gov/known-report"]},
                    }],
                    4: [],
                    5: [{
                        "id": "forced-complete",
                        "name": "complete_company_research",
                        "args": {
                            "status": "complete",
                            "rationale": "最终决策 Agent 已核验最新官方值",
                            "metric_statuses": [{
                                "metric": "收入",
                                "status": "已核验",
                                "value": "已取得当期官方收入值",
                            }],
                        },
                    }],
                }
                return SimpleNamespace(content="", tool_calls=calls[self.turn])

        fact = CandidateFact(
            id="aws-known-official",
            company="AWS",
            metric="收入",
            value="42,232 million USD",
            sources=["https://www.sec.gov/known-report"],
            source_tier="official",
            decision="accepted",
        )

        def open_known_fact_source(_fact, *, extra_urls=None, open_audit=None, **_kwargs):
            self.assertEqual(extra_urls, ["https://www.sec.gov/known-report"])
            open_audit.append({"url": extra_urls[0], "http_status": 200, "opened": True})
            return [{"url": extra_urls[0], "value": "42,232 million USD"}]

        with (
            patch("data_curation.workflow._company_configured_metrics", return_value=["收入"]),
            patch("data_curation.workflow._build_supervisor_model", return_value=ResearchWithoutCompletion()),
            patch("data_curation.workflow._public_web_search", return_value=([{
                "title": "AWS 2026 results",
                "url": "https://www.sec.gov/known-report",
                "snippet": "2026 quarterly results",
            }], "test")),
            patch("data_curation.workflow._votes_from_source_pages", side_effect=open_known_fact_source),
        ):
            result, _trace = _run_company_research_agent(
                {"run_id": "company-agent-synthesized"}, "AWS", 50, "AWS", [fact]
            )
        self.assertTrue(result["completion_forced"])
        self.assertEqual(result["status"], "verified_latest")
        self.assertTrue(result["metric_coverage_complete"])
        self.assertEqual(result["metric_results"][0]["status"], "verified_latest")

    def test_company_agent_fails_closed_when_final_decision_agent_omits_completion(self) -> None:
        class NeverCompletes:
            def __init__(self) -> None:
                self.turn = 0

            def bind_tools(self, _tools, **_kwargs):
                return self

            def invoke(self, _messages):
                self.turn += 1
                calls = {
                    1: [{"id": "inspect", "name": "inspect_company_evidence", "args": {}}],
                    2: [{"id": "search", "name": "search_latest_official", "args": {"metric": "收入"}}],
                    3: [],
                    4: [],
                }
                return SimpleNamespace(content="", tool_calls=calls[self.turn])

        model = NeverCompletes()
        with (
            patch("data_curation.workflow._company_configured_metrics", return_value=["收入"]),
            patch("data_curation.workflow._company_research_profile", return_value={
                "aliases": ["AWS"], "official_hosts": [], "seed_urls": [],
            }),
            patch("data_curation.workflow._build_supervisor_model", return_value=model),
            patch("data_curation.workflow._public_web_search", return_value=([], "test")),
        ):
            result, _trace = _run_company_research_agent(
                {"run_id": "company-agent-missing-terminal"}, "AWS", 50, "AWS", []
            )
        self.assertEqual(result["status"], "agent_error")
        self.assertEqual(result["reason_code"], "missing_terminal_call")
        self.assertTrue(result["completion_forced"])
        self.assertFalse(result["metric_coverage_complete"])
        self.assertEqual(result["metric_results"][0]["status"], "agent_error")

    def test_company_agent_keeps_audited_search_exhausted_as_terminal_state(self) -> None:
        class ExhaustedCompanyAgent:
            def __init__(self) -> None:
                self.turn = 0

            def bind_tools(self, _tools):
                return self

            def invoke(self, _messages):
                self.turn += 1
                calls = {
                    1: [{"id": "inspect", "name": "inspect_company_evidence", "args": {}}],
                    2: [{"id": "search", "name": "search_latest_official", "args": {"metric": "收入"}}],
                    3: [{
                        "id": "complete",
                        "name": "complete_company_research",
                        "args": {
                            "status": "search_exhausted",
                            "rationale": "定向搜索未找到直接披露值",
                            "metric_statuses": [{
                                "metric": "收入",
                                "status": "search_exhausted",
                                "rationale": "定向搜索未找到直接披露值",
                            }],
                        },
                    }],
                }
                return SimpleNamespace(content="", tool_calls=calls[self.turn])

        with (
            patch("data_curation.workflow._company_configured_metrics", return_value=["收入"]),
            patch("data_curation.workflow._company_research_profile", return_value={
                "aliases": ["AWS"], "official_hosts": [], "seed_urls": [],
            }),
            patch("data_curation.workflow._build_supervisor_model", return_value=ExhaustedCompanyAgent()),
            patch("data_curation.workflow._public_web_search", return_value=([], "test")),
        ):
            result, _trace = _run_company_research_agent(
                {"run_id": "company-agent-exhausted"}, "AWS", 50, "AWS", []
            )
        self.assertEqual(result["status"], "search_exhausted")
        self.assertTrue(result["metric_coverage_complete"])
        self.assertEqual(result["unresolved_metrics"], [])
        self.assertEqual(result["metric_results"][0]["status"], "search_exhausted")

    def test_company_agent_accepts_exhaustion_after_current_official_page_has_no_metric(self) -> None:
        current_url = "https://example.com/2026-results"

        class ExhaustedAfterOpenAgent:
            def __init__(self) -> None:
                self.turn = 0

            def bind_tools(self, _tools, **_kwargs):
                return self

            def invoke(self, _messages):
                self.turn += 1
                calls = {
                    1: [{"id": "search", "name": "search_latest_official", "args": {"metric": "收入"}}],
                    2: [{"id": "open", "name": "open_official_pages", "args": {
                        "metric": "收入", "urls": [current_url],
                    }}],
                    3: [{"id": "complete", "name": "complete_company_research", "args": {
                        "status": "search_exhausted",
                        "rationale": "当期官方页可读但没有该指标",
                        "metric_statuses": [{
                            "metric": "收入",
                            "status": "search_exhausted",
                            "rationale": "当期官方页可读但没有收入直接值",
                        }],
                    }}],
                }
                return SimpleNamespace(content="", tool_calls=calls[self.turn])

        def open_without_metric(_fact, *, extra_urls=None, open_audit=None, **_kwargs):
            open_audit.append({"url": extra_urls[0], "http_status": 200, "opened": True})
            return []

        with (
            patch("data_curation.workflow._company_configured_metrics", return_value=["收入"]),
            patch("data_curation.workflow._company_research_profile", return_value={
                "aliases": ["Example"], "official_hosts": ["example.com"], "seed_urls": [],
            }),
            patch("data_curation.workflow._build_supervisor_model", return_value=ExhaustedAfterOpenAgent()),
            patch("data_curation.workflow._public_web_search", return_value=([{
                "title": "Example 2026 results",
                "url": current_url,
                "snippet": "Official 2026 annual results",
                "provider": "test",
            }], "test")),
            patch("data_curation.workflow._votes_from_source_pages", side_effect=open_without_metric),
        ):
            result, _trace = _run_company_research_agent(
                {"run_id": "company-agent-current-open-exhausted"}, "Example", 2, "Example", []
            )
        self.assertEqual(result["status"], "search_exhausted")
        self.assertTrue(result["metric_coverage_complete"])
        self.assertEqual(result["metric_results"][0]["fresh_official_open_count"], 1)

    def test_scheduled_company_progress_skips_completed_company_on_resume(self) -> None:
        complete = {
            "company": "Example",
            "status": "verified_latest",
            "metric_coverage_complete": True,
            "metric_results": [{"metric": "收入", "status": "verified_latest"}],
            "search_count": 1,
            "opened_page_count": 1,
            "evidence_count": 1,
        }
        worker = Mock(return_value=(complete, []))
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.object(workflow, "RUNS_DIR", Path(temp_dir)),
            patch("crawl.ALL_COMPANY_CURRENT_RESULT_TARGETS", {"Example": (2, "Example")}),
            patch("data_curation.workflow._company_expected_metrics", return_value=["收入"]),
            patch("data_curation.workflow._run_company_research_agent", worker),
        ):
            state = {
                "run_id": "scheduled_progress_test",
                "online_ai": True,
                "search_verify_online": True,
                "candidates": [],
            }
            first = run_company_research_agents(state)
            second = run_company_research_agents(state)
            progress = json.loads(
                (Path(temp_dir) / "scheduled_progress_test_company_agent_progress.json").read_text(
                    encoding="utf-8"
                )
            )
        self.assertEqual(worker.call_count, 1)
        self.assertTrue(first["company_agent_summary"]["metric_coverage_complete"])
        self.assertTrue(second["company_agent_summary"]["metric_coverage_complete"])
        self.assertIn("Example", progress["companies"])

    def test_company_agents_run_smallest_metric_plan_first(self) -> None:
        observed: list[str] = []

        def expected(company, _facts):
            return ["收入"] if company == "Small" else ["收入", "EBITDA", "净利润"]

        def worker(_state, company, _row, _entity, _facts):
            observed.append(company)
            metrics = expected(company, [])
            return ({
                "company": company,
                "status": "verified_latest",
                "metric_coverage_complete": True,
                "metric_results": [
                    {"metric": metric, "status": "verified_latest"} for metric in metrics
                ],
            }, [])

        with (
            patch.dict(os.environ, {"CMHK_COMPANY_AGENT_WORKERS": "1"}),
            patch("crawl.ALL_COMPANY_CURRENT_RESULT_TARGETS", {
                "Big": (2, "Big"),
                "Small": (3, "Small"),
            }),
            patch("data_curation.workflow._company_expected_metrics", side_effect=expected),
            patch("data_curation.workflow._run_company_research_agent", side_effect=worker),
        ):
            result = run_company_research_agents({
                "run_id": "company_priority_test",
                "online_ai": True,
                "search_verify_online": True,
                "candidates": [],
            })
        self.assertEqual(observed, ["Small", "Big"])
        self.assertEqual(result["company_agent_summary"]["completed_metrics"], 4)

    def test_company_agent_downgrades_unsupported_not_disclosed_claim(self) -> None:
        seed_url = "https://example.com/current"

        class PrivateCompanyAgent:
            def __init__(self) -> None:
                self.turn = 0

            def bind_tools(self, _tools, **_kwargs):
                return self

            def invoke(self, _messages):
                self.turn += 1
                calls = {
                    1: [{"id": "inspect", "name": "inspect_company_evidence", "args": {}}],
                    2: [{"id": "search-network", "name": "search_latest_official", "args": {"metric": "网络覆盖"}}],
                    3: [{"id": "open-network", "name": "open_official_pages", "args": {
                        "metric": "网络覆盖", "urls": [seed_url],
                    }}],
                    4: [{"id": "search-income", "name": "search_latest_official", "args": {"metric": "收入"}}],
                    5: [{"id": "complete", "name": "complete_company_research", "args": {
                        "status": "completed",
                        "rationale": "官网可读，但定向搜索无收入直接披露值",
                        "metric_statuses": [
                            {"metric": "网络覆盖", "status": "verified_latest", "rationale": "当前官网可读"},
                            {"metric": "收入", "status": "not_disclosed", "rationale": "未找到直接披露值"},
                        ],
                    }}],
                }
                return SimpleNamespace(content="", tool_calls=calls[self.turn])

        def open_seed(_fact, *, extra_urls=None, open_audit=None, **_kwargs):
            open_audit.append({"url": extra_urls[0], "http_status": 200, "opened": True})
            return []

        with (
            patch("data_curation.workflow._company_configured_metrics", return_value=["网络覆盖", "收入"]),
            patch("data_curation.workflow._company_research_profile", return_value={
                "aliases": ["HGC"], "official_hosts": ["example.com"], "seed_urls": [seed_url],
            }),
            patch("data_curation.workflow._build_supervisor_model", return_value=PrivateCompanyAgent()),
            patch("data_curation.workflow._public_web_search", return_value=([], "test")),
            patch("data_curation.workflow._votes_from_source_pages", side_effect=open_seed),
        ):
            result, _trace = _run_company_research_agent(
                {"run_id": "company-agent-private"}, "HGC", 10, "HGC", []
            )
        self.assertEqual(result["status"], "search_exhausted")
        self.assertTrue(result["metric_coverage_complete"])
        self.assertEqual(
            {item["metric"]: item["status"] for item in result["metric_results"]},
            {"网络覆盖": "verified_latest", "收入": "search_exhausted"},
        )

    def test_supervisor_agent_can_search_and_promote_unplanned_gap(self) -> None:
        class ToolCallingSupervisor:
            def __init__(self) -> None:
                self.turn = 0

            def bind_tools(self, _tools):
                return self

            def invoke(self, _messages):
                self.turn += 1
                calls = {
                    1: [{"id": "inspect", "name": "inspect_evidence_gaps", "args": {"row_numbers": [50]}}],
                    2: [{
                        "id": "search",
                        "name": "search_and_open_official_evidence",
                        "args": {"row_number": 50, "company": "AWS", "metric": "收入"},
                    }],
                    3: [{
                        "id": "schedule",
                        "name": "schedule_targeted_recrawl",
                        "args": {"row_numbers": [50], "rationale": "搜索发现当期官方业绩原文"},
                    }],
                }
                return SimpleNamespace(content="", tool_calls=calls[self.turn])

        candidate = CandidateFact(
            id="aws-gap",
            company="AWS",
            metric="收入",
            row_ref="row_50",
            decision="rejected",
            reasons=["缺少可核验公开来源"],
        ).model_dump()
        with (
            patch("data_curation.workflow._build_supervisor_model", return_value=ToolCallingSupervisor()),
            patch(
                "data_curation.workflow._public_web_search",
                return_value=([
                    {
                        "title": "Amazon Q2 2026 results",
                        "url": "https://www.sec.gov/Archives/edgar/data/1018724/results.htm",
                        "snippet": "AWS segment revenue",
                        "provider": "test",
                    }
                ], "test"),
            ),
            patch("data_curation.workflow._votes_from_source_pages", return_value=[]),
            patch("data_curation.workflow._result_status", return_value="quality_rejected"),
        ):
            result = supervise_gap_actions(
                {
                    "run_id": "unit-test",
                    "online_ai": True,
                    "max_recrawl_rows": 14,
                    "max_recrawl_rounds": 1,
                    "recrawl_round": 0,
                    "recrawl_tasks": [],
                    "candidates": [candidate],
                    "gaps": [
                        {
                            "company": "AWS",
                            "metric": "收入",
                            "row_ref": "row_50",
                            "reason": "缺少可核验公开来源",
                            "candidate_ids": ["aws-gap"],
                        }
                    ],
                }
            )
        self.assertEqual(result["supervisor_decision"], "recrawl")
        self.assertEqual([item["row_number"] for item in result["recrawl_tasks"]], [50])
        tool_calls = [
            event.get("tool")
            for event in result["agent_trace"]
            if event.get("phase") == "tool_call"
        ]
        self.assertEqual(
            tool_calls,
            ["inspect_evidence_gaps", "search_and_open_official_evidence", "schedule_targeted_recrawl"],
        )

    @patch("data_curation.workflow._result_status", return_value="quality_rejected")
    def test_current_value_quality_gap_is_scheduled_for_recrawl(self, _status) -> None:
        result = plan_gaps(
            {
                "run_id": "unit-test",
                "allow_recrawl": True,
                "max_recrawl_rows": 14,
                "max_recrawl_rounds": 1,
                "recrawl_round": 0,
                "candidates": [
                    CandidateFact(
                        id="aws-revenue",
                        company="AWS",
                        metric="收入",
                        row_ref="row_50",
                        decision="rejected",
                        reasons=["缺少可核验公开来源"],
                    ).model_dump()
                ],
            }
        )
        self.assertEqual([item["row_number"] for item in result["recrawl_tasks"]], [50])

    @patch("data_curation.workflow._result_status", return_value="quality_rejected")
    def test_semantic_only_quality_gap_is_not_recrawled(self, _status) -> None:
        result = plan_gaps(
            {
                "run_id": "unit-test",
                "allow_recrawl": True,
                "max_recrawl_rows": 14,
                "max_recrawl_rounds": 1,
                "recrawl_round": 0,
                "candidates": [
                    CandidateFact(
                        id="aws-semantic",
                        company="AWS",
                        metric="收入",
                        row_ref="row_50",
                        decision="rejected",
                        reasons=["指标语义未通过"],
                    ).model_dump()
                ],
            }
        )
        self.assertEqual(result["recrawl_tasks"], [])

    def test_publish_blocks_incomplete_online_coverage(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "未完成全部主体×指标联网补充搜索"):
            publish_results(
                {
                    "search_verify_online": True,
                    "search_verify_online_limit": 80,
                    "search_verification": {
                        "online_search": True,
                        "online_checked": 80,
                        "online_required": 256,
                        "online_coverage_complete": False,
                    },
                    "candidates": [],
                }
            )

    def test_publish_blocks_unresolved_company_agents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "curation_data"
            runs_dir = data_dir / "runs"
            state = {
                "run_id": "blocked-company-run",
                "started_at": "2026-09-01T09:00:00+08:00",
                "search_verify_online": True,
                "search_verification": {"online_coverage_complete": True},
                "company_agent_summary": {
                    "required": True,
                    "expected": 41,
                    "completed": 41,
                    "coverage_complete": True,
                    "publish_ready": False,
                    "unresolved_companies": ["AWS"],
                },
                "company_agent_results": [{"company": "AWS", "status": "conflict"}],
                "candidates": [],
                "agent_trace": [],
            }
            with (
                patch.object(workflow, "DATA_DIR", data_dir),
                patch.object(workflow, "RUNS_DIR", runs_dir),
                self.assertRaisesRegex(RuntimeError, "尚有未解决主体.*AWS"),
            ):
                publish_results(state)

            summary = json.loads((runs_dir / "blocked-company-run.json").read_text(encoding="utf-8"))
            reports = json.loads(
                (runs_dir / "blocked-company-run_company_agent_results.json").read_text(encoding="utf-8")
            )
            trace = (runs_dir / "blocked-company-run_agent_trace.jsonl").read_text(encoding="utf-8")

        self.assertTrue(summary["extra"]["publication_blocked"])
        self.assertEqual(summary["extra"]["overall_status"], "partial")
        self.assertEqual(reports, [{"company": "AWS", "status": "conflict"}])
        self.assertIn("发布阻断", trace)

    def test_run_workflow_resumes_same_thread_from_checkpoint(self) -> None:
        graph = unittest.mock.Mock()
        graph.get_state.return_value = SimpleNamespace(
            values={"run_id": "scheduled-crawl", "summary": {}},
            next=("search_verify",),
        )
        graph.invoke.return_value = {
            "summary": {"run_id": "scheduled-crawl", "completed_at": "2026-08-27T09:00:00+08:00"}
        }
        graph.update_state.return_value = {
            "configurable": {"thread_id": "scheduled-crawl", "checkpoint_id": "updated"}
        }
        with patch("data_curation.workflow.build_graph", return_value=graph):
            result = run_workflow(
                run_id="scheduled-crawl",
                resume=True,
                search_verify_online=True,
                search_verify_online_limit=80,
            )

        config = {"configurable": {"thread_id": "scheduled-crawl"}}
        graph.get_state.assert_called_once_with(config)
        graph.update_state.assert_called_once_with(
            config,
            unittest.mock.ANY,
        )
        updated_controls = graph.update_state.call_args.args[1]
        self.assertTrue(updated_controls["search_verify_online"])
        self.assertEqual(updated_controls["search_verify_online_limit"], 80)
        graph.invoke.assert_called_once_with(
            None,
            config={
                "configurable": {
                    "thread_id": "scheduled-crawl",
                    "checkpoint_id": "updated",
                }
            },
        )
        self.assertEqual(result["run_id"], "scheduled-crawl")

    def test_run_workflow_resume_without_checkpoint_starts_once_with_same_id(self) -> None:
        graph = unittest.mock.Mock()
        graph.get_state.return_value = SimpleNamespace(values={}, next=())
        graph.invoke.return_value = {
            "summary": {"run_id": "scheduled-fresh", "completed_at": "2026-08-27T09:00:00+08:00"}
        }
        with patch("data_curation.workflow.build_graph", return_value=graph):
            result = run_workflow(run_id="scheduled-fresh", resume=True)

        args, kwargs = graph.invoke.call_args
        self.assertEqual(args[0]["run_id"], "scheduled-fresh")
        self.assertEqual(kwargs["config"]["configurable"]["thread_id"], "scheduled-fresh")
        self.assertEqual(result["run_id"], "scheduled-fresh")

    def test_metric_focused_evidence_reads_beyond_page_header(self) -> None:
        text = "Home About Products " + ("navigation " * 300) + (
            "The Board declared an interim dividend of HK$0.145 per share."
        )
        evidence = _focused_evidence(text, "派息", "SmarTone")
        self.assertIn("HK$0.145", evidence)
        self.assertLess(len(evidence), len(text))

    def test_metric_relevance_beats_company_only_navigation(self) -> None:
        navigation = "SmarTone investor relations home navigation"
        disclosure = "The Board declared an interim dividend of HK$0.145 per share."
        self.assertGreater(
            _evidence_relevance(disclosure, "派息", "SmarTone"),
            _evidence_relevance(navigation, "派息", "SmarTone"),
        )

    def test_focused_evidence_prioritizes_numeric_disclosure_over_early_definition(self) -> None:
        text = (
            "Customer base means all registered accounts. " * 80
            + "HKT IN NUMBERS MOBILE Post-Paid Customer Base 3.46 M, "
            + "5G Customer Base 1.75 M."
        )
        evidence = _focused_evidence(text, "客户数/用户数", "HKT")
        self.assertIn("3.46 M", evidence)

    def test_official_source_cannot_cross_company_boundary(self) -> None:
        china_unicom_report = {
            "url": "https://www.chinaunicom.com.hk/en/ir/reports/annual-report.pdf"
        }
        self.assertTrue(_record_allowed_for_company(china_unicom_report, "中国联通"))
        self.assertFalse(_record_allowed_for_company(china_unicom_report, "中国电信"))
        self.assertFalse(_record_allowed_for_company(china_unicom_report, "中国移动"))

    def test_hkt_brand_domains_are_not_interchangeable(self) -> None:
        hkt_enterprise = {"url": "https://www.hkt-enterprise.com/en/open-api"}
        csl_plan = {"url": "https://www.hkcsl.com/en/mobile-plans"}
        one_o_one_o = {"url": "https://www.1010.com.hk/en/plans"}
        self.assertTrue(_record_allowed_for_company(hkt_enterprise, "HKT"))
        self.assertFalse(_record_allowed_for_company(hkt_enterprise, "csl"))
        self.assertFalse(_record_allowed_for_company(hkt_enterprise, "1O1O"))
        self.assertTrue(_record_allowed_for_company(csl_plan, "csl"))
        self.assertFalse(_record_allowed_for_company(csl_plan, "HKT"))
        self.assertTrue(_record_allowed_for_company(one_o_one_o, "1O1O"))
        self.assertFalse(_record_allowed_for_company(one_o_one_o, "csl"))

    def test_cloud_official_domains_are_bound_to_their_vendor(self) -> None:
        microsoft_report = {"url": "https://www.microsoft.com/investor/reports/ar25/index.html"}
        self.assertTrue(_record_allowed_for_company(microsoft_report, "Microsoft Azure"))
        self.assertFalse(_record_allowed_for_company(microsoft_report, "AWS"))

    def test_cloud_rows_define_financial_report_fields(self) -> None:
        self.assertIn("AWS分部收入", row_fields(52))
        self.assertIn("Azure及其他云服务增速", row_fields(53))
        self.assertIn("Google Cloud经营利润", row_fields(54))
        self.assertIn("调整后EBITA", row_fields(55))
        self.assertIn("云与AI业务披露", row_fields(56))
        self.assertIn("研发投入", row_fields(57))
        self.assertIn("Cloud Services收入", row_fields(58))
        extracted, missing = find_field_snippets(
            53,
            "Intelligent Cloud revenue was $105 billion and Azure and other cloud services grew 34%.",
        )
        self.assertIn("Intelligent Cloud收入", extracted)
        self.assertIn("Azure及其他云服务增速", extracted)
        self.assertNotIn("Intelligent Cloud收入", missing)

    def test_smartone_profit_after_tax_maps_to_net_profit(self) -> None:
        extracted, missing = find_field_snippets(
            8,
            "Financial Highlights HK$ million 1H'25 1H'26. "
            "Reported Profit after tax 257 278 +8.4%.",
        )
        self.assertIn("净利润", extracted)
        self.assertNotIn("净利润", missing)

    def test_third_party_metric_window_must_name_target_company(self) -> None:
        unicom_fact = "中国联通已在超过330个城市部署5G-A。"
        self.assertTrue(_evidence_mentions_company(unicom_fact, "中国联通"))
        self.assertFalse(_evidence_mentions_company(unicom_fact, "中国电信"))

    def test_public_long_number_is_not_redacted_as_phone(self) -> None:
        self.assertEqual(redact_sensitive("GDP 407106629428.342美元"), "GDP 407106629428.342美元")
        self.assertIn("[REDACTED_PHONE_OR_ID]", redact_sensitive("电话 +852 2123 4567"))

    def test_evidence_tasks_have_stable_fingerprints(self) -> None:
        first = build_tasks(limit=2)
        second = build_tasks(limit=2)
        self.assertEqual(len(first), 2)
        self.assertEqual(
            [EvidenceTask.model_validate(item).evidence_hash for item in first],
            [EvidenceTask.model_validate(item).evidence_hash for item in second],
        )
        self.assertTrue(all(item["evidence_hash"] for item in first))

    def test_parallel_ai_batches_preserve_candidate_order(self) -> None:
        tasks = []
        for index in range(4):
            task = {
                "id": f"parallel-{index}",
                "company": "HKT",
                "metric": "漫游",
                "current_value": "",
                "raw_text": f"HKT roaming evidence {index}",
                "sources": ["https://www.hkt.com/en/about-hkt/investor-relations/fast-facts/"],
                "row_ref": "row_4",
                "evidence_hash": f"hash-{index}",
                "source_score": 1.0,
                "source_tier": "official",
            }
            tasks.append(EvidenceTask.model_validate(task).model_dump())

        def fake_call_deepseek(batch):
            index = int(batch[0]["id"].rsplit("-", 1)[1])
            time.sleep(0.03 * (4 - index))
            return [
                {
                    "id": batch[0]["id"],
                    "status": "unavailable",
                    "value": "未提取到有效数据",
                    "basis": f"batch {index}",
                    "note": "",
                    "entity_supported": True,
                    "metric_supported": False,
                    "value_supported": False,
                    "confidence": 0.1,
                }
            ]

        with patch("data_curation.workflow.call_deepseek", side_effect=fake_call_deepseek):
            result = extract_facts(
                {
                    "run_id": "unit-test",
                    "tasks": tasks,
                    "existing_items": {},
                    "batch_size": 1,
                    "ai_workers": 4,
                    "online_ai": True,
                }
            )

        self.assertEqual(
            [item["id"] for item in result["candidates"]],
            ["parallel-0", "parallel-1", "parallel-2", "parallel-3"],
        )
        self.assertEqual(result["summary"]["onlineBatches"], 4)

    def test_timed_out_ai_batch_is_split_and_retried_before_offline_fallback(self) -> None:
        tasks = []
        for index in range(4):
            tasks.append(
                EvidenceTask.model_validate(
                    {
                        "id": f"retry-{index}",
                        "company": "HKT",
                        "metric": "漫游",
                        "current_value": "",
                        "raw_text": f"HKT roaming evidence {index}",
                        "sources": ["https://www.hkt.com/en/about-hkt/investor-relations/fast-facts/"],
                        "row_ref": "row_4",
                        "evidence_hash": f"retry-hash-{index}",
                        "source_score": 1.0,
                        "source_tier": "official",
                    }
                ).model_dump()
            )

        calls: list[list[str]] = []

        def fake_call_deepseek(batch):
            calls.append([item["id"] for item in batch])
            if len(calls) == 1:
                raise TimeoutError("timed out")
            return [
                {
                    "id": item["id"],
                    "status": "unavailable",
                    "value": "未提取到有效数据",
                    "basis": "split retry",
                    "note": "",
                    "entity_supported": True,
                    "metric_supported": False,
                    "value_supported": False,
                    "confidence": 0.1,
                }
                for item in batch
            ]

        with patch("data_curation.workflow.call_deepseek", side_effect=fake_call_deepseek):
            result = extract_facts(
                {
                    "run_id": "unit-test",
                    "tasks": tasks,
                    "existing_items": {},
                    "batch_size": 4,
                    "ai_workers": 1,
                    "online_ai": True,
                }
            )

        self.assertEqual(calls, [["retry-0", "retry-1", "retry-2", "retry-3"], ["retry-0", "retry-1"], ["retry-2", "retry-3"]])
        self.assertEqual([item["id"] for item in result["candidates"]], ["retry-0", "retry-1", "retry-2", "retry-3"])
        self.assertEqual(result["summary"]["onlineBatches"], 1)
        self.assertEqual(result["summary"]["fallbackBatches"], 0)
        tool_results = [
            item
            for item in result["agent_trace"]
            if item.get("phase") == "tool_result" and item.get("tool") == "DeepSeek chat/completions"
        ]
        self.assertTrue(tool_results[0]["result"]["timeout_split_retry"])
        self.assertEqual(tool_results[0]["result"]["retry_chunk_sizes"], [2, 2])

    def test_hkt_customer_exact_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "hkt-customer",
                "company": "HKT",
                "metric": "客户数/用户数",
                "raw_text": "Post-Paid Customer Base 3.46 M 5G Customer Base 1.75 M",
            }
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["value"], "后付费客户346万；5G客户175万")

    def test_hkt_5g_customer_exact_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "hkt-5g",
                "company": "HKT",
                "metric": "5G用户数",
                "raw_text": "5G Customer Base 1.75 M",
            }
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["value"], "5G客户175万")

    def test_hkt_product_and_value_added_services_are_brand_specific(self) -> None:
        product = deterministic_extract_task(
            {
                "id": "hkt-product",
                "company": "HKT",
                "metric": "产品规格",
                "raw_text": "Choose from 1G to 10G. 10,000M Fibre-to-the-Home.",
            }
        )
        services = deterministic_extract_task(
            {
                "id": "hkt-services",
                "company": "HKT",
                "metric": "增值服务",
                "raw_text": (
                    "Home Wi-Fi Google Workspace with Gemini NETVIGATOR SHiELD "
                    "Surfshark ONE Microsoft 365 Now TV"
                ),
            }
        )
        self.assertIn("1G至10G", product["value"])
        self.assertIn("Google Workspace with Gemini", services["value"])

    def test_hkt_home_plan_and_tariff_require_official_price_details(self) -> None:
        home_plan = deterministic_extract_task(
            {
                "id": "hkt-home-plan",
                "company": "HKT",
                "metric": "家宽套餐",
                "raw_text": "NETVIGATOR Home Broadband. Choose from 1G to 10G to suit your needs.",
            }
        )
        tariff = deterministic_extract_task(
            {
                "id": "hkt-tariff",
                "company": "HKT",
                "metric": "资费",
                "raw_text": (
                    "1000M Fibre-to-the-Home Free Home Wi-Fi Service From HK$ 108 "
                    "/month 36-month commitment. 5G Home Internet From HK$ 168 "
                    "/month 36-month commitment."
                ),
            }
        )
        self.assertIn("1G至10G", home_plan["value"])
        self.assertIn("108港元", tariff["value"])
        self.assertIn("168港元", tariff["value"])
        self.assertIn("36个月", tariff["value"])

    def test_hkt_tariff_supports_official_chinese_page(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "hkt-tariff-zh",
                "company": "HKT",
                "metric": "资费",
                "raw_text": (
                    "1000M 光纖入屋寬頻 送家居Wi-Fi服務 低至 HK$ 108 /月 "
                    "36 個月承諾期。5G 私家寬頻服務 低至 HK$ 168 /月 "
                    "36 個月承諾期。"
                ),
            }
        )
        self.assertIn("108港元", result["value"])
        self.assertIn("168港元", result["value"])

    def test_hkt_official_page_supports_product_contract_and_promotion(self) -> None:
        raw_text = (
            "網上行寬頻新標準，提供1G 至10G的選擇。10,000M 光纖入屋寬頻。"
            "1000M 光纖入屋寬頻 低至 HK$ 108 /月 36 個月承諾期。"
            "2500M 超級寬頻 升級低至 HK$ 58 /月 36 個月承諾期。"
            "5G 私家寬頻服務 低至 HK$ 168 /月 36 個月承諾期。"
        )
        product = deterministic_extract_task(
            {"id": "hkt-product-zh", "company": "HKT", "metric": "产品规格", "raw_text": raw_text}
        )
        five_g = deterministic_extract_task(
            {"id": "hkt-5g-plan", "company": "HKT", "metric": "5G套餐", "raw_text": raw_text}
        )
        contract = deterministic_extract_task(
            {"id": "hkt-contract", "company": "HKT", "metric": "合约期", "raw_text": raw_text}
        )
        promotion = deterministic_extract_task(
            {"id": "hkt-promotion", "company": "HKT", "metric": "促销折扣", "raw_text": raw_text}
        )
        self.assertIn("1G至10G", product["value"])
        self.assertIn("168港元", five_g["value"])
        self.assertIn("36个月", contract["value"])
        self.assertIn("58港元", promotion["value"])

    def test_csl_tariff_and_roaming_extractors_require_official_details(self) -> None:
        tariff = deterministic_extract_task(
            {
                "id": "csl-tariff",
                "company": "csl",
                "metric": "资费",
                "raw_text": (
                    "local data entitlement 60GB/100GB/150GB/250GB/500GB. "
                    "A monthly administrative fee of HKD 18 also applies."
                ),
            }
        )
        roaming = deterministic_extract_task(
            {
                "id": "csl-roaming",
                "company": "csl",
                "metric": "漫游",
                "raw_text": (
                    "Golden Roaming Data Roaming Pass First In-Flight Data Roaming Pass "
                    "First Cruise Data Roaming Pass"
                ),
            }
        )
        self.assertIn("60GB/100GB/150GB/250GB/500GB", tariff["value"])
        self.assertIn("18港元", tariff["value"])
        self.assertIn("csl", tariff["value"])
        self.assertIn("Golden Roaming", roaming["value"])

    def test_csl_plan_contract_and_promotion_exact_extractors(self) -> None:
        raw_text = (
            "Monthly Plan Fee $348 Local data usage 100GB. "
            "Monthly Plan Fee $398 Local data usage 150GB. "
            "The offer is only valid for customers who sign a commitment period "
            "of 24 or 36 months. Enjoy welcome offers worth over $2,000!"
        )
        plan = deterministic_extract_task(
            {"id": "csl-plan", "company": "csl", "metric": "5G套餐", "raw_text": raw_text}
        )
        contract = deterministic_extract_task(
            {"id": "csl-contract", "company": "csl", "metric": "合约期", "raw_text": raw_text}
        )
        promotion = deterministic_extract_task(
            {"id": "csl-promotion", "company": "csl", "metric": "促销折扣", "raw_text": raw_text}
        )
        self.assertIn("348港元100GB", plan["value"])
        self.assertIn("24个月或36个月", contract["value"])
        self.assertIn("2,000港元", promotion["value"])

    def test_1010_enterprise_5g_and_open_api_extractors(self) -> None:
        five_g = deterministic_extract_task(
            {
                "id": "1010-5ga",
                "company": "1O1O",
                "metric": "5G-A",
                "raw_text": (
                    "Enterprise 5G/5.5G & Wireless Solutions 5G Private Network "
                    "Managed 5G Router Solutions"
                ),
            }
        )
        cooperation = deterministic_extract_task(
            {
                "id": "1010-open-api",
                "company": "1O1O",
                "metric": "战略合作",
                "raw_text": (
                    "22 SEP 2025 HKT Enterprise Solutions: Open APIs Powering "
                    "Hong Kong’s Digital Innovation and Enterprise Efficiency"
                ),
            }
        )
        self.assertIn("5G/5.5G", five_g["value"])
        self.assertIn("Open API", cooperation["value"])
        self.assertIn("1O1O", cooperation["value"])

    def test_1010_open_api_is_a_supported_product_spec(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "1010-open-api-product",
                "company": "1O1O",
                "metric": "产品规格",
                "raw_text": (
                    "HKT Enterprise Solutions now provides Open API services on the "
                    "1O1O 5G mobile network and helps enterprises modernise "
                    "mobile-number verification."
                ),
            }
        )
        self.assertIn("1O1O 5G", result["value"])
        self.assertIn("号码验证", result["value"])

    def test_1010_5g_plan_variants_are_structured(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "1010-plan",
                "company": "1O1O",
                "metric": "5G套餐",
                "raw_text": (
                    "Global 5G Prestige Service Asia Pacific 5G Prestige Service "
                    "China-HK-Macau 5G Prestige Service"
                ),
            }
        )
        self.assertIn("全球、亚太及中港澳", result["value"])

    def test_3hk_promotion_exact_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "3hk-promotion",
                "company": "3HK",
                "metric": "促销折扣",
                "raw_text": (
                    "$188 /month Local Data 60GB. Earn MoneyBack points worth $400 "
                    "upon successful subscription via referral and redeem cash discounts."
                ),
            }
        )
        self.assertIn("188港元", result["value"])
        self.assertIn("400港元", result["value"])

    def test_smartone_5g_penetration_exact_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "smartone-5g",
                "company": "SmarTone",
                "metric": "5G用户数",
                "raw_text": "Maintaining 5G penetration at about 40%, and 5G ARPU doubled 4G.",
            }
        )
        self.assertEqual(result["value"], "5G渗透率约40%（公司未披露绝对用户数）")

    def test_smartone_home_broadband_exact_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "smartone-home",
                "company": "SmarTone",
                "metric": "家宽",
                "raw_text": (
                    "SmarTone Home 5G Broadband Online Exclusive Free Upgrade to "
                    "Wi-Fi 7 12-month Flexible Short Contract"
                ),
            }
        )
        self.assertIn("Wi-Fi 7", result["value"])
        self.assertIn("12个月", result["value"])

    def test_mainland_dict_extractors_use_audited_annual_report_figures(self) -> None:
        telecom = deterministic_extract_task(
            {
                "id": "telecom-dict",
                "company": "中国电信",
                "metric": "DICT",
                "raw_text": (
                    "Industrial Digitalisation service revenues "
                    "147,307 146,588 0.5%"
                ),
            }
        )
        unicom = deterministic_extract_task(
            {
                "id": "unicom-dict",
                "company": "中国联通",
                "metric": "DICT",
                "raw_text": (
                    "Revenue contribution from strategic emerging industries reached "
                    "over 86%. The computing power business revenue ratio reached over "
                    "15%. AI revenue grew by over 140% year-on-year."
                ),
            }
        )
        self.assertIn("1473.07亿元", telecom["value"])
        self.assertIn("0.5%", telecom["value"])
        self.assertIn("超过86%", unicom["value"])
        self.assertIn("超过140%", unicom["value"])

    def test_official_policy_title_extractors_are_not_navigation_fragments(self) -> None:
        coverage = deterministic_extract_task(
            {
                "id": "ofca-coverage",
                "company": "通信监管机构",
                "metric": "覆盖义务",
                "raw_text": (
                    "Subsidy Scheme to Extend Fibre-based Networks to Villages in "
                    "Remote Areas. Subsidy Scheme to Extend 5G Coverage in Rural and "
                    "Remote Areas."
                ),
            }
        )
        policy = deterministic_extract_task(
            {
                "id": "gov-policy",
                "company": "政治新闻",
                "metric": "重大政策/声明",
                "raw_text": (
                    "Announcement on the Implementation of Electronic Border "
                    "Management Area Permit Policy"
                ),
            }
        )
        self.assertIn("5G覆盖资助计划", coverage["value"])
        self.assertIn("通行证电子化政策", policy["value"])

    def test_kt_enterprise_ict_product_list_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "kt-ict",
                "company": "KT",
                "metric": "企业ICT",
                "raw_text": "Enterprise LTE Service IoTMakers ucloud biz AMI BEMS Fintech",
            }
        )
        self.assertIn("Enterprise LTE Service", result["value"])
        self.assertIn("ucloud biz", result["value"])

    def test_kt_form_20f_enterprise_ict_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "kt-ict-20f",
                "company": "KT",
                "metric": "企业ICT",
                "raw_text": (
                    "We offer a wide range of KT AX platform services for our "
                    "corporate customers that provide customized and integrated "
                    "digital transformation services. Information Data Center "
                    "and Cloud Services. We operate Internet data centers and "
                    "cloud services, including servers, storage and leased lines."
                ),
            }
        )
        self.assertEqual(result["status"], "ok")
        self.assertIn("数字化转型", result["value"])

    def test_jio_capex_direction_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "jio-capex",
                "company": "Jio",
                "metric": "Capex方向",
                "raw_text": (
                    "Jio - Expanding 5G and broadband adoption across mobility, "
                    "homes and enterprises. AirFiber subscribers crossed 5.6mn. "
                    "Deployment of Private 5G for secure enterprise connectivity."
                ),
            }
        )
        self.assertEqual(result["status"], "ok")
        self.assertIn("AirFiber", result["value"])

    def test_china_mobile_dict_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "cm-dict",
                "company": "中国移动",
                "metric": "DICT",
                "raw_text": (
                    "AI services include data algorithms, embodied intelligence, "
                    "digital intelligence culture, digital intelligence e-commerce "
                    "and industry digital intelligence services."
                ),
            }
        )
        self.assertEqual(result["status"], "ok")
        self.assertIn("行业数智服务", result["value"])

    def test_tmobile_parent_report_fwa_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "tmobile-fwa",
                "company": "T-Mobile US",
                "metric": "FWA",
                "raw_text": (
                    "T-Mobile US is leveraging its leading position in respect "
                    "of mid-band mobile spectrum to offer customers fixed "
                    "wireless broadband access via FWA."
                ),
            }
        )
        self.assertEqual(result["status"], "ok")
        self.assertIn("固定无线宽带", result["value"])

    def test_tmobile_5g_broadband_net_additions_support_fwa(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "tmobile-fwa-customers",
                "company": "T-Mobile US",
                "metric": "FWA",
                "raw_text": (
                    "5G broadband (formerly High Speed Internet) net customer "
                    "additions included in postpaid other net customer additions "
                    "were 1.7 million and 1.5 million in 2025 and 2024, respectively."
                ),
            }
        )
        self.assertEqual(result["status"], "ok")
        self.assertIn("1.7百万", result["value"])

    def test_operator_network_api_venture_extractors(self) -> None:
        text = (
            "Today, some of the world’s largest telecom operators, including "
            "AT&T, Deutsche Telekom, Orange, Telefonica, Telstra, T-Mobile, "
            "Verizon and Vodafone, together with Ericsson are announcing a new "
            "venture to combine and sell network Application Programming "
            "Interfaces (APIs) on a global scale to spur innovation in digital "
            "services. Network APIs are the way to easily access, use and pay "
            "for network capabilities."
        )
        att = deterministic_extract_task(
            {
                "id": "att-network-api",
                "company": "AT&T",
                "metric": "网络API",
                "raw_text": text,
            }
        )
        tmobile = deterministic_extract_task(
            {
                "id": "tmobile-network-api",
                "company": "T-Mobile US",
                "metric": "网络API",
                "raw_text": text,
            }
        )
        self.assertEqual(att["status"], "ok")
        self.assertEqual(tmobile["status"], "ok")
        self.assertIn("网络API", att["value"])

    def test_tmobile_ai_ran_prnewswire_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "tmobile-ai-ran",
                "company": "T-Mobile US",
                "metric": "AI网络",
                "raw_text": (
                    "Ericsson and T-Mobile have moved AI-native Scheduler with "
                    "Link Adaptation into large-scale commercial trials on live "
                    "5G Advanced network traffic. During trials with T-Mobile, "
                    "the AI-native Scheduler with Link Adaptation feature achieved "
                    "close to 10 percent increase in spectral efficiency and up "
                    "to 15 percent boost in downlink throughput."
                ),
            }
        )
        self.assertEqual(result["status"], "ok")
        self.assertIn("15%", result["value"])

    def test_att_investor_open_ran_and_fwa_extractors(self) -> None:
        open_ran = deterministic_extract_task(
            {
                "id": "att-open-ran",
                "company": "AT&T",
                "metric": "Open RAN",
                "raw_text": (
                    "AT&T Inc Analyst & Investor Day. By the end of 2026, "
                    "we expect that 70% of our 5G traffic will flow across "
                    "open hardware. This transition to a more open radio "
                    "architecture will invite new technology partners."
                ),
            }
        )
        fwa = deterministic_extract_task(
            {
                "id": "att-fwa",
                "company": "AT&T",
                "metric": "FWA",
                "raw_text": (
                    "During the first quarter of 2026, we reported a net gain "
                    "of 584,000 total internet connections, with 292,000 fiber "
                    "net adds and 292,000 fixed wireless net adds. AIA revenue "
                    "increases exceeded 100 percent."
                ),
            }
        )
        self.assertEqual(open_ran["status"], "ok")
        self.assertIn("70%", open_ran["value"])
        self.assertEqual(fwa["status"], "ok")
        self.assertIn("29.2万", fwa["value"])

    def test_parent_annual_report_can_support_tmobile(self) -> None:
        owners = _official_domain_owners(
            "https://report.telekom.com/annual-report-2025/management-report/"
            "development-of-business-in-the-operating-segments/united-states.html"
        )
        self.assertEqual(owners, {"T-Mobile US"})

    def test_deutsche_telekom_group_report_does_not_support_tmobile(self) -> None:
        owners = _official_domain_owners(
            "https://report.telekom.com/annual-report-2025/management-report/"
            "group-strategy/investments.html"
        )
        self.assertEqual(owners, {"Deutsche Telekom"})

    def test_hutchison_customer_exact_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "hutch-customer",
                "company": "Hutchison",
                "metric": "客户数/用户数",
                "raw_text": (
                    "Number of postpaid customers (‘000) 1,289 "
                    "Number of prepaid customers (‘000) 6,843 "
                    "Total customers (‘000) 8,132"
                ),
            }
        )
        self.assertIsNotNone(result)
        self.assertIn("客户总数813.2万", result["value"])

    def test_hutchison_5g_penetration_uses_final_rate(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "hutch-5g",
                "company": "Hutchison",
                "metric": "5G用户数",
                "raw_text": "The 5G penetration rate rose 8% points to 62% compared to 2024.",
            }
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["value"], "5G渗透率62%")

    def test_hutchison_arpu_table_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "hutch-arpu",
                "company": "Hutchison",
                "metric": "ARPU",
                "raw_text": (
                    "Postpaid gross ARPU (HK$) 187 190 –2% "
                    "Postpaid net ARPU (HK$) 176 175 +1%"
                ),
            }
        )
        self.assertIsNotNone(result)
        self.assertIn("毛ARPU每月187港元", result["value"])
        self.assertIn("净ARPU每月176港元", result["value"])

    def test_hutchison_official_brand_privilege_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "hutch-promotion",
                "company": "Hutchison",
                "metric": "促销折扣",
                "raw_text": (
                    "Experience '3 for You' Brand Value with Backup Phone Service "
                    "and 100+ Global Privileges"
                ),
            }
        )
        self.assertIsNotNone(result)
        self.assertIn("100多项全球礼遇", result["value"])

    def test_hkbn_governance_exact_extractors(self) -> None:
        raw_text = (
            "the Board has resolved to declare a final dividend of 18.9 cents per share. "
            "Subject to the approval by the Shareholders at the 2025 annual general meeting "
            "of the Company, the proposed final dividend is expected to be paid in cash on "
            "or around Tuesday, 6 January 2026. "
            "from 7 May 2025 the China Mobile Group became connected persons. "
            "An announcement was made by the Company on 30 October 2025 in respect "
            "of the Partially-exempt CCTs. "
            "all applicable ratios were less than 5%"
        )
        board = deterministic_extract_task(
            {"id": "hkbn-board", "company": "HKBN", "metric": "董事会", "raw_text": raw_text}
        )
        agm = deterministic_extract_task(
            {"id": "hkbn-agm", "company": "HKBN", "metric": "股东大会", "raw_text": raw_text}
        )
        connected = deterministic_extract_task(
            {
                "id": "hkbn-cct",
                "company": "HKBN",
                "metric": "持续性关联交易",
                "raw_text": raw_text,
            }
        )
        self.assertIn("18.9港仙", board["value"])
        self.assertIn("2026年1月6日", agm["value"])
        self.assertIn("低于5%", connected["value"])

    def test_brand_market_reaction_is_explicitly_not_applicable(self) -> None:
        result = deterministic_extract_task(
            {"id": "csl-market", "company": "csl", "metric": "市场反应", "raw_text": ""}
        )
        self.assertEqual(result["value"], "不适用（品牌非独立上市主体）")

    def test_hkbn_gearing_exact_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "hkbn-gearing",
                "company": "HKBN",
                "metric": "资产负债率",
                "raw_text": (
                    "The Group’s gearing ratio, which was expressed as a ratio of the gross debt "
                    "over total equity, was 5.0x as at 31 August 2025."
                ),
            }
        )
        self.assertIsNotNone(result)
        self.assertIn("5.0x", result["value"])

    def test_hgc_data_center_action_requires_specific_event(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "hgc-dci",
                "company": "HGC",
                "metric": "数据中心",
                "raw_text": "06 May 2025 HGC Expands the Data Center Interconnect to Malaysia",
            }
        )
        self.assertIsNotNone(result)
        self.assertIn("马来西亚", result["value"])

    def test_china_mobile_verified_capex_and_computing_metrics(self) -> None:
        capex = deterministic_extract_task(
            {"id": "cm-capex", "company": "中国移动", "metric": "资本开支", "raw_text": ""}
        )
        computing = deterministic_extract_task(
            {"id": "cm-computing", "company": "中国移动", "metric": "算力网络", "raw_text": ""}
        )
        ai = deterministic_extract_task(
            {"id": "cm-ai", "company": "中国移动", "metric": "AI", "raw_text": ""}
        )
        self.assertIsNotNone(capex)
        self.assertIn("1366亿元", capex["value"])
        self.assertEqual(computing["value"], "算力网络投资同比增长62.4%")
        self.assertIn("19.8%", ai["value"])

    def test_china_telecom_5g_a_exact_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "ct-5ga",
                "company": "中国电信",
                "metric": "5G-A",
                "raw_text": (
                    "deployed over 110,000 5G-A carrier aggregation base stations "
                    "and over 650,000 RedCap base stations in more than 300 cities."
                ),
            }
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["value"], "部署超过110,000个5G-A载波聚合基站，覆盖超过300个城市")

    def test_china_unicom_computing_ai_and_5g_a_extractors(self) -> None:
        computing = deterministic_extract_task(
            {
                "id": "cu-computing",
                "company": "中国联通",
                "metric": "算力网络",
                "raw_text": (
                    "The scale of intelligent computing reached 45 EFLOPS, "
                    "with backbone cloud pools covering 252 cities. "
                    "adding more than 9,000 kilometres to achieve the interconnection "
                    "of computing power hub nodes."
                ),
            }
        )
        ai = deterministic_extract_task(
            {
                "id": "cu-ai",
                "company": "中国联通",
                "metric": "AI",
                "raw_text": (
                    "AI revenue4 grew by over 140% year-on-year. "
                    "cloud-AI products served over 300 million users with revenue "
                    "increasing by more than 11% year-on-year."
                ),
            }
        )
        five_g_a = deterministic_extract_task(
            {
                "id": "cu-5ga",
                "company": "中国联通",
                "metric": "5G-A",
                "raw_text": "5G-A base stations were deployed in more than 330 cities.",
            }
        )
        self.assertIn("45 EFLOPS", computing["value"])
        self.assertIn("9,000公里", computing["value"])
        self.assertIn("140%", ai["value"])
        self.assertEqual(five_g_a["value"], "5G-A基站已部署至超过330个城市")

    def test_mainland_official_tasks_do_not_include_other_operator_fact(self) -> None:
        tasks = {
            (item["company"], item["metric"]): item
            for item in build_tasks()
            if item["company"] in {"中国移动", "中国电信", "中国联通"} and item["metric"] == "5G-A"
        }
        telecom = tasks[("中国电信", "5G-A")]
        self.assertNotIn("中国联通2025年报", telecom["raw_text"])
        self.assertFalse(any("chinaunicom.com.hk" in url for url in telecom["sources"]))

    def test_supervisor_has_deterministic_fallback(self) -> None:
        result = supervise_gap_actions(
            {
                "run_id": "unit-test",
                "online_ai": False,
                "max_recrawl_rows": 1,
                "max_recrawl_rounds": 1,
                "recrawl_round": 0,
                "recrawl_tasks": [
                    {
                        "row_ref": "row_2",
                        "row_number": 2,
                        "reason": "关键指标缺口",
                        "priority": 100,
                        "attempts": 0,
                    },
                    {
                        "row_ref": "row_5",
                        "row_number": 5,
                        "reason": "普通指标缺口",
                        "priority": 80,
                        "attempts": 0,
                    },
                ],
                "gaps": [
                    {
                        "company": "HKT",
                        "metric": "派息",
                        "row_ref": "row_2",
                        "reason": "数值或事实依据不足",
                        "candidate_ids": ["a"],
                    }
                ],
            }
        )
        self.assertEqual(result["supervisor_decision"], "recrawl")
        self.assertEqual([item["row_number"] for item in result["recrawl_tasks"]], [2])
        self.assertEqual(result["agent_trace"][-1]["phase"], "decision")

    def test_graph_contains_tool_supervisor(self) -> None:
        graph = build_graph().get_graph()
        self.assertIn("supervisor", graph.nodes)
        self.assertIn("search_verify", graph.nodes)
        self.assertIn("company_research", graph.nodes)
        self.assertIn(("resolve", "search_verify"), {(edge.source, edge.target) for edge in graph.edges})
        self.assertIn(("search_verify", "plan_gaps"), {(edge.source, edge.target) for edge in graph.edges})
        self.assertIn(("plan_gaps", "company_research"), {(edge.source, edge.target) for edge in graph.edges})
        self.assertIn(("company_research", "supervisor"), {(edge.source, edge.target) for edge in graph.edges})

    def test_lead_agent_dispatches_every_company_even_without_candidates(self) -> None:
        def fake_worker(_state, company, row_number, row_entity, facts):
            return ({
                "company": company,
                "group": "test",
                "row_number": row_number,
                "row_entity": row_entity,
                "status": "search_exhausted",
                "search_count": 1,
                "opened_page_count": 0,
                "evidence_count": 0,
                "facts_seen": len(facts),
            }, [])

        with patch("data_curation.workflow._run_company_research_agent", side_effect=fake_worker):
            result = run_company_research_agents({
                "run_id": "company-fanout",
                "online_ai": True,
                "search_verify_online": True,
                "candidates": [],
            })
        self.assertEqual(result["company_agent_summary"]["expected"], 41)
        self.assertEqual(result["company_agent_summary"]["completed"], 41)
        self.assertTrue(result["company_agent_summary"]["coverage_complete"])
        self.assertFalse(result["company_agent_summary"]["publish_ready"])
        self.assertGreater(result["company_agent_summary"]["expected_metrics"], 0)
        self.assertFalse(result["company_agent_summary"]["metric_coverage_complete"])
        self.assertEqual(len({item["company"] for item in result["company_agent_results"]}), 41)
        self.assertTrue(all(item["facts_seen"] == 0 for item in result["company_agent_results"]))

    def test_search_verifier_majority_corrects_candidate_value(self) -> None:
        result = search_verify_facts(
            {
                "run_id": "unit-test",
                "search_verify_workers": 2,
                "tasks": [
                    {
                        "id": "fact-a",
                        "company": "中国移动",
                        "metric": "收入",
                        "row_ref": "row_29",
                        "raw_text": "中国移动2025年营业收入达到10502亿元。",
                        "sources": ["https://www.chinamobileltd.com/report"],
                    }
                ],
                "existing_items": {
                    "old-a": {
                        "schemaVersion": 4,
                        "company": "中国移动",
                        "metric": "收入",
                        "row_ref": "row_29",
                        "semantic_key": "中国移动|收入|row_29",
                        "status": "ok",
                        "decision": "accepted",
                        "value": "10502亿元",
                        "quality_score": 0.96,
                    }
                },
                "candidates": [
                    {
                        "id": "fact-a",
                        "company": "中国移动",
                        "metric": "收入",
                        "value": "10500亿元",
                        "basis": "候选值为10500亿元。",
                        "status": "ok",
                        "entity_supported": True,
                        "metric_supported": True,
                        "value_supported": True,
                        "confidence": 0.86,
                        "source_score": 1.0,
                        "source_tier": "official",
                        "row_ref": "row_29",
                        "sources": ["https://www.chinamobileltd.com/report"],
                        "quality_score": 0.94,
                        "decision": "accepted",
                    }
                ],
            }
        )
        fact = result["candidates"][0]
        self.assertEqual(fact["value"], "10502亿元")
        self.assertEqual(fact["decision"], "accepted")
        self.assertEqual(fact["search_verification"]["decision"], "majority_corrected")

    def test_search_verifier_conflict_without_majority_goes_to_review(self) -> None:
        result = search_verify_facts(
            {
                "run_id": "unit-test",
                "search_verify_workers": 2,
                "tasks": [
                    {
                        "id": "fact-b",
                        "company": "中国电信",
                        "metric": "收入",
                        "row_ref": "row_23",
                        "raw_text": "中国电信收入为5296亿元。",
                        "sources": ["https://www.chinatelecom-h.com/report"],
                    }
                ],
                "existing_items": {},
                "candidates": [
                    {
                        "id": "fact-b",
                        "company": "中国电信",
                        "metric": "收入",
                        "value": "5295亿元",
                        "basis": "候选值为5295亿元。",
                        "status": "ok",
                        "entity_supported": True,
                        "metric_supported": True,
                        "value_supported": True,
                        "confidence": 0.86,
                        "source_score": 1.0,
                        "source_tier": "official",
                        "row_ref": "row_23",
                        "sources": ["https://www.chinatelecom-h.com/report"],
                        "quality_score": 0.94,
                        "decision": "accepted",
                    }
                ],
            }
        )
        fact = result["candidates"][0]
        self.assertEqual(fact["decision"], "review")
        self.assertIn("搜索验证未形成多数口径", fact["reasons"])

    def test_search_verifier_confirms_table_value_from_metric_window(self) -> None:
        result = search_verify_facts(
            {
                "run_id": "unit-test",
                "search_verify_workers": 1,
                "tasks": [
                    {
                        "id": "icable-revenue",
                        "company": "i-CABLE",
                        "metric": "运营收入/总收益",
                        "row_ref": "row_17",
                        "raw_text": (
                            "Fiscal Year FY 2025 FY 2024 FY 2023 "
                            "Revenue 538.74 584.49 597.9"
                        ),
                        "sources": ["https://stockanalysis.com/quote/hkg/1097/financials/"],
                    }
                ],
                "existing_items": {},
                "candidates": [
                    {
                        "id": "icable-revenue",
                        "company": "i-CABLE",
                        "metric": "运营收入/总收益",
                        "value": "538.74（百万，单位未明确，推测为百万港元）",
                        "basis": "片段中明确列出Revenue 538.74。",
                        "status": "ok",
                        "entity_supported": True,
                        "metric_supported": True,
                        "value_supported": True,
                        "confidence": 0.9,
                        "source_score": 0.9,
                        "source_tier": "commercial",
                        "row_ref": "row_17",
                        "sources": ["https://stockanalysis.com/quote/hkg/1097/financials/"],
                        "quality_score": 0.94,
                        "decision": "accepted",
                    }
                ],
            }
        )
        verification = result["candidates"][0]["search_verification"]
        self.assertGreaterEqual(verification["vote_count"], 2)
        self.assertEqual(verification["decision"], "majority_confirmed")

    def test_search_verifier_ignores_unrelated_qualitative_window(self) -> None:
        result = search_verify_facts(
            {
                "run_id": "unit-test",
                "search_verify_workers": 1,
                "tasks": [
                    {
                        "id": "hkbn-board",
                        "company": "HKBN",
                        "metric": "董事会",
                        "row_ref": "row_12",
                        "raw_text": (
                            "Corporate Governance Report Board Diversity. "
                            "The Board has over 50% female Directors."
                        ),
                        "sources": ["https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_AnnualReport_2025.pdf"],
                    }
                ],
                "existing_items": {},
                "candidates": [
                    {
                        "id": "hkbn-board",
                        "company": "HKBN",
                        "metric": "董事会",
                        "value": "董事会决议宣派2025财年末期股息每股18.9港仙",
                        "basis": "Board has resolved to declare a final dividend of 18.9 cents per share",
                        "status": "ok",
                        "entity_supported": True,
                        "metric_supported": True,
                        "value_supported": True,
                        "confidence": 0.96,
                        "source_score": 1.0,
                        "source_tier": "official",
                        "row_ref": "row_12",
                        "sources": ["https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_AnnualReport_2025.pdf"],
                        "quality_score": 0.996,
                        "decision": "accepted",
                    }
                ],
            }
        )
        fact = result["candidates"][0]
        self.assertEqual(fact["decision"], "accepted")
        self.assertNotIn("搜索验证未形成多数口径", fact.get("reasons", []))

    def test_search_verifier_online_search_vote_can_join_majority(self) -> None:
        with patch(
            "data_curation.workflow._public_web_search",
            return_value=(
                [
                    {
                        "title": "中国移动2025年营业收入达到10502亿元",
                        "snippet": "中国移动发布年度业绩，营业收入达到10502亿元。",
                        "url": "https://www.chinamobileltd.com/report",
                        "provider": "unit",
                    }
                ],
                "unit",
            ),
        ):
            result = search_verify_facts(
                {
                    "run_id": "unit-test",
                    "search_verify_workers": 2,
                    "search_verify_online": True,
                    "search_verify_online_limit": 1,
                    "tasks": [
                        {
                            "id": "fact-online",
                            "company": "中国移动",
                            "metric": "收入",
                            "row_ref": "row_29",
                            "raw_text": "中国移动营业收入达到10502亿元。",
                            "sources": ["https://www.chinamobileltd.com/report"],
                        }
                    ],
                    "existing_items": {},
                    "candidates": [
                        {
                            "id": "fact-online",
                            "company": "中国移动",
                            "metric": "收入",
                            "value": "10500亿元",
                            "basis": "候选值为10500亿元。",
                            "status": "ok",
                            "entity_supported": True,
                            "metric_supported": True,
                            "value_supported": True,
                            "confidence": 0.86,
                            "source_score": 1.0,
                            "source_tier": "official",
                            "row_ref": "row_29",
                            "sources": ["https://www.chinamobileltd.com/report"],
                            "quality_score": 0.94,
                            "decision": "accepted",
                        }
                    ],
                }
            )
        fact = result["candidates"][0]
        self.assertEqual(fact["value"], "10502亿元")
        self.assertEqual(fact["search_verification"]["online_search"]["provider"], "unit")
        self.assertGreaterEqual(result["search_verification"]["online_votes"], 1)

    def test_search_verifier_zero_online_limit_checks_all_targets(self) -> None:
        calls: list[str] = []

        def fake_search(query: str):
            calls.append(query)
            return [], "unit-empty"

        with (
            patch("data_curation.workflow._public_web_search", side_effect=fake_search),
            patch("data_curation.workflow._votes_from_source_pages", return_value=[]),
        ):
            result = search_verify_facts(
                {
                    "run_id": "unit-test",
                    "search_verify_workers": 2,
                    "search_verify_online": True,
                    "search_verify_online_limit": 0,
                    "tasks": [],
                    "existing_items": {},
                    "candidates": [
                        {
                            "id": f"fact-{index}",
                            "company": "中国移动",
                            "metric": "收入",
                            "value": f"1050{index}亿元",
                            "basis": f"收入为1050{index}亿元。",
                            "status": "ok",
                            "entity_supported": True,
                            "metric_supported": True,
                            "value_supported": True,
                            "confidence": 0.9,
                            "source_score": 1.0,
                            "source_tier": "official",
                            "row_ref": f"row_{index}",
                            "sources": ["https://www.chinamobileltd.com/report"],
                            "quality_score": 0.94,
                            "decision": "rejected" if index == 2 else "accepted",
                        }
                        for index in range(3)
                    ],
                }
            )
        self.assertEqual(len(calls), 3)
        self.assertEqual(result["search_verification"]["online_checked"], 3)
        self.assertEqual(result["search_verification"]["online_required"], 3)
        self.assertTrue(result["search_verification"]["online_coverage_complete"])
        self.assertTrue(all("quarterly results" in query for query in calls))
        self.assertTrue(all("interim results" in query for query in calls))
        self.assertTrue(all("earnings release" in query for query in calls))
        self.assertTrue(all("财报" in query and "公告" in query for query in calls))

    def test_search_verifier_online_source_pages_can_recover_rejected_fact(self) -> None:
        with (
            patch("data_curation.workflow._public_web_search", return_value=([], "unit-empty")),
            patch(
                "data_curation.workflow._votes_from_source_pages",
                return_value=[
                    {
                        "value": "Net Income -489.98M",
                        "normalized_value": "-48998万",
                        "canonical": "-48998万",
                        "source": "公开来源页读取",
                        "kind": "source_page",
                        "url": "https://stockanalysis.com/quote/hkg/1097/statistics/",
                    },
                    {
                        "value": "Net Income -489.98M",
                        "normalized_value": "-48998万",
                        "canonical": "-48998万",
                        "source": "公开来源页读取",
                        "kind": "source_page",
                        "url": "https://stockanalysis.com/quote/hkg/1097/financials/",
                    },
                ],
            ),
        ):
            result = search_verify_facts(
                {
                    "run_id": "unit-test",
                    "search_verify_workers": 1,
                    "search_verify_online": True,
                    "search_verify_online_limit": 1,
                    "tasks": [],
                    "existing_items": {},
                    "candidates": [
                        {
                            "id": "icable-profit",
                            "company": "i-CABLE",
                            "metric": "净利润",
                            "value": "未提取到有效数据",
                            "basis": "现有片段不是集团净利润。",
                            "status": "unavailable",
                            "entity_supported": False,
                            "metric_supported": False,
                            "value_supported": False,
                            "confidence": 0.2,
                            "source_score": 0.5,
                            "source_tier": "commercial",
                            "row_ref": "row_17",
                            "sources": ["https://stockanalysis.com/quote/hkg/1097/financials/"],
                            "quality_score": 0.1,
                            "decision": "rejected",
                            "reasons": ["抽取结果不可用"],
                        }
                    ],
                }
            )
        fact = result["candidates"][0]
        self.assertEqual(fact["decision"], "accepted")
        self.assertEqual(fact["status"], "ok")
        self.assertEqual(fact["value"], "-48998万港元")
        self.assertEqual(fact["search_verification"]["decision"], "majority_corrected")

    def test_search_verifier_does_not_rescue_unavailable_fact_from_same_basis_twice(self) -> None:
        with (
            patch("data_curation.workflow._public_web_search", return_value=([], "unit-empty")),
            patch("data_curation.workflow._votes_from_source_pages", return_value=[]),
        ):
            result = search_verify_facts(
                {
                "run_id": "unit-test",
                "search_verify_workers": 1,
                "search_verify_online": True,
                "search_verify_online_limit": 1,
                "tasks": [],
                "existing_items": {},
                "candidates": [
                    {
                        "id": "azure-capex",
                        "company": "Microsoft Azure",
                        "metric": "资本开支",
                        "value": "未提取到有效数据",
                        "basis": "资本性资产购置同比增加20.1亿美元，无资本开支总额。",
                        "status": "unavailable",
                        "entity_supported": True,
                        "metric_supported": True,
                        "value_supported": False,
                        "confidence": 0.3,
                        "source_score": 1.0,
                        "source_tier": "official",
                        "row_ref": "row_53",
                        "sources": ["https://www.microsoft.com/investor/reports/ar25/index.html"],
                        "quality_score": 0.3,
                        "decision": "rejected",
                        "reasons": ["数值或事实依据不足"],
                    }
                ],
                }
            )
        fact = result["candidates"][0]
        self.assertEqual(fact["decision"], "rejected")
        self.assertEqual(fact["status"], "unavailable")
        self.assertEqual(
            fact["search_verification"]["decision"],
            "insufficient_independent_evidence",
        )

    def test_search_verifier_rechecks_suspicious_accepted_profit_segment(self) -> None:
        with (
            patch("data_curation.workflow._public_web_search", return_value=([], "unit-empty")),
            patch(
                "data_curation.workflow._votes_from_source_pages",
                return_value=[
                    {
                        "value": "Net Income -489.98M",
                        "normalized_value": "-48998万",
                        "canonical": "-48998万",
                        "source": "公开来源页读取",
                        "kind": "source_page",
                        "url": "https://stockanalysis.com/quote/hkg/1097/statistics/",
                    },
                    {
                        "value": "Net Income -489.98M",
                        "normalized_value": "-48998万",
                        "canonical": "-48998万",
                        "source": "公开来源页读取",
                        "kind": "source_page",
                        "url": "https://stockanalysis.com/quote/hkg/1097/financials/",
                    },
                ],
            ),
        ):
            result = search_verify_facts(
                {
                    "run_id": "unit-test",
                    "search_verify_workers": 1,
                    "search_verify_online": True,
                    "search_verify_online_limit": 1,
                    "tasks": [
                        {
                            "id": "icable-profit",
                            "raw_text": "Segment profit before depreciation was HK$243,000,000, not net profit.",
                            "sources": ["https://stockanalysis.com/quote/hkg/1097/financials/"],
                        }
                    ],
                    "existing_items": {},
                    "candidates": [
                        {
                            "id": "icable-profit",
                            "company": "i-CABLE",
                            "metric": "净利润",
                            "value": "243,000,000港元；291,000,000港元；26,000,000港元；27%",
                            "basis": "片段描述的是未扣除折旧、其他无形资产摊销及减值亏损前的经营费用和分部溢利，并非净利润。",
                            "status": "ok",
                            "entity_supported": True,
                            "metric_supported": True,
                            "value_supported": True,
                            "confidence": 0.9,
                            "source_score": 1.0,
                            "source_tier": "official",
                            "row_ref": "row_17",
                            "sources": ["https://stockanalysis.com/quote/hkg/1097/financials/"],
                            "quality_score": 0.99,
                            "decision": "accepted",
                            "reasons": [],
                        }
                    ],
                }
            )
        fact = result["candidates"][0]
        votes = fact["search_verification"]["votes"]
        self.assertEqual(fact["decision"], "accepted")
        self.assertEqual(fact["status"], "ok")
        self.assertEqual(fact["value"], "-48998万港元")
        self.assertEqual(fact["search_verification"]["decision"], "majority_corrected")
        self.assertTrue(fact["search_verification"]["online_search"]["enabled"])
        self.assertNotIn("candidate", {vote["kind"] for vote in votes})
        self.assertNotIn("local_evidence", {vote["kind"] for vote in votes})

    def test_source_page_ignores_unrelated_numeric_value(self) -> None:
        class FakeResponse:
            text = "<html><body>Adjusted EBITDA margin changed by -1.4% year over year.</body></html>"

            def raise_for_status(self) -> None:
                return None

        fact = CandidateFact(
            id="att-fwa",
            company="AT&T",
            metric="FWA",
            value="2026年一季度固定无线净增29.2万；AT&T Internet Air收入增长超过100%",
            basis="AT&T reported 292,000 fixed wireless net adds and AIA revenue exceeded 100 percent.",
            status="ok",
            entity_supported=True,
            metric_supported=True,
            value_supported=True,
            confidence=0.96,
            source_score=0.72,
            source_tier="public",
            row_ref="row_20",
            sources=["https://investors.att.com/report"],
            quality_score=0.968,
            decision="accepted",
        )
        with patch("httpx.get", return_value=FakeResponse()):
            self.assertEqual(_votes_from_source_pages(fact), [])

    def test_source_open_audit_keeps_403_separate_from_search(self) -> None:
        class ForbiddenResponse:
            text = ""
            url = "https://example.com/investors/results"
            status_code = 403
            is_success = False
            headers = {}

            def raise_for_status(self) -> None:
                raise RuntimeError("403 Forbidden")

        fact = CandidateFact(
            id="airtel-results",
            company="Bharti Airtel",
            metric="收入",
            row_ref="row_19",
            sources=[],
            decision="review",
        )
        audit = []
        with patch("httpx.get", return_value=ForbiddenResponse()):
            votes = _votes_from_source_pages(
                fact,
                extra_urls=["https://example.com/investors/results"],
                open_audit=audit,
            )
        self.assertEqual(votes, [])
        self.assertEqual(audit[0]["http_status"], 403)
        self.assertFalse(audit[0]["opened"])
        self.assertEqual(audit[0]["blocked_reason"], "HTTP 403")

    def test_search_verifier_matches_wan_unit_to_raw_integer(self) -> None:
        result = search_verify_facts(
            {
                "run_id": "unit-test",
                "search_verify_workers": 1,
                "tasks": [
                    {
                        "id": "att-fwa",
                        "raw_text": (
                            "During the first quarter of 2026, AT&T reported 292,000 "
                            "fixed wireless net adds, and Internet Air revenue exceeded 100 percent."
                        ),
                        "sources": ["https://investors.att.com/report"],
                    }
                ],
                "existing_items": {},
                "candidates": [
                    {
                        "id": "att-fwa",
                        "company": "AT&T",
                        "metric": "FWA",
                        "value": "2026年一季度固定无线净增29.2万；AT&T Internet Air收入增长超过100%",
                        "basis": "AT&T reported 292,000 fixed wireless net adds and AIA revenue exceeded 100 percent.",
                        "status": "ok",
                        "entity_supported": True,
                        "metric_supported": True,
                        "value_supported": True,
                        "confidence": 0.96,
                        "source_score": 0.72,
                        "source_tier": "public",
                        "row_ref": "row_20",
                        "sources": ["https://investors.att.com/report"],
                        "quality_score": 0.968,
                        "decision": "accepted",
                    }
                ],
            }
        )
        verification = result["candidates"][0]["search_verification"]
        self.assertEqual(result["candidates"][0]["decision"], "accepted")
        self.assertGreaterEqual(verification["vote_count"], 2)
        self.assertEqual(verification["decision"], "majority_confirmed")

    def test_search_verifier_trusts_official_basis_over_unrelated_same_page_numbers(self) -> None:
        result = search_verify_facts(
            {
                "run_id": "unit-test",
                "search_verify_workers": 1,
                "tasks": [
                    {
                        "id": "hutchison-customers",
                        "raw_text": "customers to total customer base (%) 16%; customer service revenue (%) 76%; customers (%) 0.9%",
                        "sources": ["https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0401/2026040102176.pdf"],
                    }
                ],
                "existing_items": {},
                "candidates": [
                    {
                        "id": "hutchison-customers",
                        "company": "Hutchison",
                        "metric": "客户数/用户数",
                        "value": "后付费客户128.9万；预付费客户684.3万；客户总数813.2万",
                        "basis": "后付费客户128.9万；预付费客户684.3万；客户总数813.2万",
                        "status": "ok",
                        "entity_supported": True,
                        "metric_supported": True,
                        "value_supported": True,
                        "confidence": 0.96,
                        "source_score": 1.0,
                        "source_tier": "official",
                        "row_ref": "row_5",
                        "sources": ["https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0401/2026040102176.pdf"],
                        "quality_score": 0.996,
                        "decision": "accepted",
                    }
                ],
            }
        )
        fact = result["candidates"][0]
        self.assertEqual(fact["decision"], "accepted")
        self.assertEqual(fact["search_verification"]["decision"], "majority_confirmed")
        self.assertIn("basis_in_official_evidence", {vote["kind"] for vote in fact["search_verification"]["votes"]})

    def test_search_verifier_keeps_monitoring_closure_when_source_page_has_noise(self) -> None:
        result = search_verify_facts(
            {
                "run_id": "unit-test",
                "search_verify_workers": 1,
                "tasks": [
                    {
                        "id": "smartone-roaming",
                        "raw_text": "Roaming data pack $178. APAC worldwide roaming data pack $99 1GB.",
                        "sources": ["https://5g.smartone.com/en/mobile_and_price_plans/roaming/apac_worldwide_roaming_data_pack/charges.jsp"],
                    }
                ],
                "existing_items": {},
                "candidates": [
                    {
                        "id": "smartone-roaming",
                        "company": "SmarTone",
                        "metric": "漫游",
                        "value": "本轮公开来源未发现SmarTone关于漫游的可核验披露；维持后续监测。",
                        "basis": "已检查本轮抓取来源，现有证据显示该指标未披露或仅出现导航/栏目/泛化描述。",
                        "note": "缺口闭环为未披露监测结论",
                        "status": "ok",
                        "entity_supported": True,
                        "metric_supported": True,
                        "value_supported": True,
                        "confidence": 0.9,
                        "source_score": 1.0,
                        "source_tier": "official",
                        "row_ref": "row_9",
                        "sources": ["https://5g.smartone.com/en/mobile_and_price_plans/roaming/apac_worldwide_roaming_data_pack/charges.jsp"],
                        "quality_score": 0.985,
                        "decision": "accepted",
                    }
                ],
            }
        )
        fact = result["candidates"][0]
        self.assertEqual(fact["decision"], "accepted")
        self.assertEqual(fact["search_verification"]["decision"], "majority_confirmed")
        self.assertEqual(fact["search_verification"]["conflict_count"], 0)

    def test_quality_audit_adds_hkd_unit_to_hk_financial_wan_value(self) -> None:
        result = audit_quality(
            {
                "run_id": "unit-test",
                "candidates": [
                    {
                        "id": "icable-profit",
                        "company": "i-CABLE",
                        "metric": "净利润",
                        "value": "-48998万",
                        "basis": "Net Income -489.98M, currency HKD.",
                        "note": "",
                        "status": "ok",
                        "entity_supported": True,
                        "metric_supported": True,
                        "value_supported": True,
                        "confidence": 0.95,
                        "source_score": 1.0,
                        "source_tier": "official",
                        "row_ref": "row_17",
                        "sources": ["https://stockanalysis.com/quote/hkg/1097/financials/"],
                        "quality_score": 0.99,
                        "decision": "accepted",
                    },
                ],
            }
        )
        fact = result["candidates"][0]
        self.assertEqual(fact["decision"], "accepted")
        self.assertEqual(fact["value"], "-48998万港元")
        self.assertNotIn("未通过指标格式与单位门禁", fact["reasons"])

    def test_quality_audit_adds_context_unit_to_multi_year_financial_values(self) -> None:
        result = audit_quality(
            {
                "run_id": "unit-test",
                "candidates": [
                    {
                        "id": "hutchison-ebitda",
                        "company": "Hutchison",
                        "metric": "EBITDA",
                        "value": "1,508 (2025); 1,511 (2024)",
                        "basis": "片段中明确列出 'EBITDA (2) 1,508 1,511'，单位为百万港元。",
                        "note": "",
                        "status": "ok",
                        "entity_supported": True,
                        "metric_supported": True,
                        "value_supported": True,
                        "confidence": 0.95,
                        "source_score": 1.0,
                        "source_tier": "official",
                        "row_ref": "row_5",
                        "sources": ["https://www.hthkh.com/en/ir/reports.php"],
                        "quality_score": 0.99,
                        "decision": "accepted",
                    },
                ],
            }
        )
        fact = result["candidates"][0]
        self.assertEqual(fact["decision"], "accepted")
        self.assertEqual(fact["value"], "2025: 1,508百万港元；2024: 1,511百万港元")
        self.assertNotIn("未通过指标格式与单位门禁", fact["reasons"])

    def test_quality_audit_rejects_group_total_as_cloud_metric(self) -> None:
        result = audit_quality(
            {
                "run_id": "unit-test",
                "candidates": [
                    {
                        "id": "huawei-group-growth",
                        "company": "Huawei Cloud",
                        "metric": "同比增速",
                        "value": "总收入862,072百万元人民币（同比增长22.4%）",
                        "basis": "Huawei's annual sales revenue increased 22.4% year-over-year.",
                        "note": "",
                        "status": "ok",
                        "entity_supported": True,
                        "metric_supported": True,
                        "value_supported": True,
                        "confidence": 0.95,
                        "source_score": 1.0,
                        "source_tier": "official",
                        "row_ref": "row_50",
                        "sources": ["https://www.huawei.com/en/annual-report"],
                    },
                    {
                        "id": "hkbn-user-percent-only",
                        "company": "HKBN",
                        "metric": "用户数",
                        "value": "-2%；-6%",
                        "basis": "Residential broadband customers declined 2%; enterprise customers declined 6%.",
                        "note": "",
                        "status": "ok",
                        "entity_supported": True,
                        "metric_supported": True,
                        "value_supported": True,
                        "confidence": 0.9,
                        "source_score": 1.0,
                        "source_tier": "official",
                        "row_ref": "row_47",
                        "sources": ["https://www.hkbn.net/group/en/investor-engagement/financial-results"],
                    },
                ],
            }
        )
        by_id = {item["id"]: item for item in result["candidates"]}
        self.assertEqual(by_id["huawei-group-growth"]["decision"], "rejected")
        self.assertIn("云指标缺少云业务专属口径", by_id["huawei-group-growth"]["reasons"])
        self.assertEqual(by_id["hkbn-user-percent-only"]["decision"], "rejected")
        self.assertIn("用户数仅有比例变化而无客户规模", by_id["hkbn-user-percent-only"]["reasons"])

    def test_gap_targets_restrict_recrawl_entities_and_metrics(self) -> None:
        rows = [
            {
                "row": "5",
                "entities": ["3HK", "Hutchison"],
                "sources": "",
            }
        ]
        with patch.dict(
            "os.environ",
            {
                "CMHK_GAP_TARGETS": (
                    '{"5":{"companies":["Hutchison"],'
                    '"metrics":["客户数/用户数","市场反应"]}}'
                )
            },
            clear=False,
        ):
            configured = apply_crawl_settings(rows)
        self.assertEqual(configured[0]["entities"], ["Hutchison"])
        self.assertEqual(configured[0]["selected_fields"], ["客户数/用户数", "市场反应"])

    def test_verified_icable_fields_recover_from_evidence_gap(self) -> None:
        result = audit_quality(
            {
                "candidates": [
                    {
                        "id": "icable-dividend",
                        "row_ref": "row_17",
                        "company": "i-CABLE",
                        "metric": "派息",
                        "status": "unavailable",
                        "value": "",
                        "basis": "",
                        "note": "",
                        "sources": [],
                        "source_score": 0.0,
                        "source_tier": "missing",
                        "entity_supported": False,
                        "metric_supported": False,
                        "value_supported": False,
                        "confidence": 0.0,
                        "reasons": ["主体归属未通过", "抽取结果不可用"],
                    }
                ]
            }
        )
        fact = result["candidates"][0]
        self.assertEqual(fact["decision"], "accepted")
        self.assertEqual(fact["status"], "ok")
        self.assertIn("不建议派发2025年度末期股息", fact["value"])
        self.assertEqual(fact["reasons"], [])


if __name__ == "__main__":
    unittest.main()

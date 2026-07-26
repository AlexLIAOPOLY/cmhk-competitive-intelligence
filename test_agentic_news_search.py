from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

import news_discovery_digest as digest
import strategic_briefing


HKT = ZoneInfo("Asia/Hong_Kong")


class AgenticNewsSearchTests(unittest.TestCase):
    def test_agentic_planner_has_room_and_retries_for_complete_json(self):
        spec = {
            "modules": [{"name": "竞争对手", "keywords": ["HKT"], "source_urls": []}]
        }
        with mock.patch.object(
            strategic_briefing,
            "_call_internal_ai",
            return_value={
                "sufficient": True,
                "assessment": "覆盖充分",
                "queries": [],
            },
        ) as call:
            plans, trace = digest._call_agentic_search_agent(
                phase="followup",
                spec=spec,
                coverage={"result_count": 1},
                existing_plans=[],
                start_at=datetime(2026, 7, 25, 8, 0, tzinfo=HKT),
                end_at=datetime(2026, 7, 25, 15, 0, tzinfo=HKT),
                limit=6,
            )

        self.assertEqual(plans, [])
        self.assertEqual(trace["status"], "completed")
        self.assertEqual(digest.AGENTIC_AI_ATTEMPTS, 3)
        self.assertGreaterEqual(call.call_args.kwargs["max_tokens"], 2600)
        self.assertIn("query最多180个字符", call.call_args.args[0])

    def test_target_planner_retries_gap_without_valid_query_and_sets_canonical(self):
        responses = [
            {
                "sufficient": False,
                "assessment": "仍有缺口",
                "queries": [],
            },
            {
                "sufficient": False,
                "assessment": "需要补搜HGC网络建设",
                "queries": [
                    {
                        "module": "竞争对手",
                        "query": "HGC Global Communications 网络建设",
                        "keywords": ["HGC Global Communications"],
                        "intent": "网络建设",
                    }
                ],
            },
        ]
        with mock.patch.object(
            strategic_briefing,
            "_call_internal_ai",
            side_effect=responses,
        ) as call:
            plans, trace = digest._call_agentic_search_agent(
                phase="followup",
                spec={"modules": []},
                coverage={"missing_fixed_competitors": ["HGC"]},
                existing_plans=[],
                start_at=datetime(2026, 7, 25, 8, 0, tzinfo=HKT),
                end_at=datetime(2026, 7, 25, 15, 0, tzinfo=HKT),
                limit=1,
                target_competitor="HGC",
            )

        self.assertEqual(call.call_count, 2)
        self.assertEqual(trace["status"], "completed")
        self.assertEqual(trace["attempts"], 2)
        self.assertEqual(plans[0]["canonical_competitor"], "HGC")

    def test_agentic_plan_keeps_monitoring_term_relevance_guard(self):
        raw = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss><channel><item>
          <title>Carrier lifts annual cash generation outlook after strong quarter</title>
          <link>https://example.com/news/cash-outlook</link>
          <description>T-Mobile raised guidance after subscriber growth.</description>
          <pubDate>Sat, 25 Jul 2026 08:00:00 +0800</pubDate>
          <source>Example News</source>
        </item></channel></rss>"""
        ET.fromstring(raw)
        common = {
            "provider": "google",
            "module": "竞争对手",
            "keywords": ["T-Mobile"],
            "base_query": '"T-Mobile" earnings guidance subscriber growth',
            "start_at": datetime(2026, 7, 25, 0, 0, tzinfo=HKT),
            "end_at": datetime(2026, 7, 25, 15, 0, tzinfo=HKT),
        }

        self.assertEqual(len(digest._parse_news_feed(raw, **common)), 1)
        items = digest._parse_news_feed(
            raw,
            **common,
            semantic_relevance=True,
            search_origin="agentic_expansion",
            agentic_intent="寻找未直接写公司全名的业绩指引报道",
        )

        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["semantic_relevance"])
        self.assertTrue(items[0]["literal_keyword_match"])
        self.assertEqual(items[0]["keywords"], ["T-Mobile"])
        self.assertEqual(items[0]["search_origin"], "agentic_expansion")
        unrelated = raw.replace(b"T-Mobile raised", b"The mobile group raised")
        self.assertEqual(
            digest._parse_news_feed(
                unrelated,
                **common,
                semantic_relevance=True,
                search_origin="agentic_expansion",
            ),
            [],
        )

    def test_agentic_plan_is_additive_and_deduplicates_existing_queries(self):
        existing = {'"hkt" earnings'}
        plans = digest._normalize_agentic_plans(
            {
                "queries": [
                    {
                        "module": "竞争对手",
                        "query": '"HKT" earnings',
                        "keywords": ["HKT"],
                        "intent": "重复查询",
                    },
                    {
                        "module": "竞争对手",
                        "query": '("HKT" OR "PCCW") (guidance OR subscriber growth)',
                        "keywords": ["HKT", "PCCW"],
                        "intent": "补充经营事件同义表达",
                        "reason": "固定查询只覆盖公司名称",
                    },
                ]
            },
            phase="expansion",
            existing_queries=existing,
            limit=6,
        )

        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["search_origin"], "agentic_expansion")
        self.assertTrue(plans[0]["semantic_relevance"])
        self.assertIn("subscriber growth", plans[0]["query"])
        self.assertEqual(plans[0]["canonical_competitor"], "HKT")

    def test_agentic_plan_rejects_runaway_all_operator_query(self):
        plans = digest._normalize_agentic_plans(
            {
                "queries": [
                    {
                        "module": "竞争对手",
                        "query": "HKT " + " OR 裁员" * 60,
                        "keywords": ["HKT"],
                        "intent": "失控的超长查询",
                    }
                ]
            },
            phase="followup",
            existing_queries=set(),
            limit=6,
        )

        self.assertEqual(plans, [])

    def test_followup_planning_isolated_by_missing_competitor(self):
        def fake_planner(**kwargs):
            target = kwargs["target_competitor"]
            return (
                [
                    {
                        "query": f"{target} 资费调整",
                        "fallback_query": f"{target} 资费调整",
                    }
                ],
                {
                    "status": "completed",
                    "attempts": 1,
                    "sufficient": False,
                    "assessment": f"补搜{target}",
                    "query_count": 1,
                },
            )

        with mock.patch.object(
            digest,
            "_call_agentic_search_agent",
            side_effect=fake_planner,
        ) as planner:
            plans, trace = digest._call_agentic_followup_agents(
                spec={"modules": []},
                coverage={
                    "missing_fixed_competitors": ["HKT", "SmarTone"],
                },
                existing_plans=[],
                start_at=datetime(2026, 7, 25, 8, 0, tzinfo=HKT),
                end_at=datetime(2026, 7, 25, 15, 0, tzinfo=HKT),
                limit=6,
            )

        self.assertEqual(len(plans), 2)
        self.assertEqual(trace["status"], "completed")
        self.assertEqual(
            [call.kwargs["target_competitor"] for call in planner.call_args_list],
            ["HKT", "SmarTone"],
        )

    def test_collect_news_keeps_fixed_search_when_agentic_planner_fails(self):
        spec = {
            "module_count": 1,
            "keyword_count": 1,
            "modules": [{"name": "竞争对手", "keywords": ["HKT"], "source_urls": []}],
            "source_urls": [],
        }
        fixed_item = {
            "news_id": "NEWS-FIXED",
            "title": "HKT announces enterprise network expansion",
            "url": "https://example.com/hkt",
            "source": "Example",
            "published_at": "2026-07-25T08:00:00+08:00",
            "module": "竞争对手",
            "keywords": ["HKT"],
            "canonical_competitor": "HKT",
        }
        with (
            mock.patch.object(strategic_briefing, "read_monitoring_spec", return_value=spec),
            mock.patch.object(strategic_briefing, "_query_plans", return_value=[]),
            mock.patch.object(digest, "_mandatory_competitor_plans", return_value=[{
                "module": "竞争对手",
                "query": '"HKT"',
                "fallback_query": '"HKT"',
                "keywords": ["HKT"],
                "canonical_competitor": "HKT",
                "search_origin": "mandatory_local_competitor",
            }]),
            mock.patch.object(digest, "BENCHMARK_OPERATOR_QUERIES", ()),
            mock.patch.object(digest, "PRIORITY_NEWS_QUERIES", ()),
            mock.patch.object(
                digest,
                "_execute_search_plans",
                side_effect=[
                    ([fixed_item], [], {"query_count": 1, "result_count": 1}),
                    ([], [], {"query_count": 0, "result_count": 0}),
                ],
            ),
            mock.patch.object(
                digest,
                "_call_agentic_search_agent",
                return_value=([], {"status": "failed", "error": "AI unavailable"}),
            ),
        ):
            items, errors, result_spec = digest.collect_news(
                datetime(2026, 7, 25, 0, 0, tzinfo=HKT),
                datetime(2026, 7, 25, 15, 0, tzinfo=HKT),
            )

        self.assertEqual([item["news_id"] for item in items], ["NEWS-FIXED"])
        self.assertEqual(errors, [])
        trace = result_spec["agentic_search"]
        self.assertEqual(trace["fixed_query_count"], 1)
        self.assertEqual(trace["fixed_result_count"], 1)
        self.assertEqual(trace["agentic_result_count"], 0)
        self.assertEqual(trace["rounds"][0]["status"], "failed")


if __name__ == "__main__":
    unittest.main()

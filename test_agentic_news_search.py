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

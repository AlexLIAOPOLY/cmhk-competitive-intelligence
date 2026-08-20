from __future__ import annotations

import json
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

import news_discovery_digest as digest
import strategic_briefing


HKT = ZoneInfo("Asia/Hong_Kong")


class AgenticNewsSearchTests(unittest.TestCase):
    def test_morning_window_rechecks_previous_afternoon_for_late_indexing(self):
        start_at, end_at = digest._window(
            datetime(2026, 8, 16, 9, 0, tzinfo=HKT),
            True,
        )

        self.assertEqual(start_at, datetime(2026, 8, 15, 8, 0, tzinfo=HKT))
        self.assertEqual(end_at, datetime(2026, 8, 16, 9, 0, tzinfo=HKT))

    def test_afternoon_window_keeps_one_hour_overlap_with_morning_slot(self):
        start_at, end_at = digest._window(
            datetime(2026, 8, 16, 14, 0, tzinfo=HKT),
            False,
        )

        self.assertEqual(start_at, datetime(2026, 8, 16, 8, 0, tzinfo=HKT))
        self.assertEqual(end_at, datetime(2026, 8, 16, 14, 0, tzinfo=HKT))

    def test_late_index_retry_unions_results_until_reliable_minimum(self):
        def item(index):
            return {
                "news_id": f"NEWS-{index}",
                "title": f"晚到新闻{index}",
                "url": f"https://example.com/late/{index}",
                "published_at": f"2026-08-16T08:0{index}:00+08:00",
                "module": "基础设施/网络/技术类",
            }

        specs = [
            {
                "agentic_search": {
                    "fixed_query_count": 75,
                    "fixed_result_count": count,
                }
            }
            for count in (0, 1, 2)
        ]
        with (
            mock.patch.object(
                digest,
                "collect_news",
                side_effect=[
                    ([], [], specs[0]),
                    ([item(1)], [], specs[1]),
                    ([item(2), item(3)], [], specs[2]),
                ],
            ) as collect,
            mock.patch.object(
                digest,
                "_late_index_retry_delays",
                return_value=(300, 600),
            ),
            mock.patch.object(digest.time, "sleep") as sleep,
        ):
            items, errors, spec = digest._collect_news_with_late_index_retry(
                datetime(2026, 8, 16, 8, 0, tzinfo=HKT),
                datetime(2026, 8, 16, 15, 0, tzinfo=HKT),
            )

        self.assertEqual(collect.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [300, 600])
        self.assertEqual(len(items), 3)
        self.assertEqual(errors, [])
        retry = spec["agentic_search"]["late_index_retry"]
        self.assertTrue(retry["triggered"])
        self.assertFalse(retry["exhausted"])
        self.assertEqual(retry["recovered_count"], 3)

    def test_send_digest_persists_explicit_empty_pool(self):
        now = datetime(2026, 8, 16, 15, 0, tzinfo=HKT)
        with (
            mock.patch.object(
                digest,
                "_collect_news_with_late_index_retry",
                return_value=([], [], {"agentic_search": {}}),
            ),
            mock.patch.object(digest, "_latest_timed_crawl", return_value={}),
            mock.patch.object(digest, "_build_cards", return_value=[]),
            mock.patch.object(digest, "_write_json") as write_json,
            mock.patch.dict(
                digest.os.environ,
                {"CMHK_STRATEGIC_GROUP_NOTIFICATIONS": "0"},
            ),
        ):
            payload = digest.send_digest(now=now, morning=False)

        self.assertEqual(payload["items"], [])
        self.assertNotIn("preserved_previous_news_pool", payload)
        self.assertEqual(write_json.call_args.args[0], digest.LATEST_PATH)
        self.assertEqual(write_json.call_args.args[1]["items"], [])

    def test_digest_card_only_covers_this_run_and_skips_deferred_backfill(self):
        now = datetime(2026, 8, 17, 15, 0, tzinfo=HKT)
        fresh_item = {
            "news_id": "NEWS-FRESH",
            "title": "本轮检索到的新闻",
            "url": "https://example.com/fresh",
            "source": "Example",
            "published_at": "2026-08-17T10:00:00+08:00",
            "module": "竞争对手",
            "keywords": ["HKT"],
            "snippet": "本轮新增。",
        }

        def _deferred_must_not_load(*args, **kwargs):
            raise AssertionError("digest 通报不得读取补审队列")

        with (
            mock.patch.object(
                digest,
                "_collect_news_with_late_index_retry",
                return_value=([fresh_item], [], {"agentic_search": {}}),
            ),
            mock.patch.object(digest, "_latest_timed_crawl", return_value={}),
            mock.patch.object(digest, "_write_json"),
            mock.patch.object(digest, "_send_card") as send_card,
            mock.patch.object(
                strategic_briefing,
                "_prepare_deferred_ai_candidates",
                side_effect=_deferred_must_not_load,
            ),
            mock.patch.dict(
                digest.os.environ,
                {"CMHK_STRATEGIC_GROUP_NOTIFICATIONS": "0"},
            ),
        ):
            payload = digest.send_digest(now=now, morning=False)
            cards = digest._build_cards(
                now=now,
                slot_label="下午全量",
                start_at=datetime(2026, 8, 17, 8, 0, tzinfo=HKT),
                end_at=now,
                items=[fresh_item],
                errors=[],
                crawl={},
            )

        card_text = json.dumps(cards, ensure_ascii=False)
        self.assertEqual(payload["message_ids"], [])
        self.assertEqual(send_card.call_count, 0)
        self.assertEqual([item["news_id"] for item in payload["items"]], ["NEWS-FRESH"])
        self.assertIn("本轮检索到的新闻", card_text)

    def test_digest_card_is_sent_only_to_the_project_group(self):
        responses = [{"data": {"message_id": "om_primary"}, "_identity": "bot"}]
        with mock.patch.object(
            strategic_briefing,
            "_lark_api",
            side_effect=responses,
        ) as lark_api:
            message_ids = digest._send_card(
                {
                    "header": {"title": {"content": "晨间通报"}},
                    "elements": [],
                }
            )

        self.assertEqual(message_ids, ["om_primary"])
        self.assertEqual(
            [call.kwargs["data"]["receive_id"] for call in lark_api.call_args_list],
            [strategic_briefing.PROJECT_CHAT_ID],
        )
        self.assertNotIn(
            strategic_briefing.REQUIREMENTS_CHAT_ID,
            strategic_briefing.TARGET_CHAT_IDS,
        )
        uuids = [call.kwargs["data"]["uuid"] for call in lark_api.call_args_list]
        self.assertEqual(len(set(uuids)), 1)

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
        self.assertEqual(
            call.call_args.kwargs["response_format"],
            digest.AGENTIC_SEARCH_RESPONSE_FORMAT,
        )
        self.assertIn("query最多180个字符", call.call_args.args[0])
        self.assertIn("香港监管政策和本地数字产业政策同列最高优先级", call.call_args.args[0])
        self.assertIn("自动驾驶测试与商业化", call.call_args.args[0])
        self.assertIn("口岸通关", call.call_args.args[0])

    def test_local_strategic_plans_target_hk_transport_and_cross_border_gaps(self):
        plans = digest._local_strategic_plans()

        self.assertEqual(len(plans), 2)
        self.assertTrue(all(plan["module"] == "香港本地新闻" for plan in plans))
        self.assertTrue(all(plan["semantic_relevance"] is True for plan in plans))
        self.assertTrue(all(plan["lookback_days"] == 7 for plan in plans))
        queries = " ".join(plan["query"] for plan in plans)
        self.assertIn("自动驾驶", queries)
        self.assertIn("蘿蔔快跑", queries)
        self.assertIn("皇崗口岸", queries)
        self.assertIn("一地兩檢", queries)

    def test_scheduled_crawl_signal_becomes_date_aware_search_plan(self):
        signal = {
            "signal_id": "SCN-HKT-AI",
            "crawl_run_id": "crawl-1",
            "config_row": "18",
            "monitor_object": "HKT / csl / 1O1O",
            "monitor_category": "重大动态/技术",
            "parent_url": "https://www.hkt.com/news/",
            "target_url": "https://www.hkt.com/news/2026/hkt-ai",
            "query": "HKT broad row label AI platform launch",
            "title": "HKT AI platform launch",
            "keywords": ["HKT", "AI"],
        }
        with (
            mock.patch.object(
                strategic_briefing,
                "_load_state",
                return_value={"scheduled_crawl_consumed_signal_ids": []},
            ),
            mock.patch(
                "scheduled_crawl_news_bridge.load_pending_signals",
                return_value={
                    "signals": [signal],
                    "expired_signal_ids": [],
                },
            ),
        ):
            plans, trace = digest._scheduled_crawl_plans(
                datetime(2026, 7, 28, 15, 0, tzinfo=HKT)
            )

        self.assertEqual(trace["pending_signal_count"], 1)
        self.assertEqual(trace["query_count"], 1)
        self.assertEqual(plans[0]["search_origin"], "scheduled_crawl_reference")
        self.assertEqual(plans[0]["canonical_competitor"], "HKT")
        self.assertEqual(plans[0]["query"], "HKT AI platform launch")
        self.assertEqual(plans[0]["fallback_query"], "HKT AI platform launch")
        self.assertEqual(plans[0]["lookback_days"], 3)
        self.assertEqual(plans[0]["scheduled_crawl_signal_id"], "SCN-HKT-AI")

    def test_scheduled_crawl_uses_headline_entity_over_aggregator_parent(self):
        signal = {
            "signal_id": "SCN-CHINA-MOBILE-RESULTS",
            "crawl_run_id": "crawl-finance",
            "config_row": "10",
            "monitor_object": "SmarTone",
            "monitor_category": "本地竞对财报",
            "parent_url": "https://www.aastocks.com/en/stocks/news/aafn",
            "target_url": "https://www.aastocks.com/en/stocks/news/aafn/NOW.1538114/2",
            "title": "CHINA MOBILE 1H26 Net Profit Drops; Interim DPS Hikes",
            "keywords": ["SmarTone", "CHINA", "MOBILE"],
        }
        with (
            mock.patch.object(strategic_briefing, "_load_state", return_value={}),
            mock.patch(
                "scheduled_crawl_news_bridge.load_pending_signals",
                return_value={"signals": [signal], "expired_signal_ids": []},
            ),
        ):
            plans, _ = digest._scheduled_crawl_plans(
                datetime(2026, 8, 14, 9, 0, tzinfo=HKT)
            )

        self.assertEqual(plans[0]["canonical_competitor"], "China Mobile")
        self.assertNotEqual(plans[0]["canonical_competitor"], "SmarTone")

    def test_search_executor_preserves_scheduled_crawl_provenance(self):
        plan = {
            "module": "重大动态/技术",
            "query": "HKT AI platform launch",
            "fallback_query": "HKT AI platform launch",
            "keywords": ["HKT", "AI"],
            "lookback_days": 3,
            "search_origin": "scheduled_crawl_reference",
            "scheduled_crawl_signal_id": "SCN-HKT-AI",
            "scheduled_crawl_config_row": "18",
        }
        found = {
            "title": "HKT推出AI平台",
            "url": "https://example.com/hkt-ai",
            "published_at": "2026-07-28T10:00:00+08:00",
        }
        with mock.patch.object(
            digest,
            "_google_news_search",
            return_value=[found],
        ) as search:
            items, errors, _ = digest._execute_search_plans(
                [plan],
                start_at=datetime(2026, 7, 28, 8, 0, tzinfo=HKT),
                end_at=datetime(2026, 7, 28, 15, 0, tzinfo=HKT),
            )

        self.assertEqual(errors, [])
        self.assertEqual(items[0]["scheduled_crawl_signal_id"], "SCN-HKT-AI")
        self.assertEqual(items[0]["scheduled_crawl_config_row"], "18")
        self.assertEqual(
            search.call_args.kwargs["admission_start_at"],
            datetime(2026, 7, 25, 15, 0, tzinfo=HKT),
        )

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

    def test_agentic_plan_forwards_semantic_results_without_literal_guard(self):
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
        semantic_items = digest._parse_news_feed(
            unrelated,
            **common,
            semantic_relevance=True,
            search_origin="agentic_expansion",
        )
        self.assertEqual(len(semantic_items), 1)
        self.assertFalse(semantic_items[0]["literal_keyword_match"])
        self.assertEqual(semantic_items[0]["keywords"], [])
        self.assertEqual(semantic_items[0]["query_keywords"], ["T-Mobile"])

    def test_local_semantic_result_without_literal_keyword_is_still_forwarded(self):
        raw = """<?xml version="1.0" encoding="UTF-8"?>
        <rss><channel><item>
          <title>香港智慧交通计划公布新一轮安排</title>
          <link>https://example.hk/news/smart-transport</link>
          <description>政府公布本地数字基础设施及公共服务安排。</description>
          <pubDate>Sat, 25 Jul 2026 09:00:00 +0800</pubDate>
          <source>香港新闻</source>
        </item></channel></rss>""".encode("utf-8")

        items = digest._parse_news_feed(
            raw,
            provider="google",
            module="香港政策与科技",
            keywords=["皇岗口岸"],
            base_query='"皇岗口岸" 数字基础设施',
            start_at=datetime(2026, 7, 25, 0, 0, tzinfo=HKT),
            end_at=datetime(2026, 7, 25, 15, 0, tzinfo=HKT),
            semantic_relevance=True,
            search_origin="agentic_expansion",
        )

        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["is_hong_kong"])
        self.assertTrue(items[0]["semantic_relevance"])
        self.assertFalse(items[0]["literal_keyword_match"])
        self.assertEqual(items[0]["keywords"], [])
        self.assertEqual(items[0]["query_keywords"], ["皇岗口岸"])

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
        self.assertEqual(plans[0]["lookback_days"], 0)

    def test_agentic_and_query_is_rewritten_to_or_intents(self):
        plans = digest._normalize_agentic_plans(
            {
                "queries": [
                    {
                        "module": "竞争对手",
                        "query": (
                            "HGC 环球全域电讯 环电 业绩 财报 营收 利润 亏损 "
                            "裁员 重组 投资 数据中心 云 合作 并购 管理层 人事"
                        ),
                        "keywords": ["HGC", "环球全域电讯", "环电"],
                        "intent": "经营动态",
                    }
                ]
            },
            phase="expansion",
            existing_queries=set(),
            limit=6,
        )

        self.assertEqual(len(plans), 1)
        query = plans[0]["query"]
        self.assertIn(" OR ", query)
        self.assertIn("HGC", query)
        self.assertLessEqual(query.count(" "), 16)
        self.assertNotIn("亏损 裁员 重组", query)

    def test_zero_result_agentic_plan_retries_simpler_query(self):
        calls = []

        def fake_search(plan, start_at, end_at, **kwargs):
            calls.append(plan["query"])
            if plan.get("agentic_zero_result_retry"):
                return [
                    {
                        "title": "HGC expands enterprise network",
                        "url": "https://example.com/hgc",
                    }
                ]
            return []

        with mock.patch.object(digest, "_google_news_search", side_effect=fake_search):
            items, errors, stats = digest._execute_search_plans(
                [
                    {
                        "module": "竞争对手",
                        "query": "HGC 业绩 财报 营收 利润 亏损 裁员 重组",
                        "fallback_query": "HGC 业绩 财报 营收 利润 亏损 裁员 重组",
                        "keywords": ["HGC", "环球全域电讯"],
                        "canonical_competitor": "HGC",
                        "search_origin": "agentic_followup",
                    }
                ],
                start_at=datetime(2026, 8, 17, 9, 0, tzinfo=HKT),
                end_at=datetime(2026, 8, 17, 15, 0, tzinfo=HKT),
            )

        self.assertEqual(errors, [])
        self.assertEqual(len(items), 1)
        self.assertEqual(stats["retry_count"], 1)
        self.assertEqual(stats["retry_result_count"], 1)
        self.assertGreaterEqual(len(calls), 2)
        self.assertIn(" OR ", calls[1])

    def test_compacted_query_keeps_subject_group_mandatory(self):
        compacted = digest._compact_agentic_query(
            "HGC 环球全域电讯 环电 业绩 财报 营收 利润 亏损 裁员 重组 投资 合作",
            ["HGC", "环球全域电讯", "环电"],
        )

        # "A OR B (intent)" lets a bare "A" satisfy the whole query and floods
        # the pool with unrelated news, so the subject group must be bracketed.
        self.assertTrue(compacted.startswith("("))
        self.assertRegex(compacted, r"^\([^()]+\)\s*\([^()]+\)$")
        self.assertFalse(digest._has_unguarded_top_level_or(compacted))

    def test_or_soup_planner_query_is_rewritten_with_mandatory_subject(self):
        plans = digest._normalize_agentic_plans(
            {
                "queries": [
                    {
                        "module": "竞争对手",
                        "query": "3HK OR 3香港 OR 和记电讯 5G 资费 OR 促销 OR 合作",
                        "keywords": ["3 Hong Kong", "3HK"],
                        "intent": "经营动态",
                    }
                ]
            },
            phase="followup",
            existing_queries=set(),
            limit=1,
        )

        self.assertEqual(len(plans), 1)
        self.assertFalse(digest._has_unguarded_top_level_or(plans[0]["query"]))

    def test_deterministic_gap_query_brackets_its_subject(self):
        query = digest._deterministic_gap_query(["HGC", "环球全域电讯"])

        self.assertRegex(query, r"^\([^()]+\)\s*\([^()]+\)$")
        self.assertFalse(digest._has_unguarded_top_level_or(query))

    def test_ungrounded_agentic_results_are_dropped_before_ai_review(self):
        competitor_plan = {
            "module": "竞争对手",
            "query": "(SmarTone OR 数码通) (业绩 OR 5G)",
            "keywords": ["SmarTone", "数码通"],
            "canonical_competitor": "SmarTone",
            "search_origin": "agentic_followup",
        }
        on_topic = {"title": "数码通公布全年业绩", "snippet": "SmarTone 全年收入上升。"}
        off_topic = {"title": "中年好聲音4淘汰賽", "snippet": "歌唱比賽最新一集。"}

        self.assertTrue(digest._agentic_result_is_grounded(competitor_plan, on_topic))
        self.assertFalse(digest._agentic_result_is_grounded(competitor_plan, off_topic))
        self.assertTrue(
            digest._agentic_result_is_grounded(
                competitor_plan,
                {
                    "title": "本地电讯商上调全年派息指引",
                    "snippet": "管理层称企业方案需求回升。",
                    "semantic_relevance": True,
                },
            )
        )

        # One planner term is enough. Extra noise is preferred over a miss;
        # AI review still decides what reaches the human sheet.
        policy_plan = {
            "module": "政策/法规类",
            "query": "(香港 OR 智慧交通) (测试 OR 口岸 OR 通关)",
            "keywords": ["香港", "智慧交通"],
            "search_origin": "agentic_expansion",
        }
        border = {"title": "新皇崗口岸港方口岸區測試", "snippet": "當局指發現需要改善。"}
        one_broad_term = {"title": "香港測量師學會大獎2026", "snippet": "西半山豪宅獲獎。"}
        one_generic_intent = {
            "title": "iQOO Neo 11 相機測試",
            "snippet": "手機鏡頭樣張曝光。",
        }
        unrelated = {"title": "某綜藝節目淘汰賽", "snippet": "歌唱比賽最新一集。"}

        self.assertTrue(digest._agentic_result_is_grounded(policy_plan, border))
        self.assertTrue(
            digest._agentic_result_is_grounded(policy_plan, one_broad_term)
        )
        self.assertTrue(
            digest._agentic_result_is_grounded(policy_plan, one_generic_intent)
        )
        self.assertFalse(digest._agentic_result_is_grounded(policy_plan, unrelated))

    def test_fixed_monitoring_results_keep_full_recall(self):
        fixed_plan = {
            "module": "竞争对手",
            "query": "SmarTone",
            "keywords": ["SmarTone"],
            "search_origin": "monitoring_sheet_keyword_search",
        }

        self.assertTrue(
            digest._agentic_result_is_grounded(
                fixed_plan,
                {"title": "完全无关的新闻", "snippet": "与监控词无关。"},
            )
        )

    def test_execute_search_plans_reports_dropped_noise(self):
        plan = {
            "module": "竞争对手",
            "query": "(HGC OR 环球全域电讯) (业绩 OR 合作)",
            "keywords": ["HGC", "环球全域电讯"],
            "canonical_competitor": "HGC",
            "search_origin": "agentic_expansion",
        }
        results = [
            {
                "news_id": "NEWS-1",
                "title": "HGC 宣布企业网络合作",
                "snippet": "环球全域电讯与客户签约。",
                "published_at": "2026-08-17T10:00:00+08:00",
            },
            {
                "news_id": "NEWS-2",
                "title": "某綜藝節目淘汰賽",
                "snippet": "與電訊業無關。",
                "published_at": "2026-08-17T10:30:00+08:00",
            },
        ]
        with mock.patch.object(digest, "_google_news_search", return_value=results):
            items, errors, stats = digest._execute_search_plans(
                [plan],
                start_at=datetime(2026, 8, 17, 8, 0, tzinfo=HKT),
                end_at=datetime(2026, 8, 17, 15, 0, tzinfo=HKT),
            )

        self.assertEqual(errors, [])
        self.assertEqual([item["news_id"] for item in items], ["NEWS-1"])
        self.assertEqual(stats["ungrounded_dropped_count"], 1)

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

    def test_agentic_plan_removes_malformed_site_exclusion(self):
        plans = digest._normalize_agentic_plans(
            {
                "queries": [
                    {
                        "module": "竞争对手",
                        "query": (
                            "SmarTone OR 数码通 -site:smar tone.com.hk "
                            "(5G OR 网络建设)"
                        ),
                        "keywords": ["SmarTone", "数码通"],
                        "intent": "网络建设",
                    }
                ]
            },
            phase="followup",
            existing_queries=set(),
            limit=1,
        )

        self.assertEqual(len(plans), 1)
        self.assertNotIn("site:", plans[0]["query"])
        self.assertNotIn("tone.com.hk", plans[0]["query"])
        self.assertIn("网络建设", plans[0]["query"])

    def test_target_planner_uses_deterministic_fallback_after_all_failures(self):
        with mock.patch.object(
            strategic_briefing,
            "_call_internal_ai",
            return_value={
                "sufficient": False,
                "assessment": "仍有缺口",
                "queries": [],
            },
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

        self.assertEqual(call.call_count, digest.AGENTIC_AI_ATTEMPTS)
        self.assertEqual(trace["status"], "fallback")
        self.assertEqual(plans[0]["canonical_competitor"], "HGC")
        self.assertIn("网络建设", plans[0]["query"])

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
            mock.patch.object(digest, "_local_strategic_plans", return_value=[]),
            mock.patch.object(
                digest,
                "_scheduled_crawl_plans",
                return_value=([], {"pending_signal_count": 0, "query_count": 0, "error": ""}),
            ),
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

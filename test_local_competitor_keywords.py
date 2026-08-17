import unittest
import xml.etree.ElementTree as ET
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

import local_competitor_keywords as competitors
import news_discovery_digest as digest
import news_discovery_vote_digest as vote_digest
import news_review_sheet as review_sheet
import strategic_briefing


HKT = ZoneInfo("Asia/Hong_Kong")
YAHOO_TAP_AND_GO_URL = (
    "https://hk.finance.yahoo.com/news/"
    "tap-%E6%8B%8D%E4%BD%8F%E8%B3%9E-"
    "%E6%8E%A8%E5%87%BA%E5%85%A8%E6%B8%AF%E9%A6%96%E5%BC%B5"
    "%E5%80%8B%E4%BA%BA-single-card-120657369.html"
)


class LocalCompetitorKeywordTests(unittest.TestCase):
    def test_every_fixed_group_is_compact_and_has_canonical_entity(self):
        groups = competitors.mandatory_search_groups()
        canonicals = {group["canonical"] for group in groups}

        self.assertEqual(
            canonicals,
            {
                "HKT",
                "HKBN",
                "SmarTone",
                "3 Hong Kong",
                "HGC",
                "i-CABLE",
                "China Mobile",
                "China Telecom Global (Hong Kong)",
                "China Unicom Hong Kong",
            },
        )
        self.assertTrue(all(1 <= len(group["terms"]) <= 5 for group in groups))
        self.assertEqual(competitors.priority_for("HKT"), 0)

    def test_article_content_resolves_every_named_competitor(self):
        self.assertEqual(
            competitors.canonical_competitors_for_text(
                "中国移动公布2026年中期业绩，中国联通同步更新经营数据"
            ),
            ("China Mobile", "China Unicom Hong Kong"),
        )

    def test_global_cap_never_drops_recognized_competitor_items(self):
        published_at = "2026-08-14T08:00:00+08:00"
        competitor_items = []
        for group in competitors.LOCAL_COMPETITORS:
            canonical = group["canonical"]
            for index in range(3):
                competitor_items.append(
                    {
                        "news_id": f"{canonical}-{index}",
                        "title": f"{canonical} results update {index}",
                        "snippet": "latest operating result",
                        "published_at": published_at,
                        "module": "竞争对手",
                        "canonical_competitor": canonical,
                    }
                )
        generic_items = [
            {
                "news_id": f"generic-{index}",
                "title": f"General technology news {index}",
                "snippet": "industry update",
                "published_at": published_at,
                "module": "科技/技术",
            }
            for index in range(150)
        ]

        selected, trace = digest._select_discovery_results(
            generic_items + competitor_items,
            module_order={"竞争对手": 0, "科技/技术": 1},
        )

        selected_ids = {item["news_id"] for item in selected}
        self.assertEqual(len(selected), len(generic_items) + len(competitor_items))
        self.assertTrue(
            {item["news_id"] for item in competitor_items}.issubset(selected_ids)
        )
        self.assertEqual(trace["recognized_competitor_dropped_count"], 0)
        self.assertEqual(trace["pre_ai_dropped_count"], 0)
        self.assertTrue(trace["full_recall_mode"])
        self.assertIn("China Mobile", trace["competitor_counts"])

    def test_competitor_items_expand_cap_instead_of_being_dropped(self):
        competitor_items = [
            {
                "news_id": f"hkt-{index}",
                "title": f"HKT operating update {index}",
                "snippet": "HKT result",
                "published_at": "2026-08-14T08:00:00+08:00",
                "module": "竞争对手",
                "canonical_competitor": "HKT",
            }
            for index in range(121)
        ]
        competitor_items.append(
            {
                "news_id": "china-mobile-results",
                "title": "中国移动公布2026年中期业绩",
                "snippet": "净利润及派息更新",
                "published_at": "2026-08-14T08:01:00+08:00",
                "module": "竞争对手",
            }
        )

        selected, trace = digest._select_discovery_results(
            competitor_items,
            module_order={"竞争对手": 0},
        )

        self.assertEqual(len(selected), 122)
        self.assertIn(
            "china-mobile-results",
            {item["news_id"] for item in selected},
        )
        self.assertEqual(trace["recognized_competitor_dropped_count"], 0)

    def test_new_sheet_competitor_is_protected_before_fixed_alias_update(self):
        future_competitor = {
            "news_id": "future-tel-result",
            "title": "FutureTel publishes interim results",
            "snippet": "FutureTel revenue increased",
            "published_at": "2026-08-14T08:01:00+08:00",
            "module": "竞争对手",
            "keywords": ["FutureTel"],
            "literal_keyword_match": True,
        }
        generic_items = [
            {
                "news_id": f"generic-{index}",
                "title": f"General technology news {index}",
                "snippet": "industry update",
                "published_at": "2026-08-14T08:00:00+08:00",
                "module": "科技/技术",
            }
            for index in range(130)
        ]

        selected, trace = digest._select_discovery_results(
            generic_items + [future_competitor],
            module_order={"竞争对手": 0, "科技/技术": 1},
        )

        self.assertIn("future-tel-result", {item["news_id"] for item in selected})
        self.assertEqual(
            future_competitor["monitored_competitor_terms"],
            ["FutureTel"],
        )
        self.assertEqual(trace["competitor_counts"]["监测词:FutureTel"], 1)

    def test_non_competitor_modules_are_not_silently_truncated(self):
        items = [
            {
                "news_id": f"policy-{index}",
                "title": f"Policy update {index}",
                "snippet": "regulatory development",
                "published_at": "2026-08-14T08:00:00+08:00",
                "module": "政策/法规类",
                "search_origin": "monitoring_sheet_keyword_search",
            }
            for index in range(145)
        ]

        selected, trace = digest._select_discovery_results(
            items,
            module_order={"政策/法规类": 0},
        )

        self.assertEqual(len(selected), 145)
        self.assertEqual(trace["pre_ai_dropped_count"], 0)
        self.assertEqual(trace["module_counts"]["政策/法规类"], 145)

    def test_hkt_fixed_terms_cover_tap_and_go_chinese_and_english(self):
        hkt_terms = {
            term
            for group in competitors.mandatory_search_groups()
            if group["canonical"] == "HKT"
            for term in group["terms"]
        }
        self.assertTrue(
            {"Tap & Go", "拍住賞", "拍住赏", "HKT Payment"}.issubset(hkt_terms)
        )

    def test_mandatory_plans_do_not_depend_on_monitoring_sheet(self):
        plans = digest._mandatory_competitor_plans()
        tap_plan = next(
            plan for plan in plans if "拍住賞" in plan["keywords"]
        )

        self.assertEqual(tap_plan["canonical_competitor"], "HKT")
        self.assertEqual(tap_plan["search_origin"], "mandatory_local_competitor")
        self.assertIn('"Tap & Go"', tap_plan["query"])

    def test_tap_and_go_feed_item_is_tagged_as_hkt(self):
        raw = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss><channel><item>
          <title>TAP &amp; GO launches Hong Kong's first personal Single Card</title>
          <link>{YAHOO_TAP_AND_GO_URL}</link>
          <description>Tap &amp; Go introduces a new payment card in Hong Kong.</description>
          <pubDate>Thu, 23 Jul 2026 13:06:00 +0800</pubDate>
          <source>Yahoo Finance Hong Kong</source>
        </item></channel></rss>"""
        # Guard the fixture separately so failures are clearly XML-related.
        raw = raw.replace(b"{YAHOO_TAP_AND_GO_URL}", YAHOO_TAP_AND_GO_URL.encode())
        ET.fromstring(raw)
        items = digest._parse_news_feed(
            raw,
            provider="google",
            module="竞争对手",
            keywords=["Tap & Go", "拍住賞", "HKT Payment"],
            base_query='"Tap & Go" OR "拍住賞" OR "HKT Payment"',
            start_at=datetime(2026, 7, 23, 0, 0, tzinfo=HKT),
            end_at=datetime(2026, 7, 24, 9, 0, tzinfo=HKT),
            canonical_competitor="HKT",
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["canonical_competitor"], "HKT")
        self.assertEqual(items[0]["url"], YAHOO_TAP_AND_GO_URL)
        self.assertEqual(items[0]["search_origin"], "mandatory_local_competitor")
        self.assertEqual(items[0]["search_provider"], "google")
        self.assertEqual(
            review_sheet._information_flow(items[0]),
            "后台固定竞对词库（HKT；命中：HKT、Tap & Go） → Google News搜索",
        )
        self.assertEqual(items[0]["keywords"][0], "HKT")
        self.assertTrue(items[0]["is_hong_kong"])
        self.assertEqual(items[0]["search_date"], "2026-07-24")
        self.assertEqual(
            items[0]["search_window_start"],
            "2026-07-23T00:00:00+08:00",
        )
        self.assertTrue(review_sheet._review_news_candidate(items[0])[0])

    def test_ampersand_brand_name_matches_title(self):
        self.assertTrue(
            digest._term_matches(
                "TAP & GO launches a new payment product",
                "Tap & Go",
            )
        )

    def test_cross_day_candidate_without_explicit_window_stays_rejected(self):
        keep, reason = review_sheet._review_news_candidate(
            {
                "title": "Tap & Go launches a new payment product",
                "snippet": "HKT payment service news in Hong Kong",
                "url": YAHOO_TAP_AND_GO_URL,
                "published_at": "2026-07-23T13:06:00+08:00",
                "search_date": "2026-07-24",
                "keywords": ["HKT", "Tap & Go"],
            }
        )

        self.assertFalse(keep)
        self.assertEqual(reason, "不在明确检索时间窗口")

    def test_fixed_searches_continue_when_monitoring_sheet_is_unavailable(self):
        with (
            mock.patch.object(
                strategic_briefing,
                "read_monitoring_spec",
                side_effect=RuntimeError("sheet unavailable"),
            ),
            mock.patch.object(digest, "_google_news_search", return_value=[]),
            mock.patch.object(
                digest,
                "_scheduled_crawl_plans",
                return_value=([], {"pending_signal_count": 0, "query_count": 0, "error": ""}),
            ),
        ):
            items, errors, spec = digest.collect_news(
                datetime(2026, 7, 24, 0, 0, tzinfo=HKT),
                datetime(2026, 7, 24, 15, 0, tzinfo=HKT),
            )

        self.assertEqual(items, [])
        self.assertTrue(spec["fixed_competitor_fallback"])
        self.assertTrue(
            any("已继续执行后台固定竞对词库" in error for error in errors)
        )

    def test_agentic_lookback_does_not_expand_admission_window(self):
        admission_start = datetime(2026, 7, 26, 8, 0, tzinfo=HKT)
        admission_end = datetime(2026, 7, 26, 15, 0, tzinfo=HKT)
        calls = []

        def fake_search(plan, start_at, end_at, **kwargs):
            calls.append((plan, start_at, end_at, kwargs))
            return []

        with mock.patch.object(digest, "_google_news_search", side_effect=fake_search):
            digest._execute_search_plans(
                [
                    {
                        "module": "竞争对手",
                        "query": "HKT",
                        "keywords": ["HKT"],
                        "lookback_days": 7,
                    }
                ],
                start_at=admission_start,
                end_at=admission_end,
            )

        self.assertEqual(calls[0][1], datetime(2026, 7, 19, 15, 0, tzinfo=HKT))
        self.assertEqual(calls[0][3]["admission_start_at"], admission_start)
        self.assertEqual(calls[0][3]["admission_end_at"], admission_end)

    def test_collect_news_rejects_old_item_returned_by_agentic_provider(self):
        admission_start = datetime(2026, 7, 26, 8, 0, tzinfo=HKT)
        admission_end = datetime(2026, 7, 26, 15, 0, tzinfo=HKT)
        stale_item = {
            "news_id": "NEWS-20260721-stale",
            "title": "HKT launches an AI service",
            "url": "https://example.com/hkt-ai",
            "source": "Example",
            "published_at": "2026-07-21T09:00:00+08:00",
            "search_date": "2026-07-26",
            "search_window_start": "2026-07-19T15:00:00+08:00",
            "search_window_end": "2026-07-26T15:00:00+08:00",
            "module": "竞争对手",
            "keywords": ["HKT"],
            "search_origin": "agentic_expansion",
        }
        with (
            mock.patch.object(
                strategic_briefing,
                "read_monitoring_spec",
                return_value={"revision": "test", "modules": []},
            ),
            mock.patch.object(strategic_briefing, "_query_plans", return_value=[]),
            mock.patch.object(
                digest,
                "_scheduled_crawl_plans",
                return_value=([], {"pending_signal_count": 0, "query_count": 0, "error": ""}),
            ),
            mock.patch.object(
                digest,
                "_execute_search_plans",
                side_effect=[([stale_item], [], {}), ([], [], {})],
            ),
            mock.patch.object(
                digest,
                "_call_agentic_search_agent",
                return_value=([], {"status": "ok", "sufficient": True}),
            ),
        ):
            items, _, spec = digest.collect_news(admission_start, admission_end)

        self.assertEqual(items, [])
        self.assertEqual(
            spec["agentic_search"]["admission_gate"]["rejected_count"],
            1,
        )

    def test_morning_window_covers_previous_afternoon_publication_window(self):
        start_at, end_at = digest._window(
            datetime(2026, 7, 27, 9, 16, tzinfo=HKT),
            True,
        )

        self.assertEqual(start_at, datetime(2026, 7, 26, 8, 0, tzinfo=HKT))
        self.assertEqual(end_at, datetime(2026, 7, 27, 9, 16, tzinfo=HKT))


if __name__ == "__main__":
    unittest.main()

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
                "China Telecom Global (Hong Kong)",
                "China Unicom Hong Kong",
            },
        )
        self.assertTrue(all(1 <= len(group["terms"]) <= 5 for group in groups))
        self.assertEqual(competitors.priority_for("HKT"), 0)

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
            "后台固定竞对词库 → Google News搜索",
        )
        self.assertEqual(items[0]["keywords"][0], "HKT")
        self.assertTrue(items[0]["is_hong_kong"])
        self.assertFalse(vote_digest._is_noise(items[0]))
        self.assertEqual(items[0]["search_date"], "2026-07-24")
        self.assertEqual(
            items[0]["search_window_start"],
            "2026-07-23T00:00:00+08:00",
        )
        self.assertTrue(review_sheet._review_news_candidate(items[0])[0])
        self.assertEqual(
            review_sheet._competitor_relevance(items[0]),
            (True, "香港直接竞对新闻"),
        )

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


if __name__ == "__main__":
    unittest.main()

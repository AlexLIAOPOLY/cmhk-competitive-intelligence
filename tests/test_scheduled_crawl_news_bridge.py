from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import crawl
import scheduled_crawl_news_bridge as bridge
import strategic_briefing


HKT = ZoneInfo("Asia/Hong_Kong")


class CrawlNewsLinkExtractionTests(unittest.TestCase):
    def test_extracts_article_links_and_ignores_non_news_navigation(self) -> None:
        raw = b"""
        <html><body>
          <a href="/products/mobile">Mobile plans</a>
          <a href="/news/">Newsroom</a>
          <a href="/news/2026/tap-and-go-single-card">Tap &amp; Go launches Single Card</a>
        </body></html>
        """
        links = crawl.extract_news_links(
            raw,
            "text/html; charset=utf-8",
            "https://www.hkt.example/",
        )
        urls = {item["url"] for item in links}
        self.assertIn(
            "https://www.hkt.example/news/2026/tap-and-go-single-card",
            urls,
        )
        self.assertNotIn("https://www.hkt.example/products/mobile", urls)


class ScheduledCrawlBridgeTests(unittest.TestCase):
    def _write_crawl(
        self,
        root: Path,
        links: list[dict[str, str]],
    ) -> None:
        (root / "sources.json").write_text(
            json.dumps(
                [
                    {
                        "row": "4",
                        "object": "HKT / csl / 1O1O",
                        "package": "重大动态/技术",
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (root / "run_log.json").write_text(
            json.dumps(
                [
                    {
                        "row": 4,
                        "url": "https://www.hkt.example/news/",
                        "final_url": "https://www.hkt.example/news/",
                        "http_status": 200,
                        "title": "HKT Newsroom",
                        "content_hash": "hash-current",
                        "error": "",
                        "discovered_news_links": links,
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def test_bootstrap_then_emits_only_new_article_link(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bridge_dir = root / "strategy_briefing" / "scheduled_crawl_bridge"
            old_link = {
                "url": "https://www.hkt.example/news/2026/old-release",
                "title": "HKT old release",
            }
            self._write_crawl(root, [old_link])
            first = bridge.capture_completed_crawl(
                "crawl-1",
                [4],
                captured_at=datetime(2026, 7, 24, 3, 30, tzinfo=HKT),
                root=root,
                bridge_dir=bridge_dir,
            )
            self.assertTrue(first["bootstrap"])
            self.assertEqual(first["signal_count"], 0)

            new_link = {
                "url": "https://www.hkt.example/news/2026/tap-and-go-single-card",
                "title": "Tap & Go launches Single Card",
            }
            self._write_crawl(root, [old_link, new_link])
            second = bridge.capture_completed_crawl(
                "crawl-2",
                [4],
                captured_at=datetime(2026, 7, 25, 3, 30, tzinfo=HKT),
                root=root,
                bridge_dir=bridge_dir,
            )
            self.assertFalse(second["bootstrap"])
            self.assertEqual(second["signal_count"], 1)

            pending = bridge.load_pending_signals(
                {},
                datetime(2026, 7, 25, 9, 0, tzinfo=HKT),
                bridge_dir=bridge_dir,
            )
            self.assertEqual(len(pending["signals"]), 1)
            signal = pending["signals"][0]
            self.assertEqual(signal["config_row"], "4")
            self.assertEqual(
                signal["target_url"],
                "https://www.hkt.example/news/2026/tap-and-go-single-card",
            )
            self.assertIn("HKT", signal["query"])
            self.assertIn("Tap & Go", signal["query"])

    def test_signal_attempts_retry_then_resolve(self) -> None:
        state: dict[str, object] = {}
        for _ in range(3):
            result = bridge.commit_signal_attempts(
                state,
                ["SCN-ONE"],
                [],
                [],
                max_attempts=4,
            )
            self.assertEqual(result["consumed"], 0)
        result = bridge.commit_signal_attempts(
            state,
            ["SCN-ONE"],
            [],
            [],
            max_attempts=4,
        )
        self.assertEqual(result["consumed"], 1)
        self.assertIn("SCN-ONE", state["scheduled_crawl_consumed_signal_ids"])


class StrategicBriefingBridgeTests(unittest.TestCase):
    def test_signal_search_result_is_added_with_provenance(self) -> None:
        now = datetime(2026, 7, 25, 9, 0, tzinfo=HKT)
        gathered: dict[str, dict[str, object]] = {}
        signal = {
            "signal_id": "SCN-TAPGO",
            "crawl_run_id": "crawl-2",
            "config_row": "4",
            "monitor_object": "HKT / csl / 1O1O",
            "monitor_category": "重大动态/技术",
            "parent_url": "https://www.hkt.example/news/",
            "target_url": "https://www.hkt.example/news/2026/tap-and-go-single-card",
            "title": "Tap & Go launches Single Card",
            "query": "HKT Tap & Go Single Card",
            "keywords": ["HKT", "Tap & Go", "拍住赏"],
            "discovered_at": "2026-07-25T03:30:00+08:00",
        }
        result = {
            "title": "Tap & Go拍住赏推出全港首张个人Single Card",
            "url": "https://hk.finance.yahoo.com/news/tap-go-single-card.html",
            "snippet": "HKT旗下Tap & Go拍住赏推出个人Single Card。",
            "source": "Yahoo Finance Hong Kong",
            "date": "2026-07-25T08:00:00+08:00",
        }
        with mock.patch.object(
            strategic_briefing,
            "_search_recent",
            return_value=[result],
        ):
            stats = strategic_briefing._merge_scheduled_crawl_signals(
                gathered,
                [signal],
                now,
            )

        self.assertEqual(stats["signal_count"], 1)
        self.assertEqual(stats["search_result_count"], 1)
        candidate = next(iter(gathered.values()))
        self.assertEqual(candidate["search_origin"], "scheduled_crawl_reference")
        self.assertEqual(candidate["scheduled_crawl_signal_id"], "SCN-TAPGO")
        self.assertEqual(candidate["canonical_competitor"], "HKT")
        self.assertIn("定时爬虫第4行", candidate["why"])


if __name__ == "__main__":
    unittest.main()

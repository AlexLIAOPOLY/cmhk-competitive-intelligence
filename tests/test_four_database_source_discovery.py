from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import four_database_source_discovery as discovery


class FourDatabaseSourceDiscoveryTests(unittest.TestCase):
    def test_previous_day_references_use_only_two_completed_batches_dedupe_and_report_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runs_dir = root / "strategy_briefing" / "runs"
            runs_dir.mkdir(parents=True)

            def write_run(name: str, scanned_at: str, urls: list[str], status: str = "completed") -> None:
                (runs_dir / name).write_text(json.dumps({
                    "scanned_at": scanned_at,
                    "status": status,
                    "news_discovery": {"items": [{"title": url, "url": url} for url in urls]},
                    "candidates": [],
                }), encoding="utf-8")

            write_run("2026-09-01@06-00.json", "2026-09-01T06:00:00+08:00", ["https://old.example/should-not-count"])
            first_urls = [f"https://example.com/a-{index}" for index in range(160)]
            second_urls = ["https://example.com/a-0", *[f"https://example.com/b-{index}" for index in range(159)]]
            write_run("2026-09-01@07-30.json", "2026-09-01T07:30:00+08:00", first_urls)
            write_run("2026-09-01@14-00.json", "2026-09-01T14:00:00+08:00", second_urls)
            write_run("2026-09-01@15-00-failed.json", "2026-09-01T15:00:00+08:00", ["https://failed.example/"], status="failed")

            with patch.object(discovery, "ROOT", root):
                run_names, references, unique_total = discovery._previous_day_news_references(
                    discovery.datetime(2026, 9, 2, 1, 0, tzinfo=discovery.HKT)
                )

        self.assertEqual(run_names, ["2026-09-01@07-30.json", "2026-09-01@14-00.json"])
        self.assertEqual(unique_total, 319)
        self.assertEqual(len(references), 300)
        self.assertNotIn("https://old.example/should-not-count", {item["url"] for item in references})

    def test_actual_search_queries_cover_all_metric_families_and_aliases(self) -> None:
        plans = discovery._build_search_plans()

        self.assertEqual(
            len(plans),
            len(discovery.NEWS_ENTITY_SOURCES) * len(discovery.DISCLOSURE_SEARCH_GROUPS),
        )
        self.assertTrue(all("fallback_query" not in plan for plan in plans))
        self.assertTrue(all(plan["lookback_days"] == discovery.DISCOVERY_LOOKBACK_DAYS for plan in plans))
        for entity in {plan["entity"] for plan in plans}:
            entity_plans = [plan for plan in plans if plan["entity"] == entity]
            self.assertEqual(
                {plan["disclosure_type"] for plan in entity_plans},
                set(discovery.DISCLOSURE_SEARCH_GROUPS),
            )
            combined_queries = " ".join(plan["query"] for plan in entity_plans)
            for terms in discovery.DISCLOSURE_SEARCH_GROUPS.values():
                for term in terms:
                    self.assertIn(term, combined_queries)
        hkt = next(plan for plan in plans if plan["entity"] == "HKT")
        self.assertIn('"香港电讯"', hkt["query"])
        self.assertIn('"香港電訊"', hkt["query"])
        icable = next(plan for plan in plans if plan["entity"] == "i-CABLE")
        self.assertIn('"CTF Media & Entertainment"', icable["query"])
        entities = {plan["entity"] for plan in plans}
        self.assertTrue({
            "CMHK", "HGC", "Singtel", "KT", "NTT Docomo", "Reliance Jio",
            "中国铁塔", "中国广电", "China Mobile Cloud",
        }.issubset(entities))
        self.assertEqual(len(entities), 41)

    def test_search_audit_keeps_per_domain_queries_results_and_zero_result_reason(self) -> None:
        plans = [
            {"module": "四库资料/local", "domain": "local", "entity": "HKT", "query": "full HKT", "fallback_query": "HKT earnings", "lookback_days": 2},
            {"module": "四库资料/international", "domain": "international", "entity": "AT&T", "query": "full AT&T", "fallback_query": "AT&T earnings", "lookback_days": 2},
        ]
        items = [{
            "module": "四库资料/international", "query": "AT&T earnings", "title": "AT&T result",
            "source": "Example News", "url": "https://example.com/att", "published_at": "2026-08-26T00:30:00+08:00",
            "search_provider": "google",
        }]
        signals = [{"domain": "international", "entity": "AT&T", "news_url": "https://example.com/att"}]

        audit = discovery._search_audit(plans, items, signals)

        self.assertEqual(audit["domains"]["local"]["zero_result_query_count"], 1)
        self.assertEqual(audit["domains"]["international"]["result_count"], 1)
        self.assertEqual(audit["queries"][1]["status"], "searched_with_results")
        self.assertEqual(audit["results"][0]["entity"], "AT&T")
        self.assertTrue(audit["results"][0]["handoff"])
        self.assertEqual(audit["results"][0]["disposition"], "已形成线索，交接03:00追官方原文")

    def test_signal_builder_scopes_results_to_query_entity(self) -> None:
        plans = discovery._build_search_plans()
        plan = next(
            item for item in plans
            if item["entity"] == "中国电信" and item["disclosure_type"] == "financial_results"
        )
        items = [{
            "module": "四库资料/mainland",
            "query": plan["query"],
            "title": "China Telecom earnings compare China Unicom revenue",
            "url": "https://example.com/china-telecom-results",
        }]

        signals = discovery._build_signals(plans, items, [])

        self.assertEqual([(item["domain"], item["entity"]) for item in signals], [("mainland", "中国电信")])
        self.assertEqual(signals[0]["disclosure_type"], "financial_results")

    def test_signal_builder_rejects_valuation_pages(self) -> None:
        plans = discovery._build_search_plans()
        plan = next(item for item in plans if item["entity"] == "Orange")
        items = [{
            "module": "四库资料/international",
            "query": plan["query"],
            "title": "Orange enterprise value to EBITDA forward",
            "url": "https://example.com/orange-valuation",
        }]

        self.assertEqual(discovery._build_signals(plans, items, []), [])

    def test_readable_audit_events_include_every_domain_query_result_and_handoff(self) -> None:
        payload = {
            "generated_at_hkt": "2026-08-26T01:00:00+08:00", "query_count": 2,
            "search_result_count": 1, "previous_day_reference_count": 0, "signal_count": 1, "errors": [],
            "search_audit": {
                "domains": {key: {"label": label, "query_count": int(key in {"local", "international"}), "result_count": int(key == "international"), "signal_count": int(key == "international"), "zero_result_query_count": int(key == "local"), "status": "测试状态"} for key, label in discovery.DOMAIN_LABELS.items()},
                "queries": [{"domain": "local", "entity": "HKT", "query": "HKT earnings", "lookback_days": 2, "result_count": 0, "status": "无结果"}],
                "results": [{"domain": "international", "entity": "AT&T", "title": "AT&T result", "source": "Example News", "url": "https://example.com/att", "published_at": "2026-08-26T00:30:00+08:00", "provider": "google", "disposition": "仅作搜索线索，不直接入库"}],
            },
            "signals": [{"domain": "international", "entity": "AT&T", "title": "AT&T result", "news_url": "https://example.com/att", "official_followup_urls": ["https://investors.att.com/"]}],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "run.jsonl"
            discovery._append_readable_audit_events(path, payload)
            events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(sum(event["type"] == "source_discovery_domain" for event in events), 4)
        self.assertTrue(any(event["type"] == "source_discovery_query" and event["entity"] == "HKT" for event in events))
        self.assertTrue(any(event["type"] == "source_discovery_result" and event["url"] == "https://example.com/att" for event in events))
        self.assertTrue(any(event["type"] == "source_discovery_handoff" and event["official_followup_urls"] for event in events))


if __name__ == "__main__":
    unittest.main()

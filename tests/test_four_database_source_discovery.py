from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import four_database_source_discovery as discovery


class FourDatabaseSourceDiscoveryTests(unittest.TestCase):
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

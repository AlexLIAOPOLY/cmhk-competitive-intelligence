from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import crawl


class CrawlRecoveryTests(unittest.TestCase):
    def test_dns_failure_detection_includes_nested_attempts(self):
        result = {
            "status": 0,
            "error": "",
            "fetch_attempts": [
                {"error": "curl: (6) Could not resolve host: example.com"}
            ],
        }
        self.assertTrue(crawl.is_dns_failure(result))
        self.assertFalse(crawl.is_dns_failure({"status": 403, "error": "Forbidden"}))

    def test_fetch_url_stops_duplicate_user_agent_retries_after_dns_failure(self):
        dns_result = {
            "url": "https://example.com/data",
            "final_url": "https://example.com/data",
            "status": 0,
            "content_type": "",
            "bytes": 0,
            "title": "",
            "text": "",
            "error": "curl: (6) Could not resolve host: example.com",
        }
        with (
            mock.patch.object(
                crawl,
                "compliance_decision",
                return_value={
                    "compliance_allowed": True,
                    "policy": "allow",
                    "type": "test",
                    "jurisdiction": "test",
                    "tos_status": "test",
                    "robots_status": "checked",
                    "robots_allowed": True,
                },
            ),
            mock.patch.object(
                crawl,
                "fetch_with_httpx",
                side_effect=RuntimeError("temporary DNS failure"),
            ),
            mock.patch.object(
                crawl,
                "fetch_with_curl",
                return_value=dns_result,
            ) as curl_fetch,
        ):
            result = crawl.fetch_url(mock.Mock(), "https://example.com/data")
        self.assertTrue(crawl.is_dns_failure(result))
        self.assertEqual(curl_fetch.call_count, 2)
        self.assertEqual(
            [call.kwargs["method_label"] for call in curl_fetch.call_args_list],
            ["curl_crawler_ua", "curl_direct_crawler_ua"],
        )

    def test_previous_url_evidence_restores_only_exact_successful_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results_dir = root / "results"
            evidence_dir = root / "evidence_cache"
            results_dir.mkdir()
            evidence_dir.mkdir()
            evidence_file = evidence_dir / "known.txt"
            evidence_file.write_text("有效公开证据" * 40, encoding="utf-8")
            (results_dir / "row_23.json").write_text(
                json.dumps(
                    {
                        "raw_records": [
                            {
                                "url": "https://example.com/metric",
                                "final_url": "https://example.com/metric",
                                "status": 200,
                                "evidence_path": "evidence_cache/known.txt",
                                "title": "Known metric",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.object(crawl, "ROOT", root),
                mock.patch.object(crawl, "RESULTS_DIR", results_dir),
            ):
                restored = crawl.previous_url_evidence(
                    23, "https://example.com/metric"
                )
                missing = crawl.previous_url_evidence(
                    23, "https://example.com/other"
                )
        self.assertIsNotNone(restored)
        self.assertEqual(restored["method"], "previous_evidence_dns_fallback")
        self.assertEqual(restored["live_fetch_status"], "failed")
        self.assertTrue(restored["evidence_fallback_used"])
        self.assertIsNone(missing)

    def test_known_blocked_urls_are_replaced(self):
        rows = crawl.apply_crawl_settings(crawl.apply_row_filter(crawl.parse_latest_sheet()))
        blocked = set(crawl.RECOVERABLE_URL_ALTERNATIVES)
        candidates = [
            url
            for row in rows
            for url in crawl.candidate_urls(int(row["row"]), row["sources"])
        ]
        self.assertFalse(blocked.intersection(candidates))

    def test_retired_censtatd_retail_url_uses_current_official_pages(self):
        targets = crawl.candidate_targets(
            23,
            "https://www.censtatd.gov.hk/en/scode460.html",
        )
        urls = [url for url, _owners in targets]
        self.assertNotIn("https://www.censtatd.gov.hk/en/scode460.html", urls)
        self.assertIn("https://www.censtatd.gov.hk/en/scode530.html", urls)
        self.assertIn("https://www.censtatd.gov.hk/en/page_213.html", urls)

    def test_global_operator_sources_are_isolated_by_entity(self):
        targets = crawl.candidate_targets(
            21,
            "【中国移动】\n- https://www.chinaunicom.com.hk/en/ir/reports/ar2025.pdf",
            crawl.ROW_ENTITY_OVERRIDES[21],
        )
        owners_by_url = {url: owners for url, owners in targets}
        mobile_report = (
            "https://www.chinamobileltd.com/en/ir/reports/ar2025.pdf"
        )
        self.assertEqual(owners_by_url[mobile_report], ["中国移动"])
        self.assertEqual(
            owners_by_url[
                "https://www.chinaunicom.com.hk/en/ir/reports/ar2025.pdf"
            ],
            ["中国联通"],
        )

    def test_entity_candidate_dedup_preserves_all_expected_owners(self):
        targets = crawl.candidate_targets(
            20,
            "",
            crawl.ROW_ENTITY_OVERRIDES[20],
        )
        owners_by_url = {url: owners for url, owners in targets}
        shared_api_source = (
            "https://opengateway.telefonica.com/en/news/article/"
            "telcos-leaders-join-to-redefine-the-sector-with-network-apis"
        )
        self.assertEqual(
            owners_by_url[shared_api_source],
            ["AT&T", "T-Mobile US"],
        )

    def test_tmobile_sources_exclude_deutsche_telekom_group_pages(self):
        targets = crawl.candidate_targets(
            20,
            "",
            crawl.ROW_ENTITY_OVERRIDES[20],
        )
        owners_by_url = {url: owners for url, owners in targets}
        us_report = (
            "https://report.telekom.com/annual-report-2025/management-report/"
            "development-of-business-in-the-operating-segments/united-states.html"
        )
        self.assertEqual(owners_by_url[us_report], ["T-Mobile US"])
        self.assertNotIn(
            "https://report.telekom.com/annual-report-2025/management-report/"
            "group-strategy/investments.html",
            owners_by_url,
        )

    def test_hkbn_market_fallback_is_available(self):
        fallback = crawl.verified_field_fallback(13, "HKBN")
        self.assertIn("股价异动", fallback)
        self.assertIn("8.20港元", fallback["股价异动"])
        self.assertIn("7.34港元", fallback["股价异动"])

    def test_targeted_recrawl_preserves_untouched_entities_fields_and_urls(self):
        previous = {
            "row": 4,
            "status": "partial",
            "entities": ["HKT", "csl", "1O1O"],
            "selected_fields": ["战略合作", "5G-A"],
            "source_urls": ["https://old.example/hkt", "https://old.example/csl"],
            "attempted_urls": ["https://old.example/hkt", "https://old.example/csl"],
            "extracted": {"战略合作": "旧的整行合作证据"},
            "missing_fields": ["5G-A"],
            "entity_results": [
                {
                    "entity": "HKT",
                    "status": "partial",
                    "source_urls": ["https://old.example/hkt"],
                    "extracted": {"战略合作": "HKT旧合作证据"},
                    "missing_fields": ["5G-A"],
                    "raw_records": [
                        {
                            "url": "https://old.example/hkt",
                            "final_url": "https://old.example/hkt",
                            "content_hash": "old-hkt",
                        }
                    ],
                },
                {
                    "entity": "csl",
                    "status": "partial",
                    "source_urls": ["https://old.example/csl"],
                    "extracted": {"战略合作": "csl旧合作证据"},
                    "missing_fields": ["5G-A"],
                    "raw_records": [],
                },
                {
                    "entity": "1O1O",
                    "status": "partial",
                    "source_urls": [],
                    "extracted": {"战略合作": "1O1O旧合作证据"},
                    "missing_fields": ["5G-A"],
                    "raw_records": [],
                },
            ],
            "raw_records": [],
        }
        current = {
            "row": 4,
            "status": "ok",
            "entities": ["HKT"],
            "selected_fields": ["5G-A"],
            "source_urls": ["https://new.example/hkt-5ga"],
            "attempted_urls": ["https://new.example/hkt-5ga"],
            "extracted": {"5G-A": "HKT部署5G-A"},
            "missing_fields": [],
            "entity_results": [
                {
                    "entity": "HKT",
                    "status": "ok",
                    "source_urls": ["https://new.example/hkt-5ga"],
                    "extracted": {"5G-A": "HKT部署5G-A"},
                    "missing_fields": [],
                    "raw_records": [],
                }
            ],
            "raw_records": [],
        }
        merged = crawl.merge_targeted_row_result(
            previous,
            current,
            {"companies": ["HKT"], "metrics": ["5G-A"]},
        )
        self.assertEqual(merged["entities"], ["HKT", "csl", "1O1O"])
        self.assertEqual(merged["selected_fields"], ["战略合作", "5G-A"])
        self.assertIn("https://old.example/csl", merged["source_urls"])
        self.assertIn("https://new.example/hkt-5ga", merged["source_urls"])
        entities = {item["entity"]: item for item in merged["entity_results"]}
        self.assertEqual(entities["HKT"]["extracted"]["战略合作"], "HKT旧合作证据")
        self.assertEqual(entities["HKT"]["extracted"]["5G-A"], "HKT部署5G-A")
        self.assertEqual(entities["csl"]["extracted"], {"战略合作": "csl旧合作证据"})
        self.assertEqual(entities["1O1O"]["extracted"], {"战略合作": "1O1O旧合作证据"})


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

import crawl


class CrawlRecoveryTests(unittest.TestCase):
    def test_known_blocked_urls_are_replaced(self):
        rows = crawl.apply_crawl_settings(crawl.apply_row_filter(crawl.parse_latest_sheet()))
        blocked = set(crawl.RECOVERABLE_URL_ALTERNATIVES)
        candidates = [
            url
            for row in rows
            for url in crawl.candidate_urls(int(row["row"]), row["sources"])
        ]
        self.assertFalse(blocked.intersection(candidates))

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
            "https://www.ericsson.com/en/press-releases/2024/9/"
            "global-telecom-leaders-join-forces-to-redefine-the-industry-with-network-apis"
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

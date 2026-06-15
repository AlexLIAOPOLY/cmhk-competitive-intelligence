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

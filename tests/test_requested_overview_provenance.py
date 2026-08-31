import csv
import json
import unittest
from datetime import datetime
from pathlib import Path

from scripts.crawl_requested_overview_010304_official_sources import (
    summarize_handoff_followup,
    write_integrated_dataset,
)

ROOT = Path(__file__).resolve().parents[1]
FACTS = (
    ROOT
    / "agent_knowledge"
    / "requested_overview_010304_2016_2025"
    / "annual_facts.csv"
)


class RequestedOverviewProvenanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        write_integrated_dataset(datetime.now().astimezone().isoformat())
        with FACTS.open(encoding="utf-8-sig", newline="") as handle:
            cls.rows = list(csv.DictReader(handle))

    def test_exact_official_sources_define_the_verification_count(self):
        row = next(
            item
            for item in self.rows
            if item["entity"] == "中国联通"
            and item["metric"] == "postpaid"
            and item["period"] == "FY2022"
        )
        source_urls = json.loads(row["source_urls"])
        self.assertEqual(int(row["source_count"]), len(source_urls))
        self.assertEqual(row["source_count"], "3")
        self.assertEqual(row["verification_status"], "official_multi_source_verified")
        self.assertTrue(all(url.startswith("https://www.chinaunicom.com.hk/") for url in source_urls))
        self.assertTrue(row["scope_note"].startswith("FY2022歷史點；"))

    def test_handoff_followup_exposes_entity_level_unavailable_source(self):
        discovery = {"signals": [
            {"domain": "international", "entity": "T-Mobile US", "official_followup_urls": ["https://data.sec.gov/companyfacts.json"]},
            {"domain": "international", "entity": "Bharti Airtel", "official_followup_urls": ["https://assets.airtel.in/results.pdf"]},
        ]}
        crawled = [
            {"url": "https://data.sec.gov/companyfacts.json", "ok": True, "status": 200},
            {"url": "https://assets.airtel.in/results.pdf", "ok": False, "status": 403},
        ]

        summary = summarize_handoff_followup(discovery, crawled)

        self.assertEqual(summary["expected_entities"], 2)
        self.assertEqual(summary["retrieved_entities"], 1)
        self.assertEqual(summary["unavailable_entities"], 1)
        self.assertFalse(summary["coverage_complete"])
        airtel = next(item for item in summary["entities"] if item["entity"] == "Bharti Airtel")
        self.assertEqual(airtel["status"], "external_source_unavailable")
        self.assertEqual(airtel["failed_urls"], ["https://assets.airtel.in/results.pdf"])


if __name__ == "__main__":
    unittest.main()

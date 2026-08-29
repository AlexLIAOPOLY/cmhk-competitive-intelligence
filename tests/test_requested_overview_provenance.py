import csv
import json
import unittest
from datetime import datetime
from pathlib import Path

from scripts.crawl_requested_overview_010304_official_sources import (
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

    def test_candidate_documents_do_not_inflate_exact_verification_count(self):
        row = next(
            item
            for item in self.rows
            if item["entity"] == "中国联通"
            and item["metric"] == "postpaid"
            and item["period"] == "FY2022"
        )
        self.assertEqual(row["source_count"], "0")
        self.assertEqual(row["verification_status"], "official_single_source")
        self.assertEqual(len(json.loads(row["source_urls"])), 3)
        self.assertTrue(row["scope_note"].startswith("FY2022歷史點；"))


if __name__ == "__main__":
    unittest.main()

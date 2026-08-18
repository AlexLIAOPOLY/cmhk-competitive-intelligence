import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "web/static/competitor-workbench-data.json"


class CompetitorWorkbenchDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    def test_catalog_is_historical_and_has_no_duplicate_cells(self):
        companies = {item["id"] for item in self.payload["companies"]}
        metrics = {item["key"] for item in self.payload["metrics"]}
        cells = self.payload["cells"]
        keys = [(item["company"], item["metric"], item["year"]) for item in cells]

        self.assertGreaterEqual(len(companies), 9)
        self.assertGreaterEqual(len(metrics), 30)
        self.assertGreaterEqual(len(cells), 350)
        self.assertEqual(len(keys), len(set(keys)))
        self.assertLessEqual(min(item["year"] for item in cells), 2016)
        self.assertGreaterEqual(max(item["year"] for item in cells), 2025)

    def test_every_cell_is_verified_and_has_a_safe_source(self):
        blocked = {
            "source_gap_confirmed",
            "needs_official_row_crosscheck",
            "not_applicable_precommercial",
        }
        cells = self.payload["cells"]
        self.assertFalse([item for item in cells if item["status"] in blocked])
        self.assertFalse(
            [item for item in cells if item["source"] and not item["source"].startswith(("https://", "http://"))]
        )
        self.assertFalse([item for item in cells if item["comparator"] not in {"=", ">", ">=", "<", "<=", "~", "approx", "≈"}])
        self.assertFalse([item for item in cells if not item["period"] or not item["periodEnd"]])

    def test_evidence_version_is_content_hash(self):
        self.assertRegex(self.payload["evidenceVersion"], r"^[0-9a-f]{64}$")

    def test_hkt_smartone_churn_scenario_matches_expected_history(self):
        cells = {
            (item["company"], item["year"]): item
            for item in self.payload["cells"]
            if item["metric"] == "mobile_postpaid_churn"
            and item["company"] in {"HKT", "SmarTone"}
        }
        self.assertEqual(cells[("HKT", 2021)]["value"], 0.7)
        self.assertEqual(cells[("SmarTone", 2021)]["value"], 0.8)
        self.assertEqual(cells[("HKT", 2025)]["value"], 0.7)
        self.assertNotIn(("SmarTone", 2025), cells)
        self.assertTrue(cells[("HKT", 2025)]["source"].startswith("https://"))


if __name__ == "__main__":
    unittest.main()

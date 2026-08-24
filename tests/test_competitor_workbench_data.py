import csv
import json
import unittest
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "web/static/competitor-workbench-data.json"
SOURCES = (
    ROOT / "agent_knowledge/global_top5_operators_2016_2025/annual_metrics.csv",
    ROOT / "agent_knowledge/local_hk_operator_operating_metrics_2016_2025/annual_metrics.csv",
)
BLOCKED = {"source_gap_confirmed", "needs_official_row_crosscheck", "not_applicable_precommercial"}


class CompetitorWorkbenchDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    def test_catalog_is_historical_and_has_no_duplicate_cells(self):
        companies = {item["id"] for item in self.payload["companies"]}
        metrics = {item["key"] for item in self.payload["metrics"]}
        cells = self.payload["cells"]
        keys = [(item["company"], item["metric"], item["year"]) for item in cells]

        self.assertGreaterEqual(len(companies), 11)
        self.assertGreaterEqual(len(metrics), 50)
        self.assertGreaterEqual(len(cells), 580)
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

    def test_page_contains_every_multi_year_official_database_cell(self):
        source_rows = []
        availability = defaultdict(set)
        for source in SOURCES:
            with source.open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    if row.get("verification_status") in BLOCKED or not (row.get("official_value") or "").strip():
                        continue
                    key = (row["operator"], row["metric_key"])
                    availability[key].add(int(row["year"]))
                    source_rows.append((row["operator"], row["metric_key"], int(row["year"])))
        expected = {row for row in source_rows if len(availability[row[:2]]) >= 2}
        actual = {(row["company"], row["metric"], row["year"]) for row in self.payload["cells"]}
        self.assertEqual(actual, expected)
        self.assertEqual(
            self.payload["sourceDatasets"],
            ["global_top5_operators_2016_2025", "local_hk_operator_operating_metrics_2016_2025"],
        )
        bases = {item["id"]: item for item in self.payload["knowledgeBases"]}
        self.assertEqual(bases["global_top5_operators_2016_2025"]["cellCount"], 573)
        self.assertEqual(bases["local_hk_operator_operating_metrics_2016_2025"]["cellCount"], 167)
        self.assertEqual(sum(item["cellCount"] for item in bases.values()), len(actual))

    def test_recent_global_operator_additions_are_visible(self):
        companies = {item["id"]: item for item in self.payload["companies"]}
        metrics = {item["key"] for item in self.payload["metrics"]}
        for company in ("Bharti Airtel", "Reliance Jio", "Verizon", "Deutsche Telekom", "AT&T", "NTT Group"):
            self.assertEqual(companies[company]["group"], "国际运营商")
        self.assertTrue({"revenue", "ebitda", "net_profit", "network_towers", "total_data_traffic"} <= metrics)
        self.assertIn("reported_mobile_connections", metrics)

    def test_metric_titles_are_simplified_chinese(self):
        forbidden = set("寬頻戶業務網絡電視樓蓋連費長滲擴動後預淨營總")
        labels = [item["label"] for item in self.payload["metrics"]]
        self.assertFalse([(label, sorted(set(label) & forbidden)) for label in labels if set(label) & forbidden])
        self.assertIn("移动后付客户", labels)
        self.assertIn("移动后付月流失率", labels)
        self.assertIn("住宅宽带客户", labels)

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

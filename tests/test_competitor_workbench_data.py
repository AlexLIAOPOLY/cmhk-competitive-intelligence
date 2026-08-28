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

    def test_page_contains_every_official_database_cell_including_single_year(self):
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
        expected = set(source_rows)
        actual = {
            (row["company"], row["metric"], row["year"])
            for row in self.payload["cells"]
            if not row.get("derivedFromMetric")
            and row.get("dataset") != "requested_overview_010304_2016_2025"
        }
        self.assertEqual(actual, expected)
        self.assertEqual(
            self.payload["sourceDatasets"],
            [
                "global_top5_operators_2016_2025",
                "local_hk_operator_operating_metrics_2016_2025",
                "requested_overview_010304_2016_2025",
            ],
        )
        bases = {item["id"]: item for item in self.payload["knowledgeBases"]}
        self.assertGreaterEqual(bases["global_top5_operators_2016_2025"]["cellCount"], 599)
        self.assertGreaterEqual(bases["local_hk_operator_operating_metrics_2016_2025"]["cellCount"], 172)
        self.assertGreaterEqual(bases["requested_overview_010304_2016_2025"]["cellCount"], 242)
        self.assertEqual(sum(item["cellCount"] for item in bases.values()), len(self.payload["cells"]))

    def test_requested_010304_values_are_available_to_workbench_ai(self):
        cells = {
            (item["company"], item["metric"], item["year"]): item
            for item in self.payload["cells"]
            if item["dataset"] == "requested_overview_010304_2016_2025"
        }
        self.assertEqual(cells[("HKT", "overview_01_postpaid", 2025)]["value"], 3.494)
        self.assertEqual(cells[("3HK", "overview_01_postpaid", 2025)]["value"], 1.289)
        self.assertEqual(cells[("中国移动", "overview_03_revenue", 2025)]["value"], 10501.87)
        self.assertEqual(cells[("AWS", "overview_04_revenue", 2024)]["value"], 107556.0)
        self.assertEqual(cells[("AWS", "overview_04_profit", 2024)]["value"], 39834.0)
        self.assertEqual(cells[("Google", "overview_04_investment", 2024)]["value"], 52535.0)
        self.assertIn(("中国移动", "overview_03_postpaid", 2025), cells)
        self.assertIn(("中国电信", "overview_03_postpaid", 2025), cells)
        self.assertTrue(all("sources" in item for item in cells.values()))
        self.assertTrue(all("verificationCount" in item for item in cells.values()))
        self.assertEqual(cells[("3HK", "overview_01_revenue", 2021)]["value"], 5385.0)
        self.assertEqual(cells[("HKT", "overview_01_revenue", 2024)]["value"], 34753.0)
        self.assertEqual(cells[("SmarTone", "overview_01_revenue", 2016)]["value"], 18355.611)
        self.assertEqual(
            cells[("SmarTone", "overview_01_revenue", 2016)]["status"],
            "official_single_source_user_accepted_display",
        )
        for company in ("3HK", "HKT", "SmarTone"):
            years = {
                year for entity, metric, year in cells
                if entity == company and metric == "overview_01_net_profit"
            }
            self.assertEqual(years, set(range(2016, 2026)), company)
        self.assertEqual(cells[("3HK", "overview_01_net_profit", 2017)]["value"], 4766.0)
        self.assertIn("一次性净收益", cells[("3HK", "overview_01_net_profit", 2017)]["note"])
        self.assertEqual(cells[("HKT", "overview_01_net_profit", 2017)]["value"], 4745.0)
        self.assertEqual(cells[("SmarTone", "overview_01_net_profit", 2016)]["value"], 797.15)

    def test_recent_global_operator_additions_are_visible(self):
        companies = {item["id"]: item for item in self.payload["companies"]}
        metrics = {item["key"] for item in self.payload["metrics"]}
        for company in ("Bharti Airtel", "Reliance Jio", "Verizon", "Deutsche Telekom", "AT&T", "NTT Group"):
            self.assertEqual(companies[company]["group"], "国际运营商")
        self.assertTrue({"revenue", "ebitda", "net_profit", "network_towers", "total_data_traffic"} <= metrics)
        self.assertIn("reported_mobile_connections", metrics)
        cells = {(item["company"], item["metric"], item["year"]) for item in self.payload["cells"]}
        self.assertIn(("Deutsche Telekom", "postpaid_phone_arpu", 2025), cells)
        self.assertIn(("NTT Group", "adjusted_ebitda", 2025), cells)
        self.assertIn(("3HK", "5g_population_coverage", 2021), cells)

    def test_four_international_operators_share_ten_year_postpaid_comparison(self):
        selected = {"Verizon", "Deutsche Telekom", "AT&T", "NTT Group"}
        cells = [
            item for item in self.payload["cells"]
            if item["company"] in selected and item["metric"] == "postpaid_connections"
        ]
        by_company = defaultdict(list)
        for item in cells:
            by_company[item["company"]].append(item)
        self.assertEqual(set(by_company), selected)
        self.assertTrue(all(sorted(item["year"] for item in rows) == list(range(2016, 2026)) for rows in by_company.values()))
        self.assertEqual({item["unit"] for item in cells}, {"million_subscribers"})
        self.assertEqual(
            {item.get("nativeUnit", item["unit"]) for item in cells if item["company"] != "NTT Group"},
            {"million_subscribers", "million_customers", "million_connections"},
        )
        ntt = by_company["NTT Group"]
        self.assertTrue(all(item["derivedFromMetric"] == "mobile_service_subscriptions" for item in ntt))
        self.assertTrue(all("替代口径（非后付费）" in item["scope"] for item in ntt))

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

from __future__ import annotations

import json
import unittest
from pathlib import Path

from cmhk.intelligence.executive import build_executive_intelligence_snapshot


ROOT = Path(__file__).resolve().parents[1]


class CompetitorDisplaySourceGateTests(unittest.TestCase):
    def test_local_revenue_and_ebitda_are_never_hidden_by_source_count(self):
        snapshot = build_executive_intelligence_snapshot()
        local = next(domain for domain in snapshot["domains"] if domain["id"] == "local")
        focuses = {focus["id"]: focus for focus in local["focuses"]}
        for focus_id in ("revenue", "ebitda"):
            by_name = {item["name"]: item for item in focuses[focus_id]["items"]}
            for company in ("HKT", "SmarTone", "3HK"):
                missing = [point["label"] for point in by_name[company]["trend"] if point["value"] is None]
                self.assertEqual(missing, [], f"{focus_id}:{company}")

        hkt_2024 = next(
            point for point in {item["name"]: item for item in focuses["revenue"]["items"]}["HKT"]["trend"]
            if point["label"] == "FY2024"
        )
        self.assertEqual(hkt_2024["value"], 34753.0)
        self.assertEqual(hkt_2024["verification_count"], 2)

    def test_generated_workbench_keeps_single_source_official_values_visible(self):
        payload = json.loads((ROOT / "web/static/competitor-workbench-data.json").read_text(encoding="utf-8"))
        cells = {
            (item["company"], item["metric"], item["year"]): item
            for item in payload["cells"]
        }
        smartone = cells[("SmarTone", "overview_01_revenue", 2016)]
        self.assertEqual(smartone["value"], 18355.611)
        self.assertEqual(smartone["verificationCount"], 1)
        self.assertEqual(smartone["status"], "official_single_source_user_accepted_display")
        self.assertIn("不影响展示", smartone["basis"])


if __name__ == "__main__":
    unittest.main()

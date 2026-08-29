import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "web" / "static" / "competitor-workbench-data.json"


class CompetitorWorkbenchDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_competitor_workbench_data.py")],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        cls.payload = json.loads(OUTPUT.read_text(encoding="utf-8"))

    def test_jio_values_and_gap_boundaries_are_visible(self):
        cells = {
            (row["company"], row["year"], row["metric"]): row
            for row in self.payload["cells"]
        }
        self.assertEqual(cells[("Reliance Jio", 2017, "mobile_dou")]["value"], 10)
        self.assertEqual(cells[("Reliance Jio", 2018, "mobile_arpu")]["value"], 137)
        self.assertEqual(cells[("Reliance Jio", 2018, "mobile_dou")]["value"], 9.7)

        gaps = {
            (row["company"], row["year"], row["metric"]): row
            for row in self.payload["gaps"]
        }
        self.assertEqual(
            gaps[("Reliance Jio", 2023, "5g_network_subscribers")]["searchStatus"],
            "targeted_public_search_no_direct_value",
        )
        self.assertEqual(
            gaps[("Reliance Jio", 2016, "mobile_arpu")]["searchStatus"],
            "not_applicable_precommercial",
        )
        global_meta = next(
            item
            for item in self.payload["knowledgeBases"]
            if item["id"] == "global_top5_operators_2016_2025"
        )
        self.assertEqual(global_meta["gapCount"], 232)


if __name__ == "__main__":
    unittest.main()

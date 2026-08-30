import unittest
from pathlib import Path

from cmhk.intelligence.executive import build_executive_intelligence_snapshot


ROOT = Path(__file__).resolve().parents[1]
STYLES = (ROOT / "web/static/styles.css").read_text(encoding="utf-8")
INDEX = (ROOT / "web/static/index.html").read_text(encoding="utf-8")


class CloudLatestDataLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        snapshot = build_executive_intelligence_snapshot()
        cls.cloud = next(domain for domain in snapshot["domains"] if domain["id"] == "cloud")
        cls.focuses = {focus["id"]: focus for focus in cls.cloud["focuses"]}

    def test_cloud_revenue_and_profit_use_latest_verified_year(self) -> None:
        self.assertIn("FY2025", self.focuses["revenue"]["metric"]["label"])
        self.assertIn("FY2025", self.focuses["profit"]["metric"]["label"])
        self.assertEqual(self.focuses["revenue"]["items"][0]["value"], 128725.0)
        self.assertEqual(self.focuses["profit"]["items"][0]["value"], 45606.0)

    def test_capex_keeps_each_vendor_latest_disclosed_period(self) -> None:
        investment = self.focuses["investment"]
        disclosed = [item for item in investment["items"] if item["value"] is not None]
        self.assertTrue(disclosed)
        self.assertTrue(all(item["period"] for item in disclosed))
        self.assertIn(disclosed[0]["period"], investment["metric"]["label"])
        self.assertIn("各公司最新已核验披露期", investment["context"])

    def test_cloud_stage_fills_height_and_rows_start_below_tabs(self) -> None:
        self.assertIn(".intelligence-domain-cloud .intelligence-chart-scroll .intelligence-viz-columns", STYLES)
        self.assertIn("height: calc(100% - 7px);", STYLES)
        self.assertIn(".intelligence-domain-cloud .intelligence-viz-rows", STYLES)
        self.assertIn("align-content: start;", STYLES)
        self.assertIn("overflow-y: auto;", STYLES)
        self.assertIn('/static/styles.css?v=287', INDEX)


if __name__ == "__main__":
    unittest.main()

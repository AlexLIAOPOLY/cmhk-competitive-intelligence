import json
import tempfile
import unittest
from pathlib import Path

from cmhk.intelligence.competitor_map import build_competitor_intelligence_map


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "web" / "static" / "intelligence-map.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web" / "static" / "intelligence-map.css").read_text(encoding="utf-8")
WEB_APP = (ROOT / "web_app.py").read_text(encoding="utf-8")


class CompetitorIntelligenceMapTests(unittest.TestCase):
    def test_independent_tab_preserves_competitor_workspace(self):
        self.assertIn('id="workspace-tab-competitor"', INDEX)
        self.assertIn('id="workspace-panel-competitor"', INDEX)
        self.assertIn('id="workspace-tab-intelligence-map"', INDEX)
        self.assertIn('id="workspace-panel-intelligence-map"', INDEX)
        self.assertIn('<span class="workspace-tab-label">情报图谱</span>', INDEX)

    def test_layout_has_filters_trend_network_and_evidence_insights(self):
        self.assertIn('data-map-filter="days"', SCRIPT)
        self.assertIn('data-map-filter="category"', SCRIPT)
        self.assertIn('data-map-filter="region"', SCRIPT)
        self.assertIn("trendChart(items)", SCRIPT)
        self.assertIn("networkGraph(items)", SCRIPT)
        self.assertIn("基于已审核证据自动归纳", SCRIPT)
        self.assertIn("@media (max-width: 560px)", STYLE)
        self.assertIn("grid-template-columns: minmax(0, 2fr) minmax(360px, 1fr)", STYLE)

    def test_live_endpoint_is_used(self):
        self.assertIn('fetch("/api/competitor-intelligence-map"', SCRIPT)
        self.assertIn('if path == "/api/competitor-intelligence-map":', WEB_APP)
        self.assertIn("build_competitor_intelligence_map(ROOT)", WEB_APP)

    def test_backend_shapes_only_dated_approved_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "strategy_briefing" / "published.json"
            source.parent.mkdir(parents=True)
            source.write_text(json.dumps({
                "updated_at": "2026-08-28T12:00:00+08:00",
                "items": [
                    {
                        "id": "n1",
                        "title": "HKT 推出 AI 算力与 5G 企业服务",
                        "summary": "香港市场动态",
                        "category": "竞对动态",
                        "region": "香港本地",
                        "source": "测试来源",
                        "source_date": "2026-08-28",
                    },
                    {"id": "n2", "title": "缺少日期的记录"},
                ],
            }, ensure_ascii=False), encoding="utf-8")

            payload = build_competitor_intelligence_map(root)

        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["coverageStart"], "2026-08-28")
        self.assertIn("HKT / csl", payload["items"][0]["entities"])
        self.assertIn("AI / 算力", payload["items"][0]["concepts"])
        self.assertIn("5G / 6G", payload["items"][0]["concepts"])


if __name__ == "__main__":
    unittest.main()

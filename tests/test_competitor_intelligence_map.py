import json
import tempfile
import unittest
from pathlib import Path

from cmhk.intelligence.competitor_map import build_competitor_intelligence_map
from cmhk.intelligence.market_news_insights import _validate_insights, evidence_hash


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

    def test_layout_has_interactive_trend_network_word_cloud_and_daily_table(self):
        self.assertNotIn('data-map-filter="days"', SCRIPT)
        self.assertNotIn('data-map-filter="category"', SCRIPT)
        self.assertNotIn('data-map-filter="region"', SCRIPT)
        self.assertIn("new window.Chart", SCRIPT)
        self.assertIn("window.cytoscape", SCRIPT)
        self.assertIn('data-market-view="cloud"', SCRIPT)
        self.assertIn('data-market-keyword', SCRIPT)
        self.assertIn('name: "cose"', SCRIPT)
        self.assertIn('function connectedGraph(', SCRIPT)
        self.assertIn('const treeEdges = []', SCRIPT)
        self.assertIn('while (selectedIds.size > maxNodes)', SCRIPT)
        self.assertIn('entityIds.slice(index + 1)', SCRIPT)
        self.assertIn('"包含概念"', SCRIPT)
        self.assertIn('randomize: false', SCRIPT)
        self.assertIn('function scheduleViewRotation()', SCRIPT)
        self.assertIn('10000', SCRIPT)
        self.assertIn('label: "data(label)"', SCRIPT)
        self.assertIn('maxNodes = 20, maxEdges = 28', SCRIPT)
        self.assertIn('cy.on("tap", "node, edge"', SCRIPT)
        self.assertIn('pointHoverRadius: 5', SCRIPT)
        self.assertIn('datalabels: false', SCRIPT)
        self.assertIn('market-graph-evidence-row', SCRIPT)
        self.assertIn('${esc(item.title)}</span><small>${esc(item.source)}', SCRIPT)
        self.assertNotIn('class="market-graph-evidence">', SCRIPT)
        self.assertIn('情报知识图谱', SCRIPT)
        self.assertIn('关联路径', SCRIPT)
        self.assertIn('证据新闻', SCRIPT)
        self.assertIn('打开新闻原文', SCRIPT)
        self.assertIn('data-graph-focus', SCRIPT)
        self.assertNotIn("议题变化趋势", SCRIPT)
        self.assertNotIn("全部时间", SCRIPT)
        self.assertNotIn("全部议题", SCRIPT)
        self.assertNotIn("全部区域", SCRIPT)
        self.assertIn("@media (max-width: 560px)", STYLE)
        self.assertIn("grid-template-columns: minmax(0, 1.4fr) minmax(420px, 1fr)", STYLE)
        self.assertIn("min-height: 210px", STYLE)
        self.assertIn('cytoscape-3.34.0.min.js', INDEX)
        self.assertIn('每日情报统计', SCRIPT)
        self.assertIn('function renderDailyTable(items)', SCRIPT)
        self.assertIn('market-daily-table-wrap', STYLE)
        self.assertIn('scope="row"', SCRIPT)
        self.assertNotIn('data-insight-refresh', SCRIPT)
        self.assertNotIn('重新生成4条AI情报洞察', SCRIPT)
        self.assertNotIn('market-insight-refresh-status', SCRIPT)
        self.assertNotIn('每 5 分钟自动更新', SCRIPT)
        self.assertNotIn('/api/competitor-intelligence-map/insights-stream', SCRIPT)
        self.assertIn('window.setTimeout', SCRIPT)
        self.assertIn('300000', SCRIPT)
        self.assertIn('60000', SCRIPT)
        self.assertIn('workspace-tab-change', SCRIPT)
        self.assertIn('cache: "no-store"', SCRIPT)
        self.assertIn('controller.abort()', SCRIPT)
        self.assertIn('4000', SCRIPT)

    def test_live_endpoint_is_used(self):
        self.assertIn('fetch(`/api/competitor-intelligence-map?_', SCRIPT)
        self.assertIn('if path == "/api/competitor-intelligence-map":', WEB_APP)
        self.assertIn("build_competitor_intelligence_map(ROOT)", WEB_APP)
        self.assertIn('parsed.path == "/api/competitor-intelligence-map/insights-stream"', WEB_APP)

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
        self.assertIn("keywords", payload["items"][0])
        self.assertEqual(payload["evidenceHash"], evidence_hash(payload["items"]))
        self.assertIsNone(payload["aiInsight"])

    def test_ai_insights_require_exactly_four_evidence_backed_rows(self):
        rows = [
            {"title": f"洞察{i}", "body": "这是基于已审核新闻形成的有效跨新闻分析发现。", "evidenceIds": ["n1"]}
            for i in range(1, 5)
        ]
        self.assertEqual(len(_validate_insights(rows, {"n1"})), 4)
        with self.assertRaises(RuntimeError):
            _validate_insights(rows[:3], {"n1"})


if __name__ == "__main__":
    unittest.main()

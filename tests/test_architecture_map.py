from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web/static/index.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "web/static/workspace-tabs.js").read_text(encoding="utf-8")
PAGE = (ROOT / "web/static/architecture-map.html").read_text(encoding="utf-8")
STYLE = (ROOT / "web/static/architecture-map.css").read_text(encoding="utf-8")
PUBLISHER = (ROOT / "scripts/publish_executive_dashboard_pages.py").read_text(encoding="utf-8")


class ArchitectureMapTests(unittest.TestCase):
    def test_static_architecture_tab_is_accessible_and_permission_gated(self):
        self.assertIn('id="workspace-tab-architecture"', INDEX)
        self.assertIn('aria-controls="workspace-panel-architecture"', INDEX)
        self.assertIn('id="workspace-panel-architecture"', INDEX)
        self.assertIn('data-workspace-panel="architecture"', INDEX)
        self.assertIn('data-src="/static/architecture-map.html?v=2"', INDEX)
        self.assertIn('architecture: "dashboard"', SCRIPT)

    def test_architecture_maps_every_ai_workstream_without_interactions(self):
        for label in (
            "新闻采集",
            "新闻审核",
            "战略总览 · 竞对分析",
            "监控体系 / 情报图谱",
            "战略周报",
            "业绩摘要",
            "订阅与推送",
            "小竞AI",
            "任务日志",
            "报警处置",
            "Agentic Search Planner",
            "新闻选材 Agent",
            "公司研究 Agents",
            "缺口 Supervisor",
            "Weekly Writer",
            "Quality Reviewer",
            "Performance Editor",
            "ReAct Agent",
            "AI 故障诊断",
            "影响线路复核",
            "结案摘要",
            "DeepSeek-V4-Pro",
            "GLM",
            "Qwen3-30B-A3B-Instruct-2507",
            "Kimi-K2.5",
            "Qwen3ASR",
        ):
            self.assertIn(label, PAGE)
        self.assertNotIn("<button", PAGE)
        self.assertNotIn("<a ", PAGE)
        self.assertNotIn("<script", PAGE)

    def test_architecture_is_a_node_link_diagram_in_simplified_chinese(self):
        self.assertIn('<html lang="zh-CN">', PAGE)
        self.assertIn('class="architecture-links"', PAGE)
        self.assertIn('marker-end="url(#arrow-cyan)"', PAGE)
        self.assertIn('class="architecture-node agent-core"', PAGE)
        self.assertIn('class="layer-box governance-layer"', PAGE)
        self.assertNotIn("architecture-lane", PAGE)
        self.assertNotIn("architecture-cell", PAGE)
        for traditional in ("與", "架構", "頁面", "確定", "專責", "輸出", "審核", "競對", "飛書", "圖表", "回讀"):
            self.assertNotIn(traditional, PAGE)

    def test_motion_is_directional_and_respects_reduced_motion(self):
        self.assertIn("@keyframes architecture-flow", STYLE)
        self.assertIn("@keyframes architecture-pulse", STYLE)
        self.assertIn("@keyframes architecture-orbit", STYLE)
        self.assertIn("stroke-dashoffset", STYLE)
        self.assertIn("@media (prefers-reduced-motion: reduce)", STYLE)
        self.assertIn("animation: none !important", STYLE)
        self.assertIn("@media (max-width: 720px)", STYLE)

    def test_public_snapshot_copies_the_static_architecture_assets(self):
        self.assertIn('"architecture-map.css"', PUBLISHER)
        self.assertIn('"architecture-map.html"', PUBLISHER)


if __name__ == "__main__":
    unittest.main()

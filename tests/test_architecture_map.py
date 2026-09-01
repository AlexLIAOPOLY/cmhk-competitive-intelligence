from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web/static/index.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "web/static/workspace-tabs.js").read_text(encoding="utf-8")
PAGE = (ROOT / "web/static/architecture-map.html").read_text(encoding="utf-8")
STYLE = (ROOT / "web/static/architecture-map.css").read_text(encoding="utf-8")
RESPONSIVE_SCRIPT = (ROOT / "web/static/architecture-map.js").read_text(encoding="utf-8")
PUBLISHER = (ROOT / "scripts/publish_executive_dashboard_pages.py").read_text(encoding="utf-8")


class ArchitectureMapTests(unittest.TestCase):
    def test_static_architecture_tab_is_hidden_but_the_page_is_retained(self):
        self.assertIn('id="workspace-tab-architecture"', INDEX)
        self.assertIn('aria-controls="workspace-panel-architecture"', INDEX)
        self.assertIn('data-workspace-tab="architecture" data-workspace-tab-hidden hidden', INDEX)
        self.assertIn('id="workspace-panel-architecture"', INDEX)
        self.assertIn('data-workspace-panel="architecture"', INDEX)
        self.assertIn('data-src="/static/architecture-map.html?v=8"', INDEX)
        self.assertIn('<span class="workspace-tab-label">项目系统架构</span>', INDEX)
        self.assertIn('architecture: "dashboard"', SCRIPT)

    def test_architecture_maps_every_ai_workstream_without_interactions(self):
        for label in (
            "新闻情报",
            "竞对研究",
            "报告生产",
            "小竞AI",
            "生产运维",
            "官网与公开来源",
            "四大治理数据库",
            "飞书审核回读",
            "RAG 与报告知识库",
            "CMHK AI 智能中枢",
            "Agent 编排",
            "模型路由",
            "工具调用",
            "上下文记忆",
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
            "驾驶舱与知识图谱",
            "飞书审核与战略简报",
            "Word / PDF / 音频",
            "AI 回答与引用",
            "告警闭环",
            "确定性优先",
            "失败保留确定性结果",
        ):
            self.assertIn(label, PAGE)
        self.assertNotIn("<button", PAGE)
        self.assertNotIn("<a ", PAGE)
        self.assertIn('<script src="./architecture-map.js?v=2" defer></script>', PAGE)
        self.assertEqual(PAGE.count('class="architecture-icon"'), 1)
        self.assertEqual(PAGE.count('class="architecture-symbol"'), 18)
        for placeholder in (">情<", ">研<", ">报<", ">问<", ">运<", ">源<", ">库<", ">审<", ">知<", ">编<", ">模<", ">工<", ">忆<", ">图<", ">飞<", ">档<", ">答<", ">警<"):
            self.assertNotIn(placeholder, PAGE)
        self.assertIn("assets/architecture-icons/ai-core.png", PAGE)
        self.assertNotIn("business-news.png", PAGE)
        self.assertIn("📃", PAGE)

    def test_architecture_is_a_node_link_diagram_in_simplified_chinese(self):
        self.assertIn('<html lang="zh-CN">', PAGE)
        self.assertIn('class="architecture-links"', PAGE)
        self.assertIn('marker-end="url(#arrow-data)"', PAGE)
        self.assertIn('class="ai-core"', PAGE)
        self.assertIn('class="core-capabilities"', PAGE)
        self.assertIn('class="governance-halo"', PAGE)
        self.assertIn('class="sector business-sector"', PAGE)
        self.assertNotIn("页面入口", PAGE)
        self.assertNotIn("流程编排", PAGE)
        self.assertNotIn('class="architecture-heading"', PAGE)
        self.assertNotIn('class="architecture-legend"', PAGE)
        self.assertNotIn("architecture-lane", PAGE)
        self.assertNotIn("architecture-cell", PAGE)
        for traditional in ("與", "架構", "頁面", "確定", "專責", "輸出", "審核", "競對", "飛書", "圖表", "回讀"):
            self.assertNotIn(traditional, PAGE)

    def test_motion_is_directional_and_respects_reduced_motion(self):
        self.assertIn("@keyframes flow-line", STYLE)
        self.assertIn("@keyframes core-pulse", STYLE)
        self.assertIn("@keyframes ring-spin", STYLE)
        self.assertIn("stroke-dashoffset", STYLE)
        self.assertIn("@media (prefers-reduced-motion: reduce)", STYLE)
        self.assertIn("animation: none !important", STYLE)
        self.assertIn("@media (max-width: 1000px)", STYLE)
        self.assertIn("ResizeObserver", RESPONSIVE_SCRIPT)
        self.assertIn("availableWidth / CANVAS_WIDTH", RESPONSIVE_SCRIPT)
        self.assertIn("availableHeight / CANVAS_HEIGHT", RESPONSIVE_SCRIPT)

    def test_architecture_background_uses_grid_gradient_glass(self):
        self.assertIn(".architecture-diagram::before", STYLE)
        self.assertIn("background-size: 40px 40px", STYLE)
        self.assertIn("mask-image: radial-gradient", STYLE)
        self.assertIn("backdrop-filter: blur(24px) saturate(138%)", STYLE)
        self.assertIn("linear-gradient(145deg", STYLE)
        self.assertIn('architecture-map.css?v=8', PAGE)

    def test_public_snapshot_copies_the_static_architecture_assets(self):
        self.assertIn('"architecture-map.css"', PUBLISHER)
        self.assertIn('"architecture-map.html"', PUBLISHER)
        self.assertIn('"architecture-map.js"', PUBLISHER)


if __name__ == "__main__":
    unittest.main()

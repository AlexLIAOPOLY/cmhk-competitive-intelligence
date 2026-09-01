from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "web" / "static" / "workspace-tabs.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web" / "static" / "workspace-tabs.css").read_text(encoding="utf-8")


class NewsLineageVisualStabilityTests(unittest.TestCase):
    def test_line_state_icons_are_semantic_stroke_svgs_without_circle_badges(self):
        self.assertIn(".news-lineage-status-icon {", STYLE)
        self.assertIn("fill: none; stroke: currentColor", STYLE)
        self.assertIn(".news-lineage-edge-state .news-lineage-status-icon", STYLE)
        self.assertNotIn(".news-lineage-edge-state i {", STYLE)
        self.assertNotIn(".news-lineage-edge-state.is-running", STYLE)

    def test_node_title_reserves_space_for_health_and_open_icon(self):
        self.assertIn("padding-right: 64px", STYLE)

    def test_crawler_diagram_uses_fine_subtle_grid_glass(self):
        self.assertIn(".news-lineage-viewport::before", STYLE)
        self.assertIn("background-size: 14px 14px, 14px 14px, 70px 70px, 70px 70px", STYLE)
        self.assertIn("backdrop-filter: blur(14px) saturate(128%)", STYLE)
        self.assertIn("rgba(126, 224, 244, .024)", STYLE)
        self.assertIn("rgba(141, 201, 246, .04)", STYLE)
        self.assertIn("radial-gradient(ellipse 54% 58% at center, #000 42%", STYLE)
        self.assertIn("backdrop-filter: blur(6px)", STYLE)
        self.assertIn("radial-gradient(ellipse 54% 58% at center, transparent 42%", STYLE)

    def test_quiet_fault_poll_does_not_rebuild_unchanged_news_lineage(self):
        self.assertIn("function newsLineageIncidentSignature(tasks)", SCRIPT)
        self.assertIn("if (newsLineageChanged && document.querySelector", SCRIPT)
        self.assertIn("--lineage-zoom:${initialLineageZoom}", SCRIPT)
        self.assertNotIn("transition: height .18s ease", STYLE)
        self.assertNotIn("transition: width .18s ease,height .18s ease", STYLE)
        self.assertNotIn("transition: transform .18s ease", STYLE)

    def test_cache_versions_publish_the_fixed_assets(self):
        self.assertIn('/static/workspace-tabs.css?v=145', INDEX)
        self.assertIn('/static/workspace-tabs.js?v=168', INDEX)


if __name__ == "__main__":
    unittest.main()

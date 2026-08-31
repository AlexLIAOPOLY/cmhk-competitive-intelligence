from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "web" / "static" / "workspace-tabs.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web" / "static" / "workspace-tabs.css").read_text(encoding="utf-8")


class NewsLineageVisualStabilityTests(unittest.TestCase):
    def test_line_state_icons_use_explicit_semantic_backgrounds(self):
        self.assertNotIn(
            ".news-lineage-edge-state i { display: inline-grid; width: 15px; height: 15px; place-items: center; border-radius: 50%; color: #071b26; background: currentColor;",
            STYLE,
        )
        self.assertIn(".news-lineage-edge-state.is-running i { background: #65cbe5; }", STYLE)
        self.assertIn(".news-lineage-edge-state.is-degraded i,.news-lineage-edge-state.is-at-risk i { background: #f2bd62; }", STYLE)
        self.assertIn(".news-lineage-edge-state.is-interrupted i { background: #f08078; }", STYLE)

    def test_node_title_reserves_space_for_health_and_open_icon(self):
        self.assertIn("padding-right: 64px", STYLE)

    def test_quiet_fault_poll_does_not_rebuild_unchanged_news_lineage(self):
        self.assertIn("function newsLineageIncidentSignature(tasks)", SCRIPT)
        self.assertIn("if (newsLineageChanged && document.querySelector", SCRIPT)
        self.assertIn("--lineage-zoom:${initialLineageZoom}", SCRIPT)
        self.assertNotIn("transition: height .18s ease", STYLE)
        self.assertNotIn("transition: width .18s ease,height .18s ease", STYLE)
        self.assertNotIn("transition: transform .18s ease", STYLE)

    def test_cache_versions_publish_the_fixed_assets(self):
        self.assertIn('/static/workspace-tabs.css?v=136', INDEX)
        self.assertIn('/static/workspace-tabs.js?v=162', INDEX)


if __name__ == "__main__":
    unittest.main()

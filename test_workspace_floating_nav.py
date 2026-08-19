from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
INDEX = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "web" / "static" / "workspace-tabs.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web" / "static" / "workspace-tabs.css").read_text(encoding="utf-8")


class WorkspaceFloatingNavTests(unittest.TestCase):
    def test_collapsed_navigation_floats_without_reserving_a_grid_column(self):
        self.assertIn(".workspace-layout.is-nav-collapsed { grid-template-columns: minmax(0, 1fr);", STYLE)
        self.assertIn(".workspace-layout.is-nav-collapsed .workspace-content { grid-column: 1; }", STYLE)
        self.assertIn(".workspace-layout.is-nav-collapsed .workspace-tabs { position: absolute;", STYLE)
        self.assertIn("position: absolute; top: 0; left: 10px;", STYLE)
        self.assertIn("pointer-events: none;", STYLE)
        self.assertIn("pointer-events: auto; }", STYLE)

    def test_ai_workspace_hides_brand_bar_and_uses_full_viewport_height(self):
        self.assertIn('classList.toggle("workspace-ai-active", target === "ai")', SCRIPT)
        self.assertIn('if (workspace === "ai") document.body.classList.add("workspace-ai-active")', INDEX)
        self.assertIn(".dashboard-page.workspace-ai-active .brand-bar { display: none !important; }", STYLE)
        self.assertIn(".dashboard-page.workspace-ai-active .workspace-layout { height: 100dvh; }", STYLE)


if __name__ == "__main__":
    unittest.main()

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "web" / "static" / "workspace-tabs.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web" / "static" / "workspace-tabs.css").read_text(encoding="utf-8")


class WorkspaceFloatingNavTests(unittest.TestCase):
    def test_collapsed_navigation_floats_without_reserving_a_grid_column(self):
        self.assertIn(".workspace-layout.is-nav-collapsed { grid-template-columns: minmax(0, 1fr);", STYLE)
        self.assertIn(".workspace-layout.is-nav-collapsed .workspace-content { grid-column: 1; }", STYLE)
        self.assertIn(".workspace-layout.is-nav-collapsed .workspace-tabs { position: absolute;", STYLE)
        self.assertIn("position: absolute; top: -54px; left: 180px;", STYLE)
        self.assertIn("pointer-events: none;", STYLE)
        self.assertIn("pointer-events: auto; }", STYLE)

    def test_ai_navigation_handle_has_dedicated_non_overlapping_position(self):
        self.assertIn("body.dashboard-page.workspace-ai-active .workspace-layout.is-nav-collapsed > .workspace-tabs", STYLE)
        self.assertIn("top: max(12px, env(safe-area-inset-top));", STYLE)
        self.assertIn("left: max(12px, env(safe-area-inset-left));", STYLE)
        self.assertIn("align-items: flex-start;", STYLE)
        self.assertIn("flex-basis: 34px;", STYLE)
        self.assertIn(":not(.is-nav-positioning):not(.is-nav-transitioning)", STYLE)
        self.assertIn("transform: translateY(0);", STYLE)
        self.assertIn("top: max(10px, env(safe-area-inset-top));", STYLE)
        self.assertIn(".workspace-layout.is-nav-collapsed .chat-nav-controls { margin-left: 48px; }", STYLE)
        self.assertIn(".workspace-tabs .workspace-tabs-scroll { display: none; }", STYLE)

    def test_ai_workspace_auto_collapses_hides_brand_bar_and_uses_full_viewport_height(self):
        self.assertIn('classList.toggle("workspace-ai-active", targetIsAi)', SCRIPT)
        self.assertIn('setWorkspaceNavCollapsed?.(true, { fromRect: navTransitionStart });', SCRIPT)
        self.assertIn('setWorkspaceNavCollapsed = animateTo;', SCRIPT)
        self.assertIn('window.clearTimeout(motionTimer)', SCRIPT)
        self.assertNotIn('if (motionTimer) return;', SCRIPT)
        self.assertIn('if (workspace === "ai") document.body.classList.add("workspace-ai-active")', INDEX)
        self.assertIn("transform: translateY(-105%);", STYLE)
        self.assertIn("visibility 0s linear .36s", STYLE)
        self.assertIn(".dashboard-page .brand-bar,", STYLE)
        self.assertIn(".dashboard-page.workspace-ai-active .workspace-layout { height: 100dvh; }", STYLE)
        self.assertIn("#workspace-panel-ai { padding: 0; }", STYLE)
        self.assertIn("#workspace-panel-ai .workspace-inline-surface .floating-chat", STYLE)
        self.assertIn("height: 100dvh !important;", STYLE)
        self.assertIn("border-radius: 0 !important;", STYLE)


if __name__ == "__main__":
    unittest.main()

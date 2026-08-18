from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
INDEX = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "web" / "static" / "workspace-tabs.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web" / "static" / "workspace-tabs.css").read_text(encoding="utf-8")


class WorkspaceTabsTests(unittest.TestCase):
    def test_dashboard_and_five_modules_have_accessible_tabs_and_panels(self):
        modules = (
            "dashboard",
            "monitoring",
            "competitor",
            "news",
            "weekly",
            "performance",
            "ai",
            "log",
        )
        for module in modules:
            self.assertIn(f'id="workspace-tab-{module}"', INDEX)
            self.assertIn(f'aria-controls="workspace-panel-{module}"', INDEX)
            self.assertIn(f'id="workspace-panel-{module}"', INDEX)
            self.assertIn(f'data-workspace-panel="{module}"', INDEX)
        self.assertEqual(INDEX.count('role="tab"'), len(modules))
        self.assertEqual(INDEX.count('role="tabpanel"'), len(modules))

    def test_modules_use_live_apis_and_existing_workflows(self):
        for endpoint in (
            "/api/status",
            "/api/company-metrics",
            "/api/strategic-briefs",
        ):
            self.assertIn(f'fetch("{endpoint}")', SCRIPT)
        for existing_action in (
            "#openNewsReviewSheetButton",
            "#generateButtonSecondary",
            "#generatePerformanceButton",
        ):
            self.assertIn(existing_action, SCRIPT)

    def test_navigation_is_linkable_responsive_and_keyboard_accessible(self):
        self.assertIn('params.get("workspace")', SCRIPT)
        self.assertIn('"ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"', SCRIPT)
        self.assertIn("@media (max-width: 560px)", STYLE)
        self.assertIn("overflow-x: auto", STYLE)

    def test_subscription_preference_is_described_as_browser_local(self):
        self.assertIn("订阅服务 UI DEMO", SCRIPT)
        self.assertIn("本机方案草案", SCRIPT)
        self.assertIn("尚未连接收件人管理或飞书自动发送后台", SCRIPT)
        self.assertIn('localStorage.setItem("cmhk-weekly-subscription"', SCRIPT)

    def test_external_links_are_protocol_checked_and_api_failures_are_isolated(self):
        self.assertIn('const safeUrl =', SCRIPT)
        self.assertIn('["http:", "https:"]', SCRIPT)
        self.assertIn("Promise.allSettled", SCRIPT)
        self.assertIn("renderLoadError", SCRIPT)

    def test_existing_ai_log_and_report_surfaces_are_moved_into_tabs(self):
        self.assertIn('document.querySelector("#chatModal")', SCRIPT)
        self.assertIn('document.querySelector("#logModal")', SCRIPT)
        self.assertIn('document.querySelector(weekly ? "#weeklyOutputBlock"', SCRIPT)
        self.assertIn("appendChild(chat)", SCRIPT)
        self.assertIn("appendChild(log)", SCRIPT)
        self.assertIn("appendChild(outputBlock)", SCRIPT)
        self.assertIn('id="workspaceNavCollapse"', INDEX)
        self.assertIn("is-nav-collapsed", STYLE)
        self.assertIn('class="workspace-monitoring-frame"', INDEX)
        self.assertIn("CMHK战略竞对中心", INDEX)
        self.assertIn("executive-dashboard-demo.html?embedded=1&amp;v=2", INDEX)


if __name__ == "__main__":
    unittest.main()

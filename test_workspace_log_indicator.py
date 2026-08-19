from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
APP = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")


class WorkspaceLogIndicatorTests(unittest.TestCase):
    def test_running_tasks_update_the_workspace_log_tab_after_page_load(self) -> None:
        render_activity = APP[
            APP.index("function renderLogButtonActivity()"):
            APP.index("function setBusy(")
        ]

        self.assertIn("state.hasRunningTasks || localBusy", render_activity)
        self.assertIn('document.querySelector("[data-workspace-running]")', render_activity)
        self.assertIn("workspaceRunningDot.hidden = !active", render_activity)
        self.assertIn("has-running-task", render_activity)
        self.assertIn('workspaceLogTab.setAttribute("aria-busy", active ? "true" : "false")', render_activity)
        self.assertIn('workspaceLogTab.setAttribute("aria-label", active ? "日志，有任务正在运行" : "日志")', render_activity)
        self.assertIn("data-workspace-running hidden", INDEX)

    def test_unread_reports_update_and_clear_the_workspace_report_tabs(self) -> None:
        report_indicator = APP[
            APP.index("function setWorkspaceReportTabNewState("):
            APP.index("function setReportLibraryNewIndicators(")
        ]
        viewed_handler = APP[
            APP.index('window.addEventListener("workspace-tab-change", (event) => {'):
            APP.index("function markReportConsumed(")
        ]

        self.assertIn('document.querySelector(`[data-workspace-tab="${tabName}"]`)', report_indicator)
        self.assertIn('dot.dataset.workspaceReportUnread = ""', report_indicator)
        self.assertIn('dot.className = "workspace-running-dot"', report_indicator)
        self.assertIn("dot.hidden = !visible", report_indicator)
        self.assertIn('setWorkspaceReportTabNewState("weekly"', report_indicator)
        self.assertIn('setWorkspaceReportTabNewState("performance"', report_indicator)
        self.assertIn('reportType === "weekly" || reportType === "performance"', viewed_handler)
        self.assertIn("markReportCategoryViewed(reportType)", viewed_handler)


if __name__ == "__main__":
    unittest.main()

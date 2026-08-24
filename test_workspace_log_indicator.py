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
        self.assertIn('setWorkspaceTabIndicator(workspaceLogTab, "indicatorRunning", active)', render_activity)
        self.assertIn("has-running-task", render_activity)
        self.assertIn('workspaceLogTab.setAttribute("aria-busy", active ? "true" : "false")', render_activity)
        self.assertIn('workspaceLogTab.setAttribute("aria-label", active ? "任务日志，有任务正在运行" : "任务日志")', render_activity)
        self.assertIn("data-workspace-indicator hidden", INDEX)
        self.assertNotIn("workspace-running-dot", INDEX)

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
        self.assertIn('setWorkspaceTabIndicator(tab, "indicatorReport", visible)', report_indicator)
        self.assertIn('setWorkspaceReportTabNewState("weekly"', report_indicator)
        self.assertIn('setWorkspaceReportTabNewState("performance"', report_indicator)
        self.assertIn('reportType === "weekly" || reportType === "performance"', viewed_handler)
        self.assertIn("markReportCategoryViewed(reportType)", viewed_handler)

    def test_real_task_acceptance_announces_motion_to_the_log_tab(self) -> None:
        self.assertIn('function announceTaskCreated(title, detail)', APP)
        self.assertIn('window.CMHKMotion?.announce({ kind: "task", target: "log", title, detail })', APP)
        self.assertIn('announceTaskCreated("定期数据爬虫"', APP)
        self.assertIn('announceTaskCreated("战略周报生成"', APP)
        self.assertIn('announceTaskCreated("业绩摘要生成"', APP)
        self.assertIn('announceTaskCreated("音频摘要生成"', APP)


if __name__ == "__main__":
    unittest.main()

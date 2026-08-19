from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
INDEX = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "web" / "static" / "workspace-tabs.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web" / "static" / "workspace-tabs.css").read_text(encoding="utf-8")
SUBSCRIPTION_SCRIPT = (ROOT / "web" / "static" / "subscription-admin.js").read_text(encoding="utf-8")
SUBSCRIPTION_STYLE = (ROOT / "web" / "static" / "subscription-admin.css").read_text(encoding="utf-8")


class WorkspaceTabsTests(unittest.TestCase):
    def test_dashboard_and_five_modules_have_accessible_tabs_and_panels(self):
        modules = (
            "dashboard",
            "monitoring",
            "competitor",
            "news",
            "weekly",
            "performance",
            "review",
            "subscriptions",
            "ai",
            "log",
            "fault",
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
        self.assertIn('/static/workspace-tabs.css?v=36', INDEX)
        self.assertIn('/static/workspace-tabs.js?v=30', INDEX)
        self.assertIn("backdrop-filter: blur(22px) saturate(138%)", STYLE)
        self.assertIn("border-radius: 18px", STYLE)
        self.assertIn(".workspace-tab.is-active::after", STYLE)
        self.assertIn("prefers-reduced-motion: reduce", STYLE)
        self.assertIn("@keyframes workspace-running-breathe", STYLE)
        self.assertIn("@keyframes workspace-collapse-chevron-float", STYLE)
        self.assertIn("clip-path: polygon", STYLE)
        self.assertIn(".workspace-nav-collapse span::before { animation: none !important; }", STYLE)
        self.assertIn("Boolean(state.status?.tasks?.hasRunning)", SCRIPT)
        self.assertIn("runningDot.hidden = !running", SCRIPT)
        self.assertIn("Unified floating workspace surfaces", STYLE)
        self.assertIn("--workspace-surface", STYLE)
        for asset in (
            "workspace-bg-intelligence-v1.png",
            "workspace-bg-content-v1.png",
            "workspace-bg-operations-v1.png",
        ):
            self.assertIn(asset, STYLE)
            self.assertTrue((ROOT / "web" / "static" / "assets" / asset).exists())

    def test_subscription_management_uses_server_and_feishu_delivery(self):
        self.assertIn('id="workspace-tab-subscriptions"', INDEX)
        self.assertIn('/static/subscription-admin.html?v=7', INDEX)
        self.assertIn('fetch("/api/subscriptions"', SUBSCRIPTION_SCRIPT)
        self.assertIn('action: "publish"', SUBSCRIPTION_SCRIPT)
        self.assertIn('action: "push"', SUBSCRIPTION_SCRIPT)
        self.assertIn("推送台账", SUBSCRIPTION_SCRIPT)
        self.assertIn("confirmBulk", SUBSCRIPTION_SCRIPT)
        self.assertIn("@media (max-width: 560px)", SUBSCRIPTION_STYLE)
        self.assertIn("border-radius: 15px", SUBSCRIPTION_STYLE)
        self.assertIn("workspace-bg-content-v1.png", SUBSCRIPTION_STYLE)
        self.assertNotIn("订阅服务 UI DEMO", SCRIPT)
        self.assertNotIn('localStorage.setItem("cmhk-weekly-subscription"', SCRIPT)

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

    def test_report_modules_open_pdf_previews_and_keep_word_downloads_without_top_kpi_strip(self):
        self.assertNotIn("docx-preview", INDEX)
        self.assertIn("reportPreviewPdfUrl", SCRIPT)
        self.assertIn("PDF 版式预览 · 下载保留原始 Word", SCRIPT)
        self.assertIn("data-report-preview-expand", SCRIPT)
        self.assertIn("workspaceReportSide-${kind}", SCRIPT)
        self.assertIn("showReportPreview(row.dataset.path)", SCRIPT)
        render_reports = SCRIPT[SCRIPT.index("function renderReports"):SCRIPT.index("function subscriptionPanel")]
        self.assertNotIn("workspace-kpi-strip", render_reports)
        self.assertIn(".report-preview.is-maximized", STYLE)
        self.assertIn("height: 100dvh", STYLE)
        self.assertIn(".workspace-content { height: 100%;", STYLE)
        self.assertIn("transform: none !important", STYLE)
        self.assertGreaterEqual(SCRIPT.count("state.previewRequest += 1"), 2)
        self.assertIn("border-radius: 10px", STYLE)

    def test_existing_feishu_review_sheet_is_reused_as_a_workspace_tab(self):
        self.assertIn('id="workspace-tab-review"', INDEX)
        self.assertIn("飞书表格审核栏", INDEX)
        self.assertIn('document.querySelector("#newsReviewWorkspace")', SCRIPT)
        self.assertIn('appendChild(review)', SCRIPT)

    def test_fault_monitor_uses_real_task_archive_without_control_actions(self):
        self.assertIn('id="workspace-tab-fault"', INDEX)
        self.assertIn("故障报警监控系统", INDEX)
        self.assertIn('fetch("/api/task-runs?limit=100"', SCRIPT)
        self.assertIn("renderFaultMonitor", SCRIPT)
        self.assertIn('data-fault-filter="status"', SCRIPT)
        self.assertIn('data-fault-filter="kind"', SCRIPT)
        self.assertIn("data-fault-detail", SCRIPT)
        self.assertIn("报警总数", SCRIPT)
        self.assertIn("原因摘要", SCRIPT)
        self.assertIn("解决方法", SCRIPT)
        self.assertIn("faultSolutions", SCRIPT)
        self.assertIn("/api/task-run-log?id=", SCRIPT)
        self.assertIn('class="fault-row"', SCRIPT)
        self.assertIn(".fault-table .fault-row", STYLE)
        self.assertNotIn("fault-summary", SCRIPT)
        self.assertNotIn("data-restart", SCRIPT)

    def test_competitor_workbench_starts_empty_and_uses_historical_data(self):
        self.assertIn("competitor-workbench-data.json", SCRIPT)
        self.assertIn("选择竞对", SCRIPT)
        self.assertIn("选择指标", SCRIPT)
        self.assertIn("选择年限", SCRIPT)
        self.assertIn("完成上方选择后生成对比图", SCRIPT)
        self.assertIn('fetch("/api/competitor-insight"', SCRIPT)
        self.assertIn("buildCompetitorChart", SCRIPT)
        self.assertIn("多年趋势对比", SCRIPT)
        self.assertIn("查看数据明细与官方来源", SCRIPT)
        self.assertIn("AI 竞争洞察", SCRIPT)
        self.assertIn("buildCompetitorFallbackInsight", SCRIPT)
        self.assertIn("内网 AI 正在等待安全加载", SCRIPT)
        self.assertIn('"DATA SUMMARY"', SCRIPT)
        self.assertIn("竞争格局", SCRIPT)
        self.assertIn("公司定位", SCRIPT)
        self.assertIn("业务含义", SCRIPT)
        self.assertIn("data-competitor-insight-icon", SCRIPT)
        self.assertNotIn("competitor-insight-facts", SCRIPT)
        self.assertNotIn("最新共同年差距", SCRIPT)
        self.assertNotIn("数据口径</span>", SCRIPT)
        self.assertIn('["~", "approx", "≈"]', SCRIPT)
        self.assertIn("competitor-insight-shimmer", STYLE)
        self.assertIn("competitor-matrix", STYLE)
        self.assertIn("competitor-chart-series", STYLE)
        self.assertIn("competitorInsightController?.abort()", SCRIPT)
        self.assertIn('error.name === "AbortError"', SCRIPT)
        self.assertIn("所选组合暂无可直接比较的数据", SCRIPT)
        self.assertIn("仅展示所选竞对同单位可比指标", SCRIPT)
        self.assertIn("所选组合的计量单位不一致", SCRIPT)
        self.assertIn("依次选择竞对、同单位指标和共同披露年", SCRIPT)
        self.assertIn("knowledgeBases", SCRIPT)
        self.assertNotIn("competitor-knowledge-layer", SCRIPT)
        self.assertIn("本地运营商知识库", SCRIPT)
        self.assertIn("全球重点运营商知识库", SCRIPT)
        self.assertIn("competitor-result-overview", STYLE)
        self.assertIn("DATA SUMMARY", SCRIPT)
        self.assertIn("fallbackInsight.insights", SCRIPT)

    def test_review_sheet_uses_cached_snapshot_and_inline_escape_is_safe(self):
        review_script = (ROOT / "web" / "static" / "news-review-sheet.js").read_text(encoding="utf-8")
        self.assertIn("cmhk-news-review-snapshot-v1", review_script)
        self.assertIn('workspace.classList.contains("workspace-inline-review")', review_script)

    def test_news_module_replays_the_full_ai_review_pipeline_by_date_and_run(self):
        self.assertIn('fetch("/api/crawl-runs?taskKind=strategic-news&limit=365")', SCRIPT)
        self.assertIn("/api/crawl-run-log?id=", SCRIPT)
        self.assertIn("data-news-date-option", SCRIPT)
        self.assertIn("data-news-run-option", SCRIPT)
        self.assertIn("newsSelectedRunIds", SCRIPT)
        self.assertIn("aggregateNewsStages", SCRIPT)
        self.assertIn("openNewsStageDetail", SCRIPT)
        self.assertIn("该阶段日志输出", SCRIPT)
        self.assertIn("展开该批次完整原始日志", SCRIPT)
        self.assertIn("完整运行归档", SCRIPT)
        self.assertIn("本轮真实新增新闻", SCRIPT)
        self.assertIn("AI纳入理由", SCRIPT)
        for stage in ("线索发现", "确定性门禁", "AI 语义审核", "历史语义去重", "飞书写入回读", "群组推送"):
            self.assertIn(stage, SCRIPT)
        self.assertIn("newsRuns", SCRIPT)
        self.assertNotIn("最新战略快讯", SCRIPT)
        self.assertIn("@keyframes news-signal", STYLE)
        self.assertIn("prefers-reduced-motion", STYLE)


if __name__ == "__main__":
    unittest.main()

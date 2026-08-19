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
        self.assertIn('/static/workspace-tabs.css?v=49', INDEX)
        self.assertIn('/static/workspace-tabs.js?v=38', INDEX)
        self.assertIn("width: min(calc(100% - 28px),1600px)", STYLE)
        self.assertIn("@media (max-width: 1490px)", STYLE)
        self.assertIn("aspect-ratio: 960 / 330", STYLE)
        self.assertIn("backdrop-filter: blur(22px) saturate(138%)", STYLE)
        self.assertIn("border-radius: 18px", STYLE)
        self.assertIn(".workspace-tab.is-active::after", STYLE)
        self.assertIn("prefers-reduced-motion: reduce", STYLE)
        self.assertIn("@keyframes workspace-running-breathe", STYLE)
        self.assertIn("@keyframes workspace-collapse-chevron-float", STYLE)
        self.assertIn("clip-path: polygon", STYLE)
        self.assertIn("Counter that", STYLE)
        self.assertIn("calc(236px / var(--fit-scale))", STYLE)
        self.assertIn("scale(calc(1 / var(--fit-scale)))", STYLE)
        self.assertIn(".dashboard-page.workspace-ai-active .brand-bar { display: flex !important; }", STYLE)
        self.assertIn(".dashboard-page.workspace-ai-active .workspace-layout { height: calc(100dvh - 60px); }", STYLE)
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
        self.assertIn('/static/subscription-admin.html?v=9', INDEX)
        self.assertNotIn('class="subtitle"', SUBSCRIPTION_SCRIPT)
        self.assertIn('fetch("/api/subscriptions"', SUBSCRIPTION_SCRIPT)
        self.assertIn('action: "publish"', SUBSCRIPTION_SCRIPT)
        self.assertIn('action: "push"', SUBSCRIPTION_SCRIPT)
        self.assertIn("strategic_news_schedule", SUBSCRIPTION_SCRIPT)
        self.assertIn("战略新闻定时推送", SUBSCRIPTION_SCRIPT)
        self.assertIn("06:00 / 13:30", SUBSCRIPTION_SCRIPT)
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
        self.assertIn("新闻过滤与审核", INDEX)
        self.assertIn('document.querySelector("#newsReviewWorkspace")', SCRIPT)
        self.assertIn('appendChild(review)', SCRIPT)

    def test_navigation_groups_and_renames_business_modules(self):
        intelligence = INDEX[INDEX.index('id="workspace-group-intelligence"'):INDEX.index('id="workspace-group-products"')]
        products = INDEX[INDEX.index('id="workspace-group-products"'):INDEX.index('id="workspace-group-tools"')]
        operations = INDEX[INDEX.index('id="workspace-group-tools"'):INDEX.index('id="workspace-panel-dashboard"')]
        self.assertIn("新闻过滤与审核", intelligence)
        self.assertNotIn("竞对数据分析", intelligence)
        self.assertLess(products.index("竞对数据分析"), products.index("战略周报"))
        self.assertIn("AI智能助手", products)
        self.assertNotIn("AI问数", INDEX)
        self.assertNotIn("AI智能助手", operations)

    def test_fault_monitor_uses_real_incident_ledger_without_control_actions(self):
        self.assertIn('id="workspace-tab-fault"', INDEX)
        self.assertIn("故障报警监控系统", INDEX)
        self.assertIn('fetch("/api/project-incidents?limit=100"', SCRIPT)
        self.assertIn("state.faultTotal", SCRIPT)
        self.assertIn("filtersActive ? rows.length : state.faultTotal", SCRIPT)
        self.assertIn("renderFaultMonitor", SCRIPT)
        self.assertIn('data-fault-filter="status"', SCRIPT)
        self.assertIn('data-fault-filter="kind"', SCRIPT)
        self.assertIn("data-fault-detail", SCRIPT)
        self.assertIn("报警总数", SCRIPT)
        self.assertIn("原因摘要", SCRIPT)
        self.assertIn("紧急程度", SCRIPT)
        self.assertIn("处理人员", SCRIPT)
        self.assertIn('data-fault-sort="${key}"', SCRIPT)
        self.assertIn('aria-sort="${ariaSort}"', SCRIPT)
        self.assertIn("faultSeverity", SCRIPT)
        self.assertIn("faultHandler", SCRIPT)
        self.assertIn("解决方法", SCRIPT)
        self.assertIn("faultSolutions", SCRIPT)
        self.assertIn('task.source === "project-monitor"', SCRIPT)
        self.assertIn('class="fault-row"', SCRIPT)
        self.assertIn(".fault-table .fault-row", STYLE)
        self.assertNotIn("fault-summary", SCRIPT)
        self.assertNotIn("data-restart", SCRIPT)

    def test_news_and_competitor_results_keep_vertical_scrolling(self):
        self.assertIn("#workspace-panel-news .news-process-panel", STYLE)
        self.assertIn("#workspace-panel-competitor .competitor-result", STYLE)
        self.assertIn("overflow-y: auto !important", STYLE)

    def test_competitor_workbench_starts_empty_and_uses_historical_data(self):
        self.assertIn("competitor-workbench-data.json", SCRIPT)
        self.assertIn("competitor-workbench-data.json?v=2", SCRIPT)
        self.assertIn("选择竞对", SCRIPT)
        self.assertIn("选择指标", SCRIPT)
        self.assertIn("选择年限", SCRIPT)
        self.assertIn("完成上方选择后生成对比图", SCRIPT)
        self.assertIn('fetch("/api/competitor-insight-stream"', SCRIPT)
        self.assertIn('fetch("/api/competitor-insight"', SCRIPT)
        self.assertIn("兼容模式正在生成真实 AI 结果", SCRIPT)
        self.assertIn("buildCompetitorChart", SCRIPT)
        self.assertIn("competitor-result-header", SCRIPT)
        self.assertNotIn("多年趋势对比", SCRIPT)
        self.assertIn("查看数据明细与官方来源", SCRIPT)
        self.assertIn("AI 竞争洞察", SCRIPT)
        self.assertIn("buildCompetitorFallbackInsight", SCRIPT)
        self.assertIn('card.classList.remove("is-loading", "is-streaming")', SCRIPT)
        self.assertNotIn("内网 AI 正在等待安全加载", SCRIPT)
        self.assertIn('"LOCAL DATA"', SCRIPT)
        self.assertIn('"AI STREAM"', SCRIPT)
        self.assertIn("renderCompetitorInsightDraft", SCRIPT)
        self.assertIn("竞争格局", SCRIPT)
        self.assertIn("公司定位", SCRIPT)
        self.assertIn("业务含义", SCRIPT)
        self.assertIn("data-competitor-insight-icon", SCRIPT)
        self.assertNotIn("competitor-insight-facts", SCRIPT)
        self.assertNotIn("最新共同年差距", SCRIPT)
        self.assertNotIn("数据口径</span>", SCRIPT)
        self.assertIn('["~", "approx", "≈"]', SCRIPT)
        self.assertIn("competitor-insight-shimmer", STYLE)
        self.assertIn("overflow-y: scroll", STYLE)
        self.assertIn("scrollbar-gutter: stable", STYLE)
        self.assertIn("competitor-matrix", STYLE)
        self.assertIn("competitor-chart-series", STYLE)
        self.assertIn("competitorInsightController?.abort()", SCRIPT)
        self.assertIn('error.name === "AbortError"', SCRIPT)
        self.assertIn("所选组合暂无可直接比较的数据", SCRIPT)
        self.assertIn("仅展示所选竞对同单位可比指标", SCRIPT)
        self.assertIn("visibleCompetitorIds", SCRIPT)
        self.assertIn("competitorHasCommonMetric", SCRIPT)
        self.assertIn('classList.add("is-disappearing")', SCRIPT)
        self.assertIn("competitor-option-appear", STYLE)
        self.assertIn("所选组合的计量单位不一致", SCRIPT)
        self.assertNotIn("依次选择竞对、同单位指标和共同披露年", SCRIPT)
        self.assertNotIn("正在汇总 ${runs.length} 次真实新闻任务", SCRIPT)
        self.assertIn('id="newsReviewSyncText" role="status" hidden', INDEX)
        self.assertNotIn("competitor-knowledge-layer", SCRIPT)
        self.assertIn("本地运营商知识库", SCRIPT)
        self.assertIn("全球重点运营商知识库", SCRIPT)
        self.assertIn("competitor-result-overview", STYLE)
        self.assertIn("LOCAL DATA", SCRIPT)
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

    def test_news_module_exposes_draggable_live_lineage_and_next_run_feedback(self):
        for label in (
            "每日情报如何形成",
            "定时触发",
            "固定来源与关键词",
            "定时爬虫页面线索",
            "Agentic 补缺搜索",
            "本轮新增线索",
            "影响下一轮",
        ):
            self.assertIn(label, SCRIPT)
        self.assertIn("data-news-lineage-node", SCRIPT)
        self.assertIn("setPointerCapture", SCRIPT)
        self.assertIn("syncNewsLineageEdges", SCRIPT)
        self.assertIn("localStorage.setItem(storageKey", SCRIPT)
        self.assertIn("页面变化线索会生成关联查询与关键词", SCRIPT)
        self.assertIn("30分钟到时转下轮", SCRIPT)
        self.assertIn("news-lineage-pulse", STYLE)
        self.assertIn("@keyframes news-lineage-flow", STYLE)
        self.assertIn(".news-lineage-canvas.is-paused", STYLE)


if __name__ == "__main__":
    unittest.main()

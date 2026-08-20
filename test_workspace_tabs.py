from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
INDEX = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "web" / "static" / "workspace-tabs.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web" / "static" / "workspace-tabs.css").read_text(encoding="utf-8")
SUBSCRIPTION_SCRIPT = (ROOT / "web" / "static" / "subscription-admin.js").read_text(encoding="utf-8")
SUBSCRIPTION_STYLE = (ROOT / "web" / "static" / "subscription-admin.css").read_text(encoding="utf-8")
AUTH_SCRIPT = (ROOT / "web" / "static" / "auth-client.js").read_text(encoding="utf-8")
ORGANIZATION_SCRIPT = (ROOT / "web" / "static" / "organization-admin.js").read_text(encoding="utf-8")
ORGANIZATION_STYLE = (ROOT / "web" / "static" / "organization-admin.css").read_text(encoding="utf-8")
NEWS_REVIEW_STYLE = (ROOT / "web" / "static" / "news-review-sheet.css").read_text(encoding="utf-8")


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
            "organization",
        )
        for module in modules:
            self.assertIn(f'id="workspace-tab-{module}"', INDEX)
            self.assertIn(f'aria-controls="workspace-panel-{module}"', INDEX)
            self.assertIn(f'id="workspace-panel-{module}"', INDEX)
            self.assertIn(f'data-workspace-panel="{module}"', INDEX)
        self.assertEqual(INDEX.count('role="tab"'), len(modules))
        self.assertEqual(INDEX.count('role="tabpanel"'), len(modules))

    def test_auth_permissions_gate_tabs_requests_and_organization_admin(self):
        self.assertIn('/static/auth-client.js?v=3', INDEX)
        self.assertIn('/static/organization-admin.js?v=13', INDEX)
        self.assertIn('/static/organization-admin.css?v=12', INDEX)
        self.assertIn('await window.CMHKAuth?.ready', SCRIPT)
        self.assertIn('window.CMHKAuth?.hasModule(module)', SCRIPT)
        self.assertIn('definitions.filter(([, module]) => can(module))', SCRIPT)
        self.assertIn('iframe[data-src]', SCRIPT)
        self.assertIn('fetch("/api/auth/me"', AUTH_SCRIPT)
        self.assertIn('fetch("/api/auth/logout"', AUTH_SCRIPT)
        self.assertIn('id="authUserMenuButton"', INDEX)
        self.assertIn('id="authUserAvatarImage"', INDEX)
        self.assertIn('aria-haspopup="menu"', INDEX)
        self.assertIn('document.addEventListener("pointerdown"', AUTH_SCRIPT)
        self.assertIn('event.key === "Escape"', AUTH_SCRIPT)
        self.assertIn('打开账户菜单', AUTH_SCRIPT)
        self.assertIn('request("/api/auth/admin/users")', ORGANIZATION_SCRIPT)
        self.assertIn('/api/auth/admin/users/${encodeURIComponent(detail.dataset.userId)}', ORGANIZATION_SCRIPT)
        self.assertIn('/api/auth/admin/directory/search?q=${encodeURIComponent(query)}', ORGANIZATION_SCRIPT)
        self.assertIn('request("/api/auth/admin/users/import"', ORGANIZATION_SCRIPT)
        self.assertIn('request("/api/auth/admin/audit?limit=200")', ORGANIZATION_SCRIPT)
        self.assertIn("可审计操作记录", ORGANIZATION_SCRIPT)
        self.assertIn("个人行动记录", ORGANIZATION_SCRIPT)
        self.assertIn("data-select-user", ORGANIZATION_SCRIPT)
        self.assertIn("person.avatarUrl", ORGANIZATION_SCRIPT)
        self.assertIn("!user.developmentAccount", ORGANIZATION_SCRIPT)
        self.assertIn("data-delete-user", ORGANIZATION_SCRIPT)
        self.assertIn('method: "DELETE"', ORGANIZATION_SCRIPT)
        self.assertIn('data-directory-open aria-label="添加成员"', ORGANIZATION_SCRIPT)
        self.assertNotIn('>添加飞书成员</button>', ORGANIZATION_SCRIPT)
        self.assertNotIn('>刷新成员</button>', ORGANIZATION_SCRIPT)
        self.assertNotIn('class="organization-heading"', ORGANIZATION_SCRIPT)
        self.assertNotIn('ORGANIZATION &amp; ACCESS', ORGANIZATION_SCRIPT)
        self.assertIn('query.length < 2', ORGANIZATION_SCRIPT)
        self.assertIn('function highlightSearchMatch(value, query)', ORGANIZATION_SCRIPT)
        self.assertIn('class="organization-search-match"', ORGANIZATION_SCRIPT)
        self.assertIn('highlightSearchMatch(user.name || "未命名成员", directory.query)', ORGANIZATION_SCRIPT)
        self.assertIn('highlightSearchMatch([user.department, user.email]', ORGANIZATION_SCRIPT)
        self.assertIn('.organization-search-match', ORGANIZATION_STYLE)
        self.assertIn('class="organization-title-readonly" aria-label="员工岗位"', ORGANIZATION_SCRIPT)
        self.assertNotIn('data-title maxlength="80"', ORGANIZATION_SCRIPT)
        self.assertNotIn('title: detail.querySelector("[data-title]").value', ORGANIZATION_SCRIPT)
        self.assertNotIn('修改岗位', ORGANIZATION_SCRIPT)
        self.assertIn('.organization-title-readonly', ORGANIZATION_STYLE)

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
        self.assertIn('/static/news-review-sheet.css?v=4', INDEX)
        self.assertRegex(INDEX, r'/static/workspace-tabs\.css\?v=\d+')
        self.assertRegex(INDEX, r'/static/workspace-tabs\.js\?v=\d+')
        self.assertIn("width: min(calc(100% - 28px),1600px)", STYLE)
        self.assertIn("@media (max-width: 1490px)", STYLE)
        self.assertIn("aspect-ratio: 960 / 390", STYLE)
        self.assertIn("backdrop-filter: blur(22px) saturate(138%)", STYLE)
        self.assertIn("border-radius: 18px", STYLE)
        self.assertIn(".workspace-tab.is-active::after", STYLE)
        self.assertIn("prefers-reduced-motion: reduce", STYLE)
        self.assertIn("workspace-motion-stage", STYLE)
        self.assertIn("workspace-signal-arrival", STYLE)
        self.assertIn("animation: workspace-alert-breathe 1.55s ease-in-out infinite", STYLE)
        self.assertNotIn(".workspace-tab.has-unread-signal:not(.is-active)", STYLE)
        self.assertIn("0%,100% { border-color: transparent;", STYLE)
        self.assertIn("clearWorkspaceSignal(target);", SCRIPT)
        self.assertIn('window.CMHKMotion = { announce: announceWorkspaceEvent }', SCRIPT)
        self.assertIn('event.data?.type !== "cmhk-workspace-motion"', SCRIPT)
        self.assertIn('refreshFaultData({ quiet: true })', SCRIPT)
        self.assertNotIn("workspace-running-dot", STYLE)
        self.assertIn('class="workspace-nav-icon"', INDEX)
        self.assertIn('class="workspace-nav-icon-arrow"', INDEX)
        self.assertNotIn("workspace-collapse-chevron-float", STYLE)
        self.assertNotIn("clip-path: polygon(13% 5%", STYLE)
        self.assertIn("Counter that", STYLE)
        self.assertIn("calc(236px / var(--fit-scale))", STYLE)
        self.assertIn("scale(calc(1 / var(--fit-scale)))", STYLE)
        self.assertIn(".dashboard-page.workspace-ai-active .brand-bar { display: flex !important; }", STYLE)
        self.assertIn(".dashboard-page.workspace-ai-active .workspace-layout { height: calc(100dvh - 60px); }", STYLE)
        self.assertIn(".workspace-nav-icon-arrow,", STYLE)
        self.assertIn('window.matchMedia("(prefers-reduced-motion: reduce)")', SCRIPT)
        self.assertIn('panel.classList.add("is-panel-entering")', SCRIPT)
        self.assertIn('motionPreference.matches ? "auto" : "smooth"', SCRIPT)
        self.assertIn("@keyframes workspace-panel-enter", STYLE)
        self.assertIn("@keyframes workspace-dialog-enter", STYLE)
        self.assertIn("@keyframes workspace-content-replace", STYLE)
        self.assertIn("@keyframes organization-menu-enter", ORGANIZATION_STYLE)
        self.assertIn("@keyframes news-review-workspace-enter", NEWS_REVIEW_STYLE)
        self.assertIn("@keyframes news-review-filter-enter", NEWS_REVIEW_STYLE)
        self.assertIn('layout.classList.add("is-nav-positioning")', SCRIPT)
        self.assertIn("--workspace-nav-motion-x", SCRIPT)
        self.assertIn("transition: transform .52s cubic-bezier(.22,1,.36,1)", STYLE)
        self.assertIn('button.setAttribute("aria-busy", "true")', SCRIPT)
        self.assertIn("Boolean(state.status?.tasks?.hasRunning)", SCRIPT)
        self.assertIn('runningIndicator.dataset.indicatorRunning = "true"', SCRIPT)
        self.assertIn('["indicatorRunning", "indicatorReport", "indicatorSignal"]', SCRIPT)
        self.assertIn("Unified floating workspace surfaces", STYLE)
        self.assertIn("--workspace-surface", STYLE)
        for asset in (
            "workspace-bg-intelligence-v1.png",
            "workspace-bg-content-v1.png",
            "workspace-bg-operations-v1.png",
        ):
            self.assertIn(asset, STYLE)
            self.assertTrue((ROOT / "web" / "static" / "assets" / asset).exists())
        self.assertIn(":not(.workspace-ai-active) .workspace-panel", STYLE)
        self.assertIn("background-color: rgba(7, 29, 41, .56) !important", STYLE)
        self.assertIn("backdrop-filter: blur(7px) saturate(120%)", STYLE)
        self.assertIn('/static/subscription-admin.css?v=20', (ROOT / "web" / "static" / "subscription-admin.html").read_text(encoding="utf-8"))

    def test_subscription_management_uses_server_and_feishu_delivery(self):
        self.assertIn('id="workspace-tab-subscriptions"', INDEX)
        self.assertIn('/static/subscription-admin.html?v=12', INDEX)
        self.assertNotIn('class="subtitle"', SUBSCRIPTION_SCRIPT)
        self.assertIn('fetch("/api/subscriptions"', SUBSCRIPTION_SCRIPT)
        self.assertIn('action: "publish"', SUBSCRIPTION_SCRIPT)
        self.assertIn('action: "pushLatest"', SUBSCRIPTION_SCRIPT)
        self.assertIn('announceDeliveredMessage(payload.action, evidence)', SUBSCRIPTION_SCRIPT)
        self.assertIn("strategic_news_schedule", SUBSCRIPTION_SCRIPT)
        self.assertIn("战略新闻定时推送", SUBSCRIPTION_SCRIPT)
        self.assertIn("06:00 / 13:30", SUBSCRIPTION_SCRIPT)
        self.assertIn("推送记录", SUBSCRIPTION_SCRIPT)
        self.assertIn("confirmBulk", SUBSCRIPTION_SCRIPT)
        self.assertIn("@media (max-width: 560px)", SUBSCRIPTION_STYLE)
        self.assertIn("border-radius: 14px", SUBSCRIPTION_STYLE)
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
        self.assertIn("正在读取 PDF 版式预览", SCRIPT)
        self.assertIn("data-report-preview-expand", SCRIPT)
        self.assertIn("workspaceReportSide-${kind}", SCRIPT)
        self.assertIn("showReportPreview(row.dataset.path)", SCRIPT)
        render_reports = SCRIPT[SCRIPT.index("function renderReports"):SCRIPT.index("function reportPreviewPlaceholder")]
        self.assertNotIn("workspace-kpi-strip", render_reports)
        self.assertIn(".report-preview.is-maximized", STYLE)
        self.assertIn("height: 100dvh", STYLE)
        self.assertIn(".workspace-content { height: 100%;", STYLE)
        self.assertIn("transform: none !important", STYLE)
        self.assertIn("state.previewRequest.weekly += 1", SCRIPT)
        self.assertIn("state.previewRequest.performance += 1", SCRIPT)
        self.assertIn("border-radius: 10px", STYLE)

    def test_existing_feishu_review_sheet_is_reused_as_a_workspace_tab(self):
        self.assertIn('id="workspace-tab-review"', INDEX)
        self.assertIn("新闻人工筛选", INDEX)
        self.assertIn('document.querySelector("#newsReviewWorkspace")', SCRIPT)
        self.assertIn('appendChild(review)', SCRIPT)

    def test_navigation_groups_and_renames_business_modules(self):
        intelligence = INDEX[INDEX.index('id="workspace-group-intelligence"'):INDEX.index('id="workspace-group-products"')]
        products = INDEX[INDEX.index('id="workspace-group-products"'):INDEX.index('id="workspace-group-tools"')]
        operations = INDEX[INDEX.index('id="workspace-group-tools"'):INDEX.index('id="workspace-panel-dashboard"')]
        self.assertIn("新闻生产", intelligence)
        self.assertIn("新闻检索系统", intelligence)
        self.assertIn("新闻人工筛选", intelligence)
        self.assertNotIn("新闻获取与推送", intelligence)
        self.assertNotIn("新闻过滤与审核", intelligence)
        self.assertNotIn("竞对数据分析", intelligence)
        self.assertLess(products.index("竞对数据分析"), products.index("战略周报"))
        self.assertIn("AI智能助手", products)
        self.assertNotIn("AI问数", INDEX)
        self.assertNotIn("AI智能助手", operations)

    def test_fault_monitor_uses_real_incident_ledger_with_identity_bound_resolution(self):
        self.assertIn('id="workspace-tab-fault"', INDEX)
        self.assertIn("故障报警监控系统", INDEX)
        self.assertIn('fetch("/api/project-incidents?limit=500"', SCRIPT)
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
        self.assertIn('data-fault-resolve=', SCRIPT)
        self.assertIn('fetch("/api/project-incidents/resolve"', SCRIPT)
        self.assertIn('id="faultActionFeedback"', SCRIPT)
        self.assertIn("正在处理报警", SCRIPT)
        self.assertIn("处理失败，未改变报警状态", SCRIPT)
        self.assertIn("preserveFeedback: true", SCRIPT)
        self.assertIn('incident_status: "resolved"', SCRIPT)
        self.assertIn(".fault-row.is-resolving", STYLE)
        self.assertIn(".fault-action-feedback.is-success", STYLE)
        self.assertIn(".fault-action-feedback.is-error", STYLE)
        self.assertIn("faultHandlerAvatar", SCRIPT)
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
        self.assertIn('"RETRY"', SCRIPT)
        self.assertIn('"AI STREAM"', SCRIPT)
        self.assertIn("renderCompetitorInsightDraft", SCRIPT)
        self.assertIn("parseCompetitorInsightItems", SCRIPT)
        self.assertIn("filter(Boolean).slice(0, 3)", SCRIPT)
        self.assertNotIn("competitor-insight-markdown", SCRIPT)
        self.assertNotIn("competitor-insight-markdown", STYLE)
        self.assertIn("本次 AI 暂未完成，请稍后重试", SCRIPT)
        self.assertNotIn("当前显示本地数据总结", SCRIPT)
        self.assertIn("竞争格局", SCRIPT)
        self.assertIn("公司定位", SCRIPT)
        self.assertIn("业务含义", SCRIPT)
        self.assertIn("data-competitor-insight-icon", SCRIPT)
        self.assertIn('<svg viewBox="0 0 32 32" aria-hidden="true" focusable="false">', SCRIPT)
        self.assertIn(".competitor-insight-identity i svg", STYLE)
        self.assertIn("competitor-insight-star-twinkle", STYLE)
        self.assertIn("svg path:last-child { animation-delay: .42s; }", STYLE)
        self.assertNotIn("@keyframes competitor-insight-pulse", STYLE)
        self.assertNotIn("/static/assets/ai-insight-sparkle.png", SCRIPT)
        self.assertIn('setCompetitorInsightStatus(card, status || (isAi ? ""', SCRIPT)
        self.assertNotIn("内网 AI 已完成真实生成", SCRIPT)
        self.assertNotIn("AI未生成：", SCRIPT)
        self.assertIn("font-size: 14px", STYLE)
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
        self.assertNotIn("LOCAL DATA", SCRIPT)
        self.assertNotIn("fallbackInsight.insights", SCRIPT)

    def test_review_sheet_uses_cached_snapshot_and_inline_escape_is_safe(self):
        review_script = (ROOT / "web" / "static" / "news-review-sheet.js").read_text(encoding="utf-8")
        self.assertIn("cmhk-news-review-snapshot-v1", review_script)
        self.assertIn('workspace.classList.contains("workspace-inline-review")', review_script)

    def test_news_module_replays_the_full_ai_review_pipeline_by_single_date(self):
        self.assertIn('fetch("/api/crawl-runs?taskKind=strategic-news&limit=365")', SCRIPT)
        self.assertIn("/api/crawl-run-log?id=", SCRIPT)
        self.assertIn("data-news-date-select", SCRIPT)
        self.assertNotIn("data-news-run-option", SCRIPT)
        self.assertNotIn("data-news-date-option", SCRIPT)
        self.assertIn("newsSelectedDate", SCRIPT)
        self.assertIn("newsSelectedRunIds", SCRIPT)
        self.assertIn("aggregateNewsStages", SCRIPT)
        self.assertIn("openActualNewsLineageDetail", SCRIPT)
        self.assertIn("当天实际处理轨迹", SCRIPT)
        self.assertIn("当天真实新增新闻", SCRIPT)
        self.assertIn("AI 纳入理由", SCRIPT)
        self.assertIn("aiReviewItems", SCRIPT)
        self.assertIn("dedupeItems", SCRIPT)
        self.assertIn("当天处理对象明细", SCRIPT)
        self.assertIn("AI 排除原因", SCRIPT)
        self.assertIn("排除代码", SCRIPT)
        self.assertIn("detailedRecordsForNode", SCRIPT)
        self.assertIn('params.get("newsDate")', SCRIPT)
        self.assertNotIn('name="news-archive-filter"', SCRIPT)
        for stage in ("线索发现", "确定性门禁", "AI 语义审核", "历史语义去重", "飞书写入回读", "群组推送"):
            self.assertIn(stage, SCRIPT)
        self.assertNotIn("最新战略快讯", SCRIPT)
        self.assertIn("@keyframes news-signal", STYLE)
        self.assertIn("prefers-reduced-motion", STYLE)

    def test_news_module_exposes_clickable_live_lineage_with_detailed_dialog(self):
        for label in (
            "06:00 / 13:30 战略新闻",
            "线索补缺",
            "AI审核",
            "历史去重",
            "新增新闻",
            "纳入 APP",
            "纳入周报",
        ):
            self.assertIn(label, SCRIPT)
        self.assertIn("data-news-lineage-node", SCRIPT)
        self.assertIn("点击查看整理详情", SCRIPT)
        self.assertIn("syncNewsLineageEdges", SCRIPT)
        self.assertNotIn("setPointerCapture", SCRIPT)
        self.assertNotIn("localStorage.setItem(storageKey", SCRIPT)
        self.assertIn("当天结果摘要", SCRIPT)
        self.assertIn("上下游", SCRIPT)
        self.assertIn("当天归档摘要", SCRIPT)
        self.assertIn("当天具体内容", SCRIPT)
        self.assertIn("错误定位与完整明细", SCRIPT)
        self.assertIn("newsRunErrors", SCRIPT)
        self.assertIn("查看完整错误原文", SCRIPT)
        self.assertIn("本节点无直接错误；异常来自关联运行的其他环节", SCRIPT)
        self.assertIn(".news-lineage-error-list", STYLE)
        self.assertIn("news-lineage-pulse", STYLE)
        self.assertIn("@keyframes news-lineage-flow", STYLE)
        self.assertIn(".news-lineage-dialog-summary", STYLE)
        self.assertIn(".news-stage-dialog.news-lineage-dialog", STYLE)
        self.assertIn("height: 100dvh", STYLE)
        self.assertIn(".news-lineage-detail-items::-webkit-scrollbar", STYLE)
        self.assertIn("overflow-y: scroll", STYLE)
        self.assertIn("is-item-details", SCRIPT)
        self.assertIn("grid-auto-rows: max-content", STYLE)
        self.assertIn("actualEventsForNode", SCRIPT)
        self.assertIn("当天原始处理记录", SCRIPT)
        self.assertIn("lineageRunsForNode", SCRIPT)
        self.assertIn('fetch("/api/crawl-runs?limit=500"', SCRIPT)
        self.assertIn("当天未留下该节点的逐步处理记录", SCRIPT)
        self.assertNotIn("完整处理流程", SCRIPT)
        self.assertNotIn("规则／门禁", SCRIPT)
        self.assertNotIn("lineageProcessStep", SCRIPT)
        self.assertNotIn("processSteps = processByNode", SCRIPT)
        self.assertIn(".news-lineage-process-steps", STYLE)
        self.assertIn('fetch("/api/news-review-sheet"', SCRIPT)
        self.assertIn('valueAt(row, "检索日期")', SCRIPT)
        self.assertIn('row.rollingStatus === "接受"', SCRIPT)
        self.assertIn('row.weeklyStatus === "接受"', SCRIPT)
        self.assertIn("当天选用明细", SCRIPT)
        self.assertIn(".news-lineage.is-global .news-lineage-node.is-result", STYLE)

    def test_news_module_maps_all_periodic_crawlers_into_four_database_updates(self):
        self.assertIn('fetch("/api/scheduler-overview"', SCRIPT)
        self.assertIn('fetch("/api/executive-intelligence"', SCRIPT)
        for label in (
            "06:00 / 13:30 战略新闻",
            "线索补缺",
            "AI审核",
            "历史去重",
            "新增新闻",
            "03:00 主爬虫",
            "Agent 证据审核",
            "本地运营商",
            "内地电讯企业",
            "全球云厂商",
            "香港电讯市场",
            "17项AI洞察",
            "情报进入业务入口",
        ):
            self.assertIn(label, SCRIPT)
        self.assertIn('fetch("/api/crawl-runs?limit=500"', SCRIPT)
        self.assertIn("const dateRuns = state.crawlRuns.filter", SCRIPT)
        self.assertIn("actualEventsForNode", SCRIPT)
        self.assertIn("AGENT_TRACE=", SCRIPT)
        self.assertIn("当天实际处理轨迹", SCRIPT)
        self.assertIn("不展示通用逻辑原则", SCRIPT)
        self.assertNotIn("data-news-lineage-mode", SCRIPT)
        self.assertNotIn("本轮线索", SCRIPT)
        self.assertIn("canvasSize: [1580, 620]", SCRIPT)
        self.assertIn('label: "四库分流"', SCRIPT)
        self.assertIn('["agent", "database-hub", "", "cyan"]', SCRIPT)
        self.assertNotIn('["agent", "database-hub", "四库分流", "cyan"]', SCRIPT)
        self.assertIn('label: "四库更新"', SCRIPT)
        self.assertNotIn('四库更新 · 2 × 2', SCRIPT)
        self.assertIn('group.note ? `<span>${esc(group.note)}</span>` : ""', SCRIPT)
        self.assertIn('kind === "branch"', SCRIPT)
        self.assertIn('kind === "merge"', SCRIPT)
        self.assertIn('const railX = target.x - 8', SCRIPT)
        self.assertIn('const railX = source.x + source.w + 8', SCRIPT)
        self.assertIn('const bend = Math.min(Math.max(20, gap * .44), gap / 2)', SCRIPT)
        self.assertIn('requestAnimationFrame(() => requestAnimationFrame(syncNewsLineageEdges))', SCRIPT)
        self.assertIn('new ResizeObserver(scheduleNewsLineageEdgeSync)', SCRIPT)
        self.assertIn('data-news-lineage-label', SCRIPT)
        self.assertIn('getPointAtLength(length / 2)', SCRIPT)
        self.assertNotIn("<textPath", SCRIPT)
        self.assertIn(".news-lineage-edge-label", STYLE)
        self.assertIn(".news-lineage.is-global .news-lineage-node.is-compact", STYLE)
        self.assertIn("animation-name: news-lineage-flow-global", STYLE)
        self.assertIn("to { stroke-dashoffset: -104; }", STYLE)
        for variant in ("is-ai", "is-app", "is-report", "is-database-local", "is-database-international", "is-database-cloud", "is-database-macro", "is-insight", "is-delivery"):
            self.assertIn(f".news-lineage.is-global .news-lineage-node.{variant}", STYLE)
        self.assertIn('feedbackLabel: "历史记录用于下一轮去重"', SCRIPT)
        self.assertNotIn("历史记忆影响下一轮", SCRIPT)
        self.assertNotIn('data-news-lineage-action="zoom-out"', SCRIPT)
        self.assertNotIn('data-news-lineage-action="zoom-in"', SCRIPT)
        for key in ("strategic", "news-search", "news-ai", "news-dedupe", "news-output", "main", "agent", "insights", "consumers"):
            self.assertIn(f'key: "{key}"', SCRIPT)
        for domain in ("local", "international", "cloud", "macro"):
            self.assertIn(f'domainNode("{domain}"', SCRIPT)

    def test_news_lineage_uses_semantic_health_colours_instead_of_node_type_colours(self):
        self.assertIn('const runHealth = (run) =>', SCRIPT)
        self.assertIn('const combinedRunHealth = (items) =>', SCRIPT)
        self.assertIn('data-health="${esc(node.health?.key || "unknown")}"', SCRIPT)
        self.assertIn('健康状态${esc(node.health?.label || "无记录")}', SCRIPT)
        for label in ("正常", "运行中", "警告", "异常", "无记录"):
            self.assertIn(label, SCRIPT)
        for health in ("healthy", "running", "warning", "critical", "unknown"):
            self.assertIn(f".news-lineage.is-global .news-lineage-node.is-health-{health}", STYLE)
        self.assertNotIn('node.tone', SCRIPT)


if __name__ == "__main__":
    unittest.main()

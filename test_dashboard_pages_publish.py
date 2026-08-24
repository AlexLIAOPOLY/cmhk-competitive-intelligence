from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = (
    Path(__file__).resolve().parent
    / "scripts"
    / "publish_executive_dashboard_pages.py"
)
INTELLIGENCE_BUILDER_PATH = (
    Path(__file__).resolve().parent
    / "scripts"
    / "build_intelligence_static_snapshot.js"
)
SPEC = importlib.util.spec_from_file_location("dashboard_pages_publish", SCRIPT_PATH)
assert SPEC and SPEC.loader
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


class DashboardPagesPublishTests(unittest.TestCase):
    def test_public_asset_manifest_covers_every_local_homepage_dependency(self):
        html = (publisher.STATIC_DIR / "index.html").read_text(encoding="utf-8")
        regex = __import__("re")
        referenced = set(
            regex.findall(r'<script[^>]+src="/static/([^"?]+)', html)
            + regex.findall(
                r'<link[^>]+rel="stylesheet"[^>]+href="/static/([^"?]+)',
                html,
            )
        )
        self.assertTrue(referenced)
        self.assertEqual(referenced - set(publisher.PUBLIC_STATIC_FILES), set())

        source = SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn('["/api/auth/me", {', source)
        self.assertIn('name: "公开快照"', source)

    def test_public_report_preview_is_copied_from_non_empty_local_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            static = root / "static"
            preview_dir = static / "report-previews"
            preview_dir.mkdir(parents=True)
            report_name = "8月13日运营商业绩摘要.docx"
            report_base = report_name.removesuffix(".docx")
            key = __import__("base64").urlsafe_b64encode(report_base.encode()).decode().rstrip("=")
            (preview_dir / f"{key}.pdf").write_bytes(b"%PDF-1.7\npreview")
            destination = root / "published-static"
            destination.mkdir()

            with mock.patch.object(publisher, "STATIC_DIR", static):
                copied = publisher._copy_public_report_preview(report_name, destination)

            self.assertEqual(copied.read_bytes(), b"%PDF-1.7\npreview")
            self.assertGreater(copied.stat().st_size, 0)

            self.assertIsNone(
                publisher._copy_public_report_preview("不存在的周报.docx", destination)
            )

    def test_snapshot_publisher_authenticates_loopback_session_without_exposing_credentials(self):
        with tempfile.TemporaryDirectory() as temp:
            cookie_jar = Path(temp) / "cookies.txt"
            responses = [
                mock.Mock(
                    stdout=json.dumps(
                        {
                            "ok": True,
                            "requireLogin": True,
                            "devAccounts": [
                                {
                                    "account": "local-admin",
                                    "role": "ADMIN",
                                    "status": "active",
                                }
                            ],
                        }
                    )
                ),
                mock.Mock(stdout=json.dumps({"ok": True})),
            ]

            def fake_run(command, **kwargs):
                if "--cookie-jar" in command:
                    cookie_jar.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
                return responses.pop(0)

            with mock.patch.object(publisher, "_run", side_effect=fake_run) as run:
                publisher._open_local_snapshot_session(
                    "http://127.0.0.1:8765/",
                    cookie_jar,
                )

        self.assertEqual(run.call_args_list[0].args[0][-1], "http://127.0.0.1:8765/api/auth/config")
        login = run.call_args_list[1].args[0]
        self.assertIn("--cookie-jar", login)
        self.assertIn(json.dumps({"account": "local-admin"}, ensure_ascii=False), login)
        self.assertNotIn("password", " ".join(login).lower())

    def test_authenticated_fetch_uses_cookie_and_health_endpoint(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn('live_status = fetch("/api/health")', source)
        self.assertNotIn('live_status = _fetch_local_json(source_url, "/api/status")', source)
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(
            publisher,
            "_run",
            return_value=mock.Mock(stdout=json.dumps({"ok": True})),
        ) as run:
            cookie_jar = Path(temp) / "cookies.txt"
            publisher._fetch_local_json(
                "http://127.0.0.1:8765/",
                "/api/status",
                cookie_jar=cookie_jar,
            )

        command = run.call_args.args[0]
        self.assertEqual(command[-1], "http://127.0.0.1:8765/api/status")
        self.assertEqual(command[command.index("--cookie") + 1], str(cookie_jar))

    def test_static_javascript_paths_include_template_literals(self):
        source = 'const pdf = `/static/report-previews/${key}.pdf`;'
        self.assertEqual(
            publisher._rewrite_root_javascript(source),
            'const pdf = `./static/report-previews/${key}.pdf`;',
        )

    def test_public_subscription_snapshot_never_exports_recipient_records(self):
        payload = publisher._public_subscriptions(
            {
                "subscribers": [{"display_name": "Private Person", "open_id": "ou_private"}],
                "deliveries": [{"recipient_name": "Private Person"}],
                "schedule": {"enabled": True},
            }
        )

        self.assertEqual(
            payload,
            {
                "ok": True,
                "readOnly": True,
                "subscribers": [],
                "candidates": [],
                "deliveries": [],
                "invitations": [],
            },
        )

    def test_monitoring_dashboard_uses_synced_local_operator_tabs(self):
        html = (publisher.STATIC_DIR / "executive-dashboard-demo.html").read_text(
            encoding="utf-8"
        )
        script = (publisher.STATIC_DIR / "executive-dashboard-demo.js").read_text(
            encoding="utf-8"
        )

        self.assertIn('aria-label="HKT战略监控四层体系"', html)
        self.assertRegex(html, r'src="/static/executive-dashboard-demo\.js\?v=\d+"')
        self.assertIn("HKT经营全景", html)
        self.assertIn("本地运营商对比", html)
        self.assertIn("financeCompanyFallbacks", script)
        self.assertIn('fetch("/api/executive-intelligence"', script)
        self.assertIn("operatorProfiles", script)
        self.assertIn("renderOperatorTabs", script)
        self.assertIn("data-operator-index", script)
        self.assertIn("renderOperatorPanels", script)
        self.assertIn("is-operator-switching", script)
        self.assertIn("is-view-leaving", script)
        self.assertIn("transitionRevision", script)
        self.assertNotIn("data-finance-company", script)
        self.assertNotIn('<small>${escapeHtml(item.period)}</small>', script)
        self.assertNotIn("来源：HKT官方公开数据", script)
        for source in (
            "2026072900430.pdf",
            "e-2025_Annual_Report.pdf",
            "e-2025_ESG_Report.pdf",
        ):
            self.assertIn(source, script)
        for metric in (
            "基站总数（4G）",
            "基站总数（5G）",
            "智算能力 PFLOPS",
            "总移动用户数",
            "移动综合ARPU",
            "家庭宽带用户数",
            "家庭户均收益（ARPU）",
            "客户数（大中型企业/中小企业-参考政府公布的分类）",
            "项目签约额",
            "全港实体门市数量",
            "官方手机应用程式 (如MyLink) 活跃用户数",
            "营运收入",
            "EBITDA率",
            "净利润",
        ):
            self.assertIn(metric, script)
        for removed_metric in (
            "chinamobileltd.com",
            "CHINA MOBILE NETWORK",
            "CMCC",
            "互联网骨干带宽",
            "5G网络香港覆盖率",
            "Wi-Fi热点",
            "移动后付客户",
            "住宅宽带客户",
            "The Club会员",
            "Now TV已安装用户",
            "资本开支",
            "[263.7, 283.0, 244.8, 249.3, 263.8, 280.0, 250.9]",
        ):
            self.assertNotIn(removed_metric, script)
        self.assertNotIn("来源：HKT官方公开数据", script)
        self.assertIn("[17.322, 19.231, 18.685]", script)
        for company in ("3香港", "SmarTone", "HKBN", "i-CABLE"):
            self.assertIn(company, script)
        self.assertIn('company: "CMHK"', script)
        self.assertIn('value: "5.0", unit: "百万户"', script)
        self.assertIn('value: "49", unit: "间"', script)
        self.assertIn("六家本地运营商", script)
        for comparable_value in ("8.132", "2.75", "0.916", "186", "0.198", "26.8", "20.8"):
            self.assertIn(comparable_value, script)
        self.assertIn("未披露同口径数据时显示", script)
        self.assertNotIn("打开官方来源", script)

    def test_intelligence_snapshot_removes_runtime_source_metadata(self):
        source = INTELLIGENCE_BUILDER_PATH.read_text(encoding="utf-8")
        self.assertIn("delete value.intelligence_source_url", source)
        self.assertIn("scrubRuntimeAddresses(intelligencePayload)", source)
        self.assertIn('item.removeAttribute("data-intelligence-insight-refresh")', source)
        self.assertIn('item.setAttribute("disabled", "")', source)
        self.assertIn("new MutationObserver(disableRefreshControls)", source)
        self.assertIn(".static-snapshot .intelligence-relation-title", source)

    def test_public_verification_uses_system_https_without_proxy(self):
        expected_version = "site-v2"
        with mock.patch.object(
            publisher,
            "_run",
            return_value=mock.Mock(
                stdout=json.dumps({"site_version": expected_version})
            ),
        ) as run:
            publisher._verify("https://example.github.io/project/", expected_version)

        command = run.call_args.args[0]
        self.assertEqual(command[0], "curl")
        self.assertIn("--fail", command)
        self.assertEqual(
            command[-1],
            "https://example.github.io/project/strategic-briefs.json",
        )

    def test_public_run_snapshots_keep_ui_evidence_without_internal_paths(self):
        run = publisher._public_crawl_run(
            {
                "crawl_run_id": "run-1",
                "task_kind": "strategic-news",
                "run_status": "completed",
                "progress_detail": "审核完成",
                "local_files": ["/Users/example/private.log"],
                "stream_log": "/Users/example/stream.log",
                "backend_pid": 123,
                "operational_summary": {"pages_publish": {"ok": True}},
            }
        )
        self.assertEqual(run["crawl_run_id"], "run-1")
        self.assertEqual(run["progress_detail"], "审核完成")
        self.assertNotIn("local_files", run)
        self.assertNotIn("stream_log", run)
        self.assertNotIn("backend_pid", run)

        detail = publisher._public_crawl_run_detail(
            {
                "ok": True,
                "run": {"crawl_run_id": "run-1", "local_files": ["private"]},
                "raw": "private raw log",
                "content": "private content",
                "newsItems": [{"title": "公开新闻", "source_url": "https://example.com/news"}],
            }
        )
        self.assertNotIn("raw", detail)
        self.assertNotIn("content", detail)
        self.assertEqual(detail["newsItems"][0]["title"], "公开新闻")

        output = publisher._public_report_output(
            {
                "name": "8月19日周报.docx",
                "path_str": "/Users/example/private.docx",
                "url": "/api/report-file?path=private",
                "reportType": "weekly",
                "size": 1024,
            }
        )
        self.assertEqual(output["name"], "8月19日周报.docx")
        self.assertEqual(output["url"], "")
        self.assertEqual(output["path_str"], "8月19日周报.docx")
        self.assertNotIn("/Users/", output["path_str"])

    def test_public_review_snapshot_is_read_only_and_drops_sheet_identity(self):
        snapshot = publisher._public_news_review_sheet(
            {
                "sheetId": "secret-sheet",
                "sheetUrl": "https://cmhk-try.feishu.cn/sheets/secret",
                "sheetTitle": "滚动新闻候选池",
                "headers": ["新闻标题（AI）", "原文链接"],
                "editableColumns": [0, 1],
                "rows": [{"rowNumber": 1, "values": ["标题", "https://example.com"]}],
            }
        )
        self.assertTrue(snapshot["readOnly"])
        self.assertEqual(snapshot["editableColumns"], [])
        self.assertNotIn("sheetId", snapshot)
        self.assertNotIn("sheetUrl", snapshot)
        self.assertEqual(len(snapshot["rows"]), 1)

    def test_public_organization_snapshot_keeps_read_only_ui_fields_only(self):
        users, audit = publisher._public_organization_snapshots(
            {
                "users": [{
                    "id": "private-user-id",
                    "name": "Alex",
                    "account": "private-account",
                    "email": "private@example.com",
                    "department": "Technology",
                    "title": "Manager",
                    "role": "ADMIN",
                    "roleLabel": "系统管理员",
                    "status": "active",
                    "avatarUrl": "/api/auth/avatar/private-open-id",
                    "modules": {"organization": True},
                }],
                "roles": {"ADMIN": "系统管理员"},
                "modules": {"organization": "团队管理"},
                "roleModules": {"ADMIN": {"organization": True}},
            },
            {"events": [{
                "id": "private-event-id",
                "actor_id": "private-user-id",
                "actor_open_id": "private-open-id",
                "actor_name": "Alex",
                "actor_avatar_url": "/api/auth/avatar/private-open-id",
                "action": "organization.user_import",
                "target": "member-target",
                "result": "success",
                "at": "2026-08-24T09:00:00+08:00",
                "details": {"name": "Alex", "email": "private@example.com", "token": "secret"},
            }]},
            {"incidents": []},
        )

        self.assertTrue(users["readOnly"])
        self.assertEqual(users["users"][0]["id"], "member-001")
        self.assertEqual(users["users"][0]["name"], "Alex")
        self.assertEqual(users["users"][0]["email"], "")
        self.assertEqual(users["users"][0]["account"], "")
        self.assertNotIn("avatarUrl", users["users"][0])
        self.assertEqual(audit["events"][0]["actor_id"], "member-001")
        self.assertEqual(audit["events"][0]["target_type"], "member")
        self.assertEqual(audit["events"][0]["target_label"], "Alex")
        self.assertEqual(audit["events"][0]["target_member_id"], "member-001")
        self.assertEqual(audit["events"][0]["details"], {})
        self.assertNotIn("actor_open_id", audit["events"][0])

        source = SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn('organization: true', source)
        self.assertIn('"static-data/organization-users.json"', source)
        self.assertIn("#organizationAdmin [data-delete-user]", source)

    def test_optional_public_snapshot_does_not_block_on_busy_live_preview(self):
        fetch = mock.Mock(side_effect=RuntimeError("preview is busy"))
        self.assertEqual(
            publisher._fetch_optional_public_snapshot(fetch, "/api/news-review-sheet"),
            {},
        )
        fetch.assert_called_once_with("/api/news-review-sheet")

        source = SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn('_fetch_optional_public_snapshot(fetch, "/api/weekly-report-preview")', source)

    def test_fresh_intelligence_snapshot_is_built_from_local_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "intelligence"

            def fake_run(command, **kwargs):
                self.assertEqual(command, ["node", str(publisher.INTELLIGENCE_SNAPSHOT_SCRIPT)])
                self.assertEqual(kwargs["cwd"], publisher.ROOT)
                environment = kwargs["environment_overrides"]
                self.assertEqual(
                    environment["CMHK_INTELLIGENCE_SOURCE_URL"],
                    "http://127.0.0.1:9876/",
                )
                self.assertEqual(
                    environment["CMHK_INTELLIGENCE_SNAPSHOT_DIR"],
                    str(destination),
                )
                destination.mkdir(parents=True)
                (destination / "index.html").write_text("<title>fresh</title>", encoding="utf-8")
                (destination / "intelligence.js").write_text("window.DATA = {};", encoding="utf-8")
                return mock.Mock(stdout='{"status":"built"}\n')

            with mock.patch.dict(
                publisher.os.environ,
                {"CMHK_INTELLIGENCE_SOURCE_URL": "http://127.0.0.1:9876/"},
            ), mock.patch.object(publisher, "_run", side_effect=fake_run):
                result = publisher._build_fresh_intelligence_snapshot(destination)

            self.assertEqual(result["source_url"], "http://127.0.0.1:9876/")
            self.assertTrue((destination / "index.html").is_file())
            self.assertTrue((destination / "intelligence.js").is_file())

    @unittest.skip("legacy two-page publisher contract replaced by unified homepage")
    def test_build_site_is_static_sanitized_and_stable(self):
        payload = {
            "ok": True,
            "generated_at": "2026-07-29T10:00:00+08:00",
            "items": [
                {
                    "id": "NEWS-1",
                    "title": "公开新闻",
                    "summary": "公开摘要",
                    "category": "行业动态",
                    "source_url": "https://example.com/news",
                    "published_at": "2026-07-29",
                }
            ],
        }
        later_payload = {
            **payload,
            "generated_at": "2026-07-29T10:05:00+08:00",
        }
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(
            publisher,
            "_public_news_payload",
            side_effect=[payload, later_payload],
        ):
            first = Path(temp) / "first"
            second = Path(temp) / "second"
            first_version, first_payload = publisher._build_site(first)
            second_version, second_payload = publisher._build_site(second)

            self.assertEqual(first_version, second_version)
            self.assertEqual(
                first_payload["site_version"],
                second_payload["site_version"],
            )
            html = (first / "index.html").read_text(encoding="utf-8")
            script = (first / "executive-dashboard-demo.js").read_text(
                encoding="utf-8"
            )
            style = (first / "executive-dashboard-demo.css").read_text(
                encoding="utf-8"
            )
            self.assertRegex(html, r'href="\./executive-dashboard-demo\.css\?v=\d+"')
            self.assertIn("strategy-command-grid-v2.webp", html)
            self.assertIn(
                'href="./executive-responsive-hardening.css?v=',
                html,
            )
            self.assertIn('src="./assets/executive-dashboard/', html)
            self.assertRegex(html, r'src="\./executive-dashboard-demo\.js\?v=\d+"')
            self.assertIn("--surface: #091725", style)
            self.assertIn('--font-tech: "DIN Alternate"', style)
            self.assertIn('font-feature-settings: "tnum" 1, "lnum" 1', style)
            self.assertIn('font: 680 clamp(12px, .7vw, 24px)/1', style)
            self.assertIn('font-size: clamp(14px, .82vw, 30px)', style)
            self.assertIn('background: rgba(5, 18, 30, .5)', style)
            self.assertIn("metric-sparkline", script)
            self.assertIn("network-architecture", script)
            self.assertIn("移动网络基础设施", script)
            self.assertIn("数据与云基础设施", script)
            self.assertIn("本地运营商", script)
            self.assertNotIn("topology-orbit", script)
            for network_background in (
                "network-4g-bg-v1.jpg",
                "network-5g-bg-v1.jpg",
                "network-backbone-bg-v1.jpg",
                "network-core-bg-v1.jpg",
            ):
                self.assertIn(network_background, style)
                self.assertTrue(
                    (first / "assets" / "executive-dashboard" / network_background).is_file()
                )
            for cockpit_background in (
                "cockpit-background-v1.jpg",
                "panel-network-bg-v1.jpg",
                "panel-business-bg-v1.jpg",
                "panel-reach-bg-v1.jpg",
                "panel-finance-bg-v1.jpg",
            ):
                self.assertIn(cockpit_background, style)
                self.assertTrue(
                    (first / "assets" / "executive-dashboard" / cockpit_background).is_file()
                )
            self.assertTrue((first / "assets" / "china-mobile-blue-logo.png").is_file())
            self.assertIn('class="brand" href="./" aria-label="返回主页"', html)
            self.assertIn(
                'src="./assets/china-mobile-blue-logo.png" alt="中国移动 China Mobile"',
                html,
            )
            self.assertIn(".brand:focus-visible", style)
            self.assertIn("战略监控体系", html)
            self.assertIn("STRATEGIC MONITORING SYSTEM", html)
            self.assertIn("资源与基础设施层", html)
            self.assertIn("客户与业务对标层", html)
            self.assertIn("渠道与品牌触达层", html)
            self.assertNotIn("数据为模拟展示，仅用于界面演示", html)
            self.assertNotIn("executive-dashboard-relations.js", html)
            self.assertNotIn("executive-dashboard-drilldown.js", html)
            self.assertNotIn('class="news-rail"', html)
            self.assertNotIn('class="panel-tabs', html)
            self.assertNotIn('role="tablist"', html)
            self.assertNotIn('role="tab"', html)
            self.assertNotIn("data-benchmark-url", html)
            self.assertNotIn("benchmark-company-selector", html)
            self.assertIn("HKT", html)
            self.assertIn("HKT", script)
            for company in ("HKT", "3香港", "SmarTone", "HKBN", "CMHK"):
                self.assertIn(company, script)
            selected_metrics = (
                "基站总数（4G）",
                "基站总数（5G）",
                "智算能力 PFLOPS",
                "总移动用户数",
                "移动综合ARPU",
                "家庭宽带用户数",
                "家庭户均收益（ARPU）",
                "客户数（大中型企业/中小企业-参考政府公布的分类）",
                "项目签约额",
                "全港实体门市数量",
                "官方手机应用程式 (如MyLink) 活跃用户数",
                "营运收入",
                "EBITDA率",
                "净利润",
            )
            for metric in selected_metrics:
                self.assertIn(metric, script)
            for removed_metric in (
                "5G网络平均下载速率",
                "网络可用率",
                "品牌认知度",
                "客户满意度",
                "资本开支",
                "5G网络香港覆盖率",
                "Wi-Fi热点",
                "移动后付客户",
                "The Club会员",
                "Now TV已安装用户",
            ):
                self.assertNotIn(removed_metric, script)
            self.assertNotIn("setupTabs", script)
            self.assertNotIn("extendNewsRail", script)
            self.assertIn("IntersectionObserver", script)
            self.assertIn("2026年6月", script)
            self.assertIn("data-tooltip", script)
            self.assertNotIn("data-source", script)
            self.assertNotIn("来源：HKT官方公开数据", script)
            self.assertIn("[17.322, 19.231, 18.685]", script)
            self.assertNotIn("chinamobileltd.com", script)
            self.assertNotIn("342.8", script)
            self.assertNotIn("6,880", script)
            self.assertIn('classList.add("motion-enabled")', script)
            self.assertNotIn("/api/strategic-briefs", script)
            self.assertNotIn("company-benchmarks", script)
            self.assertFalse((first / "executive-dashboard-relations.js").exists())
            self.assertFalse((first / "executive-dashboard-drilldown.js").exists())
            css = (first / "executive-dashboard-demo.css").read_text(
                encoding="utf-8"
            )
            self.assertIn("Sheet-filtered CMHK view", css)
            self.assertIn(".business-pair", css)
            self.assertIn(".scene, .panel-glass { display: none; }", css)
            self.assertFalse((first / "executive-company-benchmarks.json").exists())
            self.assertTrue((first / "executive-responsive-hardening.css").exists())
            intelligence_html = (first / "intelligence" / "index.html").read_text(
                encoding="utf-8"
            )
            self.assertIn(
                'href="./responsive-layout-hardening.css?v=6"',
                intelligence_html,
            )
            self.assertTrue(
                (first / "intelligence" / "responsive-layout-hardening.css").exists()
            )
            hardening_css = (
                first / "intelligence" / "responsive-layout-hardening.css"
            ).read_text(encoding="utf-8")
            self.assertIn("(max-height: 1000px)", hardening_css)
            self.assertIn(
                "height: calc((100vh - 8px) / var(--fit-scale) - 164px)",
                hardening_css,
            )
            self.assertTrue((first / ".nojekyll").exists())

    @unittest.skip("standalone intelligence page is no longer published")
    def test_build_site_preserves_static_intelligence_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            snapshot = Path(temp) / "snapshot"
            snapshot.mkdir()
            (snapshot / "index.html").write_text(
                "<title>四库竞争情报驾驶舱</title>",
                encoding="utf-8",
            )
            payload = {"ok": True, "generated_at": "", "items": []}
            with mock.patch.object(publisher, "INTELLIGENCE_STATIC_DIR", snapshot), mock.patch.object(
                publisher,
                "_public_news_payload",
                return_value=payload,
            ):
                destination = Path(temp) / "site"
                publisher._build_site(destination)

            self.assertEqual(
                (destination / "intelligence" / "index.html").read_text(encoding="utf-8"),
                "<title>四库竞争情报驾驶舱</title>",
            )

    def test_static_intelligence_snapshot_keeps_frontend_interactions_without_api(self):
        static_dir = Path(__file__).resolve().parent / "web" / "static" / "intelligence-public"
        html = (static_dir / "index.html").read_text(encoding="utf-8")
        script = (static_dir / "intelligence.js").read_text(encoding="utf-8")
        builder = (Path(__file__).resolve().parent / "scripts" / "build_intelligence_static_snapshot.js").read_text(encoding="utf-8")

        self.assertRegex(html, r'<script src="\./intelligence\.js\?v=[0-9a-f]{12}"></script>')
        self.assertIn(".update(leadershipCss)", builder)
        self.assertIn(".update(boardScript)", builder)
        self.assertIn("CMHK市场竞争全景", html)
        self.assertIn("战略解读", html)
        self.assertIn("运营商动态", html)
        self.assertNotIn(">竞对动态<", html)
        self.assertIn('class="ai-insight-mark"', html)
        self.assertIn('id="intelligenceDrawerBackdrop"', html)
        self.assertIn('data-intelligence-focus', script)
        self.assertIn('function selectFocus', script)
        self.assertIn('function selectEntity', script)
        self.assertIn('function openDrawer', script)
        self.assertIn('strategy-ticker-track', script)
        self.assertNotIn("/api/", script)
        self.assertNotIn("方案规模", script)
        self.assertNotIn("竞对重叠", script)
        self.assertNotIn("增长动量", script)
        self.assertNotIn("投入强度", script)
        self.assertNotRegex(script, r"127\.0\.0\.1|localhost|10\.0\.|192\.168\.")

    def test_build_site_publishes_unified_read_only_homepage(self):
        snapshots = {
            "status.json": {"ok": True, "status": {"outputs": []}},
            "company-metrics.json": {"ok": True, "data": {}},
            "executive-intelligence.json": {
                "ok": True,
                "domains": [{"id": "local-operators", "title": "本地运营商"}],
                "relations": [],
            },
            "project-incidents.json": {"ok": True, "incidents": [], "total": 0},
            "crawl-runs.json": {"ok": True, "runs": [], "total": 0},
            "task-runs.json": {"ok": True, "tasks": []},
            "strategic-briefs.json": {
                "ok": True,
                "items": [{"id": "NEWS-1", "title": "公开新闻"}],
                "monitor": {"status": "snapshot", "scan_times": ["09:00", "14:00"]},
            },
        }
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(
            publisher,
            "_build_public_runtime_snapshots",
            return_value=snapshots,
        ), mock.patch.object(
            publisher,
            "_local_source_url",
            return_value="http://127.0.0.1:8765/",
        ):
            destination = Path(temp) / "site"
            version, payload = publisher._build_site(destination)

            html = (destination / "index.html").read_text(encoding="utf-8")
            bootstrap = (destination / "static" / "public-snapshot-bootstrap.js").read_text(
                encoding="utf-8"
            )
            self.assertIn("CMHK市场竞争全景", html)
            self.assertIn("CMHK战略竞对中心", html)
            self.assertIn('data-workspace-tab="dashboard"', html)
            self.assertIn('data-workspace-tab="monitoring"', html)
            self.assertIn('src="./executive-dashboard-demo.html?embedded=1', html)
            self.assertIn('src="./static/public-snapshot-bootstrap.js?v=5"', html)
            self.assertIn('src="./static/workspace-tabs.js?v=public-5"', html)
            self.assertIn('data-workspace-tab="subscriptions"', html)
            self.assertIn('data-workspace-tab="ai"', html)
            self.assertIn('data-src="./static/public-subscriptions.html"', html)
            self.assertIn("CMHK_PUBLIC_SNAPSHOT", bootstrap)
            self.assertIn("公开网页是只读快照", bootstrap)
            self.assertIn("subscriptions: true, ai: true", bootstrap)
            self.assertIn('document.addEventListener("DOMContentLoaded", startPrivateControlLock', bootstrap)
            self.assertNotIn("observe(document.documentElement", bootstrap.split("function startPrivateControlLock", 1)[0])
            self.assertIn('"/api/scheduler-overview"', bootstrap)
            self.assertIn('"/api/news-review-sheet"', bootstrap)
            self.assertIn('"/api/weekly-report-preview"', bootstrap)
            self.assertIn('"/api/crawl-run-log"', bootstrap)
            self.assertTrue((destination / "static" / "app.js").is_file())
            self.assertTrue((destination / "static" / "public-subscriptions.html").is_file())
            self.assertTrue((destination / "static" / "public-ai.html").is_file())
            self.assertFalse((destination / "static" / "subscription-admin.html").exists())
            public_workspace = (destination / "static" / "workspace-tabs.js").read_text(
                encoding="utf-8"
            )
            self.assertIn('src="./static/public-ai.html"', public_workspace)
            self.assertNotIn('id="workspaceAiHost"', public_workspace)
            self.assertIn("void requestId;", public_workspace)
            self.assertNotIn(
                "requestCompetitorInsight({ companies, metric:",
                public_workspace,
            )
            self.assertTrue((destination / "static" / "assets" / "china-mobile-blue-logo.png").is_file())
            self.assertTrue((destination / "static-data" / "executive-intelligence.json").is_file())
            self.assertTrue((destination / "executive-dashboard-demo.html").is_file())
            self.assertFalse((destination / "intelligence").exists())
            self.assertRegex(version, r"^[0-9a-f]{64}$")
            self.assertEqual(payload["site_version"], version)


if __name__ == "__main__":
    unittest.main()

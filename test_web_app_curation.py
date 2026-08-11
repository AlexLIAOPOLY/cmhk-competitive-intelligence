from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
import json
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

import agent
import rag_llm
import web_app


class ReportFileNameTests(unittest.TestCase):
    def test_report_audio_metadata_does_not_read_transcript_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "report.wav"
            audio.write_bytes(b"audio")
            with mock.patch.object(web_app, "audio_paths_for_report", return_value=[audio]):
                metadata = web_app.report_audio_metadata(Path(tmp) / "report.docx")

        self.assertTrue(metadata["exists"])
        self.assertRegex(metadata["url"], r"^/audio/report\.wav\?v=\d+$")
        self.assertNotIn("subtitleCues", metadata)

    def test_status_defers_heavy_audio_transcript_until_playback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / "8月9日周报.docx"
            report.write_bytes(b"docx")
            with (
                mock.patch.object(web_app, "ROOT", root),
                mock.patch.object(web_app, "REPORT_METADATA_PATH", root / "metadata.json"),
                mock.patch.object(
                    web_app,
                    "report_audio_metadata",
                    return_value={
                        "exists": True,
                        "url": "/audio/report.wav",
                    },
                ) as audio_metadata,
            ):
                payload = web_app.file_info(report)

        self.assertEqual(payload["audio"], {"exists": True, "url": "/audio/report.wav"})
        audio_metadata.assert_called_once_with(report)
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        self.assertIn("/api/report-audio?path=", app)
        self.assertNotIn("data-subtitle-cues=", app)

    def test_json_response_ignores_disconnected_client(self) -> None:
        class DisconnectedHandler:
            def send_response(self, _status: int) -> None:
                pass

            def send_header(self, _name: str, _value: str) -> None:
                pass

            def end_headers(self) -> None:
                pass

            class Writer:
                @staticmethod
                def write(_body: bytes) -> None:
                    raise BrokenPipeError("client stopped polling")

            wfile = Writer()

        web_app.json_response(DisconnectedHandler(), {"ok": True})

    def test_four_database_refresh_is_visible_in_unified_task_log(self) -> None:
        task = web_app._normalize_crawl_task({
            "crawl_run_id": "refresh-1",
            "task_kind": "executive-intelligence-refresh",
            "trigger": "四库与观察结论自动更新",
            "scope": "Agent审核 agent-1",
            "run_status": "running",
            "stream_log": {"lines": 4, "bytes": 200},
            "operational_summary": {
                "model_analysis": {
                    "model": "deepseek-v4",
                    "fallback_used": True,
                    "fallback_reason": "门禁失败",
                    "evidence_hash": "abc123",
                },
                "pages_publish": {
                    "ok": True,
                    "status": "verified",
                    "site_version": "site-123",
                    "public_url": "https://example.github.io/project/",
                },
            },
        })
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")

        self.assertEqual(task["kind_label"], "四库刷新")
        self.assertEqual(task["kind"], "executive-intelligence-refresh")
        self.assertEqual(task["analysis_model"], "deepseek-v4")
        self.assertEqual(task["analysis_fallback_reason"], "门禁失败")
        self.assertEqual(task["evidence_hash"], "abc123")
        self.assertTrue(task["pages_publish_ok"])
        self.assertIn("taskAnalysisStatusMarkup", app)
        self.assertIn("证据哈希", app)
        self.assertIn("delete els.logBox.dataset.renderSignature", app)
        self.assertIn("更新失败", app)
        self.assertIn("预警发送失败", app)

    def test_status_reports_any_running_unified_task(self) -> None:
        with mock.patch.object(
            web_app,
            "load_unified_task_index",
            return_value=[
                {"task_id": "task:finished", "run_status": "completed"},
                {"task_id": "crawl:active", "run_status": "running"},
            ],
        ):
            status = web_app.build_status()

        self.assertEqual(status["tasks"], {"runningCount": 1, "hasRunning": True})

    def test_frequency_scheduler_can_be_external_without_disabling_news_monitor(self) -> None:
        with (
            mock.patch.dict(
                os.environ,
                {
                    "CMHK_DISABLE_FREQUENCY_SCHEDULER": "1",
                    "CMHK_DISABLE_EMBEDDED_SCHEDULER": "0",
                    "CMHK_DISABLE_STRATEGIC_BRIEFING_MONITOR": "0",
                },
            ),
            mock.patch("threading.Thread") as thread,
        ):
            web_app.start_scheduler_with_backend()

        names = [call.kwargs.get("name") for call in thread.call_args_list]
        self.assertNotIn("feishu-frequency-scheduler", names)
        self.assertIn("strategic-briefing-monitor", names)

    def test_dashboard_uses_four_domain_intelligence_with_drillthrough(self) -> None:
        html = (web_app.ROOT / "web/static/index.html").read_text(encoding="utf-8")
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        styles = (web_app.ROOT / "web/static/styles.css").read_text(encoding="utf-8")
        leadership_styles = (web_app.ROOT / "web/static/leadership-board.css").read_text(encoding="utf-8")

        self.assertNotIn('id="intelligenceBoardTitle"', html)
        self.assertNotIn('class="intelligence-board-header"', html)
        self.assertIn('aria-label="四库竞争情报关系看板"', html)
        self.assertIn('id="intelligenceDomainGrid"', html)
        self.assertIn('id="intelligenceRelationRail"', html)
        self.assertIn('id="intelligenceDrawer"', html)
        header_tools = html[html.index('<div class="header-tools">'):html.index('<div class="header-runtime-status">')]
        self.assertIn('id="chatFab"', header_tools)
        self.assertIn('<button class="icon-button chat-fab" id="chatFab"', html)
        self.assertEqual(html.count('id="chatFab"'), 1)
        self.assertNotIn('id="collectionOverviewTitle"', html)
        self.assertNotIn('id="dailyAssetGrid"', html)
        self.assertNotIn('id="signalTrendCanvas"', html)
        self.assertIn('fetch("/api/executive-intelligence"', app)
        self.assertNotIn('data-intelligence-drill=', app)
        self.assertNotIn('>穿透分析 ', app)
        self.assertIn('data-intelligence-entity=', app)
        self.assertIn('data-intelligence-focus=', app)
        self.assertNotIn('function entityFocusNote(', app)
        self.assertIn('if (Array.isArray(domain?.focuses)', app)
        self.assertIn('const focusMetric = selectedFocus.metric || domain.metric || {};', app)
        self.assertIn('function selectFocus(domainId, index', app)
        self.assertIn('function rotateNextFocus()', app)
        self.assertIn('window.setInterval(rotateNextFocus, 4200)', app)
        self.assertIn('Date.now() + 30000', app)
        self.assertIn('function renderScrollingLabel(value)', app)
        self.assertIn('function measureScrollingLabels(scope = grid)', app)
        self.assertIn('data-intelligence-scroll-label', app)
        self.assertIn('function patchIntelligenceNode(current, next)', app)
        self.assertIn('const updated = patchIntelligenceNode(current, elementFromMarkup(renderDomainCard(domain)))', app)
        self.assertNotIn('grid.innerHTML = domains.map(renderDomainCard).join("")', app)
        self.assertIn('.intelligence-scroll-label.is-overflowing', styles)
        self.assertIn('.intelligence-scroll-label-track { display: none !important; }', styles)
        self.assertIn('href="/static/styles.css?v=254"', html)
        self.assertIn('Log and audit surfaces: complete dark-theme coverage v252', styles)
        self.assertIn('.dashboard-page #logModal .agent-audit-timeline,', styles)
        self.assertIn('.dashboard-page #logModal .agent-quality-records,', styles)
        self.assertIn('.dashboard-page #logModal .agent-audit-sample header {', styles)
        self.assertIn('src="/static/app.js?v=260"', html)
        self.assertIn('logo.alt = "小竞 AI"', app)
        self.assertIn('.dashboard-page .message.assistant .avatar {', styles)
        self.assertIn('filter: saturate(1.3) contrast(1.12) brightness(1.08);', styles)
        self.assertIn('if (els.outputArea.parentElement !== document.body)', app)
        self.assertIn('document.body.appendChild(els.outputArea);', app)
        self.assertIn('class="intelligence-focus-tabs"', app)
        self.assertIn('class="intelligence-entity-focus"', app)
        self.assertIn('entity.ai_summary?.analysis || entity.analysis', app)
        self.assertIn('class="intelligence-entity-components"', app)
        self.assertNotIn('data-intelligence-disclosure', app)
        self.assertIn('overflow-y: auto;', styles)
        self.assertIn('overscroll-behavior: contain;', styles)
        self.assertIn('href="/static/leadership-board.css?v=8"', html)
        self.assertIn('class="ai-insight-mark"', app)
        self.assertIn('AI 洞察', app)
        self.assertIn('class="intelligence-ai-refresh', app)
        self.assertIn('/api/executive-intelligence/regenerate-insight', app)
        self.assertIn('response.body.getReader()', app)
        self.assertIn('role="status" aria-live="polite"', app)
        self.assertIn('JSON.stringify({ domain: domainId, focus: focusId, stream: true })', app)
        self.assertIn('.intelligence-ai-refresh.is-loading', leadership_styles)
        self.assertIn('.intelligence-ai-stream-status', leadership_styles)
        self.assertIn('border: 0;', leadership_styles)
        self.assertIn('font-size: 15.5px; line-height: 1.58;', leadership_styles)
        self.assertIn('is-content-switching', app)
        self.assertIn('--domain-mask-mid: .62;', leadership_styles)
        self.assertIn('--domain-mask-bottom: .18;', leadership_styles)
        self.assertIn('>来源<span aria-hidden="true">↗</span></a>', app)
        self.assertIn('target="_self">来源<span aria-hidden="true">↗</span></a>', app)
        self.assertNotIn('${safe(selectedFocus.context || domain.context)}</em>', app)
        self.assertIn('Layered technology cockpit panels for the leadership board', leadership_styles)
        self.assertIn('border-radius: 0;', leadership_styles)
        self.assertIn('box-shadow: none;', leadership_styles)
        self.assertIn('.intelligence-domain-heading > span { display: none; }', leadership_styles)
        self.assertIn('.intelligence-domain::before,', leadership_styles)
        self.assertIn('.intelligence-viz-kpis > div::before { display: none; }', leadership_styles)
        self.assertIn('class="intelligence-summary-strip"', app)
        self.assertIn('class="intelligence-decision-list"', app)
        self.assertIn('AI 洞察', app)
        self.assertIn('const sourceLink = event.target.closest(', app)
        self.assertIn('window.location.assign(sourceLink.href)', app)
        self.assertIn('border: 0;\n  color: color-mix', leadership_styles)
        self.assertNotIn('<h3>AI 审核分析', app)
        self.assertNotIn('<h3>域内关系', app)
        self.assertIn('const items = focusItems(domain, selectedFocus);', app)
        self.assertIn('data-intelligence-peer=', app)
        self.assertIn('url.searchParams.set("intelligence", id)', app)
        self.assertIn('intelligence-viz-network', app)
        self.assertIn('intelligence-viz-diverging', app)
        self.assertIn('intelligence-viz-columns', app)
        self.assertIn('intelligence-viz-kpis', app)
        self.assertIn('intelligence-viz-ranges', app)
        self.assertIn('intelligence-viz-trends', app)
        self.assertIn('intelligence-viz-disclosure', app)
        self.assertIn('competitive-intelligence-radar-v3.webp', styles)
        self.assertEqual(leadership_styles.count('competitive-intelligence-radar-v3.webp'), 4)
        self.assertIn('Executive intelligence visual refinement v2', styles)
        self.assertIn('Xiaojing AI high-contrast dark workspace v2', styles)
        self.assertIn('--chat-canvas: #071a25;', styles)
        self.assertIn('Four-domain executive typography v6', styles)
        self.assertIn('Four-domain title signature v7', styles)
        self.assertIn('Focus-specific evidence visualizations v7', styles)
        self.assertIn('grid-template-columns: minmax(0, 1.22fr) minmax(180px, .78fr);', styles)
        self.assertIn('.log-glowing {', styles)
        self.assertIn('@keyframes intelligence-atmosphere', styles)
        self.assertIn('@media (prefers-reduced-motion: reduce)', styles)
        self.assertIn("上午及下午扫描尚未完成", app)
        self.assertIn("daily-scan-comparison", app)
        self.assertIn("daily-unified-funnel-svg", app)
        self.assertIn("daily-unified-funnel-stage", app)
        self.assertIn("当日扫描漏斗", app)
        self.assertIn("renderRoundComparison", app)
        self.assertNotIn("daily-asset-kpis", app)
        self.assertIn("当天内容分布", app)
        self.assertIn('"主题构成"', app)
        self.assertIn('"业务影响"', app)
        self.assertIn('mergeRoundDistribution("categories", 4, "其他主题")', app)
        self.assertIn('mergeRoundDistribution("impacts", 4, "其他影响")', app)
        self.assertIn('label: "上午"', app)
        self.assertIn('label: "下午"', app)

    def test_latest_news_funnel_uses_completed_strategic_scan_summary(self) -> None:
        with (
            mock.patch.object(
                web_app,
                "load_crawl_run_index",
                return_value=[
                    {
                        "task_kind": "strategic-news",
                        "run_status": "completed",
                        "scope": "午后扫描（2026-07-29@15:00）",
                        "completed_at_hkt": "2026-07-29T15:52:38+08:00",
                        "operational_summary": {
                            "slot": "2026-07-29@15:00-rerun-v2",
                            "discovered": 47,
                            "ai_retained": 19,
                            "history_duplicates": 2,
                            "new_count": 17,
                        },
                    },
                ],
            ),
            mock.patch.object(
                web_app,
                "load_strategic_news_run",
                return_value={
                    "review_sheet": {
                        "new_category_counts": {
                            "竞对动态": 2,
                            "竞争对手": 1,
                            "政策监管": 3,
                        },
                        "new_source_count": 16,
                        "new_items": [
                            {"business_impact": "收入与需求"},
                            {"business_impact": "收入与需求"},
                            {"business_impact": "网络与运营"},
                        ],
                    }
                },
            ),
        ):
            funnel = web_app.build_latest_news_funnel()

        self.assertEqual(
            [(item["label"], item["value"]) for item in funnel["stages"]],
            [("检索发现", 47), ("AI确认", 19), ("历史去重", 17), ("本轮新增", 17)],
        )
        self.assertEqual(funnel["historyDuplicates"], 2)
        self.assertEqual(funnel["label"], "7月29日 15:00")
        self.assertEqual(funnel["stages"][1]["removed"], 28)
        self.assertEqual(funnel["stages"][1]["rate"], 40)
        self.assertIn("事件级语义去重", funnel["stages"][2]["detail"])
        self.assertEqual(
            funnel["summary"],
            {"discovered": 47, "confirmed": 19, "newCount": 17, "sourceCount": 16},
        )
        self.assertEqual(
            funnel["categories"],
            [{"label": "竞对动态", "value": 3}, {"label": "政策监管", "value": 3}],
        )
        self.assertEqual(
            funnel["impacts"],
            [{"label": "收入与需求", "value": 2}, {"label": "网络与运营", "value": 1}],
        )

    def test_today_news_rounds_compare_morning_and_afternoon_archives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runs_dir = Path(tmp)
            (runs_dir / "2026-07-29@09-00.json").write_text(
                json.dumps(
                    {
                        "news_discovery": {"result_count": 120},
                        "review_sheet": {
                            "batch_count": 18,
                            "new_count": 1,
                            "new_category_counts": {"竞对动态": 2, "政策监管": 1},
                            "new_items": [
                                {"business_impact": "竞争格局"},
                                {"business_impact": "收入与需求"},
                                {"business_impact": "收入与需求"},
                            ],
                        },
                        "dashboard_summary": {
                            "discovered": 120,
                            "confirmed": 20,
                            "history_duplicates": 17,
                            "new_count": 3,
                            "status": "已补录",
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (runs_dir / "2026-07-29@15-00.json").write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "news_discovery": {"result_count": 47},
                        "review_sheet": {
                            "batch_count": 19,
                            "new_count": 17,
                            "semantic_duplicate_count": 2,
                            "new_category_counts": {"竞对动态": 3, "政策监管": 2},
                            "new_items": [
                                {"business_impact": "竞争格局"},
                                {"business_impact": "客户与渠道"},
                            ],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with mock.patch.object(web_app, "STRATEGIC_BRIEFING_RUNS_DIR", runs_dir):
                rounds = web_app.build_today_news_rounds("2026-07-29")

        self.assertEqual(
            [(item["label"], item["discovered"], item["confirmed"], item["newCount"]) for item in rounds],
            [("上午", 120, 20, 3), ("下午", 47, 19, 17)],
        )
        self.assertEqual(rounds[0]["status"], "已补录")
        self.assertEqual(
            [[stage["value"] for stage in item["stages"]] for item in rounds],
            [[120, 20, 3, 3], [47, 19, 17, 17]],
        )
        self.assertEqual(
            rounds[0]["categories"],
            [{"label": "竞对动态", "value": 2}, {"label": "政策监管", "value": 1}],
        )
        self.assertEqual(
            rounds[1]["categories"],
            [{"label": "竞对动态", "value": 3}, {"label": "政策监管", "value": 2}],
        )
        self.assertEqual(
            rounds[0]["impacts"],
            [{"label": "收入与需求", "value": 2}, {"label": "竞争格局", "value": 1}],
        )
        self.assertEqual(
            rounds[1]["impacts"],
            [{"label": "客户与渠道", "value": 1}, {"label": "竞争格局", "value": 1}],
        )

    def test_strategic_news_crawl_is_visible_as_news_crawler_task(self) -> None:
        task = web_app._normalize_crawl_task(
            {
                "crawl_run_id": "20260729_150000_news",
                "task_kind": "strategic-news",
                "trigger": "战略新闻定时爬虫",
                "scope": "午后扫描（2026-07-29@15:00）",
                "run_status": "running",
                "stream_log": {"lines": 6, "bytes": 800},
            }
        )

        self.assertEqual(task["kind"], "strategic-news")
        self.assertEqual(task["kind_label"], "新闻爬虫")
        self.assertEqual(task["title"], "战略新闻定时爬虫")
        self.assertEqual(task["lines"], 6)

    def test_homepage_uses_candidate_activity_when_no_confirmed_signals_exist(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")

        self.assertIn("showCandidateFallback", app)
        self.assertIn('showCandidateFallback ? "每日候选趋势" : "每日信号趋势"', app)
        self.assertIn("Array.isArray(visuals.todayNewsRounds)", app)
        self.assertNotIn('id="signalTopicTitle">主题热度</strong>', (web_app.ROOT / "web/static/index.html").read_text(encoding="utf-8"))
        self.assertIn("renderStrategicOverview(items, payload.candidate_items)", app)

    def test_report_file_pattern_accepts_new_and_legacy_as_of_names(self) -> None:
        self.assertIsNotNone(web_app.REPORT_FILE_RE.fullmatch("7月31日周报（截至7月22日）.docx"))
        self.assertIsNotNone(web_app.REPORT_FILE_RE.fullmatch("7月31日周报（草稿，截至7月22日）.docx"))
        self.assertIsNotNone(web_app.REPORT_FILE_RE.fullmatch("7月31日周报.docx"))


class ChatThreadPersistenceTests(unittest.TestCase):
    def test_chat_thread_requests_bypass_stale_browser_cache(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")

        self.assertIn('fetch("/api/chat-threads", { cache: "no-store" })', app)
        self.assertIn(
            'fetch(`/api/chat-threads?id=${encodeURIComponent(threadId)}`, { cache: "no-store" })',
            app,
        )
        self.assertIn('if (response.status === 404)', app)
        self.assertIn('await loadChatThreads();', app)

    def test_assistant_message_preserves_exactly_three_generated_suggestions(self) -> None:
        clean = web_app._clean_chat_message({
            "role": "assistant",
            "content": "完整回答。",
            "suggestions": ["问题一？", "问题二？", "问题三？", "多余问题？"],
        })

        self.assertEqual(clean["suggestions"], ["问题一？", "问题二？", "问题三？"])

    def test_chat_message_preserves_valid_per_message_timestamps(self) -> None:
        clean = web_app._clean_chat_message({
            "role": "assistant",
            "content": "完整回答。",
            "createdAt": "2026-07-22T17:01:02.123Z",
            "completedAt": "2026-07-22T17:01:08.456Z",
        })

        self.assertEqual(clean["createdAt"], "2026-07-22T17:01:02.123Z")
        self.assertEqual(clean["completedAt"], "2026-07-22T17:01:08.456Z")

    def test_chat_message_rejects_invalid_timestamps(self) -> None:
        clean = web_app._clean_chat_message({
            "role": "user",
            "content": "测试",
            "createdAt": "not-a-date",
        })

        self.assertNotIn("createdAt", clean)

    def test_saving_chat_does_not_wait_for_ai_title_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_path = Path(temp_dir) / "threads.json"
            with (
                mock.patch.object(web_app, "CHAT_THREADS_DIR", Path(temp_dir)),
                mock.patch.object(web_app, "CHAT_THREADS_PATH", thread_path),
                mock.patch.object(web_app, "generate_chat_thread_title", side_effect=AssertionError("must be background")),
                mock.patch.object(web_app, "_schedule_chat_thread_title") as schedule_title,
            ):
                record = web_app.upsert_chat_thread({
                    "id": "thread-stream-release",
                    "messages": [{"role": "user", "content": "你好"}],
                })

        self.assertEqual(record["title"], "初次咨询")
        self.assertTrue(record["titlePending"])
        schedule_title.assert_called_once_with("thread-stream-release", "你好")

    def test_background_title_refresh_updates_saved_thread(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_path = Path(temp_dir) / "threads.json"
            web_app.CHAT_TITLE_PENDING.clear()
            web_app.CHAT_TITLE_ACTIVE.clear()
            with (
                mock.patch.object(web_app, "CHAT_THREADS_DIR", Path(temp_dir)),
                mock.patch.object(web_app, "CHAT_THREADS_PATH", thread_path),
                mock.patch.object(web_app, "generate_chat_thread_title", return_value="行业周报查询"),
            ):
                web_app.upsert_chat_thread({
                    "id": "thread-background-title",
                    "messages": [{"role": "user", "content": "我想查看最新的行业周报"}],
                })
                for _ in range(100):
                    saved = web_app.get_chat_thread("thread-background-title")
                    if saved and not saved.get("titlePending"):
                        break
                    time.sleep(0.01)

        self.assertEqual(saved["title"], "行业周报查询")
        self.assertFalse(saved["titlePending"])


class ChatApprovalProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        web_app.CHAT_APPROVAL_WAITERS.clear()

    def tearDown(self) -> None:
        web_app.CHAT_APPROVAL_WAITERS.clear()

    def test_allow_pauses_then_restarts_same_turn_with_action_id(self) -> None:
        calls: list[list[str]] = []

        def fake_agent(_message, *, approved_action_ids, **_kwargs):
            calls.append(list(approved_action_ids))
            if "trigger_full_crawl:abc" not in approved_action_ids:
                yield {
                    "type": "action_confirmation",
                    "actionId": "trigger_full_crawl:abc",
                    "label": "全量爬虫",
                    "description": "执行完整公开信息爬取。",
                }
                return
            yield {"type": "delta", "text": "已开始执行。"}
            yield {"type": "done"}

        events = list(web_app.stream_agent_with_approvals(
            "请全量爬取",
            request_id="request-allow",
            decision_waiter=lambda _request_id, _action_id: "allow",
            agent_factory=fake_agent,
        ))

        self.assertEqual(calls, [[], ["trigger_full_crawl:abc"]])
        self.assertEqual([event["type"] for event in events], [
            "action_confirmation", "approval_result", "delta", "done",
        ])
        self.assertEqual(events[0]["requestId"], "request-allow")
        self.assertEqual(events[1]["decision"], "allow")

    def test_deny_finishes_turn_without_executing_action(self) -> None:
        calls = 0

        def fake_agent(_message, *, approved_action_ids, **_kwargs):
            nonlocal calls
            calls += 1
            yield {
                "type": "action_confirmation",
                "actionId": "trigger_full_crawl:def",
                "label": "全量爬虫",
            }

        events = list(web_app.stream_agent_with_approvals(
            "请全量爬取",
            request_id="request-deny",
            decision_waiter=lambda _request_id, _action_id: "deny",
            agent_factory=fake_agent,
        ))

        self.assertEqual(calls, 1)
        self.assertEqual(events[-2], {"type": "delta", "text": "已取消执行：全量爬虫。"})
        self.assertEqual(events[-1], {"type": "done"})


class ChatAudioTranscriptionTests(unittest.TestCase):
    def test_company_asr_receives_multipart_audio_and_returns_text(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({"text": "请分析最新业绩。"}).encode()
        payload = {"audio": "data:audio/webm;codecs=opus;base64," + base64.b64encode(b"webm-audio").decode()}
        with (
            mock.patch.object(web_app, "load_ai_config", return_value={
                "base_url": web_app.INTERNAL_AI_BASE_URL,
                "api_key": "secret-test-key",
            }),
            mock.patch.object(
                web_app.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    args=["ffmpeg"],
                    returncode=0,
                    stdout=b"RIFF" + (b"\0" * 100),
                    stderr=b"",
                ),
            ) as convert,
            mock.patch.object(web_app.urllib.request, "urlopen", return_value=response) as urlopen,
            mock.patch.object(web_app, "wait_for_internal_ai_slot"),
        ):
            result = web_app.transcribe_chat_audio(payload)

        self.assertEqual(result, {"text": "请分析最新业绩。", "model": "Qwen3ASR"})
        request = urlopen.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/audio/transcriptions"))
        self.assertIn(b'name="model"', request.data)
        self.assertIn(b"Qwen3ASR", request.data)
        self.assertIn(b'name="file"', request.data)
        self.assertIn(b'filename="voice.wav"', request.data)
        self.assertIn(b"Content-Type: audio/wav", request.data)
        self.assertEqual(convert.call_args.kwargs["input"], b"webm-audio")
        self.assertEqual(convert.call_args.kwargs["timeout"], 20)

    def test_audio_validation_rejects_unsupported_data_urls(self) -> None:
        with self.assertRaisesRegex(ValueError, "只支持"):
            web_app.transcribe_chat_audio({"audio": "data:text/plain;base64,SGVsbG8="})

    def test_audio_validation_rejects_browser_recordings_ffmpeg_cannot_decode(self) -> None:
        payload = {"audio": "data:audio/webm;base64," + base64.b64encode(b"broken-webm").decode()}
        with mock.patch.object(
            web_app.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                args=["ffmpeg"],
                returncode=1,
                stdout=b"",
                stderr=b"invalid data",
            ),
        ):
            with self.assertRaisesRegex(ValueError, "无法解码"):
                web_app.transcribe_chat_audio(payload)

    def test_audio_transcription_rejects_common_silence_hallucination(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({"text": "嗯。"}).encode()
        payload = {"audio": "data:audio/webm;base64," + base64.b64encode(b"valid-webm").decode()}
        with (
            mock.patch.object(web_app, "load_ai_config", return_value={
                "base_url": web_app.INTERNAL_AI_BASE_URL,
                "api_key": "secret-test-key",
            }),
            mock.patch.object(
                web_app.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    args=["ffmpeg"],
                    returncode=0,
                    stdout=b"RIFF" + (b"\0" * 100),
                    stderr=b"",
                ),
            ),
            mock.patch.object(web_app.urllib.request, "urlopen", return_value=response),
            mock.patch.object(web_app, "wait_for_internal_ai_slot"),
        ):
            with self.assertRaisesRegex(ValueError, "语气词"):
                web_app.transcribe_chat_audio(payload)


class ChatImageAnalysisTests(unittest.TestCase):
    def test_text_chat_model_uses_dedicated_vision_model_for_images(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps({
            "choices": [{"message": {"content": "", "reasoning_content": "图片中包含一张趋势图。"}}],
        }).encode("utf-8")
        payload = {
            "model": "deepseek-v4",
            "image": "data:image/png;base64,iVBORw0KGgo=",
            "filename": "clipboard.png",
            "question": "请分析",
        }

        with (
            mock.patch.object(
                web_app,
                "load_ai_config",
                return_value={
                    "model": "deepseek-v4",
                    "base_url": "https://api.cmhk-private.example/v1",
                    "api_key": "secret",
                },
            ),
            mock.patch.object(web_app, "is_internal_ai_base_url", return_value=True),
            mock.patch.object(web_app, "wait_for_internal_ai_slot"),
            mock.patch.object(web_app.urllib.request, "urlopen", return_value=response) as urlopen,
        ):
            result = web_app.analyze_chat_image(payload)

        request_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(request_body["model"], "Kimi-K2.5")
        self.assertEqual(result["model"], "Kimi-K2.5")
        self.assertIn("趋势图", result["description"])


class FrontendCitationRenderingTests(unittest.TestCase):
    def test_log_button_breathes_while_any_unified_task_is_running(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        styles = (web_app.ROOT / "web/static/styles.css").read_text(encoding="utf-8")

        self.assertIn("function renderLogButtonActivity()", app)
        self.assertIn("state.hasRunningTasks || localBusy", app)
        self.assertIn("status.tasks?.hasRunning", app)
        self.assertIn('els.logButton.classList.toggle("log-glowing", active)', app)
        self.assertIn('els.logButton.setAttribute("aria-busy", active ? "true" : "false")', app)
        self.assertIn("@keyframes logGlow", styles)
        self.assertIn("animation: logGlow 1.8s infinite ease-in-out", styles)

    def test_chat_launcher_is_icon_only_and_keeps_an_accessible_name(self) -> None:
        markup = (web_app.ROOT / "web/static/index.html").read_text(encoding="utf-8")
        styles = (web_app.ROOT / "web/static/styles.css").read_text(encoding="utf-8")
        launcher_start = markup.index('<button class="icon-button chat-fab"')
        launcher_end = markup.index("</button>", launcher_start)
        launcher = markup[launcher_start:launcher_end]

        self.assertIn('title="打开小竞AI"', launcher)
        self.assertIn('aria-label="打开小竞AI"', launcher)
        self.assertIn("xiaojing-ai-logo-mark.png", launcher)
        self.assertNotIn("<span>", launcher)
        self.assertIn(".dashboard-page .chat-fab {\n  position: static;", styles)
        self.assertIn("width: 36px;\n  height: 36px;", styles)
        self.assertIn(".dashboard-page .chat-fab img {\n  width: 46%;\n  height: 46%;", styles)

    def test_chat_picker_menus_use_dark_high_contrast_states(self) -> None:
        styles = (web_app.ROOT / "web/static/styles.css").read_text(encoding="utf-8")

        self.assertIn(".dashboard-page .chat-model-option.active {", styles)
        self.assertIn("color: #eaf8fa;\n  background: #194354;", styles)
        self.assertIn(".dashboard-page .skill-option.is-active,", styles)
        self.assertIn(".dashboard-page .database-upload-panel,", styles)

    def test_chat_tables_and_composer_shortcuts_use_dark_contrast_surfaces(self) -> None:
        styles = (web_app.ROOT / "web/static/styles.css").read_text(encoding="utf-8")

        self.assertIn(".dashboard-page .markdown-body .chat-data-table tbody tr:nth-child(even) {", styles)
        self.assertIn("background: #0e2d3a;", styles)
        self.assertIn(".dashboard-page .chat-composer-toolbar > .composer-plus-picker .composer-plus-button,", styles)
        self.assertIn("border: 1px solid rgba(105, 169, 188, .24) !important;", styles)
        self.assertIn("border-radius: 50% !important;\n  color: #adc7d0 !important;", styles)
        self.assertNotIn("box-shadow: inset 0 -2px #65c3d8;", styles)

    def test_ai_settings_and_starter_cards_follow_dark_flat_theme(self) -> None:
        styles = (web_app.ROOT / "web/static/styles.css").read_text(encoding="utf-8")

        self.assertIn(".dashboard-page #aiSettingsModal .settings-modal {", styles)
        self.assertIn("color: #e8f3f6;\n  background: #0a222e;", styles)
        self.assertIn(".dashboard-page .chat-starter-card::before {\n  display: none !important;", styles)
        self.assertIn(".dashboard-page .chat-model-option.active {", styles)
        self.assertNotIn("box-shadow: inset 3px 0 #61c2d8;", styles)

    def test_executive_domains_default_to_overview_before_entity_selection(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")

        self.assertIn("if (!selectedName) return -1;", app)
        self.assertNotIn("<span>综合发现</span>", app)
        self.assertNotIn("data-intelligence-overview", app)
        self.assertIn("selectedEntityByDomain.delete(domainId);", app)
        self.assertIn("selectedEntityByDomain.get(domainId) === items[index].name", app)
        self.assertIn('aria-pressed="${index === selectedIndex ? "true" : "false"}"', app)

    def test_new_chat_messages_record_created_and_completed_times(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        self.assertIn('createdAt: new Date().toISOString()', app)
        self.assertIn('assistantHistoryEntry.completedAt = new Date().toISOString()', app)
        self.assertIn('threadId: state.activeThreadId', app)

    def test_legacy_process_extraction_preserves_model_prose_verbatim(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        start = app.index("function extractAssistantProcessLines")
        end = app.index("function stripAssistantControlText", start)
        snippet = app[start:end] + "\n" + (
            "console.log(JSON.stringify("
            "extractAssistantProcessLines('我确认官方信息，核验状态为已确认。')"
            "));"
        )
        completed = subprocess.run(
            ["node", "-e", snippet],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            json.loads(completed.stdout),
            {"answer": "我确认官方信息，核验状态为已确认。", "processLines": []},
        )

    def test_control_filter_removes_tags_without_rewriting_model_prose(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        start = app.index("function stripAssistantControlText")
        end = app.index("function expandCitationIndexes", start)
        snippet = app[start:end] + "\n" + (
            "console.log(JSON.stringify(["
            "stripAssistantControlText('请进一步说明，以便我为您准确检索和提供信息。\\n<suggestions>[\\\"一\\\",\\\"二\\\",\\\"三\\\"]</suggestions>'),"
            "stripAssistantControlText('您好。请问您希望查看什么？我可以帮您查询经营数据、竞品资费和宏观政策。\\n<suggestions>[\\\"一\\\",\\\"二\\\",\\\"三\\\"]</suggestions>'),"
            "stripAssistantControlText('明确主体后，我将检索本地资料并整理路线图。\\n<suggestions>[\\\"一\\\",\\\"二\\\",\\\"三\\\"]</suggestions>')"
            "]));"
        )
        completed = subprocess.run(
            ["node", "-e", snippet],
            check=True,
            capture_output=True,
            text=True,
        )
        cleaned = json.loads(completed.stdout)
        self.assertEqual(cleaned[0], "请进一步说明，以便我为您准确检索和提供信息。")
        self.assertTrue(cleaned[1].endswith("宏观政策。"), cleaned[1])
        self.assertEqual(cleaned[2], "明确主体后，我将检索本地资料并整理路线图。")

    def test_suggestion_parser_accepts_json_nested_tags_and_markdown_bullets(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        start = app.index("function normalizeSuggestionList")
        end = app.index("function estimateChatTokens", start)
        snippet = app[start:end] + "\n" + (
            "console.log(JSON.stringify(["
            "parseSuggestionTag('<suggestions>[\\\"问题一？\\\",\\\"问题二？\\\",\\\"问题三？\\\"]</suggestions>'),"
            "parseSuggestionTag('<suggestions><suggestion>甲？</suggestion><suggestion>乙？</suggestion><suggestion>丙？</suggestion></suggestions>'),"
            "parseSuggestionTag('<suggestions>\\n- 推荐追问：第一问？\\n- 推荐追问：第二问？\\n- 推荐追问：第三问？\\n</suggestions>')"
            "]));"
        )
        completed = subprocess.run(["node", "-e", snippet], check=True, capture_output=True, text=True)

        self.assertEqual(
            json.loads(completed.stdout),
            [
                ["问题一？", "问题二？", "问题三？"],
                ["甲？", "乙？", "丙？"],
                ["第一问？", "第二问？", "第三问？"],
            ],
        )

    def test_frontend_prefers_structured_suggestion_event_and_requires_three_chips(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")

        self.assertIn('event.type === "suggestions"', app)
        self.assertIn("streamedSuggestions.length === 3 ? streamedSuggestions : embeddedSuggestions", app)
        self.assertIn('if (arr.length !== 3) return "";', app)

    def test_frontend_hides_assistant_centered_and_internal_process_suggestions(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        start = app.index("function normalizeSuggestionList")
        end = app.index("function suggestionChipsHtml", start)
        snippet = app[start:end] + "\n" + (
            "console.log(JSON.stringify(normalizeSuggestionList(["
            "'是否需要我读取该数据集中的具体文件？',"
            "'您希望重点了解哪一类政策？',"
            "'梳理香港5G频谱政策时间线并标注来源'"
            "])));"
        )
        completed = subprocess.run(["node", "-e", snippet], check=True, capture_output=True, text=True)

        self.assertEqual(
            json.loads(completed.stdout),
            ["梳理香港5G频谱政策时间线并标注来源"],
        )

    def test_historical_bad_5g_suggestions_receive_contextual_safe_fallbacks(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        start = app.index("function generateFallbackSuggestions")
        end = app.index("function normalizeSuggestionList", start)
        snippet = app[start:end] + "\n" + (
            "console.log(JSON.stringify(generateFallbackSuggestions("
            "'需要了解5G频谱政策事件的时间线和影响评估'"
            ")));"
        )
        completed = subprocess.run(["node", "-e", snippet], check=True, capture_output=True, text=True)
        suggestions = json.loads(completed.stdout)

        self.assertEqual(len(suggestions), 3)
        self.assertIn("官方来源", suggestions[0])
        self.assertIn("各频段", suggestions[1])
        self.assertIn("CMHK", suggestions[2])
        self.assertIn("restoreAssistantMessageExtras(node, normalizedItem, previousUserMessage);", app)
        self.assertIn("normalizedSuggestions.length === 3", app)

    def test_voice_dictation_is_live_editable_and_uses_system_default_microphone(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        markup = (web_app.ROOT / "web/static/index.html").read_text(encoding="utf-8")

        self.assertIn('id="voiceInputButton"', markup)
        self.assertNotIn('id="voiceModeButton"', markup)
        self.assertNotIn('id="voiceModeMenu"', markup)
        self.assertNotIn('id="voiceDeviceSelect"', markup)
        self.assertNotIn("语音识别后", markup)
        self.assertNotIn("收音设备", markup)
        self.assertLess(markup.index('id="chatModelPicker"'), markup.index('id="voiceInputButton"'))
        self.assertIn("navigator.mediaDevices.getUserMedia", app)
        self.assertIn('deviceId: { ideal: "default" }', app)
        self.assertNotIn("navigator.mediaDevices.enumerateDevices", app)
        self.assertNotIn("cmhkVoiceInputDeviceId", app)
        self.assertIn("window.SpeechRecognition || window.webkitSpeechRecognition", app)
        self.assertIn("recognition.continuous = true", app)
        self.assertIn("recognition.interimResults = true", app)
        self.assertIn('recognition.addEventListener("result"', app)
        self.assertIn("renderVoiceTranscript(state.voiceLiveTranscript)", app)
        self.assertIn("new MediaRecorder", app)
        self.assertIn('fetch("/api/chat-audio-transcribe"', app)
        self.assertNotIn("voiceMode", app)
        self.assertIn('"只识别到很短的语气词"', app)
        self.assertIn("if (!state.voiceLiveTranscript && !ignorableNoSpeech)", app)
        self.assertIn("function isIgnorableVoiceTranscript(transcript)", app)
        self.assertIn("isIgnorableVoiceTranscript(liveTranscript) ? \"\" : liveTranscript", app)
        self.assertIn('state.voiceLiveTranscript = "";\n      renderVoiceTranscript("");', app)
        self.assertNotIn(
            'if (!state.voiceLiveTranscript) showTaskOperationNotice(error.message || "语音识别失败，请重试")',
            app,
        )
        self.assertNotIn("语音已转成文字", app)
        self.assertIn("recorder.start();", app)

    def test_chat_composer_keeps_model_voice_and_send_inside_one_card(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        markup = (web_app.ROOT / "web/static/index.html").read_text(encoding="utf-8")
        styles = (web_app.ROOT / "web/static/styles.css").read_text(encoding="utf-8")

        composer_start = markup.index('<div class="chat-composer">')
        toolbar_start = markup.index('<div class="chat-composer-toolbar">', composer_start)
        composer_end = markup.index("</form>", toolbar_start)
        submit_index = markup.index('id="chatSubmitButton"', toolbar_start)
        self.assertLess(submit_index, composer_end)
        self.assertIn('placeholder="随心输入"', markup[composer_start:toolbar_start])
        self.assertIn(".chat-model-picker { position: relative; min-width: 0; margin-left: auto; }", styles)
        self.assertIn("width: min(280px, calc(100vw - 32px))", styles)
        self.assertIn("border-radius: 16px", styles)
        self.assertIn(".chat-model-option { width: 100%; min-height: 40px;", styles)
        self.assertIn(".chat-model-option strong { flex: 1; min-width: 0; overflow: hidden; font-size: 13px;", styles)
        self.assertIn(".chat-model-tags { display: none; }", styles)
        self.assertIn(".chat-model-check { display: none; }", styles)
        self.assertIn(".chat-model-options::-webkit-scrollbar-thumb", styles)
        self.assertIn("border-radius: 50%", styles)
        self.assertIn("function renderChatSubmitState()", app)
        self.assertIn("els.chatSubmitButton.disabled = !state.chatBusy && !ready", app)

    def test_new_chat_uses_adapted_competitive_intelligence_starter_cards(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        markup = (web_app.ROOT / "web/static/index.html").read_text(encoding="utf-8")
        styles = (web_app.ROOT / "web/static/styles.css").read_text(encoding="utf-8")

        self.assertIn("今天想从哪类竞争情报开始？", markup)
        self.assertEqual(markup.count('class="chat-starter-card"'), 0)
        self.assertGreaterEqual(len(web_app.CHAT_STARTER_POOL), 8)
        starters = web_app.sample_chat_starters()
        self.assertEqual(len(starters), 4)
        self.assertEqual(len({item["title"] for item in starters}), 4)
        self.assertIn('fetch("/api/chat-starters", { cache: "no-store" })', app)
        self.assertIn("loadChatStarters({ render: true })", app)
        self.assertIn("await loadChatStarters()", app)
        self.assertIn('const emptyState = els.messages.querySelector(".chat-empty-state")', app)
        self.assertIn('event.target.closest(".chat-starter-card")', app)
        self.assertIn("els.messages.innerHTML = initialChatEmptyStateHtml()", app)
        for tone in ("is-blue", "is-violet", "is-teal", "is-orange"):
            self.assertTrue(any(item["tone"] == tone.removeprefix("is-") for item in web_app.CHAT_STARTER_POOL))
        self.assertIn("grid-template-columns: repeat(4, minmax(0, 1fr))", styles)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", styles)

    def test_chat_header_keeps_actions_but_removes_redundant_product_copy(self) -> None:
        markup = (web_app.ROOT / "web/static/index.html").read_text(encoding="utf-8")
        styles = (web_app.ROOT / "web/static/styles.css").read_text(encoding="utf-8")
        header_start = markup.index('<div class="chat-header">')
        header_end = markup.index("</div>", markup.index('id="closeChatButton"', header_start))
        header = markup[header_start:header_end]

        self.assertNotIn("chat-header-title", header)
        self.assertNotIn("智能 Agent：支持联网搜索", header)
        self.assertIn('id="toggleChatThreadsButton"', header)
        self.assertIn('id="newChatThreadButton"', header)
        self.assertIn('id="aiSettingsButton"', header)
        self.assertIn('class="chat-header-icon-button"', header)
        self.assertNotIn('id="clearChatButton"', header)
        self.assertIn('id="closeChatButton"', header)
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        self.assertNotIn("clearChatButton:", app)
        self.assertIn("preserveContent: true", app)
        self.assertIn("margin-right: auto", styles[styles.index(".chat-nav-controls {"):])

    def test_reasoning_uses_one_transparent_outline_without_a_filled_header_box(self) -> None:
        styles = (web_app.ROOT / "web/static/styles.css").read_text(encoding="utf-8")
        panel_start = styles.index(".model-reasoning {")
        panel_end = styles.index(".model-reasoning-content h3", panel_start)
        panel_styles = styles[panel_start:panel_end]

        self.assertIn("border: 0", panel_styles)
        self.assertIn(".model-reasoning[open] {\n  border: 1px solid #d7e4ee", panel_styles)
        self.assertGreaterEqual(panel_styles.count("background: transparent"), 3)
        self.assertIn("box-shadow: none", panel_styles)
        self.assertIn("border-top: 0", panel_styles)
        self.assertIn("outline: none", panel_styles)
        self.assertIn("text-decoration: underline", panel_styles)
        self.assertNotIn("background: #f7fafc", panel_styles)

    def test_chat_removes_all_thinking_marker_ui_but_keeps_reasoning_stream(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        styles = (web_app.ROOT / "web/static/styles.css").read_text(encoding="utf-8")

        self.assertNotIn('else if (event.type === "status")', app)
        self.assertIn('else if (event.type === "reasoning")', app)
        self.assertIn("appendModelReasoning(assistantNode, event.text)", app)
        self.assertNotIn("appendRagProcess", app)
        self.assertNotIn("appendRunSummary", app)
        self.assertNotIn("showThinkingPanel", app)
        self.assertNotIn('>Thinking<', app)
        self.assertNotIn(".rag-process", styles)
        self.assertNotIn(".thinking-dots", styles)
        merge_start = app.index("function mergeCitationMeta")
        merge_end = app.index("function hideChatApproval", merge_start)
        self.assertNotIn("appendRagProcess(", app[merge_start:merge_end])

    def test_reasoning_stream_renders_markdown_instead_of_raw_markers(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        start = app.index("function appendModelReasoning")
        end = app.index("function assistantTimelineToolEvent", start)
        reasoning_renderer = app[start:end]

        self.assertIn("content.innerHTML = markdownToHtml(content._rawReasoning)", reasoning_renderer)
        self.assertNotIn("content.textContent = content._rawReasoning", reasoning_renderer)

    def test_bold_bullet_label_with_colon_is_not_misclassified_as_heading(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        start = app.index("function escapeHtml")
        end = app.index("function parseChartNumber", start)
        snippet = app[start:end] + "\n" + (
            "console.log(markdownToHtml("
            "'## 风险与下一步动作\\n"
            "*   **风险**：若价格战持续。\\n"
            "*   **下一步动作建议**：\\n"
            "*   **停止价格战**：避免无效竞争。'));"
        )
        completed = subprocess.run(
            ["node", "-e", snippet],
            check=True,
            capture_output=True,
            text=True,
        )
        rendered = completed.stdout
        self.assertIn("<li><strong>下一步动作建议</strong>：</li>", rendered)
        self.assertNotIn("<h3>*", rendered)

    def test_runtime_sync_preserves_live_chat_history(self) -> None:
        script = (web_app.ROOT / "sync_app_runtime.sh").read_text(encoding="utf-8")
        self.assertIn("--exclude='agent_chat_threads/'", script)
        for runtime_state in (
            "strategy_briefing/",
            "agent_knowledge/crawl_run_logs/",
            "results/",
            "curation_data/",
            "crawl_runs/",
            "task_runs/",
            "agent_runs/",
            "run_log.json",
            "run_log.tsv",
            "final_audit.md",
            "coverage_report.tsv",
            "daily_validation.json",
            "scheduler_state.json",
            "scheduler_pending_run.json",
        ):
            self.assertIn(f"--exclude='{runtime_state}'", script)

    def test_frontend_finalizes_orphaned_tool_cards_for_live_and_restored_chats(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        start = app.index("function finalizePendingAssistantToolEvents")
        end = app.index("function renderAssistantToolEvent", start)
        snippet = app[start:end] + "\n" + (
            "const timeline = ["
            "{type:'tool_call_start',id:'done-1',name:'web_search'},"
            "{type:'tool_call_result',id:'done-1',name:'web_search',content:'ok'},"
            "{type:'tool_call_start',id:'pending-1',name:'read_webpage'}"
            "];"
            "const finalized = finalizePendingAssistantToolEvents(timeline);"
            "console.log(JSON.stringify({finalized,timeline}));"
        )
        completed = subprocess.run(
            ["node", "-e", snippet],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)

        self.assertEqual(len(result["finalized"]), 1)
        self.assertEqual(result["finalized"][0]["id"], "pending-1")
        self.assertIn("没有收到此工具的返回结果", result["finalized"][0]["content"])
        self.assertEqual(len(result["timeline"]), 4)
        self.assertIn("finalizePendingAssistantToolEvents(timeline);", app)
        self.assertIn("finalizePendingAssistantToolEvents(assistantTimeline);", app)

    def test_reasoning_stream_starts_a_new_block_after_each_non_reasoning_event(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        start = app.index("function appendModelReasoning")
        end = app.index("function assistantTimelineToolEvent", start)
        reasoning_renderer = app[start:end]

        self.assertIn("let panel = body.lastElementChild", reasoning_renderer)
        self.assertIn('!panel.classList.contains("model-reasoning")', reasoning_renderer)
        self.assertNotIn('body.querySelector(".model-reasoning")', reasoning_renderer)

    def test_reasoning_collapses_when_final_answer_stream_starts_and_when_stream_finishes(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        collapse_start = app.index("function collapseLatestModelReasoning")
        collapse_end = app.index("function ensureToolList", collapse_start)
        collapse_helper = app[collapse_start:collapse_end]
        append_start = app.index("function appendStreamBlock")
        append_end = app.index("function assistantAnswerNodes", append_start)
        append_helper = app[append_start:append_end]
        text_start = app.index("function currentMessageTextNode")
        text_end = app.index("function setCurrentMessageContent", text_start)
        text_helper = app[text_start:text_end]

        self.assertIn('querySelectorAll(".model-reasoning")', collapse_helper)
        self.assertIn("panel.open = false", collapse_helper)
        self.assertIn("collapseLatestModelReasoning(node)", append_helper)
        self.assertNotIn("collapseLatestModelReasoning(node)", text_helper)
        send_start = app.index("async function sendChat")
        send_end = app.index("els.generateButtons.forEach", send_start)
        send_chat = app[send_start:send_end]
        self.assertIn("let collapseReasoningOnNextDelta = false;", send_chat)
        self.assertIn('event.type === "reasoning"', send_chat)
        self.assertIn("collapseReasoningOnNextDelta = true;", send_chat)
        first_delta_start = send_chat.index('if (event.type === "delta")')
        first_delta_end = send_chat.index("textChunk = event.text;", first_delta_start)
        first_delta = send_chat[first_delta_start:first_delta_end]
        self.assertIn("if (collapseReasoningOnNextDelta)", first_delta)
        self.assertIn("collapseLatestModelReasoning(assistantNode);", first_delta)
        self.assertIn("collapseReasoningOnNextDelta = false;", first_delta)
        self.assertIn("finishStreamingText();\n    collapseLatestModelReasoning(assistantNode);", send_chat)

    def test_reasoning_stream_scrolls_its_panel_to_the_latest_token(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        scroll_start = app.index("function scrollReasoningToLatest")
        scroll_end = app.index("function appendModelReasoning", scroll_start)
        scroll_helper = app[scroll_start:scroll_end]
        reasoning_start = scroll_end
        reasoning_end = app.index("function assistantTimelineToolEvent", reasoning_start)
        reasoning_renderer = app[reasoning_start:reasoning_end]

        self.assertIn("content.scrollTop = content.scrollHeight", scroll_helper)
        self.assertIn("requestAnimationFrame(scroll)", scroll_helper)
        self.assertIn("scrollReasoningToLatest(content)", reasoning_renderer)

    def test_done_releases_chat_before_persistence_and_status_refresh_finish(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        send_start = app.index("async function sendChat")
        send_end = app.index("els.generateButtons.forEach", send_start)
        send_chat = app[send_start:send_end]

        persist_pos = send_chat.index("const completionPersist = flushDraftPersist();")
        release_pos = send_chat.index("releaseChatTurn();", persist_pos)
        await_pos = send_chat.index("await completionPersist;", release_pos)
        self.assertLess(persist_pos, release_pos)
        self.assertLess(release_pos, await_pos)
        self.assertIn("if (state.chatAbortController !== requestController) return;", send_chat)
        self.assertIn("let chatPersistChain = Promise.resolve();", app)
        self.assertIn("const snapshotBody = JSON.stringify({", app)

    def test_answer_metrics_are_rendered_last_and_restored_from_history(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        styles = (web_app.ROOT / "web/static/styles.css").read_text(encoding="utf-8")
        send_start = app.index("async function sendChat")
        send_end = app.index("els.generateButtons.forEach", send_start)
        send_chat = app[send_start:send_end]

        self.assertIn('event.type === "run_summary"', send_chat)
        self.assertIn("appendAssistantMetrics(assistantNode, finalMetrics);", send_chat)
        self.assertIn("assistantHistoryEntry.metrics = finalMetrics", send_chat)
        self.assertIn("if (item.metrics) appendAssistantMetrics(node, item.metrics);", app)
        self.assertIn(".assistant-response-metrics", styles)
        self.assertIn("font-size: 10.5px", styles)
        self.assertIn("color: #93a1ad", styles)

    def test_waiting_message_has_codex_style_steer_action(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        queue_start = app.index("function renderChatQueue")
        queue_end = app.index("function setChatSidebarCollapsed", queue_start)
        queue_code = app[queue_start:queue_end]
        handler_start = app.index("if (els.chatQueueList)")
        handler_end = app.index("if (els.webSearchToggle)", handler_start)
        handler = app[handler_start:handler_end]

        self.assertIn('data-action="steer"', queue_code)
        self.assertIn(">插队</button>", queue_code)
        self.assertIn('if (action === "steer")', handler)
        self.assertIn("state.chatQueue.unshift(queued)", handler)
        self.assertIn("state.chatAbortController.steerRequested = true", handler)
        self.assertIn("state.chatAbortController.abort()", handler)
        self.assertIn("（已收到插队消息，当前回答已停止）", app)
        self.assertIn("if (stopStreamingRender) stopStreamingRender();", app)
        self.assertIn("if (assistantNode) collapseLatestModelReasoning(assistantNode);", app)
        self.assertIn("const interruptedPersist = flushDraftPersist();\n    releaseChatTurn();\n    await interruptedPersist;", app)

    def test_action_approval_is_above_composer_and_resumes_the_same_stream(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        html = (web_app.ROOT / "web/static/index.html").read_text(encoding="utf-8")
        styles = (web_app.ROOT / "web/static/styles.css").read_text(encoding="utf-8")
        approval_start = app.index("function showActionConfirmation")
        approval_end = app.index("function resetAssistantForApprovalResume", approval_start)
        approval_renderer = app[approval_start:approval_end]

        self.assertLess(html.index('id="chatApprovalBar"'), html.index('id="chatForm"'))
        self.assertIn('fetch("/api/chat-approval"', app)
        self.assertIn('data-decision="deny"', approval_renderer)
        self.assertIn('data-decision="allow"', approval_renderer)
        self.assertNotIn("appendStreamBlock", approval_renderer)
        self.assertNotIn("sendChat(", approval_renderer)
        self.assertIn('event.type === "approval_result"', app)
        self.assertIn("resetAssistantForApprovalResume(assistantNode, assistantTimeline)", app)
        self.assertIn("requestId: chatRequestId", app)
        self.assertIn(".chat-approval-bar", styles)
        self.assertNotIn(".action-confirm-card", styles)

    def test_sent_image_preview_is_rendered_and_persisted_in_the_user_message(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        styles = (web_app.ROOT / "web/static/styles.css").read_text(encoding="utf-8")
        send_start = app.index("async function sendChat")
        send_end = app.index("els.generateButtons.forEach", send_start)
        send_chat = app[send_start:send_end]

        self.assertIn("function appendUserImagePreview", app)
        self.assertIn("appendUserImagePreview(userNode, options.displayImage)", send_chat)
        self.assertIn("userHistoryEntry.imagePreview = options.displayImage", send_chat)
        self.assertIn("appendUserImagePreview(node, item.imagePreview)", app)
        self.assertIn("dataUrl: attachment.previewDataUrl || attachment.dataUrl", app)
        self.assertNotIn("[图片：${attachment.name}]", app)
        self.assertIn(".chat-user-image-preview", styles)

        cleaned = web_app._clean_chat_message({
            "role": "user",
            "content": "请分析图片",
            "displayContent": "这个怎么说",
            "imagePreview": {
                "name": "example.png",
                "dataUrl": "data:image/png;base64,iVBORw0KGgo=",
            },
        })
        self.assertEqual(cleaned["displayContent"], "这个怎么说")
        self.assertEqual(cleaned["imagePreview"]["name"], "example.png")
        self.assertTrue(cleaned["imagePreview"]["dataUrl"].startswith("data:image/png;base64,"))

    def test_chat_composer_accepts_clipboard_images_without_changing_text_paste(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        markup = (web_app.ROOT / "web/static/index.html").read_text(encoding="utf-8")

        self.assertIn('placeholder="随心输入" title="可直接粘贴图片"', markup)
        self.assertIn('els.chatInput.addEventListener("paste"', app)
        self.assertIn("event.clipboardData", app)
        self.assertIn('item.kind === "file"', app)
        self.assertIn('startsWith("image/")', app)
        self.assertIn("event.preventDefault();", app)
        self.assertIn("attachChatImageFile(imageFile, { pasted: true });", app)
        self.assertIn("if (!imageFile) return;", app)

    def test_chat_model_choice_is_remembered_in_browser_storage(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")

        self.assertIn('CHAT_MODEL_STORAGE_KEY = "cmhk.chat.selected-model.v1"', app)
        self.assertIn("window.localStorage.getItem(CHAT_MODEL_STORAGE_KEY)", app)
        self.assertIn("window.localStorage.setItem(CHAT_MODEL_STORAGE_KEY", app)
        self.assertIn("const rememberedModel = getRememberedChatModel();", app)
        self.assertIn("rememberChatModel(model);", app)
        self.assertIn("els.composerUploadImageButton.disabled = state.chatImageAnalysisBusy;", app)
        self.assertNotIn("当前模型不支持图片，请先切换到视觉模型。", app)

    def test_daily_asset_funnels_do_not_replay_on_status_polling(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        styles = (web_app.ROOT / "web/static/styles.css").read_text(encoding="utf-8")

        self.assertIn("if (assetHost.dataset.signature === signature) return;", app)
        self.assertIn("assetHost.dataset.signature = signature;", app)
        self.assertIn('id="dailyScanComparisonTitle"', app)
        self.assertIn("daily-unified-funnel-stage", app)
        self.assertNotIn("animation: cockpit-bar-grow", styles)
        self.assertNotIn("animation: cockpit-rise 400ms", styles)

    def test_dashboard_uses_dense_flat_hierarchy_without_low_value_status_copy(self) -> None:
        markup = (web_app.ROOT / "web/static/index.html").read_text(encoding="utf-8")
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        styles = (web_app.ROOT / "web/static/styles.css").read_text(encoding="utf-8")

        self.assertNotIn("滚动 14 天", markup)
        self.assertNotIn("数据已连接", markup)
        self.assertNotIn('id="signalInsightText"', markup)
        self.assertNotIn("竞对动态最活跃", app)
        self.assertNotIn("仅统计战略部人工确认的有效快讯", markup)
        self.assertNotIn("collectionCompletedAt", markup)
        self.assertNotIn("最近采集", app)
        for copy in ("近14日</small>", "占比 --", "已确认分类", "等待同步</small>", "已进入发布层", "本轮可追溯来源"):
            self.assertNotIn(copy, markup)
        self.assertNotIn("competitorSignalShare", app)
        self.assertNotIn("latestSignalCount", app)
        self.assertNotIn("collectionTaskCoverage", app)
        self.assertIn("Dense, flat dashboard", styles)
        self.assertIn("font-size: 24px;", styles)
        self.assertIn("margin-top: auto;", styles)

    def test_homepage_keeps_report_badge_without_news_hover_or_global_dashboard(self) -> None:
        markup = (web_app.ROOT / "web/static/index.html").read_text(encoding="utf-8")
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        styles = (web_app.ROOT / "web/static/styles.css").read_text(encoding="utf-8")
        backend = (web_app.ROOT / "web_app.py").read_text(encoding="utf-8")

        self.assertIn('id="reportLibraryNewDot"', markup)
        self.assertNotIn('data-signal-filter="competitor"', markup)
        self.assertNotIn('id="signalNewsPreview"', markup)
        self.assertNotIn("signalPreviewItems", app)
        self.assertNotIn("showSignalNewsPreview", app)
        self.assertNotIn("data-signal-entity", app)
        self.assertNotIn("onHover: (_event, elements, chart)", app)
        self.assertIn('REPORT_LIBRARY_SEEN_STORAGE_KEY = "cmhk.report-library.last-seen-mtime.v1"', app)
        self.assertIn('REPORT_LIBRARY_CONSUMED_STORAGE_KEY = "cmhk.report-library.consumed-files.v1"', app)
        self.assertIn("function markReportConsumed(pathStr)", app)
        self.assertIn("files.some((file) => isReportUnread(file))", app)
        self.assertNotIn("markReportLibrarySeen();", app)
        self.assertNotIn(".signal-news-preview", styles)
        self.assertNotIn(".signal-topic-card .signal-news-preview", styles)
        self.assertNotIn(".collection-entity-list > span:hover", styles)
        self.assertIn(".report-library-new-dot", styles)
        self.assertIn(".report-file-new-dot", styles)
        self.assertIn('class="report-file-new-dot"', app)
        self.assertIn('data-path="${safePath}" title="下载"', app)
        self.assertNotIn('id="dashboardBtn"', markup)
        self.assertNotIn('id="dashboardModal"', markup)
        self.assertNotIn("openDashboard", app)
        self.assertNotIn("sampleItems", app)
        self.assertNotIn('path == "/api/dashboard"', backend)
        self.assertNotIn(".dashboard-modal-content", styles)

    def test_homepage_uses_one_row_header_and_report_generation_lives_in_library(self) -> None:
        markup = (web_app.ROOT / "web/static/index.html").read_text(encoding="utf-8")
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        styles = (web_app.ROOT / "web/static/styles.css").read_text(encoding="utf-8")

        self.assertNotIn('id="headerTime"', markup)
        self.assertNotIn("function setClock()", app)
        self.assertNotIn('<section class="command-strip">', markup)
        self.assertIn('class="command-btn btn-library topbar-command" id="reportLibraryButton"', markup)
        topbar = markup[markup.index('<div class="header-tools">'):markup.index('<div class="header-runtime-status">')]
        self.assertNotIn('id="crawlButtonSecondary"', topbar)
        self.assertIn('class="icon-button nav-link cockpit-link" href="/executive-dashboard-demo.html" title="经营驾驶舱"', topbar)
        self.assertNotIn('href="/company-data.html"', topbar)
        library_header = markup[markup.index('<header class="report-library-header">'):]
        self.assertIn('class="command-btn btn-fetch" id="crawlButtonSecondary"', library_header)
        self.assertIn('id="generatePerformanceButton"', library_header)
        self.assertIn('id="generateButtonSecondary"', library_header)
        self.assertIn(".report-library-header-actions", styles)
        self.assertIn(".header-runtime-status", styles)
        self.assertIn("height: calc(100vh - 60px);", styles)
        self.assertIn("grid-template-rows: 104px minmax(0, 1fr);", styles)

    def test_answer_metrics_are_persisted_with_chat_history(self) -> None:
        cleaned = web_app._clean_chat_message({
            "role": "assistant",
            "content": "回答正文",
            "metrics": {
                "inputTokens": 120,
                "outputTokens": 30,
                "totalTokens": 150,
                "durationMs": 2345,
                "estimated": False,
            },
        })

        self.assertEqual(cleaned["metrics"]["totalTokens"], 150)
        self.assertEqual(cleaned["metrics"]["durationMs"], 2345)
        self.assertFalse(cleaned["metrics"]["estimated"])

    def test_named_source_citation_renders_when_reference_uses_full_path(self) -> None:
        script = r"""
const fs = require('fs');
const app = fs.readFileSync('web/static/app.js', 'utf8');
const start = app.indexOf('function expandCitationIndexes');
const end = app.indexOf('function readStoredJson');
if (start < 0 || end < 0) throw new Error('function slice not found');
function escapeHtml(value) {
  return String(value || '').replace(/[&<>'"]/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
}
eval(app.slice(start, end));
const node = { dataset: { references: JSON.stringify([
  {
    index: 3,
    source: 'agent_knowledge/quarterly_competitor_metrics_2026-06-18/quarterly_metrics_summary.md · 片段 1',
    links: [{
      label: 'agent_knowledge/quarterly_competitor_metrics_2026-06-18/quarterly_metrics_summary.md · 片段 1',
      url: '/references/agent_knowledge/quarterly_competitor_metrics_2026-06-18/quarterly_metrics_summary.md'
    }]
  }
]) } };
const rendered = renderCitationMarkers('覆盖 Q2 2021 至 Q1 2026。[来源：quarterly_metrics_summary.md]', node);
if (!rendered.includes('citation-marker') || rendered.includes('[来源')) {
  throw new Error(rendered);
}
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=web_app.ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_reference_merge_reassigns_duplicate_indexes(self) -> None:
        script = r"""
const fs = require('fs');
const app = fs.readFileSync('web/static/app.js', 'utf8');
const start = app.indexOf('function readStoredJson');
const end = app.indexOf('function hideChatApproval');
if (start < 0 || end < 0) throw new Error('function slice not found');
function appendRagProcess() {}
eval(app.slice(start, end));
const node = { dataset: {} };
mergeCitationMeta(node, {
  type: 'meta',
  references: [
    { index: 1, source: '云厂商数据', links: [{ label: '云厂商数据', url: '/references/cloud.md' }] },
    { index: 2, source: '宏观数据', links: [{ label: '宏观数据', url: '/references/macro.md' }] },
    { index: 3, source: '爬虫运行日志索引', links: [{ label: '爬虫运行日志索引', url: '/references/crawl.md' }] },
    { index: 4, source: '竞对数据', links: [{ label: '竞对数据', url: '/references/competitor.md' }] }
  ],
  links: []
});
mergeCitationMeta(node, {
  type: 'meta',
  references: [
    { index: 1, source: 'agent_knowledge/quarterly_metrics_summary.md · 片段 1', links: [{ label: 'agent_knowledge/quarterly_metrics_summary.md · 片段 1', url: '/references/agent_knowledge/quarterly_metrics_summary.md' }] },
    { index: 2, source: 'agent_knowledge/quarterly_metrics.csv · 片段 2', links: [{ label: 'agent_knowledge/quarterly_metrics.csv · 片段 2', url: '/references/agent_knowledge/quarterly_metrics.csv' }] }
  ],
  links: []
});
const refs = JSON.parse(node.dataset.references);
const indexes = refs.map((ref) => ref.index);
if (new Set(indexes).size !== indexes.length || indexes.join(',') !== '1,2,3,4,5,6') {
  throw new Error(JSON.stringify(refs));
}
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=web_app.ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


class WebAppCurationCommandTests(unittest.TestCase):
    def _captured_refresh_command(self, env: dict[str, str] | None = None) -> list[str]:
        captured: dict[str, list[str]] = {}

        def fake_run(command, **_kwargs):
            captured["command"] = command
            return mock.Mock(returncode=0, stdout="", stderr="")

        with (
            mock.patch.dict(os.environ, env or {}, clear=False),
            mock.patch("subprocess.run", side_effect=fake_run),
            mock.patch("web_app.build_company_metrics_payload", return_value={"summary": {}}),
        ):
            web_app.run_company_metrics_refresh()
        return captured["command"]

    def test_company_metrics_refresh_enables_full_online_search_verification_by_default(self) -> None:
        command = self._captured_refresh_command()
        self.assertIn("--search-verify-workers", command)
        self.assertIn("--search-verify-online", command)
        self.assertIn("--search-verify-online-limit", command)
        self.assertEqual(command[command.index("--search-verify-online-limit") + 1], "0")

    def test_company_metrics_refresh_can_disable_online_search_verification(self) -> None:
        command = self._captured_refresh_command({"CMHK_SEARCH_VERIFY_ONLINE": "0"})
        self.assertIn("--search-verify-workers", command)
        self.assertNotIn("--search-verify-online", command)


class AgentWebSearchToggleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._real_follow_up_generator = agent._ensure_ai_follow_up_suggestions
        self._follow_up_patcher = mock.patch(
            "agent._ensure_ai_follow_up_suggestions",
            return_value=(
                ["继续核对哪个具体结论？", "还需要补充哪些来源？", "下一步要分析哪个主体？"],
                {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
                "answer",
            ),
        )
        self._follow_up_patcher.start()

    def tearDown(self) -> None:
        self._follow_up_patcher.stop()

    def test_trend_retrieval_exposes_the_full_quarterly_series(self) -> None:
        chunks = rag_llm._quarterly_exact_metric_chunks(
            "看看中国移动近年的收入趋势",
            dataset_ids={"quarterly_competitor_metrics_2026-06-18"},
        )

        revenue = next(
            chunk for chunk in chunks
            if "subject=中国移动" in chunk["text"] and "metric_key=revenue" in chunk["text"]
        )
        self.assertIn("coverage=Q1 2016 至 Q1 2026", revenue["text"])
        self.assertIn("points=41", revenue["text"])
        self.assertIn("Q1 2016=177504", revenue["text"])
        self.assertIn("Q1 2026=266478", revenue["text"])

    def test_chinese_rag_tokens_match_meaningful_substrings(self) -> None:
        self.assertIn("套餐", rag_llm._tokens("套餐名称"))
        self.assertIn("月费", rag_llm._tokens("最新月费_HKD"))
        self.assertTrue(rag_llm._tokens("香港宽频套餐") & rag_llm._tokens("宽频套餐名称"))

    def test_broad_tariff_query_returns_compact_cross_brand_current_data(self) -> None:
        chunks = rag_llm.retrieve_context(
            "香港竞争对手移动宽频套餐资费月费合约",
            limit=6,
            dataset_ids={"competitor_product_tariffs"},
        )
        tariff_chunks = [
            chunk for chunk in chunks
            if chunk["source"].endswith("product_tariffs_formal_agent_records.csv")
            and "产品资费结构化检索结果" in chunk["text"]
        ]
        text = "\n".join(chunk["text"] for chunk in tariff_chunks)

        self.assertGreaterEqual(len(tariff_chunks), 3)
        overview = next(
            chunk["text"]
            for chunk in tariff_chunks
            if "跨品牌当前正式套餐总览" in chunk["text"]
        )
        self.assertIn("mobile=[", overview)
        self.assertIn("broadband=[", overview)
        for brand in ["HKBN", "3HK / Hutchison", "SmarTone", "i-CABLE", "csl", "1O1O"]:
            self.assertIn(f"brand={brand}", overview)
        match = re.search(r"matched_records=(\d+)", text)
        self.assertIsNotNone(match)
        self.assertGreater(int(match.group(1)), 100)
        brand_match = re.search(r"matched_brands=(\d+)", text)
        self.assertIsNotNone(brand_match)
        self.assertGreaterEqual(int(brand_match.group(1)), 8)
        self.assertIn("query_scope=cross_brand", text)
        self.assertIn("数据集全局覆盖锚点", text)
        for brand in ["HKBN", "3HK / Hutchison", "SmarTone", "i-CABLE", "csl", "1O1O"]:
            self.assertIn(f"brand={brand}", text)
        self.assertNotIn("record_class=source_gap", text)
        self.assertNotIn("single_source_needs_review", text)

        package = rag_llm.build_context_package(tariff_chunks, token_budget=3200)
        packaged_text = package["context"]
        self.assertLessEqual(package["audit"]["skipped_chunks"], 1)
        self.assertIn("跨品牌当前正式套餐总览", packaged_text)
        self.assertIn("brand=HKBN", packaged_text)
        self.assertIn("brand=i-CABLE", packaged_text)

    def test_specific_brand_tariff_query_keeps_multiple_formal_rows(self) -> None:
        chunks = rag_llm._product_tariff_exact_chunks(
            "请对比 i-CABLE 当前宽频套餐的月费、速度和合约",
            dataset_ids={"competitor_product_tariffs"},
        )
        text = "\n".join(chunk["text"] for chunk in chunks)

        self.assertEqual(len(chunks), 1)
        self.assertIn("matched_brands=1", text)
        self.assertIn("query_scope=brand_subset", text)
        self.assertRegex(text, r"dataset_total_formal_records=\d+")
        self.assertRegex(text, r"dataset_current_formal_records=\d+")
        self.assertRegex(text, r"dataset_total_brands=\d+")
        self.assertIn("dataset_brands=", text)
        self.assertIn("不得因本次子集未出现某品牌，就推断整个数据库没有该品牌", text)
        self.assertIn("brand=i-CABLE", text)
        self.assertGreaterEqual(text.count("正式套餐："), 3)
        self.assertNotIn("brand=HKBN", text)

    def test_named_brand_tariff_comparison_starts_with_complete_overview(self) -> None:
        chunks = rag_llm._product_tariff_exact_chunks(
            "对比3HK、SmarTone、HKBN和i-CABLE的移动与宽频套餐",
            dataset_ids={"competitor_product_tariffs"},
        )
        overview = chunks[0]["text"]

        self.assertIn("跨品牌当前正式套餐总览", overview)
        self.assertIn("query_scope=named_brand_comparison", overview)
        for brand in ["3HK / Hutchison", "SmarTone", "HKBN", "i-CABLE"]:
            self.assertIn(f"brand={brand}", overview)
        self.assertIn("mobile=[", overview)
        self.assertIn("broadband=[", overview)

    def test_full_database_tariff_request_overrides_prior_brand_mention(self) -> None:
        chunks = rag_llm._product_tariff_exact_chunks(
            "现在回到全库：香港主要竞对的移动和宽频套餐分别有哪些？"
            "不要把上一轮 i-CABLE 单品牌结果当成全库",
            dataset_ids={"competitor_product_tariffs"},
        )
        overview = chunks[0]["text"]

        self.assertIn("query_scope=cross_brand", overview)
        self.assertIn("brand=3HK / Hutchison", overview)
        self.assertIn("brand=SmarTone", overview)
        self.assertIn("brand=NETVIGATOR", overview)
        self.assertIn("brand=i-CABLE", overview)

    def test_historical_tariff_trend_exposes_full_visible_year_ranges(self) -> None:
        chunks = rag_llm._product_tariff_exact_chunks(
            "查看 HKBN 历史宽频套餐资费趋势",
            dataset_ids={"competitor_product_tariffs"},
        )
        text = "\n".join(chunk["text"] for chunk in chunks)

        self.assertIn("period_coverage=2016至current", text)
        self.assertIn("annual_monthly_ranges=", text)
        for year in ["2016", "2017", "2019", "2023", "2024", "2025", "2026"]:
            self.assertRegex(text, rf"(?:annual_monthly_ranges=.*|; ){year}:HK\$")

    def test_tariff_gap_question_stays_on_gap_retrieval_path(self) -> None:
        chunks = rag_llm._product_tariff_exact_chunks(
            "为什么没有 HKBN 某套餐？请检查来源缺口和待复核记录",
            dataset_ids={"competitor_product_tariffs"},
        )

        self.assertEqual(chunks, [])

    def test_frontend_deduplicates_a_chart_repeated_in_the_final_answer(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        self.assertIn("function dedupeAssistantChartImages(node)", app)
        self.assertIn('body.querySelectorAll(".chart-result-block[data-chart-url]")', app)
        self.assertIn('image.closest(".chat-image-wrapper")?.remove()', app)
        self.assertGreaterEqual(app.count("dedupeAssistantChartImages("), 4)

    def test_plain_search_question_is_not_intercepted_when_web_toggle_is_off(self) -> None:
        self.assertIsNone(web_app.check_local_action("搜一下移动和联通的收入趋势"))
        self.assertIsNone(web_app.check_local_action("请生成周报"))
        self.assertIsNone(web_app.check_local_action("请输出 AWS revenue 未来4个季度预测表"))

    def test_operational_decisions_are_exposed_as_agent_tools(self) -> None:
        tool_names = {tool.name for tool in agent._agent_tools(allow_web_search=False)}

        self.assertIn("trigger_report_generation", tool_names)
        self.assertIn("trigger_carrier_performance_report_generation", tool_names)
        self.assertIn("trigger_full_crawl", tool_names)
        self.assertIn("list_report_outputs", tool_names)
        self.assertIn("get_crawl_settings_summary", tool_names)
        self.assertIn("list_crawl_runs", tool_names)

    def test_web_toggle_enables_capability_without_injecting_tool_workflow(self) -> None:
        captured: dict[str, str] = {}

        class FakeAgent:
            def stream(self, inputs, stream_mode=None):
                captured["message"] = inputs["messages"][0][1]
                captured["stream_mode"] = stream_mode
                return iter(())

        with mock.patch("agent.get_agent", return_value=FakeAgent()):
            events = list(agent.stream_agent("搜一下中国移动最新收入", force_web_search=True))

        self.assertEqual(events[-1], {"type": "done"})
        self.assertEqual(events[-2]["type"], "run_summary")
        self.assertEqual(events[-2]["status"], "ok")
        self.assertEqual(captured["message"], "搜一下中国移动最新收入")
        self.assertNotIn("必须调用", captured["message"])
        self.assertNotIn("两者缺一不可", captured["message"])
        self.assertEqual(captured["stream_mode"], "messages")

    def test_web_enabled_system_prompt_requests_web_and_local_data_verification(self) -> None:
        captured: dict[str, object] = {}

        class FakeLLM:
            def __init__(self, **kwargs):
                captured["llm_kwargs"] = kwargs

        def fake_create_react_agent(_llm, tools, prompt):
            captured["tools"] = {tool.name for tool in tools}
            captured["prompt"] = str(prompt)
            return object()

        with (
            mock.patch("agent.StableAgentChatDeepSeek", FakeLLM),
            mock.patch("agent.create_react_agent", side_effect=fake_create_react_agent),
        ):
            agent.get_agent(
                allow_web_search=True,
                user_message="请比较中国移动和中国联通的最新收入。",
                runtime_context={
                    "current_time": "2026-07-27T18:23:45+08:00",
                    "timezone": "HKT",
                    "utc_offset": "+0800",
                },
            )

        prompt = str(captured["prompt"])
        self.assertIn("自主选择", prompt)
        self.assertIn("联网搜索已开启", prompt)
        self.assertIn("search_local_reports 会同时返回本地和联网资料", prompt)
        self.assertIn("由你判断查询方式与次数", prompt)
        self.assertIn("指出冲突、未命中和时效差异", prompt)
        self.assertIn("根据工具描述自主规划", prompt)
        self.assertIn("不套用上一轮的结构", prompt)
        self.assertIn("本轮消息准确发送时间: 2026-07-27T18:23:45+08:00", prompt)
        self.assertIn("后端在每条消息到达时重新计算", prompt)
        self.assertNotIn("web_search", captured["tools"])
        self.assertIn("search_local_reports", captured["tools"])

    def test_web_search_filters_poisoned_results_and_supplies_official_entrypoints(self) -> None:
        poisoned = [
            {
                "title": "Омода С7 2025 года",
                "url": "https://www.drom.ru/reviews/omoda/c7/1461493/",
                "snippet": "Автомобиль 2025 2026.",
            },
            {
                "title": "Google",
                "url": "https://www.google.com/",
                "snippet": "Search.",
            },
            {
                "title": "成人视频",
                "url": "https://example.invalid/adult",
                "snippet": "OnlyFans.",
            },
        ]
        with (
            mock.patch("agent._search_with_searxng", return_value=poisoned),
            mock.patch("agent._read_webpage_text") as read_webpage,
        ):
            result = agent.web_search.invoke({
                "query": "香港 5G 频谱 政策 事件 时间线 2024 2025 2026",
                "max_results": 5,
            })

        self.assertIn("ofca.gov.hk", result)
        self.assertIn("香港通讯及频谱政策里程碑", result)
        self.assertIn("已过滤 3 个", result)
        read_webpage.assert_not_called()
        self.assertNotIn("drom.ru", result)
        self.assertNotIn("OnlyFans", result)
        self.assertNotIn("www.google.com", result)

    def test_local_data_search_returns_sources_without_hidden_original_read(self) -> None:
        chunks = [
            {
                "source": "agent_knowledge/cmhk_macro_policy_2026-06-19/manifest.json",
                "text": "宏观政策数据集。",
                "links": [],
            },
            {
                "source": "agent_knowledge/cmhk_macro_policy_2026-06-19/macro_policy_metrics.csv",
                "text": "5G频谱政策事件记录。",
                "links": [],
            },
        ]
        request_token = agent.CURRENT_USER_REQUEST.set("梳理香港5G频谱政策时间线和影响")
        try:
            with (
                mock.patch("agent.retrieve_context", return_value=chunks) as retrieve,
                mock.patch(
                    "agent.build_context_package",
                    return_value={"chunks": chunks, "audit": {"retained_chunks": 2}},
                ),
                mock.patch("agent.retrieval_quality", return_value={"status": "ok"}),
                mock.patch("agent._read_local_reference_text") as read_reference,
            ):
                result = agent.search_local_reports.invoke({"query": "香港5G频谱政策"})
        finally:
            agent.CURRENT_USER_REQUEST.reset(request_token)

        self.assertIn("macro_policy_metrics.csv", result)
        retrieval_query = retrieve.call_args.args[0]
        self.assertIn("香港5G频谱政策", retrieval_query)
        self.assertNotIn("梳理香港5G频谱政策时间线和影响", retrieval_query)
        read_reference.assert_not_called()

    def test_local_search_tool_returns_local_and_web_evidence_when_web_is_enabled(self) -> None:
        local_result = (
            "[来源 1: 本地套餐库]\n本地证据"
            '\n<metadata>{"type":"meta","sources":["本地套餐库"],"links":[],"references":'
            '[{"index":1,"source":"本地套餐库","links":[]}]}</metadata>'
        )
        web_result = (
            "[来源 6: 官方网页]\n联网证据"
            '\n<metadata>{"type":"meta","provider":"test","sources":["官方网页"],"links":[],"references":'
            '[{"index":6,"source":"官方网页","links":[]}]}</metadata>'
        )
        web_token = agent.WEB_SEARCH_AVAILABLE.set(True)
        try:
            with (
                mock.patch("agent._search_local_reports_only", return_value=local_result) as local_invoke,
                mock.patch("agent._web_search_only", return_value=web_result) as web_invoke,
            ):
                result = agent.search_local_reports.invoke({
                    "query": "SmarTone HGC 稳定性",
                    "max_results": 25,
                })
        finally:
            agent.WEB_SEARCH_AVAILABLE.reset(web_token)

        self.assertIn("【本地资料】", result)
        self.assertIn("【联网资料】", result)
        self.assertIn("本地证据", result)
        self.assertIn("联网证据", result)
        self.assertEqual(result.count("<metadata>"), 1)
        local_invoke.assert_called_once_with("SmarTone HGC 稳定性", 25)
        web_invoke.assert_called_once_with("SmarTone HGC 稳定性", 25)

    def test_generic_web_search_returns_no_sources_when_every_result_is_irrelevant(self) -> None:
        poisoned = [
            {
                "title": "Completely unrelated car review",
                "url": "https://example.com/cars/1",
                "snippet": "A vehicle review with no matching topic.",
            }
        ]
        with mock.patch("agent._search_with_searxng", return_value=poisoned):
            result = agent.web_search.invoke({
                "query": "AWS quarterly revenue operating margin",
                "max_results": 5,
            })

        self.assertIn("未返回与查询相关的可用网页结果", result)
        self.assertIn("已过滤 1 个", result)
        self.assertNotIn("[来源", result)

    def test_data_trend_and_multi_group_queries_receive_chart_tool(self) -> None:
        trend_tools = {
            tool.name
            for tool in agent._agent_tools(
                allow_web_search=True,
                user_message="请分析中国移动过去五年的收入趋势。",
            )
        }
        comparison_tools = {
            tool.name
            for tool in agent._agent_tools(
                allow_web_search=True,
                user_message="请比较中国移动、中国联通和中国电信的收入数据。",
            )
        }

        self.assertIn("render_python_chart", trend_tools)
        self.assertIn("render_python_chart", comparison_tools)

    def test_system_prompt_exposes_chart_capability_without_mandate(self) -> None:
        captured: dict[str, object] = {}

        class FakeLLM:
            def __init__(self, **kwargs):
                captured["llm_kwargs"] = kwargs

        def fake_create_react_agent(_llm, tools, prompt):
            captured["prompt"] = str(prompt)
            captured["tools"] = {tool.name for tool in tools}
            return object()

        with (
            mock.patch("agent.StableAgentChatDeepSeek", FakeLLM),
            mock.patch("agent.create_react_agent", side_effect=fake_create_react_agent),
        ):
            agent.get_agent(
                allow_web_search=True,
                user_message="请比较三家运营商过去五年的收入趋势。",
            )

        prompt = str(captured["prompt"])
        self.assertIn("render_python_chart", captured["tools"])
        self.assertNotIn("数据趋势与多组数据必须画图", prompt)
        self.assertNotIn("不能只给文字或表格", prompt)

    def test_without_force_web_search_hides_web_tools_without_toggle_notice(self) -> None:
        captured: dict[str, object] = {}

        class FakeAgent:
            def stream(self, inputs, stream_mode=None):
                captured["message"] = inputs["messages"][0][1]
                return iter(())

        def fake_get_agent(*, thinking_enabled=False, allow_web_search=True):
            captured["allow_web_search"] = allow_web_search
            return FakeAgent()

        with mock.patch("agent.get_agent", side_effect=fake_get_agent):
            list(agent.stream_agent("搜一下中国移动最新收入", force_web_search=False))

        self.assertFalse(captured["allow_web_search"])
        self.assertIn("搜一下中国移动最新收入", captured["message"])
        self.assertNotIn("联网搜索", str(captured["message"]))

    def test_disabled_web_search_removes_both_web_tools(self) -> None:
        tool_names = {tool.name for tool in agent._agent_tools(allow_web_search=False)}

        self.assertNotIn("web_search", tool_names)
        self.assertNotIn("read_webpage", tool_names)

    def test_agent_model_uses_non_streaming_gateway_and_targeted_tools(self) -> None:
        captured: dict[str, object] = {}

        class FakeLLM:
            def __init__(self, **kwargs):
                captured["llm_kwargs"] = kwargs

        def fake_create_react_agent(_llm, tools, prompt):
            captured["tools"] = {tool.name for tool in tools}
            captured["prompt"] = prompt
            return object()

        with (
            mock.patch("agent.StableAgentChatDeepSeek", FakeLLM),
            mock.patch("agent.create_react_agent", side_effect=fake_create_react_agent),
        ):
            agent.get_agent(
                allow_web_search=False,
                user_message="请查看当前系统状态并告诉我最近爬取成功和失败数量。",
            )

        self.assertTrue(captured["llm_kwargs"]["disable_streaming"])
        self.assertEqual(captured["llm_kwargs"]["temperature"], 0.1)
        self.assertEqual(captured["llm_kwargs"]["max_tokens"], 4096)
        self.assertIn("search_chat_history", captured["tools"])
        self.assertIn("get_system_status", captured["tools"])
        self.assertIn("search_local_reports", captured["tools"])
        self.assertIn("render_python_chart", captured["tools"])
        self.assertNotIn("web_search", captured["tools"])
        self.assertIn("理解用户意图，自主选择", captured["prompt"])

    def test_agent_tools_are_available_without_keyword_routing(self) -> None:
        default_names = {tool.name for tool in agent._agent_tools(allow_web_search=True)}
        targeted_names = {
            tool.name
            for tool in agent._agent_tools(
                allow_web_search=False,
                user_message="请生成周报，再查看系统状态和最近爬虫日志。",
            )
        }

        self.assertIn("search_local_reports", default_names)
        self.assertNotIn("web_search", default_names)
        self.assertIn("trigger_report_generation", targeted_names)
        self.assertIn("get_system_status", targeted_names)
        self.assertIn("list_crawl_runs", targeted_names)
        self.assertIn("render_python_chart", targeted_names)

    def test_gateway_corruption_detector_catches_known_failure_shapes(self) -> None:
        samples = [
            "<｜DSML｜tool_calls><｜DSML｜invoke name=\"get_system_status\">",
            "<search_local_reports>\n<query>本周竞对</query>\n<max_results>5</max_results>\n</search_local_reports>",
            "import pdb;pdb.set_trace(); <|begin_of_file|> Admin override restarting cleanly",
            "get_system_status() " * 40,
            "[1]" * 40,
            "¹²³⁴⁵⁶⁷⁸⁹" * 8,
            "正常中文 Русский 한국어 日本語 mixed corruption",
        ]

        for sample in samples:
            self.assertTrue(agent._looks_like_unstable_model_text(sample), sample[:80])
        self.assertFalse(agent._looks_like_unstable_model_text("这是清晰、正常的中文分析结论。"))

    def test_incomplete_answer_detector_catches_mid_sentence_provider_stops(self) -> None:
        incomplete = (
            "如需获取本周竞对动态，建议：\n"
            "- 明确指定竞对名称（如中国移动、华为云、AWS 等）或动态类型（如新品发布、财报预告、监管事件）；"
        )
        self.assertTrue(agent._looks_like_incomplete_model_answer(incomplete))
        self.assertTrue(agent._looks_like_incomplete_model_answer("这是完整句子。", "length"))
        self.assertTrue(agent._looks_like_incomplete_model_answer("分析需要结合"))
        self.assertTrue(
            agent._looks_like_incomplete_model_answer(
                '请进一步说明，\n<suggestions>["查看本周动态", "对比战略路线图"'
            )
        )
        self.assertTrue(
            agent._looks_like_incomplete_model_answer(
                '明确主体后，\n<suggestions>["中国移动", "AWS", "华为云"]'
            )
        )
        self.assertTrue(
            agent._looks_like_incomplete_model_answer(
                "这是完整正文。\n<引用来源>[来源 1] 本地资料"
            )
        )
        self.assertFalse(
            agent._looks_like_incomplete_model_answer(
                "这是语义完整的回答，只是末尾多了一个 Markdown 粗体标记。**"
            )
        )
        self.assertFalse(agent._looks_like_incomplete_model_answer("这是清晰、完整的中文分析结论。"))
        self.assertFalse(
            agent._looks_like_incomplete_model_answer(
                "结论已经完整。\n<suggestions>继续分析|查看来源|对比趋势</suggestions>"
            )
        )

    def test_complete_prose_does_not_require_ui_suggestion_footer(self) -> None:
        seemingly_finished = (
            "这段回答虽然以句号结束，但它只写完了用户要求的第一部分。"
            "模型有时会在网关或上下文限制下提前停止，finish_reason 仍可能被记录成 stop。"
            "因此不能只根据最后一个标点判断整份回答是否已经完成，还必须观察应用约定的完成标记。"
            "这里再补足一些正文长度，用来模拟真实的长回答在某一段末尾突然结束。"
        )

        self.assertFalse(agent._looks_like_incomplete_model_answer(seemingly_finished))
        self.assertFalse(agent._looks_like_incomplete_model_answer("4。"))

    def test_follow_up_parser_accepts_model_format_variants(self) -> None:
        self.assertEqual(
            agent._extract_follow_up_suggestions(
                "<suggestions><suggestion>第一问？</suggestion>"
                "<suggestion>第二问？</suggestion><suggestion>第三问？</suggestion></suggestions>"
            ),
            ["第一问？", "第二问？", "第三问？"],
        )
        self.assertEqual(
            agent._extract_follow_up_suggestions(
                "<suggestions>\n- 甲问题？\n- 乙问题？\n- 丙问题？\n</suggestions>"
            ),
            ["甲问题？", "乙问题？", "丙问题？"],
        )

    def test_follow_up_parser_rejects_answer_fragments_and_metric_values(self) -> None:
        self.assertEqual(
            agent._normalize_follow_up_suggestions(
                [
                    "*2016年**：全年收入呈现季节性波动。",
                    "Q1: 1,775.04 亿元人民币 [来源 1]",
                    "Q2: 1,928.47 亿元人民币 [来源 2]",
                ]
            ),
            [],
        )

    def test_follow_up_parser_rejects_explanatory_paragraphs_from_answer(self) -> None:
        self.assertEqual(
            agent._normalize_follow_up_suggestions(
                [
                    "数据来源与核验：以上数据优先采用官方披露值，并已与标准化表进行交叉核验。",
                    "数据完整性：当前数据覆盖了从2016年Q1至2026年Q1的完整季度序列，共41个数据点。",
                    "分析局限性：本次分析仅基于中国移动的总体营业收入，如需深入洞察则要继续查询。",
                ]
            ),
            [],
        )
        self.assertEqual(
            agent._normalize_follow_up_suggestions(
                [
                    "中国移动收入增长的主要驱动因素是什么？",
                    "对比中国移动和中国联通的收入趋势",
                    "请分析5G发展对收入的影响",
                ]
            ),
            [
                "中国移动收入增长的主要驱动因素是什么？",
                "对比中国移动和中国联通的收入趋势",
                "请分析5G发展对收入的影响",
            ],
        )

    def test_conversation_history_includes_each_messages_saved_time(self) -> None:
        context = agent._format_conversation_history(
            [
                {
                    "role": "user",
                    "content": "上一条用户消息",
                    "createdAt": "2026-07-27T10:00:00.000Z",
                },
                {
                    "role": "assistant",
                    "content": "上一条AI回答",
                    "createdAt": "2026-07-27T10:00:01.000Z",
                    "completedAt": "2026-07-27T10:00:05.000Z",
                },
            ]
        )

        self.assertIn("用户 [发送时间 2026-07-27T10:00:00.000Z]", context)
        self.assertIn("AI [发送时间 2026-07-27T10:00:01.000Z; 完成时间 2026-07-27T10:00:05.000Z]", context)

    def test_frontend_sends_saved_message_times_with_conversation_history(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        self.assertIn('createdAt: item.createdAt || ""', app)
        self.assertIn('completedAt: item.completedAt || ""', app)

    def test_existing_three_ai_suggestions_do_not_add_an_extra_model_call(self) -> None:
        answer = '完整回答。\n<suggestions>["具体问题一？", "具体问题二？", "具体问题三？"]</suggestions>'
        with mock.patch("agent.ChatDeepSeek", side_effect=AssertionError("不应额外调用模型")):
            items, usage, source = self._real_follow_up_generator("原问题", answer)

        self.assertEqual(items, ["具体问题一？", "具体问题二？", "具体问题三？"])
        self.assertEqual(usage["totalTokens"], 0)
        self.assertEqual(source, "answer")

    def test_assistant_centered_or_internal_process_suggestions_are_rejected(self) -> None:
        bad_answer = (
            "已完成当前回答。"
            '<suggestions>["是否需要我读取该数据集中的具体文件？",'
            '"您希望重点了解哪一类政策？",'
            '"是否需要结合CMHK经营数据继续分析？"]</suggestions>'
        )
        response = agent.AIMessage(
            content=(
                '["梳理香港5G频谱政策时间线并标注来源",'
                '"对比各频段的分配时间与牌照期限",'
                '"评估频谱政策对CMHK网络投资的影响"]'
            )
        )
        model = mock.Mock()
        model.invoke.return_value = response
        with (
            mock.patch("agent.ChatDeepSeek", return_value=model),
            mock.patch("agent.load_ai_config", return_value={
                "model": "deepseek-v4",
                "api_key": "test",
                "base_url": "http://internal/v1",
                "extra_parameters": {},
            }),
        ):
            items, _, source = self._real_follow_up_generator(
                "分析香港5G频谱政策时间线",
                bad_answer,
            )

        self.assertEqual(source, "dedicated_model")
        self.assertEqual(len(items), 3)
        self.assertFalse(any("是否需要我" in item or "您希望" in item for item in items))
        prompt = str(model.invoke.call_args.args[0][0].content)
        self.assertIn("用户可以直接点击继续对话", prompt)
        self.assertIn("自主生成3个自然", prompt)

    def test_missing_or_placeholder_suggestions_are_generated_by_dedicated_model(self) -> None:
        response = agent.AIMessage(
            content='["CMHK应优先验证哪个场景？", "需要补充哪些香港数据？", "如何安排下一步试点？"]',
            usage_metadata={"input_tokens": 20, "output_tokens": 30, "total_tokens": 50},
        )
        model = mock.Mock()
        model.invoke.return_value = response
        with (
            mock.patch("agent.ChatDeepSeek", return_value=model),
            mock.patch("agent.load_ai_config", return_value={
                "model": "MiniMax-M2.1",
                "api_key": "test",
                "base_url": "http://internal/v1",
                "extra_parameters": {},
            }),
        ):
            items, usage, source = self._real_follow_up_generator(
                "分析5G-A与AI融合",
                "完整回答。\n<suggestions>[]</suggestions>",
            )

        self.assertEqual(len(items), 3)
        self.assertEqual(usage["totalTokens"], 50)
        self.assertEqual(source, "dedicated_model")

    def test_stream_emits_exactly_three_structured_suggestions_before_summary(self) -> None:
        class FakeAgent:
            def stream(self, inputs, stream_mode=None):
                yield agent.AIMessage(
                    content='完整回答。\n<suggestions>["问题一？", "问题二？", "问题三？"]</suggestions>'
                ), {}

        with mock.patch("agent.get_agent", return_value=FakeAgent()):
            events = list(agent.stream_agent("请回答"))

        suggestion_event = next(event for event in events if event.get("type") == "suggestions")
        self.assertEqual(len(suggestion_event["items"]), 3)
        self.assertLess(events.index(suggestion_event), next(i for i, event in enumerate(events) if event.get("type") == "run_summary"))
        self.assertEqual(events[-1], {"type": "done"})

    def test_application_does_not_install_explicit_structure_gate(self) -> None:
        self.assertFalse(hasattr(agent, "_answer_satisfies_explicit_structure"))

    def test_chat_stream_requires_explicit_done_event_before_finalizing(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        send_start = app.index("async function sendChat")
        send_end = app.index("els.generateButtons.forEach", send_start)
        send_chat = app[send_start:send_end]

        guard = send_chat.index("if (!isDone)")
        finalize = send_chat.index("collapseLatestModelReasoning(assistantNode);", guard)
        self.assertLess(guard, finalize)
        self.assertIn('streamError.code = "STREAM_INCOMPLETE";', send_chat)
        self.assertIn("连接意外中断，本次回答未完成，请重新发送。", send_chat)

    def test_model_transport_failure_uses_application_fallback(self) -> None:
        primary_error = RuntimeError(
            "Error code: 500 - InternalServerError: Cannot connect to host 10.0.62.169:30001"
        )
        fallback_message = agent.AIMessage(content="备用模型已经完整回答。")
        fallback_result = mock.Mock()
        fallback_result.generations = [mock.Mock(message=fallback_message, generation_info={"finish_reason": "stop"})]
        config = agent.load_ai_config()
        model = agent.StableAgentChatDeepSeek(
            model="deepseek-r1-0528-PPU",
            api_key=config.get("api_key", ""),
            api_base=config.get("base_url", ""),
            disable_streaming=True,
            max_retries=1,
        )

        with mock.patch.object(agent.ChatDeepSeek, "_generate", side_effect=[primary_error, fallback_result]) as generate:
            result = model._generate([agent.HumanMessage(content="请完整回答")])

        self.assertIs(result, fallback_result)
        self.assertEqual(generate.call_count, 2)
        self.assertIn("已自动切换至 deepseek-v4", fallback_message.additional_kwargs["reasoning_content"])

    def test_model_transport_fallbacks_only_use_team_allowed_models(self) -> None:
        fallbacks = agent.StableAgentChatDeepSeek.model_fields[
            "transport_fallback_models"
        ].default
        self.assertEqual(
            fallbacks,
            ("deepseek-v4", "DeepSeek-V4-Pro", "GLM"),
        )
        self.assertNotIn(
            "deepseek-r1-0528",
            fallbacks,
        )

    def test_model_retries_when_suggestion_footer_is_cut_off(self) -> None:
        incomplete_message = agent.AIMessage(
            content='请进一步说明，\n<suggestions>["查看本周动态", "对比路线图"'
        )
        complete_message = agent.AIMessage(
            content='请告诉我希望查看哪家企业的战略路线图。\n<suggestions>["中国移动", "AWS", "华为云"]</suggestions>'
        )
        incomplete_result = mock.Mock(
            generations=[mock.Mock(message=incomplete_message, generation_info={"finish_reason": "stop"})]
        )
        complete_result = mock.Mock(
            generations=[mock.Mock(message=complete_message, generation_info={"finish_reason": "stop"})]
        )
        config = agent.load_ai_config()
        model = agent.StableAgentChatDeepSeek(
            model="deepseek-v4",
            api_key=config.get("api_key", ""),
            api_base=config.get("base_url", ""),
            disable_streaming=True,
            max_retries=1,
        )

        with mock.patch.object(
            agent.ChatDeepSeek,
            "_generate",
            side_effect=[incomplete_result, complete_result],
        ) as generate:
            result = model._generate([agent.HumanMessage(content="请完整回答")])

        self.assertIs(result, complete_result)
        self.assertEqual(generate.call_count, 2)

    def test_search_marker_does_not_force_an_original_read(self) -> None:
        incomplete_message = agent.AIMessage(content="")
        tool_message = agent.AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "read_webpage",
                    "args": {"url": "https://www.ofca.gov.hk/example"},
                    "id": "call-read-webpage",
                    "type": "tool_call",
                }
            ],
        )
        incomplete_result = mock.Mock(
            generations=[mock.Mock(message=incomplete_message, generation_info={"finish_reason": "stop"})]
        )
        tool_result = mock.Mock(
            generations=[mock.Mock(message=tool_message, generation_info={"finish_reason": "tool_calls"})]
        )
        config = agent.load_ai_config()
        model = agent.StableAgentChatDeepSeek(
            model="deepseek-v4",
            api_key=config.get("api_key", ""),
            api_base=config.get("base_url", ""),
            disable_streaming=True,
            max_retries=1,
        )
        messages = [
            agent.HumanMessage(content="请核验香港5G频谱政策。"),
            agent.ToolMessage(
                content=(
                    "搜索摘要。\n\n【强制下一步】本轮问题要求官方事实核验，"
                    "请调用 `read_webpage` 读取官网原文。"
                ),
                tool_call_id="call-search",
                name="web_search",
            ),
        ]
        tools = [{"type": "function", "function": {"name": "read_webpage", "parameters": {"type": "object"}}}]

        with mock.patch.object(
            agent.ChatDeepSeek,
            "_generate",
            side_effect=[incomplete_result, tool_result],
        ) as generate:
            result = model._generate(messages, tools=tools)

        self.assertIs(result, incomplete_result)
        self.assertEqual(generate.call_count, 1)

    def test_trend_answer_is_not_blocked_when_agent_chooses_text(self) -> None:
        text_only = agent.AIMessage(
            content=(
                "中国移动收入长期向上，最近增速有所放缓。"
                '<suggestions>["查看利润趋势", "对比中国电信", "查看收入构成"]</suggestions>'
            )
        )
        chart_call = agent.AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "render_python_chart",
                    "args": {
                        "chart_spec": (
                            '{"type":"line","title":"中国移动收入趋势","unit":"亿元",'
                            '"x":["2023","2024"],"series":[{"name":"收入","data":[10093,10408]}]}'
                        )
                    },
                    "id": "call-chart",
                    "type": "tool_call",
                }
            ],
        )
        text_result = mock.Mock(
            generations=[mock.Mock(message=text_only, generation_info={"finish_reason": "stop"})]
        )
        chart_result = mock.Mock(
            generations=[mock.Mock(message=chart_call, generation_info={"finish_reason": "tool_calls"})]
        )
        config = agent.load_ai_config()
        model = agent.StableAgentChatDeepSeek(
            model="deepseek-v4",
            api_key=config.get("api_key", ""),
            api_base=config.get("base_url", ""),
            disable_streaming=True,
            max_retries=1,
        )
        tools = [
            {
                "type": "function",
                "function": {"name": "render_python_chart", "parameters": {"type": "object"}},
            }
        ]

        with mock.patch.object(
            agent.ChatDeepSeek,
            "_generate",
            side_effect=[text_result, chart_result],
        ) as generate:
            result = model._generate(
                [agent.HumanMessage(content="看看移动的收入趋势")],
                tools=tools,
            )

        self.assertIs(result, text_result)
        self.assertEqual(generate.call_count, 1)

    def test_completed_chart_allows_trend_final_answer(self) -> None:
        complete = agent.AIMessage(
            content=(
                "中国移动收入历史趋势总体向上，表格、图表、口径及本地与联网核验结果如下。"
                '<suggestions>["查看利润趋势", "对比中国电信", "查看收入构成"]</suggestions>'
            )
        )
        complete_result = mock.Mock(
            generations=[mock.Mock(message=complete, generation_info={"finish_reason": "stop"})]
        )
        config = agent.load_ai_config()
        model = agent.StableAgentChatDeepSeek(
            model="deepseek-v4",
            api_key=config.get("api_key", ""),
            api_base=config.get("base_url", ""),
            disable_streaming=True,
            max_retries=1,
        )
        messages = [
            agent.HumanMessage(content="看看移动的收入趋势"),
            agent.ToolMessage(
                content="![中国移动收入趋势](/api/agent-charts/example.png)",
                tool_call_id="call-chart",
                name="render_python_chart",
            ),
        ]

        with mock.patch.object(agent.ChatDeepSeek, "_generate", return_value=complete_result) as generate:
            result = model._generate(messages, tools=[agent.render_python_chart])

        self.assertIs(result, complete_result)
        self.assertEqual(generate.call_count, 1)

    def test_text_only_trend_answer_does_not_get_deterministic_chart_call(self) -> None:
        text_only_1 = agent.AIMessage(
            content=(
                "中国移动收入总体上升。"
                '<suggestions>["查看利润", "对比电信", "查看用户"]</suggestions>'
            )
        )
        text_only_2 = agent.AIMessage(
            content=(
                "中国移动收入趋势向上。"
                '<suggestions>["查看利润", "对比电信", "查看用户"]</suggestions>'
            )
        )
        result_1 = mock.Mock(
            generations=[mock.Mock(message=text_only_1, generation_info={"finish_reason": "stop"})]
        )
        result_2 = mock.Mock(
            generations=[mock.Mock(message=text_only_2, generation_info={"finish_reason": "stop"})]
        )
        config = agent.load_ai_config()
        model = agent.StableAgentChatDeepSeek(
            model="deepseek-v4",
            api_key=config.get("api_key", ""),
            api_base=config.get("base_url", ""),
            disable_streaming=True,
            max_retries=1,
        )
        messages = [
            agent.HumanMessage(content="看看移动的收入趋势"),
            agent.ToolMessage(
                content=(
                    "精确季度指标行：subject=中国移动; period=Q1 2016; metric_key=revenue; "
                    "metric_zh=营业收入/收益; grain=quarter; standardized_value=177504 millions CNY;\n"
                    "精确季度指标行：subject=中国移动; period=Q2 2016; metric_key=revenue; "
                    "metric_zh=营业收入/收益; grain=quarter; standardized_value=192847 millions CNY;"
                ),
                tool_call_id="call-local",
                name="search_local_reports",
            ),
        ]
        tools = [
            {
                "type": "function",
                "function": {"name": "render_python_chart", "parameters": {"type": "object"}},
            }
        ]

        with mock.patch.object(
            agent.ChatDeepSeek,
            "_generate",
            side_effect=[result_1, result_2],
        ) as generate:
            result = model._generate(messages, tools=tools)

        self.assertIs(result, result_1)
        self.assertEqual(generate.call_count, 1)
        self.assertFalse(result.generations[0].message.tool_calls)

    def test_dual_retrieval_does_not_force_a_disclosure_rewrite(self) -> None:
        incomplete = agent.AIMessage(
            content=(
                "中国移动收入总体上升，相关来源如下。"
                '<suggestions>["查看利润", "对比电信", "查看用户"]</suggestions>'
            )
        )
        repaired = agent.AIMessage(
            content=(
                "中国移动收入总体上升。\n\n"
                "**本地与联网核验说明：** 本地季度数据与联网年度行业数据口径不可比，"
                "因此不能认定数值一致。"
                '<suggestions>["查看利润", "对比电信", "查看用户"]</suggestions>'
            )
        )
        result_1 = mock.Mock(
            generations=[mock.Mock(message=incomplete, generation_info={"finish_reason": "stop"})]
        )
        result_2 = mock.Mock(
            generations=[mock.Mock(message=repaired, generation_info={"finish_reason": "stop"})]
        )
        config = agent.load_ai_config()
        model = agent.StableAgentChatDeepSeek(
            model="deepseek-v4",
            api_key=config.get("api_key", ""),
            api_base=config.get("base_url", ""),
            disable_streaming=True,
            max_retries=1,
        )
        messages = [
            agent.HumanMessage(content="看看移动的收入趋势"),
            agent.ToolMessage(content="本地数据", tool_call_id="local", name="search_local_reports"),
            agent.ToolMessage(content="联网数据", tool_call_id="web", name="web_search"),
            agent.ToolMessage(
                content="![趋势图](/generated-charts/chart.png)",
                tool_call_id="chart",
                name="render_python_chart",
            ),
        ]

        with mock.patch.object(
            agent.ChatDeepSeek,
            "_generate",
            side_effect=[result_1, result_2],
        ) as generate:
            result = model._generate(messages, tools=[agent.render_python_chart])

        self.assertIs(result, result_1)
        self.assertEqual(generate.call_count, 1)

    def test_dual_source_disclosure_gate_is_removed(self) -> None:
        self.assertFalse(hasattr(agent.StableAgentChatDeepSeek, "_has_dual_source_disclosure"))

    def test_process_cleanup_does_not_discard_data_table_before_conclusion(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        self.assertNotIn("text = text.slice(formalStart).trim();", app)
        self.assertNotIn("const formalStart = text.search(", app)

    def test_tool_limit_does_not_generate_a_chart_outside_the_agent(self) -> None:
        self.assertFalse(hasattr(agent, "_recover_chart_after_tool_limit"))

    def test_required_read_gate_is_removed(self) -> None:
        self.assertFalse(hasattr(agent.StableAgentChatDeepSeek, "_has_pending_required_read"))

    def test_long_complete_answer_does_not_require_completion_footer(self) -> None:
        partial_message = agent.AIMessage(
            content=(
                "第一部分已经分析完毕，但第二部分和最终结论尚未生成。"
                "这个片段故意以正常句号结尾，以覆盖过去只检查标点时会漏判的场景。"
                "模型供应方仍然可能返回 stop，所以应用层必须用完整回答协议来确认结束。"
                "再增加足够的文字，使它达到真实分析回答的长度，同时仍然缺少最终建议标记。"
            )
        )
        complete_message = agent.AIMessage(
            content=(
                "第一部分、第二部分和最终结论均已完整生成，且所有段落都已经收束。"
                "完整回答协议会在正文最后附上结构化建议标记，前端读取后再结束本轮。"
                "因此这次可以安全地把流状态切换为完成，并允许用户继续发送下一条消息。"
                "该标记同时帮助应用识别语义上看似完整、实际上被截断的长回答。\n"
                '<suggestions>["继续追问", "查看来源", "新建话题"]</suggestions>'
            )
        )
        partial_result = mock.Mock(
            generations=[mock.Mock(message=partial_message, generation_info={"finish_reason": "stop"})]
        )
        complete_result = mock.Mock(
            generations=[mock.Mock(message=complete_message, generation_info={"finish_reason": "stop"})]
        )
        config = agent.load_ai_config()
        model = agent.StableAgentChatDeepSeek(
            model="deepseek-v4",
            api_key=config.get("api_key", ""),
            api_base=config.get("base_url", ""),
            disable_streaming=True,
            max_retries=1,
        )

        with mock.patch.object(
            agent.ChatDeepSeek,
            "_generate",
            side_effect=[partial_result, complete_result],
        ) as generate:
            result = model._generate([agent.HumanMessage(content="请分两部分完整回答")])

        self.assertIs(result, partial_result)
        self.assertEqual(generate.call_count, 1)

    def test_complete_answer_is_not_rewritten_to_add_footer(self) -> None:
        first_message = agent.AIMessage(
            content=(
                "第一版回答只覆盖了请求的前半部分，虽然句号完整，但缺少后续比较和结论。"
                "这里补足字符长度，模拟供应方在某一段结束后提前返回 stop 的真实场景。"
                "应用应先触发一次有界修复，而不是马上把这一版直接交给前端显示。"
            )
        )
        repaired_text = (
            "修复后的回答已经覆盖用户要求的两个比较部分，并给出了明确且完整的最终结论。"
            "所有列表和句子均已闭合，事实边界也已说明，因此正文在语义和结构上都可以正常展示。"
            "即使模型遗漏了只供前端使用的推荐追问标签，系统也不应丢弃这份已经修复完成的回答。"
        )
        repaired_message = agent.AIMessage(content=repaired_text)
        first_result = mock.Mock(
            generations=[mock.Mock(message=first_message, generation_info={"finish_reason": "stop"})]
        )
        repaired_result = mock.Mock(
            generations=[mock.Mock(message=repaired_message, generation_info={"finish_reason": "stop"})]
        )
        config = agent.load_ai_config()
        model = agent.StableAgentChatDeepSeek(
            model="deepseek-v4",
            api_key=config.get("api_key", ""),
            api_base=config.get("base_url", ""),
            disable_streaming=True,
            max_retries=1,
        )

        with mock.patch.object(
            agent.ChatDeepSeek,
            "_generate",
            side_effect=[first_result, repaired_result],
        ) as generate:
            result = model._generate([agent.HumanMessage(content="请完整比较并给出结论")])

        self.assertIs(result, first_result)
        self.assertEqual(generate.call_count, 1)
        self.assertNotIn("<suggestions>", first_message.content)

    def test_provider_length_finish_still_uses_engineering_recovery(self) -> None:
        complete_text = (
            "## 一、背景\n第一节完整。\n## 二、网络\n第二节完整。\n"
            "## 三、业务\n第三节完整。\n## 四、产业\n第四节完整。\n"
            "## 五、风险\n第五节完整。\n## 总结三点\n"
            "- 方向确定。\n- 节奏受制。\n- 香港有机会。"
        )
        complete_message = agent.AIMessage(content=complete_text)
        complete_result = mock.Mock(
            generations=[mock.Mock(message=complete_message, generation_info={"finish_reason": "length"})]
        )
        config = agent.load_ai_config()
        model = agent.StableAgentChatDeepSeek(
            model="deepseek-v4",
            api_key=config.get("api_key", ""),
            api_base=config.get("base_url", ""),
            disable_streaming=True,
            max_retries=1,
        )
        request = (
            "<current_user_request>写约800字分析，分成五节，每节完整收束，"
            "最后总结三点。</current_user_request>"
        )

        with mock.patch.object(agent.ChatDeepSeek, "_generate", return_value=complete_result) as generate:
            result = model._generate([agent.HumanMessage(content=request)])

        self.assertIs(result, complete_result)
        self.assertGreater(generate.call_count, 1)

    def test_incomplete_retry_uses_bounded_tool_free_context(self) -> None:
        incomplete_message = agent.AIMessage(
            content='现金流对比如下，\n<suggestions>["继续查看"'
        )
        complete_message = agent.AIMessage(
            content='现金流需要使用母公司口径比较，不能写成云分部独立现金流。\n<suggestions>["查看AWS", "查看Google", "查看口径"]</suggestions>'
        )
        incomplete_result = mock.Mock(
            generations=[mock.Mock(message=incomplete_message, generation_info={"finish_reason": "stop"})]
        )
        complete_result = mock.Mock(
            generations=[mock.Mock(message=complete_message, generation_info={"finish_reason": "stop"})]
        )
        config = agent.load_ai_config()
        model = agent.StableAgentChatDeepSeek(
            model="MiniMax-M2.1",
            api_key=config.get("api_key", ""),
            api_base=config.get("base_url", ""),
            disable_streaming=True,
            max_retries=1,
        )
        messages = [
            agent.SystemMessage(content="原始系统提示" * 10000),
            agent.HumanMessage(content="<current_user_request>补全现金流数据</current_user_request>"),
            *[
                agent.ToolMessage(
                    content=(f"工具结果 {index}：" + "数据" * 6000),
                    tool_call_id=f"call_{index}",
                )
                for index in range(6)
            ],
        ]

        with mock.patch.object(
            agent.ChatDeepSeek,
            "_generate",
            side_effect=[incomplete_result, complete_result],
        ) as generate:
            result = model._generate(messages, tools=[agent.search_local_reports])

        self.assertIs(result, complete_result)
        self.assertEqual(generate.call_count, 2)
        retry_messages = generate.call_args_list[1].args[0]
        retry_text = "\n".join(str(item.content or "") for item in retry_messages)
        self.assertLess(len(retry_text), 25000)
        self.assertNotIn("tools", generate.call_args_list[1].kwargs)
        self.assertIn("按问题本身决定合适的详略", retry_text)
        self.assertNotIn("1200 个中文字符", retry_text)

    def test_search_local_reports_does_not_limit_repeated_searches(self) -> None:
        with mock.patch("agent.retrieve_context", return_value=[]) as retrieve:
            results = [
                agent.search_local_reports.invoke({"query": "现金流"})
                for _ in range(12)
            ]

        self.assertEqual(retrieve.call_count, 12)
        self.assertTrue(all(result == "没有找到相关的本地报告信息。" for result in results))
        self.assertTrue(all("达到本轮调用上限" not in result for result in results))

    def test_web_search_allows_repeated_calls_and_preserves_requested_result_count(self) -> None:
        with (
            mock.patch("agent._search_with_searxng", return_value=[]) as searxng,
            mock.patch(
                "agent._search_with_duckduckgo",
                return_value=[
                    {
                        "title": "AWS Investor Relations",
                        "url": f"https://ir.aboutamazon.com/{index}",
                        "snippet": "AWS quarterly revenue and capital expenditure",
                    }
                    for index in range(12)
                ],
            ) as ddgs,
            mock.patch(
                "agent._filter_relevant_search_results",
                side_effect=lambda results, query, limit, **kwargs: (results[:limit], 0),
            ),
        ):
            results = [
                agent.web_search.invoke({"query": f"AWS quarterly revenue {year}", "max_results": 12})
                for year in range(2014, 2026)
            ]

        self.assertEqual(searxng.call_count, 12)
        self.assertEqual(ddgs.call_count, 12)
        self.assertTrue(all("达到本轮调用上限" not in result for result in results))
        self.assertTrue(all(result.count("[来源 ") == 12 for result in results))

    def test_aws_multi_year_quarterly_query_returns_complete_series(self) -> None:
        chunks = rag_llm._quarterly_exact_metric_chunks(
            "AWS Microsoft Azure Google Cloud 2016 2026 quarterly revenue trend"
        )
        aws_revenue = next(
            chunk["text"]
            for chunk in chunks
            if "subject=AWS;" in chunk["text"] and "metric_key=revenue;" in chunk["text"]
        )

        self.assertIn("coverage=Q1 2016 至 Q4 2025", aws_revenue)
        self.assertIn("points=40", aws_revenue)
        self.assertIn("Q1 2016=2566", aws_revenue)
        self.assertIn("Q4 2025=35579", aws_revenue)

    def test_aws_quarterly_chart_uses_all_40_points(self) -> None:
        token = agent.SELECTED_DATASET_IDS.set(
            {"quarterly_competitor_metrics_2026-06-18"}
        )
        try:
            with mock.patch(
                "agent.render_chart",
                return_value={
                    "url": "/charts/aws.png",
                    "path": "/tmp/aws.png",
                    "font": "Noto Sans CJK",
                },
            ) as render:
                result = agent.render_quarterly_metric_chart.invoke(
                    {"subject": "AWS", "metric_key": "revenue"}
                )
        finally:
            agent.SELECTED_DATASET_IDS.reset(token)

        spec = render.call_args.args[0]
        self.assertEqual(len(spec["x"]), 40)
        self.assertEqual(len(spec["series"][0]["data"]), 40)
        self.assertEqual(spec["x"][0], "Q1 2016")
        self.assertEqual(spec["x"][-1], "Q4 2025")
        self.assertIn("40 个数据点", result)
        self.assertIn("![AWS", result)

    def test_local_reference_allows_multiple_distinct_sources(self) -> None:
        sources = [
            "agent_knowledge/cmhk_macro_policy_2026-06-19/macro_policy_summary.md",
            "agent_knowledge/cmhk_macro_policy_2026-06-19/macro_policy_metrics.csv",
            "agent_knowledge/cmhk_macro_policy_2026-06-19/online_verification_2026-06-19.md",
            "agent_knowledge/cmhk_macro_policy_2026-06-19/manifest.json",
        ]
        with mock.patch(
            "agent._read_local_reference_text",
            side_effect=lambda source: f"[本地引用: {source}]",
        ) as read_reference:
            results = [
                agent.read_local_reference.invoke({"source": source})
                for source in sources
            ]

        self.assertEqual(read_reference.call_count, 4)
        self.assertTrue(all("达到本轮调用上限" not in result for result in results))
        self.assertTrue(all("工具调用已停止" not in result for result in results))

    def test_local_reference_does_not_limit_repeated_reads(self) -> None:
        source = "agent_knowledge/cmhk_macro_policy_2026-06-19/macro_policy_summary.md"
        with mock.patch(
            "agent._read_local_reference_text",
            return_value=f"[本地引用: {source}]",
        ) as read_reference:
            first = agent.read_local_reference.invoke({"source": source})
            duplicate = agent.read_local_reference.invoke({
                "source": f"/references/{source}",
            })

        self.assertIn("[本地引用:", first)
        self.assertIn("[本地引用:", duplicate)
        self.assertNotIn("达到本轮调用上限", duplicate)
        self.assertNotIn("本轮已经读取过", duplicate)
        self.assertEqual(read_reference.call_count, 2)

    def test_tariff_reference_reads_cross_brand_structure_not_csv_head(self) -> None:
        source = "agent_knowledge/competitor_product_tariffs/product_tariffs_formal_agent_records.csv"
        dataset_token = agent.SELECTED_DATASET_IDS.set({"competitor_product_tariffs"})
        request_token = agent.CURRENT_USER_REQUEST.set(
            "请对比香港主要竞对最新移动与宽频套餐资费，说明月费、数据量、合约期和促销差异。"
        )
        try:
            result = agent._read_local_reference_text(source)
        finally:
            agent.CURRENT_USER_REQUEST.reset(request_token)
            agent.SELECTED_DATASET_IDS.reset(dataset_token)

        self.assertIn("数据集全局覆盖锚点", result)
        self.assertIn("query_scope=cross_brand", result)
        self.assertIn("brand=3HK / Hutchison", result)
        self.assertIn("brand=SmarTone", result)
        self.assertIn("brand=HKBN", result)
        self.assertIn("brand=NETVIGATOR", result)
        self.assertNotIn("record_class,数据子库,时间类型", result)

    def test_tariff_answers_are_not_rewritten_by_a_deterministic_postprocessor(self) -> None:
        self.assertFalse(hasattr(agent, "_tariff_answer_evidence_mismatch"))
        self.assertFalse(hasattr(agent, "_tariff_evidence_fallback_answer"))

    def test_xml_pseudo_tool_call_is_recovered_without_another_model_request(self) -> None:
        pseudo_message = agent.AIMessage(
            content=(
                "<search_local_reports>\n"
                "  <query>2026-07-20 周报 竞争情报 本周</query>\n"
                "  <max_results>5</max_results>\n"
                "</search_local_reports>"
            )
        )
        pseudo_result = mock.Mock(
            generations=[mock.Mock(message=pseudo_message, generation_info={"finish_reason": "stop"})]
        )
        config = agent.load_ai_config()
        model = agent.StableAgentChatDeepSeek(
            model="deepseek-v4",
            api_key=config.get("api_key", ""),
            api_base=config.get("base_url", ""),
            disable_streaming=True,
            max_retries=1,
        )

        with mock.patch.object(agent.ChatDeepSeek, "_generate", return_value=pseudo_result) as generate:
            result = model._generate(
                [agent.HumanMessage(content="查询本周情报")],
                tools=[agent.search_local_reports],
            )

        self.assertIs(result, pseudo_result)
        self.assertEqual(generate.call_count, 1)
        recovered = result.generations[0].message
        self.assertEqual(recovered.content, "")
        self.assertEqual(recovered.tool_calls[0]["name"], "search_local_reports")
        self.assertEqual(recovered.tool_calls[0]["args"]["max_results"], 5)
        self.assertEqual(recovered.tool_calls[0]["args"]["query"], "2026-07-20 周报 竞争情报 本周")

    def test_stream_agent_repairs_unclosed_footer_before_done(self) -> None:
        class FakeAgent:
            def stream(self, inputs, stream_mode=None, config=None):
                yield agent.AIMessage(
                    content='明确主体后，\n<suggestions>["中国移动", "AWS"',
                    response_metadata={"finish_reason": "stop"},
                ), {}

        repaired = '已重新组织为完整回答。\n<suggestions>["继续分析", "查看来源", "对比路线"]</suggestions>'
        with (
            mock.patch("agent.get_agent", return_value=FakeAgent()),
            mock.patch(
                "agent._finalize_after_incomplete_run",
                return_value=(repaired, {"inputTokens": 1, "outputTokens": 2, "totalTokens": 3}),
            ) as finalize,
        ):
            events = list(agent.stream_agent("请查看路线图", thinking_enabled=False))

        answer = "".join(event.get("text", "") for event in events if event.get("type") == "delta")
        self.assertEqual(answer, repaired)
        self.assertEqual(finalize.call_count, 1)
        self.assertFalse(any(event.get("type") == "error" for event in events))
        self.assertTrue(any(event.get("type") == "run_summary" for event in events))
        self.assertEqual(events[-1].get("type"), "done")

    def test_graph_recursion_limit_is_finalized_as_answer_not_error(self) -> None:
        class FakeAgent:
            def stream(self, inputs, stream_mode=None, config=None):
                raise RuntimeError("GRAPH_RECURSION_LIMIT: stopped after 20 steps")
                yield

        final = '已基于当前证据完成收尾。\n<suggestions>["缩小范围", "查看来源", "继续追问"]</suggestions>'
        with (
            mock.patch("agent.get_agent", return_value=FakeAgent()),
            mock.patch(
                "agent._finalize_after_incomplete_run",
                return_value=(final, {"inputTokens": 5, "outputTokens": 8, "totalTokens": 13}),
            ) as finalize,
        ):
            events = list(agent.stream_agent("请完成复杂分析", thinking_enabled=False))

        answer = "".join(event.get("text", "") for event in events if event.get("type") == "delta")
        self.assertEqual(answer, final)
        self.assertEqual(finalize.call_count, 1)
        self.assertFalse(any(event.get("type") == "error" for event in events))
        self.assertEqual(events[-1].get("type"), "done")

    def test_agent_graph_has_no_product_step_limit(self) -> None:
        captured: dict[str, object] = {}

        class FakeAgent:
            def stream(self, inputs, stream_mode=None, config=None):
                captured["config"] = config
                return iter(())

        list(agent._stream_agent_events(FakeAgent(), {"messages": []}))

        self.assertEqual(captured["config"], {"recursion_limit": sys.maxsize})

    def test_legacy_tool_limit_text_does_not_stop_the_agent_stream(self) -> None:
        class FakeAgent:
            def stream(self, inputs, stream_mode=None, config=None):
                yield agent.ToolMessage(
                    content=(
                        "search_local_reports 已达到本轮调用上限（6 次），"
                        "请停止继续调用该工具，直接基于已经返回的资料给出结论。"
                    ),
                    tool_call_id="call_limit",
                ), {}
                yield agent.AIMessage(content="Agent 已继续完成回答。"), {}

        with (
            mock.patch("agent.get_agent", return_value=FakeAgent()),
            mock.patch("agent._finalize_after_incomplete_run") as finalize,
        ):
            events = list(agent.stream_agent("对比最近两周的竞对动态变化", thinking_enabled=False))

        answer = "".join(event.get("text", "") for event in events if event.get("type") == "delta")
        self.assertEqual(answer, "Agent 已继续完成回答。")
        self.assertEqual(finalize.call_count, 0)
        self.assertFalse(any(event.get("type") == "error" for event in events))
        self.assertEqual(events[-1].get("type"), "done")

    def test_parallel_calls_are_all_allowed_to_finish_after_legacy_limit_text(self) -> None:
        class FakeAgent:
            def stream(self, inputs, stream_mode=None, config=None):
                yield agent.AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "search_local_reports",
                            "args": {"query": "云厂商"},
                            "id": "call-limit",
                            "type": "tool_call",
                        },
                        {
                            "name": "web_search",
                            "args": {"query": "云厂商业绩"},
                            "id": "call-web",
                            "type": "tool_call",
                        },
                        {
                            "name": "read_webpage",
                            "args": {"url": "https://example.com"},
                            "id": "call-page",
                            "type": "tool_call",
                        },
                    ],
                ), {}
                yield agent.ToolMessage(
                    content=(
                        "search_local_reports 已达到本轮调用上限（3 次），"
                        "请停止继续调用该工具。"
                    ),
                    tool_call_id="call-limit",
                ), {}
                yield agent.ToolMessage(content="联网结果", tool_call_id="call-web"), {}
                yield agent.ToolMessage(content="网页原文", tool_call_id="call-page"), {}
                yield agent.AIMessage(content="已完成三项工具核验。"), {}

        with mock.patch("agent.get_agent", return_value=FakeAgent()):
            events = list(agent.stream_agent("分析云厂商", thinking_enabled=False))

        results = {
            event.get("id"): event
            for event in events
            if event.get("type") == "tool_call_result"
        }
        self.assertEqual(set(results), {"call-limit", "call-web", "call-page"})
        self.assertIn("达到本轮调用上限", results["call-limit"]["content"])
        self.assertEqual(results["call-web"]["content"], "联网结果")
        self.assertIn("网页原文", results["call-page"]["content"])
        answer = "".join(event.get("text", "") for event in events if event.get("type") == "delta")
        self.assertEqual(answer, "已完成三项工具核验。")
        self.assertEqual(events[-1].get("type"), "done")

    def test_repeated_tool_calls_are_not_stopped_by_the_stream_layer(self) -> None:
        class FakeAgent:
            def stream(self, inputs, stream_mode=None, config=None):
                for index in range(4):
                    call_id = f"same_{index}"
                    yield agent.AIMessage(
                        content="",
                        tool_calls=[{
                            "name": "search_local_reports",
                            "args": {"query": "同一个查询"},
                            "id": call_id,
                            "type": "tool_call",
                        }],
                    ), {}
                    yield agent.ToolMessage(content="相同检索结果", tool_call_id=call_id), {}

        with mock.patch("agent.get_agent", return_value=FakeAgent()):
            events = list(agent.stream_agent("测试重复调用保护", thinking_enabled=False))

        starts = [event for event in events if event.get("type") == "tool_call_start"]
        self.assertEqual(len(starts), 4)
        self.assertEqual(events[-1].get("type"), "done")

    def test_stream_does_not_install_a_markdown_table_limiter(self) -> None:
        self.assertFalse(hasattr(agent, "MarkdownTableLimiter"))

    def test_non_streaming_ai_message_keeps_reasoning_panel_and_final_answer(self) -> None:
        class FakeAgent:
            def stream(self, inputs, stream_mode=None):
                yield agent.AIMessage(
                    content="这是正常的中文最终答案，正文也必须通过多个连续事件逐段流式返回给页面。",
                    additional_kwargs={"reasoning_content": "The model checked context and prepared the answer."},
                ), {}

        with mock.patch("agent.get_agent", return_value=FakeAgent()):
            events = list(agent.stream_agent("请回答", thinking_enabled=False))

        reasoning = [event for event in events if event.get("type") == "reasoning"]
        answers = [event for event in events if event.get("type") == "delta"]
        self.assertGreater(len(reasoning), 1)
        self.assertGreater(len(answers), 1)
        self.assertIn("正在组织", "".join(event["text"] for event in reasoning))
        self.assertEqual(
            "".join(event["text"] for event in answers),
            "这是正常的中文最终答案，正文也必须通过多个连续事件逐段流式返回给页面。",
        )

    def test_run_summary_reports_provider_token_usage(self) -> None:
        class FakeAgent:
            def stream(self, inputs, stream_mode=None):
                yield agent.AIMessage(
                    content="简短回答。",
                    usage_metadata={"input_tokens": 321, "output_tokens": 45, "total_tokens": 366},
                ), {}

        with mock.patch("agent.get_agent", return_value=FakeAgent()):
            events = list(agent.stream_agent("请回答"))

        summary = next(event for event in events if event.get("type") == "run_summary")
        self.assertEqual(summary["usage"]["inputTokens"], 321)
        self.assertEqual(summary["usage"]["outputTokens"], 45)
        self.assertEqual(summary["usage"]["totalTokens"], 366)
        self.assertFalse(summary["usage"]["estimated"])

    def test_non_streaming_ai_message_preserves_structured_tool_events(self) -> None:
        class FakeAgent:
            def stream(self, inputs, stream_mode=None):
                yield agent.AIMessage(
                    content="",
                    tool_calls=[{"name": "get_system_status", "args": {}, "id": "call-1", "type": "tool_call"}],
                    additional_kwargs={"reasoning_content": "需要读取系统状态。"},
                ), {}
                yield agent.ToolMessage(content="系统状态正常。", tool_call_id="call-1", name="get_system_status"), {}

        with mock.patch("agent.get_agent", return_value=FakeAgent()):
            events = list(agent.stream_agent("查看系统状态"))

        starts = [event for event in events if event.get("type") == "tool_call_start"]
        results = [event for event in events if event.get("type") == "tool_call_result"]
        self.assertEqual(starts[0]["name"], "get_system_status")
        self.assertEqual(results[0]["name"], "get_system_status")
        self.assertIn("系统状态正常", results[0]["content"])

    def test_plain_greeting_keeps_context_without_special_tool_gate(self) -> None:
        captured: dict[str, str] = {}

        class FakeAgent:
            def stream(self, inputs, stream_mode=None):
                captured["message"] = inputs["messages"][0][1]
                captured["stream_mode"] = stream_mode
                yield agent.AIMessageChunk(content="您好，我是小竞AI。"), {}

        with mock.patch("agent.get_agent", return_value=FakeAgent()):
            events = list(
                agent.stream_agent(
                    "你好",
                    selected_dataset_ids=["quarterly_competitor_metrics_2026-06-18"],
                    conversation_history=[
                        {"role": "user", "content": "请分析中国铁塔收入趋势"},
                        {"role": "assistant", "content": "中国铁塔收入趋势如下..."},
                    ],
                )
            )

        first_delta = next(event for event in events if event.get("type") == "delta")
        self.assertIn("我是小竞AI", first_delta["text"])
        self.assertEqual(events[-2]["toolCount"], 0)
        self.assertEqual(events[-1], {"type": "done"})
        self.assertEqual(captured["stream_mode"], "messages")
        self.assertNotIn("普通寒暄", captured["message"])
        self.assertIn("中国铁塔", captured["message"])
        self.assertIn("若与本轮用户新指令冲突，以本轮新指令为准", captured["message"])
        self.assertNotIn("只能作为背景", captured["message"])
        self.assertNotIn("不能自动把历史主题补全为本轮问题", captured["message"])
        self.assertIn("quarterly_competitor_metrics", captured["message"])
        self.assertNotIn("长期记忆召回", captured["message"])

    def test_explicit_follow_up_prefers_fresh_same_thread_history(self) -> None:
        captured: dict[str, str] = {}

        class FakeAgent:
            def stream(self, inputs, stream_mode=None, config=None):
                captured["message"] = inputs["messages"][0][1]
                yield agent.AIMessage(content="三条建议已经完整给出。"), {}

        history = [
            {"role": "user", "content": "对比AWS和Google Cloud的年度收入与营业利润。"},
            {"role": "assistant", "content": "AWS与Google Cloud的对比表和口径如下。"},
        ]
        with mock.patch("agent.get_agent", return_value=FakeAgent()):
            events = list(
                agent.stream_agent(
                    "继续，基于前面的云厂商对比给CMHK三条可执行建议。",
                    force_web_search=True,
                    conversation_history=history,
                    active_thread_id="current-cloud-thread",
                )
            )

        self.assertTrue(any(event.get("type") == "delta" for event in events))
        self.assertIn("AWS和Google Cloud", captured["message"])
        self.assertIn("同一聊天线程的最近对话", captured["message"])
        self.assertNotIn("必须先调用 `search_chat_history`", captured["message"])
        self.assertNotIn("你必须调用 `web_search`", captured["message"])

    def test_user_profile_question_is_not_wrapped_in_a_forced_workflow(self) -> None:
        captured: dict[str, str] = {}

        class FakeAgent:
            def stream(self, inputs, stream_mode=None):
                captured["message"] = inputs["messages"][0][1]
                captured["stream_mode"] = stream_mode
                yield agent.AIMessageChunk(content="我会基于明确记忆和历史聊天回答。"), {}

        with mock.patch("agent.get_agent", return_value=FakeAgent()):
            events = list(
                agent.stream_agent(
                    "我对什么感兴趣",
                    selected_dataset_ids=["quarterly_competitor_metrics_2026-06-18"],
                    selected_skill_ids=["quarterly_competitor_data"],
                    conversation_history=[
                        {"role": "user", "content": "请分析中国铁塔收入趋势"},
                        {"role": "assistant", "content": "中国铁塔收入趋势如下..."},
                    ],
                )
            )

        self.assertTrue(any(event.get("type") == "delta" for event in events))
        self.assertEqual(events[-2]["toolCount"], 0)
        self.assertEqual(events[-1], {"type": "done"})
        self.assertEqual(captured["stream_mode"], "messages")
        self.assertNotIn("先调用 `search_agent_memory`", captured["message"])
        self.assertNotIn("再调用 `search_chat_history`", captured["message"])
        self.assertIn("中国铁塔", captured["message"])
        self.assertIn("quarterly_competitor_metrics", captured["message"])
        self.assertNotIn("quarterly_competitor_data", captured["message"])

    def test_profile_chat_history_search_returns_recent_user_questions(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = os.path.join(tempdir, "threads.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "threads": [
                            {
                                "id": "thread-1",
                                "title": "香港5G政策与CMHK收入展望",
                                "updatedAt": "2026-06-25T10:00:00",
                                "messages": [
                                    {"role": "user", "content": "请分析香港5G监管政策对CMHK未来收入的影响"},
                                    {"role": "assistant", "content": "以下是分析。"},
                                ],
                            },
                            {
                                "id": "thread-2",
                                "title": "日常问候",
                                "updatedAt": "2026-06-24T10:00:00",
                                "messages": [
                                    {"role": "user", "content": "你好"},
                                    {"role": "assistant", "content": "您好。"},
                                ],
                            },
                        ]
                    },
                    handle,
                    ensure_ascii=False,
                )
            with mock.patch("agent.CHAT_THREADS_PATH", agent.Path(path)):
                result = agent.search_chat_history.invoke({"query": "我对什么感兴趣", "limit": 5})

        self.assertIn("香港5G监管政策", result)
        self.assertIn("CMHK未来收入", result)
        self.assertNotIn("您好。", result)

    def test_chat_history_tool_filters_an_exact_time_range_and_role(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = os.path.join(tempdir, "threads.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "threads": [{
                            "id": "thread-timed",
                            "title": "定时历史查询",
                            "createdAt": "2026-07-22T17:00:00+08:00",
                            "updatedAt": "2026-07-22T17:04:00+08:00",
                            "messages": [
                                {
                                    "role": "user",
                                    "content": "下午五点我问了这个问题",
                                    "createdAt": "2026-07-22T17:01:00+08:00",
                                },
                                {
                                    "role": "assistant",
                                    "content": "这是AI在五点零三分的回答。",
                                    "createdAt": "2026-07-22T17:03:00+08:00",
                                    "completedAt": "2026-07-22T17:03:20+08:00",
                                },
                            ],
                        }]
                    },
                    handle,
                    ensure_ascii=False,
                )
            with mock.patch("agent.CHAT_THREADS_PATH", agent.Path(path)):
                result = agent.search_chat_history.invoke({
                    "query": "",
                    "start_time": "2026-07-22T17:00:30+08:00",
                    "end_time": "2026-07-22T17:02:00+08:00",
                    "role": "user",
                    "limit": 5,
                    "context_window": 0,
                })

        self.assertIn("下午五点我问了这个问题", result)
        self.assertNotIn("五点零三分", result)
        self.assertIn("逐条消息准确时间", result)

    def test_chat_history_tool_marks_legacy_time_as_thread_range(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = os.path.join(tempdir, "threads.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "threads": [{
                            "id": "thread-legacy",
                            "title": "旧历史记录",
                            "createdAt": "2026-07-20T16:00:00+08:00",
                            "updatedAt": "2026-07-20T18:00:00+08:00",
                            "messages": [{"role": "user", "content": "旧消息没有逐条时间戳"}],
                        }]
                    },
                    handle,
                    ensure_ascii=False,
                )
            with mock.patch("agent.CHAT_THREADS_PATH", agent.Path(path)):
                result = agent.search_chat_history.invoke({
                    "query": "",
                    "start_time": "2026-07-20T17:00:00+08:00",
                    "end_time": "2026-07-20T17:10:00+08:00",
                    "role": "all",
                    "limit": 5,
                })

        self.assertIn("旧消息没有逐条时间戳", result)
        self.assertIn("旧记录仅有会话时间范围", result)

    def test_chat_history_tool_is_always_available_for_agent_autonomy(self) -> None:
        tool_names = {item.name for item in agent._agent_tools(allow_web_search=False, user_message="你来判断要查什么")}
        self.assertIn("search_chat_history", tool_names)

    def test_short_input_does_not_install_a_cross_thread_history_gate(self) -> None:
        self.assertFalse(hasattr(agent, "_should_probe_chat_history_for_ambiguity"))
        self.assertFalse(hasattr(agent, "AMBIGUOUS_HISTORY_PROBE"))

    def test_history_search_excludes_current_turn_without_unrelated_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = os.path.join(tempdir, "threads.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "threads": [
                            {
                                "id": "current-thread",
                                "title": "当前模糊输入",
                                "createdAt": "2026-07-23T09:24:50+08:00",
                                "updatedAt": "2026-07-23T09:24:52+08:00",
                                "messages": [
                                    {"role": "user", "content": "富裕"},
                                    {"role": "assistant", "content": "正在分析请求，并调用相关工具获取依据。"},
                                ],
                            },
                            {
                                "id": "previous-thread",
                                "title": "上一项工作",
                                "createdAt": "2026-07-23T09:10:00+08:00",
                                "updatedAt": "2026-07-23T09:12:00+08:00",
                                "messages": [
                                    {"role": "user", "content": "请继续整理昨天的战略周报"},
                                    {"role": "assistant", "content": "已经整理完成。"},
                                ],
                            },
                        ]
                    },
                    handle,
                    ensure_ascii=False,
                )
            thread_token = agent.ACTIVE_CHAT_THREAD_ID.set("current-thread")
            request_token = agent.CURRENT_USER_REQUEST.set("富裕")
            try:
                with mock.patch("agent.CHAT_THREADS_PATH", agent.Path(path)):
                    result = agent.search_chat_history.invoke({
                        "query": "富裕",
                        "role": "user",
                        "limit": 5,
                        "context_window": 1,
                    })
            finally:
                agent.ACTIVE_CHAT_THREAD_ID.reset(thread_token)
                agent.CURRENT_USER_REQUEST.reset(request_token)

        self.assertIn("未在已保存的历史聊天线程中找到匹配消息", result)
        self.assertNotIn("请继续整理昨天的战略周报", result)
        self.assertNotIn("正在分析请求", result)

    def test_ambiguous_input_does_not_disable_available_capabilities(self) -> None:
        captured: dict[str, object] = {}

        class FakeAgent:
            def stream(self, inputs, stream_mode=None, config=None):
                captured["message"] = inputs["messages"][0][1]
                yield agent.AIMessageChunk(content="请补充说明。"), {}

        def fake_get_agent(**kwargs):
            captured["allow_web_search"] = kwargs.get("allow_web_search")
            return FakeAgent()

        with mock.patch("agent.get_agent", side_effect=fake_get_agent):
            list(agent.stream_agent("富裕", force_web_search=True, active_thread_id="thread-now"))

        self.assertTrue(captured["allow_web_search"])
        self.assertEqual(captured["message"], "富裕")

    def test_disabled_web_search_prompt_does_not_explain_toggle_state(self) -> None:
        captured: dict[str, object] = {}

        class FakeLLM:
            def __init__(self, **_kwargs):
                pass

        def fake_create_react_agent(_llm, tools, prompt):
            captured["tools"] = {tool.name for tool in tools}
            captured["prompt"] = prompt
            return object()

        with (
            mock.patch("agent.ChatDeepSeek", FakeLLM),
            mock.patch("agent.create_react_agent", side_effect=fake_create_react_agent),
        ):
            agent.get_agent(allow_web_search=False)

        self.assertNotIn("web_search", captured["tools"])
        self.assertNotIn("read_webpage", captured["tools"])
        prompt = str(captured["prompt"])
        self.assertNotIn("web_search", prompt)
        self.assertNotIn("read_webpage", prompt)
        self.assertNotIn("联网搜索已关闭", prompt)
        self.assertNotIn("请打开联网搜索", prompt)
        self.assertNotIn("打开联网搜索", prompt)
        self.assertNotIn("工具开关状态", prompt)
        self.assertIn("自主选择可用的", prompt)
        self.assertNotIn("必须双检索", prompt)

    def test_disabled_web_search_does_not_rewrite_model_output(self) -> None:
        class FakeAgent:
            def stream(self, inputs, stream_mode=None):
                yield agent.AIMessageChunk(content="联网搜索已关闭，"), {}
                yield agent.AIMessageChunk(content="本轮不会调用 web_search 或 read_webpage。"), {}
                yield agent.AIMessageChunk(content="中国移动收入趋势如下。"), {}

        with mock.patch("agent.get_agent", return_value=FakeAgent()):
            events = list(agent.stream_agent("搜一下移动收入趋势", force_web_search=False))

        text = "".join(event.get("text", "") for event in events if event.get("type") == "delta")
        self.assertEqual(
            text,
            "联网搜索已关闭，本轮不会调用 web_search 或 read_webpage。中国移动收入趋势如下。",
        )


class AgentForecastDatasetBoundaryTests(unittest.TestCase):
    def test_forecast_path_uses_latest_visible_quarterly_package(self) -> None:
        token = agent.SELECTED_DATASET_IDS.set({"quarterly_competitor_metrics_2026-06-18"})
        try:
            path = agent._selected_quarterly_metrics_path()
        finally:
            agent.SELECTED_DATASET_IDS.reset(token)

        self.assertIsNotNone(path)
        self.assertEqual(path.parent.name, "quarterly_competitor_metrics_2026-06-18")

    def test_forecast_path_rejects_superseded_quarterly_package_even_if_selected(self) -> None:
        token = agent.SELECTED_DATASET_IDS.set({"quarterly_competitor_metrics_2026-06-17"})
        try:
            path = agent._selected_quarterly_metrics_path()
        finally:
            agent.SELECTED_DATASET_IDS.reset(token)

        self.assertIsNone(path)


class WeeklyReportFailOpenWebTests(unittest.TestCase):
    def test_audio_failure_is_a_warning_after_weekly_docx_succeeds(self) -> None:
        events: list[dict] = []

        class FakeHandler:
            def send_response(self, _status):
                pass

            def send_header(self, _name, _value):
                pass

            def end_headers(self):
                pass

        class ReportProcess:
            pid = 101
            returncode = 0
            stdout = iter(["[生成成功] 最终输出文件：\n"])

            def wait(self):
                return 0

        class AudioProcess:
            pid = 102
            returncode = 0

            def communicate(self):
                return json.dumps({"ok": False, "error": "tts offline"}), ""

        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "7月24日周报.docx"
            report_path.write_bytes(b"docx")
            with (
                mock.patch.object(
                    web_app.subprocess,
                    "Popen",
                    side_effect=[ReportProcess(), AudioProcess()],
                ),
                mock.patch.object(
                    web_app,
                    "build_status",
                    return_value={"outputs": [{"name": report_path.name}]},
                ),
                mock.patch.object(web_app, "latest_output_path", return_value=report_path),
                mock.patch.object(
                    web_app,
                    "write_sse",
                    side_effect=lambda _handler, payload: events.append(payload),
                ),
            ):
                web_app._ORIGINAL_STREAM_REPORT_GENERATION(
                    FakeHandler(),
                    "generate_weekly_report.py",
                    "weekly",
                )

        done = next(event for event in reversed(events) if event.get("type") == "done")
        self.assertTrue(done["ok"])
        self.assertTrue(done["reportGenerated"])
        self.assertTrue(done["completedWithWarnings"])
        self.assertIn("周报已生成", done["message"])
        self.assertIn("tts offline", done["warning"])

    def test_audio_failure_is_a_warning_after_performance_docx_succeeds(self) -> None:
        events: list[dict] = []

        class FakeHandler:
            def send_response(self, _status):
                pass

            def send_header(self, _name, _value):
                pass

            def end_headers(self):
                pass

        class ReportProcess:
            pid = 201
            returncode = 0
            stdout = iter(["[生成成功] 最终输出文件：\n"])

            def wait(self):
                return 0

        class AudioProcess:
            pid = 202
            returncode = 0

            def communicate(self):
                return json.dumps({"ok": False, "error": "tts offline"}), ""

        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "7月24日运营商业绩摘要.docx"
            report_path.write_bytes(b"docx")
            with (
                mock.patch.object(
                    web_app.subprocess,
                    "Popen",
                    side_effect=[ReportProcess(), AudioProcess()],
                ),
                mock.patch.object(
                    web_app,
                    "build_status",
                    return_value={"outputs": [{"name": report_path.name}]},
                ),
                mock.patch.object(web_app, "latest_output_path", return_value=report_path),
                mock.patch.object(
                    web_app,
                    "write_sse",
                    side_effect=lambda _handler, payload: events.append(payload),
                ),
            ):
                web_app._ORIGINAL_STREAM_REPORT_GENERATION(
                    FakeHandler(),
                    "generate_carrier_performance_report.py",
                    "carrier-performance",
                )

        done = next(event for event in reversed(events) if event.get("type") == "done")
        self.assertTrue(done["ok"])
        self.assertTrue(done["reportGenerated"])
        self.assertTrue(done["completedWithWarnings"])
        self.assertIn("业绩摘要已生成", done["message"])
        self.assertIn("tts offline", done["warning"])

    def test_sync_weekly_endpoint_allows_long_report_generation(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["python", "generate_weekly_report.py"],
            returncode=0,
            stdout="ok",
            stderr="",
        )
        with (
            mock.patch.object(web_app.subprocess, "run", return_value=completed) as run,
            mock.patch.object(web_app, "build_status", return_value={"outputs": []}),
        ):
            result = web_app.run_report_generation()

        self.assertTrue(result["ok"])
        self.assertEqual(run.call_args.kwargs["timeout"], 900)

    def test_sync_performance_endpoint_allows_long_report_generation(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["python", "generate_carrier_performance_report.py"],
            returncode=0,
            stdout="ok",
            stderr="",
        )
        with (
            mock.patch.object(web_app.subprocess, "run", return_value=completed) as run,
            mock.patch.object(web_app, "build_status", return_value={"outputs": []}),
        ):
            result = web_app.run_carrier_performance_generation()

        self.assertTrue(result["ok"])
        self.assertEqual(run.call_args.kwargs["timeout"], 900)


class IntelligenceEntityScrollTests(unittest.TestCase):
    def test_entity_details_use_local_scroll_without_disclosure_button(self) -> None:
        app = (Path(__file__).parent / "web/static/app.js").read_text(encoding="utf-8")
        styles = (Path(__file__).parent / "web/static/styles.css").read_text(encoding="utf-8")

        self.assertIn('entity.ai_summary?.analysis || entity.analysis', app)
        self.assertIn('class="intelligence-entity-components"', app)
        self.assertNotIn('data-intelligence-disclosure', app)
        self.assertIn('grid-template-rows: auto auto minmax(44px, 1fr);', styles)
        self.assertIn('overflow-y: auto;', styles)
        self.assertIn('overscroll-behavior: contain;', styles)

    def test_macro_governance_uses_mixed_unit_visual_encodings(self) -> None:
        app = (Path(__file__).parent / "web/static/app.js").read_text(encoding="utf-8")
        styles = (Path(__file__).parent / "web/static/styles.css").read_text(encoding="utf-8")

        self.assertIn('if (visual === "governance")', app)
        self.assertIn('class="intelligence-viz intelligence-viz-governance"', app)
        self.assertIn('每格代表 10 亿港元', app)
        self.assertIn('每格代表 100 宗投诉', app)
        self.assertIn('人口覆盖程度', app)
        self.assertIn('每格代表 1,000 MHz', app)
        self.assertIn('.intelligence-viz-governance {', styles)
        self.assertIn('background: conic-gradient(', styles)


if __name__ == "__main__":
    unittest.main()

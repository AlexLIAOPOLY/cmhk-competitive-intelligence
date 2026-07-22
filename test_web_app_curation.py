from __future__ import annotations

import base64
import os
import subprocess
import json
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

import agent
import web_app


class ReportFileNameTests(unittest.TestCase):
    def test_report_file_pattern_accepts_new_and_legacy_as_of_names(self) -> None:
        self.assertIsNotNone(web_app.REPORT_FILE_RE.fullmatch("7月31日周报（截至7月22日）.docx"))
        self.assertIsNotNone(web_app.REPORT_FILE_RE.fullmatch("7月31日周报（草稿，截至7月22日）.docx"))
        self.assertIsNotNone(web_app.REPORT_FILE_RE.fullmatch("7月31日周报.docx"))


class ChatThreadPersistenceTests(unittest.TestCase):
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

    def test_audio_validation_rejects_unsupported_data_urls(self) -> None:
        with self.assertRaisesRegex(ValueError, "只支持"):
            web_app.transcribe_chat_audio({"audio": "data:text/plain;base64,SGVsbG8="})


class FrontendCitationRenderingTests(unittest.TestCase):
    def test_voice_dictation_uses_company_stt_and_auto_submits_transcript(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        markup = (web_app.ROOT / "web/static/index.html").read_text(encoding="utf-8")

        self.assertIn('id="voiceInputButton"', markup)
        self.assertLess(markup.index('id="chatModelPicker"'), markup.index('id="voiceInputButton"'))
        self.assertIn("navigator.mediaDevices.getUserMedia", app)
        self.assertIn("new MediaRecorder", app)
        self.assertIn('fetch("/api/chat-audio-transcribe"', app)
        self.assertIn("els.chatForm.requestSubmit();", app)

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

    def test_force_web_search_injects_tool_instruction(self) -> None:
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
        self.assertIn("必须调用 `web_search`", captured["message"])
        self.assertIn("尽量调用 `search_local_reports`", captured["message"])
        self.assertIn("用户问题：搜一下中国移动最新收入", captured["message"])
        self.assertEqual(captured["stream_mode"], "messages")

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
        self.assertEqual(
            captured["tools"],
            {"get_system_status", "list_crawl_runs", "get_crawl_settings_summary"},
        )
        self.assertIn("语言与可见推理稳定性", captured["prompt"])

    def test_dynamic_tool_routing_keeps_every_tool_available_by_intent(self) -> None:
        default_names = {tool.name for tool in agent._agent_tools(allow_web_search=True)}
        targeted_names = {
            tool.name
            for tool in agent._agent_tools(
                allow_web_search=False,
                user_message="请生成周报，再查看系统状态和最近爬虫日志。",
            )
        }

        self.assertIn("web_search", default_names)
        self.assertIn("trigger_report_generation", targeted_names)
        self.assertIn("get_system_status", targeted_names)
        self.assertIn("list_crawl_runs", targeted_names)

    def test_gateway_corruption_detector_catches_known_failure_shapes(self) -> None:
        samples = [
            "<｜DSML｜tool_calls><｜DSML｜invoke name=\"get_system_status\">",
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
        self.assertFalse(agent._looks_like_incomplete_model_answer("这是清晰、完整的中文分析结论。"))
        self.assertFalse(
            agent._looks_like_incomplete_model_answer(
                "结论已经完整。\n<suggestions>继续分析|查看来源|对比趋势</suggestions>"
            )
        )

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

    def test_markdown_limiter_streams_plain_text_but_buffers_table_rows(self) -> None:
        limiter = agent.MarkdownTableLimiter()
        self.assertEqual(limiter.feed("普通正文第一段"), "普通正文第一段")
        self.assertEqual(limiter.feed("继续流式返回"), "继续流式返回")
        self.assertEqual(limiter.feed("|列一|列二"), "")
        self.assertEqual(limiter.feed("|\n"), "|列一|列二|\n")

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

    def test_plain_greeting_uses_model_with_history_as_background_only(self) -> None:
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
        self.assertIn("普通寒暄", captured["message"])
        self.assertIn("中国铁塔", captured["message"])
        self.assertIn("只能作为背景", captured["message"])
        self.assertIn("不能自动把历史主题补全为本轮问题", captured["message"])
        self.assertNotIn("quarterly_competitor_metrics", captured["message"])
        self.assertNotIn("长期记忆召回", captured["message"])

    def test_user_profile_question_routes_to_memory_and_history_without_dataset_guessing(self) -> None:
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
        self.assertIn("询问自己的身份、偏好、兴趣或用户画像", captured["message"])
        self.assertIn("先调用 `search_agent_memory`", captured["message"])
        self.assertIn("再调用 `search_chat_history`", captured["message"])
        self.assertIn("明确证据", captured["message"])
        self.assertIn("基于历史用户问题的推断", captured["message"])
        self.assertIn("不要根据当前项目、当前数据库选择或上一次问题断言用户身份", captured["message"])
        self.assertIn("中国铁塔", captured["message"])
        self.assertNotIn("quarterly_competitor_metrics", captured["message"])
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
        self.assertIn("goal_readiness_audits", prompt)
        self.assertIn("superseded", prompt)
        self.assertIn("目标级审计优先", prompt)

    def test_disabled_web_search_notice_is_removed_from_stream(self) -> None:
        class FakeAgent:
            def stream(self, inputs, stream_mode=None):
                yield agent.AIMessageChunk(content="联网搜索已关闭，"), {}
                yield agent.AIMessageChunk(content="本轮不会调用 web_search 或 read_webpage。"), {}
                yield agent.AIMessageChunk(content="中国移动收入趋势如下。"), {}

        with mock.patch("agent.get_agent", return_value=FakeAgent()):
            events = list(agent.stream_agent("搜一下移动收入趋势", force_web_search=False))

        text = "".join(event.get("text", "") for event in events if event.get("type") == "delta")
        self.assertEqual(text, "中国移动收入趋势如下。")
        self.assertNotIn("联网搜索已关闭", text)
        self.assertNotIn("web_search", text)


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


if __name__ == "__main__":
    unittest.main()

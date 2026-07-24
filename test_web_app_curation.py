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
    def test_new_chat_messages_record_created_and_completed_times(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        self.assertIn('createdAt: new Date().toISOString()', app)
        self.assertIn('assistantHistoryEntry.completedAt = new Date().toISOString()', app)
        self.assertIn('threadId: state.activeThreadId', app)

    def test_process_filter_preserves_complete_dependent_sentences(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        start = app.index("const ASSISTANT_PROCESS_MARKERS")
        end = app.index("function extractAssistantProcessLines", start)
        snippet = app[start:end] + "\n" + (
            "console.log(JSON.stringify(["
            "removeProcessClauses('请进一步说明，以便我为您准确检索和提供信息。'),"
            "removeProcessClauses('明确主体后，我将检索本地资料并整理路线图。')"
            "]));"
        )
        completed = subprocess.run(
            ["node", "-e", snippet],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            json.loads(completed.stdout),
            [
                "请进一步说明，以便我为您准确检索和提供信息。",
                "明确主体后，我将检索本地资料并整理路线图。",
            ],
        )

    def test_control_filter_never_turns_complete_prose_into_a_dangling_comma(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        start = app.index("const ASSISTANT_PROCESS_MARKERS")
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

    def test_voice_dictation_uses_company_stt_and_auto_submits_transcript(self) -> None:
        app = (web_app.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        markup = (web_app.ROOT / "web/static/index.html").read_text(encoding="utf-8")

        self.assertIn('id="voiceInputButton"', markup)
        self.assertLess(markup.index('id="chatModelPicker"'), markup.index('id="voiceInputButton"'))
        self.assertIn("navigator.mediaDevices.getUserMedia", app)
        self.assertIn("new MediaRecorder", app)
        self.assertIn('fetch("/api/chat-audio-transcribe"', app)
        self.assertIn("els.chatForm.requestSubmit();", app)

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
        self.assertIn(".chat-model-menu { position: absolute; right: -72px;", styles)
        self.assertIn("border-radius: 50%", styles)
        self.assertIn("function renderChatSubmitState()", app)
        self.assertIn("els.chatSubmitButton.disabled = !state.chatBusy && !ready", app)

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
        self.assertIn("必须同时调用 `search_local_reports` 和 `web_search`", captured["message"])
        self.assertIn("两者缺一不可", captured["message"])
        self.assertIn("本地与联网数据不一致", captured["message"])
        self.assertIn("无法判断时保留冲突", captured["message"])
        self.assertIn("用户问题：搜一下中国移动最新收入", captured["message"])
        self.assertEqual(captured["stream_mode"], "messages")

    def test_web_enabled_system_prompt_requires_dual_search_for_data(self) -> None:
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
            )

        prompt = str(captured["prompt"])
        self.assertIn("涉及数据时必须双检索", prompt)
        self.assertIn("必须同时调用 `search_local_reports` 和 `web_search`，缺一不可", prompt)
        self.assertIn("即使其中一侧无相关结果或证据不足，也必须实际完成该侧检索", prompt)
        self.assertIn("本地与联网数据不一致", prompt)
        self.assertIn("不得静默选边", prompt)
        self.assertIn("web_search", captured["tools"])
        self.assertIn("search_local_reports", captured["tools"])

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

    def test_system_prompt_requires_charts_for_trends_and_multiple_data_groups(self) -> None:
        captured: dict[str, object] = {}

        class FakeLLM:
            def __init__(self, **kwargs):
                captured["llm_kwargs"] = kwargs

        def fake_create_react_agent(_llm, tools, prompt):
            captured["prompt"] = str(prompt)
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
        self.assertIn("数据趋势与多组数据必须画图", prompt)
        self.assertIn("必须在完成数据检索、原文读取和口径核验后调用 `render_python_chart`", prompt)
        self.assertIn("不能只给文字或表格", prompt)
        self.assertIn("无法生成可靠图表", prompt)
        self.assertIn("绝对不得补造数据点", prompt)

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
        self.assertEqual(
            captured["tools"],
            {"search_chat_history", "get_system_status", "list_crawl_runs", "get_crawl_settings_summary"},
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

    def test_completion_contract_catches_long_semantic_cutoff_after_full_stop(self) -> None:
        seemingly_finished = (
            "这段回答虽然以句号结束，但它只写完了用户要求的第一部分。"
            "模型有时会在网关或上下文限制下提前停止，finish_reason 仍可能被记录成 stop。"
            "因此不能只根据最后一个标点判断整份回答是否已经完成，还必须观察应用约定的完成标记。"
            "这里再补足一些正文长度，用来模拟真实的长回答在某一段末尾突然结束。"
        )

        self.assertTrue(
            agent._looks_like_incomplete_model_answer(
                seemingly_finished,
                require_completion_footer=True,
            )
        )
        self.assertFalse(
            agent._looks_like_incomplete_model_answer(
                seemingly_finished
                + '\n<suggestions>["继续分析", "查看来源", "对比趋势"]</suggestions>',
                require_completion_footer=True,
            )
        )
        self.assertFalse(
            agent._looks_like_incomplete_model_answer(
                "4。",
                require_completion_footer=True,
            )
        )

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

    def test_existing_three_ai_suggestions_do_not_add_an_extra_model_call(self) -> None:
        answer = '完整回答。\n<suggestions>["具体问题一？", "具体问题二？", "具体问题三？"]</suggestions>'
        with mock.patch("agent.ChatDeepSeek", side_effect=AssertionError("不应额外调用模型")):
            items, usage, source = self._real_follow_up_generator("原问题", answer)

        self.assertEqual(items, ["具体问题一？", "具体问题二？", "具体问题三？"])
        self.assertEqual(usage["totalTokens"], 0)
        self.assertEqual(source, "answer")

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

    def test_explicit_structure_validator_requires_all_requested_sections_and_summary(self) -> None:
        request = "写约800字分析，分成五节，每节完整收束，最后总结三点。"
        complete = (
            "## 一、背景\n第一节完整。\n## 二、网络\n第二节完整。\n"
            "## 三、业务\n第三节完整。\n## 四、产业\n第四节完整。\n"
            "## 五、风险\n第五节完整。\n## 总结三点\n"
            "- 方向确定。\n- 节奏受制。\n- 香港有机会。"
        )

        self.assertTrue(agent._answer_satisfies_explicit_structure(request, complete))
        self.assertFalse(
            agent._answer_satisfies_explicit_structure(
                request,
                complete.replace("## 五、风险\n第五节完整。\n", ""),
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

    def test_model_retries_when_long_answer_ends_cleanly_without_completion_footer(self) -> None:
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

        self.assertIs(result, complete_result)
        self.assertEqual(generate.call_count, 2)

    def test_repaired_complete_answer_gets_footer_without_being_discarded(self) -> None:
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

        self.assertIs(result, repaired_result)
        self.assertEqual(generate.call_count, 2)
        self.assertTrue(repaired_message.content.startswith(repaired_text))
        self.assertTrue(repaired_message.content.endswith("</suggestions>"))

    def test_length_finish_is_accepted_when_requested_structure_is_complete(self) -> None:
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
        self.assertEqual(generate.call_count, 1)
        self.assertTrue(complete_message.content.endswith("</suggestions>"))

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
        self.assertIn("1200 个中文字符", retry_text)

    def test_search_local_reports_stops_after_three_calls(self) -> None:
        token = agent.TOOL_RUN_STATE.set({"counts": {}})
        try:
            with mock.patch("agent.retrieve_context", return_value=[]):
                for _ in range(3):
                    self.assertEqual(
                        agent.search_local_reports.invoke({"query": "现金流"}),
                        "没有找到相关的本地报告信息。",
                    )
                limited = agent.search_local_reports.invoke({"query": "现金流"})
        finally:
            agent.TOOL_RUN_STATE.reset(token)

        self.assertIn("达到本轮调用上限（3 次）", limited)

    def test_large_retrieval_tools_have_bounded_call_limits(self) -> None:
        token = agent.TOOL_RUN_STATE.set({
            "counts": {"web_search": 3, "read_local_reference": 2}
        })
        try:
            web_limited = agent.web_search.invoke({"query": "云厂商现金流"})
            reference_limited = agent.read_local_reference.invoke({
                "source": "agent_knowledge/cloud_vendor_database/README.md"
            })
        finally:
            agent.TOOL_RUN_STATE.reset(token)

        self.assertIn("web_search 已达到本轮调用上限（3 次）", web_limited)
        self.assertIn("read_local_reference 已达到本轮调用上限（2 次）", reference_limited)

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
                "agent._finalize_after_tool_limit",
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
                "agent._finalize_after_tool_limit",
                return_value=(final, {"inputTokens": 5, "outputTokens": 8, "totalTokens": 13}),
            ) as finalize,
        ):
            events = list(agent.stream_agent("请完成复杂分析", thinking_enabled=False))

        answer = "".join(event.get("text", "") for event in events if event.get("type") == "delta")
        self.assertEqual(answer, final)
        self.assertEqual(finalize.call_count, 1)
        self.assertFalse(any(event.get("type") == "error" for event in events))
        self.assertEqual(events[-1].get("type"), "done")

    def test_agent_graph_has_bounded_recursion_limit(self) -> None:
        captured: dict[str, object] = {}

        class FakeAgent:
            def stream(self, inputs, stream_mode=None, config=None):
                captured["config"] = config
                return iter(())

        list(agent._stream_agent_events(FakeAgent(), {"messages": []}))

        self.assertEqual(captured["config"], {"recursion_limit": 20})

    def test_tool_limit_finishes_once_instead_of_looping_until_empty_done(self) -> None:
        class FakeAgent:
            def stream(self, inputs, stream_mode=None, config=None):
                yield agent.ToolMessage(
                    content=(
                        "search_local_reports 已达到本轮调用上限（6 次），"
                        "请停止继续调用该工具，直接基于已经返回的资料给出结论。"
                    ),
                    tool_call_id="call_limit",
                ), {}
                raise AssertionError("工具达到上限后不应继续消费 Agent 循环")

        final = (
            '现有资料不足以完成两周对比，请指定主体和日期。\n'
            '<suggestions>["指定竞对主体", "指定起止日期", "查看可用数据集"]</suggestions>'
        )
        with (
            mock.patch("agent.get_agent", return_value=FakeAgent()),
            mock.patch(
                "agent._finalize_after_tool_limit",
                return_value=(final, {"inputTokens": 10, "outputTokens": 20, "totalTokens": 30}),
            ) as finalize,
        ):
            events = list(agent.stream_agent("对比最近两周的竞对动态变化", thinking_enabled=False))

        answer = "".join(event.get("text", "") for event in events if event.get("type") == "delta")
        self.assertEqual(answer, final)
        self.assertEqual(finalize.call_count, 1)
        self.assertFalse(any(event.get("type") == "error" for event in events))
        self.assertEqual(events[-1].get("type"), "done")

    def test_three_identical_tool_calls_are_finalized_without_consuming_a_fourth(self) -> None:
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
                raise AssertionError("第三次相同调用后应停止 Agent 循环")

        final = '已根据现有结果完成回答。\n<suggestions>["追问一", "追问二", "追问三"]</suggestions>'
        with (
            mock.patch("agent.get_agent", return_value=FakeAgent()),
            mock.patch(
                "agent._finalize_after_tool_limit",
                return_value=(final, {"inputTokens": 1, "outputTokens": 2, "totalTokens": 3}),
            ) as finalize,
        ):
            events = list(agent.stream_agent("测试重复调用保护", thinking_enabled=False))

        starts = [event for event in events if event.get("type") == "tool_call_start"]
        self.assertEqual(len(starts), 3)
        self.assertEqual(finalize.call_count, 1)
        self.assertEqual(events[-1].get("type"), "done")

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

    def test_ambiguous_short_input_requires_history_probe_but_complete_math_does_not(self) -> None:
        self.assertTrue(agent._should_probe_chat_history_for_ambiguity("富裕"))
        self.assertTrue(agent._should_probe_chat_history_for_ambiguity("不行"))
        self.assertTrue(agent._should_probe_chat_history_for_ambiguity("那个呢"))
        self.assertFalse(agent._should_probe_chat_history_for_ambiguity("2加2等于多少？"))
        self.assertFalse(agent._should_probe_chat_history_for_ambiguity("分析中国移动收入"))
        self.assertFalse(agent._should_probe_chat_history_for_ambiguity("你好"))

    def test_ambiguous_history_probe_excludes_current_turn_and_falls_back_to_recent_history(self) -> None:
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
            ambiguous_token = agent.AMBIGUOUS_HISTORY_PROBE.set(True)
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
                agent.AMBIGUOUS_HISTORY_PROBE.reset(ambiguous_token)

        self.assertIn("关键词未直接命中", result)
        self.assertIn("请继续整理昨天的战略周报", result)
        self.assertNotIn("正在分析请求", result)

    def test_stream_marks_ambiguous_input_for_history_before_clarification(self) -> None:
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

        self.assertFalse(captured["allow_web_search"])
        self.assertIn("必须先调用 `search_chat_history`", captured["message"])
        self.assertIn("查不到相关历史后才能简洁追问", captured["message"])

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

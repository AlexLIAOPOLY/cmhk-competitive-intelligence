from __future__ import annotations

import os
import subprocess
import json
import tempfile
import unittest
from unittest import mock

import agent
import web_app


class FrontendCitationRenderingTests(unittest.TestCase):
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
        merge_end = app.index("function appendActionConfirmation", merge_start)
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

    def test_completed_reasoning_block_collapses_when_next_stream_block_arrives(self) -> None:
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

        self.assertIn('panel?.classList.contains("model-reasoning")', collapse_helper)
        self.assertIn("panel.open = false", collapse_helper)
        self.assertIn("collapseLatestModelReasoning(node)", append_helper)
        self.assertIn("collapseLatestModelReasoning(node)", text_helper)

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
const end = app.indexOf('function appendActionConfirmation');
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

        self.assertEqual(events[0]["type"], "delta")
        self.assertIn("我是小竞AI", events[0]["text"])
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

        self.assertEqual(events[0]["type"], "delta")
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

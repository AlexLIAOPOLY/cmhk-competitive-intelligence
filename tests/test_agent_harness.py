import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from langchain_core.messages import AIMessage
from cmhk.intelligence.agent_harness import (
    TruncatedModelOutput, assert_complete, run_durable_agent,
)


class AgentHarnessTests(unittest.TestCase):
    def test_valid_json_with_length_is_rejected_before_acceptance(self):
        with self.assertRaises(TruncatedModelOutput):
            assert_complete(AIMessage(content='{"accept":true}',
                                      response_metadata={"finish_reason": "length"}))

    def test_harness_retries_then_reuses_only_completed_decision(self):
        calls = []
        def execute(attempt):
            calls.append(attempt)
            if attempt == 0:
                raise TruncatedModelOutput("incomplete")
            return {"decision": "review"}
        with tempfile.TemporaryDirectory() as directory:
            args = dict(namespace="test", identity={"news_id": "one"}, directory=Path(directory))
            self.assertEqual(run_durable_agent(**args, execute=execute), {"decision": "review"})
            self.assertEqual(run_durable_agent(**args, execute=lambda _: self.fail("replayed")),
                             {"decision": "review"})
        self.assertEqual(calls, [0, 1])

    def test_permanent_truncation_never_becomes_completed_checkpoint(self):
        calls = []
        def fail(attempt):
            calls.append(attempt)
            raise TruncatedModelOutput("incomplete")
        with tempfile.TemporaryDirectory() as directory:
            args = dict(namespace="test", identity="same", directory=Path(directory))
            with self.assertRaises(TruncatedModelOutput):
                run_durable_agent(**args, execute=fail, max_attempts=2)
            self.assertEqual(run_durable_agent(**args, execute=lambda _: {"ok": True}), {"ok": True})
        self.assertEqual(calls, [0, 1])

    def test_actual_process_exit_and_restart_release_lock_and_resume(self):
        template = '''
import os
from pathlib import Path
from cmhk.intelligence.agent_harness import run_durable_agent
def execute(attempt):
    ACTION
result = run_durable_agent(namespace="restart", identity="one", directory=Path(DIRECTORY), execute=execute)
print(result["ok"])
'''
        with tempfile.TemporaryDirectory() as directory:
            code = template.replace("DIRECTORY", repr(directory))
            crashed = subprocess.run([sys.executable, "-c", code.replace("ACTION", "os._exit(17)")], capture_output=True)
            self.assertEqual(crashed.returncode, 17)
            resumed = subprocess.run([sys.executable, "-c", code.replace("ACTION", 'return {"ok": True}')],
                                     capture_output=True, text=True)
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            cached = subprocess.run([sys.executable, "-c", code.replace("ACTION", "raise AssertionError('must not replay')")],
                                    capture_output=True, text=True)
            self.assertEqual(cached.returncode, 0, cached.stderr)
            self.assertEqual(cached.stdout.strip(), "True")

    def test_changed_input_is_not_a_resume_hit(self):
        with tempfile.TemporaryDirectory() as directory:
            for value in (1, 2):
                self.assertEqual(run_durable_agent(namespace="test", identity=value,
                    directory=Path(directory), execute=lambda _: {"value": value}), {"value": value})

    def test_selection_entry_retries_parseable_truncation_and_resume_skips_model(self):
        from cmhk.intelligence import news_selection_agent as selection
        payload = {"decisions": [{"news_id": "one", "app_status": "接受",
            "weekly_status": "不接受", "app_confidence": 0.9, "weekly_confidence": 0.8,
            "reason": "真实输入的测试决策"}]}
        responses = [SimpleNamespace(content=json.dumps(payload), response_metadata={"finish_reason": reason})
                     for reason in ("length", "stop")]
        budgets = []
        def factory(**kwargs):
            budgets.append(kwargs["max_tokens"])
            model = mock.Mock()
            model.invoke.side_effect = lambda messages: responses.pop(0)
            return model
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(selection, "STATE_PATH", Path(directory) / "state.json"), \
                mock.patch.object(selection, "load_ai_config", return_value={"base_url": "https://example.test"}), \
                mock.patch.object(selection, "_model_routes", return_value=[("test-model", "dummy")]), \
                mock.patch.object(selection, "ChatDeepSeek", side_effect=factory):
            session = {"calls": 0, "preferences": False}
            token = selection._MODEL_SESSION.set(session)
            try:
                for _ in range(2):
                    self.assertEqual(selection._invoke_langchain([], [{"news_id": "one"}])[0], payload)
                self.assertEqual(session["calls"], 2)
            finally:
                selection._MODEL_SESSION.reset(token)
        self.assertEqual(budgets, [1500, 3000])

    def test_news_entry_rejects_parseable_truncation_then_resumes(self):
        import strategic_briefing as briefing
        opener = mock.Mock()
        responses = []
        for reason in ("length", "stop"):
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps({"choices": [
                {"finish_reason": reason, "message": {"content": '{"ok":true}'}}]}).encode()
            responses.append(response)
        opener.open.side_effect = responses
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(briefing, "DATA_DIR", Path(directory)), \
                mock.patch.object(briefing, "load_ai_config", return_value={"base_url": "https://example.test", "api_key": "dummy"}), \
                mock.patch.object(briefing, "build_opener", return_value=opener), \
                mock.patch.object(briefing, "wait_for_internal_ai_slot"):
            for _ in range(2):
                self.assertEqual(briefing._call_internal_ai("system", "user",
                    response_format={"type": "json_object"}), {"ok": True})
        bodies = [json.loads(call.args[0].data) for call in opener.open.call_args_list]
        self.assertEqual([body["max_tokens"] for body in bodies], [8000, 16000])
        self.assertEqual(bodies[1]["cache"], {"no-cache": True, "no-store": True})

    def test_insights_resume_after_app_cache_write_failure_without_new_inference(self):
        from cmhk.intelligence import market_news_insights as insights
        item = {"id": "one", "sourceDate": "2026-09-05", "source": "测试来源",
                "category": "测试", "title": "测试新闻", "summary": "仅用于测试"}
        answer = {"insights": [{"title": "测试洞察", "body": "这是一条仅用于接口保护测试的分析文字。",
                                  "evidenceIds": ["one"]} for _ in range(4)]}
        responses = []
        for reason in ("length", "stop"):
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps({"choices": [
                {"finish_reason": reason, "message": {"content": json.dumps(answer)}}]}).encode()
            responses.append(response)
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch("cmhk.intelligence.competitor_map.build_competitor_intelligence_map", return_value={"items": [item]}), \
                mock.patch.object(insights, "load_ai_config", return_value={"base_url": "https://example.test", "api_key": "dummy", "model": "test"}), \
                mock.patch.object(insights, "is_internal_ai_base_url", return_value=True), \
                mock.patch.object(insights, "wait_for_internal_ai_slot"), \
                mock.patch.object(insights, "open_llm_request", side_effect=responses) as invoke:
            with mock.patch.object(insights, "_write_cache", side_effect=OSError("simulated disk failure")):
                with self.assertRaises(OSError):
                    insights.generate_market_news_insights(Path(directory))
            result = insights.generate_market_news_insights(Path(directory))
            self.assertEqual(len(result["insights"]), 4)
            self.assertEqual(invoke.call_count, 2)


if __name__ == "__main__":
    unittest.main()

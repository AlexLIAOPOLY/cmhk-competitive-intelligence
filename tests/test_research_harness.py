import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from data_curation.research_harness import ResearchHarness, TruncatedModelOutput, assert_complete
from data_curation.research_plan import research_plan
from data_curation.six_agent_research import run_assignment, run_research, validate_fact, metric_value_is_bound


class ToolModel(FakeMessagesListChatModel):
    bound_tools: list[str] = []

    def _get_ls_params(self, *args, **kwargs):
        return {"ls_provider": "deepseek", "ls_model_name": "test", "ls_model_type": "chat"}

    def bind_tools(self, tools, **kwargs):
        self.bound_tools = [tool.name if hasattr(tool, "name") else tool.get("name") for tool in tools]
        return self


TASK = {"key": "hong-kong", "title": "香港研究 Agent", "purpose": "香港公司研究", "companies": ["HKT"]}


def submission(reason="未找到"):
    return AIMessage(content="", tool_calls=[{"name": "submit_metric", "args": {
        "status": "missing", "reason": reason}, "id": "submit-1", "type": "tool_call"}],
        response_metadata={"finish_reason": "tool_calls"})


class ResearchHarnessTests(unittest.TestCase):
    def test_exactly_six_agents_cover_catalog_once(self):
        plan = research_plan()
        self.assertEqual(len(plan), 6)
        self.assertEqual(len({company for task in plan for company in task["companies"]}), 41)

    def test_length_and_invalid_arguments_rejected(self):
        for message in [AIMessage(content='{"value":', response_metadata={"finish_reason": "length"}),
                        AIMessage(content="", invalid_tool_calls=[{"name": "submit_metric", "args": '{"value":', "id": "bad", "error": "incomplete"}])]:
            with self.assertRaises(TruncatedModelOutput):
                assert_complete(message)

    def test_real_harness_retries_truncation_before_tool_and_submits_once(self):
        bad = submission("不应保存")
        bad.response_metadata["finish_reason"] = "length"
        model = ToolModel(responses=[bad, submission("完整提交")])
        saved, events = [], []
        harness = ResearchHarness(TASK, model, lambda *event: events.append(event), validate_fact)
        result = harness.extract("HKT", "收入", {}, saved.append)
        self.assertEqual(result["reason"], "完整提交")
        self.assertEqual(len(saved), 1)
        self.assertEqual(set(model.bound_tools), {"find_evidence", "read_evidence", "submit_metric"})
        self.assertEqual(len([event for event in events if event[0] == "model_response"]), 2)

    def test_exhausted_truncation_never_submits(self):
        bad = submission()
        bad.response_metadata["finish_reason"] = "length"
        saved = []
        harness = ResearchHarness(TASK, ToolModel(responses=[bad]), lambda *a: None, validate_fact)
        with self.assertRaises(TruncatedModelOutput):
            harness.extract("HKT", "收入", {}, saved.append)
        self.assertEqual(saved, [])

    def test_later_failure_keeps_previous_metric_and_resume_does_not_recrawl(self):
        checkpoints = []
        def emit(phase, message, data):
            if phase == "checkpoint":
                checkpoints.append(json.loads(json.dumps(data)))
        def collector(*args):
            return {"https://www.hkt.com": {"opened": True, "official": True, "text": "HKT revenue and EBITDA"}}, []
        responses = [submission(), AIMessage(content="no tool")]
        with patch("data_curation.workflow._company_expected_metrics", return_value=["收入", "EBITDA"]):
            report = run_assignment(TASK, emit, model_factory=lambda: ToolModel(responses=responses), collector=collector)
            self.assertEqual([item["status"] for item in report["reports"][0]["items"]], ["missing", "error"])
            self.assertEqual(checkpoints[0]["reports"][0]["pages"]["https://www.hkt.com"]["text"], "HKT revenue and EBITDA")
            with patch("data_curation.six_agent_research.collect_sources", side_effect=AssertionError("must not crawl")):
                resumed = run_assignment(TASK, emit, checkpoint=report,
                    model_factory=lambda: ToolModel(responses=[submission()]),
                    collector=lambda *args: self.fail("must reuse archived pages"))
            self.assertEqual(resumed["status"], "completed")
            self.assertEqual(len(resumed["reports"][0]["items"]), 2)

    def test_valid_fact_and_unopened_or_forged_context_fail_closed(self):
        text = "HKT reported 2025 results. Revenue was HK$ 35,000 million for 2025."
        pages = {"https://www.hkt.com/report": {"opened": True, "official": True, "text": text}}
        proposed = {"company": "HKT", "metric": "收入", "status": "verified", "value": "35,000",
                    "period": "2025", "unit": "million", "source_url": "https://www.hkt.com/report",
                    "quote": "Revenue was HK$ 35,000 million for 2025.", "context_quote": "HKT reported 2025 results."}
        self.assertEqual(validate_fact(proposed, "HKT", ["收入"], pages)["status"], "verified")
        self.assertEqual(validate_fact(proposed, "HKT", ["收入"], {})["status"], "conflict")
        self.assertEqual(validate_fact({**proposed, "context_quote": "HKT reported 2026 results."}, "HKT", ["收入"], pages)["status"], "conflict")

    def test_existing_run_cannot_be_overwritten_or_resumed_with_other_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "manifest.json").write_text(json.dumps({"run_id": "old", "plan": [TASK]}))
            for resume in [False, True]:
                with self.assertRaises(ValueError):
                    run_research(run_id="new", output_dir=path, assignments=[TASK], resume=resume)

    def test_default_plan_survives_json_roundtrip_and_resumes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            manifest = {"run_id": "same", "plan": research_plan(), "status": "completed", "accepted": 2}
            (path / "manifest.json").write_text(json.dumps(manifest))
            self.assertEqual(run_research(run_id="same", output_dir=path, resume=True)["accepted"], 2)

    def test_service_revenue_must_not_accept_total_revenue_from_same_passage(self):
        text = "Operating revenue was RMB538.0 billion. Communications service revenue was RMB350.4 billion."
        self.assertFalse(metric_value_is_bound("通信服务收入", "RMB538.0 billion", text))
        self.assertTrue(metric_value_is_bound("通信服务收入", "RMB350.4 billion", text))
        self.assertTrue(metric_value_is_bound("云收入", "$42.2 billion", "AWS segment sales increased 37% to $42.2 billion."))

    def test_passage_reference_copies_exact_text_without_model_transcription(self):
        body = "HKT reported 2025 revenue of HK$ 35,000 million."
        response = AIMessage(content="", tool_calls=[{"name": "submit_metric", "args": {
            "status": "verified", "value": "35,000", "period": "2025", "unit": "HK$ million",
            "source_url": "https://hkt.com/report", "passage_id": "p0"}, "id": "one", "type": "tool_call"}],
            response_metadata={"finish_reason": "tool_calls"})
        harness = ResearchHarness(TASK, ToolModel(responses=[response]), lambda *args: None, validate_fact)
        saved=[]
        result=harness.extract("HKT", "收入", {"https://hkt.com/report": {
            "opened": True, "official": True, "text": body}}, saved.append)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["quote"], body)
        self.assertEqual(len(saved), 1)


if __name__ == "__main__":
    unittest.main()

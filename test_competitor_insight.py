import json
import unittest
from unittest.mock import patch

import web_app


MODEL_CONTENT = (
    "# 自由格式洞察\n\n"
    "模型可以自行决定段落、标签和篇幅。\n"
    "- 不要求每段带数字\n"
    "- 不强制覆盖固定栏目\n\n"
    "口径变化也不触发系统补写。"
)


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps({"choices": [{"message": {"content": MODEL_CONTENT}}]}).encode()


class _StreamingResponse(_Response):
    def __iter__(self):
        events = [
            {"choices": [{"delta": {"reasoning_content": "分析中"}}]},
            *({"choices": [{"delta": {"content": chunk}}]} for chunk in (MODEL_CONTENT[:28], MODEL_CONTENT[28:63], MODEL_CONTENT[63:])),
        ]
        for event in events:
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode()
        yield b"data: [DONE]\n\n"


class CompetitorInsightTests(unittest.TestCase):
    def payload(self):
        data = json.loads(web_app.COMPETITOR_WORKBENCH_DATA_PATH.read_text(encoding="utf-8"))
        return {
            "requestId": "selection-1",
            "companies": ["HKT", "SmarTone"],
            "metric": {"key": "mobile_postpaid_churn", "label": "移动后付费流失率"},
            "years": [2020, 2021, 2022],
            "evidenceVersion": data["evidenceVersion"],
        }

    def test_prompt_contains_only_selected_table(self):
        captured = {}

        def open_request(request, timeout):
            captured["body"] = json.loads(request.data.decode())
            captured["timeout"] = timeout
            return _Response()

        payload = self.payload()
        config = {"base_url": web_app.INTERNAL_AI_BASE_URL, "api_key": "test", "model": "test-model"}
        with patch("web_app.load_ai_config", return_value=config), patch("web_app.wait_for_internal_ai_slot"), patch(
            "web_app.urllib.request.urlopen", side_effect=open_request
        ):
            result = web_app.generate_competitor_insight(payload)

        self.assertEqual(result["requestId"], "selection-1")
        self.assertIn("HKT\t2020\t=\t0.9\tpercent", captured["body"]["messages"][1]["content"])
        self.assertIn("官方来源", captured["body"]["messages"][1]["content"])
        self.assertNotIn("RAG", captured["body"]["messages"][1]["content"])
        self.assertEqual(result["insight"], MODEL_CONTENT)
        self.assertNotIn("insights", result)
        self.assertEqual(captured["body"]["messages"][0]["content"], "你是电信行业竞争策略分析师。请分析用户提供的竞争数据并给出洞察。")
        self.assertNotIn("只输出三行", captured["body"]["messages"][0]["content"])
        self.assertNotIn("不得", captured["body"]["messages"][0]["content"])
        self.assertNotIn("max_tokens", captured["body"])
        self.assertNotIn("temperature", captured["body"])
        self.assertNotIn("chat_template_kwargs", captured["body"])

    def test_browser_cells_are_not_trusted(self):
        captured = {}

        def open_request(request, timeout):
            captured["body"] = json.loads(request.data.decode())
            return _Response()

        payload = self.payload()
        payload["cells"] = [{"company": "HKT", "year": 2020, "value": 999999, "unit": "fake"}]
        config = {"base_url": web_app.INTERNAL_AI_BASE_URL, "api_key": "test", "model": "test-model"}
        with patch("web_app.load_ai_config", return_value=config), patch("web_app.wait_for_internal_ai_slot"), patch(
            "web_app.urllib.request.urlopen", side_effect=open_request
        ):
            web_app.generate_competitor_insight(payload)
        prompt = captured["body"]["messages"][1]["content"]
        self.assertNotIn("999999", prompt)
        self.assertNotIn("fake", prompt)

    def test_streaming_mode_emits_real_status_and_content_deltas(self):
        captured = {}
        events = []

        def open_request(request, timeout):
            captured["body"] = json.loads(request.data.decode())
            captured["timeout"] = timeout
            return _StreamingResponse()

        config = {"base_url": web_app.INTERNAL_AI_BASE_URL, "api_key": "test", "model": "test-model"}
        with patch("web_app.load_ai_config", return_value=config), patch("web_app.wait_for_internal_ai_slot"), patch(
            "web_app.urllib.request.urlopen", side_effect=open_request
        ):
            result = web_app.generate_competitor_insight(self.payload(), stream_callback=events.append)

        self.assertTrue(captured["body"]["stream"])
        self.assertEqual(captured["timeout"], 55)
        self.assertEqual([event["stage"] for event in events if event["type"] == "status"], ["queue", "generating", "reasoning"])
        self.assertGreaterEqual(len([event for event in events if event["type"] == "delta"]), 3)
        self.assertEqual(result["insight"], MODEL_CONTENT)

    def test_model_receives_only_common_comparison_years(self):
        captured = {}

        def open_request(request, timeout):
            captured["body"] = json.loads(request.data.decode())
            return _Response()

        payload = self.payload()
        payload["metric"] = {"key": "mobile_postpaid_exit_arpu", "label": "移动后付期末ARPU"}
        payload["years"] = [2018, 2019, 2020, 2021, 2022]
        config = {"base_url": web_app.INTERNAL_AI_BASE_URL, "api_key": "test", "model": "test-model"}
        with patch("web_app.load_ai_config", return_value=config), patch("web_app.wait_for_internal_ai_slot"), patch(
            "web_app.urllib.request.urlopen", side_effect=open_request
        ):
            web_app.generate_competitor_insight(payload)

        prompt = captured["body"]["messages"][1]["content"]
        self.assertIn("数据年度：2020,2021,2022", prompt)
        self.assertNotIn("HKT\t2018", prompt)
        self.assertNotIn("HKT\t2019", prompt)
        self.assertIn("SmarTone\t2022", prompt)

    def test_rejects_stale_evidence_version(self):
        payload = self.payload()
        payload["evidenceVersion"] = "stale"
        with self.assertRaisesRegex(ValueError, "数据版本已更新"):
            web_app.generate_competitor_insight(payload)

    def test_visible_model_content_is_returned_exactly_without_format_gate(self):
        content = "  任意开头\n\n第四段也保留\n* Markdown 符号保留\n  末尾空格  "
        self.assertEqual(web_app._competitor_insight_content(content), content)

    def test_only_empty_model_content_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "未返回可用洞察"):
            web_app._competitor_insight_content(" \n ")

    def test_demo_report_listing_excludes_test_output(self):
        self.assertFalse(web_app.is_report_file_name("test_out.docx"))


if __name__ == "__main__":
    unittest.main()

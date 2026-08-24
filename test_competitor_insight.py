import json
import unittest
import urllib.error
from unittest.mock import patch

import web_app


MODEL_CONTENT = (
    "竞争格局｜两家公司流失率差距由0.2个百分点收窄至0.1个百分点，竞争呈收敛。\n"
    "公司定位｜HKT由0.9%降至0.8%，SmarTone由0.8%降至0.7%，双方留存压力均缓和。\n"
    "业务含义｜较低流失率可能反映后付客户稳定性增强，但不单独代表整体经营优劣。"
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
        config = {
            "base_url": web_app.INTERNAL_AI_BASE_URL,
            "api_key": "test",
            "model": "test-model",
            "extra_parameters": {"max_tokens": 500},
        }
        with patch("web_app.load_ai_config", return_value=config), patch("web_app.wait_for_internal_ai_slot"), patch(
            "web_app.urllib.request.urlopen", side_effect=open_request
        ):
            result = web_app.generate_competitor_insight(payload)

        self.assertEqual(result["requestId"], "selection-1")
        self.assertIn("HKT\t2020\t=\t0.9\tpercent", captured["body"]["messages"][1]["content"])
        self.assertIn("原生口径", captured["body"]["messages"][1]["content"])
        self.assertNotIn("https://", captured["body"]["messages"][1]["content"])
        self.assertNotIn("RAG", captured["body"]["messages"][1]["content"])
        self.assertEqual(result["insight"], MODEL_CONTENT)
        self.assertEqual(len(result["insights"]), 3)
        self.assertIn("只输出三行", captured["body"]["messages"][0]["content"])
        self.assertIn("竞争格局｜", captured["body"]["messages"][0]["content"])
        self.assertEqual(captured["body"]["max_tokens"], 1800)
        self.assertEqual(captured["body"]["temperature"], 0.1)
        self.assertEqual(captured["body"]["chat_template_kwargs"], {"enable_thinking": False})

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
        with patch("web_app.load_ai_config", return_value=config), patch("web_app.wait_for_internal_ai_slot") as wait_slot, patch(
            "web_app.urllib.request.urlopen", side_effect=open_request
        ):
            result = web_app.generate_competitor_insight(self.payload(), stream_callback=events.append)

        self.assertTrue(captured["body"]["stream"])
        self.assertEqual(captured["timeout"], 90)
        wait_kwargs = wait_slot.call_args.kwargs
        self.assertNotIn("deadline_monotonic", wait_kwargs)
        self.assertTrue(callable(wait_kwargs["wait_callback"]))
        self.assertEqual([event["stage"] for event in events if event["type"] == "status"], ["queue", "generating", "reasoning"])
        self.assertGreaterEqual(len([event for event in events if event["type"] == "delta"]), 3)
        self.assertEqual(result["insight"], MODEL_CONTENT)
        self.assertEqual(len(result["insights"]), 3)

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
        self.assertNotIn("HKT\t2018", prompt)
        self.assertNotIn("HKT\t2019", prompt)
        self.assertIn("SmarTone\t2022", prompt)

    def test_stream_retries_once_when_upstream_breaks_before_content(self):
        events = []
        config = {"base_url": web_app.INTERNAL_AI_BASE_URL, "api_key": "test", "model": "test-model"}
        with patch("web_app.load_ai_config", return_value=config), patch("web_app.wait_for_internal_ai_slot") as wait_slot, patch(
            "web_app.urllib.request.urlopen",
            side_effect=[urllib.error.URLError("connection reset"), _StreamingResponse()],
        ) as open_request:
            result = web_app.generate_competitor_insight(self.payload(), stream_callback=events.append)

        self.assertEqual(open_request.call_count, 2)
        self.assertEqual(wait_slot.call_count, 2)
        self.assertTrue(any("自动续接" in str(event.get("message") or "") for event in events))
        self.assertEqual(result["insight"], MODEL_CONTENT)

    def test_rejects_stale_evidence_version(self):
        payload = self.payload()
        payload["evidenceVersion"] = "stale"
        with self.assertRaisesRegex(ValueError, "数据版本已更新"):
            web_app.generate_competitor_insight(payload)

    def test_format_drift_is_compacted_without_rejecting_or_fallback(self):
        content = "# 分析\n\n竞争格局：差距正在收窄。\n公司定位：HKT与SmarTone均下降。\n这是模型自行表述的业务解读。"
        items = web_app._parse_competitor_insight_items(content)
        self.assertEqual(len(items), 3)
        self.assertTrue(items[0].startswith("竞争格局｜"))
        self.assertTrue(items[1].startswith("公司定位｜"))
        self.assertTrue(items[2].startswith("业务含义｜"))
        self.assertNotIn("#", " ".join(items))

    def test_missing_scope_wording_does_not_reject_usable_model_content(self):
        content = "竞争格局｜数值持续增长。\n公司定位｜两家趋势接近。\n业务含义｜竞争重心转向使用体验。"
        self.assertEqual(len(web_app._parse_competitor_insight_items(content)), 3)

    def test_only_empty_model_content_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "未返回可用洞察"):
            web_app._competitor_insight_content(" \n ")

    def test_demo_report_listing_excludes_test_output(self):
        self.assertFalse(web_app.is_report_file_name("test_out.docx"))


if __name__ == "__main__":
    unittest.main()

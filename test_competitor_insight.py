import json
import unittest
from unittest.mock import patch

import web_app


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps({"choices": [{"message": {"content": "HKT近三年保持领先，但SmarTone增速更快。"}}]}).encode()


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
        self.assertLessEqual(len(result["insight"]), 160)

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

    def test_rejects_stale_evidence_version(self):
        payload = self.payload()
        payload["evidenceVersion"] = "stale"
        with self.assertRaisesRegex(ValueError, "数据版本已更新"):
            web_app.generate_competitor_insight(payload)


if __name__ == "__main__":
    unittest.main()

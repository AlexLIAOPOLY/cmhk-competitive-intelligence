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
    def test_prompt_contains_only_selected_table(self):
        captured = {}

        def open_request(request, timeout):
            captured["body"] = json.loads(request.data.decode())
            captured["timeout"] = timeout
            return _Response()

        payload = {
            "requestId": "selection-1",
            "companies": ["HKT", "SmarTone"],
            "metric": {"key": "arpu", "label": "ARPU"},
            "years": [2023, 2024],
            "cells": [
                {"company": "HKT", "year": 2023, "value": 92, "unit": "HKD", "status": "official_only"},
                {"company": "SmarTone", "year": 2024, "value": 88, "unit": "HKD", "status": "official_only"},
            ],
        }
        config = {"base_url": web_app.INTERNAL_AI_BASE_URL, "api_key": "test", "model": "test-model"}
        with patch("web_app.load_ai_config", return_value=config), patch("web_app.wait_for_internal_ai_slot"), patch(
            "web_app.urllib.request.urlopen", side_effect=open_request
        ):
            result = web_app.generate_competitor_insight(payload)

        self.assertEqual(result["requestId"], "selection-1")
        self.assertIn("HKT\t2023\t92.0\tHKD", captured["body"]["messages"][1]["content"])
        self.assertNotIn("RAG", captured["body"]["messages"][1]["content"])
        self.assertLessEqual(len(result["insight"]), 160)

    def test_rejects_company_outside_selection(self):
        payload = {
            "companies": ["HKT", "SmarTone"],
            "metric": {"label": "ARPU"},
            "years": [2024],
            "cells": [{"company": "HKBN", "year": 2024, "value": 1}],
        }
        with self.assertRaisesRegex(ValueError, "选择范围外"):
            web_app.generate_competitor_insight(payload)


if __name__ == "__main__":
    unittest.main()

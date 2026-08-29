from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from normalize_company_metrics_ai import call_deepseek


def _response(items: list[dict[str, object]]) -> MagicMock:
    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({"items": items}, ensure_ascii=False)
                }
            }
        ]
    }
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(
        payload, ensure_ascii=False
    ).encode("utf-8")
    response.__exit__.return_value = False
    return response


def _result(item_id: str) -> dict[str, object]:
    return {
        "id": item_id,
        "status": "unavailable",
        "value": "未提取到有效数据",
        "basis": "证据不足",
        "note": "",
        "entity_supported": True,
        "metric_supported": False,
        "value_supported": False,
        "confidence": 0.1,
    }


class NormalizeCompanyMetricsAITests(unittest.TestCase):
    def test_missing_batch_ids_are_supplemented_and_returned_in_input_order(self) -> None:
        tasks = [
            {"id": "a", "company": "HKT", "metric": "收入", "raw_text": ""},
            {"id": "b", "company": "HKT", "metric": "EBITDA", "raw_text": ""},
            {"id": "c", "company": "HKT", "metric": "利润", "raw_text": ""},
        ]
        config = {
            "api_key": "test-key",
            "base_url": "https://example.invalid/v1",
            "model": "DeepSeek-V4-Pro",
        }
        with (
            patch("normalize_company_metrics_ai.load_ai_config", return_value=config),
            patch("normalize_company_metrics_ai.wait_for_internal_ai_slot"),
            patch(
                "normalize_company_metrics_ai.open_llm_request",
                side_effect=[
                    _response([_result("a"), _result("c")]),
                    _response([_result("b")]),
                ],
            ) as request,
        ):
            result = call_deepseek(tasks)

        self.assertEqual([item["id"] for item in result], ["a", "b", "c"])
        self.assertEqual(request.call_count, 2)


if __name__ == "__main__":
    unittest.main()

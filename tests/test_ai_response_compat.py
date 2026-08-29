import unittest

from ai_response_compat import (
    StructuredAIResponseError,
    final_chat_message_text,
    load_json_response,
    prepare_structured_chat_body,
    unwrap_items_payload,
)


class AIResponseCompatibilityTests(unittest.TestCase):
    def test_structured_object_contract_disables_thinking_and_requests_json_object(self):
        body = prepare_structured_chat_body(
            {"model": "deepseek-v4", "chat_template_kwargs": {"custom": True}}
        )
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertEqual(body["chat_template_kwargs"], {"custom": True})
        self.assertEqual(body["response_format"], {"type": "json_object"})

    def test_final_text_never_promotes_reasoning_to_structured_answer(self):
        with self.assertRaisesRegex(StructuredAIResponseError, "只有思考内容"):
            final_chat_message_text(
                {"choices": [{"finish_reason": "stop", "message": {"content": "", "reasoning_content": '{"ok":true}'}}]},
                operation="测试",
            )

    def test_length_truncation_is_explicit_even_when_content_is_present(self):
        with self.assertRaisesRegex(StructuredAIResponseError, "长度截断"):
            final_chat_message_text(
                {"choices": [{"finish_reason": "length", "message": {"content": '{"items": ['}}]},
                operation="测试",
            )

    def test_length_finish_accepts_independently_complete_json(self):
        self.assertEqual(
            final_chat_message_text(
                {"choices": [{"finish_reason": "length", "message": {"content": '{"items":[]}'}}]},
                operation="测试",
            ),
            '{"items":[]}',
        )

    def test_items_object_contract_keeps_legacy_array_cache_compatible(self):
        self.assertEqual(unwrap_items_payload({"items": [{"id": 1}]}), [{"id": 1}])
        self.assertEqual(unwrap_items_payload([{"id": 2}]), [{"id": 2}])

    def test_safe_terminal_delimiter_repair_handles_gateway_stop_bug(self):
        self.assertEqual(
            load_json_response('{"items":[{"id":"probe","ok":true}', operation="测试"),
            {"items": [{"id": "probe", "ok": True}]},
        )

    def test_safe_terminal_delimiter_repair_rejects_truncated_string(self):
        with self.assertRaisesRegex(StructuredAIResponseError, "不完整JSON"):
            load_json_response('{"items":[{"detail":"被截断', operation="测试")

    def test_complete_json_is_extracted_from_gateway_wrapper_text(self):
        self.assertEqual(
            load_json_response('以下为结果：\n{"items":[{"id":"probe"}]}\n完成。', operation="测试"),
            {"items": [{"id": "probe"}]},
        )


if __name__ == "__main__":
    unittest.main()

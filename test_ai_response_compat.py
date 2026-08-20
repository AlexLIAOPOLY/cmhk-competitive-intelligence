import pytest

from ai_response_compat import (
    StructuredAIResponseError,
    final_chat_message_text,
    load_json_response,
    prepare_structured_chat_body,
    unwrap_items_payload,
)


def test_structured_object_contract_disables_thinking_and_requests_json_object():
    body = prepare_structured_chat_body(
        {"model": "deepseek-v4", "chat_template_kwargs": {"custom": True}}
    )
    assert body["thinking"] == {"type": "disabled"}
    assert body["chat_template_kwargs"] == {"custom": True, "enable_thinking": False}
    assert body["response_format"] == {"type": "json_object"}


def test_final_text_never_promotes_reasoning_to_structured_answer():
    with pytest.raises(StructuredAIResponseError, match="只有思考内容"):
        final_chat_message_text(
            {
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"content": "", "reasoning_content": '{"ok":true}'},
                }]
            },
            operation="测试",
        )


def test_length_truncation_is_explicit_even_when_content_is_present():
    with pytest.raises(StructuredAIResponseError, match="长度截断"):
        final_chat_message_text(
            {
                "choices": [{
                    "finish_reason": "length",
                    "message": {"content": '{"items": ['},
                }]
            },
            operation="测试",
        )


def test_items_object_contract_keeps_legacy_array_cache_compatible():
    assert unwrap_items_payload({"items": [{"id": 1}]}) == [{"id": 1}]
    assert unwrap_items_payload([{"id": 2}]) == [{"id": 2}]


def test_safe_terminal_delimiter_repair_handles_gateway_stop_bug():
    assert load_json_response('{"items":[{"id":"probe","ok":true}', operation="测试") == {
        "items": [{"id": "probe", "ok": True}]
    }


def test_safe_terminal_delimiter_repair_rejects_truncated_string():
    with pytest.raises(StructuredAIResponseError, match="不完整JSON"):
        load_json_response('{"items":[{"detail":"被截断', operation="测试")

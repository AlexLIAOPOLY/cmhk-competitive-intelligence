from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Literal


JsonRoot = Literal["object", "array"]


class StructuredAIResponseError(ValueError):
    """Raised when a structured model call has no complete final answer."""


def deepseek_nonthinking_parameters(existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return gateway parameters that disable DeepSeek reasoning explicitly.

    ``thinking`` is the current DeepSeek API switch. ``chat_template_kwargs`` is
    retained for compatible internal gateways that still expose the older flag.
    """
    params = deepcopy(existing or {})
    params["thinking"] = {"type": "disabled"}
    template_kwargs = dict(params.get("chat_template_kwargs") or {})
    template_kwargs["enable_thinking"] = False
    params["chat_template_kwargs"] = template_kwargs
    return params


def prepare_structured_chat_body(
    body: dict[str, Any],
    *,
    root: JsonRoot = "object",
) -> dict[str, Any]:
    """Apply the internal DeepSeek structured-output contract to a chat body."""
    prepared = deepseek_nonthinking_parameters(body)
    if root == "object":
        prepared["response_format"] = {"type": "json_object"}
    else:
        # DeepSeek JSON Output only promises an object root. Array contracts still
        # receive explicit non-thinking mode and are validated by their callers.
        prepared.pop("response_format", None)
    return prepared


def final_chat_message_text(payload: dict[str, Any], *, operation: str = "结构化AI") -> str:
    """Read only a complete final answer; reasoning is never structured output."""
    choices = payload.get("choices") or []
    choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    finish_reason = str(choice.get("finish_reason") or "").strip().lower()
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    content = message.get("content")
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, dict):
        text = str(content.get("text") or content.get("content") or "").strip()
    elif isinstance(content, list):
        text = "\n".join(
            str(block.get("text") or block.get("content") or "")
            for block in content
            if isinstance(block, dict)
        ).strip()
    else:
        text = ""
    if text and finish_reason in {"length", "max_tokens"}:
        # Some compatible gateways report ``length`` after they have already
        # emitted a complete JSON value (for example when hidden reasoning used
        # the remaining allowance).  Accept only a value that the strict parser
        # can prove complete; partial strings and containers still fail closed.
        strict_text = text
        if strict_text.startswith("```"):
            strict_text = strict_text.split("\n", 1)[-1]
            if strict_text.endswith("```"):
                strict_text = strict_text[:-3].rstrip()
        try:
            json.loads(strict_text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise StructuredAIResponseError(f"{operation}最终输出被长度截断") from exc
        return text
    if text:
        return text
    if message.get("reasoning_content"):
        raise StructuredAIResponseError(f"{operation}只有思考内容，没有最终输出")
    raise StructuredAIResponseError(f"{operation}没有返回最终输出")


def unwrap_items_payload(value: Any, *, operation: str = "结构化AI") -> list[Any]:
    """Accept the object-root contract and tolerate legacy cached array output."""
    if isinstance(value, dict) and isinstance(value.get("items"), list):
        return value["items"]
    if isinstance(value, list):
        return value
    raise StructuredAIResponseError(f"{operation}未返回items数组")


def load_json_response(text: str, *, operation: str = "结构化AI") -> Any:
    """Parse JSON and repair only missing terminal object/array delimiters.

    Some compatible gateways return ``finish_reason=stop`` after a complete
    value but omit the final ``]}``. Repair is safe only when strings are closed,
    delimiters are properly nested, and the response does not end after a key,
    colon, or comma. Any content truncation still fails closed.
    """
    value = str(text or "").strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[-1]
        if value.endswith("```"):
            value = value[:-3].rstrip()
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        parse_error = exc

    # A few OpenAI-compatible gateways wrap an otherwise complete JSON answer
    # in a short prose prefix/suffix even in JSON mode. Extract only a balanced,
    # independently parseable top-level value; never guess inside an unfinished
    # string or repair arbitrary prose.
    for start, opener in (
        (index, value[index])
        for index in range(len(value))
        if value[index] in "[{"
    ):
        stack = [opener]
        in_string = False
        escaped = False
        for end in range(start + 1, len(value)):
            char = value[end]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char in "[{":
                stack.append(char)
            elif char in "]}":
                expected = "[" if char == "]" else "{"
                if not stack or stack.pop() != expected:
                    break
                if not stack:
                    try:
                        return json.loads(value[start : end + 1])
                    except json.JSONDecodeError:
                        break
    stack: list[str] = []
    in_string = False
    escaped = False
    for char in value:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "[{":
            stack.append(char)
        elif char in "]}":
            expected = "[" if char == "]" else "{"
            if not stack or stack.pop() != expected:
                raise StructuredAIResponseError(f"{operation}返回了错位的JSON括号") from parse_error
    if in_string or escaped or not stack or value.rstrip().endswith((":", ",")):
        raise StructuredAIResponseError(f"{operation}返回了不完整JSON") from parse_error
    repaired = value + "".join("]" if opener == "[" else "}" for opener in reversed(stack))
    try:
        return json.loads(repaired)
    except json.JSONDecodeError as exc:
        raise StructuredAIResponseError(f"{operation}返回了无效JSON") from exc

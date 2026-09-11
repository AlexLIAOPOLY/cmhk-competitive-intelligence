from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import time
from typing import Any, Literal


JsonRoot = Literal["object", "array"]


class StructuredAIResponseError(ValueError):
    """Raised when a structured model call has no complete final answer."""


def read_chat_completion_sse(response: Any, *, operation: str = "结构化AI",
                             max_bytes: int = 2_000_000, max_seconds: float = 180) -> dict[str, Any]:
    """Read one complete text stream; never retry or combine separate requests."""
    started = time.monotonic()
    digest = hashlib.sha256()
    diagnostics: dict[str, Any] = {"content_type": str(getattr(response, "headers", {}).get("Content-Type", "")),
                                   "bytes": 0, "chunks": 0, "done": False}
    identity = None
    content, reasoning, event_lines = [], [], []
    finish = None

    def fail(message):
        error = StructuredAIResponseError(f"{operation}流式输出无效：{message}")
        diagnostics.update(response_hash=digest.hexdigest(), elapsed_seconds=round(time.monotonic() - started, 3))
        error.stream_diagnostics = dict(diagnostics)
        raise error

    if "text/event-stream" not in diagnostics["content_type"].lower():
        try:
            raw = response.read(max_bytes + 1)
        except Exception as exc:
            fail(f"传输中断({type(exc).__name__})，不接纳部分内容")
        digest.update(raw)
        diagnostics["bytes"] = len(raw)
        try:
            cached = json.loads(raw)
            diagnostics.update(response_id=cached.get("id"), reported_model=cached.get("model"), created=cached.get("created"))
        except (ValueError, AttributeError):
            pass
        fail("请求stream=true却未返回SSE，拒绝非流式历史响应")
    try:
        while True:
            if time.monotonic() - started > max_seconds:
                fail("超过本次读取时限")
            raw = response.readline(max_bytes - diagnostics["bytes"] + 1)
            if not raw:
                fail("缺少终止[DONE]，不接纳部分内容")
            digest.update(raw)
            diagnostics["bytes"] += len(raw)
            diagnostics.setdefault("first_byte_seconds", round(time.monotonic() - started, 3))
            if diagnostics["bytes"] > max_bytes:
                fail("超过本次读取字节上限")
            try:
                line = raw.decode("utf-8").rstrip("\r\n")
            except UnicodeDecodeError:
                fail("UTF-8字符不完整")
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                event_lines.append(line[5:].lstrip(" "))
                continue
            if line:
                if line.startswith("event:") and line[6:].strip() == "error":
                    fail("服务端返回错误事件")
                continue
            if not event_lines:
                continue
            event = "\n".join(event_lines)
            event_lines = []
            if event == "[DONE]":
                diagnostics["done"] = True
                if identity is None or finish != "stop":
                    fail("缺少完整模型身份或成功stop结束标记")
                diagnostics.update(response_hash=digest.hexdigest(), elapsed_seconds=round(time.monotonic() - started, 3))
                return {"id": identity[0], "model": identity[1], "created": identity[2],
                        "choices": [{"index": 0, "finish_reason": finish,
                                     "message": {"role": "assistant", "content": "".join(content),
                                                 "reasoning_content": "".join(reasoning)}}],
                        "stream_diagnostics": diagnostics}
            try:
                chunk = json.loads(event)
            except ValueError:
                fail("事件JSON不完整")
            if not isinstance(chunk, dict) or chunk.get("error"):
                fail("事件格式错误或服务端报错")
            diagnostics["chunks"] += 1
            choices = chunk.get("choices")
            if not isinstance(choices, list):
                fail("事件缺少choices数组")
            current = (chunk.get("id"), chunk.get("model"), chunk.get("created"))
            if choices:
                if not all(value not in (None, "") for value in current):
                    fail("事件缺少实际模型/id/created")
                if identity is None:
                    identity = current
                    diagnostics.update(response_id=current[0], reported_model=current[1], created=current[2])
                if current != identity:
                    fail("跨事件模型身份或响应id发生变化")
            elif identity is not None and any(value is not None and value != identity[index] for index, value in enumerate(current)):
                fail("usage事件与当前模型身份不一致")
            if not choices:
                continue
            if len(choices) != 1 or not isinstance(choices[0], dict) or choices[0].get("index", 0) != 0:
                fail("不允许多choice或跨choice拼接")
            choice = choices[0]
            delta = choice.get("delta")
            if not isinstance(delta, dict) or delta.get("tool_calls") or delta.get("function_call"):
                fail("仅接受本次结构化文字delta")
            if finish is not None:
                fail("stop后仍返回文字choice")
            for field, target in (("content", content), ("reasoning_content", reasoning)):
                value = delta.get(field)
                if value is not None and not isinstance(value, str):
                    fail("delta文字字段类型错误")
                if value:
                    target.append(value)
            if choice.get("finish_reason"):
                finish = choice["finish_reason"]
                diagnostics["finish_reason"] = finish
                if finish != "stop":
                    fail(f"非成功结束{finish}，不接纳截断内容")
    except StructuredAIResponseError:
        raise
    except Exception as exc:
        fail(f"传输中断({type(exc).__name__})，不接纳部分内容")


def deepseek_nonthinking_parameters(existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the documented DeepSeek parameter that disables reasoning.

    Older internal routes accepted an undocumented ``chat_template_kwargs``
    switch. Do not inject it into new requests: strict gateways can reject an
    otherwise valid JSON-mode request when unknown top-level fields are present.
    Existing caller-supplied compatibility fields are preserved unchanged.
    """
    params = deepcopy(existing or {})
    params["thinking"] = {"type": "disabled"}
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

    # Repair an unfinished JSON root before looking for a nested balanced value.
    # Otherwise {"items":[{"ok":true} can be misread as the complete inner
    # object and silently lose the outer response contract.
    if value.startswith(("[", "{")):
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
    raise StructuredAIResponseError(f"{operation}返回了无效JSON") from parse_error

from __future__ import annotations

import fcntl
import hashlib
import http.client
import io
import json
import logging
import math
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable

from ai_config import api_key_candidates, load_ai_config

_STATE_LOCK = threading.RLock()
# Kept for compatibility; authoritative cooldowns live in the shared state file.
_UNAVAILABLE_UNTIL: dict[str, float] = {}
MAX_TRANSPORT_RETRIES = 2


class APIKeyPoolUnavailable(RuntimeError):
    """Retryable pool exhaustion; never a completed model/business result."""

    status_code = 429
    retryable = True

    def __init__(self, retry_after: float, key_count: int):
        self.retry_after = max(1, math.ceil(retry_after))
        self.key_count = key_count
        super().__init__(
            f"内部模型 {key_count} 个配置路由暂不可用，约 {self.retry_after} 秒后可重试；"
            "请保留当前任务进度。原因可能为额度、限流或权限，请以各 Key 记录为准。"
        )


def _fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]


def _cooldown_seconds() -> float:
    try:
        return max(30.0, float(os.environ.get("CMHK_INTERNAL_AI_KEY_COOLDOWN_SECONDS", "600")))
    except ValueError:
        return 600.0


def _state_path() -> Path:
    configured = os.environ.get("CMHK_INTERNAL_AI_KEY_STATE_PATH", "").strip()
    return Path(configured).expanduser() if configured else Path(tempfile.gettempdir()) / "cmhk_internal_ai_key_health.json"


@contextmanager
def _health_state():
    """Share cooldowns across Web, research, monitor and restarts; no credentials."""
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _STATE_LOCK, path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(state, dict):
                    state = {}
            except (OSError, ValueError):
                state = {}
            before = json.dumps(state, sort_keys=True)
            yield state
            if json.dumps(state, sort_keys=True) != before:
                fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        json.dump(state, handle, ensure_ascii=False)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, path)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _route_id(api_key: str, model: str = "") -> str:
    return _fingerprint(api_key) + (":" + model.strip().casefold() if model else "")


def api_key_retry_after(api_key: str, *, model: str = "") -> float:
    with _health_state() as state:
        until = max(float(state.get(route, {}).get("until", 0)) for route in
                    (_route_id(api_key), _route_id(api_key, model)))
    return max(0.0, until - time.time())


def available_key_routes(routes: list[tuple[str, str]]) -> list[tuple[str, str]]:
    now = time.time()
    with _health_state() as state:
        def remaining(model: str, key: str) -> float:
            return max(float(state.get(route, {}).get("until", 0)) for route in
                       (_route_id(key), _route_id(key, model))) - now
        active = [(model, key) for model, key in routes if remaining(model, key) <= 0]
        if not active and routes:
            raise APIKeyPoolUnavailable(min(remaining(model, key) for model, key in routes), len(routes))
    return active


def ordered_api_keys(config: dict[str, Any] | None = None, *, requested_key: Any = "", model: str = "") -> list[str]:
    keys = api_key_candidates(config or load_ai_config(include_key=True), requested_key=requested_key, model=model)
    return [key for _, key in available_key_routes([(model, key) for key in keys])]


def _error_text(error: BaseException, raw_body: bytes = b"") -> str:
    parts = [str(error)]
    if raw_body:
        parts.append(raw_body.decode("utf-8", errors="ignore"))
    body = getattr(error, "body", None)
    if body:
        try:
            parts.append(json.dumps(body, ensure_ascii=False))
        except (TypeError, ValueError):
            parts.append(str(body))
    return " ".join(parts).casefold()


def _status_code(error: BaseException) -> int | None:
    for attr in ("status_code", "status", "code"):
        try:
            return int(getattr(error, attr))
        except (TypeError, ValueError, AttributeError):
            pass
    return None


def key_failure_reason(error: BaseException, *, status_code: int | None = None, raw_body: bytes = b"") -> str:
    if isinstance(error, APIKeyPoolUnavailable):
        return ""
    text = _error_text(error, raw_body)
    status = status_code if status_code is not None else _status_code(error)
    if any(marker in text for marker in ("budget_exceeded", "budget has been exceeded", "insufficient_quota", "quota exceeded", "credit balance")):
        return "budget"
    if any(marker in text for marker in ("key_model_access_denied", "team_model_access_denied", "not allowed to access model", "can only access models", "model access denied", "model_access_denied")):
        return "model_access"
    if status == 429 or any(marker in text for marker in ("rate limit", "rate_limit", "too many requests")):
        return "rate_limit"
    if status == 401 or any(marker in text for marker in ("invalid api key", "authentication")):
        return "authentication"
    if status == 403:
        return "model_access"
    return ""


def is_key_unavailable_error(error: BaseException, *, status_code: int | None = None, raw_body: bytes = b"") -> bool:
    return bool(key_failure_reason(error, status_code=status_code, raw_body=raw_body))


def retry_after_seconds(error: BaseException) -> float:
    headers = getattr(error, "headers", None) or getattr(getattr(error, "response", None), "headers", None) or {}
    value = headers.get("Retry-After") or headers.get("retry-after")
    if not value:
        return 0.0
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        try:
            parsed = parsedate_to_datetime(str(value))
            return max(0.0, parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return 0.0


def mark_api_key_unavailable(api_key: str, error: BaseException | None = None, *, model: str = "", raw_body: bytes = b"") -> None:
    if not api_key:
        return
    reason = key_failure_reason(error, raw_body=raw_body) if error else "unavailable"
    cooldown = 60.0 if reason == "rate_limit" else _cooldown_seconds()
    if error is not None:
        cooldown = max(retry_after_seconds(error), 1.0) if reason == "rate_limit" and retry_after_seconds(error) else max(cooldown, retry_after_seconds(error))
    route = _route_id(api_key, model if reason == "model_access" else "")
    now = time.time()
    with _health_state() as state:
        previous = state.get(route, {})
        state[route] = {"until": max(float(previous.get("until", 0)), now + cooldown),
                        "reason": reason, "status": _status_code(error) if error else None,
                        "failed_at": now, "failures": int(previous.get("failures", 0)) + 1}
    logging.warning("内部模型 Key[%s] %s，冷却 %.0f 秒；后续请求跳过此路由。", _fingerprint(api_key),
                    {"budget": "额度不足", "rate_limit": "请求限流", "model_access": "模型权限不足", "authentication": "鉴权失败"}.get(reason, "暂不可用"), cooldown)


def is_transient_llm_error(error: BaseException) -> bool:
    if isinstance(error, APIKeyPoolUnavailable) or is_key_unavailable_error(error):
        return False
    status = _status_code(error)
    if status is not None:
        return status in {408, 409, 425, 500, 502, 503, 504}
    if isinstance(error, (TimeoutError, ConnectionError, urllib.error.URLError, http.client.IncompleteRead, http.client.RemoteDisconnected)):
        return True
    # SDK transport errors have no HTTP status; avoid importing a client in urllib users.
    return type(error).__name__ in {"APIConnectionError", "APITimeoutError", "ReadError", "ReadTimeout", "ConnectError", "ConnectTimeout", "RemoteProtocolError"}


def transport_retry_delay(error: BaseException, attempt: int) -> float:
    return max(float(2 ** attempt), retry_after_seconds(error))


def _clone_request(request: urllib.request.Request, api_key: str) -> urllib.request.Request:
    headers = {name: value for name, value in request.header_items() if name.casefold() != "authorization"}
    headers["Authorization"] = f"Bearer {api_key}"
    return urllib.request.Request(request.full_url, data=request.data, headers=headers, method=request.get_method())


class _BufferedResponse(io.BytesIO):
    """Non-streaming inference is complete before any bytes escape to callers."""
    def __init__(self, raw: bytes, response: Any):
        super().__init__(raw)
        self.status = getattr(response, "status", 200)
        self.code = getattr(response, "code", self.status)
        self.headers = getattr(response, "headers", {})
        self.url = getattr(response, "url", "")

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def getcode(self):
        return self.code

    def geturl(self):
        return self.url

    def info(self):
        return self.headers


def open_llm_request(request: urllib.request.Request, *, timeout: float,
                     config: dict[str, Any] | None = None, requested_key: Any = "", model: str = "",
                     opener: Any = None, open_func: Callable[..., Any] | None = None,
                     deadline_monotonic: float | None = None,
                     max_transport_retries: int = MAX_TRANSPORT_RETRIES,
                     buffer_response: bool | None = None):
    """Rotate unavailable keys; retry interrupted inference before exposing output.

    Streaming bodies are returned untouched: a partial stream is never replayed or
    spliced. Callers retain their existing session/checkpoint recovery semantics.
    """
    config = config or load_ai_config(include_key=True)
    keys = ordered_api_keys(config, requested_key=requested_key, model=model)
    if not keys:
        raise RuntimeError("未配置公司内部模型 API Key")
    open_request = open_func if open_func is not None else opener.open if opener is not None else urllib.request.urlopen
    try:
        body = json.loads(request.data or b"{}")
        if buffer_response is None:
            buffer_response = "/chat/completions" in request.full_url and not body.get("stream", False)
    except (ValueError, AttributeError, UnicodeDecodeError):
        buffer_response = bool(buffer_response)
    # Existing timeout is a per-attempt socket timeout. Bound extra transport work.
    deadline = deadline_monotonic if deadline_monotonic is not None else time.monotonic() + timeout * (1 + min(2, max_transport_retries))
    sent_requests = 0
    for api_key in keys:
        # A different worker may have marked a key since this request was queued.
        if api_key_retry_after(api_key, model=model) > 0:
            continue
        for attempt in range(max(0, min(2, max_transport_retries)) + 1):
            if sent_requests:
                # The caller reserved the first request; every rotation/retry must
                # also consume capacity instead of amplifying gateway rate limits.
                from ai_rate_limit import wait_for_internal_ai_slot
                wait_for_internal_ai_slot("internal-model-retry", deadline_monotonic=deadline)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("内部模型重试已达到本轮时间上限")
            try:
                sent_requests += 1
                response = open_request(_clone_request(request, api_key), timeout=min(timeout, remaining))
                if not buffer_response:
                    return response
                with response as opened:
                    return _BufferedResponse(opened.read(), opened)
            except Exception as exc:
                raw_body = b""
                if isinstance(exc, urllib.error.HTTPError):
                    raw_body = exc.read()
                    exc.fp = io.BytesIO(raw_body)
                if is_key_unavailable_error(exc, raw_body=raw_body):
                    mark_api_key_unavailable(api_key, exc, model=model, raw_body=raw_body)
                    break
                if not is_transient_llm_error(exc) or attempt >= min(2, max_transport_retries):
                    raise
                delay = transport_retry_delay(exc, attempt)
                if time.monotonic() + delay >= deadline:
                    raise TimeoutError("内部模型重试已达到本轮时间上限") from exc
                logging.warning("内部模型连接暂时中断（%s），%.1f 秒后重试 %s/%s。", type(exc).__name__, delay, attempt + 1, min(2, max_transport_retries))
                time.sleep(delay)
    # Re-read shared cooldowns, including the final key and concurrent failures.
    available_key_routes([(model, key) for key in keys])
    raise APIKeyPoolUnavailable(1, len(keys))

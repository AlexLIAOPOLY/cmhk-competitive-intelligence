from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from ai_config import api_key_candidates, load_ai_config


_STATE_LOCK = threading.RLock()
_UNAVAILABLE_UNTIL: dict[str, float] = {}


def _fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]


def _cooldown_seconds() -> float:
    try:
        return max(30.0, float(os.environ.get("CMHK_INTERNAL_AI_KEY_COOLDOWN_SECONDS", "600")))
    except ValueError:
        return 600.0


def ordered_api_keys(
    config: dict[str, Any] | None = None,
    *,
    requested_key: Any = "",
    model: str = "",
) -> list[str]:
    keys = api_key_candidates(
        config or load_ai_config(include_key=True),
        requested_key=requested_key,
        model=model,
    )
    now = time.monotonic()
    with _STATE_LOCK:
        active = [key for key in keys if _UNAVAILABLE_UNTIL.get(_fingerprint(key), 0) <= now]
        cooling = [key for key in keys if key not in active]
    return active + cooling


def mark_api_key_unavailable(api_key: str) -> None:
    if not api_key:
        return
    fingerprint = _fingerprint(api_key)
    with _STATE_LOCK:
        _UNAVAILABLE_UNTIL[fingerprint] = time.monotonic() + _cooldown_seconds()
    logging.warning(
        "内部模型 Key[%s] 额度、限流或权限不可用，已轮换下一把 Key。",
        fingerprint,
    )


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


def is_key_unavailable_error(
    error: BaseException,
    *,
    status_code: int | None = None,
    raw_body: bytes = b"",
) -> bool:
    status = status_code
    if status is None:
        for attr in ("status_code", "status"):
            try:
                value = int(getattr(error, attr))
            except (TypeError, ValueError, AttributeError):
                continue
            status = value
            break
    if status in {401, 403, 429}:
        return True
    text = _error_text(error, raw_body)
    markers = (
        "budget_exceeded",
        "budget has been exceeded",
        "insufficient_quota",
        "quota exceeded",
        "credit balance",
        "key_model_access_denied",
        "team_model_access_denied",
        "not allowed to access model",
        "can only access models",
        "invalid api key",
        "authentication",
        "rate limit",
        "rate_limit",
        "too many requests",
    )
    return any(marker in text for marker in markers)


def _clone_request(request: urllib.request.Request, api_key: str) -> urllib.request.Request:
    headers = {
        name: value
        for name, value in request.header_items()
        if name.casefold() != "authorization"
    }
    headers["Authorization"] = f"Bearer {api_key}"
    return urllib.request.Request(
        request.full_url,
        data=request.data,
        headers=headers,
        method=request.get_method(),
    )


def open_llm_request(
    request: urllib.request.Request,
    *,
    timeout: float,
    config: dict[str, Any] | None = None,
    requested_key: Any = "",
    model: str = "",
    opener: Any = None,
    open_func: Callable[..., Any] | None = None,
):
    """Open one LLM request and rotate keys only for key-scoped failures."""
    config = config or load_ai_config(include_key=True)
    keys = ordered_api_keys(config, requested_key=requested_key, model=model)
    if not keys:
        raise RuntimeError("未配置公司内部模型 API Key")
    open_request: Callable[..., Any] = (
        open_func
        if open_func is not None
        else opener.open if opener is not None else urllib.request.urlopen
    )
    last_error: BaseException | None = None
    for index, api_key in enumerate(keys):
        try:
            return open_request(_clone_request(request, api_key), timeout=timeout)
        except urllib.error.HTTPError as exc:
            raw_body = exc.read()
            exc.fp = io.BytesIO(raw_body)
            last_error = exc
            if not is_key_unavailable_error(
                exc,
                status_code=exc.code,
                raw_body=raw_body,
            ) or index >= len(keys) - 1:
                raise
            mark_api_key_unavailable(api_key)
    if last_error is not None:
        raise last_error
    raise RuntimeError("内部模型请求未执行")

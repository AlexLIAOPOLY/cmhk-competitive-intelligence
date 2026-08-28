from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import tempfile
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable, Iterator

from langchain_deepseek import ChatDeepSeek as _ChatDeepSeek

from ai_config import load_ai_config
from ai_key_rotation import (
    is_key_unavailable_error,
    mark_api_key_unavailable,
    ordered_api_keys,
)


DEFAULT_REQUESTS_PER_MINUTE = 14
_RESERVATION_ACTIVE: ContextVar[bool] = ContextVar(
    "cmhk_internal_ai_reservation_active", default=False
)
_REQUEST_PRIORITY: ContextVar[str] = ContextVar(
    "cmhk_internal_ai_request_priority", default="background"
)


def _limit() -> int:
    return max(
        1,
        min(
            15,
            int(
                os.environ.get(
                    "CMHK_INTERNAL_AI_REQUESTS_PER_MINUTE",
                    str(DEFAULT_REQUESTS_PER_MINUTE),
                )
            ),
        ),
    )


def _state_path() -> Path:
    configured = os.environ.get("CMHK_INTERNAL_AI_RATE_STATE_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(tempfile.gettempdir()) / "cmhk_internal_ai_rate_limit.json"


def set_internal_ai_priority(priority: str = "interactive"):
    """Mark a complete workflow so foreground chat keeps reserved gateway capacity."""
    return _REQUEST_PRIORITY.set(str(priority or "background"))


def reset_internal_ai_priority(token: Any) -> None:
    _REQUEST_PRIORITY.reset(token)


def _effective_limit(total_limit: int) -> int:
    if _REQUEST_PRIORITY.get() == "interactive":
        return total_limit
    reserve = max(
        1,
        min(
            total_limit - 1,
            int(os.environ.get("CMHK_INTERNAL_AI_INTERACTIVE_RESERVE", "4")),
        ),
    )
    return max(1, total_limit - reserve)


def wait_for_internal_ai_slot(
    operation: str = "internal-model",
    *,
    deadline_monotonic: float | None = None,
    wait_callback: Callable[[float], None] | None = None,
) -> float:
    """Reserve one request in the gateway's shared UTC calendar-minute bucket."""
    total_wait = 0.0
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        now = time.time()
        window = int(now // 60)
        total_limit = _limit()
        limit = _effective_limit(total_limit)
        with path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            handle.seek(0)
            try:
                state = json.load(handle)
            except (json.JSONDecodeError, TypeError, ValueError):
                state = {}
            if int(state.get("window") or -1) != window:
                state = {"window": window, "count": 0}
            count = max(0, int(state.get("count") or 0))
            if count < limit:
                state["count"] = count + 1
                state["updated_at"] = now
                state["last_operation"] = str(operation or "internal-model")[:120]
                handle.seek(0)
                handle.truncate()
                json.dump(state, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                return total_wait
            wait_seconds = max(0.25, (window + 1) * 60 - now + 0.35)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        logging.info(
            "内部模型全局队列已达 %s 次/分钟，%s 等待 %.2f 秒",
            limit,
            operation,
            wait_seconds,
        )
        if (
            deadline_monotonic is not None
            and time.monotonic() + wait_seconds >= deadline_monotonic
        ):
            raise TimeoutError(f"{operation} exceeded its time budget while rate limited")
        remaining = wait_seconds
        while remaining > 0:
            sleep_seconds = min(5.0, remaining) if wait_callback else remaining
            time.sleep(sleep_seconds)
            total_wait += sleep_seconds
            remaining -= sleep_seconds
            if wait_callback and remaining > 0:
                wait_callback(remaining)


@contextmanager
def _reserved_model_call(operation: str) -> Iterator[None]:
    if _RESERVATION_ACTIVE.get():
        yield
        return
    wait_for_internal_ai_slot(operation)
    token = _RESERVATION_ACTIVE.set(True)
    try:
        yield
    finally:
        _RESERVATION_ACTIVE.reset(token)


class RateLimitedChatDeepSeek(_ChatDeepSeek):
    """LangChain DeepSeek client sharing the same process-independent quota."""

    def _keys(self) -> list[str]:
        return ordered_api_keys(
            load_ai_config(include_key=True),
            requested_key=self.openai_api_key,
            model=str(self.model_name or ""),
        )

    @staticmethod
    def _headers(api_key: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        headers = dict(kwargs.get("extra_headers") or {})
        headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _generate(self, *args: Any, **kwargs: Any) -> Any:
        keys = self._keys()
        for index, api_key in enumerate(keys):
            try:
                with _reserved_model_call("langchain-generate"):
                    return super()._generate(
                        *args,
                        **{**kwargs, "extra_headers": self._headers(api_key, kwargs)},
                    )
            except Exception as exc:
                if not is_key_unavailable_error(exc) or index >= len(keys) - 1:
                    raise
                mark_api_key_unavailable(api_key)
        raise RuntimeError("内部模型请求未执行")

    def _stream(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
        keys = self._keys()
        for index, api_key in enumerate(keys):
            emitted = False
            try:
                with _reserved_model_call("langchain-stream"):
                    for item in super()._stream(
                        *args,
                        **{**kwargs, "extra_headers": self._headers(api_key, kwargs)},
                    ):
                        emitted = True
                        yield item
                return
            except Exception as exc:
                if emitted or not is_key_unavailable_error(exc) or index >= len(keys) - 1:
                    raise
                mark_api_key_unavailable(api_key)
        raise RuntimeError("内部模型请求未执行")

    async def _agenerate(self, *args: Any, **kwargs: Any) -> Any:
        keys = self._keys()
        for index, api_key in enumerate(keys):
            if not _RESERVATION_ACTIVE.get():
                await asyncio.to_thread(wait_for_internal_ai_slot, "langchain-agenerate")
                token = _RESERVATION_ACTIVE.set(True)
            else:
                token = None
            try:
                return await super()._agenerate(
                    *args,
                    **{**kwargs, "extra_headers": self._headers(api_key, kwargs)},
                )
            except Exception as exc:
                if not is_key_unavailable_error(exc) or index >= len(keys) - 1:
                    raise
                mark_api_key_unavailable(api_key)
            finally:
                if token is not None:
                    _RESERVATION_ACTIVE.reset(token)
        raise RuntimeError("内部模型请求未执行")

    async def _astream(self, *args: Any, **kwargs: Any) -> Any:
        keys = self._keys()
        for index, api_key in enumerate(keys):
            emitted = False
            if not _RESERVATION_ACTIVE.get():
                await asyncio.to_thread(wait_for_internal_ai_slot, "langchain-astream")
                token = _RESERVATION_ACTIVE.set(True)
            else:
                token = None
            try:
                async for item in super()._astream(
                    *args,
                    **{**kwargs, "extra_headers": self._headers(api_key, kwargs)},
                ):
                    emitted = True
                    yield item
                return
            except Exception as exc:
                if emitted or not is_key_unavailable_error(exc) or index >= len(keys) - 1:
                    raise
                mark_api_key_unavailable(api_key)
            finally:
                if token is not None:
                    _RESERVATION_ACTIVE.reset(token)
        raise RuntimeError("内部模型请求未执行")

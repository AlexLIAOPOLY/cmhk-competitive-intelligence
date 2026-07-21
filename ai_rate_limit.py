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
from typing import Any, Iterator

from langchain_deepseek import ChatDeepSeek as _ChatDeepSeek


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


def wait_for_internal_ai_slot(operation: str = "internal-model") -> float:
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
        time.sleep(wait_seconds)
        total_wait += wait_seconds


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

    def _generate(self, *args: Any, **kwargs: Any) -> Any:
        with _reserved_model_call("langchain-generate"):
            return super()._generate(*args, **kwargs)

    def _stream(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
        with _reserved_model_call("langchain-stream"):
            yield from super()._stream(*args, **kwargs)

    async def _agenerate(self, *args: Any, **kwargs: Any) -> Any:
        if _RESERVATION_ACTIVE.get():
            return await super()._agenerate(*args, **kwargs)
        await asyncio.to_thread(wait_for_internal_ai_slot, "langchain-agenerate")
        token = _RESERVATION_ACTIVE.set(True)
        try:
            return await super()._agenerate(*args, **kwargs)
        finally:
            _RESERVATION_ACTIVE.reset(token)

    async def _astream(self, *args: Any, **kwargs: Any) -> Any:
        if not _RESERVATION_ACTIVE.get():
            await asyncio.to_thread(wait_for_internal_ai_slot, "langchain-astream")
            token = _RESERVATION_ACTIVE.set(True)
        else:
            token = None
        try:
            async for item in super()._astream(*args, **kwargs):
                yield item
        finally:
            if token is not None:
                _RESERVATION_ACTIVE.reset(token)

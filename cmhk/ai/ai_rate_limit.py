from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Iterator

from langchain_deepseek import ChatDeepSeek as _ChatDeepSeek

from cmhk.ai.ai_config import load_ai_config
from cmhk.ai.ai_key_rotation import (
    is_key_unavailable_error,
    mark_api_key_unavailable,
    ordered_api_keys,
    available_key_routes,
    APIKeyPoolUnavailable,
    api_key_retry_after,
    is_transient_llm_error,
    transport_retry_delay,
    api_key_resource_id,
)


from cmhk.ai.ai_dispatch import AIQueueBusy, PRIORITY as _REQUEST_PRIORITY, model_call, async_model_call, wait_for_slot

def set_internal_ai_priority(priority: str = "interactive"):
    return _REQUEST_PRIORITY.set(str(priority or "background"))


def reset_internal_ai_priority(token: Any) -> None:
    _REQUEST_PRIORITY.reset(token)


def wait_for_internal_ai_slot(operation="internal-model", *, deadline_monotonic=None, wait_callback=None):
    return wait_for_slot(operation, deadline_monotonic=deadline_monotonic, wait_callback=wait_callback)


@contextmanager
def _reserved_model_call(operation: str, keys: list[str]) -> Iterator[str]:
    resources = {api_key_resource_id(key): key for key in keys}
    with model_call(operation, resources=list(resources)) as ticket:
        yield resources[ticket.resource]


@asynccontextmanager
async def _reserved_async_model_call(operation: str, keys: list[str]):
    resources = {api_key_resource_id(key): key for key in keys}
    async with async_model_call(operation, resources=list(resources)) as ticket:
        yield resources[ticket.resource]


class RateLimitedChatDeepSeek(_ChatDeepSeek):
    """LangChain DeepSeek client sharing the same process-independent quota."""

    def __init__(self, **kwargs):
        # The shared wrapper owns retries. SDK retries inside a lease would
        # bypass request accounting and multiply load during a gateway outage.
        kwargs["max_retries"] = 0
        super().__init__(**kwargs)

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

    def _pool_exhausted(self, keys, error=None):
        try:
            available_key_routes([(str(self.model_name or ""), key) for key in keys])
        except APIKeyPoolUnavailable as unavailable:
            if error is not None:
                # Keep the gateway status visible to workflow progress callbacks.
                unavailable.status_code = getattr(error, "status_code", None) or 429
                raise unavailable from error
            raise
        raise APIKeyPoolUnavailable(1, len(keys))

    def _handle_attempt_error(self, api_key, error, keys, attempt, *, emitted=False):
        if isinstance(error, AIQueueBusy):
            raise error
        if is_key_unavailable_error(error):
            mark_api_key_unavailable(api_key, error, model=str(self.model_name or ""))
            if emitted:
                raise error
            if len(keys) > 1:
                return "next", 0
            self._pool_exhausted(keys, error)
        if emitted or not is_transient_llm_error(error) or attempt >= 2:
            raise error
        delay = transport_retry_delay(error, attempt)
        if delay > 30:
            raise error  # Leave long waits to the durable workflow, not a UI worker.
        logging.warning("内部模型连接暂时中断（%s），%.1f 秒后重试。", type(error).__name__, delay)
        return "retry", delay

    def _generate(self, *args: Any, **kwargs: Any) -> Any:
        if self.streaming:
            return super()._generate(*args, **kwargs)  # _stream owns recovery.
        keys = self._keys()
        remaining = list(keys)
        api_key = ""
        attempt = 0
        while remaining:
            candidates = [api_key] if api_key else remaining
            try:
                with _reserved_model_call("langchain-generate", candidates) as selected:
                    api_key = selected
                    if api_key_retry_after(api_key, model=str(self.model_name or "")) > 0:
                        remaining = [key for key in remaining if key != api_key]
                        api_key = ""
                        attempt = 0
                        continue
                    return super()._generate(*args, **{**kwargs, "extra_headers": self._headers(api_key, kwargs)})
            except Exception as exc:
                action, delay = self._handle_attempt_error(api_key, exc, remaining, attempt)
                if action == "next":
                    remaining = [key for key in remaining if key != api_key]
                    api_key = ""
                    attempt = 0
                    continue
                attempt += 1
                time.sleep(delay)
        self._pool_exhausted(keys)

    def _stream(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
        keys = self._keys()
        remaining = list(keys)
        api_key = ""
        attempt = 0
        while remaining:
            emitted = False
            candidates = [api_key] if api_key else remaining
            try:
                with _reserved_model_call("langchain-stream", candidates) as selected:
                    api_key = selected
                    if api_key_retry_after(api_key, model=str(self.model_name or "")) > 0:
                        remaining = [key for key in remaining if key != api_key]
                        api_key = ""
                        attempt = 0
                        continue
                    for item in super()._stream(*args, **{**kwargs, "extra_headers": self._headers(api_key, kwargs)}):
                        emitted = True
                        yield item
                return
            except Exception as exc:
                action, delay = self._handle_attempt_error(api_key, exc, remaining, attempt, emitted=emitted)
                if action == "next":
                    remaining = [key for key in remaining if key != api_key]
                    api_key = ""
                    attempt = 0
                    continue
                attempt += 1
                time.sleep(delay)
        self._pool_exhausted(keys)

    async def _agenerate(self, *args: Any, **kwargs: Any) -> Any:
        if self.streaming:
            return await super()._agenerate(*args, **kwargs)
        keys = self._keys()
        remaining = list(keys)
        api_key = ""
        attempt = 0
        while remaining:
            candidates = [api_key] if api_key else remaining
            try:
                async with _reserved_async_model_call("langchain-agenerate", candidates) as selected:
                    api_key = selected
                    if api_key_retry_after(api_key, model=str(self.model_name or "")) > 0:
                        remaining = [key for key in remaining if key != api_key]
                        api_key = ""
                        attempt = 0
                        continue
                    return await super()._agenerate(*args, **{**kwargs, "extra_headers": self._headers(api_key, kwargs)})
            except Exception as exc:
                action, delay = self._handle_attempt_error(api_key, exc, remaining, attempt)
                if action == "next":
                    remaining = [key for key in remaining if key != api_key]
                    api_key = ""
                    attempt = 0
                    continue
                attempt += 1
                await asyncio.sleep(delay)
        self._pool_exhausted(keys)

    async def _astream(self, *args: Any, **kwargs: Any) -> Any:
        keys = self._keys()
        remaining = list(keys)
        api_key = ""
        attempt = 0
        while remaining:
            emitted = False
            candidates = [api_key] if api_key else remaining
            try:
                async with _reserved_async_model_call("langchain-astream", candidates) as selected:
                    api_key = selected
                    if api_key_retry_after(api_key, model=str(self.model_name or "")) > 0:
                        remaining = [key for key in remaining if key != api_key]
                        api_key = ""
                        attempt = 0
                        continue
                    async for item in super()._astream(*args, **{**kwargs, "extra_headers": self._headers(api_key, kwargs)}):
                        emitted = True
                        yield item
                return
            except Exception as exc:
                action, delay = self._handle_attempt_error(api_key, exc, remaining, attempt, emitted=emitted)
                if action == "next":
                    remaining = [key for key in remaining if key != api_key]
                    api_key = ""
                    attempt = 0
                    continue
                attempt += 1
                await asyncio.sleep(delay)
        self._pool_exhausted(keys)

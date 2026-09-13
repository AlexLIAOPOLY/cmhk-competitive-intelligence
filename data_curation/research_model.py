"""SDK tool streams with complete arguments and bounded route recovery."""
from contextvars import ContextVar
import hashlib
import json
import logging
import uuid

from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk

from cmhk.ai.ai_key_rotation import APIKeyPoolUnavailable, is_transient_llm_error
from cmhk.ai.ai_rate_limit import RateLimitedChatDeepSeek
from cmhk.intelligence.agent_harness import TruncatedModelOutput


class _ToolStreamAudit:
    """Observe SDK chunks before LangChain's permissive partial-JSON parser."""

    def __init__(self):
        self.identity = {}
        self.finish_reason = None
        self.tools = {}
        self.content = []
        self.reasoning = []
        self.bytes_seen = 0
        self.chunks_seen = 0

    def observe(self, chunk):
        self.chunks_seen += 1
        self.bytes_seen += len(json.dumps(chunk, ensure_ascii=False).encode())
        if self.bytes_seen > 8 * 1024 * 1024:
            raise TruncatedModelOutput("研究模型流超过大小上限；未执行工具")
        for key in ("id", "model", "created"):
            value = chunk.get(key)
            if value is not None and value != "":
                if key in self.identity and self.identity[key] != value:
                    raise TruncatedModelOutput("研究模型流响应身份改变；未执行工具")
                self.identity[key] = value
        choices = chunk.get("choices") or []
        if not choices:  # SDK's optional usage-only trailer.
            return
        if len(choices) != 1 or choices[0].get("index", 0) != 0:
            raise TruncatedModelOutput("研究模型流返回多个候选；未执行工具")
        choice = choices[0]
        delta = choice.get("delta") or {}
        if self.finish_reason is not None and (delta or choice.get("finish_reason")):
            raise TruncatedModelOutput("研究模型流结束后仍返回内容；未执行工具")
        for field, parts in (("content", self.content), ("reasoning_content", self.reasoning)):
            if delta.get(field) is not None:
                if not isinstance(delta[field], str):
                    raise TruncatedModelOutput("研究模型流文本格式异常；未执行工具")
                parts.append(delta[field])
        for fragment in delta.get("tool_calls") or []:
            index = fragment.get("index")
            if not isinstance(index, int) or index < 0:
                raise TruncatedModelOutput("研究模型工具索引缺失；未执行工具")
            call = self.tools.setdefault(index, {"id": "", "name": "", "arguments": ""})
            if fragment.get("id"):
                if call["id"] and call["id"] != fragment["id"]:
                    raise TruncatedModelOutput("研究模型工具身份改变；未执行工具")
                call["id"] = fragment["id"]
            function = fragment.get("function") or {}
            for source, target in (("name", "name"), ("arguments", "arguments")):
                value = function.get(source)
                if value is not None:
                    if not isinstance(value, str):
                        raise TruncatedModelOutput("研究模型工具参数格式异常；未执行工具")
                    call[target] += value
        if choice.get("finish_reason"):
            self.finish_reason = choice["finish_reason"]

    def complete(self):
        if not self.identity.get("id") or not self.identity.get("model") or not self.finish_reason:
            raise TruncatedModelOutput("研究模型流缺少身份或结束标记；未执行工具")
        calls = [self.tools[index] for index in sorted(self.tools)]
        audit = {
            "response_id": self.identity["id"], "model": self.identity["model"],
            "finish_reason": self.finish_reason,
            "content_sha256": hashlib.sha256(json.dumps({
                "content": "".join(self.content), "reasoning": "".join(self.reasoning),
                "tool_calls": calls,
            }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        }
        if self.finish_reason in {"length", "max_tokens", "max_output_tokens", "content_filter", "error", "cancelled"}:
            # Preserve the harness's existing truncation budget escalation, but
            # never expose partial tool arguments as executable tool calls.
            return audit, False
        if self.finish_reason not in {"stop", "tool_calls"}:
            raise TruncatedModelOutput("研究模型流结束状态异常；未执行工具")
        if self.finish_reason == "tool_calls" and not calls:
            raise TruncatedModelOutput("研究模型流缺少工具参数；未执行工具")
        identities = set()
        for call in calls:
            if not call["id"] or not call["name"] or call["id"] in identities:
                raise TruncatedModelOutput("研究模型工具标识缺失或重复；未执行工具")
            identities.add(call["id"])
            try:
                arguments = json.loads(call["arguments"])
            except (TypeError, ValueError) as exc:
                raise TruncatedModelOutput("研究模型工具参数未闭合；未执行工具") from exc
            if not isinstance(arguments, dict):
                raise TruncatedModelOutput("研究模型工具参数不是对象；未执行工具")
        return audit, True


_STREAM_AUDIT = ContextVar("research_tool_stream_audit", default=None)


def _isolated_stream_options(kwargs):
    request_id = uuid.uuid4().hex
    return {**kwargs,
        "extra_headers": {**(kwargs.get("extra_headers") or {}),
                          "Cache-Control": "no-cache, no-store", "Pragma": "no-cache",
                          "X-Request-ID": request_id},
        "extra_query": {**(kwargs.get("extra_query") or {}), "research_request_id": request_id}}


def _completed_chunks(chunks, tracker):
    audit, complete = tracker.complete()
    if complete:
        yield from chunks
        yield ChatGenerationChunk(message=AIMessageChunk(
            content="", response_metadata={"research_stream_audit": audit}))
    else:
        usage = next((chunk.message.usage_metadata for chunk in reversed(chunks)
                      if getattr(chunk.message, "usage_metadata", None)), None)
        yield ChatGenerationChunk(message=AIMessageChunk(
            content="", usage_metadata=usage, response_metadata={"research_stream_audit": audit}),
            generation_info={"finish_reason": audit["finish_reason"], "model_name": audit["model"]})


def configured_research_models(primary):
    from cmhk.ai.ai_config import load_ai_config
    config = load_ai_config(include_key=False)
    return list(dict.fromkeys([primary, *(
        name for name in (config.get("model_api_keys") or {})
        if name.casefold().startswith("deepseek")
    )]))


class ResearchChatDeepSeek(RateLimitedChatDeepSeek):
    def _convert_chunk_to_generation_chunk(self, chunk, *args, **kwargs):
        tracker = _STREAM_AUDIT.get()
        if tracker is not None:
            tracker.observe(chunk)
        return super()._convert_chunk_to_generation_chunk(chunk, *args, **kwargs)

    def _stream(self, *args, **kwargs):
        models = configured_research_models(self.model_name)
        options = _isolated_stream_options(kwargs)
        for index, name in enumerate(models):
            tracker = _ToolStreamAudit()
            token = _STREAM_AUDIT.set(tracker)
            try:
                candidate = self.model_copy(update={"model_name": name})
                # The base owns shared quota/key cooldowns. Buffer SDK chunks so
                # no caller can execute a permissively parsed partial tool call.
                chunks = list(RateLimitedChatDeepSeek._stream(candidate, *args, **options))
                yield from _completed_chunks(chunks, tracker)
                return
            except Exception as exc:
                if tracker.chunks_seen or index == len(models) - 1 or not (
                    isinstance(exc, APIKeyPoolUnavailable) or is_transient_llm_error(exc)
                ):
                    raise
                logging.warning("研究模型 %s 暂不可用（%s），使用已配置备用模型 %s",
                                name, type(exc).__name__, models[index + 1])
            finally:
                _STREAM_AUDIT.reset(token)

    async def _astream(self, *args, **kwargs):
        models = configured_research_models(self.model_name)
        options = _isolated_stream_options(kwargs)
        for index, name in enumerate(models):
            tracker = _ToolStreamAudit()
            token = _STREAM_AUDIT.set(tracker)
            try:
                candidate = self.model_copy(update={"model_name": name})
                chunks = [chunk async for chunk in RateLimitedChatDeepSeek._astream(candidate, *args, **options)]
                for chunk in _completed_chunks(chunks, tracker):
                    yield chunk
                return
            except Exception as exc:
                if tracker.chunks_seen or index == len(models) - 1 or not (
                    isinstance(exc, APIKeyPoolUnavailable) or is_transient_llm_error(exc)
                ):
                    raise
                logging.warning("研究模型 %s 暂不可用（%s），使用已配置备用模型 %s",
                                name, type(exc).__name__, models[index + 1])
            finally:
                _STREAM_AUDIT.reset(token)

    def _generate(self, *args, **kwargs):
        if self.streaming:
            return super()._generate(*args, **kwargs)
        models = configured_research_models(self.model_name)
        for index, name in enumerate(models):
            candidate = self.model_copy(update={"model_name": name})
            try:
                return RateLimitedChatDeepSeek._generate(candidate, *args, **kwargs)
            except Exception as exc:
                if index == len(models) - 1 or not (isinstance(exc, APIKeyPoolUnavailable) or is_transient_llm_error(exc)):
                    raise
                logging.warning("研究模型 %s 暂不可用（%s），使用已配置备用模型 %s", name, type(exc).__name__, models[index + 1])

    async def _agenerate(self, *args, **kwargs):
        if self.streaming:
            return await super()._agenerate(*args, **kwargs)
        models = configured_research_models(self.model_name)
        for index, name in enumerate(models):
            candidate = self.model_copy(update={"model_name": name})
            try:
                return await RateLimitedChatDeepSeek._agenerate(candidate, *args, **kwargs)
            except Exception as exc:
                if index == len(models) - 1 or not (isinstance(exc, APIKeyPoolUnavailable) or is_transient_llm_error(exc)):
                    raise
                logging.warning("研究模型 %s 暂不可用（%s），使用已配置备用模型 %s", name, type(exc).__name__, models[index + 1])

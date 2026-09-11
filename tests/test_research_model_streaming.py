"""Real SDK tool-call reconstruction; no network or production data writes."""
import asyncio
from contextlib import ExitStack, contextmanager
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
from langchain_core.messages import HumanMessage

from ai_key_rotation import APIKeyPoolUnavailable
from ai_rate_limit import RateLimitedChatDeepSeek
from cmhk.intelligence.agent_harness import TruncatedModelOutput, assert_complete
from data_curation.research_model import ResearchChatDeepSeek


HISTORICAL = json.loads((Path(__file__).parent / "fixtures/research_tool_arguments_singtel.json").read_text())
TOOL = {"type": "function", "function": {"name": "submit_metric", "description": "Submit one metric",
        "parameters": {"type": "object", "properties": {"status": {"type": "string"}}}}}
CHOICE = {"type": "function", "function": {"name": "submit_metric"}}


def event(delta=None, *, finish=None, response_id="actual-response-1", model="actual-model"):
    return {"id": response_id, "model": model, "created": 1770000000,
            "object": "chat.completion.chunk", "choices": [
                {"index": 0, "delta": delta or {}, "finish_reason": finish}]}


def tool_events(arguments=None, *, finish="tool_calls", response_id="actual-response-1"):
    raw = json.dumps(HISTORICAL["arguments"] if arguments is None else arguments, ensure_ascii=False)
    events = [event({"role": "assistant", "content": ""}, response_id=response_id)]
    # Deliberately split inside escaped strings, numbers and long quotations.
    for index in range(0, len(raw), 37):
        tool = {"index": 0, "function": {"arguments": raw[index:index + 37]}}
        if index == 0:
            tool.update({"id": "call-historical-1", "type": "function"})
            tool["function"]["name"] = "submit_metric"
        events.append(event({"tool_calls": [tool]}, response_id=response_id))
    events.append(event(finish=finish, response_id=response_id))
    events.append({"id": response_id, "model": "actual-model", "created": 1770000000,
                   "choices": [], "usage": {"prompt_tokens": 50, "completion_tokens": 30, "total_tokens": 80}})
    return events


def sse(events):
    return b"".join(("data: " + json.dumps(item, ensure_ascii=False) + "\n\n").encode() for item in events) + b"data: [DONE]\n\n"


@contextmanager
def quota_isolation():
    with ExitStack() as stack:
        stack.enter_context(patch.object(RateLimitedChatDeepSeek, "_keys", return_value=["fixture-key"]))
        stack.enter_context(patch("ai_rate_limit.api_key_retry_after", return_value=0))
        from ai_dispatch import model_call, async_model_call
        reserve = stack.enter_context(patch("ai_rate_limit.model_call", wraps=model_call))
        async_reserve = stack.enter_context(patch("ai_rate_limit.async_model_call", wraps=async_model_call))
        reserve.async_reserve = async_reserve
        stack.enter_context(patch("data_curation.research_model.configured_research_models", return_value=["primary", "backup"]))
        yield reserve


@contextmanager
def client_model(handler):
    requests = []
    def transport(request):
        requests.append({"payload": json.loads(request.content), "url": str(request.url),
                         "cache_control": request.headers.get("Cache-Control"),
                         "request_id": request.headers.get("X-Request-ID")})
        return handler(len(requests))
    with quota_isolation() as reserve, httpx.Client(transport=httpx.MockTransport(transport)) as client:
        model = ResearchChatDeepSeek(model="primary", api_key="fixture-key", base_url="https://example.test/v1",
            http_client=client, max_retries=0, streaming=True, stream_usage=True,
            extra_body={"thinking": {"type": "disabled"}, "cache": {"no-cache": True, "no-store": True}})
        yield model, requests, reserve


def response(events):
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse(events))


class BrokenStream(httpx.SyncByteStream):
    def __iter__(self):
        yield sse(tool_events()[:2]).removesuffix(b"data: [DONE]\n\n")
        raise httpx.ReadError("fixture interrupted after tool fragment")


class ResearchModelStreamingTests(unittest.TestCase):
    def test_historical_arguments_reconstructed_once_with_actual_identity_and_quota(self):
        with client_model(lambda _: response(tool_events())) as (model, requests, reserve):
            result = model.bind_tools([TOOL], tool_choice=CHOICE).invoke([HumanMessage(content="fixture")], max_tokens=8192)
        assert_complete(result)
        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_calls[0]["args"], HISTORICAL["arguments"])
        self.assertEqual(result.tool_calls[0]["id"], "call-historical-1")
        audit = result.response_metadata["research_stream_audit"]
        self.assertEqual(audit["response_id"], "actual-response-1")
        self.assertEqual(audit["model"], "actual-model")
        self.assertEqual(audit["finish_reason"], "tool_calls")
        self.assertEqual(len(audit["content_sha256"]), 64)
        self.assertEqual(len(requests), 1)
        reserve.assert_called_once_with("langchain-stream")
        self.assertTrue(requests[0]["payload"]["stream"])
        self.assertEqual(requests[0]["payload"]["max_tokens"], 8192)
        self.assertEqual(requests[0]["payload"]["tool_choice"], CHOICE)
        self.assertEqual(requests[0]["payload"]["thinking"], {"type": "disabled"})
        self.assertEqual(requests[0]["payload"]["cache"], {"no-cache": True, "no-store": True})
        self.assertIn("no-store", requests[0]["cache_control"])
        self.assertIn(requests[0]["request_id"], requests[0]["url"])
        self.assertEqual(model.model_name, "primary")

    def test_length_hides_partial_tools_but_preserves_harness_budget_and_audit(self):
        from data_curation.research_harness import ResearchHarness
        from data_curation.six_agent_research import validate_fact
        task = {"key": "hong-kong", "title": "test", "purpose": "test", "companies": ["HKT"]}
        saved, events = [], []
        def reply(number):
            return response(tool_events({"status": "missing", "reason": "fixture completed"},
                                        finish="length" if number < 3 else "tool_calls",
                                        response_id=f"actual-{number}"))
        with client_model(reply) as (model, requests, _):
            harness = ResearchHarness(task, model, lambda *event: events.append(event), validate_fact)
            harness.extract("HKT", "收入", {}, saved.append)
        self.assertEqual([r["payload"]["max_tokens"] for r in requests], [4096, 8192, 16384])
        self.assertEqual(len(saved), 1)
        responses = [e[2] for e in events if e[0] == "model_response"]
        self.assertEqual([e["stream_response_id"] for e in responses], ["actual-1", "actual-2", "actual-3"])
        self.assertEqual([e["stream_finish_reason"] for e in responses], ["length", "length", "tool_calls"])
        self.assertTrue(all(len(e["stream_content_sha256"]) == 64 for e in responses))
        self.assertEqual(len({r["request_id"] for r in requests}), 3)

    def test_length_response_cannot_expose_any_tool_calls(self):
        with client_model(lambda _: response(tool_events(finish="length"))) as (model, requests, _):
            result = model.invoke("fixture")
        self.assertEqual(result.tool_calls, [])
        with self.assertRaises(TruncatedModelOutput):
            assert_complete(result)
        self.assertEqual(len(requests), 1)

    def test_half_stream_is_not_retried_or_routed_after_a_fragment(self):
        with client_model(lambda _: httpx.Response(200, headers={"content-type": "text/event-stream"},
                                                   stream=BrokenStream())) as (model, requests, _):
            with self.assertRaises(httpx.ReadError):
                model.invoke("fixture")
        self.assertEqual(len(requests), 1)

    def test_unfinished_json_is_rejected_even_when_sdk_can_fill_closing_brace(self):
        events = tool_events({"status": "missing"})
        events[1]["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"] = '{"status":"missing"'
        with client_model(lambda _: response(events)) as (model, requests, _):
            with self.assertRaisesRegex(TruncatedModelOutput, "未闭合"):
                model.invoke("fixture")
        self.assertEqual(len(requests), 1)

    def test_identity_changes_missing_finish_and_duplicate_calls_fail_closed(self):
        identity = tool_events({"status": "missing"})
        identity[-2]["id"] = "different-response"
        changed_model = tool_events({"status": "missing"})
        changed_model[-2]["model"] = "different-model"
        duplicate = tool_events({"status": "missing"})
        call = json.loads(json.dumps(duplicate[1]["choices"][0]["delta"]["tool_calls"][0]))
        call["index"] = 1
        duplicate[1]["choices"][0]["delta"]["tool_calls"].append(call)
        for events in (identity, changed_model, tool_events({"status": "missing"})[:-2], duplicate):
            with self.subTest(events=events[-1]), client_model(lambda _: response(events)) as (model, requests, _):
                with self.assertRaises(TruncatedModelOutput):
                    model.invoke("fixture")
                self.assertEqual(len(requests), 1)

    def test_cached_nonstream_json_is_never_accepted_as_an_empty_stream(self):
        with client_model(lambda _: httpx.Response(200, json={"id": "cached", "choices": []})) as (model, requests, _):
            with self.assertRaises(TruncatedModelOutput):
                model.invoke("fixture")
        self.assertEqual(len(requests), 1)

    def test_backup_route_before_first_chunk_keeps_tool_choice_and_quota(self):
        original = RateLimitedChatDeepSeek._stream
        routes = []
        def route(candidate, *args, **kwargs):
            routes.append((candidate.model_name, kwargs.get("tool_choice")))
            if candidate.model_name == "primary":
                raise APIKeyPoolUnavailable(120, 3)
            yield from original(candidate, *args, **kwargs)
        with client_model(lambda _: response(tool_events())) as (model, requests, reserve), \
                patch.object(RateLimitedChatDeepSeek, "_stream", new=route):
            result = model.bind_tools([TOOL], tool_choice=CHOICE).invoke("fixture")
        self.assertEqual(routes, [("primary", CHOICE), ("backup", CHOICE)])
        self.assertEqual(requests[0]["payload"]["model"], "backup")
        self.assertEqual(result.tool_calls[0]["args"], HISTORICAL["arguments"])
        self.assertEqual(model.model_name, "primary")
        reserve.assert_called_once_with("langchain-stream")

    def test_async_sdk_tool_reconstruction_and_route_fallback(self):
        async def run():
            requests = []
            async def transport(request):
                requests.append(json.loads(request.content))
                return response(tool_events())
            original = RateLimitedChatDeepSeek._astream
            routes = []
            async def route(candidate, *args, **kwargs):
                routes.append(candidate.model_name)
                if candidate.model_name == "primary":
                    raise APIKeyPoolUnavailable(120, 3)
                async for chunk in original(candidate, *args, **kwargs):
                    yield chunk
            with quota_isolation() as reserve, patch.object(RateLimitedChatDeepSeek, "_astream", new=route):
                async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
                    model = ResearchChatDeepSeek(model="primary", api_key="fixture-key", base_url="https://example.test/v1",
                                                http_async_client=client, streaming=True, max_retries=0)
                    result = await model.bind_tools([TOOL], tool_choice=CHOICE).ainvoke("fixture")
            self.assertEqual(routes, ["primary", "backup"])
            self.assertEqual(len(requests), 1)
            self.assertEqual(result.tool_calls[0]["args"], HISTORICAL["arguments"])
            self.assertEqual(result.response_metadata["research_stream_audit"]["response_id"], "actual-response-1")
            reserve.async_reserve.assert_called_once_with("langchain-astream")
        asyncio.run(run())

    def test_factory_enables_sdk_streaming_and_preserves_request_budget(self):
        from data_curation.workflow import _build_supervisor_model
        with patch("data_curation.workflow.load_ai_config", return_value={
            "api_key": "fixture-key", "model": "primary", "base_url": "https://example.test/v1"}):
            model = _build_supervisor_model(max_tokens=4096, max_retries=0)
        self.assertTrue(model.streaming)
        self.assertEqual(model.max_tokens, 4096)
        self.assertEqual(model.max_retries, 0)


if __name__ == "__main__":
    unittest.main()

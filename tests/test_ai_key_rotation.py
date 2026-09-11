from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from unittest import mock

from langchain_core.messages import HumanMessage

import ai_key_rotation
import ai_config
from ai_config import api_key_candidates
from ai_rate_limit import RateLimitedChatDeepSeek, _ChatDeepSeek


class _Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _http_error(code: int, payload: dict) -> urllib.error.HTTPError:
    raw = json.dumps(payload).encode("utf-8")
    return urllib.error.HTTPError(
        "http://internal/v1/chat/completions",
        code,
        "failed",
        {},
        io.BytesIO(raw),
    )


def test_api_key_candidates_deduplicates_global_and_model_scoped_keys() -> None:
    config = {
        "api_key": "primary",
        "api_keys": ["primary", "backup"],
        "strategy_api_keys": ["backup"],
        "model_api_keys": {"free-model": ["free-only"]},
    }

    assert api_key_candidates(config, model="formal-model") == ["primary", "backup"]
    assert api_key_candidates(config, model="free-model") == [
        "primary",
        "backup",
        "free-only",
    ]


def test_explicit_global_pool_replaces_legacy_strategy_pool() -> None:
    config = {
        "api_key": "primary",
        "api_keys": ["primary", "new-backup"],
        "strategy_api_keys": ["legacy-backup"],
    }

    assert api_key_candidates(config, model="formal-model") == [
        "primary",
        "new-backup",
    ]


def test_public_config_masks_every_key_pool(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "ai_config.json"
    config_path.write_text(
        json.dumps(
            {
                "api_key": "key-primary-secret-value",
                "api_keys": ["key-primary-secret-value", "key-backup-secret-value"],
                "strategy_api_keys": ["key-legacy-secret-value"],
                "model_api_keys": {"free-model": ["key-free-secret-value"]},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ai_config, "AI_CONFIG_PATH", config_path)

    public = ai_config.load_ai_config(include_key=False)

    serialized = json.dumps(public)
    assert "secret-value" not in serialized
    assert public["api_keys"] == ["key-pr...alue", "key-ba...alue"]


def test_open_llm_request_rotates_after_budget_exceeded() -> None:
    request = urllib.request.Request(
        "http://internal/v1/chat/completions",
        data=b"{}",
        headers={"Authorization": "Bearer primary", "Content-Type": "application/json"},
        method="POST",
    )
    seen: list[str] = []

    def open_func(candidate: urllib.request.Request, *, timeout: float):
        seen.append(candidate.get_header("Authorization"))
        if len(seen) == 1:
            raise _http_error(
                400,
                {"error": {"type": "budget_exceeded", "message": "Budget has been exceeded!"}},
            )
        return _Response(b'{"ok":true}')

    with mock.patch.dict(ai_key_rotation._UNAVAILABLE_UNTIL, {}, clear=True):
        response = ai_key_rotation.open_llm_request(
            request,
            timeout=10,
            config={"api_key": "primary", "strategy_api_keys": ["backup"]},
            requested_key="primary",
            model="formal-model",
            open_func=open_func,
        )
        assert json.loads(response.read()) == {"ok": True}

    assert seen == ["Bearer primary", "Bearer backup"]


def test_open_llm_request_retries_transport_without_rotating() -> None:
    request = urllib.request.Request(
        "http://internal/v1/chat/completions",
        data=b"{}",
        method="POST",
    )
    open_func = mock.Mock(side_effect=urllib.error.URLError("offline"))

    with mock.patch.dict(ai_key_rotation._UNAVAILABLE_UNTIL, {}, clear=True):
        try:
            ai_key_rotation.open_llm_request(
                request,
                timeout=10,
                config={"api_key": "primary", "strategy_api_keys": ["backup"]},
                open_func=open_func,
            )
        except urllib.error.URLError:
            pass
        else:
            raise AssertionError("transport failure must be preserved")

    assert open_func.call_count == 3


def test_langchain_client_rotates_authorization_header() -> None:
    model = RateLimitedChatDeepSeek(
        model="formal-model",
        api_key="primary",
        api_base="http://internal/v1",
        max_retries=0,
    )
    completed = object()
    budget_error = RuntimeError("budget_exceeded: Budget has been exceeded!")

    with (
        mock.patch(
            "ai_rate_limit.load_ai_config",
            return_value={"api_key": "primary", "strategy_api_keys": ["backup"]},
        ),
        mock.patch("ai_rate_limit.wait_for_internal_ai_slot"),
        mock.patch.object(
            _ChatDeepSeek,
            "_generate",
            side_effect=[budget_error, completed],
        ) as generate,
        mock.patch.dict(ai_key_rotation._UNAVAILABLE_UNTIL, {}, clear=True),
    ):
        result = model._generate([HumanMessage(content="test")])

    assert result is completed
    assert generate.call_count == 2
    assert generate.call_args_list[0].kwargs["extra_headers"]["Authorization"] == "Bearer primary"
    assert generate.call_args_list[1].kwargs["extra_headers"]["Authorization"] == "Bearer backup"


import asyncio
import http.client
import os
import subprocess
import sys
from pathlib import Path

import pytest


POOL = {"api_keys": ["first-test-key", "second-test-key", "third-test-key"]}


def _request(stream=False):
    return urllib.request.Request("http://internal/v1/chat/completions", data=json.dumps({"stream": stream}).encode())


def _budget():
    return _http_error(400, {"error": {"type": "budget_exceeded"}})


def test_third_key_succeeds_and_future_requests_skip_both_failed_keys():
    seen = []
    def invoke(req, **kwargs):
        key = req.get_header("Authorization").removeprefix("Bearer ")
        seen.append(key)
        if key != POOL["api_keys"][2]:
            raise _budget()
        return _Response(b'{"ok":true}')
    for _ in range(2):
        with ai_key_rotation.open_llm_request(_request(), timeout=10, config=POOL, open_func=invoke) as response:
            assert json.load(response) == {"ok": True}
    assert seen == POOL["api_keys"] + [POOL["api_keys"][2]]


def test_all_three_fail_then_cooldown_stops_calls_and_expiry_recovers(monkeypatch):
    invoke = mock.Mock(side_effect=lambda *a, **k: (_ for _ in ()).throw(_budget()))
    with pytest.raises(ai_key_rotation.APIKeyPoolUnavailable) as failed:
        ai_key_rotation.open_llm_request(_request(), timeout=10, config=POOL, open_func=invoke)
    assert failed.value.key_count == 3
    assert failed.value.retryable
    assert failed.value.retry_after >= 599
    assert invoke.call_count == 3
    with pytest.raises(ai_key_rotation.APIKeyPoolUnavailable):
        ai_key_rotation.open_llm_request(_request(), timeout=10, config=POOL, open_func=invoke)
    assert invoke.call_count == 3
    now = ai_key_rotation.time.time()
    monkeypatch.setattr(ai_key_rotation.time, "time", lambda: now + 601)
    invoke.side_effect = None
    invoke.return_value = _Response(b'{"recovered":true}')
    assert json.load(ai_key_rotation.open_llm_request(_request(), timeout=10, config=POOL, open_func=invoke)) == {"recovered": True}


def test_cooldown_survives_process_restart_without_storing_credentials():
    ai_key_rotation.mark_api_key_unavailable(POOL["api_keys"][0], _budget(), raw_body=b"budget_exceeded")
    code = "from ai_key_rotation import ordered_api_keys; print(len(ordered_api_keys({'api_keys':['first-test-key','second-test-key','third-test-key']})))"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "2"
    state = Path(os.environ["CMHK_INTERNAL_AI_KEY_STATE_PATH"]).read_text()
    assert all(key not in state for key in POOL["api_keys"])
    assert "budget" in state


def test_model_permission_cooldown_does_not_disable_other_models():
    error = RuntimeError("team_model_access_denied")
    key = POOL["api_keys"][0]
    ai_key_rotation.mark_api_key_unavailable(key, error, model="Restricted")
    assert key not in ai_key_rotation.ordered_api_keys(POOL, model="Restricted")
    assert key in ai_key_rotation.ordered_api_keys(POOL, model="Allowed")


def test_rate_limit_is_distinct_from_budget_and_honors_retry_after():
    error = _http_error(429, {"error": {"type": "rate_limit"}})
    error.headers = {"Retry-After": "7"}
    key = POOL["api_keys"][0]
    ai_key_rotation.mark_api_key_unavailable(key, error)
    assert 5 < ai_key_rotation.api_key_retry_after(key) <= 7
    assert ai_key_rotation.key_failure_reason(error) == "rate_limit"
    assert ai_key_rotation.key_failure_reason(_budget(), raw_body=b"budget_exceeded") == "budget"


def test_nonstream_body_interruption_retries_without_exposing_partial_output():
    class Broken(_Response):
        def read(self, *args):
            raise http.client.IncompleteRead(b'{"partial":')
    broken = Broken(b"")
    invoke = mock.Mock(side_effect=[broken, _Response(b'{"complete":true}')])
    with mock.patch.object(ai_key_rotation.time, "sleep"):
        response = ai_key_rotation.open_llm_request(_request(), timeout=10, config=POOL, open_func=invoke)
    assert json.load(response) == {"complete": True}
    assert broken.closed
    assert invoke.call_count == 2
    assert invoke.call_args_list[0].args[0].get_header("Authorization") == invoke.call_args_list[1].args[0].get_header("Authorization")
    assert ai_key_rotation.ordered_api_keys(POOL) == POOL["api_keys"]


def test_urllib_stream_body_is_never_replayed():
    class BrokenStream(_Response):
        def read(self, *args):
            raise http.client.IncompleteRead(b"already emitted")
    stream = BrokenStream(b"")
    invoke = mock.Mock(return_value=stream)
    response = ai_key_rotation.open_llm_request(_request(stream=True), timeout=10, config=POOL, open_func=invoke)
    with pytest.raises(http.client.IncompleteRead):
        response.read()
    assert invoke.call_count == 1
    response.close()


def test_bad_request_is_not_retried_or_cooled():
    invoke = mock.Mock(side_effect=_http_error(400, {"error": "invalid schema"}))
    with pytest.raises(urllib.error.HTTPError) as caught:
        ai_key_rotation.open_llm_request(_request(), timeout=10, config=POOL, open_func=invoke)
    assert json.loads(caught.value.read()) == {"error": "invalid schema"}
    assert invoke.call_count == 1
    assert ai_key_rotation.ordered_api_keys(POOL) == POOL["api_keys"]


def test_retry_after_does_not_overrun_deadline():
    error = _http_error(503, {})
    error.headers = {"Retry-After": "60"}
    invoke = mock.Mock(side_effect=error)
    with mock.patch.object(ai_key_rotation.time, "sleep") as sleep:
        with pytest.raises(TimeoutError):
            ai_key_rotation.open_llm_request(_request(), timeout=10, config=POOL, open_func=invoke,
                                            deadline_monotonic=ai_key_rotation.time.monotonic() + 2)
    sleep.assert_not_called()
    assert invoke.call_count == 1


def test_asr_deployment_outage_does_not_disable_text_models():
    error = _http_error(429, {'error': {'message': 'No deployments available for selected model'}})
    ai_key_rotation.mark_api_key_unavailable(POOL['api_keys'][0], error, model='Qwen3ASR',
        raw_body=b'No deployments available for selected model')
    assert ai_key_rotation.api_key_retry_after(POOL['api_keys'][0], model='Qwen3ASR') > 0
    assert ai_key_rotation.api_key_retry_after(POOL['api_keys'][0], model='DeepSeek-V4-Pro') == 0


def _model():
    return RateLimitedChatDeepSeek(model="test-model", api_key=POOL["api_keys"][0], api_base="http://internal/v1", max_retries=0)


def test_langchain_sync_transport_retries_same_key():
    model = _model()
    with mock.patch("ai_rate_limit.load_ai_config", return_value=POOL), mock.patch("ai_rate_limit.wait_for_internal_ai_slot"), mock.patch("ai_rate_limit.time.sleep"), mock.patch.object(_ChatDeepSeek, "_generate", side_effect=[TimeoutError(), "done"]) as invoke:
        assert model._generate([]) == "done"
    assert invoke.call_count == 2
    assert invoke.call_args_list[0].kwargs == invoke.call_args_list[1].kwargs


def test_langchain_async_rotates_all_three_and_tracks_final_failure():
    model = _model()
    async def fail(*args, **kwargs):
        raise RuntimeError("budget_exceeded")
    with mock.patch("ai_rate_limit.load_ai_config", return_value=POOL), mock.patch("ai_rate_limit.wait_for_internal_ai_slot"), mock.patch.object(_ChatDeepSeek, "_agenerate", side_effect=fail) as invoke:
        with pytest.raises(ai_key_rotation.APIKeyPoolUnavailable):
            asyncio.run(model._agenerate([]))
    assert invoke.call_count == 3
    with pytest.raises(ai_key_rotation.APIKeyPoolUnavailable):
        ai_key_rotation.ordered_api_keys(POOL)


@pytest.mark.parametrize("asynchronous", [False, True])
def test_partial_langchain_stream_never_retries(asynchronous):
    model = _model()
    def stream(*args, **kwargs):
        yield "partial"
        raise TimeoutError("disconnected")
    async def astream(*args, **kwargs):
        yield "partial"
        raise TimeoutError("disconnected")
    async def collect():
        async for item in model._astream([]):
            emitted.append(item)
    emitted = []
    method = "_astream" if asynchronous else "_stream"
    with mock.patch("ai_rate_limit.load_ai_config", return_value=POOL), mock.patch("ai_rate_limit.wait_for_internal_ai_slot"), mock.patch.object(_ChatDeepSeek, method, side_effect=astream if asynchronous else stream) as invoke:
        with pytest.raises(TimeoutError):
            if asynchronous:
                asyncio.run(collect())
            else:
                emitted.extend(model._stream([]))
    assert emitted == ["partial"]
    assert invoke.call_count == 1


def test_strategic_route_shares_cooldowns_and_retries_read_interruption(tmp_path):
    import strategic_briefing as briefing
    ai_key_rotation.mark_api_key_unavailable(POOL["api_keys"][0], RuntimeError("budget_exceeded"))
    failed = mock.MagicMock()
    failed.__enter__.return_value.read.side_effect = http.client.IncompleteRead(b'{"partial":')
    complete = mock.MagicMock()
    complete.__enter__.return_value.read.return_value = json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}]}).encode()
    opener = mock.Mock()
    opener.open.side_effect = [failed, complete]
    with mock.patch.object(briefing, "load_ai_config", return_value={**POOL, "base_url": "http://internal/v1"}), mock.patch.object(briefing, "build_opener", return_value=opener), mock.patch.object(briefing, "wait_for_internal_ai_slot"), mock.patch.object(briefing.time, "sleep"):
        assert briefing._call_internal_ai_transport("system", "user") == {"ok": True}
    assert [call.args[0].get_header("Authorization") for call in opener.open.call_args_list] == ["Bearer second-test-key"] * 2


def test_pool_failure_keeps_checkpoint_retryable_and_completed_result_is_reused(tmp_path):
    from cmhk.intelligence.agent_harness import run_durable_agent
    calls = []
    def execute(attempt):
        calls.append(attempt)
        if len(calls) == 1:
            raise ai_key_rotation.APIKeyPoolUnavailable(10, 3)
        return {"ok": True}
    args = dict(namespace="pool-recovery", identity={"input": "unchanged"}, directory=tmp_path / "harness", execute=execute)
    with pytest.raises(ai_key_rotation.APIKeyPoolUnavailable):
        run_durable_agent(**args)
    assert run_durable_agent(**args) == {"ok": True}
    assert run_durable_agent(**args) == {"ok": True}
    assert len(calls) == 2


@pytest.mark.parametrize("asynchronous", [False, True])
def test_langchain_stream_before_first_chunk_retries_without_duplicate(asynchronous):
    model = _model()
    attempts = []
    def stream(*args, **kwargs):
        attempts.append(kwargs["extra_headers"]["Authorization"])
        if len(attempts) == 1:
            raise TimeoutError()
        yield "complete"
    async def astream(*args, **kwargs):
        for item in stream(*args, **kwargs):
            yield item
    async def collect():
        return [item async for item in model._astream([])]
    method = "_astream" if asynchronous else "_stream"
    with mock.patch("ai_rate_limit.load_ai_config", return_value=POOL), mock.patch("ai_rate_limit.wait_for_internal_ai_slot"), mock.patch("ai_rate_limit.time.sleep"), mock.patch("ai_rate_limit.asyncio.sleep", new_callable=mock.AsyncMock), mock.patch.object(_ChatDeepSeek, method, side_effect=astream if asynchronous else stream):
        assert (asyncio.run(collect()) if asynchronous else list(model._stream([]))) == ["complete"]
    assert attempts == ["Bearer first-test-key"] * 2


def test_simultaneous_workers_preserve_each_others_cooldowns():
    code = "from ai_key_rotation import mark_api_key_unavailable; import sys; mark_api_key_unavailable(sys.argv[1], RuntimeError('budget_exceeded'))"
    processes = [subprocess.Popen([sys.executable, "-c", code, key], stdout=subprocess.PIPE, stderr=subprocess.PIPE) for key in POOL["api_keys"]]
    for process in processes:
        _, error = process.communicate(timeout=15)
        assert process.returncode == 0, error.decode()
    with pytest.raises(ai_key_rotation.APIKeyPoolUnavailable):
        ai_key_rotation.ordered_api_keys(POOL)

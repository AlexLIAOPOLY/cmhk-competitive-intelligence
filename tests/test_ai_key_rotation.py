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


def test_open_llm_request_does_not_rotate_on_transport_failure() -> None:
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

    assert open_func.call_count == 1


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

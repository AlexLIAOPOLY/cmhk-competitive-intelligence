from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
AI_CONFIG_PATH = ROOT / "ai_config.json"
INTERNAL_AI_BASE_URL = (
    os.environ.get("CMHK_INTERNAL_AI_BASE_URL") or "http://10.0.62.177:4000/v1"
).strip().rstrip("/")
INTERNAL_AI_PROVIDER = (os.environ.get("CMHK_INTERNAL_AI_PROVIDER") or "deepseek").strip()
INTERNAL_AI_MODEL = (os.environ.get("CMHK_INTERNAL_AI_MODEL") or "deepseek-v4").strip()
INTERNAL_AI_API_KEY = (
    os.environ.get("CMHK_INTERNAL_AI_API_KEY") or os.environ.get("AI_API_KEY") or ""
).strip()

DEFAULT_AI_CONFIG = {
    "provider": INTERNAL_AI_PROVIDER,
    "base_url": INTERNAL_AI_BASE_URL,
    "model": INTERNAL_AI_MODEL,
    "api_key": INTERNAL_AI_API_KEY,
    "extra_parameters": {},
}


def is_internal_ai_base_url(value: str) -> bool:
    from urllib.parse import urlparse

    def normalized_endpoint(raw: str) -> tuple[str, str, int | None, str] | None:
        parsed = urlparse(str(raw or "").strip().rstrip("/"))
        host = parsed.hostname or ""
        if parsed.scheme.lower() not in {"http", "https"} or not host or parsed.query or parsed.fragment:
            return None
        return parsed.scheme.lower(), host.lower(), parsed.port, parsed.path.rstrip("/")

    return normalized_endpoint(value) == normalized_endpoint(INTERNAL_AI_BASE_URL)


def load_ai_config(include_key: bool = True) -> dict[str, Any]:
    config = DEFAULT_AI_CONFIG.copy()
    if AI_CONFIG_PATH.exists():
        try:
            saved = json.loads(AI_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                config.update({key: value for key, value in saved.items() if value is not None})
        except Exception:
            pass
    config["provider"] = config.get("provider") or INTERNAL_AI_PROVIDER
    config["base_url"] = config.get("base_url") or INTERNAL_AI_BASE_URL
    config["model"] = config.get("model") or INTERNAL_AI_MODEL
    config["api_key"] = config.get("api_key") or INTERNAL_AI_API_KEY
    if not is_internal_ai_base_url(str(config["base_url"])):
        config["base_url"] = INTERNAL_AI_BASE_URL
    if not include_key:
        api_key = str(config.get("api_key") or "")
        config["api_key"] = mask_api_key(api_key)
        config["has_api_key"] = bool(api_key)
    return config


def save_ai_config(payload: dict[str, Any]) -> dict[str, Any]:
    current = load_ai_config(include_key=True)
    provider = str(payload.get("provider") or current.get("provider") or "deepseek").strip()
    base_url = str(payload.get("base_url") or current.get("base_url") or "").strip().rstrip("/")
    if not is_internal_ai_base_url(base_url):
        raise ValueError("AI Base URL 必须是公司内网地址")
    model = str(payload.get("model") or current.get("model") or "").strip()
    incoming_key = str(payload.get("api_key") or "").strip()
    api_key = current.get("api_key", "") if incoming_key in {"", "********"} else incoming_key
    extra_parameters = payload.get("extra_parameters")
    if not isinstance(extra_parameters, dict):
        extra_parameters = current.get("extra_parameters") or {}
    config = {
        "provider": provider,
        "base_url": INTERNAL_AI_BASE_URL,
        "model": model or DEFAULT_AI_CONFIG["model"],
        "api_key": api_key,
        "extra_parameters": extra_parameters,
    }
    # These fields are managed locally because they may contain several secret
    # keys. Preserve them when the ordinary single-key settings form is saved.
    for field in ("strategy_api_keys", "model_api_keys"):
        if field in current:
            config[field] = current[field]
    AI_CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_ai_config(include_key=False)


def mask_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 10:
        return "********"
    return f"{api_key[:6]}...{api_key[-4:]}"

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
AI_CONFIG_PATH = ROOT / "ai_config.json"

DEFAULT_AI_CONFIG = {
    "provider": "deepseek",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-v4-flash",
    "api_key": "",
}


def load_ai_config(include_key: bool = True) -> dict[str, Any]:
    config = DEFAULT_AI_CONFIG.copy()
    if AI_CONFIG_PATH.exists():
        try:
            saved = json.loads(AI_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                config.update({key: value for key, value in saved.items() if value is not None})
        except Exception:
            pass
    config["provider"] = os.environ.get("AI_PROVIDER") or config.get("provider")
    config["base_url"] = os.environ.get("AI_BASE_URL") or config.get("base_url")
    config["model"] = os.environ.get("AI_MODEL") or config.get("model")
    config["api_key"] = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or config.get("api_key")
    if not include_key:
        api_key = str(config.get("api_key") or "")
        config["api_key"] = mask_api_key(api_key)
        config["has_api_key"] = bool(api_key)
    return config


def save_ai_config(payload: dict[str, Any]) -> dict[str, Any]:
    current = load_ai_config(include_key=True)
    provider = str(payload.get("provider") or current.get("provider") or "deepseek").strip()
    base_url = str(payload.get("base_url") or current.get("base_url") or "").strip().rstrip("/")
    model = str(payload.get("model") or current.get("model") or "").strip()
    incoming_key = str(payload.get("api_key") or "").strip()
    api_key = current.get("api_key", "") if incoming_key in {"", "********"} else incoming_key
    config = {
        "provider": provider,
        "base_url": base_url or DEFAULT_AI_CONFIG["base_url"],
        "model": model or DEFAULT_AI_CONFIG["model"],
        "api_key": api_key,
    }
    AI_CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_ai_config(include_key=False)


def mask_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 10:
        return "********"
    return f"{api_key[:6]}...{api_key[-4:]}"

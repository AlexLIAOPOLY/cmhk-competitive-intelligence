from __future__ import annotations

import base64
import json
import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from zoneinfo import ZoneInfo


HKT = ZoneInfo("Asia/Hong_Kong")
APP_ID = "cli_a9575e70ae799cb2"
LARK_CLI_DIR = Path.home() / "Library" / "Application Support" / "lark-cli"
APP_SECRET_FILE = LARK_CLI_DIR / f"appsecret_{APP_ID}.enc"
MASTER_KEY_FILE = LARK_CLI_DIR / "master.key.file"
STATE_DIR = Path(
    os.environ.get(
        "CMHK_STRATEGY_STATE_DIR",
        "/Users/liaowang/cmhk_public_crawl_app/strategy_briefing",
    )
)
VOTE_FILE = STATE_DIR / "news_votes.json"

_no_proxy_hosts = "open.feishu.cn,accounts.feishu.cn,.feishu.cn"
for _proxy_key in ("NO_PROXY", "no_proxy"):
    _existing_no_proxy = os.environ.get(_proxy_key, "")
    os.environ[_proxy_key] = ",".join(
        part for part in (_existing_no_proxy, _no_proxy_hosts) if part
    )

_lock = threading.RLock()
_started = False
_thread: threading.Thread | None = None


def _load_app_secret() -> str:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    encrypted = APP_SECRET_FILE.read_bytes()
    if len(encrypted) < 29:
        raise RuntimeError("飞书凭据文件无效")

    file_key = MASTER_KEY_FILE.read_bytes()
    if len(file_key) == 32:
        try:
            return AESGCM(file_key).decrypt(
                encrypted[:12], encrypted[12:], None
            ).decode("utf-8")
        except InvalidTag:
            pass

    result = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-s",
            "lark-cli",
            "-a",
            "master.key",
            "-w",
        ],
        capture_output=True,
        check=True,
        text=True,
        timeout=8,
    )
    encoded = result.stdout.strip()
    if encoded.startswith("go-keyring-base64:"):
        encoded = base64.b64decode(encoded.split(":", 1)[1]).decode("utf-8")
    keychain_key = base64.b64decode(encoded)
    if len(keychain_key) != 32:
        raise RuntimeError("macOS Keychain 主密钥无效")
    return AESGCM(keychain_key).decrypt(
        encrypted[:12], encrypted[12:], None
    ).decode("utf-8")


def _load_votes() -> dict[str, Any]:
    if not VOTE_FILE.exists():
        return {"version": 1, "items": {}}
    try:
        data = json.loads(VOTE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "items": {}}
    if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
        return {"version": 1, "items": {}}
    return data


def _save_votes(data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temp = VOTE_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(VOTE_FILE)


def record_vote(
    *,
    news_id: str,
    user_open_id: str,
    decision: str,
    message_id: str = "",
) -> dict[str, int]:
    if decision not in {"approve", "hold", "reject"}:
        raise ValueError("未知确认操作")
    with _lock:
        data = _load_votes()
        item = data["items"].setdefault(news_id, {"votes": {}})
        item["votes"][user_open_id] = {
            "decision": decision,
            "updated_at": datetime.now(HKT).isoformat(timespec="seconds"),
            "message_id": message_id,
        }
        _save_votes(data)
        return vote_counts(item)


def vote_counts(item_or_news_id: dict[str, Any] | str) -> dict[str, int]:
    if isinstance(item_or_news_id, str):
        with _lock:
            item = _load_votes()["items"].get(item_or_news_id, {})
    else:
        item = item_or_news_id
    counts = {"approve": 0, "hold": 0, "reject": 0}
    for vote in item.get("votes", {}).values():
        decision = vote.get("decision")
        if decision in counts:
            counts[decision] += 1
    return counts


def _handle_card_action(data: Any) -> Any:
    from lark_oapi.event.callback.model.p2_card_action_trigger import (
        P2CardActionTriggerResponse,
    )

    event = getattr(data, "event", None)
    action = getattr(event, "action", None)
    value = getattr(action, "value", None) or {}
    if value.get("action") != "news_vote":
        return P2CardActionTriggerResponse(
            {"toast": {"type": "warning", "content": "无法识别此操作"}}
        )

    news_id = str(value.get("news_id", "")).strip()
    decision = str(value.get("decision", "")).strip()
    operator = getattr(event, "operator", None)
    user_open_id = str(getattr(operator, "open_id", "") or "").strip()
    context = getattr(event, "context", None)
    message_id = str(getattr(context, "open_message_id", "") or "").strip()
    if not news_id or not user_open_id:
        return P2CardActionTriggerResponse(
            {"toast": {"type": "error", "content": "缺少新闻或用户信息，未记录"}}
        )

    try:
        counts = record_vote(
            news_id=news_id,
            user_open_id=user_open_id,
            decision=decision,
            message_id=message_id,
        )
    except Exception as exc:
        return P2CardActionTriggerResponse(
            {"toast": {"type": "error", "content": f"记录失败：{exc}"}}
        )

    decision_text = {
        "approve": "确认进入滚动新闻",
        "hold": "暂缓",
        "reject": "不采纳",
    }[decision]
    content = (
        f"已记录：{decision_text}｜赞成 {counts['approve']} · "
        f"暂缓 {counts['hold']} · 不采纳 {counts['reject']}"
    )
    return P2CardActionTriggerResponse(
        {"toast": {"type": "success", "content": content}}
    )


def _run_forever() -> None:
    import truststore

    truststore.inject_into_ssl()
    import lark_oapi as lark
    from lark_oapi import ws

    handler = (
        lark.EventDispatcherHandler.builder("", "", lark.LogLevel.INFO)
        .register_p2_card_action_trigger(_handle_card_action)
        .build()
    )
    client = ws.Client(
        APP_ID,
        _load_app_secret(),
        log_level=lark.LogLevel.INFO,
        event_handler=handler,
        domain="https://open.feishu.cn",
        auto_reconnect=True,
    )
    client.start()


def ensure_started() -> threading.Thread:
    global _started, _thread
    with _lock:
        if _started and _thread is not None and _thread.is_alive():
            return _thread
        _thread = threading.Thread(
            target=_run_forever,
            name="strategic-news-vote-listener",
            daemon=True,
        )
        _thread.start()
        _started = True
        return _thread


def main() -> None:
    _run_forever()


if __name__ == "__main__":
    main()

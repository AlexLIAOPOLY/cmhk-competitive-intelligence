from __future__ import annotations

import base64
import json
import os
import selectors
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from zoneinfo import ZoneInfo


HKT = ZoneInfo("Asia/Hong_Kong")
ROOT = Path(__file__).resolve().parent
APP_ID = (
    os.environ.get("CMHK_FEISHU_EVENT_APP_ID")
    or os.environ.get("CMHK_FEISHU_APP_ID")
    or os.environ.get("FEISHU_APP_ID")
    or "cli_a9575e70ae799cb2"
).strip()
LARK_CLI_DIR = Path.home() / "Library" / "Application Support" / "lark-cli"
APP_SECRET_FILE = LARK_CLI_DIR / f"appsecret_{APP_ID}.enc"
MASTER_KEY_FILE = LARK_CLI_DIR / "master.key.file"
STATE_DIR = Path(
    os.environ.get(
        "CMHK_STRATEGY_STATE_DIR",
        str(ROOT / "var" / "strategy_briefing"),
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
_project_card_handler: Any | None = None
_sidecar_thread: threading.Thread | None = None
_sidecar_processes: dict[str, subprocess.Popen[str]] = {}
SHEET_EDIT_SIDECAR = Path(
    os.environ.get(
        "CMHK_FEISHU_SHEET_EDIT_LISTENER_BIN",
        str(ROOT / "var" / "bin" / "lark-cli-drive"),
    )
)
SHEET_EDIT_APP_ID = (
    os.environ.get("CMHK_FEISHU_SHEET_EDIT_APP_ID")
    or "cli_a9575e70ae799cb2"
).strip()


def _load_app_secret() -> str:
    configured = (
        os.environ.get("CMHK_FEISHU_EVENT_APP_SECRET")
        or os.environ.get("CMHK_FEISHU_APP_SECRET")
        or os.environ.get("FEISHU_APP_SECRET")
        or ""
    ).strip()
    if configured:
        return configured
    if not APP_SECRET_FILE.is_file() or not MASTER_KEY_FILE.is_file():
        raise RuntimeError(
            "服务器未配置 CMHK_FEISHU_EVENT_APP_SECRET 或 CMHK_FEISHU_APP_SECRET"
        )

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
        try:
            result = _handle_project_card_action(data)
        except Exception as exc:
            return P2CardActionTriggerResponse(
                {"toast": {"type": "error", "content": f"处理失败：{exc}"}}
            )
        if str(result.get("status") or "") != "ignored":
            return P2CardActionTriggerResponse(
                {"toast": {"type": "success", "content": "操作已处理"}}
            )
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


def _fetch_card_content(message_id: str) -> str:
    if not message_id:
        return ""
    command = [
        "lark-cli",
        "api",
        "GET",
        f"/open-apis/im/v1/messages/{message_id}",
        "--params",
        json.dumps({"card_msg_content_type": "user_card_content"}),
        "--as",
        "bot",
        "--profile",
        APP_ID,
        "--format",
        "json",
    ]
    env = dict(os.environ)
    env["LARK_CLI_NO_PROXY"] = "1"
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if result.returncode != 0:
        return ""
    try:
        payload = json.loads(result.stdout)
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""
    data = payload.get("data") if isinstance(payload, dict) else None
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        return ""
    body = items[0].get("body") if isinstance(items[0], dict) else None
    return str(body.get("content") or "") if isinstance(body, dict) else ""


def _flatten_card_action(data: Any) -> dict[str, Any]:
    event = getattr(data, "event", None)
    header = getattr(data, "header", None)
    operator = getattr(event, "operator", None)
    action = getattr(event, "action", None)
    context = getattr(event, "context", None)
    message_id = str(getattr(context, "open_message_id", "") or "").strip()
    value = getattr(action, "value", None)
    form_value = getattr(action, "form_value", None)
    options = getattr(action, "options", None)
    return {
        "type": "card.action.trigger",
        "event_id": str(getattr(header, "event_id", "") or ""),
        "timestamp": str(getattr(header, "create_time", "") or ""),
        "operator_id": str(getattr(operator, "open_id", "") or ""),
        "message_id": message_id,
        "chat_id": str(getattr(context, "open_chat_id", "") or ""),
        "host": str(getattr(event, "host", "") or ""),
        "token": str(getattr(event, "token", "") or ""),
        "action_tag": str(getattr(action, "tag", "") or ""),
        "action_value": json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else "",
        "action_name": str(getattr(action, "name", "") or ""),
        "form_value": json.dumps(form_value, ensure_ascii=False) if isinstance(form_value, dict) else "",
        "input_value": str(getattr(action, "input_value", "") or ""),
        "option": str(getattr(action, "option", "") or ""),
        "options": ",".join(str(item) for item in options) if isinstance(options, list) else "",
        "checked": bool(getattr(action, "checked", False)),
        "timezone": str(getattr(action, "timezone", "") or ""),
        "card_content": _fetch_card_content(message_id),
        "source_profile": APP_ID,
    }


def _handle_project_card_action(data: Any) -> dict[str, Any]:
    global _project_card_handler
    if _project_card_handler is None:
        from project_monitor_card_actions import CardActionHandler

        _project_card_handler = CardActionHandler(runtime_root=ROOT)
    return _project_card_handler.handle_event_process_safe(_flatten_card_action(data))


def _handle_drive_file_edit(data: Any) -> None:
    from cmhk.integrations.feishu_sheet_edit_events import (
        capture_drive_file_edit_event,
    )

    # The event module owns the canonical path.  Deriving it from STATE_DIR
    # previously inserted an extra ``var`` component and made the audit reader
    # and the WebSocket listener use different files.
    capture_drive_file_edit_event(data)


def _run_forever() -> None:
    import truststore

    truststore.inject_into_ssl()
    import lark_oapi as lark
    from lark_oapi import ws

    handler = (
        lark.EventDispatcherHandler.builder("", "", lark.LogLevel.INFO)
        .register_p2_card_action_trigger(_handle_card_action)
        .register_p2_drive_file_edit_v1(_handle_drive_file_edit)
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


def _write_sheet_edit_status(state: str, **extra: Any) -> None:
    path = ROOT / "var" / "auth" / "feishu-sheet-edit-listener-status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "state": state,
        "pid": os.getpid(),
        "updated_at": datetime.now(HKT).isoformat(timespec="milliseconds"),
        **extra,
    }
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


def _run_event_consumer(event_key: str) -> None:
    from cmhk.integrations.feishu_sheet_edit_events import capture_drive_file_edit_event

    while True:
        env = dict(os.environ)
        env["LARK_CLI_NO_PROXY_WARN"] = "1"
        try:
            process = subprocess.Popen(
                [
                    str(SHEET_EDIT_SIDECAR),
                    "event",
                    "consume",
                    event_key,
                    "--as",
                    "bot",
                    "--profile",
                    SHEET_EDIT_APP_ID,
                ],
                cwd=ROOT,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            _sidecar_processes[event_key] = process
            assert process.stdout is not None and process.stderr is not None
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            while process.poll() is None or selector.get_map():
                for key, _ in selector.select(timeout=1):
                    line = key.fileobj.readline()
                    if not line:
                        selector.unregister(key.fileobj)
                        continue
                    if key.data == "stderr":
                        print(f"[{event_key}] {line.rstrip()}", flush=True)
                        if event_key == "drive.file.edit_v1" and "[source] feishu-websocket: connected" in line:
                            _write_sheet_edit_status("connected", consumer_pid=process.pid)
                        continue
                    event = json.loads(line)
                    if event_key == "drive.file.edit_v1":
                        record = capture_drive_file_edit_event(event)
                        if record:
                            _write_sheet_edit_status(
                                "event_received",
                                consumer_pid=process.pid,
                                event_id=record.get("event_id", ""),
                                event_create_time=record.get("create_time", ""),
                            )
            selector.close()
            return_code = process.wait()
            print(f"Feishu {event_key} consumer exited ({return_code}); restarting", flush=True)
        except Exception as exc:
            print(f"Feishu {event_key} consumer failed: {exc}", flush=True)
        finally:
            _sidecar_processes.pop(event_key, None)
        threading.Event().wait(5)


def _run_sheet_edit_sidecar() -> None:
    """Keep the spreadsheet app's recognized lark-cli event bus alive."""
    _run_event_consumer("drive.file.edit_v1")


def _ensure_sheet_edit_sidecar() -> threading.Thread:
    global _sidecar_thread
    if _sidecar_thread is not None and _sidecar_thread.is_alive():
        return _sidecar_thread
    _sidecar_thread = threading.Thread(
        target=_run_sheet_edit_sidecar,
        name="feishu-sheet-edit-sidecar-supervisor",
        daemon=True,
    )
    _sidecar_thread.start()
    return _sidecar_thread


def ensure_started() -> threading.Thread:
    global _started, _thread
    with _lock:
        _ensure_sheet_edit_sidecar()
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

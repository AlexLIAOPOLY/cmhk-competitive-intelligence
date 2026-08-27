"""Handle CMHK incident and subscription Card 2.0 callbacks.

This listener is intentionally separate from the project monitor.  It consumes
only ``card.action.trigger`` events. Incident actions retain their strict
delivery-ledger verification; subscription form submissions are routed to the
server-side subscription store and acknowledged to the clicking user.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import selectors
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from project_monitor import (
    ERROR_LEDGER_COLUMNS,
    HKT,
    ProjectMonitor,
    _append_jsonl,
    _atomic_json,
    _command_env,
    _iso,
    _read_json,
    _redact,
    _to_simplified,
)
from cmhk.auth.service import AuthService
from cmhk.services.subscriptions import SubscriptionService


ROOT = Path(__file__).resolve().parent
INCIDENT_ID_RE = re.compile(r"[0-9a-f]{24}")


class CardActionHandler:
    def __init__(
        self,
        *,
        runtime_root: Path | str | None = None,
        config_path: Path | str | None = None,
        state_dir: Path | str | None = None,
        environ: dict[str, str] | None = None,
        now_fn: Callable[[], datetime] | None = None,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.runtime_root = Path(runtime_root or os.environ.get("CMHK_MONITOR_RUNTIME_ROOT") or ROOT)
        self.config_path = Path(config_path or (ROOT / "config" / "project_monitor.json"))
        self.state_dir = Path(
            state_dir
            or os.environ.get("CMHK_MONITOR_STATE_DIR")
            or (self.runtime_root / "var" / "project_monitor")
        )
        self.environ = dict(environ or os.environ)
        self.now_fn = now_fn or (lambda: datetime.now(HKT))
        self.monitor = ProjectMonitor(
            runtime_root=self.runtime_root,
            config_path=self.config_path,
            state_dir=self.state_dir,
            environ=self.environ,
            now_fn=self.now_fn,
            command_runner=command_runner,
        )
        self.subscription_service = SubscriptionService(
            runtime_root=self.runtime_root,
            config_path=self.config_path,
            environ=self.environ,
            command_runner=self._run,
        )
        self.auth_service = AuthService(self.runtime_root)
        self.config = self.monitor.config
        self.actions_config = (
            self.config.get("card_actions")
            if isinstance(self.config.get("card_actions"), dict)
            else {}
        )
        if not self.actions_config.get("enabled"):
            raise RuntimeError("card actions are disabled in project_monitor.json")
        if str(self.actions_config.get("event_key") or "") != "card.action.trigger":
            raise RuntimeError("unsupported card action event key")
        self.action_state_path = self.state_dir / "card_actions.json"
        self.events_path = self.state_dir / "events.jsonl"
        self.web_actions_path = self.state_dir / "web_actions.jsonl"
        self.web_actions_lock_path = self.state_dir / "web_actions.lock"
        self.lock_path = self.state_dir / "card_actions.lock"
        self.processing_lock_path = self.state_dir / "card_actions_processing.lock"
        self.monitor_state_path = self.state_dir / "state.json"
        self.state = _read_json(self.action_state_path, {})
        if not isinstance(self.state, dict):
            self.state = {}
        self.state.setdefault("version", 1)
        self.state.setdefault("processed_events", {})
        self.state.setdefault("handled_messages", {})
        self._stop_requested = False
        self._event_processes: dict[str, subprocess.Popen[str]] = {}

    def now(self) -> datetime:
        value = self.now_fn()
        if value.tzinfo is None:
            value = value.replace(tzinfo=HKT)
        return value.astimezone(HKT)

    def _run(self, argv: list[str], timeout: float = 30) -> subprocess.CompletedProcess[str]:
        return self.monitor._run(argv, timeout=timeout)

    def _event_action(self, event: dict[str, Any]) -> dict[str, Any] | None:
        if str(event.get("type") or "") != "card.action.trigger":
            return None
        if str(event.get("action_tag") or "") != "button":
            return None
        if str(event.get("host") or "") != "im_message":
            return None
        raw = str(event.get("action_value") or "")
        try:
            action = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(action, dict):
            return None
        if (
            str(action.get("action") or "") != str(self.actions_config.get("action") or "")
            or str(action.get("project") or "") != "cmhk-main"
            or int(action.get("version") or 0) != 1
        ):
            return None
        incident_id = str(action.get("incident_id") or "")
        if not INCIDENT_ID_RE.fullmatch(incident_id):
            return None
        return action

    def _verify_original_delivery(self, incident_id: str, message_id: str, chat_id: str) -> None:
        monitor_state = _read_json(self.monitor_state_path, {})
        incidents = monitor_state.get("incidents") if isinstance(monitor_state, dict) else {}
        incident = incidents.get(incident_id) if isinstance(incidents, dict) else None
        if not isinstance(incident, dict):
            raise RuntimeError("回调对应的告警不在本地监控账本中")
        delivery = incident.get("delivery") if isinstance(incident.get("delivery"), dict) else {}
        target_delivery = delivery.get(chat_id) if isinstance(delivery, dict) else None
        if not isinstance(target_delivery, dict):
            raise RuntimeError("回调群与告警发送账本不一致")
        if str(target_delivery.get("message_id") or "") != message_id:
            raise RuntimeError("回调消息ID与告警发送账本不一致")
        if str(target_delivery.get("state") or "") not in {"sent_pending_readback", "verified"}:
            raise RuntimeError("原告警消息未处于可处理状态")

    def _resolve_operator(self, operator_id: str, *, user_id_type: str = "open_id") -> str:
        if user_id_type not in {"open_id", "union_id"}:
            raise ValueError("不支持的飞书用户ID类型")
        bot = self.config.get("bot") if isinstance(self.config.get("bot"), dict) else {}
        profile = str(bot.get("profile") or "")
        payload = self.monitor._json_from_process(
            self._run(
                [
                    "lark-cli",
                    "contact",
                    "+get-user",
                    "--user-id",
                    operator_id,
                    "--user-id-type",
                    user_id_type,
                    "--as",
                    "bot",
                    "--profile",
                    profile,
                    "--format",
                    "json",
                ],
                timeout=20,
            )
        )
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        user = data.get("user") if isinstance(data.get("user"), dict) else {}
        if str(user.get(user_id_type) or "") != operator_id:
            raise RuntimeError("按钮点击者身份回读不一致")
        name = _to_simplified(_redact(user.get("name") or user.get("en_name") or "", 120))
        if not name:
            raise RuntimeError("按钮点击者缺少可写入的飞书姓名")
        return name

    def _write_handler_to_sheet(self, incident_id: str, operator_name: str) -> dict[str, Any]:
        rows, row_by_incident = self.monitor._read_error_ledger()
        row_number = row_by_incident.get(incident_id)
        if not row_number:
            raise RuntimeError("错误台账中找不到该告警ID")
        current = rows[row_number - 2]
        existing_handler = str(current[12] or "").strip()
        existing_status = str(current[13] or "").strip()
        if existing_status == "已处理" and existing_handler:
            return {
                "row": row_number,
                "handler_name": existing_handler,
                "newly_handled": False,
            }

        ledger = self.monitor._error_ledger_config()
        bot = self.config.get("bot") if isinstance(self.config.get("bot"), dict) else {}
        profile = str(bot.get("profile") or "")
        green_style = {
            "background_color": "#ECFDF3",
            "font_color": "#027A48",
            "font_weight": "bold",
            "vertical_alignment": "middle",
            "word_wrap": "auto-wrap",
        }
        cells = [[
            {"value": operator_name, "cell_styles": green_style},
            {"value": "已处理", "cell_styles": green_style},
        ]]
        self.monitor._json_from_process(
            self._run(
                [
                    "lark-cli",
                    "sheets",
                    "+cells-set",
                    "--spreadsheet-token",
                    str(ledger.get("spreadsheet_token") or ""),
                    "--sheet-id",
                    str(ledger.get("sheet_id") or ""),
                    "--range",
                    f"M{row_number}:N{row_number}",
                    "--cells",
                    json.dumps(cells, ensure_ascii=False),
                    "--as",
                    "bot",
                    "--profile",
                    profile,
                    "--format",
                    "json",
                ],
                timeout=30,
            )
        )
        verified_rows, verified_mapping = self.monitor._read_error_ledger()
        verified_row = verified_mapping.get(incident_id)
        if verified_row != row_number:
            raise RuntimeError("错误台账处理人写入后告警ID行发生变化")
        verified = verified_rows[row_number - 2]
        if str(verified[12] or "") != operator_name or str(verified[13] or "") != "已处理":
            raise RuntimeError("错误台账处理人或处理状态写入后回读不一致")
        return {"row": row_number, "handler_name": operator_name, "newly_handled": True}

    def mark_incident_handled_from_web(
        self,
        incident_id: str,
        operator_open_id: str,
        operator_union_id: str = "",
    ) -> dict[str, Any]:
        """Resolve a dashboard checkbox using the authenticated Feishu identity.

        OAuth and monitoring bots are different Feishu apps, so their open_ids
        cannot be mixed. The session union_id is stable across apps and is
        resolved again through the monitoring bot before the sheet is written.
        """
        incident_id = str(incident_id or "").strip()
        operator_open_id = str(operator_open_id or "").strip()
        operator_union_id = str(operator_union_id or "").strip()
        if not INCIDENT_ID_RE.fullmatch(incident_id):
            raise ValueError("告警ID格式无效")
        if not operator_open_id.startswith("ou_"):
            raise ValueError("当前登录账号没有可匹配的飞书身份")
        if not operator_union_id.startswith("on_"):
            raise ValueError("当前登录会话缺少跨应用飞书身份，请退出后重新登录")
        monitor_state = _read_json(self.monitor_state_path, {})
        incidents = monitor_state.get("incidents") if isinstance(monitor_state, dict) else {}
        if not isinstance(incidents, dict) or not isinstance(incidents.get(incident_id), dict):
            raise ValueError("告警不在本地监控账本中")
        incident = incidents[incident_id]

        self.web_actions_lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.web_actions_lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            previous: dict[str, Any] | None = None
            try:
                lines = self.web_actions_path.read_text(encoding="utf-8").splitlines()
            except OSError:
                lines = []
            for line in reversed(lines):
                try:
                    item = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(item, dict) and str(item.get("incident_id") or "") == incident_id:
                    previous = item
                    break
            if previous:
                if str(previous.get("operator_id") or "") != operator_open_id:
                    raise RuntimeError(f"该告警已由 {previous.get('operator_name') or '其他人员'} 标记处理")
                return {**previous, "newly_handled": False}

            self.monitor._verify_bot_identity()
            operator_name = self._resolve_operator(operator_union_id, user_id_type="union_id")
            sheet_result = self._write_handler_to_sheet(incident_id, operator_name)
            effective_name = str(sheet_result.get("handler_name") or operator_name)
            if effective_name != operator_name:
                raise RuntimeError(f"飞书台账显示该告警已由 {effective_name} 处理")
            result = {
                "status": "completed",
                "source": "web",
                "incident_id": incident_id,
                "operator_id": operator_open_id,
                "operator_union_id": operator_union_id,
                "operator_name": operator_name,
                "sheet_row": sheet_result.get("row"),
                "newly_handled": bool(sheet_result.get("newly_handled")),
                "feishu_sync": "readback_verified",
                "handled_at_hkt": _iso(self.now()),
            }
            delivery = incident.get("delivery") if isinstance(incident.get("delivery"), dict) else {}
            verified_deliveries = [
                item
                for item in delivery.values()
                if isinstance(item, dict)
                and item.get("state") == "verified"
                and str(item.get("message_id") or "").startswith("om_")
                and str(item.get("chat_id") or "").startswith("oc_")
            ]
            if not verified_deliveries:
                # A notification can legitimately be absent when delivery was
                # suppressed or failed before verification.  The dashboard
                # action still has two authoritative, read-backed sinks: the
                # error ledger and this local web-action journal.  Treat the
                # missing card as "nothing to update", not as a rollback of an
                # already verified manual disposition.
                result["card_status"] = "not_sent_no_card_update"
                _append_jsonl(self.web_actions_path, {"type": "incident_marked_handled_from_web", **result})
                return result
            for target_delivery in verified_deliveries:
                target = next(
                    (
                        item
                        for item in self.config.get("targets") or []
                        if str(item.get("chat_id") or "") == str(target_delivery.get("chat_id") or "")
                    ),
                    None,
                )
                if not isinstance(target, dict):
                    raise RuntimeError("原告警群不在受控白名单中")
                self.monitor._verify_target(target)
                card = self.monitor.render_manually_repaired_card(
                    incident,
                    handler_name=operator_name,
                    handled_at_hkt=result["handled_at_hkt"],
                    handler_open_id="",
                )
                message_id = str(target_delivery.get("message_id") or "")
                profile = str((self.config.get("bot") or {}).get("profile") or "")
                self.monitor._json_from_process(
                    self._run(
                        [
                            "lark-cli", "api", "PATCH",
                            f"/open-apis/im/v1/messages/{message_id}",
                            "--as", "bot", "--profile", profile,
                            "--data", json.dumps(
                                {
                                    "content": json.dumps(
                                        card,
                                        ensure_ascii=False,
                                        separators=(",", ":"),
                                    )
                                },
                                ensure_ascii=False,
                            ),
                            "--format", "json",
                        ],
                        timeout=30,
                    )
                )
                self.monitor._readback_resolution_update(
                    incident,
                    target_delivery,
                    target,
                    expected_marker="已人工修复",
                )
            result["card_status"] = "updated_and_readback_verified"
            _append_jsonl(self.web_actions_path, {"type": "incident_marked_handled_from_web", **result})
            return result

    def _find_element(self, value: object, element_id: str) -> dict[str, Any] | None:
        if isinstance(value, dict):
            if str(value.get("element_id") or "") == element_id:
                return value
            for child in value.values():
                found = self._find_element(child, element_id)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = self._find_element(child, element_id)
                if found is not None:
                    return found
        return None

    def _handled_card(
        self,
        event: dict[str, Any],
        *,
        incident_id: str,
        handler_name: str,
        handler_open_id: str,
    ) -> dict[str, Any] | None:
        raw_content = str(event.get("card_content") or "").strip()
        if not raw_content:
            return None
        try:
            card = json.loads(raw_content)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("原卡片内容不是有效JSON，不能安全更新") from exc
        if not isinstance(card, dict) or str(card.get("schema") or "") != "2.0":
            raise RuntimeError("只允许更新本监控生成的Card 2.0告警")
        button = self._find_element(card, "resolveButton")
        prompt = self._find_element(card, "handlerPrompt")
        action_block = self._find_element(card, "actionBlock")
        if not isinstance(button, dict) or not isinstance(prompt, dict):
            raise RuntimeError("原卡片缺少受控的处理按钮或处理人区域")
        behaviors = button.get("behaviors") if isinstance(button.get("behaviors"), list) else []
        callback = next(
            (item for item in behaviors if isinstance(item, dict) and item.get("type") == "callback"),
            None,
        )
        value = callback.get("value") if isinstance(callback, dict) and isinstance(callback.get("value"), dict) else {}
        if (
            str(value.get("action") or "") != str(self.actions_config.get("action") or "")
            or str(value.get("incident_id") or "") != incident_id
        ):
            raise RuntimeError("原卡片按钮动作与回调不一致")
        handled_at = _iso(self.now())
        if handler_open_id.startswith("ou_"):
            handler_text = f"<at id={handler_open_id}></at>"
        else:
            handler_text = self.monitor._card_markdown_text(handler_name, 120)
        prompt["content"] = f"**人工修复时间**　{handled_at}\n\n**修复人员**　{handler_text}"
        button.update(
            {
                "text": {"tag": "plain_text", "content": "已人工修复"},
                "disabled": True,
                "disabled_tips": {"tag": "plain_text", "content": f"已由 {handler_name} 人工修复"},
            }
        )
        if isinstance(action_block, dict):
            columns = action_block.get("columns") if isinstance(action_block.get("columns"), list) else []
            for column in columns:
                if isinstance(column, dict):
                    column["background_style"] = "green-50"
        header = card.get("header") if isinstance(card.get("header"), dict) else {}
        header["template"] = "green"
        tags = header.get("text_tag_list") if isinstance(header.get("text_tag_list"), list) else []
        if len(tags) >= 2 and isinstance(tags[1], dict):
            tags[1] = {
                "tag": "text_tag",
                "text": {"tag": "plain_text", "content": "人工修复"},
                "color": "green",
            }
        else:
            tags.append(
                {
                    "tag": "text_tag",
                    "text": {"tag": "plain_text", "content": "人工修复"},
                    "color": "green",
                }
            )
        header["text_tag_list"] = tags[:3]
        card["header"] = header
        config = card.get("config") if isinstance(card.get("config"), dict) else {}
        summary = config.get("summary") if isinstance(config.get("summary"), dict) else {}
        summary["content"] = f"已人工修复 · {handler_name} · 告警 {incident_id}"
        config["summary"] = summary
        card["config"] = config
        return card

    def _subscription_status_card(
        self,
        event: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        raw_content = str(event.get("card_content") or "").strip()
        if not raw_content:
            return None
        try:
            card = json.loads(raw_content)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("原订阅卡片内容不是有效JSON，不能安全更新") from exc
        if not isinstance(card, dict) or str(card.get("schema") or "") != "2.0":
            raise RuntimeError("只允许更新本系统生成的Card 2.0订阅卡")
        body = card.get("body") if isinstance(card.get("body"), dict) else None
        elements = body.get("elements") if isinstance(body, dict) and isinstance(body.get("elements"), list) else None
        if not isinstance(elements, list):
            raise RuntimeError("原订阅卡片缺少可更新的内容区")

        paused = str(result.get("status") or "") == "subscription_paused"
        title = "订阅已暂停" if paused else "订阅已生效"
        if paused:
            status_text = "**订阅已暂停**\n\n所有战略情报推送已暂停，重新选择并提交即可恢复。"
        else:
            labels = "、".join(
                {
                    "weekly": "战略双周报",
                    "performance": "运营商业绩摘要",
                    "news": "战略新闻",
                }.get(str(item), str(item))
                for item in result.get("services") or []
            )
            status_text = (
                f"**订阅已生效**\n\n"
                f"订阅内容：{labels}\n\n"
                f"报告形式：{str(result.get('report_mode_label') or '')}\n\n"
                f"战略新闻：{str(result.get('news_frequency_label') or result.get('frequency_label') or '')}"
            )
        elements[:] = [
            item for item in elements
            if not (isinstance(item, dict) and str(item.get("element_id") or "") == "subscriptionStatus")
        ]
        insert_at = 1 if elements and isinstance(elements[0], dict) and elements[0].get("tag") == "img" else 0
        elements.insert(
            insert_at,
            {
                "tag": "markdown",
                "element_id": "subscriptionStatus",
                "content": status_text,
            },
        )
        save_button = self._find_element(card, "saveSubscriptions")
        if not isinstance(save_button, dict):
            for element in elements:
                if isinstance(element, dict) and element.get("tag") == "form":
                    for child in element.get("elements") or []:
                        if isinstance(child, dict) and child.get("name") == "saveSubscriptions":
                            save_button = child
                            break
        if isinstance(save_button, dict):
            save_button["text"] = {"tag": "plain_text", "content": "恢复订阅" if paused else "更新订阅"}

        header = card.get("header") if isinstance(card.get("header"), dict) else {}
        header["title"] = {"tag": "plain_text", "content": title}
        header["template"] = "grey" if paused else "green"
        card["header"] = header
        config = card.get("config") if isinstance(card.get("config"), dict) else {}
        config["summary"] = {"content": title}
        card["config"] = config
        return card

    def _update_card(self, token: str, card: dict[str, Any], *, profile: str = "") -> None:
        if not token:
            raise RuntimeError("卡片回调缺少延迟更新token")
        bot = self.config.get("bot") if isinstance(self.config.get("bot"), dict) else {}
        profile = profile or str(bot.get("profile") or "")
        body = json.dumps({"token": token, "card": card}, ensure_ascii=False)
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                self.monitor._json_from_process(
                    self._run(
                        [
                            "lark-cli",
                            "api",
                            "POST",
                            "/open-apis/interactive/v1/card/update",
                            "--as",
                            "bot",
                            "--profile",
                            profile,
                            "--data",
                            body,
                            "--format",
                            "json",
                        ],
                        timeout=30,
                    )
                )
                return
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(1)
        raise RuntimeError(f"卡片延迟更新失败：{last_error}")

    def handle_event(self, event: dict[str, Any]) -> dict[str, Any]:
        event_id = str(event.get("event_id") or "")
        processed = self.state.setdefault("processed_events", {})
        if isinstance(processed.get(event_id), dict) and processed[event_id].get("status") in {"completed", "subscription_saved", "subscription_paused"}:
            return dict(processed[event_id])
        subscription_result = self.subscription_service.handle_card_event(event)
        if subscription_result is not None:
            source_profile = str(subscription_result.pop("source_profile", "") or "")
            status_card = self._subscription_status_card(event, subscription_result)
            card_status = "skipped_missing_card_content"
            if status_card is not None:
                self._update_card(
                    str(event.get("token") or ""),
                    status_card,
                    profile=source_profile,
                )
                card_status = "updated"
            result = {
                **subscription_result,
                "card_status": card_status,
                "event_id": event_id,
                "message_id": str(event.get("message_id") or ""),
                "chat_id": str(event.get("chat_id") or ""),
                "completed_at_hkt": _iso(self.now()),
            }
            processed[event_id] = result
            self.state["last_event_at_hkt"] = result["completed_at_hkt"]
            _atomic_json(self.action_state_path, self.state)
            _append_jsonl(self.events_path, {"type": result["status"], **result})
            return result
        action = self._event_action(event)
        if action is None:
            return {"status": "ignored"}
        operator_id = str(event.get("operator_id") or "")
        message_id = str(event.get("message_id") or "")
        chat_id = str(event.get("chat_id") or "")
        incident_id = str(action.get("incident_id") or "")
        if (
            not event_id
            or not operator_id.startswith("ou_")
            or not message_id.startswith("om_")
            or not chat_id.startswith("oc_")
        ):
            raise RuntimeError("卡片回调缺少受控事件、人员、消息或群ID")
        self.monitor._verify_bot_identity()
        target = next(
            (item for item in self.config.get("targets") or [] if str(item.get("chat_id") or "") == chat_id),
            None,
        )
        if not isinstance(target, dict):
            raise RuntimeError("卡片回调群不在告警白名单")
        self.monitor._verify_target(target)
        self._verify_original_delivery(incident_id, message_id, chat_id)
        operator_name = self._resolve_operator(operator_id)
        sheet_result = self._write_handler_to_sheet(incident_id, operator_name)
        effective_name = str(sheet_result.get("handler_name") or operator_name)
        effective_open_id = operator_id if effective_name == operator_name else ""
        handled_card = self._handled_card(
            event,
            incident_id=incident_id,
            handler_name=effective_name,
            handler_open_id=effective_open_id,
        )
        card_status = "skipped_missing_card_content"
        if handled_card is not None:
            self._update_card(str(event.get("token") or ""), handled_card)
            card_status = "updated"
        result = {
            "status": "completed",
            "event_id": event_id,
            "incident_id": incident_id,
            "message_id": message_id,
            "chat_id": chat_id,
            "operator_id": operator_id,
            "operator_name": effective_name,
            "sheet_row": sheet_result.get("row"),
            "newly_handled": bool(sheet_result.get("newly_handled")),
            "card_status": card_status,
            "completed_at_hkt": _iso(self.now()),
        }
        processed[event_id] = result
        self.state.setdefault("handled_messages", {})[message_id] = {
            "incident_id": incident_id,
            "operator_id": effective_open_id,
            "operator_name": effective_name,
            "handled_at_hkt": result["completed_at_hkt"],
        }
        self.state["last_event_at_hkt"] = result["completed_at_hkt"]
        _atomic_json(self.action_state_path, self.state)
        _append_jsonl(self.events_path, {"type": "incident_marked_handled", **result})
        actor = self.auth_service.public_user_by_feishu_open_id(effective_open_id) or {
            "id": effective_open_id,
            "name": effective_name,
            "role": "",
            "avatarUrl": "",
        }
        self.auth_service.record_operation(
            actor={**actor, "feishuOpenId": effective_open_id},
            action="fault.mark_handled",
            target=incident_id,
            source="feishu_card",
            details={
                "source": "feishu_card",
                "handler_name": effective_name,
                "feishu_sync": "readback_verified",
                "sheet_row": sheet_result.get("row"),
            },
        )
        return result

    def handle_event_process_safe(self, event: dict[str, Any]) -> dict[str, Any]:
        """Serialize callbacks shared by the daemon and the WebSocket owner.

        The primary Feishu app now uses the Web application's SDK connection so
        file-edit and card callbacks share one connection.  The monitoring app
        still arrives through the standalone daemon.  Both processes write the
        same idempotency ledger, so reload it while holding a dedicated lock.
        """
        self.processing_lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.processing_lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            self.state = _read_json(self.action_state_path, {})
            if not isinstance(self.state, dict):
                self.state = {}
            self.state.setdefault("version", 1)
            self.state.setdefault("processed_events", {})
            self.state.setdefault("handled_messages", {})
            try:
                return self.handle_event(event)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _handle_signal(self, _signum: int, _frame: object) -> None:
        self._stop_requested = True
        for process in self._event_processes.values():
            if process.poll() is None:
                process.terminate()

    def run_daemon(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        bot = self.config.get("bot") if isinstance(self.config.get("bot"), dict) else {}
        profile = str(bot.get("profile") or "")
        subscriptions = self.config.get("subscriptions") if isinstance(self.config.get("subscriptions"), dict) else {}
        configured_profiles = self.actions_config.get("listener_profiles")
        if isinstance(configured_profiles, list):
            profiles = list(dict.fromkeys(
                str(item).strip() for item in configured_profiles if str(item).strip()
            ))
        else:
            profiles = list(dict.fromkeys(filter(None, [
                profile,
                str(subscriptions.get("directory_profile") or ""),
            ])))
        if not profiles:
            raise RuntimeError("card action listener has no configured profiles")
        selector = selectors.DefaultSelector()
        ready: set[str] = set()
        for event_profile in profiles:
            process = subprocess.Popen(
                [
                    "lark-cli", "event", "consume", "card.action.trigger",
                    "--as", "bot", "--profile", event_profile,
                ],
                cwd=self.runtime_root,
                env=_command_env(self.environ),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            self._event_processes[event_profile] = process
            assert process.stdout is not None and process.stderr is not None
            selector.register(process.stdout, selectors.EVENT_READ, ("stdout", event_profile))
            selector.register(process.stderr, selectors.EVENT_READ, ("stderr", event_profile))
        try:
            while not self._stop_requested:
                if all(process.poll() is not None for process in self._event_processes.values()) and not selector.get_map():
                    break
                for key, _ in selector.select(timeout=1):
                    line = key.fileobj.readline()
                    if not line:
                        try:
                            selector.unregister(key.fileobj)
                        except KeyError:
                            pass
                        continue
                    stream_name, event_profile = key.data
                    if stream_name == "stderr":
                        print(f"[{event_profile}] {line.rstrip()}", file=sys.stderr, flush=True)
                        if "[event] ready event_key=card.action.trigger" in line:
                            ready.add(event_profile)
                            listeners = self.state.setdefault("listener_profiles", {})
                            listeners[event_profile] = {"ready_at_hkt": _iso(self.now())}
                            self.state["listener_ready_at_hkt"] = _iso(self.now())
                            _atomic_json(self.action_state_path, self.state)
                        continue
                    try:
                        event = json.loads(line)
                        if not isinstance(event, dict):
                            raise ValueError("event line is not an object")
                        event["source_profile"] = event_profile
                        result = self.handle_event_process_safe(event)
                        print(json.dumps(result, ensure_ascii=False), flush=True)
                    except Exception as exc:
                        error = _redact(f"{type(exc).__name__}: {exc}", 900)
                        print(f"card action failed locally: {error}", file=sys.stderr, flush=True)
                        _append_jsonl(
                            self.events_path,
                            {
                                "type": "card_action_failed_local_only",
                                "at_hkt": _iso(self.now()),
                                "error": error,
                            },
                        )
            return_codes = {
                event_profile: process.wait(timeout=10)
                for event_profile, process in self._event_processes.items()
            }
            unhealthy = {
                event_profile: code
                for event_profile, code in return_codes.items()
                if code != 0 or event_profile not in ready
            }
            if not self._stop_requested and unhealthy:
                raise RuntimeError(
                    f"card action event consumer exited before a healthy ready state: {unhealthy}"
                )
        finally:
            selector.close()
            for event_profile, process in self._event_processes.items():
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        print(f"card action consumer {event_profile} did not exit after SIGTERM", file=sys.stderr, flush=True)
            self._event_processes = {}

    def acquire_lock(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            raise RuntimeError("another card action listener is already running")
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        return handle


def main() -> None:
    parser = argparse.ArgumentParser(description="CMHK错误告警卡片处理回调")
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--runtime-root", default="")
    parser.add_argument("--config", default="")
    parser.add_argument("--state-dir", default="")
    args = parser.parse_args()
    handler = CardActionHandler(
        runtime_root=args.runtime_root or None,
        config_path=args.config or None,
        state_dir=args.state_dir or None,
    )
    lock = handler.acquire_lock()
    try:
        if not args.daemon:
            raise RuntimeError("card action listener requires --daemon")
        handler.run_daemon()
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


if __name__ == "__main__":
    main()

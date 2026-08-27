from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import project_monitor
from project_monitor_card_actions import CardActionHandler, _atomic_json
from cmhk.services.subscriptions import subscription_entry_card
from tests.test_project_monitor import FakeCommandRunner


HKT = ZoneInfo("Asia/Hong_Kong")
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "project_monitor.json"
INCIDENT_ID = "1234567890abcdef12345678"
CHAT_ID = "oc_22bf3c7febc4bab295fedfb0b8e6c176"
MESSAGE_ID = "om_card_action_test"
OPERATOR_ID = "ou_clicker1234567890abcdef12345678"
OPERATOR_UNION_ID = "on_clicker1234567890abcdef12345678"


class CardActionRunner(FakeCommandRunner):
    def __init__(self) -> None:
        super().__init__()
        self.card_updates: list[dict] = []

    def __call__(self, argv, *, cwd, env, timeout):
        args = list(argv)
        if len(args) >= 3 and args[1:3] == ["contact", "+get-user"]:
            self.calls.append(args)
            user_id = args[args.index("--user-id") + 1]
            user_id_type = args[args.index("--user-id-type") + 1]
            name = "陳四" if user_id in {OPERATOR_ID, OPERATOR_UNION_ID} else "廖望 Alex LIAO Wang"
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    {
                        "ok": True,
                        "identity": "bot",
                        "data": {"user": {
                            "open_id": OPERATOR_ID if user_id_type == "union_id" else user_id,
                            "union_id": OPERATOR_UNION_ID,
                            "name": name,
                            "en_name": name,
                        }},
                    },
                    ensure_ascii=False,
                ),
                "",
            )
        if len(args) >= 4 and args[1:4] == [
            "api",
            "POST",
            "/open-apis/interactive/v1/card/update",
        ]:
            self.calls.append(args)
            self.card_updates.append(json.loads(args[args.index("--data") + 1]))
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps({"ok": True, "identity": "bot", "data": {"updated": True}}),
                "",
            )
        return super().__call__(args, cwd=cwd, env=env, timeout=timeout)


class CardActionHandlerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "runtime"
        self.state_dir = self.root / "var" / "project_monitor"
        self.root.mkdir(parents=True)
        self.state_dir.mkdir(parents=True)
        self.now = datetime(2026, 8, 16, 20, 0, tzinfo=HKT)
        self.runner = CardActionRunner()
        self.runner.message_targets[MESSAGE_ID] = CHAT_ID
        self.runner.ledger_rows = [
            [
                INCIDENT_ID,
                "2026-08-16T19:55:00+08:00",
                "2026-08-16T19:56:00+08:00",
                "P1 紧急",
                "规则判定",
                "定时主爬虫",
                "crawl",
                "任务失败",
                "数据未更新",
                "crawl returned 1",
                "1. 检查日志",
                "是",
                "",
                "待处理",
                "2026-08-16T19:56:00+08:00",
                "deepseek-v4",
                "已发送并回读（2/2）",
            ]
        ]
        self.state_dir.joinpath("state.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "incidents": {
                        INCIDENT_ID: {
                            "incident_id": INCIDENT_ID,
                            "condition_key": "test-error",
                            "status": "open",
                            "severity": "P1",
                            "task_name": "定时主爬虫",
                            "error": "crawl returned 1",
                            "diagnosis": {
                                "ok": True,
                                "model": "deepseek-v4",
                                "severity": "P1",
                                "severity_reason": "关键定时任务已失败，需要立即处理。",
                                "fault_cause": "爬虫进程以非零状态退出。",
                                "fault_impact": "本轮数据未完成更新。",
                                "fault_time_hkt": "2026-08-16T19:55:00+08:00",
                                "recommended_solutions": ["读取完整日志。"],
                                "needs_human": True,
                            },
                            "delivery": {
                                CHAT_ID: {
                                    "state": "verified",
                                    "message_id": MESSAGE_ID,
                                    "chat_id": CHAT_ID,
                                }
                            },
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        self.handler = CardActionHandler(
            runtime_root=self.root,
            config_path=CONFIG_PATH,
            state_dir=self.state_dir,
            environ={"CMHK_ERROR_LEDGER_ENABLED": "1"},
            now_fn=lambda: self.now,
            command_runner=self.runner,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _card(self) -> dict:
        monitor = project_monitor.ProjectMonitor(
            runtime_root=self.root,
            config_path=CONFIG_PATH,
            state_dir=self.state_dir,
            environ={"CMHK_ERROR_LEDGER_ENABLED": "0"},
            now_fn=lambda: self.now,
            command_runner=self.runner,
        )
        return monitor.render_alert_card(
            {
                "incident_id": INCIDENT_ID,
                "severity": "P1",
                "task_name": "定时主爬虫",
                "error": "crawl returned 1",
                "diagnosis": {
                    "ok": True,
                    "model": "deepseek-v4",
                    "severity": "P1",
                    "severity_reason": "关键定时任务已失败，需要立即处理。",
                    "fault_cause": "爬虫进程以非零状态退出。",
                    "fault_impact": "本轮数据未完成更新。",
                    "fault_time_hkt": "2026-08-16T19:55:00+08:00",
                    "recommended_solutions": ["读取完整日志。", "修复后核对任务归档。"],
                    "needs_human": True,
                },
            }
        )

    def _event(self, *, event_id="evt_1", message_id=MESSAGE_ID, card_content=None) -> dict:
        return {
            "type": "card.action.trigger",
            "event_id": event_id,
            "timestamp": "1786881600000",
            "operator_id": OPERATOR_ID,
            "message_id": message_id,
            "chat_id": CHAT_ID,
            "host": "im_message",
            "token": "card_update_token",
            "action_tag": "button",
            "action_value": json.dumps(
                {
                    "action": "cmhk_mark_handled_v1",
                    "incident_id": INCIDENT_ID,
                    "project": "cmhk-main",
                    "version": 1,
                }
            ),
            "action_name": "",
            "form_value": "",
            "card_content": json.dumps(card_content if card_content is not None else self._card(), ensure_ascii=False),
        }

    def _find_element(self, value, element_id):
        if isinstance(value, dict):
            if value.get("element_id") == element_id:
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

    def test_clicking_user_is_written_and_card_is_disabled(self):
        result = self.handler.handle_event(self._event())
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["newly_handled"])
        self.assertEqual(self.runner.ledger_rows[0][12], "陈四")
        self.assertEqual(self.runner.ledger_rows[0][13], "已处理")
        sheet_write = next(call for call in self.runner.calls if "+cells-set" in call)
        self.assertEqual(sheet_write[sheet_write.index("--range") + 1], "M2:N2")
        self.assertEqual(sheet_write[sheet_write.index("--as") + 1], "bot")
        self.assertEqual(len(self.runner.card_updates), 1)
        card = self.runner.card_updates[0]["card"]
        button = self._find_element(card, "resolveButton")
        prompt = self._find_element(card, "handlerPrompt")
        self.assertTrue(button["disabled"])
        self.assertEqual(button["text"]["content"], "已人工修复")
        self.assertIn(f"<at id={OPERATOR_ID}></at>", prompt["content"])
        self.assertIn("人工修复时间", prompt["content"])
        self.assertEqual(card["header"]["template"], "green")
        audit = self.handler.auth_service.operation_audit()
        self.assertEqual(audit[0]["action"], "fault.mark_handled")
        self.assertEqual(audit[0]["actor_open_id"], OPERATOR_ID)
        self.assertEqual(audit[0]["details"]["source"], "feishu_card")
        serialized = json.dumps(card, ensure_ascii=False)
        self.assertNotRegex(serialized, r"[處狀請議響間級複斷據]")

    def test_process_safe_handler_reloads_shared_idempotency_ledger(self):
        second_handler = CardActionHandler(
            runtime_root=self.root,
            config_path=CONFIG_PATH,
            state_dir=self.state_dir,
            environ={"CMHK_ERROR_LEDGER_ENABLED": "1"},
            now_fn=lambda: self.now,
            command_runner=self.runner,
        )
        event = {"type": "card.action.trigger", "event_id": "evt_shared"}
        first = {"status": "completed", "event_id": "evt_shared"}
        self.handler.state["processed_events"]["evt_shared"] = first
        _atomic_json(self.handler.action_state_path, self.handler.state)
        second = second_handler.handle_event_process_safe(event)
        self.assertEqual(second, first)
        self.assertEqual(self.runner.calls, [])

    def test_config_routes_primary_app_callbacks_to_websocket_owner(self):
        self.assertEqual(
            self.handler.actions_config.get("listener_profiles"),
            ["cmhk-innovation-digital"],
        )

    def test_duplicate_event_is_idempotent(self):
        event = self._event()
        first = self.handler.handle_event(event)
        writes_after_first = len(self.runner.ledger_write_calls())
        updates_after_first = len(self.runner.card_updates)
        second = self.handler.handle_event(event)
        self.assertEqual(second, first)
        self.assertEqual(len(self.runner.ledger_write_calls()), writes_after_first)
        self.assertEqual(len(self.runner.card_updates), updates_after_first)

    def test_dashboard_resolution_matches_feishu_identity_and_persists_separate_action(self):
        result = self.handler.mark_incident_handled_from_web(INCIDENT_ID, OPERATOR_ID, OPERATOR_UNION_ID)
        self.assertEqual(result["operator_name"], "陈四")
        self.assertEqual(result["feishu_sync"], "readback_verified")
        self.assertEqual(result["card_status"], "updated_and_readback_verified")
        self.assertTrue(result["newly_handled"])
        self.assertEqual(self.runner.ledger_rows[0][12:14], ["陈四", "已处理"])
        self.assertEqual(len(self.runner.resolution_update_calls()), 1)
        updated = json.loads(self.runner.updated_messages[MESSAGE_ID])
        self.assertIn("已人工修复", updated["header"]["title"]["content"])
        self.assertEqual(updated["header"]["icon"]["token"], "done_outlined")
        self.assertIn("人工修复时间", json.dumps(updated, ensure_ascii=False))
        lines = self.handler.web_actions_path.read_text(encoding="utf-8").splitlines()
        saved = json.loads(lines[-1])
        self.assertEqual(saved["incident_id"], INCIDENT_ID)
        self.assertEqual(saved["operator_id"], OPERATOR_ID)
        self.assertEqual(saved["operator_union_id"], OPERATOR_UNION_ID)
        identity_call = next(call for call in self.runner.calls if "+get-user" in call)
        self.assertEqual(identity_call[identity_call.index("--user-id") + 1], OPERATOR_UNION_ID)
        self.assertEqual(identity_call[identity_call.index("--user-id-type") + 1], "union_id")
        repeated = self.handler.mark_incident_handled_from_web(INCIDENT_ID, OPERATOR_ID, OPERATOR_UNION_ID)
        self.assertFalse(repeated["newly_handled"])
        self.assertEqual(len(self.handler.web_actions_path.read_text(encoding="utf-8").splitlines()), 1)

    def test_dashboard_resolution_succeeds_when_alert_card_was_never_sent(self):
        state_path = self.state_dir / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["incidents"][INCIDENT_ID]["delivery"] = {}
        state_path.write_text(json.dumps(state), encoding="utf-8")

        result = self.handler.mark_incident_handled_from_web(
            INCIDENT_ID,
            OPERATOR_ID,
            OPERATOR_UNION_ID,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["card_status"], "not_sent_no_card_update")
        self.assertEqual(self.runner.ledger_rows[0][12:14], ["陈四", "已处理"])
        self.assertEqual(self.runner.resolution_update_calls(), [])
        saved = json.loads(self.handler.web_actions_path.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(saved["incident_id"], INCIDENT_ID)

    def test_dashboard_resolution_rejects_non_feishu_login(self):
        with self.assertRaisesRegex(ValueError, "飞书身份"):
            self.handler.mark_incident_handled_from_web(INCIDENT_ID, "local-admin")

    def test_dashboard_resolution_requires_cross_app_union_identity(self):
        with self.assertRaisesRegex(ValueError, "跨应用飞书身份"):
            self.handler.mark_incident_handled_from_web(INCIDENT_ID, OPERATOR_ID)

    def test_existing_handler_is_never_overwritten_by_later_clicker(self):
        self.runner.ledger_rows[0][12] = "王五"
        self.runner.ledger_rows[0][13] = "已处理"
        result = self.handler.handle_event(self._event(event_id="evt_existing"))
        self.assertFalse(result["newly_handled"])
        self.assertEqual(self.runner.ledger_rows[0][12], "王五")
        self.assertEqual(self.runner.ledger_rows[0][13], "已处理")
        self.assertFalse(any("+cells-set" in call for call in self.runner.calls))
        card = self.runner.card_updates[0]["card"]
        prompt = self._find_element(card, "handlerPrompt")
        self.assertIn("王五", prompt["content"])
        self.assertNotIn(OPERATOR_ID, prompt["content"])

    def test_untrusted_message_id_cannot_write_sheet(self):
        with self.assertRaisesRegex(RuntimeError, "消息ID"):
            self.handler.handle_event(self._event(message_id="om_forged"))
        self.assertEqual(self.runner.ledger_rows[0][12], "")
        self.assertFalse(any("+cells-set" in call for call in self.runner.calls))
        self.assertEqual(self.runner.card_updates, [])

    def test_missing_card_content_updates_sheet_but_skips_card_without_guessing(self):
        event = self._event()
        event["card_content"] = ""
        result = self.handler.handle_event(event)
        self.assertEqual(result["card_status"], "skipped_missing_card_content")
        self.assertEqual(self.runner.ledger_rows[0][12], "陈四")
        self.assertEqual(self.runner.ledger_rows[0][13], "已处理")
        self.assertEqual(self.runner.card_updates, [])

    def test_subscription_success_card_shows_status_and_keeps_update_form(self):
        event = {
            "card_content": json.dumps(
                subscription_entry_card(image_key="img_v3_subscription_poster"),
                ensure_ascii=False,
            )
        }
        card = self.handler._subscription_status_card(
            event,
            {
                "status": "subscription_saved",
                "services": ["news", "performance", "weekly"],
                "report_mode_label": "PDF + 单独语音",
                "news_frequency_label": "每天两次",
            },
        )
        self.assertIsNotNone(card)
        self.assertEqual(card["header"]["template"], "green")
        self.assertEqual(card["header"]["title"]["content"], "订阅已生效")
        status = self._find_element(card, "subscriptionStatus")
        self.assertIn("战略双周报", status["content"])
        form = next(item for item in card["body"]["elements"] if item.get("tag") == "form")
        button = next(item for item in form["elements"] if item.get("name") == "saveSubscriptions")
        self.assertEqual(button["text"]["content"], "更新订阅")

    def test_subscription_pause_card_shows_paused_state(self):
        event = {"card_content": json.dumps(subscription_entry_card(), ensure_ascii=False)}
        card = self.handler._subscription_status_card(
            event,
            {"status": "subscription_paused", "services": []},
        )
        self.assertEqual(card["header"]["template"], "grey")
        self.assertEqual(card["header"]["title"]["content"], "订阅已暂停")
        status = self._find_element(card, "subscriptionStatus")
        self.assertIn("所有战略情报推送已暂停", status["content"])


if __name__ == "__main__":
    unittest.main()

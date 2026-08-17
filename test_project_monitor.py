from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import project_monitor


HKT = ZoneInfo("Asia/Hong_Kong")
CONFIG_PATH = Path(__file__).resolve().parent / "config" / "project_monitor.json"


class FakeCommandRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.message_targets: dict[str, str] = {}
        self.fail_send_chats: set[str] = set()
        self.fail_readback = False
        self.fail_ledger = False
        self.bot_app_id = "cli_a9575e70ae799cb2"
        self.ledger_rows: list[list[str]] = []
        self.chat_names = {
            "oc_22bf3c7febc4bab295fedfb0b8e6c176": "竞对AI项目需求沟通群",
            "oc_f86adbf0010f3e648400c377bf26179b": "揭榜-竞争对手与行业情报监测AI应用",
        }

    def __call__(self, argv, *, cwd, env, timeout):
        args = list(argv)
        self.calls.append(args)
        if args[:2] == ["launchctl", "print"]:
            return subprocess.CompletedProcess(args, 0, "state = running\n", "")
        if args[:2] == ["lark-cli", "whoami"]:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    {
                        "profile": "cli_a9575e70ae799cb2",
                        "appId": self.bot_app_id,
                        "identity": "bot",
                        "available": True,
                        "tokenStatus": "ready",
                    }
                ),
                "",
            )
        if len(args) >= 4 and args[1:4] == ["im", "chats", "get"]:
            params = json.loads(args[args.index("--params") + 1])
            chat_id = params["chat_id"]
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    {
                        "ok": True,
                        "identity": "bot",
                        "data": {
                            "name": self.chat_names.get(chat_id, "wrong"),
                            "chat_mode": "group",
                            "chat_status": "normal",
                            "external": False,
                        },
                    }
                ),
                "",
            )
        if len(args) >= 3 and args[1:3] == ["contact", "+get-user"]:
            user_id = args[args.index("--user-id") + 1]
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    {
                        "ok": True,
                        "identity": "bot",
                        "data": {
                            "user": {
                                "open_id": user_id,
                                "name": "廖望 Alex LIAO Wang",
                                "en_name": "廖望 Alex LIAO Wang",
                            }
                        },
                    }
                ),
                "",
            )
        if len(args) >= 3 and args[1:3] == ["sheets", "+workbook-info"]:
            if self.fail_ledger:
                return subprocess.CompletedProcess(
                    args,
                    1,
                    "",
                    json.dumps({"ok": False, "error": {"message": "simulated ledger failure"}}),
                )
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    {
                        "ok": True,
                        "identity": "bot",
                        "data": {
                            "revision": 100,
                            "sheets": [
                                {"sheet_id": "9c638d", "sheet_name": "主表"},
                                {"sheet_id": "j1AY6G", "sheet_name": "项目错误告警"},
                            ],
                        },
                    },
                    ensure_ascii=False,
                ),
                "",
            )
        if len(args) >= 3 and args[1:3] == ["sheets", "+table-get"]:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    {
                        "ok": True,
                        "identity": "bot",
                        "data": {
                            "sheets": [
                                {
                                    "name": "项目错误告警",
                                    "columns": list(project_monitor.ERROR_LEDGER_COLUMNS),
                                    "data": [list(row) for row in self.ledger_rows],
                                    "range": f"A1:Q{len(self.ledger_rows) + 1}",
                                }
                            ]
                        },
                    },
                    ensure_ascii=False,
                ),
                "",
            )
        if len(args) >= 3 and args[1:3] == ["sheets", "+table-put"]:
            if self.fail_ledger:
                return subprocess.CompletedProcess(
                    args,
                    1,
                    "",
                    json.dumps({"ok": False, "error": {"message": "simulated ledger failure"}}),
                )
            payload = json.loads(args[args.index("--sheets") + 1])
            new_rows = [list(row) for row in payload["sheets"][0]["data"]]
            start_row = len(self.ledger_rows) + 2
            self.ledger_rows.extend(new_rows)
            end_row = len(self.ledger_rows) + 1
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    {
                        "ok": True,
                        "identity": "bot",
                        "data": {
                            "sheets": [
                                {
                                    "name": "项目错误告警",
                                    "range": f"A{start_row}:Q{end_row}",
                                    "data_rows": len(new_rows),
                                }
                            ]
                        },
                    },
                    ensure_ascii=False,
                ),
                "",
            )
        if len(args) >= 3 and args[1:3] == ["sheets", "+cells-set"]:
            if self.fail_ledger:
                return subprocess.CompletedProcess(
                    args,
                    1,
                    "",
                    json.dumps({"ok": False, "error": {"message": "simulated ledger failure"}}),
                )
            if "--writes" in args:
                writes = json.loads(args[args.index("--writes") + 1])
            else:
                writes = [
                    {
                        "range": args[args.index("--range") + 1],
                        "cells": json.loads(args[args.index("--cells") + 1]),
                    }
                ]
            for write in writes:
                match = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", write["range"])
                if not match or match.group(2) != match.group(4):
                    raise AssertionError(f"unsupported fake range: {write['range']}")
                row_number = int(match.group(2))
                while len(self.ledger_rows) < row_number - 1:
                    self.ledger_rows.append([""] * 17)
                start_col = 0
                for char in match.group(1):
                    start_col = start_col * 26 + ord(char) - ord("A") + 1
                start_col -= 1
                row = self.ledger_rows[row_number - 2]
                for offset, cell in enumerate(write["cells"][0]):
                    if "value" in cell:
                        row[start_col + offset] = str(cell["value"])
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps({"ok": True, "identity": "bot", "data": {"writes": len(writes)}}),
                "",
            )
        if "+messages-send" in args:
            chat_id = args[args.index("--chat-id") + 1]
            if chat_id in self.fail_send_chats:
                return subprocess.CompletedProcess(
                    args,
                    1,
                    "",
                    json.dumps({"ok": False, "error": {"message": "simulated send failure"}}),
                )
            message_id = "om_test_" + str(len(self.message_targets) + 1)
            self.message_targets[message_id] = chat_id
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps({"ok": True, "data": {"message_id": message_id, "chat_id": chat_id}}),
                "",
            )
        if "+messages-mget" in args:
            if self.fail_readback:
                return subprocess.CompletedProcess(
                    args,
                    1,
                    "",
                    json.dumps({"ok": False, "error": {"message": "simulated readback failure"}}),
                )
            message_id = args[args.index("--message-ids") + 1]
            chat_id = self.message_targets[message_id]
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    {
                        "ok": True,
                        "data": {
                            "messages": [
                                {
                                    "message_id": message_id,
                                    "chat_id": chat_id,
                                    "msg_type": "interactive",
                                    "sender": {
                                        "id": self.bot_app_id,
                                        "name": "Alex的狂热粉丝",
                                        "sender_type": "app",
                                    },
                                }
                            ]
                        },
                    }
                ),
                "",
            )
        raise AssertionError(f"unexpected command: {args}")

    def send_calls(self) -> list[list[str]]:
        return [call for call in self.calls if "+messages-send" in call]

    def ledger_write_calls(self) -> list[list[str]]:
        return [
            call
            for call in self.calls
            if any(command in call for command in ("+table-put", "+cells-set"))
        ]


class ProjectMonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "runtime"
        self.state_dir = Path(self.temp.name) / "state"
        self.log_root = Path(self.temp.name) / "logs"
        self.root.mkdir(parents=True)
        self.log_root.mkdir(parents=True)
        (self.root / "agent_knowledge" / "crawl_run_logs").mkdir(parents=True)
        (self.root / "task_runs").mkdir(parents=True)
        (self.root / "strategy_briefing" / "runs").mkdir(parents=True)
        (self.root / "var" / "feishu_media_metrics").mkdir(parents=True)
        (self.root / "agent_knowledge" / "crawl_run_logs" / "index.json").write_text("[]")
        (self.root / "task_runs" / "index.json").write_text('{"tasks": []}')
        (self.root / "strategy_briefing" / "state.json").write_text(
            json.dumps({"last_cycle_at": "2026-08-16T14:00:00+08:00"})
        )
        (self.root / "var" / "feishu_media_metrics" / "state.json").write_text(
            json.dumps({"sent_slots": {"20260816-1000": "om_existing"}})
        )
        (self.root / "var" / "feishu_media_metrics" / "daemon.stderr.log").write_text("")
        (self.log_root / "frequency_scheduler.stderr.log").write_text("")
        (self.log_root / "web_app.stderr.log").write_text("")
        (self.log_root / "project_monitor.stderr.log").write_text("")
        (self.log_root / "project_monitor_card_actions.stderr.log").write_text("")
        self.now = datetime(2026, 8, 16, 14, 0, tzinfo=HKT)
        self.runner = FakeCommandRunner()
        self.ai_calls = 0
        self._write_completed_slot("09:00")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_completed_slot(self, slot: str) -> None:
        hour, minute = slot.split(":")
        path = self.root / "strategy_briefing" / "runs" / f"2026-08-16@{hour}-{minute}.json"
        path.write_text(
            json.dumps(
                {
                    "slot": f"2026-08-16@{slot}",
                    "status": "completed",
                    "notification_status": "sent",
                    "scanned_at": f"2026-08-16T{slot}:02+08:00",
                    "completed_at": f"2026-08-16T{hour}:{int(minute)+5:02d}:00+08:00",
                }
            )
        )

    def _ai(self, incident):
        self.ai_calls += 1
        return {
            "severity": incident["severity"],
            "severity_reason": "定時任務或外部寫入可能漏跑，屬需要即時處理的生產錯誤。",
            "fault_cause": "根據現有錯誤證據，爬蟲進程以非零狀態退出。",
            "fault_impact": "本輪資料未完成更新，下游結果可能繼續使用舊資料。",
            "fault_time_hkt": incident["occurred_at_hkt"],
            "recommended_solutions": ["讀取完整任務日誌。", "只恢復未完成階段並驗證結果。"],
            "needs_human": True,
        }

    def _monitor(self, *, enabled=False, ai=None, enable_ledger=False) -> project_monitor.ProjectMonitor:
        return project_monitor.ProjectMonitor(
            runtime_root=self.root,
            config_path=CONFIG_PATH,
            state_dir=self.state_dir,
            environ={
                "CMHK_ALERT_NOTIFICATIONS": "1" if enabled else "0",
                "CMHK_ALERT_AI_DIAGNOSIS": "1",
                "CMHK_ERROR_LEDGER_ENABLED": "1" if enable_ledger else "0",
                "CMHK_MONITOR_LOG_ROOT": str(self.log_root),
                "CMHK_MONITOR_SOURCE_ROOT": str(self.root),
            },
            now_fn=lambda: self.now,
            command_runner=self.runner,
            http_getter=lambda _url, _timeout: {
                "ok": True,
                "status": {
                    "visuals": {
                        "quality": {"failed": 0},
                        "crawl": {"successRate": 100, "completedAt": "2026-08-16 03:05:00"},
                    }
                },
            },
            ai_diagnoser=ai or self._ai,
        )

    def _issue(self, monitor, key="test-error"):
        return monitor._issue(
            condition_key=key,
            component="crawl",
            task_name="定时主爬虫",
            severity="P1",
            summary="任务失败",
            error="crawl returned 1",
            impact="本轮数据未完成更新。",
            suggestions=["检查日志。"],
            terminal=True,
        )

    def test_catalog_covers_main_tasks_and_explicitly_excludes_token_hub(self):
        config = json.loads(CONFIG_PATH.read_text())
        kinds = {item["id"] for item in config["task_kinds"]}
        self.assertEqual(
            kinds,
            {
                "crawl",
                "strategic-news",
                "executive-intelligence-refresh",
                "weekly-report",
                "carrier-performance",
                "audio-generation",
                "feishu-media-metrics",
            },
        )
        self.assertIn("token-hub", config["excluded_components"])
        self.assertEqual(len(config["targets"]), 2)
        self.assertEqual(config["bot"]["app_id"], "cli_a9575e70ae799cb2")
        self.assertEqual(
            config["card_actions"]["primary_handler_open_id"],
            "ou_c90bf12154574fc836d69f4bf1429ddc",
        )
        self.assertIn("处理人员", config["error_ledger"]["columns"])
        service_ids = {item["id"] for item in config["services"]}
        self.assertIn("project-monitor", service_ids)
        self.assertIn("project-monitor-card-actions", service_ids)

    def test_ai_message_content_blocks_are_normalized_before_json_parsing(self):
        monitor = self._monitor()
        content = [
            {"type": "output_text", "text": '{"severity":"P3",'},
            {"type": "output_text", "text": '"needs_human":true}'},
        ]

        parsed = monitor._extract_json_object(monitor._ai_message_text(content))

        self.assertEqual(parsed, {"severity": "P3", "needs_human": True})

    def test_solution_numbering_is_not_duplicated_by_card_or_ledger(self):
        self.assertEqual(project_monitor._solution_text("1. 检查完整日志。"), "检查完整日志。")
        self.assertEqual(project_monitor._solution_text("2、修复后回读。"), "修复后回读。")

    def test_failed_crawl_registry_record_becomes_actionable_error(self):
        path = self.root / "agent_knowledge" / "crawl_run_logs" / "index.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "crawl_run_id": "run-1",
                        "task_kind": "crawl",
                        "trigger": "定时爬虫",
                        "run_status": "failed",
                        "failure_stage": "feishu_sync",
                        "started_at_hkt": "2026-08-16T03:00:00+08:00",
                        "completed_at_hkt": "2026-08-16T03:20:00+08:00",
                        "progress_detail": "飞书同步返回码 1",
                    }
                ]
            )
        )
        issues = self._monitor().collect_issues()
        issue = next(item for item in issues if item["condition_key"] == "crawl-task-failed:run-1")
        self.assertEqual(issue["severity"], "P1")
        self.assertIn("飞书同步", issue["error"])

    def test_failed_report_and_stale_report_are_covered(self):
        path = self.root / "task_runs" / "index.json"
        path.write_text(
            json.dumps(
                {
                    "tasks": [
                        {
                            "task_id": "task:failed",
                            "kind": "weekly-report",
                            "title": "双周报",
                            "run_status": "failed",
                            "started_at_hkt": "2026-08-16T10:00:00+08:00",
                            "completed_at_hkt": "2026-08-16T10:05:00+08:00",
                            "status_detail": "报告生成进程返回 1",
                        },
                        {
                            "task_id": "task:stale",
                            "kind": "audio-generation",
                            "title": "语音",
                            "run_status": "running",
                            "started_at_hkt": "2026-08-16T10:00:00+08:00",
                            "heartbeat_at_hkt": "2026-08-16T10:00:00+08:00",
                            "progress_detail": "等待时间戳",
                        },
                    ]
                }
            )
        )
        issues = self._monitor().collect_issues()
        keys = {item["condition_key"] for item in issues}
        self.assertIn("general-task-failed:task:failed", keys)
        self.assertIn("general-task-stuck:task:stale", keys)

    def test_missing_strategic_slot_is_p1_after_start_grace(self):
        self.now = datetime(2026, 8, 16, 15, 20, tzinfo=HKT)
        issues = self._monitor().collect_issues()
        issue = next(item for item in issues if item["condition_key"] == "strategic-slot-not-started:2026-08-16@15-00")
        self.assertEqual(issue["severity"], "P1")

    def test_active_strategic_scan_heartbeat_prevents_false_monitor_stale_alarm(self):
        self.now = datetime(2026, 8, 16, 15, 10, tzinfo=HKT)
        (self.root / "strategy_briefing" / "state.json").write_text(
            json.dumps({"last_cycle_at": "2026-08-16T15:00:00+08:00"})
        )
        (self.root / "agent_knowledge" / "crawl_run_logs" / "latest.json").write_text(
            json.dumps(
                {
                    "crawl_run_id": "strategic-running-1",
                    "task_kind": "strategic-news",
                    "run_status": "running",
                    "heartbeat_at_hkt": "2026-08-16T15:09:55+08:00",
                }
            )
        )

        issues = self._monitor().collect_issues()

        self.assertNotIn(
            "strategic-monitor-heartbeat-stale",
            {item["condition_key"] for item in issues},
        )

    def test_missing_feishu_media_metrics_slot_is_covered(self):
        self.now = datetime(2026, 8, 16, 17, 25, tzinfo=HKT)
        self._write_completed_slot("15:00")
        (self.root / "strategy_briefing" / "state.json").write_text(
            json.dumps({"last_cycle_at": self.now.isoformat(timespec="seconds")})
        )
        issues = self._monitor().collect_issues()
        issue = next(
            item
            for item in issues
            if item["condition_key"] == "feishu-media-metrics-slot-missed:20260816-1700"
        )
        self.assertEqual(issue["severity"], "P2")

    def test_feishu_media_metrics_daemon_error_log_is_covered(self):
        log_path = self.root / "var" / "feishu_media_metrics" / "daemon.stderr.log"
        log_path.write_text('{"ok": false, "error": "飞书回读失败"}\n')
        issues = self._monitor().collect_issues()
        issue = next(
            item
            for item in issues
            if item["condition_key"].startswith("feishu-media-metrics-error:")
        )
        self.assertEqual(issue["severity"], "P2")

    def test_monitor_and_card_action_failures_are_covered(self):
        (self.log_root / "project_monitor.stderr.log").write_text(
            "project monitor cycle failed: simulated state error\n"
        )
        (self.log_root / "project_monitor_card_actions.stderr.log").write_text(
            "card action failed locally: simulated sheet error\n"
        )
        issues = self._monitor().collect_issues()
        by_component = {item["component"]: item for item in issues}
        self.assertEqual(by_component["project-monitor"]["severity"], "P1")
        self.assertEqual(by_component["project-monitor-card-actions"]["severity"], "P2")

    def test_notifications_disabled_never_calls_ai_or_send(self):
        monitor = self._monitor(enabled=False)
        monitor.collect_issues = lambda: [self._issue(monitor)]
        result = monitor.run_cycle()
        self.assertEqual(result["mode"], "shadow_no_send")
        self.assertEqual(self.ai_calls, 0)
        self.assertEqual(self.runner.send_calls(), [])
        self.assertEqual(result["normal_messages_sent"], 0)
        self.assertEqual(result["recovery_messages_sent"], 0)

    def test_no_error_means_no_ai_and_no_group_message(self):
        monitor = self._monitor(enabled=True)
        monitor.collect_issues = lambda: []
        result = monitor.run_cycle()
        self.assertEqual(result["active_incidents"], [])
        self.assertEqual(self.ai_calls, 0)
        self.assertEqual(self.runner.send_calls(), [])

    def test_error_is_ai_analysed_once_then_sent_as_expected_bot_to_both_groups(self):
        monitor = self._monitor(enabled=True)
        monitor.collect_issues = lambda: [self._issue(monitor)]
        result = monitor.run_cycle()
        self.assertEqual(self.ai_calls, 1)
        sends = self.runner.send_calls()
        self.assertEqual(len(sends), 2)
        sent_chats = {args[args.index("--chat-id") + 1] for args in sends}
        self.assertEqual(sent_chats, set(self.runner.chat_names))
        for args in sends:
            self.assertEqual(args[args.index("--as") + 1], "bot")
            self.assertEqual(args[args.index("--profile") + 1], "cli_a9575e70ae799cb2")
            self.assertEqual(args[args.index("--msg-type") + 1], "interactive")
            card = json.loads(args[args.index("--content") + 1])
            self.assertEqual(card["schema"], "2.0")
            self.assertEqual(card["header"]["template"], "red")
            self.assertIn("P1｜紧急故障 · 定时主爬虫", card["header"]["title"]["content"])
            self.assertEqual(len(card["body"]["elements"]), 5)
            serialized = json.dumps(card, ensure_ascii=False)
            self.assertIn("重要等级（LLM 复核）", serialized)
            self.assertIn("故障原因", serialized)
            self.assertIn("故障影响", serialized)
            self.assertIn("故障时间", serialized)
            self.assertIn("建议解决方案", serialized)
            self.assertIn("需要人工介入", serialized)
            self.assertIn(
                "<at id=ou_c90bf12154574fc836d69f4bf1429ddc></at>",
                serialized,
            )
            self.assertIn('"action": "cmhk_mark_handled_v1"', serialized)
            self.assertNotRegex(serialized, r"[緊處請議響間級複斷據]")
        states = result["active_incidents"][0]["delivery_states"]
        self.assertEqual(set(states.values()), {"verified"})

    def test_ai_failure_fails_closed_without_any_group_send(self):
        def failing_ai(_incident):
            self.ai_calls += 1
            raise RuntimeError("AI unavailable")

        monitor = self._monitor(enabled=True, ai=failing_ai)
        monitor.collect_issues = lambda: [self._issue(monitor)]
        result = monitor.run_cycle()
        self.assertEqual(self.ai_calls, 1)
        self.assertEqual(self.runner.send_calls(), [])
        self.assertEqual(result["active_incidents"][0]["diagnosis_status"], "failed_waiting_retry")

    def test_ai_output_missing_required_fault_field_fails_closed(self):
        def incomplete_ai(incident):
            payload = self._ai(incident)
            payload.pop("fault_impact")
            return payload

        monitor = self._monitor(enabled=True, ai=incomplete_ai)
        monitor.collect_issues = lambda: [self._issue(monitor)]
        result = monitor.run_cycle()
        self.assertEqual(self.runner.send_calls(), [])
        self.assertEqual(result["active_incidents"][0]["diagnosis_status"], "failed_waiting_retry")

    def test_ai_cannot_lower_rule_severity(self):
        def lower_severity_ai(incident):
            payload = self._ai(incident)
            payload["severity"] = "P3"
            return payload

        monitor = self._monitor(enabled=True, ai=lower_severity_ai)
        monitor.collect_issues = lambda: [self._issue(monitor)]
        result = monitor.run_cycle()
        self.assertEqual(len(self.runner.send_calls()), 2)
        self.assertEqual(result["active_incidents"][0]["ai_severity"], "P1")

    def test_ai_fault_time_must_match_observed_evidence(self):
        def wrong_time_ai(incident):
            payload = self._ai(incident)
            payload["fault_time_hkt"] = "2026-08-15T01:00:00+08:00"
            return payload

        monitor = self._monitor(enabled=True, ai=wrong_time_ai)
        monitor.collect_issues = lambda: [self._issue(monitor)]
        result = monitor.run_cycle()
        self.assertEqual(self.runner.send_calls(), [])
        self.assertEqual(result["active_incidents"][0]["diagnosis_status"], "failed_waiting_retry")

    def test_incident_first_seen_while_disabled_is_never_replayed_when_gate_enables(self):
        monitor = self._monitor(enabled=False)
        monitor.collect_issues = lambda: [self._issue(monitor)]
        monitor.run_cycle()
        monitor.environ["CMHK_ALERT_NOTIFICATIONS"] = "1"
        monitor.run_cycle()
        self.assertEqual(self.ai_calls, 0)
        self.assertEqual(self.runner.send_calls(), [])

    def test_resolved_shadow_condition_reappears_as_new_enabled_incident(self):
        monitor = self._monitor(enabled=False)
        issues = [self._issue(monitor)]
        issues[0]["terminal"] = False
        monitor.collect_issues = lambda: list(issues)
        first = monitor.run_cycle()
        first_id = first["active_incidents"][0]["incident_id"]
        issues.clear()
        monitor.run_cycle()
        monitor.environ["CMHK_ALERT_NOTIFICATIONS"] = "1"
        issues.append(self._issue(monitor))
        issues[0]["terminal"] = False
        third = monitor.run_cycle()
        self.assertEqual(self.ai_calls, 1)
        self.assertEqual(len(self.runner.send_calls()), 2)
        self.assertNotEqual(third["active_incidents"][0]["incident_id"], first_id)

    def test_terminal_one_shot_error_is_retained_until_ai_retry_succeeds(self):
        def flaky_ai(incident):
            self.ai_calls += 1
            if self.ai_calls == 1:
                raise RuntimeError("temporary AI failure")
            return {
                "severity": incident["severity"],
                "severity_reason": "該錯誤已令本輪任務失敗，需要處理。",
                "fault_cause": "根據現有證據，背景任務執行時發生錯誤。",
                "fault_impact": "本輪產物未完成，但上一版資料仍保留。",
                "fault_time_hkt": incident["occurred_at_hkt"],
                "recommended_solutions": ["檢查完整日誌並只恢復失敗步驟。"],
                "needs_human": True,
            }

        monitor = self._monitor(enabled=True, ai=flaky_ai)
        issues = [self._issue(monitor)]
        monitor.collect_issues = lambda: list(issues)
        first = monitor.run_cycle()
        self.assertEqual(first["active_incidents"][0]["diagnosis_status"], "failed_waiting_retry")
        self.assertEqual(self.runner.send_calls(), [])
        issues.clear()
        self.now += timedelta(minutes=5, seconds=1)
        second = monitor.run_cycle()
        self.assertEqual(self.ai_calls, 2)
        self.assertEqual(len(self.runner.send_calls()), 2)
        self.assertEqual(second["active_incidents"][0]["diagnosis_status"], "completed")

    def test_wrong_bot_app_id_fails_closed_before_send(self):
        self.runner.bot_app_id = "cli_wrong"
        monitor = self._monitor(enabled=True)
        monitor.collect_issues = lambda: [self._issue(monitor)]
        result = monitor.run_cycle()
        self.assertEqual(self.ai_calls, 1)
        self.assertEqual(self.runner.send_calls(), [])
        states = result["active_incidents"][0]["delivery_states"]
        self.assertEqual(set(states.values()), {"failed_before_verification"})

    def test_wrong_live_chat_name_fails_closed_for_that_target(self):
        first = "oc_22bf3c7febc4bab295fedfb0b8e6c176"
        self.runner.chat_names[first] = "错误群名"
        monitor = self._monitor(enabled=True)
        monitor.collect_issues = lambda: [self._issue(monitor)]
        result = monitor.run_cycle()
        sends = self.runner.send_calls()
        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0][sends[0].index("--chat-id") + 1], "oc_f86adbf0010f3e648400c377bf26179b")
        states = result["active_incidents"][0]["delivery_states"]
        self.assertEqual(states[first], "failed_before_verification")
        self.assertEqual(states["oc_f86adbf0010f3e648400c377bf26179b"], "verified")

    def test_send_success_with_readback_failure_is_not_retried_as_duplicate(self):
        self.runner.fail_readback = True
        monitor = self._monitor(enabled=True)
        monitor.collect_issues = lambda: [self._issue(monitor)]
        first = monitor.run_cycle()
        self.assertEqual(len(self.runner.send_calls()), 2)
        states = first["active_incidents"][0]["delivery_states"]
        self.assertEqual(set(states.values()), {"sent_pending_readback"})
        self.now += timedelta(minutes=1)
        monitor.run_cycle()
        self.assertEqual(len(self.runner.send_calls()), 2)

    def test_one_chat_failure_does_not_block_the_other_chat(self):
        failed_chat = "oc_22bf3c7febc4bab295fedfb0b8e6c176"
        self.runner.fail_send_chats.add(failed_chat)
        monitor = self._monitor(enabled=True)
        monitor.collect_issues = lambda: [self._issue(monitor)]
        result = monitor.run_cycle()
        states = result["active_incidents"][0]["delivery_states"]
        self.assertEqual(states[failed_chat], "failed_before_verification")
        self.assertEqual(states["oc_f86adbf0010f3e648400c377bf26179b"], "verified")

    def test_resolved_condition_is_local_only_and_never_sends_recovery(self):
        monitor = self._monitor(enabled=True)
        issues = [self._issue(monitor)]
        issues[0]["terminal"] = False
        monitor.collect_issues = lambda: list(issues)
        monitor.run_cycle()
        self.assertEqual(len(self.runner.send_calls()), 2)
        issues.clear()
        result = monitor.run_cycle()
        self.assertEqual(result["active_incidents"], [])
        self.assertEqual(len(self.runner.send_calls()), 2)
        events = self.state_dir.joinpath("events.jsonl").read_text()
        self.assertIn("incident_resolved_local_only", events)

    def test_error_ledger_records_errors_in_shadow_without_ai_or_group_messages(self):
        monitor = self._monitor(enabled=False, enable_ledger=True)
        monitor.collect_issues = lambda: [self._issue(monitor)]
        result = monitor.run_cycle()
        self.assertEqual(self.ai_calls, 0)
        self.assertEqual(self.runner.send_calls(), [])
        self.assertEqual(len(self.runner.ledger_rows), 1)
        row = self.runner.ledger_rows[0]
        self.assertRegex(row[0], r"^[0-9a-f]{24}$")
        self.assertEqual(row[3], "P1 紧急")
        self.assertIn("规则最低等级", row[4])
        self.assertEqual(row[5], "定时主爬虫")
        self.assertEqual(row[6], "crawl")
        self.assertEqual(row[7], "任务失败")
        self.assertEqual(row[8], "本轮数据未完成更新。")
        self.assertIn("crawl returned 1", row[9])
        self.assertIn("检查日志", row[10])
        self.assertEqual(row[11], "待LLM判断")
        self.assertEqual(row[12], "")
        self.assertEqual(row[13], "待处理")
        self.assertEqual(row[15], "未调用（影子模式）")
        self.assertEqual(row[16], "未发送（影子期）")
        self.assertEqual(result["error_ledger"]["synced_incidents"], 1)
        writes_before = len(self.runner.ledger_write_calls())
        monitor.run_cycle()
        self.assertEqual(len(self.runner.ledger_rows), 1)
        self.assertEqual(len(self.runner.ledger_write_calls()), writes_before)

    def test_error_ledger_updates_system_fields_without_overwriting_handler_columns(self):
        monitor = self._monitor(enabled=False, enable_ledger=True)
        issue = self._issue(monitor)
        monitor.collect_issues = lambda: [issue]
        monitor.run_cycle()
        self.runner.ledger_rows[0][12] = "张三"
        self.runner.ledger_rows[0][13] = "处理中"
        issue["impact"] = "更新后的故障影响。"
        self.now += timedelta(minutes=1)
        monitor.run_cycle()
        row = self.runner.ledger_rows[0]
        self.assertEqual(row[8], "更新后的故障影响。")
        self.assertEqual(row[12], "张三")
        self.assertEqual(row[13], "处理中")
        update = next(call for call in reversed(self.runner.calls) if "+cells-set" in call)
        writes = json.loads(update[update.index("--writes") + 1])
        self.assertEqual({item["range"] for item in writes}, {"A2:L2", "O2:Q2"})

    def test_error_ledger_failure_is_local_only_and_never_sends(self):
        self.runner.fail_ledger = True
        monitor = self._monitor(enabled=False, enable_ledger=True)
        monitor.collect_issues = lambda: [self._issue(monitor)]
        result = monitor.run_cycle()
        self.assertEqual(self.ai_calls, 0)
        self.assertEqual(self.runner.send_calls(), [])
        self.assertIn("simulated ledger failure", result["error_ledger"]["last_error"])
        events = self.state_dir.joinpath("events.jsonl").read_text()
        self.assertIn("error_ledger_sync_failed_local_only", events)

    def test_sensitive_values_are_redacted_before_incident_storage(self):
        monitor = self._monitor()
        issue = monitor._issue(
            condition_key="secret",
            component="crawl",
            task_name="secret test",
            severity="P2",
            summary="bad",
            error="Authorization: Bearer abcdefghijklmnop api_key=sk-secret-secret-secret",
            impact="none",
            suggestions=[],
        )
        self.assertNotIn("abcdefghijklmnop", issue["error"])
        self.assertNotIn("sk-secret", issue["error"])
        self.assertIn("[REDACTED]", issue["error"])

    def test_hong_kong_variant_is_normalized_to_mainland_simplified_wording(self):
        self.assertEqual(project_monitor._to_simplified("到底是甚麼？"), "到底是什么？")


if __name__ == "__main__":
    unittest.main()

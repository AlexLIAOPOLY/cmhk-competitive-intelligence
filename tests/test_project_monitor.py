from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import project_monitor


HKT = ZoneInfo("Asia/Hong_Kong")
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "project_monitor.json"
REQUIREMENTS_CHAT_ID = "oc_22bf3c7febc4bab295fedfb0b8e6c176"
PROJECT_CHAT_ID = "oc_f86adbf0010f3e648400c377bf26179b"
INCIDENT_CHAT_ID = "oc_4b8863e13b04e8d70023ba165b496a6b"
BOTH_ROLES = "requirements,project"


class FakeCommandRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.message_targets: dict[str, str] = {}
        self.fail_send_chats: set[str] = set()
        self.fail_readback = False
        self.fail_resolution_update = False
        self.updated_messages: dict[str, str] = {}
        self.fail_ledger = False
        self.fail_ledger_styles = False
        self.ledger_append_row_shift = 0
        self.bot_app_id = "cli_a9575e70ae799cb2"
        self.ledger_rows: list[list[str]] = []
        self.chat_names = {
            "oc_22bf3c7febc4bab295fedfb0b8e6c176": "竞对AI项目需求沟通群",
            "oc_f86adbf0010f3e648400c377bf26179b": "揭榜-竞争对手与行业情报监测AI应用",
            "oc_4b8863e13b04e8d70023ba165b496a6b": "战略竞对故障处理群",
        }
        self.service_pid = 4242
        self.service_started = "Mon Aug 17 17:40:26 2026"

    def __call__(self, argv, *, cwd, env, timeout):
        args = list(argv)
        self.calls.append(args)
        if args[:2] == ["launchctl", "print"]:
            return subprocess.CompletedProcess(
                args,
                0,
                f"state = running\npid = {self.service_pid}\n",
                "",
            )
        if args[:2] == ["ps", "-p"]:
            return subprocess.CompletedProcess(args, 0, self.service_started + "\n", "")
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
                                {"sheet_id": "9c638d", "sheet_name": "主表", "row_count": 200},
                                {
                                    "sheet_id": "j1AY6G",
                                    "sheet_name": "项目错误告警",
                                    "row_count": 200,
                                },
                            ],
                        },
                    },
                    ensure_ascii=False,
                ),
                "",
            )
        if len(args) >= 3 and args[1:3] == ["sheets", "+cells-get"]:
            all_rows = [list(project_monitor.ERROR_LEDGER_COLUMNS), *self.ledger_rows]
            cells = [
                [[{"value": value} if value != "" else {} for value in row][index] for index in range(17)]
                for row in all_rows
            ]
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    {
                        "ok": True,
                        "identity": "bot",
                        "data": {
                            "has_more": False,
                            "ranges": [
                                {
                                    "actual_range": f"A1:Q{len(all_rows)}",
                                    "range": f"A1:Q{len(all_rows)}",
                                    "cells": cells,
                                    "row_indices": list(range(1, len(all_rows) + 1)),
                                    "col_indices": [chr(ord("A") + index) for index in range(17)],
                                    "truncated": False,
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
            for _ in range(self.ledger_append_row_shift):
                self.ledger_rows.append([""] * 17)
            self.ledger_append_row_shift = 0
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
        if len(args) >= 3 and args[1:3] == ["sheets", "+styles-put"]:
            if self.fail_ledger_styles:
                return subprocess.CompletedProcess(
                    args,
                    1,
                    "",
                    json.dumps({"ok": False, "error": {"message": "simulated style failure"}}),
                )
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps({"ok": True, "identity": "bot", "data": {"styled": True}}),
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
            content = self.updated_messages.get(message_id, "")
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
                                    "content": content,
                                    "updated": bool(content),
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
        if len(args) >= 4 and args[1:4] == ["api", "PATCH", args[3]]:
            if self.fail_resolution_update:
                return subprocess.CompletedProcess(
                    args,
                    1,
                    "",
                    json.dumps({"ok": False, "error": {"message": "simulated update failure"}}),
                )
            message_id = args[3].rsplit("/", 1)[-1]
            payload = json.loads(args[args.index("--data") + 1])
            self.updated_messages[message_id] = payload["content"]
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps({"ok": True, "identity": "bot", "data": {}}),
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

    def resolution_update_calls(self) -> list[list[str]]:
        return [
            call
            for call in self.calls
            if len(call) >= 4 and call[1:3] == ["api", "PATCH"]
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

    def test_fresh_independent_scheduler_heartbeat_suppresses_stale_log_alarm(self):
        scheduler_log = self.log_root / "frequency_scheduler.stderr.log"
        old_timestamp = (self.now - timedelta(hours=1)).timestamp()
        os.utime(scheduler_log, (old_timestamp, old_timestamp))
        heartbeat_path = self.root / "var" / "frequency_scheduler" / "heartbeat.json"
        heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        heartbeat_path.write_text(json.dumps({
            "service": "frequency-scheduler",
            "pid": 84947,
            "status": "running",
            "stage": "crawl_running",
            "crawl_run_id": "20260825_030017_080611",
            "updated_at_hkt": self.now.isoformat(timespec="seconds"),
        }))
        monitor = self._monitor()

        issues = monitor._detect_runtime_logs()

        self.assertNotIn("frequency-scheduler-heartbeat-stale", {item["condition_key"] for item in issues})

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
        if incident.get("_analysis_kind") == "resolution":
            return {
                "resolution_summary": "独立心跳证明调度器持续存活，原告警来自旧日志口径。",
                "recovery_cause": "任务执行期间 stderr 没有更新，但调度器进程没有中断。",
                "verification_summary": "已回读独立心跳的时间、PID、状态和阶段。",
                "remaining_risk": "无需补跑；继续观察下一轮心跳。",
                "needs_followup": False,
            }
        return {
            "severity": incident["severity"],
            "severity_reason": "定時任務或外部寫入可能漏跑，屬需要即時處理的生產錯誤。",
            "fault_cause": "根據現有錯誤證據，爬蟲進程以非零狀態退出。",
            "fault_impact": "本輪資料未完成更新，下游結果可能繼續使用舊資料。",
            "fault_time_hkt": incident["occurred_at_hkt"],
            "recommended_solutions": ["讀取完整任務日誌。", "只恢復未完成階段並驗證結果。"],
            "needs_human": True,
        }

    def _monitor(
        self,
        *,
        enabled=False,
        ai=None,
        enable_ledger=False,
        alert_roles: str | None = None,
        respect_route_cutover: bool = False,
    ) -> project_monitor.ProjectMonitor:
        environ = {
            "CMHK_ALERT_NOTIFICATIONS": "1" if enabled else "0",
            "CMHK_ALERT_AI_DIAGNOSIS": "1",
            "CMHK_ERROR_LEDGER_ENABLED": "1" if enable_ledger else "0",
            "CMHK_MONITOR_LOG_ROOT": str(self.log_root),
            "CMHK_MONITOR_SOURCE_ROOT": str(self.root),
            "CMHK_MONITOR_REPLAY_EXISTING_LOGS": "1",
        }
        if alert_roles is not None:
            environ["CMHK_ALERT_TARGET_ROLES"] = alert_roles
        monitor = project_monitor.ProjectMonitor(
            runtime_root=self.root,
            config_path=CONFIG_PATH,
            state_dir=self.state_dir,
            environ=environ,
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
        if not respect_route_cutover:
            for target in monitor.configured_targets:
                target.pop("notify_from_hkt", None)
        resolution_updates = monitor.config.get("resolution_message_updates")
        if isinstance(resolution_updates, dict):
            resolution_updates.pop("backfill_from_hkt", None)
        return monitor

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

    def _write_slot_archive(self, slot: str, payload: dict) -> None:
        hour, minute = slot.split(":")
        path = self.root / "strategy_briefing" / "runs" / f"2026-08-16@{hour}-{minute}.json"
        base = json.loads(path.read_text()) if path.exists() else {}
        base.update(payload)
        path.write_text(json.dumps(base))

    def test_open_ui_runtime_failure_is_alerted_and_resolved_state_is_clear(self):
        path = self.root / "var" / "ui_runtime_incidents.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "incident_type": "competitor-ai-insight",
            "status": "open",
            "component": "competitor-workbench",
            "task_name": "竞对工作台 AI 竞争洞察",
            "severity": "P2",
            "summary": "竞对工作台 AI 洞察未生成",
            "error": "TimeoutError: timed out",
            "impact": "AI 洞察未生成。",
            "suggestions": ["恢复 AI 洞察阶段。"],
            "first_seen_at_hkt": "2026-08-16T12:00:00+08:00",
        }
        path.write_text(json.dumps({"version": 1, "incidents": {"competitor-ai-insight": record}}))

        issues = self._monitor()._detect_ui_runtime_incidents()

        self.assertEqual([item["condition_key"] for item in issues], ["ui-runtime:competitor-ai-insight"])
        self.assertEqual(issues[0]["severity"], "P2")
        record["status"] = "resolved"
        path.write_text(json.dumps({"version": 1, "incidents": {"competitor-ai-insight": record}}))
        self.assertEqual(self._monitor()._detect_ui_runtime_incidents(), [])

    def test_empty_agentic_gap_search_alerts_even_when_scan_completes(self):
        self._write_slot_archive(
            "09:00",
            {
                "news_discovery": {
                    "agentic_search": {
                        "agentic_query_count": 8,
                        "agentic_result_count": 0,
                    }
                }
            },
        )
        monitor = self._monitor()

        issues = monitor._detect_strategic_content_quality()

        self.assertEqual(len(issues), 1)
        self.assertIn("Agentic", issues[0]["summary"])
        self.assertEqual(issues[0]["severity"], "P2")

    def test_agentic_gap_search_with_results_is_not_alerted(self):
        self._write_slot_archive(
            "09:00",
            {
                "news_discovery": {
                    "agentic_search": {
                        "agentic_query_count": 8,
                        "agentic_result_count": 3,
                    }
                }
            },
        )

        self.assertEqual(self._monitor()._detect_strategic_content_quality(), [])

    def test_no_agentic_queries_planned_is_not_treated_as_failure(self):
        self._write_slot_archive(
            "09:00",
            {
                "news_discovery": {
                    "agentic_search": {
                        "agentic_query_count": 0,
                        "agentic_result_count": 0,
                    }
                }
            },
        )

        self.assertEqual(self._monitor()._detect_strategic_content_quality(), [])

    def test_blocked_dirty_copy_raises_a_p1_alert(self):
        self._write_slot_archive(
            "09:00",
            {
                "review_sheet": {
                    "dirty_copy_blocked_count": 2,
                    "dirty_copy_blocked": [
                        {"reason": "标题含模型提示词", "title": "合法JSON 需要判断"},
                    ],
                }
            },
        )
        monitor = self._monitor()

        issues = monitor._detect_strategic_content_quality()

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "P1")
        self.assertIn("提示词", issues[0]["summary"])

    def test_deferred_review_backlog_alerts_past_threshold(self):
        (self.root / "strategy_briefing" / "candidate_ai_editor_deferred.json").write_text(
            json.dumps({"items": [{"key": f"k{index}"} for index in range(60)]})
        )
        monitor = self._monitor()

        issues = monitor._detect_strategic_content_quality()

        self.assertEqual(len(issues), 1)
        self.assertIn("补审队列", issues[0]["summary"])

    def test_small_deferred_queue_does_not_alert(self):
        (self.root / "strategy_briefing" / "candidate_ai_editor_deferred.json").write_text(
            json.dumps({"items": [{"key": "k1"}]})
        )

        self.assertEqual(self._monitor()._detect_strategic_content_quality(), [])

    def test_content_quality_detector_is_registered(self):
        monitor = self._monitor()
        with mock.patch.object(
            monitor, "_detect_strategic_content_quality", return_value=[]
        ) as detector:
            monitor.collect_issues()

        detector.assert_called_once()

    def test_catalog_covers_main_tasks_and_explicitly_excludes_token_hub(self):
        config = json.loads(CONFIG_PATH.read_text())
        kinds = {item["id"] for item in config["task_kinds"]}
        self.assertEqual(
            kinds,
            {
                "crawl",
                "strategic-news",
                "four-database-source-discovery",
                "executive-intelligence-refresh",
                "weekly-report",
                "carrier-performance",
                "audio-generation",
                "feishu-media-metrics",
            },
        )
        self.assertIn("token-hub", config["excluded_components"])
        self.assertEqual(len(config["targets"]), 3)
        self.assertEqual(
            [item["chat_id"] for item in config["targets"] if item.get("alert_notify")],
            [INCIDENT_CHAT_ID],
        )
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

    def test_four_database_feishu_log_failure_is_alerted_with_audit_evidence(self):
        path = self.root / "agent_knowledge" / "crawl_run_logs" / "index.json"
        path.write_text(json.dumps([{
            "crawl_run_id": "four-db-log-failed",
            "task_kind": "executive-intelligence-refresh",
            "trigger": "四库与观察结论自动更新",
            "run_status": "failed",
            "failure_stage": "four_database_feishu_log",
            "started_at_hkt": "2026-08-16T03:00:00+08:00",
            "completed_at_hkt": "2026-08-16T03:20:00+08:00",
            "progress_detail": "四库与页面已完成，但飞书日志写后回读失败",
            "operational_summary": {
                "feishu_detail_log": {"ok": False, "error": "readback mismatch", "written": 602, "readback_verified": False},
                "overview_source_recrawl": {"path": "agent_knowledge/source_audit.json"},
            },
            "local_files": {"stream_log": "agent_knowledge/log.jsonl"},
        }]))

        issue = next(item for item in self._monitor().collect_issues() if item["condition_key"] == "crawl-task-failed:four-db-log-failed")

        self.assertEqual(issue["severity"], "P2")
        self.assertIn("feishu_log_error=readback mismatch", issue["evidence"])
        self.assertIn("readback_verified=False", " ".join(issue["evidence"]))
        self.assertTrue(any("只补写缺失日志" in item for item in issue["suggestions"]))

    def test_four_database_log_recovery_requires_positive_event_id_readback(self):
        path = self.root / "agent_knowledge" / "crawl_run_logs" / "index.json"
        record = {
            "component": "executive-intelligence-refresh",
            "occurred_at_hkt": "2026-08-16T03:20:00+08:00",
        }
        run = {
            "crawl_run_id": "four-db-log-recovered",
            "task_kind": "executive-intelligence-refresh",
            "run_status": "completed",
            "completed_at_hkt": "2026-08-16T04:20:00+08:00",
            "operational_summary": {
                "feishu_detail_log": {"ok": True, "written": 603, "row_start": 672, "row_end": 1274, "readback_verified": False},
            },
        }
        path.write_text(json.dumps([run]))
        monitor = self._monitor()
        self.assertEqual(monitor._four_database_log_recovery_evidence(record), [])
        run["operational_summary"]["feishu_detail_log"]["readback_verified"] = True
        path.write_text(json.dumps([run]))

        evidence = monitor._four_database_log_recovery_evidence(record)

        self.assertTrue(any("readback_verified=true" in item for item in evidence))
        self.assertTrue(any("672-1274" in item for item in evidence))

    def test_newer_success_supersedes_older_failed_crawl(self):
        path = self.root / "agent_knowledge" / "crawl_run_logs" / "index.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "crawl_run_id": "failed-old",
                        "task_kind": "crawl",
                        "run_status": "failed",
                        "completed_at_hkt": "2026-08-16T03:20:00+08:00",
                    },
                    {
                        "crawl_run_id": "completed-new",
                        "task_kind": "crawl",
                        "run_status": "completed",
                        "completed_at_hkt": "2026-08-16T04:20:00+08:00",
                    },
                ]
            )
        )

        keys = {item["condition_key"] for item in self._monitor().collect_issues()}

        self.assertNotIn("crawl-task-failed:failed-old", keys)

    def test_fully_gated_intelligence_fallback_is_not_reported_as_failure(self):
        path = self.root / "agent_knowledge" / "crawl_run_logs" / "index.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "crawl_run_id": "refresh-fallback",
                        "task_kind": "executive-intelligence-refresh",
                        "trigger": "四库与AI观察结论刷新",
                        "run_status": "failed",
                        "completed_at_hkt": "2026-08-16T12:20:00+08:00",
                        "operational_summary": {
                            "status": "completed_with_fallback",
                            "model_analysis": {
                                "fallback_used": True,
                                "focuses_expected": 17,
                                "focuses_passed": 17,
                            },
                            "pages_publish": {"ok": True, "status": "verified"},
                        },
                    }
                ]
            )
        )

        keys = {item["condition_key"] for item in self._monitor().collect_issues()}

        self.assertNotIn("crawl-task-failed:refresh-fallback", keys)

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

    def test_newer_success_supersedes_older_failed_general_task(self):
        path = self.root / "task_runs" / "index.json"
        path.write_text(
            json.dumps(
                {
                    "tasks": [
                        {
                            "task_id": "weekly-old",
                            "kind": "weekly-report",
                            "run_status": "failed",
                            "completed_at_hkt": "2026-08-16T10:05:00+08:00",
                        },
                        {
                            "task_id": "weekly-new",
                            "kind": "weekly-report",
                            "run_status": "completed",
                            "completed_at_hkt": "2026-08-16T11:05:00+08:00",
                        },
                    ]
                }
            )
        )

        keys = {item["condition_key"] for item in self._monitor().collect_issues()}

        self.assertNotIn("general-task-failed:weekly-old", keys)

    def test_missing_strategic_slot_is_p1_after_start_grace(self):
        self.now = datetime(2026, 8, 16, 15, 20, tzinfo=HKT)
        issues = self._monitor().collect_issues()
        issue = next(item for item in issues if item["condition_key"] == "strategic-slot-not-started:2026-08-16@14-00")
        self.assertEqual(issue["severity"], "P1")

    def test_running_scan_is_allowed_until_next_midnight_cutoff(self):
        self.now = datetime(2026, 8, 16, 23, 30, tzinfo=HKT)
        monitor = self._monitor()
        monitor._strategic_task_started = lambda _slot: True

        issues = monitor._detect_strategic_slots()

        self.assertNotIn(
            "strategic-slot-incomplete:2026-08-16@09-00",
            {item["condition_key"] for item in issues},
        )

    def test_planned_midnight_cutoff_archive_is_not_reported_as_failure(self):
        self.now = datetime(2026, 8, 16, 23, 59, tzinfo=HKT)
        path = self.root / "strategy_briefing" / "runs" / "2026-08-16@09-00.json"
        path.write_text(
            json.dumps(
                {
                    "slot": "2026-08-16@09:00",
                    "status": "cutoff",
                    "notification_status": "not_sent_cutoff",
                    "cutoff_at": "2026-08-17T00:00:00+08:00",
                }
            )
        )

        issues = self._monitor()._detect_strategic_slots()

        self.assertNotIn(
            "strategic-slot-failed:2026-08-16@09-00:cutoff:not_sent_cutoff",
            {item["condition_key"] for item in issues},
        )

    def test_strategic_pending_archive_is_not_failed_during_finish_grace(self):
        self.now = datetime(2026, 8, 16, 9, 58, 29, tzinfo=HKT)
        path = self.root / "strategy_briefing" / "runs" / "2026-08-16@09-00.json"
        path.write_text(json.dumps({
            "slot": "2026-08-16@09:00",
            "status": "pipeline_completed",
            "notification_status": "pending",
            "scanned_at": "2026-08-16T09:58:27+08:00",
        }))

        keys = {item["condition_key"] for item in self._monitor()._detect_strategic_slots()}

        self.assertNotIn("strategic-slot-failed:2026-08-16@09-00", keys)

    def test_strategic_pending_archive_is_failed_after_finish_grace(self):
        self.now = datetime(2026, 8, 16, 10, 11, tzinfo=HKT)
        path = self.root / "strategy_briefing" / "runs" / "2026-08-16@09-00.json"
        path.write_text(json.dumps({
            "slot": "2026-08-16@09:00",
            "status": "pipeline_completed",
            "notification_status": "pending",
            "scanned_at": "2026-08-16T09:58:27+08:00",
        }))

        keys = {item["condition_key"] for item in self._monitor()._detect_strategic_slots()}

        self.assertIn("strategic-slot-failed:2026-08-16@09-00", keys)

    def test_active_strategic_scan_heartbeat_prevents_false_monitor_stale_alarm(self):
        self.now = datetime(2026, 8, 16, 15, 10, tzinfo=HKT)
        (self.root / "strategy_briefing" / "state.json").write_text(
            json.dumps({"last_cycle_at": "2026-08-16T14:00:00+08:00"})
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
        self._write_completed_slot("14:00")
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
            if item["condition_key"] == "feishu-media-metrics-error"
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

    def test_runtime_log_conditions_use_stable_keys(self):
        (self.log_root / "web_app.stderr.log").write_text(
            "ERROR:root:候选 abcdef1234567890 批量编辑失败\n"
        )
        monitor = self._monitor()
        issues = monitor.collect_issues()
        issue = next(item for item in issues if item["component"] == "web-app")
        self.assertEqual(issue["condition_key"], "web-background-error")

    def test_legacy_fingerprinted_log_incidents_are_retired(self):
        monitor = self._monitor(enabled=False)
        legacy_key = "web-background-error:old-cursor-fingerprint"
        legacy_id = "legacy-incident"
        monitor.state["conditions"] = {legacy_key: legacy_id}
        monitor.state["incidents"] = {
            legacy_id: {
                "incident_id": legacy_id,
                "condition_key": legacy_key,
                "status": "open",
                "terminal": True,
                "first_seen_at_hkt": self.now.isoformat(timespec="seconds"),
            }
        }

        _, active = monitor._upsert_incidents([])

        self.assertEqual(active, [])
        self.assertEqual(monitor.state["incidents"][legacy_id]["status"], "resolved")
        self.assertEqual(
            monitor.state["incidents"][legacy_id]["resolution_reason"],
            "superseded_by_stable_log_condition",
        )

    def test_log_incident_before_current_service_start_is_retired(self):
        monitor = self._monitor(enabled=True)
        monitor._detect_launch_services()
        incident_id = "pre-restart-incident"
        monitor.state["conditions"] = {"web-background-error": incident_id}
        monitor.state["incidents"] = {
            incident_id: {
                "incident_id": incident_id,
                "condition_key": "web-background-error",
                "component": "web-app",
                "status": "open",
                "terminal": True,
                "occurred_at_hkt": "2026-08-17T09:00:00+08:00",
                "first_seen_at_hkt": "2026-08-17T09:00:00+08:00",
                "delivery": {},
            }
        }

        _, active = monitor._upsert_incidents([])

        self.assertEqual(active, [])
        record = monitor.state["incidents"][incident_id]
        self.assertEqual(record["status"], "resolved")
        self.assertEqual(record["resolution_reason"], "service_restarted_after_error")

    def test_legacy_terminal_quality_record_resolves_when_not_current(self):
        monitor = self._monitor(enabled=True)
        incident_id = "old-quality-incident"
        old_key = "data-quality:old-run:4:98"
        monitor.state["conditions"] = {old_key: incident_id}
        monitor.state["incidents"] = {
            incident_id: {
                "incident_id": incident_id,
                "condition_key": old_key,
                "component": "crawl",
                "status": "open",
                "terminal": True,
                "occurred_at_hkt": "2026-08-16T03:00:00+08:00",
            }
        }

        _, active = monitor._upsert_incidents([])

        self.assertEqual(active, [])
        record = monitor.state["incidents"][incident_id]
        self.assertEqual(record["status"], "resolved")
        self.assertEqual(record["resolution_reason"], "condition_no_longer_current")

    def test_recovered_scheduler_log_incident_closes_without_service_restart(self):
        monitor = self._monitor(enabled=True)
        incident_id = "scheduler-network-timeout"
        monitor.state["conditions"] = {"scheduler-log-error": incident_id}
        monitor.state["incidents"] = {
            incident_id: {
                "incident_id": incident_id,
                "condition_key": "scheduler-log-error",
                "component": "frequency-scheduler",
                "status": "open",
                "terminal": True,
                "occurred_at_hkt": "2026-08-16T13:55:00+08:00",
            }
        }

        _, active = monitor._upsert_incidents([])

        self.assertEqual(active, [])
        record = monitor.state["incidents"][incident_id]
        self.assertEqual(record["status"], "resolved")
        self.assertEqual(record["resolution_reason"], "log_condition_cleared")

    def test_media_metrics_log_incident_closes_after_verified_slot_delivery(self):
        monitor = self._monitor(enabled=True)
        incident_id = "media-rate-limit"
        monitor.state["conditions"] = {"feishu-media-metrics-error": incident_id}
        monitor.state["incidents"] = {
            incident_id: {
                "incident_id": incident_id,
                "condition_key": "feishu-media-metrics-error",
                "component": "feishu-media-metrics",
                "status": "open",
                "terminal": True,
                "occurred_at_hkt": "2026-08-16T17:00:33+08:00",
            }
        }
        state_path = self.root / "var" / "feishu_media_metrics" / "state.json"
        state_path.write_text(
            json.dumps(
                {
                    "sent_slots": {"20260816-1700": "om_verified"},
                    "slot_deliveries": {
                        "20260816-1700": {
                            "message_id": "om_verified",
                            "chat_id": "oc_destination",
                            "verified_at_hkt": "2026-08-16T17:02:49+08:00",
                            "readback_verified": True,
                        }
                    },
                }
            )
        )

        _, active = monitor._upsert_incidents([])

        self.assertEqual(active, [])
        record = monitor.state["incidents"][incident_id]
        self.assertEqual(record["status"], "resolved")
        self.assertEqual(record["resolution_reason"], "media_metrics_delivery_verified")
        self.assertIn("om_verified", " ".join(record["resolution"]["evidence"]))

    def test_media_metrics_log_incident_stays_open_without_slot_delivery(self):
        monitor = self._monitor(enabled=True)
        incident_id = "media-rate-limit"
        monitor.state["conditions"] = {"feishu-media-metrics-error": incident_id}
        monitor.state["incidents"] = {
            incident_id: {
                "incident_id": incident_id,
                "condition_key": "feishu-media-metrics-error",
                "component": "feishu-media-metrics",
                "status": "open",
                "terminal": True,
                "occurred_at_hkt": "2026-08-16T17:00:33+08:00",
            }
        }
        state_path = self.root / "var" / "feishu_media_metrics" / "state.json"
        state_path.write_text(json.dumps({"sent_slots": {}}))

        _, active = monitor._upsert_incidents([])

        self.assertEqual([item["incident_id"] for item in active], [incident_id])
        self.assertEqual(monitor.state["incidents"][incident_id]["status"], "open")

    def test_strategic_slot_accepts_same_day_migrated_morning_archive(self):
        expected = self.root / "strategy_briefing" / "runs" / "2026-08-16@09-00.json"
        expected.unlink()
        migrated = self.root / "strategy_briefing" / "runs" / "2026-08-16@07-00.json"
        migrated.write_text(
            json.dumps(
                {
                    "slot": "2026-08-16@07:00",
                    "slot_label": "晨间扫描",
                    "status": "completed",
                    "notification_status": "sent",
                    "scanned_at": "2026-08-16T07:00:00+08:00",
                    "completed_at": "2026-08-16T07:20:00+08:00",
                }
            )
        )

        issues = self._monitor()._detect_strategic_slots()

        self.assertNotIn(
            "strategic-slot-not-started:2026-08-16@09-00",
            {item["condition_key"] for item in issues},
        )

    def test_first_log_observation_starts_at_eof_without_replay(self):
        path = self.log_root / "web_app.stderr.log"
        path.write_text("ERROR old failure before monitor start\n")
        monitor = self._monitor(enabled=True)
        monitor.environ.pop("CMHK_MONITOR_REPLAY_EXISTING_LOGS", None)

        issues = monitor.collect_issues()

        self.assertNotIn("web-background-error", {item["condition_key"] for item in issues})
        self.assertEqual(monitor.state["log_offsets"][str(path)], path.stat().st_size)

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

    def test_error_is_ai_analysed_once_then_sent_as_expected_bot_to_incident_group(self):
        monitor = self._monitor(enabled=True)
        monitor.collect_issues = lambda: [self._issue(monitor)]
        result = monitor.run_cycle()
        self.assertEqual(self.ai_calls, 1)
        sends = self.runner.send_calls()
        self.assertEqual(len(sends), 1)
        sent_chats = {args[args.index("--chat-id") + 1] for args in sends}
        self.assertEqual(sent_chats, {INCIDENT_CHAT_ID})
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

    def test_ui_runtime_alert_also_fails_closed_if_ai_is_the_failure(self):
        def failing_ai(_incident):
            raise RuntimeError("AI unavailable")

        monitor = self._monitor(ai=failing_ai)
        incident = monitor._issue(
            condition_key="ui-runtime:competitor-ai-insight",
            component="competitor-workbench",
            task_name="竞对工作台 AI 竞争洞察",
            severity="P2",
            summary="AI 洞察未生成",
            error="TimeoutError: timed out",
            impact="AI 洞察未完成。",
            suggestions=["恢复 AI 洞察阶段。"],
        )
        incident.update({"incident_id": "ui-test", "diagnosis": {}, "diagnosis_attempts": 0})

        self.assertFalse(monitor._ensure_ai_diagnosis(incident))
        self.assertEqual(incident["diagnosis_status"], "failed_waiting_retry")
        self.assertFalse(incident.get("diagnosis"))

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
        self.assertEqual(len(self.runner.send_calls()), 1)
        self.assertEqual(result["active_incidents"][0]["ai_severity"], "P1")

    def test_ai_cannot_override_program_locked_fault_time(self):
        def wrong_time_ai(incident):
            payload = self._ai(incident)
            payload["fault_time_hkt"] = "2026-08-15T01:00:00+08:00"
            return payload

        monitor = self._monitor(enabled=True, ai=wrong_time_ai)
        monitor.collect_issues = lambda: [self._issue(monitor)]
        result = monitor.run_cycle()
        self.assertEqual(len(self.runner.send_calls()), 1)
        self.assertEqual(result["active_incidents"][0]["diagnosis_status"], "completed")
        incident = next(iter(monitor.state["incidents"].values()))
        self.assertEqual(incident["diagnosis"]["fault_time_hkt"], incident["occurred_at_hkt"])

    def test_repeated_ai_contract_failure_never_uses_deterministic_fallback(self):
        def incomplete_ai(incident):
            payload = self._ai(incident)
            payload.pop("fault_impact")
            return payload

        monitor = self._monitor(enabled=True, ai=incomplete_ai)
        monitor.collect_issues = lambda: [self._issue(monitor)]
        first = monitor.run_cycle()
        self.assertEqual(first["active_incidents"][0]["diagnosis_status"], "failed_waiting_retry")
        self.assertEqual(self.runner.send_calls(), [])
        self.now += timedelta(minutes=5, seconds=1)
        second = monitor.run_cycle()
        self.assertEqual(second["active_incidents"][0]["diagnosis_status"], "failed_waiting_retry")
        self.assertEqual(self.runner.send_calls(), [])
        self.now += timedelta(minutes=5, seconds=1)

        third = monitor.run_cycle()

        self.assertEqual(third["active_incidents"][0]["diagnosis_status"], "failed_waiting_retry")
        self.assertEqual(len(self.runner.send_calls()), 0)

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
        self.assertEqual(len(self.runner.send_calls()), 1)
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
        self.assertEqual(len(self.runner.send_calls()), 1)
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

    def test_previous_groups_are_excluded_from_alert_routing_by_default(self):
        monitor = self._monitor(enabled=True)
        routed = {str(item.get("chat_id")) for item in monitor.alert_targets}
        self.assertEqual(routed, {INCIDENT_CHAT_ID})
        monitor.collect_issues = lambda: [self._issue(monitor)]
        result = monitor.run_cycle()
        chat_calls = {
            json.loads(args[args.index("--params") + 1])["chat_id"]
            for args in self.runner.calls
            if len(args) >= 4 and args[1:4] == ["im", "chats", "get"]
        }
        self.assertNotIn(REQUIREMENTS_CHAT_ID, chat_calls)
        self.assertNotIn(PROJECT_CHAT_ID, chat_calls)
        self.assertEqual(
            set(result["active_incidents"][0]["delivery_states"]),
            {INCIDENT_CHAT_ID},
        )
        self.assertEqual(result["alert_routing_policy"], "incident_group_only")
        self.assertEqual(
            {item["chat_id"]: item["alert_notify"] for item in result["targets"]},
            {
                REQUIREMENTS_CHAT_ID: False,
                PROJECT_CHAT_ID: False,
                INCIDENT_CHAT_ID: True,
            },
        )

    def test_route_cutover_does_not_replay_incident_first_seen_before_activation(self):
        monitor = self._monitor(enabled=True, respect_route_cutover=True)
        monitor.collect_issues = lambda: [self._issue(monitor)]
        result = monitor.run_cycle()
        self.assertEqual(self.runner.send_calls(), [])
        self.assertEqual(self.ai_calls, 0)
        self.assertEqual(
            result["active_incidents"][0]["delivery_states"][INCIDENT_CHAT_ID],
            "suppressed_route_cutover",
        )
        self.assertEqual(self.runner.ledger_rows, [])

    def test_ledger_notification_status_counts_routed_group_only(self):
        monitor = self._monitor(enabled=True, enable_ledger=True)
        monitor.collect_issues = lambda: [self._issue(monitor)]
        monitor.run_cycle()
        self.assertEqual(self.runner.ledger_rows[0][16], "已发送并回读（1/1）")

    def test_opted_out_group_cannot_be_sent_even_if_called_directly(self):
        monitor = self._monitor(enabled=True)
        incident = self._issue(monitor)
        incident["diagnosis"] = {"ok": True}
        target = next(
            item for item in monitor.configured_targets if item["chat_id"] == REQUIREMENTS_CHAT_ID
        )
        with self.assertRaises(RuntimeError):
            monitor._send_to_target(incident, target)
        self.assertEqual(self.runner.send_calls(), [])

    def test_wrong_live_chat_name_fails_closed_for_that_target(self):
        self.runner.chat_names[REQUIREMENTS_CHAT_ID] = "错误群名"
        monitor = self._monitor(enabled=True, alert_roles=BOTH_ROLES)
        monitor.collect_issues = lambda: [self._issue(monitor)]
        result = monitor.run_cycle()
        sends = self.runner.send_calls()
        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0][sends[0].index("--chat-id") + 1], PROJECT_CHAT_ID)
        states = result["active_incidents"][0]["delivery_states"]
        self.assertEqual(states[REQUIREMENTS_CHAT_ID], "failed_before_verification")
        self.assertEqual(states[PROJECT_CHAT_ID], "verified")

    def test_send_success_with_readback_failure_is_not_retried_as_duplicate(self):
        self.runner.fail_readback = True
        monitor = self._monitor(enabled=True)
        monitor.collect_issues = lambda: [self._issue(monitor)]
        first = monitor.run_cycle()
        self.assertEqual(len(self.runner.send_calls()), 1)
        states = first["active_incidents"][0]["delivery_states"]
        self.assertEqual(set(states.values()), {"sent_pending_readback"})
        self.now += timedelta(minutes=1)
        monitor.run_cycle()
        self.assertEqual(len(self.runner.send_calls()), 1)

    def test_one_chat_failure_does_not_block_the_other_chat(self):
        self.runner.fail_send_chats.add(REQUIREMENTS_CHAT_ID)
        monitor = self._monitor(enabled=True, alert_roles=BOTH_ROLES)
        monitor.collect_issues = lambda: [self._issue(monitor)]
        result = monitor.run_cycle()
        states = result["active_incidents"][0]["delivery_states"]
        self.assertEqual(states[REQUIREMENTS_CHAT_ID], "failed_before_verification")
        self.assertEqual(states[PROJECT_CHAT_ID], "verified")

    def test_resolved_condition_updates_original_card_without_sending_recovery(self):
        monitor = self._monitor(enabled=True)
        issues = [self._issue(monitor)]
        issues[0]["condition_key"] = "frequency-scheduler-heartbeat-stale"
        issues[0]["terminal"] = False
        monitor.collect_issues = lambda: list(issues)
        monitor.run_cycle()
        self.assertEqual(len(self.runner.send_calls()), 1)
        heartbeat_path = self.root / "var" / "frequency_scheduler" / "heartbeat.json"
        heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        heartbeat_path.write_text(json.dumps({
            "service": "frequency-scheduler", "pid": 1234, "status": "running",
            "stage": "crawl_running", "crawl_run_id": "run-1",
            "updated_at_hkt": self.now.isoformat(timespec="seconds"),
        }))
        issues.clear()
        result = monitor.run_cycle()
        self.assertEqual(result["active_incidents"], [])
        self.assertEqual(len(self.runner.send_calls()), 1)
        self.assertEqual(len(self.runner.resolution_update_calls()), 1)
        message_id = next(iter(self.runner.updated_messages))
        updated_card = json.loads(self.runner.updated_messages[message_id])
        self.assertEqual(updated_card["header"]["template"], "green")
        self.assertIn("已确认任务正常", updated_card["header"]["title"]["content"])
        self.assertEqual(updated_card["header"]["icon"]["token"], "done_outlined")
        self.assertNotIn(
            "resolveButton",
            json.dumps(updated_card, ensure_ascii=False),
        )
        incident = next(iter(monitor.state["incidents"].values()))
        self.assertEqual(incident["resolution"]["type"], "normal_task_progress")
        self.assertFalse(incident["resolution"]["action"]["performed"])
        self.assertEqual(incident["resolution"]["ai_summary"]["source"], "llm")
        delivery = incident["delivery"][INCIDENT_CHAT_ID]
        self.assertEqual(delivery["resolution_update"]["state"], "verified")
        self.assertEqual(result["recovery_messages_sent"], 0)
        self.assertEqual(result["recovery_messages_updated"], 1)
        events = self.state_dir.joinpath("events.jsonl").read_text()
        self.assertIn("incident_resolved_local_only", events)
        self.assertIn("alert_resolution_update_verified", events)

    def test_failed_resolution_update_retries_without_sending_new_message(self):
        monitor = self._monitor(enabled=True)
        issues = [self._issue(monitor)]
        issues[0]["condition_key"] = "frequency-scheduler-heartbeat-stale"
        issues[0]["terminal"] = False
        monitor.collect_issues = lambda: list(issues)
        monitor.run_cycle()
        self.runner.fail_resolution_update = True
        heartbeat_path = self.root / "var" / "frequency_scheduler" / "heartbeat.json"
        heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        heartbeat_path.write_text(json.dumps({
            "service": "frequency-scheduler", "pid": 1234, "status": "running",
            "stage": "crawl_running", "crawl_run_id": "run-1",
            "updated_at_hkt": self.now.isoformat(timespec="seconds"),
        }))
        issues.clear()
        monitor.run_cycle()
        self.assertEqual(len(self.runner.send_calls()), 1)
        self.assertEqual(len(self.runner.resolution_update_calls()), 1)
        incident = next(iter(monitor.state["incidents"].values()))
        delivery = incident["delivery"][INCIDENT_CHAT_ID]
        self.assertEqual(delivery["resolution_update"]["state"], "failed_waiting_retry")
        monitor.run_cycle()
        self.assertEqual(len(self.runner.resolution_update_calls()), 1)

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

    def test_error_ledger_append_uses_actual_range_when_remote_row_moves(self):
        self.runner.ledger_append_row_shift = 1
        monitor = self._monitor(enabled=True, enable_ledger=True)
        monitor.collect_issues = lambda: [self._issue(monitor)]
        result = monitor.run_cycle()
        self.assertIsNone(result["error_ledger"]["last_error"])
        self.assertEqual(len(self.runner.send_calls()), 1)
        incident_id = result["active_incidents"][0]["incident_id"]
        matching_rows = [row for row in self.runner.ledger_rows if row[0] == incident_id]
        self.assertEqual(len(matching_rows), 1)
        style_call = next(call for call in self.runner.calls if "+styles-put" in call)
        styles = json.loads(style_call[style_call.index("--styles") + 1])
        self.assertEqual(styles["styles"][0]["cell_styles"][0]["range"], "A3:Q3")

    def test_alert_waits_for_ledger_row_when_append_fails(self):
        self.runner.fail_ledger = True
        monitor = self._monitor(enabled=True, enable_ledger=True)
        monitor.collect_issues = lambda: [self._issue(monitor)]
        result = monitor.run_cycle()
        self.assertEqual(self.runner.send_calls(), [])
        self.assertEqual(
            result["active_incidents"][0].get("delivery_states"),
            {},
        )

    def test_style_failure_does_not_block_incident_row_or_delivery(self):
        self.runner.fail_ledger_styles = True
        monitor = self._monitor(enabled=True, enable_ledger=True)
        monitor.collect_issues = lambda: [self._issue(monitor)]
        result = monitor.run_cycle()
        self.assertEqual(len(self.runner.ledger_rows), 1)
        self.assertEqual(len(self.runner.send_calls()), 1)
        events = self.state_dir.joinpath("events.jsonl").read_text()
        self.assertIn("error_ledger_style_failed_local_only", events)

    def test_duplicate_incident_rows_prefer_the_human_handled_row(self):
        incident_id = "1234567890abcdef12345678"
        first = [incident_id, *([""] * 16)]
        first[13] = "待处理"
        second = [incident_id, *([""] * 16)]
        second[12] = "李四"
        second[13] = "已处理"
        self.runner.ledger_rows = [first, [""] * 17, second]
        monitor = self._monitor(enabled=True, enable_ledger=True)
        rows, mapping = monitor._read_error_ledger()
        self.assertEqual(mapping[incident_id], 4)
        self.assertEqual(rows[mapping[incident_id] - 2][12], "李四")

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

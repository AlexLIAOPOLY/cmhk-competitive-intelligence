from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import daily_crawl_and_write
import crawl_run_registry
import scheduler


class FeishuCliEnvironmentTests(unittest.TestCase):
    def test_run_cmd_always_disables_proxy(self) -> None:
        completed = subprocess.CompletedProcess(["lark-cli"], 0, stdout="{}", stderr="")
        with (
            mock.patch.dict(
                daily_crawl_and_write.os.environ,
                {
                    "HTTP_PROXY": "http://127.0.0.1:7897",
                    "HTTPS_PROXY": "http://127.0.0.1:7897",
                },
            ),
            mock.patch.object(daily_crawl_and_write.subprocess, "run", return_value=completed) as run,
        ):
            daily_crawl_and_write.run_cmd(["lark-cli", "auth", "status"])

        command_env = run.call_args.kwargs["env"]
        self.assertEqual(command_env["LARK_CLI_NO_PROXY"], "1")
        self.assertNotIn("HTTP_PROXY", command_env)
        self.assertNotIn("HTTPS_PROXY", command_env)


class CrawlRunReconciliationTests(unittest.TestCase):
    def test_live_external_scheduler_is_not_marked_interrupted(self) -> None:
        record = {
            "crawl_run_id": "crawl-live-external",
            "run_status": "running",
            "backend_pid": 12345,
            "worker_pid": 0,
        }
        with (
            mock.patch.object(crawl_run_registry, "load_index", return_value=[record]),
            mock.patch.object(
                crawl_run_registry,
                "_pid_alive",
                side_effect=lambda pid: pid == 12345,
            ),
            mock.patch.object(
                crawl_run_registry,
                "mark_crawl_run_interrupted",
            ) as mark_interrupted,
        ):
            updated = crawl_run_registry.reconcile_interrupted_crawl_runs()

        self.assertEqual(updated, [])
        mark_interrupted.assert_not_called()

    def test_run_cmd_retries_eof_without_enabling_proxy(self) -> None:
        failed = subprocess.CompletedProcess(
            ["lark-cli"],
            1,
            stdout='{"ok":false,"error":{"message":"API call failed: EOF"}}',
            stderr="",
        )
        succeeded = subprocess.CompletedProcess(["lark-cli"], 0, stdout='{"ok":true}', stderr="")
        with (
            mock.patch.object(daily_crawl_and_write.subprocess, "run", side_effect=[failed, succeeded]) as run,
            mock.patch.object(daily_crawl_and_write.time, "sleep"),
        ):
            output = daily_crawl_and_write.run_cmd(["lark-cli", "sheets", "+read"])

        self.assertEqual(json.loads(output), {"ok": True})
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertEqual(call.kwargs["env"]["LARK_CLI_NO_PROXY"], "1")


class ScheduledAgentAuditTests(unittest.TestCase):
    def test_agent_success_is_not_rejected_when_feishu_log_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "run.jsonl"
            log_path.write_text("", encoding="utf-8")
            proc = subprocess.CompletedProcess(
                ["python"],
                0,
                stdout='AGENT_TRACE={"run_id":"agent-123"}\n',
                stderr="",
            )
            summary = {"agent_run_id": "agent-123", "tasks": 3}
            with (
                mock.patch.object(scheduler.subprocess, "run", return_value=proc),
                mock.patch.object(scheduler, "_validated_curation_summary", return_value=(summary, [])),
                mock.patch.object(scheduler, "heartbeat_crawl_run"),
            ):
                ok, code, curation, trace_sync, error = scheduler._run_scheduled_agent_audit(
                    "crawl-123",
                    log_path,
                    log_sheet_id="",
                )

        self.assertTrue(ok)
        self.assertEqual(code, 0)
        self.assertEqual(curation, summary)
        self.assertTrue(trace_sync["skipped"])
        self.assertEqual(error, "")

    def test_feishu_sync_failure_does_not_skip_agent_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "run.jsonl"
            crawl = subprocess.CompletedProcess(["crawl"], 0, stdout="crawl ok\n", stderr="")
            sync = subprocess.CompletedProcess(["sync"], 1, stdout="", stderr="API call failed: EOF\n")
            curation = {"agent_run_id": "agent-after-sync-failure", "tasks": 4}
            with (
                mock.patch.object(scheduler, "save_state"),
                mock.patch.object(scheduler, "_write_pending_run"),
                mock.patch.object(scheduler, "_clear_pending_run"),
                mock.patch.object(
                    scheduler,
                    "start_crawl_run",
                    return_value={
                        "crawl_run_id": "crawl-sync-failure",
                        "stream_log_path": str(log_path),
                    },
                ),
                mock.patch.object(scheduler, "append_crawl_run_event"),
                mock.patch.object(scheduler, "heartbeat_crawl_run"),
                mock.patch.object(scheduler.subprocess, "run", side_effect=[crawl, sync]),
                mock.patch.object(
                    scheduler,
                    "_run_scheduled_agent_audit",
                    return_value=(True, 0, curation, {"skipped": True}, ""),
                ) as audit,
                mock.patch.object(scheduler, "register_crawl_run") as register,
            ):
                ok = scheduler.run_due_rows([3], {})

        self.assertFalse(ok)
        audit.assert_called_once_with(
            "crawl-sync-failure",
            log_path,
            log_sheet_id="",
        )
        self.assertEqual(register.call_args.kwargs["failure_stage"], "feishu_sync")
        self.assertEqual(register.call_args.kwargs["curation_summary"], curation)
        self.assertIn("Agent 审核已完整执行", register.call_args.kwargs["progress_detail"])

    def test_successful_scheduled_run_captures_news_bridge_before_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "run.jsonl"
            log_path.write_text("", encoding="utf-8")
            crawl = subprocess.CompletedProcess(["crawl"], 0, stdout="crawl ok\n", stderr="")
            sync = subprocess.CompletedProcess(
                ["sync"],
                0,
                stdout='{"log_sheet_id":"sheet-1"}',
                stderr="",
            )
            curation = {"agent_run_id": "agent-success", "tasks": 4}
            bridge = {
                "crawl_run_id": "crawl-success",
                "bootstrap": False,
                "page_count": 12,
                "signal_count": 2,
            }
            with (
                mock.patch.object(scheduler, "save_state"),
                mock.patch.object(scheduler, "_write_pending_run"),
                mock.patch.object(scheduler, "_clear_pending_run"),
                mock.patch.object(
                    scheduler,
                    "start_crawl_run",
                    return_value={
                        "crawl_run_id": "crawl-success",
                        "stream_log_path": str(log_path),
                    },
                ),
                mock.patch.object(scheduler, "append_crawl_run_event") as append,
                mock.patch.object(scheduler, "heartbeat_crawl_run"),
                mock.patch.object(scheduler.subprocess, "run", side_effect=[crawl, sync]),
                mock.patch.object(
                    scheduler,
                    "_run_scheduled_agent_audit",
                    return_value=(True, 0, curation, {"ok": True}, ""),
                ),
                mock.patch.object(
                    scheduler,
                    "capture_completed_crawl",
                    return_value=bridge,
                ) as capture,
                mock.patch.object(
                    scheduler,
                    "read_live_schedule",
                    return_value=[{"row": 3, "frequency": "每天 03:00"}],
                ),
                mock.patch.object(scheduler, "register_crawl_run") as register,
            ):
                state = {}
                ok = scheduler.run_due_rows([3], state)

        self.assertTrue(ok)
        self.assertIn("3", state["last_completed"])
        capture.assert_called_once()
        self.assertEqual(capture.call_args.args[:2], ("crawl-success", [3]))
        self.assertEqual(
            register.call_args.kwargs["curation_summary"]["news_bridge"],
            bridge,
        )
        self.assertTrue(
            any(
                call.args[1].get("type") == "news_bridge"
                and call.args[1].get("signalCount") == 2
                for call in append.call_args_list
            )
        )

    def test_interrupted_sync_completed_run_is_recovered_from_archived_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            relative = Path("agent_knowledge/crawl_run_logs/runs/recover.jsonl")
            log_path = root / relative
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                '{"log_sheet_id": "sheet-recover"}\n'
                '{"type":"monitor","detail":"网页抓取和飞书同步已完成，正在执行完整 Agent 审核流程。"}\n',
                encoding="utf-8",
            )
            record = {
                "crawl_run_id": "crawl-recover",
                "trigger": "定时爬虫",
                "scope": "定时指定行（第3行、第4行）",
                "run_status": "failed",
                "phase": "已中断",
                "interrupted": True,
                "started_at_hkt": "2026-07-29T15:19:27+08:00",
                "local_files": {"stream_log": str(relative)},
            }
            with (
                mock.patch.object(scheduler, "ROOT", root),
                mock.patch.object(
                    scheduler,
                    "PENDING_RUN_PATH",
                    root / "scheduler_pending_run.json",
                ),
                mock.patch.object(
                    scheduler,
                    "load_crawl_run_index",
                    return_value=[record],
                ),
            ):
                recovered = scheduler._recover_interrupted_pending_run()

        self.assertEqual(recovered["stage"], "sync_completed")
        self.assertEqual(recovered["rows"], [3, 4])
        self.assertEqual(recovered["log_sheet_id"], "sheet-recover")

    def test_resume_from_sync_checkpoint_skips_web_crawl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "resume.jsonl"
            log_path.write_text("", encoding="utf-8")
            pending = {
                "stage": "sync_completed",
                "crawl_run_id": "crawl-resume",
                "rows": [3, 4],
                "scope": "定时指定行（第3行、第4行）",
                "started_at_hkt": "2026-07-29T15:19:27+08:00",
                "stream_log_path": str(log_path),
                "log_sheet_id": "sheet-resume",
                "sync_return_code": 0,
            }
            state = {
                "attempts": {
                    "3": "2026-07-29T15:19:27+08:00",
                    "4": "2026-07-29T15:19:27+08:00",
                }
            }
            with (
                mock.patch.object(scheduler, "_write_pending_run"),
                mock.patch.object(scheduler, "_clear_pending_run") as clear_pending,
                mock.patch.object(scheduler, "resume_crawl_run"),
                mock.patch.object(scheduler, "append_crawl_run_event"),
                mock.patch.object(scheduler, "heartbeat_crawl_run"),
                mock.patch.object(
                    scheduler,
                    "_run_scheduled_agent_audit",
                    return_value=(
                        True,
                        0,
                        {"agent_run_id": "agent-resume"},
                        {"ok": True},
                        "",
                    ),
                ) as audit,
                mock.patch.object(
                    scheduler,
                    "capture_completed_crawl",
                    return_value={"page_count": 10, "signal_count": 2},
                ) as bridge,
                mock.patch.object(
                    scheduler,
                    "read_live_schedule",
                    return_value=[
                        {"row": 3, "frequency": "每天 03:00"},
                        {"row": 4, "frequency": "每天 03:00"},
                    ],
                ),
                mock.patch.object(scheduler, "save_state"),
                mock.patch.object(scheduler, "register_crawl_run") as register,
                mock.patch.object(scheduler.subprocess, "run") as subprocess_run,
            ):
                ok = scheduler.resume_pending_run(pending, state)

        self.assertTrue(ok)
        audit.assert_called_once_with(
            "crawl-resume",
            log_path,
            log_sheet_id="sheet-resume",
        )
        bridge.assert_called_once()
        subprocess_run.assert_not_called()
        self.assertEqual(state["attempts"], {})
        self.assertIn("3", state["last_completed"])
        self.assertIn("4", state["last_completed"])
        self.assertEqual(register.call_args.kwargs["crawl_return_code"], 0)
        clear_pending.assert_called_once()

    def test_pending_attempt_does_not_advance_schedule_from_partial_row_output(self) -> None:
        now = scheduler.datetime(2026, 7, 29, 16, 0, tzinfo=scheduler.HKT)
        attempt = now - scheduler.timedelta(hours=1)
        previous_success = scheduler.datetime(2026, 7, 28, 3, 0, tzinfo=scheduler.HKT)
        with (
            mock.patch.object(
                scheduler,
                "read_live_schedule",
                return_value=[{"row": 3, "frequency": "每天 03:00"}],
            ),
            mock.patch.object(
                scheduler,
                "last_success",
                return_value=previous_success,
            ) as last_success,
        ):
            due, audit = scheduler.due_rows(
                now,
                {"attempts": {"3": attempt.isoformat(timespec="seconds")}},
            )

        self.assertEqual(due, [3])
        self.assertEqual(audit[0]["status"], "due")
        last_success.assert_called_once_with(3, before=attempt)

    def test_completed_ledger_prevents_immediate_repeat_with_stale_result_time(self) -> None:
        now = scheduler.datetime(2026, 7, 30, 11, 7, tzinfo=scheduler.HKT)
        stale_result = scheduler.datetime(2026, 7, 29, 3, 0, tzinfo=scheduler.HKT)
        completed = scheduler.datetime(2026, 7, 30, 11, 6, tzinfo=scheduler.HKT)
        with (
            mock.patch.object(
                scheduler,
                "read_live_schedule",
                return_value=[{"row": 3, "frequency": "每天 03:00"}],
            ),
            mock.patch.object(
                scheduler,
                "last_success",
                return_value=stale_result,
            ),
        ):
            due, audit = scheduler.due_rows(
                now,
                {
                    "attempts": {},
                    "last_completed": {
                        "3": completed.isoformat(timespec="seconds"),
                    },
                },
            )

        self.assertEqual(due, [])
        self.assertEqual(audit[0]["status"], "waiting")
        self.assertEqual(
            audit[0]["last_success_hkt"],
            completed.isoformat(timespec="seconds"),
        )

    def test_completed_ledger_is_restored_from_successful_run_archive(self) -> None:
        state = {"last_completed": {}}
        with mock.patch.object(
            scheduler,
            "load_crawl_run_index",
            return_value=[
                {
                    "trigger": "定时爬虫",
                    "run_status": "completed",
                    "scope": "定时指定行（第2行、第3行）",
                    "completed_at_hkt": "2026-07-30T11:06:15+08:00",
                },
                {
                    "trigger": "战略新闻定时爬虫",
                    "run_status": "completed",
                    "scope": "晨间扫描（2026-07-30@09:00）",
                    "completed_at_hkt": "2026-07-30T10:56:36+08:00",
                },
            ],
        ):
            scheduler._restore_completed_rows_from_run_archive(state)

        self.assertEqual(
            state["last_completed"],
            {
                "2": "2026-07-30T11:06:15+08:00",
                "3": "2026-07-30T11:06:15+08:00",
            },
        )

    def test_interrupted_pending_resume_bypasses_retry_backoff(self) -> None:
        pending = {
            "stage": "sync_completed",
            "crawl_run_id": "crawl-restart",
            "last_attempt_at_hkt": scheduler.datetime.now(scheduler.HKT).isoformat(
                timespec="seconds"
            ),
        }
        with (
            mock.patch.object(scheduler, "load_state", return_value={}),
            mock.patch.object(scheduler, "_load_pending_run", return_value=pending),
            mock.patch.object(
                scheduler,
                "_pending_run_was_interrupted",
                return_value=True,
            ),
            mock.patch.object(scheduler, "crawl_process_running", return_value=False),
            mock.patch.object(
                scheduler,
                "agent_audit_process_running",
                return_value=False,
            ),
            mock.patch.object(
                scheduler,
                "resume_pending_run",
                return_value=True,
            ) as resume,
        ):
            result = scheduler.run_cycle()

        self.assertTrue(result["resumed"])
        resume.assert_called_once_with(pending, {})


class TaskLogScrollTests(unittest.TestCase):
    def test_running_task_log_scroll_waits_for_layout_and_stays_at_bottom(self) -> None:
        app = (scheduler.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        helper_start = app.index("function scrollTaskLogToBottom")
        helper_end = app.index("function stopCrawlLogPolling", helper_start)
        helper = app[helper_start:helper_end]
        loader_start = app.index("async function loadCrawlRunLog")
        loader_end = app.index("async function loadCrawlRuns", loader_start)
        loader = app[loader_start:loader_end]

        self.assertIn('els.logBox.querySelectorAll(".task-run-process > pre")', helper)
        self.assertIn("processLog.scrollTop = processLog.scrollHeight", helper)
        self.assertIn("els.logBox.scrollTop = els.logBox.scrollHeight", helper)
        self.assertGreaterEqual(helper.count("requestAnimationFrame"), 2)
        running_branch = loader[loader.index('if (task.run_status === "running")'):]
        running_branch = running_branch[:running_branch.index("} else {")]
        self.assertIn("scrollTaskLogToBottom();", running_branch)
        self.assertNotIn("wasNearBottom", running_branch)


if __name__ == "__main__":
    unittest.main()

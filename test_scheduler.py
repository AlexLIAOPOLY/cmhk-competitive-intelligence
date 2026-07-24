from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import daily_crawl_and_write
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

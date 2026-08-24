from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import web_app


class _FakeTimer:
    created: list["_FakeTimer"] = []

    def __init__(self, interval, function, args=()):
        self.interval = interval
        self.function = function
        self.args = args
        self.daemon = False
        self.name = ""
        self.started = False
        self.__class__.created.append(self)

    def start(self):
        self.started = True


class TaskAutoRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeTimer.created.clear()

    def test_interrupted_report_and_audio_are_scheduled_once(self) -> None:
        tasks = [
            {
                "task_id": "task:weekly-1",
                "task_run_id": "weekly-1",
                "kind": "weekly-report",
                "scope": "战略部每周周报",
                "retry_count": 0,
            },
            {
                "task_id": "task:audio-1",
                "task_run_id": "audio-1",
                "kind": "audio-generation",
                "target_path": "/tmp/report.docx",
                "retry_count": 1,
            },
            {
                "task_id": "task:weekly-older",
                "task_run_id": "weekly-older",
                "kind": "weekly-report",
                "scope": "战略部每周周报",
                "retry_count": 0,
            },
        ]
        with mock.patch.object(web_app.threading, "Timer", _FakeTimer):
            scheduled = web_app.schedule_interrupted_general_task_retries(tasks)

        self.assertEqual(scheduled, ["task:weekly-1", "task:audio-1"])
        self.assertEqual(len(_FakeTimer.created), 2)
        self.assertTrue(all(timer.started and timer.daemon for timer in _FakeTimer.created))

    def test_old_interruption_is_recovered_once_after_upgrade(self) -> None:
        rows = [
            {
                "task_id": "task:old",
                "run_status": "failed",
                "interrupted": True,
                "recovery_disposition": "",
            },
            {
                "task_id": "task:already-scheduled",
                "run_status": "failed",
                "interrupted": True,
                "recovery_disposition": "scheduled",
            },
        ]
        with mock.patch.object(web_app, "_task_read_local_index", return_value=rows):
            pending = web_app.pending_interrupted_general_task_retries()
        self.assertEqual([task["task_id"] for task in pending], ["task:old"])

    def test_retry_limit_prevents_restart_loop(self) -> None:
        task = {
            "task_id": "task:weekly-max",
            "task_run_id": "weekly-max",
            "kind": "weekly-report",
            "retry_count": web_app.GENERAL_TASK_MAX_AUTO_RETRIES,
        }
        with (
            mock.patch.object(web_app.threading, "Timer", _FakeTimer),
            mock.patch.object(web_app, "append_general_task_log") as append_log,
        ):
            scheduled = web_app.schedule_interrupted_general_task_retries([task])

        self.assertEqual(scheduled, [])
        self.assertEqual(_FakeTimer.created, [])
        self.assertIn("最大", append_log.call_args.args[1])

    def test_recovered_audio_keeps_target_for_another_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = root / "weekly.docx"
            report.write_bytes(b"docx")
            original = {
                "task_id": "task:audio-original",
                "kind": "audio-generation",
                "title": "生成音频摘要",
                "scope": report.name,
                "script": "tts_service.py",
                "target_path": str(report),
                "retry_count": 1,
            }
            with (
                mock.patch.object(web_app, "ROOT", root),
                mock.patch.object(
                    web_app,
                    "start_general_task_run",
                    return_value={"task_id": "task:audio-retry"},
                ) as start,
                mock.patch.object(web_app, "append_general_task_log"),
                mock.patch.object(web_app, "heartbeat_general_task_run"),
                mock.patch.object(web_app, "finish_general_task_run") as finish,
                mock.patch.object(
                    web_app,
                    "synthesize_report_audio",
                    return_value={"ok": True, "audio": {"name": "weekly.mp3"}},
                ),
            ):
                web_app._run_recovered_general_task(original)

        self.assertEqual(start.call_args.kwargs["retry_count"], 2)
        self.assertEqual(start.call_args.kwargs["target_path"], str(report))
        finish.assert_called_once_with(
            "task:audio-retry", True, "自动恢复成功：weekly.mp3"
        )


if __name__ == "__main__":
    unittest.main()

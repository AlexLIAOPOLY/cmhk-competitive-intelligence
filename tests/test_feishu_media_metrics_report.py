import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "feishu_media_metrics_report.py"
SPEC = importlib.util.spec_from_file_location("feishu_media_metrics_report", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FeishuMediaMetricsReportTests(unittest.TestCase):
    def test_file_statistics_can_use_server_bot_profile(self):
        result = MODULE.CommandResult(
            payload={"ok": True, "data": {"statistics": {"uv": 8, "pv": 12}}},
            stderr="",
        )
        with patch.dict(MODULE.os.environ, {"CMHK_FEISHU_DRIVE_IDENTITY": "bot"}), patch.object(
            MODULE, "run_lark", return_value=result
        ) as run:
            stats = MODULE.get_file_statistics("file_test", "file", profile="server-bot")
        self.assertEqual(stats["uv"], 8)
        self.assertIn("bot", run.call_args.args[0])
        self.assertEqual(run.call_args.kwargs["profile"], "server-bot")

    def test_file_statistics_preserves_local_default_user_profile(self):
        result = MODULE.CommandResult(payload={"ok": True, "data": {"statistics": {}}}, stderr="")
        with patch.dict(MODULE.os.environ, {}, clear=True), patch.object(
            MODULE, "run_lark", return_value=result
        ) as run:
            MODULE.get_file_statistics("file_test", "file", profile="bot-only-profile")
        self.assertIn("user", run.call_args.args[0])
        self.assertIsNone(run.call_args.kwargs["profile"])

    def test_run_lark_retries_rate_limit_with_exponential_backoff(self):
        rate_limited = subprocess.CompletedProcess(
            ["lark-cli"],
            1,
            "",
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "subtype": "rate_limit",
                        "code": 429,
                        "message": "TAT endpoint rate limited (HTTP 429)",
                        "retryable": True,
                    },
                }
            ),
        )
        succeeded = subprocess.CompletedProcess(
            ["lark-cli"],
            0,
            json.dumps({"ok": True, "data": {"message_id": "om_recovered"}}),
            "",
        )
        with patch.object(MODULE.subprocess, "run", side_effect=[rate_limited, succeeded]) as runner, patch.object(
            MODULE.random, "uniform", return_value=0.0
        ), patch.object(MODULE.time, "sleep") as sleeper:
            result = MODULE.run_lark(["im", "+messages-mget", "--message-ids", "om_test"])

        self.assertTrue(result.payload["ok"])
        self.assertEqual(runner.call_count, 2)
        sleeper.assert_called_once_with(1.0)

    def test_run_lark_does_not_retry_non_rate_limit_error(self):
        failed = subprocess.CompletedProcess(
            ["lark-cli"],
            1,
            "",
            json.dumps({"ok": False, "error": {"code": 403, "message": "forbidden"}}),
        )
        with patch.object(MODULE.subprocess, "run", return_value=failed) as runner, patch.object(
            MODULE.time, "sleep"
        ) as sleeper:
            with self.assertRaises(MODULE.ReportError):
                MODULE.run_lark(["im", "+messages-mget", "--message-ids", "om_test"])

        runner.assert_called_once()
        sleeper.assert_not_called()

    def test_render_exact_table(self):
        rows = [
            {
                "title": "引子篇｜系列正式启动",
                "published_at": "2026-08-05 09:37",
                "messages": [
                    {"label": "图文", "read_count": 1595},
                    {"label": "视频", "read_count": 1599},
                ],
                "drive": None,
                "primary_read": 1595,
            },
            {
                "title": "AI科普｜人工智能為甚麼能聽懂我們說話？",
                "published_at": "2026-08-06 17:54",
                "messages": [{"label": "", "read_count": 1586}],
                "drive": {"uv": 81},
                "primary_read": 1586,
            },
        ]
        table = MODULE.render_markdown(rows, 1870)
        self.assertIn("图文1,595人（85.3%）；视频1,599人（85.5%）", table)
        self.assertIn("| 2026-08-05 09:37 |", table)
        self.assertIn("81人（4.33%）", table)
        self.assertIn("5.11%", table)
        self.assertEqual(table.count("无法统计"), 2)

    def test_due_slots_is_idempotent(self):
        now = MODULE.datetime(2026, 8, 11, 17, 5, tzinfo=MODULE.HKT)
        state = {"sent_slots": {"20260811-1000": "om_old"}}
        due = MODULE.due_slots(now, state)
        self.assertEqual([slot for slot, _ in due], ["20260811-1700"])

    def test_preview_rejects_group(self):
        with self.assertRaises(MODULE.ReportError):
            MODULE.require_preview_chat({"chat_mode": "group", "chat_status": "normal"})

    def test_discovers_series_titles_without_code_change(self):
        discovery = {"title_markers": ["科普系列"], "include_series_launch": True}
        exact = "【第三期｜量子科普系列】量子通信到底是什么？"
        compact = {"content": '<card title="【第三期｜量子科普系列】量子通信到底是什么？">'}
        self.assertEqual(MODULE.compact_card_title(compact), exact)
        self.assertTrue(MODULE.tracked_publication_title(exact, discovery))
        self.assertEqual(MODULE.publication_display_title(exact), "量子科普｜量子通信到底是什么？")
        self.assertFalse(MODULE.tracked_publication_title("普通部门通知", discovery))

    def test_extracts_drive_token_from_card(self):
        payload = {"card_link": {"url": "https://cmhk-try.feishu.cn/file/AbC123_token"}}
        self.assertEqual(MODULE.drive_token_from_card(payload), "AbC123_token")

    def test_auto_discovery_appends_future_publication_to_state(self):
        config = {
            "source_chat": {"chat_id": "oc_cmhk"},
            "sender": {"profile": "fixed", "app_id": "cli_fixed"},
            "auto_discovery": {"enabled": True, "start": "2026-08-01", "title_markers": ["科普系列"]},
            "publications": [],
        }
        history = [
            {
                "message_id": "om_future",
                "chat_id": "oc_cmhk",
                "msg_type": "interactive",
                "message_position": "10",
                "deleted": False,
                "sender": {"id": "cli_fixed"},
                "content": '<card title="【第三期｜AI科普系列】AI到底是什么？">',
            }
        ]
        state = {}
        with patch.object(MODULE, "list_chat_messages", return_value=history), patch.object(
            MODULE,
            "get_card_payload",
            return_value={"card_link": {"url": "https://cmhk-try.feishu.cn/file/Future123"}},
        ):
            publications = MODULE.discover_publications(config, state)
        self.assertEqual(publications[0]["title"], "AI科普｜AI到底是什么？")
        self.assertEqual(publications[0]["drive_file_token"], "Future123")
        self.assertEqual(state["auto_discovery"]["tracked_publications"], 1)
        self.assertEqual(len(state["discovered_publications"]), 1)

    def test_render_landscape_image(self):
        rows = [
            {
                "title": "6G科普｜6G到底是什麼？",
                "published_at": "2026-08-11 11:58",
                "messages": [{"label": "", "read_count": 1374}],
                "drive": {"uv": 158},
                "primary_read": 1374,
            }
        ]
        output = Path("var/feishu_media_metrics/test_report.png")
        try:
            MODULE.render_image(rows, 1870, output)
            with MODULE.Image.open(output) as image:
                self.assertEqual(image.size, (1920, 780))
                self.assertGreater(image.width, image.height * 2)
        finally:
            output.unlink(missing_ok=True)

    def test_render_grows_for_all_historical_rows(self):
        rows = [
            {
                "title": f"AI科普｜第{i}期",
                "published_at": "2026-08-11 11:58",
                "messages": [{"label": "", "read_count": 100}],
                "drive": {"uv": 10},
                "primary_read": 100,
            }
            for i in range(6)
        ]
        output = Path("var/feishu_media_metrics/test_history_report.png")
        try:
            MODULE.render_image(rows, 1870, output)
            with MODULE.Image.open(output) as image:
                self.assertEqual(image.width, 1920)
                self.assertGreater(image.height, 780)
        finally:
            output.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()

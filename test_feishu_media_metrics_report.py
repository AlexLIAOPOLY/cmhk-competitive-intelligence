import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parent / "scripts" / "feishu_media_metrics_report.py"
SPEC = importlib.util.spec_from_file_location("feishu_media_metrics_report", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FeishuMediaMetricsReportTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

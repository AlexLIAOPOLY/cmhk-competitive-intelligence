from __future__ import annotations

import io
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from pypdf import PdfReader

from cmhk.reporting.operational_pdf import (
    build_report_model,
    generate_operational_report_pdf,
    renderable_text,
    report_window,
)


HKT = ZoneInfo("Asia/Hong_Kong")
NOW = datetime(2026, 8, 23, 16, 30, tzinfo=HKT)


def alert(day: int, *, status: str = "resolved", severity: str = "P2") -> dict:
    return {
        "occurred_at_hkt": f"2026-08-{day:02d}T10:00:00+08:00",
        "incident_status": status,
        "severity": severity,
        "kind": "web-service",
        "title": "中文报警：接口超时",
        "scope": "正式运行环境",
        "error": "检测到超时，成功率下降至 98.7%。",
        "auto_repaired_at_hkt": f"2026-08-{day:02d}T10:05:00+08:00",
    }


def task(day: int, *, status: str = "completed") -> dict:
    return {
        "started_at_hkt": f"2026-08-{day:02d}T11:00:00+08:00",
        "run_status": status,
        "kind": "strategic-news",
        "kind_label": "战略新闻任务",
        "title": "新闻抓取与审核",
        "scope": "香港竞对",
        "phase": "发布校验",
        "duration_ms": 12500,
        "lines": 188,
        "status_detail": "任务完成并通过归档及回读门禁。",
    }


class OperationalReportPdfTests(unittest.TestCase):
    def test_calendar_windows_use_hong_kong_time(self):
        self.assertEqual(report_window("daily", NOW)[0].isoformat(), "2026-08-23T00:00:00+08:00")
        self.assertEqual(report_window("weekly", NOW)[0].isoformat(), "2026-08-17T00:00:00+08:00")
        self.assertEqual(report_window("monthly", NOW)[0].isoformat(), "2026-08-01T00:00:00+08:00")
        self.assertEqual(report_window("annual", NOW)[0].isoformat(), "2026-01-01T00:00:00+08:00")

    def test_alert_statistics_are_real_and_detailed(self):
        rows = [alert(23, status="open", severity="P1"), alert(22), {**alert(21, severity="P3"), "handler_name": "廖望"}]
        model = build_report_model("alert", "monthly", rows, now=NOW)
        self.assertEqual(model["total"], 3)
        self.assertEqual(model["statuses"]["待处理"], 1)
        self.assertEqual(model["statuses"]["自动恢复"], 1)
        self.assertEqual(model["statuses"]["人工修复"], 1)
        self.assertEqual(model["severities"]["P1"], 1)
        self.assertIn(("恢复率", "66.7%", "已恢复/总数"), model["kpis"])

    def test_log_statistics_include_success_and_latency(self):
        rows = [task(23), task(22, status="failed"), {**task(21), "duration_ms": 37500}]
        model = build_report_model("log", "monthly", rows, now=NOW)
        self.assertEqual(model["total"], 3)
        self.assertIn(("成功率", "66.7%", "完成/总数"), model["kpis"])
        self.assertIn(("P95耗时", "37.5s", "第95百分位"), model["kpis"])

    def test_all_periods_generate_searchable_chinese_pdf_with_metadata(self):
        rows = [alert(23), alert(18, status="open", severity="P1"), alert(2, severity="P3")]
        for period in ("daily", "weekly", "monthly", "annual"):
            with self.subTest(period=period):
                body, _model = generate_operational_report_pdf("alert", period, rows, now=NOW)
                self.assertTrue(body.startswith(b"%PDF-"))
                reader = PdfReader(io.BytesIO(body))
                text = "\n".join(page.extract_text() or "" for page in reader.pages)
                self.assertIn("故障报警运营报告", text)
                self.assertIn("管理摘要", text)
                self.assertIn("统计分析", text)
                self.assertIn("明细记录", text)
                labels = {"daily": "日报", "weekly": "周报", "monthly": "月报", "annual": "年报"}
                self.assertEqual(reader.metadata.title, f"故障报警运营报告 - {labels[period]}")
                self.assertTrue(all((page.extract_text() or "").strip() for page in reader.pages))

    def test_unsupported_glyph_is_normalized_before_render(self):
        self.assertEqual(renderable_text("中文\U0001f4a5"), "中文?")


if __name__ == "__main__":
    unittest.main()

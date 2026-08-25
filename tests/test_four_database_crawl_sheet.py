from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from cmhk.integrations import four_database_crawl_sheet as sheet


class FourDatabaseCrawlSheetTests(unittest.TestCase):
    def test_discovery_rows_keep_queries_results_and_handoff(self) -> None:
        rows = sheet.discovery_rows(
            {
                "run_id": "source-1", "generated_at_hkt": "2026-08-25T01:00:00+08:00",
                "handoff_for_date": "2026-08-25", "query_count": 1, "search_result_count": 1,
                "signal_count": 1, "previous_day_reference_count": 0,
                "signals": [{"domain": "cloud", "entity": "AWS", "title": "AWS results", "news_url": "https://news.example/a", "official_followup_urls": ["https://amazon.com/ir"]}],
            },
            plans=[{"module": "四库资料/cloud", "query": "AWS earnings", "fallback_query": "AWS revenue"}],
            search_items=[{"title": "AWS results", "url": "https://news.example/a", "summary": "lead"}],
        )
        self.assertEqual([row["动作"] for row in rows], ["运行汇总", "搜索查询", "搜索结果", "四库线索"])
        self.assertEqual(rows[-1]["入库决定"], "")
        self.assertIn("amazon.com/ir", rows[-1]["交接／父任务"])

    def test_pipeline_rows_keep_each_url_and_rejection_reason(self) -> None:
        rows = sheet.pipeline_rows(
            {"task_run_id": "task-1", "agent_run_id": "agent-1", "ok": True, "completed_at_hkt": "2026-08-25T03:10:00+08:00"},
            recrawl={"summary": {"official_urls": 1, "retrieved": 1, "failed": 0}, "source_crawl": [{"url": "https://example.com/ir", "domains": ["cloud"], "ok": True, "status": 200, "content_changed": True, "content_fingerprint": "abc"}]},
            candidates=[{"id": "f1", "row_ref": "row_50", "company": "AWS", "metric": "云收入", "value": "100", "status": "ok", "decision": "quality_rejected", "reasons": ["缺少云业务上下文"], "sources": ["https://example.com/ir"], "evidence_hash": "xyz"}],
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1]["内容变化"], "是")
        self.assertEqual(rows[2]["入库决定"], "quality_rejected")
        self.assertIn("缺少云业务上下文", rows[2]["原因／错误"])

    def test_append_uses_next_real_data_row_not_physical_sheet_size(self) -> None:
        calls = []

        def fake_run(args, *, input_text=""):
            calls.append((args, input_text))
            if "+workbook-info" in args:
                return {"ok": True, "data": {"sheets": [{"sheet_name": sheet.SHEET_TITLE, "sheet_id": "s1"}]}}
            if "+csv-get" in args:
                return {"ok": True, "data": {"current_region": "A1:Q671"}}
            return {"ok": True, "data": {}}

        with TemporaryDirectory() as temp_dir, \
             mock.patch.object(sheet, "STATE_PATH", Path(temp_dir) / "state.json"), \
             mock.patch.object(sheet, "LOCK_PATH", Path(temp_dir) / "write.lock"), \
             mock.patch.object(sheet, "_run", side_effect=fake_run):
            result = sheet.append_rows([sheet._row(run_id="r1", stage="测试", action="真实事件", discriminator="1")])
        self.assertEqual(result["written"], 1)
        table_call = next((args, body) for args, body in calls if "+table-put" in args)
        payload = __import__("json").loads(table_call[1])
        self.assertEqual(payload["sheets"][0]["start_cell"], "A672")
        self.assertEqual(payload["sheets"][0]["mode"], "overwrite")
        self.assertFalse(payload["sheets"][0]["header"])


if __name__ == "__main__":
    unittest.main()

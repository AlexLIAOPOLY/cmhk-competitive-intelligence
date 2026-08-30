from __future__ import annotations

import unittest
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from cmhk.integrations import four_database_crawl_sheet as sheet


class FourDatabaseCrawlSheetTests(unittest.TestCase):
    def test_write_retries_sheet_revision_conflict(self) -> None:
        outcomes = [
            subprocess.CompletedProcess(
                [],
                1,
                stdout="",
                stderr='{"code":900015205,"message":"cs recommited, rev is 43469"}',
            ),
            subprocess.CompletedProcess([], 0, stdout='{"ok":true,"data":{}}', stderr=""),
        ]
        with mock.patch.object(sheet.subprocess, "run", side_effect=outcomes) as run, \
             mock.patch.object(sheet.time, "sleep"):
            payload = sheet._run(["sheets", "+table-put"], retry_safe=True)

        self.assertTrue(payload["ok"])
        self.assertEqual(run.call_count, 2)

    def test_live_read_retries_timeout_exception(self) -> None:
        outcomes = [
            subprocess.TimeoutExpired(["lark-cli"], 180),
            subprocess.CompletedProcess([], 0, stdout='{"ok":true,"data":{}}', stderr=""),
        ]
        with mock.patch.object(sheet.subprocess, "run", side_effect=outcomes) as run, \
             mock.patch.object(sheet.time, "sleep"):
            payload = sheet._run(["sheets", "+workbook-info"], retry_safe=True)

        self.assertTrue(payload["ok"])
        self.assertEqual(run.call_count, 2)

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
        row = sheet._row(run_id="r1", stage="测试", action="真实事件", discriminator="1")
        written = False

        def fake_run(args, *, input_text="", retry_safe=False):
            nonlocal written
            calls.append((args, input_text))
            if "+workbook-info" in args:
                return {"ok": True, "data": {"sheets": [{"sheet_name": sheet.SHEET_TITLE, "sheet_id": "s1"}]}}
            if "+table-put" in args:
                written = True
                return {"ok": True, "data": {}}
            if "+csv-get" in args:
                requested_range = args[args.index("--range") + 1]
                current_region = "A1:Q672" if written else "A1:Q671"
                annotated = ""
                if written and requested_range in {"B672:B672", "B2:B672"}:
                    annotated = f"[row=672] {row['事件ID']}"
                return {"ok": True, "data": {"annotated_csv": annotated, "current_region": current_region}}
            return {"ok": True, "data": {}}

        with TemporaryDirectory() as temp_dir, \
             mock.patch.object(sheet, "STATE_PATH", Path(temp_dir) / "state.json"), \
             mock.patch.object(sheet, "LOCK_PATH", Path(temp_dir) / "write.lock"), \
             mock.patch.object(sheet, "_run", side_effect=fake_run):
            result = sheet.append_rows([row])
        self.assertEqual(result["written"], 1)
        self.assertTrue(result["readback_verified"])
        self.assertEqual((result["row_start"], result["row_end"]), (672, 672))
        table_call = next((args, body) for args, body in calls if "+table-put" in args)
        payload = __import__("json").loads(table_call[1])
        self.assertEqual(payload["sheets"][0]["start_cell"], "A672")
        self.assertEqual(payload["sheets"][0]["mode"], "overwrite")
        self.assertFalse(payload["sheets"][0]["header"])

    def test_duplicate_events_require_current_live_readback(self) -> None:
        row = sheet._row(run_id="r2", stage="测试", action="重复保护", discriminator="1")
        calls = []

        def fake_run(args, *, input_text="", retry_safe=False):
            calls.append(args)
            if "+workbook-info" in args:
                return {"ok": True, "data": {"sheets": [{"sheet_name": sheet.SHEET_TITLE}]}}
            if "+csv-get" in args:
                requested_range = args[args.index("--range") + 1]
                annotated = f"[row=20] {row['事件ID']}" if requested_range == "B2:B20" else ""
                return {"ok": True, "data": {"annotated_csv": annotated, "current_region": "A1:Q20"}}
            raise AssertionError(f"unexpected write call: {args}")

        with TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            state_path.write_text(__import__("json").dumps({
                "event_ids": [row["事件ID"]], "last_readback_verified": True,
                "last_row_start": 20, "last_row_end": 20,
            }))
            with mock.patch.object(sheet, "STATE_PATH", state_path), \
                 mock.patch.object(sheet, "LOCK_PATH", Path(temp_dir) / "write.lock"), \
                 mock.patch.object(sheet, "_run", side_effect=fake_run):
                result = sheet.append_rows([row])
        self.assertTrue(any("+csv-get" in call for call in calls))
        self.assertFalse(any("+table-put" in call for call in calls))
        self.assertEqual(result["skipped"], 1)
        self.assertTrue(result["readback_verified"])
        self.assertEqual(result["readback_reason"], "live_full_event_id_readback")

    def test_event_id_changes_with_result_content_but_not_timestamp(self) -> None:
        first = sheet._row(
            run_id="r3", stage="03:00四库更新", action="运行汇总",
            result="completed_with_fallback", value="成功490；失败119",
            timestamp="2026-08-30T04:28:55+08:00",
        )
        corrected = sheet._row(
            run_id="r3", stage="03:00四库更新", action="运行汇总",
            result="成功", value="成功484；失败125",
            timestamp="2026-08-30T04:53:34+08:00",
        )
        same_content_later = sheet._row(
            run_id="r3", stage="03:00四库更新", action="运行汇总",
            result="成功", value="成功484；失败125",
            timestamp="2026-08-30T05:00:00+08:00",
        )

        self.assertNotEqual(first["事件ID"], corrected["事件ID"])
        self.assertEqual(corrected["事件ID"], same_content_later["事件ID"])


if __name__ == "__main__":
    unittest.main()

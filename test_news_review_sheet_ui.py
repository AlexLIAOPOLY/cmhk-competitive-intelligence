from __future__ import annotations

from contextlib import nullcontext
import unittest
from unittest import mock

import news_review_sheet
import web_app


def sheet_row(*values: str) -> list[str]:
    return [*values, *([""] * (len(news_review_sheet.HEADERS) - len(values)))]


class NewsReviewSheetModelTests(unittest.TestCase):
    def test_snapshot_keeps_live_sheet_rows_and_edit_contract(self) -> None:
        rows = [
            sheet_row(
                "待审核",
                "接受",
                "未同步",
                "2026-08-03",
                "香港本地",
                "竞对动态",
                "香港电讯推出自主研发 AI 平台",
                "平台汇聚全球 AI 资源。",
                "香港01",
                "2026-08-03",
                "https://example.com/news",
            )
        ]
        with (
            mock.patch.object(news_review_sheet, "_resolved_review_sheet_id", return_value="sheet-1"),
            mock.patch.object(news_review_sheet, "_read_rows", return_value=rows),
        ):
            payload = news_review_sheet.review_sheet_snapshot()

        self.assertEqual(payload["sheetId"], "sheet-1")
        self.assertEqual(payload["headers"], news_review_sheet.HEADERS)
        self.assertNotIn(2, payload["editableColumns"])
        self.assertEqual(payload["rows"][0]["rowNumber"], 2)
        self.assertEqual(payload["rows"][0]["values"][6], "香港电讯推出自主研发 AI 平台")

    def test_update_coalesces_adjacent_cells_and_requires_readback(self) -> None:
        before = sheet_row("待审核", "待审核", "未同步", "2026-08-03")
        after = sheet_row("接受", "接受", "已纳入", "2026-08-03")
        with (
            mock.patch.object(news_review_sheet, "_resolved_review_sheet_id", return_value="sheet-1"),
            mock.patch.object(news_review_sheet, "_review_process_lock", return_value=nullcontext(True)),
            mock.patch.object(news_review_sheet, "_read_rows", side_effect=[[before], [after]]),
            mock.patch.object(news_review_sheet, "_write") as write,
            mock.patch.object(news_review_sheet, "apply_reviews", return_value={"accepted_count": 1}),
        ):
            payload = news_review_sheet.update_review_sheet_cells(
                [
                    {"rowNumber": 2, "columnIndex": 0, "before": "待审核", "value": "接受"},
                    {"rowNumber": 2, "columnIndex": 1, "before": "待审核", "value": "接受"},
                ]
            )

        write.assert_called_once_with("sheet-1", "A2:B2", [["接受", "接受"]])
        self.assertTrue(payload["readbackVerified"])
        self.assertEqual(payload["changedCount"], 2)
        self.assertEqual(payload["rows"][0]["values"][2], "已纳入")

    def test_update_stops_on_stale_cell_instead_of_overwriting(self) -> None:
        rows = [sheet_row("接受", "待审核", "已纳入")]
        with (
            mock.patch.object(news_review_sheet, "_resolved_review_sheet_id", return_value="sheet-1"),
            mock.patch.object(news_review_sheet, "_review_process_lock", return_value=nullcontext(True)),
            mock.patch.object(news_review_sheet, "_read_rows", return_value=rows),
            mock.patch.object(news_review_sheet, "_write") as write,
        ):
            with self.assertRaisesRegex(RuntimeError, "其他用户修改"):
                news_review_sheet.update_review_sheet_cells(
                    [{"rowNumber": 2, "columnIndex": 0, "before": "待审核", "value": "不接受"}]
                )
        write.assert_not_called()

    def test_sync_status_column_is_not_user_editable(self) -> None:
        rows = [sheet_row("待审核", "待审核", "未同步")]
        with (
            mock.patch.object(news_review_sheet, "_resolved_review_sheet_id", return_value="sheet-1"),
            mock.patch.object(news_review_sheet, "_review_process_lock", return_value=nullcontext(True)),
            mock.patch.object(news_review_sheet, "_read_rows", return_value=rows),
        ):
            with self.assertRaisesRegex(ValueError, "不能手工修改"):
                news_review_sheet.update_review_sheet_cells(
                    [{"rowNumber": 2, "columnIndex": 2, "before": "未同步", "value": "已纳入"}]
                )


class NewsReviewSheetStaticUiTests(unittest.TestCase):
    def test_report_library_contains_real_sheet_workspace(self) -> None:
        html = (web_app.STATIC_DIR / "index.html").read_text(encoding="utf-8")
        script = (web_app.STATIC_DIR / "news-review-sheet.js").read_text(encoding="utf-8")
        css = (web_app.STATIC_DIR / "news-review-sheet.css").read_text(encoding="utf-8")

        self.assertIn('id="openNewsReviewSheetButton"', html)
        self.assertIn('id="newsReviewWorkspace"', html)
        self.assertIn('fetch("/api/news-review-sheet"', script)
        self.assertIn('fetch("/api/news-review-sheet/update"', script)
        self.assertIn('"text/html": new Blob', script)
        self.assertEqual(script.count('"text/plain": new Blob'), 1)
        self.assertIn('value === "暂缓"', script)
        self.assertIn('value === "同步失败"', script)
        self.assertIn("model.saving", script)
        self.assertIn('application/vnd.ms-excel', script)
        self.assertIn("position: sticky", css)
        self.assertIn(".news-review-status-select.status-accepted", css)


if __name__ == "__main__":
    unittest.main()

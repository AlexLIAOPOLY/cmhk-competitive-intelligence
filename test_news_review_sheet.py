import unittest
from unittest import mock

import news_review_sheet as review_sheet
import strategic_briefing


class NewsReviewSheetSyncTests(unittest.TestCase):
    def _existing_row(self):
        return [
            "接受",
            "已同步",
            "2026-07-21",
            "香港本地",
            "竞对动态",
            "历史新闻",
            "这是一条必须永久保留的历史新闻摘要。",
            "历史媒体",
            "2026-07-21",
            "https://example.com/history",
            "HKT",
            "历史入池理由",
        ]

    def _new_item(self):
        return {
            "news_id": review_sheet._news_item_id(
                "https://example.com/new",
                "今日新新闻",
            ),
            "url": "https://example.com/new",
            "ai_title": "今日新新闻",
            "ai_summary": "这是一条应当追加到历史记录之后的今日新闻摘要。",
            "source": "今日媒体",
            "source_date": "2026-07-22",
            "search_date": "2026-07-22",
            "region": "国际/行业",
            "category": "行业动态",
        }

    def test_sync_places_new_rows_above_history_and_preserves_history(self):
        writes = []
        with (
            mock.patch.object(review_sheet, "ensure_sheet", return_value="sheet"),
            mock.patch.object(
                review_sheet,
                "_read_rows",
                return_value=[self._existing_row()],
            ),
            mock.patch.object(
                review_sheet,
                "_write",
                side_effect=lambda _sheet_id, cell_range, values: writes.append(
                    (cell_range, values)
                ),
            ),
            mock.patch.object(review_sheet, "_read_json", return_value={}),
            mock.patch.object(review_sheet, "_write_json"),
            mock.patch.object(
                review_sheet,
                "curate_news_items",
                side_effect=lambda items: (items, {}),
            ),
            mock.patch.object(
                strategic_briefing,
                "polish_candidates_before_review",
                side_effect=lambda items: items,
            ),
        ):
            result = review_sheet.sync_candidates([self._new_item()])

        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual([cell_range for cell_range, _ in writes], ["A2:L3"])
        self.assertEqual(writes[0][1][0][5], "今日新新闻")
        self.assertEqual(writes[0][1][1], self._existing_row())

    def test_sync_places_current_batch_first_when_search_dates_match(self):
        writes = []
        existing = self._existing_row()
        existing[2] = "2026-07-22"
        with (
            mock.patch.object(review_sheet, "ensure_sheet", return_value="sheet"),
            mock.patch.object(review_sheet, "_read_rows", return_value=[existing]),
            mock.patch.object(
                review_sheet,
                "_write",
                side_effect=lambda _sheet_id, cell_range, values: writes.append(
                    (cell_range, values)
                ),
            ),
            mock.patch.object(review_sheet, "_read_json", return_value={}),
            mock.patch.object(review_sheet, "_write_json"),
            mock.patch.object(
                review_sheet,
                "curate_news_items",
                side_effect=lambda items: (items, {}),
            ),
            mock.patch.object(
                strategic_briefing,
                "polish_candidates_before_review",
                side_effect=lambda items: items,
            ),
        ):
            review_sheet.sync_candidates([self._new_item()])

        self.assertEqual(writes[0][1][0][5], "今日新新闻")
        self.assertEqual(writes[0][1][1][5], "历史新闻")

    def test_sync_stops_when_sheet_returns_fewer_rows_than_last_sync(self):
        write = mock.Mock()
        with (
            mock.patch.object(review_sheet, "ensure_sheet", return_value="sheet"),
            mock.patch.object(
                review_sheet,
                "_read_rows",
                return_value=[self._existing_row()],
            ),
            mock.patch.object(review_sheet, "_write", write),
            mock.patch.object(
                review_sheet,
                "_read_json",
                return_value={"last_candidate_count": 2},
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "已停止追加"):
                review_sheet.sync_candidates([])

        write.assert_not_called()


if __name__ == "__main__":
    unittest.main()

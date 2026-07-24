import unittest
from unittest import mock

import news_review_sheet as review_sheet
import strategic_briefing


class NewsReviewSheetSyncTests(unittest.TestCase):
    def _existing_row(self):
        return [
            "接受",
            "待审核",
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
            "新闻搜索爬虫（历史候选）",
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
        self.assertEqual([cell_range for cell_range, _ in writes], ["A2:N3"])
        self.assertEqual(writes[0][1][0][6], "今日新新闻")
        self.assertEqual(writes[0][1][1], self._existing_row())

    def test_sync_places_current_batch_first_when_search_dates_match(self):
        writes = []
        existing = self._existing_row()
        existing[3] = "2026-07-22"
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

        self.assertEqual(writes[0][1][0][6], "今日新新闻")
        self.assertEqual(writes[0][1][1][6], "历史新闻")

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

    def test_weekly_status_is_independent_from_app_status(self):
        row = self._existing_row()
        row[0] = "不接受"
        row[1] = "接受"

        parsed = review_sheet._row_dict(row, 2)

        self.assertEqual(parsed["status"], "不接受")
        self.assertEqual(parsed["weekly_status"], "接受")
        self.assertEqual(parsed["sync_status"], "已同步")
        self.assertEqual(
            parsed["information_flow"],
            "新闻搜索爬虫（历史候选）",
        )

    def test_information_flow_distinguishes_three_acquisition_paths(self):
        self.assertEqual(
            review_sheet._information_flow(
                {
                    "search_origin": "mandatory_local_competitor",
                    "search_provider": "google",
                }
            ),
            "后台固定竞对词库 → Google News搜索",
        )
        self.assertEqual(
            review_sheet._information_flow(
                {"search_origin": "scheduled_crawl_reference"}
            ),
            "定时页面爬虫发现 → 新闻搜索核验",
        )
        self.assertEqual(
            review_sheet._information_flow(
                {
                    "search_origin": "monitoring_sheet_keyword_search",
                    "search_provider": "bing",
                }
            ),
            "飞书监测表关键词 → Bing News搜索",
        )

    def test_weekly_candidates_only_include_manual_accepts_inside_window(self):
        included = self._existing_row()
        included[0] = "待审核"
        included[1] = "接受"
        included[3] = "2026-07-24"
        included[9] = "2026-07-24"
        outside = list(included)
        outside[6] = "窗口外新闻"
        outside[9] = "2026-07-17"
        outside[10] = "https://example.com/outside"
        pending = list(included)
        pending[1] = "待审核"
        pending[6] = "未选择新闻"
        pending[10] = "https://example.com/pending"
        with (
            mock.patch.object(review_sheet, "ensure_sheet", return_value="sheet"),
            mock.patch.object(
                review_sheet,
                "_read_rows",
                return_value=[included, outside, pending],
            ),
        ):
            rows, audit = review_sheet.load_weekly_report_candidates(
                "2026-07-18",
                "2026-07-24",
            )

        self.assertEqual([row["title"] for row in rows], ["历史新闻"])
        self.assertEqual(audit["acceptedRows"], 2)
        self.assertEqual(audit["includedRows"], 1)
        self.assertEqual(audit["reasons"]["out_of_window"], 1)

    def test_version_seven_row_migrates_by_inserting_weekly_status(self):
        legacy = [
            "接受",
            "已纳入",
            "2026-07-24",
            "国际/行业",
            "行业动态",
            "旧标题",
            "旧摘要",
            "旧媒体",
            "2026-07-24",
            "https://example.com/legacy",
            "AI",
            "旧理由",
        ]
        migrated = [legacy[0], "待审核", *legacy[1:]]

        parsed = review_sheet._row_dict(migrated, 2)

        self.assertEqual(parsed["weekly_status"], "待审核")
        self.assertEqual(parsed["title"], "旧标题")
        self.assertEqual(parsed["source_url"], "https://example.com/legacy")


if __name__ == "__main__":
    unittest.main()

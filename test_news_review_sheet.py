import unittest
from unittest import mock

import news_review_sheet as review_sheet
import strategic_briefing


class NewsReviewSheetSyncTests(unittest.TestCase):
    def test_non_forced_cycle_skips_when_another_process_holds_lock(self):
        with mock.patch.object(
            review_sheet,
            "_review_process_lock",
        ) as process_lock:
            process_lock.return_value.__enter__.return_value = False
            result = review_sheet.run_cycle(force=False)

        self.assertEqual(result["status"], "busy")
        self.assertEqual(
            result["reason"],
            "another_review_process_is_running",
        )

    def test_information_flow_labels_agentic_search_round(self):
        flow = review_sheet._information_flow(
            {
                "search_origin": "agentic_followup",
                "search_provider": "google",
                "module": "竞争对手",
                "keywords": ["T-Mobile"],
            }
        )
        self.assertEqual(
            flow,
            "Agentic Search 缺口复查（模块：竞争对手；命中：T-Mobile） → Google News搜索",
        )

    def test_current_competitor_product_news_is_kept_for_human_review(self):
        keep, reason = review_sheet._review_news_candidate(
            {
                "title": "数码通推出限时5G套餐优惠",
                "snippet": "数码通公布新的5G套餐优惠及客户服务安排。",
                "url": "https://example.com/news/2026/07/26/smartone-plan",
                "source": "PR Newswire",
                "published_at": "2026-07-26T08:00:00+08:00",
                "search_date": "2026-07-26",
                "keywords": ["SmarTone", "数码通"],
                "module": "竞争对手",
            }
        )
        self.assertTrue(keep)
        self.assertEqual(reason, "香港直接竞对新闻")

    def test_seven_day_agentic_window_is_rejected_before_review(self):
        keep, reason = review_sheet._review_news_candidate(
            {
                "title": "HKT Tech Week 2026展示AI方案",
                "snippet": "香港电讯展示企业AI及网络方案。",
                "url": "https://example.com/news/hkt-tech-week-2026",
                "source": "Example",
                "published_at": "2026-07-21T18:44:10+08:00",
                "search_date": "2026-07-26",
                "search_window_start": "2026-07-19T15:00:46+08:00",
                "search_window_end": "2026-07-26T15:00:46+08:00",
                "search_origin": "agentic_expansion",
                "keywords": ["HKT"],
                "module": "竞争对手",
            }
        )

        self.assertFalse(keep)
        self.assertEqual(reason, "新闻搜索入库窗口异常")

    def test_competitor_query_metadata_alone_is_not_entity_evidence(self):
        relevant, reason = review_sheet._competitor_relevance(
            {
                "title": "Panthers player eager to return after injury",
                "snippet": "The football player discussed the upcoming season.",
                "source": "Sports News",
                "url": "https://example.com/sports/player-return",
                "keywords": ["HKT", "csl"],
                "module": "竞争对手",
            }
        )
        self.assertFalse(relevant)
        self.assertEqual(reason, "未直接关联竞对或香港电信市场")

    def test_ambiguous_csl_sports_reference_is_not_competitor_news(self):
        keep, reason = review_sheet._review_news_candidate(
            {
                "title": "Panthers player eager to return after injury",
                "snippet": "CSL reporter interviews the football player about the season.",
                "source": "AOL",
                "url": "https://example.com/sports/player-return",
                "published_at": "2026-07-26T08:00:00+08:00",
                "search_date": "2026-07-26",
                "keywords": ["HKT", "csl"],
                "module": "竞争对手",
            }
        )
        self.assertFalse(keep)
        self.assertEqual(reason, "生活、体育或误命中新闻")

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

    @staticmethod
    def _semantic_keep(items, history):
        return {
            "kept": items,
            "duplicates": [],
            "deferred": [],
            "decisions": [],
            "history_count": len(history),
            "history_shards": 1,
        }

    def test_sync_places_new_rows_above_history_and_preserves_history(self):
        writes = []
        read_count = [0]

        def read_rows(_sheet_id):
            read_count[0] += 1
            return [self._existing_row()] if read_count[0] == 1 else writes[0][1]

        with (
            mock.patch.object(review_sheet, "ensure_sheet", return_value="sheet"),
            mock.patch.object(
                review_sheet,
                "_read_rows",
                side_effect=read_rows,
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
            mock.patch.object(
                strategic_briefing,
                "agent_semantic_deduplicate_candidates",
                side_effect=self._semantic_keep,
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
        read_count = [0]

        def read_rows(_sheet_id):
            read_count[0] += 1
            return [existing] if read_count[0] == 1 else writes[0][1]

        with (
            mock.patch.object(review_sheet, "ensure_sheet", return_value="sheet"),
            mock.patch.object(review_sheet, "_read_rows", side_effect=read_rows),
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
            mock.patch.object(
                strategic_briefing,
                "agent_semantic_deduplicate_candidates",
                side_effect=self._semantic_keep,
            ),
        ):
            review_sheet.sync_candidates([self._new_item()])

        self.assertEqual(writes[0][1][0][6], "今日新新闻")
        self.assertEqual(writes[0][1][1][6], "历史新闻")

    def test_sync_collapses_existing_rich_link_duplicates_and_keeps_manual_decision(self):
        pending = self._existing_row()
        pending[0] = "待审核"
        pending[10] = [
            {
                "link": "https://example.com/news/same-event",
                "text": "阅读原文",
                "type": "url",
            }
        ]
        rejected = list(pending)
        rejected[0] = "不接受"
        rejected[6] = "同一事件的人工拒绝记录"
        writes = []
        read_count = [0]

        def read_rows(_sheet_id):
            read_count[0] += 1
            return [pending, rejected] if read_count[0] == 1 else writes[0][1]

        with (
            mock.patch.object(review_sheet, "ensure_sheet", return_value="sheet"),
            mock.patch.object(
                review_sheet,
                "_read_rows",
                side_effect=read_rows,
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
                return_value=([], {}),
            ),
        ):
            result = review_sheet.sync_candidates([])

        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(writes[0][0], "A2:N2")
        self.assertEqual(writes[0][1][0][0], "不接受")
        self.assertEqual(writes[0][1][0][6], "同一事件的人工拒绝记录")
        self.assertEqual(writes[1][0], "A3:N3")
        self.assertEqual(writes[1][1], [[""] * len(review_sheet.HEADERS)])

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

    def test_load_curated_latest_propagates_ai_review_failure(self):
        source = {
            "generated_at": "2026-07-27T09:41:27+08:00",
            "items": [self._new_item()],
        }
        with (
            mock.patch.object(
                review_sheet,
                "_read_json",
                side_effect=lambda path, default: (
                    source if path == review_sheet.LATEST_PATH else default
                ),
            ),
            mock.patch.object(
                review_sheet,
                "curate_news_items",
                return_value=(source["items"], {}),
            ),
            mock.patch.object(
                strategic_briefing,
                "polish_candidates_before_review",
                side_effect=RuntimeError("AI review deferred"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "AI review deferred"):
                review_sheet._load_curated_latest()

    def test_run_cycle_records_failed_ai_review_without_syncing_sheet(self):
        sync = mock.Mock()
        with (
            mock.patch.object(review_sheet, "_read_json", return_value={}),
            mock.patch.object(review_sheet, "_write_json") as write_json,
            mock.patch.object(
                review_sheet,
                "_load_curated_latest",
                side_effect=RuntimeError("AI review deferred"),
            ),
            mock.patch.object(review_sheet, "sync_candidates", sync),
        ):
            with self.assertRaisesRegex(RuntimeError, "AI review deferred"):
                review_sheet.run_cycle(force=True)

        sync.assert_not_called()
        state = write_json.call_args.args[1]
        self.assertEqual(state["last_poll_status"], "failed")
        self.assertIn("AI review deferred", state["last_poll_error"])

    def test_run_cycle_skips_reprocessing_when_source_is_unchanged(self):
        state = {
            "last_poll_epoch": 0,
            "last_source_generated_at": "2026-07-27T09:41:27+08:00",
            "last_source_summary": {
                "generated_at": "2026-07-27T09:41:27+08:00",
                "candidate_count": 29,
            },
            "sheet_id": "sheet",
            "sheet_url": "https://example.com/sheet",
            "last_candidate_count": 277,
        }
        load_latest = mock.Mock()
        sync = mock.Mock()
        with (
            mock.patch.object(review_sheet, "_read_json", return_value=state),
            mock.patch.object(review_sheet, "_write_json") as write_json,
            mock.patch.dict(
                review_sheet.os.environ,
                {"CMHK_STRATEGIC_GROUP_NOTIFICATIONS": "1"},
            ),
            mock.patch.object(
                review_sheet,
                "_current_source_generated_at",
                return_value="2026-07-27T09:41:27+08:00",
            ),
            mock.patch.object(review_sheet, "_load_curated_latest", load_latest),
            mock.patch.object(review_sheet, "sync_candidates", sync),
            mock.patch.object(
                review_sheet,
                "apply_reviews",
                return_value={"changed_rows": 0},
            ) as apply_reviews,
        ):
            result = review_sheet.run_cycle()

        load_latest.assert_not_called()
        sync.assert_not_called()
        apply_reviews.assert_called_once_with("sheet")
        self.assertTrue(result["source_unchanged"])
        self.assertEqual(result["sheet_candidate_count"], 277)
        self.assertFalse(
            write_json.call_args.args[1]["group_notifications_paused"]
        )

    def test_legacy_notice_builder_does_not_sync_candidates_twice(self):
        with (
            mock.patch.object(review_sheet, "_load_curated_latest") as load_latest,
            mock.patch.object(review_sheet, "sync_candidates") as sync,
            mock.patch.object(review_sheet, "apply_reviews") as apply_reviews,
        ):
            cards = review_sheet.build_notice_cards(items=[self._new_item()])

        self.assertEqual(cards, [])
        load_latest.assert_not_called()
        sync.assert_not_called()
        apply_reviews.assert_not_called()

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

    def test_row_dict_extracts_real_url_from_feishu_rich_link_cell(self):
        row = self._existing_row()
        row[10] = [
            {
                "cellPosition": None,
                "link": "https://example.com/news/rich-link",
                "text": "阅读原文",
                "type": "url",
            }
        ]

        parsed = review_sheet._row_dict(row, 2)

        self.assertEqual(
            parsed["source_url"],
            "https://example.com/news/rich-link",
        )
        self.assertEqual(
            parsed["news_id"],
            review_sheet._news_item_id(
                "https://example.com/news/rich-link",
                row[6],
            ),
        )

    def test_information_flow_distinguishes_three_acquisition_paths(self):
        self.assertEqual(
            review_sheet._information_flow(
                {
                    "search_origin": "mandatory_local_competitor",
                    "search_provider": "google",
                    "canonical_competitor": "HKT",
                    "keywords": ["HKT", "Tap & Go"],
                }
            ),
            "后台固定竞对词库（HKT；命中：HKT、Tap & Go） → Google News搜索",
        )
        self.assertEqual(
            review_sheet._information_flow(
                {
                    "search_origin": "scheduled_crawl_reference",
                    "scheduled_crawl_config_row": "18",
                    "scheduled_crawl_parent_url": "https://www.hkt.com/news/",
                    "keywords": ["HKT", "5G"],
                }
            ),
            "定时页面爬虫（配置第18行；hkt.com；命中：HKT、5G）发现 → 新闻搜索核验",
        )
        self.assertEqual(
            review_sheet._information_flow(
                {
                    "search_origin": "monitoring_sheet_keyword_search",
                    "search_provider": "bing",
                    "module": "竞争对手",
                    "keywords": ["香港电讯", "5G"],
                }
            ),
            "飞书监测表关键词（模块：竞争对手；命中：香港电讯、5G） → Bing News搜索",
        )
        self.assertEqual(
            review_sheet._information_flow(
                {
                    "search_origin": "background_fixed_keywords",
                    "module": "政策监管",
                    "keywords": ["OFCA"],
                }
            ),
            "后台固定战略词库（模块：政策监管；命中：OFCA） → 新闻搜索",
        )

    def test_historical_flow_states_the_evidence_limit_and_matched_keyword(self):
        self.assertEqual(
            review_sheet._historical_information_flow("HKT、Tap & Go"),
            "历史新闻搜索（搜索引擎未留存；命中：HKT、Tap & Go）",
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

    def test_current_format_never_auto_shifts_misaligned_row(self):
        shifted = [
            "待审核",
            "待审核",
            "未同步",
            "",
            "",
            "2026-07-28",
            "香港本地",
            "",
            "竞对动态",
            "错位标题",
            "错位摘要",
            "https://example.com/wrong-column",
            "2026-07-28",
            "旧流程",
        ]

        normalized = review_sheet._normalized_sheet_row(
            shifted,
            review_sheet.FORMAT_VERSION,
        )

        self.assertEqual(normalized, shifted)
        with self.assertRaisesRegex(RuntimeError, "原文链接不在K列"):
            review_sheet._validate_sheet_rows(
                [normalized],
                context="测试表",
            )

    def test_sheet_schema_accepts_complete_current_row(self):
        review_sheet._validate_sheet_rows(
            [self._existing_row()],
            context="测试表",
        )


if __name__ == "__main__":
    unittest.main()

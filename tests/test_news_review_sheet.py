import json
import subprocess
import unittest
from unittest import mock

import cmhk.intelligence.news_review_sheet as review_sheet
import strategic_briefing


class NewsReviewSheetSyncTests(unittest.TestCase):
    @staticmethod
    def _lark_result(payload, returncode=0):
        return subprocess.CompletedProcess(
            args=["lark-cli"],
            returncode=returncode,
            stdout=json.dumps(payload, ensure_ascii=False),
            stderr="",
        )

    def test_lark_read_retries_transient_2200_then_succeeds(self):
        transient = self._lark_result(
            {"ok": False, "error": {"code": 2200, "message": "Internal Error"}},
            returncode=1,
        )
        success = self._lark_result({"ok": True, "data": {"values": []}})
        with (
            mock.patch.object(
                review_sheet.subprocess,
                "run",
                side_effect=[transient, success],
            ) as run,
            mock.patch.object(review_sheet.time, "sleep") as sleep,
        ):
            result = review_sheet._lark(
                "sheets",
                "+read",
                retry_transient=True,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_lark_read_stops_after_three_transient_failures(self):
        transient = self._lark_result(
            {"ok": False, "error": {"code": 2200, "message": "Internal Error"}},
            returncode=1,
        )
        with (
            mock.patch.object(
                review_sheet.subprocess,
                "run",
                side_effect=[transient, transient, transient],
            ) as run,
            mock.patch.object(review_sheet.time, "sleep") as sleep,
        ):
            with self.assertRaisesRegex(RuntimeError, "2200"):
                review_sheet._lark(
                    "sheets",
                    "+read",
                    retry_transient=True,
                )

        self.assertEqual(run.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])

    def test_lark_read_retries_timeout_then_succeeds(self):
        success = self._lark_result({"ok": True, "data": {"values": []}})
        with (
            mock.patch.object(
                review_sheet.subprocess,
                "run",
                side_effect=[
                    subprocess.TimeoutExpired(cmd=["lark-cli"], timeout=120),
                    success,
                ],
            ) as run,
            mock.patch.object(review_sheet.time, "sleep") as sleep,
        ):
            result = review_sheet._lark(
                "sheets",
                "+read",
                retry_transient=True,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_lark_read_does_not_retry_permission_error(self):
        forbidden = self._lark_result(
            {"ok": False, "error": {"code": 403, "message": "Forbidden"}},
            returncode=1,
        )
        with (
            mock.patch.object(
                review_sheet.subprocess,
                "run",
                return_value=forbidden,
            ) as run,
            mock.patch.object(review_sheet.time, "sleep") as sleep,
        ):
            with self.assertRaisesRegex(RuntimeError, "403"):
                review_sheet._lark(
                    "sheets",
                    "+read",
                    retry_transient=True,
                )

        run.assert_called_once()
        sleep.assert_not_called()

    def test_insert_rows_reapplies_review_row_height(self):
        with (
            mock.patch.object(review_sheet, "_lark") as lark,
            mock.patch.object(review_sheet, "_best_effort") as best_effort,
        ):
            review_sheet._insert_rows("sheet", 3, start_index=1)

        lark.assert_called_once_with(
            "sheets",
            "+insert-dimension",
            "--spreadsheet-token",
            review_sheet.SPREADSHEET_TOKEN,
            "--sheet-id",
            "sheet",
            "--dimension",
            "ROWS",
            "--start-index",
            "1",
            "--end-index",
            "4",
            "--inherit-style",
            "AFTER",
        )
        best_effort.assert_called_once_with(
            "sheets",
            "+update-dimension",
            "--spreadsheet-token",
            review_sheet.SPREADSHEET_TOKEN,
            "--sheet-id",
            "sheet",
            "--dimension",
            "ROWS",
            "--start-index",
            "2",
            "--end-index",
            "4",
            "--fixed-size",
            str(review_sheet.REVIEW_ROW_HEIGHT_PX),
            "--visible",
        )

    def test_insert_rows_formats_separator_band(self):
        with (
            mock.patch.object(review_sheet, "_lark"),
            mock.patch.object(review_sheet, "_best_effort") as best_effort,
        ):
            review_sheet._insert_rows(
                "sheet",
                5,
                start_index=1,
                separator_count=2,
            )

        self.assertEqual(best_effort.call_count, 3)
        self.assertEqual(
            best_effort.call_args_list[1],
            mock.call(
                "sheets",
                "+update-dimension",
                "--spreadsheet-token",
                review_sheet.SPREADSHEET_TOKEN,
                "--sheet-id",
                "sheet",
                "--dimension",
                "ROWS",
                "--start-index",
                "5",
                "--end-index",
                "6",
                "--fixed-size",
                str(review_sheet.SEPARATOR_ROW_HEIGHT_PX),
                "--visible",
            ),
        )
        self.assertEqual(
            best_effort.call_args_list[2],
            mock.call(
                "sheets",
                "+set-style",
                "--spreadsheet-token",
                review_sheet.SPREADSHEET_TOKEN,
                "--range",
                "sheet!A5:N6",
                "--style",
                json.dumps(
                    {"backColor": review_sheet.SEPARATOR_ROW_COLOR},
                    ensure_ascii=False,
                ),
            ),
        )

    def test_canonical_news_url_preserves_article_identity_query(self):
        first = (
            "https://hkcna.hk/docDetail.jsp?id=101381240&channel=4372"
            "&utm_source=test"
        )
        second = "https://hkcna.hk/docDetail.jsp?channel=4372&id=101381961"

        self.assertNotEqual(
            review_sheet._canonical_news_url(first),
            review_sheet._canonical_news_url(second),
        )
        self.assertEqual(
            review_sheet._canonical_news_url(first),
            "https://hkcna.hk/docDetail.jsp?channel=4372&id=101381240",
        )

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
        self.assertEqual(reason, "待AI审核")

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

    def test_competitor_query_metadata_is_forwarded_to_ai(self):
        keep, reason = review_sheet._review_news_candidate(
            {
                "title": "Panthers player eager to return after injury",
                "snippet": "The football player discussed the upcoming season.",
                "source": "Sports News",
                "url": "https://example.com/sports/player-return",
                "published_at": "2026-07-26T08:00:00+08:00",
                "search_date": "2026-07-26",
                "keywords": ["HKT", "csl"],
                "module": "竞争对手",
            }
        )
        self.assertTrue(keep)
        self.assertEqual(reason, "待AI审核")

    def test_ambiguous_csl_sports_reference_reaches_ai_review(self):
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
        self.assertTrue(keep)
        self.assertEqual(reason, "待AI审核")

    def test_manufacturing_innovation_agreement_reaches_ai_review(self):
        keep, reason = review_sheet._review_news_candidate(
            {
                "title": "特区政府与国家工信部签署协议推进共建制造业创新中心",
                "snippet": "双方共同支持在香港建设制造业创新中心。",
                "source": "香港商报",
                "url": "https://www.hkcd.com.hk/hkcdweb/content/2026/07/28/content_8767010.html",
                "published_at": "2026-07-28T14:58:59+08:00",
                "search_date": "2026-07-28",
                "keywords": ["工信部"],
                "module": "宏观经济&国际形势&地缘政治&其他国际性质关注词汇",
            }
        )
        self.assertTrue(keep)
        self.assertEqual(reason, "待AI审核")

    class _LiveSheet:
        def __init__(self, rows):
            self.rows = [list(row) for row in rows]
            self.writes = []
            self.inserts = []

        def read(self, _sheet_id):
            return [
                list(row)
                for row in self.rows
                if any(cell not in (None, "") for cell in row)
            ]

        def insert(
            self,
            _sheet_id,
            count,
            *,
            start_index=1,
            separator_count=0,
        ):
            self.inserts.append(
                {
                    "start_index": start_index,
                    "count": count,
                    "separator_count": separator_count,
                }
            )
            position = max(0, int(start_index) - 1)
            blanks = [[""] * len(review_sheet.HEADERS) for _ in range(count)]
            self.rows = self.rows[:position] + blanks + self.rows[position:]

        def write(self, _sheet_id, cell_range, values):
            self.writes.append((cell_range, values))
            start = int("".join(character for character in cell_range.split(":")[0] if character.isdigit()))
            for offset, row in enumerate(values):
                index = start - 2 + offset
                while len(self.rows) <= index:
                    self.rows.append([""] * len(review_sheet.HEADERS))
                self.rows[index] = (
                    list(row) + [""] * len(review_sheet.HEADERS)
                )[: len(review_sheet.HEADERS)]
            while self.rows and not any(cell not in (None, "") for cell in self.rows[-1]):
                self.rows.pop()

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
        sheet = self._LiveSheet([self._existing_row()])
        progress_events = []
        semantic_histories = []
        acknowledged_items = []

        with (
            mock.patch.object(review_sheet, "ensure_sheet", return_value="sheet"),
            mock.patch.object(review_sheet, "_read_rows", side_effect=sheet.read),
            mock.patch.object(review_sheet, "_write", side_effect=sheet.write),
            mock.patch.object(review_sheet, "_insert_rows", side_effect=sheet.insert),
            mock.patch.object(review_sheet, "_read_json", return_value={}),
            mock.patch.object(review_sheet, "_write_json") as write_json,
            mock.patch.object(
                review_sheet,
                "curate_news_items",
                side_effect=lambda items: (items, {}),
            ),
            mock.patch.object(
                strategic_briefing,
                "polish_candidates_before_review",
                side_effect=lambda items, **_kwargs: items,
            ),
            mock.patch.object(
                strategic_briefing,
                "agent_semantic_deduplicate_candidates",
                side_effect=lambda items, history, **_kwargs: (
                    semantic_histories.append(history)
                    or self._semantic_keep(items, history)
                ),
            ),
            mock.patch.object(
                strategic_briefing,
                "acknowledge_deferred_ai_candidates",
                side_effect=lambda items: (
                    acknowledged_items.extend(items)
                    or {
                        "requested_count": len(items),
                        "removed_count": len(items),
                        "queued_count": 0,
                    }
                ),
            ),
        ):
            result = review_sheet.sync_candidates(
                [self._new_item()],
                progress_callback=lambda phase, detail: progress_events.append(
                    (phase, detail)
                ),
            )

        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["ai_included_count"], 1)
        self.assertTrue(result["existing_rows_untouched"])
        self.assertEqual(
            result["new_items"],
            [
                {
                    "news_id": self._new_item()["news_id"],
                    "title": "今日新新闻",
                    "summary": "这是一条应当追加到历史记录之后的今日新闻摘要。",
                    "category": "行业动态",
                    "region": "国际/行业",
                    "source": "今日媒体",
                    "published_at": "2026-07-22",
                    "url": "https://example.com/new",
                    "inclusion_reason": "",
                    "business_impact": "",
                }
            ],
        )
        self.assertEqual(
            sheet.inserts,
            [{"start_index": 1, "count": 3, "separator_count": 2}],
        )
        self.assertEqual([cell_range for cell_range, _ in sheet.writes], ["A2:N2"])
        self.assertEqual(sheet.writes[0][1][0][6], "今日新新闻")
        self.assertFalse(any(sheet.rows[1]))
        self.assertFalse(any(sheet.rows[2]))
        self.assertEqual(sheet.rows[3], self._existing_row())
        self.assertEqual(
            [[item["news_id"] for item in history] for history in semantic_histories],
            [["NEWS-4A3C54DE894A40"]],
        )
        self.assertEqual(
            result["semantic_history_scope"],
            "hkt_search_day_and_previous_2_days",
        )
        self.assertEqual(result["semantic_search_day"], "2026-07-22")
        self.assertEqual(acknowledged_items, [self._new_item()])
        self.assertEqual(result["deferred_delivery_ack"]["removed_count"], 1)
        progress_phases = [phase for phase, _detail in progress_events]
        for phase in (
            "飞书审核表准备",
            "飞书历史读取",
            "候选确定性门禁",
            "AI逐条审核",
            "新增候选组装",
            "人工审核状态保护",
            "飞书分批写入",
            "飞书逐格回读",
        ):
            self.assertIn(phase, progress_phases)
        self.assertEqual(result["rescued_decision_count"], 0)
        saved_state = write_json.call_args.args[1]
        metadata = saved_state[review_sheet.GATE_METADATA_STATE_KEY]
        self.assertEqual(
            metadata["https://example.com/new"]["published_at"],
            "2026-07-22",
        )

    def test_recent_semantic_history_includes_today_and_previous_two_days(self):
        search_day, history = review_sheet._same_day_semantic_history(
            [
                {"news_id": "morning", "search_date": "2026-08-15"},
                {"news_id": "prior-1", "search_date": "2026-08-14"},
                {"news_id": "prior-2", "search_date": "2026-08-13"},
                {"news_id": "too-old", "search_date": "2026-08-12"},
                {"news_id": "malformed", "search_date": ""},
            ],
            generated_at="2026-08-15T15:05:00+08:00",
            candidate_items=[{"search_date": "2026-08-15"}],
        )

        self.assertEqual(search_day, "2026-08-15")
        self.assertEqual(
            [item["news_id"] for item in history],
            ["morning", "prior-1", "prior-2"],
        )

    def test_sync_places_current_batch_first_when_search_dates_match(self):
        existing = self._existing_row()
        existing[3] = "2026-07-22"
        sheet = self._LiveSheet([existing])

        with (
            mock.patch.object(review_sheet, "ensure_sheet", return_value="sheet"),
            mock.patch.object(review_sheet, "_read_rows", side_effect=sheet.read),
            mock.patch.object(review_sheet, "_write", side_effect=sheet.write),
            mock.patch.object(review_sheet, "_insert_rows", side_effect=sheet.insert),
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

        self.assertEqual(sheet.writes[0][1][0][6], "今日新新闻")
        self.assertEqual(
            sheet.inserts,
            [{"start_index": 1, "count": 2, "separator_count": 1}],
        )
        self.assertFalse(any(sheet.rows[1]))
        self.assertEqual(sheet.rows[2][6], "历史新闻")

    def test_sync_does_not_rewrite_existing_duplicate_rows(self):
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
        sheet = self._LiveSheet([pending, rejected])

        with (
            mock.patch.object(review_sheet, "ensure_sheet", return_value="sheet"),
            mock.patch.object(review_sheet, "_read_rows", side_effect=sheet.read),
            mock.patch.object(review_sheet, "_write", side_effect=sheet.write),
            mock.patch.object(review_sheet, "_insert_rows", side_effect=sheet.insert),
            mock.patch.object(review_sheet, "_read_json", return_value={}),
            mock.patch.object(review_sheet, "_write_json"),
            mock.patch.object(
                review_sheet,
                "curate_news_items",
                return_value=([], {}),
            ),
        ):
            result = review_sheet.sync_candidates([])

        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(sheet.writes, [])
        self.assertEqual(sheet.inserts, [])
        self.assertEqual(sheet.rows[1][0], "不接受")
        self.assertEqual(sheet.rows[1][6], "同一事件的人工拒绝记录")

    def test_sync_keeps_review_decisions_made_during_ai_pass(self):
        pending = self._existing_row()
        pending[0] = "待审核"
        pending[1] = "待审核"
        pending[2] = "未同步"
        sheet = self._LiveSheet([pending])

        def polish(items, **_kwargs):
            sheet.rows[0][0] = "接受"
            sheet.rows[0][1] = "接受"
            sheet.rows[0][2] = "未同步"
            return items

        with (
            mock.patch.object(review_sheet, "ensure_sheet", return_value="sheet"),
            mock.patch.object(review_sheet, "_read_rows", side_effect=sheet.read),
            mock.patch.object(review_sheet, "_write", side_effect=sheet.write),
            mock.patch.object(review_sheet, "_insert_rows", side_effect=sheet.insert),
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
                side_effect=polish,
            ),
            mock.patch.object(
                strategic_briefing,
                "agent_semantic_deduplicate_candidates",
                side_effect=self._semantic_keep,
            ),
        ):
            result = review_sheet.sync_candidates([self._new_item()])

        written_titles = [row[6] for _range, rows in sheet.writes for row in rows]
        self.assertNotIn("历史新闻", written_titles)
        self.assertEqual(sheet.rows[3][:3], ["接受", "接受", "未同步"])
        self.assertEqual(result["rescued_decision_count"], 1)
        self.assertEqual(result["rescued_decisions"][0]["before"], "待审核 / 待审核 / 未同步")
        self.assertEqual(result["rescued_decisions"][0]["after"], "接受 / 接受 / 未同步")

    def test_sync_stops_when_sheet_returns_fewer_rows_than_last_sync(self):
        write = mock.Mock()
        insert = mock.Mock()
        with (
            mock.patch.object(review_sheet, "ensure_sheet", return_value="sheet"),
            mock.patch.object(
                review_sheet,
                "_read_rows",
                return_value=[self._existing_row()],
            ),
            mock.patch.object(review_sheet, "_write", write),
            mock.patch.object(review_sheet, "_insert_rows", insert),
            mock.patch.object(
                review_sheet,
                "_read_json",
                return_value={"last_candidate_count": 2},
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "已停止追加"):
                review_sheet.sync_candidates([])

        write.assert_not_called()
        insert.assert_not_called()

    def test_load_curated_latest_defers_ai_review_to_sync_transaction(self):
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
            ) as polish,
        ):
            items, metadata = review_sheet._load_curated_latest()

        polish.assert_not_called()
        self.assertEqual(items, source["items"])
        self.assertEqual(metadata["candidate_count"], 1)

    def test_load_curated_latest_leaves_empty_source_for_sync_queue_replay(self):
        with mock.patch.object(review_sheet, "_read_json", return_value={}):
            items, metadata = review_sheet._load_curated_latest()

        self.assertEqual(items, [])
        self.assertEqual(metadata["input_count"], 0)
        self.assertEqual(metadata["candidate_count"], 0)
        self.assertEqual(metadata["filtered_count"], 0)

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

    def test_run_cycle_reuses_verified_result_for_same_scheduled_slot(self):
        cached = {
            "status": "ok",
            "readback_verified": True,
            "new_count": 3,
            "new_items": [{"title": "cached"}],
            "sheet_candidate_count": 471,
        }
        state = {
            review_sheet.SUCCESSFUL_CYCLE_RESULTS_STATE_KEY: {
                "2026-08-06@09:00": cached,
            }
        }
        load_latest = mock.Mock()
        sync = mock.Mock()
        apply_reviews = mock.Mock()
        with (
            mock.patch.object(review_sheet, "_read_json", return_value=state),
            mock.patch.object(review_sheet, "_load_curated_latest", load_latest),
            mock.patch.object(review_sheet, "sync_candidates", sync),
            mock.patch.object(review_sheet, "apply_reviews", apply_reviews),
        ):
            result = review_sheet.run_cycle(
                force=True,
                schedule_dashboard_publish=False,
                idempotency_key="2026-08-06@09:00",
            )

        self.assertTrue(result["reused_verified_result"])
        self.assertTrue(result["readback_verified"])
        self.assertEqual(result["new_count"], 3)
        load_latest.assert_not_called()
        sync.assert_not_called()
        apply_reviews.assert_not_called()

    def test_background_cycle_completes_pending_scheduled_slot_receipt(self):
        state_holder = {
            "value": {
                "last_poll_epoch": 0,
                review_sheet.PENDING_CYCLE_STATE_KEY: {
                    "key": "2026-08-06@09:00",
                    "source_generated_at": "2026-08-06T09:00:41+08:00",
                },
            }
        }

        def read_state(_path, _default):
            return dict(state_holder["value"])

        def write_state(_path, payload):
            state_holder["value"] = dict(payload)

        with (
            mock.patch.object(review_sheet, "_read_json", side_effect=read_state),
            mock.patch.object(review_sheet, "_write_json", side_effect=write_state),
            mock.patch.object(
                review_sheet,
                "_current_source_generated_at",
                return_value="2026-08-06T09:00:41+08:00",
            ),
            mock.patch.object(
                review_sheet,
                "_load_curated_latest",
                return_value=([], {"generated_at": "2026-08-06T09:00:41+08:00", "candidate_count": 3}),
            ),
            mock.patch.object(
                review_sheet,
                "sync_candidates",
                return_value={
                    "sheet_id": "sheet",
                    "candidate_count": 471,
                    "readback_verified": True,
                    "new_count": 3,
                    "new_items": [{"title": "new"}],
                },
            ),
            mock.patch.object(
                review_sheet,
                "apply_reviews",
                return_value={"changed_rows": 0},
            ),
        ):
            result = review_sheet.run_cycle(schedule_dashboard_publish=False)

        self.assertTrue(result["readback_verified"])
        receipts = state_holder["value"][
            review_sheet.SUCCESSFUL_CYCLE_RESULTS_STATE_KEY
        ]
        self.assertTrue(receipts["2026-08-06@09:00"]["readback_verified"])
        self.assertNotIn(
            review_sheet.PENDING_CYCLE_STATE_KEY,
            state_holder["value"],
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

    def test_apply_reviews_never_overwrites_human_decision_when_gate_blocks(self):
        accepted = self._existing_row()
        accepted[0] = "接受"
        accepted[2] = "已纳入"
        writes = []
        with (
            mock.patch.object(review_sheet, "_read_rows", return_value=[accepted]),
            mock.patch.object(
                review_sheet,
                "_read_json",
                return_value={"items": []},
            ),
            mock.patch.object(review_sheet, "_write_json"),
            mock.patch.object(
                review_sheet,
                "_review_news_candidate",
                return_value=(False, "缺少可验证发布日期"),
            ),
            mock.patch.object(
                review_sheet,
                "_write",
                side_effect=lambda sheet, cell_range, values: writes.append(
                    (sheet, cell_range, values)
                ),
            ),
        ):
            result = review_sheet.apply_reviews("sheet")

        self.assertEqual(writes, [("sheet", "C2:C2", [["同步失败"]])])
        self.assertEqual(result["requested_accept_count"], 1)
        self.assertEqual(result["blocked_accept_count"], 1)
        self.assertEqual(result["rejected_count"], 0)
        self.assertEqual(
            result["blocked_reviews"][0]["reason"],
            "缺少可验证发布日期",
        )

    def test_apply_reviews_restores_precise_gate_metadata_after_sheet_round_trip(self):
        accepted = self._existing_row()
        accepted[0] = "接受"
        accepted[2] = "同步失败"
        accepted[3] = "2026-07-30"
        accepted[6] = "香港电讯上半年多赚4%至21.5亿"
        accepted[9] = "2026-07-29"
        accepted[10] = "https://example.com/hkt-interim-results"
        metadata_key = review_sheet._gate_metadata_key(accepted[10])
        writes = []
        published_payloads = []

        def read_json(path, default):
            if path == review_sheet.STATE_PATH:
                return {
                    review_sheet.GATE_METADATA_STATE_KEY: {
                        metadata_key: {
                            "published_at": "2026-07-29T17:16:00+08:00",
                            "search_window_start": "2026-07-29T14:00:00+08:00",
                            "search_window_end": "2026-07-30T10:46:54+08:00",
                            "search_origin": "background_fixed_keywords",
                        }
                    }
                }
            return {"items": []}

        with (
            mock.patch.object(review_sheet, "_read_rows", return_value=[accepted]),
            mock.patch.object(review_sheet, "_read_json", side_effect=read_json),
            mock.patch.object(
                review_sheet,
                "_write_json",
                side_effect=lambda path, payload: published_payloads.append(
                    (path, payload)
                ),
            ),
            mock.patch.object(
                review_sheet,
                "_write",
                side_effect=lambda sheet, cell_range, values: writes.append(
                    (sheet, cell_range, values)
                ),
            ),
        ):
            result = review_sheet.apply_reviews("sheet")

        self.assertEqual(result["accepted_count"], 1)
        self.assertEqual(result["blocked_accept_count"], 0)
        self.assertEqual(writes, [("sheet", "C2:C2", [["已纳入"]])])
        published = next(
            payload
            for path, payload in published_payloads
            if path == review_sheet.PUBLISHED_PATH
        )
        self.assertEqual(
            published["items"][0]["published_at"],
            "2026-07-29T17:16:00+08:00",
        )

    def test_cross_day_sheet_row_without_precise_metadata_stays_blocked(self):
        accepted = self._existing_row()
        accepted[0] = "接受"
        accepted[2] = "同步失败"
        accepted[3] = "2026-07-30"
        accepted[9] = "2026-07-29"
        writes = []
        with (
            mock.patch.object(review_sheet, "_read_rows", return_value=[accepted]),
            mock.patch.object(
                review_sheet,
                "_read_json",
                side_effect=lambda path, default: (
                    {} if path == review_sheet.STATE_PATH else {"items": []}
                ),
            ),
            mock.patch.object(review_sheet, "_write_json"),
            mock.patch.object(
                review_sheet,
                "_write",
                side_effect=lambda sheet, cell_range, values: writes.append(
                    (sheet, cell_range, values)
                ),
            ),
        ):
            result = review_sheet.apply_reviews("sheet")

        self.assertEqual(result["accepted_count"], 0)
        self.assertEqual(result["blocked_accept_count"], 1)
        self.assertEqual(
            result["blocked_reviews"][0]["reason"],
            "不在明确检索时间窗口",
        )
        self.assertEqual(writes, [])

    def test_ensure_sheet_refuses_automatic_schema_migration_before_writing(self):
        writes = []
        with (
            mock.patch.object(
                review_sheet,
                "_read_json",
                return_value={"format_version": 8},
            ),
            mock.patch.object(review_sheet, "_spreadsheet_info", return_value={}),
            mock.patch.object(review_sheet, "_find_sheet_id", return_value="sheet"),
            mock.patch.object(
                review_sheet,
                "_sheet_row_count",
                return_value=review_sheet.MAX_SHEET_ROWS,
            ),
            mock.patch.object(
                review_sheet,
                "_write",
                side_effect=lambda *args: writes.append(args),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "自动整表迁移已禁用"):
                review_sheet.ensure_sheet()

        self.assertEqual(writes, [])


if __name__ == "__main__":
    unittest.main()

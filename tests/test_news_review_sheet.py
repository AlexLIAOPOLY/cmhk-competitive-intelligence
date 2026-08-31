import json
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import cmhk.intelligence.news_review_sheet as review_sheet
import strategic_briefing


class NewsReviewSheetSyncTests(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        temp_root = Path(self._temp_dir.name)
        for attribute, filename in (
            ("STATE_PATH", "state.json"),
            ("PUBLISHED_PATH", "published.json"),
            ("HISTORY_PATH", "history.json"),
            ("RETENTION_AUDIT_PATH", "retention.jsonl"),
        ):
            patcher = mock.patch.object(review_sheet, attribute, temp_root / filename)
            patcher.start()
            self.addCleanup(patcher.stop)
        self._spreadsheet_info_patch = mock.patch.object(
            review_sheet,
            "_spreadsheet_info",
            return_value={"data": {"sheets": []}},
        )
        self._spreadsheet_info_patch.start()
        self.addCleanup(self._spreadsheet_info_patch.stop)

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

    def test_lark_write_retries_nested_network_timeout_then_succeeds(self):
        transient = self._lark_result(
            {
                "ok": False,
                "error": {
                    "type": "network",
                    "subtype": "timeout",
                    "message": "dial tcp 198.18.0.52:443: connect: operation timed out",
                },
            },
            returncode=1,
        )
        success = self._lark_result({"ok": True, "data": {}})
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
                "+cells-set",
                retry_transient=True,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_write_many_uses_one_current_cells_set_batch(self):
        with mock.patch.object(review_sheet, "_lark") as lark:
            review_sheet._write_many(
                "sheet-1",
                [
                    ("A2:B2", [["接受", "不接受"]]),
                    ("A3:B3", [["不接受", "接受"]]),
                ],
                identity="bot",
                profile="bot-profile",
            )

        args = lark.call_args.args
        self.assertEqual(args[:2], ("sheets", "+cells-set"))
        writes = json.loads(args[args.index("--writes") + 1])
        self.assertEqual(len(writes), 2)
        self.assertEqual(writes[0]["sheet_id"], "sheet-1")
        self.assertEqual(writes[0]["cells"][0][0]["value"], "接受")
        self.assertFalse(lark.call_args.kwargs["retry_transient"])
        self.assertEqual(lark.call_args.kwargs["identity_override"], "bot")

    def test_single_write_disables_blind_transient_retry(self):
        with mock.patch.object(review_sheet, "_lark") as lark:
            review_sheet._write("sheet-1", "A2:A2", [["接受"]])

        self.assertFalse(lark.call_args.kwargs["retry_transient"])

    def test_human_screener_is_written_as_verified_native_mention_without_notification(self):
        before = self._existing_row()
        # Visible text alone is not proof of a clickable @ mention. This
        # legacy/plain cell must still be upgraded to native rich text.
        before[review_sheet.SCREENER_COLUMN_INDEX] = "廖望 Alex LIAO Wang"
        after = list(before)
        record_id = review_sheet._row_dict(before, 2)["news_id"]
        with (
            mock.patch.object(
                review_sheet,
                "_read_rows",
                side_effect=[[before], [before], [after]],
            ),
            mock.patch.object(
                review_sheet,
                "_screener_mention_tokens",
                side_effect=[{}, {2: {"ou_alex"}}],
            ),
            mock.patch.object(review_sheet, "_lark") as lark,
        ):
            result = review_sheet._write_review_sheet_screeners_locked(
                "sheet-1",
                [
                    {
                        "rowNumber": 2,
                        "recordId": record_id,
                        "name": "廖望 Alex LIAO Wang",
                        "mentionToken": "ou_alex",
                    }
                ],
            )

        args = lark.call_args.args
        writes = json.loads(args[args.index("--writes") + 1])
        mention = writes[0]["cells"][0][0]["rich_text"][0]
        self.assertEqual(writes[0]["range"], "A2")
        self.assertEqual(mention["type"], "mention")
        self.assertEqual(mention["text"], "廖望 Alex LIAO Wang")
        self.assertEqual(mention["mention_token"], "ou_alex")
        self.assertIs(mention["notify"], False)
        self.assertEqual(result["changedCount"], 1)
        self.assertEqual(result["verifiedCount"], 1)
        self.assertTrue(result["readbackVerified"])

    def test_native_screener_mention_reader_uses_real_row_indices_and_tokens(self):
        with mock.patch.object(
            review_sheet,
            "_lark",
            return_value={
                "ok": True,
                "data": {
                    "has_more": False,
                    "ranges": [{
                        "actual_range": "A314:A314",
                        "row_indices": [314],
                        "col_indices": ["A"],
                        "truncated": False,
                        "cells": [[{
                            "value": "廖望 Alex LIAO Wang",
                            "rich_text": [{
                                "type": "mention",
                                "text": "廖望 Alex LIAO Wang",
                                "mention_type": 0,
                                "mention_token": "ou_alex",
                                "notify": False,
                            }],
                        }]],
                    }],
                },
            },
        ) as lark:
            result = review_sheet._screener_mention_tokens(
                "sheet-1",
                [314],
                identity="user",
                profile="profile-1",
            )

        self.assertEqual(result, {314: {"ou_alex"}})
        self.assertIn("A314:A314", lark.call_args.args)
        self.assertTrue(lark.call_args.kwargs["retry_transient"])
        self.assertEqual(lark.call_args.kwargs["profile_override"], "profile-1")

    def test_ai_screener_is_written_as_plain_name_and_idempotent_after_readback(self):
        before = self._existing_row()
        after = list(before)
        after[review_sheet.SCREENER_COLUMN_INDEX] = "新闻自动初筛机器人"
        record_id = review_sheet._row_dict(before, 2)["news_id"]
        with (
            mock.patch.object(
                review_sheet,
                "_read_rows",
                side_effect=[[before], [before], [after]],
            ),
            mock.patch.object(review_sheet, "_lark") as lark,
        ):
            result = review_sheet._write_review_sheet_screeners_locked(
                "sheet-1",
                [{
                    "rowNumber": 2,
                    "recordId": record_id,
                    "name": "新闻自动初筛机器人",
                }],
            )

        args = lark.call_args.args
        writes = json.loads(args[args.index("--writes") + 1])
        self.assertEqual(
            writes[0]["cells"][0][0],
            {"value": "新闻自动初筛机器人"},
        )
        self.assertEqual(result["changedCount"], 1)

        with (
            mock.patch.object(review_sheet, "_read_rows", return_value=[after]),
            mock.patch.object(review_sheet, "_lark") as second_write,
        ):
            second = review_sheet._write_review_sheet_screeners_locked(
                "sheet-1",
                [{
                    "rowNumber": 2,
                    "recordId": record_id,
                    "name": "新闻自动初筛机器人",
                }],
            )
        second_write.assert_not_called()
        self.assertEqual(second["changedCount"], 0)
        self.assertEqual(second["verifiedCount"], 1)

    def test_screener_readback_does_not_accept_a_similar_but_different_person(self):
        self.assertFalse(review_sheet._screener_matches("@Alex", "Alexander"))
        self.assertTrue(
            review_sheet._screener_matches(
                "@廖望 Alex LIAO Wang",
                "廖望Alex LIAO Wang",
            )
        )

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
                "sheet!A5:O6",
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
            "",
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
        self.assertEqual([cell_range for cell_range, _ in sheet.writes], ["A2:O2"])
        self.assertEqual(
            sheet.writes[0][1][0][review_sheet.TITLE_COLUMN_INDEX],
            "今日新新闻",
        )
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
        existing[review_sheet.SEARCH_DATE_COLUMN_INDEX] = "2026-07-22"
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

        self.assertEqual(
            sheet.writes[0][1][0][review_sheet.TITLE_COLUMN_INDEX],
            "今日新新闻",
        )
        self.assertEqual(
            sheet.inserts,
            [{"start_index": 1, "count": 2, "separator_count": 1}],
        )
        self.assertFalse(any(sheet.rows[1]))
        self.assertEqual(sheet.rows[2][review_sheet.TITLE_COLUMN_INDEX], "历史新闻")

    def test_sorted_rows_keep_the_matching_selector_item_identity(self):
        older = self._new_item()
        newer = {
            **self._new_item(),
            "news_id": review_sheet._news_item_id(
                "https://example.com/newer",
                "较新候选",
            ),
            "url": "https://example.com/newer",
            "ai_title": "较新候选",
            "ai_summary": "日期较新的候选应排在前面且保持同一 news_id。",
            "source_date": "2026-07-23",
            "search_date": "2026-07-23",
        }
        sheet = self._LiveSheet([self._existing_row()])
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
                side_effect=lambda items, **_kwargs: items,
            ),
            mock.patch.object(
                strategic_briefing,
                "agent_semantic_deduplicate_candidates",
                side_effect=self._semantic_keep,
            ),
        ):
            result = review_sheet.sync_candidates([older, newer])

        written_rows = sheet.writes[0][1]
        self.assertEqual(
            [row[review_sheet.TITLE_COLUMN_INDEX] for row in written_rows],
            ["较新候选", "今日新新闻"],
        )
        self.assertEqual(
            [item["news_id"] for item in result["new_items"]],
            [newer["news_id"], older["news_id"]],
        )

    def test_sync_does_not_rewrite_existing_duplicate_rows(self):
        pending = self._existing_row()
        pending[review_sheet.APP_STATUS_COLUMN_INDEX] = "待审核"
        pending[review_sheet.SOURCE_URL_COLUMN_INDEX] = [
            {
                "link": "https://example.com/news/same-event",
                "text": "阅读原文",
                "type": "url",
            }
        ]
        rejected = list(pending)
        rejected[review_sheet.APP_STATUS_COLUMN_INDEX] = "不接受"
        rejected[review_sheet.TITLE_COLUMN_INDEX] = "同一事件的人工拒绝记录"
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
        self.assertEqual(
            sheet.rows[1][review_sheet.APP_STATUS_COLUMN_INDEX],
            "不接受",
        )
        self.assertEqual(
            sheet.rows[1][review_sheet.TITLE_COLUMN_INDEX],
            "同一事件的人工拒绝记录",
        )

    def test_sync_keeps_review_decisions_made_during_ai_pass(self):
        pending = self._existing_row()
        pending[review_sheet.APP_STATUS_COLUMN_INDEX] = "待审核"
        pending[review_sheet.WEEKLY_STATUS_COLUMN_INDEX] = "待审核"
        pending[review_sheet.SYNC_STATUS_COLUMN_INDEX] = "未同步"
        sheet = self._LiveSheet([pending])

        def polish(items, **_kwargs):
            sheet.rows[0][review_sheet.APP_STATUS_COLUMN_INDEX] = "接受"
            sheet.rows[0][review_sheet.WEEKLY_STATUS_COLUMN_INDEX] = "接受"
            sheet.rows[0][review_sheet.SYNC_STATUS_COLUMN_INDEX] = "未同步"
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

        written_titles = [
            row[review_sheet.TITLE_COLUMN_INDEX]
            for _range, rows in sheet.writes
            for row in rows
        ]
        self.assertNotIn("历史新闻", written_titles)
        self.assertEqual(
            [sheet.rows[3][column] for column in review_sheet.HUMAN_DECISION_COLUMNS],
            ["接受", "接受", "未同步"],
        )
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
        dashboard_publish = mock.Mock()
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
                "_schedule_public_dashboard_publish",
                dashboard_publish,
            ),
            mock.patch.object(
                review_sheet,
                "apply_reviews",
                return_value={"changed_rows": 0},
            ) as apply_reviews,
            mock.patch.object(
                review_sheet,
                "_maintain_review_history_and_retention",
                return_value={"status": "ok", "historyTotalRows": 277, "removedRows": 0},
            ),
        ):
            result = review_sheet.run_cycle()

        load_latest.assert_not_called()
        sync.assert_not_called()
        apply_reviews.assert_called_once_with("sheet")
        self.assertTrue(result["source_unchanged"])
        self.assertEqual(result["sheet_candidate_count"], 277)
        self.assertEqual(
            result["dashboard_publish"]["status"],
            "unchanged_no_publish",
        )
        dashboard_publish.assert_not_called()
        self.assertFalse(
            write_json.call_args.args[1]["group_notifications_paused"]
        )

    def test_run_cycle_publishes_when_review_state_changed(self):
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
        with (
            mock.patch.object(review_sheet, "_read_json", return_value=state),
            mock.patch.object(review_sheet, "_write_json"),
            mock.patch.object(
                review_sheet,
                "_current_source_generated_at",
                return_value="2026-07-27T09:41:27+08:00",
            ),
            mock.patch.object(
                review_sheet,
                "apply_reviews",
                return_value={"changed_rows": 1},
            ),
            mock.patch.object(
                review_sheet,
                "_maintain_review_history_and_retention",
                return_value={"status": "ok", "removedRows": 0},
            ),
            mock.patch.object(
                review_sheet,
                "_schedule_public_dashboard_publish",
                return_value={"status": "started", "pid": 123},
            ) as dashboard_publish,
        ):
            result = review_sheet.run_cycle()

        self.assertTrue(result["source_unchanged"])
        self.assertEqual(result["dashboard_publish"]["status"], "started")
        dashboard_publish.assert_called_once_with()

    def test_retention_failure_does_not_break_verified_review_sync(self):
        state = {
            "last_poll_epoch": 0,
            "last_source_generated_at": "2026-08-30T07:30:00+08:00",
            "last_source_summary": {
                "generated_at": "2026-08-30T07:30:00+08:00",
                "candidate_count": 5,
            },
            "sheet_id": "sheet",
            "sheet_url": "https://example.com/sheet",
            "last_candidate_count": 5,
        }
        with (
            mock.patch.object(review_sheet, "_read_json", return_value=state),
            mock.patch.object(review_sheet, "_write_json"),
            mock.patch.object(
                review_sheet,
                "_current_source_generated_at",
                return_value="2026-08-30T07:30:00+08:00",
            ),
            mock.patch.object(
                review_sheet,
                "apply_reviews",
                return_value={"changed_rows": 0, "readback_verified": True},
            ),
            mock.patch.object(
                review_sheet,
                "_maintain_review_history_and_retention",
                side_effect=RuntimeError("retention unavailable"),
            ),
        ):
            result = review_sheet.run_cycle(schedule_dashboard_publish=False)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["retention"]["status"], "failed")
        self.assertIn("retention unavailable", result["retention"]["error"])

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
                    "new_items": [{"news_id": "NEWS-NEW", "title": "new"}],
                },
            ),
            mock.patch.object(
                review_sheet,
                "apply_reviews",
                return_value={"changed_rows": 0},
            ),
            mock.patch.object(
                review_sheet,
                "_maintain_review_history_and_retention",
                return_value={"status": "ok", "historyTotalRows": 471, "removedRows": 0},
            ),
        ):
            result = review_sheet.run_cycle(schedule_dashboard_publish=False)

        self.assertTrue(result["readback_verified"])
        self.assertEqual(result["selection_batch_key"], "2026-08-06@09:00")
        self.assertTrue(result["selection_agent_pending"])
        self.assertIn(
            "2026-08-06@09:00",
            state_holder["value"][review_sheet.PENDING_SELECTION_BATCHES_STATE_KEY],
        )
        receipts = state_holder["value"][
            review_sheet.SUCCESSFUL_CYCLE_RESULTS_STATE_KEY
        ]
        self.assertTrue(receipts["2026-08-06@09:00"]["readback_verified"])
        self.assertNotIn(
            review_sheet.PENDING_CYCLE_STATE_KEY,
            state_holder["value"],
        )

    def test_pending_selection_receipts_are_not_silently_evicted(self):
        state_holder = {"value": {}}

        def read_state(_path, _default):
            return dict(state_holder["value"])

        def write_state(_path, payload):
            state_holder["value"] = dict(payload)

        with (
            mock.patch.object(review_sheet, "_read_json", side_effect=read_state),
            mock.patch.object(review_sheet, "_write_json", side_effect=write_state),
        ):
            for index in range(review_sheet.MAX_PENDING_SELECTION_BATCHES + 1):
                review_sheet._register_pending_selection_batch(
                    new_items=[{"news_id": f"NEWS-{index}"}],
                    sheet_id="sheet",
                    generated_at="2026-08-30T10:00:00+08:00",
                )

        batches = state_holder["value"][
            review_sheet.PENDING_SELECTION_BATCHES_STATE_KEY
        ]
        self.assertEqual(len(batches), review_sheet.MAX_PENDING_SELECTION_BATCHES + 1)

    def test_pending_selection_receipt_requires_verified_completion(self):
        state_holder = {"value": {}}

        def read_state(_path, _default):
            return dict(state_holder["value"])

        def write_state(_path, payload):
            state_holder["value"] = dict(payload)

        with (
            mock.patch.object(review_sheet, "_read_json", side_effect=read_state),
            mock.patch.object(review_sheet, "_write_json", side_effect=write_state),
        ):
            batch_key = review_sheet._register_pending_selection_batch(
                new_items=[{"news_id": "NEWS-1"}],
                sheet_id="sheet",
                generated_at="2026-08-30T10:00:00+08:00",
            )
            review_sheet.fail_selection_batch(
                batch_key,
                "temporary failure",
                attempted_at="2026-08-30T10:01:00+08:00",
            )
            pending = review_sheet.pending_selection_batches(limit=1)[0]
            self.assertEqual(pending["status"], "retry_pending")
            self.assertEqual(pending["attempt_count"], 1)
            with self.assertRaisesRegex(ValueError, "未完成回读"):
                review_sheet.complete_selection_batch(
                    batch_key,
                    {"status": "completed", "readback_verified": False},
                )
            review_sheet.complete_selection_batch(
                batch_key,
                {"status": "completed", "readback_verified": True},
            )

        self.assertEqual(review_sheet.PENDING_SELECTION_BATCHES_STATE_KEY in state_holder["value"], True)
        self.assertEqual(
            state_holder["value"][review_sheet.PENDING_SELECTION_BATCHES_STATE_KEY],
            {},
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
        row[review_sheet.APP_STATUS_COLUMN_INDEX] = "不接受"
        row[review_sheet.WEEKLY_STATUS_COLUMN_INDEX] = "接受"

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
        row[review_sheet.SOURCE_URL_COLUMN_INDEX] = [
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
                row[review_sheet.TITLE_COLUMN_INDEX],
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
        included[review_sheet.APP_STATUS_COLUMN_INDEX] = "待审核"
        included[review_sheet.WEEKLY_STATUS_COLUMN_INDEX] = "接受"
        included[review_sheet.SEARCH_DATE_COLUMN_INDEX] = "2026-07-24"
        included[review_sheet.SOURCE_DATE_COLUMN_INDEX] = "2026-07-24"
        outside = list(included)
        outside[review_sheet.TITLE_COLUMN_INDEX] = "窗口外新闻"
        outside[review_sheet.SOURCE_DATE_COLUMN_INDEX] = "2026-07-17"
        outside[review_sheet.SOURCE_URL_COLUMN_INDEX] = "https://example.com/outside"
        pending = list(included)
        pending[review_sheet.WEEKLY_STATUS_COLUMN_INDEX] = "待审核"
        pending[review_sheet.TITLE_COLUMN_INDEX] = "未选择新闻"
        pending[review_sheet.SOURCE_URL_COLUMN_INDEX] = "https://example.com/pending"
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

    def test_retention_plan_uses_day_fifteen_and_either_acceptance(self):
        def candidate(
            search_date: str,
            title: str,
            *,
            app_status: str = "待审核",
            weekly_status: str = "待审核",
        ) -> list[str]:
            row = self._existing_row()
            row[review_sheet.APP_STATUS_COLUMN_INDEX] = app_status
            row[review_sheet.WEEKLY_STATUS_COLUMN_INDEX] = weekly_status
            row[review_sheet.SEARCH_DATE_COLUMN_INDEX] = search_date
            row[review_sheet.TITLE_COLUMN_INDEX] = title
            row[review_sheet.SOURCE_URL_COLUMN_INDEX] = f"https://example.com/{title}"
            return row

        rows = [
            candidate("2026-08-16", "age-14"),
            candidate("2026-08-15", "age-15"),
            candidate("2026-08-01", "app-accepted", app_status="接受"),
            candidate("2026-08-01", "weekly-accepted", weekly_status="接受"),
            candidate("", "missing-date"),
        ]

        plan, warnings = review_sheet._retention_plan(
            rows,
            today_hkt=date(2026, 8, 30),
        )

        self.assertEqual([item["title"] for item in plan], ["age-15"])
        self.assertEqual(plan[0]["age_days"], 15)
        self.assertEqual(warnings[0]["title"], "missing-date")
        self.assertEqual(
            warnings[0]["reason"],
            "missing_or_invalid_search_date_kept",
        )

    def test_retention_mirrors_complete_rows_before_whole_row_delete_and_readback(self):
        expired = self._existing_row()
        expired[review_sheet.APP_STATUS_COLUMN_INDEX] = "不接受"
        expired[review_sheet.WEEKLY_STATUS_COLUMN_INDEX] = "待审核"
        expired[review_sheet.SEARCH_DATE_COLUMN_INDEX] = "2026-08-15"
        expired[review_sheet.TITLE_COLUMN_INDEX] = "满十五天未接受"
        expired[review_sheet.SOURCE_URL_COLUMN_INDEX] = "https://example.com/expired"
        accepted = self._existing_row()
        accepted[review_sheet.APP_STATUS_COLUMN_INDEX] = "待审核"
        accepted[review_sheet.WEEKLY_STATUS_COLUMN_INDEX] = "接受"
        accepted[review_sheet.SEARCH_DATE_COLUMN_INDEX] = "2026-08-01"
        accepted[review_sheet.TITLE_COLUMN_INDEX] = "周报已接受"
        accepted[review_sheet.SOURCE_URL_COLUMN_INDEX] = "https://example.com/weekly-kept"
        recent = self._existing_row()
        recent[review_sheet.APP_STATUS_COLUMN_INDEX] = "待审核"
        recent[review_sheet.WEEKLY_STATUS_COLUMN_INDEX] = "待审核"
        recent[review_sheet.SEARCH_DATE_COLUMN_INDEX] = "2026-08-16"
        recent[review_sheet.TITLE_COLUMN_INDEX] = "尚未满十五天"
        recent[review_sheet.SOURCE_URL_COLUMN_INDEX] = "https://example.com/recent"
        review_sheet._write_json(
            review_sheet.STATE_PATH,
            {"sheet_id": "sheet", "sheet_title": "候选池"},
        )

        with (
            mock.patch.object(
                review_sheet,
                "_read_rows",
                side_effect=[
                    [expired, accepted, recent],
                    [expired, accepted, recent],
                    [accepted, recent],
                ],
            ),
            mock.patch.object(review_sheet, "_delete_sheet_row_range") as delete_rows,
        ):
            result = review_sheet._maintain_review_history_and_retention(
                active_sheet_id="sheet",
                force=True,
                today_hkt=date(2026, 8, 30),
            )

        delete_rows.assert_called_once_with(
            "sheet",
            2,
            2,
            identity="",
            profile="",
        )
        self.assertEqual(result["removedRows"], 1)
        self.assertEqual(result["historyTotalRows"], 3)
        history = review_sheet._review_history_payload()["records"]
        expired_id = review_sheet._row_dict(expired, 2)["news_id"]
        accepted_id = review_sheet._row_dict(accepted, 3)["news_id"]
        self.assertFalse(history[expired_id]["feishu_visible"])
        self.assertEqual(history[expired_id]["values"], expired)
        self.assertTrue(history[accepted_id]["feishu_visible"])
        audit_events = [
            json.loads(line)
            for line in review_sheet.RETENTION_AUDIT_PATH.read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        self.assertEqual([item["event"] for item in audit_events], ["planned", "verified"])
        saved_state = review_sheet._read_json(review_sheet.STATE_PATH, {})
        self.assertEqual(saved_state[review_sheet.RETENTION_STATE_DATE_KEY], "2026-08-30")
        self.assertIn(expired_id, saved_state["archived_news_ids"])

    def test_retention_aborts_when_decision_changes_between_preflight_reads(self):
        pending = self._existing_row()
        pending[review_sheet.APP_STATUS_COLUMN_INDEX] = "待审核"
        pending[review_sheet.WEEKLY_STATUS_COLUMN_INDEX] = "待审核"
        pending[review_sheet.SEARCH_DATE_COLUMN_INDEX] = "2026-08-01"
        accepted = list(pending)
        accepted[review_sheet.APP_STATUS_COLUMN_INDEX] = "接受"
        review_sheet._write_json(
            review_sheet.STATE_PATH,
            {"sheet_id": "sheet", "sheet_title": "候选池"},
        )
        with (
            mock.patch.object(
                review_sheet,
                "_read_rows",
                side_effect=[[pending], [accepted]],
            ),
            mock.patch.object(review_sheet, "_delete_sheet_row_range") as delete_rows,
        ):
            with self.assertRaisesRegex(RuntimeError, "发生变化"):
                review_sheet._maintain_review_history_and_retention(
                    active_sheet_id="sheet",
                    force=True,
                    today_hkt=date(2026, 8, 30),
                )
        delete_rows.assert_not_called()
        self.assertEqual(len(review_sheet._review_history_payload()["records"]), 1)

    def test_retention_dry_run_mirrors_and_plans_without_mutating_feishu(self):
        expired = self._existing_row()
        expired[review_sheet.APP_STATUS_COLUMN_INDEX] = "待审核"
        expired[review_sheet.WEEKLY_STATUS_COLUMN_INDEX] = "不接受"
        expired[review_sheet.SEARCH_DATE_COLUMN_INDEX] = "2026-08-01"
        review_sheet._write_json(
            review_sheet.STATE_PATH,
            {"sheet_id": "sheet", "sheet_title": "候选池"},
        )
        with (
            mock.patch.object(
                review_sheet,
                "_read_rows",
                side_effect=[[expired], [expired]],
            ),
            mock.patch.object(review_sheet, "_delete_sheet_row_range") as delete_rows,
        ):
            result = review_sheet._maintain_review_history_and_retention(
                active_sheet_id="sheet",
                force=True,
                dry_run=True,
                today_hkt=date(2026, 8, 30),
            )

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["plannedRows"], 1)
        self.assertEqual(result["removedRows"], 0)
        delete_rows.assert_not_called()
        self.assertFalse(review_sheet.RETENTION_AUDIT_PATH.exists())
        self.assertEqual(len(review_sheet._review_history_payload()["records"]), 1)
        state = review_sheet._read_json(review_sheet.STATE_PATH, {})
        self.assertNotIn(review_sheet.RETENTION_STATE_DATE_KEY, state)

    def test_retention_accepts_ambiguous_delete_only_after_full_readback(self):
        expired = self._existing_row()
        expired[review_sheet.APP_STATUS_COLUMN_INDEX] = "不接受"
        expired[review_sheet.WEEKLY_STATUS_COLUMN_INDEX] = "待审核"
        expired[review_sheet.SEARCH_DATE_COLUMN_INDEX] = "2026-08-01"
        review_sheet._write_json(
            review_sheet.STATE_PATH,
            {"sheet_id": "sheet", "sheet_title": "候选池"},
        )
        with (
            mock.patch.object(
                review_sheet,
                "_read_rows",
                side_effect=[[expired], [expired], []],
            ),
            mock.patch.object(
                review_sheet,
                "_delete_sheet_row_range",
                side_effect=RuntimeError("timeout after server applied delete"),
            ),
        ):
            result = review_sheet._maintain_review_history_and_retention(
                active_sheet_id="sheet",
                force=True,
                today_hkt=date(2026, 8, 30),
            )

        self.assertEqual(result["removedRows"], 1)
        events = [
            json.loads(line)["event"]
            for line in review_sheet.RETENTION_AUDIT_PATH.read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        self.assertEqual(
            events,
            ["planned", "write_error_readback_verified", "verified"],
        )

    def test_partial_retention_records_deleted_ids_and_current_count_before_retry(self):
        first = self._existing_row()
        first[review_sheet.APP_STATUS_COLUMN_INDEX] = "待审核"
        first[review_sheet.WEEKLY_STATUS_COLUMN_INDEX] = "待审核"
        first[review_sheet.SEARCH_DATE_COLUMN_INDEX] = "2026-08-01"
        first[review_sheet.TITLE_COLUMN_INDEX] = "较低行待删"
        first[review_sheet.SOURCE_URL_COLUMN_INDEX] = "https://example.com/first-expired"
        survivor = self._existing_row()
        survivor[review_sheet.APP_STATUS_COLUMN_INDEX] = "接受"
        survivor[review_sheet.WEEKLY_STATUS_COLUMN_INDEX] = "待审核"
        survivor[review_sheet.SEARCH_DATE_COLUMN_INDEX] = "2026-08-01"
        survivor[review_sheet.TITLE_COLUMN_INDEX] = "接受保留"
        survivor[review_sheet.SOURCE_URL_COLUMN_INDEX] = "https://example.com/survivor"
        second = self._existing_row()
        second[review_sheet.APP_STATUS_COLUMN_INDEX] = "不接受"
        second[review_sheet.WEEKLY_STATUS_COLUMN_INDEX] = "暂缓"
        second[review_sheet.SEARCH_DATE_COLUMN_INDEX] = "2026-08-01"
        second[review_sheet.TITLE_COLUMN_INDEX] = "较高行待删"
        second[review_sheet.SOURCE_URL_COLUMN_INDEX] = "https://example.com/second-expired"
        review_sheet._write_json(
            review_sheet.STATE_PATH,
            {"sheet_id": "sheet", "sheet_title": "候选池", "last_candidate_count": 3},
        )
        with (
            mock.patch.object(
                review_sheet,
                "_read_rows",
                side_effect=[
                    [first, survivor, second],
                    [first, survivor, second],
                    [first, survivor],
                ],
            ),
            mock.patch.object(
                review_sheet,
                "_delete_sheet_row_range",
                side_effect=[None, RuntimeError("second range timeout")],
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "未完整确认"):
                review_sheet._maintain_review_history_and_retention(
                    active_sheet_id="sheet",
                    force=True,
                    today_hkt=date(2026, 8, 30),
                )

        second_id = review_sheet._row_dict(second, 4)["news_id"]
        state = review_sheet._read_json(review_sheet.STATE_PATH, {})
        self.assertIn(second_id, state["archived_news_ids"])
        self.assertEqual(state["last_candidate_count"], 2)
        self.assertNotIn(review_sheet.RETENTION_STATE_DATE_KEY, state)
        history = review_sheet._review_history_payload()["records"]
        self.assertFalse(history[second_id]["feishu_visible"])

    def test_weekly_report_uses_local_history_after_sheet_rollover(self):
        accepted = self._existing_row()
        accepted[review_sheet.APP_STATUS_COLUMN_INDEX] = "不接受"
        accepted[review_sheet.WEEKLY_STATUS_COLUMN_INDEX] = "接受"
        accepted[review_sheet.SEARCH_DATE_COLUMN_INDEX] = "2026-08-20"
        accepted[review_sheet.SOURCE_DATE_COLUMN_INDEX] = "2026-08-20"
        accepted[review_sheet.TITLE_COLUMN_INDEX] = "已归档但仍纳入周报"
        accepted[review_sheet.SOURCE_URL_COLUMN_INDEX] = "https://example.com/archived-weekly"
        review_sheet._upsert_review_history_rows(
            sheet_id="old-sheet",
            sheet_title="旧候选池",
            rows=[accepted],
            active_sheet_id="new-sheet",
        )
        review_sheet._write_json(
            review_sheet.STATE_PATH,
            {
                "sheet_id": "new-sheet",
                "sheet_title": "新候选池",
                "archive_parts": [
                    {"sheet_id": "old-sheet", "sheet_title": "旧候选池"}
                ],
            },
        )
        with (
            mock.patch.object(review_sheet, "ensure_sheet", return_value="new-sheet"),
            mock.patch.object(review_sheet, "_read_rows", return_value=[]),
        ):
            rows, audit = review_sheet.load_weekly_report_candidates(
                "2026-08-18",
                "2026-08-24",
            )

        self.assertEqual([row["title"] for row in rows], ["已归档但仍纳入周报"])
        self.assertEqual(rows[0]["storage_source"], "local_history")
        self.assertEqual(audit["sheetRows"], 0)
        self.assertEqual(audit["localHistoryRows"], 1)

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
        migrated = ["", legacy[0], "待审核", *legacy[1:], ""]

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

        self.assertEqual(
            normalized,
            (shifted + [""])[: len(review_sheet.HEADERS)],
        )
        with self.assertRaisesRegex(RuntimeError, "检索日期不在E列"):
            review_sheet._validate_sheet_rows(
                [normalized],
                context="测试表",
            )

    def test_sheet_schema_accepts_complete_current_row(self):
        review_sheet._validate_sheet_rows(
            [self._existing_row()],
            context="测试表",
        )

    def test_system_only_separator_artifact_is_quarantined(self):
        artifact = [""] * len(review_sheet.HEADERS)
        artifact[review_sheet.SCREENER_COLUMN_INDEX] = "新闻自动初筛机器人"
        artifact[review_sheet.SYNC_STATUS_COLUMN_INDEX] = "未同步"

        review_sheet._validate_sheet_rows([artifact], context="测试表")
        self.assertTrue(review_sheet._is_system_only_review_row(artifact))
        plan, warnings = review_sheet._retention_plan(
            [artifact], today_hkt=date(2026, 8, 31)
        )
        self.assertEqual(plan, [])
        self.assertEqual(warnings, [])

    def test_screener_write_relocates_by_record_id_after_row_insert(self):
        target = self._existing_row()
        record_id = review_sheet._row_dict(target, 2)["news_id"]
        blank = [""] * len(review_sheet.HEADERS)
        moved = [blank, target]
        written = [blank, list(target)]
        written[1][review_sheet.SCREENER_COLUMN_INDEX] = "新闻自动初筛机器人"
        with (
            mock.patch.object(
                review_sheet,
                "_read_rows",
                side_effect=[[target], moved, written],
            ),
            mock.patch.object(review_sheet, "_lark") as lark,
        ):
            result = review_sheet._write_review_sheet_screeners_locked(
                "sheet-1",
                [{
                    "rowNumber": 2,
                    "recordId": record_id,
                    "name": "新闻自动初筛机器人",
                }],
            )

        writes = json.loads(
            lark.call_args.args[lark.call_args.args.index("--writes") + 1]
        )
        self.assertEqual(writes[0]["range"], "A3")
        self.assertEqual(result["verifiedCount"], 1)

    def test_apply_reviews_never_overwrites_human_decision_when_gate_blocks(self):
        accepted = self._existing_row()
        accepted[review_sheet.APP_STATUS_COLUMN_INDEX] = "接受"
        accepted[review_sheet.SYNC_STATUS_COLUMN_INDEX] = "已纳入"
        writes = []

        def write_many(sheet, regions, **_kwargs):
            writes.extend((sheet, cell_range, values) for cell_range, values in regions)
            accepted[review_sheet.SYNC_STATUS_COLUMN_INDEX] = "同步失败"

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
                "_write_many",
                side_effect=write_many,
            ),
        ):
            result = review_sheet.apply_reviews("sheet")

        self.assertEqual(writes, [("sheet", "D2:D2", [["同步失败"]])])
        self.assertEqual(result["requested_accept_count"], 1)
        self.assertEqual(result["blocked_accept_count"], 1)
        self.assertEqual(result["rejected_count"], 0)
        self.assertEqual(
            result["blocked_reviews"][0]["reason"],
            "缺少可验证发布日期",
        )

    def test_apply_reviews_restores_precise_gate_metadata_after_sheet_round_trip(self):
        accepted = self._existing_row()
        accepted[review_sheet.APP_STATUS_COLUMN_INDEX] = "接受"
        accepted[review_sheet.SYNC_STATUS_COLUMN_INDEX] = "同步失败"
        accepted[review_sheet.SEARCH_DATE_COLUMN_INDEX] = "2026-07-30"
        accepted[review_sheet.TITLE_COLUMN_INDEX] = "香港电讯上半年多赚4%至21.5亿"
        accepted[review_sheet.SOURCE_DATE_COLUMN_INDEX] = "2026-07-29"
        accepted[review_sheet.SOURCE_URL_COLUMN_INDEX] = (
            "https://example.com/hkt-interim-results"
        )
        metadata_key = review_sheet._gate_metadata_key(
            accepted[review_sheet.SOURCE_URL_COLUMN_INDEX]
        )
        writes = []
        published_payloads = []

        def write_many(sheet, regions, **_kwargs):
            writes.extend((sheet, cell_range, values) for cell_range, values in regions)
            accepted[review_sheet.SYNC_STATUS_COLUMN_INDEX] = "已纳入"

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
                "_write_many",
                side_effect=write_many,
            ),
        ):
            result = review_sheet.apply_reviews("sheet")

        self.assertEqual(result["accepted_count"], 1)
        self.assertEqual(result["blocked_accept_count"], 0)
        self.assertEqual(writes, [("sheet", "D2:D2", [["已纳入"]])])
        published = next(
            payload
            for path, payload in published_payloads
            if path == review_sheet.PUBLISHED_PATH
        )
        self.assertEqual(
            published["items"][0]["published_at"],
            "2026-07-29T17:16:00+08:00",
        )
        self.assertEqual(published["items"][0]["approval_sheet_id"], "sheet")

    def test_apply_reviews_reconciles_timeout_that_already_landed_before_publishing(self):
        accepted = self._existing_row()
        accepted[review_sheet.APP_STATUS_COLUMN_INDEX] = "接受"
        accepted[review_sheet.SYNC_STATUS_COLUMN_INDEX] = "未同步"
        events = []

        def read_rows(*_args, **_kwargs):
            events.append(("read", accepted[review_sheet.SYNC_STATUS_COLUMN_INDEX]))
            return [list(accepted)]

        def write_many(*_args, **_kwargs):
            events.append(("write", accepted[review_sheet.SYNC_STATUS_COLUMN_INDEX]))
            accepted[review_sheet.SYNC_STATUS_COLUMN_INDEX] = "已纳入"
            raise RuntimeError("request timeout")

        def write_json(path, _payload):
            if path == review_sheet.PUBLISHED_PATH:
                events.append(
                    ("publish", accepted[review_sheet.SYNC_STATUS_COLUMN_INDEX])
                )

        with (
            mock.patch.object(review_sheet, "_read_rows", side_effect=read_rows),
            mock.patch.object(
                review_sheet,
                "_read_json",
                return_value={"items": []},
            ),
            mock.patch.object(review_sheet, "_write_json", side_effect=write_json),
            mock.patch.object(
                review_sheet,
                "_review_news_candidate",
                return_value=(True, "通过"),
            ),
            mock.patch.object(
                review_sheet,
                "_write_many",
                side_effect=write_many,
            ) as write,
            mock.patch.object(review_sheet.time, "sleep") as sleep,
        ):
            result = review_sheet.apply_reviews("sheet")

        write.assert_called_once()
        sleep.assert_not_called()
        self.assertTrue(result["sync_status_readback_verified"])
        self.assertEqual(result["sync_status_verified_count"], 1)
        self.assertEqual(events[-1], ("publish", "已纳入"))
        self.assertEqual([event[0] for event in events], ["read", "write", "read", "publish"])

    def test_apply_reviews_stops_on_sync_status_conflict_without_local_publish(self):
        accepted = self._existing_row()
        accepted[review_sheet.APP_STATUS_COLUMN_INDEX] = "接受"
        accepted[review_sheet.SYNC_STATUS_COLUMN_INDEX] = "未同步"

        def write_many(*_args, **_kwargs):
            accepted[review_sheet.SYNC_STATUS_COLUMN_INDEX] = "人工覆盖"
            raise RuntimeError("request timeout")

        with (
            mock.patch.object(
                review_sheet,
                "_read_rows",
                side_effect=lambda *_args, **_kwargs: [list(accepted)],
            ),
            mock.patch.object(
                review_sheet,
                "_read_json",
                return_value={"items": []},
            ),
            mock.patch.object(review_sheet, "_write_json") as write_json,
            mock.patch.object(
                review_sheet,
                "_review_news_candidate",
                return_value=(True, "通过"),
            ),
            mock.patch.object(
                review_sheet,
                "_write_many",
                side_effect=write_many,
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "被其他操作修改"):
                review_sheet.apply_reviews("sheet")

        write_json.assert_not_called()

    def test_apply_reviews_preserves_pre_rollover_ticker_items(self):
        published_payloads = []
        archived_item = {
            "id": "NEWS-ARCHIVED",
            "title": "已在上一分卷审核的快讯",
            "summary": "分卷后仍应在驾驶舱展示。",
            "category": "竞对动态",
            "source_url": "https://example.com/archived",
            "published_at": "2026-08-25T09:00:00+08:00",
            "approval_source": review_sheet.SHEET_SOURCE,
        }

        def read_json(path, default):
            if path == review_sheet.STATE_PATH:
                return {"archive_parts": [{"sheet_id": "old-sheet"}]}
            return {"items": [archived_item]}

        with (
            mock.patch.object(review_sheet, "_read_rows", return_value=[]),
            mock.patch.object(review_sheet, "_read_json", side_effect=read_json),
            mock.patch.object(
                review_sheet,
                "_write_json",
                side_effect=lambda path, payload: published_payloads.append(
                    (path, payload)
                ),
            ),
        ):
            result = review_sheet.apply_reviews("new-sheet")

        self.assertEqual(result["accepted_count"], 0)
        self.assertEqual(result["published_count"], 1)
        published = next(
            payload
            for path, payload in published_payloads
            if path == review_sheet.PUBLISHED_PATH
        )
        self.assertEqual(published["items"], [archived_item])

    def test_apply_reviews_removes_unselected_item_from_active_part(self):
        active_item = {
            "id": "NEWS-ACTIVE",
            "title": "当前分卷的快讯",
            "source_url": "https://example.com/active",
            "published_at": "2026-08-26T09:00:00+08:00",
            "approval_source": review_sheet.SHEET_SOURCE,
            "approval_sheet_id": "new-sheet",
        }
        published_payloads = []

        def read_json(path, default):
            if path == review_sheet.STATE_PATH:
                return {"archive_parts": [{"sheet_id": "old-sheet"}]}
            return {"items": [active_item]}

        with (
            mock.patch.object(review_sheet, "_read_rows", return_value=[]),
            mock.patch.object(review_sheet, "_read_json", side_effect=read_json),
            mock.patch.object(
                review_sheet,
                "_write_json",
                side_effect=lambda path, payload: published_payloads.append(
                    (path, payload)
                ),
            ),
        ):
            result = review_sheet.apply_reviews("new-sheet")

        self.assertEqual(result["accepted_count"], 0)
        published = next(
            payload
            for path, payload in published_payloads
            if path == review_sheet.PUBLISHED_PATH
        )
        self.assertEqual(published["items"], [])

    def test_cross_day_sheet_row_without_precise_metadata_stays_blocked(self):
        accepted = self._existing_row()
        accepted[review_sheet.APP_STATUS_COLUMN_INDEX] = "接受"
        accepted[review_sheet.SYNC_STATUS_COLUMN_INDEX] = "同步失败"
        accepted[review_sheet.SEARCH_DATE_COLUMN_INDEX] = "2026-07-30"
        accepted[review_sheet.SOURCE_DATE_COLUMN_INDEX] = "2026-07-29"
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

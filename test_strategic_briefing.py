import io
import json
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import strategic_briefing as briefing


class StrategicBriefingTests(unittest.TestCase):
    def setUp(self):
        critic = mock.patch.object(
            briefing, "AI_EDITOR_CRITIC_ENABLED", False
        )
        critic.start()
        self.addCleanup(critic.stop)

    def test_obvious_mismatch_gate_rejects_only_fully_ungrounded_5g_match(self):
        reason = briefing._obvious_mismatch_exclusion_reason(
            {
                "title": "印度三大油企转向美国LPG寻求能源供应多元化",
                "snippet": "企业计划采购液化石油气以分散能源来源。",
                "module": "基础设施/网络/技术类",
                "keywords": "5G-Advanced、5.5G、6G R&D、5G",
            },
            {"should_include": True, "keywords": "5G-Advanced、5G"},
        )

        self.assertIn("移动通信监控词无正文证据", reason)

    def test_prompt_leak_title_recovers_chinese_news_fragment(self):
        result = briefing._validated_ai_copy(
            {
                "title": "我们需要回答合法JSON。需要判断。输入新闻：中国移动上半年营收增长",
                "summary": "中国移动公布上半年经营数据，算力与智能服务成为增长动能。",
                "should_include": True,
                "region": "国际/行业",
                "category": "竞对动态",
                "keywords": "China Mobile",
                "inclusion_reason": "中国移动发布半年报，可对标竞对经营表现。",
                "region_reason": "事件主体位于内地市场。",
                "decision_path": "竞对直通",
                "signal_type": "竞对经营动作",
                "business_impact": "竞争格局",
                "exclusion_code": "无",
            },
            require_review_fields=True,
            require_decision_fields=True,
            allowed_keywords=["China Mobile"],
            source_item={
                "source_title": "China Mobile first-half results",
                "source_summary": "China Mobile reported first-half revenue growth.",
            },
        )
        self.assertEqual(result["title"], "中国移动上半年营收增长")
        self.assertNotIn("合法JSON", result["title"])
        self.assertNotIn("输入新闻", result["title"])

    def test_english_prompt_leak_title_is_rejected_instead_of_published(self):
        with self.assertRaisesRegex(RuntimeError, "标题含提示词"):
            briefing._validated_ai_copy(
                {
                    "title": "我们需要回答合法JSON。需要判断。输入新闻：PLDT eyes Southern Luzon",
                    "summary": "我们需要回答合法JSON。需要判断。输入新闻：PLDT eyes Southern Luzon for largest data center.",
                    "should_include": True,
                    "region": "国际/行业",
                    "category": "基础设施/网络/技术类",
                    "keywords": "data center",
                    "inclusion_reason": "涉及数据中心投资。",
                    "region_reason": "事件发生在菲律宾。",
                    "decision_path": "战略信号",
                    "signal_type": "关键技术",
                    "business_impact": "资本配置",
                    "exclusion_code": "无",
                },
                require_review_fields=True,
                require_decision_fields=True,
                allowed_keywords=["data center"],
                source_item={
                    "source_title": "PLDT eyes Southern Luzon for largest data center amid AI boom",
                    "source_summary": "PLDT is considering Southern Luzon for a data center.",
                },
            )

    def test_program_listing_title_is_excluded_from_review_sheet(self):
        reason = briefing._obvious_mismatch_exclusion_reason(
            {
                "source_title": "第一台|太阳底下新鲜事|16/08/2026",
                "title": "第一台|太阳底下新鲜事|16/08/2026",
                "snippet": "香港电台节目时间表。",
                "module": "竞争对手",
                "keywords": "HKT、香港电讯",
            },
            {
                "should_include": True,
                "title": "第一台|太阳底下新鲜事|16/08/2026",
                "summary": "香港电台节目介绍。",
                "keywords": "HKT",
            },
        )
        self.assertIn("节目单", reason)

    def test_obvious_mismatch_gate_preserves_ungrounded_but_plausibly_useful_news(self):
        cases = [
            {
                "title": "FCC称Starlink在美用户超700万",
                "snippet": "SpaceX卫星互联网订阅用户大幅增长。",
                "module": "竞争对手",
                "keywords": "AT&T、Verizon、T-Mobile",
            },
            {
                "title": "An airline leaked my passport online",
                "snippet": "Passenger passport details were exposed by an airline.",
                "module": "政策/法规类",
                "keywords": "Personal Data、跨境数据流动",
            },
            {
                "title": "2026 OCP APAC Summit | Microsoft | From Silicon to Systems",
                "snippet": "Microsoft discusses infrastructure design at OCP APAC.",
                "module": "基础设施/网络/技术类",
                "keywords": "CPU、5G-Advanced",
            },
        ]

        for source_item in cases:
            with self.subTest(title=source_item["title"]):
                self.assertEqual(
                    briefing._obvious_mismatch_exclusion_reason(
                        source_item,
                        {
                            "should_include": True,
                            "keywords": source_item["keywords"],
                        },
                    ),
                    "",
                )

    def test_obvious_mismatch_gate_preserves_grounded_keyword_edge_news(self):
        reason = briefing._obvious_mismatch_exclusion_reason(
            {
                "title": "DFI集团与GNC扩大合作至新加坡成港澳星独家分销商",
                "snippet": "合作覆盖港澳及新加坡市场。",
                "module": "行业动态",
                "keywords": "港澳",
            },
            {"should_include": True, "keywords": "港澳"},
        )

        self.assertEqual(reason, "")

    def test_obvious_mismatch_gate_preserves_independent_ai_signal(self):
        reason = briefing._obvious_mismatch_exclusion_reason(
            {
                "title": "字节跳动AI工具豆包推荐酒店抽取12%佣金引争议",
                "snippet": "AI平台商业化佣金模式受到质疑。",
                "module": "竞争对手",
                "keywords": "HGC、SmarTone",
            },
            {"should_include": True, "keywords": "HGC、SmarTone"},
        )

        self.assertEqual(reason, "")

    def test_obvious_mismatch_gate_never_removes_confirmed_competitor(self):
        reason = briefing._obvious_mismatch_exclusion_reason(
            {
                "title": "Singtel下周发布财报",
                "snippet": "新电信将披露最新季度业绩。",
                "module": "竞争对手",
                "keywords": "云网融合",
                "canonical_competitor": "Singtel",
            },
            {"should_include": True, "keywords": "云网融合"},
        )

        self.assertEqual(reason, "")

    def test_public_snapshot_exposes_dated_candidate_activity_for_empty_state_charts(self):
        with (
            mock.patch.object(briefing, "_load_state", return_value={}),
            mock.patch.object(briefing, "_load_published", return_value=[]),
            mock.patch.object(
                briefing,
                "_read_json",
                return_value={
                    "items": [
                        {
                            "title": "运营商发布网络建设计划",
                            "module": "基础设施/网络/技术类",
                            "source_date": "2026-07-28T08:00:00+08:00",
                        },
                        {
                            "title": "没有明确发布日期",
                            "module": "竞争对手",
                            "source_date": "",
                        },
                    ]
                },
            ),
        ):
            snapshot = briefing.public_snapshot()

        self.assertEqual(snapshot["items"], [])
        self.assertEqual(
            snapshot["candidate_items"],
            [
                {
                    "title": "运营商发布网络建设计划",
                    "category": "网络与技术",
                    "published_at": "2026-07-28T08:00:00+08:00",
                }
            ],
        )

    def test_comprehensive_query_plans_cover_every_configured_keyword(self):
        spec = {
            "modules": [
                {
                    "name": "模块甲",
                    "keywords": [f"关键词{index}" for index in range(27)],
                    "source_urls": [],
                },
                {
                    "name": "模块乙",
                    "keywords": [f"战略词{index}" for index in range(18)],
                    "source_urls": [],
                },
            ]
        }
        state = {"query_cursor": 9}

        plans = briefing._query_plans(spec, state, max_queries=None)

        covered = {
            keyword
            for plan in plans
            for keyword in plan["keywords"]
        }
        self.assertEqual(
            covered,
            {
                keyword
                for module in spec["modules"]
                for keyword in module["keywords"]
            },
        )
        self.assertEqual(len(plans), 10)
        self.assertEqual(state["query_cursor"], 0)

    def test_lightweight_query_plans_keep_rotating_limit(self):
        spec = {
            "modules": [
                {
                    "name": "模块",
                    "keywords": [f"关键词{index}" for index in range(30)],
                    "source_urls": [],
                }
            ]
        }
        state = {"query_cursor": 0}

        plans = briefing._query_plans(spec, state, max_queries=4)

        self.assertEqual(len(plans), 4)
        self.assertEqual(state["query_cursor"], 4)

    def test_split_keywords_preserves_commas_inside_parentheses(self):
        self.assertEqual(
            briefing._split_keywords(
                "港元利率（HIBOR 1M/3M），人民币、美元汇率"
            ),
            ["港元利率（HIBOR 1M/3M）", "人民币", "美元汇率"],
        )

    def test_scan_downstream_error_cannot_be_recorded_as_completed(self):
        with self.assertRaisesRegex(RuntimeError, "飞书审核表"):
            briefing._require_scan_downstream_success(
                {"result_count": 29},
                {"error": "'history_shards'"},
            )

        briefing._require_scan_downstream_success(
            {"result_count": 29},
            {"status": "ok", "new_count": 1, "readback_verified": True},
        )

        with self.assertRaisesRegex(RuntimeError, "逐格回读"):
            briefing._require_scan_downstream_success(
                {"result_count": 29},
                {"status": "ok", "new_count": 1},
            )

    def test_scan_persists_completed_pipeline_before_group_notification(self):
        order = []
        review_result = {
            "status": "ok",
            "readback_verified": True,
            "new_count": 0,
            "new_items": [],
            "sheet_url": "https://example.com/sheet",
            "source_candidate_count": 0,
            "batch_count": 0,
            "semantic_history_count": 300,
            "semantic_history_shards": 3,
            "semantic_duplicate_count": 0,
            "semantic_deferred_count": 0,
        }

        def record_write(_path, payload):
            status = payload.get("status") if isinstance(payload, dict) else ""
            if status == "pipeline_completed":
                order.append("pipeline_persisted")
            elif status == "completed":
                order.append("final_persisted")

        def record_review(**kwargs):
            order.append("review")
            self.assertTrue(kwargs["force"])
            self.assertFalse(kwargs["schedule_dashboard_publish"])
            self.assertEqual(kwargs["idempotency_key"], "2026-07-29@15:00-test")
            return review_result

        def record_notification(**_kwargs):
            order.append("notify")
            self.assertEqual(
                briefing.os.environ.get("CMHK_STRATEGIC_GROUP_NOTIFICATIONS"),
                "1",
            )
            return "om_after_completion", "bot"

        def record_registry_final(_crawl_run_id, **kwargs):
            order.append("registry_finalized")
            self.assertTrue(kwargs["ok"])
            self.assertTrue(kwargs["summary"]["readback_verified"])
            return {}

        with (
            mock.patch.object(
                briefing,
                "start_crawl_run",
                return_value={
                    "crawl_run_id": "strategic_test_run",
                    "stream_log_path": "/tmp/strategic_test_run.jsonl",
                },
            ),
            mock.patch.object(
                briefing,
                "append_crawl_run_event",
            ) as append_crawl_event,
            mock.patch.object(briefing, "heartbeat_crawl_run"),
            mock.patch.object(
                briefing,
                "finalize_operational_crawl_run",
                side_effect=record_registry_final,
            ),
            mock.patch.object(
                briefing,
                "read_monitoring_spec",
                return_value={
                    "spec_hash": "spec",
                    "module_count": 6,
                    "keyword_count": 135,
                    "source_urls": [],
                },
            ),
            mock.patch.object(
                briefing,
                "load_pending_signals",
                return_value={"signals": [], "expired_signal_ids": []},
            ),
            mock.patch.object(
                briefing.news_review_sheet,
                "curate_news_items",
                return_value=([], {}),
                create=True,
            ) if hasattr(briefing, "news_review_sheet") else mock.patch(
                "news_review_sheet.curate_news_items",
                return_value=([], {}),
            ),
            mock.patch(
                "news_discovery_vote_digest.send_digest",
                return_value={
                    "result_count": 0,
                    "hong_kong_count": 0,
                    "query_errors": [],
                    "window_start": "2026-07-29T08:00:00+08:00",
                    "window_end": "2026-07-29T15:00:00+08:00",
                    "agentic_search": {
                        "fixed_query_count": 53,
                        "fixed_result_count": 0,
                        "fixed_search": {"zero_result_count": 53},
                        "agentic_query_count": 2,
                        "agentic_result_count": 0,
                        "rounds": [
                            {
                                "phase": "expansion",
                                "status": "completed",
                                "search": {"query_count": 2, "result_count": 0},
                            }
                        ],
                        "admission_gate": {
                            "accepted_count": 0,
                            "rejected_count": 0,
                        },
                        "scheduled_crawl_search": {
                            "attempted_signal_ids": ["signal-1"],
                            "query_count": 1,
                            "retrieval_result_count": 0,
                            "admitted_result_count": 0,
                        },
                    },
                },
            ),
            mock.patch(
                "news_review_sheet.run_cycle",
                side_effect=record_review,
            ),
            mock.patch.object(briefing, "polish_candidates_before_review", return_value=[]),
            mock.patch.object(briefing, "_load_candidates", return_value=[]),
            mock.patch.object(briefing, "_save_candidates"),
            mock.patch.object(
                briefing,
                "commit_signal_attempts",
                return_value={"attempted": 0, "passed": 0, "consumed": 0},
            ),
            mock.patch.object(
                briefing,
                "_atomic_write_json",
                side_effect=record_write,
            ),
            mock.patch.object(briefing, "_append_event"),
            mock.patch.object(
                briefing,
                "_send_scan_message",
                side_effect=record_notification,
            ),
            mock.patch.dict(
                briefing.os.environ,
                {"CMHK_STRATEGIC_GROUP_NOTIFICATIONS": "1"},
            ),
        ):
            result = briefing._run_scan(
                datetime(2026, 7, 29, 15, 0, tzinfo=briefing.HKT),
                "2026-07-29@15:00-test",
                "午后扫描",
                {},
                ensure_group_notifications=True,
            )

        self.assertEqual(
            order,
            [
                "review",
                "pipeline_persisted",
                "notify",
                "final_persisted",
                "registry_finalized",
            ],
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["message_id"], "om_after_completion")
        self.assertEqual(result["task_run_id"], "strategic_test_run")
        task_log = "\n".join(
            str(call.args[1].get("text") or "")
            for call in append_crawl_event.call_args_list
            if len(call.args) > 1 and isinstance(call.args[1], dict)
        )
        for expected_phase in (
            "检索时间窗",
            "固定监控检索",
            "Agentic Search补缺",
            "定时页面线索合并",
            "AI审核结果",
            "历史语义去重",
            "飞书写入与逐格回读",
            "群通知准备",
        ):
            self.assertIn(expected_phase, task_log)

    def test_formal_scheduled_scan_stops_when_task_log_cannot_be_created(self):
        with (
            mock.patch.object(
                briefing,
                "start_crawl_run",
                side_effect=OSError("registry unavailable"),
            ),
            mock.patch.object(briefing, "_run_scan_impl") as run_impl,
        ):
            with self.assertRaisesRegex(RuntimeError, "无法建立任务日志"):
                briefing._run_scan(
                    datetime(2026, 7, 30, 9, 0, tzinfo=briefing.HKT),
                    "2026-07-30@09:00",
                    "晨间扫描",
                    {},
                    ensure_group_notifications=True,
                )

        run_impl.assert_not_called()

    def test_formal_scan_respects_paused_notification_configuration(self):
        result = {
            "status": "completed",
            "notification_status": "queued_while_paused",
            "message_id": "",
            "news_discovery": {"result_count": 0},
            "review_sheet": {
                "batch_count": 0,
                "semantic_duplicate_count": 0,
                "new_count": 0,
                "readback_verified": True,
            },
        }

        def run_impl(*_args, **_kwargs):
            self.assertEqual(
                briefing.os.environ.get("CMHK_STRATEGIC_GROUP_NOTIFICATIONS"),
                "0",
            )
            return dict(result)

        with (
            mock.patch.dict(
                briefing.os.environ,
                {"CMHK_STRATEGIC_GROUP_NOTIFICATIONS": "0"},
            ),
            mock.patch.object(briefing, "_completed_scan_archive", return_value={}),
            mock.patch.object(
                briefing,
                "start_crawl_run",
                return_value={
                    "crawl_run_id": "paused_notification_test",
                    "stream_log_path": "/tmp/paused_notification_test.jsonl",
                },
            ),
            mock.patch.object(briefing, "append_crawl_run_event"),
            mock.patch.object(briefing, "heartbeat_crawl_run"),
            mock.patch.object(briefing, "finalize_operational_crawl_run"),
            mock.patch.object(briefing, "_run_scan_impl", side_effect=run_impl),
        ):
            completed = briefing._run_scan(
                datetime(2026, 7, 30, 9, 0, tzinfo=briefing.HKT),
                "2026-07-30@09:00-paused-test",
                "晨间扫描",
                {},
                ensure_group_notifications=True,
            )

        self.assertEqual(completed["notification_status"], "queued_while_paused")

    def test_completed_scan_archive_prevents_any_second_run(self):
        slot_key = "2026-07-30@09:00"
        archived = {
            "slot": slot_key,
            "slot_label": "晨间扫描",
            "status": "completed",
            "notification_status": "sent",
            "message_id": "om_first_success",
            "candidate_count": 10,
            "completed_at": "2026-07-30T09:19:15+08:00",
            "review_sheet": {"new_count": 10},
        }
        state = {}

        with (
            tempfile.TemporaryDirectory() as temporary,
            mock.patch.object(briefing, "RUNS_DIR", Path(temporary)),
            mock.patch.object(briefing, "start_crawl_run") as start_run,
            mock.patch.object(briefing, "_run_scan_impl") as run_impl,
        ):
            briefing._atomic_write_json(
                briefing._scan_run_path(slot_key),
                archived,
            )
            result = briefing._run_scan(
                datetime(2026, 7, 30, 10, 46, tzinfo=briefing.HKT),
                slot_key,
                "晨间扫描",
                state,
                ensure_group_notifications=True,
            )

        self.assertTrue(result["reused_completed_slot"])
        self.assertEqual(result["message_id"], "om_first_success")
        self.assertEqual(
            state["scan_slots"][slot_key]["status"],
            "completed",
        )
        self.assertTrue(
            state["scan_slots"][slot_key]["recovered_from_archive"],
        )
        self.assertEqual(state["outbound_message_ids"], ["om_first_success"])
        start_run.assert_not_called()
        run_impl.assert_not_called()

    def test_incomplete_archive_does_not_block_retry(self):
        slot_key = "2026-07-30@09:00"
        incomplete = {
            "slot": slot_key,
            "status": "completed",
            "notification_status": "sent",
            "message_id": "",
        }

        with (
            tempfile.TemporaryDirectory() as temporary,
            mock.patch.object(briefing, "RUNS_DIR", Path(temporary)),
        ):
            briefing._atomic_write_json(
                briefing._scan_run_path(slot_key),
                incomplete,
            )
            self.assertEqual(briefing._completed_scan_archive(slot_key), {})

    def test_cycle_recovers_completed_archive_from_stale_state(self):
        now = datetime(2026, 7, 30, 10, 46, tzinfo=briefing.HKT)
        slot_key = "2026-07-30@09:00"
        archived = {
            "slot": slot_key,
            "slot_label": "晨间扫描",
            "status": "completed",
            "notification_status": "sent",
            "message_id": "om_already_sent",
            "candidate_count": 10,
            "completed_at": "2026-07-30T09:19:15+08:00",
            "review_sheet": {"new_count": 10},
        }
        stale_state = {
            "initialized_at": "2026-07-29T08:00:00+08:00",
            "scan_slots": {},
            "last_group_bucket": int(now.timestamp())
            // briefing.GROUP_CHECK_SECONDS,
        }
        saved = {}

        def completed_archive(key):
            return archived if key == slot_key else {}

        def save_state(state):
            saved.update(state)

        with (
            tempfile.TemporaryDirectory() as temporary,
            mock.patch.object(briefing, "DATA_DIR", Path(temporary)),
            mock.patch.object(
                briefing,
                "RUNS_DIR",
                Path(temporary) / "runs",
            ),
            mock.patch.object(
                briefing,
                "PROCESS_LOCK_PATH",
                Path(temporary) / "cycle.lock",
            ),
            mock.patch.object(briefing, "MONITOR_ENABLED", True),
            mock.patch.object(briefing, "_load_state", return_value=stale_state),
            mock.patch.object(
                briefing,
                "_completed_scan_archive",
                side_effect=completed_archive,
            ),
            mock.patch.object(briefing, "_run_scan") as run_scan,
            mock.patch.object(
                briefing,
                "_flush_pending_scan_notifications",
                return_value=[],
            ),
            mock.patch.object(briefing, "_save_state", side_effect=save_state),
        ):
            result = briefing.run_cycle(now)

        self.assertEqual(result["scans"], [])
        self.assertEqual(
            saved["scan_slots"][slot_key]["message_id"],
            "om_already_sent",
        )
        self.assertTrue(
            saved["scan_slots"][slot_key]["recovered_from_archive"],
        )
        run_scan.assert_not_called()

    def test_paused_completed_archive_recovers_pending_notification(self):
        slot_key = "2026-07-30@15:00"
        archived = {
            "slot": slot_key,
            "slot_label": "午后扫描",
            "status": "completed",
            "notification_status": "queued_while_paused",
            "message_id": "",
            "candidate_count": 2,
            "scanned_at": "2026-07-30T15:00:00+08:00",
            "spec": {"keyword_count": 135, "module_count": 6},
            "review_sheet": {"new_count": 2, "new_items": []},
        }
        state = {}

        briefing._recover_completed_scan_slot(state, slot_key, archived)

        pending = state["pending_scan_notifications"][slot_key]
        self.assertEqual(pending["slot_label"], "午后扫描")
        self.assertEqual(pending["review_result"]["new_count"], 2)

    def test_archive_recovery_uses_reviewed_new_count_for_monitoring(self):
        slot_key = "2026-07-30@15:00"
        archived = {
            "slot": slot_key,
            "status": "completed",
            "notification_status": "sent",
            "message_id": "om_reviewed",
            "candidate_count": 0,
            "completed_at": "2026-07-30T15:08:00+08:00",
            "review_sheet": {"new_count": 2},
        }
        state = {
            "last_scan_at": "2026-07-30T09:08:00+08:00",
            "last_scan_candidate_count": 0,
        }

        briefing._recover_completed_scan_slot(state, slot_key, archived)

        self.assertEqual(state["scan_slots"][slot_key]["candidate_count"], 2)
        self.assertEqual(state["last_scan_candidate_count"], 2)
        self.assertEqual(state["last_scan_slot"], slot_key)

    def test_reviewed_candidate_count_falls_back_for_legacy_results(self):
        self.assertEqual(briefing._reviewed_candidate_count({}, 3), 3)
        self.assertEqual(briefing._reviewed_candidate_count({"new_count": None}, 3), 0)

    def test_replayed_notification_marks_archive_as_sent(self):
        slot_key = "2026-07-30@15:00"
        archived = {
            "slot": slot_key,
            "slot_label": "午后扫描",
            "status": "completed",
            "notification_status": "queued_while_paused",
            "message_id": "",
            "scanned_at": "2026-07-30T15:00:00+08:00",
            "spec": {"keyword_count": 135, "module_count": 6},
            "review_sheet": {"new_count": 2},
        }
        state = {
            "scan_slots": {slot_key: {"status": "completed"}},
            "pending_scan_notifications": {
                slot_key: {
                    "now": "2026-07-30T15:00:00+08:00",
                    "slot_label": "午后扫描",
                    "spec": archived["spec"],
                    "review_result": archived["review_sheet"],
                }
            },
        }

        with (
            tempfile.TemporaryDirectory() as temporary,
            mock.patch.object(briefing, "RUNS_DIR", Path(temporary)),
            mock.patch.dict(
                briefing.os.environ,
                {"CMHK_STRATEGIC_GROUP_NOTIFICATIONS": "1"},
            ),
            mock.patch.object(
                briefing,
                "_send_scan_message",
                return_value=("om_replayed_once", "bot"),
            ),
            mock.patch.object(briefing, "_append_event"),
        ):
            briefing._atomic_write_json(
                briefing._scan_run_path(slot_key),
                archived,
            )
            sent = briefing._flush_pending_scan_notifications(
                datetime(2026, 7, 30, 15, 10, tzinfo=briefing.HKT),
                state,
            )
            final_archive = briefing._read_json(
                briefing._scan_run_path(slot_key),
                {},
            )

        self.assertEqual(
            sent,
            [{"slot": slot_key, "message_id": "om_replayed_once"}],
        )
        self.assertEqual(final_archive["notification_status"], "sent")
        self.assertEqual(final_archive["message_id"], "om_replayed_once")
        self.assertEqual(state["pending_scan_notifications"], {})

    def test_scan_notification_retries_with_stable_idempotency_key(self):
        response = {
            "data": {"message_id": "om_notification"},
            "_identity": "bot",
        }
        with (
            mock.patch.dict(
                briefing.os.environ,
                {"CMHK_STRATEGIC_GROUP_NOTIFICATIONS": "1"},
            ),
            mock.patch.object(
                briefing,
                "_lark_api",
                side_effect=[
                    RuntimeError("temporary EOF"),
                    response,
                    response,
                    response,
                    response,
                ],
            ) as lark_api,
            mock.patch.object(briefing.time, "sleep") as sleep,
        ):
            message_id, identity = briefing._send_scan_message(
                now=datetime(2026, 7, 28, 9, 0, tzinfo=briefing.HKT),
                slot_label="晨间扫描",
                candidates=[],
                spec={"keyword_count": 136, "module_count": 6},
                review_result={
                    "new_count": 16,
                    "new_category_counts": {"竞对动态": 16},
                    "new_region_counts": {"香港本地": 3, "国际/行业": 13},
                    "new_source_count": 14,
                    "source_candidate_count": 26,
                    "sheet_url": "https://example.com/sheet",
                },
                notification_key="2026-07-28@09:00",
            )
            repeated_message_id, _ = briefing._send_scan_message(
                now=datetime(2026, 7, 28, 9, 0, tzinfo=briefing.HKT),
                slot_label="晨间扫描",
                candidates=[],
                spec={"keyword_count": 136, "module_count": 6},
                review_result={
                    "new_count": 16,
                    "new_category_counts": {"竞对动态": 16},
                    "new_region_counts": {"香港本地": 3, "国际/行业": 13},
                    "new_source_count": 14,
                    "source_candidate_count": 26,
                    "sheet_url": "https://example.com/sheet",
                },
                notification_key="2026-07-28@09:00",
            )

        self.assertEqual(message_id, "om_notification")
        self.assertEqual(repeated_message_id, "om_notification")
        self.assertEqual(identity, "bot")
        self.assertEqual(lark_api.call_count, 5)
        first_uuid = lark_api.call_args_list[0].kwargs["data"]["uuid"]
        second_uuid = lark_api.call_args_list[1].kwargs["data"]["uuid"]
        self.assertEqual(first_uuid, second_uuid)
        self.assertEqual(
            first_uuid,
            lark_api.call_args_list[3].kwargs["data"]["uuid"],
        )
        second_chat_uuid = lark_api.call_args_list[2].kwargs["data"]["uuid"]
        self.assertNotEqual(first_uuid, second_chat_uuid)
        self.assertEqual(
            second_chat_uuid,
            lark_api.call_args_list[4].kwargs["data"]["uuid"],
        )
        self.assertEqual(
            [
                call.kwargs["data"]["receive_id"]
                for call in lark_api.call_args_list[1:3]
            ],
            list(briefing.TARGET_CHAT_IDS),
        )
        self.assertNotIn("uuid", lark_api.call_args_list[0].kwargs["params"])
        self.assertRegex(
            first_uuid,
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        )
        sleep.assert_called_once_with(1)

    def test_scan_notification_lists_at_most_five_priority_items(self):
        items = [
            {
                "title": f"香港竞对动态{index}",
                "summary": f"第{index}条动态的事实摘要。",
                "category": "竞对动态",
                "region": "香港本地",
                "source": "测试媒体",
                "published_at": f"2026-07-29T08:0{index}:00+08:00",
                "url": f"https://example.com/news/{index}",
                "inclusion_reason": "竞对推出新产品，影响产品定价和客户竞争。",
            }
            for index in range(1, 7)
        ]
        items[-1]["region"] = "国际/行业"
        response = {
            "data": {"message_id": "om_notification"},
            "_identity": "bot",
        }
        with (
            mock.patch.dict(
                briefing.os.environ,
                {"CMHK_STRATEGIC_GROUP_NOTIFICATIONS": "1"},
            ),
            mock.patch.object(
                briefing,
                "_lark_api",
                return_value=response,
            ) as lark_api,
        ):
            briefing._send_scan_message(
                now=datetime(2026, 7, 29, 9, 0, tzinfo=briefing.HKT),
                slot_label="晨间扫描",
                candidates=[],
                spec={"keyword_count": 135, "module_count": 6},
                review_result={
                    "new_count": 6,
                    "new_items": items,
                    "new_category_counts": {"竞对动态": 6},
                    "new_region_counts": {"香港本地": 5, "国际/行业": 1},
                    "new_source_count": 1,
                    "input_count": 120,
                    "source_candidate_count": 22,
                    "ai_included_count": 18,
                    "semantic_duplicate_count": 16,
                    "sheet_url": "https://example.com/sheet",
                },
                notification_key="2026-07-29@09:00",
            )

        card = json.loads(lark_api.call_args.kwargs["data"]["content"])
        rendered = json.dumps(card, ensure_ascii=False)
        self.assertIn("CMHK战略早茶｜6条新增", rendered)
        self.assertIn("香港竞对动态5", rendered)
        self.assertNotIn("香港竞对动态6", rendered)
        self.assertIn("另有 1 条候选", rendered)
        self.assertIn("检索发现 **120** → AI确认 **18**", rendered)
        self.assertIn("审核本轮6条新闻", rendered)
        self.assertIn("香港竞对 5", rendered)
        self.assertIn("国际竞对 1", rendered)
        self.assertIn("待审核 6", rendered)

    def test_pending_scan_notification_replays_once_after_resume(self):
        slot_key = "2026-07-28@09:00"
        state = {
            "scan_slots": {slot_key: {"status": "completed", "message_id": ""}},
            "pending_scan_notifications": {
                slot_key: {
                    "now": "2026-07-28T09:00:00+08:00",
                    "slot_label": "晨间扫描",
                    "spec": {"keyword_count": 136, "module_count": 6},
                    "review_result": {"new_count": 16},
                }
            },
        }
        with (
            mock.patch.dict(
                briefing.os.environ,
                {"CMHK_STRATEGIC_GROUP_NOTIFICATIONS": "1"},
            ),
            mock.patch.object(
                briefing,
                "_send_scan_message",
                return_value=("om_replayed", "bot"),
            ) as send,
            mock.patch.object(briefing, "_append_event") as append_event,
        ):
            result = briefing._flush_pending_scan_notifications(
                datetime(2026, 7, 28, 10, 0, tzinfo=briefing.HKT),
                state,
            )

        self.assertEqual(
            result,
            [{"slot": slot_key, "message_id": "om_replayed"}],
        )
        self.assertEqual(state["pending_scan_notifications"], {})
        self.assertEqual(
            state["scan_slots"][slot_key]["message_id"],
            "om_replayed",
        )
        self.assertEqual(state["outbound_message_ids"], ["om_replayed"])
        send.assert_called_once()
        append_event.assert_called_once()

    def test_empty_semantic_dedupe_reports_zero_history_shards(self):
        result = briefing.agent_semantic_deduplicate_candidates(
            [],
            [{"news_id": "old", "title": "历史新闻"}],
        )

        self.assertEqual(result["kept"], [])
        self.assertEqual(result["history_count"], 1)
        self.assertEqual(result["history_shards"], 0)

    def test_strategic_news_review_defaults_to_deepseek_v4_pro(self):
        self.assertEqual(briefing.DEFAULT_STRATEGY_AI_MODEL, "DeepSeek-V4-Pro")

    def test_strategic_ai_switches_key_after_budget_exceeded(self):
        budget_error = briefing.HTTPError(
            "http://internal/chat/completions",
            400,
            "Bad Request",
            {},
            io.BytesIO(
                json.dumps(
                    {
                        "error": {
                            "type": "budget_exceeded",
                            "code": "400",
                            "message": "Budget has been exceeded",
                        }
                    }
                ).encode()
            ),
        )
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {
                "choices": [
                    {"message": {"content": json.dumps({"ok": True})}}
                ]
            }
        ).encode()
        opener = mock.MagicMock()
        opener.open.side_effect = [budget_error, response]
        with (
            mock.patch.object(
                briefing,
                "load_ai_config",
                return_value={
                    "base_url": "http://10.0.62.177:4000/v1",
                    "model": "deepseek-v4",
                    "api_key": "secondary-key",
                    "strategy_api_keys": ["exhausted-key", "secondary-key"],
                },
            ),
            mock.patch.object(briefing, "build_opener", return_value=opener),
            mock.patch.object(briefing, "wait_for_internal_ai_slot"),
        ):
            result = briefing._call_internal_ai("system", "user")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(opener.open.call_count, 2)
        requests = [call.args[0] for call in opener.open.call_args_list]
        self.assertEqual(
            [request.get_header("Authorization") for request in requests],
            ["Bearer exhausted-key", "Bearer secondary-key"],
        )

    def test_strategic_ai_switches_to_model_bound_fallback(self):
        access_error = briefing.HTTPError(
            "http://internal/chat/completions",
            401,
            "Unauthorized",
            {},
            io.BytesIO(
                json.dumps(
                    {
                        "error": {
                            "type": "team_model_access_denied",
                            "code": "401",
                            "message": "Team not allowed to access model",
                        }
                    }
                ).encode()
            ),
        )
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {
                "choices": [
                    {"message": {"content": json.dumps({"ok": True})}}
                ]
            }
        ).encode()
        opener = mock.MagicMock()
        opener.open.side_effect = [access_error, response]
        with (
            mock.patch.object(
                briefing,
                "load_ai_config",
                return_value={
                    "base_url": "http://10.0.62.177:4000/v1",
                    "model": "deepseek-v4",
                    "api_key": "v4-key",
                    "strategy_api_keys": ["v4-key"],
                    "model_api_keys": {"deepseek-v4-free": ["free-key"]},
                },
            ),
            mock.patch.object(briefing, "build_opener", return_value=opener),
            mock.patch.object(briefing, "wait_for_internal_ai_slot"),
        ):
            result = briefing._call_internal_ai("system", "user")

        self.assertEqual(result, {"ok": True})
        requests = [call.args[0] for call in opener.open.call_args_list]
        self.assertEqual(
            [json.loads(request.data)["model"] for request in requests],
            ["DeepSeek-V4-Pro", "deepseek-v4-free"],
        )
        self.assertEqual(
            [request.get_header("Authorization") for request in requests],
            ["Bearer v4-key", "Bearer free-key"],
        )

    def _approved_brief(self) -> dict:
        return {
            "id": "NEWS-TEST",
            "title": "English source headline",
            "summary": "Source summary for an approved item.",
            "category": "竞对动态",
            "source_url": "https://example.com/news",
            "published_at": "2026-07-16T09:00:00+08:00",
            "approval_message_id": "message-1",
        }

    def test_polish_approved_brief_requires_chinese_editor_output(self):
        with mock.patch.object(
            briefing,
            "_call_internal_ai",
            return_value={
                "title": "竞对推出新一代企业网络方案",
                "summary": "该公司发布新的企业网络方案，重点关注产品能力变化及其对香港市场竞争格局的影响。",
            },
        ) as call:
            result = briefing._polish_approved_brief(self._approved_brief())
        self.assertRegex(result["title"], r"[\u4e00-\u9fff]")
        self.assertLessEqual(len(result["summary"]), 96)
        self.assertTrue(result["ai_polished_at"])
        self.assertEqual(call.call_args.kwargs["max_tokens"], 2400)

    def test_model_authored_copy_is_normalized_to_simplified_chinese(self):
        result = briefing._validated_ai_copy(
            {
                "title": "香港電訊擴展人工智能服務",
                "summary": "香港電訊宣佈擴展人工智能服務，為企業客戶提供新的網絡能力。",
                "should_include": True,
                "region": "香港本地",
                "category": "競對動態",
                "keywords": "人工智能",
                "inclusion_reason": "直接關係香港企業市場的競爭格局變化。",
                "region_reason": "事件主體與受影響市場均在香港。",
            },
            require_review_fields=True,
            allowed_keywords="人工智能",
        )
        self.assertEqual(result["title"], "香港电讯扩展人工智能服务")
        self.assertIn("企业客户", result["summary"])
        self.assertEqual(result["category"], "竞对动态")
        self.assertIn("竞争格局变化", result["inclusion_reason"])

    def test_region_is_not_overridden_by_hard_coded_place_rules(self):
        result = briefing._validated_ai_copy(
            {
                "title": "辉达代理AI RTX Spark携手联发科",
                "summary": "辉达代理AI RTX Spark技术与联发科合作，并有4家台厂新品接力上场。",
                "should_include": True,
                "region": "香港本地",
                "category": "行业动态",
                "keywords": "AI",
                "inclusion_reason": "涉及AI技术合作与台厂新品上市，具产业动态价值。",
                "region_reason": "模型错误认为影响香港市场。",
            },
            require_review_fields=True,
            allowed_keywords="AI",
            source_item={
                "source_title": "7/22盘前｜辉达代理AI RTX Spark牵手联发科 4台厂新品接力上场",
                "source_summary": "台股盘前重点新闻。",
                "jurisdiction": "TW",
            },
        )
        self.assertEqual(result["region"], "香港本地")

    def test_competitor_route_normalizes_final_competitor_category(self):
        result = briefing._validated_ai_copy(
            {
                "title": "T-Mobile上调2026年自由现金流预期",
                "summary": "T-Mobile上调全年自由现金流指引，并维持服务收入展望。",
                "should_include": True,
                "region": "国际/行业",
                "category": "行业动态",
                "keywords": "T-Mobile",
                "inclusion_reason": "上调现金流指引将影响资本配置判断。",
                "region_reason": "事件主体和受影响市场均位于美国。",
                "decision_path": "竞对直通",
                "signal_type": "竞对经营动作",
                "business_impact": "资本配置",
                "exclusion_code": "无",
            },
            require_review_fields=True,
            require_decision_fields=True,
            allowed_keywords="T-Mobile",
            source_item={
                "module": "竞争对手",
                "source_title": "T-Mobile raises 2026 free cash flow outlook",
            },
        )

        self.assertEqual(result["category"], "竞对动态")

    def test_strategic_signal_does_not_keep_upstream_competitor_module_as_category(self):
        result = briefing._validated_ai_copy(
            {
                "title": "三星电子公布人工智能芯片业务增长",
                "summary": "三星电子披露人工智能存储芯片需求增长，并公布半导体业务最新经营数据。",
                "should_include": True,
                "region": "国际/行业",
                "category": "竞争对手",
                "keywords": "AI",
                "inclusion_reason": "芯片业务数据反映人工智能基础设施需求变化。",
                "region_reason": "事件主体和主要市场均位于香港以外。",
                "decision_path": "战略信号",
                "signal_type": "关键技术",
                "business_impact": "收入与需求",
                "exclusion_code": "无",
            },
            require_review_fields=True,
            require_decision_fields=True,
            allowed_keywords="AI",
            source_item={"module": "竞争对手"},
        )

        self.assertEqual(result["decision_path"], "战略信号")
        self.assertEqual(result["category"], "基础设施/网络/技术类")

    def test_compact_strategic_signal_maps_category_from_ai_signal_not_search_module(self):
        result = briefing._expanded_compact_decision(
            {
                "route": "S",
                "region": "I",
                "signal": "S",
                "impact": "C",
                "exclude": "0",
            },
            source_item={
                "title": "欣兴公布AI载板营收占比",
                "category": "竞争对手",
                "keywords": ["AI"],
            },
        )

        self.assertEqual(result["decision_path"], "战略信号")
        self.assertEqual(result["signal_type"], "供应链")
        self.assertEqual(result["category"], "行业动态")

    def test_compact_competitor_route_uses_final_competitor_category(self):
        result = briefing._expanded_compact_decision(
            {
                "route": "C",
                "region": "I",
                "signal": "C",
                "impact": "A",
                "exclude": "0",
            },
            source_item={
                "title": "Singtel explores dual listing for Nxera",
                "category": "竞争对手",
                "keywords": ["Singtel"],
            },
        )

        self.assertEqual(result["decision_path"], "竞对直通")
        self.assertEqual(result["category"], "竞对动态")

    def test_candidate_editor_receives_non_binding_search_hints(self):
        payload = briefing._candidate_editor_input(
            "1234567890abcdef",
            {
                "module": "竞争对手",
                "category": "竞对动态",
                "title": "T-Mobile raises 2026 free cash flow outlook",
                "snippet": "T-Mobile raised its full-year free cash flow guidance.",
                "keywords": ["T-Mobile"],
            },
        )
        self.assertEqual(payload["monitoring_module"], "竞争对手")
        self.assertEqual(payload["upstream_category_hint"], "竞对动态")
        self.assertNotIn("competitor_candidate", payload)
        self.assertNotIn("monitoring_scope_confirmed", payload)
        self.assertIn("T-Mobile", payload["matched_keywords"])
        self.assertIn("业绩或现金流指引", briefing._CATEGORY_CLASSIFICATION_GUIDANCE)
        self.assertIn("地域与分类是两个独立维度", briefing._CATEGORY_CLASSIFICATION_GUIDANCE)
        self.assertIn("技术监控词命中", briefing._CATEGORY_CLASSIFICATION_GUIDANCE)
        self.assertIn("泛香港5G基站", briefing._CATEGORY_CLASSIFICATION_GUIDANCE)
        self.assertIn(
            "matched_keywords全部来自正式监控配置",
            briefing._STRATEGIC_INCLUSION_GUIDANCE,
        )
        self.assertIn(
            "不得再要求关联某家竞对",
            briefing._STRATEGIC_INCLUSION_GUIDANCE,
        )
        self.assertIn(
            "香港监管政策、牌照频谱及政府产业政策",
            briefing._SOFT_PRIORITY_GUIDANCE,
        )
        self.assertIn(
            "香港本地运营商和本地竞对动态同等重要",
            briefing._SOFT_PRIORITY_GUIDANCE,
        )
        self.assertIn(
            "国际/行业新闻可以在排序和群卡片展示上稍低优先",
            briefing._SOFT_PRIORITY_GUIDANCE,
        )
        self.assertIn(
            "不是程序硬拦截",
            briefing._SOFT_PRIORITY_GUIDANCE,
        )
        self.assertIn(
            "不能因此从候选池删除",
            briefing._SOFT_PRIORITY_GUIDANCE,
        )
        self.assertIn(
            "中国内地部委单独发布的全国政策属于国际/行业",
            briefing._SOFT_PRIORITY_GUIDANCE,
        )
        self.assertIn(
            "未注明司法管辖区的机构名不得猜成香港",
            briefing._SOFT_PRIORITY_GUIDANCE,
        )
        self.assertIn(
            "普通海外AI与芯片消息若有具体变化可保留",
            briefing._SOFT_PRIORITY_GUIDANCE,
        )
        self.assertIn(
            "必须走战略信号通道",
            briefing._SOFT_PRIORITY_GUIDANCE,
        )
        self.assertIn(
            "只出现在来源媒体或网址",
            briefing._SOFT_PRIORITY_GUIDANCE,
        )
        self.assertIn(
            "台湾的数位发展部",
            briefing._SOFT_PRIORITY_GUIDANCE,
        )
        self.assertIn(
            "不得照抄‘竞争对手’等上游模块名",
            briefing._SOFT_PRIORITY_GUIDANCE,
        )
        self.assertIn(
            "CMHK）是本公司而不是竞对",
            briefing._CATEGORY_CLASSIFICATION_GUIDANCE,
        )

    def test_non_competitor_strategic_keyword_signal_is_included(self):
        item = {
            "module": "政策/法规类",
            "category": "政策监管",
            "title": "香港公布数据中心能源使用新规",
            "snippet": "新规将提高数据中心能源披露和合规要求，并影响运营成本。",
            "keywords": ["Data center", "监管"],
            "source": "Government News",
            "url": "https://example.com/news/hk-data-centre-rule",
        }
        ai_result = {
            "items": [
                {
                    "id": briefing._candidate_editor_key(item)[:16],
                    "title": "香港公布数据中心能源使用新规",
                    "summary": "香港提高数据中心能源披露及合规要求，相关运营商将面对新的合规与成本安排。",
                    "should_include": True,
                    "region": "香港本地",
                    "category": "政策监管",
                    "keywords": "Data center、监管",
                    "inclusion_reason": "数据中心能源新规将直接改变基础设施合规要求和运营成本。",
                    "region_reason": "政策由香港发布并影响香港数据中心运营。",
                    "decision_path": "战略信号",
                    "signal_type": "监管政策",
                    "business_impact": "合规与牌照",
                    "exclusion_code": "无",
                }
            ]
        }
        with (
            mock.patch.object(briefing, "_read_json", return_value={"items": {}}),
            mock.patch.object(briefing, "_atomic_write_json"),
            mock.patch.object(briefing, "_call_internal_ai", return_value=ai_result),
        ):
            result = briefing.polish_candidates_before_review([item])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["ai_decision_path"], "战略信号")
        self.assertEqual(result[0]["ai_signal_type"], "监管政策")
        self.assertEqual(result[0]["ai_business_impact"], "合规与牌照")

    def test_ai_critic_cannot_remove_included_item_but_can_correct_region(self):
        media_item = {
            "title": "房协与数码港推房地产科技计划",
            "snippet": "房协与数码港支持初创分析停车场车辆。",
            "keywords": ["i-CABLE"],
            "source": "i-cable.com",
            "url": "https://example.com/housing",
            "region": "香港本地",
            "category": "竞对动态",
        }
        taiwan_item = {
            "title": "数发部建立量化AI人才标准",
            "snippet": "台湾数位发展部发布AI人才指引。",
            "keywords": ["AI"],
            "source": "rti.org.tw",
            "url": "https://example.com/taiwan-ai",
            "region": "香港本地",
            "category": "基础设施/网络/技术类",
        }
        response = {
            "items": [
                {
                    "id": briefing._candidate_editor_key(media_item)[:16],
                    "keep": False,
                    "region": "香港本地",
                    "category": "行业动态",
                    "reason": "竞对名只出现在来源媒体，事件主体并非有线宽频。",
                },
                {
                    "id": briefing._candidate_editor_key(taiwan_item)[:16],
                    "keep": True,
                    "region": "国际/行业",
                    "category": "基础设施/网络/技术类",
                    "reason": "事件主体是台湾数位发展部，地域应为国际行业。",
                },
            ]
        }
        with (
            mock.patch.object(briefing, "AI_EDITOR_CRITIC_ENABLED", True),
            mock.patch.object(
                briefing, "_call_internal_ai", return_value=response
            ),
        ):
            kept, audit = briefing._critic_review_included(
                [media_item, taiwan_item]
            )

        self.assertEqual(len(kept), 2)
        self.assertTrue(kept[0]["ai_critic_disagreed"])
        self.assertEqual(kept[1]["region"], "国际/行业")
        self.assertEqual(audit["removed_count"], 0)
        self.assertFalse(audit["delete_enabled"])
        self.assertEqual(audit["corrected_count"], 1)

    def test_ai_critic_only_reviews_a_kept_candidate_once_per_pipeline(self):
        item = {
            "title": "有线宽频召开股东特别大会",
            "snippet": "有线宽频发布股东特别大会及暂停办理股份过户登记公告。",
            "keywords": ["i-CABLE", "有线宽频"],
            "canonical_competitor": "i-CABLE",
            "source": "信报",
            "url": "https://example.com/icable-egm",
            "region": "香港本地",
            "category": "竞对动态",
        }
        response = {
            "items": [
                {
                    "id": briefing._candidate_editor_key(item)[:16],
                    "keep": True,
                    "region": "香港本地",
                    "category": "竞对动态",
                    "reason": "有线宽频是事件主体，股东大会属于竞对资本治理动态。",
                }
            ]
        }
        with (
            mock.patch.object(briefing, "AI_EDITOR_CRITIC_ENABLED", True),
            mock.patch.object(
                briefing, "_call_internal_ai", return_value=response
            ) as ai_call,
        ):
            first, first_audit = briefing._critic_review_included([item])
            second, second_audit = briefing._critic_review_included(first)

        self.assertEqual(ai_call.call_count, 1)
        self.assertEqual(first_audit["already_reviewed_count"], 0)
        self.assertEqual(second_audit["already_reviewed_count"], 1)
        self.assertEqual(
            second[0]["ai_critic_version"],
            briefing.AI_EDITOR_CRITIC_VERSION,
        )

    def test_ai_critic_prompt_protects_competitor_when_search_hint_points_elsewhere(self):
        item = {
            "title": "AT&T完成收购EchoStar频谱牌照",
            "snippet": "AT&T完成约230亿美元无线频谱牌照交易。",
            "keywords": ["中国联通香港"],
            "canonical_competitor": "China Unicom Hong Kong",
            "source": "Yahoo Finance",
            "url": "https://example.com/att-spectrum",
            "region": "国际/行业",
            "category": "竞对动态",
        }
        response = {
            "items": [
                {
                    "id": briefing._candidate_editor_key(item)[:16],
                    "keep": True,
                    "region": "国际/行业",
                    "category": "竞对动态",
                    "reason": "AT&T是正式监控竞对，频谱牌照收购属于竞对网络与资本动作。",
                }
            ]
        }
        with (
            mock.patch.object(briefing, "AI_EDITOR_CRITIC_ENABLED", True),
            mock.patch.object(
                briefing, "_call_internal_ai", return_value=response
            ) as ai_call,
        ):
            kept, _audit = briefing._critic_review_included([item])

        prompt = ai_call.call_args.args[0]
        self.assertEqual(len(kept), 1)
        self.assertIn(
            "即使matched_keywords或configured_competitor_hint",
            prompt,
        )
        self.assertIn("频谱和牌照", prompt)
        self.assertIn("股东大会", prompt)

    def test_manufacturing_innovation_agreement_reaches_ai_and_can_be_included(self):
        item = {
            "module": "宏观经济&国际形势&地缘政治&其他国际性质关注词汇",
            "title": "特区政府与国家工信部签署协议推进共建制造业创新中心",
            "snippet": "双方深化内地和香港产业合作，共同支持在香港建设制造业创新中心。",
            "keywords": ["工信部"],
            "source": "香港商报",
            "url": "https://www.hkcd.com.hk/hkcdweb/content/2026/07/28/content_8767010.html",
        }
        ai_result = {
            "items": [
                {
                    "id": briefing._candidate_editor_key(item)[:16],
                    "title": "特区政府与工信部共建制造业创新中心",
                    "summary": "双方签署合作协议，在香港建设制造业创新中心并深化产业合作。",
                    "should_include": True,
                    "region": "香港本地",
                    "category": "宏观与政策",
                    "keywords": "工信部",
                    "inclusion_reason": "正式合作协议推动香港产业基础设施及关键技术发展。",
                    "region_reason": "签约主体包括香港特区政府，项目明确在香港建设。",
                    "decision_path": "战略信号",
                    "signal_type": "监管政策",
                    "business_impact": "资本配置",
                    "exclusion_code": "无",
                }
            ]
        }
        with (
            mock.patch.object(briefing, "_read_json", return_value={"items": {}}),
            mock.patch.object(briefing, "_atomic_write_json"),
            mock.patch.object(
                briefing, "_call_internal_ai", return_value=ai_result
            ) as ai_call,
        ):
            result = briefing.polish_candidates_before_review([item])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["ai_region"], "香港本地")
        self.assertEqual(result[0]["ai_category"], "政策监管")
        self.assertEqual(ai_call.call_count, 1)

    def test_strategic_signal_fills_missing_business_impact_without_dropping(self):
        result = briefing._validated_ai_copy(
            {
                "title": "行业发布人工智能发展报告",
                "summary": "报告梳理人工智能产业趋势，并公布模型部署和行业应用的新数据。",
                "should_include": True,
                "region": "国际/行业",
                "category": "行业动态",
                "keywords": "AI",
                "inclusion_reason": "报告公布人工智能部署和行业应用的具体变化。",
                "region_reason": "报告讨论全球行业趋势。",
                "decision_path": "战略信号",
                "signal_type": "关键技术",
                "business_impact": "无",
                "exclusion_code": "无",
            },
            require_review_fields=True,
            require_decision_fields=True,
            allowed_keywords="AI",
        )

        self.assertTrue(result["should_include"])
        self.assertEqual(result["business_impact"], "竞争格局")

    def test_commentary_decision_is_not_overridden_by_regex(self):
        result = briefing._validated_ai_copy(
                {
                    "title": "评论员分析地区战争对市场的影响",
                    "summary": "评论员讨论地区战争可能带来的长期市场风险。",
                    "should_include": True,
                    "region": "国际/行业",
                    "category": "宏观经济",
                    "keywords": "War",
                    "inclusion_reason": "评论涉及战争，因此可能影响运营和供应。",
                    "region_reason": "评论讨论国际地区局势。",
                    "decision_path": "战略信号",
                    "signal_type": "宏观与地缘",
                    "business_impact": "供应韧性",
                    "exclusion_code": "无",
                },
                require_review_fields=True,
                require_decision_fields=True,
                allowed_keywords="War",
                source_item={
                    "source_title": "MSNBC评论员分析特朗普对伊战争150天影响",
                    "source_summary": "节目嘉宾分析战争可能造成的政治和市场影响。",
                },
            )
        self.assertTrue(result["should_include"])

    def test_generic_trend_decision_is_not_overridden_by_regex(self):
        result = briefing._validated_ai_copy(
                {
                    "title": "中国AI四强追赶美国",
                    "summary": "文章比较中国与美国人工智能企业的整体发展趋势。",
                    "should_include": True,
                    "region": "国际/行业",
                    "category": "行业动态",
                    "keywords": "AI",
                    "inclusion_reason": "行业竞争趋势可能影响市场格局。",
                    "region_reason": "内容讨论国际行业竞争。",
                    "decision_path": "战略信号",
                    "signal_type": "关键技术",
                    "business_impact": "竞争格局",
                    "exclusion_code": "无",
                },
                require_review_fields=True,
                require_decision_fields=True,
                allowed_keywords="AI",
                source_item={
                    "source_title": "中国AI四强追赶美国",
                    "source_summary": "文章比较两国企业的整体发展趋势。",
                },
            )
        self.assertTrue(result["should_include"])

    def test_stock_market_decision_is_not_overridden_by_regex(self):
        result = briefing._validated_ai_copy(
                {
                    "title": "韩股重挫AI晶片股暴跌",
                    "summary": "AI相关疑虑导致晶片股价大幅下跌。",
                    "should_include": True,
                    "region": "国际/行业",
                    "category": "行业动态",
                    "keywords": "AI",
                    "inclusion_reason": "股市下跌可能影响行业融资。",
                    "region_reason": "事件发生在韩国市场。",
                    "decision_path": "战略信号",
                    "signal_type": "市场需求",
                    "business_impact": "资本配置",
                    "exclusion_code": "无",
                },
                require_review_fields=True,
                require_decision_fields=True,
                allowed_keywords="AI",
                source_item={
                    "source_title": "韩股一度重挫逾7% AI相关疑虑造成晶片股价暴跌",
                    "source_summary": "韩国股市下跌，晶片股价格大幅波动。",
                },
            )
        self.assertTrue(result["should_include"])

    def test_business_candidate_always_reaches_ai_review(self):
        item = {
            "module": "基础设施/网络/技术类",
            "category": "行业动态",
            "title": "中国AI四强追赶美国",
            "snippet": "文章比较中美人工智能企业的整体发展趋势。",
            "keywords": ["AI"],
            "source": "Example",
            "url": "https://example.com/ai-trend",
        }
        ai_result = {
            "items": [
                {
                    "id": briefing._candidate_editor_key(item)[:16],
                    "title": "中国AI四强追赶美国",
                    "summary": "文章比较中美人工智能企业的整体发展趋势。",
                    "should_include": True,
                    "region": "国际/行业",
                    "category": "行业动态",
                    "keywords": "AI",
                    "inclusion_reason": "行业竞争趋势可能影响市场格局。",
                    "region_reason": "内容讨论国际行业竞争。",
                    "decision_path": "战略信号",
                    "signal_type": "关键技术",
                    "business_impact": "竞争格局",
                    "exclusion_code": "无",
                }
            ]
        }
        writes = []
        with (
            mock.patch.object(briefing, "_read_json", return_value={"items": {}}),
            mock.patch.object(
                briefing,
                "_atomic_write_json",
                side_effect=lambda path, payload: writes.append((path, payload)),
            ),
            mock.patch.object(
                briefing,
                "_call_internal_ai",
                return_value=ai_result,
            ) as call,
        ):
            result = briefing.polish_candidates_before_review([item])

        self.assertEqual(len(result), 1)
        self.assertEqual(call.call_count, 1)
        audit = next(
            payload
            for path, payload in writes
            if path == briefing.AI_EDITOR_AUDIT_PATH
        )
        self.assertEqual(audit["resolved_count"], 1)
        self.assertEqual(audit["excluded_count"], 0)
        self.assertEqual(audit["deferred_count"], 0)

    def test_review_copy_uses_source_title_and_summary_when_ai_omits_format_fields(self):
        result = briefing._validated_ai_copy(
            {
                "should_include": False,
                "region": "国际/行业",
                "category": "行业动态",
                "keywords": "AI",
                "inclusion_reason": "文章仅偶然提及AI，没有具体技术、市场或业务事件。",
                "region_reason": "事件发生在海外市场。",
                "decision_path": "排除",
                "signal_type": "无",
                "business_impact": "无",
                "exclusion_code": "关键词偶然出现",
            },
            require_review_fields=True,
            require_decision_fields=True,
            allowed_keywords="AI",
            source_item={
                "source_title": "海外企业发布季度社会活动简报",
                "source_summary": "该企业介绍社区活动，并在背景材料中偶然提到人工智能。",
            },
        )

        self.assertEqual(result["title"], "海外企业发布季度社会活动简报")
        self.assertIn("社区活动", result["summary"])
        self.assertFalse(result["should_include"])

    def test_excluded_media_name_alias_is_normalized_without_retry(self):
        result = briefing._validated_ai_copy(
            {
                "title": "日本政府据报支持央行近期加息",
                "summary": "i-CABLE报道日本政府支持央行近期加息，事件主体与有线宽频无关。",
                "should_include": False,
                "region": "国际/行业",
                "category": "宏观经济&国际形势&地缘政治&其他国际性质关注词汇",
                "keywords": "i-CABLE、有线宽频",
                "inclusion_reason": "无",
                "region_reason": "事件主体与受影响市场在日本。",
                "decision_path": "排除",
                "signal_type": "无",
                "business_impact": "无",
                "exclusion_code": "关键词仅在媒体名中出现",
            },
            require_review_fields=True,
            require_decision_fields=True,
            allowed_keywords=["i-CABLE", "有线宽频"],
        )

        self.assertFalse(result["should_include"])
        self.assertEqual(result["exclusion_code"], "关键词偶然出现")
        self.assertGreaterEqual(len(result["inclusion_reason"]), 8)

    def test_unknown_exclusion_reason_is_still_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "有效排除原因代码"):
            briefing._validated_ai_copy(
                {
                    "title": "海外企业发布社区活动简报",
                    "summary": "该企业介绍社区活动，并在背景材料中偶然提到人工智能。",
                    "should_include": False,
                    "region": "国际/行业",
                    "category": "行业动态",
                    "keywords": "AI",
                    "inclusion_reason": "这是一个无法归一的自由文本理由。",
                    "region_reason": "事件发生在海外市场。",
                    "decision_path": "排除",
                    "signal_type": "无",
                    "business_impact": "无",
                    "exclusion_code": "模型不喜欢这条新闻",
                },
                require_review_fields=True,
                require_decision_fields=True,
                allowed_keywords=["AI"],
            )

    def test_editor_prompts_include_three_complete_few_shot_routes(self):
        guidance = briefing._AI_EDITOR_FEW_SHOT_GUIDANCE
        self.assertIn('"decision_path":"竞对直通"', guidance)
        self.assertIn('"decision_path":"战略信号"', guidance)
        self.assertIn('"decision_path":"排除"', guidance)
        self.assertIn("不得只写‘无’", guidance)
        self.assertIn('"route":"C"', briefing._AI_EDITOR_COMPACT_FEW_SHOT_GUIDANCE)
        self.assertIn('"route":"S"', briefing._AI_EDITOR_COMPACT_FEW_SHOT_GUIDANCE)
        self.assertIn('"route":"X"', briefing._AI_EDITOR_COMPACT_FEW_SHOT_GUIDANCE)

    def test_single_item_retry_accepts_batch_wrapper(self):
        item = {
            "module": "政策/法规类",
            "category": "政策监管",
            "title": "海外社区活动简报",
            "snippet": "该企业介绍社区活动，并在背景材料中偶然提到人工智能。",
            "keywords": ["AI"],
            "source": "Example",
            "url": "https://example.com/community",
        }
        wrapped_retry = {
            "items": [
                {
                    "id": briefing._candidate_editor_key(item)[:16],
                    "should_include": False,
                    "region": "国际/行业",
                    "category": "行业动态",
                    "keywords": "AI",
                    "inclusion_reason": "文章仅偶然提及AI，没有具体技术、市场或业务事件。",
                    "region_reason": "事件发生在海外市场。",
                    "decision_path": "排除",
                    "signal_type": "无",
                    "business_impact": "无",
                    "exclusion_code": "关键词偶然出现",
                }
            ]
        }
        with (
            mock.patch.object(briefing, "_read_json", return_value={"items": {}}),
            mock.patch.object(briefing, "_atomic_write_json"),
            mock.patch.object(
                briefing,
                "_call_internal_ai",
                side_effect=[{}, {}, wrapped_retry],
            ),
        ):
            result = briefing.polish_candidates_before_review([item])

        self.assertEqual(result, [])

    def test_verbose_batch_omission_gets_compact_decision_instead_of_defer(self):
        included = {
            "module": "竞争对手",
            "category": "竞对动态",
            "title": "HKT推出企业AI平台",
            "snippet": "HKT announced an AI platform for enterprise customers.",
            "keywords": ["HKT", "AI"],
            "source": "Example",
            "url": "https://example.com/hkt-ai",
        }
        excluded = {
            "module": "基础设施/网络/技术类",
            "category": "行业动态",
            "title": "评论员讨论人工智能未来",
            "snippet": "评论员表达对人工智能未来的个人观点，没有宣布具体变化。",
            "keywords": ["AI"],
            "source": "Example",
            "url": "https://example.com/ai-opinion",
        }
        verbose = {
            "items": [
                {
                    "id": briefing._candidate_editor_key(included)[:16],
                    "title": "HKT推出企业AI平台",
                    "summary": "HKT面向企业客户推出AI平台，扩展企业数字服务能力。",
                    "should_include": True,
                    "region": "香港本地",
                    "category": "竞对动态",
                    "keywords": "HKT、AI",
                    "inclusion_reason": "HKT推出企业AI平台，直接影响企业产品与竞争格局。",
                    "region_reason": "事件主体及目标市场均在香港。",
                    "decision_path": "竞对直通",
                    "signal_type": "竞对经营动作",
                    "business_impact": "竞争格局",
                    "exclusion_code": "无",
                }
            ]
        }
        compact = {
            "items": [
                {
                    "id": briefing._candidate_editor_key(excluded)[:16],
                    "route": "X",
                    "signal": "0",
                    "impact": "0",
                    "exclude": "5",
                    "region": "I",
                }
            ]
        }
        writes = []
        with (
            mock.patch.object(briefing, "_read_json", return_value={"items": {}}),
            mock.patch.object(
                briefing,
                "_atomic_write_json",
                side_effect=lambda path, payload: writes.append((path, payload)),
            ),
            mock.patch.object(
                briefing,
                "_call_internal_ai",
                side_effect=[verbose, compact],
            ) as call,
        ):
            result = briefing.polish_candidates_before_review([included, excluded])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["ai_decision_path"], "竞对直通")
        self.assertEqual(call.call_count, 2)
        audit = next(
            payload
            for path, payload in writes
            if path == briefing.AI_EDITOR_AUDIT_PATH
        )
        self.assertEqual(audit["resolved_count"], 2)
        self.assertEqual(audit["excluded_count"], 1)
        self.assertEqual(audit["deferred_count"], 0)
        self.assertEqual(audit["compact_retry_item_count"], 1)
        self.assertEqual(audit["compact_retry_resolved_count"], 1)

    def test_compact_codes_repair_invalid_verbose_decision_without_third_call(self):
        item = {
            "module": "基础设施/网络/技术类",
            "category": "行业动态",
            "title": "香港公布数据中心能源使用新规",
            "snippet": "新规提高数据中心能源披露要求并影响运营成本。",
            "keywords": ["Data center"],
            "source": "Example",
            "url": "https://example.com/data-centre-rule",
        }
        item_id = briefing._candidate_editor_key(item)[:16]
        verbose = {
            "items": [
                {
                    "id": item_id,
                    "title": "香港公布数据中心能源使用新规",
                    "summary": "香港提高数据中心能源披露要求，相关运营方将面对新的合规与成本安排。",
                    "should_include": True,
                    "region": "香港本地",
                    "category": "行业动态",
                    "keywords": "Data center",
                    "inclusion_reason": "数据中心新规将改变基础设施运营要求。",
                    "region_reason": "政策在香港发布。",
                    "decision_path": "战略信号",
                    "signal_type": "监管政策",
                    "business_impact": "一整段不合法的自由文本",
                    "exclusion_code": "无",
                }
            ]
        }
        compact = {
            "items": [
                {
                    "id": item_id,
                    "route": "S",
                    "signal": "R",
                    "impact": "L",
                    "exclude": "0",
                    "region": "H",
                }
            ]
        }
        with (
            mock.patch.object(briefing, "_read_json", return_value={"items": {}}),
            mock.patch.object(briefing, "_atomic_write_json"),
            mock.patch.object(
                briefing,
                "_call_internal_ai",
                side_effect=[verbose, compact],
            ) as call,
        ):
            result = briefing.polish_candidates_before_review([item])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["ai_business_impact"], "合规与牌照")
        self.assertEqual(result[0]["ai_decision_path"], "战略信号")
        self.assertEqual(result[0]["ai_category"], "政策监管")
        self.assertEqual(call.call_count, 2)

    def test_plain_text_ai_rescue_keeps_real_international_competitor(self):
        item = {
            "module": "竞争对手",
            "category": "竞对动态",
            "title": "Vodafone Qatar reports 22% increase in net profit for H1",
            "snippet": "Vodafone Qatar announced its consolidated half-year results.",
            "keywords": ["Vodafone"],
            "source": "Example",
            "url": "https://example.com/vodafone-results",
        }
        with mock.patch.object(
            briefing,
            "_call_internal_ai",
            return_value={
                "_plain_text": (
                    "C|I|C|R|0|沃达丰卡塔尔上半年净利润增长22%|"
                    "沃达丰卡塔尔公布上半年业绩，净利润同比增长22%。"
                )
            },
        ):
            result = briefing._plain_text_rescue_review(
                item,
                model_override="deepseek-v4",
            )

        self.assertTrue(result["should_include"])
        self.assertEqual(result["decision_path"], "竞对直通")
        self.assertEqual(result["category"], "竞对动态")
        self.assertEqual(result["region"], "国际/行业")

    def test_candidate_editor_input_includes_publication_and_review_time(self):
        item = {
            "title": "李家超：冀9月公布首份五年规划",
            "snippet": "五年规划咨询将于本周五结束。",
            "published_at": "2026-08-09T09:00:00+08:00",
        }
        with mock.patch.object(
            briefing, "_now_iso", return_value="2026-08-10T10:30:00+08:00"
        ):
            payload = briefing._candidate_editor_input("item-key", item)

        self.assertEqual(payload["published_at_hkt"], "2026-08-09T09:00:00+08:00")
        self.assertEqual(payload["reviewed_at_hkt"], "2026-08-10T10:30:00+08:00")

    def test_candidate_editor_key_changes_when_publication_time_changes(self):
        item = {
            "title": "同一标题",
            "snippet": "同一摘要内容。",
            "published_at": "2026-08-09T09:00:00+08:00",
        }
        changed = {**item, "published_at": "2026-08-10T09:00:00+08:00"}

        self.assertNotEqual(
            briefing._candidate_editor_key(item),
            briefing._candidate_editor_key(changed),
        )

    def test_ai_copy_rejects_future_event_rewritten_as_completed(self):
        with self.assertRaisesRegex(RuntimeError, "尚未发生.*结束"):
            briefing._validated_ai_copy(
                {
                    "title": "香港首份五年规划咨询结束",
                    "summary": "香港首份五年规划咨询已结束，政府正整理分析意见。",
                },
                source_item={
                    "source_summary": (
                        "行政长官表示，五年规划咨询将于在本周五结束，"
                        "政府正不停蹄整理及分析意见。"
                    )
                },
            )

    def test_ai_copy_accepts_future_event_when_tense_is_preserved(self):
        result = briefing._validated_ai_copy(
            {
                "title": "香港首份五年规划咨询将结束",
                "summary": "香港首份五年规划咨询将于本周五结束，政府正整理分析意见。",
            },
            source_item={
                "source_summary": "五年规划咨询将于在本周五结束，政府正整理分析意见。"
            },
        )

        self.assertIn("将于本周五结束", result["summary"])

    def test_ai_copy_accepts_completed_event_when_source_is_completed(self):
        result = briefing._validated_ai_copy(
            {
                "title": "香港首份五年规划咨询结束",
                "summary": "香港首份五年规划咨询已结束，政府开始整理分析意见。",
            },
            source_item={
                "source_summary": "五年规划咨询已结束，政府开始整理分析意见。"
            },
        )

        self.assertIn("已结束", result["summary"])

    def test_single_item_retry_time_budget_defers_after_deadline(self):
        items = [
            {
                "module": "基础设施/网络/技术类",
                "category": "行业动态",
                "title": f"海外企业发布技术活动简报{i}",
                "snippet": "该企业介绍社区活动，并在背景材料中偶然提到人工智能。",
                "keywords": ["AI"],
                "source": "Example",
                "url": f"https://example.com/community/{i}",
            }
            for i in range(2)
        ]
        writes = []
        with (
            mock.patch.object(briefing, "_read_json", return_value={"items": {}}),
            mock.patch.object(
                briefing,
                "_atomic_write_json",
                side_effect=lambda path, payload: writes.append((path, payload)),
            ),
            mock.patch.object(briefing, "_call_internal_ai", return_value={}) as call,
            mock.patch.object(briefing, "AI_EDITOR_SINGLE_RETRY_MAX_SECONDS", 0),
        ):
            result = briefing.polish_candidates_before_review(items)

        self.assertEqual(result, [])
        self.assertEqual(call.call_count, 2)
        audit = next(
            payload
            for path, payload in writes
            if path == briefing.AI_EDITOR_AUDIT_PATH
        )
        self.assertEqual(audit["single_retry_attempt_count"], 0)
        self.assertEqual(audit["retry_time_budget_exhausted_count"], 2)
        self.assertEqual(audit["compact_retry_item_count"], 2)
        self.assertEqual(audit["compact_retry_resolved_count"], 0)
        self.assertFalse(audit["write_blocked"])

    def test_single_item_retry_reviews_every_failed_candidate_without_count_cap(self):
        items = [
            {
                "module": "竞争对手",
                "category": "竞对动态",
                "title": f"KDDI发布网络计划{i}",
                "snippet": "KDDI announced a network plan.",
                "keywords": ["KDDI"],
                "source": "Example",
                "url": f"https://example.com/kddi/{i}",
            }
            for i in range(13)
        ]

        def ai_response(system_prompt, user_prompt, **_kwargs):
            if "字段为title、summary" not in system_prompt:
                return {}
            source = json.loads(user_prompt)
            return {
                "title": source["title"],
                "summary": "KDDI公布网络建设计划及后续服务安排。",
                "should_include": True,
                "region": "国际/行业",
                "category": "竞对动态",
                "keywords": "KDDI",
                "inclusion_reason": "KDDI公布网络建设计划，影响竞对网络部署。",
                "region_reason": "事件主体为国际运营商KDDI。",
                "decision_path": "竞对直通",
                "signal_type": "竞对经营动作",
                "business_impact": "网络与运营",
                "exclusion_code": "",
            }

        writes = []
        with (
            mock.patch.object(briefing, "_read_json", return_value={"items": {}}),
            mock.patch.object(
                briefing,
                "_atomic_write_json",
                side_effect=lambda path, payload: writes.append((path, payload)),
            ),
            mock.patch.object(briefing, "_call_internal_ai", side_effect=ai_response),
            mock.patch.object(briefing.time, "monotonic", return_value=100.0),
        ):
            result = briefing.polish_candidates_before_review(items)

        audit = next(
            payload
            for path, payload in writes
            if path == briefing.AI_EDITOR_AUDIT_PATH
        )
        self.assertEqual(len(result), 13)
        self.assertEqual(audit["single_retry_attempt_count"], 13)
        self.assertEqual(audit["retry_time_budget_exhausted_count"], 0)
        self.assertEqual(audit["deferred_count"], 0)
        self.assertEqual(audit["single_retry_time_budget_seconds"], 1800)

    def test_competitor_route_fills_format_only_impact_without_blocking(self):
        result = briefing._validated_ai_copy(
            {
                "title": "SmarTone调整门店客户服务时间",
                "summary": "SmarTone公布门店客户服务时间调整，直接影响现有客户服务安排。",
                "should_include": True,
                "region": "香港本地",
                "category": "竞对动态",
                "keywords": "SmarTone",
                "inclusion_reason": "门店服务时间调整属于竞对客户服务信息。",
                "region_reason": "事件主体及受影响门店均在香港。",
                "decision_path": "竞对直通",
                "signal_type": "",
                "business_impact": "无",
                "exclusion_code": "",
            },
            require_review_fields=True,
            require_decision_fields=True,
            allowed_keywords="SmarTone",
            source_item={
                "module": "竞争对手",
                "title": "SmarTone调整门店客户服务时间",
                "keywords": ["SmarTone"],
            },
        )

        self.assertTrue(result["should_include"])
        self.assertEqual(result["signal_type"], "竞对经营动作")
        self.assertEqual(result["business_impact"], "竞争格局")
        self.assertEqual(result["exclusion_code"], "无")

    def test_ai_competitor_decision_is_not_overridden_by_code(self):
        result = briefing._validated_ai_copy(
                {
                    "title": "AT&T开展社区数字技能培训",
                    "summary": "AT&T在当地社区开设数字技能培训项目并向居民提供设备。",
                    "should_include": False,
                    "region": "国际/行业",
                    "category": "行业动态",
                    "keywords": "AT&T",
                    "inclusion_reason": "活动规模较小，缺少战略价值。",
                    "region_reason": "事件发生在美国。",
                    "decision_path": "排除",
                    "signal_type": "无",
                    "business_impact": "无",
                    "exclusion_code": "无电信战略影响",
                },
                require_review_fields=True,
                require_decision_fields=True,
                allowed_keywords="AT&T",
                source_item={
                    "module": "竞争对手",
                    "title": "AT&T开展社区数字技能培训",
                    "snippet": "AT&T opened a digital skills training center.",
                    "keywords": ["AT&T"],
                },
            )
        self.assertFalse(result["should_include"])

    def test_confirmed_competitor_event_is_included_even_when_routine(self):
        item = {
            "module": "竞争对手",
            "category": "行业动态",
            "title": "T-Mobile推出常规客户服务更新",
            "snippet": "T-Mobile announced a routine customer service update.",
            "keywords": ["T-Mobile"],
            "source": "Example News",
            "url": "https://example.com/news/t-mobile-service",
            "ai_title": "T-Mobile更新客户服务安排",
            "ai_summary": "T-Mobile公布常规客户服务调整，涉及现有用户的服务安排。",
            "ai_should_include": True,
            "ai_region": "国际/行业",
            "ai_category": "竞对动态",
            "ai_keywords": "T-Mobile",
            "ai_inclusion_reason": "客户服务调整直接影响用户体验与渠道运营。",
            "ai_region_reason": "事件主体和受影响市场均位于美国。",
            "ai_decision_path": "竞对直通",
            "ai_signal_type": "竞对经营动作",
            "ai_business_impact": "客户与渠道",
            "ai_exclusion_code": "无",
            "ai_editor_version": briefing.AI_EDITOR_VERSION,
        }

        with (
            mock.patch.object(briefing, "_read_json", return_value={"items": {}}),
            mock.patch.object(briefing, "_atomic_write_json"),
            mock.patch.object(briefing, "_call_internal_ai") as ai_call,
        ):
            result = briefing.polish_candidates_before_review([item])

        self.assertEqual(len(result), 1)
        ai_call.assert_not_called()

    def test_batch_editor_failure_uses_compact_review_before_single_item_copy(self):
        item = {
            "module": "竞争对手",
            "category": "竞对动态",
            "title": "HKBN推出企业宽频服务更新",
            "snippet": "HKBN announced an enterprise broadband service update in Hong Kong.",
            "keywords": ["HKBN"],
            "source": "Example News",
            "url": "https://example.com/news/hkbn-broadband",
        }
        single_result = {
            "title": "香港宽频更新企业宽频服务",
            "summary": "香港宽频在香港推出企业宽频服务更新，调整企业客户的网络服务安排。",
            "should_include": True,
            "region": "香港本地",
            "category": "竞对动态",
            "keywords": "HKBN",
            "inclusion_reason": "直接反映香港宽频的企业客户产品与服务变化。",
            "region_reason": "事件主体及受影响市场均在香港。",
            "decision_path": "竞对直通",
            "signal_type": "竞对经营动作",
            "business_impact": "产品与定价",
            "exclusion_code": "无",
        }
        compact_result = {
            "items": [
                {
                    "id": briefing._candidate_editor_key(item)[:16],
                    "route": "C",
                    "signal": "C",
                    "impact": "P",
                    "exclude": "0",
                    "region": "H",
                }
            ]
        }
        with (
            mock.patch.object(briefing, "_read_json", return_value={"items": {}}),
            mock.patch.object(briefing, "_atomic_write_json"),
            mock.patch.object(
                briefing,
                "_call_internal_ai",
                side_effect=[
                    ValueError("unterminated JSON"),
                    compact_result,
                    single_result,
                ],
            ) as ai_call,
        ):
            result = briefing.polish_candidates_before_review([item])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["ai_title"], single_result["title"])
        self.assertEqual(ai_call.call_count, 3)

    def test_batch_parse_failure_compactly_excludes_noise_without_single_retry(self):
        item = {
            "module": "竞争对手",
            "category": "竞对动态",
            "title": "BMW M4 CSL发布轻量化跑车",
            "snippet": "BMW introduced a lightweight sports car.",
            "keywords": ["csl"],
            "source": "Example News",
            "url": "https://example.com/news/bmw-m4-csl",
        }
        compact_result = {
            "items": [
                {
                    "id": briefing._candidate_editor_key(item)[:16],
                    "route": "X",
                    "signal": "0",
                    "impact": "0",
                    "exclude": "1",
                    "region": "I",
                }
            ]
        }
        writes = []
        with (
            mock.patch.object(briefing, "_read_json", return_value={"items": {}}),
            mock.patch.object(
                briefing,
                "_atomic_write_json",
                side_effect=lambda path, payload: writes.append((path, payload)),
            ),
            mock.patch.object(
                briefing,
                "_call_internal_ai",
                side_effect=[ValueError("unterminated JSON"), compact_result],
            ) as ai_call,
        ):
            result = briefing.polish_candidates_before_review([item])

        self.assertEqual(result, [])
        self.assertEqual(ai_call.call_count, 2)
        audit = next(
            payload
            for path, payload in writes
            if path == briefing.AI_EDITOR_AUDIT_PATH
        )
        self.assertEqual(audit["deferred_count"], 0)
        self.assertEqual(audit["compact_retry_resolved_count"], 1)
        self.assertEqual(audit["single_retry_attempt_count"], 0)

    def test_editor_defers_fully_failed_ai_batch_without_blocking(self):
        item = {
            "module": "竞争对手",
            "category": "竞对动态",
            "title": "KDDI与Globe合作改造零售门店",
            "snippet": "KDDI and Globe announced a retail store partnership.",
            "keywords": ["KDDI"],
            "source": "Example News",
            "url": "https://example.com/news/kddi-globe",
        }
        writes = []
        with (
            mock.patch.object(briefing, "_read_json", return_value={"items": {}}),
            mock.patch.object(
                briefing,
                "_atomic_write_json",
                side_effect=lambda path, payload: writes.append((path, payload)),
            ),
            mock.patch.object(
                briefing,
                "_call_internal_ai",
                side_effect=RuntimeError("rate limited"),
            ),
        ):
            result = briefing.polish_candidates_before_review([item])

        self.assertEqual(result, [])
        audit = next(
            payload
            for path, payload in writes
            if path == briefing.AI_EDITOR_AUDIT_PATH
        )
        self.assertEqual(audit["input_count"], 1)
        self.assertEqual(audit["resolved_count"], 0)
        self.assertEqual(audit["deferred_count"], 1)
        self.assertTrue(audit["continued_with_partial_results"])
        self.assertFalse(audit["write_blocked"])
        self.assertFalse(audit["policy"]["batch_blocking"])
        queue = next(
            payload
            for path, payload in writes
            if path == briefing.AI_EDITOR_DEFERRED_PATH
        )
        self.assertEqual(queue["items"][0]["attempts"], 1)
        self.assertEqual(queue["items"][0]["item"]["url"], item["url"])
        self.assertEqual(audit["deferred_queue"]["queued_count"], 1)

    def test_deferred_queue_honors_cooldown_then_acks_delivered_item(self):
        item = {
            "module": "竞争对手",
            "category": "竞对动态",
            "title": "KDDI发布网络升级计划",
            "snippet": "KDDI announced a network upgrade.",
            "source": "Example News",
            "url": "https://example.com/news/kddi-network-upgrade",
        }
        key = briefing._candidate_editor_key(item)
        first_attempt = datetime(2026, 8, 9, 9, 0, tzinfo=briefing.HKT)
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            briefing,
            "AI_EDITOR_DEFERRED_PATH",
            Path(directory) / "deferred.json",
        ):
            initial = briefing._persist_deferred_ai_candidates(
                {},
                [item],
                [{"key": key, "error": "rate limited"}],
                now=first_attempt,
            )
            cooled_items, cooled_records, cooled_stats = (
                briefing._prepare_deferred_ai_candidates(
                    [item],
                    now=first_attempt + timedelta(minutes=10),
                )
            )
            retry_items, retry_records, retry_stats = (
                briefing._prepare_deferred_ai_candidates(
                    [],
                    now=first_attempt
                    + timedelta(minutes=briefing.AI_EDITOR_DEFERRED_RETRY_MINUTES + 1),
                )
            )
            source_retry_items, _, source_retry_stats = (
                briefing._prepare_deferred_ai_candidates(
                    [item, item],
                    now=first_attempt
                    + timedelta(minutes=briefing.AI_EDITOR_DEFERRED_RETRY_MINUTES + 1),
                )
            )
            resolved = briefing._persist_deferred_ai_candidates(
                retry_records,
                retry_items,
                [],
                pending_delivery_items=retry_items,
                now=first_attempt + timedelta(hours=1),
            )
            pending = briefing._read_json(
                briefing.AI_EDITOR_DEFERRED_PATH, {}
            )
            acknowledged = briefing.acknowledge_deferred_ai_candidates(
                retry_items,
                now=first_attempt + timedelta(hours=1, minutes=1),
            )
            saved = briefing._read_json(briefing.AI_EDITOR_DEFERRED_PATH, {})

        self.assertEqual(initial["queued_count"], 1)
        self.assertEqual(cooled_items, [])
        self.assertEqual(cooled_stats["cooldown_count"], 1)
        self.assertIn(key, cooled_records)
        self.assertEqual(retry_items, [item])
        self.assertEqual(retry_stats["retry_loaded_count"], 1)
        self.assertEqual(source_retry_items, [item])
        self.assertEqual(source_retry_stats["retry_loaded_count"], 1)
        self.assertEqual(resolved["resolved_removed_count"], 0)
        self.assertEqual(resolved["pending_delivery_count"], 1)
        self.assertEqual(pending["items"][0]["status"], "pending_delivery")
        self.assertEqual(acknowledged["removed_count"], 1)
        self.assertEqual(saved["items"], [])

    def test_pending_delivery_bypasses_cooldown_and_survives_until_ack(self):
        item = {
            "category": "行业动态",
            "title": "数据中心扩建",
            "snippet": "A new data centre expansion was announced.",
            "source": "Example",
            "url": "https://example.com/data-centre-expansion",
        }
        now = datetime(2026, 8, 15, 10, 0, tzinfo=briefing.HKT)
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            briefing,
            "AI_EDITOR_DEFERRED_PATH",
            Path(directory) / "deferred.json",
        ):
            persisted = briefing._persist_deferred_ai_candidates(
                {},
                [item],
                [],
                pending_delivery_items=[item],
                now=now,
            )
            loaded, _records, stats = briefing._prepare_deferred_ai_candidates(
                [],
                now=now + timedelta(minutes=1),
            )
            before_ack = briefing.has_pending_ai_candidates()
            briefing.acknowledge_deferred_ai_candidates(loaded, now=now)
            after_ack = briefing.has_pending_ai_candidates()

        self.assertEqual(persisted["pending_delivery_count"], 1)
        self.assertEqual(loaded, [item])
        self.assertEqual(stats["cooldown_count"], 0)
        self.assertTrue(before_ack)
        self.assertFalse(after_ack)

    def test_deferred_delivery_key_stays_pinned_after_ai_field_rewrites(self):
        item = {
            "module": "竞争对手",
            "category": "行业动态",
            "title": "KDDI announces a network investment",
            "snippet": "KDDI announced a concrete network investment.",
            "source": "Example",
            "url": "https://example.com/kddi-investment",
            "keywords": "KDDI",
        }
        original_key = briefing._candidate_editor_key(item)
        rewritten = {
            **item,
            "source_title": item["title"],
            "title": "KDDI宣布网络投资",
            "category": "竞对动态",
            "region": "国际/行业",
            "_ai_editor_queue_key": original_key,
        }

        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            briefing,
            "AI_EDITOR_DEFERRED_PATH",
            Path(directory) / "deferred.json",
        ):
            persisted = briefing._persist_deferred_ai_candidates(
                {},
                [item],
                [],
                pending_delivery_items=[rewritten],
            )
            queued = briefing._read_json(
                briefing.AI_EDITOR_DEFERRED_PATH, {}
            )
            acknowledged = briefing.acknowledge_deferred_ai_candidates(
                [rewritten]
            )

        self.assertEqual(briefing._candidate_editor_key(rewritten), original_key)
        self.assertEqual(persisted["pending_delivery_count"], 1)
        self.assertEqual(queued["items"][0]["key"], original_key)
        self.assertEqual(acknowledged["removed_count"], 1)

    def test_deferred_queue_prunes_invalid_but_retains_old_and_retried_records(self):
        now = datetime(2026, 8, 9, 12, 0, tzinfo=briefing.HKT)
        base_item = {
            "category": "行业动态",
            "title": "AI基础设施投资增加",
            "snippet": "Operators increased AI infrastructure investment.",
            "source": "Example",
            "url": "https://example.com/news/ai-infrastructure",
        }
        invalid = {"editor_version": briefing.AI_EDITOR_VERSION, "attempts": "bad", "item": base_item}
        expired_item = {**base_item, "url": "https://example.com/news/expired"}
        exhausted_item = {**base_item, "url": "https://example.com/news/exhausted"}
        payload = {
            "items": [
                invalid,
                {
                    "editor_version": briefing.AI_EDITOR_VERSION,
                    "attempts": 1,
                    "queued_at": (now - timedelta(days=30)).isoformat(),
                    "item": expired_item,
                },
                {
                    "editor_version": briefing.AI_EDITOR_VERSION,
                    "attempts": 99,
                    "queued_at": now.isoformat(),
                    "item": exhausted_item,
                },
            ]
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            briefing,
            "AI_EDITOR_DEFERRED_PATH",
            Path(directory) / "deferred.json",
        ):
            briefing._atomic_write_json(briefing.AI_EDITOR_DEFERRED_PATH, payload)
            items, records, stats = briefing._prepare_deferred_ai_candidates([], now=now)

        self.assertEqual(items, [expired_item, exhausted_item])
        self.assertEqual(len(records), 2)
        self.assertEqual(stats["invalid_count"], 1)
        self.assertEqual(stats["expired_count"], 0)
        self.assertEqual(stats["exhausted_count"], 0)

    def test_deferred_queue_has_no_item_cap_and_retains_until_resolved(self):
        now = datetime(2026, 8, 9, 12, 0, tzinfo=briefing.HKT)
        items = [
            {
                "category": "行业动态",
                "title": f"候选 {index}",
                "snippet": "等待可靠AI审核。",
                "source": "Example",
                "url": f"https://example.com/news/{index}",
            }
            for index in range(605)
        ]
        deferred = [
            {"key": briefing._candidate_editor_key(item), "error": "temporary AI failure"}
            for item in items
        ]
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            briefing,
            "AI_EDITOR_DEFERRED_PATH",
            Path(directory) / "deferred.json",
        ):
            stats = briefing._persist_deferred_ai_candidates(
                {}, items, deferred, now=now
            )
            saved = briefing._read_json(briefing.AI_EDITOR_DEFERRED_PATH, {})

        self.assertEqual(stats["queued_count"], 605)
        self.assertEqual(stats["capped_count"], 0)
        self.assertEqual(len(saved["items"]), 605)
        self.assertEqual(saved["policy"]["retention"], "until_resolved")
        self.assertNotIn("max_items", saved["policy"])

    def test_deferred_queue_migrates_previous_editor_version(self):
        now = datetime(2026, 8, 10, 10, 0, tzinfo=briefing.HKT)
        item = {
            "category": "政策监管",
            "title": "香港公布监管咨询安排",
            "snippet": "监管咨询将于本周五结束。",
            "published_at": "2026-08-09T09:00:00+08:00",
            "source": "Example",
            "url": "https://example.com/news/consultation",
        }
        payload = {
            "items": [
                {
                    "editor_version": briefing.AI_EDITOR_VERSION - 1,
                    "attempts": 1,
                    "queued_at": (now - timedelta(hours=1)).isoformat(),
                    "last_attempt_at": (now - timedelta(hours=1)).isoformat(),
                    "item": item,
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            briefing,
            "AI_EDITOR_DEFERRED_PATH",
            Path(directory) / "deferred.json",
        ):
            briefing._atomic_write_json(briefing.AI_EDITOR_DEFERRED_PATH, payload)
            items, records, stats = briefing._prepare_deferred_ai_candidates([], now=now)

        key = briefing._candidate_editor_key(item)
        self.assertEqual(items, [item])
        self.assertEqual(records[key]["editor_version"], briefing.AI_EDITOR_VERSION)
        self.assertEqual(stats["migrated_count"], 1)
        self.assertEqual(stats["invalid_count"], 0)

    def test_editor_isolates_one_failed_item_and_continues_resolved_items(self):
        items = []
        for index in range(1):
            items.append(
                {
                    "module": "竞争对手",
                    "category": "竞对动态",
                    "title": f"Verizon发布第{index + 1}项网络更新",
                    "snippet": "Verizon announced a network service update.",
                    "keywords": ["Verizon"],
                    "source": "Example News",
                    "url": f"https://example.com/news/verizon-{index + 1}",
                    "ai_title": f"Verizon发布第{index + 1}项网络更新",
                    "ai_summary": "Verizon公布网络服务更新及相关客户安排。",
                    "ai_should_include": True,
                    "ai_region": "国际/行业",
                    "ai_category": "竞对动态",
                    "ai_keywords": "Verizon",
                    "ai_inclusion_reason": "直接反映被监测竞对的网络服务变化。",
                    "ai_region_reason": "事件主体为国际对标运营商Verizon。",
                    "ai_decision_path": "竞对直通",
                    "ai_signal_type": "竞对经营动作",
                    "ai_business_impact": "网络与运营",
                    "ai_exclusion_code": "无",
                    "ai_editor_version": briefing.AI_EDITOR_VERSION,
                }
            )
        items.append(
            {
                "module": "竞争对手",
                "category": "竞对动态",
                "title": "KDDI发布门店更新",
                "snippet": "KDDI announced a retail store update.",
                "keywords": ["KDDI"],
                "source": "Example News",
                "url": "https://example.com/news/kddi-store",
            }
        )
        writes = []
        with (
            mock.patch.object(briefing, "_read_json", return_value={"items": {}}),
            mock.patch.object(
                briefing,
                "_atomic_write_json",
                side_effect=lambda path, payload: writes.append((path, payload)),
            ),
            mock.patch.object(
                briefing,
                "_call_internal_ai",
                side_effect=RuntimeError("rate limited"),
            ),
        ):
            result = briefing.polish_candidates_before_review(items)

        self.assertEqual(len(result), 1)
        audit = next(
            payload
            for path, payload in writes
            if path == briefing.AI_EDITOR_AUDIT_PATH
        )
        self.assertEqual(audit["resolved_count"], 1)
        self.assertEqual(audit["deferred_count"], 1)
        self.assertTrue(audit["continued_with_partial_results"])
        self.assertFalse(audit["write_blocked"])

    def test_cached_ai_business_decision_is_not_overridden_by_code(self):
        item = {
            "module": "竞争对手",
            "category": "竞对动态",
            "title": "Globe partners with Japan's KDDI to reinvent retail stores",
            "snippet": "Globe Telecom is partnering with KDDI on physical retail.",
            "keywords": ["KDDI"],
            "source": "Example News",
            "url": "https://example.com/news/kddi-globe",
        }
        wrong = {
            "title": "Globe与日本KDDI合作重塑零售门店",
            "summary": "Globe与日本KDDI达成合作，共同优化实体零售门店体验。",
            "should_include": False,
            "region": "国际/行业",
            "category": "行业动态",
            "keywords": "KDDI",
            "inclusion_reason": "KDDI不是目标竞对，因此不纳入监控。",
            "region_reason": "事件发生在菲律宾与日本市场。",
            "decision_path": "排除",
            "signal_type": "无",
            "business_impact": "无",
            "exclusion_code": "同名或主体误判",
            "editor_version": briefing.AI_EDITOR_VERSION,
        }
        with (
            mock.patch.object(
                briefing,
                "_read_json",
                return_value={
                    "items": {briefing._candidate_editor_key(item): wrong}
                },
            ),
            mock.patch.object(briefing, "_atomic_write_json"),
            mock.patch.object(
                briefing,
                "_call_internal_ai",
            ) as ai_call,
        ):
            result = briefing.polish_candidates_before_review([item])

        self.assertEqual(result, [])
        ai_call.assert_not_called()

    def test_semantic_agent_deduplicates_same_event_with_different_headline(self):
        item = {
            "news_id": "candidate-1",
            "ai_title": "Verizon第二季度业绩超出预期",
            "ai_summary": "Verizon公布第二季度财报，收入与用户表现超过市场预期。",
            "source_date": "2026-07-25",
            "source": "媒体甲",
            "url": "https://example.com/verizon-results-cn",
        }
        history = [
            {
                "news_id": "history-1",
                "title": "Verizon Q2 results beat expectations",
                "summary": "The carrier reported its second-quarter revenue and subscriber results.",
                "source_date": "2026-07-25",
                "source": "媒体乙",
                "source_url": "https://example.com/verizon-results-en",
            }
        ]
        with (
            mock.patch.object(
                briefing,
                "_call_internal_ai",
                return_value={
                    "items": [
                        {
                            "id": "candidate-1",
                            "is_duplicate": True,
                            "duplicate_of": "history-1",
                            "reason": "两条记录均描述Verizon同一份第二季度财报及同一组业绩结果。",
                        }
                    ]
                },
            ),
            mock.patch.object(briefing, "_atomic_write_json"),
        ):
            result = briefing.agent_semantic_deduplicate_candidates([item], history)

        self.assertEqual(result["kept"], [])
        self.assertEqual(len(result["duplicates"]), 1)
        self.assertEqual(result["duplicates"][0]["duplicate_of"], "history-1")

    def test_semantic_agent_independently_confirms_same_batch_events(self):
        first = {
            "news_id": "candidate-a",
            "ai_title": "Verizon门店连续第14年举办免费背包活动",
            "ai_summary": "Verizon授权门店在返校季向家庭免费派发背包。",
            "source_date": "2026-07-26",
            "source": "媒体甲",
            "url": "https://example.com/verizon-backpack-a",
        }
        second = {
            "news_id": "candidate-b",
            "ai_title": "Verizon TCC举办返校季背包赠送活动",
            "ai_summary": "Verizon门店举办School Rocks活动并向学生免费赠送背包。",
            "source_date": "2026-07-26",
            "source": "媒体乙",
            "url": "https://example.com/verizon-backpack-b",
        }
        responses = [
            {
                "items": [
                    {
                        "id": "candidate-a",
                        "is_duplicate": False,
                        "duplicate_of": "",
                        "reason": "当前历史中没有相同活动记录。",
                    },
                    {
                        "id": "candidate-b",
                        "is_duplicate": False,
                        "duplicate_of": "",
                        "reason": "批量初审暂未确认与其他记录重复。",
                    },
                ]
            },
            {
                "items": [
                    {
                        "id": "candidate-a",
                        "is_duplicate": False,
                        "duplicate_of": "",
                        "reason": "独立复核未发现更早的相同活动。",
                    },
                    {
                        "id": "candidate-b",
                        "is_duplicate": True,
                        "duplicate_of": "candidate-a",
                        "reason": "两条记录均为Verizon返校季免费背包派发活动。",
                    }
                ]
            },
        ]
        with (
            mock.patch.object(
                briefing,
                "_call_internal_ai",
                side_effect=responses,
            ),
            mock.patch.object(briefing, "_atomic_write_json"),
        ):
            result = briefing.agent_semantic_deduplicate_candidates(
                [first, second],
                [],
            )

        self.assertEqual(result["kept"], [first])
        self.assertEqual(len(result["duplicates"]), 1)
        self.assertEqual(result["duplicates"][0]["duplicate_of"], "candidate-a")

    def test_semantic_dedupe_uses_high_confidence_competitor_event_signature(self):
        item = {
            "news_id": "candidate-erie",
            "ai_title": "Verizon门店参与Erie社区返校季背包赠送活动",
            "ai_summary": "Verizon门店参与School Rocks活动并向学生免费赠送书包。",
            "source_date": "2026-07-27",
            "source": "媒体甲",
            "url": "https://example.com/verizon-erie",
        }
        history = [
            {
                "news_id": "history-backpack",
                "title": "Verizon门店举办返校季背包赠送活动",
                "summary": "Verizon门店向家庭免费派发背包。",
                "source_date": "2026-07-25",
                "source": "媒体乙",
                "source_url": "https://example.com/verizon-backpack",
            }
        ]
        with (
            mock.patch.object(briefing, "_call_internal_ai") as ai_call,
            mock.patch.object(briefing, "_atomic_write_json"),
        ):
            result = briefing.agent_semantic_deduplicate_candidates([item], history)

        self.assertEqual(result["kept"], [])
        self.assertEqual(len(result["duplicates"]), 1)
        self.assertEqual(
            result["duplicates"][0]["duplicate_of"],
            "history-backpack",
        )
        ai_call.assert_not_called()

    def test_semantic_priority_history_surfaces_exact_url_before_similar_topics(self):
        candidate = {
            "id": "candidate",
            "title": "Verizon门店举办返校季活动",
            "summary": "Verizon门店向家庭赠送背包。",
            "published_at": "2026-07-25",
            "url": "https://example.com/verizon-backpack?utm_source=rss",
        }
        history = [
            {
                "id": "same-topic",
                "title": "Verizon开展暑期客户活动",
                "summary": "Verizon在多个城市举办客户活动。",
                "published_at": "2026-07-25",
                "url": "https://example.com/verizon-summer",
            },
            {
                "id": "same-url",
                "title": "Local Verizon stores host backpack giveaways",
                "summary": "Stores give backpacks to families for back-to-school.",
                "published_at": "2026-07-25",
                "url": "https://example.com/verizon-backpack",
            },
        ]

        ranked = briefing._semantic_priority_history(candidate, history)

        self.assertEqual(ranked[0]["id"], "same-url")

    def test_semantic_agent_keeps_different_events_from_same_competitor(self):
        item = {
            "news_id": "candidate-2",
            "ai_title": "Verizon在纽约扩建5G网络",
            "ai_summary": "Verizon宣布在纽约新增5G基站并扩大网络覆盖。",
            "source_date": "2026-07-26",
            "source": "媒体甲",
            "url": "https://example.com/verizon-5g",
        }
        history = [
            {
                "news_id": "history-2",
                "title": "Verizon公布第二季度财报",
                "summary": "Verizon披露收入、利润和用户数据。",
                "source_date": "2026-07-25",
                "source": "媒体乙",
                "source_url": "https://example.com/verizon-results",
            }
        ]
        with (
            mock.patch.object(
                briefing,
                "_call_internal_ai",
                return_value={
                    "items": [
                        {
                            "id": "candidate-2",
                            "is_duplicate": False,
                            "duplicate_of": "",
                            "reason": "两条新闻虽涉及同一公司，但分别是网络扩建和财报披露两个不同事件。",
                        }
                    ]
                },
            ),
            mock.patch.object(briefing, "_atomic_write_json"),
        ):
            result = briefing.agent_semantic_deduplicate_candidates([item], history)

        self.assertEqual(result["kept"], [item])
        self.assertEqual(result["duplicates"], [])

    def test_semantic_agent_failure_defers_candidate_instead_of_bypassing(self):
        item = {
            "news_id": "candidate-3",
            "ai_title": "香港宽频推出企业服务",
            "ai_summary": "香港宽频公布新的企业连接服务及客户安排。",
            "source_date": "2026-07-26",
            "source": "媒体甲",
            "url": "https://example.com/hkbn-enterprise",
        }
        with (
            mock.patch.object(
                briefing,
                "_call_internal_ai",
                side_effect=RuntimeError("Agent unavailable"),
            ),
            mock.patch.object(briefing, "_atomic_write_json"),
        ):
            result = briefing.agent_semantic_deduplicate_candidates([item], [])

        self.assertEqual(result["kept"], [])
        self.assertEqual(result["duplicates"], [])
        self.assertEqual(len(result["deferred"]), 1)

    def test_semantic_agent_cannot_deny_same_id_or_url_identity_match(self):
        item = {
            "news_id": "same-id",
            "ai_title": "Verizon门店举办返校季活动",
            "ai_summary": "Verizon门店向家庭赠送背包。",
            "source_date": "2026-07-25",
            "source": "媒体甲",
            "url": "https://example.com/verizon-backpack",
        }
        history = [
            {
                "news_id": "same-id",
                "title": "Local Verizon stores host backpack giveaways",
                "summary": "Stores give backpacks to families.",
                "source_date": "2026-07-25",
                "source": "媒体乙",
                "source_url": "https://example.com/verizon-backpack",
            }
        ]
        with (
            mock.patch.object(
                briefing,
                "_call_internal_ai",
            ) as ai_call,
            mock.patch.object(briefing, "_atomic_write_json"),
        ):
            result = briefing.agent_semantic_deduplicate_candidates([item], history)

        self.assertEqual(result["kept"], [])
        self.assertEqual(len(result["duplicates"]), 1)
        self.assertEqual(result["duplicates"][0]["duplicate_of"], "same-id")
        self.assertEqual(result["deferred"], [])
        ai_call.assert_not_called()

    def test_candidate_editor_passes_competitor_hint_without_prejudging(self):
        payload = briefing._candidate_editor_input(
            "1234567890abcdef",
            {
                "module": "竞争对手",
                "title": "HKBN launches a broadband service update",
                "snippet": "HKBN announced the service change in Hong Kong.",
                "keywords": ["HKBN"],
                "canonical_competitor": "HKBN",
            },
        )
        self.assertEqual(payload["configured_competitor_hint"], "HKBN")
        self.assertNotIn("competitor_candidate", payload)

    def test_editor_tells_agent_to_distinguish_hong_kong_csl_from_csl_limited(self):
        item = {
            "module": "竞争对手",
            "category": "竞对动态",
            "title": "CSL profit expected to remain flat in FY27",
            "snippet": "A broker maintained its rating on the Australian company.",
            "keywords": ["csl"],
            "source": "Market News",
            "url": "https://example.com/news/csl-rating",
        }
        ai_result = {
            "items": [
                {
                    "id": briefing._candidate_editor_key(item)[:16],
                    "title": "CSL预计FY27利润持平",
                    "summary": "券商预计澳洲CSL公司FY27利润持平，并维持其股票评级。",
                    "should_include": False,
                    "region": "国际/行业",
                    "category": "行业动态",
                    "keywords": "csl",
                    "inclusion_reason": "主体是澳洲生物科技公司CSL Limited，并非香港csl电讯品牌。",
                    "region_reason": "事件主体为澳洲公司。",
                    "decision_path": "排除",
                    "signal_type": "无",
                    "business_impact": "无",
                    "exclusion_code": "同名或主体误判",
                }
            ]
        }
        with (
            mock.patch.object(briefing, "_read_json", return_value={"items": {}}),
            mock.patch.object(briefing, "_atomic_write_json"),
            mock.patch.object(
                briefing,
                "_call_internal_ai",
                return_value=ai_result,
            ) as ai_call,
        ):
            result = briefing.polish_candidates_before_review([item])

        self.assertEqual(result, [])
        self.assertIn("澳洲生物科技公司CSL Limited", ai_call.call_args.args[0])

    def test_editor_prompt_declares_verified_international_operator_as_monitored_competitor(self):
        item = {
            "module": "竞争对手",
            "category": "竞对动态",
            "title": "Globe partners with Japan's KDDI to reinvent retail stores",
            "snippet": "Globe Telecom is partnering with KDDI on physical retail.",
            "keywords": ["KDDI"],
            "source": "Example News",
            "url": "https://example.com/news/kddi-globe",
        }
        ai_result = {
            "items": [
                {
                    "id": briefing._candidate_editor_key(item)[:16],
                    "title": "Globe与KDDI合作改造零售门店",
                    "summary": "Globe与日本运营商KDDI合作优化实体零售体验并探索业务增长机会。",
                    "should_include": True,
                    "region": "国际/行业",
                    "category": "竞对动态",
                    "keywords": "KDDI",
                    "inclusion_reason": "反映被监测国际运营商KDDI的渠道合作动态。",
                    "region_reason": "事件主体为菲律宾与日本运营商。",
                    "decision_path": "竞对直通",
                    "signal_type": "竞对经营动作",
                    "business_impact": "客户与渠道",
                    "exclusion_code": "无",
                }
            ]
        }
        with (
            mock.patch.object(briefing, "_read_json", return_value={"items": {}}),
            mock.patch.object(briefing, "_atomic_write_json"),
            mock.patch.object(
                briefing,
                "_call_internal_ai",
                return_value=ai_result,
            ) as ai_call,
        ):
            result = briefing.polish_candidates_before_review([item])

        self.assertEqual(len(result), 1)
        prompt = ai_call.call_args.args[0]
        self.assertIn("该运营商就是被监测竞对", prompt)
        self.assertIn("KDDI、AT&T、Verizon", prompt)

    def test_approved_brief_prompt_requires_simplified_chinese(self):
        with mock.patch.object(
            briefing,
            "_call_internal_ai",
            return_value={
                "title": "竞对推出新一代企业网络方案",
                "summary": "该公司发布新的企业网络方案，重点关注产品能力变化及市场影响。",
            },
        ) as call:
            briefing._polish_approved_brief(self._approved_brief())
        self.assertIn("简体中文", call.call_args.args[0])

    def test_polish_approved_brief_rejects_english_title(self):
        with mock.patch.object(
            briefing,
            "_call_internal_ai",
            return_value={
                "title": "English source headline",
                "summary": "这是一段符合长度要求但标题仍未中文化的中文摘要内容。",
            },
        ):
            with self.assertRaisesRegex(RuntimeError, "中文快讯标题"):
                briefing._polish_approved_brief(self._approved_brief())

    def test_ai_editor_failure_keeps_approved_item_pending(self):
        message = {
            "message_id": "message-1",
            "create_time": str(int(time.time() * 1000)),
            "msg_type": "text",
        }
        state = {}
        with (
            mock.patch.object(briefing, "_list_group_messages", return_value=([message], "bot")),
            mock.patch.object(briefing, "_message_text", return_value="确认发布 SB20260716M-01"),
            mock.patch.object(briefing, "_load_published", return_value=[]),
            mock.patch.object(briefing, "_load_candidates", return_value=[]),
            mock.patch.object(briefing, "_classify_approval", return_value=self._approved_brief()),
            mock.patch.object(briefing, "_polish_approved_brief", side_effect=RuntimeError("AI暂不可用")),
            mock.patch.object(briefing, "_save_published") as save,
        ):
            result = briefing._sync_group(datetime.now(briefing.HKT), state)
        self.assertEqual(result["published"], 0)
        self.assertEqual(len(state["pending_briefs"]), 1)
        self.assertIn("AI暂不可用", state["last_group_error"])
        save.assert_not_called()

    def test_ai_editor_success_publishes_pending_item(self):
        approved = self._approved_brief()
        polished = {
            **approved,
            "title": "竞对推出新一代企业网络方案",
            "summary": "该公司发布新的企业网络方案，重点关注产品能力变化及其对香港市场竞争格局的影响。",
            "ai_polished_at": "2026-07-16T12:00:00+08:00",
        }
        state = {"pending_briefs": [approved]}
        with (
            mock.patch.object(briefing, "_list_group_messages", return_value=([], "bot")),
            mock.patch.object(briefing, "_load_published", return_value=[]),
            mock.patch.object(briefing, "_load_candidates", return_value=[]),
            mock.patch.object(briefing, "_polish_approved_brief", return_value=polished),
            mock.patch.object(briefing, "_save_published") as save,
        ):
            result = briefing._sync_group(datetime.now(briefing.HKT), state)
        self.assertEqual(result["published"], 1)
        self.assertEqual(state["pending_briefs"], [])
        self.assertEqual(state["last_group_error"], "")
        save.assert_called_once()


if __name__ == "__main__":
    unittest.main()

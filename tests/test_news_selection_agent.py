from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from types import SimpleNamespace

from cmhk.intelligence import news_review_sheet
from cmhk.intelligence import news_selection_agent as agent


def _row(
    *,
    title: str,
    url: str,
    app: str = "待审核",
    weekly: str = "待审核",
) -> list[str]:
    return [
        "",
        app,
        weekly,
        "未同步",
        "2026-08-28",
        "香港",
        "电信与网络",
        title,
        title + "摘要",
        "测试媒体",
        "2026-08-28 09:00",
        url,
        "5G、香港",
        "影响香港电讯市场",
        "固定监控 → 新闻搜索",
    ]


def _review_event(
    *,
    event_id: str,
    title: str,
    field: str,
    after: str,
    at: str,
    actor_id: str,
    actor_name: str,
    actor_role: str,
    before: str = "待审核",
    **detail_overrides,
) -> dict:
    return {
        "id": event_id,
        "at": at,
        "actor_id": actor_id,
        "actor_name": actor_name,
        "actor_role": actor_role,
        "action": "news_review.update",
        "result": "success",
        "details": {
            "target_label": title,
            "field": field,
            "before": before,
            "after": after,
            **detail_overrides,
        },
    }


class NewsSelectionAgentTests(unittest.TestCase):
    def test_simplified_normalizes_model_explanations(self):
        self.assertEqual(agent._simplified("國際網絡與歷史取捨"), "国际网络与历史取舍")

    def test_default_news_selection_model_is_v4_pro(self):
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch.object(
                agent,
                "load_ai_config",
                return_value={"strategy_api_keys": ["secret"]},
            ),
        ):
            self.assertEqual(agent._model_routes()[0][0], "DeepSeek-V4-Pro")

    def test_human_examples_are_balanced_per_field_and_label(self):
        examples = []
        for field in ("app", "weekly"):
            other = "weekly" if field == "app" else "app"
            for index, status in enumerate(
                ["接受", "接受", "不接受", "不接受", "不接受"]
            ):
                examples.append(
                    {
                        "news_id": f"{field}-{index}",
                        "title": f"{field}-{status}-{index}",
                        f"{field}_status": status,
                        f"{other}_status": "待审核",
                        "verified_human_fields": [field],
                        "human_correction_fields": [field] if index == 1 else [],
                    }
                )

        balanced, stats = agent._balanced_human_examples(examples, per_class_limit=10)

        self.assertEqual(len(balanced), 10)
        self.assertEqual(stats["app_accept_count"], 2)
        self.assertEqual(stats["app_reject_count"], 3)
        self.assertEqual(stats["weekly_accept_count"], 2)
        self.assertEqual(stats["weekly_reject_count"], 3)
        self.assertEqual(stats["source_app_accept_count"], 2)
        self.assertEqual(stats["source_app_reject_count"], 3)
        self.assertEqual(stats["source_app_accept_rate"], 0.4)
        self.assertTrue(
            all(
                item["weekly_status"] == "待审核"
                for item in balanced
                if item["verified_human_fields"] == ["app"]
            )
        )

    def test_large_all_reject_batch_is_blocked_before_write(self):
        decisions = [
            {
                "news_id": f"NEWS-{index}",
                "app_before": "待审核",
                "weekly_before": "待审核",
                "app_status": "不接受",
                "weekly_status": "不接受",
            }
            for index in range(20)
        ]
        with self.assertRaisesRegex(RuntimeError, "整批全部不接受"):
            agent._validate_model_decision_distribution(decisions)

        decisions[0]["app_status"] = "接受"
        decisions[0]["weekly_status"] = "接受"
        agent._validate_model_decision_distribution(decisions)

    def test_implausibly_high_acceptance_is_blocked_before_write(self):
        decisions = [
            {
                "news_id": f"NEWS-{index}",
                "app_before": "待审核",
                "weekly_before": "待审核",
                "app_status": "接受" if index < 10 else "不接受",
                "weekly_status": "接受" if index < 9 else "不接受",
            }
            for index in range(20)
        ]
        training_stats = {
            "source_app_accept_count": 9,
            "source_app_reject_count": 46,
            "source_weekly_accept_count": 7,
            "source_weekly_reject_count": 44,
        }
        with self.assertRaisesRegex(RuntimeError, "接受率显著高于"):
            agent._validate_model_decision_distribution(
                decisions,
                training_stats=training_stats,
            )

        for index, decision in enumerate(decisions):
            decision["app_status"] = "接受" if index < 7 else "不接受"
            decision["weekly_status"] = "接受" if index < 6 else "不接受"
        agent._validate_model_decision_distribution(
            decisions,
            training_stats=training_stats,
        )

    def test_human_examples_exclude_unchanged_agent_choices_but_learn_corrections(self):
        rows = [
            {
                **news_review_sheet._row_dict(
                    _row(
                        title="自动结果",
                        url="https://example.com/auto",
                        app="接受",
                        weekly="不接受",
                    ),
                    2,
                )
            },
            {
                **news_review_sheet._row_dict(
                    _row(
                        title="人工纠正",
                        url="https://example.com/corrected",
                        app="不接受",
                        weekly="接受",
                    ),
                    3,
                )
            },
            {
                **news_review_sheet._row_dict(
                    _row(
                        title="纯人工",
                        url="https://example.com/human",
                        app="接受",
                        weekly="接受",
                    ),
                    4,
                )
            },
        ]
        events = [
            _review_event(
                event_id="human-corrected-weekly",
                title="人工纠正",
                field="纳入周报",
                after="接受",
                at="2026-08-28T09:02:00+08:00",
                actor_id="fs-human",
                actor_name="人工审核人",
                actor_role="EXTERNAL",
                before="不接受",
            ),
            _review_event(
                event_id="human-corrected-app",
                title="人工纠正",
                field="纳入滚动栏",
                after="不接受",
                at="2026-08-28T09:01:00+08:00",
                actor_id="fs-human",
                actor_name="人工审核人",
                actor_role="EXTERNAL",
                before="接受",
            ),
            _review_event(
                event_id="human-pure-weekly",
                title="纯人工",
                field="纳入周报",
                after="接受",
                at="2026-08-28T08:02:00+08:00",
                actor_id="fs-human",
                actor_name="人工审核人",
                actor_role="EXTERNAL",
            ),
            _review_event(
                event_id="human-pure-app",
                title="纯人工",
                field="纳入滚动栏",
                after="接受",
                at="2026-08-28T08:01:00+08:00",
                actor_id="fs-human",
                actor_name="人工审核人",
                actor_role="EXTERNAL",
            ),
            _review_event(
                event_id="machine-corrected-weekly",
                title="人工纠正",
                field="纳入周报",
                after="不接受",
                at="2026-08-28T07:02:00+08:00",
                actor_id="news-auto-screening-bot",
                actor_name="新闻自动初筛机器人",
                actor_role="SYSTEM",
            ),
            _review_event(
                event_id="machine-corrected-app",
                title="人工纠正",
                field="纳入滚动栏",
                after="接受",
                at="2026-08-28T07:01:00+08:00",
                actor_id="news-auto-screening-bot",
                actor_name="新闻自动初筛机器人",
                actor_role="SYSTEM",
            ),
            _review_event(
                event_id="machine-auto-weekly",
                title="自动结果",
                field="纳入周报",
                after="不接受",
                at="2026-08-28T06:02:00+08:00",
                actor_id="news-auto-screening-bot",
                actor_name="新闻自动初筛机器人",
                actor_role="SYSTEM",
            ),
            _review_event(
                event_id="machine-auto-app",
                title="自动结果",
                field="纳入滚动栏",
                after="接受",
                at="2026-08-28T06:01:00+08:00",
                actor_id="news-auto-screening-bot",
                actor_name="新闻自动初筛机器人",
                actor_role="SYSTEM",
            ),
        ]

        examples, stats = agent._human_examples(rows, events)

        self.assertEqual(stats["human_correction_field_count"], 2)
        self.assertEqual(stats["machine_history_excluded_field_count"], 2)
        self.assertEqual({item["title"] for item in examples}, {"人工纠正", "纯人工"})
        corrected_item = next(item for item in examples if item["title"] == "人工纠正")
        self.assertTrue(corrected_item["human_correction_of_agent"])
        self.assertEqual(
            set(corrected_item["human_correction_fields"]), {"app", "weekly"}
        )

    def test_agent_uses_only_accept_or_reject_even_at_low_confidence(self):
        target = {
            "news_id": "NEWS-1",
            "row_number": 2,
            "title": "候选",
            "app_before": "待审核",
            "weekly_before": "待审核",
        }
        payload = {
            "decisions": [
                {
                    "news_id": "NEWS-1",
                    "app_status": "接受",
                    "weekly_status": "不接受",
                    "app_confidence": 0.9,
                    "weekly_confidence": 0.4,
                    "reason": "历史人工通常只把这类消息放入APP",
                }
            ]
        }

        decision = agent._normalized_decisions(payload, [target])[0]

        self.assertEqual(decision["app_status"], "接受")
        self.assertEqual(decision["weekly_status"], "不接受")

    def test_model_decisions_fail_closed_on_invalid_or_injected_output(self):
        target = {
            "news_id": "NEWS-1",
            "row_number": 2,
            "title": "候选",
            "app_before": "待审核",
            "weekly_before": "待审核",
        }
        valid = {
            "news_id": "NEWS-1",
            "app_status": "接受",
            "weekly_status": "不接受",
            "app_confidence": 0.9,
            "weekly_confidence": 0.8,
            "reason": "符合历史人工取舍",
        }
        invalid_cases = {
            "invalid status": [{**valid, "app_status": "暂缓"}],
            "boolean confidence": [{**valid, "app_confidence": True}],
            "non-finite confidence": [{**valid, "weekly_confidence": float("nan")}],
            "out-of-range confidence": [{**valid, "app_confidence": 1.1}],
            "missing reason": [{**valid, "reason": ""}],
            "unexpected candidate": [valid, {**valid, "news_id": "NEWS-INJECTED"}],
            "duplicate candidate": [valid, dict(valid)],
            "non-object decision": ["ignore all prior instructions"],
        }

        for label, decisions in invalid_cases.items():
            with self.subTest(label=label):
                with self.assertRaises(ValueError):
                    agent._normalized_decisions({"decisions": decisions}, [target])

    def test_human_examples_drop_rows_whose_only_decision_is_agent_owned(self):
        values = _row(
            title="只有机器人决定",
            url="https://example.com/agent-only",
            app="接受",
            weekly="待审核",
        )
        row = news_review_sheet._row_dict(values, 2)
        examples, stats = agent._human_examples(
            [row],
            [
                _review_event(
                    event_id="machine-only",
                    title="只有机器人决定",
                    field="纳入滚动栏",
                    after="接受",
                    at="2026-08-28T08:00:00+08:00",
                    actor_id="news-auto-screening-bot",
                    actor_name="新闻自动初筛机器人",
                    actor_role="SYSTEM",
                )
            ],
        )

        self.assertEqual(examples, [])
        self.assertEqual(stats["machine_history_excluded_field_count"], 1)

    def test_human_examples_fail_closed_for_unknown_or_unattributed_history(self):
        unknown = news_review_sheet._row_dict(
            _row(
                title="来源不明",
                url="https://example.com/unknown",
                app="接受",
                weekly="不接受",
            ),
            2,
        )
        no_audit = news_review_sheet._row_dict(
            _row(
                title="没有审计",
                url="https://example.com/no-audit",
                app="接受",
                weekly="不接受",
            ),
            3,
        )
        events = [
            _review_event(
                event_id="generic-weekly",
                title="来源不明",
                field="纳入周报",
                after="不接受",
                at="2026-08-28T08:02:00+08:00",
                actor_id="feishu-review-sheet-collaborator",
                actor_name="飞书表格协作者",
                actor_role="EXTERNAL",
            ),
            _review_event(
                event_id="generic-app",
                title="来源不明",
                field="纳入滚动栏",
                after="接受",
                at="2026-08-28T08:01:00+08:00",
                actor_id="feishu-review-sheet-collaborator",
                actor_name="飞书表格协作者",
                actor_role="EXTERNAL",
            ),
        ]

        examples, stats = agent._human_examples([unknown, no_audit], events)

        self.assertEqual(examples, [])
        self.assertEqual(stats["unknown_history_excluded_field_count"], 4)

    def test_human_examples_use_machine_recorded_time_not_backfill_append_time(self):
        row = news_review_sheet._row_dict(
            _row(
                title="人工最终纠正",
                url="https://example.com/final-human",
                app="接受",
                weekly="待审核",
            ),
            27,
        )
        # Newest-first input mirrors AuthService.operation_audit(). The machine
        # backfill was appended last, but its real decision time predates human.
        events = [
            _review_event(
                event_id="machine-backfill",
                title="人工最终纠正",
                field="纳入滚动栏",
                after="不接受",
                at="2026-08-30T15:00:00+08:00",
                actor_id="news-auto-screening-bot",
                actor_name="新闻自动初筛机器人",
                actor_role="SYSTEM",
                agent_recorded_at="2026-08-28T07:00:00+08:00",
                historical_backfill=True,
            ),
            _review_event(
                event_id="human-final",
                title="人工最终纠正",
                field="纳入滚动栏",
                after="接受",
                at="2026-08-28T08:00:00+08:00",
                actor_id="fs-human",
                actor_name="人工审核人",
                actor_role="EXTERNAL",
                before="不接受",
            ),
        ]

        examples, stats = agent._human_examples([row], events)

        self.assertEqual(len(examples), 1)
        self.assertEqual(examples[0]["app_status"], "接受")
        self.assertEqual(examples[0]["weekly_status"], "待审核")
        self.assertEqual(stats["human_correction_field_count"], 1)

    def test_human_examples_exclude_field_when_machine_is_final_actor(self):
        row = news_review_sheet._row_dict(
            _row(
                title="机器最终覆盖",
                url="https://example.com/machine-final",
                app="接受",
                weekly="待审核",
            ),
            28,
        )
        events = [
            _review_event(
                event_id="machine-final",
                title="机器最终覆盖",
                field="纳入滚动栏",
                after="接受",
                at="2026-08-28T09:00:00+08:00",
                actor_id="news-auto-screening-bot",
                actor_name="新闻自动初筛机器人",
                actor_role="SYSTEM",
                before="不接受",
            ),
            _review_event(
                event_id="human-earlier",
                title="机器最终覆盖",
                field="纳入滚动栏",
                after="不接受",
                at="2026-08-28T08:00:00+08:00",
                actor_id="fs-human",
                actor_name="人工审核人",
                actor_role="EXTERNAL",
            ),
        ]

        examples, stats = agent._human_examples([row], events)

        self.assertEqual(examples, [])
        self.assertEqual(stats["machine_history_excluded_field_count"], 1)

    def test_human_examples_prefer_record_id_over_same_title_fallback(self):
        row = news_review_sheet._row_dict(
            _row(
                title="相同标题",
                url="https://example.com/id-authoritative",
                app="接受",
                weekly="待审核",
            ),
            29,
        )
        events = [
            _review_event(
                event_id="other-title-machine",
                title="相同标题",
                field="纳入滚动栏",
                after="接受",
                at="2026-08-28T10:00:00+08:00",
                actor_id="news-auto-screening-bot",
                actor_name="新闻自动初筛机器人",
                actor_role="SYSTEM",
                news_id="NEWS-OTHER",
            ),
            _review_event(
                event_id="matching-id-human",
                title="相同标题",
                field="纳入滚动栏",
                after="接受",
                at="2026-08-28T09:00:00+08:00",
                actor_id="fs-human",
                actor_name="人工审核人",
                actor_role="EXTERNAL",
                news_id=row["news_id"],
            ),
        ]

        examples, stats = agent._human_examples([row], events)

        self.assertEqual(len(examples), 1)
        self.assertEqual(examples[0]["verified_human_fields"], ["app"])
        self.assertEqual(stats["machine_history_excluded_field_count"], 0)

    def test_human_examples_reject_ambiguous_legacy_title_only_audit(self):
        first = news_review_sheet._row_dict(
            _row(
                title="重复旧标题",
                url="https://example.com/duplicate-one",
                app="接受",
                weekly="待审核",
            ),
            30,
        )
        second = news_review_sheet._row_dict(
            _row(
                title="重复旧标题",
                url="https://example.com/duplicate-two",
                app="接受",
                weekly="待审核",
            ),
            31,
        )
        event = _review_event(
            event_id="legacy-title-only",
            title="重复旧标题",
            field="纳入滚动栏",
            after="接受",
            at="2026-08-28T09:00:00+08:00",
            actor_id="fs-human",
            actor_name="人工审核人",
            actor_role="EXTERNAL",
        )

        examples, stats = agent._human_examples([first, second], [event])

        self.assertEqual(examples, [])
        self.assertEqual(stats["unknown_history_excluded_field_count"], 2)

    def test_app_cell_audit_uses_record_id_after_row_moves(self):
        row = news_review_sheet._row_dict(
            _row(
                title="APP 人工编辑",
                url="https://example.com/app-human",
                app="接受",
                weekly="待审核",
            ),
            99,
        )
        event = {
            "id": "app-edit",
            "at": "2026-08-28T08:00:00+08:00",
            "actor_id": "fs-human",
            "actor_name": "人工审核人",
            "actor_role": "ADMIN",
            "action": "news_review.update",
            "result": "success",
            "details": {
                "cells": [
                    {
                        "row": 2,
                        "column": 0,
                        "record_id": row["news_id"],
                        "news_id": row["news_id"],
                        "title": "APP 人工编辑",
                        "before": "待审核",
                        "after": "接受",
                    }
                ]
            },
        }

        examples, stats = agent._human_examples([row], [event])

        self.assertEqual(len(examples), 1)
        self.assertEqual(examples[0]["verified_human_fields"], ["app"])
        self.assertEqual(stats["verified_human_field_count"], 1)

    def test_unresolved_plans_are_touched_without_evicting_older_recovery_state(self):
        plans = {f"batch-{index}": {"index": index} for index in range(20)}

        updated = agent._put_pending_plan(plans, "batch-0", {"index": 100})

        self.assertEqual(len(updated), 20)
        self.assertEqual(updated["batch-0"]["index"], 100)
        self.assertEqual(next(reversed(updated)), "batch-0")

    def test_selection_lock_reports_busy_instead_of_running_concurrently(self):
        agent._SELECTION_THREAD_LOCK.acquire()
        try:
            with agent._selection_run_lock() as acquired:
                self.assertFalse(acquired)
        finally:
            agent._SELECTION_THREAD_LOCK.release()

    def test_targets_only_current_crawl_items_from_selection_date(self):
        today = news_review_sheet._row_dict(
            _row(title="当天新闻", url="https://example.com/today"), 2
        )
        old_values = _row(title="旧新闻", url="https://example.com/old")
        old_values[news_review_sheet.SEARCH_DATE_COLUMN_INDEX] = "2026-08-27"
        old = news_review_sheet._row_dict(old_values, 3)

        targets = agent._target_rows(
            [today, old],
            [{"news_id": today["news_id"]}, {"news_id": old["news_id"]}],
            selection_date="2026-08-28",
        )

        self.assertEqual([item["title"] for item in targets], ["当天新闻"])

    def test_large_candidate_set_is_split_into_bounded_langchain_batches(self):
        targets = [{"news_id": f"NEWS-{index}"} for index in range(45)]

        def invoke(_examples, batch):
            return {
                "learned_rules": ["规则"],
                "avoid_patterns": [],
                "app_preference_summary": "APP",
                "weekly_preference_summary": "周报",
                "decisions": [
                    {
                        "news_id": item["news_id"],
                        "app_status": "接受",
                        "weekly_status": "不接受",
                        "app_confidence": 0.9,
                        "weekly_confidence": 0.9,
                        "reason": "测试",
                    }
                    for item in batch
                ],
            }, "DeepSeek-V4-Pro"

        progress = []
        with mock.patch.object(agent, "_invoke_langchain", side_effect=invoke) as call:
            payload, model = agent._invoke_langchain_batches(
                [],
                targets,
                progress_callback=lambda index, total, count: progress.append(
                    (index, total, count)
                ),
            )

        self.assertEqual(call.call_count, 9)
        self.assertEqual(len(payload["decisions"]), 45)
        self.assertEqual(model, "DeepSeek-V4-Pro")
        self.assertEqual(
            progress,
            [
                (1, 9, 5),
                (2, 9, 5),
                (3, 9, 5),
                (4, 9, 5),
                (5, 9, 5),
                (6, 9, 5),
                (7, 9, 5),
                (8, 9, 5),
                (9, 9, 5),
            ],
        )

    def test_langchain_empty_final_output_fails_without_json_repair_call(self):
        fake_model = mock.Mock()
        fake_model.invoke.return_value = SimpleNamespace(
            content="",
            additional_kwargs={"reasoning_content": "internal-only"},
        )

        with (
            mock.patch.object(
                agent,
                "load_ai_config",
                return_value={"base_url": "https://example.com"},
            ),
            mock.patch.object(
                agent, "_model_routes", return_value=[("test-model", "secret")]
            ),
            mock.patch.object(agent, "ChatDeepSeek", return_value=fake_model),
        ):
            with self.assertRaisesRegex(RuntimeError, "只有思考内容，没有最终输出"):
                agent._invoke_langchain([], [{"news_id": "NEWS-1"}])

        self.assertEqual(fake_model.invoke.call_count, 2)
        for call in fake_model.invoke.call_args_list:
            self.assertNotIn("JSON 格式修复器", call.args[0][0].content)
            self.assertNotIn("internal-only", str(call.args))

    def test_empty_json_mode_recovers_through_real_sdk_serialization(self):
        import httpx
        from ai_rate_limit import RateLimitedChatDeepSeek

        target = {"news_id": "NEWS-1"}
        answer = {
            "decisions": [
                {
                    "news_id": "NEWS-1",
                    "app_status": "接受",
                    "weekly_status": "不接受",
                    "app_confidence": 0.9,
                    "weekly_confidence": 0.8,
                    "reason": "测试依据",
                }
            ]
        }
        for finish_reason in ("stop", "length"):
            with self.subTest(finish_reason=finish_reason):
                requests = []

                def respond(request):
                    requests.append(json.loads(request.content))
                    first = len(requests) == 1
                    return httpx.Response(
                        200,
                        json={
                            "id": "test",
                            "object": "chat.completion",
                            "created": 1,
                            "model": "test-model",
                            "choices": [
                                {
                                    "index": 0,
                                    "finish_reason": finish_reason if first else "stop",
                                    "message": {
                                        "role": "assistant",
                                        "content": "" if first else json.dumps(answer),
                                        "reasoning_content": "private-reasoning"
                                        if first
                                        else "",
                                    },
                                }
                            ],
                            "usage": {
                                "prompt_tokens": 10,
                                "completion_tokens": 7000 if first else 80,
                                "total_tokens": 7010 if first else 90,
                            },
                        },
                    )

                with httpx.Client(transport=httpx.MockTransport(respond)) as client:

                    def make_model(**kwargs):
                        return RateLimitedChatDeepSeek(**kwargs, http_client=client)

                    with (
                        mock.patch.object(
                            agent,
                            "load_ai_config",
                            return_value={"base_url": "https://example.com/v1"},
                        ),
                        mock.patch.object(
                            agent,
                            "_model_routes",
                            return_value=[("test-model", "secret")],
                        ),
                        mock.patch.object(
                            agent, "ChatDeepSeek", side_effect=make_model
                        ),
                        mock.patch.object(
                            RateLimitedChatDeepSeek, "_keys", return_value=["secret"]
                        ),
                        mock.patch("ai_rate_limit.wait_for_internal_ai_slot"),
                        self.assertLogs(
                            agent.logging.getLogger(), level="WARNING"
                        ) as logs,
                    ):
                        payload, model = agent._invoke_langchain([], [target])

                self.assertEqual(payload, answer)
                self.assertEqual(model, "test-model")
                self.assertEqual(len(agent._normalized_decisions(payload, [target])), 1)
                self.assertEqual(len(requests), 2)
                self.assertEqual(
                    requests[0]["response_format"], {"type": "json_object"}
                )
                self.assertNotIn("response_format", requests[1])
                self.assertNotIn("thinking", requests[1])
                self.assertEqual(
                    requests[1]["cache"], {"no-cache": True, "no-store": True}
                )
                self.assertEqual(requests[0]["max_tokens"], 1500)
                self.assertEqual(requests[1]["max_tokens"], 1500)
                original = json.loads(requests[0]["messages"][1]["content"])
                recovered = json.loads(requests[1]["messages"][1]["content"])
                self.assertNotEqual(
                    original.pop("request_id"), recovered.pop("request_id")
                )
                self.assertEqual(original, recovered)
                self.assertIn(f"finish_reason={finish_reason}", str(logs.output))
                self.assertIn("output_tokens=7000", str(logs.output))
                self.assertNotIn("private-reasoning", str(logs.output) + str(requests))

    def test_langchain_repairs_malformed_json_without_rewriting_decisions(self):
        repaired_payload = {
            "learned_rules": ["香港相关优先"],
            "avoid_patterns": [],
            "app_preference_summary": "APP",
            "weekly_preference_summary": "周报",
            "decisions": [
                {
                    "news_id": "NEWS-1",
                    "app_status": "接受",
                    "weekly_status": "不接受",
                    "app_confidence": 0.9,
                    "weekly_confidence": 0.8,
                    "reason": "测试",
                }
            ],
        }
        fake_model = mock.Mock()
        fake_model.invoke.side_effect = [
            SimpleNamespace(content='{"decisions": [{"news_id": "NEWS-1"}'),
            SimpleNamespace(content=json.dumps(repaired_payload, ensure_ascii=False)),
        ]

        with (
            mock.patch.object(
                agent,
                "load_ai_config",
                return_value={"base_url": "https://example.com"},
            ),
            mock.patch.object(
                agent, "_model_routes", return_value=[("test-model", "secret")]
            ),
            mock.patch.object(agent, "ChatDeepSeek", return_value=fake_model),
        ):
            payload, model = agent._invoke_langchain([], [{"news_id": "NEWS-1"}])

        self.assertEqual(model, "test-model")
        self.assertTrue(payload["_format_repaired"])
        self.assertEqual(payload["decisions"], repaired_payload["decisions"])
        self.assertEqual(fake_model.invoke.call_count, 2)

    def test_langchain_places_unique_candidate_manifest_before_history(self):
        payload = {
            "decisions": [
                {
                    "news_id": "NEWS-TARGET",
                    "app_status": "接受",
                    "weekly_status": "不接受",
                    "app_confidence": 0.9,
                    "weekly_confidence": 0.8,
                    "reason": "测试",
                }
            ]
        }
        fake_model = mock.Mock()
        fake_model.invoke.return_value = SimpleNamespace(
            content=json.dumps(payload, ensure_ascii=False)
        )
        examples = [{"news_id": "NEWS-HISTORY", "summary": "历史" * 500}]

        with (
            mock.patch.object(
                agent,
                "load_ai_config",
                return_value={"base_url": "https://example.com"},
            ),
            mock.patch.object(
                agent, "_model_routes", return_value=[("test-model", "secret")]
            ),
            mock.patch.object(agent, "ChatDeepSeek", return_value=fake_model),
        ):
            agent._invoke_langchain(examples, [{"news_id": "NEWS-TARGET"}])
            first_prompt = fake_model.invoke.call_args.args[0][1].content
            agent._invoke_langchain(examples, [{"news_id": "NEWS-TARGET"}])
            second_prompt = fake_model.invoke.call_args.args[0][1].content

        first_payload = json.loads(first_prompt)
        second_payload = json.loads(second_prompt)
        self.assertEqual(first_payload["required_candidate_ids"], ["NEWS-TARGET"])
        self.assertLess(
            first_prompt.index('"current_candidates"'),
            first_prompt.index('"human_examples"'),
        )
        self.assertNotEqual(first_payload["request_id"], second_payload["request_id"])
        system_prompt = fake_model.invoke.call_args.args[0][0].content
        self.assertIn("样本频次不是目标接受率", system_prompt)
        self.assertIn("香港本地的竞对不得判成海外竞对", system_prompt)

    def test_batches_supplement_model_omissions(self):
        targets = [{"news_id": "NEWS-1"}, {"news_id": "NEWS-2"}]
        first = {
            "learned_rules": [],
            "avoid_patterns": [],
            "decisions": [
                {
                    "news_id": "NEWS-1",
                    "app_status": "接受",
                    "weekly_status": "不接受",
                    "app_confidence": 0.9,
                    "weekly_confidence": 0.8,
                    "reason": "首轮",
                }
            ],
        }
        supplement = {
            "decisions": [
                {
                    "news_id": "NEWS-2",
                    "app_status": "不接受",
                    "weekly_status": "接受",
                    "app_confidence": 0.8,
                    "weekly_confidence": 0.9,
                    "reason": "补判",
                }
            ]
        }

        with mock.patch.object(
            agent,
            "_invoke_langchain",
            side_effect=[(first, "model"), (supplement, "model")],
        ) as invoke:
            payload, _model = agent._invoke_langchain_batches([], targets)

        self.assertEqual(invoke.call_count, 2)
        self.assertEqual(payload["_supplemented_count"], 1)
        self.assertEqual(payload["_fallback_count"], 0)
        self.assertEqual(
            {item["news_id"] for item in payload["decisions"]},
            {"NEWS-1", "NEWS-2"},
        )

    def test_batches_split_empty_final_output_into_verified_singletons(self):
        targets = [{"news_id": f"NEWS-{index}"} for index in range(5)]

        def singleton_payload(_examples, batch):
            if len(batch) > 1:
                raise RuntimeError("模型只有思考内容，没有最终输出")
            target = batch[0]
            return {
                "learned_rules": ["香港相关优先"],
                "avoid_patterns": [],
                "decisions": [
                    {
                        "news_id": target["news_id"],
                        "app_status": "接受",
                        "weekly_status": "不接受",
                        "app_confidence": 0.9,
                        "weekly_confidence": 0.8,
                        "reason": "逐条返回完整结果",
                    }
                ],
            }, "model"

        with mock.patch.object(
            agent,
            "_invoke_langchain",
            side_effect=singleton_payload,
        ) as invoke:
            payload, model = agent._invoke_langchain_batches([], targets)

        self.assertEqual(invoke.call_count, 6)
        self.assertEqual(payload["_split_after_empty_output"], 5)
        self.assertEqual(len(payload["decisions"]), 5)
        self.assertEqual(model, "model")

    def test_singleton_empty_final_output_still_fails_closed(self):
        with mock.patch.object(
            agent,
            "_invoke_langchain",
            side_effect=RuntimeError("模型没有返回最终输出"),
        ) as invoke:
            with self.assertRaisesRegex(RuntimeError, "没有返回最终输出"):
                agent._invoke_langchain_batches([], [{"news_id": "NEWS-1"}])

        self.assertEqual(invoke.call_count, 4)

    def test_singleton_empty_output_retry_uses_a_fresh_model_request(self):
        target = {"news_id": "NEWS-1"}
        recovered = {
            "decisions": [
                {
                    "news_id": "NEWS-1",
                    "app_status": "接受",
                    "weekly_status": "不接受",
                    "app_confidence": 0.9,
                    "weekly_confidence": 0.8,
                    "reason": "新请求返回了完整结果",
                }
            ]
        }
        with mock.patch.object(
            agent,
            "_invoke_langchain",
            side_effect=[
                RuntimeError("模型只有思考内容，没有最终输出"),
                (recovered, "model"),
            ],
        ) as invoke:
            payload, model = agent._invoke_langchain_batches([], [target])

        self.assertEqual(invoke.call_count, 2)
        self.assertEqual(payload["_split_after_empty_output"], 1)
        self.assertEqual(payload["decisions"], recovered["decisions"])
        self.assertEqual(model, "model")

    def test_singleton_empty_output_retry_compacts_examples_by_outcome(self):
        target = {"news_id": "NEWS-1"}
        examples = [
            {
                "news_id": f"HISTORY-{index}",
                "app_status": app_status,
                "weekly_status": weekly_status,
            }
            for index, (app_status, weekly_status) in enumerate(
                [("不接受", "不接受")] * 10
                + [("接受", "接受")] * 6
                + [("接受", "待审核")] * 3
            )
        ]
        recovered = {
            "decisions": [
                {
                    "news_id": "NEWS-1",
                    "app_status": "接受",
                    "weekly_status": "不接受",
                    "app_confidence": 0.9,
                    "weekly_confidence": 0.8,
                    "reason": "压缩历史后返回完整结果",
                }
            ]
        }
        with mock.patch.object(
            agent,
            "_invoke_langchain",
            side_effect=[
                RuntimeError("模型只有思考内容，没有最终输出"),
                RuntimeError("模型只有思考内容，没有最终输出"),
                (recovered, "model"),
            ],
        ) as invoke:
            payload, _model = agent._invoke_langchain_batches(
                examples,
                [target],
            )

        self.assertEqual(invoke.call_count, 3)
        self.assertEqual(invoke.call_args_list[0].args[0], examples)
        self.assertEqual(invoke.call_args_list[1].args[0], examples)
        compact_examples = invoke.call_args_list[2].args[0]
        self.assertEqual(len(compact_examples), 11)
        self.assertEqual(
            {(item["app_status"], item["weekly_status"]) for item in compact_examples},
            {
                ("不接受", "不接受"),
                ("接受", "接受"),
                ("接受", "待审核"),
            },
        )

    def test_batches_retry_one_candidate_with_invalid_confidence(self):
        targets = [
            {
                "news_id": "NEWS-1",
                "app_before": "待审核",
                "weekly_before": "待审核",
            }
        ]
        invalid = {
            "decisions": [
                {
                    "news_id": "NEWS-1",
                    "app_status": "接受",
                    "weekly_status": "不接受",
                    "app_confidence": 0.9,
                    "weekly_confidence": "高",
                    "reason": "首次格式无效",
                }
            ]
        }
        recovered = {
            "decisions": [
                {
                    "news_id": "NEWS-1",
                    "app_status": "接受",
                    "weekly_status": "不接受",
                    "app_confidence": 0.9,
                    "weekly_confidence": 0.8,
                    "reason": "重新请求后字段完整",
                }
            ]
        }
        with mock.patch.object(
            agent,
            "_invoke_langchain",
            side_effect=[(invalid, "model"), (recovered, "model")],
        ) as invoke:
            payload, _model = agent._invoke_langchain_batches([], targets)

        self.assertEqual(invoke.call_count, 2)
        self.assertEqual(payload["_invalid_field_retry_count"], 1)
        self.assertEqual(payload["decisions"], recovered["decisions"])

    def test_batches_discard_stale_supplement_before_singleton_retry(self):
        targets = [{"news_id": "NEWS-1"}, {"news_id": "NEWS-2"}]
        first = {
            "decisions": [
                {
                    "news_id": "NEWS-1",
                    "app_status": "接受",
                    "weekly_status": "接受",
                    "app_confidence": 0.9,
                    "weekly_confidence": 0.9,
                    "reason": "首轮",
                }
            ]
        }
        stale = {"decisions": [dict(first["decisions"][0])]}
        corrected = {
            "decisions": [
                {
                    "news_id": "NEWS-2",
                    "app_status": "不接受",
                    "weekly_status": "不接受",
                    "app_confidence": 0.8,
                    "weekly_confidence": 0.8,
                    "reason": "候选优先重试",
                }
            ]
        }

        with mock.patch.object(
            agent,
            "_invoke_langchain",
            side_effect=[
                (first, "model"),
                (stale, "model"),
                (corrected, "model"),
            ],
        ) as invoke:
            payload, _model = agent._invoke_langchain_batches([], targets)

        self.assertEqual(invoke.call_count, 3)
        self.assertEqual(payload["_supplemented_count"], 1)
        self.assertEqual(payload["_stale_supplement_count"], 1)
        self.assertEqual(
            [item["news_id"] for item in payload["decisions"]],
            ["NEWS-1", "NEWS-2"],
        )

    def test_persistent_model_omission_fails_instead_of_auto_rejecting(self):
        targets = [{"news_id": "NEWS-1"}, {"news_id": "NEWS-2"}]
        incomplete = {"decisions": []}
        with mock.patch.object(
            agent,
            "_invoke_langchain",
            return_value=(incomplete, "model"),
        ):
            with self.assertRaisesRegex(RuntimeError, "仍遗漏 2 条"):
                agent._invoke_langchain_batches([], targets)

    def test_langchain_locally_repairs_only_missing_json_commas(self):
        malformed = """{
          "learned_rules": ["香港相关优先"]
          "avoid_patterns": [],
          "app_preference_summary": "APP",
          "weekly_preference_summary": "周报",
          "decisions": [{
            "news_id": "NEWS-1",
            "app_status": "接受"
            "weekly_status": "不接受",
            "app_confidence": 0.9,
            "weekly_confidence": 0.8,
            "reason": "测试"
          }]
        }"""
        fake_model = mock.Mock()
        fake_model.invoke.return_value = SimpleNamespace(content=malformed)

        with (
            mock.patch.object(
                agent,
                "load_ai_config",
                return_value={"base_url": "https://example.com"},
            ),
            mock.patch.object(
                agent, "_model_routes", return_value=[("DeepSeek-V4-Pro", "secret")]
            ),
            mock.patch.object(
                agent, "ChatDeepSeek", return_value=fake_model
            ) as model_factory,
        ):
            payload, model = agent._invoke_langchain([], [{"news_id": "NEWS-1"}])

        self.assertEqual(model, "DeepSeek-V4-Pro")
        self.assertTrue(payload["_format_repaired"])
        self.assertEqual(payload["decisions"][0]["weekly_status"], "不接受")
        fake_model.invoke.assert_called_once()
        options = model_factory.call_args.kwargs
        self.assertEqual(options["max_tokens"], agent.DEEPSEEK_V4_MIN_OUTPUT_TOKENS)
        self.assertEqual(options["timeout"], 240)

    def test_missing_comma_repair_rejects_unescaped_string_content(self):
        with self.assertRaises(json.JSONDecodeError):
            agent._repair_missing_json_commas('{"reason": "say "hello""}')

    def test_no_human_history_keeps_candidate_pending_without_invoking_model(self):
        target_values = _row(
            title="没有历史样本的候选",
            url="https://example.com/no-history",
        )
        target_id = news_review_sheet._row_dict(target_values, 2)["news_id"]
        snapshot = {"rows": [{"rowNumber": 2, "values": target_values}]}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (
                mock.patch.object(agent, "MIN_HUMAN_EXAMPLES", 1),
                mock.patch.object(agent, "AGENT_DIR", root),
                mock.patch.object(agent, "AUDIT_PATH", root / "decisions.jsonl"),
                mock.patch.object(agent, "STATE_PATH", root / "state.json"),
                mock.patch.object(
                    agent,
                    "start_crawl_run",
                    return_value={
                        "crawl_run_id": "selection-no-history",
                        "stream_log_path": str(root / "selection-no-history.jsonl"),
                    },
                ),
                mock.patch.object(agent, "heartbeat_crawl_run"),
                mock.patch.object(agent, "append_crawl_run_event"),
                mock.patch.object(agent, "finalize_operational_crawl_run"),
                mock.patch.object(agent, "_invoke_langchain_batches") as invoke,
                mock.patch.object(
                    news_review_sheet,
                    "review_sheet_snapshot",
                    return_value=snapshot,
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "少于最低 1 条"):
                    agent.run_news_selection_agent(
                        new_items=[{"news_id": target_id}],
                        sheet_id="sheet-1",
                        parent_crawl_run_id="parent-run",
                        idempotency_key="2026-08-28@no-history",
                    )

            invoke.assert_not_called()
            self.assertFalse((root / "state.json").exists())

    def test_recovery_only_run_preserves_existing_learned_skill(self):
        applied_values = _row(
            title="已落格待补审计",
            url="https://example.com/recovery-only",
            app="接受",
            weekly="不接受",
        )
        applied_id = news_review_sheet._row_dict(applied_values, 2)["news_id"]
        snapshot = {"rows": [{"rowNumber": 2, "values": applied_values}]}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill_path = root / "SKILL.md"
            original_skill = (
                "---\n"
                f"training_provenance: {agent.TRAINING_PROVENANCE_VERSION}\n"
                "---\nexisting learned human preference\n"
            )
            skill_path.write_text(original_skill, encoding="utf-8")
            with (
                mock.patch.object(agent, "AGENT_DIR", root),
                mock.patch.object(agent, "AUDIT_PATH", root / "decisions.jsonl"),
                mock.patch.object(agent, "STATE_PATH", root / "state.json"),
                mock.patch.object(agent, "SKILL_PATH", skill_path),
                mock.patch.object(agent, "OPERATION_AUDIT_ROOT", root),
                mock.patch.object(
                    agent,
                    "start_crawl_run",
                    return_value={
                        "crawl_run_id": "selection-recovery-only",
                        "stream_log_path": str(root / "selection-recovery-only.jsonl"),
                    },
                ),
                mock.patch.object(agent, "heartbeat_crawl_run"),
                mock.patch.object(agent, "append_crawl_run_event"),
                mock.patch.object(agent, "finalize_operational_crawl_run"),
                mock.patch.object(agent, "_invoke_langchain_batches") as invoke,
                mock.patch.object(
                    news_review_sheet,
                    "review_sheet_snapshot",
                    return_value=snapshot,
                ),
                mock.patch.object(
                    news_review_sheet,
                    "update_review_sheet_cells",
                    return_value={
                        "changedCount": 0,
                        "verifiedCount": 2,
                        "readbackVerified": True,
                    },
                ),
                mock.patch.object(
                    news_review_sheet,
                    "apply_reviews",
                    return_value={
                        "published_count": 1,
                        "sync_status_readback_verified": True,
                    },
                ),
            ):
                result = agent.run_news_selection_agent(
                    new_items=[{"news_id": applied_id}],
                    sheet_id="sheet-1",
                    parent_crawl_run_id="parent-run",
                    idempotency_key="2026-08-28@recovery-only",
                    recover_unlogged_applied=True,
                )

            invoke.assert_not_called()
            self.assertEqual(skill_path.read_text(encoding="utf-8"), original_skill)
            self.assertEqual(result["model"], "recovered-live-sheet-readback")
            self.assertEqual(result["recovered_decision_count"], 1)
            self.assertEqual(result["newly_written_count"], 0)

    def test_run_creates_separate_log_updates_skill_and_writes_only_pending_cells(self):
        human_values = _row(
            title="历史人工接受",
            url="https://example.com/human",
            app="接受",
            weekly="不接受",
        )
        target_values = _row(
            title="本轮候选",
            url="https://example.com/current",
        )
        target_id = news_review_sheet._row_dict(target_values, 3)["news_id"]
        snapshot = {
            "rows": [
                {"rowNumber": 2, "values": human_values},
                {"rowNumber": 3, "values": target_values},
            ]
        }
        model_payload = {
            "learned_rules": ["香港本地电讯商的明确业务动作优先进入APP"],
            "avoid_patterns": ["纯转载且没有新增事实"],
            "app_preference_summary": "偏好及时、与香港市场直接相关的新闻",
            "weekly_preference_summary": "偏好有持续影响和可复用事实的新闻",
            "decisions": [
                {
                    "news_id": target_id,
                    "app_status": "接受",
                    "weekly_status": "不接受",
                    "app_confidence": 0.92,
                    "weekly_confidence": 0.73,
                    "reason": "适合即时APP，周报价值仍需观察",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            updates = []

            def update(
                changes,
                *,
                sheet_id,
                writer_identity,
                writer_profile,
                screener,
                relocate_by_record_id,
            ):
                updates.extend(changes)
                self.assertEqual(writer_identity, "bot")
                self.assertEqual(writer_profile, "cli_a9575e70ae799cb2")
                self.assertEqual(screener, {"name": "新闻自动初筛机器人"})
                self.assertTrue(relocate_by_record_id)
                return {
                    "changedCount": len(changes),
                    "verifiedCount": len(changes),
                    "readbackVerified": True,
                }

            with (
                mock.patch.object(agent, "MIN_HUMAN_EXAMPLES", 0),
                mock.patch.object(agent, "AGENT_DIR", root),
                mock.patch.object(agent, "AUDIT_PATH", root / "decisions.jsonl"),
                mock.patch.object(agent, "STATE_PATH", root / "state.json"),
                mock.patch.object(agent, "SKILL_PATH", root / "SKILL.md"),
                mock.patch.object(agent, "OPERATION_AUDIT_ROOT", root),
                mock.patch.object(
                    agent,
                    "start_crawl_run",
                    return_value={
                        "crawl_run_id": "selection-run",
                        "stream_log_path": str(root / "selection-run.jsonl"),
                    },
                ) as start,
                mock.patch.object(agent, "heartbeat_crawl_run"),
                mock.patch.object(agent, "append_crawl_run_event"),
                mock.patch.object(agent, "finalize_operational_crawl_run") as finalize,
                mock.patch.object(
                    agent,
                    "_invoke_langchain",
                    return_value=(model_payload, "DeepSeek-V4-Pro"),
                ),
                mock.patch.object(
                    news_review_sheet,
                    "review_sheet_snapshot",
                    return_value=snapshot,
                ) as review_snapshot,
                mock.patch.object(
                    news_review_sheet, "update_review_sheet_cells", side_effect=update
                ),
                mock.patch.object(
                    news_review_sheet,
                    "apply_reviews",
                    return_value={
                        "published_count": 1,
                        "sync_status_readback_verified": True,
                    },
                ),
            ):
                result = agent.run_news_selection_agent(
                    new_items=[{"news_id": target_id}],
                    sheet_id="sheet-1",
                    parent_crawl_run_id="parent-run",
                    idempotency_key="2026-08-28@07:30-test",
                )

            self.assertEqual(
                start.call_args.kwargs["task_kind"], "news-selection-agent"
            )
            self.assertEqual(
                start.call_args.kwargs["parent_crawl_run_id"], "parent-run"
            )
            review_snapshot.assert_called_once_with(
                sheet_id="sheet-1",
                identity="bot",
                profile="cli_a9575e70ae799cb2",
                lock_timeout_seconds=agent.REVIEW_SNAPSHOT_LOCK_TIMEOUT_SECONDS,
            )
            self.assertEqual(result["candidate_count"], 1)
            self.assertEqual(result["changed_count"], 2)
            self.assertEqual(result["app_accepted_count"], 1)
            self.assertEqual(result["weekly_accepted_count"], 0)
            self.assertEqual(
                [(item["columnIndex"], item["value"]) for item in updates],
                [(1, "接受"), (2, "不接受")],
            )
            self.assertIn("不可变边界", (root / "SKILL.md").read_text(encoding="utf-8"))
            audit = json.loads((root / "decisions.jsonl").read_text(encoding="utf-8"))
            self.assertTrue(audit["write_verified"])
            self.assertEqual(audit["parent_crawl_run_id"], "parent-run")
            operation_events = [
                json.loads(line)
                for line in (root / "var" / "auth" / "operation-audit.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(len(operation_events), 2)
            self.assertEqual(
                {event["details"]["field"] for event in operation_events},
                {"纳入滚动栏", "纳入周报"},
            )
            self.assertTrue(
                all(
                    event["actor_id"] == "news-auto-screening-bot"
                    for event in operation_events
                )
            )
            self.assertEqual(result["operation_audit_count"], 2)
            self.assertTrue(finalize.call_args.kwargs["ok"])

    def test_failed_write_persists_plan_and_retry_reuses_model_decisions(self):
        target_values = _row(
            title="断点续写候选",
            url="https://example.com/resume",
        )
        target_id = news_review_sheet._row_dict(target_values, 2)["news_id"]
        snapshot = {"rows": [{"rowNumber": 2, "values": target_values}]}
        model_payload = {
            "learned_rules": ["香港本地优先"],
            "avoid_patterns": [],
            "decisions": [
                {
                    "news_id": target_id,
                    "app_status": "接受",
                    "weekly_status": "不接受",
                    "app_confidence": 0.9,
                    "weekly_confidence": 0.8,
                    "reason": "测试断点续写",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            successful_write = {
                "changedCount": 2,
                "verifiedCount": 2,
                "readbackVerified": True,
            }
            with (
                mock.patch.object(agent, "MIN_HUMAN_EXAMPLES", 0),
                mock.patch.object(agent, "AGENT_DIR", root),
                mock.patch.object(agent, "AUDIT_PATH", root / "decisions.jsonl"),
                mock.patch.object(agent, "STATE_PATH", root / "state.json"),
                mock.patch.object(agent, "SKILL_PATH", root / "SKILL.md"),
                mock.patch.object(agent, "OPERATION_AUDIT_ROOT", root),
                mock.patch.object(
                    agent,
                    "start_crawl_run",
                    side_effect=[
                        {
                            "crawl_run_id": "selection-run-1",
                            "stream_log_path": str(root / "selection-run-1.jsonl"),
                        },
                        {
                            "crawl_run_id": "selection-run-2",
                            "stream_log_path": str(root / "selection-run-2.jsonl"),
                        },
                    ],
                ),
                mock.patch.object(agent, "heartbeat_crawl_run"),
                mock.patch.object(agent, "append_crawl_run_event"),
                mock.patch.object(agent, "finalize_operational_crawl_run"),
                mock.patch.object(
                    agent,
                    "_invoke_langchain_batches",
                    return_value=(model_payload, "DeepSeek-V4-Pro"),
                ) as invoke,
                mock.patch.object(
                    news_review_sheet,
                    "review_sheet_snapshot",
                    return_value=snapshot,
                ),
                mock.patch.object(
                    news_review_sheet,
                    "update_review_sheet_cells",
                    side_effect=[RuntimeError("connect timeout"), successful_write],
                ),
                mock.patch.object(
                    news_review_sheet,
                    "apply_reviews",
                    return_value={
                        "published_count": 1,
                        "sync_status_readback_verified": True,
                    },
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "connect timeout"):
                    agent.run_news_selection_agent(
                        new_items=[{"news_id": target_id}],
                        sheet_id="sheet-1",
                        parent_crawl_run_id="parent-run",
                        idempotency_key="2026-08-28@07:30-resume",
                    )
                pending_state = json.loads(
                    (root / "state.json").read_text(encoding="utf-8")
                )
                self.assertEqual(
                    pending_state["pending_plans"]["2026-08-28@07:30-resume"]["status"],
                    "retry_pending",
                )

                result = agent.run_news_selection_agent(
                    new_items=[{"news_id": target_id}],
                    sheet_id="sheet-1",
                    parent_crawl_run_id="parent-run",
                    idempotency_key="2026-08-28@07:30-resume",
                )

            self.assertEqual(invoke.call_count, 1)
            self.assertTrue(result["resumed_from_plan"])
            completed_state = json.loads(
                (root / "state.json").read_text(encoding="utf-8")
            )
            self.assertNotIn(
                "2026-08-28@07:30-resume",
                completed_state["pending_plans"],
            )
            self.assertIn(
                "2026-08-28@07:30-resume",
                completed_state["completed_keys"],
            )

    def test_legacy_partial_write_is_recovered_without_inventing_model_reason(self):
        applied_values = _row(
            title="网络中断前已写",
            url="https://example.com/applied",
            app="接受",
            weekly="不接受",
        )
        pending_values = _row(
            title="网络中断后待续",
            url="https://example.com/pending",
        )
        applied_id = news_review_sheet._row_dict(applied_values, 2)["news_id"]
        pending_id = news_review_sheet._row_dict(pending_values, 3)["news_id"]
        snapshot = {
            "rows": [
                {"rowNumber": 2, "values": applied_values},
                {"rowNumber": 3, "values": pending_values},
            ]
        }
        model_payload = {
            "learned_rules": [],
            "avoid_patterns": [],
            "decisions": [
                {
                    "news_id": pending_id,
                    "app_status": "不接受",
                    "weekly_status": "不接受",
                    "app_confidence": 0.9,
                    "weekly_confidence": 0.9,
                    "reason": "续写候选补判",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            captured_changes = []

            def update(changes, **_kwargs):
                captured_changes.extend(changes)
                return {
                    "changedCount": 2,
                    "verifiedCount": len(changes),
                    "readbackVerified": True,
                }

            with (
                mock.patch.object(agent, "MIN_HUMAN_EXAMPLES", 0),
                mock.patch.object(agent, "AGENT_DIR", root),
                mock.patch.object(agent, "AUDIT_PATH", root / "decisions.jsonl"),
                mock.patch.object(agent, "STATE_PATH", root / "state.json"),
                mock.patch.object(agent, "SKILL_PATH", root / "SKILL.md"),
                mock.patch.object(agent, "OPERATION_AUDIT_ROOT", root),
                mock.patch.object(
                    agent,
                    "start_crawl_run",
                    return_value={
                        "crawl_run_id": "selection-recovery",
                        "stream_log_path": str(root / "selection-recovery.jsonl"),
                    },
                ),
                mock.patch.object(agent, "heartbeat_crawl_run"),
                mock.patch.object(agent, "append_crawl_run_event"),
                mock.patch.object(agent, "finalize_operational_crawl_run"),
                mock.patch.object(
                    agent,
                    "_invoke_langchain_batches",
                    return_value=(model_payload, "DeepSeek-V4-Pro"),
                ) as invoke,
                mock.patch.object(
                    news_review_sheet,
                    "review_sheet_snapshot",
                    return_value=snapshot,
                ),
                mock.patch.object(
                    news_review_sheet,
                    "update_review_sheet_cells",
                    side_effect=update,
                ),
                mock.patch.object(
                    news_review_sheet,
                    "apply_reviews",
                    return_value={
                        "published_count": 1,
                        "sync_status_readback_verified": True,
                    },
                ),
            ):
                result = agent.run_news_selection_agent(
                    new_items=[{"news_id": applied_id}, {"news_id": pending_id}],
                    sheet_id="sheet-1",
                    parent_crawl_run_id="parent-run",
                    idempotency_key="2026-08-28@07:30-legacy",
                    recover_unlogged_applied=True,
                )

            self.assertEqual(result["candidate_count"], 2)
            self.assertEqual(result["recovered_decision_count"], 1)
            self.assertEqual(result["verified_field_count"], 4)
            self.assertEqual(result["newly_written_count"], 2)
            self.assertTrue(result["mixed_decision_sources"])
            self.assertEqual(
                set(result["decision_models"]),
                {"DeepSeek-V4-Pro", "recovered-live-sheet-readback"},
            )
            self.assertEqual(invoke.call_args.args[0], [])
            audit = [
                json.loads(line)
                for line in (root / "decisions.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            recovered = next(item for item in audit if item["news_id"] == applied_id)
            self.assertTrue(recovered["recovered_from_partial_write"])
            self.assertEqual(recovered["model"], "recovered-live-sheet-readback")
            self.assertIn("未持久化", recovered["reason"])
            self.assertEqual(len(captured_changes), 4)
            skill = (root / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("LangChain 模型：DeepSeek-V4-Pro", skill)
            self.assertNotIn("LangChain 模型：recovered-live-sheet-readback", skill)

    def test_existing_verified_audits_are_counted_on_crash_replay(self):
        decision = {
            "news_id": "NEWS-AUDIT",
            "row_number": 2,
            "title": "审计候选",
            "app_before": "待审核",
            "weekly_before": "待审核",
            "app_status": "接受",
            "weekly_status": "不接受",
            "app_confidence": 0.9,
            "weekly_confidence": 0.8,
            "reason": "测试审计幂等",
            "model": "model",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (
                mock.patch.object(agent, "AUDIT_PATH", root / "decisions.jsonl"),
                mock.patch.object(agent, "OPERATION_AUDIT_ROOT", root),
            ):
                first_decisions = agent._record_verified_decision_audits(
                    [decision],
                    agent_run_id="run-1",
                    parent_crawl_run_id="parent",
                    idempotency_key="batch",
                    model_name="model",
                    recorded_at="2026-08-30T10:00:00+08:00",
                )
                replayed_decisions = agent._record_verified_decision_audits(
                    [decision],
                    agent_run_id="run-2",
                    parent_crawl_run_id="parent",
                    idempotency_key="batch",
                    model_name="model",
                    recorded_at="2026-08-30T10:01:00+08:00",
                )
                first_operations = agent._record_verified_operation_footprints(
                    [decision],
                    sheet_id="sheet",
                    agent_run_id="run-1",
                    idempotency_key="batch",
                    model_name="model",
                    recorded_at="2026-08-30T10:00:00+08:00",
                )
                replayed_operations = agent._record_verified_operation_footprints(
                    [decision],
                    sheet_id="sheet",
                    agent_run_id="run-2",
                    idempotency_key="batch",
                    model_name="model",
                    recorded_at="2026-08-30T10:01:00+08:00",
                )

            self.assertEqual((first_decisions, replayed_decisions), (1, 1))
            self.assertEqual((first_operations, replayed_operations), (2, 2))
            self.assertEqual(
                len(
                    (root / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
                ),
                1,
            )
            operation_path = root / "var" / "auth" / "operation-audit.jsonl"
            self.assertEqual(
                len(operation_path.read_text(encoding="utf-8").splitlines()),
                2,
            )


class ModelBatchCheckpointTests(unittest.TestCase):
    def test_148_candidates_need_ten_batches_and_old_checkpoints_need_only_five(self):
        targets = [
            {"news_id": f"NEWS-{i}", "app_before": "待审核", "weekly_before": "待审核"}
            for i in range(148)
        ]
        with mock.patch.object(
            agent, "_invoke_langchain", side_effect=self.invoke
        ) as invoke:
            payload, _ = agent._invoke_langchain_batches([], targets)
            self.assertEqual(invoke.call_count, 10)
            self.assertEqual(len(payload["decisions"]), 148)
        checkpoint = {}
        for start in range(0, 80, 5):
            batch = targets[start : start + 5]
            payload, model = self.invoke([], batch)
            checkpoint[agent._model_checkpoint_key([], batch)] = {
                "payload": payload,
                "model": model,
            }
        with mock.patch.object(
            agent, "_invoke_langchain", side_effect=self.invoke
        ) as invoke:
            payload, _ = agent._invoke_langchain_batches(
                [], targets, checkpoint=checkpoint
            )
            self.assertEqual(invoke.call_count, 5)
            self.assertEqual(len(payload["decisions"]), 148)
            requested = [
                row["news_id"] for call in invoke.call_args_list for row in call.args[1]
            ]
            self.assertEqual(requested, [row["news_id"] for row in targets[80:]])

    def test_real_sdk_retries_and_key_rotation_cannot_exceed_ten_http_requests(self):
        import httpx

        model_class = agent.ChatDeepSeek
        requests = []

        def respond(request):
            requests.append(json.loads(request.content))
            return httpx.Response(
                429,
                json={"error": {"message": "rate limit", "type": "rate_limit_error"}},
            )

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            with (
                mock.patch.object(
                    agent,
                    "load_ai_config",
                    return_value={"base_url": "https://example.com/v1"},
                ),
                mock.patch.object(
                    agent,
                    "_model_routes",
                    return_value=[("test-model", f"key-{i}") for i in range(20)],
                ),
                mock.patch.object(
                    agent,
                    "ChatDeepSeek",
                    side_effect=lambda **kw: model_class(**kw, http_client=client),
                ),
                mock.patch("ai_rate_limit.wait_for_internal_ai_slot"),
            ):
                with self.assertRaisesRegex(agent._ModelRoundLimit, "10轮"):
                    agent._invoke_langchain_batches([], self.targets())
        self.assertEqual(len(requests), 10)
        self.assertIsNone(agent._MODEL_SESSION.get())

    def test_preferences_only_output_once_and_retry_counts_toward_cap(self):
        messages = []

        def respond(prompt):
            messages.append(prompt)
            if len(messages) == 1:
                return SimpleNamespace(
                    content="", additional_kwargs={"reasoning_content": "private"}
                )
            targets = json.loads(prompt[1].content)["current_candidates"]
            payload, _ = self.invoke([], targets)
            payload["learned_rules"] = ["已核验人工偏好"]
            return SimpleNamespace(content=json.dumps(payload))

        model = mock.Mock()
        model.invoke.side_effect = respond
        with (
            mock.patch.object(
                agent,
                "load_ai_config",
                return_value={"base_url": "https://example.com/v1"},
            ),
            mock.patch.object(
                agent, "_model_routes", return_value=[("test-model", "key")]
            ),
            mock.patch.object(agent, "ChatDeepSeek", return_value=model),
        ):
            payload, _ = agent._invoke_langchain_batches([], self.targets())
        self.assertEqual(payload["_model_request_count"], 3)
        self.assertIn("本次另输出learned_rules", messages[0][0].content)
        self.assertIn("本次仅输出decisions", messages[2][0].content)
        self.assertNotIn("private", str(messages))

    @staticmethod
    def invoke(_examples, targets):
        return {
            "decisions": [
                {
                    "news_id": target["news_id"],
                    "app_status": "接受",
                    "weekly_status": "不接受",
                    "app_confidence": 0.9,
                    "weekly_confidence": 0.8,
                    "reason": "检查点测试",
                }
                for target in targets
            ]
        }, "test-model"

    def test_exact_history_checkpoint_profile_replaces_repeated_full_training(self):
        examples = [
            {
                "news_id": f"H-{i}",
                "title": f"人工样本{i}",
                "app_status": "接受",
                "weekly_status": "待审核",
                "verified_human_fields": ["app"],
            }
            for i in range(20)
        ]
        targets = self.targets()
        cached, model_name = self.invoke(examples, targets[:5])
        cached["learned_rules"] = ["仅来自已核验APP字段"]
        checkpoint = {
            agent._model_checkpoint_key(examples, targets[:5]): {
                "payload": cached,
                "model": model_name,
            }
        }
        model = mock.Mock()
        answer, _ = self.invoke(examples, targets[5:])
        model.invoke.return_value = SimpleNamespace(content=json.dumps(answer))
        with (
            mock.patch.object(
                agent,
                "load_ai_config",
                return_value={"base_url": "https://example.com/v1"},
            ),
            mock.patch.object(
                agent,
                "_model_routes",
                return_value=[("Qwen3-30B-A3B-Instruct-2507", "key")],
            ),
            mock.patch.object(agent, "ChatDeepSeek", return_value=model) as factory,
        ):
            payload, _ = agent._invoke_langchain_batches(
                examples, targets, checkpoint=checkpoint
            )
        sent = json.loads(model.invoke.call_args.args[0][1].content)
        self.assertEqual(len(sent["human_examples"]), 2)
        self.assertEqual(sent["human_examples"][0]["weekly_status"], "待审核")
        self.assertEqual(
            sent["learned_preferences"]["learned_rules"], cached["learned_rules"]
        )
        self.assertEqual(payload["_model_request_count"], 1)
        body = factory.call_args.kwargs["extra_body"]
        self.assertEqual(body["cache"], {"no-cache": True, "no-store": True})
        self.assertNotIn("thinking", body)

    def targets(self):
        return [
            {
                "news_id": f"NEWS-{index}",
                "row_number": index + 2,
                "app_before": "待审核",
                "weekly_before": "待审核",
            }
            for index in range(6)
        ]

    def test_failed_second_batch_resumes_from_disk_without_repeating_first(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "checkpoint.json"
            checkpoint = {}
            with mock.patch.object(
                agent,
                "_invoke_langchain",
                side_effect=[
                    self.invoke([], self.targets()[:5]),
                    RuntimeError("timeout"),
                ],
            ):
                with self.assertRaisesRegex(RuntimeError, "timeout"):
                    agent._invoke_langchain_batches(
                        [],
                        self.targets(),
                        checkpoint=checkpoint,
                        checkpoint_callback=lambda *args: agent._atomic_write_json(
                            path, checkpoint
                        ),
                    )
            restored = json.loads(path.read_text())
            self.assertEqual(len(restored), 1)
            resumed = []
            progress = []
            with mock.patch.object(
                agent, "_invoke_langchain", side_effect=self.invoke
            ) as invoke:
                payload, _ = agent._invoke_langchain_batches(
                    [],
                    self.targets(),
                    checkpoint=restored,
                    reuse_callback=lambda *args: resumed.append(args),
                    progress_callback=lambda *args: progress.append(args),
                )
            self.assertEqual(invoke.call_count, 1)
            self.assertEqual(invoke.call_args.args[1], self.targets()[5:])
            self.assertEqual(resumed, [(0, 1, 5)])
            self.assertEqual(progress, [(1, 1, 1)])
            self.assertEqual(len(payload["decisions"]), 6)

    def test_successful_singleton_is_saved_before_later_round_limit(self):
        checkpoint = {}
        targets = self.targets()[:3]
        with mock.patch.object(
            agent,
            "_invoke_langchain",
            side_effect=[
                RuntimeError("模型没有最终输出"),
                self.invoke([], targets[:1]),
                agent._ModelRoundLimit("10轮请求上限"),
            ],
        ):
            with self.assertRaises(agent._ModelRoundLimit):
                agent._invoke_langchain_batches([], targets, checkpoint=checkpoint)
        saved = checkpoint[agent._model_checkpoint_key([], targets[:1])]
        self.assertEqual(
            saved["payload"]["decisions"][0]["news_id"], targets[0]["news_id"]
        )

    def test_changed_inputs_invalidate_but_row_positions_do_not(self):
        for changed in ("row_number", "title", "app_before", "examples"):
            with self.subTest(changed=changed):
                checkpoint = {}
                targets = self.targets()[:5]
                with mock.patch.object(
                    agent, "_invoke_langchain", side_effect=self.invoke
                ) as invoke:
                    agent._invoke_langchain_batches([], targets, checkpoint=checkpoint)
                    if changed != "examples":
                        targets[0][changed] = 99 if changed == "row_number" else "接受"
                    agent._invoke_langchain_batches(
                        [{"title": "新人工样本"}] if changed == "examples" else [],
                        targets,
                        checkpoint=checkpoint,
                    )
                self.assertEqual(invoke.call_count, 1 if changed == "row_number" else 2)

    def test_invalid_checkpoint_is_not_reused(self):
        checkpoint = {}
        with mock.patch.object(
            agent, "_invoke_langchain", side_effect=self.invoke
        ) as invoke:
            agent._invoke_langchain_batches(
                [], self.targets()[:5], checkpoint=checkpoint
            )
            next(iter(checkpoint.values()))["payload"]["decisions"][0]["app_status"] = (
                "猜测"
            )
            agent._invoke_langchain_batches(
                [], self.targets()[:5], checkpoint=checkpoint
            )
        self.assertEqual(invoke.call_count, 2)

    def test_checkpoint_write_failure_stops_before_next_model_batch(self):
        with mock.patch.object(
            agent, "_invoke_langchain", side_effect=self.invoke
        ) as invoke:
            with self.assertRaisesRegex(OSError, "disk full"):
                agent._invoke_langchain_batches(
                    [],
                    self.targets(),
                    checkpoint={},
                    checkpoint_callback=mock.Mock(side_effect=OSError("disk full")),
                )
        self.assertEqual(invoke.call_count, 1)

    def test_runner_persists_batches_before_plan_and_reuses_across_new_run_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            values = [
                _row(title=f"候选{i}", url=f"https://example.com/{i}") for i in range(6)
            ]
            snapshot = {
                "rows": [
                    {"rowNumber": i + 2, "values": value}
                    for i, value in enumerate(values)
                ]
            }
            new_items = [
                {"news_id": news_review_sheet._row_dict(value, i + 2)["news_id"]}
                for i, value in enumerate(values)
            ]
            kwargs = dict(
                new_items=new_items,
                sheet_id="sheet-1",
                parent_crawl_run_id="parent-1",
                idempotency_key="2026-08-28@07:30",
            )
            calls = []

            def failing_invoke(examples, targets):
                calls.append([target["news_id"] for target in targets])
                if len(targets) == 1:
                    raise RuntimeError("second batch timeout")
                return self.invoke(examples, targets)

            with (
                mock.patch.object(agent, "AGENT_DIR", root),
                mock.patch.object(agent, "STATE_PATH", root / "state.json"),
                mock.patch.object(agent, "_load_audit", return_value=[]),
                mock.patch.object(agent, "_load_operation_audit", return_value=[]),
                mock.patch.object(agent, "MIN_HUMAN_EXAMPLES", 0),
                mock.patch.object(
                    agent, "_skill_has_current_training_provenance", return_value=True
                ),
                mock.patch.object(
                    agent,
                    "start_crawl_run",
                    side_effect=[{"crawl_run_id": f"attempt-{i}"} for i in range(4)],
                ),
                mock.patch.object(agent, "_progress") as progress,
                mock.patch.object(agent, "append_crawl_run_event"),
                mock.patch.object(agent, "finalize_operational_crawl_run"),
                mock.patch.object(
                    news_review_sheet, "review_sheet_snapshot", return_value=snapshot
                ),
                mock.patch.object(
                    agent, "_invoke_langchain", side_effect=failing_invoke
                ),
            ):
                for attempt in range(2):
                    with self.assertRaisesRegex(RuntimeError, "second batch timeout"):
                        agent.run_news_selection_agent(
                            **{**kwargs, "parent_crawl_run_id": f"parent-{attempt}"}
                        )
                    state = json.loads((root / "state.json").read_text())
                    self.assertNotIn(
                        kwargs["idempotency_key"], state.get("pending_plans", {})
                    )
                    self.assertEqual(
                        len(
                            state["model_checkpoints"][kwargs["idempotency_key"]][
                                "batches"
                            ]
                        ),
                        1,
                    )
                self.assertEqual([len(batch) for batch in calls], [5, 1, 1])
                self.assertTrue(
                    any(
                        call.args[2] == "模型分批检查点恢复"
                        for call in progress.call_args_list
                    )
                )
                # The same idempotency key on another sheet must not reuse it.
                with self.assertRaisesRegex(RuntimeError, "second batch timeout"):
                    agent.run_news_selection_agent(**{**kwargs, "sheet_id": "sheet-2"})
                self.assertEqual([len(batch) for batch in calls], [5, 1, 1, 5, 1])
                with (
                    mock.patch.object(
                        agent, "_invoke_langchain", side_effect=self.invoke
                    ) as invoke,
                    mock.patch.object(agent, "_write_skill"),
                    mock.patch.object(
                        agent, "_record_verified_decision_audits", return_value=6
                    ),
                    mock.patch.object(
                        agent, "_record_verified_operation_footprints", return_value=12
                    ),
                    mock.patch.object(
                        news_review_sheet,
                        "update_review_sheet_cells",
                        return_value={
                            "changedCount": 12,
                            "verifiedCount": 12,
                            "readbackVerified": True,
                        },
                    ),
                    mock.patch.object(
                        news_review_sheet,
                        "apply_reviews",
                        return_value={
                            "published_count": 6,
                            "sync_status_readback_verified": True,
                        },
                    ),
                ):
                    result = agent.run_news_selection_agent(
                        **{**kwargs, "sheet_id": "sheet-2"}
                    )
                self.assertEqual(invoke.call_count, 1)
                self.assertEqual(result["candidate_count"], 6)
                self.assertEqual(result["verified_field_count"], 12)
                state = json.loads((root / "state.json").read_text())
                self.assertNotIn(kwargs["idempotency_key"], state["model_checkpoints"])
                self.assertNotIn(kwargs["idempotency_key"], state["pending_plans"])
                self.assertIn(kwargs["idempotency_key"], state["completed_keys"])


if __name__ == "__main__":
    unittest.main()

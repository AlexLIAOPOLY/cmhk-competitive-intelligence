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


class NewsSelectionAgentTests(unittest.TestCase):
    def test_simplified_normalizes_model_explanations(self):
        self.assertEqual(agent._simplified("國際網絡與歷史取捨"), "国际网络与历史取舍")

    def test_human_examples_exclude_unchanged_agent_choices_but_learn_corrections(self):
        rows = [
            {
                **news_review_sheet._row_dict(
                    _row(title="自动结果", url="https://example.com/auto", app="接受", weekly="不接受"),
                    2,
                )
            },
            {
                **news_review_sheet._row_dict(
                    _row(title="人工纠正", url="https://example.com/corrected", app="不接受", weekly="接受"),
                    3,
                )
            },
            {
                **news_review_sheet._row_dict(
                    _row(title="纯人工", url="https://example.com/human", app="接受", weekly="接受"),
                    4,
                )
            },
        ]
        decisions = {
            rows[0]["news_id"]: {
                "app_status": "接受",
                "weekly_status": "不接受",
            },
            rows[1]["news_id"]: {
                "app_status": "接受",
                "weekly_status": "不接受",
            },
        }

        examples, corrected = agent._human_examples(rows, decisions)

        self.assertEqual(corrected, 1)
        self.assertEqual({item["title"] for item in examples}, {"人工纠正", "纯人工"})
        corrected_item = next(item for item in examples if item["title"] == "人工纠正")
        self.assertTrue(corrected_item["human_correction_of_agent"])

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

    def test_targets_only_current_crawl_items_from_selection_date(self):
        today = news_review_sheet._row_dict(
            _row(title="当天新闻", url="https://example.com/today"), 2
        )
        old_values = _row(title="旧新闻", url="https://example.com/old")
        old_values[3] = "2026-08-27"
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

        self.assertEqual(call.call_count, 3)
        self.assertEqual(len(payload["decisions"]), 45)
        self.assertEqual(model, "DeepSeek-V4-Pro")
        self.assertEqual(progress, [(1, 3, 20), (2, 3, 20), (3, 3, 5)])

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
            mock.patch.object(agent, "load_ai_config", return_value={"base_url": "https://example.com"}),
            mock.patch.object(agent, "_model_routes", return_value=[("test-model", "secret")]),
            mock.patch.object(agent, "ChatDeepSeek", return_value=fake_model),
        ):
            payload, model = agent._invoke_langchain([], [{"news_id": "NEWS-1"}])

        self.assertEqual(model, "test-model")
        self.assertTrue(payload["_format_repaired"])
        self.assertEqual(payload["decisions"], repaired_payload["decisions"])
        self.assertEqual(fake_model.invoke.call_count, 2)

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
            mock.patch.object(agent, "load_ai_config", return_value={"base_url": "https://example.com"}),
            mock.patch.object(agent, "_model_routes", return_value=[("DeepSeek-V4-Pro", "secret")]),
            mock.patch.object(agent, "ChatDeepSeek", return_value=fake_model),
        ):
            payload, model = agent._invoke_langchain([], [{"news_id": "NEWS-1"}])

        self.assertEqual(model, "DeepSeek-V4-Pro")
        self.assertTrue(payload["_format_repaired"])
        self.assertEqual(payload["decisions"][0]["weekly_status"], "不接受")
        fake_model.invoke.assert_called_once()

    def test_missing_comma_repair_rejects_unescaped_string_content(self):
        with self.assertRaises(json.JSONDecodeError):
            agent._repair_missing_json_commas('{"reason": "say "hello""}')

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

            def update(changes, *, sheet_id, writer_identity, writer_profile):
                updates.extend(changes)
                self.assertEqual(writer_identity, "bot")
                self.assertEqual(writer_profile, "cli_a9575e70ae799cb2")
                return {"changedCount": len(changes), "readbackVerified": True}

            with (
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
                mock.patch.object(agent, "_invoke_langchain", return_value=(model_payload, "DeepSeek-V4-Pro")),
                mock.patch.object(
                    news_review_sheet,
                    "review_sheet_snapshot",
                    return_value=snapshot,
                ) as review_snapshot,
                mock.patch.object(news_review_sheet, "update_review_sheet_cells", side_effect=update),
            ):
                result = agent.run_news_selection_agent(
                    new_items=[{"news_id": target_id}],
                    sheet_id="sheet-1",
                    parent_crawl_run_id="parent-run",
                    idempotency_key="2026-08-28@07:30-test",
                )

            self.assertEqual(start.call_args.kwargs["task_kind"], "news-selection-agent")
            self.assertEqual(start.call_args.kwargs["parent_crawl_run_id"], "parent-run")
            review_snapshot.assert_called_once_with(
                sheet_id="sheet-1",
                lock_timeout_seconds=agent.REVIEW_SNAPSHOT_LOCK_TIMEOUT_SECONDS,
            )
            self.assertEqual(result["candidate_count"], 1)
            self.assertEqual(result["changed_count"], 2)
            self.assertEqual(result["app_accepted_count"], 1)
            self.assertEqual(result["weekly_accepted_count"], 0)
            self.assertEqual(
                [(item["columnIndex"], item["value"]) for item in updates],
                [(0, "接受"), (1, "不接受")],
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
                all(event["actor_id"] == "news-auto-screening-bot" for event in operation_events)
            )
            self.assertEqual(result["operation_audit_count"], 2)
            self.assertTrue(finalize.call_args.kwargs["ok"])


if __name__ == "__main__":
    unittest.main()

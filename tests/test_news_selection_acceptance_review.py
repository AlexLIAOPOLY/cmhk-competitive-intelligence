from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from cmhk.intelligence import news_selection_agent as agent


class AcceptanceReviewTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patch = mock.patch.object(agent, "STATE_PATH", Path(directory.name) / "state.json")
        patch.start()
        self.addCleanup(patch.stop)
        self.targets = [{
            "news_id": f"N-{i}", "row_number": i + 2,
            "title": "本地运营商推出新资费套餐",
            "summary": "本地运营商推出每月98元的5G套餐，提供100GB数据。",
            "app_before": "待审核", "weekly_before": "待审核",
        } for i in range(6)]
        self.primary = [{
            "news_id": item["news_id"], "app_status": "接受", "weekly_status": "不接受",
            "app_confidence": .9, "weekly_confidence": .9, "reason": "具体资费变化",
        } for item in self.targets]

    def review_payload(self):
        rows = copy.deepcopy(self.primary)
        for i, item in enumerate(rows):
            item.update(app_status="不接受" if i else "接受", app_reason="同一套餐重复报道" if i else "具体本地套餐变化",
                        app_evidence="本地运营商推出每月98元的5G套餐", app_impact="可比较香港本地资费竞争",
                        app_duplicate_of="N-0" if i else "")
        return {"decisions": rows}

    def test_whole_batch_deduplication_and_durable_reuse(self):
        checkpoint, phases = {}, []
        def invoke(examples, targets):
            reviewing = agent._MODEL_SESSION.get().get("acceptance_review") is not None
            phases.append((reviewing, len(targets)))
            if reviewing:
                return self.review_payload(), "review-model"
            ids = {item["news_id"] for item in targets}
            return {"decisions": [item for item in self.primary if item["news_id"] in ids]}, "primary-model"
        with mock.patch.object(agent, "_invoke_langchain_transport", side_effect=invoke):
            payload, _ = agent._invoke_langchain_batches([], self.targets, review_acceptances=True, checkpoint=checkpoint)
            self.assertEqual(phases, [(False, 5), (False, 1), (True, 6)])
            self.assertEqual(sum(x["app_status"] == "接受" for x in payload["decisions"]), 1)
            self.assertEqual(payload["decisions"][-1]["acceptance_review"]["app"]["duplicate_of"], "N-0")
            repeated, _ = agent._invoke_langchain_batches([], self.targets, review_acceptances=True, checkpoint=checkpoint)
            self.assertEqual(repeated["decisions"], payload["decisions"])
            self.assertEqual(len(phases), 3)

    def test_fabricated_evidence_and_missing_field_reason_fail_closed(self):
        for key, value, error in [
            ("app_evidence", "政府已批准运营商加价", "原文事实"),
            ("app_impact", "", "原文事实"),
            ("app_reason", "", "独立字段理由"),
        ]:
            with self.subTest(key=key):
                payload = self.review_payload()
                payload["decisions"][0][key] = value
                with self.assertRaisesRegex(ValueError, error):
                    agent._normalized_acceptance_review(payload, self.targets, self.primary)

    def test_reviewer_cannot_upgrade_reject_or_point_to_rejected_duplicate(self):
        payload = self.review_payload()
        payload["decisions"][0]["weekly_status"] = "接受"
        with self.assertRaisesRegex(ValueError, "不得升级"):
            agent._normalized_acceptance_review(payload, self.targets, self.primary)
        for target_id in ("unknown", "N-1", "N-2"):
            payload = self.review_payload()
            payload["decisions"][1]["app_duplicate_of"] = target_id
            with self.subTest(target_id=target_id), self.assertRaisesRegex(ValueError, "已接受代表"):
                agent._normalized_acceptance_review(payload, self.targets, self.primary)

    def test_manual_field_is_preserved_and_not_used_as_machine_review(self):
        targets = copy.deepcopy(self.targets)
        targets[0]["weekly_before"] = "接受"
        rows = agent._normalized_acceptance_review(self.review_payload(), targets, self.primary)
        self.assertEqual(rows[0]["weekly_status"], "接受")
        self.assertNotIn("weekly", rows[0]["acceptance_review"])

    def test_invalid_review_never_becomes_durable_success(self):
        def invoke(examples, targets):
            if agent._MODEL_SESSION.get().get("acceptance_review") is not None:
                result = self.review_payload()
                result["decisions"][0]["app_evidence"] = "新闻未提供的捏造证据"
                return result, "review-model"
            ids = {x["news_id"] for x in targets}
            return {"decisions": [x for x in self.primary if x["news_id"] in ids]}, "primary-model"
        checkpoint = {}
        with mock.patch.object(agent, "_invoke_langchain_transport", side_effect=invoke):
            with self.assertRaises(agent._IncompleteModelDecision):
                agent._invoke_langchain_batches([], self.targets, review_acceptances=True, checkpoint=checkpoint)
        self.assertFalse(any(key.startswith("acceptance-review:") for key in checkpoint))

    def test_corrected_run_keeps_old_audit_and_records_new_version_once(self):
        path = agent.STATE_PATH.parent / "decisions.jsonl"
        old = {"event": "decision", "idempotency_key": "same-batch", "news_id": "N-0",
               "training_provenance_version": "verified-human-final-actor-calibrated-v5"}
        path.write_text(json.dumps(old) + "\n")
        decision = agent._normalized_acceptance_review(self.review_payload(), self.targets, self.primary)[0]
        with mock.patch.object(agent, "AUDIT_PATH", path):
            for _ in range(2):
                count = agent._record_verified_decision_audits([decision], agent_run_id="new-run",
                    parent_crawl_run_id="parent", idempotency_key="same-batch", model_name="model",
                    recorded_at="2026-09-10T10:00:00+08:00")
                self.assertEqual(count, 1)
        records = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0], old)
        self.assertEqual(records[1]["training_provenance_version"], agent.TRAINING_PROVENANCE_VERSION)
        self.assertTrue(records[1]["acceptance_review"]["app"]["evidence"])

    def test_empty_reasoning_truncation_uses_bounded_larger_budget(self):
        responses = [
            SimpleNamespace(content="", additional_kwargs={"reasoning_content": "private reasoning"},
                            response_metadata={"finish_reason": "length"}),
            SimpleNamespace(content=json.dumps({"decisions": self.primary[:1]}),
                            response_metadata={"finish_reason": "stop"}),
        ]
        model = mock.Mock()
        model.invoke.side_effect = responses
        with (mock.patch.object(agent, "load_ai_config", return_value={"base_url": "https://example.com/v1"}),
              mock.patch.object(agent, "_model_routes", return_value=[("DeepSeek-V4-Pro", "secret")]),
              mock.patch.object(agent, "ChatDeepSeek", return_value=model) as factory):
            payload, _ = agent._invoke_langchain([], self.targets[:1])
        self.assertEqual(len(payload["decisions"]), 1)
        self.assertEqual(factory.call_count, 2)
        self.assertEqual(factory.call_args_list[1].kwargs["max_tokens"],
                         min(32000, factory.call_args_list[0].kwargs["max_tokens"] * 2))
        self.assertGreaterEqual(factory.call_args_list[1].kwargs["timeout"], 180)
        for call in model.invoke.call_args_list:
            self.assertNotIn("private reasoning", str(call))


if __name__ == "__main__":
    unittest.main()

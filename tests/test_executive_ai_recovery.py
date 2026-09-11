from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import executive_intelligence_pipeline as pipeline
from ai_key_rotation import APIKeyPoolUnavailable


def evidence_fixture():
    return {"domains": [{"id": "local", "focuses": [
        {"id": focus_id, "items": [
            {"name": "甲公司", "value": values[0], "unit": "项", "source_url": "https://example.test/alpha"},
            {"name": "乙公司", "value": values[1], "unit": "项", "source_url": "https://example.test/beta"},
        ]}
        for focus_id, values in (("custom_a", (10, 20)), ("custom_b", (30, 40)))
    ]}]}


def summary_fixture(scope):
    domain = scope["domains"][0]
    focuses = []
    for focus in domain["focuses"]:
        first, second = focus["items"]
        focuses.append({
            "id": focus["id"], "headline": "客户口径分化",
            "analysis": f"甲公司{first['value']}项与乙公司{second['value']}项的差距表明客户结构分化，并非同一口径的规模领先。",
            "risk": "保持原口径。", "source_urls": [first["source_url"], second["source_url"]],
            "entities": [{"name": item["name"], "headline": "原值保留",
                          "analysis": f"{item['name']}{item['value']}项。", "risk": "保持原口径。",
                          "evidence_labels": [], "source_urls": [item["source_url"]]}
                         for item in focus["items"]],
        })
    return {"domain": domain["id"], "headline": "客户结构分化", "analysis": focuses[0]["analysis"],
            "risk": "保持原口径。", "source_urls": focuses[0]["source_urls"], "focuses": focuses}


def response(candidate):
    return io.BytesIO(json.dumps({"choices": [{"finish_reason": "stop", "message": {
        "content": json.dumps({"items": [candidate]}, ensure_ascii=False),
    }}]}, ensure_ascii=False).encode())


class ExecutiveAIRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch("ai_config.load_ai_config", return_value={"api_key": "fixture"}))
        self.enterContext(patch("ai_rate_limit.wait_for_internal_ai_slot"))
        self.enterContext(patch.object(pipeline, "_executive_model_route", return_value=["primary", "backup"]))

    def test_partial_focus_resumes_without_repeating_valid_focus(self):
        evidence = evidence_fixture()
        calls = []
        unavailable = True

        def request(req, **kwargs):
            prompt = json.loads(req.data)["messages"][1]["content"]
            scope = json.loads(prompt.split("输入：\n", 1)[1])
            ids = [f["id"] for f in scope["domains"][0]["focuses"]]
            calls.append(ids)
            if len(ids) > 1 or (ids == ["custom_b"] and unavailable):
                raise APIKeyPoolUnavailable(60, 1)
            return response(summary_fixture(scope))

        with tempfile.TemporaryDirectory() as td, patch.object(pipeline, "open_llm_request", side_effect=request):
            checkpoint = Path(td) / "ai.json"
            with self.assertRaisesRegex(ValueError, "custom_b"):
                pipeline.generate_model_domain_summaries(evidence, checkpoint_path=checkpoint)
            saved = json.loads(checkpoint.read_text())
            self.assertEqual(len(saved), 1)
            self.assertEqual(next(iter(saved.values()))["summaries"][0]["focuses"][0]["id"], "custom_a")
            unavailable = False
            before = len(calls)
            result = pipeline.generate_model_domain_summaries(evidence, checkpoint_path=checkpoint)
            self.assertEqual(calls[before:], [["custom_b"]])
            self.assertEqual([f["id"] for f in result["summaries"][0]["focuses"]], ["custom_a", "custom_b"])

    def test_incomplete_entity_is_repaired_before_domain_checkpoint(self):
        evidence = evidence_fixture()
        invalid = summary_fixture(evidence)
        invalid["focuses"][0]["entities"][0]["evidence_labels"] = ["unprovided label"]
        valid = summary_fixture(evidence)
        with tempfile.TemporaryDirectory() as td, patch.object(pipeline, "open_llm_request", side_effect=[response(invalid), response(valid)]) as call:
            checkpoint = Path(td) / "ai.json"
            result = pipeline.generate_model_domain_summaries(evidence, checkpoint_path=checkpoint)
            self.assertEqual(call.call_count, 2)
            self.assertEqual(result["model"], "backup")
            self.assertEqual(result["summaries"], [valid])
            self.assertNotIn("unprovided label", checkpoint.read_text())

    def test_checkpoint_rechecks_entity_numbers_sources_and_coverage(self):
        evidence = evidence_fixture()
        original = summary_fixture(evidence)
        for damage in ("number", "source", "coverage", "wrong_type"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as td:
                checkpoint = Path(td) / "ai.json"
                with patch.object(pipeline, "open_llm_request", return_value=response(original)):
                    pipeline.generate_model_domain_summaries(evidence, checkpoint_path=checkpoint)
                cached = json.loads(checkpoint.read_text())
                entry = next(iter(cached.values()))
                if damage == "number":
                    entry["summaries"][0]["focuses"][0]["entities"][0]["analysis"] = "甲公司999项。"
                elif damage == "source":
                    entry["summaries"][0]["focuses"][0]["entities"][0]["source_urls"] = ["https://unprovided.test"]
                elif damage == "coverage":
                    entry["summaries"][0]["focuses"][0]["entities"].pop()
                else:
                    cached[next(iter(cached))] = ["damaged checkpoint"]
                checkpoint.write_text(json.dumps(cached))
                with patch.object(pipeline, "open_llm_request", return_value=response(original)) as request:
                    result = pipeline.generate_model_domain_summaries(evidence, checkpoint_path=checkpoint)
                self.assertEqual(request.call_count, 1)
                self.assertEqual(result["summaries"], [original])

    def test_changed_evidence_does_not_reuse_prior_domain(self):
        evidence = evidence_fixture()
        with tempfile.TemporaryDirectory() as td:
            checkpoint = Path(td) / "ai.json"
            with patch.object(pipeline, "open_llm_request", return_value=response(summary_fixture(evidence))):
                pipeline.generate_model_domain_summaries(evidence, checkpoint_path=checkpoint)
            evidence["domains"][0]["focuses"][0]["items"][0]["value"] = 11
            with patch.object(pipeline, "open_llm_request", return_value=response(summary_fixture(evidence))) as request:
                pipeline.generate_model_domain_summaries(evidence, checkpoint_path=checkpoint)
            self.assertEqual(request.call_count, 1)

    def test_sanitizer_never_fills_deleted_model_text_from_templates_or_sources(self):
        evidence = evidence_fixture()
        raw = summary_fixture(evidence)
        damaged = raw["focuses"][0]
        damaged["analysis"] = "999项。"
        damaged["risk"] = "999项。"
        damaged["entities"][0].update(headline="999项。", analysis="999项。", risk="999项。")
        original = copy.deepcopy(raw)
        cleaned = pipeline._drop_unsupported_numeric_clauses([raw], evidence)
        self.assertEqual(raw, original)
        self.assertEqual(cleaned[0]["focuses"][0]["analysis"], "")
        self.assertEqual(cleaned[0]["focuses"][0]["risk"], "")
        self.assertTrue(all(cleaned[0]["focuses"][0]["entities"][0][key] == "" for key in ("headline", "analysis", "risk")))
        with self.assertRaises(ValueError):
            pipeline._validate_model_summaries(cleaned, evidence)

    def test_manual_focus_uses_backup_after_key_pool_cooldown(self):
        focus = evidence_fixture()["domains"][0]["focuses"][0]
        answer = summary_fixture({"domains": [{"id": "local", "focuses": [focus]}]})["focuses"][0]
        reply = io.BytesIO(json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}]}).encode())
        with patch.object(pipeline, "open_llm_request", side_effect=[APIKeyPoolUnavailable(60, 1), reply]) as request:
            result = pipeline.generate_model_focus_insight("local", focus)
        self.assertEqual(result["model"], "backup")
        self.assertEqual([kwargs["model"] for _, kwargs in request.call_args_list], ["primary", "backup"])

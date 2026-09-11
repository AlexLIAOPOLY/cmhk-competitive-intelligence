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

    def test_failed_first_focus_does_not_block_later_focus_and_domain_checkpoints(self):
        evidence = evidence_fixture()
        other = copy.deepcopy(evidence["domains"][0])
        other.update(id="international", focuses=other["focuses"][:1])
        evidence["domains"].append(other)
        unavailable = True
        calls = []

        def request(req, **kwargs):
            scope = json.loads(json.loads(req.data)["messages"][1]["content"].split("输入：\n", 1)[1])
            domain = scope["domains"][0]
            ids = [f["id"] for f in domain["focuses"]]
            calls.append((domain["id"], ids))
            if domain["id"] == "local" and (len(ids) > 1 or (ids == ["custom_a"] and unavailable)):
                raise APIKeyPoolUnavailable(60, 1)
            return response(summary_fixture(scope))

        with tempfile.TemporaryDirectory() as td, patch.object(pipeline, "open_llm_request", side_effect=request):
            checkpoint = Path(td) / "ai.json"
            with self.assertRaisesRegex(ValueError, "local.custom_a"):
                pipeline.generate_model_domain_summaries(evidence, checkpoint_path=checkpoint, allow_partial_domains=True)
            saved = json.loads(checkpoint.read_text())
            persisted = [(x["summaries"][0]["domain"], [f["id"] for f in x["summaries"][0]["focuses"]]) for x in saved.values()]
            self.assertCountEqual(persisted, [("local", ["custom_b"]), ("international", ["custom_a"])])
            unavailable = False
            before = len(calls)
            result = pipeline.generate_model_domain_summaries(evidence, checkpoint_path=checkpoint, allow_partial_domains=True)
            self.assertEqual(calls[before:], [("local", ["custom_a"])])
            self.assertEqual(len(result["summaries"]), 2)

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

    def test_validation_retry_changes_prefix_and_retains_feedback(self):
        focus = evidence_fixture()["domains"][0]["focuses"][0]
        valid = summary_fixture({"domains": [{"id": "local", "focuses": [focus]}]})["focuses"][0]
        invalid = {**valid, "analysis": valid["analysis"] * 5}
        cached_prefixes = {}
        bodies = []

        def request(req, **kwargs):
            body = json.loads(req.data)
            bodies.append(body)
            self.assertEqual(body["cache"], {"no-cache": True, "no-store": True})
            prefix = body["messages"][0]["content"][:90]
            candidate = cached_prefixes.setdefault(prefix, invalid if len(bodies) == 1 else valid)
            return io.BytesIO(json.dumps({"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps(candidate, ensure_ascii=False),
            }}]}).encode())

        with patch.object(pipeline, "open_llm_request", side_effect=request):
            result = pipeline.generate_model_focus_insight("local", focus)
        self.assertEqual(len(bodies), 2)
        self.assertEqual(result["focus"]["analysis"], valid["analysis"])
        self.assertIn("上次未通过校验", bodies[1]["messages"][-1]["content"])
        self.assertEqual(bodies[0]["messages"][1], bodies[1]["messages"][1])
        self.assertNotIn(bodies[0]["messages"][0]["content"].splitlines()[0], bodies[1]["messages"][0]["content"])

    def test_ebitda_operating_cash_generation_dimension_retains_other_gates(self):
        focus = {"items": [
            {"name": "HKT", "value": 14234.0}, {"name": "SmarTone", "value": 2445.1},
            {"name": "3HK", "value": 1508.0},
        ]}
        analysis = ("HKT的EBITDA为14234.0百万港元，SmarTone为2445.1百万港元，3HK为1508.0百万港元，"
                    "显示HKT的经营造血规模显著不同，与SmarTone和3HK不在同一层次。")
        self.assertEqual(pipeline._focus_gate_error("local", "ebitda", analysis, focus), "")
        self.assertIn("120字", pipeline._focus_gate_error("local", "ebitda", analysis * 2, focus))
        self.assertFalse(pipeline._has_deep_interpretation("HKT的经营造血为14234.0百万港元。"))
        self.assertIn("行动建议", pipeline._focus_gate_error("local", "ebitda", analysis + "建议优先扩张。", focus))

    def test_manual_focus_retries_title_rejected_by_publication(self):
        focus = evidence_fixture()["domains"][0]["focuses"][0]
        focus["id"] = "revenue"
        valid = summary_fixture({"domains": [{"id": "local", "focuses": [focus]}]})["focuses"][0]
        valid["headline"] = "客户基础分化"
        invalid = {**valid, "headline": "营收规模不同"}
        replies = [io.BytesIO(json.dumps({"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(item, ensure_ascii=False),
        }}]}).encode()) for item in (invalid, valid)]
        with patch.object(pipeline, "open_llm_request", side_effect=replies) as request:
            result = pipeline.generate_model_focus_insight("local", focus)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(result["focus"]["headline"], valid["headline"])


class DiscoveryIncrementalEvidenceTests(unittest.TestCase):
    def fixture(self):
        domains = []
        for domain_id, value in (("local", 11), ("international", 22), ("mainland", 33), ("cloud", 44)):
            domains.append({"id": domain_id, "focuses": [], "research_comparison_scope": "独立半年披露，不替代年度比较",
                            "agent_verified_facts": [{"company": domain_id, "metric": "净利润", "value": value,
                                "unit": "亿元", "period": "H1 2026", "grain": "half_year",
                                "source_url": f"https://example.test/{domain_id}", "storage_verified": True}]})
        discoveries = [{"from": a, "to": b, "title": "半年利润范围不同", "kind": "AI综合研判",
                        "detail": f"两域半年利润为{x}亿元与{y}亿元，差距表明利润规模不同，并非同一范围的经营质量领先。",
                        "source_urls": [f"https://example.test/{a}", f"https://example.test/{b}"]}
                       for a, b, x, y in (("local", "international", 11, 22), ("international", "mainland", 22, 33),
                                           ("mainland", "cloud", 33, 44), ("cloud", "local", 44, 11))]
        return {"domains": domains}, discoveries

    def test_compact_keeps_separate_period_facts_and_bounds_payload(self):
        evidence, discoveries = self.fixture()
        fact = evidence["domains"][0]["agent_verified_facts"][0]
        evidence["domains"][0]["agent_verified_facts"] = [copy.deepcopy(fact) for _ in range(40)] + [
            {**fact, "value": 987654, "source_url": "https://omitted.test/hidden"}]
        compact = pipeline._compact_discovery_evidence(evidence)
        self.assertEqual(len(compact["domains"][0]["agent_verified_facts"]), 40)
        self.assertEqual(compact["domains"][0]["agent_verified_facts"][0], fact)
        self.assertEqual(compact["domains"][0]["focuses"], [])
        self.assertEqual(compact["domains"][0]["research_comparison_scope"], evidence["domains"][0]["research_comparison_scope"])
        self.assertEqual(pipeline._validate_model_discoveries(discoveries, compact), discoveries)
        for damage in ("number", "source"):
            with self.subTest(damage=damage):
                invalid = copy.deepcopy(discoveries)
                if damage == "number":
                    invalid[0]["detail"] = invalid[0]["detail"].replace("11亿元", "987654亿元")
                else:
                    invalid[0]["source_urls"].append("https://omitted.test/hidden")
                with self.assertRaisesRegex(ValueError, "输入之外"):
                    pipeline._validate_model_discoveries(invalid, compact)
        compact["domains"][0]["agent_verified_facts"][0]["period"] = "changed"
        self.assertEqual(fact["period"], "H1 2026")

    def test_generation_prompt_and_gate_share_incremental_evidence(self):
        evidence, discoveries = self.fixture()
        original_validate = pipeline._validate_model_discoveries
        seen = []

        def request(req, **kwargs):
            body = json.loads(req.data)
            scope = json.loads(body["messages"][1]["content"].split("输入：\n", 1)[1])
            seen.append(scope)
            return io.BytesIO(json.dumps({"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps({"items": discoveries}, ensure_ascii=False),
            }}]}).encode())

        def validate(raw, scope):
            self.assertEqual(scope, seen[0])
            return original_validate(raw, scope)

        with patch("ai_config.load_ai_config", return_value={"api_key": "fixture"}), \
             patch("ai_rate_limit.wait_for_internal_ai_slot"), \
             patch.object(pipeline, "open_llm_request", side_effect=request), \
             patch.object(pipeline, "_validate_model_discoveries", side_effect=validate):
            result = pipeline.generate_model_discoveries(evidence)
        self.assertEqual(result["discoveries"], discoveries)

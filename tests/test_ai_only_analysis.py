import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import executive_intelligence_pipeline as pipeline
from cmhk.intelligence.ai_provenance import AI_ONLY_POLICY, model_generated_only


class AIOnlyAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.evidence = {"domains": [{"id": "local", "focuses": [{"id": "revenue"}, {"id": "users"}]}]}
        self.summaries = [{"domain": "local", "focuses": [
            {"id": "revenue", "analysis": "model revenue", "headline": "Revenue", "risk": "scope"},
            {"id": "users", "analysis": "model users", "headline": "Users", "risk": "scope"},
        ]}]
        self.discoveries = [{"from": "local", "to": "cloud", "detail": "model relation"}]
        self.bundle = {
            "generation_policy": AI_ONLY_POLICY, "model": "test-model", "discovery_model": "test-model",
            "generated_at_hkt": "now", "summaries": self.summaries, "discoveries": self.discoveries,
            "evidence_hash": pipeline._content_hash(self.evidence), "insight_format": pipeline.INSIGHT_FORMAT_VERSION,
        }
        self.enterContext(patch.object(pipeline, "_analysis_input_snapshot", return_value=self.evidence))
        # Validator internals are covered separately; these exercise admission and writes.
        self.enterContext(patch.object(pipeline, "_validate_model_summaries", side_effect=lambda raw, *_a, **_k: copy.deepcopy(raw)))
        self.enterContext(patch.object(pipeline, "_validate_model_discoveries", side_effect=lambda raw, *_a, **_k: copy.deepcopy(raw)))
        self.generate = self.enterContext(patch.object(pipeline, "generate_model_domain_summaries", return_value={
            "model": "test-model", "generated_at_hkt": "now", "summaries": self.summaries,
        }))
        self.discover = self.enterContext(patch.object(pipeline, "generate_model_discoveries", return_value={
            "model": "test-model", "generated_at_hkt": "now", "discoveries": self.discoveries,
        }))
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory) / "analysis.json"
        self.path.write_text(json.dumps({"model_analysis": self.bundle, "agent_run_id": "test"}))

    def test_provenance_rejects_legacy_fallback_and_nested_rule(self):
        self.assertTrue(model_generated_only(self.bundle))
        for change in ({"generation_policy": None}, {"fallback_used": True},
                       {"discovery_fallback_used": True}, {"model": "deterministic-evidence-fallback"},
                       {"discoveries": [{"origin": "evidence_rule"}]}):
            self.assertFalse(model_generated_only({**self.bundle, **change}), change)

    def test_current_ai_cache_reuses_without_calls(self):
        result = pipeline.publish_model_domain_summaries(self.path)
        self.assertTrue(result["reused"])
        self.generate.assert_not_called()
        self.discover.assert_not_called()

    def test_legacy_cache_regenerates_all_not_just_bad_category(self):
        old = {**self.bundle, "fallback_used": True}
        self.path.write_text(json.dumps({"model_analysis": old}))
        result = pipeline.publish_model_domain_summaries(self.path)
        self.assertTrue(model_generated_only(result))
        self.generate.assert_called_once()
        self.discover.assert_called_once()

    def test_changed_evidence_invalidates_entire_bundle(self):
        self.bundle["evidence_hash"] = "old"
        self.path.write_text(json.dumps({"model_analysis": self.bundle}))
        pipeline.publish_model_domain_summaries(self.path)
        self.generate.assert_called_once()
        self.discover.assert_called_once()

    def test_model_failure_preserves_previous_file_without_fallback(self):
        self.generate.side_effect = RuntimeError("HTTP 401")
        self.bundle["fallback_used"] = True
        self.path.write_text(json.dumps({"model_analysis": self.bundle}))
        original = self.path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "401"):
            pipeline.publish_model_domain_summaries(self.path)
        self.assertEqual(self.path.read_bytes(), original)
        self.discover.assert_not_called()

    def test_discovery_failure_does_not_partially_write_new_summaries(self):
        self.path.write_text('{"model_analysis": {"evidence_hash": "old"}}')
        original = self.path.read_bytes()
        self.discover.side_effect = RuntimeError("invalid model response")
        with self.assertRaises(RuntimeError):
            pipeline.publish_model_domain_summaries(self.path)
        self.assertEqual(self.path.read_bytes(), original)

    def test_generator_cannot_relabel_rule_results(self):
        self.path.write_text('{}')
        self.generate.return_value["model"] = "evidence-rule-fallback"
        with self.assertRaisesRegex(ValueError, "非AI"):
            pipeline.publish_model_domain_summaries(self.path)
        self.assertEqual(self.path.read_text(), '{}')

    def test_manual_failure_preserves_all_existing_text(self):
        original = self.path.read_bytes()
        with patch.object(pipeline, "generate_model_focus_insight", side_effect=RuntimeError("AI failed")):
            with self.assertRaisesRegex(RuntimeError, "AI failed"):
                pipeline.regenerate_model_focus_summary("local", "revenue", path=self.path)
        self.assertEqual(self.path.read_bytes(), original)

    def test_manual_success_changes_only_target_focus(self):
        replacement = {"id": "revenue", "analysis": "new model revenue", "headline": "New", "risk": "scope"}
        with patch.object(pipeline, "generate_model_focus_insight", return_value={"model": "new-model", "focus": replacement}):
            result = pipeline.regenerate_model_focus_summary("local", "revenue", path=self.path)
        saved = json.loads(self.path.read_text())["model_analysis"]
        self.assertEqual(saved["summaries"][0]["focuses"][1], self.summaries[0]["focuses"][1])
        self.assertEqual(saved["discoveries"], self.discoveries)
        self.assertEqual(result["origin"], "ai")
        self.assertEqual(result["analysis"], "new model revenue")

    def test_repair_cannot_synthesize_analysis_or_relationship(self):
        raw = [{"domain": "local", "focuses": [{"id": "revenue", "analysis": "too shallow"}]}]
        self.assertEqual(pipeline._repair_model_summaries(raw, self.evidence), raw)
        discoveries = [{"title": "shallow", "detail": "just data"}]
        self.assertEqual(pipeline._repair_discovery_conciseness(discoveries), discoveries)
        self.assertEqual(pipeline._repair_discovery_depth(discoveries, self.evidence), (discoveries, 0))

    def test_legacy_degraded_result_never_finalizes_as_success(self):
        self.assertFalse(pipeline._validated_fallback_complete({"status": "completed_with_fallback"}))

    def test_history_only_displays_attested_model_discoveries(self):
        from data_curation.research_plan import ARCHITECTURE_VERSION
        from data_curation.research_readback import research_snapshot
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "curation_data/research_runs/history"
            directory.mkdir(parents=True)
            model = {"model": "deterministic-evidence-fallback", "fallback_used": True,
                     "evidence_hash": "same", "discovery_model": "test-model",
                     "discovery_evidence_repair_count": 0, "discoveries_passed": 1,
                     "generated_at_hkt": "2026-09-10T07:00:00+08:00",
                     "summaries": [{"focuses": [{"analysis": "RULE OUTPUT"}]}],
                     "discoveries": [{"detail": "REAL MODEL OUTPUT"}]}
            (directory / "manifest.json").write_text(json.dumps({
                "architecture": ARCHITECTURE_VERSION, "run_id": "history", "plan": [],
                "started_at": "2026-09-10T03:00:00+08:00", "publication": {"model_analysis": model},
            }))
            analysis_path = root / "agent_knowledge/executive_intelligence_refresh/ai_analysis.json"
            analysis_path.parent.mkdir(parents=True)
            analysis_path.write_text(json.dumps({"agent_run_id": "history", "model_analysis": model}))
            result = research_snapshot(root, "2026-09-10")
            self.assertEqual([item["detail"] for item in result["insight_items"]], ["REAL MODEL OUTPUT"])
            model["discovery_fallback_used"] = True
            analysis_path.write_text(json.dumps({"agent_run_id": "history", "model_analysis": model}))
            self.assertEqual(research_snapshot(root, "2026-09-10")["insight_items"], [])


if __name__ == "__main__":
    unittest.main()

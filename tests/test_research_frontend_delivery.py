import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from data_curation.research_freshness import load_baseline, compare_candidate
from scripts import publish_executive_dashboard_pages as publisher
import executive_intelligence_pipeline as pipeline


class FrontendDeliveryTests(unittest.TestCase):
    def test_unchanged_facts_rebind_to_new_run_without_regenerating_ai(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source, output = directory / 'facts.jsonl', directory / 'analysis.json'
            source.write_text('')
            pipeline.publish_ai_analysis(agent_run_id='research_20260913', verified_facts_path=source, output_path=output)
            prior = json.loads(output.read_text())
            prior['model_analysis'] = {'original_model_text': 'preserved'}
            output.write_text(json.dumps(prior))
            result = pipeline.publish_ai_analysis(agent_run_id='research_20260914', verified_facts_path=source, output_path=output)
            current = json.loads(output.read_text())
            self.assertFalse(result['changed'])
            self.assertEqual(current['agent_run_id'], 'research_20260914')
            self.assertEqual(current['model_analysis'], prior['model_analysis'])

    def test_reused_analysis_details_bind_to_verified_run_archive(self):
        from data_curation.research_readback import research_snapshot
        from cmhk.intelligence.ai_provenance import AI_ONLY_POLICY
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / 'curation_data/research_runs/research_20260913'
            directory.mkdir(parents=True)
            model = {'generation_policy': AI_ONLY_POLICY, 'model': 'model-a', 'discovery_model': 'model-b',
                'generated_at_hkt': '2026-09-12T12:33:21+08:00', 'evidence_hash': 'same-evidence', 'reused': True,
                'summaries': [{'domain': 'local', 'focuses': [{'headline': f'focus-{i}'} for i in range(15)]}],
                'discoveries': [{'title': f'cross-{i}'} for i in range(4)]}
            digest = pipeline.archive_model_analysis(directory, directory.name, model)
            manifest = {'run_id': directory.name, 'architecture': 'six_research_agents_v1',
                'started_at': '2026-09-13T03:00:00+08:00',
                'status': 'partial', 'publication': {'status': 'completed', 'model_analysis': {
                    'ok': True, 'reused': True, 'generated_at_hkt': model['generated_at_hkt'],
                    'evidence_hash': model['evidence_hash'], 'snapshot_sha256': digest}}}
            path = directory / 'manifest.json'; path.write_text(json.dumps(manifest))
            latest = root / 'agent_knowledge/executive_intelligence_refresh/ai_analysis.json'
            latest.parent.mkdir(parents=True)
            latest.write_text(json.dumps({'agent_run_id': 'research_20260914', 'model_analysis': model}))
            self.assertEqual(len(research_snapshot(root, '2026-09-13')['insight_items']), 19)
            for key, value in [('snapshot_sha256', 'tampered'), ('evidence_hash', 'other-evidence'), ('reused', False)]:
                invalid = json.loads(json.dumps(manifest)); invalid['publication']['model_analysis'][key] = value
                path.write_text(json.dumps(invalid))
                self.assertEqual(research_snapshot(root, '2026-09-13')['insight_items'], [], key)
            path.write_text(json.dumps(manifest))
            archive = directory / 'published_ai_analysis.json'
            archive.write_text(archive.read_text().replace('focus-0', 'unreviewed-text'))
            self.assertEqual(research_snapshot(root, '2026-09-13')['insight_items'], [])

    def test_latest_frontend_sources_are_trusted_baselines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {
                "local_hk_operator_operating_metrics_2016_2025/annual_metrics.json": {"rows": [{"operator": "CMHK", "metric": "收入", "period": "FY2025", "value": 12}]},
                "cloud_vendor_metrics_2026-06-17/cloud_vendor_metrics_2016_2025.json": {"rows": [{"vendor": "AWS", "metric_key": "cloud_revenue", "fiscal_year": "2025", "value": 20}]},
                "requested_overview_010304_2016_2025/annual_facts.json": {"rows": [{"entity": "NTT DOCOMO", "metric": "ebitda", "period": "FY2025", "value": 30, "source_urls": ["https://example.test/report"], "scope_note": "group"}]},
            }
            for name, data in files.items():
                target = root / "agent_knowledge" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(data))
            baseline = load_baseline(root)
            for company, metric in [("CMHK", "收入"), ("AWS", "云收入"), ("NTT Docomo", "EBITDA")]:
                candidate = {"status": "verified", "metric": metric, "period": "FY2025", "value": 999}
                self.assertEqual(compare_candidate(candidate, baseline["companies"][company])["status"], "no_update")
            self.assertEqual(baseline["companies"]["NTT Docomo"]["EBITDA"][0]["scope"], "group")

    def test_rebuild_failure_blocks_publication(self):
        with patch.object(pipeline, "_run_builder", return_value=subprocess.CompletedProcess([], 1, "", "broken source")), patch.object(pipeline.subprocess, "run") as publish:
            with self.assertRaisesRegex(RuntimeError, "竞对前端数据重建失败"):
                pipeline._publish_and_verify_github_pages()
            publish.assert_not_called()

    def test_rebuild_precedes_publication(self):
        order = []
        def rebuild(*args):
            order.append("rebuild")
            return subprocess.CompletedProcess([], 0, "built", "")
        def publish(*args, **kwargs):
            order.append("publish")
            return subprocess.CompletedProcess([], 0, json.dumps({"status": "verified", "site_version": "v1", "public_url": "https://example.test/"}), "")
        with patch.object(pipeline, "_run_builder", side_effect=rebuild), patch.object(pipeline.subprocess, "run", side_effect=publish):
            self.assertTrue(pipeline._publish_and_verify_github_pages()["ok"])
        self.assertEqual(order, ["rebuild", "publish"])

    def test_public_readback_rejects_stale_comparison_data(self):
        with patch.object(publisher, "_run", side_effect=lambda args: subprocess.CompletedProcess(args, 0, json.dumps({"site_version": "v1"}) if args[-1].endswith("strategic-briefs.json") else "old", "")), patch.object(publisher.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "公开竞对数据"):
                publisher._verify("https://example.test", "v1", hashlib.sha256(b"new").hexdigest())

    def test_public_package_includes_required_research_renderer(self):
        self.assertIn("research-diagram.js", publisher.PUBLIC_STATIC_FILES)
        self.assertIn('route === "/api/news-research"', publisher.PUBLIC_SNAPSHOT_BOOTSTRAP)
        self.assertIn("run: null, runs: [], agents: [], events: []", publisher.PUBLIC_SNAPSHOT_BOOTSTRAP)

    def test_history_uses_saved_assignments_after_frontend_catalog_changes(self):
        from data_curation.research_readback import research_snapshot
        from data_curation.research_plan import ARCHITECTURE_VERSION
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "curation_data/research_runs/history"
            directory.mkdir(parents=True)
            plan = [{"key": "asia-pacific", "title": "历史研究", "companies": ["Singtel"], "purpose": "原任务"}]
            (directory / "manifest.json").write_text(json.dumps({"architecture": ARCHITECTURE_VERSION, "started_at": "2026-09-07T03:00:00+08:00", "run_id": "history", "plan": plan}))
            snapshot = research_snapshot(root, "2026-09-07")
            self.assertEqual(snapshot["plan"], plan)
            self.assertEqual(len(snapshot["agents"]), 1)
            self.assertIsNone(research_snapshot(root, "2026-09-08")["run"])

    def test_research_metrics_follow_current_frontend_focus_labels(self):
        from data_curation.research_plan import frontend_metric_plan
        snapshot = {"domains": [{"id": "international", "focuses": [{"label": label} for label in ["营收", "净利润", "资本开支", "移动ARPU", "新披露指标"]]}]}
        with patch("cmhk.intelligence.executive.build_executive_intelligence_snapshot", return_value=snapshot):
            self.assertEqual(frontend_metric_plan()["international"], ["收入", "净利润", "资本开支", "ARPU", "新披露指标"])

    def test_current_four_frontend_domains_have_research_metrics(self):
        from data_curation.research_plan import frontend_metric_plan
        plan = frontend_metric_plan()
        self.assertEqual(set(plan), {"local", "international", "mainland", "cloud"})
        self.assertTrue({"收入", "净利润", "资本开支", "ARPU"} <= set(plan["international"]))

    def test_overview_focus_ids_keep_cloud_and_customer_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "agent_knowledge/requested_overview_010304_2016_2025/annual_facts.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps({"rows": [
                {"entity": "AWS", "domain": "04", "metric": "revenue", "period": "FY2025", "value": 10},
                {"entity": "中国移动", "domain": "03", "metric": "postpaid", "period": "FY2025", "value": 20},
                {"entity": "HKT", "domain": "01", "metric": "postpaid", "period": "FY2025", "value": 30}]}))
            data = load_baseline(root)["companies"]
            self.assertIn("云收入", data["AWS"])
            self.assertNotIn("收入", data["AWS"])
            self.assertIn("移动客户数", data["中国移动"])
            self.assertIn("后付费用户数", data["HKT"])

    def test_assignment_and_resume_use_only_homepage_metrics(self):
        from data_curation.six_agent_research import run_assignment
        task = {"key": "asia-pacific", "title": "亚太", "purpose": "研究", "companies": ["Singtel"]}
        collector = lambda *args: ({"https://example.test": {"opened": True, "official": True, "text": ""}}, [])
        with patch("data_curation.research_harness.ResearchHarness"), patch("data_curation.workflow._company_expected_metrics", return_value=["AI"]):
            new = run_assignment(task, lambda *args: None, model_factory=lambda: object(), collector=collector, baseline={})
            self.assertEqual(set(new["reports"][0]["metrics"]), {"收入", "净利润", "资本开支", "ARPU"})
            old = {"reports": [{"company": "Singtel", "status": "partial", "metrics": ["AI"], "items": []}]}
            resumed = run_assignment(task, lambda *args: None, checkpoint=old, model_factory=lambda: object(), collector=collector, baseline={})
            self.assertEqual(resumed["reports"][0]["metrics"], new["reports"][0]["metrics"])

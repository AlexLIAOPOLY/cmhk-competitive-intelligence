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

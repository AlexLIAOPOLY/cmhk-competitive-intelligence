import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import scheduler
import executive_intelligence_pipeline as pipeline
from data_curation.daily_research import dispatch, HKT
from data_curation.research_plan import ARCHITECTURE_VERSION, research_plan
from data_curation.research_readback import research_snapshot


class SixAgentPipelineTests(unittest.TestCase):
    def test_new_scheduler_never_invokes_legacy_chain(self):
        with patch.object(scheduler, "crawl_process_running", return_value=False), \
             patch.object(scheduler, "agent_audit_process_running", return_value=False), \
             patch.object(scheduler, "standalone_research_process_running", return_value=False), \
             patch.object(scheduler, "legacy_run_cycle", side_effect=AssertionError("legacy")), \
             patch.object(scheduler, "run_due_four_database_source_discovery", side_effect=AssertionError("discovery")), \
             patch.object(scheduler, "dispatch_subscription_queue", return_value={}), \
             patch.object(scheduler, "dispatch_scheduled_weekly_report", return_value={}), \
             patch.object(scheduler, "dispatch_scheduled_performance_report", return_value={}), \
             patch("data_curation.daily_research.dispatch", return_value={"agent_count": 6}) as launch:
            result = scheduler.run_cycle()
            self.assertEqual(result["research"]["agent_count"], 6)
            launch.assert_called_once()

    def test_daily_dispatch_dry_run_does_not_create_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = dispatch(root, datetime(2026, 9, 5, 3, 1, tzinfo=HKT), dry_run=True)
            self.assertEqual(len(result["plan"]), 6)
            self.assertEqual(list(root.iterdir()), [])
            self.assertFalse(dispatch(root, datetime(2026, 9, 5, 2, tzinfo=HKT))["due"])

    def test_snapshot_is_date_scoped_and_does_not_send_page_bodies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "curation_data/research_runs/research_20260905"
            run.mkdir(parents=True)
            (run / "manifest.json").write_text(json.dumps({"architecture": ARCHITECTURE_VERSION,
                "run_id": run.name, "started_at": "2026-09-05T03:00:00+08:00", "status": "running"}))
            (run / "hong-kong.json").write_text(json.dumps({**research_plan()[0], "reports": [{
                "company": "HKT", "pages": {"url": {"opened": True, "text": "original page body"}},
                "items": [{"metric": "收入", "quote": "evidence quote"}]}]}))
            snapshot = research_snapshot(root, "2026-09-05")
            self.assertEqual(len(snapshot["agents"]), 6)
            self.assertNotIn("text", snapshot["agents"][0]["reports"][0]["pages"]["url"])
            self.assertEqual(snapshot["agents"][0]["reports"][0]["items"][0]["quote"], "evidence quote")
            self.assertIsNone(research_snapshot(root, "2026-09-04")["run"])
            with self.assertRaises(ValueError):
                research_snapshot(root, "../../secrets")

    def test_six_agent_four_library_upsert_keeps_missing_and_historical_values(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = {domain: Path(directory) / (domain + ".json") for domain in pipeline.FACT_DOMAIN_IDS}
            old = {"company": "HKT", "metric": "收入", "period": "2025", "unit": "HKD million",
                   "analysis": "35000", "quality_score": .9, "source_tier": "official", "source_url": "https://hkt.com/2025"}
            paths["local"].write_text(json.dumps({"facts": [old]}))
            macro = '{"facts": [{"unchanged": true}]}'
            paths["macro"].write_text(macro)
            new = {**old, "period": "2026", "analysis": "36000"}
            analysis = {"architecture": ARCHITECTURE_VERSION, "agent_run_id": "research_test",
                        "domains": {"local": [new]}}
            result = pipeline.publish_domain_fact_sidecars(analysis, output_paths=paths)
            self.assertEqual(result["local"]["submitted_facts"], 1)
            self.assertEqual(result["local"]["facts"], 2)
            self.assertEqual(paths["macro"].read_text(), macro)
            first = paths["local"].read_text()
            repeated = pipeline.publish_domain_fact_sidecars(analysis, output_paths=paths)
            self.assertFalse(repeated["local"]["changed"])
            self.assertEqual(paths["local"].read_text(), first)
            pipeline.publish_domain_fact_sidecars({**analysis, "domains": {}}, output_paths=paths)
            self.assertEqual(len(json.loads(paths["local"].read_text())["facts"]), 2)

    def test_six_research_publication_requires_its_own_finished_manifest(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(pipeline, "ROOT", Path(directory)):
            with self.assertRaises(ValueError):
                pipeline.run_pipeline(agent_run_id="research_test", curation_summary={"architecture": ARCHITECTURE_VERSION})
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()

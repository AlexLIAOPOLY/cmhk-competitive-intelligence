import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from data_curation.research_storage import DOMAIN_PATHS, MAIN_PATH, audit_storage, merge_domain, project_fact
from cmhk.data.daily_financial_promotion import _exact_money, _incremental_rows, promote_daily_financial_facts
from data_curation.research_kpi import write_formal_facts

ROOT = Path(__file__).resolve().parents[1]


def fact(**updates):
    return {"id": "test-id", "company": "HKT", "metric": "收入", "period": "H1 2026",
            "value": "HKD 200 million", "unit": "HKD million", "decision": "accepted",
            "status": "ok", "freshness": "new_period", "entity_supported": True,
            "metric_supported": True, "value_supported": True, "quality_score": .95,
            "source_tier": "official", "evidence_hash": "test-hash",
            "sources": ["https://www.hkt.com/test"], **updates}


class ResearchStorageTests(unittest.TestCase):
    def test_pipeline_projection_and_api_readback_preserve_periods_zero_and_detect_drift(self):
        import executive_intelligence_pipeline as pipeline
        from data_curation.research_readback import research_snapshot
        from data_curation.research_plan import ARCHITECTURE_VERSION
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "curation_data/research_runs/research_20260910"
            run.mkdir(parents=True)
            facts = [fact(metric="用户数", value=0, unit="人", id="first"),
                     fact(metric="用户数", value=1, unit="人", id="second", period="Q3 2026")]
            verified = run / "verified_facts.jsonl"
            verified.write_text('\n'.join(json.dumps(item) for item in facts))
            manifest = {"architecture": ARCHITECTURE_VERSION, "research_policy": "latest_disclosure_incremental_v1",
                        "accepted": 2, "status": "completed", "run_id": run.name, "started_at": "2026-09-10T03:00:00+08:00",
                        "publication": {"status": "completed", "database_updated": True}}
            (run / "manifest.json").write_text(json.dumps(manifest))
            analysis = pipeline.build_ai_analysis(agent_run_id=run.name, verified_facts_path=verified, curation_summary=manifest)
            self.assertEqual(analysis["domains"]["local"][0]["analysis"], 0)
            self.assertEqual(analysis["domain_counts"]["local"], 2)
            pipeline.publish_domain_fact_sidecars(analysis, output_paths={key: root / path for key, path in DOMAIN_PATHS.items()})
            self.assertFalse(research_snapshot(root, "2026-09-10")["run"]["publication"]["database_updated"])
            main = root / MAIN_PATH
            main.parent.mkdir(parents=True, exist_ok=True)
            main.write_text('{"rows":[]}')
            write_formal_facts(root, facts)
            before = research_snapshot(root, "2026-09-10")
            self.assertTrue(before["run"]["publication"]["database_updated"])
            self.assertEqual(before["storage_readback"]["confirmed"], 2)
            (root / DOMAIN_PATHS["local"]).write_text('{"facts":[]}')
            self.assertTrue(research_snapshot(root, "2026-09-10")["run"]["publication"]["database_updated"])
            main.write_text('{"rows":[]}')
            after = research_snapshot(root, "2026-09-10")
            self.assertFalse(after["run"]["publication"]["database_updated"])
            self.assertTrue(after["run"]["publication"]["recorded_database_updated"])
            self.assertEqual(json.loads((run / "manifest.json").read_text()), manifest)

    def merge(self, path, items, **kwargs):
        return merge_domain(path, [project_fact(item) for item in items], domain="local",
                            run_id="research_test", generated_at="2026-09-10", **kwargs)

    def test_idempotence_alias_zero_and_conflict_preservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "facts.json"
            first = self.merge(path, [fact(value=0)])
            self.assertEqual(first["inserted_facts"], 1)
            before = path.read_bytes()
            second = self.merge(path, [fact(value=0, metric="运营收入/总收益", id="alias")])
            self.assertTrue(second["ok"])
            self.assertEqual(second["already_saved_facts"], 1)
            self.assertEqual(path.read_bytes(), before)
            conflict = self.merge(path, [fact(value=999)])
            self.assertFalse(conflict["ok"])
            self.assertEqual(conflict["items"][0]["status"], "conflict_preserved")
            self.assertEqual(path.read_bytes(), before)

    def test_corrupt_existing_store_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "facts.json"
            path.write_text("{broken")
            with self.assertRaises(ValueError):
                self.merge(path, [fact()])
            self.assertEqual(path.read_text(), "{broken")

    def test_failed_disk_write_cannot_claim_saved(self):
        with tempfile.TemporaryDirectory() as tmp, patch("data_curation.six_agent_research.atomic_write_json"):
            result = self.merge(Path(tmp) / "facts.json", [fact()])
            self.assertFalse(result["ok"])
            self.assertEqual(result["confirmed_facts"], 0)

    def test_current_readback_detects_later_overwrite_and_missing_accepted_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / DOMAIN_PATHS["local"]
            raw = fact(metric="用户数", value=0, unit="人")
            self.merge(path, [raw])
            self.assertFalse(audit_storage(root, [raw])["ok"])
            main = root / MAIN_PATH
            main.parent.mkdir(parents=True, exist_ok=True)
            main.write_text('{"rows":[]}')
            write_formal_facts(root, [raw])
            self.assertTrue(audit_storage(root, [raw])["ok"])
            self.assertFalse(audit_storage(root, [raw], expected=2)["ok"])
            path.write_text('{"facts": []}')
            self.assertTrue(audit_storage(root, [raw])["ok"])
            main.write_text('{"rows":[]}')
            readback = audit_storage(root, [raw])
            self.assertEqual(readback["missing"], 1)
            self.assertFalse(readback["ok"])

    def test_exact_amounts_and_ambiguous_definitions(self):
        for value, unit, expected in [("19.6 RMB Bil", "RMB Bil", (19600, "CNY")),
                                      ("4.3591 KRW trillion", "KRW trillion", (4359100, "KRW")),
                                      ("€16,392 million", "€ million", (16392, "EUR")),
                                      ("-HKD 2.5 million", "HKD million", (-2.5, "HKD")),
                                      ("0 USD million", "USD million", (0, "USD"))]:
            self.assertEqual(_exact_money(value, unit), expected)
        for value in ["USD 10-20 million", "over USD 20 million", "2026 USD 20 million", "USD 20 million (10%)", "USD 20 EUR million", "USD 2 million billion", "USD 12,34 million"]:
            self.assertIsNone(_exact_money(value, "USD million"), value)
        self.assertEqual(_incremental_rows([json.dumps(fact(metric="EBITDA或经营利润"))]), [])
        self.assertEqual(_incremental_rows([json.dumps(fact(source_tier="media"))]), [])
        self.assertEqual(_incremental_rows([json.dumps(fact(company="Telstra"))]), [])

    def test_primary_preservation_also_preserves_subject_index_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, verified = root / "quarterly_metrics.json", root / "facts.jsonl"
            old = {"subject": "HKT / csl / 1O1O", "period": "H1 2026", "metric_key": "revenue",
                   "value": 100, "unit": "millions HKD", "grain": "half_year", "period_end": "2026-06-30"}
            path.write_text(json.dumps({"rows": [old], "subjects": [{"subject": old["subject"], "metrics": {"revenue": {"H1 2026": 100}}, "periods": []}]}))
            verified.write_text('\n'.join(json.dumps(fact(period=p)) for p in ["H1 2026", "Q3 2026"]))
            args = dict(database_path=path, local_financial_path=root / "absent", verified_facts_path=verified, incremental_only=True)
            result = promote_daily_financial_facts(**args)
            self.assertEqual(result["added_rows"], 1)
            payload = json.loads(path.read_text())
            self.assertEqual(payload["subjects"][0]["metrics"]["revenue"]["H1 2026"], 100)
            self.assertIn(old, payload["rows"])
            # A retry must repair a partially published derived export too.
            path.with_suffix('.csv').write_text('incomplete export')
            self.assertEqual(promote_daily_financial_facts(**args)["added_rows"], 0)
            self.assertNotEqual(path.with_suffix('.csv').read_text(), 'incomplete export')
            path.write_text('{broken')
            with self.assertRaises(ValueError):
                promote_daily_financial_facts(**args)
            self.assertEqual(path.read_text(), '{broken')

    def test_activation_protects_live_data_even_from_an_old_queued_release(self):
        script = (ROOT / "scripts/queued_web_app_reload_worker.sh").read_text()
        command = re.search(r'  /usr/bin/rsync -a "\$release_dir/" "\$RUNTIME/".*?>> "\$LOG_FILE" 2>&1', script, re.S)[0]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release, runtime = root / "release", root / "runtime"
            relatives = [*DOMAIN_PATHS.values(), MAIN_PATH, "curation_data/research_runs/test/manifest.json"]
            for directory, content in [(release, "stale"), (runtime, "live")]:
                directory.mkdir()
                (directory / "test-code.js").write_text(content)
                for relative in relatives:
                    path = directory / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content)
            import os
            subprocess.run(["bash", "-c", command], check=True,
                           env={**os.environ, "release_dir": str(release), "RUNTIME": str(runtime), "LOG_FILE": str(root / "log")})
            self.assertEqual((runtime / "test-code.js").read_text(), "stale")
            for relative in relatives:
                self.assertEqual((runtime / relative).read_text(), "live")


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from data_curation import daily_research as daily


class ManualRerunTests(unittest.TestCase):
    def test_new_batch_preserves_daily_history_and_uses_complete_pipeline_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / "curation_data/research_runs/research_20260907/manifest.json"
            old.parent.mkdir(parents=True)
            old.write_text('{"historical": true}')
            summary = {"status": "completed", "accepted": 0, "review": 0,
                       "research_policy": "latest_disclosure_incremental_v1"}
            with patch.object(daily, "ROOT", root), patch.object(daily, "run_research", return_value=summary) as research:
                result = daily.execute(root, "research_20260907_rerun_153300")
            self.assertEqual(result["publication"]["result_status"], "no_new_disclosures")
            self.assertFalse(research.call_args.kwargs["resume"])
            self.assertEqual(old.read_text(), '{"historical": true}')
            self.assertTrue((old.parent.parent / "research_20260907_rerun_153300/manifest.json").exists())

    def test_manual_batch_id_cannot_escape_research_directory(self):
        for value in ["../research_20260907", "research_20260907_rerun_x", "research_20260907/other"]:
            with self.assertRaises(ValueError):
                daily.execute(daily.ROOT, value)

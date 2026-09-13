import json
import tempfile
import unittest
from pathlib import Path

from data_curation.research_kpi import CARRIER_PATH, CLOUD_PATH
from data_curation.research_table_view import formal_table_view


class ResearchFormalTableViewTests(unittest.TestCase):
    def make_root(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        carrier = root / CARRIER_PATH
        carrier.parent.mkdir(parents=True)
        carrier.write_text(json.dumps({"rows": [
            {"subject": "HKT / csl / 1O1O", "period": "H1 2026", "metric_key": "revenue", "metric_zh": "收入", "value": 10, "unit": "millions HKD", "official_source_url": "https://example.test/hkt"},
            {"subject": "Singtel", "period": "FY2025", "metric_key": "revenue", "metric_zh": "收入", "value": 20, "unit": "millions SGD"},
        ]}, ensure_ascii=False))
        cloud = root / CLOUD_PATH
        cloud.parent.mkdir(parents=True)
        cloud.write_text(json.dumps({"rows": [
            {"vendor": "AWS", "fiscal_year": "2025", "metric_key": "cloud_revenue", "metric_zh": "云收入", "value": 30, "currency": "USD", "unit": "millions"},
        ]}, ensure_ascii=False))
        run_id = "research_20260913"
        run = root / "curation_data" / "research_runs" / run_id
        run.mkdir(parents=True)
        run.joinpath("manifest.json").write_text(json.dumps({
            "run_id": run_id,
            "publication": {"storage_readback": {"items": [
                {"main_table": {"status": "written", "path": CARRIER_PATH, "row_key": {"subject": "HKT / csl / 1O1O", "period": "H1 2026", "metric_key": "revenue"}, "current_value": 10, "unit": "millions HKD"}},
                {"main_table": {"status": "written", "path": CLOUD_PATH, "row_key": {"vendor": "AWS", "fiscal_year": "2025", "metric_key": "cloud_revenue"}, "current_value": 30, "unit": "millions", "currency": "USD"}},
            ]}},
        }, ensure_ascii=False))
        return root

    def test_full_table_is_paginated_and_run_rows_are_highlighted(self):
        payload = formal_table_view(self.make_root(), run_id="research_20260913", table_id="carrier")
        self.assertEqual(payload["summary"]["total"], 2)
        self.assertEqual(payload["summary"]["new_total"], 1)
        self.assertTrue(payload["rows"][0]["is_new"])
        self.assertIn("value", payload["rows"][0]["highlighted_cells"])
        self.assertFalse(payload["rows"][1]["is_new"])
        self.assertIn("official_source_url", [column["key"] for column in payload["columns"]])

    def test_search_and_new_only_filter_the_complete_source(self):
        root = self.make_root()
        searched = formal_table_view(root, run_id="research_20260913", table_id="carrier", query="Singtel")
        self.assertEqual(searched["summary"]["filtered"], 1)
        self.assertEqual(searched["rows"][0]["values"]["subject"], "Singtel")
        added = formal_table_view(root, run_id="research_20260913", table_id="cloud", highlight_only=True)
        self.assertEqual(added["summary"]["filtered"], 1)
        self.assertTrue(added["rows"][0]["is_new"])

    def test_stale_receipt_does_not_highlight_changed_current_value(self):
        root = self.make_root()
        path = root / CARRIER_PATH
        table = json.loads(path.read_text())
        table["rows"][0]["value"] = 11
        path.write_text(json.dumps(table))
        payload = formal_table_view(root, run_id="research_20260913", table_id="carrier")
        self.assertEqual(payload["summary"]["new_total"], 0)
        self.assertEqual(payload["summary"]["highlight_mismatch"], 1)

    def test_arbitrary_paths_and_run_ids_are_rejected(self):
        root = self.make_root()
        with self.assertRaisesRegex(ValueError, "正式表编号无效"):
            formal_table_view(root, run_id="research_20260913", table_id="../../secret")
        with self.assertRaisesRegex(ValueError, "研究批次编号无效"):
            formal_table_view(root, run_id="../research_20260913", table_id="carrier")


if __name__ == "__main__":
    unittest.main()

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_competitor_numeric_integrity.py"
SPEC = importlib.util.spec_from_file_location("numeric_integrity_audit", SCRIPT)
AUDIT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(AUDIT)


class CompetitorNumericIntegrityAuditTest(unittest.TestCase):
    def test_every_gap_has_a_recorded_search_boundary(self):
        summaries = []
        rows = []
        for config in AUDIT.DATASETS:
            dataset_rows, summary = AUDIT.audit_dataset(config)
            rows.extend(dataset_rows)
            summaries.append(summary)
        self.assertEqual(sum(item["row_count"] for item in summaries), 7648)
        self.assertEqual(sum(item["duplicate_rows"] for item in summaries), 0)
        self.assertEqual(sum(item["invalid_numeric_rows"] for item in summaries), 0)
        self.assertEqual(
            sum(item["numeric_without_source_reference"] for item in summaries), 0
        )
        self.assertEqual(
            sum(item["targeted_search_not_recorded_rows"] for item in summaries), 0
        )
        tariff_gaps = [
            row
            for row in rows
            if row["dataset_id"] == "competitor_product_tariffs"
            and row["value_state"] == "missing"
        ]
        self.assertEqual(len(tariff_gaps), 4)
        self.assertTrue(
            all(
                row["gap_search_status"]
                == "documented_public_product_source_no_price"
                for row in tariff_gaps
            )
        )
        self.assertTrue(all(row["resolved_source_url_count"] == 1 for row in tariff_gaps))


if __name__ == "__main__":
    unittest.main()

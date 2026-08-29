import csv
import tempfile
import unittest
from pathlib import Path

from scripts.audit_hk_product_tariff_followups import generate_followup_audit


class ProductTariffFollowupAuditTest(unittest.TestCase):
    def test_duplicate_parsed_candidates_are_counted_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dataset = Path(tmp)
            fields = [
                "period_label",
                "brand",
                "product_category",
                "gap_type",
                "source_id",
                "source_url",
                "archive_url",
                "evidence_excerpt",
            ]
            base = {
                "period_label": "current",
                "brand": "HKBN",
                "product_category": "home_fibre_broadband",
                "gap_type": "single_source_unverified_plan_row",
                "source_id": "hkbn_home_broadband_offer",
                "source_url": "https://example.com/hkbn",
                "archive_url": "",
            }
            rows = [
                {**base, "evidence_excerpt": "HKBN 1000M Home Broadband Plan；period=current；speed=1000；fee=378；evidence=first excerpt"},
                {**base, "evidence_excerpt": "HKBN 1000M Home Broadband Plan；period=current；speed=1000；fee=378；evidence=second excerpt"},
            ]
            with (dataset / "source_gaps.csv").open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)

            result = generate_followup_audit(dataset)

            with (dataset / "verification_followup_audit.csv").open(encoding="utf-8-sig", newline="") as handle:
                output = list(csv.DictReader(handle))
            self.assertEqual(result["verification_backlog_rechecked"], 1)
            self.assertEqual(result["duplicate_queue_rows_removed"], 1)
            self.assertEqual(len(output), 1)
            self.assertEqual(output[0]["candidate_plan"], "HKBN 1000M Home Broadband Plan")
            self.assertEqual(output[0]["recheck_status"], "no_equivalent_second_source_found")


if __name__ == "__main__":
    unittest.main()

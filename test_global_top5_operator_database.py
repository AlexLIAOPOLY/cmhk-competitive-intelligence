import json
import subprocess
import sys
import unittest
from pathlib import Path

import rag_llm


ROOT = Path(__file__).resolve().parent
GLOBAL = ROOT / "agent_knowledge" / "global_top5_operators_2016_2025"
ORIGINAL = ROOT / "agent_knowledge" / "quarterly_competitor_metrics_2026-06-18"


class GlobalTop5OperatorDatabaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_global_top5_operator_database.py")],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        cls.payload = json.loads((GLOBAL / "annual_metrics.json").read_text(encoding="utf-8"))
        cls.rows = cls.payload["rows"]
        cls.index = {(r["operator_id"], r["year"], r["metric_key"]): r for r in cls.rows}

    def test_quality_gate_and_unique_keys(self):
        audit = json.loads((GLOBAL / "quality_audit.json").read_text(encoding="utf-8"))
        self.assertEqual(audit["status"], "pass")
        self.assertEqual(audit["duplicate_key_count"], 0)
        self.assertEqual(audit["invalid_source_ids"], [])

    def test_anchor_values_and_customer_scope(self):
        expected = {
            ("china_mobile", 2025, "mobile_subscribers"): 1005,
            ("china_telecom", 2025, "5g_network_subscribers"): 301.81,
            ("china_unicom", 2025, "5g_network_subscribers"): 232.18,
            ("bharti_airtel", 2025, "total_customers"): 590.514,
            ("reliance_jio", 2025, "total_customers"): 488.2,
        }
        for key, value in expected.items():
            self.assertEqual(self.index[key]["value"], value)
        self.assertNotIn(("bharti_airtel", 2025, "mobile_subscribers"), self.index)
        self.assertNotIn(("reliance_jio", 2025, "mobile_subscribers"), self.index)

    def test_5g_definitions_and_shared_network_are_explicit(self):
        metric_keys = {r["metric_key"] for r in self.rows}
        self.assertIn("5g_package_subscribers", metric_keys)
        self.assertIn("5g_network_subscribers", metric_keys)
        for operator_id in ("china_telecom", "china_unicom"):
            row = self.index[(operator_id, 2025, "5g_base_stations")]
            self.assertIn("Shared-network scope", row["quality_note"])

    def test_precommercial_and_derived_values_are_not_overstated(self):
        jio = self.index[("reliance_jio", 2016, "total_customers")]
        self.assertIsNone(jio["value"])
        self.assertEqual(jio["verification_status"], "not_applicable_precommercial")
        unicom = self.index[("china_unicom", 2025, "mobile_subscribers")]
        self.assertEqual(unicom["verification_status"], "official_derived_from_verified_rows")
        self.assertEqual(unicom["comparator"], "≈")

    def test_china_sidecar_only_adds_operating_metrics(self):
        sidecar = json.loads((ORIGINAL / "annual_operating_metrics_2016_2025.json").read_text(encoding="utf-8"))
        self.assertEqual({r["operator_id"] for r in sidecar["rows"]}, {"china_mobile", "china_telecom", "china_unicom"})
        financial_metrics = {"revenue", "ebitda", "ebit", "earnings_before_tax", "net_profit", "capex", "net_debt", "shareholders_equity"}
        self.assertFalse(financial_metrics & {r["metric_key"] for r in sidecar["rows"]})

    def test_xiaojing_ai_exact_retrieval_respects_selected_database(self):
        question = "中国移动2025移动用户数、中国电信2025年5G网络用户数、Jio FY2025总客户数和移动ARPU"
        chunks = rag_llm._global_operator_exact_metric_chunks(
            question,
            dataset_ids={"global_top5_operators_2016_2025"},
        )
        combined = "\n".join(chunk["text"] for chunk in chunks)
        self.assertIn("operator=中国移动", combined)
        self.assertIn("official_value=1005 million_subscribers", combined)
        self.assertIn("operator=中国电信", combined)
        self.assertIn("official_value=301.81 million_subscribers", combined)
        self.assertIn("operator=Reliance Jio", combined)
        self.assertIn("official_value=488.2 million_customers", combined)
        self.assertIn("official_value=206.2 INR_per_user_month", combined)
        self.assertEqual(
            rag_llm._global_operator_exact_metric_chunks(
                question,
                dataset_ids={"cloud_vendor_database"},
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()

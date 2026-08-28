from __future__ import annotations

import csv
import json
import subprocess
import sys
import unittest
from pathlib import Path

import agent
import cmhk.agent.rag as rag_llm


ROOT = Path(__file__).resolve().parents[1]
DATASET_ID = "local_hk_operator_operating_metrics_2016_2025"
DATASET = ROOT / "agent_knowledge" / DATASET_ID


class LocalHKOperatorOperatingDatabaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_local_hk_operator_operating_database.py")],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        with (DATASET / "annual_metrics.csv").open("r", encoding="utf-8-sig", newline="") as handle:
            cls.rows = list(csv.DictReader(handle))

    def row(self, operator_id: str, year: int, metric_key: str) -> dict[str, str]:
        matches = [
            row for row in self.rows
            if row["operator_id"] == operator_id
            and int(row["year"]) == year
            and row["metric_key"] == metric_key
        ]
        self.assertEqual(len(matches), 1, (operator_id, year, metric_key))
        return matches[0]

    def test_manifest_and_quality_gate(self) -> None:
        manifest = json.loads((DATASET / "manifest.json").read_text(encoding="utf-8"))
        quality = json.loads((DATASET / "quality_audit.json").read_text(encoding="utf-8"))
        payload = json.loads((DATASET / "annual_metrics.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["id"], DATASET_ID)
        self.assertEqual(set(payload["operators"]), {"cmhk", "hkt", "three_hk", "smartone", "hkbn", "hgc", "icable"})
        self.assertEqual(quality["status"], "pass")
        self.assertEqual(quality["duplicate_key_count"], 0)
        self.assertEqual(quality["invalid_source_ids"], [])
        self.assertGreaterEqual(quality["available_value_rows"], 160)

    def test_known_official_values_and_period_ends(self) -> None:
        self.assertEqual(self.row("hkt", 2025, "5g_customers")["official_value"], "2.096")
        self.assertEqual(self.row("three_hk", 2025, "5g_penetration")["official_value"], "62")
        self.assertEqual(self.row("smartone", 2022, "mobile_postpaid_exit_arpu")["official_value"], "213")
        self.assertEqual(self.row("smartone", 2022, "mobile_postpaid_exit_arpu")["period_end"], "2022-06-30")
        self.assertEqual(self.row("hkbn", 2025, "consumer_broadband_customers")["official_value"], "0.907")
        self.assertEqual(self.row("hkbn", 2025, "consumer_broadband_customers")["period_end"], "2025-08-31")
        self.assertEqual(self.row("icable", 2022, "pay_tv_customers")["official_value"], "0.662")
        self.assertEqual(self.row("three_hk", 2022, "5g_base_station_expansion")["official_value"], "50")
        self.assertEqual(self.row("three_hk", 2022, "5g_base_station_expansion")["comparator"], ">=")

    def test_unfilled_gaps_remain_missing_and_normalized_disclosures_are_labelled(self) -> None:
        hgc = self.row("hgc", 2025, "mobile_postpaid_arpu")
        self.assertEqual(hgc["official_value"], "")
        self.assertEqual(hgc["verification_status"], "source_gap_confirmed")
        self.assertIn("not estimated", hgc["quality_note"])
        smartone = self.row("smartone", 2025, "5g_penetration")
        self.assertEqual(smartone["official_value"], "40")
        self.assertEqual(smartone["verification_status"], "official_qualitative_continuity_normalized")
        self.assertIn("broadly stable", smartone["quality_note"])
        hkt_traffic = self.row("hkt", 2025, "annual_mobile_data_traffic")
        self.assertEqual(hkt_traffic["official_value"], "")
        self.assertEqual(hkt_traffic["verification_status"], "source_gap_confirmed")

    def test_scope_breaks_are_machine_readable(self) -> None:
        conflicts = json.loads((DATASET / "conflicts_and_scope_breaks.json").read_text(encoding="utf-8"))["items"]
        kinds = {(item["operator_id"], item["type"]) for item in conflicts}
        self.assertIn(("three_hk", "scope_change_and_restatement"), kinds)
        self.assertIn(("smartone", "fiscal_year_difference"), kinds)
        self.assertIn(("hgc", "private_company_disclosure_gap"), kinds)
        self.assertIn(("icable", "service_discontinuation"), kinds)

    def test_xiaojing_exact_retrieval_and_dataset_isolation(self) -> None:
        chunks = rag_llm._local_hk_operator_exact_metric_chunks(
            "HKT 2025年5G客戶數是多少？",
            dataset_ids={DATASET_ID},
        )
        self.assertEqual(len(chunks), 1)
        self.assertIn("official_value=2.096 million_customers", chunks[0]["text"])
        self.assertIn("period_end=2025-12-31", chunks[0]["text"])

    def test_xiaojing_reads_full_three_operator_ten_year_series_with_provenance(self) -> None:
        chunks = rag_llm._local_hk_operator_exact_metric_chunks(
            "请列出3HK、HKT、SmarTone 2016至2025年5G渗透率",
            dataset_ids={DATASET_ID},
        )
        self.assertEqual(len(chunks), 30)
        text = "\n".join(item["text"] for item in chunks)
        self.assertIn("operator=3HK", text)
        self.assertIn("operator=HKT", text)
        self.assertIn("operator=SmarTone", text)
        self.assertIn("verification_status=operational_zero_from_precommercial_timeline", text)
        self.assertIn("verification_status=official_derived_from_disclosed_growth_bridge", text)
        self.assertIn("verification_status=official_range_normalized", text)
        self.assertIn("verification_status=official_qualitative_continuity_normalized", text)

        churn_chunks = rag_llm._local_hk_operator_exact_metric_chunks(
            "请列出3HK、HKT、SmarTone 2016至2025年移动后付月流失率",
            dataset_ids={DATASET_ID},
        )
        self.assertEqual(len(churn_chunks), 30)
        churn_text = "\n".join(item["text"] for item in churn_chunks)
        self.assertIn("operator=SmarTone", churn_text)
        self.assertIn("period=FY2025", churn_text)
        self.assertIn("未披露（source_gap_confirmed）", churn_text)

        postpaid_chunks = rag_llm._local_hk_operator_exact_metric_chunks(
            "HKT和3HK的FY2025后付费用户数分别是多少？",
            dataset_ids={DATASET_ID},
        )
        postpaid_text = "\n".join(chunk["text"] for chunk in postpaid_chunks)
        self.assertEqual(len(postpaid_chunks), 2)
        self.assertIn("operator=HKT", postpaid_text)
        self.assertIn("official_value=3.494 million_customers", postpaid_text)
        self.assertIn("operator=3HK", postpaid_text)
        self.assertIn("official_value=1.289 million_customers", postpaid_text)
        self.assertNotIn("未披露（source_gap_confirmed）", postpaid_text)

        gap_chunks = rag_llm._local_hk_operator_exact_metric_chunks(
            "HGC 2025年ARPU是多少？",
            dataset_ids={DATASET_ID},
        )
        self.assertEqual(len(gap_chunks), 1)
        self.assertIn("未披露（source_gap_confirmed）", gap_chunks[0]["text"])
        self.assertIn("不能當作0或推測", gap_chunks[0]["text"])

        isolated = rag_llm._local_hk_operator_exact_metric_chunks(
            "HKT 2025年5G客戶數是多少？",
            dataset_ids={"global_top5_operators_2016_2025"},
        )
        self.assertEqual(isolated, [])

        traffic_chunks = rag_llm._local_hk_operator_exact_metric_chunks(
            "HKT 2025年年度移動數據流量是多少？",
            dataset_ids={DATASET_ID},
        )
        self.assertEqual(len(traffic_chunks), 1)
        self.assertIn("metric_key=annual_mobile_data_traffic", traffic_chunks[0]["text"])
        self.assertIn("未披露（source_gap_confirmed）", traffic_chunks[0]["text"])

    def test_aliases_and_metric_disambiguation(self) -> None:
        chunks = rag_llm._local_hk_operator_exact_metric_chunks(
            "香港寬頻HKBN FY2025住宅ARPU和ARPH",
            dataset_ids={DATASET_ID},
        )
        texts = "\n".join(chunk["text"] for chunk in chunks)
        self.assertIn("metric_key=residential_arpu", texts)
        self.assertIn("official_value=186 HKD_per_month", texts)
        self.assertIn("metric_key=residential_arph", texts)
        self.assertIn("official_value=217 HKD_per_household_month", texts)

    def test_agent_preserves_original_exact_metric_when_tool_query_drifts(self) -> None:
        dataset_token = agent.SELECTED_DATASET_IDS.set({DATASET_ID})
        request_token = agent.CURRENT_USER_REQUEST.set(
            "3HK 2022年5G基站扩展幅度是多少？这是绝对基站数还是相对增长？"
        )
        try:
            result = agent._search_local_reports_only("3HK 2022年基站数和资本开支", 4)
        finally:
            agent.CURRENT_USER_REQUEST.reset(request_token)
            agent.SELECTED_DATASET_IDS.reset(dataset_token)
        first_source = result.split("[\u6765\u6e90 2:", 1)[0]
        self.assertIn("metric_key=5g_base_station_expansion", first_source)
        self.assertIn("official_value=50 percent", first_source)
        self.assertIn("local_hk_operator_operating_metrics_2016_2025/annual_metrics.csv", first_source)


if __name__ == "__main__":
    unittest.main()

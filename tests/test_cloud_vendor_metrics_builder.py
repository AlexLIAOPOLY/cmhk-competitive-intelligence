from __future__ import annotations

import json
import unittest

from scripts import build_cloud_vendor_metrics_knowledge as builder
from cmhk.agent import rag as rag_llm


class CloudVendorMetricsBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.vendors = [json.loads(json.dumps(item)) for item in builder.VENDORS]
        builder._extend_from_quarterly_history(cls.vendors)
        cls.vendors = [builder.enrich_vendor(item) for item in cls.vendors]
        cls.rows = builder.flatten_rows(cls.vendors)

    def test_table_uses_aligned_2016_2025_window(self):
        self.assertEqual(
            sorted({row["fiscal_year"] for row in self.rows}),
            [str(year) for year in range(2016, 2026)],
        )
        aws_revenue = [
            row for row in self.rows
            if row["vendor"] == "AWS" and row["metric_key"] == "cloud_revenue" and row["official_value"] != ""
        ]
        self.assertEqual(len(aws_revenue), 10)

    def test_every_admitted_value_has_official_sources_and_an_evidence_grade(self):
        for row in self.rows:
            if row["official_value"] == "":
                continue
            sources = json.loads(row["verification_sources"])
            self.assertGreaterEqual(row["verification_count"], 1)
            self.assertEqual(row["verification_count"], len({source["url"] for source in sources}))
            self.assertNotEqual(row["verification_status"], "needs_official_row_crosscheck")
            self.assertTrue(all(source["type"].startswith("official_") for source in sources))

    def test_missing_cells_are_explicit_and_never_numeric_zero(self):
        for row in self.rows:
            if row["official_value"] != "":
                continue
            self.assertIn(row["verification_status"], {"source_gap_confirmed", "scope_not_comparable"})
            self.assertTrue(row["gap_reason_code"])
            self.assertTrue(row["gap_reason"])
            self.assertNotEqual(row["value"], 0)

    def test_china_mobile_cloud_uses_disclosed_values_and_preserves_2025_gap(self):
        rows = {
            (row["fiscal_year"], row["metric_key"]): row
            for row in self.rows
            if row["vendor"] == "China Mobile Cloud"
        }

        self.assertEqual(rows[("2023", "cloud_revenue")]["official_value"], 83349)
        self.assertEqual(rows[("2024", "cloud_revenue")]["official_value"], 100400)
        self.assertEqual(rows[("2024", "revenue_yoy")]["official_value"], 20.4)
        self.assertEqual(rows[("2023", "group_capex")]["official_value"], 180300)
        self.assertEqual(rows[("2024", "group_capex")]["official_value"], 164000)
        self.assertEqual(rows[("2025", "cloud_revenue")]["verification_status"], "source_gap_confirmed")
        self.assertEqual(rows[("2025", "group_capex")]["verification_status"], "source_gap_confirmed")
        self.assertEqual(rows[("2025", "cloud_operating_profit")]["verification_status"], "source_gap_confirmed")

    def test_every_china_mobile_row_binds_three_distinct_official_documents(self):
        for row in self.rows:
            if row["vendor"] != "China Mobile Cloud":
                continue
            sources = json.loads(row["verification_sources"])
            self.assertEqual(row["verification_count"], 3)
            self.assertEqual(row["verification_method"], "three_distinct_official_documents")
            self.assertEqual(len({source["id"] for source in sources}), 3)
            self.assertEqual(len({source["url"] for source in sources}), 3)
            self.assertTrue(all(source["type"].startswith("official_") for source in sources))

    def test_existing_cloud_vendor_values_remain_present(self):
        expected = {
            ("AWS", "2025", "cloud_revenue"): 128725,
            ("Google Cloud", "2025", "cloud_revenue"): 58705,
            ("Alibaba Cloud", "2025", "cloud_revenue"): 118028,
            ("Microsoft Azure / Intelligent Cloud", "2025", "cloud_revenue"): 106265,
            ("Oracle Cloud", "2025", "cloud_revenue"): 24506,
        }
        actual = {
            (row["vendor"], row["fiscal_year"], row["metric_key"]): row["official_value"]
            for row in self.rows
        }
        for key, value in expected.items():
            self.assertEqual(actual[key], value)

    def test_group_capex_uses_metric_specific_three_document_evidence(self):
        expected = {
            ("Google Cloud", "2023"): 32251,
            ("Google Cloud", "2024"): 52535,
            ("Microsoft Azure / Intelligent Cloud", "2023"): 28107,
            ("Microsoft Azure / Intelligent Cloud", "2024"): 44477,
            ("Oracle Cloud", "2023"): 8695,
            ("Oracle Cloud", "2024"): 6866,
        }
        rows = {
            (row["vendor"], row["fiscal_year"]): row
            for row in self.rows
            if row["metric_key"] == "group_capex"
        }
        for key, value in expected.items():
            row = rows[key]
            sources = json.loads(row["verification_sources"])
            self.assertEqual(row["official_value"], value)
            self.assertEqual(row["verification_count"], 3)
            self.assertEqual(row["verification_method"], "three_distinct_official_documents")
            self.assertEqual(len({source["url"] for source in sources}), 3)

        for vendor in {
            "Google Cloud",
            "Microsoft Azure / Intelligent Cloud",
            "Oracle Cloud",
        }:
            self.assertEqual(rows[(vendor, "2025")]["verification_status"], "source_gap_confirmed")

    def test_xiaojing_ai_retrieves_exact_alibaba_legacy_rows(self):
        chunks = rag_llm._cloud_vendor_exact_metric_chunks(
            "Alibaba Cloud FY2018云计算分部收入和调整后EBITA是多少？",
            dataset_ids={"cloud_vendor_metrics_2026-06-17"},
        )
        combined = "\n".join(chunk["text"] for chunk in chunks)
        self.assertIn("vendor=Alibaba Cloud; period=FY2018", combined)
        self.assertIn("metric_key=legacy_cloud_segment_revenue_then_reported", combined)
        self.assertIn("official_value=13390 RMB millions", combined)
        self.assertIn("metric_key=legacy_cloud_adjusted_ebita_then_reported", combined)
        self.assertIn("official_value=-799 RMB millions", combined)

    def test_xiaojing_ai_returns_governed_cloud_gap_not_adjacent_vendor(self):
        chunks = rag_llm.retrieve_context(
            "Huawei Cloud FY2020云收入是否披露？",
            limit=3,
            dataset_ids={"cloud_vendor_metrics_2026-06-17"},
        )
        self.assertTrue(chunks)
        self.assertIn("vendor=Huawei Cloud / Cloud Computing; period=FY2020", chunks[0]["text"])
        self.assertIn("未披露（source_gap_confirmed）", chunks[0]["text"])
        self.assertIn("不得当作0", chunks[0]["text"])

    def test_cloud_exact_retrieval_respects_selected_database(self):
        self.assertEqual(
            rag_llm._cloud_vendor_exact_metric_chunks(
                "AWS FY2025云收入",
                dataset_ids={"global_top5_operators_2016_2025"},
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()

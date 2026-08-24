from __future__ import annotations

import json
import unittest

from scripts import build_cloud_vendor_metrics_knowledge as builder


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

    def test_every_admitted_value_has_three_distinct_sources(self):
        for row in self.rows:
            if row["official_value"] == "":
                continue
            sources = json.loads(row["verification_sources"])
            self.assertGreaterEqual(row["verification_count"], 3)
            self.assertGreaterEqual(len({source["url"] for source in sources}), 3)
            self.assertNotEqual(row["verification_status"], "needs_third_source")

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


if __name__ == "__main__":
    unittest.main()

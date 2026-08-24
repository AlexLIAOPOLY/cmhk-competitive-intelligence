import unittest

from cmhk.agent.rag import _quarterly_exact_metric_chunks
from scripts import audit_cross_database_disclosures as audit


class DisclosureCatalogTests(unittest.TestCase):
    def test_cloud_aliases_only_count_cloud_category_rows(self) -> None:
        all_rows = {config["id"]: [] for config in audit.DATASETS}
        all_rows[audit.LATEST_QUARTERLY.name] = [
            {"subject": "AWS", "category": "cloud", "metric_key": "operating_income", "official_value": "9421"},
            {"subject": "Carrier Example", "category": "carrier", "metric_key": "operating_income", "official_value": "123"},
            {"subject": "Google Cloud", "category": "cloud", "metric_key": "revenue", "official_value": "9574"},
            {
                "subject": "Microsoft Azure / Intelligent Cloud",
                "category": "cloud",
                "metric_key": "azure_and_other_cloud_services_growth_yoy",
                "official_value": "31",
            },
        ]

        rows = audit.disclosure_catalog(all_rows)
        quarterly = {
            row["metric_key"]: row
            for row in rows
            if row["dataset_id"] == audit.LATEST_QUARTERLY.name
        }

        self.assertEqual(quarterly["cloud_operating_income"]["available_value_rows"], 1)
        self.assertEqual(quarterly["cloud_operating_income"]["subjects_with_values"], 1)
        self.assertEqual(quarterly["cloud_revenue"]["available_value_rows"], 1)
        self.assertEqual(quarterly["cloud_revenue_growth"]["available_value_rows"], 1)

    def test_chinese_specific_quarter_returns_exact_cloud_operating_income(self) -> None:
        chunks = _quarterly_exact_metric_chunks(
            "AWS 2024年第一季度云经营利润是多少？",
            {audit.LATEST_QUARTERLY.name},
        )

        self.assertEqual(len(chunks), 1)
        self.assertIn("精确季度指标行：subject=AWS; period=Q1 2024", chunks[0]["text"])
        self.assertIn("metric_key=operating_income", chunks[0]["text"])
        self.assertIn("official_value=9421 millions USD", chunks[0]["text"])


if __name__ == "__main__":
    unittest.main()

import copy
import unittest

from cmhk.intelligence import executive as e


class AnnualSourceTests(unittest.TestCase):
    def row(self, period, value, url, label):
        return {"subject": "Example", "metric_key": "net_income", "period": period,
                "value": value, "official_value": value, "unit": "millions HKD",
                "verification_status": "official_match", "official_source_url": url,
                "official_source_label": label,
                "verification_sources": [{"url": url, "label": label}]}

    def test_annual_primary_replaces_first_half_url_without_changing_values(self):
        rows = [self.row("H1 2025", 2070, "https://official.test/interim", "Example 2025 Interim Report"),
                self.row("H2 2025", 3216, "https://official.test/annual", "Example 2025 Annual Report")]
        original = copy.deepcopy(rows)
        annual = e._annual_financial_value(rows, "Example", "net_income", 2025)
        self.assertEqual(annual["value"], 5286)
        self.assertEqual(annual["period"], "FY2025")
        self.assertEqual(annual["source_url"], "https://official.test/annual")
        self.assertEqual(annual["source_url_aliases"], ["https://official.test/interim"])
        self.assertEqual(annual["source_urls"], ["https://official.test/interim", "https://official.test/annual"])
        self.assertEqual([x["value"] for x in annual["annual_source_components"]], [2070, 3216])
        self.assertEqual(rows, original)

    def test_does_not_blindly_choose_second_url_or_another_year(self):
        for label in ("Example 2025 Interim Report", "Example 2024 Annual Report", "Example annual report"):
            rows = [self.row("H1 2025", 2, "https://official.test/h1", "Example 2025 Interim Report"),
                    self.row("H2 2025", 3, "https://official.test/h2", label)]
            with self.subTest(label=label):
                annual = e._annual_financial_value(rows, "Example", "net_income", 2025)
                self.assertEqual(annual["source_url"], "https://official.test/h1")
                self.assertNotIn("source_url_aliases", annual)

    def test_four_quarters_select_full_year_disclosure_and_keep_all_components(self):
        rows = [self.row(f"Q{i} 2025", i, f"https://official.test/q{i}",
                        "Example 2025 Annual Results Announcement" if i == 4 else f"Example Q{i} 2025 Results") for i in range(1, 5)]
        annual = e._annual_financial_value(rows, "Example", "net_income", 2025)
        self.assertEqual(annual["value"], 10)
        self.assertEqual(annual["source_url"], "https://official.test/q4")
        self.assertEqual(len(annual["annual_source_components"]), 4)

    def test_chinese_annual_report_label_supported(self):
        rows = [self.row("H1 2025", 2, "https://official.test/h1", "示例2025年中报"),
                self.row("H2 2025", 3, "https://official.test/full", "示例2025年年度业绩")]
        self.assertEqual(e._annual_financial_value(rows, "Example", "net_income", 2025)["source_url"], "https://official.test/full")

    def test_metadata_survives_reader_evidence_for_explicit_migration(self):
        rows = [self.row("H1 2025", 2, "https://official.test/h1", "Example 2025 Interim Report"),
                self.row("H2 2025", 3, "https://official.test/full", "Example 2025 Annual Report")]
        annual = e._annual_financial_value(rows, "Example", "net_income", 2025)
        item = e._financial_item("Example", annual, "净利润", "亿元", "")
        evidence = e._analysis_evidence_snapshot([{"id": "mainland", "focuses": [{"id": "net_profit", "items": [item]}]}])
        projected = evidence["domains"][0]["focuses"][0]["items"][0]
        for field in ("source_url_aliases", "source_urls", "annual_source_components"):
            self.assertEqual(projected[field], annual[field])
        self.assertEqual(projected["source_url"], "https://official.test/full")


if __name__ == "__main__":
    unittest.main()

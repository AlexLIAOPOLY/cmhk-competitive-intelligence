from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import cmhk.data.local_financial_results as finance


HKT_2026_TEXT = """
2026 Interim Results
5G customer base expanded by 16% to 2.2 million.
Total revenue increased by 8% to HK$18,685 million.
Total EBITDA grew by 3% to HK$6,586 million.
Profit attributable to holders of Share Stapled Units increased by 4% to HK$2,153 million.
Interim distribution per Share Stapled Unit of 34.80 HK cents.
CAPITAL EXPENDITURE Capital expenditure including capitalised interest for the six months ended
30 June 2026 was HK$1,042 million.
"""


class LocalFinancialResultsTests(unittest.TestCase):
    def test_hkex_thousands_table_and_interim_nil_dividend_are_normalized(self) -> None:
        text = """
        INTERIM RESULTS FOR THE SIX MONTHS ENDED 30 JUNE 2026
        HK$'000    2026    2025
        Revenue 244,420 277,511
        Loss for the period (276,514) (216,816)
        During the six months ended 30 June 2026, capital expenditure on property,
        plant and equipment amounted to approximately HK$10 million.
        The Board does not recommend the payment of any interim dividend.
        """

        metrics = {item["metric_key"]: item["value"] for item in finance._extract_metrics(text)}

        self.assertEqual(metrics["revenue"], "HK$244.42 million")
        self.assertEqual(metrics["net_profit"], "-HK$276.514 million")
        self.assertEqual(metrics["capital_expenditure"], "HK$10 million")
        self.assertEqual(metrics["dividend"], "HK$Nil")

    def test_hkex_notice_number_prefix_is_the_publication_date(self) -> None:
        self.assertEqual(
            finance._publication_date(
                {
                    "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0327/2026032703354.pdf",
                    "text": "for the year ended 31 December 2025",
                }
            ),
            "2026-03-27",
        )

    def test_icable_hkex_results_announcement_is_an_official_report(self) -> None:
        url = "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0327/2026032703354.pdf"
        self.assertTrue(
            finance._is_official_report(
                17,
                {
                    "url": url,
                    "final_url": url,
                    "status": 200,
                    "content_type": "application/pdf",
                    "title": "FINAL RESULTS ANNOUNCEMENT FOR THE YEAR ENDED 31 DECEMBER 2025",
                    "text_sample": "i-CABLE Communications Limited annual results",
                },
            )
        )

    def test_report_title_year_outranks_later_publication_year_in_url(self) -> None:
        period, report_type, rank = finance._report_period(
            {
                "url": "https://www.hkt.com/api-service/assets/e-2026.02.09_(2025_Annual_Results_Announcement).pdf",
                "title": "2025 Annual Results Announcement",
                "text_sample": "Annual results for the year ended 31 December 2025.",
            }
        )

        self.assertEqual((period, report_type, rank), ("FY 2025", "annual", (2025, 4)))

    def test_report_filename_year_outranks_historical_fy_in_body(self) -> None:
        period, report_type, rank = finance._report_period(
            {
                "url": "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_AnnualReport_2025.pdf",
                "title": "PDF extracted by pdftotext",
                "text_sample": "Five-year summary FY22 FY23 FY24. Annual report for the year ended 31 August 2025.",
            }
        )

        self.assertEqual((period, report_type, rank), ("FY 2025", "annual", (2025, 4)))

    def test_official_announcement_is_structured_with_next_day_due_time(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            results = root / "results"
            results.mkdir()
            database = root / "cmhk.data.local_financial_results.json"
            (results / "row_2.json").write_text(
                json.dumps(
                    {
                        "row": 2,
                        "fetched_at_hkt": "2026-07-30T03:10:00+08:00",
                        "raw_records": [
                            {
                                "url": "https://www.hkt.com/api-service/assets/e-2026.07.29_(2026_Interim_Results_Announcement).pdf",
                                "final_url": "https://www.hkt.com/api-service/assets/e-2026.07.29_(2026_Interim_Results_Announcement).pdf",
                                "status": 200,
                                "content_type": "application/pdf",
                                "title": "PDF extracted by pdftotext",
                                "content_hash": "hkt-2026",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.object(finance, "RESULTS_DIR", results),
                mock.patch.object(finance, "DATABASE_PATH", database),
                mock.patch.object(finance, "_record_text", return_value=HKT_2026_TEXT),
            ):
                payload = finance.rebuild_local_financial_database(
                    rows=[2],
                    now=datetime(2026, 7, 30, 3, 10, tzinfo=finance.HKT),
                )

            report = payload["reports"][0]
            self.assertTrue(payload["quality"]["ok"])
            self.assertEqual(report["period"], "H1 2026")
            self.assertEqual(report["publication_date"], "2026-07-29")
            self.assertEqual(report["due_at_hkt"], "2026-07-30T03:00:00+08:00")
            values = {item["metric_key"]: item["value"] for item in report["metrics"]}
            self.assertEqual(values["revenue"], "HK$18,685 million")
            self.assertEqual(values["ebitda"], "HK$6,586 million")
            self.assertEqual(values["net_profit"], "HK$2,153 million")
            self.assertEqual(values["capital_expenditure"], "HK$1,042 million")
            self.assertEqual(values["dividend"], "34.80 HK cents")
            self.assertEqual(values["5g_customers"], "2.2 million")
            self.assertTrue(database.exists())

    def test_missing_official_report_fails_closed_and_preserves_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            results = root / "results"
            results.mkdir()
            database = root / "cmhk.data.local_financial_results.json"
            database.write_text('{"reports": [{"row": 2, "period": "FY 2025"}]}', encoding="utf-8")
            (results / "row_2.json").write_text('{"row": 2, "raw_records": []}', encoding="utf-8")
            before = database.read_text(encoding="utf-8")
            with (
                mock.patch.object(finance, "RESULTS_DIR", results),
                mock.patch.object(finance, "DATABASE_PATH", database),
            ):
                payload = finance.rebuild_local_financial_database(rows=[2])

            self.assertFalse(payload["quality"]["ok"])
            self.assertIn("未发现可读取的官方财报", payload["quality"]["failures"][0])
            self.assertEqual(database.read_text(encoding="utf-8"), before)

    def test_newer_discovered_report_that_cannot_be_read_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            results = root / "results"
            results.mkdir()
            database = root / "cmhk.data.local_financial_results.json"
            database.write_text('{"reports": [{"row": 2, "period": "H1 2026"}]}', encoding="utf-8")
            old_url = "https://www.hkt.com/api-service/assets/2026_interim_results.pdf"
            new_url = "https://www.hkt.com/api-service/assets/2026_annual_results.pdf"
            (results / "row_2.json").write_text(
                json.dumps(
                    {
                        "row": 2,
                        "raw_records": [
                            {
                                "url": old_url,
                                "final_url": old_url,
                                "status": 200,
                                "content_type": "application/pdf",
                                "title": "2026 Interim Results",
                                "text_sample": HKT_2026_TEXT,
                            },
                            {
                                "url": "https://www.hkt.com/investor-relations/results",
                                "final_url": "https://www.hkt.com/investor-relations/results",
                                "status": 200,
                                "content_type": "text/html",
                                "title": "Results",
                                "discovered_report_links": [
                                    {"url": new_url, "title": "2026 Annual Results"}
                                ],
                            },
                            {
                                "url": new_url,
                                "final_url": new_url,
                                "status": 503,
                                "content_type": "application/pdf",
                                "title": "2026 Annual Results",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            before = database.read_text(encoding="utf-8")
            with (
                mock.patch.object(finance, "RESULTS_DIR", results),
                mock.patch.object(finance, "DATABASE_PATH", database),
            ):
                payload = finance.rebuild_local_financial_database(rows=[2])

            self.assertFalse(payload["quality"]["ok"])
            self.assertEqual(payload["last_check"][0]["status"], "newer_official_report_unavailable")
            self.assertIn("已发现更新一期官方财报 FY 2026", payload["quality"]["failures"][0])
            self.assertEqual(database.read_text(encoding="utf-8"), before)

    def test_older_extracted_report_cannot_replace_newer_database_period(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            results = root / "results"
            results.mkdir()
            database = root / "cmhk.data.local_financial_results.json"
            database.write_text(
                json.dumps({"reports": [{"row": 11, "company": "HKBN", "period": "H1 2026", "metrics": []}]}),
                encoding="utf-8",
            )
            annual_url = "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_AnnualReport_2025.pdf"
            (results / "row_11.json").write_text(
                json.dumps(
                    {
                        "row": 11,
                        "raw_records": [
                            {
                                "url": annual_url,
                                "final_url": annual_url,
                                "status": 200,
                                "content_type": "application/pdf",
                                "title": "PDF extracted by pdftotext",
                                "text_sample": "Annual Report 2025. Total revenue was HK$6,000 million. EBITDA was HK$1,000 million.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.object(finance, "RESULTS_DIR", results),
                mock.patch.object(finance, "DATABASE_PATH", database),
            ):
                payload = finance.rebuild_local_financial_database(rows=[11])

            self.assertTrue(payload["quality"]["ok"])
            self.assertEqual(payload["reports"][0]["period"], "H1 2026")
            self.assertEqual(payload["last_check"][0]["status"], "stale_official_report_ignored")


if __name__ == "__main__":
    unittest.main()

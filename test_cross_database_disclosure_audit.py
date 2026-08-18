from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rag_llm import _strict_source_document_count, _strict_three_source_row_text, retrieve_context
from source_document_identity import is_derived_value


class StrictSourceDocumentCountTest(unittest.TestCase):
    def test_same_document_sections_count_once(self) -> None:
        row = {
            "official_source_url": "https://example.com/report.pdf#page=1",
            "verification_sources": json.dumps(
                [
                    {"url": "https://example.com/report.pdf#page=3"},
                    {"url": "https://example.com/report.pdf#page=8"},
                    {"url": "https://example.com/report.pdf"},
                ]
            ),
        }
        self.assertEqual(_strict_source_document_count(row), 1)

    def test_three_distinct_documents_pass(self) -> None:
        row = {
            "official_source_url": "https://issuer.example/report.pdf",
            "verification_sources": json.dumps(
                [
                    {"url": "https://issuer.example/results.pdf"},
                    {"url": "https://exchange.example/filing.pdf"},
                ]
            ),
        }
        self.assertEqual(_strict_source_document_count(row), 3)

    def test_source_ids_resolve_through_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sources.json"
            path.write_text(
                json.dumps(
                    {
                        "sources": [
                            {"source_id": "a", "url": "https://a.example/report"},
                            {"source_id": "b", "url": "https://b.example/report"},
                            {"source_id": "c", "url": "https://c.example/report"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            row = {"verification_sources": json.dumps(["a", "b", "c"])}
            self.assertEqual(_strict_source_document_count(row, source_registry_path=path), 3)

    def test_mirror_urls_with_same_document_identity_count_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sources.json"
            path.write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "source_id": "issuer-copy",
                                "source_document_id": "annual-report-2025",
                                "url": "https://issuer.example/annual.pdf",
                            },
                            {
                                "source_id": "exchange-copy",
                                "source_document_id": "annual-report-2025",
                                "url": "https://exchange.example/annual.pdf",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            row = {
                "primary_source_url": "https://issuer.example/annual.pdf",
                "verification_sources": json.dumps(["issuer-copy", "exchange-copy"]),
            }
            self.assertEqual(_strict_source_document_count(row, source_registry_path=path), 1)

    def test_split_sections_and_exchange_mirror_of_one_report_count_once(self) -> None:
        row = {
            "official_source_url": "https://issuer.example/ar2025/highlights.pdf",
            "verification_sources": json.dumps(
                [
                    {
                        "label": "Example 2025 Annual Report - Financial Highlights",
                        "url": "https://issuer.example/ar2025/highlights.pdf",
                    },
                    {
                        "label": "Example 2025 Annual Report - Cash Flows",
                        "url": "https://issuer.example/ar2025/cashflows.pdf",
                    },
                    {
                        "label": "Example 2025 Annual Report - HKEX",
                        "url": "https://exchange.example/2025-annual.pdf",
                    },
                ]
            ),
        }
        self.assertEqual(_strict_source_document_count(row), 1)

    def test_a_share_and_h_share_annual_reports_remain_distinct(self) -> None:
        row = {
            "verification_sources": json.dumps(
                [
                    {
                        "label": "Example 2025 H-share Annual Report",
                        "url": "https://issuer.example/h-annual.pdf",
                    },
                    {
                        "label": "Example 2025 A-share Annual Report",
                        "url": "https://exchange.example/a-annual.pdf",
                    },
                ]
            )
        }
        self.assertEqual(_strict_source_document_count(row), 2)

    def test_arithmetic_reconciliation_is_derived_even_with_official_status(self) -> None:
        row = {
            "official_value": "3232",
            "verification_status": "official_only",
            "verification_method": "official_full_year_minus_h1_reconciliation",
            "official_evidence": "2025年报全年5,448减1H 2,216，复算H2为3,232。",
        }
        self.assertTrue(is_derived_value(row))
        self.assertIn(
            "triple_source_status=derived_not_directly_disclosed",
            _strict_three_source_row_text(row, 4),
        )

    def test_plain_crosscheck_does_not_make_a_direct_value_derived(self) -> None:
        row = {
            "official_value": "100",
            "verification_status": "official_match",
            "verification_method": "official_crosscheck",
            "verification_note": "Annual report and results announcement agree.",
        }
        self.assertFalse(is_derived_value(row))

    def test_chinese_half_year_question_returns_exact_hkt_row_with_strict_count(self) -> None:
        chunks = retrieve_context(
            "HKT 2025年上半年收入是多少？有几份独立来源文档？",
            limit=6,
            dataset_ids={"quarterly_competitor_metrics_2026-08-18"},
        )
        combined = "\n".join(chunk["text"] for chunk in chunks)
        self.assertIn("subject=HKT / csl / 1O1O; period=H1 2025; metric_key=revenue", combined)
        self.assertIn("official_value=17322 millions HKD", combined)
        self.assertIn("distinct_source_document_count=4", combined)
        self.assertIn("triple_source_status=three_distinct_sources_verified", combined)
        self.assertNotIn("period=H1 2016; metric_key=revenue", combined)

    def test_quarterly_exact_context_exposes_strict_status(self) -> None:
        chunks = retrieve_context(
            "3HK H1 2021资本开支",
            limit=3,
            dataset_ids={"quarterly_competitor_metrics_2026-08-18"},
        )
        exact = next(chunk["text"] for chunk in chunks if "精确季度指标行" in chunk["text"])
        self.assertIn("verification_count=3", exact)
        self.assertIn("distinct_source_document_count=1", exact)
        self.assertIn("triple_source_status=below_three_source_threshold", exact)

    def test_hthkh_h2_derived_revenue_is_never_three_source_certified(self) -> None:
        chunks = retrieve_context(
            "3HK 2025年下半年收入是多少？是否通过三来源核验？",
            limit=6,
            dataset_ids={"quarterly_competitor_metrics_2026-08-18"},
        )
        exact = next(chunk["text"] for chunk in chunks if "period=H2 2025; metric_key=revenue" in chunk["text"])
        self.assertIn("official_value=3232 millions HKD", exact)
        self.assertIn("triple_source_status=derived_not_directly_disclosed", exact)


if __name__ == "__main__":
    unittest.main()

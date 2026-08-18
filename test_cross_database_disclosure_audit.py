from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rag_llm import _strict_source_document_count, retrieve_context


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

    def test_quarterly_exact_context_exposes_strict_status(self) -> None:
        chunks = retrieve_context(
            "3HK H1 2021资本开支",
            limit=3,
            dataset_ids={"quarterly_competitor_metrics_2026-06-18"},
        )
        exact = next(chunk["text"] for chunk in chunks if "精确季度指标行" in chunk["text"])
        self.assertIn("verification_count=3", exact)
        self.assertIn("distinct_source_document_count=1", exact)
        self.assertIn("triple_source_status=below_three_source_threshold", exact)


if __name__ == "__main__":
    unittest.main()

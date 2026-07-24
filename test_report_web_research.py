from __future__ import annotations

import unittest

from report_web_research import run_web_research


class ReportWebResearchTests(unittest.TestCase):
    def test_parallel_research_preserves_request_order_and_metadata(self) -> None:
        def search_client(query, limit):
            return {
                "query": query,
                "provider": "unit",
                "results": [
                    {
                        "title": f"{query} result",
                        "url": f"https://example.com/{query[-1]}",
                        "snippet": f"limit={limit}",
                    }
                ],
                "error": "",
            }

        rows = run_web_research(
            [
                {"id": "A", "query": "query-1"},
                {"id": "B", "query": "query-2"},
            ],
            search_client=search_client,
            limit=3,
            workers=2,
        )

        self.assertEqual([row["id"] for row in rows], ["A", "B"])
        self.assertEqual([row["provider"] for row in rows], ["unit", "unit"])
        self.assertEqual(rows[1]["results"][0]["snippet"], "limit=3")


if __name__ == "__main__":
    unittest.main()

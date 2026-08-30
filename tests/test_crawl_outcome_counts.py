from __future__ import annotations

import unittest

from crawl import EXTRA_CANDIDATES, row_outcome_counts


class CrawlOutcomeCountTests(unittest.TestCase):
    def test_all_duplicate_key_source_candidates_remain_covered(self) -> None:
        self.assertIn(
            "https://www.policyaddress.gov.hk/2025/en/index.html",
            EXTRA_CANDIDATES[24],
        )
        self.assertIn("https://www.ofca.gov.hk/en/home/index.html", EXTRA_CANDIDATES[28])
        self.assertIn("https://www.enisa.europa.eu/news", EXTRA_CANDIDATES[28])
        self.assertIn(
            "https://www.imda.gov.sg/regulations-and-licensing-listing",
            EXTRA_CANDIDATES[28],
        )

    def test_quality_gate_rejection_is_not_reported_as_operational_failure(self) -> None:
        counts = row_outcome_counts(
            [
                {"status": "ok"},
                {"status": "partial"},
                {"status": "quality_rejected"},
                {"status": "failed"},
            ]
        )

        self.assertEqual(counts["quality_rejected"], 1)
        self.assertEqual(counts["operational_failed"], 1)


if __name__ == "__main__":
    unittest.main()

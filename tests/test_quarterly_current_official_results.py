from __future__ import annotations

import csv
import unittest
from pathlib import Path

from scripts import build_quarterly_metrics_knowledge as builder


ROOT = Path(__file__).resolve().parents[1]


class QuarterlyCurrentOfficialResultsTests(unittest.TestCase):
    def test_builder_carries_current_official_quarters(self) -> None:
        expected = {
            "AWS": (builder.AWS_2025_METRICS, "Q2 2026", "revenue", 42232),
            "Microsoft": (builder.MICROSOFT_2025_METRICS, "Q2 2026", "revenue", 39306),
            "Google": (builder.GOOGLE_CLOUD_2025_METRICS, "Q2 2026", "revenue", 24768),
            "Tencent": (builder.TENCENT_FBS_METRICS, "Q2 2026", "fintech_business_services_revenue", 60286),
            "Alibaba": (builder.ALIBABA_CLOUD_METRICS, "FY2027 Q1", "revenue", 48437),
        }
        for metrics, period, metric_key, value in expected.values():
            self.assertEqual(metrics[metric_key][period], value)

    def test_canonical_database_contains_current_results_and_icable(self) -> None:
        path = ROOT / "agent_knowledge/quarterly_competitor_metrics_2026-06-18/quarterly_metrics.csv"
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        keyed = {
            (row["subject"], row["period"], row["metric_key"]): row
            for row in rows
        }
        self.assertEqual(keyed[("AWS", "Q2 2026", "revenue")]["official_value"], "42232")
        self.assertEqual(keyed[("Google Cloud", "Q2 2026", "revenue")]["official_value"], "24768")
        self.assertEqual(keyed[("i-CABLE", "H1 2026", "revenue")]["official_value"], "244.42")


if __name__ == "__main__":
    unittest.main()

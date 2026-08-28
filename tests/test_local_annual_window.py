from __future__ import annotations

import json
import unittest
from pathlib import Path

from cmhk.intelligence import executive


class LocalAnnualWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.financial_payload = json.loads(executive.INTERNATIONAL_PATH.read_text(encoding="utf-8"))
        cls.operating_payload = json.loads(executive.LOCAL_OPERATING_PATH.read_text(encoding="utf-8"))
        cls.operating_sources = json.loads(executive.LOCAL_OPERATING_SOURCES_PATH.read_text(encoding="utf-8"))

    def test_window_rolls_only_after_an_official_full_year_report(self) -> None:
        h1_report = {
            "company": "HKT", "period": "H1 2026", "report_type": "interim",
            "publication_date": "2026-07-29", "source_url": "https://example.com/hkt-h1-2026.pdf",
            "verification_status": "official_document_extracted",
            "metrics": [{"metric_key": "revenue", "value": "HK$18,685 million"}],
        }
        annual_report = {
            "company": "HKT", "period": "FY 2026", "report_type": "annual",
            "publication_date": "2027-02-01", "source_url": "https://example.com/hkt-fy2026.pdf",
            "verification_status": "official_document_extracted",
            "metrics": [
                {"metric_key": "revenue", "value": "HK$40,000 million"},
                {"metric_key": "ebitda", "value": "HK$15,000 million"},
                {"metric_key": "net_profit", "value": "HK$5,500 million"},
            ],
        }
        h1_only = executive._requested_hong_kong_domain(
            self.financial_payload, self.operating_payload, self.operating_sources, {"reports": [h1_report]}
        )
        self.assertIn("2016–2025财年窗口", h1_only["context"])
        self.assertEqual(
            next(item for item in h1_only["focuses"][0]["items"] if item["name"] == "HKT")["period"],
            "FY2025",
        )

        rolled = executive._requested_hong_kong_domain(
            self.financial_payload, self.operating_payload, self.operating_sources,
            {"reports": [annual_report, h1_report]},
        )
        hkt_revenue = next(item for item in rolled["focuses"][0]["items"] if item["name"] == "HKT")
        self.assertEqual((hkt_revenue["period"], hkt_revenue["value"]), ("FY2026", 40000.0))
        self.assertEqual(
            [point["label"] for point in hkt_revenue["trend"]],
            [f"FY{year}" for year in range(2017, 2027)],
        )
        self.assertIn("FY2017–FY2026", rolled["context"])
        self.assertEqual(rolled["latest_financial_results"][0]["period"], "FY 2026")
        ebitda = next(focus for focus in rolled["focuses"] if focus["id"] == "ebitda")
        self.assertNotIn("15000", ebitda["insight"], "FY2026 HKT must not be ranked against FY2025 peers")

    def test_unrelated_company_full_year_report_does_not_roll_operator_window(self) -> None:
        domain = executive._requested_hong_kong_domain(
            self.financial_payload,
            self.operating_payload,
            self.operating_sources,
            {"reports": [{
                "company": "i-CABLE", "period": "FY 2026", "report_type": "annual",
                "publication_date": "2027-03-01", "source_url": "https://example.com/icable-fy2026.pdf",
                "verification_status": "official_document_extracted",
                "metrics": [{"metric_key": "revenue", "value": "HK$1,000 million"}],
            }]},
        )
        self.assertIn("2016–2025财年窗口", domain["context"])

    def test_live_snapshot_exposes_latest_financial_reports_to_the_ui(self) -> None:
        snapshot = executive.build_executive_intelligence_snapshot()
        local = next(domain for domain in snapshot["domains"] if domain["id"] == "local")
        hkt = next(report for report in local["latest_financial_results"] if report["company"] == "HKT")
        self.assertEqual(hkt["period"], "H1 2026")
        self.assertEqual(hkt["verification_status"], "official_document_extracted")

    def test_monitoring_chart_labels_latest_financial_values_with_the_report_period(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "web/static/executive-dashboard-demo.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('const period = report.period || "最新披露期";', script)
        self.assertIn('trend: disclosed ? period : "未披露"', script)
        self.assertIn('periods: [disclosed ? period : "未披露"]', script)
        self.assertIn('profile.key === "cmhk" ? "2026首7月" : (metric?.periods?.at(-1) || "")', script)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from executive_company_benchmarks import build_company_benchmarks


class ExecutiveCompanyBenchmarkTests(unittest.TestCase):
    def test_payload_contains_five_companies_and_verified_peer_financials(self):
        payload = build_company_benchmarks()

        self.assertTrue(payload["ok"])
        self.assertEqual(
            [item["id"] for item in payload["companies"]],
            ["cmhk", "hkt", "three", "smartone", "hkbn"],
        )
        self.assertEqual(payload["values"]["cmhk"]["revenue"]["value"], 96.8)
        for company_id in ("hkt", "three", "smartone", "hkbn"):
            company = payload["values"][company_id]
            self.assertIn("revenue", company)
            self.assertIn("ebitda", company)
            self.assertTrue(company["revenue"]["source_url"].startswith("https://"))
            self.assertNotIn("needs_official", company["revenue"]["verification_status"])

    def test_derived_margins_share_the_verified_revenue_period(self):
        payload = build_company_benchmarks()

        for company_id in ("hkt", "three", "smartone", "hkbn"):
            values = payload["values"][company_id]
            self.assertEqual(values["ebitda_margin"]["period"], values["revenue"]["period"])
            self.assertEqual(values["net_margin"]["period"], values["revenue"]["period"])


if __name__ == "__main__":
    unittest.main()

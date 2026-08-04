from __future__ import annotations

import json
import unittest

from executive_intelligence import _international_domain, build_executive_intelligence_snapshot


class ExecutiveIntelligenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = build_executive_intelligence_snapshot()

    def test_four_domains_are_present_and_backed_by_entities(self):
        domains = self.snapshot["domains"]
        self.assertEqual([item["id"] for item in domains], ["local", "international", "cloud", "macro"])
        self.assertTrue(all(item["entities"] for item in domains))
        self.assertGreaterEqual(domains[0]["metric"]["value"], 100)

    def test_relationships_connect_different_domains_and_are_typed(self):
        relations = self.snapshot["relations"]
        self.assertGreaterEqual(len(relations), 4)
        self.assertTrue(all(item["from"] != item["to"] for item in relations))
        self.assertTrue(all(item["kind"] and item["detail"] for item in relations))
        cloud_relation = next(item for item in relations if item["from"] == "international" and item["to"] == "cloud")
        self.assertEqual(cloud_relation["kind"], "跨期间方向参照")
        self.assertIn("报告期间与业务口径不同", cloud_relation["detail"])

    def test_relationship_strip_always_exposes_exactly_four_executive_discoveries(self):
        relations = self.snapshot["relations"]
        self.assertEqual(len(relations), 4)
        self.assertEqual(len({tuple(sorted((item["from"], item["to"]))) for item in relations}), 4)
        self.assertEqual(
            {domain for item in relations for domain in (item["from"], item["to"])},
            {"local", "international", "cloud", "macro"},
        )

    def test_source_links_are_public_http_urls(self):
        for domain in self.snapshot["domains"]:
            self.assertTrue(domain["sources"])
            for source in domain["sources"]:
                self.assertTrue(source["url"].startswith(("https://", "http://")))

    def test_each_domain_exposes_four_distinct_data_backed_focuses(self):
        for domain in self.snapshot["domains"]:
            focuses = domain["focuses"]
            self.assertEqual(len(focuses), 4, domain["id"])
            self.assertEqual(len({focus["id"] for focus in focuses}), 4, domain["id"])
            signatures = {
                json.dumps(
                    {
                        "label": focus["metric"]["label"],
                        "visual": focus["visual"],
                        "items": [
                            (item["name"], item.get("value"), item.get("unit"))
                            for item in focus["items"]
                        ],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                for focus in focuses
            }
            self.assertEqual(len(signatures), 4, domain["id"])
            for focus in focuses:
                self.assertTrue(focus["items"], f"{domain['id']}:{focus['id']}")
                self.assertTrue(focus["insight"])
                self.assertTrue(focus["metric"]["label"])
                for item in focus["items"]:
                    self.assertTrue(item["analysis"])
                    self.assertTrue(item["source_url"].startswith(("https://", "http://")))

    def test_focuses_preserve_their_real_measurement_semantics(self):
        domains = {domain["id"]: domain for domain in self.snapshot["domains"]}
        local = {focus["id"]: focus for focus in domains["local"]["focuses"]}
        self.assertEqual([local[key]["visual"] for key in ("scale", "track", "price", "overlap")],
                         ["columns", "rows", "ranges", "network"])
        self.assertTrue(all("low" in item and "high" in item for item in local["price"]["items"]))

        international = {focus["id"]: focus for focus in domains["international"]["focuses"]}
        self.assertNotEqual(
            [item["value"] for item in international["growth"]["items"]],
            [item["value"] for item in international["momentum"]["items"]],
        )
        self.assertTrue(all("trend" in item for item in international["momentum"]["items"]))
        self.assertEqual(min(item["value"] for item in international["gap"]["items"]), 0)

        cloud = {focus["id"]: focus for focus in domains["cloud"]["focuses"]}
        self.assertTrue(all("trend" in item for item in cloud["trend"]["items"]))
        self.assertTrue(any(item["value"] is None for item in cloud["profit"]["items"]))

        macro = {focus["id"]: focus for focus in domains["macro"]["focuses"]}
        name_sets = {tuple(item["name"] for item in focus["items"]) for focus in macro.values()}
        self.assertEqual(len(name_sets), 4)

    def test_frontend_payload_exposes_ai_gate_and_refresh_status(self):
        self.assertIn("refresh", self.snapshot)
        self.assertIn("ai", self.snapshot)
        self.assertTrue(all("ai_analysis" in domain for domain in self.snapshot["domains"]))
        macro = next(domain for domain in self.snapshot["domains"] if domain["id"] == "macro")
        self.assertEqual(macro["metric"]["label"], "移动服务订户及连接")
        self.assertIn("机器类型连接", macro["insight"])

    def test_international_dashboard_prefers_official_value_over_normalized_value(self):
        common = {
            "subject": "中国移动",
            "metric_key": "revenue_growth_yoy",
            "verification_status": "official_match",
            "official_source_url": "https://example.com/report.pdf",
        }
        domain = _international_domain({"rows": [
            {**common, "period": "Q4 2025", "value": "2.50%", "official_value": 2.4},
            {**common, "period": "Q1 2026", "value": "1.03%", "official_value": 1.031},
        ]})
        self.assertEqual(domain["entities"][0]["value"], 1.03)
        momentum = next(item for item in domain["focuses"] if item["id"] == "momentum")
        self.assertEqual(momentum["items"][0]["value"], -1.37)


if __name__ == "__main__":
    unittest.main()

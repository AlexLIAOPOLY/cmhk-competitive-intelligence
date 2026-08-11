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
        ai_relations = [item for item in relations if item.get("origin") == "ai"]
        if ai_relations:
            self.assertTrue(all(item["source_urls"] for item in ai_relations))
        else:
            self.assertTrue(any(item["kind"] == "跨期间方向参照" for item in relations))

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
        price_insight = local["price"]["insight"]
        price_items = [item for item in local["price"]["items"] if item.get("value") is not None]
        lowest = min(price_items, key=lambda item: item["value"])
        highest = max(price_items, key=lambda item: item["value"])
        self.assertIn(lowest["name"], price_insight)
        self.assertIn(highest["name"], price_insight)
        self.assertIn(str(int(lowest["value"])), price_insight)
        self.assertIn(str(int(highest["value"])), price_insight)
        self.assertIn("价差", price_insight)
        self.assertNotIn("缺失值不估算", price_insight)

        international = {focus["id"]: focus for focus in domains["international"]["focuses"]}
        self.assertNotEqual(
            [item["value"] for item in international["growth"]["items"]],
            [item["value"] for item in international["momentum"]["items"]],
        )
        self.assertTrue(all("trend" in item for item in international["momentum"]["items"]))
        self.assertNotIn("gap", international)
        self.assertEqual(international["investment"]["label"], "投入强度")
        self.assertTrue(
            all(
                item["value"] is None or "资本开支占营收" in item["detail"]
                for item in international["investment"]["items"]
            )
        )
        self.assertIn("资本开支/营收", international["investment"]["metric"]["label"])

        cloud = {focus["id"]: focus for focus in domains["cloud"]["focuses"]}
        self.assertTrue(all("trend" in item for item in cloud["trend"]["items"]))
        self.assertTrue(any(item["value"] is None for item in cloud["profit"]["items"]))

        macro = {focus["id"]: focus for focus in domains["macro"]["focuses"]}
        name_sets = {tuple(item["name"] for item in focus["items"]) for focus in macro.values()}
        self.assertEqual(len(name_sets), 4)
        self.assertEqual(macro["governance"]["visual"], "governance")
        self.assertEqual(
            [item["name"] for item in macro["governance"]["items"]],
            ["电信业投资", "电讯投诉", "5G人口覆盖", "5G相关频谱"],
        )

    def test_frontend_payload_exposes_ai_gate_and_refresh_status(self):
        self.assertIn("refresh", self.snapshot)
        self.assertIn("ai", self.snapshot)
        self.assertTrue(all("ai_analysis" in domain for domain in self.snapshot["domains"]))
        macro = next(domain for domain in self.snapshot["domains"] if domain["id"] == "macro")
        self.assertEqual(macro["metric"]["label"], "移动服务订户及连接")
        self.assertIn("机器类型连接", macro["insight"])
        for domain in self.snapshot["domains"]:
            self.assertTrue(all("ai_summary" in focus for focus in domain["focuses"]))

    def test_every_clickable_entity_exposes_concrete_components(self):
        for domain in self.snapshot["domains"]:
            for focus in domain["focuses"]:
                for item in focus["items"]:
                    self.assertTrue(item.get("components"), f"{domain['id']}:{focus['id']}:{item['name']}")
                    self.assertTrue(all(component.get("label") for component in item["components"]))

    def test_icable_scale_lists_unique_plans_and_duplicate_record_risk(self):
        local = next(domain for domain in self.snapshot["domains"] if domain["id"] == "local")
        scale = next(focus for focus in local["focuses"] if focus["id"] == "scale")
        icable = next(item for item in scale["items"] if item["name"] == "i-CABLE")
        self.assertEqual(icable["record_count"], 10)
        self.assertEqual(icable["component_count"], 8)
        self.assertIn("2 条重复记录", icable["analysis"])
        self.assertIn("月费 HK$58–118", icable["analysis"])
        self.assertIn(
            "i-CABLE Broadband 公屋居屋 1000M HK$68",
            {component["label"] for component in icable["components"]},
        )

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

    def test_international_investment_intensity_uses_same_period_official_values(self):
        rows = []
        for subject, capex, revenue in (
            ("中国移动", -30_000, 250_000),
            ("中国电信", -15_000, 125_000),
            ("中国联通", -12_000, 100_000),
        ):
            common = {
                "subject": subject,
                "period": "Q1 2026",
                "verification_status": "official_match",
                "official_unit": "millions CNY",
                "official_source_url": "https://example.com/report.pdf",
            }
            rows.extend([
                {**common, "metric_key": "revenue_growth_yoy", "official_value": 1.0},
                {**common, "metric_key": "capital_expenditures", "official_value": capex},
                {**common, "metric_key": "revenue", "official_value": revenue},
            ])
        domain = _international_domain({"rows": rows})
        investment = next(focus for focus in domain["focuses"] if focus["id"] == "investment")
        self.assertEqual([item["value"] for item in investment["items"][:3]], [12.0, 12.0, 12.0])
        self.assertTrue(all(item["component_count"] == 2 for item in investment["items"][:3]))
        self.assertIn("三家最大相差0.00个百分点", investment["insight"])
        self.assertNotIn("用于比较", investment["insight"])
        momentum = next(focus for focus in domain["focuses"] if focus["id"] == "momentum")
        self.assertNotIn("正值代表", momentum["insight"])
        disclosure = next(focus for focus in domain["focuses"] if focus["id"] == "disclosure")
        self.assertNotIn("用于判断", disclosure["insight"])


if __name__ == "__main__":
    unittest.main()

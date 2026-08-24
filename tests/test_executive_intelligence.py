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
        self.assertGreaterEqual(domains[0]["metric"]["value"], 50)

    def test_relationships_connect_different_domains_and_are_typed(self):
        relations = self.snapshot["relations"]
        self.assertGreaterEqual(len(relations), 4)
        self.assertTrue(all(item["from"] != item["to"] for item in relations))
        self.assertTrue(all(item["kind"] and item["detail"] for item in relations))
        ai_relations = [item for item in relations if item.get("origin") == "ai"]
        if ai_relations:
            self.assertTrue(all(item["source_urls"] for item in ai_relations))
        else:
            self.assertTrue(any(item["kind"] == "不可直接比较" for item in relations))

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

    def test_each_domain_exposes_expected_distinct_data_backed_focuses(self):
        for domain in self.snapshot["domains"]:
            focuses = domain["focuses"]
            expected_count = 5 if domain["id"] == "local" else 4
            self.assertEqual(len(focuses), expected_count, domain["id"])
            self.assertEqual(len({focus["id"] for focus in focuses}), expected_count, domain["id"])
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
            self.assertEqual(len(signatures), expected_count, domain["id"])
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
        self.assertEqual(local["financials"]["label"], "重要财务指标")
        self.assertEqual(local["financials"]["visual"], "financial")
        self.assertGreaterEqual(len(local["financials"]["items"]), 4)
        self.assertEqual(
            [local[key]["label"] for key in ("scale", "mobile_price", "fibre_value", "overlap")],
            ["在售产品组合", "个人5G月费", "家宽每千兆价格", "同类价格重合"],
        )
        self.assertEqual([local[key]["visual"] for key in ("scale", "mobile_price", "fibre_value", "overlap")],
                         ["columns", "ranges", "rows", "network"])
        self.assertEqual(local["scale"]["metric"]["unit"], "个产品")
        self.assertTrue(all(item["unit"] == "个产品" for item in local["scale"]["items"]))
        self.assertEqual(local["fibre_value"]["metric"]["unit"], "港元/千兆/月")
        self.assertTrue(all(item["unit"] == "港元/千兆/月" for item in local["fibre_value"]["items"]))
        self.assertTrue(any(item["record_count"] > item["component_count"] for item in local["scale"]["items"]))
        self.assertIn("数据采集于", local["scale"]["context"])
        self.assertIn("香港时间", local["scale"]["context"])
        self.assertTrue(all("low" in item and "high" in item for item in local["mobile_price"]["items"]))
        mobile_3hk = next(item for item in local["mobile_price"]["items"] if item["name"] == "3HK / Hutchison")
        self.assertEqual(mobile_3hk["value"], 168.0)
        self.assertNotIn(68.0, [component.get("value") for component in mobile_3hk["components"]])
        price_insight = local["mobile_price"]["insight"]
        price_items = [item for item in local["mobile_price"]["items"] if item.get("value") is not None]
        lowest = min(price_items, key=lambda item: item["value"])
        highest = max(price_items, key=lambda item: item["value"])
        self.assertIn(lowest["name"], price_insight)
        self.assertIn(highest["name"], price_insight)
        self.assertIn(str(int(lowest["value"])), price_insight)
        self.assertIn(str(int(highest["value"])), price_insight)
        self.assertIn("月费区间", price_insight)

        international = {focus["id"]: focus for focus in domains["international"]["focuses"]}
        self.assertEqual(domains["international"]["title"], "内地电讯企业")
        self.assertEqual(international["momentum"]["label"], "增长变化")
        self.assertIn("放缓已扩散至全部公司", international["momentum"]["insight"])
        self.assertIn(international["growth"]["items"][0]["period"], international["growth"]["metric"]["label"])
        self.assertNotEqual(
            [item["value"] for item in international["growth"]["items"]],
            [item["value"] for item in international["momentum"]["items"]],
        )
        self.assertTrue(all("trend" in item for item in international["momentum"]["items"]))
        self.assertNotIn("gap", international)
        self.assertEqual(international["investment"]["label"], "资本投入占比")
        self.assertTrue(
            all(
                item["value"] is None or "资本开支占营收" in item["detail"]
                for item in international["investment"]["items"]
            )
        )
        self.assertIn("资本开支/营收", international["investment"]["metric"]["label"])

        cloud = {focus["id"]: focus for focus in domains["cloud"]["focuses"]}
        self.assertEqual(cloud["growth"]["label"], "收入增长")
        self.assertEqual(cloud["trend"]["headline"], "收入提速并非少数")
        self.assertTrue(all("口径" in item["detail"] for item in cloud["growth"]["items"]))
        self.assertTrue(all("trend" in item for item in cloud["trend"]["items"]))
        self.assertTrue(any(item["value"] is None for item in cloud["profit"]["items"]))
        self.assertTrue(all(item["value"] is not None or item["unit"] == "" for item in cloud["trend"]["items"]))
        self.assertTrue(all(item["value"] is not None or item["unit"] == "" for item in cloud["profit"]["items"]))
        self.assertIn("margin_change", cloud)

        macro = {focus["id"]: focus for focus in domains["macro"]["focuses"]}
        self.assertEqual(macro["service"]["label"], "投入与投诉")
        name_sets = {tuple(item["name"] for item in focus["items"]) for focus in macro.values()}
        self.assertEqual(len(name_sets), 4)
        self.assertEqual(macro["service"]["visual"], "kpis")
        self.assertIn("电讯投诉", [item["name"] for item in macro["service"]["items"]])
        investment = next(item for item in macro["service"]["items"] if item["name"] == "电讯业投资")
        self.assertTrue(all(component.get("unit") == "百万港元" for component in investment["components"]))
        coverage = next(item for item in macro["service"]["items"] if item["name"] == "5G人口覆盖")
        self.assertEqual(coverage["value"], "超过99%")
        macro_text = json.dumps(macro, ensure_ascii=False)
        self.assertNotIn("e+", macro_text.lower())
        for untranslated_unit in ("subscriptions", "access lines", '"unit": "count"', '"unit": "index"'):
            self.assertNotIn(untranslated_unit, macro_text)
        purchasing = macro["purchasing"]
        income = next(item for item in purchasing["items"] if item["name"] == "家庭月入中位数")
        cpi = next(item for item in purchasing["items"] if item["name"] == "甲类消费物价同比")
        self.assertTrue(income["detail"].startswith(cpi["detail"].replace("截至 ", "")))
        self.assertIn(income["detail"].split(" 对比 ", 1)[0], purchasing["insight"])
        self.assertIn("期间不同", macro["service"]["insight"])

    def test_reader_facing_database_copy_avoids_internal_jargon_and_false_comparisons(self):
        visible = []
        for domain in self.snapshot["domains"]:
            visible.extend([domain["title"], domain["kicker"], domain["context"], domain["insight"]])
            for focus in domain["focuses"]:
                visible.extend([focus["label"], focus["context"], focus["insight"], focus["metric"]["label"]])
                for item in focus["items"]:
                    visible.extend([item["name"], item["detail"], item["analysis"], item["unit"]])
        for relation in self.snapshot["relations"]:
            visible.extend([relation["title"], relation["detail"], relation["kind"]])
        text = "\n".join(str(item) for item in visible)
        for forbidden in (
            "竞对", "赛道", "交锋", "增长梯队", "投入强度", "增长动量", "移动用户",
            "月费带", "结构化平均月费中位数", "direct_product_line_and_segment",
            "official_proxy_segment", "direct_segment_non_gaap_profit", "proxy_segment",
            "segment_with_reclassification",
        ):
            self.assertNotIn(forbidden, text)
        self.assertIn("联网设备", text)
        self.assertTrue(
            any(boundary in text for boundary in ("不直接比较", "不可直接比较", "不能直接比较"))
        )
        self.assertNotIn("同类套餐竞争最多", text)
        self.assertNotIn("可核验指标数", text)
        self.assertNotIn("（%）", text)

    def test_frontend_payload_exposes_ai_gate_and_refresh_status(self):
        self.assertIn("refresh", self.snapshot)
        self.assertIn("ai", self.snapshot)
        self.assertTrue(all("ai_analysis" in domain for domain in self.snapshot["domains"]))
        macro = next(domain for domain in self.snapshot["domains"] if domain["id"] == "macro")
        self.assertEqual(macro["metric"]["label"], "手机卡/设备同比")
        connections = next(focus for focus in macro["focuses"] if focus["id"] == "connections")
        self.assertEqual(connections["label"], "登记数量")
        self.assertEqual(
            [item["name"] for item in connections["items"]],
            ["手机卡/设备", "移动宽带", "每百人登记"],
        )
        self.assertIn("不能当作客户人数增长", connections["insight"])
        self.assertIn("独立客户", macro["insight"])
        for domain in self.snapshot["domains"]:
            self.assertTrue(all("ai_summary" in focus for focus in domain["focuses"]))
        if not self.snapshot["ai"]["model_analysis_fresh"]:
            self.assertEqual(self.snapshot["ai"]["model_analysis"], {})

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
        self.assertIn("10 条记录", icable["analysis"])
        self.assertIn("8 个在售产品", icable["analysis"])
        self.assertIn(
            "光纤家宽｜1000Mbps",
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
        self.assertIn("三家公司最高与最低相差0.00个百分点", investment["insight"])
        self.assertNotIn("用于比较", investment["insight"])
        momentum = next(focus for focus in domain["focuses"] if focus["id"] == "momentum")
        self.assertNotIn("正值代表", momentum["insight"])
        margin = next(focus for focus in domain["focuses"] if focus["id"] == "margin")
        self.assertNotIn("用于判断", margin["insight"])

    def test_reader_facing_snapshot_uses_percent_symbol_instead_of_percentage_points(self):
        visible = json.dumps(self.snapshot["domains"], ensure_ascii=False)

        self.assertNotIn("百分点", visible)
        self.assertIn('"unit": "%"', visible)


if __name__ == "__main__":
    unittest.main()

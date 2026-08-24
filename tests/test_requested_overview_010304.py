from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import executive_intelligence_pipeline as pipeline
from cmhk.intelligence.executive import build_executive_intelligence_snapshot


class RequestedOverview010304Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = build_executive_intelligence_snapshot()
        cls.domains = {domain["id"]: domain for domain in cls.snapshot["domains"]}

    def test_domain_order_and_short_tabs_match_request(self):
        self.assertEqual(
            [(domain["index"], domain["id"], domain["title"]) for domain in self.snapshot["domains"]],
            [
                ("01", "local", "香港电讯市场"),
                ("02", "international", "国际运营商"),
                ("03", "mainland", "内地运营商"),
                ("04", "cloud", "全球云厂商"),
            ],
        )
        self.assertEqual([focus["label"] for focus in self.domains["local"]["focuses"]], ["营收", "EBITDA", "净利润", "后付费用户数"])
        self.assertEqual([focus["label"] for focus in self.domains["mainland"]["focuses"]], ["营收", "EBITDA", "净利润", "后付费用户数"])
        self.assertEqual([focus["label"] for focus in self.domains["cloud"]["focuses"]], ["云收入", "云利润", "资本开支"])

    def test_domain_02_keeps_colleague_international_contract(self):
        domain = self.domains["international"]
        self.assertEqual([focus["id"] for focus in domain["focuses"]], ["revenue", "ebitda", "net_profit", "postpaid_arpu"])
        self.assertEqual([item["name"] for item in domain["focuses"][0]["items"]], ["Verizon", "Deutsche Telekom", "AT&T", "NTT Group"])

    def test_hong_kong_and_mainland_units_are_consistent(self):
        local = {focus["id"]: focus for focus in self.domains["local"]["focuses"]}
        mainland = {focus["id"]: focus for focus in self.domains["mainland"]["focuses"]}
        self.assertEqual({item["unit"] for item in local["revenue"]["items"] if item["value"] is not None}, {"百万港元"})
        self.assertEqual({item["unit"] for item in mainland["revenue"]["items"] if item["value"] is not None}, {"亿元"})
        self.assertEqual({item["unit"] for item in local["ebitda"]["items"] if item["value"] is not None}, {"百万港元"})
        self.assertEqual({item["unit"] for item in mainland["ebitda"]["items"] if item["value"] is not None}, {"亿元"})
        self.assertEqual({item["unit"] for item in local["net_profit"]["items"] if item["value"] is not None}, {"百万港元"})
        self.assertEqual({item["unit"] for item in mainland["net_profit"]["items"] if item["value"] is not None}, {"亿元"})
        for domain in (local, mainland):
            self.assertNotIn("%", {item["unit"] for focus in domain.values() for item in focus["items"] if item.get("value") is not None})

    def test_cloud_currency_values_are_normalized_to_usd(self):
        cloud = {focus["id"]: focus for focus in self.domains["cloud"]["focuses"]}
        self.assertEqual({item["unit"] for item in cloud["investment"]["items"] if item["value"] is not None}, {"百万美元"})
        self.assertEqual({item["unit"] for item in cloud["revenue"]["items"] if item["value"] is not None}, {"百万美元"})
        self.assertEqual({item["unit"] for item in cloud["profit"]["items"] if item["value"] is not None}, {"百万美元"})
        self.assertTrue(all(focus["metric"]["unit"] == "百万美元" for focus in cloud.values()))
        self.assertGreaterEqual(len([source for source in self.domains["cloud"]["sources"] if "汇率" in source["label"] or "Federal Reserve" in source["label"]]), 3)

    def test_cloud_revenue_and_profit_use_scrollable_columns_with_small_units(self):
        cloud = {focus["id"]: focus for focus in self.domains["cloud"]["focuses"]}
        self.assertEqual(cloud["revenue"]["visual"], "columns")
        self.assertEqual(cloud["profit"]["visual"], "columns")
        root = Path(__file__).resolve().parents[1]
        app = (root / "web/static/app.js").read_text(encoding="utf-8")
        styles = (root / "web/static/styles.css").read_text(encoding="utf-8")
        self.assertIn('class="intelligence-chart-scroll"', app)
        self.assertIn('<small>${safe(item.unit)}</small>', app)
        self.assertIn('.intelligence-chart-scroll {', styles)
        self.assertIn('overflow-x: auto;', styles)
        self.assertIn('.intelligence-viz-columns strong small {', styles)

    def test_focus_prompt_uses_strategic_few_shots_instead_of_a_new_keyword_gate(self):
        source = Path(pipeline.__file__).read_text(encoding="utf-8")
        self.assertIn("问题：只告诉读者数据是什么，没有提炼战略发现", source)
        self.assertIn("利润池向头部集中", source)
        self.assertIn("口径缺口意味着客户价值和客户质量无法穿透比较", source)
        self.assertNotIn("_STRATEGIC_FINDING_MARKERS", source)

    def test_default_focus_copy_states_strategic_findings_not_display_instructions(self):
        forbidden = ("只展示金额", "只展示FY2024", "只复述")
        required = ("资源承载", "盈利缓冲", "盈利韧性", "利润池", "客户价值", "收入基础", "投入转化")
        for domain in self.snapshot["domains"]:
            for focus in domain["focuses"]:
                insight = str(focus.get("insight") or "")
                self.assertFalse(any(term in insight for term in forbidden), f"{domain['id']}:{focus['id']}:{insight}")
                self.assertTrue(any(term in insight for term in required), f"{domain['id']}:{focus['id']}:{insight}")

    def test_only_triple_source_values_are_admitted_for_requested_gaps(self):
        local = {focus["id"]: focus for focus in self.domains["local"]["focuses"]}
        by_name = {item["name"]: item for item in local["postpaid"]["items"]}
        self.assertEqual(by_name["HKT"]["verification_count"], 3)
        self.assertEqual(by_name["3HK"]["verification_count"], 3)
        self.assertIsNone(by_name["CMHK"]["value"])
        self.assertIsNone(by_name["SmarTone"]["value"])
        self.assertEqual(sum(point["value"] is not None for point in by_name["HKT"]["trend"]), 10)
        self.assertEqual(sum(point["value"] is not None for point in by_name["3HK"]["trend"]), 10)
        mainland_postpaid = next(focus for focus in self.domains["mainland"]["focuses"] if focus["id"] == "postpaid")
        detail = json.dumps(mainland_postpaid, ensure_ascii=False)
        self.assertIn("官方文件未单列后付费用户数", detail)
        self.assertNotIn("移动用户总数1005", detail)
        self.assertTrue(all(item["value"] is None for item in mainland_postpaid["items"]))

    def test_all_requested_items_expose_the_complete_ten_year_window(self):
        for domain_id in ("local", "mainland", "cloud"):
            for focus in self.domains[domain_id]["focuses"]:
                for item in focus["items"]:
                    self.assertEqual(len(item.get("trend") or []), 10, f"{domain_id}:{focus['id']}:{item['name']}")
                    self.assertEqual([point["label"] for point in item["trend"]], [f"FY{year}" for year in range(2016, 2026)])

    def test_ai_summary_and_regeneration_contract_accept_current_focuses(self):
        evidence = pipeline._analysis_input_snapshot()
        summaries = pipeline._deterministic_domain_summaries(evidence)
        discoveries = pipeline._deterministic_discoveries(evidence)
        self.assertEqual([summary["domain"] for summary in summaries], ["local", "international", "mainland", "cloud"])
        self.assertEqual(len(discoveries), 4)
        self.assertTrue(self.snapshot["ai"]["model_analysis_fresh"])
        self.assertTrue(all(focus.get("ai_summary") for domain in self.snapshot["domains"] for focus in domain["focuses"]))

    def test_manual_regeneration_falls_back_to_current_evidence_when_model_times_out(self):
        current = pipeline._read_json(pipeline.AI_ANALYSIS_PATH, {})
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ai_analysis.json"
            path.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
            with patch(
                "executive_intelligence_pipeline.generate_model_focus_insight",
                side_effect=TimeoutError("model timeout"),
            ):
                result = pipeline.regenerate_model_focus_summary("mainland", "postpaid", path=path)
        self.assertTrue(result["ok"])
        self.assertEqual(result["origin"], "evidence_rule")
        self.assertIn("后付费用户", result["analysis"])
        self.assertNotIn("移动用户总数为", result["analysis"])


if __name__ == "__main__":
    unittest.main()

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
                ("01", "local", "本地运营商"),
                ("02", "international", "国际运营商"),
                ("03", "mainland", "内地运营商"),
                ("04", "cloud", "全球云厂商"),
            ],
        )
        self.assertEqual([focus["label"] for focus in self.domains["local"]["focuses"]], ["营收", "EBITDA", "净利润", "后付费用户数"])
        self.assertEqual([focus["label"] for focus in self.domains["mainland"]["focuses"]], ["营收", "EBITDA", "净利润", "移动客户数"])
        self.assertEqual(self.domains["mainland"]["kicker"], "移动｜电信｜联通")
        self.assertTrue(all([item["name"] for item in focus["items"]] == ["中国移动", "中国电信", "中国联通"] for focus in self.domains["mainland"]["focuses"]))
        self.assertEqual([focus["label"] for focus in self.domains["cloud"]["focuses"]], ["云收入", "云利润", "资本开支"])

    def test_domain_02_keeps_colleague_international_contract(self):
        domain = self.domains["international"]
        self.assertEqual([focus["id"] for focus in domain["focuses"]], ["revenue", "ebitda", "net_profit", "postpaid_arpu"])
        self.assertEqual([item["name"] for item in domain["focuses"][0]["items"]], ["Verizon", "Deutsche Telekom", "AT&T", "NTT Group"])

    def test_domain_02_top_right_metrics_show_the_current_leader(self):
        for focus in self.domains["international"]["focuses"]:
            leader = max(focus["items"], key=lambda item: item["value"])
            self.assertEqual(focus["metric"]["value"], leader["value"])
            self.assertEqual(focus["metric"]["unit"], leader["unit"])
            self.assertEqual(focus["metric"]["label"], f"{leader['name']} FY2025")

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

    def test_cmhk_reference_ppt_values_keep_period_and_dimension_labels(self):
        local = {focus["id"]: focus for focus in self.domains["local"]["focuses"]}
        revenue = next(item for item in local["revenue"]["items"] if item["name"] == "CMHK")
        profit = next(item for item in local["net_profit"]["items"] if item["name"] == "CMHK")
        self.assertEqual((revenue["value"], revenue["unit"], revenue["period"]), (4544.6, "百万港元", "2026首7月"))
        self.assertEqual((profit["value"], profit["unit"], profit["period"]), (583.2, "百万港元", "2026首7月"))
        components = {component["label"]: component for component in revenue["components"]}
        self.assertEqual(components["5G客户渗透率"]["unit"], "%")
        self.assertIn("期末值", components["5G客户渗透率"]["detail"])
        self.assertIn("年化", components["总资产收益率"]["detail"])
        app = (Path(__file__).resolve().parents[1] / "web/static/app.js").read_text(encoding="utf-8")
        styles = (Path(__file__).resolve().parents[1] / "web/static/styles.css").read_text(encoding="utf-8")
        self.assertIn("Math.min(8, components.length)", app)
        self.assertIn("components.slice(0, 8)", app)
        self.assertIn('entity.period === "2026首7月" ? "2026首7月累计"', app)
        self.assertIn('item.period === "2026首7月"', app)
        self.assertIn("intelligence-period-prefix", app)
        self.assertIn("intelligence-period-prefix", styles)
        self.assertIn("intelligence-entity-period-note", styles)
        self.assertIn(".intelligence-domain-local .intelligence-entity-focus:not(.is-overview)", styles)

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
        required = (
            "资源承载", "资源底盘", "资源容错", "持续投入", "经营容错", "经营造血", "价战容错",
            "盈利缓冲", "盈利韧性", "利润池", "客户价值", "账户价值", "客户经营",
            "收入基础", "收入底盘", "自我融资", "再投资", "生态扩张", "资本军备", "投入转化",
        )
        for domain in self.snapshot["domains"]:
            for focus in domain["focuses"]:
                insight = str(focus.get("insight") or "")
                self.assertFalse(any(term in insight for term in forbidden), f"{domain['id']}:{focus['id']}:{insight}")
                self.assertTrue(any(term in insight for term in required), f"{domain['id']}:{focus['id']}:{insight}")

    def test_every_overview_focus_has_a_strategic_meaning_headline(self):
        forbidden = (
            "FY", "营收", "EBITDA", "净利润", "后付费用户", "云收入", "云利润", "资本开支",
            "金额", "绝对值", "序列", "入库", "披露", "口径", "数据", "待补", "重新判断", "按三来源",
        )
        for domain in self.snapshot["domains"]:
            for focus in domain["focuses"]:
                headline = str(focus.get("headline") or "")
                self.assertTrue(headline, f"{domain['id']}:{focus['id']}")
                self.assertFalse(any(term in headline for term in forbidden), f"{domain['id']}:{focus['id']}:{headline}")

    def test_deterministic_ai_copy_keeps_specific_numbers_and_adds_strategic_meaning(self):
        evidence = pipeline._analysis_input_snapshot()
        summaries = pipeline._deterministic_domain_summaries(evidence)
        direct_headline_terms = pipeline._OVERVIEW_DIRECT_HEADLINE_TERMS
        strategic_terms = pipeline._OVERVIEW_STRATEGIC_MEANING_TERMS
        for summary in summaries:
            for focus in summary["focuses"]:
                key = (summary["domain"], focus["id"])
                if key not in pipeline._OVERVIEW_STRATEGIC_HEADLINES:
                    continue
                self.assertEqual(focus["headline"], pipeline._OVERVIEW_STRATEGIC_HEADLINES[key])
                self.assertFalse(any(term in focus["headline"] for term in direct_headline_terms))
                self.assertTrue(pipeline._numeric_tokens(focus["analysis"]), key)
                self.assertTrue(any(term in focus["analysis"] for term in strategic_terms), key)

    def test_overview_prompt_teaches_operating_judgement_instead_of_rank_restatement(self):
        focus = next(item for item in self.domains["local"]["focuses"] if item["id"] == "revenue")
        generic = "HKT FY2025营收36553百万港元，3HK为5448百万港元；收入规模形成梯队，意味着资源承载力不同。"
        self.assertFalse(pipeline._focus_gate_error("local", "revenue", generic, focus))
        generated = pipeline._compact_grounded_focus_analysis("local", focus)
        self.assertIn("HKT的经营资源底盘最厚", generated)
        self.assertIn("3HK的资源容错较窄", generated)

    def test_overview_gate_rejects_contradictory_competitor_exclusion(self):
        focus = next(item for item in self.domains["local"]["focuses"] if item["id"] == "ebitda")
        contradictory = (
            "HKT EBITDA为14234百万港元，SmarTone与3HK分别为2445.1和1508百万港元，"
            "不能纳入这一判断；盈利缓冲分层意味着持续投入与价格竞争容错不同。"
        )
        self.assertIn(
            "判断自相矛盾",
            pipeline._focus_gate_error("local", "ebitda", contradictory, focus),
        )

    def test_only_triple_source_values_are_admitted_for_requested_gaps(self):
        local = {focus["id"]: focus for focus in self.domains["local"]["focuses"]}
        by_name = {item["name"]: item for item in local["postpaid"]["items"]}
        self.assertEqual(by_name["HKT"]["verification_count"], 3)
        self.assertEqual(by_name["3HK"]["verification_count"], 3)
        self.assertIsNone(by_name["CMHK"]["value"])
        self.assertIsNone(by_name["SmarTone"]["value"])
        self.assertEqual(sum(point["value"] is not None for point in by_name["HKT"]["trend"]), 10)
        self.assertEqual(sum(point["value"] is not None for point in by_name["3HK"]["trend"]), 10)
        mainland_mobile = next(focus for focus in self.domains["mainland"]["focuses"] if focus["id"] == "postpaid")
        mainland_by_name = {item["name"]: item for item in mainland_mobile["items"]}
        self.assertEqual(mainland_by_name["中国移动"]["value"], 10.05)
        self.assertEqual(mainland_by_name["中国电信"]["value"], 4.3865)
        self.assertEqual(mainland_by_name["中国联通"]["value"], 3.573)
        self.assertIn("推导约值", mainland_by_name["中国联通"]["analysis"])
        self.assertNotIn("中国广电", mainland_by_name)

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

    def test_runtime_contract_proves_the_daily_summary_matches_the_current_ui(self):
        contract = self.snapshot["ui_contract"]
        self.assertEqual(contract["domain_ids"], ["local", "international", "mainland", "cloud"])
        self.assertEqual(contract["summary_domain_ids"], contract["domain_ids"])
        self.assertEqual(contract["focuses_expected"], 15)
        self.assertEqual(contract["focuses_summarized"], 15)
        self.assertTrue(contract["aligned"])

    def test_every_missing_value_has_an_audited_gap_status(self):
        missing = [
            item
            for domain in self.snapshot["domains"]
            for focus in domain["focuses"]
            for item in focus["items"]
            if item.get("value") is None
        ]
        self.assertTrue(missing)
        self.assertTrue(all(item.get("gap_status") in {"public_not_found", "knowledge_pending"} for item in missing))
        for item in missing:
            detail = str(item.get("detail") or "")
            if item["gap_status"] == "public_not_found":
                self.assertIn("官网、年报、业绩公告与业绩演示复核", detail)
            else:
                self.assertIn("不得表述为互联网未披露", detail)

    def test_china_unicom_fy2025_ebitda_is_recovered_from_local_audit_knowledge(self):
        ebitda = next(focus for focus in self.domains["mainland"]["focuses"] if focus["id"] == "ebitda")
        unicom = next(item for item in ebitda["items"] if item["name"] == "中国联通")
        self.assertEqual(unicom["value"], 994.2)
        self.assertEqual(unicom["unit"], "亿元")
        self.assertEqual(unicom["verification_count"], 2)
        self.assertEqual(len(unicom["source_urls"]), 2)
        self.assertTrue(unicom["source_urls"][0].endswith(".pdf"))
        self.assertIn("highlights.php?data=quarterly", unicom["source_urls"][1])

    def test_user_accepted_single_source_cloud_values_are_displayed_with_true_periods(self):
        cloud = {focus["id"]: focus for focus in self.domains["cloud"]["focuses"]}
        revenue = {item["name"]: item for item in cloud["revenue"]["items"]}
        investment = {item["name"]: item for item in cloud["investment"]["items"]}
        self.assertEqual(revenue["中国移动云"]["value"], 7869.3)
        self.assertEqual(revenue["中国移动云"]["period"], "H1 2025")
        self.assertIn("不代替FY2025全年", revenue["中国移动云"]["analysis"])
        self.assertEqual(
            {name: investment[name]["value"] for name in ("AWS", "Alibaba", "腾讯", "Huawei")},
            {"AWS": 77658.0, "Alibaba": 4444.0, "腾讯": 10677.4, "Huawei": 7299.5},
        )
        self.assertTrue(all(investment[name]["period"] == "FY2024" for name in ("AWS", "Alibaba", "腾讯", "Huawei")))
        self.assertTrue(all("不是" in investment[name]["analysis"] for name in ("AWS", "Alibaba", "腾讯", "Huawei")))
        self.assertEqual(cloud["investment"]["metric"]["value"], 77658.0)
        self.assertIn("AWS FY2024", cloud["investment"]["metric"]["label"])

    def test_overview_method_and_frontend_do_not_conflate_local_gaps_with_non_disclosure(self):
        self.assertIn("本地知识库", self.snapshot["method"])
        self.assertEqual(
            self.snapshot["data_audit"]["gap_status_counts"],
            {"public_not_found": 5},
        )
        root = Path(__file__).resolve().parents[1]
        app = (root / "web/static/app.js").read_text(encoding="utf-8")
        self.assertIn('gapStatus === "public_not_found" ? "未见公开披露" : "待核验"', app)
        self.assertIn('board.dataset.refreshAligned', app)
        self.assertIn('四域与AI已对齐', app)
        self.assertIn('["≈", "~", "approx"].includes(comparator) ? "约"', app)

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
        self.assertIn("移动客户", result["analysis"])
        self.assertIn("ARPU", result["analysis"])


if __name__ == "__main__":
    unittest.main()

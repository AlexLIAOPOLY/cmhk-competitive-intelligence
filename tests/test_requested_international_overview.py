from __future__ import annotations

import json
import unittest
from pathlib import Path

import cmhk.agent.rag as rag
import agent as xiaojing_agent
import executive_intelligence_pipeline as pipeline
from cmhk.intelligence.executive import _requested_international_domain


ROOT = Path(__file__).resolve().parents[1]


class RequestedInternationalOverviewTests(unittest.TestCase):
    def test_overview_keeps_four_domain_shape_and_uses_requested_carriers(self) -> None:
        payload = json.loads((
            ROOT / "agent_knowledge/global_top5_operators_2016_2025/annual_metrics.json"
        ).read_text(encoding="utf-8"))
        sources = json.loads((
            ROOT / "agent_knowledge/global_top5_operators_2016_2025/sources.json"
        ).read_text(encoding="utf-8"))
        source_registry = {
            str(item.get("source_id") or ""): str(item.get("url") or "")
            for item in sources.get("sources") or []
        }

        domain = _requested_international_domain(payload, source_registry)

        self.assertEqual(domain["index"], "02")
        self.assertEqual(domain["title"], "国际运营商")
        self.assertEqual(
            {item["name"] for item in domain["entities"]},
            {"NTT DOCOMO", "SoftBank Corp.", "SK Telecom", "Singtel"},
        )
        self.assertEqual(
            [focus["id"] for focus in domain["focuses"]],
            ["revenue", "net_profit", "capex", "mobile_arpu"],
        )
        self.assertEqual(
            [focus["label"] for focus in domain["focuses"]],
            ["营收", "净利润", "资本开支", "移动ARPU"],
        )
        self.assertTrue(all(item["unit"] == "百万美元" for item in domain["focuses"][0]["items"]))
        self.assertTrue(all(item["unit"] == "百万美元" for item in domain["focuses"][1]["items"]))
        self.assertTrue(all(item["unit"] == "百万美元" for item in domain["focuses"][2]["items"]))
        self.assertTrue(all(item["unit"] == "美元/月" for item in domain["focuses"][3]["items"]))
        self.assertNotIn("同比", json.dumps(domain["focuses"][:3], ensure_ascii=False))
        self.assertNotIn("利润率", json.dumps(domain["focuses"][:3], ensure_ascii=False))
        self.assertTrue(all(len(focus["items"]) == 4 for focus in domain["focuses"]))
        self.assertTrue(all(len(item["trend"]) == 10 for item in domain["focuses"][0]["items"]))
        self.assertTrue(all(len(item["trend"]) == 10 for item in domain["focuses"][2]["items"]))
        self.assertTrue(all(len(item["trend"]) == 10 for item in domain["focuses"][3]["items"]))
        arpu = {item["name"]: item for item in domain["focuses"][3]["items"]}
        self.assertEqual(arpu["NTT DOCOMO"]["value"], 26.46)
        self.assertEqual(arpu["SoftBank Corp."]["value"], 24.86)
        self.assertEqual(arpu["SK Telecom"]["value"], 19.58)
        self.assertEqual(arpu["Singtel"]["value"], 18.36)
        self.assertNotIn("NTT Group", {item["name"] for item in domain["entities"]})
        available = [item for focus in domain["focuses"] for item in focus["items"] if item["value"] is not None]
        self.assertTrue(all(item["verification_count"] >= 1 for item in available))
        self.assertTrue(all(len(item["source_urls"]) >= 1 for item in available))
        self.assertNotIn("Bharti Airtel", {item["name"] for item in domain["entities"]})
        self.assertNotIn("ARPA", json.dumps(domain, ensure_ascii=False))

    def test_reference_operators_refresh_without_changing_ranking(self) -> None:
        from data_curation.research_plan import ASSIGNMENTS
        from cmhk.intelligence.executive import _analysis_evidence_snapshot
        payload = json.loads((ROOT / "agent_knowledge/global_top5_operators_2016_2025/annual_metrics.json").read_text())
        before = _requested_international_domain(payload)
        expected = ["Verizon", "Deutsche Telekom", "AT&T", "NTT Group", "Bharti Airtel", "Reliance Jio"]
        assigned = {company for task in ASSIGNMENTS for company in task.companies}
        for company in expected:
            self.assertIn("NTT" if company == "NTT Group" else company, assigned)
        for focus in before["focuses"]:
            self.assertEqual([item["name"] for item in focus["reference_items"]], expected)
            self.assertTrue(all(item["ranking_eligible"] is False for item in focus["reference_items"]))
        new_row = dict(next(row for row in payload["rows"] if row["operator"] == "Verizon" and row["metric_key"] == "revenue" and row["year"] == 2025))
        new_row.update(year=2026, period="FY2026", value=999999, official_value=999999)
        payload["rows"].append(new_row)
        after = _requested_international_domain(payload)
        reference = after["focuses"][0]["reference_items"][0]
        self.assertEqual((reference["period"], reference["value"]), ("FY2026", 999999))
        self.assertEqual(reference["trend"][-1]["label"], "FY2026")
        self.assertEqual(before["focuses"][0]["metric"], after["focuses"][0]["metric"])
        self.assertEqual(before["focuses"][0]["insight"], after["focuses"][0]["insight"])
        self.assertEqual(_analysis_evidence_snapshot([before]), _analysis_evidence_snapshot([after]))
        missing = next(item for item in after["focuses"][3]["reference_items"] if item["name"] == "Verizon")
        self.assertIsNone(missing["value"])  # ARPA must not be substituted for ARPU.

    def test_xiaojing_retrieves_new_metric_pairs(self) -> None:
        cases = {
            "Verizon FY2025后付费用户和ARPA是多少？": {"postpaid_connections", "postpaid_arpa"},
            "AT&T FY2025后付费用户和后付费ARPU是多少？": {"postpaid_connections", "postpaid_phone_arpu"},
            "NTT Group FY2025移动电话服务订阅数和移动ARPU是多少？": {"mobile_service_subscriptions", "mobile_arpu"},
        }
        for question, expected in cases.items():
            chunks = rag._global_operator_exact_metric_chunks(
                question, dataset_ids={"global_top5_operators_2016_2025"}
            )
            actual = {
                chunk["text"].split("metric_key=", 1)[1].split(";", 1)[0]
                for chunk in chunks
            }
            self.assertEqual(actual, expected)

    def test_xiaojing_retrieves_single_source_overview_facts_exactly(self) -> None:
        chunks = rag.retrieve_context("中国联通 FY2016 EBITDA和净利润", limit=2)
        self.assertEqual(len(chunks), 2)
        combined = "\n".join(chunk["text"] for chunk in chunks)
        self.assertIn("FY2016=794.98 亿元", combined)
        self.assertIn("FY2016=6.25 亿元", combined)
        self.assertIn("official_single_source_user_accepted_display", combined)

    def test_ntt_generic_ebitda_question_returns_full_official_series(self) -> None:
        chunks = rag._global_operator_exact_metric_chunks(
            "NTT Group FY2016到FY2025 EBITDA",
            dataset_ids={"global_top5_operators_2016_2025"},
        )
        self.assertEqual(len(chunks), 1)
        self.assertIn("metric_key=adjusted_ebitda", chunks[0]["text"])
        self.assertIn("point_count=10", chunks[0]["text"])
        self.assertIn("FY2016=3183.3", chunks[0]["text"])
        self.assertIn("FY2025=3423.3", chunks[0]["text"])

    def test_xiaojing_maps_ntt_postpaid_question_to_explicit_substitute(self) -> None:
        question = (
            "列出Verizon、Deutsche Telekom、AT&T、NTT Group的FY2025"
            "后付费用户数，单位统一为百万，并明确NTT口径。"
        )
        chunks = rag._global_operator_exact_metric_chunks(
            question, dataset_ids={"global_top5_operators_2016_2025"}
        )
        pairs = {
            (
                chunk["text"].split("operator_id=", 1)[1].split(";", 1)[0],
                chunk["text"].split("metric_key=", 1)[1].split(";", 1)[0],
            )
            for chunk in chunks
        }
        self.assertEqual(
            pairs,
            {
                ("verizon", "postpaid_connections"),
                ("deutsche_telekom", "postpaid_connections"),
                ("att", "postpaid_connections"),
                ("ntt_group", "mobile_service_subscriptions"),
            },
        )
        self.assertTrue(any("not labelled postpaid customers" in chunk["text"] for chunk in chunks))
        self.assertTrue(any("不得写成NTT无数值" in chunk["text"] for chunk in chunks))

    def test_xiaojing_compacts_four_ten_year_series_without_losing_values(self) -> None:
        chunks = rag._global_operator_exact_metric_chunks(
            "Verizon、Deutsche Telekom、AT&T、NTT Group从2016到2025的后付费用户数",
            dataset_ids={"global_top5_operators_2016_2025"},
        )
        self.assertEqual(len(chunks), 4)
        by_pair = {
            (
                chunk["text"].split("operator_id=", 1)[1].split(";", 1)[0],
                chunk["text"].split("metric_key=", 1)[1].split(";", 1)[0],
            ): chunk["text"]
            for chunk in chunks
        }
        self.assertTrue(all("point_count=10" in text for text in by_pair.values()))
        self.assertIn("FY2016=108.796", by_pair[("verizon", "postpaid_connections")])
        self.assertIn("FY2025=126.705", by_pair[("verizon", "postpaid_connections")])
        self.assertIn("FY2016=74.88", by_pair[("ntt_group", "mobile_service_subscriptions")])
        self.assertIn("FY2025=93.065", by_pair[("ntt_group", "mobile_service_subscriptions")])
        self.assertIn("不得用有值、xxx或估算", by_pair[("ntt_group", "mobile_service_subscriptions")])

    def test_xiaojing_single_year_followup_still_receives_complete_series(self) -> None:
        chunks = rag._global_operator_exact_metric_chunks(
            "NTT Group FY2016移动电话服务订阅数",
            dataset_ids={"global_top5_operators_2016_2025"},
        )
        self.assertEqual(len(chunks), 1)
        text = chunks[0]["text"]
        self.assertIn("point_count=10", text)
        self.assertIn("FY2016=74.88", text)
        self.assertIn("FY2025=93.065", text)

    def test_xiaojing_preserves_million_unit_when_presenting_fx_rows(self) -> None:
        chunks = rag._global_operator_exact_metric_chunks(
            "比较 SK Telecom 与 Singtel FY2025 营业收入，统一美元",
            dataset_ids={"global_top5_operators_2016_2025"},
        )
        combined = "\n".join(chunk["text"] for chunk in chunks)
        self.assertIn("17099213 KRW_million", combined)
        self.assertIn("14146 SGD_million", combined)
        self.assertIn("原币单位后缀_million表示数值以百万原币计", combined)
        self.assertIn("不得只把单位改写成亿而不同时换算数值", combined)

    def test_xiaojing_structured_four_carrier_answer_is_complete_and_exact(self) -> None:
        result = xiaojing_agent._structured_global_postpaid_answer(
            "Verizon、Deutsche Telekom、AT&T、NTT Group从2016到2025是否各有10个后付费用户年度点？",
            {"global_top5_operators_2016_2025"},
        )
        self.assertIsNotNone(result)
        answer, evidence = result
        self.assertIn("Verizon | 10 | 108.796 | 126.705", answer)
        self.assertIn("Deutsche Telekom | 10 | 34.427 | 116.445", answer)
        self.assertIn("AT&T | 10 | 77.372 | 90.879", answer)
        self.assertIn("NTT Group | 10 | 74.88 | 93.065", answer)
        self.assertIn("无插值、无换算", answer)
        self.assertIn("非后付费客户数", answer)
        self.assertEqual(len(evidence["series"]), 4)

    def test_mobile_arpu_ai_gate_rejects_non_comparable_pairing(self) -> None:
        snapshot = pipeline._analysis_input_snapshot()
        focus = next(
            focus
            for domain in snapshot["domains"] if domain["id"] == "international"
            for focus in domain["focuses"] if focus["id"] == "mobile_arpu"
        )
        bad_analysis = (
            "NTT DOCOMO移动ARPU为26.46美元/月；"
            "SK Telecom客户经营底盘较强，两家定义不同，不可直接混排。"
        )
        self.assertIn(
            "两家日系运营商",
            pipeline._focus_gate_error("international", "mobile_arpu", bad_analysis, focus),
        )


if __name__ == "__main__":
    unittest.main()

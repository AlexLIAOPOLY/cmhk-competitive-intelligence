from __future__ import annotations

import json
import unittest
from pathlib import Path

import cmhk.agent.rag as rag
import executive_intelligence_pipeline as pipeline
from cmhk.intelligence.executive import _requested_international_domain


ROOT = Path(__file__).resolve().parents[1]


class RequestedInternationalOverviewTests(unittest.TestCase):
    def test_overview_keeps_four_domain_shape_and_uses_requested_carriers(self) -> None:
        payload = json.loads((
            ROOT / "agent_knowledge/global_top5_operators_2016_2025/annual_metrics.json"
        ).read_text(encoding="utf-8"))

        domain = _requested_international_domain(payload)

        self.assertEqual(domain["index"], "02")
        self.assertEqual(domain["title"], "国际运营商")
        self.assertEqual(
            {item["name"] for item in domain["entities"]},
            {"Verizon", "Deutsche Telekom", "AT&T", "NTT Group"},
        )
        self.assertEqual(
            [focus["id"] for focus in domain["focuses"]],
            ["revenue", "ebitda", "net_profit", "postpaid_arpu"],
        )
        self.assertEqual(
            [focus["label"] for focus in domain["focuses"]],
            ["营收", "EBITDA", "净利润", "后付费用户数"],
        )
        self.assertTrue(all(item["unit"] == "十亿美元" for item in domain["focuses"][0]["items"]))
        self.assertTrue(all(item["unit"] == "十亿美元" for item in domain["focuses"][1]["items"]))
        self.assertTrue(all(item["unit"] == "十亿美元" for item in domain["focuses"][2]["items"]))
        self.assertTrue(all(item["components"][1]["unit"] == "美元/月" for item in domain["focuses"][3]["items"]))
        self.assertNotIn("同比", json.dumps(domain["focuses"][:3], ensure_ascii=False))
        self.assertNotIn("利润率", json.dumps(domain["focuses"][:3], ensure_ascii=False))
        self.assertTrue(all(len(focus["items"]) == 4 for focus in domain["focuses"]))
        self.assertTrue(all(len(item["trend"]) == 10 for item in domain["focuses"][0]["items"]))
        self.assertTrue(all(len(item["trend"]) == 10 for item in domain["focuses"][2]["items"]))
        self.assertTrue(all(len(item["trend"]) == 10 for item in domain["focuses"][3]["items"]))
        postpaid = {item["name"]: item for item in domain["focuses"][3]["items"]}
        self.assertEqual(postpaid["Verizon"]["value"], 126.7)
        self.assertEqual(postpaid["Deutsche Telekom"]["value"], 116.44)
        self.assertEqual(postpaid["AT&T"]["value"], 90.88)
        self.assertEqual(postpaid["NTT Group"]["value"], 93.06)
        self.assertIn("替代口径", postpaid["NTT Group"]["detail"])
        self.assertTrue(all(item["verification_count"] >= 3 for item in domain["entities"]))
        self.assertNotIn("Comcast", json.dumps(domain, ensure_ascii=False))
        self.assertNotIn("Bharti Airtel", json.dumps(domain, ensure_ascii=False))
        self.assertIn("ARPA", json.dumps(domain, ensure_ascii=False))

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

    def test_postpaid_ai_gate_rejects_cross_company_arpu_pairing(self) -> None:
        snapshot = pipeline._analysis_input_snapshot()
        focus = next(
            focus
            for domain in snapshot["domains"] if domain["id"] == "international"
            for focus in domain["focuses"] if focus["id"] == "postpaid_arpu"
        )
        bad_analysis = (
            "Verizon后付费连接达126.7百万，ARPU为50.71美元/月；"
            "NTT Group手机订阅52.97百万，ARPU为26.48美元/月；"
            "Verizon为ARPA口径，两家定义不同，不可直接混排。"
        )
        self.assertIn(
            "正确配对",
            pipeline._focus_gate_error("international", "postpaid_arpu", bad_analysis, focus),
        )


if __name__ == "__main__":
    unittest.main()

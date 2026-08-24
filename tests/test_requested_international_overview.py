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

from __future__ import annotations

import unittest

from data_curation.workflow import _accepted_cache_items, _source_rank, audit_quality, plan_gaps


def candidate(**overrides):
    value = {
        "id": "fact-1",
        "company": "HKT",
        "metric": "运营收入/总收益",
        "value": "36,553",
        "basis": "Revenue 36,553，单位为百万HKD。",
        "note": "",
        "status": "ok",
        "entity_supported": True,
        "metric_supported": True,
        "value_supported": True,
        "confidence": 0.95,
        "source_score": 1.0,
        "source_tier": "official",
        "row_ref": "row_2",
        "sources": ["https://www.hkt.com/results"],
        "quality_score": 0.0,
        "decision": "pending",
        "reasons": [],
    }
    value.update(overrides)
    return value


class DataCurationTests(unittest.TestCase):
    def test_official_source_has_highest_rank(self):
        self.assertEqual(_source_rank(["https://www.hkt.com/results"]), (1.0, "official"))
        self.assertEqual(_source_rank(["https://stockanalysis.com/quote/hkg/6823"]), (0.62, "commercial"))

    def test_numeric_value_inherits_explicit_context_unit(self):
        result = audit_quality({"candidates": [candidate()]})
        fact = result["candidates"][0]
        self.assertEqual(fact["value"], "36,553百万港元")
        self.assertEqual(fact["decision"], "accepted")

    def test_numeric_value_inherits_unit_from_note(self):
        result = audit_quality(
            {
                "candidates": [
                    candidate(
                        company="iCable",
                        metric="EBITDA",
                        value="-302.59",
                        basis="财务表列示 EBITDA -302.59。",
                        note="单位为百万港元",
                    )
                ]
            }
        )
        fact = result["candidates"][0]
        self.assertEqual(fact["value"], "-302.59百万港元")
        self.assertEqual(fact["decision"], "accepted")

    def test_value_recovers_explicit_number_from_basis(self):
        result = audit_quality(
            {
                "candidates": [
                    candidate(
                        company="SmarTone",
                        metric="服务收入",
                        value="与去年同期相近",
                        basis="Service revenue was similar to the same period last year at $2,303 million.",
                    )
                ]
            }
        )
        fact = result["candidates"][0]
        self.assertIn("2,303 million", fact["value"])
        self.assertEqual(fact["decision"], "accepted")

    def test_non_listed_company_not_applicable_is_publishable(self):
        result = audit_quality(
            {
                "candidates": [
                    candidate(
                        company="HGC",
                        metric="派息",
                        value="未提取到有效数据",
                        basis="不适用（HGC为非上市主体）",
                        status="unavailable",
                        value_supported=False,
                        confidence=0.2,
                    )
                ]
            }
        )
        fact = result["candidates"][0]
        self.assertEqual(fact["value"], "不适用（非上市主体）")
        self.assertEqual(fact["decision"], "accepted")

    def test_audit_reentry_clears_stale_audit_reasons(self):
        result = audit_quality(
            {
                "candidates": [
                    candidate(
                        company="HKT",
                        metric="EBITDA",
                        value="10,064",
                        basis="EBITDA 10,064，单位应为百万港元。",
                        reasons=["未通过指标格式与单位门禁"],
                        decision="rejected",
                    )
                ]
            }
        )
        fact = result["candidates"][0]
        self.assertEqual(fact["value"], "10,064百万港元")
        self.assertEqual(fact["decision"], "accepted")
        self.assertNotIn("未通过指标格式与单位门禁", fact["reasons"])

    def test_negative_evidence_is_not_recovered_as_qualitative_fact(self):
        result = audit_quality(
            {
                "candidates": [
                    candidate(
                        metric="战略合作",
                        value="未提取到有效数据",
                        basis="片段仅列出合作栏目名称，未提供具体合作伙伴或事项。",
                        status="unavailable",
                        value_supported=False,
                        confidence=0.2,
                    )
                ]
            }
        )
        fact = result["candidates"][0]
        self.assertEqual(fact["status"], "unavailable")
        self.assertEqual(fact["decision"], "rejected")

    def test_navigation_text_is_rejected(self):
        result = audit_quality(
            {
                "candidates": [
                    candidate(
                        value="36,553百万港元",
                        basis="Skip to main content Log In Sign Up",
                    )
                ]
            }
        )
        self.assertEqual(result["candidates"][0]["decision"], "rejected")

    def test_recrawl_regression_keeps_previous_best(self):
        best = candidate(value="36,553百万港元", decision="accepted", quality_score=0.99)
        degraded = candidate(
            id="fact-2",
            status="unavailable",
            decision="rejected",
            reasons=["抽取结果不可用"],
        )
        result = plan_gaps(
            {
                "candidates": [degraded],
                "best_candidates": [best],
                "best_accepted_count": 1,
                "recrawl_round": 1,
                "allow_recrawl": True,
                "max_recrawl_rounds": 1,
                "node_events": [],
            }
        )
        self.assertEqual(result["candidates"][0]["decision"], "accepted")
        self.assertEqual(result["recrawl_tasks"], [])

    def test_cache_semantic_key_keeps_best_previous_fact(self):
        previous = {
            "old-id": {
                "status": "ok",
                "company": "HKT",
                "metric": "派息",
                "row_ref": "row_2",
                "quality_score": 0.95,
            }
        }
        accepted = _accepted_cache_items(previous)
        self.assertIn("HKT|派息|row_2", accepted)
        self.assertEqual(accepted["HKT|派息|row_2"]["quality_score"], 0.95)


if __name__ == "__main__":
    unittest.main()

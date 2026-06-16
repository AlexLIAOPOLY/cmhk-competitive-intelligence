from __future__ import annotations

import unittest
from unittest.mock import patch

from company_metrics import (
    _apply_ai_cache,
    _apply_brand_market_reaction_not_applicable,
    build_company_metrics_payload,
    _cache_item_brand_consistent,
)
from data_curation.workflow import (
    _accepted_cache_items,
    _cache_item_metric_semantically_valid,
    _candidate_from_cache,
    _source_rank,
    audit_quality,
    plan_gaps,
    validate_entities,
)
from data_curation.schemas import EvidenceTask


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
    def test_plain_5g_cannot_be_published_as_5g_advanced(self) -> None:
        task = EvidenceTask(
            id="jio-5ga",
            company="Jio",
            metric="5G-A",
            current_value="",
            raw_text="Jio Hyperlite offers 5G-as-a-Service and is compliant with 3GPP.",
            sources=["https://www.jio.com/business/5g/"],
            row_ref="row_19",
            source_score=0.72,
            source_tier="public",
            evidence_hash="hash",
        )
        candidate_fact = _candidate_from_cache(
            task,
            {
                "status": "ok",
                "value": "Jio Hyperlite 5G Stack",
                "basis": "The source describes a 5G stack.",
                "entity_supported": True,
                "metric_supported": True,
                "value_supported": True,
                "confidence": 0.9,
            },
        )
        self.assertEqual(candidate_fact.status, "unavailable")
        self.assertFalse(candidate_fact.metric_supported)

    def test_network_api_cannot_be_published_as_open_ran(self) -> None:
        task = EvidenceTask(
            id="dt-open-ran",
            company="Deutsche Telekom",
            metric="Open RAN",
            current_value="",
            raw_text="Network APIs and T-DevEdge platform launched.",
            sources=["https://www.telekom.com/network-apis"],
            row_ref="row_20",
            source_score=1.0,
            source_tier="official",
            evidence_hash="hash",
        )
        candidate_fact = _candidate_from_cache(
            task,
            {
                "status": "ok",
                "value": "Network APIs launched",
                "basis": "The source describes network APIs.",
                "entity_supported": True,
                "metric_supported": True,
                "value_supported": True,
                "confidence": 0.9,
            },
        )
        self.assertEqual(candidate_fact.status, "unavailable")
        self.assertFalse(candidate_fact.metric_supported)

    def test_cache_protection_rejects_semantically_wrong_5g_advanced(self) -> None:
        self.assertFalse(
            _cache_item_metric_semantically_valid(
                {
                    "metric": "5G-A",
                    "value": "Jio Hyperlite 5G Stack",
                    "basis": "The source describes 5G-as-a-Service.",
                }
            )
        )

    def test_deterministic_extractor_overrides_stale_unavailable_cache(self) -> None:
        from data_curation.workflow import extract_facts

        task = {
            "id": "cm-dict",
            "company": "中国移动",
            "metric": "DICT",
            "current_value": "",
            "raw_text": (
                "AI services include data algorithms, embodied intelligence, "
                "digital intelligence culture, digital intelligence e-commerce "
                "and industry digital intelligence services."
            ),
            "sources": ["https://www.chinamobileltd.com/en/ir/reports/ar2025.pdf"],
            "row_ref": "row_21",
            "evidence_hash": "test-hash",
            "source_score": 1.0,
            "source_tier": "official",
        }
        state = {
            "tasks": [task],
            "existing_items": {
                "cm-dict": {
                    "status": "unavailable",
                    "value": "未提取到有效数据",
                    "confidence": 0.1,
                }
            },
            "online_ai": False,
            "batch_size": 25,
        }
        result = extract_facts(state)
        self.assertEqual(result["candidates"][0]["status"], "ok")
        self.assertIn("行业数智服务", result["candidates"][0]["value"])

    def test_ai_cache_falls_back_to_preserved_accepted_semantic_item(self):
        rows = [
            {
                "id": "current-id",
                "company": "HKT",
                "metric": "资费",
                "rowRef": "row_3",
                "sourceType": "public-crawl",
                "value": "网页残片",
                "detail": "",
            }
        ]
        cache = {
            "schemaVersion": 3,
            "items": {
                "current-id": {
                    "company": "HKT",
                    "metric": "资费",
                    "row_ref": "row_3",
                    "status": "unavailable",
                    "value": "未提取到有效数据",
                },
                "preserved-id": {
                    "company": "HKT",
                    "metric": "资费",
                    "row_ref": "row_3",
                    "status": "ok",
                    "value": "1000M家宽月费108港元",
                    "basis": "HKT官方套餐页",
                    "entity_supported": True,
                    "metric_supported": True,
                    "value_supported": True,
                    "confidence": 0.96,
                },
            },
        }
        with patch("company_metrics._read_json", return_value=cache):
            cleaned = _apply_ai_cache(rows)
        self.assertEqual(cleaned[0]["aiStatus"], "ok")
        self.assertEqual(cleaned[0]["value"], "1000M家宽月费108港元")

    def test_brand_market_reaction_is_deterministically_not_applicable(self):
        row = {"company": "3HK", "metric": "市场反应", "value": "错误的股息片段"}
        self.assertTrue(_apply_brand_market_reaction_not_applicable(row))
        self.assertEqual(row["value"], "不适用（品牌非独立上市主体）")
        self.assertEqual(row["aiStatus"], "ok")

    def test_company_metrics_dashboard_excludes_non_company_subjects(self):
        payload = build_company_metrics_payload()
        companies = set(payload["companies"])
        self.assertFalse({"行业资讯", "政治新闻", "政治资讯", "经济资讯", "社会资讯", "3HK"} & companies)
        self.assertIn("3HK / Hutchison", companies)
        self.assertEqual(payload["summary"]["publishableAiFacts"], payload["summary"]["publishedAiFacts"])
        self.assertEqual(payload["summary"]["suppressedRecords"], 0)

    def test_brand_cache_rejects_other_brand_qualitative_fact(self):
        self.assertFalse(
            _cache_item_brand_consistent(
                {
                    "company": "csl",
                    "metric": "产品规格",
                    "value": "HKT Enterprise Solutions推出Open API服务",
                    "basis": "服务运行在1O1O 5G网络上。",
                }
            )
        )
        self.assertTrue(
            _cache_item_brand_consistent(
                {
                    "company": "1O1O",
                    "metric": "企业专线",
                    "value": "HKT Enterprise Solutions提供Open API服务",
                    "basis": "服务明确运行在1O1O 5G网络上。",
                }
            )
        )

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

    def test_non_listed_brand_market_reaction_is_publishable(self):
        result = audit_quality(
            {
                "candidates": [
                    candidate(
                        company="csl",
                        metric="市场反应",
                        value="未提取到有效数据",
                        basis="csl为HKT旗下品牌，不是独立上市主体。",
                        status="unavailable",
                        entity_supported=False,
                        metric_supported=False,
                        value_supported=False,
                        confidence=0.1,
                    )
                ]
            }
        )
        fact = result["candidates"][0]
        self.assertEqual(fact["value"], "不适用（品牌非独立上市主体）")
        self.assertEqual(fact["decision"], "accepted")

    def test_offline_entity_evidence_overrides_missing_model_checkbox(self):
        fact = candidate(
            company="HKT",
            entity_supported=False,
            metric_supported=True,
            value_supported=True,
        )
        result = validate_entities(
            {
                "tasks": [
                    {
                        "id": fact["id"],
                        "company": "HKT",
                        "metric": fact["metric"],
                        "raw_text": "HKT total revenue was HK$36,553 million.",
                        "sources": ["https://www.hkt.com/results"],
                    }
                ],
                "candidates": [fact],
            }
        )
        self.assertTrue(result["candidates"][0]["entity_supported"])
        self.assertNotEqual(result["candidates"][0]["decision"], "rejected")

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

    def test_negative_numeric_sentence_is_not_recovered_as_fact(self):
        result = audit_quality(
            {
                "candidates": [
                    candidate(
                        metric="5G用户数",
                        value="未提取到有效数据",
                        basis="片段未提供5G用户数具体数字，仅有5G栏目名称。",
                        status="unavailable",
                        metric_supported=False,
                        value_supported=False,
                        confidence=0.1,
                    )
                ]
            }
        )
        fact = result["candidates"][0]
        self.assertEqual(fact["status"], "unavailable")
        self.assertEqual(fact["decision"], "rejected")

    def test_home_broadband_package_price_passes_gate(self):
        result = audit_quality(
            {
                "candidates": [
                    candidate(
                        metric="家宽套餐",
                        value="1000M光纤入屋宽带低至HK$108/月",
                        basis="官网列示1000M光纤入屋宽带低至HK$108/月。",
                    )
                ]
            }
        )
        self.assertEqual(result["candidates"][0]["decision"], "accepted")

    def test_metric_semantic_failure_cannot_enter_review(self):
        result = audit_quality(
            {
                "candidates": [
                    candidate(
                        metric="促销折扣",
                        value="片段未提供具体促销活动。",
                        basis="片段只包含一般品牌介绍。",
                        status="ok",
                        metric_supported=False,
                        value_supported=True,
                        confidence=0.9,
                    )
                ]
            }
        )
        fact = result["candidates"][0]
        self.assertEqual(fact["decision"], "rejected")
        self.assertIn("指标语义未通过", fact["reasons"])

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

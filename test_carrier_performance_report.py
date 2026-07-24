from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import mock

import generate_carrier_performance_report as report


def sample_sections() -> list[dict]:
    return [
        {
            "company": "测试运营商",
            "title": "测试运营商关键摘要",
            "items": [
                "派息：全年每股派息0.50港元，同比增长5%。",
                "资本开支：2025年资本开支100亿元。",
                "战略升级：围绕AI和云服务升级，收入达到200亿元；产品目录和重复信息较多，需要压缩。",
                "券商观点：机构维持买入评级，目标价10港元。",
                "市场反应：股价由8港元升至9港元，上涨12.5%。",
            ],
        }
    ]


class CarrierPerformanceAiEditorTests(unittest.TestCase):
    def test_rewrite_keeps_structure_and_accepts_grounded_fields(self) -> None:
        response = {
            "companies": [
                {
                    "company": "测试运营商",
                    "fields": {
                        "dividend": "全年每股派息0.50港元，同比增长5%。",
                        "capex": "2025年资本开支100亿元。",
                        "strategy": "公司围绕AI和云服务推进升级，相关收入达到200亿元。",
                        "broker": "机构维持买入评级，目标价10港元。",
                        "market": "股价由8港元升至9港元，上涨12.5%。",
                    },
                }
            ]
        }
        with TemporaryDirectory() as temp_dir, mock.patch.object(
            report, "PERFORMANCE_AI_AUDIT_PATH", Path(temp_dir) / "audit.json"
        ):
            rewritten = report.rewrite_performance_sections_with_ai(
                sample_sections(), ai_client=lambda _packs: (response, "test-model"), progress=lambda _message: None
            )

        self.assertEqual(len(rewritten), 1)
        self.assertEqual(len(rewritten[0]["items"]), 5)
        self.assertIn("公司围绕AI和云服务推进升级", rewritten[0]["items"][2])

    def test_invented_number_falls_back_to_locked_evidence(self) -> None:
        response = {
            "companies": [
                {
                    "company": "测试运营商",
                    "fields": {
                        "dividend": "全年每股派息0.80港元，同比增长8%。",
                    },
                }
            ]
        }
        with TemporaryDirectory() as temp_dir, mock.patch.object(
            report, "PERFORMANCE_AI_AUDIT_PATH", Path(temp_dir) / "audit.json"
        ):
            rewritten = report.rewrite_performance_sections_with_ai(
                sample_sections(), ai_client=lambda _packs: (response, "test-model"), progress=lambda _message: None
            )

        self.assertEqual(rewritten[0]["items"][0], sample_sections()[0]["items"][0])

    def test_model_failure_preserves_existing_summary(self) -> None:
        def fail(_packs):
            raise RuntimeError("offline")

        with TemporaryDirectory() as temp_dir, mock.patch.object(
            report, "PERFORMANCE_AI_AUDIT_PATH", Path(temp_dir) / "audit.json"
        ):
            rewritten = report.rewrite_performance_sections_with_ai(
                sample_sections(), ai_client=fail, progress=lambda _message: None
            )

        self.assertEqual(rewritten, sample_sections())

    def test_online_research_is_passed_to_ai_and_can_support_a_new_number(self) -> None:
        response = {
            "companies": [
                {
                    "company": "测试运营商",
                    "fields": {
                        "capex": "2026年资本开支计划为88亿元。",
                    },
                }
            ]
        }
        captured_packs = []

        def ai_client(packs):
            captured_packs.extend(packs)
            return response, "test-model"

        web_research = {
            "测试运营商": {
                "query": "测试运营商 2026 资本开支",
                "provider": "unit",
                "results": [
                    {
                        "title": "测试运营商公布2026年资本开支计划",
                        "url": "https://example.com/capex",
                        "snippet": "公司公布2026年资本开支计划为88亿元。",
                    }
                ],
                "error": "",
            }
        }
        with TemporaryDirectory() as temp_dir, mock.patch.object(
            report, "PERFORMANCE_AI_AUDIT_PATH", Path(temp_dir) / "audit.json"
        ):
            rewritten = report.rewrite_performance_sections_with_ai(
                sample_sections(),
                ai_client=ai_client,
                progress=lambda _message: None,
                web_research=web_research,
            )
            audit = (Path(temp_dir) / "audit.json").read_text(encoding="utf-8")

        self.assertEqual(captured_packs[0]["web_research"], web_research["测试运营商"])
        self.assertIn("88亿元", rewritten[0]["items"][1])
        self.assertIn("https://example.com/capex", audit)

    def test_company_research_fails_closed_when_all_searches_are_empty(self) -> None:
        def empty_search(query, _limit):
            return {"query": query, "provider": "", "results": [], "error": "offline"}

        with self.assertRaisesRegex(RuntimeError, "不能静默跳过"):
            report.research_performance_companies_online(
                sample_sections(),
                search_client=empty_search,
                progress=lambda _message: None,
            )

    def test_company_research_repairs_a_first_round_search_gap(self) -> None:
        calls = []

        def second_round_search(query, _limit):
            calls.append(query)
            if len(calls) == 1:
                return {"query": query, "provider": "", "results": [], "error": "no result"}
            return {
                "query": query,
                "provider": "unit",
                "results": [
                    {
                        "title": "测试运营商官方年报",
                        "url": "https://example.com/annual-report",
                        "snippet": "测试运营商公布最新年度业绩。",
                    }
                ],
                "error": "",
            }

        researched = report.research_performance_companies_online(
            sample_sections(),
            search_client=second_round_search,
            progress=lambda _message: None,
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(researched["测试运营商"]["provider"], "unit")


if __name__ == "__main__":
    unittest.main()

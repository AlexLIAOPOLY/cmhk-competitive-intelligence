from __future__ import annotations

import json
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import mock

from docx import Document

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
    def test_editor_requests_are_split_into_small_parallel_batches(self) -> None:
        packs = [
            {
                "company": f"测试运营商{index}",
                "title": "测试",
                "evidence": {},
                "web_research": {},
            }
            for index in range(5)
        ]
        batch_sizes = []

        def ai_client(batch):
            batch_sizes.append(len(batch))
            return {
                "companies": [
                    {"company": pack["company"], "fields": {}} for pack in batch
                ]
            }, "test-model"

        returned, model, failed = report.call_performance_editor_batches(
            packs,
            ai_client=ai_client,
            progress=lambda _message: None,
        )

        self.assertEqual(sorted(batch_sizes), [1, 2, 2])
        self.assertEqual(len(returned), 5)
        self.assertEqual(model, "test-model")
        self.assertEqual(failed, set())

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

        limitations = []
        messages = []
        with TemporaryDirectory() as temp_dir, mock.patch.object(
            report, "PERFORMANCE_AI_AUDIT_PATH", Path(temp_dir) / "audit.json"
        ):
            rewritten = report.rewrite_performance_sections_with_ai(
                sample_sections(),
                ai_client=fail,
                progress=messages.append,
                limitations=limitations,
            )

        self.assertEqual(rewritten, sample_sections())
        self.assertTrue(any(item["stage"] == "ai_batch" for item in limitations))
        self.assertTrue(any("[业绩摘要局限][ai_batch]" in message for message in messages))

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

    def test_company_research_records_limitations_and_continues_when_searches_are_empty(self) -> None:
        def empty_search(query, _limit):
            return {"query": query, "provider": "", "results": [], "error": "offline"}

        limitations = []
        messages = []
        researched = report.research_performance_companies_online(
            sample_sections(),
            search_client=empty_search,
            progress=messages.append,
            limitations=limitations,
        )

        self.assertFalse(researched["测试运营商"]["results"])
        self.assertEqual(limitations[0]["stage"], "web_research")
        self.assertIn("两轮公开网页搜索", limitations[0]["reason"])
        self.assertTrue(any("[业绩摘要局限][web_research]" in message for message in messages))

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

    def test_missing_template_never_switches_to_a_different_format(self) -> None:
        model = report.fallback_performance_model()
        with TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            output = temp / "业绩摘要.docx"
            with (
                mock.patch.object(report, "TEMPLATE_PATH", temp / "missing-template.docx"),
                mock.patch.object(report, "build_dynamic_model", return_value=model),
                mock.patch.object(report, "render_emergency_performance_docx") as emergency,
            ):
                with self.assertRaisesRegex(RuntimeError, "保持原版式"):
                    report.render_report(output_path=output, archive=False)
                self.assertFalse(output.exists())
                emergency.assert_not_called()

    def test_unresolved_sources_keep_report_marked_limited(self) -> None:
        model = {"sections": [], "generationLimitations": [], "researchAudit": {"unresolved": [{"field": "broker"}]}}
        self.assertEqual(report.sanitize_performance_model(model)["generationMode"], "limited")

    def test_report_removes_opening_explanation_and_keeps_template_fonts(self) -> None:
        from docx.oxml.ns import qn
        model = report.fallback_performance_model()
        model['sections'] = sample_sections()
        with TemporaryDirectory() as folder:
            path = report.render_report(output_path=Path(folder)/'业绩摘要.docx', archive=False, model=model)
            document = Document(path)
        text = '\n'.join(p.text for p in document.paragraphs)
        self.assertNotIn(model['subtitle'], text)
        self.assertNotIn(model['intro'], text)
        self.assertEqual(document.paragraphs[0].text, model['title'])
        self.assertEqual(document.paragraphs[1].text, model['table_caption'])
        self.assertEqual(document.paragraphs[0].runs[0].font.size.pt, 20)
        for table in document.tables:
            for row in table.rows:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        for run in paragraph.runs:
                            self.assertEqual(run.font.name, 'FangSong')
                            self.assertEqual(run.font.size.pt, 12)
                            self.assertEqual(run._r.rPr.rFonts.get(qn('w:eastAsia')), 'FangSong')
        body = next(p for p in document.paragraphs if p.text.startswith('1. 派息'))
        self.assertEqual(body.runs[1].font.size.pt, 14)
        self.assertFalse(body.runs[1].bold)

    def test_sources_leave_body_but_financial_qualifiers_and_broker_dates_remain(self) -> None:
        cases = [
            ("派息", "每股15.5港仙（2025年2月28日：每股15.5港仙）（含税）。（来源：公司公告（2026年4月24日））", "每股15.5港仙（2025年2月28日：每股15.5港仙）（含税）。"),
            ("资本开支", "资本开支现金流（负值表示流出）-169百万港元。", "资本开支现金流（负值表示流出）-169百万港元。"),
            ("市场反应", "据StockAnalysis 2026年9月10日16:08 HKT，股价4.605港元（+1.21%）。", "截至2026年9月10日16:08 HKT，股价4.605港元（+1.21%）。"),
            ("券商观点", "摩根士丹利买入目标价14港元（2026-07-29）。（来源：经济通，2026-09-10）", "摩根士丹利买入目标价14港元（2026-07-29）。"),
            ("战略升级", "公司发展多元化收入来源。", "公司发展多元化收入来源。"),
        ]
        for label, before, expected in cases:
            with self.subTest(label=label):
                actual = report.performance_body_without_sources(before, label)
                self.assertEqual(actual, expected)
                self.assertEqual(report.performance_body_without_sources(actual, label), expected)

    def test_public_commentary_keeps_its_identity_without_source_furniture(self) -> None:
        before = "据观点网2026年8月27日公开报道（非机构评级），收入2.44亿港元；该报道为公开信息整理，不构成投资建议。"
        self.assertEqual(report.performance_body_without_sources(before, "券商观点"), "公开评论指出，收入2.44亿港元。")

    def test_report_sources_remain_in_sidecar_instead_of_document(self) -> None:
        model = report.fallback_performance_model()
        model['sections'] = sample_sections()
        model['sections'][0]['items'][0] += '（来源：公司业绩公告，2026年8月13日）'
        model['researchAudit'] = {'sources': ['https://example.com/results']}
        with TemporaryDirectory() as folder:
            path = report.render_report(output_path=Path(folder)/'业绩摘要.docx', archive=False, model=model)
            text = '\n'.join(p.text for p in Document(path).paragraphs)
            audit = json.loads(path.with_suffix('.quality.json').read_text())
        self.assertNotIn('来源：', text)
        self.assertIn('全年每股派息0.50港元，同比增长5%。', text)
        self.assertEqual(audit['researchAudit'], model['researchAudit'])
        self.assertIn('来源：', audit['sourceAttributionEdits'][0]['original'])

    def test_generation_uses_independent_agent_without_shared_refresh(self) -> None:
        with (
            mock.patch.object(report, "refresh_feishu_mirror") as feishu,
            mock.patch.object(report, "crawl_carrier_sources") as crawl,
            mock.patch("cmhk.reporting.performance_agent.build_model", return_value={"sentinel": True}) as agent,
        ):
            self.assertEqual(report.build_dynamic_model(), {"sentinel": True})
        agent.assert_called_once()
        feishu.assert_not_called()
        crawl.assert_not_called()


if __name__ == "__main__":
    unittest.main()

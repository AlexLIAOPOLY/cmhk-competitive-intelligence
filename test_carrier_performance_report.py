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


if __name__ == "__main__":
    unittest.main()

import json
import unittest
from unittest.mock import patch

import web_app


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        content = (
            "竞争格局｜两家公司流失率差距由0.2个百分点收窄至0.1个百分点，竞争呈收敛。\n"
            "公司定位｜HKT由0.9%降至0.8%，SmarTone由0.8%降至0.7%，双方留存压力均缓和。\n"
            "业务含义｜较低流失率可能反映后付客户稳定性增强，但0.1个百分点差距不足以代表整体经营优劣。"
        )
        return json.dumps({"choices": [{"message": {"content": content}}]}).encode()


class CompetitorInsightTests(unittest.TestCase):
    def payload(self):
        data = json.loads(web_app.COMPETITOR_WORKBENCH_DATA_PATH.read_text(encoding="utf-8"))
        return {
            "requestId": "selection-1",
            "companies": ["HKT", "SmarTone"],
            "metric": {"key": "mobile_postpaid_churn", "label": "移动后付费流失率"},
            "years": [2020, 2021, 2022],
            "evidenceVersion": data["evidenceVersion"],
        }

    def test_prompt_contains_only_selected_table(self):
        captured = {}

        def open_request(request, timeout):
            captured["body"] = json.loads(request.data.decode())
            captured["timeout"] = timeout
            return _Response()

        payload = self.payload()
        config = {"base_url": web_app.INTERNAL_AI_BASE_URL, "api_key": "test", "model": "test-model"}
        with patch("web_app.load_ai_config", return_value=config), patch("web_app.wait_for_internal_ai_slot"), patch(
            "web_app.urllib.request.urlopen", side_effect=open_request
        ):
            result = web_app.generate_competitor_insight(payload)

        self.assertEqual(result["requestId"], "selection-1")
        self.assertIn("HKT\t2020\t=\t0.9\tpercent", captured["body"]["messages"][1]["content"])
        self.assertIn("官方来源", captured["body"]["messages"][1]["content"])
        self.assertNotIn("RAG", captured["body"]["messages"][1]["content"])
        self.assertEqual(len(result["insights"]), 3)
        self.assertIn("竞争格局", result["insights"][0])
        self.assertIn("不是复述数据", captured["body"]["messages"][0]["content"])
        self.assertIn("公司层面的竞争洞察", captured["body"]["messages"][0]["content"])
        self.assertIn("所选公司都必须被覆盖", captured["body"]["messages"][0]["content"])
        self.assertIn("指标解释边界", captured["body"]["messages"][1]["content"])
        self.assertIn("客户留存压力", captured["body"]["messages"][1]["content"])

    def test_browser_cells_are_not_trusted(self):
        captured = {}

        def open_request(request, timeout):
            captured["body"] = json.loads(request.data.decode())
            return _Response()

        payload = self.payload()
        payload["cells"] = [{"company": "HKT", "year": 2020, "value": 999999, "unit": "fake"}]
        config = {"base_url": web_app.INTERNAL_AI_BASE_URL, "api_key": "test", "model": "test-model"}
        with patch("web_app.load_ai_config", return_value=config), patch("web_app.wait_for_internal_ai_slot"), patch(
            "web_app.urllib.request.urlopen", side_effect=open_request
        ):
            web_app.generate_competitor_insight(payload)
        prompt = captured["body"]["messages"][1]["content"]
        self.assertNotIn("999999", prompt)
        self.assertNotIn("fake", prompt)

    def test_model_receives_only_common_comparison_years(self):
        captured = {}

        def open_request(request, timeout):
            captured["body"] = json.loads(request.data.decode())
            return _Response()

        payload = self.payload()
        payload["metric"] = {"key": "mobile_postpaid_exit_arpu", "label": "移动后付期末ARPU"}
        payload["years"] = [2018, 2019, 2020, 2021, 2022]
        config = {"base_url": web_app.INTERNAL_AI_BASE_URL, "api_key": "test", "model": "test-model"}
        with patch("web_app.load_ai_config", return_value=config), patch("web_app.wait_for_internal_ai_slot"), patch(
            "web_app.urllib.request.urlopen", side_effect=open_request
        ):
            web_app.generate_competitor_insight(payload)

        prompt = captured["body"]["messages"][1]["content"]
        self.assertIn("共同首尾锚点：2020—2022", prompt)
        self.assertNotIn("HKT\t2018", prompt)
        self.assertNotIn("HKT\t2019", prompt)
        self.assertIn("SmarTone\t2022", prompt)

    def test_rejects_stale_evidence_version(self):
        payload = self.payload()
        payload["evidenceVersion"] = "stale"
        with self.assertRaisesRegex(ValueError, "数据版本已更新"):
            web_app.generate_competitor_insight(payload)

    def test_rejects_incomplete_business_insight_structure(self):
        with self.assertRaisesRegex(RuntimeError, "结构不完整"):
            web_app._parse_competitor_business_insights("只有一条数据摘要")

    def test_business_lens_does_not_equate_scale_with_overall_performance(self):
        lens = web_app._competitor_metric_business_lens("mobile_subscribers", "移动用户数")
        self.assertIn("规模", lens)
        self.assertIn("不自动代表", lens)

    def test_rejects_wrong_insight_labels(self):
        insights = ["数据摘要｜0.1", "公司定位｜HKT 0.8、SmarTone 0.7", "业务含义｜0.1"]
        with self.assertRaisesRegex(RuntimeError, "标签或顺序"):
            web_app._validate_competitor_business_insights(insights, ["HKT", "SmarTone"], [])

    def test_rejects_company_position_that_omits_selected_company(self):
        insights = ["竞争格局｜差距0.1", "公司定位｜HKT为0.8", "业务含义｜流失率0.8"]
        with self.assertRaisesRegex(RuntimeError, "未覆盖全部"):
            web_app._validate_competitor_business_insights(insights, ["HKT", "SmarTone"], [])

    def test_rejects_causal_or_overall_superiority_claim(self):
        insights = ["竞争格局｜差距0.1证明竞争稳定", "公司定位｜HKT为0.8、SmarTone为0.7", "业务含义｜HKT整体经营领先0.1"]
        with self.assertRaisesRegex(RuntimeError, "过强因果"):
            web_app._validate_competitor_business_insights(insights, ["HKT", "SmarTone"], [])

    def test_demo_report_listing_excludes_test_output(self):
        self.assertFalse(web_app.is_report_file_name("test_out.docx"))


if __name__ == "__main__":
    unittest.main()

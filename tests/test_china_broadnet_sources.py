import unittest
from unittest.mock import patch

from data_curation import workflow as w
from data_curation.six_agent_research import collect_sources, company_value_is_bound, validate_fact
from data_curation.research_kpi import normalize_fact


NRTA = "https://www.nrta.gov.cn/art/2026/8/14/art_114_73831.html"
STATISTICS = "https://gbdsj.cq.gov.cn/sjfb/202608/t20260824_15973393.html"


class BroadnetSourcesTests(unittest.TestCase):
    def test_collector_admits_verified_regulators_when_company_site_fails(self):
        profile = w._company_research_profile("中国广电")
        self.assertIn("中国广播电视网络集团有限公司", profile["aliases"])
        self.assertEqual(set(profile["official_hosts"]), {"cbn.cn", "nrta.gov.cn", "gbdsj.cq.gov.cn"})
        self.assertFalse(w._host_matches_governed_official("https://unrelated.gov.cn/", profile["official_hosts"]))
        def read(url, **kwargs):
            opened = url in {NRTA, STATISTICS}
            return {"url": url, "final_url": url, "opened": opened, "text": "监管机构原文" if opened else "", "http_status": 200 if opened else 0}
        with patch.object(w, "_public_web_search", return_value=([], "fixture")), patch.object(w, "_read_source_page", side_effect=read):
            pages, _ = collect_sources("中国广电", ["收入", "移动客户数"], lambda *args: None)
        self.assertTrue(pages[NRTA]["official"] and pages[NRTA]["opened"])
        self.assertTrue(pages[STATISTICS]["official"] and pages[STATISTICS]["opened"])
        self.assertFalse(pages["https://www.cbn.cn/"]["opened"])

    def test_industry_or_regional_amount_cannot_use_group_identity_elsewhere(self):
        for quote in (
            "中国广电集团有关报道。2026年上半年全国广播电视服务业总收入7513.89亿元。",
            "中国广电集团发布，全国广播电视服务业总收入7513.89亿元。",
            "中国广电集团参与的全国广播电视服务业总收入7513.89亿元。",
            "中国广电湖南网络有限公司2026年收入7513.89亿元。",
            "中国广电集团旗下子公司2026年收入7513.89亿元。",
        ):
            with self.subTest(quote=quote):
                self.assertFalse(company_value_is_bound("中国广电", "7513.89", quote, NRTA))
                fact = dict(company="中国广电", metric="收入", status="verified", value="7513.89", period="2026", unit="亿元", source_url=NRTA, quote=quote)
                self.assertEqual(validate_fact(fact, "中国广电", ["收入"], {NRTA: dict(opened=True, official=True, text=quote)})["status"], "conflict")

    def test_direct_group_figure_is_not_rejected_merely_for_regulator_host(self):
        quote = "中国广播电视网络集团有限公司2026年收入CNY 123亿元。"
        fact = dict(company="中国广电", metric="收入", status="verified", value="123", period="2026", unit="CNY 亿元", source_url=NRTA, quote=quote)
        self.assertEqual(validate_fact(fact, "中国广电", ["收入"], {NRTA: dict(opened=True, official=True, text=quote)})["status"], "verified")

    def test_approximate_subscriber_value_is_preserved_then_rejected_for_exact_table(self):
        quote = "中国广电集团2026年上半年移动客户数近4400万户。"
        fact = dict(company="中国广电", metric="移动客户数", status="verified", value="4400", period="2026年上半年", unit="万户", source_url=NRTA, quote=quote)
        pages = {NRTA: dict(opened=True, official=True, text=quote)}
        self.assertEqual(validate_fact(fact, "中国广电", ["移动客户数"], pages)["status"], "conflict")
        preserved = validate_fact({**fact, "value": "近4400"}, "中国广电", ["移动客户数"], pages)
        self.assertEqual(preserved["status"], "verified")
        row, _, reason = normalize_fact({"company": "中国广电", "metric": "移动客户数", "value": "近4400", "unit": "万户", "period": "H1 2026", "basis": quote,
                               "decision": "accepted", "status": "ok", "research_status": "verified", "freshness": "new_period", "source_tier": "official", "quality_score": 1,
                               "entity_supported": True, "metric_supported": True, "value_supported": True, "evidence_hash": "fixture", "sources": [NRTA]})
        self.assertIsNone(row)
        self.assertIn("数量级/单位不明确", reason)

from __future__ import annotations

import unittest
import time
from unittest.mock import patch

from data_curation.schemas import CandidateFact, EvidenceTask
from data_curation.workflow import (
    _votes_from_source_pages,
    audit_quality,
    build_graph,
    extract_facts,
    search_verify_facts,
    supervise_gap_actions,
)
from crawl import apply_crawl_settings, redact_sensitive
from normalize_company_metrics_ai import (
    _evidence_relevance,
    _evidence_mentions_company,
    _focused_evidence,
    _official_domain_owners,
    _record_allowed_for_company,
    build_tasks,
    deterministic_extract_task,
)


class DataCurationWorkflowTests(unittest.TestCase):
    def test_metric_focused_evidence_reads_beyond_page_header(self) -> None:
        text = "Home About Products " + ("navigation " * 300) + (
            "The Board declared an interim dividend of HK$0.145 per share."
        )
        evidence = _focused_evidence(text, "派息", "SmarTone")
        self.assertIn("HK$0.145", evidence)
        self.assertLess(len(evidence), len(text))

    def test_metric_relevance_beats_company_only_navigation(self) -> None:
        navigation = "SmarTone investor relations home navigation"
        disclosure = "The Board declared an interim dividend of HK$0.145 per share."
        self.assertGreater(
            _evidence_relevance(disclosure, "派息", "SmarTone"),
            _evidence_relevance(navigation, "派息", "SmarTone"),
        )

    def test_focused_evidence_prioritizes_numeric_disclosure_over_early_definition(self) -> None:
        text = (
            "Customer base means all registered accounts. " * 80
            + "HKT IN NUMBERS MOBILE Post-Paid Customer Base 3.46 M, "
            + "5G Customer Base 1.75 M."
        )
        evidence = _focused_evidence(text, "客户数/用户数", "HKT")
        self.assertIn("3.46 M", evidence)

    def test_official_source_cannot_cross_company_boundary(self) -> None:
        china_unicom_report = {
            "url": "https://www.chinaunicom.com.hk/en/ir/reports/annual-report.pdf"
        }
        self.assertTrue(_record_allowed_for_company(china_unicom_report, "中国联通"))
        self.assertFalse(_record_allowed_for_company(china_unicom_report, "中国电信"))
        self.assertFalse(_record_allowed_for_company(china_unicom_report, "中国移动"))

    def test_hkt_brand_domains_are_not_interchangeable(self) -> None:
        hkt_enterprise = {"url": "https://www.hkt-enterprise.com/en/open-api"}
        csl_plan = {"url": "https://www.hkcsl.com/en/mobile-plans"}
        one_o_one_o = {"url": "https://www.1010.com.hk/en/plans"}
        self.assertTrue(_record_allowed_for_company(hkt_enterprise, "HKT"))
        self.assertFalse(_record_allowed_for_company(hkt_enterprise, "csl"))
        self.assertFalse(_record_allowed_for_company(hkt_enterprise, "1O1O"))
        self.assertTrue(_record_allowed_for_company(csl_plan, "csl"))
        self.assertFalse(_record_allowed_for_company(csl_plan, "HKT"))
        self.assertTrue(_record_allowed_for_company(one_o_one_o, "1O1O"))
        self.assertFalse(_record_allowed_for_company(one_o_one_o, "csl"))

    def test_third_party_metric_window_must_name_target_company(self) -> None:
        unicom_fact = "中国联通已在超过330个城市部署5G-A。"
        self.assertTrue(_evidence_mentions_company(unicom_fact, "中国联通"))
        self.assertFalse(_evidence_mentions_company(unicom_fact, "中国电信"))

    def test_public_long_number_is_not_redacted_as_phone(self) -> None:
        self.assertEqual(redact_sensitive("GDP 407106629428.342美元"), "GDP 407106629428.342美元")
        self.assertIn("[REDACTED_PHONE_OR_ID]", redact_sensitive("电话 +852 2123 4567"))

    def test_evidence_tasks_have_stable_fingerprints(self) -> None:
        first = build_tasks(limit=2)
        second = build_tasks(limit=2)
        self.assertEqual(len(first), 2)
        self.assertEqual(
            [EvidenceTask.model_validate(item).evidence_hash for item in first],
            [EvidenceTask.model_validate(item).evidence_hash for item in second],
        )
        self.assertTrue(all(item["evidence_hash"] for item in first))

    def test_parallel_ai_batches_preserve_candidate_order(self) -> None:
        tasks = []
        for index in range(4):
            task = {
                "id": f"parallel-{index}",
                "company": "HKT",
                "metric": "漫游",
                "current_value": "",
                "raw_text": f"HKT roaming evidence {index}",
                "sources": ["https://www.hkt.com/en/about-hkt/investor-relations/fast-facts/"],
                "row_ref": "row_4",
                "evidence_hash": f"hash-{index}",
                "source_score": 1.0,
                "source_tier": "official",
            }
            tasks.append(EvidenceTask.model_validate(task).model_dump())

        def fake_call_deepseek(batch):
            index = int(batch[0]["id"].rsplit("-", 1)[1])
            time.sleep(0.03 * (4 - index))
            return [
                {
                    "id": batch[0]["id"],
                    "status": "unavailable",
                    "value": "未提取到有效数据",
                    "basis": f"batch {index}",
                    "note": "",
                    "entity_supported": True,
                    "metric_supported": False,
                    "value_supported": False,
                    "confidence": 0.1,
                }
            ]

        with patch("data_curation.workflow.call_deepseek", side_effect=fake_call_deepseek):
            result = extract_facts(
                {
                    "run_id": "unit-test",
                    "tasks": tasks,
                    "existing_items": {},
                    "batch_size": 1,
                    "ai_workers": 4,
                    "online_ai": True,
                }
            )

        self.assertEqual(
            [item["id"] for item in result["candidates"]],
            ["parallel-0", "parallel-1", "parallel-2", "parallel-3"],
        )
        self.assertEqual(result["summary"]["onlineBatches"], 4)

    def test_hkt_customer_exact_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "hkt-customer",
                "company": "HKT",
                "metric": "客户数/用户数",
                "raw_text": "Post-Paid Customer Base 3.46 M 5G Customer Base 1.75 M",
            }
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["value"], "后付费客户346万；5G客户175万")

    def test_hkt_5g_customer_exact_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "hkt-5g",
                "company": "HKT",
                "metric": "5G用户数",
                "raw_text": "5G Customer Base 1.75 M",
            }
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["value"], "5G客户175万")

    def test_hkt_product_and_value_added_services_are_brand_specific(self) -> None:
        product = deterministic_extract_task(
            {
                "id": "hkt-product",
                "company": "HKT",
                "metric": "产品规格",
                "raw_text": "Choose from 1G to 10G. 10,000M Fibre-to-the-Home.",
            }
        )
        services = deterministic_extract_task(
            {
                "id": "hkt-services",
                "company": "HKT",
                "metric": "增值服务",
                "raw_text": (
                    "Home Wi-Fi Google Workspace with Gemini NETVIGATOR SHiELD "
                    "Surfshark ONE Microsoft 365 Now TV"
                ),
            }
        )
        self.assertIn("1G至10G", product["value"])
        self.assertIn("Google Workspace with Gemini", services["value"])

    def test_hkt_home_plan_and_tariff_require_official_price_details(self) -> None:
        home_plan = deterministic_extract_task(
            {
                "id": "hkt-home-plan",
                "company": "HKT",
                "metric": "家宽套餐",
                "raw_text": "NETVIGATOR Home Broadband. Choose from 1G to 10G to suit your needs.",
            }
        )
        tariff = deterministic_extract_task(
            {
                "id": "hkt-tariff",
                "company": "HKT",
                "metric": "资费",
                "raw_text": (
                    "1000M Fibre-to-the-Home Free Home Wi-Fi Service From HK$ 108 "
                    "/month 36-month commitment. 5G Home Internet From HK$ 168 "
                    "/month 36-month commitment."
                ),
            }
        )
        self.assertIn("1G至10G", home_plan["value"])
        self.assertIn("108港元", tariff["value"])
        self.assertIn("168港元", tariff["value"])
        self.assertIn("36个月", tariff["value"])

    def test_hkt_tariff_supports_official_chinese_page(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "hkt-tariff-zh",
                "company": "HKT",
                "metric": "资费",
                "raw_text": (
                    "1000M 光纖入屋寬頻 送家居Wi-Fi服務 低至 HK$ 108 /月 "
                    "36 個月承諾期。5G 私家寬頻服務 低至 HK$ 168 /月 "
                    "36 個月承諾期。"
                ),
            }
        )
        self.assertIn("108港元", result["value"])
        self.assertIn("168港元", result["value"])

    def test_hkt_official_page_supports_product_contract_and_promotion(self) -> None:
        raw_text = (
            "網上行寬頻新標準，提供1G 至10G的選擇。10,000M 光纖入屋寬頻。"
            "1000M 光纖入屋寬頻 低至 HK$ 108 /月 36 個月承諾期。"
            "2500M 超級寬頻 升級低至 HK$ 58 /月 36 個月承諾期。"
            "5G 私家寬頻服務 低至 HK$ 168 /月 36 個月承諾期。"
        )
        product = deterministic_extract_task(
            {"id": "hkt-product-zh", "company": "HKT", "metric": "产品规格", "raw_text": raw_text}
        )
        five_g = deterministic_extract_task(
            {"id": "hkt-5g-plan", "company": "HKT", "metric": "5G套餐", "raw_text": raw_text}
        )
        contract = deterministic_extract_task(
            {"id": "hkt-contract", "company": "HKT", "metric": "合约期", "raw_text": raw_text}
        )
        promotion = deterministic_extract_task(
            {"id": "hkt-promotion", "company": "HKT", "metric": "促销折扣", "raw_text": raw_text}
        )
        self.assertIn("1G至10G", product["value"])
        self.assertIn("168港元", five_g["value"])
        self.assertIn("36个月", contract["value"])
        self.assertIn("58港元", promotion["value"])

    def test_csl_tariff_and_roaming_extractors_require_official_details(self) -> None:
        tariff = deterministic_extract_task(
            {
                "id": "csl-tariff",
                "company": "csl",
                "metric": "资费",
                "raw_text": (
                    "local data entitlement 60GB/100GB/150GB/250GB/500GB. "
                    "A monthly administrative fee of HKD 18 also applies."
                ),
            }
        )
        roaming = deterministic_extract_task(
            {
                "id": "csl-roaming",
                "company": "csl",
                "metric": "漫游",
                "raw_text": (
                    "Golden Roaming Data Roaming Pass First In-Flight Data Roaming Pass "
                    "First Cruise Data Roaming Pass"
                ),
            }
        )
        self.assertIn("60GB/100GB/150GB/250GB/500GB", tariff["value"])
        self.assertIn("18港元", tariff["value"])
        self.assertIn("csl", tariff["value"])
        self.assertIn("Golden Roaming", roaming["value"])

    def test_csl_plan_contract_and_promotion_exact_extractors(self) -> None:
        raw_text = (
            "Monthly Plan Fee $348 Local data usage 100GB. "
            "Monthly Plan Fee $398 Local data usage 150GB. "
            "The offer is only valid for customers who sign a commitment period "
            "of 24 or 36 months. Enjoy welcome offers worth over $2,000!"
        )
        plan = deterministic_extract_task(
            {"id": "csl-plan", "company": "csl", "metric": "5G套餐", "raw_text": raw_text}
        )
        contract = deterministic_extract_task(
            {"id": "csl-contract", "company": "csl", "metric": "合约期", "raw_text": raw_text}
        )
        promotion = deterministic_extract_task(
            {"id": "csl-promotion", "company": "csl", "metric": "促销折扣", "raw_text": raw_text}
        )
        self.assertIn("348港元100GB", plan["value"])
        self.assertIn("24个月或36个月", contract["value"])
        self.assertIn("2,000港元", promotion["value"])

    def test_1010_enterprise_5g_and_open_api_extractors(self) -> None:
        five_g = deterministic_extract_task(
            {
                "id": "1010-5ga",
                "company": "1O1O",
                "metric": "5G-A",
                "raw_text": (
                    "Enterprise 5G/5.5G & Wireless Solutions 5G Private Network "
                    "Managed 5G Router Solutions"
                ),
            }
        )
        cooperation = deterministic_extract_task(
            {
                "id": "1010-open-api",
                "company": "1O1O",
                "metric": "战略合作",
                "raw_text": (
                    "22 SEP 2025 HKT Enterprise Solutions: Open APIs Powering "
                    "Hong Kong’s Digital Innovation and Enterprise Efficiency"
                ),
            }
        )
        self.assertIn("5G/5.5G", five_g["value"])
        self.assertIn("Open API", cooperation["value"])
        self.assertIn("1O1O", cooperation["value"])

    def test_1010_open_api_is_a_supported_product_spec(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "1010-open-api-product",
                "company": "1O1O",
                "metric": "产品规格",
                "raw_text": (
                    "HKT Enterprise Solutions now provides Open API services on the "
                    "1O1O 5G mobile network and helps enterprises modernise "
                    "mobile-number verification."
                ),
            }
        )
        self.assertIn("1O1O 5G", result["value"])
        self.assertIn("号码验证", result["value"])

    def test_1010_5g_plan_variants_are_structured(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "1010-plan",
                "company": "1O1O",
                "metric": "5G套餐",
                "raw_text": (
                    "Global 5G Prestige Service Asia Pacific 5G Prestige Service "
                    "China-HK-Macau 5G Prestige Service"
                ),
            }
        )
        self.assertIn("全球、亚太及中港澳", result["value"])

    def test_3hk_promotion_exact_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "3hk-promotion",
                "company": "3HK",
                "metric": "促销折扣",
                "raw_text": (
                    "$188 /month Local Data 60GB. Earn MoneyBack points worth $400 "
                    "upon successful subscription via referral and redeem cash discounts."
                ),
            }
        )
        self.assertIn("188港元", result["value"])
        self.assertIn("400港元", result["value"])

    def test_smartone_5g_penetration_exact_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "smartone-5g",
                "company": "SmarTone",
                "metric": "5G用户数",
                "raw_text": "Maintaining 5G penetration at about 40%, and 5G ARPU doubled 4G.",
            }
        )
        self.assertEqual(result["value"], "5G渗透率约40%（公司未披露绝对用户数）")

    def test_smartone_home_broadband_exact_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "smartone-home",
                "company": "SmarTone",
                "metric": "家宽",
                "raw_text": (
                    "SmarTone Home 5G Broadband Online Exclusive Free Upgrade to "
                    "Wi-Fi 7 12-month Flexible Short Contract"
                ),
            }
        )
        self.assertIn("Wi-Fi 7", result["value"])
        self.assertIn("12个月", result["value"])

    def test_mainland_dict_extractors_use_audited_annual_report_figures(self) -> None:
        telecom = deterministic_extract_task(
            {
                "id": "telecom-dict",
                "company": "中国电信",
                "metric": "DICT",
                "raw_text": (
                    "Industrial Digitalisation service revenues "
                    "147,307 146,588 0.5%"
                ),
            }
        )
        unicom = deterministic_extract_task(
            {
                "id": "unicom-dict",
                "company": "中国联通",
                "metric": "DICT",
                "raw_text": (
                    "Revenue contribution from strategic emerging industries reached "
                    "over 86%. The computing power business revenue ratio reached over "
                    "15%. AI revenue grew by over 140% year-on-year."
                ),
            }
        )
        self.assertIn("1473.07亿元", telecom["value"])
        self.assertIn("0.5%", telecom["value"])
        self.assertIn("超过86%", unicom["value"])
        self.assertIn("超过140%", unicom["value"])

    def test_official_policy_title_extractors_are_not_navigation_fragments(self) -> None:
        coverage = deterministic_extract_task(
            {
                "id": "ofca-coverage",
                "company": "通信监管机构",
                "metric": "覆盖义务",
                "raw_text": (
                    "Subsidy Scheme to Extend Fibre-based Networks to Villages in "
                    "Remote Areas. Subsidy Scheme to Extend 5G Coverage in Rural and "
                    "Remote Areas."
                ),
            }
        )
        policy = deterministic_extract_task(
            {
                "id": "gov-policy",
                "company": "政治新闻",
                "metric": "重大政策/声明",
                "raw_text": (
                    "Announcement on the Implementation of Electronic Border "
                    "Management Area Permit Policy"
                ),
            }
        )
        self.assertIn("5G覆盖资助计划", coverage["value"])
        self.assertIn("通行证电子化政策", policy["value"])

    def test_kt_enterprise_ict_product_list_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "kt-ict",
                "company": "KT",
                "metric": "企业ICT",
                "raw_text": "Enterprise LTE Service IoTMakers ucloud biz AMI BEMS Fintech",
            }
        )
        self.assertIn("Enterprise LTE Service", result["value"])
        self.assertIn("ucloud biz", result["value"])

    def test_kt_form_20f_enterprise_ict_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "kt-ict-20f",
                "company": "KT",
                "metric": "企业ICT",
                "raw_text": (
                    "We offer a wide range of KT AX platform services for our "
                    "corporate customers that provide customized and integrated "
                    "digital transformation services. Information Data Center "
                    "and Cloud Services. We operate Internet data centers and "
                    "cloud services, including servers, storage and leased lines."
                ),
            }
        )
        self.assertEqual(result["status"], "ok")
        self.assertIn("数字化转型", result["value"])

    def test_jio_capex_direction_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "jio-capex",
                "company": "Jio",
                "metric": "Capex方向",
                "raw_text": (
                    "Jio - Expanding 5G and broadband adoption across mobility, "
                    "homes and enterprises. AirFiber subscribers crossed 5.6mn. "
                    "Deployment of Private 5G for secure enterprise connectivity."
                ),
            }
        )
        self.assertEqual(result["status"], "ok")
        self.assertIn("AirFiber", result["value"])

    def test_china_mobile_dict_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "cm-dict",
                "company": "中国移动",
                "metric": "DICT",
                "raw_text": (
                    "AI services include data algorithms, embodied intelligence, "
                    "digital intelligence culture, digital intelligence e-commerce "
                    "and industry digital intelligence services."
                ),
            }
        )
        self.assertEqual(result["status"], "ok")
        self.assertIn("行业数智服务", result["value"])

    def test_tmobile_parent_report_fwa_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "tmobile-fwa",
                "company": "T-Mobile US",
                "metric": "FWA",
                "raw_text": (
                    "T-Mobile US is leveraging its leading position in respect "
                    "of mid-band mobile spectrum to offer customers fixed "
                    "wireless broadband access via FWA."
                ),
            }
        )
        self.assertEqual(result["status"], "ok")
        self.assertIn("固定无线宽带", result["value"])

    def test_tmobile_5g_broadband_net_additions_support_fwa(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "tmobile-fwa-customers",
                "company": "T-Mobile US",
                "metric": "FWA",
                "raw_text": (
                    "5G broadband (formerly High Speed Internet) net customer "
                    "additions included in postpaid other net customer additions "
                    "were 1.7 million and 1.5 million in 2025 and 2024, respectively."
                ),
            }
        )
        self.assertEqual(result["status"], "ok")
        self.assertIn("1.7百万", result["value"])

    def test_operator_network_api_venture_extractors(self) -> None:
        text = (
            "Today, some of the world’s largest telecom operators, including "
            "AT&T, Deutsche Telekom, Orange, Telefonica, Telstra, T-Mobile, "
            "Verizon and Vodafone, together with Ericsson are announcing a new "
            "venture to combine and sell network Application Programming "
            "Interfaces (APIs) on a global scale to spur innovation in digital "
            "services. Network APIs are the way to easily access, use and pay "
            "for network capabilities."
        )
        att = deterministic_extract_task(
            {
                "id": "att-network-api",
                "company": "AT&T",
                "metric": "网络API",
                "raw_text": text,
            }
        )
        tmobile = deterministic_extract_task(
            {
                "id": "tmobile-network-api",
                "company": "T-Mobile US",
                "metric": "网络API",
                "raw_text": text,
            }
        )
        self.assertEqual(att["status"], "ok")
        self.assertEqual(tmobile["status"], "ok")
        self.assertIn("网络API", att["value"])

    def test_tmobile_ai_ran_prnewswire_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "tmobile-ai-ran",
                "company": "T-Mobile US",
                "metric": "AI网络",
                "raw_text": (
                    "Ericsson and T-Mobile have moved AI-native Scheduler with "
                    "Link Adaptation into large-scale commercial trials on live "
                    "5G Advanced network traffic. During trials with T-Mobile, "
                    "the AI-native Scheduler with Link Adaptation feature achieved "
                    "close to 10 percent increase in spectral efficiency and up "
                    "to 15 percent boost in downlink throughput."
                ),
            }
        )
        self.assertEqual(result["status"], "ok")
        self.assertIn("15%", result["value"])

    def test_att_investor_open_ran_and_fwa_extractors(self) -> None:
        open_ran = deterministic_extract_task(
            {
                "id": "att-open-ran",
                "company": "AT&T",
                "metric": "Open RAN",
                "raw_text": (
                    "AT&T Inc Analyst & Investor Day. By the end of 2026, "
                    "we expect that 70% of our 5G traffic will flow across "
                    "open hardware. This transition to a more open radio "
                    "architecture will invite new technology partners."
                ),
            }
        )
        fwa = deterministic_extract_task(
            {
                "id": "att-fwa",
                "company": "AT&T",
                "metric": "FWA",
                "raw_text": (
                    "During the first quarter of 2026, we reported a net gain "
                    "of 584,000 total internet connections, with 292,000 fiber "
                    "net adds and 292,000 fixed wireless net adds. AIA revenue "
                    "increases exceeded 100 percent."
                ),
            }
        )
        self.assertEqual(open_ran["status"], "ok")
        self.assertIn("70%", open_ran["value"])
        self.assertEqual(fwa["status"], "ok")
        self.assertIn("29.2万", fwa["value"])

    def test_parent_annual_report_can_support_tmobile(self) -> None:
        owners = _official_domain_owners(
            "https://report.telekom.com/annual-report-2025/management-report/"
            "development-of-business-in-the-operating-segments/united-states.html"
        )
        self.assertEqual(owners, {"T-Mobile US"})

    def test_deutsche_telekom_group_report_does_not_support_tmobile(self) -> None:
        owners = _official_domain_owners(
            "https://report.telekom.com/annual-report-2025/management-report/"
            "group-strategy/investments.html"
        )
        self.assertEqual(owners, {"Deutsche Telekom"})

    def test_hutchison_customer_exact_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "hutch-customer",
                "company": "Hutchison",
                "metric": "客户数/用户数",
                "raw_text": (
                    "Number of postpaid customers (‘000) 1,289 "
                    "Number of prepaid customers (‘000) 6,843 "
                    "Total customers (‘000) 8,132"
                ),
            }
        )
        self.assertIsNotNone(result)
        self.assertIn("客户总数813.2万", result["value"])

    def test_hutchison_5g_penetration_uses_final_rate(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "hutch-5g",
                "company": "Hutchison",
                "metric": "5G用户数",
                "raw_text": "The 5G penetration rate rose 8% points to 62% compared to 2024.",
            }
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["value"], "5G渗透率62%")

    def test_hutchison_arpu_table_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "hutch-arpu",
                "company": "Hutchison",
                "metric": "ARPU",
                "raw_text": (
                    "Postpaid gross ARPU (HK$) 187 190 –2% "
                    "Postpaid net ARPU (HK$) 176 175 +1%"
                ),
            }
        )
        self.assertIsNotNone(result)
        self.assertIn("毛ARPU每月187港元", result["value"])
        self.assertIn("净ARPU每月176港元", result["value"])

    def test_hutchison_official_brand_privilege_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "hutch-promotion",
                "company": "Hutchison",
                "metric": "促销折扣",
                "raw_text": (
                    "Experience '3 for You' Brand Value with Backup Phone Service "
                    "and 100+ Global Privileges"
                ),
            }
        )
        self.assertIsNotNone(result)
        self.assertIn("100多项全球礼遇", result["value"])

    def test_hkbn_governance_exact_extractors(self) -> None:
        raw_text = (
            "the Board has resolved to declare a final dividend of 18.9 cents per share. "
            "Subject to the approval by the Shareholders at the 2025 annual general meeting "
            "of the Company, the proposed final dividend is expected to be paid in cash on "
            "or around Tuesday, 6 January 2026. "
            "from 7 May 2025 the China Mobile Group became connected persons. "
            "An announcement was made by the Company on 30 October 2025 in respect "
            "of the Partially-exempt CCTs. "
            "all applicable ratios were less than 5%"
        )
        board = deterministic_extract_task(
            {"id": "hkbn-board", "company": "HKBN", "metric": "董事会", "raw_text": raw_text}
        )
        agm = deterministic_extract_task(
            {"id": "hkbn-agm", "company": "HKBN", "metric": "股东大会", "raw_text": raw_text}
        )
        connected = deterministic_extract_task(
            {
                "id": "hkbn-cct",
                "company": "HKBN",
                "metric": "持续性关联交易",
                "raw_text": raw_text,
            }
        )
        self.assertIn("18.9港仙", board["value"])
        self.assertIn("2026年1月6日", agm["value"])
        self.assertIn("低于5%", connected["value"])

    def test_brand_market_reaction_is_explicitly_not_applicable(self) -> None:
        result = deterministic_extract_task(
            {"id": "csl-market", "company": "csl", "metric": "市场反应", "raw_text": ""}
        )
        self.assertEqual(result["value"], "不适用（品牌非独立上市主体）")

    def test_hkbn_gearing_exact_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "hkbn-gearing",
                "company": "HKBN",
                "metric": "资产负债率",
                "raw_text": (
                    "The Group’s gearing ratio, which was expressed as a ratio of the gross debt "
                    "over total equity, was 5.0x as at 31 August 2025."
                ),
            }
        )
        self.assertIsNotNone(result)
        self.assertIn("5.0x", result["value"])

    def test_hgc_data_center_action_requires_specific_event(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "hgc-dci",
                "company": "HGC",
                "metric": "数据中心",
                "raw_text": "06 May 2025 HGC Expands the Data Center Interconnect to Malaysia",
            }
        )
        self.assertIsNotNone(result)
        self.assertIn("马来西亚", result["value"])

    def test_china_mobile_verified_capex_and_computing_metrics(self) -> None:
        capex = deterministic_extract_task(
            {"id": "cm-capex", "company": "中国移动", "metric": "资本开支", "raw_text": ""}
        )
        computing = deterministic_extract_task(
            {"id": "cm-computing", "company": "中国移动", "metric": "算力网络", "raw_text": ""}
        )
        ai = deterministic_extract_task(
            {"id": "cm-ai", "company": "中国移动", "metric": "AI", "raw_text": ""}
        )
        self.assertIsNotNone(capex)
        self.assertIn("1366亿元", capex["value"])
        self.assertEqual(computing["value"], "算力网络投资同比增长62.4%")
        self.assertIn("19.8%", ai["value"])

    def test_china_telecom_5g_a_exact_extractor(self) -> None:
        result = deterministic_extract_task(
            {
                "id": "ct-5ga",
                "company": "中国电信",
                "metric": "5G-A",
                "raw_text": (
                    "deployed over 110,000 5G-A carrier aggregation base stations "
                    "and over 650,000 RedCap base stations in more than 300 cities."
                ),
            }
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["value"], "部署超过110,000个5G-A载波聚合基站，覆盖超过300个城市")

    def test_china_unicom_computing_ai_and_5g_a_extractors(self) -> None:
        computing = deterministic_extract_task(
            {
                "id": "cu-computing",
                "company": "中国联通",
                "metric": "算力网络",
                "raw_text": (
                    "The scale of intelligent computing reached 45 EFLOPS, "
                    "with backbone cloud pools covering 252 cities. "
                    "adding more than 9,000 kilometres to achieve the interconnection "
                    "of computing power hub nodes."
                ),
            }
        )
        ai = deterministic_extract_task(
            {
                "id": "cu-ai",
                "company": "中国联通",
                "metric": "AI",
                "raw_text": (
                    "AI revenue4 grew by over 140% year-on-year. "
                    "cloud-AI products served over 300 million users with revenue "
                    "increasing by more than 11% year-on-year."
                ),
            }
        )
        five_g_a = deterministic_extract_task(
            {
                "id": "cu-5ga",
                "company": "中国联通",
                "metric": "5G-A",
                "raw_text": "5G-A base stations were deployed in more than 330 cities.",
            }
        )
        self.assertIn("45 EFLOPS", computing["value"])
        self.assertIn("9,000公里", computing["value"])
        self.assertIn("140%", ai["value"])
        self.assertEqual(five_g_a["value"], "5G-A基站已部署至超过330个城市")

    def test_mainland_official_tasks_do_not_include_other_operator_fact(self) -> None:
        tasks = {
            (item["company"], item["metric"]): item
            for item in build_tasks()
            if item["company"] in {"中国移动", "中国电信", "中国联通"} and item["metric"] == "5G-A"
        }
        telecom = tasks[("中国电信", "5G-A")]
        self.assertNotIn("中国联通2025年报", telecom["raw_text"])
        self.assertFalse(any("chinaunicom.com.hk" in url for url in telecom["sources"]))

    def test_supervisor_has_deterministic_fallback(self) -> None:
        result = supervise_gap_actions(
            {
                "run_id": "unit-test",
                "online_ai": False,
                "max_recrawl_rows": 1,
                "max_recrawl_rounds": 1,
                "recrawl_round": 0,
                "recrawl_tasks": [
                    {
                        "row_ref": "row_2",
                        "row_number": 2,
                        "reason": "关键指标缺口",
                        "priority": 100,
                        "attempts": 0,
                    },
                    {
                        "row_ref": "row_5",
                        "row_number": 5,
                        "reason": "普通指标缺口",
                        "priority": 80,
                        "attempts": 0,
                    },
                ],
                "gaps": [
                    {
                        "company": "HKT",
                        "metric": "派息",
                        "row_ref": "row_2",
                        "reason": "数值或事实依据不足",
                        "candidate_ids": ["a"],
                    }
                ],
            }
        )
        self.assertEqual(result["supervisor_decision"], "recrawl")
        self.assertEqual([item["row_number"] for item in result["recrawl_tasks"]], [2])
        self.assertEqual(result["agent_trace"][-1]["phase"], "decision")

    def test_graph_contains_tool_supervisor(self) -> None:
        graph = build_graph().get_graph()
        self.assertIn("supervisor", graph.nodes)
        self.assertIn("search_verify", graph.nodes)
        self.assertIn(("resolve", "search_verify"), {(edge.source, edge.target) for edge in graph.edges})
        self.assertIn(("search_verify", "plan_gaps"), {(edge.source, edge.target) for edge in graph.edges})
        self.assertIn(("plan_gaps", "supervisor"), {(edge.source, edge.target) for edge in graph.edges})

    def test_search_verifier_majority_corrects_candidate_value(self) -> None:
        result = search_verify_facts(
            {
                "run_id": "unit-test",
                "search_verify_workers": 2,
                "tasks": [
                    {
                        "id": "fact-a",
                        "company": "中国移动",
                        "metric": "收入",
                        "row_ref": "row_29",
                        "raw_text": "中国移动2025年营业收入达到10502亿元。",
                        "sources": ["https://www.chinamobileltd.com/report"],
                    }
                ],
                "existing_items": {
                    "old-a": {
                        "schemaVersion": 4,
                        "company": "中国移动",
                        "metric": "收入",
                        "row_ref": "row_29",
                        "semantic_key": "中国移动|收入|row_29",
                        "status": "ok",
                        "decision": "accepted",
                        "value": "10502亿元",
                        "quality_score": 0.96,
                    }
                },
                "candidates": [
                    {
                        "id": "fact-a",
                        "company": "中国移动",
                        "metric": "收入",
                        "value": "10500亿元",
                        "basis": "候选值为10500亿元。",
                        "status": "ok",
                        "entity_supported": True,
                        "metric_supported": True,
                        "value_supported": True,
                        "confidence": 0.86,
                        "source_score": 1.0,
                        "source_tier": "official",
                        "row_ref": "row_29",
                        "sources": ["https://www.chinamobileltd.com/report"],
                        "quality_score": 0.94,
                        "decision": "accepted",
                    }
                ],
            }
        )
        fact = result["candidates"][0]
        self.assertEqual(fact["value"], "10502亿元")
        self.assertEqual(fact["decision"], "accepted")
        self.assertEqual(fact["search_verification"]["decision"], "majority_corrected")

    def test_search_verifier_conflict_without_majority_goes_to_review(self) -> None:
        result = search_verify_facts(
            {
                "run_id": "unit-test",
                "search_verify_workers": 2,
                "tasks": [
                    {
                        "id": "fact-b",
                        "company": "中国电信",
                        "metric": "收入",
                        "row_ref": "row_23",
                        "raw_text": "中国电信收入为5296亿元。",
                        "sources": ["https://www.chinatelecom-h.com/report"],
                    }
                ],
                "existing_items": {},
                "candidates": [
                    {
                        "id": "fact-b",
                        "company": "中国电信",
                        "metric": "收入",
                        "value": "5295亿元",
                        "basis": "候选值为5295亿元。",
                        "status": "ok",
                        "entity_supported": True,
                        "metric_supported": True,
                        "value_supported": True,
                        "confidence": 0.86,
                        "source_score": 1.0,
                        "source_tier": "official",
                        "row_ref": "row_23",
                        "sources": ["https://www.chinatelecom-h.com/report"],
                        "quality_score": 0.94,
                        "decision": "accepted",
                    }
                ],
            }
        )
        fact = result["candidates"][0]
        self.assertEqual(fact["decision"], "review")
        self.assertIn("搜索验证未形成多数口径", fact["reasons"])

    def test_search_verifier_confirms_table_value_from_metric_window(self) -> None:
        result = search_verify_facts(
            {
                "run_id": "unit-test",
                "search_verify_workers": 1,
                "tasks": [
                    {
                        "id": "icable-revenue",
                        "company": "i-CABLE",
                        "metric": "运营收入/总收益",
                        "row_ref": "row_17",
                        "raw_text": (
                            "Fiscal Year FY 2025 FY 2024 FY 2023 "
                            "Revenue 538.74 584.49 597.9"
                        ),
                        "sources": ["https://stockanalysis.com/quote/hkg/1097/financials/"],
                    }
                ],
                "existing_items": {},
                "candidates": [
                    {
                        "id": "icable-revenue",
                        "company": "i-CABLE",
                        "metric": "运营收入/总收益",
                        "value": "538.74（百万，单位未明确，推测为百万港元）",
                        "basis": "片段中明确列出Revenue 538.74。",
                        "status": "ok",
                        "entity_supported": True,
                        "metric_supported": True,
                        "value_supported": True,
                        "confidence": 0.9,
                        "source_score": 0.9,
                        "source_tier": "commercial",
                        "row_ref": "row_17",
                        "sources": ["https://stockanalysis.com/quote/hkg/1097/financials/"],
                        "quality_score": 0.94,
                        "decision": "accepted",
                    }
                ],
            }
        )
        verification = result["candidates"][0]["search_verification"]
        self.assertGreaterEqual(verification["vote_count"], 2)
        self.assertEqual(verification["decision"], "majority_confirmed")

    def test_search_verifier_ignores_unrelated_qualitative_window(self) -> None:
        result = search_verify_facts(
            {
                "run_id": "unit-test",
                "search_verify_workers": 1,
                "tasks": [
                    {
                        "id": "hkbn-board",
                        "company": "HKBN",
                        "metric": "董事会",
                        "row_ref": "row_12",
                        "raw_text": (
                            "Corporate Governance Report Board Diversity. "
                            "The Board has over 50% female Directors."
                        ),
                        "sources": ["https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_AnnualReport_2025.pdf"],
                    }
                ],
                "existing_items": {},
                "candidates": [
                    {
                        "id": "hkbn-board",
                        "company": "HKBN",
                        "metric": "董事会",
                        "value": "董事会决议宣派2025财年末期股息每股18.9港仙",
                        "basis": "Board has resolved to declare a final dividend of 18.9 cents per share",
                        "status": "ok",
                        "entity_supported": True,
                        "metric_supported": True,
                        "value_supported": True,
                        "confidence": 0.96,
                        "source_score": 1.0,
                        "source_tier": "official",
                        "row_ref": "row_12",
                        "sources": ["https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_AnnualReport_2025.pdf"],
                        "quality_score": 0.996,
                        "decision": "accepted",
                    }
                ],
            }
        )
        fact = result["candidates"][0]
        self.assertEqual(fact["decision"], "accepted")
        self.assertNotIn("搜索验证未形成多数口径", fact.get("reasons", []))

    def test_search_verifier_online_search_vote_can_join_majority(self) -> None:
        with patch(
            "data_curation.workflow._public_web_search",
            return_value=(
                [
                    {
                        "title": "中国移动2025年营业收入达到10502亿元",
                        "snippet": "中国移动发布年度业绩，营业收入达到10502亿元。",
                        "url": "https://www.chinamobileltd.com/report",
                        "provider": "unit",
                    }
                ],
                "unit",
            ),
        ):
            result = search_verify_facts(
                {
                    "run_id": "unit-test",
                    "search_verify_workers": 2,
                    "search_verify_online": True,
                    "search_verify_online_limit": 1,
                    "tasks": [
                        {
                            "id": "fact-online",
                            "company": "中国移动",
                            "metric": "收入",
                            "row_ref": "row_29",
                            "raw_text": "中国移动营业收入达到10502亿元。",
                            "sources": ["https://www.chinamobileltd.com/report"],
                        }
                    ],
                    "existing_items": {},
                    "candidates": [
                        {
                            "id": "fact-online",
                            "company": "中国移动",
                            "metric": "收入",
                            "value": "10500亿元",
                            "basis": "候选值为10500亿元。",
                            "status": "ok",
                            "entity_supported": True,
                            "metric_supported": True,
                            "value_supported": True,
                            "confidence": 0.86,
                            "source_score": 1.0,
                            "source_tier": "official",
                            "row_ref": "row_29",
                            "sources": ["https://www.chinamobileltd.com/report"],
                            "quality_score": 0.94,
                            "decision": "accepted",
                        }
                    ],
                }
            )
        fact = result["candidates"][0]
        self.assertEqual(fact["value"], "10502亿元")
        self.assertEqual(fact["search_verification"]["online_search"]["provider"], "unit")
        self.assertGreaterEqual(result["search_verification"]["online_votes"], 1)

    def test_search_verifier_zero_online_limit_checks_all_targets(self) -> None:
        calls: list[str] = []

        def fake_search(query: str):
            calls.append(query)
            return [], "unit-empty"

        with (
            patch("data_curation.workflow._public_web_search", side_effect=fake_search),
            patch("data_curation.workflow._votes_from_source_pages", return_value=[]),
        ):
            result = search_verify_facts(
                {
                    "run_id": "unit-test",
                    "search_verify_workers": 2,
                    "search_verify_online": True,
                    "search_verify_online_limit": 0,
                    "tasks": [],
                    "existing_items": {},
                    "candidates": [
                        {
                            "id": f"fact-{index}",
                            "company": "中国移动",
                            "metric": "收入",
                            "value": f"1050{index}亿元",
                            "basis": f"收入为1050{index}亿元。",
                            "status": "ok",
                            "entity_supported": True,
                            "metric_supported": True,
                            "value_supported": True,
                            "confidence": 0.9,
                            "source_score": 1.0,
                            "source_tier": "official",
                            "row_ref": f"row_{index}",
                            "sources": ["https://www.chinamobileltd.com/report"],
                            "quality_score": 0.94,
                            "decision": "accepted",
                        }
                        for index in range(3)
                    ],
                }
            )
        self.assertEqual(len(calls), 3)
        self.assertEqual(result["search_verification"]["online_checked"], 3)

    def test_search_verifier_online_source_pages_can_recover_rejected_fact(self) -> None:
        with (
            patch("data_curation.workflow._public_web_search", return_value=([], "unit-empty")),
            patch(
                "data_curation.workflow._votes_from_source_pages",
                return_value=[
                    {
                        "value": "Net Income -489.98M",
                        "normalized_value": "-48998万",
                        "canonical": "-48998万",
                        "source": "公开来源页读取",
                        "kind": "source_page",
                        "url": "https://stockanalysis.com/quote/hkg/1097/statistics/",
                    },
                    {
                        "value": "Net Income -489.98M",
                        "normalized_value": "-48998万",
                        "canonical": "-48998万",
                        "source": "公开来源页读取",
                        "kind": "source_page",
                        "url": "https://stockanalysis.com/quote/hkg/1097/financials/",
                    },
                ],
            ),
        ):
            result = search_verify_facts(
                {
                    "run_id": "unit-test",
                    "search_verify_workers": 1,
                    "search_verify_online": True,
                    "search_verify_online_limit": 1,
                    "tasks": [],
                    "existing_items": {},
                    "candidates": [
                        {
                            "id": "icable-profit",
                            "company": "i-CABLE",
                            "metric": "净利润",
                            "value": "未提取到有效数据",
                            "basis": "现有片段不是集团净利润。",
                            "status": "unavailable",
                            "entity_supported": False,
                            "metric_supported": False,
                            "value_supported": False,
                            "confidence": 0.2,
                            "source_score": 0.5,
                            "source_tier": "commercial",
                            "row_ref": "row_17",
                            "sources": ["https://stockanalysis.com/quote/hkg/1097/financials/"],
                            "quality_score": 0.1,
                            "decision": "rejected",
                            "reasons": ["抽取结果不可用"],
                        }
                    ],
                }
            )
        fact = result["candidates"][0]
        self.assertEqual(fact["decision"], "accepted")
        self.assertEqual(fact["status"], "ok")
        self.assertEqual(fact["value"], "-48998万港元")
        self.assertEqual(fact["search_verification"]["decision"], "majority_corrected")

    def test_search_verifier_rechecks_suspicious_accepted_profit_segment(self) -> None:
        with (
            patch("data_curation.workflow._public_web_search", return_value=([], "unit-empty")),
            patch(
                "data_curation.workflow._votes_from_source_pages",
                return_value=[
                    {
                        "value": "Net Income -489.98M",
                        "normalized_value": "-48998万",
                        "canonical": "-48998万",
                        "source": "公开来源页读取",
                        "kind": "source_page",
                        "url": "https://stockanalysis.com/quote/hkg/1097/statistics/",
                    },
                    {
                        "value": "Net Income -489.98M",
                        "normalized_value": "-48998万",
                        "canonical": "-48998万",
                        "source": "公开来源页读取",
                        "kind": "source_page",
                        "url": "https://stockanalysis.com/quote/hkg/1097/financials/",
                    },
                ],
            ),
        ):
            result = search_verify_facts(
                {
                    "run_id": "unit-test",
                    "search_verify_workers": 1,
                    "search_verify_online": True,
                    "search_verify_online_limit": 1,
                    "tasks": [
                        {
                            "id": "icable-profit",
                            "raw_text": "Segment profit before depreciation was HK$243,000,000, not net profit.",
                            "sources": ["https://stockanalysis.com/quote/hkg/1097/financials/"],
                        }
                    ],
                    "existing_items": {},
                    "candidates": [
                        {
                            "id": "icable-profit",
                            "company": "i-CABLE",
                            "metric": "净利润",
                            "value": "243,000,000港元；291,000,000港元；26,000,000港元；27%",
                            "basis": "片段描述的是未扣除折旧、其他无形资产摊销及减值亏损前的经营费用和分部溢利，并非净利润。",
                            "status": "ok",
                            "entity_supported": True,
                            "metric_supported": True,
                            "value_supported": True,
                            "confidence": 0.9,
                            "source_score": 1.0,
                            "source_tier": "official",
                            "row_ref": "row_17",
                            "sources": ["https://stockanalysis.com/quote/hkg/1097/financials/"],
                            "quality_score": 0.99,
                            "decision": "accepted",
                            "reasons": [],
                        }
                    ],
                }
            )
        fact = result["candidates"][0]
        votes = fact["search_verification"]["votes"]
        self.assertEqual(fact["decision"], "accepted")
        self.assertEqual(fact["status"], "ok")
        self.assertEqual(fact["value"], "-48998万港元")
        self.assertEqual(fact["search_verification"]["decision"], "majority_corrected")
        self.assertTrue(fact["search_verification"]["online_search"]["enabled"])
        self.assertNotIn("candidate", {vote["kind"] for vote in votes})
        self.assertNotIn("local_evidence", {vote["kind"] for vote in votes})

    def test_source_page_ignores_unrelated_numeric_value(self) -> None:
        class FakeResponse:
            text = "<html><body>Adjusted EBITDA margin changed by -1.4% year over year.</body></html>"

            def raise_for_status(self) -> None:
                return None

        fact = CandidateFact(
            id="att-fwa",
            company="AT&T",
            metric="FWA",
            value="2026年一季度固定无线净增29.2万；AT&T Internet Air收入增长超过100%",
            basis="AT&T reported 292,000 fixed wireless net adds and AIA revenue exceeded 100 percent.",
            status="ok",
            entity_supported=True,
            metric_supported=True,
            value_supported=True,
            confidence=0.96,
            source_score=0.72,
            source_tier="public",
            row_ref="row_20",
            sources=["https://investors.att.com/report"],
            quality_score=0.968,
            decision="accepted",
        )
        with patch("httpx.get", return_value=FakeResponse()):
            self.assertEqual(_votes_from_source_pages(fact), [])

    def test_search_verifier_matches_wan_unit_to_raw_integer(self) -> None:
        result = search_verify_facts(
            {
                "run_id": "unit-test",
                "search_verify_workers": 1,
                "tasks": [
                    {
                        "id": "att-fwa",
                        "raw_text": (
                            "During the first quarter of 2026, AT&T reported 292,000 "
                            "fixed wireless net adds, and Internet Air revenue exceeded 100 percent."
                        ),
                        "sources": ["https://investors.att.com/report"],
                    }
                ],
                "existing_items": {},
                "candidates": [
                    {
                        "id": "att-fwa",
                        "company": "AT&T",
                        "metric": "FWA",
                        "value": "2026年一季度固定无线净增29.2万；AT&T Internet Air收入增长超过100%",
                        "basis": "AT&T reported 292,000 fixed wireless net adds and AIA revenue exceeded 100 percent.",
                        "status": "ok",
                        "entity_supported": True,
                        "metric_supported": True,
                        "value_supported": True,
                        "confidence": 0.96,
                        "source_score": 0.72,
                        "source_tier": "public",
                        "row_ref": "row_20",
                        "sources": ["https://investors.att.com/report"],
                        "quality_score": 0.968,
                        "decision": "accepted",
                    }
                ],
            }
        )
        verification = result["candidates"][0]["search_verification"]
        self.assertEqual(result["candidates"][0]["decision"], "accepted")
        self.assertGreaterEqual(verification["vote_count"], 2)
        self.assertEqual(verification["decision"], "majority_confirmed")

    def test_search_verifier_trusts_official_basis_over_unrelated_same_page_numbers(self) -> None:
        result = search_verify_facts(
            {
                "run_id": "unit-test",
                "search_verify_workers": 1,
                "tasks": [
                    {
                        "id": "hutchison-customers",
                        "raw_text": "customers to total customer base (%) 16%; customer service revenue (%) 76%; customers (%) 0.9%",
                        "sources": ["https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0401/2026040102176.pdf"],
                    }
                ],
                "existing_items": {},
                "candidates": [
                    {
                        "id": "hutchison-customers",
                        "company": "Hutchison",
                        "metric": "客户数/用户数",
                        "value": "后付费客户128.9万；预付费客户684.3万；客户总数813.2万",
                        "basis": "后付费客户128.9万；预付费客户684.3万；客户总数813.2万",
                        "status": "ok",
                        "entity_supported": True,
                        "metric_supported": True,
                        "value_supported": True,
                        "confidence": 0.96,
                        "source_score": 1.0,
                        "source_tier": "official",
                        "row_ref": "row_5",
                        "sources": ["https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0401/2026040102176.pdf"],
                        "quality_score": 0.996,
                        "decision": "accepted",
                    }
                ],
            }
        )
        fact = result["candidates"][0]
        self.assertEqual(fact["decision"], "accepted")
        self.assertEqual(fact["search_verification"]["decision"], "majority_confirmed")
        self.assertIn("basis_in_official_evidence", {vote["kind"] for vote in fact["search_verification"]["votes"]})

    def test_search_verifier_keeps_monitoring_closure_when_source_page_has_noise(self) -> None:
        result = search_verify_facts(
            {
                "run_id": "unit-test",
                "search_verify_workers": 1,
                "tasks": [
                    {
                        "id": "smartone-roaming",
                        "raw_text": "Roaming data pack $178. APAC worldwide roaming data pack $99 1GB.",
                        "sources": ["https://5g.smartone.com/en/mobile_and_price_plans/roaming/apac_worldwide_roaming_data_pack/charges.jsp"],
                    }
                ],
                "existing_items": {},
                "candidates": [
                    {
                        "id": "smartone-roaming",
                        "company": "SmarTone",
                        "metric": "漫游",
                        "value": "本轮公开来源未发现SmarTone关于漫游的可核验披露；维持后续监测。",
                        "basis": "已检查本轮抓取来源，现有证据显示该指标未披露或仅出现导航/栏目/泛化描述。",
                        "note": "缺口闭环为未披露监测结论",
                        "status": "ok",
                        "entity_supported": True,
                        "metric_supported": True,
                        "value_supported": True,
                        "confidence": 0.9,
                        "source_score": 1.0,
                        "source_tier": "official",
                        "row_ref": "row_9",
                        "sources": ["https://5g.smartone.com/en/mobile_and_price_plans/roaming/apac_worldwide_roaming_data_pack/charges.jsp"],
                        "quality_score": 0.985,
                        "decision": "accepted",
                    }
                ],
            }
        )
        fact = result["candidates"][0]
        self.assertEqual(fact["decision"], "accepted")
        self.assertEqual(fact["search_verification"]["decision"], "majority_confirmed")
        self.assertEqual(fact["search_verification"]["conflict_count"], 0)

    def test_quality_audit_adds_hkd_unit_to_hk_financial_wan_value(self) -> None:
        result = audit_quality(
            {
                "run_id": "unit-test",
                "candidates": [
                    {
                        "id": "icable-profit",
                        "company": "i-CABLE",
                        "metric": "净利润",
                        "value": "-48998万",
                        "basis": "Net Income -489.98M, currency HKD.",
                        "note": "",
                        "status": "ok",
                        "entity_supported": True,
                        "metric_supported": True,
                        "value_supported": True,
                        "confidence": 0.95,
                        "source_score": 1.0,
                        "source_tier": "official",
                        "row_ref": "row_17",
                        "sources": ["https://stockanalysis.com/quote/hkg/1097/financials/"],
                        "quality_score": 0.99,
                        "decision": "accepted",
                    },
                ],
            }
        )
        fact = result["candidates"][0]
        self.assertEqual(fact["decision"], "accepted")
        self.assertEqual(fact["value"], "-48998万港元")
        self.assertNotIn("未通过指标格式与单位门禁", fact["reasons"])

    def test_quality_audit_adds_context_unit_to_multi_year_financial_values(self) -> None:
        result = audit_quality(
            {
                "run_id": "unit-test",
                "candidates": [
                    {
                        "id": "hutchison-ebitda",
                        "company": "Hutchison",
                        "metric": "EBITDA",
                        "value": "1,508 (2025); 1,511 (2024)",
                        "basis": "片段中明确列出 'EBITDA (2) 1,508 1,511'，单位为百万港元。",
                        "note": "",
                        "status": "ok",
                        "entity_supported": True,
                        "metric_supported": True,
                        "value_supported": True,
                        "confidence": 0.95,
                        "source_score": 1.0,
                        "source_tier": "official",
                        "row_ref": "row_5",
                        "sources": ["https://www.hthkh.com/en/ir/reports.php"],
                        "quality_score": 0.99,
                        "decision": "accepted",
                    },
                ],
            }
        )
        fact = result["candidates"][0]
        self.assertEqual(fact["decision"], "accepted")
        self.assertEqual(fact["value"], "2025: 1,508百万港元；2024: 1,511百万港元")
        self.assertNotIn("未通过指标格式与单位门禁", fact["reasons"])

    def test_gap_targets_restrict_recrawl_entities_and_metrics(self) -> None:
        rows = [
            {
                "row": "5",
                "entities": ["3HK", "Hutchison"],
                "sources": "",
            }
        ]
        with patch.dict(
            "os.environ",
            {
                "CMHK_GAP_TARGETS": (
                    '{"5":{"companies":["Hutchison"],'
                    '"metrics":["客户数/用户数","市场反应"]}}'
                )
            },
            clear=False,
        ):
            configured = apply_crawl_settings(rows)
        self.assertEqual(configured[0]["entities"], ["Hutchison"])
        self.assertEqual(configured[0]["selected_fields"], ["客户数/用户数", "市场反应"])

    def test_verified_icable_fields_recover_from_evidence_gap(self) -> None:
        result = audit_quality(
            {
                "candidates": [
                    {
                        "id": "icable-dividend",
                        "row_ref": "row_17",
                        "company": "i-CABLE",
                        "metric": "派息",
                        "status": "unavailable",
                        "value": "",
                        "basis": "",
                        "note": "",
                        "sources": [],
                        "source_score": 0.0,
                        "source_tier": "missing",
                        "entity_supported": False,
                        "metric_supported": False,
                        "value_supported": False,
                        "confidence": 0.0,
                        "reasons": ["主体归属未通过", "抽取结果不可用"],
                    }
                ]
            }
        )
        fact = result["candidates"][0]
        self.assertEqual(fact["decision"], "accepted")
        self.assertEqual(fact["status"], "ok")
        self.assertIn("不建议派发2025年度末期股息", fact["value"])
        self.assertEqual(fact["reasons"], [])


if __name__ == "__main__":
    unittest.main()

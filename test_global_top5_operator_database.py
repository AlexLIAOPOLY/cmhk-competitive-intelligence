import json
import subprocess
import sys
import unittest
from pathlib import Path

import rag_llm
import agent


ROOT = Path(__file__).resolve().parent
GLOBAL = ROOT / "agent_knowledge" / "global_top5_operators_2016_2025"
ORIGINAL = ROOT / "agent_knowledge" / "quarterly_competitor_metrics_2026-06-18"


class GlobalTop5OperatorDatabaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_global_top5_operator_database.py")],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        cls.payload = json.loads((GLOBAL / "annual_metrics.json").read_text(encoding="utf-8"))
        cls.rows = cls.payload["rows"]
        cls.index = {(r["operator_id"], r["year"], r["metric_key"]): r for r in cls.rows}

    def test_quality_gate_and_unique_keys(self):
        audit = json.loads((GLOBAL / "quality_audit.json").read_text(encoding="utf-8"))
        self.assertEqual(audit["status"], "backlog_open")
        self.assertGreater(audit["below_three_source_rows"], 0)
        self.assertEqual(audit["duplicate_key_count"], 0)
        self.assertEqual(audit["invalid_source_ids"], [])
        self.assertEqual(
            audit["three_source_certified_rows_by_operator"],
            {
                "Bharti Airtel": 45,
                "Reliance Jio": 23,
                "中国电信": 57,
                "中国移动": 68,
                "中国联通": 52,
            },
        )
        audit_text = (GLOBAL / "quality_audit.md").read_text(encoding="utf-8")
        self.assertIn("## 全库核验等级", audit_text)
        self.assertIn("## 三来源认证行（按运营商）", audit_text)
        self.assertIn("- Bharti Airtel: 45", audit_text)

    def test_anchor_values_and_customer_scope(self):
        expected = {
            ("china_mobile", 2025, "mobile_subscribers"): 1005,
            ("china_telecom", 2025, "5g_network_subscribers"): 301.81,
            ("china_unicom", 2025, "5g_network_subscribers"): 232.18,
            ("bharti_airtel", 2025, "total_customers"): 590.514,
            ("reliance_jio", 2025, "total_customers"): 488.2,
        }
        for key, value in expected.items():
            self.assertEqual(self.index[key]["value"], value)
        self.assertNotIn(("bharti_airtel", 2025, "mobile_subscribers"), self.index)
        self.assertNotIn(("reliance_jio", 2025, "mobile_subscribers"), self.index)

    def test_5g_definitions_and_shared_network_are_explicit(self):
        metric_keys = {r["metric_key"] for r in self.rows}
        self.assertIn("5g_package_subscribers", metric_keys)
        self.assertIn("5g_network_subscribers", metric_keys)
        for operator_id in ("china_telecom", "china_unicom"):
            row = self.index[(operator_id, 2025, "5g_base_stations")]
            self.assertIn("Shared-network scope", row["quality_note"])
            self.assertEqual(row["distinct_source_document_count"], 3)
        for year in (2020, 2021, 2023, 2024):
            for operator_id in ("china_telecom", "china_unicom"):
                self.assertEqual(
                    self.index[(operator_id, year, "5g_base_stations")]["triple_source_status"],
                    "three_distinct_sources_verified",
                )
        for operator_id in ("china_telecom", "china_unicom"):
            self.assertEqual(
                self.index[(operator_id, 2022, "5g_base_stations")]["triple_source_status"],
                "below_three_source_threshold",
            )
        for year in range(2021, 2026):
            self.assertEqual(
                self.index[("china_mobile", year, "5g_base_stations")]["triple_source_status"],
                "three_distinct_sources_verified",
            )

    def test_precommercial_and_derived_values_are_not_overstated(self):
        jio = self.index[("reliance_jio", 2016, "total_customers")]
        self.assertIsNone(jio["value"])
        self.assertEqual(jio["verification_status"], "not_applicable_precommercial")
        unicom = self.index[("china_unicom", 2025, "mobile_subscribers")]
        self.assertEqual(unicom["verification_status"], "official_derived_from_verified_rows")
        self.assertEqual(unicom["comparator"], "≈")
        self.assertEqual(unicom["triple_source_status"], "derived_not_directly_disclosed")
        missing = self.index[("china_unicom", 2025, "mobile_arpu")]
        self.assertEqual(missing["distinct_source_document_count"], 0)
        self.assertEqual(missing["triple_source_status"], "not_applicable_missing_value")

    def test_china_sidecar_only_adds_operating_metrics(self):
        sidecar = json.loads((ORIGINAL / "annual_operating_metrics_2016_2025.json").read_text(encoding="utf-8"))
        self.assertEqual({r["operator_id"] for r in sidecar["rows"]}, {"china_mobile", "china_telecom", "china_unicom"})
        financial_metrics = {"revenue", "ebitda", "ebit", "earnings_before_tax", "net_profit", "capex", "net_debt", "shareholders_equity"}
        self.assertFalse(financial_metrics & {r["metric_key"] for r in sidecar["rows"]})

    def test_xiaojing_ai_exact_retrieval_respects_selected_database(self):
        question = "中国移动2025移动用户数、中国电信2025年5G网络用户数、Jio FY2025总客户数和移动ARPU"
        chunks = rag_llm._global_operator_exact_metric_chunks(
            question,
            dataset_ids={"global_top5_operators_2016_2025"},
        )
        combined = "\n".join(chunk["text"] for chunk in chunks)
        self.assertIn("operator=中国移动", combined)
        self.assertIn("official_value=1005 million_subscribers", combined)
        self.assertIn("operator=中国电信", combined)
        self.assertIn("official_value=301.81 million_subscribers", combined)
        self.assertIn("operator=Reliance Jio", combined)
        self.assertIn("official_value=488.2 million_customers", combined)
        self.assertIn("official_value=206.2 INR_per_user_month", combined)
        self.assertEqual(
            rag_llm._global_operator_exact_metric_chunks(
                question,
                dataset_ids={"cloud_vendor_database"},
            ),
            [],
        )

    def test_xiaojing_ai_retrieves_new_disclosures_with_strict_source_status(self):
        cases = [
            ("中国移动2025年融合宽带网络客户", "official_value=329 million_customers", 3),
            ("中国移动2025年家庭客户综合ARPU", "official_value=44.5 RMB_per_user_month", 3),
            ("中国电信2025年移动ARPU", "official_value=45.1 RMB_per_user_month", 3),
            ("中国联通2025年5G网络用户", "official_value=232.18 million_subscribers", 3),
            ("中国联通2025年连接用户总规模", "official_value=1200 million_connections", 3),
        ]
        for question, value_text, strict_count in cases:
            combined = "\n".join(
                chunk["text"]
                for chunk in rag_llm._global_operator_exact_metric_chunks(
                    question,
                    dataset_ids={"global_top5_operators_2016_2025"},
                )
            )
            self.assertIn(value_text, combined)
            self.assertIn(f"distinct_source_document_count={strict_count}", combined)

    def test_exact_iot_value_uses_three_exact_documents_not_rounded_materials(self):
        row = self.index[("china_mobile", 2025, "iot_connections")]
        self.assertEqual(row["value"], 1482)
        self.assertEqual(row["distinct_source_document_count"], 4)
        self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
        self.assertEqual(
            set(row["verification_sources"]),
            {"china_mobile_ar_2025", "china_mobile_ar_a_2025", "china_mobile_ar_summary_2025", "china_mobile_q1_2026_comparatives"},
        )

    def test_2025_dou_has_three_separate_legal_disclosure_documents(self):
        row = self.index[("china_mobile", 2025, "mobile_dou")]
        self.assertEqual(row["value"], 17.3)
        self.assertEqual(row["distinct_source_document_count"], 3)
        self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
        self.assertEqual(
            set(row["verification_sources"]),
            {"china_mobile_ar_2025", "china_mobile_ar_a_2025", "china_mobile_ar_summary_2025"},
        )

    def test_2025_gigabit_broadband_uses_exact_not_rounded_values(self):
        row = self.index[("china_mobile", 2025, "gigabit_broadband_customers")]
        self.assertEqual(row["value"], 109)
        self.assertEqual(row["distinct_source_document_count"], 3)
        self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")

    def test_jio_2025_metric_sources_match_the_disclosed_scope_and_value(self):
        certified = {
            "total_customers": 3,
            "value_of_sales_and_services": 3,
            "ebitda": 3,
            "mobile_arpu": 3,
            "mobile_dou": 4,
            "5g_network_subscribers": 4,
            "connected_homes": 3,
        }
        for metric_key, source_count in certified.items():
            row = self.index[("reliance_jio", 2025, metric_key)]
            self.assertEqual(row["distinct_source_document_count"], source_count)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")

        revenue = self.index[("reliance_jio", 2025, "revenue_from_operations")]
        self.assertEqual(revenue["value"], 131336)
        self.assertEqual(revenue["verification_sources"], ["reliance_jio_ar_2025"])
        self.assertEqual(revenue["triple_source_status"], "below_three_source_threshold")
        self.assertIn("128,218", revenue["quality_note"])

        traffic = self.index[("reliance_jio", 2025, "total_data_traffic")]
        self.assertEqual(traffic["value"], 184.5)
        self.assertEqual(traffic["verification_sources"], ["jio_2025_media_release"])
        self.assertEqual(traffic["triple_source_status"], "below_three_source_threshold")

        cells = self.index[("reliance_jio", 2025, "5g_base_stations")]
        self.assertEqual(cells["verification_sources"], ["jio_2025_factsheet"])
        self.assertEqual(cells["triple_source_status"], "below_three_source_threshold")

    def test_jio_2025_source_registry_carries_metric_level_evidence(self):
        sources = {
            source["source_id"]: source
            for source in json.loads((GLOBAL / "sources.json").read_text(encoding="utf-8"))["sources"]
        }
        self.assertEqual(sources["jio_2025_media_release"]["evidence"]["total_data_traffic"]["value"], 184.5)
        self.assertEqual(sources["jio_2025_factsheet"]["evidence"]["connected_homes"]["value"], 18)
        self.assertEqual(sources["jio_q2_2026_integrated_filing"]["evidence"]["ebitda"]["value"], 65001)

    def test_jio_2024_uses_exact_comparatives_and_corrected_home_scope(self):
        certified = {
            "total_customers": 4,
            "value_of_sales_and_services": 3,
            "mobile_arpu": 3,
            "total_data_traffic": 4,
            "5g_network_subscribers": 3,
            "5g_base_stations": 3,
        }
        for metric_key, source_count in certified.items():
            row = self.index[("reliance_jio", 2024, metric_key)]
            self.assertEqual(row["distinct_source_document_count"], source_count)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")

        homes = self.index[("reliance_jio", 2024, "connected_homes")]
        self.assertEqual(homes["value"], 12)
        self.assertEqual(homes["distinct_source_document_count"], 2)
        self.assertEqual(homes["triple_source_status"], "below_three_source_threshold")
        self.assertIn("earlier 11 million", homes["quality_note"])

        revenue = self.index[("reliance_jio", 2024, "revenue_from_operations")]
        self.assertEqual(revenue["verification_sources"], ["reliance_jio_ar_2025"])
        self.assertEqual(revenue["triple_source_status"], "below_three_source_threshold")

        ebitda = self.index[("reliance_jio", 2024, "ebitda")]
        self.assertEqual(ebitda["value"], 56675)
        self.assertEqual(ebitda["distinct_source_document_count"], 2)
        self.assertEqual(ebitda["triple_source_status"], "below_three_source_threshold")

    def test_jio_2023_q4_documents_are_bound_only_to_values_they_disclose(self):
        certified = {
            "total_customers": 3,
            "ebitda": 4,
            "mobile_arpu": 3,
            "total_data_traffic": 3,
            "5g_base_stations": 3,
        }
        for metric_key, source_count in certified.items():
            row = self.index[("reliance_jio", 2023, metric_key)]
            self.assertEqual(row["distinct_source_document_count"], source_count)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")

        gross = self.index[("reliance_jio", 2023, "value_of_sales_and_services")]
        self.assertEqual(gross["value"], 119791)
        self.assertNotIn("jio_2023_media_release", gross["verification_sources"])
        self.assertEqual(gross["distinct_source_document_count"], 2)

        revenue = self.index[("reliance_jio", 2023, "revenue_from_operations")]
        self.assertEqual(revenue["value"], 101961)
        self.assertNotIn("jio_2023_media_release", revenue["verification_sources"])

        dou = self.index[("reliance_jio", 2023, "mobile_dou")]
        self.assertEqual(dou["distinct_source_document_count"], 2)

        homes = self.index[("reliance_jio", 2023, "connected_homes")]
        self.assertEqual(homes["verification_sources"], ["reliance_jio_ar_2023"])

    def test_jio_2022_exact_sources_respect_restated_financials(self):
        certified = {
            "total_customers": 4,
            "ebitda": 3,
            "mobile_arpu": 4,
            "mobile_dou": 3,
            "total_data_traffic": 3,
        }
        for metric_key, source_count in certified.items():
            row = self.index[("reliance_jio", 2022, metric_key)]
            self.assertEqual(row["distinct_source_document_count"], source_count)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")

        gross = self.index[("reliance_jio", 2022, "value_of_sales_and_services")]
        self.assertEqual(gross["value"], 100166)
        self.assertEqual(gross["verification_sources"], ["reliance_jio_ar_2023"])
        self.assertEqual(gross["triple_source_status"], "below_three_source_threshold")
        self.assertIn("100,161", gross["quality_note"])

        revenue = self.index[("reliance_jio", 2022, "revenue_from_operations")]
        self.assertEqual(revenue["value"], 85122)
        self.assertEqual(revenue["verification_sources"], ["reliance_jio_ar_2023"])

        homes = self.index[("reliance_jio", 2022, "connected_homes")]
        self.assertEqual(homes["value"], 5)
        self.assertEqual(homes["distinct_source_document_count"], 2)
        self.assertEqual(homes["triple_source_status"], "below_three_source_threshold")

    def test_airtel_fy2025_uses_three_exact_comparative_documents(self):
        four_sources = {
            "total_customers",
            "revenue",
            "ebitda",
            "earnings_before_tax",
            "net_profit",
            "net_debt",
        }
        three_sources = {"capex", "shareholders_equity", "network_towers"}
        for metric_key in four_sources:
            row = self.index[("bharti_airtel", 2025, metric_key)]
            self.assertEqual(row["distinct_source_document_count"], 5)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
        for metric_key in three_sources:
            row = self.index[("bharti_airtel", 2025, metric_key)]
            self.assertEqual(row["distinct_source_document_count"], 4)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")

        equity = self.index[("bharti_airtel", 2025, "shareholders_equity")]
        self.assertEqual(equity["value"], 1136718)
        self.assertNotIn("bharti_airtel_ar_2025", equity["verification_sources"])
        self.assertIn("1,136,719", equity["quality_note"])

        revenue = self.index[("bharti_airtel", 2025, "revenue")]
        self.assertEqual(revenue["value"], 1815110)
        self.assertIn("1,729,850", revenue["quality_note"])

    def test_airtel_fy2025_source_registry_has_metric_level_evidence(self):
        sources = {
            source["source_id"]: source
            for source in json.loads((GLOBAL / "sources.json").read_text(encoding="utf-8"))["sources"]
        }
        self.assertEqual(sources["airtel_q1_2026_ir_pack"]["evidence"]["revenue"]["value"], 1815110)
        self.assertEqual(sources["airtel_q2_2026_ir_pack"]["evidence"]["shareholders_equity"]["value"], 1136718)
        self.assertEqual(sources["airtel_2025_ir_pack"]["evidence"]["network_towers"]["value"], 375146)
        self.assertEqual(sources["bharti_airtel_ar_2025"]["evidence"]["shareholders_equity"]["value"], 1136719)

    def test_xiaojing_retrieves_airtel_fy2025_three_source_rows(self):
        combined = "\n".join(
            chunk["text"]
            for chunk in rag_llm._global_operator_exact_metric_chunks(
                "Bharti Airtel FY2025总客户数、营业收入、EBITDA、净利润、资本开支、净债务、股东权益和网络铁塔是多少？逐项说明三来源状态。",
                dataset_ids={"global_top5_operators_2016_2025"},
            )
        )
        expected_values = {
            "total_customers": "590.514 million_customers",
            "revenue": "1815110 INR_million",
            "ebitda": "1049994 INR_million",
            "net_profit": "337440 INR_million",
            "capex": "422904 INR_million",
            "net_debt": "2038384 INR_million",
            "shareholders_equity": "1136718 INR_million",
            "network_towers": "375146 sites",
        }
        for metric_key, value_text in expected_values.items():
            self.assertIn(f"metric_key={metric_key}", combined)
            self.assertIn(f"official_value={value_text}", combined)
        self.assertGreaterEqual(combined.count("triple_source_status=three_distinct_sources_verified"), 8)

    def test_airtel_fy2024_uses_three_exact_later_comparative_documents(self):
        expected_values = {
            "total_customers": 561.970,
            "revenue": 1643643,
            "ebitda": 889064,
            "earnings_before_tax": 250532,
            "net_profit": 77820,
            "capex": 489268,
            "net_debt": 1943799,
            "shareholders_equity": 820188,
            "network_towers": 355150,
        }
        expected_sources = {
            "airtel_q1_2026_ir_pack",
            "airtel_q2_2026_ir_pack",
            "airtel_q3_2026_ir_pack",
            "airtel_2025_ir_pack",
        }
        for metric_key, expected_value in expected_values.items():
            row = self.index[("bharti_airtel", 2024, metric_key)]
            self.assertEqual(row["value"], expected_value)
            self.assertEqual(set(row["verification_sources"]), expected_sources)
            self.assertEqual(row["distinct_source_document_count"], 4)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")

    def test_airtel_fy2024_comparative_registry_and_annual_report_identity(self):
        sources = {
            source["source_id"]: source
            for source in json.loads((GLOBAL / "sources.json").read_text(encoding="utf-8"))["sources"]
        }
        for source_id in ("airtel_q1_2026_ir_pack", "airtel_q2_2026_ir_pack", "airtel_q3_2026_ir_pack", "airtel_2025_ir_pack"):
            evidence = sources[source_id]["comparative_evidence"]["FY2024"]
            self.assertEqual(evidence["total_customers"]["value"], 561.970)
            self.assertEqual(evidence["revenue"]["value"], 1643643)
            self.assertEqual(evidence["network_towers"]["value"], 355150)
        self.assertEqual(
            sources["bharti_airtel_ar_2024"]["source_document_id"],
            sources["airtel_2024_five_year"]["source_document_id"],
        )

    def test_airtel_fy2023_uses_latest_recast_three_document_comparatives(self):
        expected_values = {
            "total_customers": 518.446,
            "revenue": 1539257,
            "ebitda": 768378,
            "earnings_before_tax": 185701,
            "net_profit": 82526,
            "capex": 382145,
            "net_debt": 2042234,
            "shareholders_equity": 775629,
            "network_towers": 309054,
        }
        expected_sources = {
            "airtel_q1_2026_ir_pack",
            "airtel_q2_2026_ir_pack",
            "airtel_q3_2026_ir_pack",
        }
        for metric_key, expected_value in expected_values.items():
            row = self.index[("bharti_airtel", 2023, metric_key)]
            self.assertEqual(row["value"], expected_value)
            self.assertEqual(set(row["verification_sources"]), expected_sources)
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
        self.assertIn("1,391,448", self.index[("bharti_airtel", 2023, "revenue")]["quality_note"])
        profit_note = self.index[("bharti_airtel", 2023, "net_profit")]["quality_note"]
        self.assertIn("83,459", profit_note)
        self.assertIn("Both are after-exceptional", profit_note)
        self.assertIn("not a before-exceptional value", profit_note)
        self.assertIn("82,390", profit_note)

    def test_airtel_fy2023_registry_carries_recast_metric_evidence(self):
        sources = {
            source["source_id"]: source
            for source in json.loads((GLOBAL / "sources.json").read_text(encoding="utf-8"))["sources"]
        }
        for source_id in ("airtel_q1_2026_ir_pack", "airtel_q2_2026_ir_pack", "airtel_q3_2026_ir_pack"):
            evidence = sources[source_id]["comparative_evidence"]["FY2023"]
            self.assertEqual(evidence["revenue"]["value"], 1539257)
            self.assertEqual(evidence["net_profit"]["value"], 82526)
            self.assertEqual(evidence["net_debt"]["value"], 2042234)

    def test_xiaojing_retrieves_airtel_fy2023_recast_three_source_rows(self):
        combined = "\n".join(
            chunk["text"]
            for chunk in rag_llm._global_operator_exact_metric_chunks(
                "Bharti Airtel FY2023总客户数、营业收入、EBITDA、净利润、资本开支、净债务、股东权益和网络铁塔是多少？逐项说明三来源和重列口径。",
                dataset_ids={"global_top5_operators_2016_2025"},
            )
        )
        expected_values = {
            "total_customers": "518.446 million_customers",
            "revenue": "1539257 INR_million",
            "ebitda": "768378 INR_million",
            "net_profit": "82526 INR_million",
            "capex": "382145 INR_million",
            "net_debt": "2042234 INR_million",
            "shareholders_equity": "775629 INR_million",
            "network_towers": "309054 sites",
        }
        for metric_key, value_text in expected_values.items():
            self.assertIn(f"metric_key={metric_key}", combined)
            self.assertIn(f"official_value={value_text}", combined)
        self.assertIn("earlier INR1,391,448m basis", combined)
        self.assertGreaterEqual(combined.count("distinct_source_document_count=3"), 8)
        self.assertGreaterEqual(combined.count("triple_source_status=three_distinct_sources_verified"), 8)

    def test_airtel_fy2022_uses_four_exact_ex_indus_comparative_documents(self):
        expected_values = {
            "total_customers": 489.729,
            "revenue": 1165469,
            "ebitda": 581103,
            "earnings_before_tax": 107845,
            "net_profit": 42549,
            "capex": 256616,
            "net_debt": 1603073,
            "shareholders_equity": 665543,
            "network_towers": 268848,
        }
        expected_sources = {
            "airtel_q1_2024_ir_pack",
            "airtel_q2_2024_ir_pack",
            "airtel_q3_2024_ir_pack",
            "airtel_q4_2024_ir_pack",
        }
        for metric_key, expected_value in expected_values.items():
            row = self.index[("bharti_airtel", 2022, metric_key)]
            self.assertEqual(row["value"], expected_value)
            self.assertEqual(set(row["verification_sources"]), expected_sources)
            self.assertEqual(row["distinct_source_document_count"], 4)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
            self.assertIn("explicitly exclude", row["quality_note"])
            self.assertIn("FY2022-FY2023 growth requires a scope-break warning", row["quality_note"])

    def test_airtel_fy2022_registry_carries_metric_level_evidence(self):
        sources = {
            source["source_id"]: source
            for source in json.loads((GLOBAL / "sources.json").read_text(encoding="utf-8"))["sources"]
        }
        for source_id in ("airtel_q1_2024_ir_pack", "airtel_q2_2024_ir_pack", "airtel_q3_2024_ir_pack", "airtel_q4_2024_ir_pack"):
            evidence = sources[source_id]["comparative_evidence"]["FY2022"]
            self.assertEqual(evidence["total_customers"]["value"], 489.729)
            self.assertEqual(evidence["revenue"]["value"], 1165469)
            self.assertEqual(evidence["net_debt"]["value"], 1603073)

    def test_xiaojing_retrieves_airtel_fy2022_four_source_scope_break_rows(self):
        combined = "\n".join(
            chunk["text"]
            for chunk in rag_llm._global_operator_exact_metric_chunks(
                "Bharti Airtel FY2022总客户数、营业收入、EBITDA、净利润、资本开支、净债务、股东权益和网络铁塔是多少？逐项说明三来源状态和FY2022至FY2023口径断点。",
                dataset_ids={"global_top5_operators_2016_2025"},
            )
        )
        expected_values = {
            "total_customers": "489.729 million_customers",
            "revenue": "1165469 INR_million",
            "ebitda": "581103 INR_million",
            "net_profit": "42549 INR_million",
            "capex": "256616 INR_million",
            "net_debt": "1603073 INR_million",
            "shareholders_equity": "665543 INR_million",
            "network_towers": "268848 sites",
        }
        for metric_key, value_text in expected_values.items():
            self.assertIn(f"metric_key={metric_key}", combined)
            self.assertIn(f"official_value={value_text}", combined)
        self.assertIn("explicitly exclude the consolidation impact", combined)
        self.assertGreaterEqual(combined.count("distinct_source_document_count=4"), 8)
        self.assertGreaterEqual(combined.count("triple_source_status=three_distinct_sources_verified"), 8)

    def test_airtel_fy2021_uses_four_exact_later_comparative_documents(self):
        expected_values = {
            "total_customers": 469.864,
            "revenue": 1006158,
            "ebitda": 461387,
            "earnings_before_tax": 22586,
            "net_profit": -150835,
            "capex": 241685,
            "net_debt": 1485076,
            "shareholders_equity": 589527,
            "network_towers": 244504,
        }
        expected_sources = {
            "airtel_q1_2024_ir_pack",
            "airtel_q2_2024_ir_pack",
            "airtel_q3_2024_ir_pack",
            "airtel_q4_2024_ir_pack",
        }
        for metric_key, expected_value in expected_values.items():
            row = self.index[("bharti_airtel", 2021, metric_key)]
            self.assertEqual(row["value"], expected_value)
            self.assertEqual(set(row["verification_sources"]), expected_sources)
            self.assertEqual(row["distinct_source_document_count"], 4)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
            self.assertIn("FY2021 and FY2022 are repeated exactly", row["quality_note"])
        self.assertIn("INR-42,063m", self.index[("bharti_airtel", 2021, "earnings_before_tax")]["quality_note"])

    def test_airtel_fy2021_registry_carries_metric_level_evidence(self):
        sources = {
            source["source_id"]: source
            for source in json.loads((GLOBAL / "sources.json").read_text(encoding="utf-8"))["sources"]
        }
        for source_id in ("airtel_q1_2024_ir_pack", "airtel_q2_2024_ir_pack", "airtel_q3_2024_ir_pack", "airtel_q4_2024_ir_pack"):
            evidence = sources[source_id]["comparative_evidence"]["FY2021"]
            self.assertEqual(evidence["total_customers"]["value"], 469.864)
            self.assertEqual(evidence["earnings_before_tax"]["value"], 22586)
            self.assertEqual(evidence["network_towers"]["value"], 244504)

    def test_xiaojing_retrieves_airtel_fy2021_four_source_recast_rows(self):
        combined = "\n".join(
            chunk["text"]
            for chunk in rag_llm._global_operator_exact_metric_chunks(
                "Bharti Airtel FY2021总客户数、营业收入、EBITDA、税前利润、净利润、资本开支、净债务、股东权益和网络铁塔是多少？逐项说明三来源和税前利润重列。",
                dataset_ids={"global_top5_operators_2016_2025"},
            )
        )
        expected_values = {
            "total_customers": "469.864 million_customers",
            "revenue": "1006158 INR_million",
            "ebitda": "461387 INR_million",
            "earnings_before_tax": "22586 INR_million",
            "net_profit": "-150835 INR_million",
            "capex": "241685 INR_million",
            "net_debt": "1485076 INR_million",
            "shareholders_equity": "589527 INR_million",
            "network_towers": "244504 sites",
        }
        for metric_key, value_text in expected_values.items():
            self.assertIn(f"metric_key={metric_key}", combined)
            self.assertIn(f"official_value={value_text}", combined)
        self.assertIn("earlier loss-before-tax value of INR-42,063m", combined)
        self.assertGreaterEqual(combined.count("distinct_source_document_count=4"), 9)
        self.assertGreaterEqual(combined.count("triple_source_status=three_distinct_sources_verified"), 9)

    def test_xiaojing_retrieves_airtel_fy2024_three_source_rows(self):
        combined = "\n".join(
            chunk["text"]
            for chunk in rag_llm._global_operator_exact_metric_chunks(
                "Bharti Airtel FY2024总客户数、营业收入、EBITDA、净利润、资本开支、净债务、股东权益和网络铁塔是多少？逐项说明三来源状态。",
                dataset_ids={"global_top5_operators_2016_2025"},
            )
        )
        expected_values = {
            "total_customers": "561.97 million_customers",
            "revenue": "1643643 INR_million",
            "ebitda": "889064 INR_million",
            "net_profit": "77820 INR_million",
            "capex": "489268 INR_million",
            "net_debt": "1943799 INR_million",
            "shareholders_equity": "820188 INR_million",
            "network_towers": "355150 sites",
        }
        for metric_key, value_text in expected_values.items():
            self.assertIn(f"metric_key={metric_key}", combined)
            self.assertIn(f"official_value={value_text}", combined)
        self.assertGreaterEqual(combined.count("distinct_source_document_count=4"), 8)
        self.assertGreaterEqual(combined.count("triple_source_status=three_distinct_sources_verified"), 8)

    def test_xiaojing_understands_common_customer_and_traffic_shorthand(self):
        combined = "\n".join(
            chunk["text"]
            for chunk in rag_llm._global_operator_exact_metric_chunks(
                "Reliance Jio FY2022 的客户数、ARPU、DOU、数据流量、EBITDA分别是多少？逐项说明三来源状态。",
                dataset_ids={"global_top5_operators_2016_2025"},
            )
        )
        expected = {
            "total_customers": "official_value=410.2 million_customers",
            "mobile_arpu": "official_value=167.6 INR_per_user_month",
            "mobile_dou": "official_value=19.7 GB_per_user_month",
            "total_data_traffic": "official_value=91.4 billion_GB",
            "ebitda": "official_value=40268 INR_crore",
        }
        for metric_key, value_text in expected.items():
            self.assertIn(f"metric_key={metric_key}", combined)
            self.assertIn(value_text, combined)
        self.assertGreaterEqual(combined.count("triple_source_status=three_distinct_sources_verified"), 5)

    def test_xiaojing_compound_query_inherits_single_operator_across_clauses(self):
        combined = "\n".join(
            chunk["text"]
            for chunk in rag_llm._global_operator_exact_metric_chunks(
                "中国移动2025年DOU、千兆宽带客户和物联网卡连接数分别是多少？三来源状态呢？",
                dataset_ids={"global_top5_operators_2016_2025"},
            )
        )
        self.assertIn("metric_key=mobile_dou", combined)
        self.assertIn("official_value=17.3 GB_per_user_month", combined)
        self.assertIn("metric_key=gigabit_broadband_customers", combined)
        self.assertIn("official_value=109 million_customers", combined)
        self.assertIn("metric_key=iot_connections", combined)
        self.assertIn("official_value=1482 million_connections", combined)
        self.assertGreaterEqual(combined.count("triple_source_status=three_distinct_sources_verified"), 3)

    def test_source_registry_has_canonical_document_identity(self):
        sources = json.loads((GLOBAL / "sources.json").read_text(encoding="utf-8"))["sources"]
        self.assertTrue(sources)
        self.assertTrue(all(source.get("source_document_id") for source in sources))

    def test_derived_annual_traffic_is_not_three_source_certified(self):
        for year in range(2016, 2026):
            row = self.index[("china_mobile", year, "handset_data_traffic")]
            self.assertEqual(row["basis"], "official_quarterly_sum")
            self.assertEqual(row["triple_source_status"], "derived_not_directly_disclosed")

    def test_compound_question_keeps_operator_metric_pairs_and_skips_gaps(self):
        question = "中国移动2025年融合宽带网络客户、中国电信2025年移动ARPU、中国联通2025年连接用户总规模"
        combined = "\n".join(
            chunk["text"]
            for chunk in rag_llm._global_operator_exact_metric_chunks(
                question,
                dataset_ids={"global_top5_operators_2016_2025"},
            )
        )
        self.assertIn("operator=中国移动", combined)
        self.assertIn("metric_key=integrated_broadband_network_customers", combined)
        self.assertIn("operator=中国电信", combined)
        self.assertIn("official_value=45.1 RMB_per_user_month", combined)
        self.assertIn("operator=中国联通", combined)
        self.assertIn("metric_key=total_connectivity_subscribers", combined)
        self.assertNotIn("operator=中国移动; operator_id=china_mobile; period=FY2025; period_end=2025-12-31; metric_key=mobile_arpu", combined)
        self.assertNotIn("metric_key=mobile_arpu; metric_zh=移动ARPU; official_value= RMB", combined)

    def test_agent_keeps_original_compound_exact_rows_when_tool_query_drifts(self):
        dataset_token = agent.SELECTED_DATASET_IDS.set({"global_top5_operators_2016_2025"})
        request_token = agent.CURRENT_USER_REQUEST.set(
            "中国移动2025年融合宽带网络客户、中国电信2025年移动ARPU、中国联通2025年连接用户总规模"
        )
        try:
            result = agent._search_local_reports_only("中国移动2025年资本开支", 6)
        finally:
            agent.CURRENT_USER_REQUEST.reset(request_token)
            agent.SELECTED_DATASET_IDS.reset(dataset_token)
        first_results = result.split("[来源 4:", 1)[0]
        self.assertIn("metric_key=integrated_broadband_network_customers", first_results)
        self.assertIn("official_value=45.1 RMB_per_user_month", first_results)
        self.assertIn("metric_key=total_connectivity_subscribers", first_results)


if __name__ == "__main__":
    unittest.main()

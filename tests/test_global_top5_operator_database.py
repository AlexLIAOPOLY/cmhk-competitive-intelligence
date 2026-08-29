import json
import subprocess
import sys
import unittest
from pathlib import Path

import cmhk.agent.rag as rag_llm
import agent


ROOT = Path(__file__).resolve().parents[1]
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
                "AT&T": 42,
                "Bharti Airtel": 98,
                "Deutsche Telekom": 40,
                "NTT Group": 37,
                "Reliance Jio": 27,
                "Verizon": 39,
                "中国广电": 6,
                "中国电信": 64,
                "中国移动": 80,
                "中国联通": 65,
            },
        )
        audit_text = (GLOBAL / "quality_audit.md").read_text(encoding="utf-8")
        self.assertIn("## 全库核验等级", audit_text)
        self.assertIn("## 三来源认证行（按运营商）", audit_text)
        self.assertIn("- Bharti Airtel: 98", audit_text)

    def test_requested_international_operators_keep_all_official_values(self):
        requested = {"verizon", "deutsche_telekom", "att", "ntt_group"}
        rows = [row for row in self.rows if row["operator_id"] in requested]
        self.assertEqual(len(rows), 167)
        self.assertEqual({row["operator_id"] for row in rows}, requested)
        self.assertTrue({"revenue", "net_profit", "reported_mobile_connections", "adjusted_ebitda",
                         "adjusted_ebitda_margin", "postpaid_connections"}.issubset(
                            {row["metric_key"] for row in rows}
                         ))
        self.assertFalse(any(row["verification_status"] == "source_gap_confirmed" for row in rows))
        ntt_ebitda = [row for row in rows if row["operator_id"] == "ntt_group" and row["metric_key"] == "adjusted_ebitda"]
        self.assertEqual(len(ntt_ebitda), 10)
        self.assertEqual(ntt_ebitda[0]["verification_status"], "official_single_source")
        self.assertEqual(ntt_ebitda[0]["distinct_source_document_count"], 1)
        self.assertFalse(any("comcast" in str(row).lower() for row in self.rows))

    def test_xiaojing_exact_retrieval_recognizes_requested_operators(self):
        cases = {
            "Verizon FY2025营收是多少？": ("operator=Verizon", "official_value=138191 USD_million"),
            "德国电信 FY2025移动连接数是多少？": ("operator=Deutsche Telekom", "official_value=273.2 million_connections"),
            "AT&T FY2025净利润是多少？": ("operator=AT&T", "official_value=21953 USD_million"),
            "NTT Group FY2025营收是多少？": ("operator=NTT Group", "official_value=14409.1 JPY_billion"),
        }
        for question, expected in cases.items():
            chunks = rag_llm._global_operator_exact_metric_chunks(
                question, dataset_ids={"global_top5_operators_2016_2025"}
            )
            combined = "\n".join(chunk["text"] for chunk in chunks)
            self.assertIn(expected[0], combined)
            self.assertIn(expected[1], combined)
            self.assertIn("distinct_source_document_count=3", combined)
            self.assertIn("triple_source_status=three_distinct_sources_verified", combined)

    def test_china_broadnet_2024_5g_users_have_exact_metric_evidence(self):
        row = self.index[("china_broadnet", 2024, "5g_network_subscribers")]
        self.assertGreaterEqual(len(row["candidate_sources"]), 3)
        self.assertEqual(len(row["verification_sources"]), 4)
        self.assertEqual(row["distinct_source_document_count"], 4)
        self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")

    def test_china_telecom_historical_subscriber_series_use_three_exact_documents(self):
        for year in range(2016, 2025):
            expected_sources = {
                f"china_telecom_kpi_{year}",
                f"china_telecom_results_{year}",
                f"china_telecom_press_{year}",
            }
            for metric_key in ("mobile_subscribers", "fixed_broadband_subscribers"):
                row = self.index[("china_telecom", year, metric_key)]
                self.assertEqual(set(row["verification_sources"]), expected_sources)
                self.assertEqual(row["distinct_source_document_count"], 3)
                self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")

        for year in range(2016, 2019):
            row = self.index[("china_telecom", year, "4g_subscribers")]
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")

    def test_china_telecom_fy2019_5g_package_value_uses_year_end_scope(self):
        row = self.index[("china_telecom", 2019, "5g_package_subscribers")]
        self.assertEqual(row["value"], 4.61)
        self.assertNotEqual(row["value"], 10.73)
        self.assertEqual(
            set(row["verification_sources"]),
            {"china_telecom_results_2019", "china_telecom_results_2020", "china_telecom_press_2020"},
        )
        self.assertEqual(row["distinct_source_document_count"], 3)
        self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
        self.assertIn("February 2020", row["quality_note"])

    def test_china_telecom_5g_package_history_uses_three_exact_documents(self):
        for year in range(2020, 2025):
            row = self.index[("china_telecom", year, "5g_package_subscribers")]
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")

    def test_china_telecom_historical_arpu_and_traffic_keep_exact_scope(self):
        for year in (2016, 2017, 2020, 2021, 2022, 2023, 2024):
            row = self.index[("china_telecom", year, "mobile_arpu")]
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
        for year in (2018, 2019):
            row = self.index[("china_telecom", year, "mobile_arpu")]
            self.assertIsNone(row["value"])
            self.assertEqual(row["triple_source_status"], "not_applicable_missing_value")

        for year in range(2016, 2024):
            row = self.index[("china_telecom", year, "handset_data_traffic")]
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
        self.assertEqual(self.index[("china_telecom", 2023, "handset_data_traffic")]["value"], 72.772)

        for year in range(2019, 2025):
            row = self.index[("china_telecom", year, "broadband_arpu")]
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
            self.assertIn("blended", row["scope"])

        traffic_text = "\n".join(
            chunk["text"]
            for chunk in rag_llm._global_operator_exact_metric_chunks(
                "中国电信2023年手机数据流量",
                dataset_ids={"global_top5_operators_2016_2025"},
            )
        )
        self.assertIn("official_value=72.772 billion_GB", traffic_text)
        self.assertIn("distinct_source_document_count=3", traffic_text)

    def test_jio_early_candidate_sources_without_exact_bindings_are_not_certified(self):
        legacy_candidate_rows = [
            (2017, "total_customers"),
            (2018, "total_customers"),
            (2018, "value_of_sales_and_services"),
            (2018, "ebit"),
            (2019, "total_customers"),
            (2019, "mobile_arpu"),
            (2019, "mobile_dou"),
            (2020, "total_customers"),
            (2020, "mobile_arpu"),
            (2020, "mobile_dou"),
            (2020, "ebitda"),
            (2021, "total_customers"),
            (2021, "mobile_arpu"),
            (2021, "mobile_dou"),
            (2021, "total_data_traffic"),
            (2021, "ebitda"),
        ]
        for year, metric_key in legacy_candidate_rows:
            row = self.index[("reliance_jio", year, metric_key)]
            self.assertLess(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "below_three_source_threshold")
            self.assertGreaterEqual(len(row["candidate_sources"]), len(row["verification_sources"]))

    def test_airtel_fy2017_mobile_broadband_base_stations_use_year_end_total(self):
        row = self.index[("bharti_airtel", 2017, "mobile_broadband_base_stations")]
        self.assertEqual(row["value"], 190860)
        self.assertNotEqual(row["value"], 136479)
        self.assertEqual(row["distinct_source_document_count"], 5)
        self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
        self.assertIn("cumulative rollout over two years", row["quality_note"])

    def test_jio_fy2018_churn_has_four_independent_official_documents(self):
        row = self.index[("reliance_jio", 2018, "churn")]
        self.assertEqual(row["value"], 0.25)
        self.assertEqual(row["unit"], "percent_per_month")
        self.assertEqual(row["basis"], "exit_quarter")
        self.assertEqual(row["distinct_source_document_count"], 4)
        self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
        self.assertEqual(
            set(row["verification_sources"]),
            {
                "reliance_jio_ar_2018",
                "jio_2018_q4_media_release",
                "jio_2018_standalone_media_release",
                "reliance_sustainability_2018",
            },
        )

        chunks = rag_llm._global_operator_exact_metric_chunks(
            "Jio FY2018月度用户流失率是多少？",
            dataset_ids={"global_top5_operators_2016_2025"},
        )
        text = "\n".join(chunk["text"] for chunk in chunks)
        self.assertIn("metric_key=churn", text)
        self.assertIn("official_value=0.25 percent_per_month", text)
        self.assertIn("distinct_source_document_count=4", text)

    def test_jio_early_official_arpu_and_dou_values_are_retained_with_quality_labels(self):
        dou_2017 = self.index[("reliance_jio", 2017, "mobile_dou")]
        arpu_2018 = self.index[("reliance_jio", 2018, "mobile_arpu")]
        dou_2018 = self.index[("reliance_jio", 2018, "mobile_dou")]
        self.assertEqual(dou_2017["value"], 10)
        self.assertEqual(arpu_2018["value"], 137)
        self.assertEqual(dou_2018["value"], 9.7)
        for row in (dou_2017, arpu_2018, dou_2018):
            self.assertEqual(row["verification_status"], "official_single_source")
            self.assertEqual(row["distinct_source_document_count"], 1)
            self.assertEqual(row["triple_source_status"], "below_three_source_threshold")

        arpu_2017 = self.index[("reliance_jio", 2017, "mobile_arpu")]
        users_2023 = self.index[("reliance_jio", 2023, "5g_network_subscribers")]
        self.assertIsNone(arpu_2017["value"])
        self.assertIn("did not disclose a comparable paid", arpu_2017["quality_note"])
        self.assertIsNone(users_2023["value"])
        self.assertIn("Targeted review", users_2023["quality_note"])

    def test_jio_early_financial_sources_preserve_values_without_overcertifying(self):
        ebit_2019 = self.index[("reliance_jio", 2019, "ebit")]
        self.assertEqual(ebit_2019["value"], 8784)
        self.assertEqual(ebit_2019["verification_sources"], ["jio_2019_q4_media_release"])
        self.assertEqual(ebit_2019["triple_source_status"], "below_three_source_threshold")

        value_2019 = self.index[("reliance_jio", 2019, "value_of_sales_and_services")]
        self.assertEqual(value_2019["value"], 46506)
        self.assertEqual(value_2019["verification_sources"], ["jio_2019_q4_media_release"])
        self.assertNotIn("reliance_jio_ar_2020", value_2019["verification_sources"])
        self.assertEqual(value_2019["triple_source_status"], "below_three_source_threshold")

        for metric_key, value in (
            ("value_of_sales_and_services", 69605),
            ("revenue_from_operations", 59407),
        ):
            row = self.index[("reliance_jio", 2020, metric_key)]
            self.assertEqual(row["value"], value)
            self.assertEqual(row["verification_sources"], [])
            self.assertEqual(row["distinct_source_document_count"], 0)
            self.assertEqual(row["triple_source_status"], "below_three_source_threshold")

        for metric_key, value in (
            ("value_of_sales_and_services", 90287),
            ("revenue_from_operations", 76642),
        ):
            row = self.index[("reliance_jio", 2021, metric_key)]
            self.assertEqual(row["value"], value)
            self.assertEqual(row["verification_sources"], ["reliance_jio_ar_2023"])
            self.assertEqual(row["distinct_source_document_count"], 1)
            self.assertEqual(row["triple_source_status"], "below_three_source_threshold")

    def test_china_mobile_4g_base_station_history_uses_three_exact_documents(self):
        expected = {
            2016: 1.51,
            2017: 1.87,
            2018: 2.41,
            2019: 3.09,
            2020: 3.28,
            2021: 3.32,
            2022: 3.34,
            2023: 3.37,
        }
        strict_counts = {2016: 3, 2017: 3, 2018: 3, 2019: 3, 2020: 3, 2021: 3, 2022: 3, 2023: 2}
        for year, value in expected.items():
            row = self.index[("china_mobile", year, "4g_base_stations")]
            self.assertEqual(row["value"], value)
            self.assertEqual(row["distinct_source_document_count"], strict_counts[year])
            self.assertEqual(
                row["triple_source_status"],
                "three_distinct_sources_verified" if strict_counts[year] >= 3 else "below_three_source_threshold",
            )

    def test_xiaojing_expands_global_operator_year_ranges(self):
        combined = "\n".join(
            chunk["text"]
            for chunk in rag_llm._global_operator_exact_metric_chunks(
                "中国移动2016到2019年4G基站分别是多少？三来源状态呢？",
                dataset_ids={"global_top5_operators_2016_2025"},
            )
        )
        for year, value in ((2016, "1.51"), (2017, "1.87"), (2018, "2.41"), (2019, "3.09")):
            self.assertIn(f"period=FY{year}", combined)
            self.assertIn(f"official_value={value} million_base_stations", combined)
        self.assertGreaterEqual(combined.count("triple_source_status=three_distinct_sources_verified"), 4)

    def test_china_mobile_fy2016_fixed_broadband_has_three_exact_documents(self):
        row = self.index[("china_mobile", 2016, "fixed_broadband_subscribers")]
        self.assertEqual(row["value"], 77.62)
        self.assertEqual(row["unit"], "million_subscribers")
        self.assertEqual(row["distinct_source_document_count"], 3)
        self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
        self.assertEqual(
            set(row["verification_sources"]),
            {"china_mobile_ar_2016", "china_mobile_results_2016", "china_mobile_sd_2016"},
        )

    def test_china_mobile_fy2017_fixed_broadband_has_three_exact_documents(self):
        row = self.index[("china_mobile", 2017, "fixed_broadband_subscribers")]
        self.assertEqual(row["value"], 112.69)
        self.assertEqual(row["unit"], "million_subscribers")
        self.assertEqual(row["distinct_source_document_count"], 3)
        self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
        self.assertEqual(
            set(row["verification_sources"]),
            {"china_mobile_results_2017", "china_mobile_sd_2017", "china_mobile_press_2017"},
        )

    def test_china_mobile_fy2018_to_fy2022_broadband_preserves_exact_two_source_values(self):
        expected = {2018: 156.69, 2019: 187.04, 2020: 210.32, 2021: 240.11, 2022: 272.17}
        for year, value in expected.items():
            row = self.index[("china_mobile", year, "fixed_broadband_subscribers")]
            self.assertEqual(row["value"], value)
            self.assertEqual(row["distinct_source_document_count"], 2)
            self.assertEqual(row["triple_source_status"], "below_three_source_threshold")
            self.assertEqual(
                row["verification_sources"],
                [f"china_mobile_results_{year}", f"china_mobile_results_{year + 1}"],
            )

    def test_china_mobile_fy2016_to_fy2017_mobile_arpu_has_three_exact_documents(self):
        expected = {
            2016: (57.5, {"china_mobile_results_2016", "china_mobile_results_2017", "china_mobile_press_2017"}),
            2017: (57.7, {"china_mobile_results_2017", "china_mobile_press_2017", "china_mobile_results_2018"}),
        }
        for year, (value, sources) in expected.items():
            row = self.index[("china_mobile", year, "mobile_arpu")]
            self.assertEqual(row["value"], value)
            self.assertEqual(row["unit"], "RMB_per_user_month")
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
            self.assertEqual(set(row["verification_sources"]), sources)

    def test_china_mobile_fy2018_to_fy2022_mobile_arpu_has_three_exact_documents(self):
        expected = {2018: 53.1, 2019: 49.1, 2020: 47.4, 2021: 48.8, 2022: 49.0}
        for year, value in expected.items():
            row = self.index[("china_mobile", year, "mobile_arpu")]
            self.assertEqual(row["value"], value)
            self.assertEqual(row["unit"], "RMB_per_user_month")
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
            self.assertEqual(
                row["verification_sources"],
                [f"china_mobile_ar_{year}", f"china_mobile_results_{year}", f"china_mobile_results_{year + 1}"],
            )

    def test_china_mobile_fy2023_to_fy2024_mobile_arpu_has_three_exact_documents(self):
        for year, value in ((2023, 49.3), (2024, 48.5)):
            row = self.index[("china_mobile", year, "mobile_arpu")]
            self.assertEqual(row["value"], value)
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
            self.assertEqual(
                row["verification_sources"],
                [f"china_mobile_ar_{year}", f"china_mobile_ar_a_{year}", f"china_mobile_results_{year}"],
            )

    def test_china_mobile_fy2016_to_fy2024_dou_has_three_exact_documents(self):
        expected = {2016: 0.697, 2017: 1.399, 2018: 3.6, 2019: 6.7, 2020: 9.4, 2021: 12.6, 2022: 14.1, 2023: 15.9, 2024: 15.9}
        for year, value in expected.items():
            row = self.index[("china_mobile", year, "mobile_dou")]
            self.assertEqual(row["value"], value)
            self.assertEqual(row["unit"], "GB_per_user_month")
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
        self.assertEqual(
            self.index[("china_mobile", 2017, "mobile_dou")]["verification_sources"],
            ["china_mobile_ar_2017", "china_mobile_20f_2017", "china_mobile_results_2017"],
        )

    def test_china_mobile_fy2016_to_fy2024_mobile_customers_keep_exact_precision(self):
        expected = {
            2016: 848.90,
            2017: 887.20,
            2018: 925.07,
            2019: 950.28,
            2020: 941.92,
            2021: 956.89,
            2022: 975.01,
            2023: 991.00,
            2024: 1004,
        }
        for year, value in expected.items():
            row = self.index[("china_mobile", year, "mobile_subscribers")]
            self.assertEqual(row["value"], value)
            self.assertEqual(row["unit"], "million_subscribers")
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")

    def test_china_mobile_fy2016_to_fy2020_4g_customers_keep_exact_precision(self):
        expected = {2016: 535.04, 2017: 649.51, 2018: 712.65, 2019: 758.01, 2020: 775.31}
        for year, value in expected.items():
            row = self.index[("china_mobile", year, "4g_subscribers")]
            self.assertEqual(row["value"], value)
            self.assertEqual(row["unit"], "million_subscribers")
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
        fy2021 = self.index[("china_mobile", 2021, "4g_subscribers")]
        self.assertEqual(fy2021["value"], 822)
        self.assertLess(fy2021["distinct_source_document_count"], 3)
        self.assertEqual(fy2021["triple_source_status"], "below_three_source_threshold")

    def test_china_mobile_fy2021_to_fy2024_5g_network_customers_keep_exact_precision(self):
        expected = {2021: 206.65, 2022: 327.16, 2023: 464.81, 2024: 552}
        for year, value in expected.items():
            row = self.index[("china_mobile", year, "5g_network_subscribers")]
            self.assertEqual(row["value"], value)
            self.assertEqual(row["unit"], "million_subscribers")
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")

    def test_china_mobile_fy2019_to_fy2023_5g_package_customers_have_three_documents(self):
        expected = {2019: 2.55, 2020: 165, 2021: 387, 2022: 614, 2023: 795}
        for year, value in expected.items():
            row = self.index[("china_mobile", year, "5g_package_subscribers")]
            self.assertEqual(row["value"], value)
            self.assertEqual(row["unit"], "million_subscribers")
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
        self.assertEqual(
            self.index[("china_mobile", 2019, "5g_package_subscribers")]["verification_sources"],
            ["china_mobile_results_2019", "china_mobile_ar_2020", "china_mobile_20f_2020"],
        )

    def test_china_mobile_fy2017_to_fy2024_household_blended_arpu_has_three_documents(self):
        expected = {2017: 33.3, 2018: 34.4, 2019: 35.3, 2020: 37.7, 2021: 39.8, 2022: 42.1, 2023: 43.1, 2024: 43.8}
        for year, value in expected.items():
            row = self.index[("china_mobile", year, "household_customer_blended_arpu")]
            self.assertEqual(row["value"], value)
            self.assertEqual(row["unit"], "RMB_per_user_month")
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
            self.assertIn("not interchangeable with wireline broadband ARPU", row["quality_note"])

    def test_china_mobile_fy2016_to_fy2023_wireline_broadband_arpu_has_three_documents(self):
        expected = {2016: 32.1, 2017: 35.1, 2018: 33.5, 2019: 32.8, 2020: 34.0, 2021: 34.7, 2022: 34.1, 2023: 34.5}
        for year, value in expected.items():
            row = self.index[("china_mobile", year, "broadband_arpu")]
            self.assertEqual(row["value"], value)
            self.assertEqual(row["unit"], "RMB_per_user_month")
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
            self.assertIn("stored separately from household", row["quality_note"])

    def test_china_mobile_total_base_station_history_keeps_exact_source_limits(self):
        strict_counts = {2019: 2, 2020: 3, 2021: 1, 2022: 1, 2023: 1}
        for year, value in ((2019, 4.48), (2020, 5.14), (2021, 5.50), (2022, 6.0), (2023, 6.60)):
            row = self.index[("china_mobile", year, "total_base_stations")]
            self.assertEqual(row["value"], value)
            self.assertEqual(row["distinct_source_document_count"], strict_counts[year])
            self.assertEqual(
                row["triple_source_status"],
                "three_distinct_sources_verified" if strict_counts[year] >= 3 else "below_three_source_threshold",
            )
        row_2018 = self.index[("china_mobile", 2018, "total_base_stations")]
        self.assertEqual(row_2018["distinct_source_document_count"], 1)
        self.assertEqual(row_2018["triple_source_status"], "below_three_source_threshold")
        self.assertEqual(
            self.index[("china_mobile", 2020, "total_base_stations")]["verification_sources"],
            ["china_mobile_ar_2020", "china_mobile_prospectus_2021", "china_mobile_results_announcement_2020"],
        )
        self.assertNotIn(
            "china_mobile_20f_2018",
            self.index[("china_mobile", 2018, "total_base_stations")]["verification_sources"],
        )
        self.assertEqual(
            self.index[("china_mobile", 2022, "total_base_stations")]["verification_sources"],
            ["china_mobile_ar_summary_2022"],
        )
        self.assertEqual(
            self.index[("china_mobile", 2023, "total_base_stations")]["verification_sources"],
            ["china_mobile_ar_summary_2023"],
        )

    def test_anchor_values_and_customer_scope(self):
        expected = {
            ("china_mobile", 2025, "mobile_subscribers"): 1005,
            ("china_telecom", 2025, "5g_network_subscribers"): 301.81,
            ("china_unicom", 2025, "5g_network_subscribers"): 232.18,
            ("bharti_airtel", 2025, "total_customers"): 590.514,
            ("reliance_jio", 2025, "total_customers"): 488.2,
            ("china_broadnet", 2024, "5g_network_subscribers"): 32.7546,
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
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
        for year in range(2020, 2026):
            for operator_id in ("china_telecom", "china_unicom"):
                row = self.index[(operator_id, year, "5g_base_stations")]
                self.assertEqual(row["distinct_source_document_count"], 3)
                self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
        for operator_id in ("china_telecom", "china_unicom"):
            row = self.index[(operator_id, 2022, "5g_base_stations")]
            self.assertEqual(row["value"], 1.0)
            self.assertEqual(row["comparator"], ">=")
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertIn("previous 1.05 million precision was not retained", row["quality_note"])
        for year in range(2019, 2025):
            self.assertEqual(
                self.index[("china_mobile", year, "5g_base_stations")]["triple_source_status"],
                "below_three_source_threshold",
            )
        mobile_2025 = self.index[("china_mobile", 2025, "5g_base_stations")]
        self.assertEqual(mobile_2025["distinct_source_document_count"], 3)
        self.assertEqual(mobile_2025["triple_source_status"], "three_distinct_sources_verified")
        self.assertEqual(
            self.index[("china_mobile", 2019, "5g_base_stations")]["verification_sources"],
            ["china_mobile_20f_2019", "china_mobile_sd_2019"],
        )
        self.assertEqual(
            self.index[("china_mobile", 2020, "5g_base_stations")]["verification_sources"],
            ["china_mobile_20f_2020", "china_mobile_sd_2020"],
        )

    def test_china_unicom_fy2020_5g_package_subscribers_has_three_documents(self):
        row = self.index[("china_unicom", 2020, "5g_package_subscribers")]
        self.assertEqual(row["value"], 70.83)
        self.assertEqual(row["distinct_source_document_count"], 3)
        self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
        self.assertEqual(
            row["verification_sources"],
            ["china_unicom_ar_2020", "china_unicom_results_2020", "china_unicom_transcript_2020"],
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

    def test_china_unicom_historical_operating_kpis_have_three_exact_documents(self):
        expected = {
            "mobile_subscribers": {
                2016: 263.822, 2017: 284.163, 2018: 315.036,
                2019: 318.475, 2020: 305.811, 2021: 317.115,
            },
            "fixed_broadband_subscribers": {
                2016: 75.236, 2017: 76.539, 2018: 80.880,
                2019: 83.478, 2020: 86.095, 2021: 95.046, 2022: 103.630,
            },
            "4g_subscribers": {
                2016: 104.551, 2017: 174.876, 2018: 219.925,
                2019: 253.766, 2020: 270.181,
            },
            "mobile_arpu": {
                2016: 46.4, 2017: 48.0, 2018: 45.7,
                2019: 40.4, 2020: 42.1, 2021: 43.9,
            },
            "broadband_arpu": {
                2016: 49.4, 2017: 46.3, 2018: 44.6,
                2019: 41.6, 2020: 41.5, 2021: 41.3,
            },
            "mobile_dou": {
                2017: 2.433, 2019: 8.0,
            },
            "handset_data_traffic": {2017: 7.786},
            "4g_base_stations": {
                2016: 0.740, 2017: 0.852, 2018: 0.987,
                2020: 1.503, 2021: 1.560,
            },
            "fixed_broadband_access_ports": {
                2018: 215, 2019: 221, 2020: 225,
                2021: 239, 2022: 250, 2023: 266,
            },
            "iot_connections": {2022: 385.540, 2023: 493.911},
            "4g_population_coverage": {2018: 90, 2019: 93, 2020: 94, 2021: 95},
        }
        for metric_key, values in expected.items():
            for year, value in values.items():
                row = self.index[("china_unicom", year, metric_key)]
                self.assertEqual(row["value"], value)
                self.assertEqual(row["distinct_source_document_count"], 3)
                self.assertEqual(row["verification_status"], "official_three_distinct_sources_verified")
                self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")

        mobile_arpu_2022 = self.index[("china_unicom", 2022, "mobile_arpu")]
        self.assertEqual(mobile_arpu_2022["value"], 44.3)
        self.assertEqual(mobile_arpu_2022["distinct_source_document_count"], 2)
        self.assertEqual(mobile_arpu_2022["triple_source_status"], "below_three_source_threshold")

        for year, expected_sources in {
            2020: {"china_unicom_results_2020", "china_unicom_results_2021"},
            2021: {"china_unicom_results_2021", "china_unicom_results_2022"},
        }.items():
            dou = self.index[("china_unicom", year, "mobile_dou")]
            self.assertEqual(set(dou["verification_sources"]), expected_sources)
            self.assertEqual(dou["distinct_source_document_count"], 2)
            self.assertEqual(dou["triple_source_status"], "below_three_source_threshold")

    def test_xiaojing_retrieves_china_unicom_three_source_dou_history(self):
        combined = "\n".join(
            chunk["text"]
            for chunk in rag_llm._global_operator_exact_metric_chunks(
                "中国联通2017年和2019年手机用户DOU月户均流量是多少？说明三来源。",
                dataset_ids={"global_top5_operators_2016_2025"},
            )
        )
        for value in ("2.433 GB_per_user_month", "8.0 GB_per_user_month"):
            self.assertIn(f"official_value={value}", combined)
        self.assertGreaterEqual(combined.count("distinct_source_document_count=3"), 2)
        self.assertGreaterEqual(combined.count("triple_source_status=three_distinct_sources_verified"), 2)

    def test_xiaojing_retrieves_china_unicom_fy2017_handset_data_traffic(self):
        combined = "\n".join(
            chunk["text"]
            for chunk in rag_llm._global_operator_exact_metric_chunks(
                "中国联通2017年手机数据流量是多少？说明三来源。",
                dataset_ids={"global_top5_operators_2016_2025"},
            )
        )
        self.assertIn("metric_key=handset_data_traffic", combined)
        self.assertIn("official_value=7.786 billion_GB", combined)
        self.assertIn("distinct_source_document_count=3", combined)
        self.assertIn("triple_source_status=three_distinct_sources_verified", combined)

    def test_xiaojing_retrieves_china_unicom_precise_4g_base_station_history(self):
        expected = {
            2016: "0.74 million_base_stations",
            2017: "0.852 million_base_stations",
            2018: "0.987 million_base_stations",
            2020: "1.503 million_base_stations",
            2021: "1.56 million_base_stations",
        }
        for year, value_text in expected.items():
            combined = "\n".join(
                chunk["text"]
                for chunk in rag_llm._global_operator_exact_metric_chunks(
                    f"中国联通{year}年4G基站数是多少？说明三来源。",
                    dataset_ids={"global_top5_operators_2016_2025"},
                )
            )
            self.assertIn(f"official_value={value_text}", combined)
            self.assertIn("distinct_source_document_count=3", combined)
            self.assertIn("triple_source_status=three_distinct_sources_verified", combined)

        conflict = self.index[("china_unicom", 2019, "4g_base_stations")]
        self.assertIsNone(conflict["value"])
        self.assertIn("restated 1.410 million to 1.407 million", conflict["quality_note"])
        scope_break = self.index[("china_unicom", 2022, "4g_base_stations")]
        self.assertIsNone(scope_break["value"])
        self.assertIn("self-built and 2.276 million available", scope_break["quality_note"])

    def test_xiaojing_retrieves_china_unicom_broadband_access_port_history(self):
        expected = {2018: 215, 2019: 221, 2020: 225, 2021: 239, 2022: 250, 2023: 266}
        for year, value in expected.items():
            combined = "\n".join(
                chunk["text"]
                for chunk in rag_llm._global_operator_exact_metric_chunks(
                    f"中国联通{year}年固网宽带接入端口数是多少？说明三来源。",
                    dataset_ids={"global_top5_operators_2016_2025"},
                )
            )
            self.assertIn("metric_key=fixed_broadband_access_ports", combined)
            self.assertIn(f"official_value={value} million_ports", combined)
            self.assertIn("distinct_source_document_count=3", combined)
            self.assertIn("triple_source_status=three_distinct_sources_verified", combined)

        for year in (2016, 2017, 2024, 2025):
            self.assertIsNone(self.index[("china_unicom", year, "fixed_broadband_access_ports")]["value"])

    def test_xiaojing_retrieves_china_unicom_exact_iot_connection_history(self):
        for year, value in {2022: 385.540, 2023: 493.911}.items():
            combined = "\n".join(
                chunk["text"]
                for chunk in rag_llm._global_operator_exact_metric_chunks(
                    f"中国联通{year}年物联网终端连接数是多少？说明三来源。",
                    dataset_ids={"global_top5_operators_2016_2025"},
                )
            )
            self.assertIn("metric_key=iot_connections", combined)
            self.assertIn(f"official_value={value} million_connections", combined)
            self.assertIn("distinct_source_document_count=3", combined)
            self.assertIn("triple_source_status=three_distinct_sources_verified", combined)

        self.assertIsNone(self.index[("china_unicom", 2024, "iot_connections")]["value"])

    def test_xiaojing_retrieves_china_unicom_4g_population_coverage_history(self):
        for year, value in {2018: 90, 2019: 93, 2020: 94, 2021: 95}.items():
            combined = "\n".join(
                chunk["text"]
                for chunk in rag_llm._global_operator_exact_metric_chunks(
                    f"中国联通{year}年4G人口覆盖率是多少？说明三来源。",
                    dataset_ids={"global_top5_operators_2016_2025"},
                )
            )
            self.assertIn("metric_key=4g_population_coverage", combined)
            self.assertIn(f"official_value={value} percent", combined)
            self.assertIn("distinct_source_document_count=3", combined)
            self.assertIn("triple_source_status=three_distinct_sources_verified", combined)

        for year in (2017, 2022):
            self.assertIsNone(self.index[("china_unicom", year, "4g_population_coverage")]["value"])

    def test_china_sidecar_only_adds_operating_metrics(self):
        sidecar = json.loads((ORIGINAL / "annual_operating_metrics_2016_2025.json").read_text(encoding="utf-8"))
        self.assertEqual({r["operator_id"] for r in sidecar["rows"]}, {"china_mobile", "china_telecom", "china_unicom", "china_broadnet"})
        financial_metrics = {"revenue", "ebitda", "ebit", "earnings_before_tax", "net_profit", "capex", "net_debt", "shareholders_equity"}
        self.assertFalse(financial_metrics & {r["metric_key"] for r in sidecar["rows"]})

    def test_china_broadnet_scope_gaps_and_selectively_bound_sources(self):
        available = [
            row for row in self.rows
            if row["operator_id"] == "china_broadnet" and row["value"] is not None
        ]
        self.assertEqual(len(available), 24)
        certified = [row for row in available if row["distinct_source_document_count"] >= 3]
        self.assertEqual(
            [(row["year"], row["metric_key"]) for row in certified],
            [
                (2022, "5g_base_stations"),
                (2022, "5g_network_subscribers"),
                (2023, "5g_base_stations"),
                (2023, "5g_network_subscribers"),
                (2024, "5g_network_subscribers"),
                (2025, "5g_network_subscribers"),
            ],
        )
        self.assertTrue(all(len(row["candidate_sources"]) >= len(row["verification_sources"]) for row in available))
        users_2024 = self.index[("china_broadnet", 2024, "5g_network_subscribers")]
        self.assertEqual(users_2024["value"], 32.7546)
        self.assertEqual(users_2024["triple_source_status"], "three_distinct_sources_verified")
        self.assertEqual(users_2024["distinct_source_document_count"], 4)
        users_2023 = self.index[("china_broadnet", 2023, "5g_network_subscribers")]
        self.assertEqual(users_2023["comparator"], ">")
        self.assertEqual(users_2023["distinct_source_document_count"], 3)
        self.assertEqual(users_2023["triple_source_status"], "three_distinct_sources_verified")
        users_2022 = self.index[("china_broadnet", 2022, "5g_network_subscribers")]
        self.assertEqual(users_2022["comparator"], ">")
        self.assertEqual(users_2022["distinct_source_document_count"], 3)
        users_2025 = self.index[("china_broadnet", 2025, "5g_network_subscribers")]
        self.assertEqual(users_2025["comparator"], "≈")
        self.assertEqual(users_2025["distinct_source_document_count"], 3)
        base_2023 = self.index[("china_broadnet", 2023, "5g_base_stations")]
        self.assertEqual(base_2023["value"], 0.62)
        self.assertIn("co-built and shared", base_2023["scope"])
        self.assertEqual(base_2023["distinct_source_document_count"], 3)
        base_2022 = self.index[("china_broadnet", 2022, "5g_base_stations")]
        self.assertEqual(base_2022["distinct_source_document_count"], 3)
        self.assertIn("co-built and shared", base_2022["scope"])
        cable = self.index[("china_broadnet", 2024, "cable_tv_actual_users")]
        self.assertEqual(cable["value"], 208)
        self.assertIn("not China Broadnet consolidated", cable["scope"])
        mobile_arpu = self.index[("china_broadnet", 2025, "mobile_arpu")]
        self.assertIsNone(mobile_arpu["value"])
        self.assertEqual(mobile_arpu["verification_status"], "source_gap_confirmed")

    def test_china_broadnet_regulator_reposts_share_document_identity(self):
        source_payload = json.loads((GLOBAL / "sources.json").read_text(encoding="utf-8"))
        sources = {source["source_id"]: source for source in source_payload["sources"]}
        self.assertEqual(
            sources["china_broadnet_nrta_2022"]["source_document_id"],
            sources["china_broadnet_guangdong_2022"]["source_document_id"],
        )
        self.assertEqual(
            sources["china_broadnet_nrta_2024"]["source_document_id"],
            sources["china_broadnet_pingliang_gov_2024"]["source_document_id"],
        )

    def test_xiaojing_ai_retrieves_china_broadnet_values_and_gaps(self):
        value_chunks = rag_llm._global_operator_exact_metric_chunks(
            "中国广电2024年5G用户和有线电视实际用户",
            dataset_ids={"global_top5_operators_2016_2025"},
        )
        value_text = "\n".join(chunk["text"] for chunk in value_chunks)
        self.assertIn("operator=中国广电", value_text)
        self.assertIn("official_value=32.7546 million_subscribers", value_text)
        self.assertIn("official_value=208 million_users", value_text)
        self.assertIn("distinct_source_document_count=4", value_text)
        self.assertIn("triple_source_status=three_distinct_sources_verified", value_text)
        gap_chunks = rag_llm._global_operator_exact_metric_chunks(
            "中国广电2025年移动ARPU和固定宽带用户",
            dataset_ids={"global_top5_operators_2016_2025"},
        )
        gap_text = "\n".join(chunk["text"] for chunk in gap_chunks)
        self.assertIn("未披露（source_gap_confirmed", gap_text)
        self.assertIn("不能当作0", gap_text)

    def test_china_broadnet_compound_year_metric_associations_fit_tool_limit(self):
        question = (
            "中国广电2022至2025年5G用户、2023年700MHz 5G基站、2024年全国有线电视实际用户分别是多少？"
            "再说明2025年中国广电移动ARPU、固定宽带用户、移动数据流量是否披露。"
        )
        chunks = rag_llm.retrieve_context(
            question,
            limit=12,
            dataset_ids={"global_top5_operators_2016_2025"},
        )
        combined = "\n".join(chunk["text"] for chunk in chunks)
        for year in (2022, 2023, 2024, 2025):
            self.assertIn(f"period=FY{year}", combined)
        self.assertIn("official_value=42 million_subscribers", combined)
        self.assertIn("metric_key=mobile_arpu", combined)
        self.assertIn("metric_key=fixed_broadband_subscribers", combined)
        self.assertIn("metric_key=total_data_traffic", combined)

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

    def test_china_telecom_fy2025_network_upgrade_uses_three_documents(self):
        expected_sources = {
            "china_telecom_results_2025",
            "china_telecom_announcement_2025",
            "china_telecom_press_2025",
        }
        for metric_key, value, unit, comparator in (
            ("ten_g_pon_ports", 10, "million_ports", ">="),
            ("urban_gigabit_coverage", 97, "percent", ">"),
        ):
            row = self.index[("china_telecom", 2025, metric_key)]
            self.assertEqual((row["value"], row["unit"], row["comparator"]), (value, unit, comparator))
            self.assertEqual(set(row["verification_sources"]), expected_sources)
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")

        combined = "\n".join(
            chunk["text"]
            for chunk in rag_llm._global_operator_exact_metric_chunks(
                "中国电信2025年5G基站、10G PON端口和城市千兆宽带覆盖率是多少？",
                dataset_ids={"global_top5_operators_2016_2025"},
            )
        )
        self.assertIn("official_value=1.54 million_base_stations", combined)
        self.assertIn("official_value=10 million_ports", combined)
        self.assertIn("official_value=97 percent", combined)
        self.assertGreaterEqual(combined.count("triple_source_status=three_distinct_sources_verified"), 3)

    def test_china_telecom_fy2025_penetration_rates_use_three_exact_documents(self):
        expected_sources = {
            "china_telecom_ar_2025",
            "china_telecom_announcement_2025",
            "china_telecom_press_2025",
        }
        for metric_key, value in (
            ("5g_network_penetration", 68.8),
            ("gigabit_broadband_penetration", 31.6),
        ):
            row = self.index[("china_telecom", 2025, metric_key)]
            self.assertEqual((row["value"], row["unit"]), (value, "percent"))
            self.assertEqual(set(row["verification_sources"]), expected_sources)
            self.assertNotIn("china_telecom_results_2025", row["verification_sources"])
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")

        combined = "\n".join(
            chunk["text"]
            for chunk in rag_llm._global_operator_exact_metric_chunks(
                "中国电信2025年5G网络用户渗透率和千兆宽带渗透率是多少？",
                dataset_ids={"global_top5_operators_2016_2025"},
            )
        )
        self.assertIn("official_value=68.8 percent", combined)
        self.assertIn("official_value=31.6 percent", combined)
        self.assertGreaterEqual(combined.count("distinct_source_document_count=3"), 2)

    def test_china_mobile_fy2025_scale_and_value_metrics_use_exact_documents(self):
        common_sources = {
            "china_mobile_ar_2025",
            "china_mobile_results_2025",
            "china_mobile_press_2025",
        }
        expected = {
            "mobile_subscribers": (1005, "million_subscribers"),
            "5g_network_subscribers": (642, "million_subscribers"),
            "5g_base_stations": (2.77, "million_base_stations"),
            "mobile_broadband_integration_rate": (96.5, "percent"),
            "government_enterprise_customers": (36.17, "million_customers"),
            "households_gigabit_coverage": (530, "million_households"),
            "intelligent_compute_capacity": (92.5, "EFLOPS_FP16"),
        }
        for metric_key, value_and_unit in expected.items():
            row = self.index[("china_mobile", 2025, metric_key)]
            self.assertEqual((row["value"], row["unit"]), value_and_unit)
            self.assertEqual(set(row["verification_sources"]), common_sources)
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
        self.assertEqual(self.index[("china_mobile", 2025, "5g_base_stations")]["comparator"], ">=")

        arpu = self.index[("china_mobile", 2025, "mobile_arpu")]
        self.assertEqual((arpu["value"], arpu["unit"]), (46.8, "RMB_per_user_month"))
        self.assertEqual(
            set(arpu["verification_sources"]),
            {"china_mobile_ar_2025", "china_mobile_results_2025", "china_mobile_ar_summary_2025"},
        )
        self.assertEqual(arpu["distinct_source_document_count"], 3)
        self.assertEqual(arpu["triple_source_status"], "three_distinct_sources_verified")

        for question, expected_text in (
            ("中国移动2025年5G网络用户数", "official_value=642 million_subscribers"),
            ("中国移动2025年移动ARPU", "official_value=46.8 RMB_per_user_month"),
            ("中国移动2025年5G基站", "official_value=2.77 million_base_stations"),
        ):
            combined = "\n".join(
                chunk["text"]
                for chunk in rag_llm._global_operator_exact_metric_chunks(
                    question,
                    dataset_ids={"global_top5_operators_2016_2025"},
                )
            )
            self.assertIn(expected_text, combined)
            self.assertIn("distinct_source_document_count=3", combined)

    def test_china_telecom_fy2025_broadband_arpu_and_compute_use_exact_documents(self):
        broadband = self.index[("china_telecom", 2025, "broadband_arpu")]
        self.assertEqual((broadband["value"], broadband["unit"]), (47.1, "RMB_per_user_month"))
        self.assertEqual(
            set(broadband["verification_sources"]),
            {"china_telecom_ar_2025", "china_telecom_results_2025", "china_telecom_factsheet_2025"},
        )
        self.assertEqual(broadband["distinct_source_document_count"], 3)
        self.assertEqual(broadband["triple_source_status"], "three_distinct_sources_verified")

        compute = self.index[("china_telecom", 2025, "intelligent_compute_capacity")]
        self.assertEqual((compute["value"], compute["unit"]), (46, "EFLOPS_FP16"))
        self.assertEqual(
            set(compute["verification_sources"]),
            {"china_telecom_ar_2025", "china_telecom_results_2025", "china_telecom_announcement_2025"},
        )
        self.assertEqual(compute["distinct_source_document_count"], 3)
        self.assertEqual(compute["triple_source_status"], "three_distinct_sources_verified")

        for question, expected_text in (
            ("中国电信2025年宽带ARPU", "official_value=47.1 RMB_per_user_month"),
            ("中国电信2025年智算规模", "official_value=46 EFLOPS_FP16"),
        ):
            combined = "\n".join(
                chunk["text"]
                for chunk in rag_llm._global_operator_exact_metric_chunks(
                    question,
                    dataset_ids={"global_top5_operators_2016_2025"},
                )
            )
            self.assertIn(expected_text, combined)
            self.assertIn("distinct_source_document_count=3", combined)

    def test_china_telecom_fy2025_precise_subscriber_totals_use_operating_documents(self):
        expected_sources = {
            "china_telecom_press_2025",
            "china_telecom_kpi_2025",
            "china_telecom_q4_operating_announcement_2025",
        }
        expected = {
            "mobile_subscribers": 438.65,
            "5g_network_subscribers": 301.81,
            "fixed_broadband_subscribers": 201.12,
        }
        for metric_key, value in expected.items():
            row = self.index[("china_telecom", 2025, metric_key)]
            self.assertEqual((row["value"], row["unit"]), (value, "million_subscribers"))
            self.assertEqual(set(row["verification_sources"]), expected_sources)
            self.assertNotIn("china_telecom_results_2025", row["verification_sources"])
            self.assertNotIn("china_telecom_announcement_2025", row["verification_sources"])
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")

        for question, expected_text in (
            ("中国电信2025年移动用户数", "official_value=438.65 million_subscribers"),
            ("中国电信2025年5G网络用户数", "official_value=301.81 million_subscribers"),
            ("中国电信2025年固定宽带用户数", "official_value=201.12 million_subscribers"),
        ):
            combined = "\n".join(
                chunk["text"]
                for chunk in rag_llm._global_operator_exact_metric_chunks(
                    question,
                    dataset_ids={"global_top5_operators_2016_2025"},
                )
            )
            self.assertIn(expected_text, combined)
            self.assertIn("distinct_source_document_count=3", combined)

    def test_china_unicom_fy2025_conservative_connectivity_bounds_use_three_documents(self):
        expected = {
            "mobile_population_coverage": (99, "percent"),
            "5g_a_deployment_cities": (330, "cities"),
            "iot_connections": (700, "million_connections"),
            "integrated_subscriber_penetration": (78, "percent"),
            "integrated_package_arpu": (100, "RMB_per_user_month"),
            "cloud_ai_product_users": (300, "million_users"),
        }
        expected_sources = {
            "china_unicom_ar_2025",
            "china_unicom_results_2025",
            "china_unicom_press_2025",
        }
        for metric_key, (value, unit) in expected.items():
            row = self.index[("china_unicom", 2025, metric_key)]
            self.assertEqual((row["value"], row["unit"]), (value, unit))
            self.assertEqual(set(row["verification_sources"]), expected_sources)
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")

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
            "total_data_traffic": 4,
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
        self.assertEqual(
            traffic["verification_sources"],
            [
                "jio_2025_media_release",
                "jio_q1_2026_media_release",
                "jio_q2_2026_media_release",
                "jio_q3_2026_media_release",
            ],
        )
        self.assertEqual(traffic["triple_source_status"], "three_distinct_sources_verified")

        cells = self.index[("reliance_jio", 2025, "5g_base_stations")]
        self.assertEqual(cells["verification_sources"], ["jio_2025_factsheet"])
        self.assertEqual(cells["triple_source_status"], "below_three_source_threshold")

        spectrum = self.index[("reliance_jio", 2025, "spectrum_holdings")]
        self.assertEqual(spectrum["value"], 26801)
        self.assertEqual(spectrum["unit"], "MHz_uplink_plus_downlink")
        self.assertEqual(spectrum["distinct_source_document_count"], 4)
        self.assertEqual(spectrum["triple_source_status"], "three_distinct_sources_verified")
        self.assertEqual(
            spectrum["verification_sources"],
            [
                "reliance_jio_ar_2025",
                "jio_q1_2025_analyst_presentation",
                "jio_2024_spectrum_acquisition_release",
                "jio_q1_2025_media_release",
            ],
        )

        spectrum_text = "\n".join(
            chunk["text"]
            for chunk in rag_llm._global_operator_exact_metric_chunks(
                "Jio FY2025频谱持有量是多少？有几份独立来源？",
                dataset_ids={"global_top5_operators_2016_2025"},
            )
        )
        self.assertIn("official_value=26801 MHz_uplink_plus_downlink", spectrum_text)
        self.assertIn("distinct_source_document_count=4", spectrum_text)
        self.assertIn("triple_source_status=three_distinct_sources_verified", spectrum_text)

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
            "total_customers": 3,
            "value_of_sales_and_services": 3,
            "total_data_traffic": 3,
            "5g_base_stations": 3,
        }
        for metric_key, source_count in certified.items():
            row = self.index[("reliance_jio", 2024, metric_key)]
            self.assertEqual(row["distinct_source_document_count"], source_count)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")

        for metric_key in ("mobile_arpu", "mobile_dou", "5g_network_subscribers"):
            row = self.index[("reliance_jio", 2024, metric_key)]
            self.assertEqual(row["distinct_source_document_count"], 2)
            self.assertEqual(row["triple_source_status"], "below_three_source_threshold")

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
        self.assertEqual(
            ebitda["verification_sources"],
            ["reliance_jio_ar_2025", "jio_2025_media_release", "jio_2025_integrated_financials"],
        )
        self.assertEqual(ebitda["distinct_source_document_count"], 3)
        self.assertEqual(ebitda["triple_source_status"], "three_distinct_sources_verified")

        sources = {
            source["source_id"]: source
            for source in json.loads((GLOBAL / "sources.json").read_text(encoding="utf-8"))["sources"]
        }
        filing = sources["jio_2025_integrated_financials"]["comparative_evidence"]["FY2024"]
        self.assertEqual(filing["ebitda"]["value"], 56675)

        combined = "\n".join(
            chunk["text"]
            for chunk in rag_llm._global_operator_exact_metric_chunks(
                "Reliance Jio FY2024 EBITDA是多少？说明三来源状态。",
                dataset_ids={"global_top5_operators_2016_2025"},
            )
        )
        self.assertIn("official_value=56675 INR_crore", combined)
        self.assertIn("distinct_source_document_count=3", combined)
        self.assertIn("triple_source_status=three_distinct_sources_verified", combined)

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
        self.assertEqual(
            gross["verification_sources"],
            ["reliance_jio_ar_2023", "reliance_jio_ar_2024", "jio_q2_2024_media_release"],
        )
        self.assertEqual(gross["distinct_source_document_count"], 3)
        self.assertEqual(gross["triple_source_status"], "three_distinct_sources_verified")

        gross_chunks = rag_llm._global_operator_exact_metric_chunks(
            "Reliance Jio FY2023销售及服务价值是多少？说明三来源状态。",
            dataset_ids={"global_top5_operators_2016_2025"},
        )
        gross_text = "\n".join(chunk["text"] for chunk in gross_chunks)
        self.assertIn("official_value=119791 INR_crore", gross_text)
        self.assertIn("distinct_source_document_count=3", gross_text)
        self.assertIn("triple_source_status=three_distinct_sources_verified", gross_text)

        revenue = self.index[("reliance_jio", 2023, "revenue_from_operations")]
        self.assertEqual(revenue["value"], 101961)
        self.assertNotIn("jio_2023_media_release", revenue["verification_sources"])

        dou = self.index[("reliance_jio", 2023, "mobile_dou")]
        self.assertEqual(
            dou["verification_sources"],
            ["reliance_jio_ar_2023", "jio_2023_q4", "jio_2024_q4"],
        )
        self.assertEqual(dou["distinct_source_document_count"], 3)
        self.assertEqual(dou["triple_source_status"], "three_distinct_sources_verified")

        next_year_dou = self.index[("reliance_jio", 2024, "mobile_dou")]
        self.assertEqual(
            next_year_dou["verification_sources"],
            ["reliance_jio_ar_2024", "jio_2025_q4"],
        )
        self.assertEqual(next_year_dou["distinct_source_document_count"], 2)
        self.assertEqual(next_year_dou["triple_source_status"], "below_three_source_threshold")

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
        self.assertEqual(
            homes["verification_sources"],
            ["reliance_jio_ar_2022", "jio_rjil_ar_2022"],
        )
        self.assertEqual(homes["distinct_source_document_count"], 2)
        self.assertEqual(homes["triple_source_status"], "below_three_source_threshold")

        home_chunks = rag_llm._global_operator_exact_metric_chunks(
            "Reliance Jio FY2022已连接家庭是多少？说明三来源状态。",
            dataset_ids={"global_top5_operators_2016_2025"},
        )
        home_text = "\n".join(chunk["text"] for chunk in home_chunks)
        self.assertIn("official_value=5 million_premises", home_text)
        self.assertIn("comparator=>=", home_text)
        self.assertIn("distinct_source_document_count=2", home_text)

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
        self.assertIn("annual-KPI loss-before-tax value of INR-42,063m", combined)
        self.assertGreaterEqual(combined.count("distinct_source_document_count=4"), 9)
        self.assertGreaterEqual(combined.count("triple_source_status=three_distinct_sources_verified"), 9)

    def test_airtel_fy2017_adds_common_financials_and_preserves_scope_conflicts(self):
        expected_values = {
            "total_customers": 372.354,
            "revenue": 942506,
            "ebitda": 356208,
            "earnings_before_tax": 77232,
            "net_profit": 37997,
            "capex": 198745,
            "net_debt": 913999,
            "shareholders_equity": 674563,
            "network_towers": 184255,
        }
        for metric_key, expected_value in expected_values.items():
            row = self.index[("bharti_airtel", 2017, metric_key)]
            self.assertEqual(row["value"], expected_value)
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
        self.assertIn("INR954,684m", self.index[("bharti_airtel", 2017, "revenue")]["quality_note"])
        self.assertIn("INR88,929m", self.index[("bharti_airtel", 2017, "earnings_before_tax")]["quality_note"])
        self.assertIn("162,046", self.index[("bharti_airtel", 2017, "network_towers")]["quality_note"])
        traffic = self.index[("bharti_airtel", 2017, "total_data_traffic")]
        self.assertEqual(traffic["value"], 0.903)
        self.assertEqual(traffic["distinct_source_document_count"], 1)
        self.assertIn("consolidated annual headline", traffic["scope"])

    def test_airtel_fy2016_adds_common_financials_network_detail_and_preserves_scope_break(self):
        expected_values = {
            "total_customers": 357.428,
            "revenue": 965321,
            "ebitda": 341682,
            "earnings_before_tax": 128463,
            "net_profit": 60767,
            "capex": 205919,
            "net_debt": 835106,
            "shareholders_equity": 667693,
            "network_towers": 181376,
            "mobile_broadband_base_stations": 118197,
        }
        for metric_key, expected_value in expected_values.items():
            row = self.index[("bharti_airtel", 2016, metric_key)]
            self.assertEqual(row["value"], expected_value)
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
        self.assertIn("INR965,320m", self.index[("bharti_airtel", 2016, "revenue")]["quality_note"])
        self.assertIn("INR106,723m", self.index[("bharti_airtel", 2016, "earnings_before_tax")]["quality_note"])
        self.assertIn("INR60,768m", self.index[("bharti_airtel", 2016, "net_profit")]["quality_note"])
        self.assertIn("154,097", self.index[("bharti_airtel", 2016, "network_towers")]["quality_note"])
        traffic = self.index[("bharti_airtel", 2016, "total_data_traffic")]
        self.assertEqual(traffic["value"], 0.597)
        self.assertEqual(traffic["distinct_source_document_count"], 1)
        self.assertEqual(traffic["triple_source_status"], "below_three_source_threshold")
        self.assertIn("consolidated annual headline", traffic["scope"])

    def test_airtel_fy2016_registry_carries_exact_annual_ir_and_network_evidence(self):
        sources = {
            source["source_id"]: source
            for source in json.loads((GLOBAL / "sources.json").read_text(encoding="utf-8"))["sources"]
        }
        annual = sources["bharti_airtel_ar_2019"]["comparative_evidence"]["FY2016"]
        self.assertEqual(annual["revenue"]["value"], 965321)
        self.assertEqual(annual["earnings_before_tax"]["value"], 128463)
        contemporary = sources["airtel_q4_2016_ir_pack"]["evidence"]
        self.assertEqual(contemporary["capex"]["value"], 205919)
        self.assertEqual(contemporary["network_towers"]["value"], 181376)
        self.assertEqual(contemporary["mobile_broadband_base_stations"]["value"], 118197)
        next_quarter = sources["airtel_q1_2017_ir_pack"]["comparative_evidence"]["FY2016"]
        self.assertEqual(next_quarter["mobile_broadband_base_stations"]["value"], 118197)
        annual_2016 = sources["bharti_airtel_ar_2016"]["evidence"]
        self.assertEqual(annual_2016["total_data_traffic"]["value"], 0.597)

    def test_xiaojing_retrieves_airtel_fy2016_certified_rows_and_scope_conflicts(self):
        combined = "\n".join(
            chunk["text"]
            for chunk in rag_llm._global_operator_exact_metric_chunks(
                "Bharti Airtel FY2016总客户数、营业收入、EBITDA、税前利润、净利润、资本开支、净债务、股东权益、网络铁塔、移动宽带基站和数据流量是多少？解释重列、范围差异和核验状态。",
                dataset_ids={"global_top5_operators_2016_2025"},
            )
        )
        expected_values = {
            "total_customers": "357.428 million_customers",
            "revenue": "965321 INR_million",
            "ebitda": "341682 INR_million",
            "earnings_before_tax": "128463 INR_million",
            "net_profit": "60767 INR_million",
            "capex": "205919 INR_million",
            "net_debt": "835106 INR_million",
            "shareholders_equity": "667693 INR_million",
            "network_towers": "181376 sites",
            "mobile_broadband_base_stations": "118197 base_stations",
            "total_data_traffic": "0.597 billion_GB",
        }
        for metric_key, value_text in expected_values.items():
            self.assertIn(f"metric_key={metric_key}", combined)
            self.assertIn(f"official_value={value_text}", combined)
        self.assertIn("INR965,320m", combined)
        self.assertIn("INR106,723m", combined)
        self.assertIn("INR60,768m", combined)
        self.assertIn("154,097", combined)
        self.assertGreaterEqual(combined.count("triple_source_status=three_distinct_sources_verified"), 10)
        self.assertIn("triple_source_status=below_three_source_threshold", combined)

    def test_airtel_fy2017_registry_carries_exact_annual_and_ir_evidence(self):
        sources = {
            source["source_id"]: source
            for source in json.loads((GLOBAL / "sources.json").read_text(encoding="utf-8"))["sources"]
        }
        annual = sources["bharti_airtel_ar_2021"]["comparative_evidence"]["FY2017"]
        self.assertEqual(annual["revenue"]["value"], 942506)
        self.assertEqual(annual["earnings_before_tax"]["value"], 77232)
        contemporary = sources["airtel_q4_2017_ir_pack"]["evidence"]
        self.assertEqual(contemporary["capex"]["value"], 198745)
        self.assertEqual(contemporary["network_towers"]["value"], 184255)
        later = sources["airtel_q4_2019_ir_pack"]["comparative_evidence"]["FY2017"]
        self.assertEqual(later["revenue"]["value"], 942506)
        self.assertEqual(later["network_towers"]["value"], 184255)

    def test_xiaojing_retrieves_airtel_fy2017_three_source_rows_and_conflicts(self):
        combined = "\n".join(
            chunk["text"]
            for chunk in rag_llm._global_operator_exact_metric_chunks(
                "Bharti Airtel FY2017总客户数、营业收入、EBITDA、税前利润、净利润、资本开支、净债务、股东权益、网络铁塔和数据流量是多少？解释口径差异。",
                dataset_ids={"global_top5_operators_2016_2025"},
            )
        )
        expected_values = {
            "total_customers": "372.354 million_customers",
            "revenue": "942506 INR_million",
            "ebitda": "356208 INR_million",
            "earnings_before_tax": "77232 INR_million",
            "net_profit": "37997 INR_million",
            "capex": "198745 INR_million",
            "net_debt": "913999 INR_million",
            "shareholders_equity": "674563 INR_million",
            "network_towers": "184255 sites",
        }
        for metric_key, value_text in expected_values.items():
            self.assertIn(f"metric_key={metric_key}", combined)
            self.assertIn(f"official_value={value_text}", combined)
        self.assertIn("INR954,684m", combined)
        self.assertIn("INR88,929m", combined)
        self.assertIn("162,046", combined)
        self.assertGreaterEqual(combined.count("triple_source_status=three_distinct_sources_verified"), 9)

    def test_airtel_fy2018_adds_common_financials_and_uses_later_comparable_basis(self):
        expected_values = {
            "total_customers": 413.822,
            "revenue": 826388,
            "ebitda": 304479,
            "earnings_before_tax": 32669,
            "net_profit": 10990,
            "capex": 268176,
            "net_debt": 1001060,
            "shareholders_equity": 695344,
            "network_towers": 187541,
            "mobile_broadband_base_stations": 298014,
            "total_data_traffic": 3.9018,
        }
        for metric_key, expected_value in expected_values.items():
            row = self.index[("bharti_airtel", 2018, metric_key)]
            self.assertEqual(row["value"], expected_value)
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
        self.assertIn("INR836,879m", self.index[("bharti_airtel", 2018, "revenue")]["quality_note"])
        self.assertIn("INR40,601m", self.index[("bharti_airtel", 2018, "earnings_before_tax")]["quality_note"])
        self.assertIn("INR10,989m", self.index[("bharti_airtel", 2018, "net_profit")]["quality_note"])
        self.assertIn("INR952,285m", self.index[("bharti_airtel", 2018, "net_debt")]["quality_note"])
        self.assertIn("INR695,322m", self.index[("bharti_airtel", 2018, "shareholders_equity")]["quality_note"])
        self.assertIn("165,748", self.index[("bharti_airtel", 2018, "network_towers")]["quality_note"])

    def test_airtel_fy2018_registry_carries_metric_specific_comparatives(self):
        sources = {
            source["source_id"]: source
            for source in json.loads((GLOBAL / "sources.json").read_text(encoding="utf-8"))["sources"]
        }
        annual = sources["bharti_airtel_ar_2019"]["comparative_evidence"]["FY2018"]
        self.assertEqual(annual["revenue"]["value"], 826388)
        self.assertEqual(annual["earnings_before_tax"]["value"], 32669)
        self.assertEqual(annual["total_data_traffic"]["value"], 3.9018)
        later = sources["airtel_q4_2020_ir_pack"]["comparative_evidence"]["FY2018"]
        self.assertEqual(later["net_debt"]["value"], 1001060)
        self.assertEqual(later["shareholders_equity"]["value"], 695344)
        self.assertEqual(later["network_towers"]["value"], 187541)

    def test_xiaojing_retrieves_airtel_fy2018_three_source_rows_and_restatements(self):
        combined = "\n".join(
            chunk["text"]
            for chunk in rag_llm._global_operator_exact_metric_chunks(
                "Bharti Airtel FY2018总客户数、营业收入、EBITDA、税前利润、净利润、资本开支、净债务、股东权益、网络铁塔、移动宽带基站和数据流量是多少？解释重列和范围差异。",
                dataset_ids={"global_top5_operators_2016_2025"},
            )
        )
        expected_values = {
            "total_customers": "413.822 million_customers",
            "revenue": "826388 INR_million",
            "ebitda": "304479 INR_million",
            "earnings_before_tax": "32669 INR_million",
            "net_profit": "10990 INR_million",
            "capex": "268176 INR_million",
            "net_debt": "1001060 INR_million",
            "shareholders_equity": "695344 INR_million",
            "network_towers": "187541 sites",
            "mobile_broadband_base_stations": "298014 base_stations",
            "total_data_traffic": "3.9018 billion_GB",
        }
        for metric_key, value_text in expected_values.items():
            self.assertIn(f"metric_key={metric_key}", combined)
            self.assertIn(f"official_value={value_text}", combined)
        self.assertIn("INR836,879m", combined)
        self.assertIn("INR952,285m", combined)
        self.assertIn("165,748", combined)
        self.assertGreaterEqual(combined.count("distinct_source_document_count=3"), 11)

    def test_airtel_fy2019_adds_common_financials_and_uses_metric_specific_sources(self):
        expected_values = {
            "total_customers": 403.645,
            "revenue": 807802,
            "ebitda": 262937,
            "earnings_before_tax": -17318,
            "net_profit": 4095,
            "capex": 287427,
            "net_debt": 1129899,
            "shareholders_equity": 714222,
            "network_towers": 204356,
            "mobile_broadband_base_stations": 417613,
            "total_data_traffic": 11.733,
        }
        for metric_key, expected_value in expected_values.items():
            row = self.index[("bharti_airtel", 2019, metric_key)]
            self.assertEqual(row["value"], expected_value)
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
        self.assertIn("181,079", self.index[("bharti_airtel", 2019, "network_towers")]["quality_note"])
        self.assertIn("402.418m", self.index[("bharti_airtel", 2019, "total_customers")]["quality_note"])
        self.assertIn("INR-46,606m", self.index[("bharti_airtel", 2019, "earnings_before_tax")]["quality_note"])
        self.assertIn("INR327,931m", self.index[("bharti_airtel", 2019, "capex")]["quality_note"])
        self.assertIn("INR1,082,346m", self.index[("bharti_airtel", 2019, "net_debt")]["quality_note"])

    def test_airtel_fy2019_registry_does_not_double_count_annual_report_landing(self):
        sources = {
            source["source_id"]: source
            for source in json.loads((GLOBAL / "sources.json").read_text(encoding="utf-8"))["sources"]
        }
        self.assertEqual(
            sources["bharti_airtel_ar_2019"]["source_document_id"],
            sources["airtel_2019_five_year"]["source_document_id"],
        )
        annual = sources["bharti_airtel_ar_2019"]["evidence"]
        self.assertEqual(annual["total_data_traffic"]["value"], 11.733)
        self.assertEqual(annual["mobile_broadband_base_stations"]["value"], 417613)
        for source_id in ("airtel_q4_2020_ir_pack", "airtel_q1_2021_ir_pack"):
            evidence = sources[source_id]["comparative_evidence"]["FY2019"]
            self.assertEqual(evidence["network_towers"]["value"], 204356)
            self.assertEqual(evidence["net_debt"]["value"], 1129899)

    def test_xiaojing_retrieves_airtel_fy2019_three_source_rows_and_scope_breaks(self):
        combined = "\n".join(
            chunk["text"]
            for chunk in rag_llm._global_operator_exact_metric_chunks(
                "Bharti Airtel FY2019总客户数、营业收入、EBITDA、税前利润、净利润、资本开支、净债务、股东权益、网络铁塔、移动宽带基站和数据流量是多少？解释口径冲突。",
                dataset_ids={"global_top5_operators_2016_2025"},
            )
        )
        expected_values = {
            "total_customers": "403.645 million_customers",
            "revenue": "807802 INR_million",
            "ebitda": "262937 INR_million",
            "earnings_before_tax": "-17318 INR_million",
            "net_profit": "4095 INR_million",
            "capex": "287427 INR_million",
            "net_debt": "1129899 INR_million",
            "shareholders_equity": "714222 INR_million",
            "network_towers": "204356 sites",
            "mobile_broadband_base_stations": "417613 base_stations",
            "total_data_traffic": "11.733 billion_GB",
        }
        for metric_key, value_text in expected_values.items():
            self.assertIn(f"metric_key={metric_key}", combined)
            self.assertIn(f"official_value={value_text}", combined)
        self.assertIn("181,079", combined)
        self.assertIn("INR-46,606m", combined)
        self.assertGreaterEqual(combined.count("distinct_source_document_count=3"), 11)

    def test_airtel_fy2020_uses_metric_specific_three_source_matrix(self):
        expected_values = {
            "total_customers": 422.100,
            "revenue": 846765,
            "ebitda": 347696,
            "earnings_before_tax": -44819,
            "net_profit": -321832,
            "capex": 244866,
            "net_debt": 1245209,
            "shareholders_equity": 771448,
            "network_towers": 219546,
        }
        common_sources = {"airtel_q1_2023_ir_pack", "airtel_q2_2023_ir_pack", "airtel_q3_2023_ir_pack"}
        customer_sources = {"airtel_q2_2023_ir_pack", "airtel_q3_2023_ir_pack", "bharti_airtel_ar_2023"}
        for metric_key, expected_value in expected_values.items():
            row = self.index[("bharti_airtel", 2020, metric_key)]
            self.assertEqual(row["value"], expected_value)
            self.assertEqual(set(row["verification_sources"]), customer_sources if metric_key == "total_customers" else common_sources)
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")
        pbt_note = self.index[("bharti_airtel", 2020, "earnings_before_tax")]["quality_note"]
        self.assertIn("INR-44,819m", pbt_note)
        self.assertIn("INR-445,711m", pbt_note)
        customer_note = self.index[("bharti_airtel", 2020, "total_customers")]["quality_note"]
        self.assertIn("423.287m is excluded", customer_note)

    def test_airtel_fy2020_registry_carries_metric_specific_evidence(self):
        sources = {
            source["source_id"]: source
            for source in json.loads((GLOBAL / "sources.json").read_text(encoding="utf-8"))["sources"]
        }
        q1 = sources["airtel_q1_2023_ir_pack"]["comparative_evidence"]["FY2020"]
        self.assertNotIn("total_customers", q1)
        self.assertEqual(q1["earnings_before_tax"]["value"], -44819)
        for source_id in ("airtel_q2_2023_ir_pack", "airtel_q3_2023_ir_pack"):
            evidence = sources[source_id]["comparative_evidence"]["FY2020"]
            self.assertEqual(evidence["total_customers"]["value"], 422.100)
            self.assertEqual(evidence["network_towers"]["value"], 219546)
        annual = sources["bharti_airtel_ar_2023"]["comparative_evidence"]["FY2020"]
        self.assertEqual(set(annual), {"total_customers"})

    def test_airtel_fy2020_network_and_traffic_use_three_annual_documents(self):
        expected_sources = {
            "bharti_airtel_ar_2020",
            "bharti_airtel_ar_2021",
            "airtel_2024_five_year",
        }
        for metric_key, value in (
            ("mobile_broadband_base_stations", 503883),
            ("total_data_traffic", 21.020),
        ):
            row = self.index[("bharti_airtel", 2020, metric_key)]
            self.assertEqual(row["value"], value)
            self.assertEqual(set(row["verification_sources"]), expected_sources)
            self.assertEqual(row["distinct_source_document_count"], 3)
            self.assertEqual(row["triple_source_status"], "three_distinct_sources_verified")

        sources = {
            source["source_id"]: source
            for source in json.loads((GLOBAL / "sources.json").read_text(encoding="utf-8"))["sources"]
        }
        comparative = sources["bharti_airtel_ar_2021"]["comparative_evidence"]["FY2020"]
        self.assertEqual(comparative["mobile_broadband_base_stations"]["value"], 503883)
        self.assertEqual(comparative["total_data_traffic"]["value"], 21.020)

    def test_xiaojing_retrieves_airtel_fy2020_three_source_definition_breaks(self):
        combined = "\n".join(
            chunk["text"]
            for chunk in rag_llm._global_operator_exact_metric_chunks(
                "Bharti Airtel FY2020总客户数、营业收入、EBITDA、税前利润、净利润、资本开支、净债务、股东权益、网络铁塔、移动宽带基站和数据流量是多少？解释税前利润和客户数口径差异。",
                dataset_ids={"global_top5_operators_2016_2025"},
            )
        )
        expected_values = {
            "total_customers": "422.1 million_customers",
            "revenue": "846765 INR_million",
            "ebitda": "347696 INR_million",
            "earnings_before_tax": "-44819 INR_million",
            "net_profit": "-321832 INR_million",
            "capex": "244866 INR_million",
            "net_debt": "1245209 INR_million",
            "shareholders_equity": "771448 INR_million",
            "network_towers": "219546 sites",
            "mobile_broadband_base_stations": "503883 base_stations",
            "total_data_traffic": "21.02 billion_GB",
        }
        for metric_key, value_text in expected_values.items():
            self.assertIn(f"metric_key={metric_key}", combined)
            self.assertIn(f"official_value={value_text}", combined)
        self.assertIn("annual-report KPI earnings-before-tax value of INR-445,711m", combined)
        self.assertIn("earlier Q1 pack's 423.287m is excluded", combined)
        self.assertGreaterEqual(combined.count("distinct_source_document_count=3"), 11)

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

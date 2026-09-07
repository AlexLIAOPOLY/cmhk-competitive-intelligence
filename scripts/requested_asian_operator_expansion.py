"""Strict ten-year expansion for the four requested Asian carriers.

Values with at least one exact official source are added. Source counts remain
explicit so downstream readers can distinguish one-source and multi-source rows.
Each issuer keeps its native fiscal year, currency, reporting perimeter and
restatement basis.  The caller's ``add_series`` function independently checks
the exact value/unit binding recorded below before certifying a row.
"""

from __future__ import annotations

from typing import Any, Callable


YEARS = list(range(2016, 2026))


OPERATORS: dict[str, dict[str, Any]] = {
    "singtel": {
        "name": "Singtel",
        "legal_name": "Singapore Telecommunications Limited",
        "fiscal_year_end": "03-31",
        "existing_financial_reference": "",
    },
    "sk_telecom": {
        "name": "SK Telecom",
        "legal_name": "SK Telecom Co., Ltd.",
        "fiscal_year_end": "12-31",
        "existing_financial_reference": "",
    },
    "ntt_docomo": {
        "name": "NTT DOCOMO",
        "legal_name": "NTT DOCOMO, INC.",
        "fiscal_year_end": "03-31",
        "period_end_year_offset": 1,
        "existing_financial_reference": "",
    },
    "softbank_corp": {
        "name": "SoftBank Corp.",
        "legal_name": "SoftBank Corp.",
        "fiscal_year_end": "03-31",
        "period_end_year_offset": 1,
        "existing_financial_reference": "",
    },
}


SERIES: dict[str, dict[str, tuple[list[float | int | None], str]]] = {
    "singtel": {
        "revenue": (
            [16961, 16711, 17268, 17372, 16542, 15644, 15339, 14624, 14128, 14146],
            "SGD_million",
        ),
        "ebitda": (
            [5013, 4998, 5051, 4692, 4541, 3832, 3767, 3686, 3597, 3792],
            "SGD_million",
        ),
        "net_profit": (
            [3871, 3853, 5473, 3095, 1075, 554, 1949, 2225, 795, 4017],
            "SGD_million",
        ),
        "capex": (
            [1930, 2261, 2349, 1718, 2037, 2214, 2217, 2162, 2150, 2133],
            "SGD_million",
        ),
        "mobile_arpu": ([48, 47, 45, 33, 30, 23, 24, 26, 25, 24], "SGD_per_user_month"),
    },
    "sk_telecom": {
        "revenue": (
            [17091816, 17520013, 16873960, 15416431, 16087747, 16748585, 17304973, 17608511, 17940609, 17099213],
            "KRW_million",
        ),
        "net_profit": (
            [1660101, 2657595, 3131988, 860733, 1500538, 2418989, 947831, 1145937, 1387095, 375084],
            "KRW_million",
        ),
        "capex": (
            [2490455, 2715859, 2792390, 3375883, 3557800, 2915851, 2908287, 2973882, 2487360, 2206567],
            "KRW_million",
        ),
        "mobile_arpu": ([35636, 34901, 32246, 31080, 30314, 30517, 30546, 29874, 29355, 27845], "KRW_per_user_month"),
    },
    "ntt_docomo": {
        "revenue": ([4584.6, 4762.3, 4840.8, 4651.3, 5880.9, 5870.2, 6059.0, 6140.0, 6213.1, 6458.1], "JPY_billion"),
        "net_profit": ([652.5, 790.8, 663.6, 591.5, 749.6, 752.1, 771.8, 795.1, 718.5, 660.2], "JPY_billion"),
        "capex": ([597.1, 577.0, 593.7, 572.8, 734.3, 698.6, 706.3, 705.4, 714.3, 857.5], "JPY_billion"),
        "mobile_service_subscriptions": (
            [74.880, 76.370, 78.453, 80.326, 82.632, 84.752, 87.495, 89.940, 91.407, 93.065],
            "million_subscriptions",
        ),
        "mobile_arpu": (
            [4250, 4370, 4360, 4230, 4280, 4150, 4050, 3980, 3940, 3960],
            "JPY_per_user_month",
        ),
    },
    "softbank_corp": {
        "revenue": ([3483.1, 3582.6, 4656.8, 4861.2, 5205.5, 5690.6, 5912.0, 6084.0, 6544.3, 7038.7], "JPY_billion"),
        "net_profit": ([441.2, 400.7, 462.5, 473.1, 491.3, 517.1, 336.1, 489.1, 526.1, 550.8], "JPY_billion"),
        "capex": ([320.579, 370.387, 498.401, 565.481, 680.277, 647.3, 788.6, 650.9, 912.8, 745.3], "JPY_billion"),
        "mobile_service_subscriptions": (
            [32.400, 33.175, 34.741, 36.499, 37.910, 38.569, 39.596, 40.484, 41.175, 41.317],
            "million_subscriptions",
        ),
        "mobile_arpu": (
            [4500, 4340, 4360, 4420, 4290, 4070, 3850, 3740, 3740, 3720],
            "JPY_per_user_month",
        ),
    },
}


SOFTBANK_SOURCES = {
    "softbank_sbg_fy16_q4": (2016, "SoftBank Group FY2016 Q4 data sheet", "https://group.softbank/system/files/pdf/ir/presentations/2016/earnings-datasheet_q4fy2016_01_en.pdf", "official_results_datasheet"),
    "softbank_sbg_fy17_q4": (2017, "SoftBank Group FY2017 Q4 data sheet", "https://group.softbank/system/files/pdf/ir/presentations/2017/earnings-datasheet_q4fy2017_01_en.pdf", "official_results_datasheet"),
    "softbank_sbg_ar2017": (2017, "SoftBank Group Annual Report 2017", "https://group.softbank/system/files/pdf/ir/financials/annual_reports/annual-report_fy2017_02_en.pdf", "official_annual_report"),
    "softbank_fy18_q4": (2018, "SoftBank Corp. FY2018 Q4 data sheet", "https://www.softbank.jp/en/corp/set/data/ir/documents/presentations/fy2018/results/pdf/sbkk_earnings_datasheet_20190508.pdf", "official_results_datasheet"),
    "softbank_fy18_investor": (2018, "SoftBank Corp. FY2018 investor presentation", "https://www.softbank.jp/en/corp/set/data/ir/documents/presentations/fy2018/investors/pdf/sbkk_investors_presentation_20190508_en.pdf", "official_investor_presentation"),
    "softbank_fy19_investor": (2019, "SoftBank Corp. FY2019 investor presentation", "https://www.softbank.jp/en/corp/set/data/ir/documents/presentations/fy2019/investors/pdf/sbkk_investors_presentation_20200511_en.pdf", "official_investor_presentation"),
    "softbank_fy19_q1": (2019, "SoftBank Corp. FY2019 Q1 data sheet", "https://www.softbank.jp/en/corp/set/data/ir/documents/presentations/fy2019/results/pdf/sbkk_earnings_datasheet_20190805.pdf", "official_results_datasheet"),
    "softbank_fy19_q4": (2019, "SoftBank Corp. FY2019 Q4 data sheet", "https://www.softbank.jp/en/corp/set/data/ir/documents/presentations/fy2019/results/pdf/sbkk_earnings_datasheet_20200511.pdf", "official_results_datasheet"),
    "softbank_fy20_q1": (2020, "SoftBank Corp. FY2020 Q1 data sheet", "https://www.softbank.jp/en/corp/set/data/ir/documents/presentations/fy2020/results/pdf/sbkk_earnings_datasheet_20200804.pdf", "official_results_datasheet"),
    "softbank_fy20_q4": (2020, "SoftBank Corp. FY2020 Q4 data sheet", "https://www.softbank.jp/en/corp/set/data/ir/documents/presentations/fy2020/results/pdf/sbkk_earnings_datasheet_20210511.pdf", "official_results_datasheet"),
    "softbank_fy21_q1": (2021, "SoftBank Corp. FY2021 Q1 data sheet", "https://www.softbank.jp/en/corp/set/data/ir/documents/presentations/fy2021/results/pdf/sbkk_earnings_datasheet_20210804.pdf", "official_results_datasheet"),
    "softbank_fy21_q4": (2021, "SoftBank Corp. FY2021 Q4 data sheet", "https://www.softbank.jp/en/corp/set/data/ir/documents/presentations/fy2021/results/pdf/sbkk_earnings_datasheet_20220511.pdf", "official_results_datasheet"),
    "softbank_fy22_q1": (2022, "SoftBank Corp. FY2022 Q1 data sheet", "https://www.softbank.jp/en/corp/set/data/ir/documents/presentations/fy2022/results/pdf/sbkk_earnings_datasheet_20220804.pdf", "official_results_datasheet"),
    "softbank_fy22_q4": (2022, "SoftBank Corp. FY2022 Q4 data sheet", "https://www.softbank.jp/en/corp/set/data/ir/documents/presentations/fy2022/results/pdf/sbkk_earnings_datasheet_20230510.pdf", "official_results_datasheet"),
    "softbank_fy23_q1": (2023, "SoftBank Corp. FY2023 Q1 data sheet", "https://www.softbank.jp/en/corp/set/data/ir/documents/presentations/fy2023/results/pdf/sbkk_earnings_datasheet_20230804.pdf", "official_results_datasheet"),
    "softbank_fy23_q4": (2023, "SoftBank Corp. FY2023 Q4 data sheet", "https://www.softbank.jp/en/corp/set/data/ir/documents/presentations/fy2023/results/pdf/sbkk_earnings_datasheet_pdf_20240509.pdf", "official_results_datasheet"),
    "softbank_fy24_q1": (2024, "SoftBank Corp. FY2024 Q1 data sheet", "https://www.softbank.jp/en/corp/set/data/ir/documents/presentations/fy2024/results/pdf/sbkk_earnings_datasheet_pdf_20240806.pdf", "official_results_datasheet"),
    "softbank_fy24_q4": (2024, "SoftBank Corp. FY2024 Q4 data sheet", "https://www.softbank.jp/en/corp/set/data/ir/documents/presentations/fy2024/results/pdf/sbkk_earnings_datasheet_pdf_20250508.pdf", "official_results_datasheet"),
    "softbank_fy25_q1": (2025, "SoftBank Corp. FY2025 Q1 data sheet", "https://www.softbank.jp/en/corp/set/data/ir/documents/presentations/fy2025/results/pdf/sbkk_earnings_datasheet_pdf_20250805.pdf", "official_results_datasheet"),
    "softbank_fy25_q4": (2025, "SoftBank Corp. FY2025 Q4 data sheet", "https://www.softbank.jp/corp/set/data/ir/documents/presentations/fy2025/results/pdf/sbkk_earnings_datasheet_pdf_20260511.pdf", "official_results_datasheet"),
    "softbank_fy25_investor": (2025, "SoftBank Corp. FY2025 investor presentation", "https://www.softbank.jp/en/corp/set/data/ir/documents/presentations/fy2025/investors/pdf/sbkk_investors_presentation_20260511_en.pdf", "official_investor_presentation"),
    "softbank_fy25_financial": (2025, "SoftBank Corp. FY2025 consolidated financial report", "https://www.softbank.jp/en/corp/set/data/ir/documents/financial_reports/fy2025/pdf/sbkk_financial_report_20260511_en.pdf", "official_financial_report"),
    "softbank_fy26_q1": (2026, "SoftBank Corp. FY2026 Q1 data sheet", "https://www.softbank.jp/corp/set/data/ir/documents/presentations/fy2026/results/pdf/sbkk_earnings_datasheet_pdf_20260804.pdf", "official_results_datasheet"),
}


_SOFTBANK_MOBILE_METRICS = ("mobile_service_subscriptions", "mobile_arpu")


SOFTBANK_PASS_SOURCES: dict[int, dict[str, tuple[str, ...]]] = {
    2016: {metric: ("softbank_sbg_fy16_q4", "softbank_sbg_fy17_q4", "softbank_sbg_ar2017") for metric in _SOFTBANK_MOBILE_METRICS},
    2017: {
        "mobile_service_subscriptions": ("softbank_sbg_fy17_q4", "softbank_fy18_q4", "softbank_fy18_investor"),
        "mobile_arpu": ("softbank_fy18_q4", "softbank_fy18_investor", "softbank_fy19_investor"),
    },
    2018: {metric: ("softbank_fy18_q4", "softbank_fy19_q1", "softbank_fy19_q4") for metric in _SOFTBANK_MOBILE_METRICS},
    2019: {metric: ("softbank_fy19_q4", "softbank_fy20_q1", "softbank_fy20_q4") for metric in _SOFTBANK_MOBILE_METRICS},
    2020: {metric: ("softbank_fy20_q4", "softbank_fy21_q1", "softbank_fy21_q4") for metric in _SOFTBANK_MOBILE_METRICS},
    2021: {metric: ("softbank_fy21_q4", "softbank_fy22_q1", "softbank_fy22_q4") for metric in _SOFTBANK_MOBILE_METRICS},
    2022: {metric: ("softbank_fy22_q4", "softbank_fy23_q1", "softbank_fy23_q4") for metric in _SOFTBANK_MOBILE_METRICS},
    2023: {metric: ("softbank_fy23_q4", "softbank_fy24_q1", "softbank_fy24_q4") for metric in _SOFTBANK_MOBILE_METRICS},
    2024: {metric: ("softbank_fy24_q4", "softbank_fy25_q1", "softbank_fy25_q4") for metric in _SOFTBANK_MOBILE_METRICS},
    2025: {
        "mobile_arpu": ("softbank_fy25_q4", "softbank_fy25_investor", "softbank_fy26_q1"),
        "mobile_service_subscriptions": ("softbank_fy25_q4",),
        "revenue": ("softbank_fy25_financial",),
        "net_profit": ("softbank_fy25_financial",),
        "capex": ("softbank_fy25_financial",),
    },
}

for _year, _source_id in {
    2016: "softbank_sbg_fy16_q4",
    2017: "softbank_sbg_fy17_q4",
    2018: "softbank_fy18_q4",
    2019: "softbank_fy19_q4",
    2020: "softbank_fy20_q4",
    2021: "softbank_fy21_q4",
    2022: "softbank_fy22_q4",
    2023: "softbank_fy23_q4",
    2024: "softbank_fy24_q4",
    2025: "softbank_fy25_financial",
}.items():
    SOFTBANK_PASS_SOURCES.setdefault(_year, {}).update({
        metric: (_source_id,) for metric in ("revenue", "net_profit", "capex")
    })


SOFTBANK_CANDIDATE_SOURCES = {
    2025: {
        "mobile_service_subscriptions": ("softbank_fy25_q4", "softbank_fy26_q1"),
    },
}


SINGTEL_ANNUAL_REPORT_URLS = {
    2016: "https://cdn2.singteldigital.com/content/dam/singtel/investorRelations/annualReports/2016/Singtel_AR2016.pdf",
    2017: "https://cdn1.singteldigital.com/content/dam/singtel/investorRelations/annualReports/2017/singtelar17-full-AR.pdf",
    2018: "https://cdn2.singteldigital.com/content/dam/singtel/investorRelations/annualReports/2018/singtel-annual-report-2018.pdf",
    2019: "https://cdn2.singteldigital.com/content/dam/singtel/investorRelations/annualReports/2019/singtel-annual-report-2019.pdf",
    2020: "https://cdn2.singteldigital.com/content/dam/singtel/investorRelations/annualReports/2020/singtel-annual-report-2020.pdf",
    2021: "https://cdn2.singteldigital.com/content/dam/singtel/investorRelations/annualReports/2021/singtel-annual-report-2021.pdf",
    2022: "https://cdn2.singteldigital.com/content/dam/singtel/investorRelations/annualReports/2022/Singtel-Annual-Report-2022.pdf",
    2023: "https://media.aws.singtel.com/info-singtel/annualreport/2023/Singtel_Annual_Report_2023_Higher_Res.pdf",
    2024: "https://media.aws.singtel.com/info-singtel/annualreport/2024/Annual-Report-2024.pdf",
    2025: "https://cdn2.singteldigital.com/content/dam/singtel/investorRelations/annualReports/2025/Singtel-AR25.pdf",
    2026: "https://cdn2.singteldigital.com/content/dam/singtel/investorRelations/annualReports/2026/AR2026.pdf",
}


SINGTEL_MDA_URLS = {
    2016: "https://cdn2.singteldigital.com/content/dam/singtel/investorRelations/financialResults/2016/Q4FY16_MDA.pdf",
    2017: "https://cdn2.singteldigital.com/content/dam/singtel/investorRelations/financialResults/2017/Q4FY17_MDA.pdf",
    2018: "https://cdn2.singteldigital.com/content/dam/singtel/investorRelations/financialResults/2018/Q4FY18-MDA.pdf",
    2019: "https://cdn2.singteldigital.com/content/dam/singtel/investorRelations/financialResults/2019/Q4FY19-MDA.pdf",
    2020: "https://cdn1.singteldigital.com/content/dam/singtel/investorRelations/financialResults/2020/Q4FY20-Group-MDA_Finalv2.pdf",
    2021: "https://cdn1.singteldigital.com/content/dam/singtel/investorRelations/financialResults/2021/H2FY21-Group-MDA.pdf",
    2022: "https://cdn1.singteldigital.com/content/dam/singtel/investorRelations/financialResults/2022/H2FY22-Group-MDA.pdf",
    2023: "https://cdn2.singteldigital.com/content/dam/singtel/investorRelations/financialResults/2023/h2fy23/H2FY23-Group-MDA.pdf",
    2024: "https://cdn2.singteldigital.com/content/dam/singtel/investorRelations/financialResults/2024/h2fy24/Group-Mar-2024-MDA-2.pdf",
    2025: "https://cdn1.singteldigital.com/content/dam/singtel/investorRelations/financialResults/2025/H2FY25/FY25-Group-MDA_Finalv2.pdf",
}


SINGTEL_SOURCE_YEARS = {
    2016: ("singtel_ar_2016", "singtel_ar_2017", "singtel_ar_2018"),
    2017: ("singtel_ar_2017", "singtel_ar_2018", "singtel_ar_2019"),
    # FY2018 is retained on the later SFRS(I)-restated basis, so the original
    # FY2018 annual-report values are intentionally not counted.
    2018: ("singtel_ar_2019", "singtel_ar_2020", "singtel_ar_2021"),
    2019: ("singtel_ar_2019", "singtel_ar_2020", "singtel_ar_2021"),
    2020: ("singtel_ar_2020", "singtel_ar_2021", "singtel_ar_2022"),
    2021: ("singtel_ar_2021", "singtel_ar_2022", "singtel_ar_2023"),
    2022: ("singtel_ar_2022", "singtel_ar_2023", "singtel_ar_2024"),
    2023: ("singtel_ar_2023", "singtel_ar_2024", "singtel_ar_2025"),
    2024: ("singtel_ar_2024", "singtel_ar_2025", "singtel_mda_2024"),
    2025: ("singtel_ar_2025", "singtel_ar_2026", "singtel_mda_2025"),
}


SKT_ANNUAL_REPORT_URLS = {
    2016: "https://www.sktelecom.com/img/eng/annual/20210713/SKT2016AReng.pdf",
    2017: "https://www.sktelecom.com/img/eng/annual/20210713/SKT2017AReng.pdf",
    2018: "https://www.sktelecom.com/img/eng/annual/20210713/SKT2018AReng.pdf",
    2019: "https://www.sktelecom.com/img/eng/annual/20210713/SKT2019AReng.pdf",
    2020: "https://www.sktelecom.com/img/eng/annual/20210716/SKT2020AnnualReportENG.pdf",
    2021: "https://www.sktelecom.com/img/eng/annual/20240409/SK_Telecom_Annual_Report_2021_Eng_F.pdf",
    2022: "https://www.sktelecom.com/img/eng/annual/20240409/SK_Telecom_AnnualReport_2022_Eng.pdf",
    2023: "https://www.sktelecom.com/img/eng/annual/20240731/SK_Telecom_Annual_Report_2023_Eng.pdf",
    2024: "https://www.sktelecom.com/img/eng/annual/20250808/SK_Telecom_Annual_Report_2024_ENG_F_0808.pdf",
}


SKT_OTHER_SOURCES = {
    "skt_audit_2024_consolidated": {
        "year": 2024,
        "label": "SK Telecom FY2024 consolidated audit report",
        "url": "https://www.sktelecom.com/img/eng/audit/20250311/FY2024_Audit_Report%28Consolidated%29.pdf",
        "source_type": "official_audited_financial_statements",
        "document_id": "skt:consolidated_audit:2024",
    },
    "skt_20f_2025": {
        "year": 2025,
        "label": "SK Telecom 2025 Form 20-F",
        "url": "https://www.sec.gov/Archives/edgar/data/1015650/000119312526188763/d78252d20f.htm",
        "source_type": "official_regulatory_filing",
        "document_id": "skt:20f:2025",
    },
    "skt_6k_2025_audited_fs": {
        "year": 2025,
        "label": "SK Telecom FY2025 audited financial statements furnished on Form 6-K",
        "url": "https://www.sec.gov/Archives/edgar/data/1015650/000119312526101145/d25304d6k.htm",
        "source_type": "official_regulatory_filing",
        "document_id": "skt:6k_audited_financials:2025",
    },
}

SKT_ARPU_SOURCE_URLS = {
    2016: SKT_ANNUAL_REPORT_URLS[2016],
    2017: SKT_ANNUAL_REPORT_URLS[2017],
    2018: "https://www.sktelecom.com/img/eng/qua/20190131/4Q18InvestorBriefingENG.pdf",
    2019: "https://www.sktelecom.com/img/eng/persist_report/20210713/SSKT2019AReng.pdf",
    2020: "https://www.sktelecom.com/img/eng/persist_report/20210716/SKT2020AnnualReportENG.pdf",
    2021: SKT_ANNUAL_REPORT_URLS[2021],
    2022: SKT_ANNUAL_REPORT_URLS[2022],
    2023: "https://www.sktelecom.com/img/eng/persist_report/20240731/SK_Telecom_Annual_Report_2023_Eng.pdf?v2=",
    2024: "https://www.sktelecom.com/img/kor/persist_report/20250808/SK_Telecom_Annual_Report_2024_ENG_F_0808.pdf",
    2025: "https://www.sec.gov/Archives/edgar/data/1015650/000119312526188763/d78252d20f.htm",
}


SKT_PASS_SOURCES: dict[int, dict[str, tuple[str, ...]]] = {
    2016: {metric: ("skt_ar_2016", "skt_ar_2017", "skt_ar_2018") for metric in SERIES["sk_telecom"]},
    2017: {metric: ("skt_ar_2017", "skt_ar_2018", "skt_ar_2019") for metric in SERIES["sk_telecom"]},
    2018: {metric: ("skt_ar_2018", "skt_ar_2019", "skt_ar_2020") for metric in SERIES["sk_telecom"]},
    2019: {
        "capex": ("skt_ar_2019", "skt_ar_2020", "skt_ar_2021"),
    },
    2020: {
        "net_profit": ("skt_ar_2020", "skt_ar_2021", "skt_ar_2022"),
        "capex": ("skt_ar_2020", "skt_ar_2021", "skt_ar_2022"),
    },
    2021: {metric: ("skt_ar_2021", "skt_ar_2022", "skt_ar_2023") for metric in SERIES["sk_telecom"]},
    2022: {metric: ("skt_ar_2022", "skt_ar_2023", "skt_ar_2024") for metric in SERIES["sk_telecom"]},
    2023: {
        metric: ("skt_ar_2023", "skt_ar_2024", "skt_audit_2024_consolidated")
        for metric in SERIES["sk_telecom"]
    },
    2024: {
        metric: ("skt_ar_2024", "skt_audit_2024_consolidated", "skt_20f_2025")
        for metric in SERIES["sk_telecom"]
    },
}
SKT_PASS_SOURCES[2019].update({"revenue": ("skt_ar_2021",), "net_profit": ("skt_ar_2021",)})
SKT_PASS_SOURCES[2020]["revenue"] = ("skt_ar_2021",)
SKT_PASS_SOURCES[2025] = {
    "revenue": ("skt_6k_2025_audited_fs",),
    "net_profit": ("skt_6k_2025_audited_fs",),
    "capex": ("skt_6k_2025_audited_fs",),
}
for _year in YEARS:
    SKT_PASS_SOURCES.setdefault(_year, {})["mobile_arpu"] = (f"skt_arpu_{_year}",)


SKT_CANDIDATE_SOURCES: dict[int, dict[str, tuple[str, ...]]] = {
    2019: {
        "revenue": ("skt_ar_2019", "skt_ar_2020", "skt_ar_2021"),
        "net_profit": ("skt_ar_2019", "skt_ar_2020", "skt_ar_2021"),
    },
    2020: {
        "revenue": ("skt_ar_2020", "skt_ar_2021", "skt_ar_2022"),
    },
    2025: {
        metric: ("skt_20f_2025", "skt_6k_2025_audited_fs")
        for metric in SERIES["sk_telecom"]
    },
}


DOCOMO_SOURCES = {
    "docomo_annual_operating_2026": {
        "year": 2025,
        "label": "NTT DOCOMO Annual Operating Data through FY2025",
        "url": "https://www.docomo.ne.jp/english/corporate/ir/binary/pdf/library/finance/annual/annual_e.pdf?ver=1750381212",
        "source_type": "official_operating_statistics",
        "document_id": "docomo:annual_operating_data:2026",
    },
    "docomo_fy2016_earnings": {
        "year": 2016,
        "label": "NTT DOCOMO FY2016 earnings release",
        "url": "https://www.docomo.ne.jp/english/corporate/ir/binary/pdf/library/earnings/earnings_release_fy2016_4q_e.pdf",
        "source_type": "official_earnings_release",
        "document_id": "docomo:earnings:2016",
    },
    "docomo_fy2016_20f": {
        "year": 2016,
        "label": "NTT DOCOMO FY2016 Form 20-F",
        "url": "https://www.docomo.ne.jp/english/corporate/ir/binary/pdf/library/sec/20f_fy2016_e.pdf",
        "source_type": "official_regulatory_filing",
        "document_id": "docomo:20f:2016",
    },
    "docomo_fy2017_earnings": {
        "year": 2017,
        "label": "NTT DOCOMO FY2017 earnings release",
        "url": "https://www.docomo.ne.jp/english/corporate/ir/binary/pdf/library/earnings/earnings_release_fy2017_4q_e.pdf",
        "source_type": "official_earnings_release",
        "document_id": "docomo:earnings:2017",
    },
    "docomo_fy2017_yuho": {
        "year": 2017,
        "label": "NTT DOCOMO FY2017 annual securities report",
        "url": "https://www.docomo.ne.jp/english/corporate/ir/binary/pdf/library/report/fy2017/yuho_fy2017_e.pdf",
        "source_type": "official_regulatory_filing",
        "document_id": "docomo:yuho:2017",
    },
    "docomo_fy2018_earnings": {
        "year": 2018,
        "label": "NTT DOCOMO FY2018 earnings release",
        "url": "https://www.docomo.ne.jp/english/corporate/ir/binary/pdf/library/earnings/earnings_release_fy2018_4q_e.pdf",
        "source_type": "official_earnings_release",
        "document_id": "docomo:earnings:2018",
    },
    "docomo_fy2018_yuho": {
        "year": 2018,
        "label": "NTT DOCOMO FY2018 annual securities report",
        "url": "https://www.docomo.ne.jp/english/corporate/ir/binary/pdf/library/report/fy2018/annual_securities_fy2018_e.pdf",
        "source_type": "official_regulatory_filing",
        "document_id": "docomo:yuho:2018",
    },
    "docomo_fy2019_earnings": {
        "year": 2019,
        "label": "NTT DOCOMO FY2019 earnings release",
        "url": "https://www.docomo.ne.jp/english/corporate/ir/binary/pdf/library/earnings/earnings_release_fy2019_4q_e.pdf",
        "source_type": "official_earnings_release",
        "document_id": "docomo:earnings:2019",
    },
    "docomo_fy2019_yuho": {
        "year": 2019,
        "label": "NTT DOCOMO FY2019 annual securities report (revised)",
        "url": "https://www.docomo.ne.jp/english/corporate/ir/binary/pdf/library/report/fy2019/annual_securities_fy2019_e_revised.pdf",
        "source_type": "official_regulatory_filing",
        "document_id": "docomo:yuho:2019:revised",
    },
}

_DOCOMO_RESULTS_PRESENTATION_DATES = {
    2016: "170427", 2017: "180427", 2018: "190426", 2019: "200428",
    2020: "210511", 2021: "220512", 2022: "230512", 2023: "240510",
    2024: "250509", 2025: "260508",
}
for _year, _date in _DOCOMO_RESULTS_PRESENTATION_DATES.items():
    DOCOMO_SOURCES[f"docomo_fy{_year}_presentation"] = {
        "year": _year,
        "label": f"NTT DOCOMO FY{_year} financial results presentation",
        "url": f"https://www.docomo.ne.jp/english/corporate/ir/binary/pdf/library/presentation/{_date}/presentation_fy{_year}_4q_e.pdf",
        "source_type": "official_results_presentation",
        "document_id": f"docomo:results_presentation:{_year}",
    }

for _year in range(2020, 2026):
    _suffix = "0508" if _year == 2025 else "0509" if _year == 2024 else "0510" if _year == 2023 else "0512"
    DOCOMO_SOURCES[f"ntt_fy{_year}_data"] = {
        "year": _year,
        "label": f"NTT FY{_year} annual results data workbook",
        "url": f"https://group.ntt/en/ir/library/results/{_year}/excel/fy{_year}q4data{_suffix}.xlsx",
        "source_type": "official_results_workbook",
        "document_id": f"ntt:annual_results_data:{_year}",
    }
    DOCOMO_SOURCES[f"ntt_fy{_year}_yuho"] = {
        "year": _year,
        "label": f"NTT FY{_year} annual securities report",
        "url": (
            f"https://group.ntt/en/ir/library/yuho/{_year}/pdf/"
            f"{_year - 1984}yuho{'_2' if _year == 2021 else ''}.pdf"
        ),
        "source_type": "official_regulatory_filing",
        "document_id": f"ntt:yuho:{_year}",
    }


_DOCOMO_MOBILE_METRICS = ("mobile_service_subscriptions", "mobile_arpu")


DOCOMO_PASS_SOURCES: dict[int, dict[str, tuple[str, ...]]] = {
    2016: {
        "mobile_service_subscriptions": (
            "docomo_annual_operating_2026", "docomo_fy2016_earnings", "docomo_fy2016_20f"
        ),
    },
    2017: {
        "mobile_service_subscriptions": (
            "docomo_annual_operating_2026", "docomo_fy2017_earnings", "docomo_fy2017_yuho"
        ),
        "mobile_arpu": (
            "docomo_annual_operating_2026", "docomo_fy2018_earnings", "docomo_fy2018_yuho"
        ),
    },
    2018: {
        metric: ("docomo_annual_operating_2026", "docomo_fy2018_earnings", "docomo_fy2018_yuho")
        for metric in _DOCOMO_MOBILE_METRICS
    },
    2019: {
        metric: ("docomo_annual_operating_2026", "docomo_fy2019_earnings", "docomo_fy2019_yuho")
        for metric in _DOCOMO_MOBILE_METRICS
    },
    **{
        year: {
            metric: ("docomo_annual_operating_2026", f"ntt_fy{year}_data", f"ntt_fy{year}_yuho")
            for metric in _DOCOMO_MOBILE_METRICS
        }
        for year in range(2020, 2026)
    },
}
DOCOMO_PASS_SOURCES[2016]["mobile_arpu"] = ("docomo_annual_operating_2026",)
for _year in YEARS:
    DOCOMO_PASS_SOURCES.setdefault(_year, {}).update({
        metric: (f"docomo_fy{_year}_presentation",)
        for metric in ("revenue", "net_profit", "capex")
    })


def _values(operator_id: str, metric_key: str) -> tuple[dict[int, float | int | None], str]:
    raw, unit = SERIES[operator_id][metric_key]
    return dict(zip(YEARS, raw)), unit


def _register_singtel_sources(sources: dict[str, dict[str, Any]]) -> None:
    for document_year, url in SINGTEL_ANNUAL_REPORT_URLS.items():
        source_id = f"singtel_ar_{document_year}"
        sources[source_id] = {
            "source_id": source_id,
            "source_document_id": f"singtel:annual_report:{document_year}",
            "operator_id": "singtel",
            "year": document_year,
            "label": f"Singtel Annual Report {document_year}",
            "url": url,
            "source_type": "official_annual_report",
            "publisher": OPERATORS["singtel"]["legal_name"],
            "comparative_evidence": {},
        }
    for value_year, url in SINGTEL_MDA_URLS.items():
        source_id = f"singtel_mda_{value_year}"
        sources[source_id] = {
            "source_id": source_id,
            "source_document_id": f"singtel:management_discussion:{value_year}",
            "operator_id": "singtel",
            "year": value_year,
            "label": f"Singtel FY{value_year} Management Discussion and Analysis",
            "url": url,
            "source_type": "official_results_mda",
            "publisher": OPERATORS["singtel"]["legal_name"],
            "comparative_evidence": {},
        }

    for value_year, source_ids in SINGTEL_SOURCE_YEARS.items():
        for metric_key in SERIES["singtel"]:
            values, unit = _values("singtel", metric_key)
            metric_source_ids = (
                (f"singtel_mda_{value_year}",)
                if metric_key == "mobile_arpu"
                else source_ids
            )
            locator = (
                f"FY{value_year} Singapore mobile blended ARPU table"
                if metric_key == "mobile_arpu"
                else f"FY{value_year} Group five-year financial summary"
                if all("_ar_" in source_id for source_id in metric_source_ids)
                else f"FY{value_year} Group financial and cash-capex tables"
            )
            for source_id in metric_source_ids:
                sources[source_id].setdefault("comparative_evidence", {}).setdefault(
                    f"FY{value_year}", {}
                )[metric_key] = {
                    "value": values[value_year],
                    "unit": unit,
                    "locator": locator,
                }


def _register_skt_sources(sources: dict[str, dict[str, Any]]) -> None:
    for document_year, url in SKT_ANNUAL_REPORT_URLS.items():
        source_id = f"skt_ar_{document_year}"
        sources[source_id] = {
            "source_id": source_id,
            "source_document_id": f"skt:annual_report:{document_year}",
            "operator_id": "sk_telecom",
            "year": document_year,
            "label": f"SK Telecom Annual Report {document_year}",
            "url": url,
            "source_type": "official_annual_report",
            "publisher": OPERATORS["sk_telecom"]["legal_name"],
            "comparative_evidence": {},
        }
    for source_id, spec in SKT_OTHER_SOURCES.items():
        sources[source_id] = {
            "source_id": source_id,
            "source_document_id": spec["document_id"],
            "operator_id": "sk_telecom",
            "year": spec["year"],
            "label": spec["label"],
            "url": spec["url"],
            "source_type": spec["source_type"],
            "publisher": OPERATORS["sk_telecom"]["legal_name"],
            "comparative_evidence": {},
        }
    for value_year, url in SKT_ARPU_SOURCE_URLS.items():
        source_id = f"skt_arpu_{value_year}"
        sources[source_id] = {
            "source_id": source_id,
            "source_document_id": f"skt:mobile_arpu:{value_year}",
            "operator_id": "sk_telecom",
            "year": value_year,
            "label": f"SK Telecom FY{value_year} official ARPU disclosure",
            "url": url,
            "source_type": "official_operating_statistics",
            "publisher": OPERATORS["sk_telecom"]["legal_name"],
            "comparative_evidence": {},
        }

    for value_year, metric_sources in SKT_PASS_SOURCES.items():
        for metric_key, source_ids in metric_sources.items():
            values, unit = _values("sk_telecom", metric_key)
            for source_id in source_ids:
                sources[source_id].setdefault("comparative_evidence", {}).setdefault(
                    f"FY{value_year}", {}
                )[metric_key] = {
                    "value": values[value_year],
                    "unit": unit,
                    "locator": (
                        "Consolidated Statements of Cash Flows > acquisitions of property and equipment"
                        if metric_key == "capex"
                        else "SK Telecom mobile ARPU operating table"
                        if metric_key == "mobile_arpu"
                        else "Consolidated Statements of Income/Comprehensive Income comparative column"
                    ),
                }


def _register_docomo_sources(sources: dict[str, dict[str, Any]]) -> None:
    for source_id, spec in DOCOMO_SOURCES.items():
        sources[source_id] = {
            "source_id": source_id,
            "source_document_id": spec["document_id"],
            "operator_id": "ntt_docomo",
            "year": spec["year"],
            "label": spec["label"],
            "url": spec["url"],
            "source_type": spec["source_type"],
            "publisher": (
                "NTT DOCOMO, INC." if source_id.startswith("docomo_") else "NTT, Inc."
            ),
            "comparative_evidence": {},
        }
    for value_year, metric_sources in DOCOMO_PASS_SOURCES.items():
        for metric_key, source_ids in metric_sources.items():
            values, unit = _values("ntt_docomo", metric_key)
            for source_id in source_ids:
                sources[source_id].setdefault("comparative_evidence", {}).setdefault(
                    f"FY{value_year}", {}
                )[metric_key] = {
                    "value": values[value_year],
                    "unit": unit,
                    "locator": (
                        "Cellular/mobile service subscriptions table"
                        if metric_key == "mobile_service_subscriptions"
                        else "Aggregate/Mobile ARPU table"
                        if metric_key == "mobile_arpu"
                        else "Consolidated results highlights: revenue, attributable profit and capital expenditures"
                    ),
                }


def _register_softbank_sources(sources: dict[str, dict[str, Any]]) -> None:
    for source_id, (document_year, label, url, source_type) in SOFTBANK_SOURCES.items():
        sources[source_id] = {
            "source_id": source_id,
            "source_document_id": f"softbank:{source_id.removeprefix('softbank_')}",
            "operator_id": "softbank_corp",
            "year": document_year,
            "label": label,
            "url": url,
            "source_type": source_type,
            "publisher": "SoftBank Corp." if "softbank_sbg_" not in source_id else "SoftBank Group Corp.",
            "comparative_evidence": {},
        }
    for value_year, metric_sources in SOFTBANK_PASS_SOURCES.items():
        for metric_key, source_ids in metric_sources.items():
            values, unit = _values("softbank_corp", metric_key)
            for source_id in source_ids:
                sources[source_id].setdefault("comparative_evidence", {}).setdefault(
                    f"FY{value_year}", {}
                )[metric_key] = {
                    "value": values[value_year],
                    "unit": unit,
                    "locator": (
                        "Mobile service: main subscribers table (reported in thousands; normalized to millions)"
                        if metric_key == "mobile_service_subscriptions"
                        else "Mobile service ARPU table"
                        if metric_key == "mobile_arpu"
                        else "Consolidated results and capital expenditures table"
                    ),
                }


def apply_requested_asian_expansion(
    operators: dict[str, dict[str, Any]],
    metrics: dict[str, tuple[str, str]],
    sources: dict[str, dict[str, Any]],
    add_series: Callable[..., None],
) -> None:
    operators.update(OPERATORS)
    _register_singtel_sources(sources)
    _register_skt_sources(sources)
    _register_docomo_sources(sources)
    _register_softbank_sources(sources)

    scope = (
        "Singtel Group consolidated financials; native 31 March fiscal year; FY2018 uses the "
        "later SFRS(I)-restated comparative basis; capex is the issuer's cash-capex KPI. "
        "Mobile ARPU is Singapore blended prepaid and postpaid ARPU, not a group-wide KPI"
    )
    for metric_key in SERIES["singtel"]:
        values, unit = _values("singtel", metric_key)
        add_series(
            "singtel",
            metric_key,
            values,
            unit=unit,
            scope=scope,
            source_ids={
                year: [f"singtel_mda_{year}"] if metric_key == "mobile_arpu" else list(SINGTEL_SOURCE_YEARS[year])
                for year in values
            },
            note=(
                "At least one exact Singtel official document supports every stored value. "
                "FY2018 retains the later SFRS(I)-restated series and FY2019 begins the SFRS(I) 15 boundary. Native SGD million "
                "and issuer fiscal years are retained; no FX conversion or interpolation is applied."
            ),
        )

    docomo_scope = (
        "NTT DOCOMO Group; fiscal year ending the following 31 March. FY2020 begins the "
        "integrated group scope and is not strictly like-for-like with FY2019; mobile ARPU "
        "subscriptions include MVNO and communications-module contracts"
    )
    for metric_key in SERIES["ntt_docomo"]:
        raw_values, unit = _values("ntt_docomo", metric_key)
        values = {
            year: value if metric_key in DOCOMO_PASS_SOURCES.get(year, {}) else None
            for year, value in raw_values.items()
        }
        source_ids = {
            year: list(
                DOCOMO_PASS_SOURCES.get(year, {}).get(metric_key)
                or (
                    "docomo_annual_operating_2026",
                    "docomo_fy2016_earnings",
                    "docomo_fy2016_20f",
                )
            )
            for year in values
        }
        add_series(
            "ntt_docomo",
            metric_key,
            values,
            unit=unit,
            scope=docomo_scope,
            source_ids=source_ids,
            note=(
                "At least one exact official DOCOMO/NTT document supports every stored value. "
                "FY2016 Mobile ARPU uses the issuer's JPY4,250 mobile ARPU series. "
                "FY2021 onward Mobile ARPU uses the new definition including OCN mobile; "
                "FY2024 includes a mail-related revenue reclassification."
            ),
        )

    softbank_scope = (
        "SoftBank mobile service main subscribers and mobile ARPU; fiscal year ending "
        "the following 31 March; FY2016-FY2017 predecessor disclosures use SoftBank "
        "Group's Domestic Telecommunications segment for the business later held by SoftBank Corp."
    )
    for metric_key in SERIES["softbank_corp"]:
        raw_values, unit = _values("softbank_corp", metric_key)
        values = {
            year: value if metric_key in SOFTBANK_PASS_SOURCES.get(year, {}) else None
            for year, value in raw_values.items()
        }
        source_ids = {
            year: list(
                SOFTBANK_PASS_SOURCES.get(year, {}).get(metric_key)
                or SOFTBANK_CANDIDATE_SOURCES.get(year, {}).get(metric_key)
                or ()
            )
            for year in values
        }
        add_series(
            "softbank_corp",
            metric_key,
            values,
            unit=unit,
            scope=softbank_scope,
            source_ids=source_ids,
            note=(
                "At least one exact SoftBank official document supports every stored value. "
                "Main subscribers include multiple brands, tablets, data devices and Wireless "
                "Home Phone and are not a strict postpaid count. FY2017 ARPU retains the later "
                "IFRS 15-restated JPY4,340 rather than the prior JPY4,350 basis. FY2024 renamed "
                "Total ARPU to Mobile ARPU. FY2016-FY2017 capex uses the predecessor Domestic "
                "Telecommunications segment and is not strictly like-for-like with later SoftBank Corp. years."
            ),
        )

    skt_scope = (
        "SK Telecom Co., Ltd. and subsidiaries consolidated; calendar fiscal year; "
        "capex is cash acquisitions of property and equipment, not management guidance. "
        "Mobile ARPU is the separately disclosed MNO/mobile-service measure excluding MVNO; "
        "FY2023 introduces a definition boundary"
    )
    gap_notes = {
        (2019, "revenue"): "Later continuing-operations restatement after the SK Square spin-off appears in fewer than three distinct official documents; the original FY2019 group revenue conflicts with that basis.",
        (2019, "net_profit"): "The selected restated profit matches only two distinct later annual reports; the contemporaneous FY2019 value differs.",
        (2020, "revenue"): "Later continuing-operations restatement after the SK Square spin-off appears in only two distinct official annual reports; the contemporaneous FY2020 group revenue differs.",
    }
    for metric_key in SERIES["sk_telecom"]:
        raw_values, unit = _values("sk_telecom", metric_key)
        values = {
            year: value if metric_key in SKT_PASS_SOURCES.get(year, {}) else None
            for year, value in raw_values.items()
        }
        source_ids = {
            year: list(
                SKT_PASS_SOURCES.get(year, {}).get(metric_key)
                or SKT_CANDIDATE_SOURCES.get(year, {}).get(metric_key)
                or ()
            )
            for year in values
        }
        add_series(
            "sk_telecom",
            metric_key,
            values,
            unit=unit,
            scope=skt_scope,
            basis="cash_acquisitions_of_property_and_equipment" if metric_key == "capex" else "reported_or_later_restated_consolidated",
            source_ids=source_ids,
            note=(
                "At least one exact SK Telecom official document supports every stored value. "
                "The 1 November 2021 SK Square spin-off creates a continuing-operations "
                "restatement boundary for FY2019-FY2020 revenue. "
                + " ".join(
                    note for (year, key), note in gap_notes.items() if key == metric_key
                )
            ).strip(),
        )

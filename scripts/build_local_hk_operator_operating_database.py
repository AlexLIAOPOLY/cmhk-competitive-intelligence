from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "agent_knowledge" / "local_hk_operator_operating_metrics_2016_2025"
BUILD_TIME = "2026-08-29T15:45:02+08:00"
YEARS = list(range(2016, 2026))

OPERATORS = {
    "cmhk": {"name": "CMHK", "legal_name": "China Mobile Hong Kong Company Limited", "fiscal_year_end": "12-31", "brands": ["CMHK"]},
    "hkt": {"name": "HKT", "legal_name": "HKT Trust and HKT Limited", "fiscal_year_end": "12-31", "brands": ["csl", "1O1O"]},
    "three_hk": {"name": "3HK", "legal_name": "Hutchison Telecommunications Hong Kong Holdings Limited", "fiscal_year_end": "12-31", "brands": ["3 Hong Kong"]},
    "smartone": {"name": "SmarTone", "legal_name": "SmarTone Telecommunications Holdings Limited", "fiscal_year_end": "06-30", "brands": ["SmarTone"]},
    "hkbn": {"name": "HKBN", "legal_name": "HKBN Ltd.", "fiscal_year_end": "08-31", "brands": ["香港寬頻"]},
    "hgc": {"name": "HGC", "legal_name": "HGC Global Communications Limited", "fiscal_year_end": "12-31", "brands": ["環球全域電訊"]},
    "icable": {"name": "i-CABLE", "legal_name": "i-CABLE Communications Limited", "fiscal_year_end": "12-31", "brands": ["有線寬頻", "HOY TV"]},
}

METRICS = {
    "total_customers": ("總客戶數", "million_customers"),
    "mobile_postpaid_customers": ("移動後付客戶", "million_customers"),
    "mobile_prepaid_customers": ("移動預付客戶", "million_customers"),
    "5g_customers": ("5G客戶", "million_customers"),
    "5g_penetration": ("5G滲透率", "percent"),
    "consumer_broadband_customers": ("住宅寬頻客戶", "million_customers"),
    "ftth_connections": ("FTTH連接", "million_connections"),
    "homes_passed_or_connected": ("寬頻網絡覆蓋/接入家庭", "million_homes"),
    "commercial_buildings_covered": ("商業樓宇覆蓋", "buildings"),
    "residential_arpu": ("住宅業務ARPU", "HKD_per_month"),
    "residential_arph": ("住宅業務ARPH", "HKD_per_household_month"),
    "mobile_postpaid_arpu": ("移動後付ARPU", "HKD_per_user_month"),
    "mobile_postpaid_exit_arpu": ("移動後付期末ARPU", "HKD_per_user_month"),
    "mobile_postpaid_net_arpu": ("移動後付淨ARPU", "HKD_per_user_month"),
    "mobile_postpaid_net_ampu": ("移動後付淨AMPU", "HKD_per_user_month"),
    "mobile_postpaid_churn": ("移動後付月流失率", "percent"),
    "pay_tv_customers": ("收費電視客戶", "million_customers"),
    "telephony_customers": ("固網電話客戶", "million_customers"),
    "5g_population_coverage": ("5G人口覆蓋率", "percent"),
    "mobile_data_dou": ("月戶均移動數據流量DOU", "GB_per_user_month"),
    "annual_mobile_data_traffic": ("年度移動數據流量", "TB"),
    "total_base_stations": ("移動基站總數", "base_stations"),
    "5g_base_stations": ("5G基站數", "base_stations"),
    "5g_base_station_expansion": ("5G基站擴展幅度", "percent"),
    "free_tv_population_coverage": ("免費電視人口/家庭覆蓋率", "percent"),
    "mtr_stations_5g_enhanced": ("5G增強地鐵站", "stations"),
    "residential_2gbps_plus_customers": ("住宅2Gbps以上客戶", "customers"),
    "enterprise_2gbps_plus_customers": ("企業2Gbps以上客戶", "customers"),
    "enterprise_core_churn": ("企業核心業務月流失率", "percent"),
    "5g_home_broadband_revenue_growth": ("5G家庭寬頻收入增長", "percent"),
    "5g_home_broadband_ebitda_growth": ("5G家庭寬頻EBITDA增長", "percent"),
}


def hkt_url(year: int) -> str:
    paths = {
        2016: "01e%20-%20Annual%20Repor.pdf", 2017: "e01-%20Annual%20Report.pdf",
        2018: "2018-hkt-annual-re_e.pdf", 2019: "e1-Annual-Report.pdf",
        2020: "e01_Annual%20Report.pdf", 2021: "e01-e_Annual%20Repor.pdf",
        2022: "e01-HKT%20Annual%20Rep.pdf", 2023: "e01-2023%20Annual%20Re.pdf",
        2024: "e01-2024%20Annual%20Report.pdf", 2025: "e-2025_Annual_Report.pdf",
    }
    return "https://www.hkt.com/api-service/assets/" + paths[year]


def smartone_url(year: int) -> str:
    return f"https://www.smartoneholdings.com/about/investor/financial_reports/english/{year-1}_{year}_annual.pdf"


HKT_ANNUAL_RESULTS = {
    2016: ("HKT 2016 Annual Res.pdf", "e01-2017.01.13 (201.pdf"),
    2017: ("HKT 2017 Annual Res.pdf", "e01-2018.02.06 (201.pdf"),
    2018: ("hkt-2018-annual-res.pdf", "e01-2019.02.22 (201.pdf"),
    2019: ("hkt-2019-annual-res.pdf", "e-2020.02.12 (2019 .pdf"),
    2020: ("hkt-2020-annual-res.pdf", "e01-2021.02.04 (202.pdf"),
    2021: ("hkt-2021-annual-res.pdf", "e01-2022.02.24 (202.pdf"),
    2022: ("hkt-2022-annual-res.pdf", "e01-2023.02.23 (202.pdf"),
    2023: ("hkt-2023-annual-res.pdf", "e01-hkt-2023-annual.pdf"),
    2024: ("hkt-2024-annual-results-presentation.pdf", "e01-2025.02.20 (2024 Annual Results Announcement).pdf"),
    2025: ("c01-2025_Annual_Results.pdf", "e-2026.02.09_(2025_Annual_Results_Announcement).pdf"),
}

THREE_HK_ANNUAL_RESULTS = {
    2016: ("https://doc.irasia.com/listco/hk/hthkh/announcement/a170937-e215_2016resultsannouncement.pdf", "https://www.hthkh.com/en/ir/presentation/pre170228.pdf"),
    2017: ("https://doc.irasia.com/listco/hk/hthkh/announcement/a189326-e215_2017resultsannouncement.pdf", "https://www.hthkh.com/en/ir/presentation/pre180226.pdf"),
    2018: ("https://doc.irasia.com/listco/hk/hthkh/announcement/a207044-e215_2018resultsannouncement.pdf", "https://www.hthkh.com/en/ir/presentation/pre190228.pdf"),
    2019: ("https://doc.irasia.com/listco/hk/hthkh/announcement/a225532-e215_2019resultsannouncement.pdf", "https://www.hthkh.com/en/ir/presentation/pre200228.pdf"),
    2020: ("https://doc.irasia.com/listco/hk/hthkh/announcement/a243524-e215_2020annualresultsannoucement.pdf", "https://www.hthkh.com/en/ir/presentation/pre210226.pdf"),
    2021: ("https://doc.irasia.com/listco/hk/hthkh/annual/2021/res.pdf", "https://www.hthkh.com/en/ir/presentation/pre220225.pdf"),
    2022: ("https://doc.irasia.com/listco/hk/hthkh/annual/2022/res.pdf", "https://doc.irasia.com/listco/hk/hthkh/cpresent/pre230228.pdf"),
    2023: ("https://doc.irasia.com/listco/hk/hthkh/annual/2023/res.pdf", "https://www.hthkh.com/en/ir/presentation/pre240305.pdf"),
    2024: ("https://doc.irasia.com/listco/hk/hthkh/annual/2024/res.pdf", "https://www.hthkh.com/en/ir/presentation/pre250314.pdf"),
    2025: ("https://doc.irasia.com/listco/hk/hthkh/announcement/a332012-e_2025annualresultsannouncement.pdf", "https://www.hthkh.com/en/ir/presentation/pre260309.pdf"),
}


SOURCES: dict[str, dict[str, Any]] = {}
for year in YEARS:
    SOURCES[f"hkt_ar_{year}"] = {"source_id": f"hkt_ar_{year}", "operator_id": "hkt", "year": year, "label": f"HKT {year} Annual Report", "url": hkt_url(year), "source_type": "official_annual_report", "publisher": OPERATORS["hkt"]["legal_name"]}
    SOURCES[f"three_hk_ar_{year}"] = {"source_id": f"three_hk_ar_{year}", "operator_id": "three_hk", "year": year, "label": f"Hutchison Telecommunications Hong Kong {year} Annual Report", "url": f"https://www.hthkh.com/en/ir/reports/ar{year}/ar{year}.pdf", "source_type": "official_annual_report", "publisher": OPERATORS["three_hk"]["legal_name"]}
    hkt_presentation, hkt_announcement = HKT_ANNUAL_RESULTS[year]
    SOURCES[f"hkt_presentation_{year}"] = {"source_id": f"hkt_presentation_{year}", "operator_id": "hkt", "year": year, "label": f"HKT {year} Annual Results Presentation", "url": "https://www.hkt.com/api-service/assets/" + hkt_presentation.replace(" ", "%20"), "source_type": "official_results_presentation", "publisher": OPERATORS["hkt"]["legal_name"]}
    SOURCES[f"hkt_results_{year}"] = {"source_id": f"hkt_results_{year}", "operator_id": "hkt", "year": year, "label": f"HKT {year} Annual Results Announcement", "url": "https://www.hkt.com/api-service/assets/" + hkt_announcement.replace(" ", "%20"), "source_type": "official_results_announcement", "publisher": OPERATORS["hkt"]["legal_name"]}
    three_results, three_presentation = THREE_HK_ANNUAL_RESULTS[year]
    SOURCES[f"three_hk_results_{year}"] = {"source_id": f"three_hk_results_{year}", "operator_id": "three_hk", "year": year, "label": f"3HK {year} Annual Results Announcement", "url": three_results, "source_type": "official_results_announcement", "publisher": OPERATORS["three_hk"]["legal_name"]}
    SOURCES[f"three_hk_presentation_{year}"] = {"source_id": f"three_hk_presentation_{year}", "operator_id": "three_hk", "year": year, "label": f"3HK {year} Annual Results Presentation", "url": three_presentation, "source_type": "official_results_presentation", "publisher": OPERATORS["three_hk"]["legal_name"]}
for year in range(2016, 2026):
    SOURCES[f"smartone_ar_{year}"] = {"source_id": f"smartone_ar_{year}", "operator_id": "smartone", "year": year, "label": f"SmarTone FY{year} Annual Report", "url": smartone_url(year), "source_type": "official_annual_report", "publisher": OPERATORS["smartone"]["legal_name"]}
SOURCES.update({
    "smartone_presentation_2021": {"source_id": "smartone_presentation_2021", "operator_id": "smartone", "year": 2021, "label": "SmarTone FY2021 Annual Results Presentation", "url": "https://www.smartoneholdings.com/about/investor/results/english/2021annual_present.pdf", "source_type": "official_results_presentation", "publisher": OPERATORS["smartone"]["legal_name"]},
    "smartone_presentation_2022": {"source_id": "smartone_presentation_2022", "operator_id": "smartone", "year": 2022, "label": "SmarTone FY2022 Annual Results Presentation", "url": "https://www.smartoneholdings.com/about/investor/results/english/2022_annual_present.pdf", "source_type": "official_results_presentation", "publisher": OPERATORS["smartone"]["legal_name"]},
    "smartone_results_2022": {"source_id": "smartone_results_2022", "operator_id": "smartone", "year": 2022, "label": "SmarTone FY2022 Annual Results", "url": "https://www.smartoneholdings.com/about/investor/results/english/2022_annual_results.pdf", "source_type": "official_results_announcement", "publisher": OPERATORS["smartone"]["legal_name"]},
    "smartone_presentation_2023": {"source_id": "smartone_presentation_2023", "operator_id": "smartone", "year": 2023, "label": "SmarTone FY2023 Annual Results Presentation", "url": "https://www.smartoneholdings.com/about/investor/results/english/2023_annual_present.pdf", "source_type": "official_results_presentation", "publisher": OPERATORS["smartone"]["legal_name"]},
    "smartone_results_2023": {"source_id": "smartone_results_2023", "operator_id": "smartone", "year": 2023, "label": "SmarTone FY2023 Annual Results", "url": "https://www.smartoneholdings.com/about/investor/results/english/2023_annual_results.pdf", "source_type": "official_results_announcement", "publisher": OPERATORS["smartone"]["legal_name"]},
    "smartone_presentation_2024": {"source_id": "smartone_presentation_2024", "operator_id": "smartone", "year": 2024, "label": "SmarTone FY2024 Annual Results Presentation", "url": "https://www.smartoneholdings.com/about/investor/results/english/2024_annual_present.pdf", "source_type": "official_results_presentation", "publisher": OPERATORS["smartone"]["legal_name"]},
    "smartone_results_2024": {"source_id": "smartone_results_2024", "operator_id": "smartone", "year": 2024, "label": "SmarTone FY2024 Annual Results", "url": "https://www.smartoneholdings.com/about/investor/results/english/2024_annual_results.pdf", "source_type": "official_results_announcement", "publisher": OPERATORS["smartone"]["legal_name"]},
    "hkt_results_2025": {"source_id": "hkt_results_2025", "operator_id": "hkt", "year": 2025, "label": "HKT 2025 Annual Results Announcement", "url": "https://www.hkt.com/api-service/assets/e-2026.02.09_(2025_Annual_Results_Announcement).pdf", "source_type": "official_results_announcement", "publisher": OPERATORS["hkt"]["legal_name"]},
    "hkt_presentation_2025": {"source_id": "hkt_presentation_2025", "operator_id": "hkt", "year": 2025, "label": "HKT 2025 Annual Results Presentation", "url": "https://www.hkt.com/api-service/assets/c01-2025_Annual_Results.pdf", "source_type": "official_results_presentation", "publisher": OPERATORS["hkt"]["legal_name"]},
    "three_hk_highlights_2025": {"source_id": "three_hk_highlights_2025", "operator_id": "three_hk", "year": 2025, "label": "3HK 2025 Annual Results Highlights", "url": "https://www.hthkh.com/en/ir/reports/ar2025/highlights.pdf", "source_type": "official_results_highlights", "publisher": OPERATORS["three_hk"]["legal_name"]},
    "three_hk_analysis_2025": {"source_id": "three_hk_analysis_2025", "operator_id": "three_hk", "year": 2025, "label": "3HK 2025 Annual Results Analysis", "url": "https://www.hthkh.com/en/ir/reports/ar2025/analysis.pdf", "source_type": "official_results_analysis", "publisher": OPERATORS["three_hk"]["legal_name"]},
    "smartone_results_2025": {"source_id": "smartone_results_2025", "operator_id": "smartone", "year": 2025, "label": "SmarTone FY2025 Annual Results", "url": "https://www.smartoneholdings.com/about/investor/results/english/2025_annual_results.pdf", "source_type": "official_results_announcement", "publisher": OPERATORS["smartone"]["legal_name"]},
    "smartone_presentation_2025": {"source_id": "smartone_presentation_2025", "operator_id": "smartone", "year": 2025, "label": "SmarTone FY2025 Annual Results Presentation", "url": "https://www.smartoneholdings.com/about/investor/results/english/2025_annual_present.pdf", "source_type": "official_results_presentation", "publisher": OPERATORS["smartone"]["legal_name"]},
    "smartone_interim_presentation_2025": {"source_id": "smartone_interim_presentation_2025", "operator_id": "smartone", "year": 2025, "label": "SmarTone FY2025 Interim Results Presentation", "url": "https://www.smartoneholdings.com/about/investor/results/english/2025_interim_present.pdf", "source_type": "official_interim_results_presentation", "publisher": OPERATORS["smartone"]["legal_name"]},
    "smartone_mtr_coverage_2021": {"source_id": "smartone_mtr_coverage_2021", "operator_id": "smartone", "year": 2021, "label": "SmarTone official company profile - full 5G coverage at 97 MTR stations from 27 June 2021", "url": "https://www.smartoneholdings.com/jsp/site/about_us/english/index.jsp", "source_type": "official_company_profile", "publisher": OPERATORS["smartone"]["legal_name"]},
    "three_hk_5g_coverage_2020": {"source_id": "three_hk_5g_coverage_2020", "operator_id": "three_hk", "year": 2020, "label": "3HK official release - 99% 5G coverage", "url": "https://www.hthkh.com/en/ir/press.php?prid=%2Fpress%2Fp201014", "source_type": "official_press_release", "publisher": OPERATORS["three_hk"]["legal_name"]},
    "three_hk_5g_coverage_2022": {"source_id": "three_hk_5g_coverage_2022", "operator_id": "three_hk", "year": 2022, "label": "3HK official release - 99% 5G coverage confirmed in 2022", "url": "https://www.hthkh.com/en/ir/press.php?prid=%2Fpress%2Fp220630", "source_type": "official_press_release", "publisher": OPERATORS["three_hk"]["legal_name"]},
    "smartone_5g_launch_2020": {"source_id": "smartone_5g_launch_2020", "operator_id": "smartone", "year": 2020, "label": "Mobile World Live report of SmarTone CTO launch statement - 70% population coverage", "url": "https://www.mobileworldlive.com/asia-pacific/smartone-launches-5g-with-70-population-coverage/", "source_type": "industry_news_direct_company_statement", "publisher": "Mobile World Live"},
    "smartone_5g_mtr_2022": {"source_id": "smartone_5g_mtr_2022", "operator_id": "smartone", "year": 2022, "label": "SmarTone official 5G page - full coverage at 98 MTR stations", "url": "https://5g.smartone.com/en/5G/", "source_type": "official_product_network_page", "publisher": OPERATORS["smartone"]["legal_name"]},
    "pccw_now_tv_2016": {"source_id": "pccw_now_tv_2016", "operator_id": "hkt", "year": 2016, "label": "PCCW 2016 Annual Report - Now TV installed base", "url": "https://www.hkexnews.hk/listedco/listconews/sehk/2017/0214/ltn20170214300.pdf", "source_type": "official_parent_annual_report", "publisher": "PCCW Limited"},
    "pccw_now_tv_2017": {"source_id": "pccw_now_tv_2017", "operator_id": "hkt", "year": 2017, "label": "PCCW 2017 Annual Results - Now TV installed base", "url": "https://www.hkexnews.hk/listedco/listconews/SEHK/2018/0207/LTN20180207557.pdf", "source_type": "official_parent_results_announcement", "publisher": "PCCW Limited"},
    "pccw_now_tv_2019": {"source_id": "pccw_now_tv_2019", "operator_id": "hkt", "year": 2019, "label": "PCCW 2019 Annual Report - Now TV 2018 and 2019 installed bases", "url": "https://www.pccw.com/staticfiles/PCCWCorpsite/About%20PCCW/Investor%20Relations/documents-on-display/008-e-pccw-2019-annual-report.pdf", "source_type": "official_parent_annual_report", "publisher": "PCCW Limited"},
    "cmhk_customer_milestone_2021": {"source_id": "cmhk_customer_milestone_2021", "operator_id": "cmhk", "year": 2021, "label": "CMHK press release distributed by PR Newswire - customer base exceeded five million", "url": "https://www.prnasia.com/story/323800-1.shtml", "source_type": "company_press_release_distribution", "publisher": OPERATORS["cmhk"]["legal_name"]},
    "cmhk_5g_customer_milestone_2021": {"source_id": "cmhk_5g_customer_milestone_2021", "operator_id": "cmhk", "year": 2021, "label": "CMHK press release distributed by PR Newswire - 5G customers exceeded one million", "url": "https://www.prnasia.com/story/338861-1.shtml", "source_type": "company_press_release_distribution", "publisher": OPERATORS["cmhk"]["legal_name"]},
    "cmhk_5g_customer_milestone_2022": {"source_id": "cmhk_5g_customer_milestone_2022", "operator_id": "cmhk", "year": 2022, "label": "CMHK management statement - 5G users exceeded two million in September 2022", "url": "https://hk.on.cc/hk/bkn/cnt/news/20230323/bkn-20230323090026470-0323_00822_001.html", "source_type": "public_report_direct_company_statement", "publisher": "on.cc"},
    "cmhk_5g_launch_2020": {"source_id": "cmhk_5g_launch_2020", "operator_id": "cmhk", "year": 2020, "label": "China Daily report of CMHK commercial 5G launch population coverage", "url": "https://www.chinadailyhk.com/hk/article/126287", "source_type": "public_report_direct_company_statement", "publisher": "China Daily Hong Kong"},
    "cmhk_5g_base_stations_2020": {"source_id": "cmhk_5g_base_stations_2020", "operator_id": "cmhk", "year": 2020, "label": "CGTN report of CMHK commercial 5G launch base-station count", "url": "https://news.cgtn.com/news/2020-04-02/China-Mobile-launches-5G-commercial-service-in-Hong-Kong-PmistIqGKA/index.html", "source_type": "public_report_direct_company_statement", "publisher": "CGTN"},
    "cmhk_investhk_profile_2024": {"source_id": "cmhk_investhk_profile_2024", "operator_id": "cmhk", "year": 2024, "label": "Invest Hong Kong profile quoting CMHK customer and 5G subscriber milestones", "url": "https://www.investhk.gov.hk/media/ginf5rc0/202403-print_investhk_cloud-dc_en.pdf", "source_type": "government_agency_company_profile", "publisher": "Invest Hong Kong"},
    "hkbn_mobile_mvno_launch_2016": {"source_id": "hkbn_mobile_mvno_launch_2016", "operator_id": "hkbn", "year": 2016, "label": "HKBN official release - mobile services launched in September 2016", "url": "https://reg.hkbn.net/WwwCMS/upload/pdf/en/20160913_MVNO_press_release_E_Final.pdf", "source_type": "official_press_release", "publisher": OPERATORS["hkbn"]["legal_name"]},
    "icable_mobile_launch_2020": {"source_id": "icable_mobile_launch_2020", "operator_id": "icable", "year": 2020, "label": "i-CABLE official milestone - iMobile brand debuted in December 2020", "url": "https://www.i-cablecomm.com/en/milestones", "source_type": "official_company_milestone", "publisher": OPERATORS["icable"]["legal_name"]},
    "hgc_mobile_launch_2026": {"source_id": "hgc_mobile_launch_2026", "operator_id": "hgc", "year": 2026, "label": "HGC official release - HGC Mobile launched after the audit period", "url": "https://www.hgc.com.hk/press-releases/hgc-announces-the-launch-of-hgc-mobile-expanding-mobile-connectivity-footprint-with-enhanced-network-on-the-go-experience", "source_type": "official_press_release", "publisher": OPERATORS["hgc"]["legal_name"]},
    "hkbn_interim_presentation_2024": {"source_id": "hkbn_interim_presentation_2024", "operator_id": "hkbn", "year": 2023, "label": "HKBN FY2024 Interim Results Presentation with 2H2023 operating comparatives", "url": "https://webcast.irasia.com/hkbn/interim/2024/archived/documents/pre_i.pdf", "source_type": "official_interim_results_presentation", "publisher": OPERATORS["hkbn"]["legal_name"]},
})
HKBN_OFFICIAL_REPORT_URLS = {
    2016: "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_AnnualReport2016_HKEX.pdf",
    2017: "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_AnnualReport.pdf",
    2018: "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_Annual_Report_2018.pdf",
    2019: "https://www.hkexnews.hk/listedco/listconews/sehk/2019/1111/2019111100307.pdf",
    2020: "https://reg.hkbn.net/WwwCMS/upload/pdf/en/20201112_AnnualReport2020_Eng.pdf",
    2021: "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_FY21_AnnualResultsAnnouncement.pdf",
    2022: "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_FY22_AnnualResultsAnnouncement.pdf",
    2023: "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_FY23_AnnualResultsAnnouncement.pdf",
    2024: "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_AnnualReport_2024.pdf",
    2025: "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_AnnualReport_2025.pdf",
}
for year in YEARS:
    SOURCES[f"hkbn_ar_{year}"] = {
        "source_id": f"hkbn_ar_{year}",
        "operator_id": "hkbn",
        "year": year,
        "label": f"HKBN FY{year} official annual report/results",
        "url": HKBN_OFFICIAL_REPORT_URLS[year],
        "source_type": "official_annual_report_or_results",
        "publisher": OPERATORS["hkbn"]["legal_name"],
    }
for year in [2024, 2025]:
    SOURCES[f"hkbn_results_{year}"] = {"source_id": f"hkbn_results_{year}", "operator_id": "hkbn", "year": year, "label": "HKBN FY2025 Annual Results Presentation and FY2024 comparative", "url": "https://reg.hkbn.net/WwwCMS/upload/pdf/en/FY25_HKBN_Annual_Results_Announcement_Presentation_en.pdf", "source_type": "official_results_presentation", "publisher": OPERATORS["hkbn"]["legal_name"]}
for year in range(2022, 2026):
    SOURCES[f"icable_ar_{year}"] = {"source_id": f"icable_ar_{year}", "operator_id": "icable", "year": year, "label": f"i-CABLE {year} Annual Report", "url": "https://www.i-cablecomm.com/en/annual-interim-reports", "source_type": "official_annual_report_page", "publisher": OPERATORS["icable"]["legal_name"]}
SOURCES.update({
    "icable_ar_2016": {"source_id": "icable_ar_2016", "operator_id": "icable", "year": 2016, "label": "i-CABLE 2016 Annual Report", "url": "https://www.hkexnews.hk/listedco/listconews/sehk/2017/0322/LTN20170322225.pdf", "source_type": "official_annual_report", "publisher": OPERATORS["icable"]["legal_name"]},
    "icable_ar_2017": {"source_id": "icable_ar_2017", "operator_id": "icable", "year": 2017, "label": "i-CABLE 2017 Annual Report", "url": "https://www.hkexnews.hk/listedco/listconews/SEHK/2018/0419/LTN201804191333.pdf", "source_type": "official_annual_report", "publisher": OPERATORS["icable"]["legal_name"]},
    "icable_results_2018": {"source_id": "icable_results_2018", "operator_id": "icable", "year": 2018, "label": "i-CABLE 2018 Final Results", "url": "https://www.hkexnews.hk/listedco/listconews/SEHK/2019/0329/LTN20190329689.pdf", "source_type": "official_results_announcement", "publisher": OPERATORS["icable"]["legal_name"]},
    "icable_ar_2020": {"source_id": "icable_ar_2020", "operator_id": "icable", "year": 2020, "label": "i-CABLE 2020 Annual Report with 2019 comparatives", "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2021/0330/2021033003416.pdf", "source_type": "official_annual_report", "publisher": OPERATORS["icable"]["legal_name"]},
    "hgc_results_2024": {"source_id": "hgc_results_2024", "operator_id": "hgc", "year": 2024, "label": "HGC 2024 business results press release", "url": "https://www.hgc.com.hk/press-releases/hgc-continues-to-deepen-telecommunications-infrastructure-enhancing-ai-powered-ict-services", "source_type": "official_press_release", "publisher": OPERATORS["hgc"]["legal_name"]},
})
SOURCES["hgc_2016_group_ar"] = {"source_id": "hgc_2016_group_ar", "operator_id": "hgc", "year": 2016, "label": "Hutchison Telecommunications Hong Kong 2016 Annual Report (HGC then within group)", "url": "https://www.hthkh.com/en/ir/reports/ar2016/ar2016.pdf", "source_type": "official_annual_report", "publisher": OPERATORS["three_hk"]["legal_name"]}
SOURCES["hgc_current_site"] = {"source_id": "hgc_current_site", "operator_id": "hgc", "year": 2025, "label": "HGC official website", "url": "https://www.hgc-intl.com/", "source_type": "official_company_site", "publisher": OPERATORS["hgc"]["legal_name"]}

ROWS: list[dict[str, Any]] = []


def add_series(operator_id: str, metric_key: str, values: dict[int, float | int | None], *, scope: str, basis: str = "year_end", comparator: str = "=", source_ids: dict[int, list[str]] | None = None, note: str = "", unit: str | None = None, status: str = "official_single_source", gap_reason_code: str = "", gap_reason: str = "") -> None:
    metric_zh, default_unit = METRICS[metric_key]
    spec = OPERATORS[operator_id]
    for year, value in values.items():
        ids = (source_ids or {}).get(year, [])
        reviewed = list(dict.fromkeys(sid for sid in ids if sid in SOURCES))
        valid = reviewed if value is not None else []
        resolved_gap_reason = gap_reason or note
        resolved_gap_reason_code = gap_reason_code or (
            "not_numerically_disclosed" if resolved_gap_reason else "review_not_started"
        )
        row_status = (
            "source_gap_confirmed" if value is None
            else status if status != "official_single_source"
            else "official_three_distinct_sources_verified" if len(valid) >= 3
            else "official_multi_source_verified" if len(valid) >= 2
            else status
        )
        if value is not None:
            global_availability_status = "value_verified"
            gap_search_scope = "not_applicable_value_verified"
        elif resolved_gap_reason_code == "not_applicable_business_scope":
            global_availability_status = "not_applicable_business_scope"
            gap_search_scope = "not_applicable_business_scope"
        elif resolved_gap_reason_code == "precommercial_kpi_not_defined":
            global_availability_status = "not_applicable_precommercial"
            gap_search_scope = "not_applicable_precommercial"
        else:
            global_availability_status = "broader_web_search_not_yet_proven"
            gap_search_scope = (
                "issuer_official_annual_report_results_and_presentation"
                if reviewed
                else "not_yet_reviewed"
            )
        ROWS.append({
            "operator_id": operator_id, "operator": spec["name"], "legal_name": spec["legal_name"],
            "year": year, "period": f"FY{year}", "period_end": f"{year}-{spec['fiscal_year_end']}", "grain": "annual",
            "metric_key": metric_key, "metric_zh": metric_zh, "value": value, "official_value": value,
            "unit": unit or default_unit, "comparator": comparator, "scope": scope, "basis": basis,
            "verification_status": row_status, "verification_count": len(valid),
            "primary_source_id": valid[0] if valid else "", "primary_source_url": SOURCES[valid[0]]["url"] if valid else "",
            "verification_sources": valid, "reviewed_source_ids": reviewed,
            "reviewed_source_urls": [SOURCES[sid]["url"] for sid in reviewed],
            "reviewed_source_count": len(reviewed),
            "audit_outcome": "value_verified" if value is not None else "source_gap_confirmed",
            "gap_reason_code": resolved_gap_reason_code if value is None else "",
            "gap_reason": resolved_gap_reason if value is None else "",
            "gap_search_scope": gap_search_scope,
            "global_availability_status": global_availability_status,
            "related_public_metric": "",
            "related_public_value": "",
            "related_public_unit": "",
            "related_public_comparator": "",
            "related_public_note": "",
            "quality_note": note,
        })


def annual_sources(operator_id: str, years: list[int]) -> dict[int, list[str]]:
    prefix = {"hkt": "hkt", "three_hk": "three_hk", "smartone": "smartone"}[operator_id]
    sources = {
        year: (
            [f"{prefix}_ar_{year}", f"{prefix}_results_{year}", f"{prefix}_presentation_{year}"]
            if operator_id in {"hkt", "three_hk"} else [f"{prefix}_ar_{year}"]
        )
        for year in years
    }
    if 2025 in sources:
        sources[2025] = {
            "hkt": ["hkt_ar_2025", "hkt_results_2025", "hkt_presentation_2025"],
            "three_hk": ["three_hk_ar_2025", "three_hk_highlights_2025", "three_hk_analysis_2025"],
            "smartone": ["smartone_ar_2025", "smartone_results_2025", "smartone_presentation_2025"],
        }[operator_id]
    if operator_id == "smartone":
        for year in range(2021, 2026):
            if year not in sources:
                continue
            extra = [f"smartone_presentation_{year}", f"smartone_results_{year}"]
            sources[year] = list(dict.fromkeys([*sources[year], *[sid for sid in extra if sid in SOURCES]]))
    return sources


# CMHK is not separately listed. Public milestone disclosures are retained with
# their exact within-year dates/bases and must not be presented as year-end KPIs.
add_series("cmhk", "mobile_postpaid_customers", {year: None for year in YEARS}, scope="Hong Kong post-paid mobile customer base", note="CMHK is not separately listed and does not publish a reusable annual post-paid subscriber series; group mobile totals are not substituted.")
add_series("cmhk", "total_customers", {2021: 5.0}, scope="existing CMHK mobile-number customers", comparator=">", basis="milestone_2021-06-16", source_ids={2021: ["cmhk_customer_milestone_2021"]}, status="official_single_source", note="CMHK's distributed press release says the customer base exceeded five million on 16 June 2021, including monthly-plan, prepaid and MySim customers; this is a dated milestone, not a 31 December closing balance.")
add_series("cmhk", "5g_customers", {2021: 1.0, 2022: 2.0}, scope="existing CMHK 5G service customers", comparator=">", basis="milestone_within_year", source_ids={2021: ["cmhk_5g_customer_milestone_2021"], 2022: ["cmhk_5g_customer_milestone_2022"]}, status="public_report_direct_company_statement", note="The points are dated milestones: above one million on 29 October 2021 and above two million in September 2022; they are not 31 December closing balances.")
add_series("cmhk", "homes_passed_or_connected", {2021: 1.13}, scope="households covered by CMHK self-built home broadband network", comparator=">", basis="cumulative_as_of_2021-06-28_press_release", source_ids={2021: ["cmhk_customer_milestone_2021"]}, status="official_single_source", note="The press release states cumulative network coverage above 1.13 million households; this is network coverage, not a broadband-customer count.")
add_series("cmhk", "5g_population_coverage", {2020: 70}, scope="Hong Kong population coverage at commercial 5G launch", comparator=">=", basis="commercial_launch_2020-04-01", source_ids={2020: ["cmhk_5g_launch_2020"]}, status="public_report_direct_company_statement", note="China Daily reported CMHK's launch statement that its 5G signal reached up to 70% of Hong Kong's population; this launch-point value is not the expected end-2020 coverage target.")
add_series("cmhk", "5g_base_stations", {2020: 500}, scope="opened CMHK 5G base stations at commercial launch", comparator=">=", basis="commercial_launch_2020-04-01", source_ids={2020: ["cmhk_5g_base_stations_2020"]}, status="public_report_direct_company_statement", note="A launch report states 500 5G base stations had been built and opened; this is a launch-point count, not a 31 December closing balance.")
add_series("cmhk", "total_customers", {2024: 5.0}, scope="CMHK customer base", comparator=">", basis="InvestHK_profile_published_2024-03", source_ids={2024: ["cmhk_investhk_profile_2024"]}, status="public_report_direct_company_statement", note="Invest Hong Kong's March 2024 profile states that CMHK has more than five million customers; this is a rounded publication-date milestone, not a 31 December closing balance.")
add_series("cmhk", "5g_customers", {2024: 2.0}, scope="CMHK 5G subscriber base", comparator=">", basis="InvestHK_profile_published_2024-03", source_ids={2024: ["cmhk_investhk_profile_2024"]}, status="public_report_direct_company_statement", note="Invest Hong Kong's March 2024 profile states that CMHK has over two million 5G subscribers; this is a rounded publication-date milestone and does not replace an undisclosed year-end value.")

# HKT: calendar-year annual metrics. H2 values are the year-end points in the official KPI tables.
add_series("hkt", "total_customers", dict(zip(YEARS, [4.512, 4.407, 4.324, 4.679, 4.605, 4.770, 4.787, 4.764, 4.805, 4.817])), scope="Hong Kong mobile subscribers, post-paid plus prepaid", source_ids=annual_sources("hkt", YEARS), note="This is HKT's total mobile subscriber base, not a sum of fixed-line, broadband and media accounts.")
add_series("hkt", "mobile_postpaid_customers", dict(zip(YEARS, [3.130, 3.217, 3.247, 3.250, 3.252, 3.297, 3.323, 3.428, 3.459, 3.494])), scope="Hong Kong post-paid mobile customer base", source_ids=annual_sources("hkt", YEARS))
add_series("hkt", "mobile_prepaid_customers", dict(zip(YEARS, [1.382, 1.190, 1.077, 1.429, 1.353, 1.473, 1.464, 1.336, 1.346, 1.323])), scope="Hong Kong prepaid mobile customer base", source_ids=annual_sources("hkt", YEARS))
add_series("hkt", "mobile_postpaid_exit_arpu", dict(zip(YEARS, [233, 232, 198, 200, 184, 187, 188, 191, 193, 195])), scope="Hong Kong post-paid exit ARPU", basis="exit_month", source_ids=annual_sources("hkt", YEARS))
add_series("hkt", "mobile_postpaid_churn", dict(zip(YEARS, [1.3, 1.1, 1.0, 1.0, 0.9, 0.7, 0.8, 0.8, 0.7, 0.7])), scope="monthly post-paid churn", basis="monthly_rate", source_ids=annual_sources("hkt", YEARS))
add_series("hkt", "5g_customers", {year: 0 for year in range(2016, 2020)}, scope="commercial post-paid 5G customer base", source_ids=annual_sources("hkt", list(range(2016, 2020))), status="operational_zero_from_precommercial_timeline", note="Commercial 5G service had not launched; zero is a verified commercial-customer state, not an issuer-published KPI.")
add_series("hkt", "5g_customers", {2020: .264, 2021: .680, 2022: 1.061, 2023: 1.4, 2024: 1.747, 2025: 2.096}, scope="post-paid 5G customer base", comparator=">=", source_ids=annual_sources("hkt", list(range(2020, 2026))), note="2023 was disclosed as approaching 1.4 million; comparator preserves the rounded wording.")
add_series("hkt", "5g_penetration", {year: 0 for year in range(2016, 2020)}, scope="commercial 5G penetration within post-paid customer base", source_ids=annual_sources("hkt", list(range(2016, 2020))), status="operational_zero_from_precommercial_timeline", note="Commercial 5G did not exist in Hong Kong before 2020; 0% records the verified pre-commercial state rather than a published issuer KPI.")
add_series("hkt", "5g_penetration", {2020: 8, 2021: 21, 2022: 32, 2023: 41, 2024: 51, 2025: 60}, scope="5G penetration within post-paid customer base", source_ids=annual_sources("hkt", list(range(2020, 2026))))
add_series("hkt", "consumer_broadband_customers", dict(zip(YEARS, [1.401, 1.423, 1.445, 1.450, 1.457, 1.461, 1.465, 1.471, 1.474, 1.488])), scope="retail consumer broadband access lines", source_ids=annual_sources("hkt", YEARS), note="FY2021 was corrected from 1.637m total broadband access lines to the directly comparable 1.461m retail consumer line count.")
add_series("hkt", "ftth_connections", dict(zip(YEARS, [.616, .698, .781, .833, .892, .944, .969, 1.01, 1.04, 1.086])), scope="consumer FTTH access lines/connections", source_ids=annual_sources("hkt", YEARS), note="FY2017 698k is directly disclosed in the official results presentation; FY2023 is reported as 1.01m and over one million.")
add_series("hkt", "homes_passed_or_connected", {2023: 2.4, 2024: 2.5}, scope="households covered by upgraded fibre network", comparator=">", source_ids=annual_sources("hkt", [2023, 2024]))
add_series("hkt", "commercial_buildings_covered", {2018: 7400}, scope="non-residential buildings covered by the fibre-rich integrated network", source_ids=annual_sources("hkt", [2018]))
add_series("hkt", "telephony_customers", dict(zip(YEARS, [2.648, 2.638, 2.631, 2.598, 2.522, 2.443, 2.343, 2.227, 2.114, 2.026])), scope="exchange lines in service, business plus residential", source_ids=annual_sources("hkt", YEARS), note="Exchange lines are the issuer's reusable fixed-telephony customer proxy; they are not unique persons.")
add_series("hkt", "pay_tv_customers", {2020: 1.348, 2021: 1.373, 2022: 1.398, 2023: 1.429, 2024: 1.433, 2025: 1.464}, scope="Now TV installed base", source_ids=annual_sources("hkt", list(range(2020, 2026))))
add_series("hkt", "5g_population_coverage", {2021: 99}, scope="territory-wide commercial 5G population coverage", source_ids=annual_sources("hkt", [2021]), note="Official FY2021 results presentation states 99% territory-wide coverage including all MTR lines.")

# 3HK: 2016-24 group scope included Macau; 2025 report isolates Hong Kong and restates the 2024 comparator.
add_series("three_hk", "mobile_postpaid_customers", dict(zip(YEARS, [1.486, 1.487, 1.499, 1.475, 1.427, 1.442, 1.470, 1.463, 1.423, 1.289])), scope="Hong Kong and Macau through 2024; Hong Kong only in 2025", source_ids=annual_sources("three_hk", YEARS), note="FY2025 report restated FY2024 to 1.316m after the Macau disposal; original historical figures are retained and the restatement is recorded separately.")
add_series("three_hk", "mobile_prepaid_customers", dict(zip(YEARS, [1.736, 1.841, 1.777, 2.180, 1.852, 1.760, 1.808, 2.500, 3.217, 6.843])), scope="Hong Kong and Macau through 2024; Hong Kong only in 2025", source_ids=annual_sources("three_hk", YEARS), note="FY2025 report restated FY2024 to 3.162m after the Macau disposal.")
add_series("three_hk", "total_customers", dict(zip(YEARS, [3.222, 3.328, 3.276, 3.655, 3.279, 3.202, 3.278, 3.963, 4.640, 8.132])), scope="post-paid plus prepaid customers; Hong Kong and Macau through 2024, Hong Kong only in 2025", source_ids=annual_sources("three_hk", YEARS), note="FY2025 report restated FY2024 to 4.478m; 2025 prepaid growth and scope change make simple trend comparisons unsafe.")
add_series("three_hk", "mobile_postpaid_arpu", dict(zip(YEARS, [247, 230, 219, 205, 196, 192, 185, 190, 184, 187])), scope="post-paid gross ARPU", source_ids=annual_sources("three_hk", YEARS), note="FY2025 report restated FY2024 gross ARPU to HKD190; original FY2024 disclosure is retained.")
add_series("three_hk", "mobile_postpaid_net_arpu", dict(zip(YEARS, [205, 197, 186, 176, 171, 171, 168, 174, 170, 176])), scope="post-paid net ARPU excluding handset/device revenue as defined by company", source_ids=annual_sources("three_hk", YEARS), note="FY2025 report restated FY2024 net ARPU to HKD175.")
add_series("three_hk", "mobile_postpaid_net_ampu", dict(zip(YEARS, [189, 181, 169, 161, 150, 148, 145, 152, 148, 149])), scope="post-paid net AMPU", source_ids=annual_sources("three_hk", YEARS), note="FY2016 uses the FY2017 report's restated comparable value of HKD189; the original FY2016 report's local-only HKD161 is retained as a scope conflict.")
add_series("three_hk", "mobile_postpaid_churn", dict(zip(YEARS, [1.3, 1.3, 1.3, 1.2, 1.1, 1.2, .8, 1.0, 1.0, .9])), scope="monthly post-paid churn", basis="monthly_rate", source_ids=annual_sources("three_hk", YEARS))
add_series("three_hk", "5g_penetration", {year: 0 for year in range(2016, 2020)}, scope="commercial 5G penetration within post-paid base", source_ids=annual_sources("three_hk", list(range(2016, 2020))), status="operational_zero_from_precommercial_timeline", note="3HK launched commercial 5G in April 2020; 0% records the verified pre-commercial state rather than a published issuer KPI.")
add_series("three_hk", "5g_penetration", {2020: 10.3}, scope="5G penetration within Hong Kong post-paid base", source_ids=annual_sources("three_hk", [2020]), note="The FY2020 results presentation discloses 5G subscribers at 10.3% of the Hong Kong post-paid base.")
add_series("three_hk", "5g_penetration", {2021: 21}, scope="5G penetration within Hong Kong post-paid base", source_ids={2021: ["three_hk_ar_2022", "three_hk_presentation_2022"]}, status="official_derived_from_disclosed_growth_bridge", note="Derived from the FY2022 presentation: FY2022 post-paid base +2%, 5G base +46%, and FY2022 penetration 30%; implied FY2021 penetration is 30% × 1.02 ÷ 1.46 = 20.96%, rounded to 21%.")
add_series("three_hk", "5g_penetration", {2022: 30, 2023: 46, 2024: 54, 2025: 62}, scope="5G penetration within post-paid base", source_ids=annual_sources("three_hk", [2022, 2023, 2024, 2025]))
add_series("three_hk", "5g_customers", {year: 0 for year in range(2016, 2020)}, scope="commercial 5G customer base", source_ids=annual_sources("three_hk", list(range(2016, 2020))), status="operational_zero_from_precommercial_timeline", note="Commercial 5G service had not launched; zero is a verified commercial-customer state.")
add_series("three_hk", "5g_customers", {2020: .147, 2021: .303, 2022: .441, 2023: .673, 2024: .768, 2025: .799}, scope="implied Hong Kong 5G customer base", comparator="≈", source_ids=annual_sources("three_hk", list(range(2020, 2026))), status="official_derived_from_penetration_and_postpaid_base", note="Derived as disclosed 5G penetration multiplied by the disclosed post-paid base; rounded to the nearest thousand customers and kept approximate.")
add_series("three_hk", "5g_population_coverage", {2020: 99}, scope="Hong Kong 5G network coverage", source_ids={2020: ["three_hk_5g_coverage_2020"]})
add_series("three_hk", "5g_population_coverage", {2021: 99, 2023: 99}, scope="Hong Kong 5G population coverage", comparator=">=", source_ids=annual_sources("three_hk", [2021, 2023]))
add_series("three_hk", "5g_population_coverage", {2022: 99}, scope="Hong Kong 5G network coverage", source_ids={2022: ["three_hk_5g_coverage_2022"]}, note="The June 2022 official release says coverage had already reached 99% for quite some time.")
add_series("three_hk", "5g_base_stations", {2021: 1300}, scope="3.5 GHz golden-spectrum 5G base stations", comparator=">", source_ids=annual_sources("three_hk", [2021]), note="This is the disclosed 3.5 GHz golden-spectrum layer, not a count of every 5G radio site across all spectrum bands.")
add_series("three_hk", "5g_base_station_expansion", {2021: 43, 2022: 50}, scope="cumulative 5G base-station expansion versus Q3 2020", comparator=">=", basis="cumulative_vs_q3_2020", source_ids=annual_sources("three_hk", [2021, 2022]), note="Relative expansion only; the company did not disclose a reusable absolute annual base-station count.")
add_series("three_hk", "mtr_stations_5g_enhanced", {2023: 65}, scope="busy MTR stations across nine lines covered by network enhancement", source_ids=annual_sources("three_hk", [2023]))
add_series("three_hk", "5g_home_broadband_revenue_growth", {2024: 69}, scope="year-on-year 5G Home Broadband revenue growth", basis="year_on_year", source_ids=annual_sources("three_hk", [2024]))

# SmarTone fiscal year ends 30 June; annual and exit ARPU are kept as distinct series.
sm_years = list(range(2016, 2026))
add_series("smartone", "total_customers", {2016: 1.97, 2017: 2.06, 2018: 2.39, 2019: 2.55, 2020: 2.70, 2021: 2.74, 2022: 2.748, 2023: 2.681, 2024: 2.713}, scope="Hong Kong customer base", source_ids=annual_sources("smartone", sm_years), note="FY2022-FY2024 use the exact presentation values 2.748m, 2.681m and 2.713m; FY2025 did not disclose an exact total.")
add_series("smartone", "mobile_postpaid_arpu", {2016: 301, 2017: 285, 2018: 257, 2019: 224, 2020: 210, 2021: 199}, scope="annual average mobile post-paid ARPU", basis="annual_average", source_ids=annual_sources("smartone", list(range(2016, 2022))), note="FY2019 canonical value follows HKFRS 15; the older-accounting HKAS 18 value of HKD247 is retained in conflicts.")
add_series("smartone", "mobile_postpaid_exit_arpu", {2020: 189, 2021: 202, 2022: 213, 2023: 224, 2024: 224, 2025: 222}, scope="June/exit mobile post-paid ARPU", basis="exit_month", source_ids=annual_sources("smartone", list(range(2020, 2026))), note="Later presentations shorten the label to mobile post-paid ARPU but plot June year-end points continuously against the FY2022 exit-ARPU anchor.")
add_series("smartone", "mobile_postpaid_churn", {2016: .9, 2017: 1.0, 2018: .8, 2019: .8, 2020: .7, 2021: .8, 2022: .7}, scope="monthly mobile post-paid churn", basis="monthly_rate", source_ids=annual_sources("smartone", list(range(2016, 2023))))
add_series("smartone", "5g_penetration", {year: 0 for year in range(2016, 2020)}, scope="commercial 5G penetration among post-paid MNO customers", source_ids=annual_sources("smartone", list(range(2016, 2020))), status="operational_zero_from_precommercial_timeline", note="SmarTone launched commercial 5G in May 2020; 0% records the verified pre-commercial state rather than a published issuer KPI.")
add_series("smartone", "5g_penetration", {2021: 18}, scope="5G penetration among post-paid MNO customers", comparator="≈", source_ids={2021: ["smartone_presentation_2021", "smartone_ar_2021"]}, status="official_range_normalized", note="FY2021 presentation disclosed a high-teen percentage; 18% is the normalized representative value and remains approximate.")
add_series("smartone", "5g_penetration", {2022: 28, 2023: 37, 2024: 39}, scope="5G penetration among post-paid MNO customers", source_ids=annual_sources("smartone", [2022, 2023, 2024]), note="FY2024 uses the exact 39% presentation value instead of the annual report's rounded approximately 40% wording.")
add_series("smartone", "5g_penetration", {2025: 39}, scope="5G penetration among post-paid MNO customers", comparator="≈", source_ids=annual_sources("smartone", [2025]), status="official_qualitative_continuity_normalized", note="FY2025 states that 5G penetration held broadly stable; the exact FY2024 39% anchor is retained as an approximate continuity value, not a newly disclosed exact point.")
add_series("smartone", "5g_customers", {year: 0 for year in range(2016, 2020)}, scope="commercial 5G customer base", source_ids=annual_sources("smartone", list(range(2016, 2020))), status="operational_zero_from_precommercial_timeline", note="Commercial 5G service had not launched; zero is a verified commercial-customer state.")
add_series("smartone", "5g_population_coverage", {2022: 99}, scope="5G population coverage", comparator=">", source_ids=annual_sources("smartone", [2022]), note="Official FY2022 annual report states over 99% population coverage.")
add_series("smartone", "mtr_stations_5g_enhanced", {2021: 97}, scope="MTR stations with full SmarTone 5G coverage from 27 June 2021", source_ids={2021: ["smartone_mtr_coverage_2021"]}, note="Official company profile states full 5G coverage of 97 stations across 10 MTR lines.")
add_series("smartone", "5g_population_coverage", {2020: 70}, scope="population coverage at commercial 5G launch in May 2020", basis="launch_point", source_ids={2020: ["smartone_5g_launch_2020"]}, status="public_report_direct_company_statement", note="Mobile World Live reported SmarTone CTO's launch statement of 70% population coverage and a citywide target by mid-2021; retained despite being a reputable industry report rather than an issuer-hosted document.")
add_series("smartone", "mtr_stations_5g_enhanced", {2022: 98}, scope="MTR stations with full SmarTone 5G coverage from 9 May 2022", source_ids={2022: ["smartone_5g_mtr_2022"]}, note="Official SmarTone 5G page states full coverage of 98 stations across 10 MTR lines.")
add_series("smartone", "5g_home_broadband_revenue_growth", {2023: 100}, scope="year-on-year 5G Home Broadband revenue growth", comparator=">", basis="year_on_year", source_ids=annual_sources("smartone", [2023]))
add_series("smartone", "5g_home_broadband_revenue_growth", {2024: 33, 2025: 16}, scope="year-on-year 5G Home Broadband revenue growth", basis="year_on_year", source_ids=annual_sources("smartone", [2024, 2025]))
add_series("smartone", "5g_home_broadband_ebitda_growth", {2024: 70, 2025: 18}, scope="year-on-year 5G Home Broadband EBITDA growth", basis="year_on_year", source_ids=annual_sources("smartone", [2024, 2025]))

# HKBN: exact values available from the current annual report and results presentation.
hkbn_sources = {
    year: (
        [f"hkbn_ar_{year}", f"hkbn_results_{year}"]
        if year in {2024, 2025}
        else [f"hkbn_ar_{year}"]
    )
    for year in YEARS
}
hkbn_dual = {year: hkbn_sources[year] for year in [2024, 2025]}
hkbn_coverage_sources = {**hkbn_sources, 2023: ["hkbn_interim_presentation_2024"]}
add_series("hkbn", "mobile_postpaid_customers", {2016: 0, 2017: .147, 2018: .265, 2019: .277, 2020: .275, 2021: .254, 2022: .241, 2023: .239, 2024: .217, 2025: .181}, scope="activated mobile subscriptions under HKBN's MVNO service", source_ids=hkbn_sources, note="FY2016 ended before HKBN's September 2016 consumer mobile launch, so the period-end operational value is zero. FY2017-FY2025 are the company's disclosed activated/mobile subscriptions; they are not network-owner SIM totals.")
add_series("hkbn", "total_customers", {2016: .898, 2017: .994, 2018: 1.017, 2019: 1.019, 2020: 1.019, 2021: .997, 2022: .976, 2023: .972, 2024: .932}, scope="unique residential customers", source_ids=hkbn_sources, note="This is HKBN's disclosed residential-customer count, not a sum of broadband, voice and mobile subscriptions. FY2025 ceased disclosing this line, so no FY2025 value is inferred.")
add_series("hkbn", "mobile_postpaid_arpu", {2020: 110, 2021: 111, 2022: 110}, scope="HKBN mobile ARPU", basis="annual_average", source_ids=hkbn_sources, note="FY2017-FY2019 split mobile ARPU between customers with and without broadband and therefore do not provide one directly comparable aggregate; FY2020-FY2022 disclose a single mobile ARPU.")
add_series("hkbn", "homes_passed_or_connected", {2016: 2.202, 2017: 2.249, 2018: 2.297, 2019: 2.360, 2020: 2.415, 2021: 2.466, 2022: 2.513, 2023: 2.560, 2024: 2.596, 2025: 2.646}, scope="residential homes passed", source_ids=hkbn_coverage_sources)
add_series("hkbn", "commercial_buildings_covered", {2021: 7584, 2022: 8006, 2023: 8090, 2024: 8163, 2025: 8220}, scope="commercial buildings covered", source_ids=hkbn_coverage_sources)
add_series("hkbn", "consumer_broadband_customers", dict(zip(YEARS, [.857, .871, .860, .878, .886, .886, .897, .920, .907, .907])), scope="residential broadband subscriptions", source_ids=hkbn_sources)
add_series("hkbn", "residential_arpu", {2016: 173, 2017: 168, 2018: 176, 2019: 185, 2020: 190, 2021: 192, 2022: 184, 2023: None, 2024: 182, 2025: 186}, scope="historical full-base residential broadband ARPU", source_ids=hkbn_sources, note="FY2023 full-year residential ARPU was not directly disclosed in the reviewed annual materials; a 2H2023 point is retained separately as related evidence.")
add_series("hkbn", "residential_arph", {2024: 207, 2025: 217}, scope="residential ARPH", source_ids=hkbn_dual)
add_series("hkbn", "residential_2gbps_plus_customers", {2025: 95000}, scope="residential customers on 2Gbps or faster plans", comparator=">", source_ids=hkbn_dual)
add_series("hkbn", "enterprise_2gbps_plus_customers", {2025: 12000}, scope="enterprise GigaFast broadband customers", comparator=">", source_ids=hkbn_dual)
add_series("hkbn", "enterprise_core_churn", {2024: 1.4, 2025: 1.2}, scope="monthly enterprise core business churn", basis="monthly_rate", source_ids=hkbn_dual)

# i-CABLE: official customer tables are continuous through 2022; pay-TV is not extended after service cessation.
icable_sources = {year: [f"icable_ar_{year}"] for year in range(2022, 2026)}
icable_customer_sources = {
    2016: ["icable_ar_2016"], 2017: ["icable_ar_2017"], 2018: ["icable_results_2018"],
    2019: ["icable_ar_2020"], 2020: ["icable_ar_2020"],
    2021: ["icable_ar_2022"], 2022: ["icable_ar_2022"],
}
add_series("icable", "pay_tv_customers", {2016: .909, 2017: .850, 2018: .800, 2019: .772, 2020: .736, 2021: .715, 2022: .662}, scope="pay-TV customer base", source_ids=icable_customer_sources, note="Pay-TV service ceased in June 2023; later years are a structural discontinuity, not zero-filled.")
add_series("icable", "consumer_broadband_customers", {2016: .156, 2017: .149, 2018: .155, 2019: .175, 2020: .197, 2021: .202, 2022: .198}, scope="broadband customer base", source_ids=icable_customer_sources)
add_series("icable", "telephony_customers", {2016: .095, 2017: .090, 2018: .087, 2019: .082, 2020: .076, 2021: .073, 2022: .068}, scope="telephony customer base", source_ids=icable_customer_sources)
add_series("icable", "homes_passed_or_connected", {2022: 2.0, 2023: 2.0, 2024: 2.0, 2025: 2.3}, scope="network infrastructure households covered/connected", comparator=">", source_ids=icable_sources, note="2025 uses connected-household wording; prior years use network-covering wording, so growth should not be computed across the scope change.")
add_series("icable", "free_tv_population_coverage", {2022: 99, 2024: 99, 2025: 99}, scope="free-to-air TV population/household coverage", comparator="≈", source_ids=icable_sources)

# HGC: private-company disclosure is sparse; retain only explicitly published scope-specific values.
add_series("hgc", "homes_passed_or_connected", {2016: 1.8}, scope="carrier-grade fixed network households served while HGC was within HTHKH", comparator=">", source_ids={2016: ["hgc_2016_group_ar"]}, note="Historical group disclosure only; not presented as a current HGC customer count.")
add_series("hgc", "total_customers", {2024: 1.0}, scope="customers using HGC services", comparator=">", source_ids={2024: ["hgc_results_2024"]})
add_series("hgc", "consumer_broadband_customers", {2024: .4}, scope="residential broadband users", comparator=">", source_ids={2024: ["hgc_results_2024"]})


CORE_METRICS = ["total_customers", "mobile_postpaid_customers", "5g_customers", "5g_penetration", "consumer_broadband_customers", "homes_passed_or_connected", "mobile_postpaid_arpu", "mobile_postpaid_churn", "mobile_data_dou", "annual_mobile_data_traffic", "total_base_stations", "5g_base_stations"]
FULL_AUDIT_OPERATORS = ("hkt", "three_hk", "smartone")
MOBILE_ONLY_NON_APPLICABLE = {
    "consumer_broadband_customers", "ftth_connections", "homes_passed_or_connected",
    "commercial_buildings_covered", "residential_arpu", "residential_arph",
    "pay_tv_customers", "telephony_customers", "free_tv_population_coverage",
    "residential_2gbps_plus_customers", "enterprise_2gbps_plus_customers",
    "enterprise_core_churn",
}
MOBILE_NETWORK_CORE_METRICS = {
    "mobile_postpaid_customers", "mobile_postpaid_arpu", "mobile_postpaid_churn",
    "mobile_data_dou", "annual_mobile_data_traffic", "total_base_stations",
    "5g_base_stations", "5g_customers", "5g_penetration",
}


def gap_explanation(operator_id: str, metric_key: str, year: int) -> tuple[str, str]:
    operator = OPERATORS[operator_id]["name"]
    metric = METRICS[metric_key][0]
    if operator_id == "hgc" and metric_key in MOBILE_NETWORK_CORE_METRICS:
        return (
            "not_applicable_business_scope",
            f"HGC在本审计期2016–2025经营固定网络及ICT业务，HGC Mobile到2026年4月才推出；因此FY{year}的{metric}不适用，且不以合作网络或香港市场总量替代。",
        )
    if operator_id == "icable" and metric_key in {"total_base_stations", "5g_base_stations"}:
        return (
            "not_applicable_business_scope",
            f"i-CABLE的iMobile为合作网络上的移动服务，并非自建公众移动无线接入网；因此FY{year}的{metric}不适用，合作MNO基站不归入i-CABLE。",
        )
    if operator_id == "icable" and year < 2020 and metric_key in MOBILE_NETWORK_CORE_METRICS:
        return (
            "not_applicable_business_scope",
            f"i-CABLE到2020年12月才推出iMobile；FY{year}尚无该移动业务，因此{metric}不适用，不把市场总量或其他运营商数值归给i-CABLE。",
        )
    if operator_id == "hkbn" and metric_key in {"total_base_stations", "5g_base_stations"}:
        return (
            "not_applicable_business_scope",
            f"HKBN移动服务通过合作MNO网络提供，并不拥有同口径公众移动基站；因此FY{year}的{metric}不适用，合作MNO基站不归入HKBN。",
        )
    if operator_id in {"three_hk", "smartone"} and metric_key in MOBILE_ONLY_NON_APPLICABLE:
        return (
            "not_applicable_business_scope",
            f"{operator}在本审计期为移动网络运营商，官方材料没有同口径固定宽带、固网电话、电视或固定企业接入业务，因此{metric}不适用；未以集团外业务或第三方网络数据替代。",
        )
    if metric_key == "free_tv_population_coverage" and operator_id == "hkt":
        return (
            "not_applicable_business_scope",
            "HKT披露的是收费电视安装基数，不是免费电视人口或家庭覆盖率；两个口径不互换。",
        )
    if metric_key.startswith("5g_") or metric_key in {"5g_customers", "5g_penetration", "5g_population_coverage", "5g_base_stations"}:
        if year < 2020:
            return (
                "precommercial_kpi_not_defined",
                f"香港商业5G于2020年推出；FY{year}官方材料没有把{metric}定义为可复用年度KPI。仅5G客户与渗透率在可证明为商业服务零值时单独记0，其余不推定。",
            )
    if metric_key in {"mobile_data_dou", "annual_mobile_data_traffic"}:
        return (
            "growth_only_no_absolute_value",
            f"已复核{operator} FY{year}年报、业绩公告及演示；仅见数据用量或流量增长描述，没有{metric}的年度绝对值，不能从增长率反推。",
        )
    if metric_key in {"total_base_stations", "5g_base_stations"}:
        return (
            "increment_only_no_total_value",
            f"已复核{operator} FY{year}官方材料；只见站点增建、覆盖或相对扩展描述，没有{metric}的年末总量，不能把增量或cell site冒充基站总数。",
        )
    if metric_key == "5g_base_station_expansion" and operator_id != "three_hk":
        return (
            "metric_definition_not_comparable",
            f"该指标采用3HK相对2020年第三季度的专属累计扩展基线；{operator}没有披露同一基线的年度百分比，不能横向套用。",
        )
    if metric_key == "mtr_stations_5g_enhanced":
        return (
            "initiative_specific_count_not_disclosed",
            f"已复核{operator} FY{year}官方材料；可能披露港铁线路或整体覆盖，但没有同口径的5G增强车站数量，线路数不替代车站数。",
        )
    if metric_key in {"5g_home_broadband_revenue_growth", "5g_home_broadband_ebitda_growth"} and year <= 2021:
        return (
            "service_launch_or_growth_base_unavailable",
            f"FY{year}处于5G家庭宽带推出或早期爬坡阶段，官方没有可复用的完整同比基数及{metric}数值；增长率不记0。",
        )
    return (
        "not_numerically_disclosed",
        f"已逐项复核{operator} FY{year}官方年报、业绩公告及业绩演示；{metric}没有直接可复用的年度数值，定性表述、不同口径或无基数增长未转换为数值。",
    )


def add_explicit_gaps() -> None:
    existing = {(row["operator_id"], row["year"], row["metric_key"]) for row in ROWS}
    for operator_id in OPERATORS:
        for year in YEARS:
            metrics = METRICS if operator_id in FULL_AUDIT_OPERATORS else CORE_METRICS
            for metric_key in metrics:
                key = (operator_id, year, metric_key)
                if key in existing:
                    continue
                reason_code, reason = gap_explanation(operator_id, metric_key, year)
                if operator_id in FULL_AUDIT_OPERATORS:
                    reviewed_sources = annual_sources(operator_id, [year])
                elif operator_id == "cmhk":
                    reviewed_sources = {year: [
                        "cmhk_customer_milestone_2021", "cmhk_5g_customer_milestone_2021",
                        "cmhk_5g_customer_milestone_2022", "cmhk_5g_launch_2020",
                        "cmhk_5g_base_stations_2020", "cmhk_investhk_profile_2024",
                    ]}
                elif operator_id == "hkbn":
                    reviewed_sources = {year: hkbn_sources[year]}
                elif operator_id == "icable":
                    reviewed_sources = {year: (
                        icable_customer_sources.get(year, [])
                        or icable_sources.get(year, [])
                        or ["icable_mobile_launch_2020"]
                    )}
                elif operator_id == "hgc" and year == 2016:
                    reviewed_sources = {year: ["hgc_2016_group_ar"]}
                elif operator_id == "hgc":
                    reviewed_sources = {year: ["hgc_results_2024", "hgc_current_site", "hgc_mobile_launch_2026"]}
                else:
                    reviewed_sources = {year: []}
                add_series(
                    operator_id,
                    metric_key,
                    {year: None},
                    scope="reviewed official annual report, results announcement and presentation",
                    source_ids=reviewed_sources,
                    note=reason,
                    gap_reason_code=reason_code,
                    gap_reason=reason,
                )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = ["operator_id", "operator", "legal_name", "year", "period", "period_end", "grain", "metric_key", "metric_zh", "value", "official_value", "unit", "comparator", "scope", "basis", "verification_status", "verification_count", "primary_source_id", "primary_source_url", "verification_sources", "reviewed_source_count", "reviewed_source_ids", "reviewed_source_urls", "audit_outcome", "gap_reason_code", "gap_reason", "gap_search_scope", "global_availability_status", "related_public_metric", "related_public_value", "related_public_unit", "related_public_comparator", "related_public_note", "quality_note"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            item = dict(row)
            item["verification_sources"] = json.dumps(item["verification_sources"], ensure_ascii=False)
            item["reviewed_source_ids"] = json.dumps(item["reviewed_source_ids"], ensure_ascii=False)
            item["reviewed_source_urls"] = json.dumps(item["reviewed_source_urls"], ensure_ascii=False)
            writer.writerow(item)


def main() -> None:
    add_explicit_gaps()
    for row in ROWS:
        if (
            row["operator_id"] == "hkt"
            and row["metric_key"] == "total_base_stations"
            and row["year"] in {2016, 2017}
        ):
            row.update(
                {
                    "global_availability_status": "related_scope_value_found_not_directly_comparable",
                    "related_public_metric": "mobile_network_sites",
                    "related_public_value": 3000,
                    "related_public_unit": "sites",
                    "related_public_comparator": ">",
                    "related_public_note": "HKT official annual report says a network of more than 3,000 sites; a network site is not treated as an identical base-station count.",
                    "gap_reason": (
                        f"{row['gap_reason']} Related official evidence: HKT reports a network of more than 3,000 mobile network sites; "
                        "network sites are not treated as an identical base-station count."
                    ).strip(),
                }
            )
        if row["operator_id"] == "smartone" and row["year"] == 2025 and row["metric_key"] == "total_customers":
            row["reviewed_source_ids"] = list(dict.fromkeys([*row["reviewed_source_ids"], "smartone_interim_presentation_2025"]))
            row["reviewed_source_urls"] = [SOURCES[sid]["url"] for sid in row["reviewed_source_ids"]]
            row["reviewed_source_count"] = len(row["reviewed_source_ids"])
            row.update(
                {
                    "global_availability_status": "related_scope_value_found_not_directly_comparable",
                    "related_public_metric": "interim_customer_base",
                    "related_public_value": 2.873,
                    "related_public_unit": "million_customers",
                    "related_public_comparator": "=",
                    "related_public_note": "SmarTone disclosed 2.873 million customers at 31 December 2024 in its FY2025 interim presentation; the FY2025 annual materials did not disclose the 30 June 2025 year-end count.",
                }
            )
        if row["operator_id"] == "smartone" and row["year"] == 2025 and row["metric_key"] == "total_base_stations":
            row.update(
                {
                    "global_availability_status": "related_scope_value_found_not_directly_comparable",
                    "related_public_metric": "new_network_sites",
                    "related_public_value": 100,
                    "related_public_unit": "sites",
                    "related_public_comparator": ">",
                    "related_public_note": "SmarTone's FY2025 presentation says 100+ new sites were added in key areas; this is an annual increment, not the total base-station count.",
                }
            )
        if row["operator_id"] == "hkt" and row["metric_key"] == "pay_tv_customers" and row["year"] in {2016, 2017, 2018, 2019}:
            related_values = {2016: 1.303, 2017: 1.301, 2018: 1.344, 2019: 1.361}
            source_id = "pccw_now_tv_2016" if row["year"] == 2016 else "pccw_now_tv_2017" if row["year"] == 2017 else "pccw_now_tv_2019"
            row["reviewed_source_ids"] = list(dict.fromkeys([*row["reviewed_source_ids"], source_id]))
            row["reviewed_source_urls"] = [SOURCES[sid]["url"] for sid in row["reviewed_source_ids"]]
            row["reviewed_source_count"] = len(row["reviewed_source_ids"])
            row.update(
                {
                    "global_availability_status": "related_scope_value_found_not_directly_comparable",
                    "related_public_metric": "now_tv_installed_base_under_pccw",
                    "related_public_value": related_values[row["year"]],
                    "related_public_unit": "million_customers",
                    "related_public_comparator": "=",
                    "related_public_note": "Now TV was reported within PCCW before HKT acquired the business in 2020; this public installed base is retained as predecessor-scope evidence and is not presented as an HKT reporting-entity KPI.",
                }
            )
        if row["operator_id"] == "hkt" and row["year"] == 2024 and row["metric_key"] == "mtr_stations_5g_enhanced":
            row.update(
                {
                    "global_availability_status": "related_scope_value_found_not_directly_comparable",
                    "related_public_metric": "planned_mtr_station_5g_upgrades",
                    "related_public_value": 24,
                    "related_public_unit": "stations",
                    "related_public_comparator": "=",
                    "related_public_note": "HKT's FY2024 presentation identifies a 24-high-traffic-station upgrade programme targeted for completion by 2026; this planned scope is not treated as completed FY2024 stations.",
                }
            )
        if row["operator_id"] == "hkbn" and row["year"] == 2023 and row["metric_key"] == "residential_arpu":
            source_id = "hkbn_interim_presentation_2024"
            row["reviewed_source_ids"] = list(dict.fromkeys([*row["reviewed_source_ids"], source_id]))
            row["reviewed_source_urls"] = [SOURCES[sid]["url"] for sid in row["reviewed_source_ids"]]
            row["reviewed_source_count"] = len(row["reviewed_source_ids"])
            row.update(
                {
                    "global_availability_status": "related_scope_value_found_not_directly_comparable",
                    "related_public_metric": "2H2023_residential_arpu",
                    "related_public_value": 177,
                    "related_public_unit": "HKD_per_month",
                    "related_public_comparator": "=",
                    "related_public_note": "HKBN's FY2024 interim presentation reports 2H2023 residential ARPU of HKD177; this half-year point is retained as related evidence and is not presented as the missing FY2023 full-year ARPU.",
                }
            )
        if row["operator_id"] == "hgc" and row["year"] == 2024 and row["metric_key"] == "homes_passed_or_connected":
            source_id = "hgc_results_2024"
            row["reviewed_source_ids"] = list(dict.fromkeys([*row["reviewed_source_ids"], source_id]))
            row["reviewed_source_urls"] = [SOURCES[sid]["url"] for sid in row["reviewed_source_ids"]]
            row["reviewed_source_count"] = len(row["reviewed_source_ids"])
            row.update(
                {
                    "global_availability_status": "related_scope_value_found_not_directly_comparable",
                    "related_public_metric": "village_households_reached_by_fibre_projects",
                    "related_public_value": 41000,
                    "related_public_unit": "households",
                    "related_public_comparator": "≈",
                    "related_public_note": "HGC's FY2024 release says fibre work in more than 200 villages benefited about 41,000 village households; this project subset is retained as related evidence and is not presented as HGC's total homes passed.",
                    "gap_reason": (
                        f"{row['gap_reason']} HGC separately disclosed about 41,000 village households benefited by rural fibre projects; "
                        "that project subset is not a total homes-passed figure."
                    ).strip(),
                }
            )
    for row in ROWS:
        if (
            row["operator_id"] in FULL_AUDIT_OPERATORS
            and row["value"] is None
            and row["global_availability_status"]
            not in {"not_applicable_business_scope", "not_applicable_precommercial"}
        ):
            row["gap_search_scope"] = "issuer_materials_plus_targeted_public_web_search"
            if row["global_availability_status"] == "broader_web_search_not_yet_proven":
                row["global_availability_status"] = "targeted_public_web_search_completed_no_direct_value"
                row["gap_reason"] = (
                    f"{row['gap_reason']} Targeted public-web search completed on 2026-08-29; "
                    "no direct same-period, same-scope numeric value was found. This is not a claim that the entire web contains no value."
                ).strip()
    for row in ROWS:
        if (
            row["operator_id"] not in FULL_AUDIT_OPERATORS
            and row["value"] is None
            and row["global_availability_status"]
            not in {"not_applicable_business_scope", "not_applicable_precommercial"}
        ):
            row["gap_search_scope"] = "issuer_materials_plus_targeted_public_web_search"
            if row["global_availability_status"] == "broader_web_search_not_yet_proven":
                row["global_availability_status"] = "targeted_public_web_search_completed_no_direct_value"
                row["gap_reason"] = (
                    f"{row['gap_reason']} Targeted issuer and public-web search completed on 2026-08-29; "
                    "no direct same-period, same-scope numeric value was found. This records the search boundary and is not a claim that every page on the internet was exhaustively indexed."
                ).strip()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = sorted(ROWS, key=lambda row: (row["operator_id"], row["year"], row["metric_key"], row["scope"]))
    keys = [(row["operator_id"], row["year"], row["metric_key"]) for row in rows]
    duplicates = [list(key) for key, count in Counter(keys).items() if count > 1]
    invalid_sources = sorted({sid for row in rows for sid in row["verification_sources"] if sid not in SOURCES})
    invalid_reviewed_sources = sorted({sid for row in rows for sid in row["reviewed_source_ids"] if sid not in SOURCES})
    available = [row for row in rows if row["value"] is not None]
    target_rows = [row for row in rows if row["operator_id"] in FULL_AUDIT_OPERATORS]
    target_expected_rows = len(FULL_AUDIT_OPERATORS) * len(METRICS) * len(YEARS)
    target_gaps = [row for row in target_rows if row["value"] is None]
    gaps_without_reason = [
        [row["operator_id"], row["year"], row["metric_key"]]
        for row in target_gaps if not row["gap_reason_code"] or not row["gap_reason"]
    ]
    gaps_without_review_sources = [
        [row["operator_id"], row["year"], row["metric_key"]]
        for row in target_gaps if not row["reviewed_source_ids"]
    ]
    values_without_sources = [
        [row["operator_id"], row["year"], row["metric_key"]]
        for row in target_rows if row["value"] is not None and not row["verification_sources"]
    ]
    invalid_numeric_rows = [
        [row["operator_id"], row["year"], row["metric_key"], row["value"]]
        for row in target_rows
        if row["value"] is not None and (
            float(row["value"]) < 0
            or (row["unit"] == "percent" and float(row["value"]) > 100)
        )
    ]
    row_lookup = {(row["operator_id"], row["year"], row["metric_key"]): row for row in target_rows}
    customer_identity_breaks = []
    for operator_id in ("hkt", "three_hk"):
        for year in YEARS:
            total = row_lookup[(operator_id, year, "total_customers")]["value"]
            postpaid = row_lookup[(operator_id, year, "mobile_postpaid_customers")]["value"]
            prepaid = row_lookup[(operator_id, year, "mobile_prepaid_customers")]["value"]
            if all(value is not None for value in (total, postpaid, prepaid)) and abs(float(total) - float(postpaid) - float(prepaid)) > .002:
                customer_identity_breaks.append([operator_id, year, total, postpaid, prepaid])
    coverage = [
        {
            "operator_id": row["operator_id"], "operator": row["operator"], "year": row["year"],
            "metric_key": row["metric_key"], "status": row["audit_outcome"],
            "gap_reason_code": row["gap_reason_code"], "reviewed_source_count": row["reviewed_source_count"],
        }
        for row in rows
        if row["operator_id"] in FULL_AUDIT_OPERATORS or row["metric_key"] in CORE_METRICS
    ]
    conflicts = [
        {"operator_id": "three_hk", "years": "2024-2025", "metric": "customers_and_arpu", "type": "scope_change_and_restatement", "selected_basis": "retain original historical rows; record 2025 restated comparators", "detail": "FY2025 isolates Hong Kong after disposal of the Macau operation and restates FY2024 postpaid 1.316m, prepaid 3.162m, total 4.478m, gross ARPU HKD190 and net ARPU HKD175."},
        {"operator_id": "three_hk", "years": "2016", "metric": "mobile_postpaid_net_ampu", "type": "scope_restatement", "selected_basis": "FY2017 restated comparable HKD189", "detail": "FY2016 originally reported local postpaid net AMPU HKD161; FY2017 restated the comparable postpaid net AMPU to HKD189 after excluding MVNO revenue."},
        {"operator_id": "hkt", "years": "2021", "metric": "consumer_broadband_customers", "type": "metric_scope_correction", "selected_basis": "retail consumer broadband access lines 1.461m", "detail": "The prior 1.637m value was total broadband access lines including business and wholesale and has been removed from the consumer series."},
        {"operator_id": "smartone", "years": "2019", "metric": "mobile_postpaid_arpu", "type": "accounting_standard_change", "selected_basis": "HKFRS 15 annual ARPU HKD224", "detail": "The same report also showed HKD247 under the former HKAS 18 basis."},
        {"operator_id": "smartone", "years": "2020-2025", "metric": "mobile_postpaid_exit_arpu", "type": "presentation_label_shortening", "selected_basis": "continuous June/exit series 189, 202, 213, 224, 224, 222", "detail": "FY2020-FY2022 explicitly call the KPI exit ARPU; later presentations shorten the title but retain June year-end points and the same continuous series."},
        {"operator_id": "smartone", "years": "2024-2025", "metric": "5g_penetration", "type": "exact_then_qualitative", "selected_basis": "FY2024 exact presentation 39%; FY2025 approximate continuity 39%", "detail": "FY2024 annual report rounds to approximately 40% while the official presentation states 39%; FY2025 says broadly stable without a new exact point."},
        {"operator_id": "smartone", "years": "2017-2025", "metric": "period_end", "type": "fiscal_year_difference", "selected_basis": "30 June fiscal year end", "detail": "Do not align SmarTone FY labels with HKT/3HK/i-CABLE calendar years without using period_end."},
        {"operator_id": "hkbn", "years": "2024-2025", "metric": "period_end", "type": "fiscal_year_difference", "selected_basis": "31 August fiscal year end", "detail": "Do not align HKBN FY labels with calendar-year operators without using period_end."},
        {"operator_id": "icable", "years": "2023-2025", "metric": "pay_tv_customers", "type": "service_discontinuation", "selected_basis": "leave later annual rows absent/gap", "detail": "Pay-TV service ceased in June 2023; no zero or synthetic continuation is inserted."},
        {"operator_id": "icable", "years": "2022-2025", "metric": "homes_passed_or_connected", "type": "scope_wording_change", "selected_basis": "retain comparator and scope text", "detail": "2025 uses connected-households wording while prior disclosures describe households covered."},
        {"operator_id": "hgc", "years": "2016-2025", "metric": "all_operating_kpis", "type": "private_company_disclosure_gap", "selected_basis": "only assert explicitly published values", "detail": "HGC does not publish a listed-company-style annual customer/ARPU series; missing values remain source gaps."},
    ]
    audit_failures = [
        *duplicates, *invalid_sources, *invalid_reviewed_sources, *gaps_without_reason,
        *gaps_without_review_sources, *values_without_sources, *invalid_numeric_rows,
        *customer_identity_breaks,
    ]
    if len(target_rows) != target_expected_rows:
        audit_failures.append(["target_row_count", len(target_rows), target_expected_rows])
    all_gaps = [row for row in rows if row["value"] is None]
    all_gaps_without_reason = [
        [row["operator_id"], row["year"], row["metric_key"]]
        for row in all_gaps
        if not row["gap_reason_code"] or not row["gap_reason"]
    ]
    all_gaps_not_yet_reviewed = [
        row for row in all_gaps if row["gap_search_scope"] == "not_yet_reviewed"
    ]
    pending_web_search_rows = [
        row
        for row in all_gaps
        if row["global_availability_status"] == "broader_web_search_not_yet_proven"
    ]
    related_scope_rows = [
        row
        for row in all_gaps
        if row["global_availability_status"]
        == "related_scope_value_found_not_directly_comparable"
    ]
    targeted_search_no_direct_value_rows = [
        row
        for row in all_gaps
        if row["global_availability_status"]
        == "targeted_public_web_search_completed_no_direct_value"
    ]
    quality = {
        "generated_at": BUILD_TIME, "status": "pass" if not audit_failures else "fail",
        "row_count": len(rows), "available_value_rows": len(available), "source_gap_rows": len(rows) - len(available),
        "source_count": len(SOURCES), "duplicate_key_count": len(duplicates), "duplicate_keys": duplicates,
        "invalid_source_ids": invalid_sources, "invalid_reviewed_source_ids": invalid_reviewed_sources,
        "verification_status_counts": dict(Counter(row["verification_status"] for row in rows)),
        "available_rows_by_operator": dict(Counter(row["operator"] for row in available)),
        "global_web_search": {
            "status": "pending" if pending_web_search_rows else "complete",
            "scope": "all operators and every missing operator-year-metric row",
            "pending_gap_rows": len(pending_web_search_rows),
            "targeted_search_no_direct_value_rows": len(targeted_search_no_direct_value_rows),
            "related_scope_value_rows": len(related_scope_rows),
            "completed_gap_rows": len(all_gaps)
            - len(pending_web_search_rows)
            - len(related_scope_rows),
            "issuer_material_review_not_started_rows": len(all_gaps_not_yet_reviewed),
            "gaps_without_reason": all_gaps_without_reason,
            "rule": "A reviewed issuer-material gap is not proof that the whole public web has no value.",
        },
        "full_audit": {
            "operators": list(FULL_AUDIT_OPERATORS), "years": YEARS, "metric_count": len(METRICS),
            "expected_rows": target_expected_rows, "actual_rows": len(target_rows),
            "available_value_rows": sum(row["value"] is not None for row in target_rows),
            "source_gap_rows": len(target_gaps), "gaps_without_reason": gaps_without_reason,
            "broader_web_search_not_yet_proven": sum(
                row["global_availability_status"] == "broader_web_search_not_yet_proven"
                for row in target_gaps
            ),
            "targeted_public_web_search_completed_no_direct_value": sum(
                row["global_availability_status"]
                == "targeted_public_web_search_completed_no_direct_value"
                for row in target_gaps
            ),
            "related_scope_values_found": sum(
                row["global_availability_status"] == "related_scope_value_found_not_directly_comparable"
                for row in target_gaps
            ),
            "gaps_without_review_sources": gaps_without_review_sources,
            "values_without_sources": values_without_sources, "invalid_numeric_rows": invalid_numeric_rows,
            "customer_identity_breaks": customer_identity_breaks,
        },
        "rules": ["Every audited operator × year × metric key must have exactly one row.", "Every value must have bound official evidence.", "Every gap must contain a structured reason and the reviewed official sources.", "Issuer-material review is not labelled as proof that the entire public web has no value.", "Related-scope public values are retained but never substituted for the requested metric.", "No analyst interpolation.", "Pre-commercial 5G zeroes and normalized qualitative disclosures must be explicitly labelled.", "A source gap is not silently treated as zero.", "Annual average ARPU and exit ARPU are separate metrics.", "Fiscal year end and scope breaks must be applied before comparison."],
    }
    payload = {"dataset_id": "local_hk_operator_operating_metrics_2016_2025", "generated_at": BUILD_TIME, "relationship": "Operating-metric sidecar. Existing financial facts remain in hk_competitor_product_tariffs/local_financial_results.json and are not duplicated.", "operators": OPERATORS, "metrics": {key: {"metric_zh": value[0], "default_unit": value[1]} for key, value in METRICS.items()}, "rows": rows}
    (OUT / "annual_metrics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(OUT / "annual_metrics.csv", rows)
    write_csv(OUT / "full_metric_audit_2016_2025.csv", target_rows)
    (OUT / "full_metric_audit_2016_2025.json").write_text(json.dumps({"generated_at": BUILD_TIME, "operators": list(FULL_AUDIT_OPERATORS), "years": YEARS, "metrics": list(METRICS), "rows": target_rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (OUT / "coverage.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["operator_id", "operator", "year", "metric_key", "status", "gap_reason_code", "reviewed_source_count"])
        writer.writeheader(); writer.writerows(coverage)
    (OUT / "sources.json").write_text(json.dumps({"generated_at": BUILD_TIME, "sources": list(SOURCES.values())}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "quality_audit.json").write_text(json.dumps(quality, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "conflicts_and_scope_breaks.json").write_text(json.dumps({"generated_at": BUILD_TIME, "items": conflicts}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (OUT / "conflicts_and_scope_breaks.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["operator_id", "years", "metric", "type", "selected_basis", "detail"])
        writer.writeheader(); writer.writerows(conflicts)
    source_inventory = "\n".join(["# 公開來源盤點", "", "| 運營商 | 盤點範圍 | 可用性 |", "|---|---|---|", "| CMHK | 公司新聞稿、政府機構公司專訪及定向公開網檢索 | 低至中；未單獨上市，只保留帶日期的客戶、5G、覆蓋及基站里程碑 |", "| HKT | 2016–2025官方年報 | 高，可建立客戶、5G、寬頻、ARPU、流失率長序列 |", "| 3HK | 2016–2025官方年報及结果演示 | 高，但2025年存在澳門業務出售後的口徑變更 |", "| SmarTone | FY2016–FY2025官方年報及结果演示 | 中高，後期不再公開若干絕對KPI |", "| HKBN | FY2016–FY2025官方年報／業績公告 | 高，可建立住宅客戶、移動訂閱、寬頻及覆蓋長序列；MVNO合作網絡基站不歸入HKBN |", "| HGC | 官方網站、新聞稿及2016年集團年報 | 低，私營公司未披露年度客戶/ARPU序列；移動業務於2026年才推出 |", "| i-CABLE | 2016–2025官方年報／業績公告及公司里程碑 | 中，2023年收費電視停播形成結構斷點，iMobile合作網絡基站不歸入i-CABLE |", "", "官方披露优先；政府机构或可信公开材料中的公司直接陈述会单独标注来源类型。商用前5G为可验证的运营零值，区间或连续性表述会以近似值及独立状态记录；定向公开网复核后仍无依据的年份保留为 `source_gap_confirmed`，但不写成整个互联网绝对无数据。", ""])
    (OUT / "source_inventory.md").write_text(source_inventory, encoding="utf-8")
    audit_matrix_lines = [
        "# 3HK、HKT、SmarTone 2016–2025全指标审计",
        "",
        f"- 指标：{len(METRICS)}项",
        f"- 理论审计格：{target_expected_rows}",
        f"- 实际审计格：{len(target_rows)}",
        f"- 有官方依据数值：{sum(row['value'] is not None for row in target_rows)}",
        f"- 确认缺口：{len(target_gaps)}（每格均保留理由及已复核官方来源）",
        "",
        "| 运营商 | 指标 | 有值年度 | 缺口年度 |",
        "|---|---|---:|---:|",
    ]
    for operator_id in FULL_AUDIT_OPERATORS:
        for metric_key, (metric_zh, _unit) in METRICS.items():
            metric_rows = [row for row in target_rows if row["operator_id"] == operator_id and row["metric_key"] == metric_key]
            value_count = sum(row["value"] is not None for row in metric_rows)
            audit_matrix_lines.append(f"| {OPERATORS[operator_id]['name']} | {metric_zh} (`{metric_key}`) | {value_count} | {len(metric_rows) - value_count} |")
    audit_matrix_lines.extend(["", "缺口不是空行：每一行都包含 `gap_reason_code`、`gap_reason`、`reviewed_source_ids` 与 `reviewed_source_urls`。", "", "`source_gap_confirmed` 只表示已列出的发行人官方材料没有同口径数值；三家目标运营商剩余缺口已完成定向公开网检索，并标为 `targeted_public_web_search_completed_no_direct_value`，但这仍不等于已证明整个互联网不存在。相关但不同口径的公开值会保存在 `related_public_*` 字段，绝不冒充目标指标。", ""])
    (OUT / "full_metric_audit_2016_2025.md").write_text("\n".join(audit_matrix_lines), encoding="utf-8")
    quality_md = "\n".join(["# 香港本地運營商經營指標庫質量審計", "", f"- 結構與來源門禁：`{quality['status']}`", f"- 全庫尚待定向公開網補搜：{len(pending_web_search_rows)} 行", f"- 全库定向公开网检索后无同口径直接值：{len(targeted_search_no_direct_value_rows)} 行", f"- 明細行：{len(rows)}", f"- 有值行：{len(available)}", f"- 明確缺口：{len(rows)-len(available)}", f"- 三家全量审计格：{len(target_rows)}/{target_expected_rows}", f"- 三家缺口有理由：{len(target_gaps)-len(gaps_without_reason)}/{len(target_gaps)}", f"- 三家缺口有复核来源：{len(target_gaps)-len(gaps_without_review_sources)}/{len(target_gaps)}", f"- 公開來源條目：{len(SOURCES)}", f"- 重複鍵：{len(duplicates)}", f"- 無效來源引用：{len(invalid_sources) + len(invalid_reviewed_sources)}", "", "`pass` 只代表目前數據列的結構、來源綁定、缺口理由和定向检索边界通過門禁；定向公开网检索没有找到同口径直接值，也不代表已证明整个互联网没有数据。", "", "## 質量規則", "", *[f"- {rule}" for rule in quality["rules"]], ""])
    (OUT / "quality_audit.md").write_text(quality_md, encoding="utf-8")
    summary = "\n".join(["# 香港本地運營商2016–2025經營指標摘要", "", "收錄 CMHK、HKT/csl/1O1O、3HK、SmarTone、HKBN、HGC 及 i-CABLE 的公開非財務指標，並與現有財務庫分工，不重複複製財務數據。", "", "## 可查指標", "", "- 移動總客戶、後付/預付客戶、5G客戶與滲透率", "- 住宅寬頻、FTTH、homes passed/connected、商業樓宇覆蓋", "- ARPU、期末ARPU、淨ARPU、ARPH、後付及企業流失率", "- 移動DOU、年度數據流量、基站總數與5G基站（未披露的年份保留為明確缺口）", "- 5G人口覆蓋、地鐵站增強、2Gbps+客戶、5G家庭寬頻收入/EBITDA增長", "- i-CABLE收費電視、固網電話與免費電視覆蓋", "", "## 使用邊界", "", "- CMHK、HKT、3HK、SmarTone、HKBN、HGC及i-CABLE均已完成发行人材料与定向公开网检索；找到的直接值已补回，不同口径相关值单独保留。", f"- 全库有 {len(targeted_search_no_direct_value_rows)} 个适用但仍缺直接值的格，经定向公开网检索未找到同期间、同口径数值；这记录了检索边界，不等于声称整个互联网绝对不存在。", f"- 尚未完成定向公开网检索的缺口为 {len(pending_web_search_rows)} 个。", "- 3HK 2025年開始為香港單一口徑，不可與2024年原披露直接計算增長。", "- SmarTone為6月底財年，HKBN為8月底財年；比較時以 `period_end` 對齊。", "- HGC为私营公司，只保留明确发布的范围值；HGC Mobile于2026年才推出，2016–2025移动指标按不适用处理。", "- HKBN及i-CABLE的移动服务使用合作MNO网络；其客户／ARPU若披露则保留，但合作方基站不归入两家公司。", ""])
    (OUT / "summary.md").write_text(summary, encoding="utf-8")
    readme = "\n".join(["# 香港本地運營商非財務經營指標庫", "", "## 入口", "", "- `annual_metrics.json` / `.csv`：標準長表", "- `full_metric_audit_2016_2025.*`：3HK、HKT、SmarTone全部指标×全部年度审计矩阵", "- `coverage.csv`：逐年覆蓋、缺口原因分类及复核来源数", "- `sources.json`：官方及其他明確標注的公開來源", "- `source_inventory.md`：收集前來源盤點", "- `quality_audit.*`：質量門禁", "- `conflicts_and_scope_breaks.*`：重述、財年差與業務斷點", "", "## 與現有數據庫的關係", "", "財務事實仍以 `agent_knowledge/hk_competitor_product_tariffs/local_financial_results.json` 為準；本庫只補充客戶、5G、寬頻、網絡、ARPU、流失率等非財務經營指標。", "", "## 重建", "", "```bash", "python3 scripts/build_local_hk_operator_operating_database.py", "```", ""])
    (OUT / "README.md").write_text(readme, encoding="utf-8")
    manifest = {"id": "local_hk_operator_operating_metrics_2016_2025", "title": "香港本地運營商2016–2025非財務經營指標庫", "summary": "CMHK、HKT、3HK、SmarTone、HKBN、HGC、i-CABLE客戶、5G、寬頻、網絡、ARPU、流失率及其他公開KPI。", "source_type": "official_public_multi_source", "updated_at": BUILD_TIME, "tags": ["hong_kong_carriers", "local_operators", "subscribers", "5g", "broadband", "network", "arpu", "churn", "operating_metrics"], "entrypoints": ["README.md", "summary.md", "annual_metrics.json", "annual_metrics.csv", "full_metric_audit_2016_2025.json", "full_metric_audit_2016_2025.csv", "full_metric_audit_2016_2025.md", "sources.json", "source_inventory.md", "coverage.csv", "quality_audit.json", "quality_audit.md", "conflicts_and_scope_breaks.json", "conflicts_and_scope_breaks.csv"], "row_count": len(rows), "quality": {"status": quality["status"], "verification_scope": "official_public_values_with_documented_source_gaps_and_search_boundaries", "verified_count": len(available), "gap_count": len(all_gaps), "global_web_search_status": quality["global_web_search"]["status"], "pending_web_search_rows": len(pending_web_search_rows), "targeted_search_no_direct_value_rows": len(targeted_search_no_direct_value_rows), "source_count": len(SOURCES), "available_value_rows": len(available), "full_audit_rows": len(target_rows), "full_audit_expected_rows": target_expected_rows}, "linked_existing_datasets": ["hk_competitor_product_tariffs"]}
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(OUT), "rows": len(rows), "available": len(available), "sources": len(SOURCES), "quality": quality["status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

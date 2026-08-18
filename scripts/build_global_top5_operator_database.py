from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "agent_knowledge" / "global_top5_operators_2016_2025"
ORIGINAL_DB = ROOT / "agent_knowledge" / "quarterly_competitor_metrics_2026-06-18"
BUILD_TIME = "2026-08-18T00:00:00+08:00"
YEARS = list(range(2016, 2026))

OPERATORS = {
    "china_mobile": {
        "name": "中国移动",
        "legal_name": "China Mobile Limited",
        "fiscal_year_end": "12-31",
        "existing_financial_reference": "../quarterly_competitor_metrics_2026-06-18/quarterly_metrics.json#subject=中国移动",
    },
    "bharti_airtel": {
        "name": "Bharti Airtel",
        "legal_name": "Bharti Airtel Limited",
        "fiscal_year_end": "03-31",
        "existing_financial_reference": "",
    },
    "reliance_jio": {
        "name": "Reliance Jio",
        "legal_name": "Jio Platforms Limited / Reliance Jio Infocomm Limited",
        "fiscal_year_end": "03-31",
        "existing_financial_reference": "",
    },
    "china_telecom": {
        "name": "中国电信",
        "legal_name": "China Telecom Corporation Limited",
        "fiscal_year_end": "12-31",
        "existing_financial_reference": "../quarterly_competitor_metrics_2026-06-18/quarterly_metrics.json#subject=中国电信",
    },
    "china_unicom": {
        "name": "中国联通",
        "legal_name": "China Unicom (Hong Kong) Limited",
        "fiscal_year_end": "12-31",
        "existing_financial_reference": "../quarterly_competitor_metrics_2026-06-18/quarterly_metrics.json#subject=中国联通",
    },
    "china_broadnet": {
        "name": "中国广电",
        "legal_name": "China Broadcasting Network Group Corporation Ltd. / China Broadnet",
        "fiscal_year_end": "12-31",
        "existing_financial_reference": "",
    },
}

METRICS = {
    "total_customers": ("集团总客户数", "million_customers"),
    "mobile_subscribers": ("移动用户数", "million_subscribers"),
    "4g_subscribers": ("4G用户数", "million_subscribers"),
    "5g_package_subscribers": ("5G套餐用户数", "million_subscribers"),
    "5g_network_subscribers": ("5G网络用户数", "million_subscribers"),
    "fixed_broadband_subscribers": ("固网宽带用户数", "million_subscribers"),
    "connected_homes": ("已连接家庭/场所", "million_premises"),
    "churn": ("月度用户流失率", "percent_per_month"),
    "mobile_arpu": ("移动ARPU", "local_currency_per_user_month"),
    "broadband_arpu": ("宽带ARPU", "local_currency_per_user_month"),
    "household_customer_blended_arpu": ("家庭客户综合ARPU", "local_currency_per_user_month"),
    "mobile_dou": ("月户均移动数据流量DOU", "GB_per_user_month"),
    "total_data_traffic": ("年度数据流量", "billion_GB"),
    "handset_data_traffic": ("年度手机上网流量", "billion_GB"),
    "network_towers": ("网络铁塔/站点", "sites"),
    "mobile_broadband_base_stations": ("移动宽带基站", "base_stations"),
    "total_base_stations": ("移动基站总数", "million_base_stations"),
    "4g_base_stations": ("4G基站数", "million_base_stations"),
    "5g_base_stations": ("5G基站数", "million_base_stations"),
    "shared_4g_5g_base_stations": ("可共享4G/5G基站数", "million_base_stations"),
    "spectrum_holdings": ("频谱持有量", "MHz_uplink_plus_downlink"),
    "cable_tv_actual_users": ("全国有线电视实际用户", "million_users"),
    "two_way_digital_cable_tv_users": ("全国有线电视双向数字实际用户", "million_users"),
    "hd_uhd_cable_tv_users": ("全国有线电视高清及超高清用户", "million_users"),
    "uhd_cable_tv_users": ("全国有线电视超高清用户", "million_users"),
    "cable_network_industry_revenue": ("全国有线电视网络收入", "RMB_million"),
    "integrated_broadband_network_customers": ("融合宽带网络客户", "million_customers"),
    "gigabit_broadband_customers": ("千兆宽带客户", "million_customers"),
    "iot_connections": ("物联网连接", "million_connections"),
    "mobile_broadband_integration_rate": ("移动宽带融合率", "percent"),
    "government_enterprise_customers": ("政企客户", "million_customers"),
    "households_gigabit_coverage": ("千兆网络覆盖家庭", "million_households"),
    "iptv_subscribers": ("IPTV用户", "million_subscribers"),
    "gigabit_broadband_penetration": ("千兆宽带渗透率", "percent"),
    "5g_network_penetration": ("5G网络用户渗透率", "percent"),
    "total_connectivity_subscribers": ("连接用户总规模", "million_connections"),
    "integrated_subscriber_penetration": ("融合用户渗透率", "percent"),
    "integrated_package_arpu": ("融合套餐ARPU", "RMB_per_user_month"),
    "mobile_population_coverage": ("移动网络人口覆盖率", "percent"),
    "5g_a_deployment_cities": ("5G-A部署城市", "cities"),
    "cloud_ai_product_users": ("云AI产品用户", "million_users"),
    "intelligent_compute_capacity": ("智能算力", "EFLOPS_FP16"),
    "ten_g_pon_ports": ("10G PON端口", "million_ports"),
    "urban_gigabit_coverage": ("城市千兆宽带覆盖率", "percent"),
    "revenue": ("营业收入", "INR_million"),
    "value_of_sales_and_services": ("销售及服务价值", "INR_crore"),
    "revenue_from_operations": ("经营收入", "INR_crore"),
    "ebitda": ("EBITDA", "INR_million"),
    "ebit": ("EBIT", "INR_million"),
    "earnings_before_tax": ("税前利润", "INR_million"),
    "net_profit": ("净利润", "INR_million"),
    "capex": ("资本开支", "INR_million"),
    "net_debt": ("净债务", "INR_million"),
    "shareholders_equity": ("股东权益", "INR_million"),
}


def annual_url(operator_id: str, year: int) -> str:
    if operator_id == "china_mobile":
        return f"https://www.chinamobileltd.com/en/ir/reports/ar{year}.pdf"
    if operator_id == "china_telecom":
        return f"https://www.chinatelecom-h.com/en/ir/report/annual{year}.pdf"
    if operator_id == "china_unicom":
        return f"https://www.chinaunicom.com.hk/en/ir/reports/ar{year}.pdf"
    if operator_id == "bharti_airtel":
        if year <= 2020:
            return f"https://www.airtel.in/airtel-annual-report-{year-1}-{str(year)[-2:]}/"
        if year == 2025:
            return "https://assets.airtel.in/static-assets/cms/investor/docs/annual_results_2024_25/Integrated_Report_and_Annual_Financial_Statements.pdf"
        return "https://www.airtel.in/about-bharti/equity/results/annual-results"
    return f"https://www.ril.com/ar{year-1}-{str(year)[-2:]}/digital-services.html"


SOURCES: dict[str, dict[str, Any]] = {}
for operator_id, spec in OPERATORS.items():
    if operator_id == "china_broadnet":
        # China Broadnet is not listed and does not publish a comparable annual-
        # report series.  Only explicit regulator, government and filing sources
        # are registered below; never manufacture annual-report URLs for it.
        continue
    for year in YEARS:
        sid = f"{operator_id}_ar_{year}"
        SOURCES[sid] = {
            "source_id": sid,
            "operator_id": operator_id,
            "year": year,
            "label": f"{spec['legal_name']} {year} annual report",
            "url": annual_url(operator_id, year),
            "source_type": "official_annual_report",
            "publisher": spec["legal_name"],
        }

for year in YEARS:
    SOURCES[f"china_mobile_ops_{year}"] = {
        "source_id": f"china_mobile_ops_{year}", "operator_id": "china_mobile", "year": year,
        "label": f"China Mobile quarterly operating data {year}",
        "url": f"https://www.chinamobileltd.com/en/ir/operation_q.php?year={year}&scroll2title=1",
        "source_type": "official_operating_statistics", "publisher": "China Mobile Limited",
    }
    SOURCES[f"china_telecom_kpi_{year}"] = {
        "source_id": f"china_telecom_kpi_{year}", "operator_id": "china_telecom", "year": year,
        "label": f"China Telecom KPI / annual-results operating table {year}",
        "url": f"https://www.chinatelecom-h.com/en/ir/kpi.php?year={year}",
        "source_type": "official_operating_statistics", "publisher": "China Telecom Corporation Limited",
    }
    SOURCES[f"china_unicom_ops_{year}"] = {
        "source_id": f"china_unicom_ops_{year}", "operator_id": "china_unicom", "year": year,
        "label": f"China Unicom operating data / results presentation {year}",
        "url": f"https://www.chinaunicom.com.hk/en/ir/operating.php?year={year}",
        "source_type": "official_operating_statistics", "publisher": "China Unicom (Hong Kong) Limited",
    }

# A results presentation is a separate official document from both the annual
# report and the operating/KPI table.  It is the third document used for the
# strict per-value source gate on the three mainland operators' disclosed KPIs.
RESULTS_PRESENTATIONS = {
    "china_mobile": {
        2016: "pre170323", 2017: "pre180322", 2018: "pre190321", 2019: "pre200319",
        2020: "pre210325", 2021: "pre220323", 2022: "pre230323", 2023: "pre240321",
        2024: "pre250320", 2025: "pre260326",
    },
    "china_telecom": {
        2016: "annpre170321", 2017: "annpre180328", 2018: "annpre190319", 2019: "annpre200324",
        2020: "annpre210309", 2021: "annpre220317", 2022: "annpre230322", 2023: "annpre240326",
        2024: "annpre250325", 2025: "annpre260324",
    },
    "china_unicom": {
        2016: "pre170315", 2017: "pre180315", 2018: "pre190313", 2019: "pre200323",
        2020: "pre210311", 2021: "pre220311", 2022: "pre230308", 2023: "pre240319",
        2024: "pre250318", 2025: "pre260319",
    },
}
PRESENTATION_BASE = {
    "china_mobile": "https://www.chinamobileltd.com/en/ir/webcasts/",
    "china_telecom": "https://www.chinatelecom-h.com/en/ir/presentations/",
    "china_unicom": "https://www.chinaunicom.com.hk/en/ir/presentations/",
}
for operator_id, years in RESULTS_PRESENTATIONS.items():
    for year, stem in years.items():
        sid = f"{operator_id}_results_{year}"
        SOURCES[sid] = {
            "source_id": sid,
            "operator_id": operator_id,
            "year": year,
            "label": f"{OPERATORS[operator_id]['legal_name']} {year} annual results presentation",
            "url": f"{PRESENTATION_BASE[operator_id]}{stem}.pdf",
            "source_type": "official_results_presentation",
            "publisher": OPERATORS[operator_id]["legal_name"],
        }

# China Unicom's SEC filings, sustainability reports and December operating
# announcements are separate source documents from the annual-results slide
# decks.  They preserve the exact thousand-subscriber precision that later
# presentations sometimes round away.
SOURCES.update({
    **{
        f"china_unicom_20f_{year}": {
            "source_id": f"china_unicom_20f_{year}",
            "operator_id": "china_unicom",
            "year": year,
            "label": f"China Unicom {year} annual report on Form 20-F",
            "url": f"https://www.chinaunicom.com.hk/en/ir/reports/{year}_20f.pdf",
            "source_type": "official_sec_form_20f",
            "publisher": "China Unicom (Hong Kong) Limited",
        }
        for year in (2018, 2019, 2020)
    },
    **{
        f"china_unicom_csr_{year}": {
            "source_id": f"china_unicom_csr_{year}",
            "operator_id": "china_unicom",
            "year": year,
            "label": f"China Unicom Sustainability Report {year}",
            "url": f"https://www.chinaunicom.com.hk/en/esg/reports/csr{year}.pdf",
            "source_type": "official_sustainability_report",
            "publisher": "China Unicom (Hong Kong) Limited",
        }
        for year in (2016, 2017, 2020, 2022)
    },
    "china_unicom_csr_2018": {
        "source_id": "china_unicom_csr_2018",
        "operator_id": "china_unicom",
        "year": 2018,
        "label": "China Unicom Corporate Social Responsibility Report 2018",
        "url": "https://www.chinaunicom.com.hk/en/esg/reports/csr2018.pdf",
        "source_type": "official_sustainability_report",
        "publisher": "China Unicom (Hong Kong) Limited",
    },
    "china_unicom_csr_2019": {
        "source_id": "china_unicom_csr_2019",
        "operator_id": "china_unicom",
        "year": 2019,
        "label": "China Unicom Corporate Social Responsibility Report 2019",
        "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2020/0617/2020061700317.pdf",
        "source_type": "official_sustainability_report",
        "publisher": "China Unicom (Hong Kong) Limited",
    },
    "china_unicom_csr_2021": {
        "source_id": "china_unicom_csr_2021",
        "operator_id": "china_unicom",
        "year": 2021,
        "label": "China Unicom Sustainability Report 2021",
        "url": "https://www.chinaunicom.com.hk/en/esg/reports/csr2021.pdf",
        "source_type": "official_sustainability_report",
        "publisher": "China Unicom (Hong Kong) Limited",
    },
    "china_unicom_dec_ops_2016": {
        "source_id": "china_unicom_dec_ops_2016",
        "operator_id": "china_unicom",
        "year": 2016,
        "label": "China Unicom operational statistics for December 2016",
        "url": "https://www.hkexnews.hk/listedco/listconews/sehk/2017/0119/LTN20170119339.pdf",
        "source_type": "official_hkex_operating_announcement",
        "publisher": "China Unicom (Hong Kong) Limited",
    },
    "china_unicom_dec_ops_2020": {
        "source_id": "china_unicom_dec_ops_2020",
        "operator_id": "china_unicom",
        "year": 2020,
        "label": "China Unicom operational statistics for December 2020",
        "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2021/0120/2021012000402.pdf",
        "source_type": "official_hkex_operating_announcement",
        "publisher": "China Unicom (Hong Kong) Limited",
    },
    "china_unicom_dec_ops_2021": {
        "source_id": "china_unicom_dec_ops_2021",
        "operator_id": "china_unicom",
        "year": 2021,
        "label": "China Unicom operational statistics for December 2021",
        "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2022/0120/2022012000495.pdf",
        "source_type": "official_hkex_operating_announcement",
        "publisher": "China Unicom (Hong Kong) Limited",
    },
    "china_unicom_press_2017": {
        "source_id": "china_unicom_press_2017",
        "operator_id": "china_unicom",
        "year": 2017,
        "label": "China Unicom 2017 annual-results press release",
        "url": "https://www.chinaunicom.com.hk/en/media/press/p180315.pdf",
        "source_type": "official_results_press_release",
        "publisher": "China Unicom (Hong Kong) Limited",
    },
})

# China Telecom's annual-results press releases are separate legal documents
# from both its KPI webpage and annual-results presentation.  They retain the
# exact two-decimal subscriber tables needed by the strict source gate.
CHINA_TELECOM_PRESS_RELEASES = {
    2016: "p170321", 2017: "p180328", 2018: "p190319", 2019: "p200324",
    2020: "p210309", 2021: "p220317", 2022: "p230322", 2023: "p240326",
    2024: "p250325",
}
for year, stem in CHINA_TELECOM_PRESS_RELEASES.items():
    sid = f"china_telecom_press_{year}"
    SOURCES[sid] = {
        "source_id": sid,
        "operator_id": "china_telecom",
        "year": year,
        "label": f"China Telecom {year} annual-results press release",
        "url": f"https://www.chinatelecom-h.com/en/media/press/{stem}.pdf",
        "source_type": "official_results_press_release",
        "publisher": "China Telecom Corporation Limited",
    }

for year in (2016, 2017, 2020):
    sid = f"china_telecom_transcript_{year}"
    SOURCES[sid] = {
        "source_id": sid,
        "operator_id": "china_telecom",
        "year": year,
        "label": f"China Telecom {year} annual-results management transcript",
        "url": f"https://www.chinatelecom-h.com/en/ir/transcripts/tra_ar{year}.pdf",
        "source_type": "official_results_transcript",
        "publisher": "China Telecom Corporation Limited",
    }

SOURCES.update({
    "china_mobile_press_2017": {
        "source_id": "china_mobile_press_2017", "operator_id": "china_mobile", "year": 2017,
        "label": "China Mobile 2017 annual results press release",
        "url": "https://www.chinamobileltd.com/en/file/view.php?id=190673",
        "source_type": "official_results_press_release", "publisher": "China Mobile Limited",
        "evidence": {
            "fixed_broadband_subscribers": {
                "value": 112.69,
                "unit": "million_subscribers",
                "locator": "Operating Performance table; FY2017 total wireline broadband customers",
            },
        },
    },
    **{
        f"china_mobile_ar_a_{year}": {
            "source_id": f"china_mobile_ar_a_{year}", "operator_id": "china_mobile", "year": year,
            "label": f"China Mobile {year} A-share annual report",
            "url": f"https://www.chinamobileltd.com/sc/ir/reports/ar{year}_ashare.pdf",
            "source_type": "official_a_share_annual_report", "publisher": "China Mobile Limited",
        }
        for year in range(2021, 2025)
    },
    "china_mobile_20f_2021": {
        "source_id": "china_mobile_20f_2021", "operator_id": "china_mobile", "year": 2021,
        "label": "China Mobile 2021 annual report on Form 20-F",
        "url": "https://www.chinamobileltd.com/en/ir/reports/ar2021/2021_20f.pdf",
        "source_type": "official_sec_annual_filing", "publisher": "China Mobile Limited",
        "evidence": {
            "total_base_stations": {"value": 5.50, "unit": "million_base_stations", "comparator": ">=", "locator": "Base Stations, year-end network scale"},
        },
    },
    "china_mobile_20f_2019": {
        "source_id": "china_mobile_20f_2019", "operator_id": "china_mobile", "year": 2019,
        "label": "China Mobile 2019 annual report on Form 20-F",
        "url": "https://www.chinamobileltd.com/en/ir/reports/ar2019/2019_20f.pdf",
        "source_type": "official_sec_annual_filing", "publisher": "China Mobile Limited",
        "evidence": {
            "total_base_stations": {"value": 4.48, "unit": "million_base_stations", "locator": "Base Stations, year-end network scale"},
            "5g_base_stations": {"value": 0.05, "unit": "million_base_stations", "comparator": ">=", "locator": "Base Stations; over 50,000 put in use during 2019"},
        },
    },
    "china_mobile_sd_2019": {
        "source_id": "china_mobile_sd_2019", "operator_id": "china_mobile", "year": 2019,
        "label": "China Mobile 2019 sustainability report",
        "url": "https://www.chinamobileltd.com/en/ir/reports/ar2019/sd2019.pdf",
        "source_type": "official_sustainability_report", "publisher": "China Mobile Limited",
        "evidence": {
            "5g_base_stations": {"value": 0.05, "unit": "million_base_stations", "comparator": ">=", "locator": "5G is Here; deployed over 50,000 5G base stations"},
        },
    },
    "china_mobile_20f_2020": {
        "source_id": "china_mobile_20f_2020", "operator_id": "china_mobile", "year": 2020,
        "label": "China Mobile 2020 annual report on Form 20-F",
        "url": "https://www.chinamobileltd.com/en/ir/reports/ar2020/2020_20f.pdf",
        "source_type": "official_sec_annual_filing", "publisher": "China Mobile Limited",
        "evidence": {
            "5g_base_stations": {"value": 0.39, "unit": "million_base_stations", "comparator": ">=", "locator": "Base Stations; over 390,000 built by year-end 2020"},
        },
    },
    "china_mobile_sd_2020": {
        "source_id": "china_mobile_sd_2020", "operator_id": "china_mobile", "year": 2020,
        "label": "China Mobile 2020 sustainability report",
        "url": "https://www.chinamobileltd.com/en/ir/reports/ar2020/sd2020.pdf",
        "source_type": "official_sustainability_report", "publisher": "China Mobile Limited",
        "evidence": {
            "5g_base_stations": {"value": 0.39, "unit": "million_base_stations", "locator": "2016-2020 achievements; opened 390,000 5G base stations"},
        },
    },
    "china_mobile_20f_2018": {
        "source_id": "china_mobile_20f_2018", "operator_id": "china_mobile", "year": 2018,
        "label": "China Mobile 2018 annual report on Form 20-F",
        "url": "https://www.chinamobileltd.com/en/ir/reports/ar2018/2018_20f.pdf",
        "source_type": "official_sec_annual_filing", "publisher": "China Mobile Limited",
        "evidence": {
            "4g_base_stations": {"value": 2.41, "unit": "million_base_stations", "locator": "Personal Mobile Market, year-end network scale"},
        },
    },
    "china_mobile_20f_2016": {
        "source_id": "china_mobile_20f_2016", "operator_id": "china_mobile", "year": 2016,
        "label": "China Mobile 2016 annual report on Form 20-F",
        "url": "https://www.sec.gov/Archives/edgar/data/1117795/000119312517142311/d240713d20f.htm",
        "source_type": "official_sec_annual_filing", "publisher": "China Mobile Limited / U.S. SEC",
        "evidence": {
            "4g_base_stations": {"value": 1.51, "unit": "million_base_stations", "locator": "Item 4, Mobile Market"},
        },
    },
    "china_mobile_sd_2016": {
        "source_id": "china_mobile_sd_2016", "operator_id": "china_mobile", "year": 2016,
        "label": "China Mobile 2016 sustainability report",
        "url": "https://www.chinamobileltd.com/en/ir/reports/ar2016/sd2016.pdf",
        "source_type": "official_sustainability_report", "publisher": "China Mobile Limited",
        "evidence": {
            "4g_base_stations": {"value": 1.51, "unit": "million_base_stations", "locator": "Big Connectivity, year-end network scale"},
        },
    },
    "china_mobile_20f_2017": {
        "source_id": "china_mobile_20f_2017", "operator_id": "china_mobile", "year": 2017,
        "label": "China Mobile 2017 annual report on Form 20-F",
        "url": "https://www.chinamobileltd.com/en/ir/reports/ar2017/2017_20f.pdf",
        "source_type": "official_sec_annual_filing", "publisher": "China Mobile Limited",
        "evidence": {
            "4g_base_stations": {"value": 1.87, "unit": "million_base_stations", "locator": "Personal Mobile Market, year-end network scale"},
        },
    },
    "china_mobile_sd_2017": {
        "source_id": "china_mobile_sd_2017", "operator_id": "china_mobile", "year": 2017,
        "label": "China Mobile 2017 sustainability report",
        "url": "https://www.chinamobileltd.com/en/ir/reports/ar2017/sd2017.pdf",
        "source_type": "official_sustainability_report", "publisher": "China Mobile Limited",
        "evidence": {
            "4g_base_stations": {"value": 1.87, "unit": "million_base_stations", "locator": "Optimizing Connectivity Capabilities"},
        },
    },
    "china_mobile_sd_2018": {
        "source_id": "china_mobile_sd_2018", "operator_id": "china_mobile", "year": 2018,
        "label": "China Mobile 2018 sustainability report",
        "url": "https://www.chinamobileltd.com/en/ir/reports/ar2018/sd2018.pdf",
        "source_type": "official_sustainability_report", "publisher": "China Mobile Limited",
        "evidence": {
            "4g_base_stations": {"value": 2.41, "unit": "million_base_stations", "locator": "network scale at the end of 2018"},
        },
    },
    "china_mobile_prospectus_2021": {
        "source_id": "china_mobile_prospectus_2021", "operator_id": "china_mobile", "year": 2021,
        "label": "China Mobile A-share prospectus with FY2018-FY2020 operating comparatives",
        "url": "https://www.chinamobileltd.com/sc/ir/sse_filings/sca211221b.pdf",
        "source_type": "official_listing_prospectus", "publisher": "China Mobile Limited",
        "comparative_evidence": {
            "FY2018": {
                "4g_base_stations": {"value": 2.41, "unit": "million_base_stations", "locator": "operating KPI table"},
                "total_base_stations": {"value": 3.85, "unit": "million_base_stations", "locator": "operating KPI table"},
            },
            "FY2019": {
                "4g_base_stations": {"value": 3.09, "unit": "million_base_stations", "locator": "operating KPI table"},
                "total_base_stations": {"value": 4.48, "unit": "million_base_stations", "locator": "operating KPI table"},
            },
            "FY2020": {
                "4g_base_stations": {"value": 3.28, "unit": "million_base_stations", "locator": "operating KPI table"},
                "total_base_stations": {"value": 5.14, "unit": "million_base_stations", "locator": "operating KPI table"},
            },
        },
    },
    "china_mobile_results_announcement_2020": {
        "source_id": "china_mobile_results_announcement_2020", "operator_id": "china_mobile", "year": 2020,
        "label": "China Mobile 2020 annual results announcement",
        "url": "https://www.chinamobileltd.com/en/file/view.php?id=244722",
        "source_type": "official_annual_results_announcement", "publisher": "China Mobile Limited",
        "evidence": {
            "total_base_stations": {"value": 5.14, "unit": "million_base_stations", "locator": "chairman's statement; year-end network scale, page 8"},
        },
    },
    "china_mobile_sd_2021": {
        "source_id": "china_mobile_sd_2021", "source_document_id": "china_mobile_sd_2021",
        "operator_id": "china_mobile", "year": 2021,
        "label": "China Mobile 2021 sustainability report performance chapter",
        "url": "https://www.chinamobileltd.com/sc/esg/sd/2021_ashare/09.pdf",
        "source_type": "official_sustainability_report", "publisher": "China Mobile Limited",
        "comparative_evidence": {
            "FY2019": {"4g_base_stations": {"value": 3.09, "unit": "million_base_stations", "locator": "network scale performance table"}},
            "FY2020": {"4g_base_stations": {"value": 3.28, "unit": "million_base_stations", "locator": "network scale performance table"}},
            "FY2021": {"4g_base_stations": {"value": 3.32, "unit": "million_base_stations", "locator": "network scale performance table"}},
        },
    },
    "china_mobile_sd_2022": {
        "source_id": "china_mobile_sd_2022", "operator_id": "china_mobile", "year": 2022,
        "label": "China Mobile 2022 sustainability report",
        "url": "https://www.chinamobileltd.com/tc/ir/reports/ar2022/sd2022.pdf",
        "source_type": "official_sustainability_report", "publisher": "China Mobile Limited",
        "comparative_evidence": {
            "FY2020": {"4g_base_stations": {"value": 3.28, "unit": "million_base_stations", "locator": "network scale performance table"}},
            "FY2021": {"4g_base_stations": {"value": 3.32, "unit": "million_base_stations", "locator": "network scale performance table"}},
            "FY2022": {"4g_base_stations": {"value": 3.34, "unit": "million_base_stations", "locator": "network scale performance table"}},
        },
    },
    "china_mobile_sd_2023": {
        "source_id": "china_mobile_sd_2023", "operator_id": "china_mobile", "year": 2023,
        "label": "China Mobile 2023 sustainability report",
        "url": "https://www.chinamobileltd.com/en/ir/reports/ar2023/sd2023.pdf",
        "source_type": "official_sustainability_report", "publisher": "China Mobile Limited",
        "comparative_evidence": {
            "FY2021": {"4g_base_stations": {"value": 3.32, "unit": "million_base_stations", "locator": "network scale performance table"}},
            "FY2022": {"4g_base_stations": {"value": 3.34, "unit": "million_base_stations", "locator": "network scale performance table"}},
            "FY2023": {"4g_base_stations": {"value": 3.37, "unit": "million_base_stations", "locator": "network scale performance table"}},
        },
    },
    "china_mobile_sd_2024": {
        "source_id": "china_mobile_sd_2024", "operator_id": "china_mobile", "year": 2024,
        "label": "China Mobile 2024 sustainability report",
        "url": "https://www.chinamobileltd.com/tc/ir/reports/ar2024/sd2024.pdf",
        "source_type": "official_sustainability_report", "publisher": "China Mobile Limited",
        "comparative_evidence": {
            "FY2022": {"4g_base_stations": {"value": 3.34, "unit": "million_base_stations", "locator": "network scale performance table"}},
            "FY2023": {"4g_base_stations": {"value": 3.37, "unit": "million_base_stations", "locator": "network scale performance table"}},
            "FY2024": {"4g_base_stations": {"value": 3.39, "unit": "million_base_stations", "comparator": ">", "locator": "network scale performance table"}},
        },
    },
    "china_mobile_ar_a_2025": {
        "source_id": "china_mobile_ar_a_2025", "operator_id": "china_mobile", "year": 2025,
        "label": "China Mobile 2025 A-share annual report",
        "url": "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-03-27/600941_20260327_EIXS.pdf",
        "source_type": "official_a_share_annual_report", "publisher": "China Mobile Limited",
    },
    "china_mobile_ar_summary_2025": {
        "source_id": "china_mobile_ar_summary_2025", "operator_id": "china_mobile", "year": 2025,
        "label": "China Mobile 2025 A-share annual report summary",
        "url": "https://dataclouds.cninfo.com.cn/shgonggao/hsomarket/2026/20260326/73569fff33d04e62bf68fe56c4599249.PDF",
        "source_type": "official_a_share_annual_report_summary", "publisher": "China Mobile Limited",
    },
    "china_mobile_ar_summary_2022": {
        "source_id": "china_mobile_ar_summary_2022", "operator_id": "china_mobile", "year": 2022,
        "label": "China Mobile 2022 A-share annual report summary",
        "url": "https://www.chinamobileltd.com/sc/ir/sse_filings/sca230324a.pdf",
        "source_type": "official_a_share_annual_report_summary", "publisher": "China Mobile Limited",
        "evidence": {
            "total_base_stations": {"value": 6.0, "unit": "million_base_stations", "comparator": ">=", "locator": "infrastructure section; total commissioned base stations exceeded 6 million"},
        },
    },
    "china_mobile_ar_summary_2023": {
        "source_id": "china_mobile_ar_summary_2023", "operator_id": "china_mobile", "year": 2023,
        "label": "China Mobile 2023 A-share annual report summary",
        "url": "https://www.chinamobileltd.com/sc/ir/sse_filings/sca240322a.pdf",
        "source_type": "official_a_share_annual_report_summary", "publisher": "China Mobile Limited",
        "evidence": {
            "total_base_stations": {"value": 6.60, "unit": "million_base_stations", "comparator": ">=", "locator": "infrastructure section; total commissioned base stations exceeded 6.60 million"},
        },
    },
    "china_mobile_press_2025": {
        "source_id": "china_mobile_press_2025", "operator_id": "china_mobile", "year": 2025,
        "label": "China Mobile 2025 annual results press release",
        "url": "https://www.chinamobileltd.com/en/media/press/p260326.pdf",
        "source_type": "official_results_press_release", "publisher": "China Mobile Limited",
    },
    "china_mobile_q1_2026_comparatives": {
        "source_id": "china_mobile_q1_2026_comparatives", "operator_id": "china_mobile", "year": 2025,
        "label": "China Mobile 2026 first-quarter results with FY2025 comparatives",
        "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0420/2026042001454.pdf",
        "source_type": "official_quarterly_results_announcement", "publisher": "China Mobile Limited",
    },
    "china_telecom_announcement_2025": {
        "source_id": "china_telecom_announcement_2025", "operator_id": "china_telecom", "year": 2025,
        "label": "China Telecom 2025 annual results announcement",
        "url": "https://doc.irasia.com/listco/hk/chinatelecom/annual/2025/res.pdf",
        "source_type": "official_results_announcement", "publisher": "China Telecom Corporation Limited",
    },
    "china_telecom_press_2025": {
        "source_id": "china_telecom_press_2025", "operator_id": "china_telecom", "year": 2025,
        "label": "China Telecom 2025 annual results press release",
        "url": "https://www.chinatelecom-h.com/en/media/press/p260324.pdf",
        "source_type": "official_results_press_release", "publisher": "China Telecom Corporation Limited",
    },
    "china_telecom_factsheet_2025": {
        "source_id": "china_telecom_factsheet_2025", "operator_id": "china_telecom", "year": 2025,
        "label": "China Telecom April 2026 investor factsheet with FY2025 operating KPIs",
        "url": "https://www.chinatelecom-h.com/en/ir/factsheet/factsheet2604.pdf",
        "source_type": "official_investor_factsheet", "publisher": "China Telecom Corporation Limited",
    },
    "china_telecom_q4_operating_announcement_2025": {
        "source_id": "china_telecom_q4_operating_announcement_2025", "operator_id": "china_telecom", "year": 2025,
        "label": "China Telecom key operating statistics for the fourth quarter of 2025",
        "url": "https://doc.irasia.com/listco/hk/chinatelecom/announcement/ca260324.pdf",
        "source_type": "official_hkex_operating_announcement", "publisher": "China Telecom Corporation Limited",
    },
    "china_unicom_press_2025": {
        "source_id": "china_unicom_press_2025", "operator_id": "china_unicom", "year": 2025,
        "label": "China Unicom 2025 annual results press release",
        "url": "https://www.chinaunicom.com.hk/en/media/press/p260319.pdf",
        "source_type": "official_results_press_release", "publisher": "China Unicom (Hong Kong) Limited",
    },
    "china_unicom_q4_operating_announcement_2025": {
        "source_id": "china_unicom_q4_operating_announcement_2025", "operator_id": "china_unicom", "year": 2025,
        "label": "China Unicom operational statistics for the fourth quarter of 2025",
        "url": "https://www.hkexnews.hk/listedco/listconews/sehk/2026/0319/2026031900251.pdf",
        "source_type": "official_hkex_operating_announcement", "publisher": "China Unicom (Hong Kong) Limited",
    },
    "airtel_2019_five_year": {
        "source_id": "airtel_2019_five_year", "operator_id": "bharti_airtel", "year": 2019,
        "label": "Bharti Airtel FY2018-19 five-year performance highlights",
        "url": "https://www.airtel.in/airtel-annual-report-2018-19/performance-highlight.php",
        "source_type": "official_five_year_summary", "publisher": "Bharti Airtel Limited",
    },
    "airtel_2024_five_year": {
        "source_id": "airtel_2024_five_year", "operator_id": "bharti_airtel", "year": 2024,
        "label": "Bharti Airtel FY2023-24 integrated report five-year KPI",
        "url": "https://assets.airtel.in/static-assets/cms/investor/docs/annual_results_2023_24/Integrated_Report_and_Financial_Statements_Single_view.pdf",
        "source_type": "official_five_year_summary", "publisher": "Bharti Airtel Limited",
    },
    "airtel_2025_ir_pack": {
        "source_id": "airtel_2025_ir_pack", "operator_id": "bharti_airtel", "year": 2025,
        "label": "Bharti Airtel FY2025-26 Q4 investor relations pack (comparatives)",
        "url": "https://assets.airtel.in/static-assets/cms/investor/docs/quarterly_results/2025-26/Q4/Quarterly-IR-Pack-Bharti-Airtel-Consolidated.pdf",
        "source_type": "official_results_presentation", "publisher": "Bharti Airtel Limited",
        "evidence": {
            "total_customers": {"value": 590.514, "unit": "million_customers", "locator": "performance at a glance, page 4"},
            "revenue": {"value": 1815110, "unit": "INR_million", "locator": "FY2025 comparative consolidated financials, pages 4 and 8"},
            "ebitda": {"value": 1049994, "unit": "INR_million", "locator": "FY2025 comparative consolidated financials, pages 4 and 8"},
            "earnings_before_tax": {"value": 369712, "unit": "INR_million", "locator": "FY2025 comparative consolidated financials, pages 4 and 11"},
            "net_profit": {"value": 337440, "unit": "INR_million", "locator": "FY2025 net income after exceptional items, pages 4 and 8"},
            "capex": {"value": 422904, "unit": "INR_million", "locator": "FY2025 comparative consolidated financials, pages 4 and 8"},
            "net_debt": {"value": 2038384, "unit": "INR_million", "locator": "FY2025 comparative net debt, page 8"},
            "shareholders_equity": {"value": 1136718, "unit": "INR_million", "locator": "FY2025 comparative statement of financial position"},
            "network_towers": {"value": 375146, "unit": "sites", "locator": "performance at a glance, page 4"},
        },
    },
    "airtel_q1_2026_ir_pack": {
        "source_id": "airtel_q1_2026_ir_pack", "operator_id": "bharti_airtel", "year": 2025,
        "label": "Bharti Airtel FY2025-26 Q1 investor relations pack with FY2025 comparatives",
        "url": "https://assets.airtel.in/static-assets/cms/investor/docs/quarterly_results/2025-26/Q1/Quarterly_IR_Pack_Bharti_Airtel_Consolidated.pdf",
        "source_type": "official_results_presentation", "publisher": "Bharti Airtel Limited",
        "evidence": {
            "total_customers": {"value": 590.514, "unit": "million_customers", "locator": "performance at a glance, page 4"},
            "revenue": {"value": 1815110, "unit": "INR_million", "locator": "performance at a glance, page 4"},
            "ebitda": {"value": 1049994, "unit": "INR_million", "locator": "performance at a glance, page 4"},
            "earnings_before_tax": {"value": 369712, "unit": "INR_million", "locator": "performance at a glance, page 4"},
            "net_profit": {"value": 337440, "unit": "INR_million", "locator": "net income after exceptional items, page 4"},
            "capex": {"value": 422904, "unit": "INR_million", "locator": "performance at a glance, page 4"},
            "net_debt": {"value": 2038384, "unit": "INR_million", "locator": "performance at a glance, page 4"},
            "shareholders_equity": {"value": 1136718, "unit": "INR_million", "locator": "performance at a glance, page 4"},
            "network_towers": {"value": 375146, "unit": "sites", "locator": "performance at a glance, page 4"},
        },
    },
    "airtel_q2_2026_ir_pack": {
        "source_id": "airtel_q2_2026_ir_pack", "operator_id": "bharti_airtel", "year": 2025,
        "label": "Bharti Airtel FY2025-26 Q2 investor relations pack with FY2025 comparatives",
        "url": "https://assets.airtel.in/static-assets/cms/investor/docs/quarterly_results/2025-26/Q2/Quarterly-IR-Pack-Bharti-Airtel-Consolidated.pdf",
        "source_type": "official_results_presentation", "publisher": "Bharti Airtel Limited",
        "evidence": {
            "total_customers": {"value": 590.514, "unit": "million_customers", "locator": "performance at a glance, page 4"},
            "revenue": {"value": 1815110, "unit": "INR_million", "locator": "performance at a glance, page 4"},
            "ebitda": {"value": 1049994, "unit": "INR_million", "locator": "performance at a glance, page 4"},
            "earnings_before_tax": {"value": 369712, "unit": "INR_million", "locator": "performance at a glance, page 4"},
            "net_profit": {"value": 337440, "unit": "INR_million", "locator": "net income after exceptional items, page 4"},
            "capex": {"value": 422904, "unit": "INR_million", "locator": "performance at a glance, page 4"},
            "net_debt": {"value": 2038384, "unit": "INR_million", "locator": "performance at a glance, page 4"},
            "shareholders_equity": {"value": 1136718, "unit": "INR_million", "locator": "performance at a glance, page 4"},
            "network_towers": {"value": 375146, "unit": "sites", "locator": "performance at a glance, page 4"},
        },
    },
    "airtel_q3_2026_ir_pack": {
        "source_id": "airtel_q3_2026_ir_pack", "operator_id": "bharti_airtel", "year": 2025,
        "label": "Bharti Airtel FY2025-26 Q3 investor relations pack with FY2023-FY2025 comparatives",
        "url": "https://assets.airtel.in/static-assets/cms/investor/docs/quarterly_results/2025-26/q3/Quarterly-IR-Pack-Bharti-Airtel-Consolidated.pdf",
        "source_type": "official_results_presentation", "publisher": "Bharti Airtel Limited",
    },
    "airtel_q1_2024_ir_pack": {
        "source_id": "airtel_q1_2024_ir_pack", "operator_id": "bharti_airtel", "year": 2024,
        "label": "Bharti Airtel FY2023-24 Q1 investor relations pack with FY2021-FY2022 comparatives",
        "url": "https://assets.airtel.in/teams/simplycms/ADTECH/docs/Quarterly_IR_Pack_BA_Consolidated_june2023.pdf",
        "source_type": "official_results_presentation", "publisher": "Bharti Airtel Limited",
    },
    "airtel_q2_2024_ir_pack": {
        "source_id": "airtel_q2_2024_ir_pack", "operator_id": "bharti_airtel", "year": 2024,
        "label": "Bharti Airtel FY2023-24 Q2 investor relations pack with FY2021-FY2022 comparatives",
        "url": "https://assets.airtel.in/teams/simplycms/ADTECH/docs/quarterly_ir_pack_consolidated_31102023.pdf",
        "source_type": "official_results_presentation", "publisher": "Bharti Airtel Limited",
    },
    "airtel_q3_2024_ir_pack": {
        "source_id": "airtel_q3_2024_ir_pack", "operator_id": "bharti_airtel", "year": 2024,
        "label": "Bharti Airtel FY2023-24 Q3 investor relations pack with FY2021-FY2022 comparatives",
        "url": "https://assets.airtel.in/teams/simplycms/ADTECH/docs/Q3_FY24_Quarterly_IR_Pack_Consolidated.pdf",
        "source_type": "official_results_presentation", "publisher": "Bharti Airtel Limited",
    },
    "airtel_q4_2024_ir_pack": {
        "source_id": "airtel_q4_2024_ir_pack", "operator_id": "bharti_airtel", "year": 2024,
        "label": "Bharti Airtel FY2023-24 Q4 investor relations pack with FY2021-FY2022 comparatives",
        "url": "https://assets.airtel.in/static-assets/cms/investor/docs/quarterly_results/2023_24/Q4/Quarterly_IR_Pack_Bharti_Airtel_Consolidated.pdf",
        "source_type": "official_results_presentation", "publisher": "Bharti Airtel Limited",
    },
    "airtel_q1_2023_ir_pack": {
        "source_id": "airtel_q1_2023_ir_pack", "operator_id": "bharti_airtel", "year": 2023,
        "label": "Bharti Airtel FY2022-23 Q1 investor relations pack with FY2020 comparatives",
        "url": "https://assets.airtel.in/teams/simplycms/web/docs/Quarterly-IR-Pack-Bharti-Airtel-Consolidated.pdf",
        "source_type": "official_results_presentation", "publisher": "Bharti Airtel Limited",
    },
    "airtel_q2_2023_ir_pack": {
        "source_id": "airtel_q2_2023_ir_pack", "operator_id": "bharti_airtel", "year": 2023,
        "label": "Bharti Airtel FY2022-23 Q2 board-outcome investor pack with FY2020 comparatives",
        "url": "https://assets.airtel.in/teams/simplycms/web/docs/BM-Outcome-October-31-2022-140123.pdf",
        "source_type": "official_results_presentation", "publisher": "Bharti Airtel Limited",
    },
    "airtel_q3_2023_ir_pack": {
        "source_id": "airtel_q3_2023_ir_pack", "operator_id": "bharti_airtel", "year": 2023,
        "label": "Bharti Airtel FY2022-23 Q3 investor relations pack with FY2020 comparatives",
        "url": "https://assets.airtel.in/teams/simplycms/web/docs/quarterly-ir-pack-bharti-airtel-consolidated-07022023.pdf",
        "source_type": "official_results_presentation", "publisher": "Bharti Airtel Limited",
    },
    "airtel_q4_2019_ir_pack": {
        "source_id": "airtel_q4_2019_ir_pack", "operator_id": "bharti_airtel", "year": 2019,
        "label": "Bharti Airtel FY2018-19 Q4 and full-year investor relations pack",
        "url": "https://assets.airtel.in/static-assets/cms/investor/docs/bsy/iportal/images/Quarterly-Report-Q4-FY19_2407E1EBDDC5228CFED54A15BF96772C.pdf",
        "source_type": "official_results_presentation", "publisher": "Bharti Airtel Limited",
        "evidence": {
            "revenue": {"value": 807802, "unit": "INR_million", "locator": "full-year consolidated statement of operations, page 6"},
            "ebitda": {"value": 262937, "unit": "INR_million", "locator": "full-year consolidated statement of operations, page 6"},
            "net_profit": {"value": 4095, "unit": "INR_million", "locator": "full-year consolidated statement of operations, page 6"},
            "capex": {"value": 287427, "unit": "INR_million", "locator": "full-year consolidated capex, page 6"},
            "mobile_broadband_base_stations": {"value": 417613, "unit": "base_stations", "locator": "India mobile operating review, page 25"},
            "total_data_traffic": {"value": 11.733, "unit": "billion_GB", "locator": "India mobile full-year data traffic, page 25; converted from 11,733bn MB"},
        },
    },
    "airtel_q4_2018_ir_pack": {
        "source_id": "airtel_q4_2018_ir_pack", "operator_id": "bharti_airtel", "year": 2018,
        "label": "Bharti Airtel FY2017-18 Q4 and full-year investor relations pack",
        "url": "https://assets.airtel.in/static-assets/cms/investor/docs/bsy/iportal/images/Quarterly-Report-Q4FY18_E7BCAFF7FF854F1485F4E1BD1CEEE04F.pdf",
        "source_type": "official_results_presentation", "publisher": "Bharti Airtel Limited",
        "evidence": {
            "total_customers": {"value": 413.822, "unit": "million_customers", "locator": "FY2018 performance-at-a-glance"},
            "ebitda": {"value": 304479, "unit": "INR_million", "locator": "FY2018 performance-at-a-glance"},
            "capex": {"value": 268176, "unit": "INR_million", "locator": "FY2018 performance-at-a-glance"},
            "network_towers": {"value": 187541, "unit": "sites", "locator": "FY2018 group KPI performance-at-a-glance"},
        },
    },
    "airtel_q4_2017_ir_pack": {
        "source_id": "airtel_q4_2017_ir_pack", "operator_id": "bharti_airtel", "year": 2017,
        "label": "Bharti Airtel FY2016-17 Q4 and full-year investor relations pack",
        "url": "https://assets.airtel.in/static-assets/cms/investor/docs/bsy/iportal/images/Quarterly-Report_Q4FY17_v1_26E1845963512A6EA80F781D752B6F6A_1518159193004.pdf",
        "source_type": "official_results_presentation", "publisher": "Bharti Airtel Limited",
        "evidence": {
            "total_customers": {"value": 372.354, "unit": "million_customers", "locator": "FY2017 performance-at-a-glance, page 4"},
            "revenue": {"value": 954684, "unit": "INR_million", "locator": "FY2017 original performance-at-a-glance; superseded by later comparable 942,506"},
            "ebitda": {"value": 356208, "unit": "INR_million", "locator": "FY2017 performance-at-a-glance, page 4"},
            "earnings_before_tax": {"value": 88929, "unit": "INR_million", "locator": "FY2017 profit-before-tax before exceptional items, page 4; different from annual KPI EBT"},
            "net_profit": {"value": 37997, "unit": "INR_million", "locator": "FY2017 performance-at-a-glance, page 4"},
            "capex": {"value": 198745, "unit": "INR_million", "locator": "FY2017 performance-at-a-glance, page 4"},
            "net_debt": {"value": 913999, "unit": "INR_million", "locator": "FY2017 performance-at-a-glance, page 4"},
            "shareholders_equity": {"value": 674563, "unit": "INR_million", "locator": "FY2017 performance-at-a-glance, page 4"},
            "network_towers": {"value": 184255, "unit": "sites", "locator": "FY2017 group KPI performance-at-a-glance, page 4"},
            "mobile_broadband_base_stations": {"value": 190860, "unit": "base_stations", "locator": "India network and coverage trends, page 55"},
        },
    },
    "airtel_q4_2016_ir_pack": {
        "source_id": "airtel_q4_2016_ir_pack", "operator_id": "bharti_airtel", "year": 2016,
        "label": "Bharti Airtel FY2015-16 Q4 and full-year investor relations pack",
        "url": "https://assets.airtel.in/static-assets/cms/investor/docs/bsy/iportal/images/Quarterly-Report_Q4FY16_888E9E8BA8B6D373CBB53F526F3F4357.pdf",
        "source_type": "official_results_presentation", "publisher": "Bharti Airtel Limited",
        "evidence": {
            "total_customers": {"value": 357.428, "unit": "million_customers", "locator": "FY2016 performance-at-a-glance"},
            "capex": {"value": 205919, "unit": "INR_million", "locator": "FY2016 performance-at-a-glance"},
            "net_debt": {"value": 835106, "unit": "INR_million", "locator": "FY2016 performance-at-a-glance"},
            "shareholders_equity": {"value": 667693, "unit": "INR_million", "locator": "FY2016 performance-at-a-glance"},
            "network_towers": {"value": 181376, "unit": "sites", "locator": "FY2016 group KPI performance-at-a-glance"},
            "mobile_broadband_base_stations": {"value": 118197, "unit": "base_stations", "locator": "India mobile network and coverage trends"},
        },
    },
    "airtel_q1_2017_ir_pack": {
        "source_id": "airtel_q1_2017_ir_pack", "operator_id": "bharti_airtel", "year": 2016,
        "label": "Bharti Airtel FY2016-17 Q1 investor relations pack with March 2016 comparatives",
        "url": "https://assets.airtel.in/static-assets/cms/investor/docs/bsy/iportal/images/Quarterly-Report_Q1-FY17_380EA153EE667A65F7A9E10B6FDB8A60_1518162263552.pdf",
        "source_type": "official_results_presentation", "publisher": "Bharti Airtel Limited",
        "comparative_evidence": {
            "FY2016": {
                "mobile_broadband_base_stations": {"value": 118197, "unit": "base_stations", "locator": "March 2016 India mobile network and coverage comparative"},
            },
        },
    },
    "airtel_q4_2020_ir_pack": {
        "source_id": "airtel_q4_2020_ir_pack", "operator_id": "bharti_airtel", "year": 2020,
        "label": "Bharti Airtel FY2019-20 Q4 investor relations pack with FY2019 comparatives",
        "url": "https://assets.airtel.in/teams/simplycms/web/pdf/Quarterly_IR_Pack_Bharti_Airtel_Consolidated2_19052020.pdf",
        "source_type": "official_results_presentation", "publisher": "Bharti Airtel Limited",
    },
    "airtel_q1_2021_ir_pack": {
        "source_id": "airtel_q1_2021_ir_pack", "operator_id": "bharti_airtel", "year": 2021,
        "label": "Bharti Airtel FY2020-21 Q1 investor relations pack with FY2019 comparatives",
        "url": "https://assets.airtel.in/teams/simplycms/web/docs/Quarterly_IR_Pack_Bharti_Airtel_Consolidated29072020.pdf",
        "source_type": "official_results_presentation", "publisher": "Bharti Airtel Limited",
    },
    "airtel_q2_2022_ir_pack": {
        "source_id": "airtel_q2_2022_ir_pack", "operator_id": "bharti_airtel", "year": 2022,
        "label": "Bharti Airtel FY2021-22 Q2 investor relations pack with FY2019 comparatives",
        "url": "https://assets.airtel.in/teams/simplycms/web/docs/quarterly-ir-pack-bharti-airtel-consolidated-nov-21121.pdf",
        "source_type": "official_results_presentation", "publisher": "Bharti Airtel Limited",
    },
    "jio_2018_q4_media_release": {
        "source_id": "jio_2018_q4_media_release", "operator_id": "reliance_jio", "year": 2018,
        "label": "RIL FY2017-18 Q4 annual results media release",
        "url": "https://www.ril.com/sites/default/files/2023-01/RIL-Media-Release-4Q-FY-1718%20%281%29.pdf",
        "source_type": "official_results_media_release", "publisher": "Reliance Industries Limited",
        "evidence": {
            "total_customers": {"value": 186.6, "unit": "million_customers", "locator": "Digital Services business table, page 11"},
            "value_of_sales_and_services": {"value": 23916, "unit": "INR_crore", "locator": "Digital Services segment revenue, page 11"},
            "ebit": {"value": 3174, "unit": "INR_crore", "locator": "Digital Services segment EBIT, page 11"},
            "churn": {"value": 0.25, "unit": "percent_per_month", "locator": "Digital Services results summary and customer growth, page 11"},
        },
        "comparative_evidence": {
            "FY2017": {
                "total_customers": {"value": 108.9, "unit": "million_customers", "locator": "Digital Services business table, FY2017 comparative column, page 11"},
            }
        },
    },
    "jio_2018_standalone_media_release": {
        "source_id": "jio_2018_standalone_media_release", "operator_id": "reliance_jio", "year": 2018,
        "label": "Reliance Jio Infocomm FY2017-18 Q4 standalone media release",
        "url": "https://www.ril.com/sites/default/files/2023-01/Jio-Media-Release-4Q-FY-1718.pdf",
        "source_type": "official_subsidiary_results_release", "publisher": "Reliance Jio Infocomm Limited",
        "evidence": {
            "churn": {"value": 0.25, "unit": "percent_per_month", "locator": "quarter highlights and customer growth, page 1"},
        },
    },
    "reliance_sustainability_2018": {
        "source_id": "reliance_sustainability_2018", "operator_id": "reliance_jio", "year": 2018,
        "label": "Reliance Industries FY2017-18 sustainability report",
        "url": "https://www.ril.com/sites/default/files/2023-11/RILs-Sustainability-Report-2017-18.pdf",
        "source_type": "official_sustainability_report", "publisher": "Reliance Industries Limited",
        "evidence": {
            "churn": {"value": 0.25, "unit": "percent_per_month", "locator": "customer satisfaction performance table, page 47"},
        },
    },
    "jio_2019_q4_analyst_presentation": {
        "source_id": "jio_2019_q4_analyst_presentation", "operator_id": "reliance_jio", "year": 2019,
        "label": "RIL FY2018-19 Q4 analyst presentation",
        "url": "https://www.ril.com/sites/default/files/2022-12/RIL-4Q-FY19-Analyst-Presentation-18Apr19.pdf",
        "source_type": "official_results_presentation", "publisher": "Reliance Industries Limited",
        "evidence": {
            "total_customers": {"value": 306.7, "unit": "million_customers", "locator": "Digital Services segment performance"},
            "mobile_arpu": {"value": 126.2, "unit": "INR_per_user_month", "locator": "subscriber engagement KPI table"},
            "mobile_dou": {"value": 10.9, "unit": "GB_per_user_month", "locator": "subscriber engagement KPI table"},
        },
    },
    "jio_2019_q4_media_release": {
        "source_id": "jio_2019_q4_media_release", "operator_id": "reliance_jio", "year": 2019,
        "label": "RIL FY2018-19 Q4 annual results media release",
        "url": "https://www.ril.com/sites/default/files/2023-01/Media%20Release%20Q4.pdf",
        "source_type": "official_results_media_release", "publisher": "Reliance Industries Limited",
        "evidence": {
            "total_customers": {"value": 306.7, "unit": "million_customers", "locator": "Digital Services business table"},
            "value_of_sales_and_services": {"value": 46506, "unit": "INR_crore", "locator": "Digital Services segment revenue"},
            "ebit": {"value": 8784, "unit": "INR_crore", "locator": "Digital Services segment EBIT"},
        },
    },
    "jio_2020_rjil_media_release": {
        "source_id": "jio_2020_rjil_media_release", "operator_id": "reliance_jio", "year": 2020,
        "label": "Reliance Jio Infocomm FY2019-20 Q4 media release",
        "url": "https://www.ril.com/sites/default/files/2023-01/RJIL_Media-Release_Mar-20.pdf",
        "source_type": "official_results_media_release", "publisher": "Reliance Jio Infocomm Limited",
        "evidence": {
            "total_customers": {"value": 387.5, "unit": "million_customers", "locator": "Q4 performance highlights, page 1"},
            "mobile_arpu": {"value": 130.6, "unit": "INR_per_user_month", "locator": "Q4 performance highlights, page 1"},
            "mobile_dou": {"value": 11.3, "unit": "GB_per_user_month", "locator": "customer engagement update"},
        },
    },
    "jio_2020_ril_media_release": {
        "source_id": "jio_2020_ril_media_release", "operator_id": "reliance_jio", "year": 2020,
        "label": "RIL FY2019-20 Q4 annual results media release",
        "url": "https://www.ril.com/sites/default/files/2022-12/RIL-Media-Release-4Q-FY-19-20.pdf",
        "source_type": "official_results_media_release", "publisher": "Reliance Industries Limited",
        "evidence": {
            "total_customers": {"value": 387.5, "unit": "million_customers", "locator": "Digital Services business table"},
            "mobile_arpu": {"value": 130.6, "unit": "INR_per_user_month", "locator": "Digital Services operating update"},
            "mobile_dou": {"value": 11.3, "unit": "GB_per_user_month", "locator": "Digital Services customer engagement update"},
        },
    },
    "jio_2021_q4_analyst_presentation": {
        "source_id": "jio_2021_q4_analyst_presentation", "operator_id": "reliance_jio", "year": 2021,
        "label": "RIL FY2020-21 Q4 analyst presentation",
        "url": "https://www.ril.com/sites/default/files/2022-12/RIL-4Q-FY21-Analyst-Presentation-30Apr21.pdf",
        "source_type": "official_results_presentation", "publisher": "Reliance Industries Limited",
        "evidence": {
            "total_customers": {"value": 426.2, "unit": "million_customers", "locator": "RJIL operating metrics table"},
            "mobile_arpu": {"value": 138.2, "unit": "INR_per_user_month", "locator": "RJIL operating metrics table"},
            "mobile_dou": {"value": 13.3, "unit": "GB_per_user_month", "locator": "RJIL operating metrics table"},
            "ebitda": {"value": 34035, "unit": "INR_crore", "locator": "FY2021 consolidated segment EBITDA summary"},
        },
    },
    "jio_rjil_ar_2022": {
        "source_id": "jio_rjil_ar_2022", "operator_id": "reliance_jio", "year": 2022,
        "label": "Reliance Jio Infocomm Limited FY2021-22 annual report",
        "url": "https://www.ril.com/sites/default/files/2023-01/annual-report-of-fy-2021-22.pdf",
        "source_type": "official_subsidiary_annual_report", "publisher": "Reliance Jio Infocomm Limited",
        "evidence": {
            "connected_homes": {"value": 5, "unit": "million_premises", "comparator": ">", "locator": "operations highlights; over 5 million connected homes"},
            "total_data_traffic": {"value": 91.4, "unit": "billion_GB", "locator": "operations highlights; 91.4 exabytes during FY2022"},
        },
    },
    "jio_2025_q4": {
        "source_id": "jio_2025_q4", "operator_id": "reliance_jio", "year": 2025,
        "label": "RIL FY2024-25 Q4 analyst presentation",
        "url": "https://www.ril.com/sites/default/files/2025-04/RIL_4Q_FY25_Analyst_Presentation_25Apr25.pdf",
        "source_type": "official_results_presentation", "publisher": "Reliance Industries Limited",
        "evidence": {
            "total_customers": {"value": 488.2, "unit": "million_customers", "locator": "subscriber and usage KPI table"},
            "mobile_arpu": {"value": 206.2, "unit": "INR_per_user_month", "locator": "subscriber and usage KPI table"},
            "mobile_dou": {"value": 33.6, "unit": "GB_per_user_month", "locator": "subscriber and usage KPI table"},
            "5g_network_subscribers": {"value": 191, "unit": "million_subscribers", "locator": "Jio platform highlights"},
            "connected_homes": {"value": 18, "unit": "million_premises", "comparator": ">", "locator": "home subscribers update"},
        },
        "comparative_evidence": {
            "FY2024": {
                "mobile_dou": {"value": 28.7, "unit": "GB_per_user_month", "locator": "subscriber and usage KPI comparative column"},
            }
        },
    },
    "jio_q1_2025_analyst_presentation": {
        "source_id": "jio_q1_2025_analyst_presentation", "operator_id": "reliance_jio", "year": 2025,
        "label": "RIL FY2024-25 Q1 analyst presentation",
        "url": "https://www.ril.com/sites/default/files/2024-07/RIL_1Q_FY25_Analyst_Presentation_19July24.pdf",
        "source_type": "official_results_presentation", "publisher": "Reliance Industries Limited",
        "evidence": {
            "spectrum_holdings": {"value": 26801, "unit": "MHz_uplink_plus_downlink", "locator": "Jio consolidates leadership in spectrum footprint, page 19"},
        },
    },
    "jio_2024_spectrum_acquisition_release": {
        "source_id": "jio_2024_spectrum_acquisition_release", "operator_id": "reliance_jio", "year": 2025,
        "label": "Jio spectrum acquisition media release, 26 June 2024",
        "url": "https://www.ril.com/sites/default/files/2024-06/26062024_MR_Jio_consolidates_its_leadership_position.pdf",
        "source_type": "official_corporate_media_release", "publisher": "Reliance Jio Infocomm Limited",
        "evidence": {
            "spectrum_holdings": {"value": 26801, "unit": "MHz_uplink_plus_downlink", "locator": "spectrum footprint statement, page 1"},
        },
    },
    "jio_q1_2025_media_release": {
        "source_id": "jio_q1_2025_media_release", "operator_id": "reliance_jio", "year": 2025,
        "label": "RIL FY2024-25 Q1 results media release",
        "url": "https://www.ril.com/sites/default/files/2024-07/19072024-Media-Release-RIL-Q1-FY2024-25-Financial-and-Operational-Performance_0.pdf",
        "source_type": "official_results_media_release", "publisher": "Reliance Industries Limited",
        "evidence": {
            "spectrum_holdings": {"value": 26801, "unit": "MHz_uplink_plus_downlink", "locator": "JPL strategic progress, page 6"},
        },
    },
    "jio_2025_media_release": {
        "source_id": "jio_2025_media_release", "operator_id": "reliance_jio", "year": 2025,
        "label": "RIL FY2024-25 annual results media release",
        "url": "https://www.ril.com/sites/default/files/2025-04/SE_Media_release.pdf",
        "source_type": "official_results_media_release", "publisher": "Reliance Industries Limited",
        "evidence": {
            "total_customers": {"value": 488.2, "unit": "million_customers", "locator": "operational update table, page 6"},
            "mobile_arpu": {"value": 206.2, "unit": "INR_per_user_month", "locator": "operational update table, page 6"},
            "mobile_dou": {"value": 33.6, "unit": "GB_per_user_month", "locator": "operational update narrative, page 6"},
            "total_data_traffic": {"value": 184.5, "unit": "billion_GB", "locator": "operational update table, page 6"},
            "5g_network_subscribers": {"value": 191, "unit": "million_subscribers", "comparator": "~", "locator": "JPL highlights, page 5"},
            "value_of_sales_and_services": {"value": 154119, "unit": "INR_crore", "locator": "consolidated segment information"},
            "ebitda": {"value": 65001, "unit": "INR_crore", "locator": "consolidated segment information"},
        },
        "comparative_evidence": {
            "FY2024": {
                "total_customers": {"value": 481.8, "unit": "million_customers", "locator": "operational update table, page 6"},
                "mobile_arpu": {"value": 181.7, "unit": "INR_per_user_month", "locator": "operational update table, page 6"},
                "total_data_traffic": {"value": 148.5, "unit": "billion_GB", "locator": "operational update table, page 6"},
                "value_of_sales_and_services": {"value": 132938, "unit": "INR_crore", "locator": "consolidated segment information"},
                "ebitda": {"value": 56675, "unit": "INR_crore", "locator": "consolidated segment information"},
            }
        },
    },
    "jio_q1_2026_media_release": {
        "source_id": "jio_q1_2026_media_release", "operator_id": "reliance_jio", "year": 2025,
        "label": "RIL Q1 FY2025-26 results media release with FY2025 comparatives",
        "url": "https://www.ril.com/sites/default/files/2025-07/SE_MR.pdf",
        "source_type": "official_results_media_release", "publisher": "Reliance Industries Limited",
        "evidence": {
            "total_data_traffic": {"value": 184.5, "unit": "billion_GB", "locator": "operational update FY2025 comparative column, page 5"},
        },
    },
    "jio_q2_2026_media_release": {
        "source_id": "jio_q2_2026_media_release", "operator_id": "reliance_jio", "year": 2025,
        "label": "RIL Q2 FY2025-26 results media release with FY2025 comparatives",
        "url": "https://www.ril.com/sites/default/files/2025-10/Media_Release_RIL_Q2_FY2025-26_Financial_and_Operational_Performance.pdf",
        "source_type": "official_results_media_release", "publisher": "Reliance Industries Limited",
        "evidence": {
            "total_data_traffic": {"value": 184.5, "unit": "billion_GB", "locator": "operational update FY2025 comparative column, page 5"},
        },
    },
    "jio_q3_2026_media_release": {
        "source_id": "jio_q3_2026_media_release", "operator_id": "reliance_jio", "year": 2025,
        "label": "RIL Q3 FY2025-26 results media release with FY2025 comparatives",
        "url": "https://www.ril.com/sites/default/files/2026-01/SE_16012026_MR.pdf",
        "source_type": "official_results_media_release", "publisher": "Reliance Industries Limited",
        "evidence": {
            "total_data_traffic": {"value": 184.5, "unit": "billion_GB", "locator": "operational update FY2025 comparative column, page 5"},
        },
    },
    "jio_2025_integrated_financials": {
        "source_id": "jio_2025_integrated_financials", "operator_id": "reliance_jio", "year": 2025,
        "label": "RIL FY2024-25 audited integrated financial filing with FY2024 comparatives",
        "url": "https://www.ril.com/sites/default/files/2025-04/SE_Integrated%20Financials_0.pdf",
        "source_type": "official_stock_exchange_filing", "publisher": "Reliance Industries Limited",
        "comparative_evidence": {
            "FY2024": {
                "value_of_sales_and_services": {"value": 132938, "unit": "INR_crore", "locator": "FY2024 audited comparative in consolidated segment information, page 8"},
                "ebitda": {"value": 56675, "unit": "INR_crore", "locator": "FY2024 audited comparative in consolidated segment information, page 8"},
            }
        },
    },
    "jio_2025_factsheet": {
        "source_id": "jio_2025_factsheet", "operator_id": "reliance_jio", "year": 2025,
        "label": "Jio Platforms factsheet 2025",
        "url": "https://www.ril.com/sites/default/files/2025-09/Jio-Factsheet-2025.pdf",
        "source_type": "official_investor_factsheet", "publisher": "Reliance Industries Limited",
        "evidence": {
            "mobile_arpu": {"value": 206.2, "unit": "INR_per_user_month", "locator": "At a glance"},
            "mobile_dou": {"value": 33.6, "unit": "GB_per_user_month", "locator": "Increasing connectivity"},
            "5g_network_subscribers": {"value": 191, "unit": "million_subscribers", "comparator": ">=", "locator": "Leading 5G adoption"},
            "connected_homes": {"value": 18, "unit": "million_premises", "locator": "Increasing connectivity"},
            "5g_base_stations": {"value": 1, "unit": "million_base_stations", "comparator": ">", "locator": "Leading 5G adoption; disclosed as 5G cells"},
        },
    },
    "jio_q2_2026_integrated_filing": {
        "source_id": "jio_q2_2026_integrated_filing", "operator_id": "reliance_jio", "year": 2025,
        "label": "RIL Q2 FY2025-26 integrated stock-exchange filing with FY2025 comparatives",
        "url": "https://www.ril.com/sites/default/files/2025-10/SE_Integrated_Filing.pdf",
        "source_type": "official_stock_exchange_filing", "publisher": "Reliance Industries Limited",
        "evidence": {
            "value_of_sales_and_services": {"value": 154119, "unit": "INR_crore", "locator": "FY2025 audited comparative in segment information"},
            "ebitda": {"value": 65001, "unit": "INR_crore", "locator": "FY2025 audited comparative in segment information"},
        },
    },
    "jio_2024_factsheet": {
        "source_id": "jio_2024_factsheet", "operator_id": "reliance_jio", "year": 2024,
        "label": "Jio Platforms factsheet 2024",
        "url": "https://www.ril.com/sites/default/files/2024-08/Jio_Factsheet_2024_V2.pdf",
        "source_type": "official_investor_factsheet", "publisher": "Reliance Industries Limited",
        "evidence": {
            "total_customers": {"value": 481.8, "unit": "million_customers", "locator": "At a glance"},
            "value_of_sales_and_services": {"value": 132938, "unit": "INR_crore", "locator": "At a glance"},
            "mobile_arpu": {"value": 181.7, "unit": "INR_per_user_month", "locator": "At a glance"},
            "total_data_traffic": {"value": 148.5, "unit": "billion_GB", "locator": "At a glance"},
            "5g_network_subscribers": {"value": 108, "unit": "million_subscribers", "comparator": ">=", "locator": "Leading 5G adoption"},
            "connected_homes": {"value": 12, "unit": "million_premises", "comparator": ">", "locator": "Increasing connectivity"},
            "5g_base_stations": {"value": 1, "unit": "million_base_stations", "comparator": ">", "locator": "Leading 5G adoption; disclosed as 5G cells"},
        },
    },
    "jio_q2_2024_media_release": {
        "source_id": "jio_q2_2024_media_release", "operator_id": "reliance_jio", "year": 2024,
        "label": "RIL Q2 FY2023-24 results media release",
        "url": "https://www.ril.com/sites/default/files/2023-11/27102023-Media-Release-RIL-Q2-FY2023-24-Financial-and-Operational-Performance.pdf",
        "source_type": "official_results_media_release", "publisher": "Reliance Industries Limited",
        "evidence": {
            "5g_base_stations": {"value": 1, "unit": "million_base_stations", "comparator": ">", "locator": "strategic progress; disclosed as 5G cells"},
        },
        "comparative_evidence": {
            "FY2023": {
                "value_of_sales_and_services": {"value": 119791, "unit": "INR_crore", "locator": "FY2023 audited comparative in consolidated segment information"},
            }
        },
    },
    "jio_2023_q4": {
        "source_id": "jio_2023_q4", "operator_id": "reliance_jio", "year": 2023,
        "label": "RIL FY2022-23 Q4 analyst presentation",
        "url": "https://www.ril.com/sites/default/files/2023-08/RIL-4Q-FY23-Analyst-Presentation-21Apr23_Final.pdf",
        "source_type": "official_results_presentation", "publisher": "Reliance Industries Limited",
        "evidence": {
            "total_customers": {"value": 439.3, "unit": "million_customers", "locator": "RJIL key operating metrics"},
            "mobile_arpu": {"value": 178.8, "unit": "INR_per_user_month", "locator": "RJIL key operating metrics"},
            "mobile_dou": {"value": 23.1, "unit": "GB_per_user_month", "locator": "RJIL key operating metrics"},
            "total_data_traffic": {"value": 113.3, "unit": "billion_GB", "locator": "Digital Services highlights"},
            "ebitda": {"value": 50286, "unit": "INR_crore", "locator": "Digital Services highlights; RIL segment basis"},
            "5g_base_stations": {"value": 0.060, "unit": "million_base_stations", "comparator": "~", "locator": "5G rollout update; disclosed as sites"},
        },
        "comparative_evidence": {
            "FY2022": {
                "total_customers": {"value": 410.2, "unit": "million_customers", "locator": "RJIL key operating metrics comparative column"},
                "mobile_arpu": {"value": 167.6, "unit": "INR_per_user_month", "locator": "RJIL key operating metrics comparative column"},
                "mobile_dou": {"value": 19.7, "unit": "GB_per_user_month", "locator": "RJIL key operating metrics comparative column"},
            }
        },
    },
    "jio_2023_media_release": {
        "source_id": "jio_2023_media_release", "operator_id": "reliance_jio", "year": 2023,
        "label": "RIL FY2022-23 annual results media release",
        "url": "https://rilstaticasset.akamaized.net/sites/default/files/2023-05/Media-Release-RIL-Q4-FY23-21042023-1.pdf",
        "source_type": "official_results_media_release", "publisher": "Reliance Industries Limited",
        "evidence": {
            "total_customers": {"value": 439.3, "unit": "million_customers", "locator": "operational update table"},
            "mobile_arpu": {"value": 178.8, "unit": "INR_per_user_month", "locator": "operational update table"},
            "total_data_traffic": {"value": 113.3, "unit": "billion_GB", "locator": "operational update table"},
            "ebitda": {"value": 50286, "unit": "INR_crore", "locator": "audited consolidated segment information"},
            "5g_base_stations": {"value": 0.060, "unit": "million_base_stations", "comparator": "~", "locator": "strategic progress; disclosed as sites"},
        },
        "comparative_evidence": {
            "FY2022": {
                "total_customers": {"value": 410.2, "unit": "million_customers", "locator": "operational update comparative column"},
                "mobile_arpu": {"value": 167.6, "unit": "INR_per_user_month", "locator": "operational update comparative column"},
                "total_data_traffic": {"value": 91.4, "unit": "billion_GB", "locator": "operational update comparative column"},
            }
        },
    },
    "jio_2024_q4": {
        "source_id": "jio_2024_q4", "operator_id": "reliance_jio", "year": 2024,
        "label": "RIL FY2023-24 Q4 analyst presentation",
        "url": "https://www.ril.com/sites/default/files/2024-04/RIL-4Q-FY24-Analyst-Presentation-22Apr24-website.pdf",
        "source_type": "official_results_presentation", "publisher": "Reliance Industries Limited",
        "comparative_evidence": {
            "FY2023": {
                "mobile_dou": {"value": 23.1, "unit": "GB_per_user_month", "locator": "RJIL key operating metrics comparative column"},
            }
        },
    },
    "jio_2022_q4": {
        "source_id": "jio_2022_q4", "operator_id": "reliance_jio", "year": 2022,
        "label": "RIL FY2021-22 Q4 media release",
        "url": "https://www.ril.com/sites/default/files/2023-01/Media-Release-RIL-Q4FY2021-22-06052022_0.pdf",
        "source_type": "official_results_release", "publisher": "Reliance Industries Limited",
        "evidence": {
            "total_customers": {"value": 410.2, "unit": "million_customers", "locator": "annual performance and operational update"},
            "mobile_arpu": {"value": 167.6, "unit": "INR_per_user_month", "locator": "operational update"},
            "mobile_dou": {"value": 19.7, "unit": "GB_per_user_month", "locator": "operational update"},
            "total_data_traffic": {"value": 91.4, "unit": "billion_GB", "locator": "annual performance"},
            "ebitda": {"value": 40268, "unit": "INR_crore", "locator": "audited consolidated segment information"},
            "connected_homes": {"value": 6, "unit": "million_premises", "comparator": ">", "locator": "operational update"},
        },
    },
})

# Identify the underlying disclosure independently of its hosting URL.  An
# issuer copy, exchange mirror, or archive copy of the same report must count
# as one source document, not several.
for _source_id, _source in SOURCES.items():
    _source.setdefault("source_document_id", _source_id)

# The annual-results landing entry and the direct PDF below resolve to the
# same FY2023-24 integrated report, so they must never count as two documents.
SOURCES["bharti_airtel_ar_2024"]["source_document_id"] = "airtel_integrated_report_fy2024"
SOURCES["airtel_2024_five_year"]["source_document_id"] = "airtel_integrated_report_fy2024"
# The FY2019 performance-highlight page is part of the same FY2018-19
# integrated report as the annual-report landing entry.  Treating them as two
# sources would overstate document independence for FY2019.
SOURCES["bharti_airtel_ar_2019"]["source_document_id"] = "airtel_integrated_report_fy2019"
SOURCES["airtel_2019_five_year"]["source_document_id"] = "airtel_integrated_report_fy2019"
SOURCES["bharti_airtel_ar_2021"]["url"] = "https://assets.airtel.in/teams/simplycms/web/docs/Airtel-Integrated_Report_and_Annual_Financial_Statements_2021.pdf"

AIRTEL_FY2016_ANNUAL_COMPARATIVE_EVIDENCE = {
    "total_customers": {"value": 357.428, "unit": "million_customers", "locator": "five-year consolidated KPI table"},
    "revenue": {"value": 965321, "unit": "INR_million", "locator": "five-year consolidated KPI table; Ind AS comparative"},
    "ebitda": {"value": 341682, "unit": "INR_million", "locator": "five-year consolidated KPI table"},
    "earnings_before_tax": {"value": 128463, "unit": "INR_million", "locator": "five-year annual KPI; after exceptional items"},
    "net_profit": {"value": 60767, "unit": "INR_million", "locator": "five-year consolidated KPI table"},
    "net_debt": {"value": 835106, "unit": "INR_million", "locator": "five-year consolidated KPI table"},
    "shareholders_equity": {"value": 667693, "unit": "INR_million", "locator": "five-year consolidated KPI table"},
}
SOURCES["bharti_airtel_ar_2016"]["evidence"] = {
    "mobile_broadband_base_stations": {"value": 118197, "unit": "base_stations", "locator": "India mobile network review"},
    "total_data_traffic": {"value": 0.597, "unit": "billion_GB", "locator": "corporate overview annual headline; converted from 597bn MB"},
}
SOURCES["bharti_airtel_ar_2017"]["comparative_evidence"] = {
    "FY2016": AIRTEL_FY2016_ANNUAL_COMPARATIVE_EVIDENCE,
}
SOURCES["bharti_airtel_ar_2017"]["evidence"] = {
    "total_data_traffic": {
        "value": 0.903,
        "unit": "billion_GB",
        "locator": "FY2016-17 corporate overview headline; converted from 903bn MB",
    },
}

AIRTEL_FY2017_NETWORK_COMPARATIVE_EVIDENCE = {
    "mobile_broadband_base_stations": {"value": 190860, "unit": "base_stations", "locator": "FY2016-17 India mobile network year-end comparative"},
}
SOURCES["bharti_airtel_ar_2018"].setdefault("comparative_evidence", {})["FY2017"] = AIRTEL_FY2017_NETWORK_COMPARATIVE_EVIDENCE

AIRTEL_FY2017_ANNUAL_COMPARATIVE_EVIDENCE = {
    "total_customers": {"value": 372.354, "unit": "million_customers", "locator": "five-year consolidated KPI table"},
    "revenue": {"value": 942506, "unit": "INR_million", "locator": "five-year consolidated KPI table; later comparable basis"},
    "ebitda": {"value": 356208, "unit": "INR_million", "locator": "five-year consolidated KPI table"},
    "earnings_before_tax": {"value": 77232, "unit": "INR_million", "locator": "five-year annual KPI; after exceptional items"},
    "net_profit": {"value": 37997, "unit": "INR_million", "locator": "five-year consolidated KPI table"},
    "net_debt": {"value": 913999, "unit": "INR_million", "locator": "five-year consolidated KPI table"},
    "shareholders_equity": {"value": 674563, "unit": "INR_million", "locator": "five-year consolidated KPI table"},
}

AIRTEL_FY2019_ANNUAL_EVIDENCE = {
    "revenue": {"value": 807802, "unit": "INR_million", "locator": "FY2018-19 consolidated financial highlights"},
    "ebitda": {"value": 262937, "unit": "INR_million", "locator": "FY2018-19 consolidated financial highlights"},
    "earnings_before_tax": {"value": -17318, "unit": "INR_million", "locator": "FY2018-19 consolidated financial highlights; annual KPI basis"},
    "net_profit": {"value": 4095, "unit": "INR_million", "locator": "FY2018-19 consolidated financial highlights"},
    "mobile_broadband_base_stations": {"value": 417613, "unit": "base_stations", "locator": "manufactured capital, page 49"},
    "total_data_traffic": {"value": 11.733, "unit": "billion_GB", "locator": "manufactured capital, page 49; converted from 11,733bn MB"},
}
SOURCES["bharti_airtel_ar_2019"]["evidence"] = AIRTEL_FY2019_ANNUAL_EVIDENCE

AIRTEL_FY2019_ANNUAL_COMPARATIVE_EVIDENCE = {
    "revenue": {"value": 807802, "unit": "INR_million", "locator": "FY2018-19 comparative consolidated financial highlights"},
    "ebitda": {"value": 262937, "unit": "INR_million", "locator": "FY2018-19 comparative consolidated financial highlights"},
    "earnings_before_tax": {"value": -17318, "unit": "INR_million", "locator": "FY2018-19 comparative annual KPI; before exceptional items"},
    "net_profit": {"value": 4095, "unit": "INR_million", "locator": "FY2018-19 comparative consolidated financial highlights"},
    "mobile_broadband_base_stations": {"value": 417613, "unit": "base_stations", "locator": "FY2018-19 comparative India mobile network review"},
    "total_data_traffic": {"value": 11.733, "unit": "billion_GB", "locator": "FY2018-19 comparative India mobile data chart; converted from 11,733bn MB"},
}
SOURCES["bharti_airtel_ar_2020"]["comparative_evidence"] = {
    "FY2019": AIRTEL_FY2019_ANNUAL_COMPARATIVE_EVIDENCE,
    "FY2017": AIRTEL_FY2017_ANNUAL_COMPARATIVE_EVIDENCE,
    "FY2016": AIRTEL_FY2016_ANNUAL_COMPARATIVE_EVIDENCE,
}
SOURCES["bharti_airtel_ar_2021"]["comparative_evidence"] = {
    "FY2017": AIRTEL_FY2017_ANNUAL_COMPARATIVE_EVIDENCE,
    "FY2020": {
        "mobile_broadband_base_stations": {"value": 503883, "unit": "base_stations", "locator": "FY2019-20 comparative in India mobile network review, pages 154-155"},
        "total_data_traffic": {"value": 21.020, "unit": "billion_GB", "locator": "FY2019-20 comparative in India mobile data-usage chart, pages 154-155; converted from 21,020bn MB"},
    },
}
SOURCES["bharti_airtel_ar_2020"]["evidence"] = {
    **SOURCES["bharti_airtel_ar_2020"].get("evidence", {}),
    "mobile_broadband_base_stations": {
        "value": 503883,
        "unit": "base_stations",
        "locator": "FY2019-20 India mobile network review, year-end installed base",
    },
    "total_data_traffic": {
        "value": 21.020,
        "unit": "billion_GB",
        "locator": "FY2019-20 India mobile data-usage chart; converted from 21,020bn MB",
    },
}
SOURCES["airtel_2024_five_year"].setdefault("comparative_evidence", {})["FY2020"] = {
    "mobile_broadband_base_stations": {
        "value": 503883,
        "unit": "base_stations",
        "locator": "five-year manufactured-capital network KPI comparative",
    },
    "total_data_traffic": {
        "value": 21.020,
        "unit": "billion_GB",
        "locator": "five-year India mobile data-traffic comparative; converted from 21,020bn MB",
    },
}
SOURCES["bharti_airtel_ar_2022"]["comparative_evidence"] = {
    "FY2019": {
        "revenue": {"value": 807802, "unit": "INR_million", "locator": "five-year KPI, page 36"},
        "ebitda": {"value": 262937, "unit": "INR_million", "locator": "five-year KPI, page 36"},
        "earnings_before_tax": {"value": -17318, "unit": "INR_million", "locator": "five-year KPI, page 36; before exceptional items"},
        "net_profit": {"value": 4095, "unit": "INR_million", "locator": "five-year KPI, page 36"},
        "total_customers": {"value": 403.645, "unit": "million_customers", "locator": "five-year KPI, page 36"},
        "net_debt": {"value": 1129899, "unit": "INR_million", "locator": "five-year consolidated financials, page 37; includes finance lease obligations"},
        "shareholders_equity": {"value": 714222, "unit": "INR_million", "locator": "five-year consolidated financials, page 37"},
    }
}

AIRTEL_FY2019_IR_COMPARATIVE_EVIDENCE = {
    "total_customers": {"value": 403.645, "unit": "million_customers", "locator": "FY2019 performance-at-a-glance comparative"},
    "revenue": {"value": 807802, "unit": "INR_million", "locator": "FY2019 performance-at-a-glance comparative"},
    "ebitda": {"value": 262937, "unit": "INR_million", "locator": "FY2019 performance-at-a-glance comparative"},
    "net_profit": {"value": 4095, "unit": "INR_million", "locator": "FY2019 performance-at-a-glance net income"},
    "capex": {"value": 287427, "unit": "INR_million", "locator": "FY2019 performance-at-a-glance comparative"},
    "net_debt": {"value": 1129899, "unit": "INR_million", "locator": "FY2019 comparable net debt including lease obligations"},
    "shareholders_equity": {"value": 714222, "unit": "INR_million", "locator": "FY2019 performance-at-a-glance comparative"},
    "network_towers": {"value": 204356, "unit": "sites", "locator": "FY2019 group KPI performance-at-a-glance comparative"},
}
for _source_id in ("airtel_q4_2020_ir_pack", "airtel_q1_2021_ir_pack"):
    SOURCES[_source_id]["comparative_evidence"] = {
        "FY2019": AIRTEL_FY2019_IR_COMPARATIVE_EVIDENCE
    }
SOURCES["airtel_q2_2022_ir_pack"]["comparative_evidence"] = {
    "FY2019": {
        key: value
        for key, value in AIRTEL_FY2019_IR_COMPARATIVE_EVIDENCE.items()
        if key in {"total_customers", "capex", "net_debt", "shareholders_equity", "network_towers"}
    }
}

AIRTEL_FY2018_ANNUAL_COMPARATIVE_EVIDENCE = {
    "revenue": {"value": 826388, "unit": "INR_million", "locator": "FY2017-18 comparative consolidated financial highlights"},
    "ebitda": {"value": 304479, "unit": "INR_million", "locator": "FY2017-18 comparative consolidated financial highlights"},
    "earnings_before_tax": {"value": 32669, "unit": "INR_million", "locator": "FY2017-18 comparative annual KPI; before exceptional items"},
    "net_profit": {"value": 10990, "unit": "INR_million", "locator": "FY2017-18 comparative consolidated financial highlights"},
    "mobile_broadband_base_stations": {"value": 298014, "unit": "base_stations", "locator": "FY2017-18 comparative India mobile network review"},
    "total_data_traffic": {"value": 3.9018, "unit": "billion_GB", "locator": "FY2017-18 comparative India mobile data chart; converted from 3,901.8bn MB"},
}
SOURCES["bharti_airtel_ar_2019"]["comparative_evidence"] = {
    "FY2018": AIRTEL_FY2018_ANNUAL_COMPARATIVE_EVIDENCE,
    "FY2017": AIRTEL_FY2017_ANNUAL_COMPARATIVE_EVIDENCE,
    "FY2016": AIRTEL_FY2016_ANNUAL_COMPARATIVE_EVIDENCE,
}
SOURCES["bharti_airtel_ar_2019"]["comparative_evidence"]["FY2017"].update(AIRTEL_FY2017_NETWORK_COMPARATIVE_EVIDENCE)
SOURCES["bharti_airtel_ar_2020"]["comparative_evidence"]["FY2018"] = AIRTEL_FY2018_ANNUAL_COMPARATIVE_EVIDENCE
SOURCES["bharti_airtel_ar_2020"]["comparative_evidence"]["FY2017"].update(AIRTEL_FY2017_NETWORK_COMPARATIVE_EVIDENCE)
SOURCES["bharti_airtel_ar_2022"]["comparative_evidence"]["FY2018"] = {
    "revenue": {"value": 826388, "unit": "INR_million", "locator": "five-year KPI, page 36"},
    "ebitda": {"value": 304479, "unit": "INR_million", "locator": "five-year KPI, page 36"},
    "earnings_before_tax": {"value": 32669, "unit": "INR_million", "locator": "five-year KPI, page 36; before exceptional items"},
    "net_profit": {"value": 10990, "unit": "INR_million", "locator": "five-year KPI, page 36"},
    "net_debt": {"value": 1001060, "unit": "INR_million", "locator": "five-year consolidated financials, page 37; includes finance lease obligations"},
    "shareholders_equity": {"value": 695344, "unit": "INR_million", "locator": "five-year consolidated financials, page 37"},
}

AIRTEL_FY2018_IR_COMPARATIVE_EVIDENCE = {
    "total_customers": {"value": 413.822, "unit": "million_customers", "locator": "FY2018 performance-at-a-glance comparative"},
    "revenue": {"value": 826388, "unit": "INR_million", "locator": "FY2018 later comparable performance-at-a-glance"},
    "ebitda": {"value": 304479, "unit": "INR_million", "locator": "FY2018 performance-at-a-glance comparative"},
    "net_profit": {"value": 10990, "unit": "INR_million", "locator": "FY2018 later comparable net income"},
    "capex": {"value": 268176, "unit": "INR_million", "locator": "FY2018 performance-at-a-glance comparative"},
    "net_debt": {"value": 1001060, "unit": "INR_million", "locator": "FY2018 comparable net debt including lease obligations"},
    "shareholders_equity": {"value": 695344, "unit": "INR_million", "locator": "FY2018 later comparable shareholder equity"},
    "network_towers": {"value": 187541, "unit": "sites", "locator": "FY2018 group KPI performance-at-a-glance comparative"},
    "mobile_broadband_base_stations": {"value": 298014, "unit": "base_stations", "locator": "FY2018 India mobile comparative in FY2019 operating review"},
    "total_data_traffic": {"value": 3.9018, "unit": "billion_GB", "locator": "FY2018 India mobile comparative in FY2019 operating review; converted from 3,902bn MB"},
}
SOURCES["airtel_q4_2019_ir_pack"].setdefault("comparative_evidence", {})["FY2018"] = {
    key: value
    for key, value in AIRTEL_FY2018_IR_COMPARATIVE_EVIDENCE.items()
    if key in {"total_customers", "revenue", "ebitda", "net_profit", "capex", "shareholders_equity", "network_towers", "mobile_broadband_base_stations", "total_data_traffic"}
}
for _source_id in ("airtel_q4_2020_ir_pack", "airtel_q1_2021_ir_pack"):
    SOURCES[_source_id]["comparative_evidence"]["FY2018"] = AIRTEL_FY2018_IR_COMPARATIVE_EVIDENCE

AIRTEL_FY2017_IR_COMPARATIVE_EVIDENCE = {
    "total_customers": {"value": 372.354, "unit": "million_customers", "locator": "FY2017 performance-at-a-glance comparative"},
    "ebitda": {"value": 356208, "unit": "INR_million", "locator": "FY2017 performance-at-a-glance comparative"},
    "net_profit": {"value": 37997, "unit": "INR_million", "locator": "FY2017 performance-at-a-glance net income"},
    "capex": {"value": 198745, "unit": "INR_million", "locator": "FY2017 performance-at-a-glance comparative"},
    "net_debt": {"value": 913999, "unit": "INR_million", "locator": "FY2017 performance-at-a-glance comparative"},
    "shareholders_equity": {"value": 674563, "unit": "INR_million", "locator": "FY2017 performance-at-a-glance comparative"},
    "network_towers": {"value": 184255, "unit": "sites", "locator": "FY2017 group KPI performance-at-a-glance comparative"},
}
SOURCES["airtel_q4_2018_ir_pack"].setdefault("comparative_evidence", {})["FY2017"] = AIRTEL_FY2017_IR_COMPARATIVE_EVIDENCE
SOURCES["airtel_q4_2018_ir_pack"]["comparative_evidence"]["FY2017"].update(AIRTEL_FY2017_NETWORK_COMPARATIVE_EVIDENCE)
SOURCES["airtel_q4_2019_ir_pack"].setdefault("comparative_evidence", {})["FY2017"] = {
    **AIRTEL_FY2017_IR_COMPARATIVE_EVIDENCE,
    "revenue": {"value": 942506, "unit": "INR_million", "locator": "FY2017 later comparable performance-at-a-glance"},
    "earnings_before_tax": {"value": 88929, "unit": "INR_million", "locator": "FY2017 profit-before-tax before exceptional items; different from annual KPI EBT"},
}

AIRTEL_FY2016_IR_COMPARATIVE_EVIDENCE = {
    "total_customers": {"value": 357.428, "unit": "million_customers", "locator": "FY2016 performance-at-a-glance comparative"},
    "capex": {"value": 205919, "unit": "INR_million", "locator": "FY2016 performance-at-a-glance comparative"},
    "net_debt": {"value": 835106, "unit": "INR_million", "locator": "FY2016 performance-at-a-glance comparative"},
    "shareholders_equity": {"value": 667693, "unit": "INR_million", "locator": "FY2016 performance-at-a-glance comparative"},
    "network_towers": {"value": 181376, "unit": "sites", "locator": "FY2016 group KPI performance-at-a-glance comparative"},
}
SOURCES["airtel_q4_2017_ir_pack"].setdefault("comparative_evidence", {})["FY2016"] = AIRTEL_FY2016_IR_COMPARATIVE_EVIDENCE
SOURCES["airtel_q4_2018_ir_pack"].setdefault("comparative_evidence", {})["FY2016"] = AIRTEL_FY2016_IR_COMPARATIVE_EVIDENCE

AIRTEL_FY2024_COMPARATIVE_EVIDENCE = {
    "total_customers": {"value": 561.970, "unit": "million_customers", "locator": "FY2024 comparative, performance at a glance, page 4"},
    "revenue": {"value": 1643643, "unit": "INR_million", "locator": "FY2024 comparative, performance at a glance, page 4"},
    "ebitda": {"value": 889064, "unit": "INR_million", "locator": "FY2024 comparative, performance at a glance, page 4"},
    "earnings_before_tax": {"value": 250532, "unit": "INR_million", "locator": "FY2024 comparative, performance at a glance, page 4"},
    "net_profit": {"value": 77820, "unit": "INR_million", "locator": "FY2024 net income after exceptional items, performance at a glance, page 4"},
    "capex": {"value": 489268, "unit": "INR_million", "locator": "FY2024 comparative, performance at a glance, page 4"},
    "net_debt": {"value": 1943799, "unit": "INR_million", "locator": "FY2024 comparative, performance at a glance, page 4"},
    "shareholders_equity": {"value": 820188, "unit": "INR_million", "locator": "FY2024 comparative, performance at a glance, page 4"},
    "network_towers": {"value": 355150, "unit": "sites", "locator": "FY2024 comparative, performance at a glance, page 4"},
}
SOURCES["airtel_q3_2026_ir_pack"]["evidence"] = {
    _metric_key: dict(_evidence)
    for _metric_key, _evidence in SOURCES["airtel_q2_2026_ir_pack"]["evidence"].items()
}
for _source_id in ("airtel_q1_2026_ir_pack", "airtel_q2_2026_ir_pack", "airtel_q3_2026_ir_pack", "airtel_2025_ir_pack"):
    SOURCES[_source_id]["comparative_evidence"] = {
        "FY2024": AIRTEL_FY2024_COMPARATIVE_EVIDENCE
    }

AIRTEL_FY2023_COMPARATIVE_EVIDENCE = {
    "total_customers": {"value": 518.446, "unit": "million_customers", "locator": "FY2023 comparative, performance at a glance, page 4"},
    "revenue": {"value": 1539257, "unit": "INR_million", "locator": "FY2023 recast comparative, performance at a glance, page 4"},
    "ebitda": {"value": 768378, "unit": "INR_million", "locator": "FY2023 recast comparative, performance at a glance, page 4"},
    "earnings_before_tax": {"value": 185701, "unit": "INR_million", "locator": "FY2023 recast comparative, performance at a glance, page 4"},
    "net_profit": {"value": 82526, "unit": "INR_million", "locator": "FY2023 net income after exceptional items, performance at a glance, page 4"},
    "capex": {"value": 382145, "unit": "INR_million", "locator": "FY2023 recast comparative, performance at a glance, page 4"},
    "net_debt": {"value": 2042234, "unit": "INR_million", "locator": "FY2023 recast comparative, performance at a glance, page 4"},
    "shareholders_equity": {"value": 775629, "unit": "INR_million", "locator": "FY2023 comparative, performance at a glance, page 4"},
    "network_towers": {"value": 309054, "unit": "sites", "locator": "FY2023 comparative, performance at a glance, page 4"},
}
for _source_id in ("airtel_q1_2026_ir_pack", "airtel_q2_2026_ir_pack", "airtel_q3_2026_ir_pack"):
    SOURCES[_source_id]["comparative_evidence"]["FY2023"] = AIRTEL_FY2023_COMPARATIVE_EVIDENCE

AIRTEL_FY2022_COMPARATIVE_EVIDENCE = {
    "total_customers": {"value": 489.729, "unit": "million_customers", "locator": "FY2022 comparative, performance at a glance, page 4"},
    "revenue": {"value": 1165469, "unit": "INR_million", "locator": "FY2022 comparative, performance at a glance, page 4"},
    "ebitda": {"value": 581103, "unit": "INR_million", "locator": "FY2022 comparative, performance at a glance, page 4"},
    "earnings_before_tax": {"value": 107845, "unit": "INR_million", "locator": "FY2022 comparative, performance at a glance, page 4"},
    "net_profit": {"value": 42549, "unit": "INR_million", "locator": "FY2022 net income, performance at a glance, page 4"},
    "capex": {"value": 256616, "unit": "INR_million", "locator": "FY2022 comparative, performance at a glance, page 4"},
    "net_debt": {"value": 1603073, "unit": "INR_million", "locator": "FY2022 comparative, performance at a glance, page 4"},
    "shareholders_equity": {"value": 665543, "unit": "INR_million", "locator": "FY2022 comparative, performance at a glance, page 4"},
    "network_towers": {"value": 268848, "unit": "sites", "locator": "FY2022 comparative, performance at a glance, page 4"},
}
AIRTEL_FY2021_COMPARATIVE_EVIDENCE = {
    "total_customers": {"value": 469.864, "unit": "million_customers", "locator": "FY2021 comparative, performance at a glance, page 4"},
    "revenue": {"value": 1006158, "unit": "INR_million", "locator": "FY2021 comparative, performance at a glance, page 4"},
    "ebitda": {"value": 461387, "unit": "INR_million", "locator": "FY2021 comparative, performance at a glance, page 4"},
    "earnings_before_tax": {"value": 22586, "unit": "INR_million", "locator": "FY2021 recast profit before tax, performance at a glance, page 4"},
    "net_profit": {"value": -150835, "unit": "INR_million", "locator": "FY2021 net income after exceptional items, performance at a glance, page 4"},
    "capex": {"value": 241685, "unit": "INR_million", "locator": "FY2021 comparative, performance at a glance, page 4"},
    "net_debt": {"value": 1485076, "unit": "INR_million", "locator": "FY2021 comparative, performance at a glance, page 4"},
    "shareholders_equity": {"value": 589527, "unit": "INR_million", "locator": "FY2021 comparative, performance at a glance, page 4"},
    "network_towers": {"value": 244504, "unit": "sites", "locator": "FY2021 comparative, performance at a glance, page 4"},
}
for _source_id in ("airtel_q1_2024_ir_pack", "airtel_q2_2024_ir_pack", "airtel_q3_2024_ir_pack", "airtel_q4_2024_ir_pack"):
    SOURCES[_source_id]["comparative_evidence"] = {
        "FY2021": AIRTEL_FY2021_COMPARATIVE_EVIDENCE,
        "FY2022": AIRTEL_FY2022_COMPARATIVE_EVIDENCE
    }

AIRTEL_FY2020_IR_COMPARATIVE_EVIDENCE = {
    "revenue": {"value": 846765, "unit": "INR_million", "locator": "FY2020 comparative, performance at a glance, page 3"},
    "ebitda": {"value": 347696, "unit": "INR_million", "locator": "FY2020 comparative, performance at a glance, page 3"},
    "earnings_before_tax": {"value": -44819, "unit": "INR_million", "locator": "FY2020 IR-pack profit before tax, performance at a glance, page 3"},
    "net_profit": {"value": -321832, "unit": "INR_million", "locator": "FY2020 net income, performance at a glance, page 3"},
    "capex": {"value": 244866, "unit": "INR_million", "locator": "FY2020 comparative, performance at a glance, page 3"},
    "net_debt": {"value": 1245209, "unit": "INR_million", "locator": "FY2020 comparative, performance at a glance, page 3"},
    "shareholders_equity": {"value": 771448, "unit": "INR_million", "locator": "FY2020 comparative, performance at a glance, page 3"},
    "network_towers": {"value": 219546, "unit": "sites", "locator": "FY2020 comparative, performance at a glance, page 3"},
}
AIRTEL_FY2020_CUSTOMER_EVIDENCE = {
    "total_customers": {"value": 422.100, "unit": "million_customers", "locator": "FY2020 later comparative total customer base"},
}
SOURCES["airtel_q1_2023_ir_pack"]["comparative_evidence"] = {
    "FY2020": AIRTEL_FY2020_IR_COMPARATIVE_EVIDENCE
}
for _source_id in ("airtel_q2_2023_ir_pack", "airtel_q3_2023_ir_pack"):
    SOURCES[_source_id]["comparative_evidence"] = {
        "FY2020": {**AIRTEL_FY2020_IR_COMPARATIVE_EVIDENCE, **AIRTEL_FY2020_CUSTOMER_EVIDENCE}
    }
SOURCES["bharti_airtel_ar_2023"].setdefault("comparative_evidence", {})["FY2020"] = AIRTEL_FY2020_CUSTOMER_EVIDENCE

SOURCES["bharti_airtel_ar_2025"]["evidence"] = {
    "total_customers": {"value": 590.514, "unit": "million_customers", "locator": "key performance indicators, pages 56-57"},
    "revenue": {"value": 1815110, "unit": "INR_million", "locator": "key performance indicators and financial review"},
    "ebitda": {"value": 1049994, "unit": "INR_million", "locator": "key performance indicators and financial review"},
    "earnings_before_tax": {"value": 369712, "unit": "INR_million", "locator": "key performance indicators and financial review"},
    "net_profit": {"value": 337440, "unit": "INR_million", "locator": "financial review; profit for the year after exceptional items"},
    "net_debt": {"value": 2038384, "unit": "INR_million", "locator": "consolidated key ratios table"},
    "shareholders_equity": {"value": 1136719, "unit": "INR_million", "locator": "consolidated key ratios table; differs by INR1m from later IR packs"},
}

SOURCES["reliance_jio_ar_2025"]["evidence"] = {
    "total_customers": {"value": 488.2, "unit": "million_customers", "locator": "Digital Services business performance"},
    "value_of_sales_and_services": {"value": 154119, "unit": "INR_crore", "locator": "Digital Services financial performance"},
    "revenue_from_operations": {"value": 131336, "unit": "INR_crore", "locator": "Digital Services financial performance"},
    "ebitda": {"value": 65001, "unit": "INR_crore", "locator": "Digital Services financial performance"},
    "mobile_dou": {"value": 33.6, "unit": "GB_per_user_month", "locator": "Digital Services customer engagement"},
    "5g_network_subscribers": {"value": 191, "unit": "million_subscribers", "comparator": "~", "locator": "Digital Services network adoption"},
    "connected_homes": {"value": 18, "unit": "million_premises", "comparator": "~", "locator": "Digital Services homes update"},
    "spectrum_holdings": {"value": 26801, "unit": "MHz_uplink_plus_downlink", "locator": "Digital Services regulatory developments; spectrum footprint"},
}
SOURCES["reliance_jio_ar_2018"].setdefault("evidence", {})["churn"] = {
    "value": 0.25,
    "unit": "percent_per_month",
    "locator": "Digital Services operating review; lowest monthly churn at FY2018 year end",
}
SOURCES["reliance_jio_ar_2025"]["comparative_evidence"] = {
    "FY2024": {
        "value_of_sales_and_services": {"value": 132938, "unit": "INR_crore", "locator": "Digital Services financial performance comparative column"},
        "revenue_from_operations": {"value": 113176, "unit": "INR_crore", "locator": "Digital Services financial performance comparative column"},
        "ebitda": {"value": 56675, "unit": "INR_crore", "locator": "Digital Services financial performance comparative column"},
    }
}
SOURCES["reliance_jio_ar_2024"]["evidence"] = {
    "total_customers": {"value": 481.8, "unit": "million_customers", "locator": "Digital Services headline and business performance"},
    "mobile_arpu": {"value": 181.7, "unit": "INR_per_user_month", "locator": "Digital Services KPI disclosure"},
    "mobile_dou": {"value": 28.7, "unit": "GB_per_user_month", "locator": "Digital Services customer engagement"},
    "total_data_traffic": {"value": 148.5, "unit": "billion_GB", "locator": "Digital Services headline"},
    "5g_network_subscribers": {"value": 108, "unit": "million_subscribers", "comparator": ">", "locator": "Digital Services True5G update"},
    "connected_homes": {"value": 12, "unit": "million_premises", "comparator": "~", "locator": "Digital Services fixed broadband update"},
    "5g_base_stations": {"value": 1, "unit": "million_base_stations", "comparator": ">", "locator": "Manufactured Capital; disclosed as 5G cells"},
}
SOURCES["reliance_jio_ar_2024"]["comparative_evidence"] = {
    "FY2023": {
        "value_of_sales_and_services": {"value": 119791, "unit": "INR_crore", "locator": "Digital Services financial performance comparative column"},
        "revenue_from_operations": {"value": 101961, "unit": "INR_crore", "locator": "Digital Services financial performance comparative column"},
        "ebitda": {"value": 50286, "unit": "INR_crore", "locator": "Digital Services financial performance comparative column"},
    }
}
SOURCES["reliance_jio_ar_2023"]["evidence"] = {
    "total_customers": {"value": 439.3, "unit": "million_customers", "locator": "Digital Services performance update"},
    "value_of_sales_and_services": {"value": 119791, "unit": "INR_crore", "locator": "Digital Services business performance"},
    "mobile_arpu": {"value": 178.8, "unit": "INR_per_user_month", "locator": "Digital Services performance update"},
    "mobile_dou": {"value": 23.1, "unit": "GB_per_user_month", "locator": "Digital Services performance update"},
    "total_data_traffic": {"value": 113.3, "unit": "billion_GB", "locator": "Digital Services network traffic"},
    "ebitda": {"value": 50286, "unit": "INR_crore", "locator": "Digital Services performance update"},
    "connected_homes": {"value": 9, "unit": "million_premises", "comparator": ">", "locator": "Digital Services wired broadband"},
    "5g_base_stations": {"value": 0.060, "unit": "million_base_stations", "comparator": "~", "locator": "Digital Services 5G rollout; disclosed as sites"},
}
SOURCES["reliance_jio_ar_2023"]["comparative_evidence"] = {
    "FY2021": {
        "value_of_sales_and_services": {"value": 90287, "unit": "INR_crore", "locator": "Digital Services three-year financial performance chart"},
        "revenue_from_operations": {"value": 76642, "unit": "INR_crore", "locator": "Digital Services three-year financial performance chart"},
    },
    "FY2022": {
        "value_of_sales_and_services": {"value": 100166, "unit": "INR_crore", "locator": "Digital Services financial performance comparative column"},
        "revenue_from_operations": {"value": 85122, "unit": "INR_crore", "locator": "Digital Services financial performance comparative column"},
        "ebitda": {"value": 40268, "unit": "INR_crore", "locator": "Digital Services financial performance comparative column"},
    }
}
SOURCES["reliance_jio_ar_2022"]["evidence"] = {
    "total_customers": {"value": 410.2, "unit": "million_customers", "locator": "Digital Services KPI table"},
    "value_of_sales_and_services": {"value": 100161, "unit": "INR_crore", "locator": "Digital Services financial performance; superseded precision"},
    "mobile_arpu": {"value": 167.6, "unit": "INR_per_user_month", "locator": "Digital Services KPI table"},
    "mobile_dou": {"value": 19.7, "unit": "GB_per_user_month", "locator": "Digital Services KPI table"},
    "total_data_traffic": {"value": 91.4, "unit": "billion_GB", "locator": "Digital Services KPI table"},
    "ebitda": {"value": 40268, "unit": "INR_crore", "locator": "Digital Services financial performance"},
    "connected_homes": {"value": 5, "unit": "million_premises", "comparator": ">", "locator": "Chairman statement"},
}


SOURCES.update({
    "china_broadnet_nrta_2022": {
        "source_id": "china_broadnet_nrta_2022", "operator_id": "china_broadnet", "year": 2022,
        "label": "国家广播电视总局 2022年全国广播电视行业统计公报",
        "url": "https://www.nrta.gov.cn/art/2023/4/27/art_113_64140.html",
        "source_type": "official_regulator_statistical_bulletin", "publisher": "国家广播电视总局",
        "source_document_id": "china_broadnet_nrta_statistical_bulletin_2022",
        "evidence": {
            "5g_network_subscribers": {"value": 5.5, "unit": "million_subscribers", "comparator": ">", "locator": "2022年全国广播电视行业统计公报；广电5G用户超过550万户"},
        },
    },
    "china_broadnet_guangdong_2022": {
        "source_id": "china_broadnet_guangdong_2022", "operator_id": "china_broadnet", "year": 2022,
        "label": "广东省广播电视局转载2022年全国广播电视行业统计公报",
        "url": "https://gbdsj.gd.gov.cn/zxzx/hydt/content/post_4172060.html",
        "source_type": "official_provincial_government_publication", "publisher": "广东省广播电视局",
        "source_document_id": "china_broadnet_nrta_statistical_bulletin_2022",
    },
    "china_broadnet_nrta_tech_review_2022": {
        "source_id": "china_broadnet_nrta_tech_review_2022", "operator_id": "china_broadnet", "year": 2022,
        "label": "国家广播电视总局 2022广电视听十大科技关键词",
        "url": "https://www.nrta.gov.cn/art/2023/2/11/art_113_63379.html",
        "source_type": "official_regulator_technology_review", "publisher": "国家广播电视总局",
    },
    "china_broadnet_jiacreat_filing_2022": {
        "source_id": "china_broadnet_jiacreat_filing_2022", "operator_id": "china_broadnet", "year": 2022,
        "label": "佳创视讯监管问询回复（引用2022年广电行业统计公报）",
        "url": "https://static.cninfo.com.cn/finalpage/2023-06-05/1216993014.PDF",
        "source_type": "official_exchange_filing", "publisher": "深圳市佳创视讯技术股份有限公司",
        "evidence": {
            "5g_network_subscribers": {"value": 5.5, "unit": "million_subscribers", "comparator": ">", "locator": "监管问询回复行业概况；广电5G用户超过550万户"},
        },
    },
    "china_broadnet_lianhe_rating_2022": {
        "source_id": "china_broadnet_lianhe_rating_2022", "operator_id": "china_broadnet", "year": 2022,
        "label": "联合资信2023年跟踪评级报告（载2022年广电行业数据）",
        "url": "https://www.lhratings.com/reports/B007919-P49578-2020-GZ2023.pdf",
        "source_type": "credit_rating_report", "publisher": "联合资信评估股份有限公司",
        "evidence": {
            "5g_network_subscribers": {"value": 5.5, "unit": "million_subscribers", "comparator": ">", "locator": "2023年跟踪评级报告；截至2022年底广电5G用户超过550万户"},
        },
    },
    "china_broadnet_lianhe_rating_revenue_2022": {
        "source_id": "china_broadnet_lianhe_rating_revenue_2022", "operator_id": "china_broadnet", "year": 2022,
        "label": "联合资信2023年另一主体跟踪评级报告（载2022年广电行业数据）",
        "url": "https://www.lhratings.com/reports/B025317-P65910-2022-GZ2023.pdf",
        "source_type": "credit_rating_report", "publisher": "联合资信评估股份有限公司",
    },
    "china_broadnet_nrta_2023": {
        "source_id": "china_broadnet_nrta_2023", "operator_id": "china_broadnet", "year": 2023,
        "label": "国家广播电视总局 2023年全国广播电视行业统计公报",
        "url": "https://www.nrta.gov.cn/art/2024/5/8/art_113_67383.html",
        "source_type": "official_regulator_statistical_bulletin", "publisher": "国家广播电视总局",
        "evidence": {
            "5g_network_subscribers": {"value": 23, "unit": "million_subscribers", "comparator": ">", "locator": "截至2023年底；广电5G用户超过2300万户"},
        },
    },
    "china_broadnet_crta_2023": {
        "source_id": "china_broadnet_crta_2023", "operator_id": "china_broadnet", "year": 2023,
        "label": "中国广播电视设备工业协会 广电行业综合信息2024年第05期",
        "url": "https://www.crta.com.cn/upload/default/666a5f9f184a0.pdf",
        "source_type": "industry_association_report", "publisher": "中国广播电视设备工业协会",
        "evidence": {
            "5g_network_subscribers": {"value": 23, "unit": "million_subscribers", "comparator": ">", "locator": "广电行业综合信息2024年第05期；广电5G用户超过2300万户"},
        },
    },
    "china_broadnet_guangxi_ar_2023": {
        "source_id": "china_broadnet_guangxi_ar_2023", "operator_id": "china_broadnet", "year": 2023,
        "label": "广西广电网络2023年年度报告",
        "url": "https://static.cninfo.com.cn/finalpage/2024-04-26/1219840147.PDF",
        "source_type": "official_exchange_annual_report", "publisher": "广西广播电视信息网络股份有限公司",
        "evidence": {
            "5g_network_subscribers": {"value": 23, "unit": "million_subscribers", "comparator": ">", "locator": "2023年年度报告行业情况；广电5G用户数量突破2300万"},
        },
    },
    "china_broadnet_shaanxi_ar_2023": {
        "source_id": "china_broadnet_shaanxi_ar_2023", "operator_id": "china_broadnet", "year": 2023,
        "label": "陕西广电网络2023年年度报告",
        "url": "https://dataclouds.cninfo.com.cn/shgonggao/2024/2024-04-25/ea120bea023211ef932efa163e26e5de.pdf",
        "source_type": "official_exchange_annual_report", "publisher": "陕西广电网络传媒（集团）股份有限公司",
    },
    "china_broadnet_digital_china_2023": {
        "source_id": "china_broadnet_digital_china_2023", "operator_id": "china_broadnet", "year": 2023,
        "label": "数字中国建设峰会：开创网络共建共享新模式",
        "url": "https://www.digitalchina.gov.cn/2024/xwzx/szkx/202407/t20240712_4858448.htm",
        "source_type": "official_government_feature", "publisher": "数字中国建设峰会",
    },
    "china_broadnet_cctv_2023": {
        "source_id": "china_broadnet_cctv_2023", "operator_id": "china_broadnet", "year": 2023,
        "label": "央视网：2023年全国广播电视和网络视听行业统计",
        "url": "https://news.cctv.com/2024/05/08/ARTIo3ZmzWpgQu6QOgRqR6vw240508.shtml",
        "source_type": "central_media_report", "publisher": "央视网",
    },
    "china_broadnet_cww_network_2023": {
        "source_id": "china_broadnet_cww_network_2023", "operator_id": "china_broadnet", "year": 2023,
        "label": "通信世界网：中国广电可调度4G/5G基站超400万站",
        "url": "https://www.cww.net.cn/article?id=583903",
        "source_type": "industry_media_report", "publisher": "通信世界网",
    },
    "china_broadnet_broker_network_2023": {
        "source_id": "china_broadnet_broker_network_2023", "operator_id": "china_broadnet", "year": 2023,
        "label": "证券研究报告：广电可调度4G/5G基站超400万站",
        "url": "https://pdf.dfcfw.com/pdf/H3_AP202310311607124281_1.pdf",
        "source_type": "broker_research_report", "publisher": "证券研究机构",
    },
    "china_broadnet_nrta_2024": {
        "source_id": "china_broadnet_nrta_2024", "operator_id": "china_broadnet", "year": 2024,
        "label": "国家广播电视总局 2024年全国广播电视行业统计公报",
        "url": "https://www.nrta.gov.cn/art/2025/5/9/art_113_70729.html",
        "source_type": "official_regulator_statistical_bulletin", "publisher": "国家广播电视总局",
        "source_document_id": "china_broadnet_nrta_statistical_bulletin_2024",
        "evidence": {
            "5g_network_subscribers": {"value": 32.7546, "unit": "million_subscribers", "locator": "第三部分；截至2024年底，广电5G用户3275.46万户"},
        },
    },
    "china_broadnet_crta_2024": {
        "source_id": "china_broadnet_crta_2024", "operator_id": "china_broadnet", "year": 2024,
        "label": "中国广播电视设备工业协会 广电行业综合信息2025年第06期",
        "url": "https://www.crta.com.cn/upload/default/686f2e532b64a.pdf",
        "source_type": "industry_association_report", "publisher": "中国广播电视设备工业协会",
        "evidence": {
            "5g_network_subscribers": {"value": 32.7546, "unit": "million_subscribers", "locator": "广电行业综合信息2025年第06期；全国2024年统计"},
        },
    },
    "china_broadnet_pingliang_gov_2024": {
        "source_id": "china_broadnet_pingliang_gov_2024", "operator_id": "china_broadnet", "year": 2024,
        "label": "平凉市文旅局转载2024年全国广播电视行业统计公报",
        "url": "https://wlj.pingliang.gov.cn/xwdt/gddt/art/2025/art_6465492f99c348a2bc7a8202dfecd639.html",
        "source_type": "official_local_government_publication", "publisher": "平凉市文化广电和旅游局",
        "source_document_id": "china_broadnet_nrta_statistical_bulletin_2024",
    },
    "china_broadnet_jiangsu_bond_2024": {
        "source_id": "china_broadnet_jiangsu_bond_2024", "operator_id": "china_broadnet", "year": 2024,
        "label": "江苏有线2025年科技创新公司债券募集说明书（载2024年行业数据）",
        "url": "https://static.sse.com.cn/bond/bridge2/disclosure/announcement/c/202507/7d9670_20250715_AT3P.pdf",
        "source_type": "official_exchange_bond_prospectus", "publisher": "江苏省广电有线信息网络股份有限公司",
        "evidence": {
            "5g_network_subscribers": {"value": 32.7546, "unit": "million_subscribers", "locator": "募集说明书第68页；2024年广电5G用户"},
        },
    },
    "china_broadnet_people_2024": {
        "source_id": "china_broadnet_people_2024", "operator_id": "china_broadnet", "year": 2024,
        "label": "人民网：广电总局发布2024年全国广播电视行业统计公报",
        "url": "https://ent-app.people.cn/n1/2025/0509/c1012-40476621.html",
        "source_type": "central_media_report", "publisher": "人民网",
        "evidence": {
            "5g_network_subscribers": {"value": 32.7546, "unit": "million_subscribers", "locator": "广电总局2024年行业统计公报报道"},
        },
    },
    "china_broadnet_nrta_2025": {
        "source_id": "china_broadnet_nrta_2025", "operator_id": "china_broadnet", "year": 2025,
        "label": "国家广播电视总局 2025年全国广播电视行业统计公报",
        "url": "https://www.nrta.gov.cn/art/2026/5/13/art_113_73265.html",
        "source_type": "official_regulator_statistical_bulletin", "publisher": "国家广播电视总局",
        "evidence": {
            "5g_network_subscribers": {"value": 42, "unit": "million_subscribers", "comparator": "≈", "locator": "截至2025年底；广电5G用户近4200万户"},
        },
    },
    "china_broadnet_cww_2025": {
        "source_id": "china_broadnet_cww_2025", "operator_id": "china_broadnet", "year": 2025,
        "label": "通信世界网：中国广电5G用户4200万户",
        "url": "https://www.cww.net.cn/article?id=778C9D26DAFB4E278A395F1F65F5F824",
        "source_type": "industry_media_report", "publisher": "通信世界网",
        "evidence": {
            "5g_network_subscribers": {"value": 42, "unit": "million_subscribers", "comparator": "≈", "locator": "广电总局2025年统计公报报道；广电5G用户近4200万户"},
        },
    },
    "china_broadnet_cena_2025": {
        "source_id": "china_broadnet_cena_2025", "operator_id": "china_broadnet", "year": 2025,
        "label": "中国电子报：2025年全国广播电视行业统计公报数据",
        "url": "https://epaper.cena.com.cn/pc/attachment/202605/15/bcd96469-d762-41b6-b25d-0f123a5bc13c.pdf",
        "source_type": "industry_newspaper_report", "publisher": "中国电子报",
        "evidence": {
            "5g_network_subscribers": {"value": 42, "unit": "million_subscribers", "comparator": "≈", "locator": "2026年5月15日版面；广电5G用户近4200万户"},
        },
    },
    "china_broadnet_zhonghong_2025": {
        "source_id": "china_broadnet_zhonghong_2025", "operator_id": "china_broadnet", "year": 2025,
        "label": "中宏网：2025年广播电视和网络视听行业统计数据",
        "url": "https://www.zhonghongwang.com/show-258-460651-1.html",
        "source_type": "media_report", "publisher": "中宏网",
    },
    "china_broadnet_chinacatv_2025": {
        "source_id": "china_broadnet_chinacatv_2025", "operator_id": "china_broadnet", "year": 2025,
        "label": "中国有线电视网：2025年全国广播电视行业统计公报",
        "url": "https://m.chinacatv.org.cn/site/content/2572.html",
        "source_type": "industry_association_media_report", "publisher": "中国有线电视网",
    },
    "china_broadnet_szse_filing_2025": {
        "source_id": "china_broadnet_szse_filing_2025", "operator_id": "china_broadnet", "year": 2025,
        "label": "深交所上市公司2025年年度报告（载2025年广电行业数据）",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2026-04-22/38c75996-c060-42ac-bd14-3d032fdcd871.PDF",
        "source_type": "official_exchange_annual_report", "publisher": "深圳证券交易所",
    },
    "china_broadnet_miit_scope_2024": {
        "source_id": "china_broadnet_miit_scope_2024", "operator_id": "china_broadnet", "year": 2024,
        "label": "工信部2024年通信业统计口径说明（自2月起含中国广电）",
        "url": "https://www.miit.gov.cn/gxsj/tjfx/txy/art/2024/art_261a6af193fb4cc6a0dbe5fff0deadfd.html",
        "source_type": "official_regulator_scope_note", "publisher": "工业和信息化部",
    },
    "china_broadnet_nbs_2025": {
        "source_id": "china_broadnet_nbs_2025", "operator_id": "china_broadnet", "year": 2025,
        "label": "国家统计局 2025年国民经济和社会发展统计公报",
        "url": "https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202602/t20260228_1962662.html",
        "source_type": "official_national_statistical_bulletin", "publisher": "国家统计局",
    },
})
SOURCES["china_mobile_ar_2020"].setdefault("evidence", {})["total_base_stations"] = {
    "value": 5.14,
    "unit": "million_base_stations",
    "locator": "operating review; more than 5.14 million base stations at year end",
}
for _year, _value in ((2016, 1.51), (2017, 1.87), (2018, 2.41), (2019, 3.09)):
    SOURCES[f"china_mobile_ar_{_year}"].setdefault("evidence", {})["4g_base_stations"] = {
        "value": _value,
        "unit": "million_base_stations",
        "locator": f"FY{_year} annual report operating review; year-end 4G base-station total",
    }
for _source_id, _locator in (
    ("china_mobile_ar_2016", "FY2016 annual report company profile; year-end wireline broadband customers"),
    ("china_mobile_results_2016", "FY2016 annual-results presentation household market; wireline broadband customers"),
    ("china_mobile_sd_2016", "FY2016 sustainability report Big Connectivity; year-end wireline broadband customers"),
):
    SOURCES[_source_id].setdefault("evidence", {})["fixed_broadband_subscribers"] = {
        "value": 77.62,
        "unit": "million_subscribers",
        "locator": _locator,
    }
for _source_id, _locator in (
    ("china_mobile_results_2017", "FY2017 annual-results presentation operating-data appendix; total wireline broadband customers"),
    ("china_mobile_sd_2017", "FY2017 sustainability report economic-performance table; wireline broadband customers"),
):
    SOURCES[_source_id].setdefault("evidence", {})["fixed_broadband_subscribers"] = {
        "value": 112.69,
        "unit": "million_subscribers",
        "locator": _locator,
    }
for _year, _value in ((2018, 156.69), (2019, 187.04), (2020, 210.32), (2021, 240.11), (2022, 272.17)):
    SOURCES[f"china_mobile_results_{_year}"].setdefault("evidence", {})["fixed_broadband_subscribers"] = {
        "value": _value,
        "unit": "million_subscribers",
        "locator": f"FY{_year} annual-results presentation operating-data appendix; current-year wireline broadband customers",
    }
    SOURCES[f"china_mobile_results_{_year + 1}"].setdefault("comparative_evidence", {}).setdefault(f"FY{_year}", {})["fixed_broadband_subscribers"] = {
        "value": _value,
        "unit": "million_subscribers",
        "locator": f"FY{_year + 1} annual-results presentation operating-data appendix; FY{_year} comparative wireline broadband customers",
    }
for _source_id, _value, _locator in (
    ("china_mobile_results_2016", 57.5, "FY2016 annual-results presentation operating-data appendix; current-year mobile ARPU"),
    ("china_mobile_results_2017", 57.7, "FY2017 annual-results presentation operating-data appendix; current-year mobile ARPU"),
    ("china_mobile_press_2017", 57.7, "FY2017 annual-results press release operating-performance table; current-year mobile ARPU"),
):
    SOURCES[_source_id].setdefault("evidence", {})["mobile_arpu"] = {
        "value": _value,
        "unit": "RMB_per_user_month",
        "locator": _locator,
    }
for _source_id, _year, _value in (
    ("china_mobile_results_2017", 2016, 57.5),
    ("china_mobile_press_2017", 2016, 57.5),
    ("china_mobile_results_2018", 2017, 57.7),
):
    SOURCES[_source_id].setdefault("comparative_evidence", {}).setdefault(f"FY{_year}", {})["mobile_arpu"] = {
        "value": _value,
        "unit": "RMB_per_user_month",
        "locator": f"official operating table; FY{_year} comparative mobile ARPU",
    }
for _year, _value in ((2018, 53.1), (2019, 49.1), (2020, 47.4), (2021, 48.8), (2022, 49.0)):
    SOURCES[f"china_mobile_ar_{_year}"].setdefault("evidence", {})["mobile_arpu"] = {
        "value": _value,
        "unit": "RMB_per_user_month",
        "locator": f"FY{_year} annual report key operating data; mobile ARPU",
    }
    SOURCES[f"china_mobile_results_{_year}"].setdefault("evidence", {})["mobile_arpu"] = {
        "value": _value,
        "unit": "RMB_per_user_month",
        "locator": f"FY{_year} annual-results presentation operating-data appendix; current-year mobile ARPU",
    }
    SOURCES[f"china_mobile_results_{_year + 1}"].setdefault("comparative_evidence", {}).setdefault(f"FY{_year}", {})["mobile_arpu"] = {
        "value": _value,
        "unit": "RMB_per_user_month",
        "locator": f"FY{_year + 1} annual-results presentation operating-data appendix; FY{_year} comparative mobile ARPU",
    }
for _year, _value in ((2023, 49.3), (2024, 48.5)):
    for _source_id, _label in (
        (f"china_mobile_ar_{_year}", "H-share annual report"),
        (f"china_mobile_ar_a_{_year}", "A-share annual report"),
        (f"china_mobile_results_{_year}", "annual-results presentation"),
    ):
        SOURCES[_source_id].setdefault("evidence", {})["mobile_arpu"] = {
            "value": _value,
            "unit": "RMB_per_user_month",
            "locator": f"FY{_year} {_label}; mobile ARPU operating KPI",
        }
for _year, _value in (
    (2016, 848.90),
    (2017, 887.20),
    (2018, 925.07),
    (2019, 950.28),
    (2020, 941.92),
    (2021, 956.89),
    (2022, 975.01),
):
    SOURCES[f"china_mobile_ar_{_year}"].setdefault("evidence", {})["mobile_subscribers"] = {
        "value": _value,
        "unit": "million_subscribers",
        "locator": f"FY{_year} annual report key operating data; year-end mobile customers",
    }
    SOURCES[f"china_mobile_results_{_year}"].setdefault("evidence", {})["mobile_subscribers"] = {
        "value": _value,
        "unit": "million_subscribers",
        "locator": f"FY{_year} annual-results presentation operating-data appendix; current-year mobile customers",
    }
    SOURCES[f"china_mobile_results_{_year + 1}"].setdefault("comparative_evidence", {}).setdefault(f"FY{_year}", {})["mobile_subscribers"] = {
        "value": _value,
        "unit": "million_subscribers",
        "locator": f"FY{_year + 1} annual-results presentation operating-data appendix; FY{_year} comparative mobile customers",
    }
for _year, _value in ((2023, 991.00), (2024, 1004)):
    for _source_id, _label in (
        (f"china_mobile_ar_{_year}", "H-share annual report"),
        (f"china_mobile_ar_a_{_year}", "A-share annual report"),
        (f"china_mobile_results_{_year}", "annual-results presentation"),
    ):
        SOURCES[_source_id].setdefault("evidence", {})["mobile_subscribers"] = {
            "value": _value,
            "unit": "million_subscribers",
            "locator": f"FY{_year} {_label}; year-end mobile customers",
        }
for _year, _value in (
    (2016, 535.04),
    (2017, 649.51),
    (2018, 712.65),
    (2019, 758.01),
    (2020, 775.31),
):
    SOURCES[f"china_mobile_ar_{_year}"].setdefault("evidence", {})["4g_subscribers"] = {
        "value": _value,
        "unit": "million_subscribers",
        "locator": f"FY{_year} annual report key operating data; year-end 4G customers",
    }
    SOURCES[f"china_mobile_results_{_year}"].setdefault("evidence", {})["4g_subscribers"] = {
        "value": _value,
        "unit": "million_subscribers",
        "locator": f"FY{_year} annual-results presentation operating-data appendix; current-year 4G customers",
    }
    SOURCES[f"china_mobile_results_{_year + 1}"].setdefault("comparative_evidence", {}).setdefault(f"FY{_year}", {})["4g_subscribers"] = {
        "value": _value,
        "unit": "million_subscribers",
        "locator": f"FY{_year + 1} annual-results presentation operating-data appendix; FY{_year} comparative 4G customers",
    }
for _year, _value in ((2021, 206.65), (2022, 327.16)):
    SOURCES[f"china_mobile_ar_{_year}"].setdefault("evidence", {})["5g_network_subscribers"] = {
        "value": _value,
        "unit": "million_subscribers",
        "locator": f"FY{_year} annual report key operating data; year-end 5G network customers",
    }
    SOURCES[f"china_mobile_results_{_year}"].setdefault("evidence", {})["5g_network_subscribers"] = {
        "value": _value,
        "unit": "million_subscribers",
        "locator": f"FY{_year} annual-results presentation operating-data appendix; current-year 5G network customers",
    }
    SOURCES[f"china_mobile_results_{_year + 1}"].setdefault("comparative_evidence", {}).setdefault(f"FY{_year}", {})["5g_network_subscribers"] = {
        "value": _value,
        "unit": "million_subscribers",
        "locator": f"FY{_year + 1} annual-results presentation operating-data appendix; FY{_year} comparative 5G network customers",
    }
for _year, _value in ((2023, 464.81), (2024, 552)):
    for _source_id, _label in (
        (f"china_mobile_ar_{_year}", "H-share annual report"),
        (f"china_mobile_ar_a_{_year}", "A-share annual report"),
        (f"china_mobile_results_{_year}", "annual-results presentation"),
    ):
        SOURCES[_source_id].setdefault("evidence", {})["5g_network_subscribers"] = {
            "value": _value,
            "unit": "million_subscribers",
            "locator": f"FY{_year} {_label}; year-end 5G network customers",
        }
SOURCES["china_mobile_results_2019"].setdefault("evidence", {})["5g_package_subscribers"] = {
    "value": 2.55,
    "unit": "million_subscribers",
    "locator": "FY2019 annual-results presentation customer-market chart; December 2019 5G package customers",
}
for _source_id, _label in (
    ("china_mobile_ar_2020", "FY2020 H-share annual report key operating data"),
    ("china_mobile_20f_2020", "FY2020 Form 20-F selected historical operating table"),
):
    SOURCES[_source_id].setdefault("comparative_evidence", {}).setdefault("FY2019", {})["5g_package_subscribers"] = {
        "value": 2.55,
        "unit": "million_subscribers",
        "locator": f"{_label}; FY2019 comparative 5G package customer base",
    }
for _year, _value in ((2020, 165), (2021, 387), (2022, 614)):
    SOURCES[f"china_mobile_ar_{_year}"].setdefault("evidence", {})["5g_package_subscribers"] = {
        "value": _value,
        "unit": "million_subscribers",
        "locator": f"FY{_year} annual report key operating data; year-end 5G package customers",
    }
    SOURCES[f"china_mobile_results_{_year}"].setdefault("evidence", {})["5g_package_subscribers"] = {
        "value": _value,
        "unit": "million_subscribers",
        "locator": f"FY{_year} annual-results presentation customer-market chart; current-year 5G package customers",
    }
    SOURCES[f"china_mobile_results_{_year + 1}"].setdefault("comparative_evidence", {}).setdefault(f"FY{_year}", {})["5g_package_subscribers"] = {
        "value": _value,
        "unit": "million_subscribers",
        "locator": f"FY{_year + 1} annual-results presentation customer-market chart; FY{_year} comparative 5G package customers",
    }
for _source_id, _label in (
    ("china_mobile_ar_2023", "H-share annual report"),
    ("china_mobile_ar_a_2023", "A-share annual report"),
    ("china_mobile_results_2023", "annual-results presentation"),
):
    SOURCES[_source_id].setdefault("evidence", {})["5g_package_subscribers"] = {
        "value": 795,
        "unit": "million_subscribers",
        "locator": f"FY2023 {_label}; year-end 5G package customers",
    }
for _year, _value in ((2017, 33.3), (2018, 34.4), (2019, 35.3), (2020, 37.7), (2021, 39.8), (2022, 42.1)):
    SOURCES[f"china_mobile_ar_{_year}"].setdefault("evidence", {})["household_customer_blended_arpu"] = {
        "value": _value,
        "unit": "RMB_per_user_month",
        "locator": f"FY{_year} annual report key operating data; household broadband/customer blended ARPU",
    }
    SOURCES[f"china_mobile_results_{_year}"].setdefault("evidence", {})["household_customer_blended_arpu"] = {
        "value": _value,
        "unit": "RMB_per_user_month",
        "locator": f"FY{_year} annual-results presentation household-market operating table; current-year blended ARPU",
    }
    SOURCES[f"china_mobile_results_{_year + 1}"].setdefault("comparative_evidence", {}).setdefault(f"FY{_year}", {})["household_customer_blended_arpu"] = {
        "value": _value,
        "unit": "RMB_per_user_month",
        "locator": f"FY{_year + 1} annual-results presentation household-market table; FY{_year} comparative blended ARPU",
    }
for _year, _value in ((2023, 43.1), (2024, 43.8)):
    for _source_id, _label in (
        (f"china_mobile_ar_{_year}", "H-share annual report"),
        (f"china_mobile_ar_a_{_year}", "A-share annual report"),
        (f"china_mobile_results_{_year}", "annual-results presentation"),
    ):
        SOURCES[_source_id].setdefault("evidence", {})["household_customer_blended_arpu"] = {
            "value": _value,
            "unit": "RMB_per_user_month",
            "locator": f"FY{_year} {_label}; household customer blended ARPU",
        }
for _year, _value in ((2016, 32.1), (2017, 35.1), (2018, 33.5), (2019, 32.8), (2020, 34.0), (2021, 34.7), (2022, 34.1)):
    SOURCES[f"china_mobile_ar_{_year}"].setdefault("evidence", {})["broadband_arpu"] = {
        "value": _value,
        "unit": "RMB_per_user_month",
        "locator": f"FY{_year} annual report key operating data; wireline broadband ARPU",
    }
    SOURCES[f"china_mobile_results_{_year}"].setdefault("evidence", {})["broadband_arpu"] = {
        "value": _value,
        "unit": "RMB_per_user_month",
        "locator": f"FY{_year} annual-results presentation operating-data appendix; current-year wireline broadband ARPU",
    }
    SOURCES[f"china_mobile_results_{_year + 1}"].setdefault("comparative_evidence", {}).setdefault(f"FY{_year}", {})["broadband_arpu"] = {
        "value": _value,
        "unit": "RMB_per_user_month",
        "locator": f"FY{_year + 1} annual-results presentation operating-data appendix; FY{_year} comparative wireline broadband ARPU",
    }
for _source_id, _label in (
    ("china_mobile_ar_2023", "H-share annual report"),
    ("china_mobile_ar_a_2023", "A-share annual report"),
    ("china_mobile_results_2023", "annual-results presentation"),
):
    SOURCES[_source_id].setdefault("evidence", {})["broadband_arpu"] = {
        "value": 34.5,
        "unit": "RMB_per_user_month",
        "locator": f"FY2023 {_label}; wireline broadband ARPU",
    }
for _year, _value in ((2016, 0.697), (2017, 1.399), (2018, 3.6), (2019, 6.7), (2020, 9.4), (2021, 12.6), (2022, 14.1)):
    SOURCES[f"china_mobile_ar_{_year}"].setdefault("evidence", {})["mobile_dou"] = {
        "value": _value,
        "unit": "GB_per_user_month",
        "locator": f"FY{_year} annual report key operating data; handset data traffic DOU",
    }
    SOURCES[f"china_mobile_results_{_year}"].setdefault("evidence", {})["mobile_dou"] = {
        "value": _value,
        "unit": "GB_per_user_month",
        "locator": f"FY{_year} annual-results presentation operating-data appendix; current-year handset DOU",
    }
for _year, _value in ((2016, 0.697), (2018, 3.6), (2019, 6.7), (2020, 9.4), (2021, 12.6), (2022, 14.1)):
    SOURCES[f"china_mobile_results_{_year + 1}"].setdefault("comparative_evidence", {}).setdefault(f"FY{_year}", {})["mobile_dou"] = {
        "value": _value,
        "unit": "GB_per_user_month",
        "locator": f"FY{_year + 1} annual-results presentation operating-data appendix; FY{_year} comparative handset DOU",
    }
SOURCES["china_mobile_20f_2017"].setdefault("evidence", {})["mobile_dou"] = {
    "value": 1.399,
    "unit": "GB_per_user_month",
    "locator": "FY2017 Form 20-F selected historical operating table; 1,399 MB per user per month",
}
for _year, _value in ((2023, 15.9), (2024, 15.9)):
    for _source_id, _label in (
        (f"china_mobile_ar_{_year}", "H-share annual report"),
        (f"china_mobile_ar_a_{_year}", "A-share annual report"),
        (f"china_mobile_results_{_year}", "annual-results presentation"),
    ):
        SOURCES[_source_id].setdefault("evidence", {})["mobile_dou"] = {
            "value": _value,
            "unit": "GB_per_user_month",
            "locator": f"FY{_year} {_label}; handset data traffic DOU",
        }
SOURCES["china_broadnet_nrta_tech_review_2022"].setdefault("evidence", {})["5g_base_stations"] = {
    "value": 0.48, "unit": "million_base_stations", "locator": "2022年广电视听十大科技关键词；共建共享完成48万个700MHz基站",
}
SOURCES["china_mobile_sd_2022"].setdefault("evidence", {})["5g_base_stations"] = {
    "value": 0.48, "unit": "million_base_stations", "locator": "2022 sustainability report; 480,000 700MHz 5G base stations built with China Broadnet",
}
SOURCES["china_mobile_results_2022"].setdefault("evidence", {})["5g_base_stations"] = {
    "value": 0.48, "unit": "million_base_stations", "locator": "2022 annual results presentation; 480k cumulative 700MHz base stations",
}
SOURCES["china_mobile_ar_2023"].setdefault("evidence", {})["5g_base_stations"] = {
    "value": 0.62, "unit": "million_base_stations", "locator": "2023 annual report chairman statement; 620,000 700MHz 5G base stations",
}
SOURCES["china_mobile_sd_2023"].setdefault("evidence", {})["5g_base_stations"] = {
    "value": 0.62, "unit": "million_base_stations", "locator": "2023 sustainability report; 620,000 700MHz 5G base stations",
}
SOURCES["china_mobile_results_2023"].setdefault("evidence", {})["5g_base_stations"] = {
    "value": 0.62, "unit": "million_base_stations", "locator": "2023 annual results presentation; 620k cumulative 700MHz base stations",
}
for _source_id in ("china_mobile_ar_2025", "china_mobile_ar_a_2025", "china_mobile_ar_summary_2025"):
    SOURCES[_source_id].setdefault("evidence", {}).update({
        "mobile_dou": {
            "value": 17.3,
            "unit": "GB_per_user_month",
            "locator": "FY2025 operating KPI disclosure",
        },
        "gigabit_broadband_customers": {
            "value": 109,
            "unit": "million_customers",
            "locator": "FY2025 household-market operating KPI disclosure",
        },
        "iot_connections": {
            "value": 1482,
            "unit": "million_connections",
            "locator": "FY2025 IoT card connection KPI disclosure",
        },
    })
SOURCES["china_mobile_q1_2026_comparatives"].setdefault("comparative_evidence", {})["FY2025"] = {
    "iot_connections": {
        "value": 1482,
        "unit": "million_connections",
        "locator": "FY2025 comparative operating KPI column",
    },
}
for _source_id in ("china_mobile_ar_2025", "china_mobile_results_2025", "china_mobile_press_2025"):
    SOURCES[_source_id].setdefault("evidence", {}).update({
        "mobile_subscribers": {
            "value": 1005,
            "unit": "million_subscribers",
            "locator": "FY2025 communications-services operating disclosure",
        },
        "5g_network_subscribers": {
            "value": 642,
            "unit": "million_subscribers",
            "locator": "FY2025 communications-services operating disclosure",
        },
        "5g_base_stations": {
            "value": 2.77,
            "unit": "million_base_stations",
            "comparator": ">",
            "locator": "FY2025 network infrastructure disclosure; more than 2.77 million stations",
        },
        "integrated_broadband_network_customers": {
            "value": 329,
            "unit": "million_customers",
            "locator": "FY2025 integrated broadband network customer disclosure",
        },
        "mobile_broadband_integration_rate": {
            "value": 96.5,
            "unit": "percent",
            "locator": "FY2025 mass and corporate customer integration disclosure",
        },
        "government_enterprise_customers": {
            "value": 36.17,
            "unit": "million_customers",
            "locator": "FY2025 government and enterprise customer disclosure",
        },
        "households_gigabit_coverage": {
            "value": 530,
            "unit": "million_households",
            "locator": "FY2025 gigabit network household coverage disclosure",
        },
        "intelligent_compute_capacity": {
            "value": 92.5,
            "unit": "EFLOPS_FP16",
            "locator": "FY2025 total self-built and rented intelligent computing capacity disclosure",
        },
    })

# China Telecom subscriber history: the KPI webpage, annual-results
# presentation and results press release are three independently published
# official documents.  Bind only the exact values shown in all three.
_CT_MOBILE_SUBSCRIBERS = {
    2016: 215.00, 2017: 249.96, 2018: 303.00, 2019: 335.57,
    2020: 351.02, 2021: 372.43, 2022: 391.18, 2023: 407.77, 2024: 424.52,
}
_CT_FIXED_BROADBAND_SUBSCRIBERS = {
    2016: 123.12, 2017: 133.53, 2018: 145.79, 2019: 153.13,
    2020: 158.53, 2021: 169.71, 2022: 180.90, 2023: 190.16, 2024: 197.44,
}
_CT_4G_SUBSCRIBERS = {2016: 121.87, 2017: 182.04, 2018: 242.43}
_CT_5G_PACKAGE_SUBSCRIBERS = {
    2019: 4.61, 2020: 86.50, 2021: 187.80,
    2022: 267.96, 2023: 318.66, 2024: 351.48,
}
for _year in range(2016, 2025):
    for _source_id, _label in (
        (f"china_telecom_kpi_{_year}", "December KPI table"),
        (f"china_telecom_results_{_year}", "annual-results presentation"),
        (f"china_telecom_press_{_year}", "annual-results press release"),
    ):
        SOURCES[_source_id].setdefault("evidence", {}).update({
            "mobile_subscribers": {
                "value": _CT_MOBILE_SUBSCRIBERS[_year],
                "unit": "million_subscribers",
                "locator": f"FY{_year} {_label}; exact year-end mobile subscriber table",
            },
            "fixed_broadband_subscribers": {
                "value": _CT_FIXED_BROADBAND_SUBSCRIBERS[_year],
                "unit": "million_subscribers",
                "locator": f"FY{_year} {_label}; exact year-end wireline broadband subscriber table",
            },
        })
        if _year in _CT_4G_SUBSCRIBERS:
            SOURCES[_source_id].setdefault("evidence", {})["4g_subscribers"] = {
                "value": _CT_4G_SUBSCRIBERS[_year],
                "unit": "million_subscribers",
                "locator": f"FY{_year} {_label}; exact year-end 4G subscriber table",
            }
        if _year in _CT_5G_PACKAGE_SUBSCRIBERS and _year >= 2020:
            SOURCES[_source_id].setdefault("evidence", {})["5g_package_subscribers"] = {
                "value": _CT_5G_PACKAGE_SUBSCRIBERS[_year],
                "unit": "million_subscribers",
                "locator": f"FY{_year} {_label}; exact year-end 5G package subscriber table",
            }

# FY2019's year-end 5G-package value is 4.61 million.  The previously captured
# 10.73 million was explicitly dated February 2020 in the FY2019 annual report
# and must not be stored as a December 2019 observation.
SOURCES["china_telecom_results_2019"].setdefault("evidence", {})["5g_package_subscribers"] = {
    "value": 4.61,
    "unit": "million_subscribers",
    "locator": "FY2019 annual-results presentation; December 2019 5G package subscribers",
}
for _source_id, _label in (
    ("china_telecom_results_2020", "FY2020 annual-results presentation"),
    ("china_telecom_press_2020", "FY2020 annual-results press release"),
):
    SOURCES[_source_id].setdefault("comparative_evidence", {}).setdefault("FY2019", {})["5g_package_subscribers"] = {
        "value": 4.61,
        "unit": "million_subscribers",
        "locator": f"{_label}; exact FY2019 comparative 5G package subscriber value",
    }

_CT_MOBILE_ARPU = {
    2016: 55.5, 2017: 55.1,
    2020: 44.1, 2021: 45.0, 2022: 45.2, 2023: 45.4, 2024: 45.6,
}
_CT_MOBILE_ARPU_SOURCES = {
    2016: ["china_telecom_results_2016", "china_telecom_transcript_2016", "china_telecom_results_2017"],
    2017: ["china_telecom_results_2017", "china_telecom_transcript_2017", "china_telecom_results_2018"],
    2020: ["china_telecom_results_2020", "china_telecom_transcript_2020", "china_telecom_results_2021"],
    **{
        year: [f"china_telecom_ar_{year}", f"china_telecom_results_{year}", f"china_telecom_press_{year}"]
        for year in range(2021, 2025)
    },
}
for _year, _value in _CT_MOBILE_ARPU.items():
    if _year in (2016, 2017, 2020):
        SOURCES[f"china_telecom_results_{_year}"].setdefault("evidence", {})["mobile_arpu"] = {
            "value": _value,
            "unit": "RMB_per_user_month",
            "locator": f"FY{_year} annual-results presentation; current-year mobile ARPU",
        }
        SOURCES[f"china_telecom_transcript_{_year}"].setdefault("evidence", {})["mobile_arpu"] = {
            "value": _value,
            "unit": "RMB_per_user_month",
            "locator": f"FY{_year} management transcript; current-year mobile ARPU",
        }
        SOURCES[f"china_telecom_results_{_year + 1}"].setdefault("comparative_evidence", {}).setdefault(f"FY{_year}", {})["mobile_arpu"] = {
            "value": _value,
            "unit": "RMB_per_user_month",
            "locator": f"FY{_year + 1} annual-results presentation; FY{_year} comparative mobile ARPU",
        }
    else:
        for _source_id, _label in (
            (f"china_telecom_ar_{_year}", "annual report"),
            (f"china_telecom_results_{_year}", "annual-results presentation"),
            (f"china_telecom_press_{_year}", "annual-results press release"),
        ):
            SOURCES[_source_id].setdefault("evidence", {})["mobile_arpu"] = {
                "value": _value,
                "unit": "RMB_per_user_month",
                "locator": f"FY{_year} {_label}; mobile ARPU disclosure",
            }

_CT_HANDSET_DATA_TRAFFIC = {
    2016: 1.277, 2017: 3.597, 2018: 14.073, 2019: 24.370,
    2020: 34.690, 2021: 46.966, 2022: 60.193, 2023: 72.772,
}
_CT_HANDSET_DATA_TRAFFIC_SOURCES = {}
for _year, _value in _CT_HANDSET_DATA_TRAFFIC.items():
    _CT_HANDSET_DATA_TRAFFIC_SOURCES[_year] = [
        f"china_telecom_ar_{_year}",
        f"china_telecom_results_{_year}",
        f"china_telecom_results_{_year + 1}",
    ]
    for _source_id, _label in (
        (f"china_telecom_ar_{_year}", "annual report key operating table"),
        (f"china_telecom_results_{_year}", "annual-results presentation current-year column"),
    ):
        SOURCES[_source_id].setdefault("evidence", {})["handset_data_traffic"] = {
            "value": _value,
            "unit": "billion_GB",
            "locator": f"FY{_year} {_label}; exact kTB value converted at 1 kTB = 0.001 billion GB",
        }
    SOURCES[f"china_telecom_results_{_year + 1}"].setdefault("comparative_evidence", {}).setdefault(f"FY{_year}", {})["handset_data_traffic"] = {
        "value": _value,
        "unit": "billion_GB",
        "locator": f"FY{_year + 1} annual-results presentation comparative column; exact FY{_year} kTB value converted at 1 kTB = 0.001 billion GB",
    }

_CT_BROADBAND_BLENDED_ARPU = {
    2019: 42.6, 2020: 44.4, 2021: 45.9, 2022: 46.3, 2023: 47.6, 2024: 47.6,
}
_CT_BROADBAND_BLENDED_ARPU_SOURCES = {
    2019: ["china_telecom_ar_2019", "china_telecom_press_2019", "china_telecom_results_2020"],
    **{
        year: [f"china_telecom_ar_{year}", f"china_telecom_results_{year}", f"china_telecom_press_{year}"]
        for year in range(2020, 2025)
    },
}
for _year, _value in _CT_BROADBAND_BLENDED_ARPU.items():
    if _year == 2019:
        for _source_id, _label in (
            ("china_telecom_ar_2019", "FY2019 annual report"),
            ("china_telecom_press_2019", "FY2019 annual-results press release"),
        ):
            SOURCES[_source_id].setdefault("evidence", {})["broadband_arpu"] = {
                "value": _value,
                "unit": "RMB_per_user_month",
                "locator": f"{_label}; broadband blended ARPU",
            }
        SOURCES["china_telecom_results_2020"].setdefault("comparative_evidence", {}).setdefault("FY2019", {})["broadband_arpu"] = {
            "value": _value,
            "unit": "RMB_per_user_month",
            "locator": "FY2020 annual-results presentation; exact FY2019 comparative broadband blended ARPU",
        }
    else:
        for _source_id, _label in (
            (f"china_telecom_ar_{_year}", "annual report"),
            (f"china_telecom_results_{_year}", "annual-results presentation"),
            (f"china_telecom_press_{_year}", "annual-results press release"),
        ):
            SOURCES[_source_id].setdefault("evidence", {})["broadband_arpu"] = {
                "value": _value,
                "unit": "RMB_per_user_month",
                "locator": f"FY{_year} {_label}; broadband blended ARPU",
            }

# China Unicom historical operating KPIs.  The source maps deliberately mix
# separately filed Form 20-Fs, sustainability reports, HKEX operating
# announcements and annual-results presentations.  A current-year table and a
# following-year comparative are separate documents; translated or mirrored
# copies of one document are never counted twice.
_CU_MOBILE_SUBSCRIBERS = {
    2016: 263.822, 2017: 284.163, 2018: 315.036,
    2019: 318.475, 2020: 305.811, 2021: 317.115,
}
_CU_FIXED_BROADBAND_SUBSCRIBERS = {
    2016: 75.236, 2017: 76.539, 2018: 80.880,
    2019: 83.478, 2020: 86.095, 2021: 95.046,
}
_CU_4G_SUBSCRIBERS = {
    2016: 104.551, 2017: 174.876, 2018: 219.925,
    2019: 253.766, 2020: 270.181,
}
_CU_MOBILE_ARPU = {
    2016: 46.4, 2017: 48.0, 2018: 45.7, 2019: 40.4,
    2020: 42.1, 2021: 43.9, 2022: 44.3,
}
_CU_BROADBAND_ACCESS_ARPU = {
    2016: 49.4, 2017: 46.3, 2018: 44.6,
    2019: 41.6, 2020: 41.5, 2021: 41.3,
}
_CU_MOBILE_DOU = {
    2017: 2.433, 2019: 8.0, 2020: 9.7, 2021: 12.7,
}
_CU_4G_BASE_STATIONS = {
    2016: 0.740, 2017: 0.852, 2018: 0.987,
    2020: 1.503, 2021: 1.560,
}

_CU_MOBILE_SUBSCRIBER_SOURCES = {
    2016: ["china_unicom_dec_ops_2016", "china_unicom_20f_2018", "china_unicom_csr_2018"],
    2017: ["china_unicom_20f_2018", "china_unicom_20f_2019", "china_unicom_csr_2018"],
    2018: ["china_unicom_20f_2018", "china_unicom_20f_2019", "china_unicom_csr_2018"],
    2019: ["china_unicom_20f_2019", "china_unicom_20f_2020", "china_unicom_csr_2019"],
    2020: ["china_unicom_20f_2020", "china_unicom_results_2020", "china_unicom_dec_ops_2020"],
    2021: ["china_unicom_results_2021", "china_unicom_dec_ops_2021", "china_unicom_csr_2021"],
}
_CU_FIXED_BROADBAND_SUBSCRIBER_SOURCES = {
    2016: ["china_unicom_dec_ops_2016", "china_unicom_20f_2018", "china_unicom_csr_2018"],
    2017: ["china_unicom_20f_2018", "china_unicom_results_2018", "china_unicom_csr_2018"],
    2018: ["china_unicom_results_2018", "china_unicom_results_2019", "china_unicom_csr_2018"],
    2019: ["china_unicom_results_2019", "china_unicom_results_2020", "china_unicom_csr_2019"],
    2020: ["china_unicom_results_2020", "china_unicom_results_2021", "china_unicom_dec_ops_2020"],
    2021: ["china_unicom_results_2021", "china_unicom_dec_ops_2021", "china_unicom_csr_2021"],
}
_CU_4G_SUBSCRIBER_SOURCES = {
    2016: ["china_unicom_dec_ops_2016", "china_unicom_20f_2018", "china_unicom_csr_2018"],
    2017: ["china_unicom_20f_2018", "china_unicom_20f_2019", "china_unicom_csr_2018"],
    2018: ["china_unicom_20f_2018", "china_unicom_20f_2019", "china_unicom_csr_2018"],
    2019: ["china_unicom_20f_2019", "china_unicom_20f_2020", "china_unicom_csr_2019"],
    2020: ["china_unicom_20f_2020", "china_unicom_results_2020", "china_unicom_dec_ops_2020"],
}
_CU_MOBILE_ARPU_SOURCES = {
    **{
        year: [
            f"china_unicom_ar_{year}",
            f"china_unicom_results_{year}",
            f"china_unicom_results_{year + 1}",
        ]
        for year in range(2016, 2022)
    },
    2022: ["china_unicom_results_2022", "china_unicom_results_2023"],
}
_CU_BROADBAND_ACCESS_ARPU_SOURCES = {
    year: [
        f"china_unicom_ar_{year}",
        f"china_unicom_results_{year}",
        f"china_unicom_results_{year + 1}",
    ]
    for year in range(2016, 2022)
}
_CU_MOBILE_DOU_SOURCES = {
    2017: ["china_unicom_ar_2017", "china_unicom_results_2017", "china_unicom_press_2017"],
    2019: ["china_unicom_ar_2019", "china_unicom_results_2019", "china_unicom_results_2020"],
    # These two rows are retained because they already existed in the database,
    # but only the two exact presentation documents are bound.  Annual-report
    # narrative uses approximate wording and is deliberately not counted.
    2020: ["china_unicom_results_2020", "china_unicom_results_2021"],
    2021: ["china_unicom_results_2021", "china_unicom_results_2022"],
}
_CU_4G_BASE_STATION_SOURCES = {
    2016: ["china_unicom_csr_2016", "china_unicom_csr_2017", "china_unicom_csr_2018"],
    2017: ["china_unicom_csr_2017", "china_unicom_csr_2018", "china_unicom_csr_2019"],
    2018: ["china_unicom_csr_2018", "china_unicom_csr_2019", "china_unicom_csr_2020"],
    2020: ["china_unicom_csr_2020", "china_unicom_csr_2021", "china_unicom_csr_2022"],
    2021: ["china_unicom_csr_2021", "china_unicom_csr_2022", "china_unicom_ar_2021"],
}


def _bind_cu_historical_evidence(
    source_id: str,
    *,
    year: int,
    metric_key: str,
    value: float,
    unit: str,
    locator: str,
) -> None:
    source = SOURCES[source_id]
    evidence = {"value": value, "unit": unit, "locator": locator}
    if int(source["year"]) == year:
        source.setdefault("evidence", {})[metric_key] = evidence
    else:
        source.setdefault("comparative_evidence", {}).setdefault(f"FY{year}", {})[metric_key] = evidence


for _metric_key, _values, _source_map, _unit in (
    ("mobile_subscribers", _CU_MOBILE_SUBSCRIBERS, _CU_MOBILE_SUBSCRIBER_SOURCES, "million_subscribers"),
    ("fixed_broadband_subscribers", _CU_FIXED_BROADBAND_SUBSCRIBERS, _CU_FIXED_BROADBAND_SUBSCRIBER_SOURCES, "million_subscribers"),
    ("4g_subscribers", _CU_4G_SUBSCRIBERS, _CU_4G_SUBSCRIBER_SOURCES, "million_subscribers"),
    ("mobile_arpu", _CU_MOBILE_ARPU, _CU_MOBILE_ARPU_SOURCES, "RMB_per_user_month"),
    ("broadband_arpu", _CU_BROADBAND_ACCESS_ARPU, _CU_BROADBAND_ACCESS_ARPU_SOURCES, "RMB_per_user_month"),
    ("mobile_dou", _CU_MOBILE_DOU, _CU_MOBILE_DOU_SOURCES, "GB_per_user_month"),
    ("4g_base_stations", _CU_4G_BASE_STATIONS, _CU_4G_BASE_STATION_SOURCES, "million_base_stations"),
):
    for _year, _value in _values.items():
        for _source_id in _source_map[_year]:
            _bind_cu_historical_evidence(
                _source_id,
                year=_year,
                metric_key=_metric_key,
                value=_value,
                unit=_unit,
                locator=(
                    f"FY{_year} exact China Unicom operating KPI; "
                    f"{METRICS[_metric_key][0]} at the disclosed precision"
                ),
            )
for _source_id in ("china_mobile_ar_2025", "china_mobile_results_2025", "china_mobile_ar_summary_2025"):
    SOURCES[_source_id].setdefault("evidence", {}).update({
        "mobile_arpu": {
            "value": 46.8,
            "unit": "RMB_per_user_month",
            "locator": "FY2025 mobile ARPU operating KPI disclosure",
        },
        "household_customer_blended_arpu": {
            "value": 44.5,
            "unit": "RMB_per_user_month",
            "locator": "FY2025 household customer blended ARPU disclosure",
        },
    })
for _source_id in ("china_telecom_ar_2025", "china_telecom_results_2025", "china_telecom_factsheet_2025"):
    SOURCES[_source_id].setdefault("evidence", {}).update({
        "mobile_arpu": {
            "value": 45.1,
            "unit": "RMB_per_user_month",
            "locator": "FY2025 mobile service ARPU disclosure",
        },
        "broadband_arpu": {
            "value": 47.1,
            "unit": "RMB_per_user_month",
            "locator": "FY2025 wireline broadband blended ARPU disclosure",
        },
    })
for _source_id in ("china_telecom_ar_2025", "china_telecom_results_2025", "china_telecom_announcement_2025"):
    SOURCES[_source_id].setdefault("evidence", {})["5g_base_stations"] = {
        "value": 1.54,
        "unit": "million_base_stations",
        "locator": "FY2025 shared 5G mid/high-band network; more than 1.54 million base stations",
    }
for _source_id in ("china_telecom_press_2025", "china_telecom_kpi_2025", "china_telecom_q4_operating_announcement_2025"):
    SOURCES[_source_id].setdefault("evidence", {}).update({
        "mobile_subscribers": {
            "value": 438.65,
            "unit": "million_subscribers",
            "locator": "FY2025 year-end mobile subscriber operating statistics",
        },
        "5g_network_subscribers": {
            "value": 301.81,
            "unit": "million_subscribers",
            "locator": "FY2025 year-end 5G network subscriber operating statistics",
        },
        "fixed_broadband_subscribers": {
            "value": 201.12,
            "unit": "million_subscribers",
            "locator": "FY2025 year-end wireline broadband subscriber operating statistics",
        },
    })
for _source_id in ("china_telecom_results_2025", "china_telecom_announcement_2025", "china_telecom_press_2025"):
    SOURCES[_source_id].setdefault("evidence", {}).update({
        "ten_g_pon_ports": {
            "value": 10,
            "unit": "million_ports",
            "locator": "FY2025 network infrastructure update; 10 million 10G PON ports constructed",
        },
        "urban_gigabit_coverage": {
            "value": 97,
            "unit": "percent",
            "locator": "FY2025 network infrastructure update; gigabit broadband covered over 97% of urban residential areas",
        },
    })
for _source_id in ("china_telecom_ar_2025", "china_telecom_announcement_2025", "china_telecom_press_2025"):
    SOURCES[_source_id].setdefault("evidence", {}).update({
        "5g_network_penetration": {
            "value": 68.8,
            "unit": "percent",
            "locator": "FY2025 fundamental-business review; 5G network subscriber penetration rate",
        },
        "gigabit_broadband_penetration": {
            "value": 31.6,
            "unit": "percent",
            "locator": "FY2025 fundamental-business review; gigabit broadband subscriber penetration rate",
        },
    })
for _source_id in ("china_telecom_ar_2025", "china_telecom_results_2025", "china_telecom_announcement_2025"):
    SOURCES[_source_id].setdefault("evidence", {})["intelligent_compute_capacity"] = {
        "value": 46,
        "unit": "EFLOPS_FP16",
        "locator": "FY2025 self-owned intelligent computing capacity disclosure",
    }
for _source_id in ("china_unicom_ar_2025", "china_unicom_ops_2025", "china_unicom_q4_operating_announcement_2025"):
    SOURCES[_source_id].setdefault("evidence", {})["5g_network_subscribers"] = {
        "value": 232.18,
        "unit": "million_subscribers",
        "locator": "FY2025 5G network user disclosure",
    }
for _source_id in ("china_unicom_ar_2025", "china_unicom_results_2025", "china_unicom_press_2025"):
    SOURCES[_source_id].setdefault("evidence", {})["total_connectivity_subscribers"] = {
        "value": 1200,
        "unit": "million_connections",
        "locator": "FY2025 total connectivity subscriber disclosure",
    }
    SOURCES[_source_id].setdefault("evidence", {}).update({
        "mobile_population_coverage": {
            "value": 99,
            "unit": "percent",
            "locator": "FY2025 connectivity update; mobile network population coverage exceeded 99%",
        },
        "5g_a_deployment_cities": {
            "value": 330,
            "unit": "cities",
            "locator": "FY2025 connectivity update; 5G-A base stations deployed in more than 330 cities",
        },
        "iot_connections": {
            "value": 700,
            "unit": "million_connections",
            "locator": "FY2025 connectivity update; IoT connections exceeded 700 million",
        },
        "integrated_subscriber_penetration": {
            "value": 78,
            "unit": "percent",
            "locator": "FY2025 connectivity update; integrated subscriber penetration exceeded 78%",
        },
        "integrated_package_arpu": {
            "value": 100,
            "unit": "RMB_per_user_month",
            "locator": "FY2025 connectivity update; integrated package ARPU remained above RMB100",
        },
        "cloud_ai_product_users": {
            "value": 300,
            "unit": "million_users",
            "locator": "FY2025 service update; Cloud-AI products served more than 300 million users",
        },
    })
for _source_id, _source in SOURCES.items():
    _source.setdefault("source_document_id", _source_id)


ROWS: list[dict[str, Any]] = []


def source_has_exact_metric_evidence(
    source: dict[str, Any],
    *,
    year: int,
    metric_key: str,
    value: float | int,
    unit: str,
) -> bool:
    """Return True only when the document registry binds this exact value and unit."""
    candidates: list[dict[str, Any]] = []
    direct = source.get("evidence", {}).get(metric_key)
    if isinstance(direct, dict):
        candidates.append(direct)
    comparative = source.get("comparative_evidence", {}).get(f"FY{year}", {}).get(metric_key)
    if isinstance(comparative, dict):
        candidates.append(comparative)
    for evidence in candidates:
        if evidence.get("unit") != unit:
            continue
        try:
            if abs(float(evidence.get("value")) - float(value)) <= 1e-9:
                return True
        except (TypeError, ValueError):
            continue
    return False


def add_series(
    operator_id: str,
    metric_key: str,
    values: dict[int, float | int | None],
    *,
    unit: str | None = None,
    scope: str,
    basis: str = "year_end",
    comparator: str = "=",
    source_ids: dict[int, list[str]] | None = None,
    note: str = "",
    status: str = "official_multi_source_verified",
) -> None:
    metric_zh, default_unit = METRICS[metric_key]
    for year, value in values.items():
        ids = (source_ids or {}).get(year)
        if ids is None:
            ids = [f"{operator_id}_ar_{year}"]
        candidate_ids = [sid for sid in ids if sid in SOURCES]
        row_unit = unit or default_unit
        valid_ids = (
            [
                sid
                for sid in candidate_ids
                if source_has_exact_metric_evidence(
                    SOURCES[sid],
                    year=year,
                    metric_key=metric_key,
                    value=value,
                    unit=row_unit,
                )
            ]
            if value is not None
            else []
        )
        source_document_ids = sorted({
            str(SOURCES[sid].get("source_document_id") or SOURCES[sid]["url"])
            for sid in valid_ids
        }) if value is not None else []
        distinct_source_document_count = len(source_document_ids)
        row_status = status
        if value is None:
            row_status = "source_gap_confirmed"
        elif distinct_source_document_count >= 3:
            row_status = "official_three_distinct_sources_verified"
        elif distinct_source_document_count == 2:
            row_status = "official_two_distinct_sources"
        elif status == "official_multi_source_verified":
            row_status = "official_single_source"
        ROWS.append({
            "operator_id": operator_id,
            "operator": OPERATORS[operator_id]["name"],
            "legal_name": OPERATORS[operator_id]["legal_name"],
            "year": year,
            "period": f"FY{year}",
            "period_end": f"{year}-{OPERATORS[operator_id]['fiscal_year_end']}",
            "grain": "annual",
            "metric_key": metric_key,
            "metric_zh": metric_zh,
            "value": value,
            "official_value": value,
            "unit": row_unit,
            "comparator": comparator,
            "scope": scope,
            "basis": basis,
            "verification_status": row_status,
            "verification_count": len(valid_ids),
            "distinct_source_document_count": distinct_source_document_count,
            "distinct_source_document_ids": source_document_ids,
            "triple_source_status": (
                "not_applicable_missing_value"
                if value is None
                else "three_distinct_sources_verified"
                if distinct_source_document_count >= 3 and "derived" not in row_status
                else "derived_not_directly_disclosed"
                if "derived" in row_status
                else "below_three_source_threshold"
            ),
            "primary_source_id": valid_ids[0] if valid_ids else "",
            "primary_source_url": SOURCES[valid_ids[0]]["url"] if valid_ids else "",
            "verification_sources": valid_ids,
            "candidate_sources": candidate_ids,
            "quality_note": note,
        })


def paired(operator_id: str, years: list[int], secondary: str | None = None) -> dict[int, list[str]]:
    suffix = {"china_mobile": "ops", "china_telecom": "kpi", "china_unicom": "ops"}.get(operator_id)
    result = {}
    for year in years:
        ids = [f"{operator_id}_ar_{year}"]
        if suffix:
            ids.append(f"{operator_id}_{suffix}_{year}")
        elif secondary:
            ids.append(secondary)
        results_id = f"{operator_id}_results_{year}"
        if results_id in SOURCES:
            ids.append(results_id)
        result[year] = ids
    return result


CM_2025_THREE = ["china_mobile_ar_2025", "china_mobile_results_2025", "china_mobile_press_2025"]
CM_2025_ARPU_THREE = ["china_mobile_ar_2025", "china_mobile_results_2025", "china_mobile_ar_summary_2025"]
CT_2025_THREE = ["china_telecom_ar_2025", "china_telecom_results_2025", "china_telecom_announcement_2025"]
CU_2025_THREE = ["china_unicom_ar_2025", "china_unicom_results_2025", "china_unicom_press_2025"]

SHARED_5G_BASE_STATION_SOURCES = {
    2020: ["china_telecom_ar_2020", "china_unicom_ar_2020", "china_telecom_results_2020"],
    2021: ["china_telecom_ar_2021", "china_unicom_ar_2021", "china_telecom_results_2021"],
    2022: ["china_telecom_ar_2022", "china_unicom_ar_2022", "china_unicom_results_2022"],
    2023: ["china_telecom_ar_2023", "china_unicom_ar_2023", "china_telecom_results_2023"],
    2024: ["china_telecom_ar_2024", "china_unicom_ar_2024", "china_telecom_results_2024"],
    2025: CT_2025_THREE,
}

for source_id in SHARED_5G_BASE_STATION_SOURCES[2022]:
    SOURCES[source_id].setdefault("evidence", {})["5g_base_stations"] = {
        "value": 1.0,
        "unit": "million_base_stations",
        "comparator": ">=",
        "locator": "FY2022 5G co-build/co-share network scale",
    }

CHINA_MOBILE_5G_BASE_STATION_SOURCES = {
    2019: ["china_mobile_ar_2019", "china_mobile_20f_2019", "china_mobile_sd_2019"],
    2020: ["china_mobile_ar_2020", "china_mobile_20f_2020", "china_mobile_sd_2020"],
    2021: ["china_mobile_ar_2021", "china_mobile_ar_a_2021", "china_mobile_20f_2021"],
    2022: ["china_mobile_ar_2022", "china_mobile_ar_a_2022", "china_mobile_results_2022"],
    2023: ["china_mobile_ar_2023", "china_mobile_ar_a_2023", "china_mobile_results_2023"],
    2024: ["china_mobile_ar_2024", "china_mobile_ar_a_2024", "china_mobile_results_2024"],
    2025: CM_2025_THREE,
}

CHINA_MOBILE_4G_BASE_STATION_SOURCES = {
    2016: ["china_mobile_ar_2016", "china_mobile_20f_2016", "china_mobile_sd_2016"],
    2017: ["china_mobile_ar_2017", "china_mobile_20f_2017", "china_mobile_sd_2017"],
    2018: ["china_mobile_ar_2018", "china_mobile_20f_2018", "china_mobile_sd_2018"],
    2019: ["china_mobile_ar_2019", "china_mobile_prospectus_2021", "china_mobile_sd_2021"],
    2020: ["china_mobile_prospectus_2021", "china_mobile_sd_2021", "china_mobile_sd_2022"],
    2021: ["china_mobile_sd_2021", "china_mobile_sd_2022", "china_mobile_sd_2023"],
    2022: ["china_mobile_sd_2022", "china_mobile_sd_2023", "china_mobile_sd_2024"],
    2023: ["china_mobile_ar_2023", "china_mobile_sd_2023", "china_mobile_sd_2024"],
}

CHINA_MOBILE_TOTAL_BASE_STATION_SOURCES = {
    2018: ["china_mobile_ar_2018", "china_mobile_prospectus_2021"],
    2019: ["china_mobile_ar_2019", "china_mobile_20f_2019", "china_mobile_prospectus_2021"],
    2020: ["china_mobile_ar_2020", "china_mobile_prospectus_2021", "china_mobile_results_announcement_2020"],
    2021: ["china_mobile_ar_2021", "china_mobile_ar_a_2021", "china_mobile_20f_2021"],
    2022: ["china_mobile_ar_2022", "china_mobile_ar_a_2022", "china_mobile_ar_summary_2022"],
    2023: ["china_mobile_ar_2023", "china_mobile_ar_a_2023", "china_mobile_ar_summary_2023"],
}


def override_sources(mapping: dict[int, list[str]], year: int, source_ids: list[str]) -> dict[int, list[str]]:
    result = dict(mapping)
    result[year] = source_ids
    return result


# China Mobile: existing finance is linked, not copied. Operating values are official year-end/annual figures.
cm_years = YEARS
CHINA_MOBILE_FIXED_BROADBAND_SOURCES = paired("china_mobile", cm_years)
CHINA_MOBILE_FIXED_BROADBAND_SOURCES.update({
    2016: ["china_mobile_ar_2016", "china_mobile_results_2016", "china_mobile_sd_2016"],
    2017: ["china_mobile_results_2017", "china_mobile_sd_2017", "china_mobile_press_2017"],
    **{
        year: [f"china_mobile_results_{year}", f"china_mobile_results_{year + 1}"]
        for year in range(2018, 2023)
    },
    2025: [],
})
CHINA_MOBILE_ARPU_SOURCES = paired("china_mobile", cm_years)
CHINA_MOBILE_ARPU_SOURCES.update({
    2016: ["china_mobile_results_2016", "china_mobile_results_2017", "china_mobile_press_2017"],
    2017: ["china_mobile_results_2017", "china_mobile_press_2017", "china_mobile_results_2018"],
    **{
        year: [f"china_mobile_ar_{year}", f"china_mobile_results_{year}", f"china_mobile_results_{year + 1}"]
        for year in range(2018, 2023)
    },
    2023: ["china_mobile_ar_2023", "china_mobile_ar_a_2023", "china_mobile_results_2023"],
    2024: ["china_mobile_ar_2024", "china_mobile_ar_a_2024", "china_mobile_results_2024"],
    2025: CM_2025_ARPU_THREE,
})
CHINA_MOBILE_DOU_SOURCES = {
    2016: ["china_mobile_ar_2016", "china_mobile_results_2016", "china_mobile_results_2017"],
    2017: ["china_mobile_ar_2017", "china_mobile_20f_2017", "china_mobile_results_2017"],
    **{
        year: [f"china_mobile_ar_{year}", f"china_mobile_results_{year}", f"china_mobile_results_{year + 1}"]
        for year in range(2018, 2023)
    },
    2023: ["china_mobile_ar_2023", "china_mobile_ar_a_2023", "china_mobile_results_2023"],
    2024: ["china_mobile_ar_2024", "china_mobile_ar_a_2024", "china_mobile_results_2024"],
    2025: ["china_mobile_ar_2025", "china_mobile_ar_a_2025", "china_mobile_ar_summary_2025"],
}
CHINA_MOBILE_SUBSCRIBER_SOURCES = {
    **{
        year: [f"china_mobile_ar_{year}", f"china_mobile_results_{year}", f"china_mobile_results_{year + 1}"]
        for year in range(2016, 2023)
    },
    2023: ["china_mobile_ar_2023", "china_mobile_ar_a_2023", "china_mobile_results_2023"],
    2024: ["china_mobile_ar_2024", "china_mobile_ar_a_2024", "china_mobile_results_2024"],
    2025: CM_2025_THREE,
}
CHINA_MOBILE_4G_SUBSCRIBER_SOURCES = paired("china_mobile", list(range(2016, 2022)))
CHINA_MOBILE_4G_SUBSCRIBER_SOURCES.update({
    year: [f"china_mobile_ar_{year}", f"china_mobile_results_{year}", f"china_mobile_results_{year + 1}"]
    for year in range(2016, 2021)
})
CHINA_MOBILE_5G_NETWORK_SUBSCRIBER_SOURCES = {
    2021: ["china_mobile_ar_2021", "china_mobile_results_2021", "china_mobile_results_2022"],
    2022: ["china_mobile_ar_2022", "china_mobile_results_2022", "china_mobile_results_2023"],
    2023: ["china_mobile_ar_2023", "china_mobile_ar_a_2023", "china_mobile_results_2023"],
    2024: ["china_mobile_ar_2024", "china_mobile_ar_a_2024", "china_mobile_results_2024"],
    2025: CM_2025_THREE,
}
CHINA_MOBILE_5G_PACKAGE_SUBSCRIBER_SOURCES = {
    2019: ["china_mobile_results_2019", "china_mobile_ar_2020", "china_mobile_20f_2020"],
    2020: ["china_mobile_ar_2020", "china_mobile_results_2020", "china_mobile_results_2021"],
    2021: ["china_mobile_ar_2021", "china_mobile_results_2021", "china_mobile_results_2022"],
    2022: ["china_mobile_ar_2022", "china_mobile_results_2022", "china_mobile_results_2023"],
    2023: ["china_mobile_ar_2023", "china_mobile_ar_a_2023", "china_mobile_results_2023"],
}
CHINA_MOBILE_HOUSEHOLD_BLENDED_ARPU_SOURCES = {
    **{
        year: [f"china_mobile_ar_{year}", f"china_mobile_results_{year}", f"china_mobile_results_{year + 1}"]
        for year in range(2017, 2023)
    },
    2023: ["china_mobile_ar_2023", "china_mobile_ar_a_2023", "china_mobile_results_2023"],
    2024: ["china_mobile_ar_2024", "china_mobile_ar_a_2024", "china_mobile_results_2024"],
    2025: CM_2025_ARPU_THREE,
}
CHINA_MOBILE_BROADBAND_ARPU_SOURCES = {
    **{
        year: [f"china_mobile_ar_{year}", f"china_mobile_results_{year}", f"china_mobile_results_{year + 1}"]
        for year in range(2016, 2023)
    },
    2023: ["china_mobile_ar_2023", "china_mobile_ar_a_2023", "china_mobile_results_2023"],
}
add_series("china_mobile", "mobile_subscribers", dict(zip(cm_years, [848.90, 887.20, 925.07, 950.28, 941.92, 956.89, 975.01, 991.00, 1004, 1005])), scope="group mobile customer base", source_ids=CHINA_MOBILE_SUBSCRIBER_SOURCES, note="FY2016-FY2022 retain the exact two-decimal values repeated in the annual report and consecutive annual-results presentations. FY2023-FY2024 use the H-share annual report, A-share annual report and current-year presentation. FY2025 uses the annual report, presentation and results press release.")
add_series("china_mobile", "4g_subscribers", {2016:535.04, 2017:649.51, 2018:712.65, 2019:758.01, 2020:775.31, 2021:822}, scope="group 4G customer base", source_ids=CHINA_MOBILE_4G_SUBSCRIBER_SOURCES, note="FY2016-FY2020 retain the exact two-decimal values repeated in the annual report and consecutive annual-results presentations. FY2021 remains at its disclosed rounded precision and below the three-document threshold because the annual-results presentation switched its customer breakdown from 4G to 5G network customers.")
add_series("china_mobile", "5g_package_subscribers", {2019:2.55, 2020:165, 2021:387, 2022:614, 2023:795}, scope="contracted 5G package customers; not equivalent to active 5G network users", source_ids=CHINA_MOBILE_5G_PACKAGE_SUBSCRIBER_SOURCES, note="Each FY2019-FY2023 row is bound to three exact official documents. FY2019 uses the current-year presentation plus the FY2020 annual report and Form 20-F comparative tables. 5G package customers are kept separate from active 5G network customers.")
add_series("china_mobile", "5g_network_subscribers", {2021:206.65, 2022:327.16, 2023:464.81, 2024:552, 2025:642}, scope="customers that used the 5G network; definition differs from 5G package customers", source_ids=CHINA_MOBILE_5G_NETWORK_SUBSCRIBER_SOURCES, note="FY2021-FY2023 retain the precise operating-table values rather than rounded headline figures. Each FY2021-FY2024 row is bound to three exact official documents; FY2025 uses the annual report, presentation and results press release.")
add_series("china_mobile", "fixed_broadband_subscribers", dict(zip(cm_years, [77.62,112.69,156.69,187.04,210.32,240.11,272.17,298,315,None])), scope="group wireline broadband customers", source_ids=CHINA_MOBILE_FIXED_BROADBAND_SOURCES, note="FY2016-FY2017 each use three exact official documents. FY2018-FY2022 retain the two-decimal values repeated in consecutive annual-results presentations and remain below the three-document threshold. FY2025 changed to integrated broadband network customers; the 329 million integrated-scope value is stored separately and is not substituted into this legacy series.")
add_series("china_mobile", "broadband_arpu", {2016:32.1, 2017:35.1, 2018:33.5, 2019:32.8, 2020:34.0, 2021:34.7, 2022:34.1, 2023:34.5}, unit="RMB_per_user_month", scope="wireline broadband ARPU; earlier-year scope includes combinations of household, small-business/corporate broadband and dedicated-line revenue as disclosed", source_ids=CHINA_MOBILE_BROADBAND_ARPU_SOURCES, note="FY2016-FY2023 each use three exact official documents. This access-business ARPU is stored separately from household broadband/customer blended ARPU; China Mobile stopped presenting it in the FY2024 annual operating table.")
add_series("china_mobile", "mobile_arpu", dict(zip(cm_years, [57.5,57.7,53.1,49.1,47.4,48.8,49.0,49.3,48.5,46.8])), unit="RMB_per_user_month", scope="group mobile business annual ARPU", source_ids=CHINA_MOBILE_ARPU_SOURCES)
add_series("china_mobile", "household_customer_blended_arpu", {2017:33.3, 2018:34.4, 2019:35.3, 2020:37.7, 2021:39.8, 2022:42.1, 2023:43.1, 2024:43.8, 2025:44.5}, unit="RMB_per_user_month", scope="household broadband/customer blended ARPU; terminology changed from household broadband to household customer without merging with wireline broadband access ARPU", source_ids=CHINA_MOBILE_HOUSEHOLD_BLENDED_ARPU_SOURCES, note="FY2017-FY2024 each use three exact official documents. The blended household metric is not interchangeable with wireline broadband ARPU, which includes different business scopes in earlier years.")
add_series("china_mobile", "mobile_dou", dict(zip(cm_years, [0.697,1.399,3.6,6.7,9.4,12.6,14.1,15.9,15.9,17.3])), scope="average handset data traffic per user per month; 2016-17 converted from MB to GB", source_ids=CHINA_MOBILE_DOU_SOURCES, note="FY2016-FY2024 values are bound to three exact documents per year. FY2017 deliberately uses the annual report, Form 20-F and current-year results presentation because the following-year presentation rounds 1.399 GB to 1.4 GB. FY2025 uses the H-share annual report, A-share annual report and separately filed A-share annual report summary; the reviewed annual-results announcement does not disclose DOU.")
add_series("china_mobile", "handset_data_traffic", dict(zip(cm_years, [5.6807,12.5693,35.4534,65.89,90.70,124.8,144.7,165.9,168.2,183.8])), scope="sum of four official quarterly handset-data-traffic values; 2016-18 converted from billion MB", basis="official_quarterly_sum", source_ids=override_sources(paired("china_mobile", cm_years), 2025, ["china_mobile_ops_2025"]), note="Derived only by summing the four official quarterly values; no interpolation.")
add_series("china_mobile", "total_base_stations", {2018:3.85, 2019:4.48, 2020:5.14, 2021:5.50, 2022:6.0, 2023:6.60}, scope="all commissioned mobile base stations", comparator=">=", source_ids=CHINA_MOBILE_TOTAL_BASE_STATION_SOURCES, note="Annual reports use 'more than/over' for some years. FY2019-FY2023 have three exact independent legal documents except FY2018, which remains at two exact documents; rounded values and same-document mirrors are excluded.")
add_series("china_mobile", "4g_base_stations", {2016:1.51, 2017:1.87, 2018:2.41, 2019:3.09, 2020:3.28, 2021:3.32, 2022:3.34, 2023:3.37}, scope="commissioned 4G base stations", source_ids=CHINA_MOBILE_4G_BASE_STATION_SOURCES, note="FY2016-FY2023 values are bound to exact year-end operating tables across annual, SEC, prospectus, and sustainability documents. Language variants or chapter PDFs of the same sustainability report count as one source document.")
add_series("china_mobile", "5g_base_stations", {2019:0.05, 2020:0.39, 2021:0.73, 2022:1.285, 2023:1.94, 2024:2.40, 2025:2.77}, scope="commissioned 5G base stations, including applicable 700MHz co-built sites", comparator=">=", source_ids=CHINA_MOBILE_5G_BASE_STATION_SOURCES)
add_series("china_mobile", "integrated_broadband_network_customers", {2025:329}, scope="household broadband, enterprise broadband, dedicated Internet lines and dedicated data lines", source_ids={2025:CM_2025_THREE})
add_series("china_mobile", "gigabit_broadband_customers", {2025:109}, scope="group gigabit broadband customers", source_ids={2025:["china_mobile_ar_2025", "china_mobile_ar_a_2025", "china_mobile_ar_summary_2025"]}, note="The H-share annual report, A-share annual report and separately filed A-share annual report summary each give the exact 109 million value. The presentation and press release round to 110 million and are not counted.")
add_series("china_mobile", "iot_connections", {2025:1482}, scope="cellular IoT card connections", source_ids={2025:["china_mobile_ar_2025", "china_mobile_ar_a_2025", "china_mobile_ar_summary_2025", "china_mobile_q1_2026_comparatives"]}, note="The H-share annual report, A-share annual report, separately filed annual report summary and the FY2025 comparative column in the 2026 first-quarter results each disclose the exact value of 1,482 million. Rounded presentation and press-release values are not counted.")
add_series("china_mobile", "mobile_broadband_integration_rate", {2025:96.5}, scope="integration rate between mobile and broadband customers", source_ids={2025:CM_2025_THREE})
add_series("china_mobile", "government_enterprise_customers", {2025:36.17}, scope="government and enterprise customers", source_ids={2025:CM_2025_THREE})
add_series("china_mobile", "households_gigabit_coverage", {2025:530}, scope="households covered by gigabit network", source_ids={2025:CM_2025_THREE})
add_series("china_mobile", "intelligent_compute_capacity", {2025:92.5}, scope="total self-built plus rented intelligent compute capacity", source_ids={2025:CM_2025_THREE})

# China Telecom: finance remains in the existing quarterly database.
ct_years = YEARS
CHINA_TELECOM_SUBSCRIBER_SOURCES = {
    year: [f"china_telecom_kpi_{year}", f"china_telecom_results_{year}", f"china_telecom_press_{year}"]
    for year in range(2016, 2025)
}
CHINA_TELECOM_SUBSCRIBER_SOURCES[2025] = [
    *CT_2025_THREE,
    "china_telecom_press_2025",
    "china_telecom_kpi_2025",
    "china_telecom_q4_operating_announcement_2025",
]
CHINA_TELECOM_5G_PACKAGE_SOURCES = {
    2019: ["china_telecom_results_2019", "china_telecom_results_2020", "china_telecom_press_2020"],
    **{
        year: [f"china_telecom_kpi_{year}", f"china_telecom_results_{year}", f"china_telecom_press_{year}"]
        for year in range(2020, 2025)
    },
}
add_series("china_telecom", "mobile_subscribers", dict(zip(ct_years, [215.00,249.96,303.00,335.57,351.02,372.43,391.18,407.77,424.52,438.65])), scope="mobile subscribers", source_ids=CHINA_TELECOM_SUBSCRIBER_SOURCES, note="FY2016-FY2024 each use the exact December KPI table, annual-results presentation and separately published results press release; FY2025 uses the exact annual/operating disclosures already registered.")
add_series("china_telecom", "4g_subscribers", {2016:121.87, 2017:182.04, 2018:242.43}, scope="4G subscribers/users", source_ids={year: CHINA_TELECOM_SUBSCRIBER_SOURCES[year] for year in range(2016, 2019)}, note="Each value is bound to the exact December KPI table, annual-results presentation and separately published results press release.")
add_series("china_telecom", "5g_package_subscribers", _CT_5G_PACKAGE_SUBSCRIBERS, scope="5G package subscribers; not equivalent to active 5G network users", source_ids=CHINA_TELECOM_5G_PACKAGE_SOURCES, note="FY2019 is corrected to the disclosed 31 December value of 4.61 million. The former 10.73 million observation was dated February 2020 and is excluded from FY2019. Each retained row has three exact official document bindings.")
add_series("china_telecom", "5g_network_subscribers", {2024:250.73, 2025:301.81}, scope="5G network subscribers; 2024 comparative was restated on the new network-user basis", source_ids=override_sources(paired("china_telecom", [2024,2025]), 2025, [*CT_2025_THREE, "china_telecom_press_2025", "china_telecom_kpi_2025", "china_telecom_q4_operating_announcement_2025"]))
add_series("china_telecom", "fixed_broadband_subscribers", dict(zip(ct_years, [123.12,133.53,145.79,153.13,158.53,169.71,180.90,190.16,197.44,201.12])), scope="wireline broadband subscribers", source_ids=CHINA_TELECOM_SUBSCRIBER_SOURCES, note="FY2016-FY2024 each use the exact December KPI table, annual-results presentation and separately published results press release; FY2025 uses the exact annual/operating disclosures already registered.")
add_series("china_telecom", "mobile_arpu", {2016:55.5,2017:55.1,2018:None,2019:None,2020:44.1,2021:45.0,2022:45.2,2023:45.4,2024:45.6,2025:45.1}, unit="RMB_per_user_month", scope="mobile service ARPU", source_ids={**_CT_MOBILE_ARPU_SOURCES, 2025:["china_telecom_ar_2025", "china_telecom_results_2025", "china_telecom_factsheet_2025"]}, note="FY2016, FY2017 and FY2020-FY2025 have three exact official document bindings. FY2018-FY2019 remain explicit gaps because only two exact annual-results presentations were verified; rounded or scope-mismatched references are not substituted.")
add_series("china_telecom", "broadband_arpu", {**_CT_BROADBAND_BLENDED_ARPU, 2025:47.1}, unit="RMB_per_user_month", scope="wireline broadband blended ARPU", source_ids={**_CT_BROADBAND_BLENDED_ARPU_SOURCES, 2025:["china_telecom_ar_2025", "china_telecom_results_2025", "china_telecom_factsheet_2025"]}, note="FY2019-FY2025 use the integrated broadband-access, IPTV/e-Surfing HD and Smart Family blended definition; this series is not mixed with the narrower wireline broadband access ARPU shown in older presentation appendices.")
add_series("china_telecom", "handset_data_traffic", {**_CT_HANDSET_DATA_TRAFFIC, 2024:89.979, 2025:106.046}, scope="annual handset data traffic; converted from official kTB convention to billion GB at 1 kTB = 0.001 billion GB", source_ids={**_CT_HANDSET_DATA_TRAFFIC_SOURCES, 2024:paired("china_telecom", [2024])[2024], 2025:["china_telecom_ar_2025", "china_telecom_results_2025", "china_telecom_press_2025"]}, note="FY2016-FY2023 each use the annual report plus current-year and following-year annual-results presentation exact tables. FY2024-FY2025 retain their disclosed precision but remain below the strict three-exact-document threshold where later materials round the kTB value.")
add_series("china_telecom", "5g_base_stations", {2020:0.38,2021:0.69,2022:1.0,2023:1.21,2024:1.375,2025:1.54}, scope="5G mid-band co-built/shared base stations in service across China Telecom and China Unicom networks; not attributable one-for-one to either operator", comparator=">=", source_ids=SHARED_5G_BASE_STATION_SOURCES, note="Shared-network scope; never sum China Telecom and China Unicom rows. FY2022 is stored as the officially supported lower bound of at least one million; the previous 1.05 million precision was not retained because the reviewed exact official documents state reached/over one million.")
add_series("china_telecom", "5g_network_penetration", {2025:68.8}, scope="5G network subscribers as a share of mobile subscribers", source_ids={2025:[*CT_2025_THREE, "china_telecom_press_2025"]})
add_series("china_telecom", "gigabit_broadband_penetration", {2025:31.6}, scope="gigabit broadband subscribers as a share of broadband subscribers", source_ids={2025:[*CT_2025_THREE, "china_telecom_press_2025"]})
add_series("china_telecom", "ten_g_pon_ports", {2025:10}, scope="10G PON ports in the gigabit fibre network", comparator=">=", source_ids={2025:[*CT_2025_THREE, "china_telecom_press_2025"]})
add_series("china_telecom", "urban_gigabit_coverage", {2025:97}, scope="urban residential areas covered by gigabit broadband", comparator=">", source_ids={2025:[*CT_2025_THREE, "china_telecom_press_2025"]})
add_series("china_telecom", "intelligent_compute_capacity", {2025:46}, scope="self-owned intelligent computing power", source_ids={2025:CT_2025_THREE})

# China Unicom: exact mobile/broadband values remain separate from the broader connectivity aggregate.
cu_years = YEARS
add_series("china_unicom", "mobile_subscribers", {2016:263.822,2017:284.163,2018:315.036,2019:318.475,2020:305.811,2021:317.115,2022:322.70,2023:333.30,2024:343.98,2025:357.30}, scope="mobile billing subscribers", source_ids={**paired("china_unicom", cu_years), **_CU_MOBILE_SUBSCRIBER_SOURCES}, note="FY2016-FY2021 retain the exact thousand-subscriber precision repeated across three separate official documents. FY2022 remains at presentation precision below the strict three-document gate. FY2023-FY2025 are handled below as approximate official year-end-plus-net-addition reconstructions.")
add_series("china_unicom", "4g_subscribers", _CU_4G_SUBSCRIBERS, scope="4G subscribers / billing subscribers using 4G or 5G network", source_ids=_CU_4G_SUBSCRIBER_SOURCES, note="FY2016-FY2020 retain exact thousand-subscriber values from three separate official filings, reports or operating announcements per year.")
add_series("china_unicom", "5g_package_subscribers", {2020:70.83,2021:154.93,2022:212.73,2023:259.64,2024:290.44}, scope="5G package subscribers; disclosure replaced by network-user measure in 2025", source_ids=paired("china_unicom", list(range(2020,2025))))
add_series("china_unicom", "5g_network_subscribers", {2025:232.18}, scope="customers that used the 5G network during the period; not comparable with prior 5G package subscribers", source_ids={2025:["china_unicom_ar_2025","china_unicom_ops_2025","china_unicom_q4_operating_announcement_2025"]})
add_series("china_unicom", "fixed_broadband_subscribers", {2016:75.236,2017:76.539,2018:80.880,2019:83.478,2020:86.095,2021:95.046,2022:103.63,2023:113.42,2024:122.26,2025:129.87}, scope="fixed-line broadband billing subscribers", source_ids={**paired("china_unicom", cu_years), **_CU_FIXED_BROADBAND_SUBSCRIBER_SOURCES}, note="FY2016-FY2021 retain the exact thousand-subscriber precision repeated across three separate official documents. FY2022 remains at presentation precision below the strict three-document gate. FY2023-FY2025 are handled below as approximate official year-end-plus-net-addition reconstructions.")
add_series("china_unicom", "mobile_arpu", {**_CU_MOBILE_ARPU,2023:None,2024:None,2025:None}, unit="RMB_per_user_month", scope="mobile billing subscriber ARPU", source_ids={**paired("china_unicom", ct_years), **_CU_MOBILE_ARPU_SOURCES}, note="FY2016-FY2021 each use the annual report plus current-year and following-year annual-results presentations. FY2022 has two exact presentations and remains below the strict three-document threshold. From 2023 the company increasingly emphasised integrated-package ARPU; mobile-only ARPU is left as a documented gap.")
add_series("china_unicom", "broadband_arpu", {**_CU_BROADBAND_ACCESS_ARPU,2022:None,2023:None,2024:None,2025:None}, unit="RMB_per_user_month", scope="fixed-line broadband access ARPU", source_ids={**paired("china_unicom", list(range(2016,2026))), **_CU_BROADBAND_ACCESS_ARPU_SOURCES}, note="FY2016-FY2021 each use the annual report plus current-year and following-year annual-results presentations. The access-only series stops before the later blended/integrated broadband ARPU definition and is not spliced across that scope change.")
add_series("china_unicom", "mobile_dou", {2016:None,2017:2.433,2018:None,2019:8.0,2020:9.7,2021:12.7,2022:None,2023:None,2024:None,2025:None}, scope="monthly average DOU per handset subscriber", source_ids=_CU_MOBILE_DOU_SOURCES, note="FY2017 is converted exactly from the disclosed 2,433 MB at 1,000 MB = 1 GB. FY2017 and FY2019 each use three separate exact official documents. FY2020 and FY2021 retain the database's existing exact values with two exact presentation documents only; annual-report or press-release wording says approximately and is not counted as an exact third source. Other years remain explicit gaps until three same-scope exact documents are verified.")
add_series("china_unicom", "4g_base_stations", {2016:0.740,2017:0.852,2018:0.987,2019:None,2020:1.503,2021:1.560,2022:None,2023:None,2024:None,2025:None}, scope="China Unicom 4G base stations before the disclosure changed to available/self-built/shared network measures", source_ids=_CU_4G_BASE_STATION_SOURCES, note="FY2016-FY2018 and FY2020-FY2021 each use three separate official annual or sustainability reports carrying the same value. FY2019 remains blank because later sustainability reporting restated 1.410 million to 1.407 million. FY2022 remains blank here because the company separately disclosed 1.696 million self-built and 2.276 million available stations; these scopes are not spliced into the earlier series.")
add_series("china_unicom", "5g_base_stations", {2020:0.38,2021:0.69,2022:1.0,2023:1.21,2024:1.375,2025:1.54}, scope="5G mid-band co-built/shared base stations in service across China Unicom and China Telecom networks; not attributable one-for-one", comparator=">=", source_ids=SHARED_5G_BASE_STATION_SOURCES, note="Shared-network scope; never sum China Unicom and China Telecom rows. FY2022 is stored as the officially supported lower bound of at least one million; the previous 1.05 million precision was not retained because the reviewed exact official documents state reached/over one million.")
add_series("china_unicom", "total_connectivity_subscribers", {2025:1200}, scope="mobile billing, fixed broadband, fixed local access, IoT terminals and networking leased lines", comparator=">", source_ids={2025:CU_2025_THREE})
add_series("china_unicom", "mobile_population_coverage", {2025:99}, scope="mobile network population coverage", comparator=">", source_ids={2025:CU_2025_THREE})
add_series("china_unicom", "5g_a_deployment_cities", {2025:330}, scope="cities with 5G-A base-station deployment", comparator=">", source_ids={2025:CU_2025_THREE})
add_series("china_unicom", "iot_connections", {2025:700}, scope="IoT terminal connections; presentation gives 720 million while press release uses over 700 million", comparator=">", source_ids={2025:CU_2025_THREE}, note="The conservative lower bound is common to all three official documents; use 720 million only when citing the presentation-specific precision.")
add_series("china_unicom", "integrated_subscriber_penetration", {2025:78}, scope="integrated subscribers", comparator=">", source_ids={2025:CU_2025_THREE})
add_series("china_unicom", "integrated_package_arpu", {2025:100}, scope="integrated package subscribers", comparator=">", source_ids={2025:CU_2025_THREE})
add_series("china_unicom", "cloud_ai_product_users", {2025:300}, scope="users served by Cloud-AI products", comparator=">", source_ids={2025:CU_2025_THREE})

# Bharti Airtel: complete consolidated financial history plus disclosed operating KPIs.
airtel_years = YEARS
airtel_sources = {y:[f"bharti_airtel_ar_{y}", "airtel_2019_five_year" if y <= 2019 else "airtel_2024_five_year" if y <= 2024 else "airtel_2025_ir_pack"] for y in airtel_years}
airtel_2025_ir_sources = ["airtel_q1_2026_ir_pack", "airtel_q2_2026_ir_pack", "airtel_q3_2026_ir_pack", "airtel_2025_ir_pack"]
airtel_2024_ir_sources = list(airtel_2025_ir_sources)
airtel_2023_ir_sources = ["airtel_q1_2026_ir_pack", "airtel_q2_2026_ir_pack", "airtel_q3_2026_ir_pack"]
airtel_2022_ir_sources = ["airtel_q1_2024_ir_pack", "airtel_q2_2024_ir_pack", "airtel_q3_2024_ir_pack", "airtel_q4_2024_ir_pack"]
airtel_2021_ir_sources = list(airtel_2022_ir_sources)
airtel_2020_ir_sources = ["airtel_q1_2023_ir_pack", "airtel_q2_2023_ir_pack", "airtel_q3_2023_ir_pack"]
airtel_2020_customer_sources = ["airtel_q2_2023_ir_pack", "airtel_q3_2023_ir_pack", "bharti_airtel_ar_2023"]
airtel_2020_network_detail_sources = ["bharti_airtel_ar_2020", "bharti_airtel_ar_2021", "airtel_2024_five_year"]
airtel_2019_annual_financial_sources = ["bharti_airtel_ar_2019", "bharti_airtel_ar_2020", "bharti_airtel_ar_2022"]
airtel_2019_ir_kpi_sources = ["airtel_q4_2020_ir_pack", "airtel_q1_2021_ir_pack", "airtel_q2_2022_ir_pack"]
airtel_2019_capex_sources = ["airtel_q4_2019_ir_pack", "airtel_q4_2020_ir_pack", "airtel_q1_2021_ir_pack"]
airtel_2019_network_detail_sources = ["bharti_airtel_ar_2019", "bharti_airtel_ar_2020", "airtel_q4_2019_ir_pack"]
airtel_2018_annual_financial_sources = ["bharti_airtel_ar_2019", "bharti_airtel_ar_2020", "bharti_airtel_ar_2022"]
airtel_2018_ir_kpi_sources = ["airtel_q4_2019_ir_pack", "airtel_q4_2020_ir_pack", "airtel_q1_2021_ir_pack"]
airtel_2018_net_debt_sources = ["airtel_q4_2020_ir_pack", "airtel_q1_2021_ir_pack", "bharti_airtel_ar_2022"]
airtel_2018_capex_sources = ["airtel_q4_2018_ir_pack", "airtel_q4_2019_ir_pack", "airtel_q4_2020_ir_pack"]
airtel_2018_network_detail_sources = ["bharti_airtel_ar_2019", "bharti_airtel_ar_2020", "airtel_q4_2019_ir_pack"]
airtel_2017_annual_financial_sources = ["bharti_airtel_ar_2019", "bharti_airtel_ar_2020", "bharti_airtel_ar_2021"]
airtel_2017_ir_kpi_sources = ["airtel_q4_2017_ir_pack", "airtel_q4_2018_ir_pack", "airtel_q4_2019_ir_pack"]
airtel_2016_annual_financial_sources = ["bharti_airtel_ar_2017", "bharti_airtel_ar_2019", "bharti_airtel_ar_2020"]
airtel_2016_ir_kpi_sources = ["airtel_q4_2016_ir_pack", "airtel_q4_2017_ir_pack", "airtel_q4_2018_ir_pack"]
airtel_2016_network_detail_sources = ["bharti_airtel_ar_2016", "airtel_q4_2016_ir_pack", "airtel_q1_2017_ir_pack"]
airtel_2017_network_detail_sources = ["airtel_q4_2017_ir_pack", "bharti_airtel_ar_2018", "airtel_q4_2018_ir_pack", "bharti_airtel_ar_2019", "bharti_airtel_ar_2020"]
airtel_2016_traffic_sources = ["bharti_airtel_ar_2016"]
airtel_sources_with_exact_2024 = override_sources(airtel_sources, 2024, airtel_2024_ir_sources)
airtel_sources_with_exact_2023_2024 = override_sources(airtel_sources_with_exact_2024, 2023, airtel_2023_ir_sources)
airtel_sources_with_exact_2022_2024 = override_sources(airtel_sources_with_exact_2023_2024, 2022, airtel_2022_ir_sources)
airtel_sources_with_exact_2021_2024 = override_sources(airtel_sources_with_exact_2022_2024, 2021, airtel_2021_ir_sources)
airtel_sources_with_exact_2020_2024 = override_sources(airtel_sources_with_exact_2021_2024, 2020, airtel_2020_ir_sources)
airtel_customer_sources_with_exact_2020_2024 = override_sources(airtel_sources_with_exact_2021_2024, 2020, airtel_2020_customer_sources)
airtel_2025_with_annual = ["bharti_airtel_ar_2025", *airtel_2025_ir_sources]
airtel_fy2021_2022_scope_note = "FY2021 and FY2022 are repeated exactly in four FY2023-24 IR packs that explicitly exclude the consolidation impact of erstwhile Bharti Infratel/Indus Towers. FY2023 onward uses a later recast basis, so FY2022-FY2023 growth requires a scope-break warning."
airtel_fy2020_scope_note = "FY2020 IR-pack comparatives explicitly exclude the consolidation impact of erstwhile Bharti Infratel/Indus Towers. Three FY2022-23 quarterly packs repeat the stored financial and tower values; the later FY2020 total-customer basis of 422.100m is supported by Q2, Q3 and the FY2023 annual report, while the earlier Q1 pack's 423.287m is excluded."
airtel_fy2019_scope_note = "FY2019 group KPI packs report 204,356 towers, while the India mobile manufactured-capital disclosure reports 181,079; the group KPI is retained for cross-year comparability and the narrower value remains in the conflict register. The later FY2023 annual report alone restates total customers to 402.418m, so the exactly repeated 403.645m basis remains selected under the three-document rule."
airtel_fy2018_scope_note = "FY2018 later comparable packs report group KPI towers of 187,541, while the India mobile manufactured-capital disclosure reports 165,748; the group KPI is retained. Later comparable revenue is INR826,388m rather than the earlier INR836,879m, and net debt including finance lease obligations is INR1,001,060m rather than the pre-lease INR952,285m."
airtel_fy2017_scope_note = "FY2017 uses the later comparable revenue of INR942,506m rather than the original results-pack INR954,684m. Annual KPI earnings before tax is INR77,232m, while the results-pack profit-before-tax-before-exceptional-items line is INR88,929m. Group KPI network towers are 184,255; the India-mobile operating review's 162,046 is a narrower scope. The 0.903bn-GB traffic figure is a consolidated annual headline, not India-mobile traffic, and remains below the three-document threshold."
airtel_fy2016_scope_note = "FY2016 annual KPI tables use INR965,321m revenue, INR128,463m earnings before tax and INR60,767m net profit; early IR packs round or classify these as INR965,320m, INR106,723m profit before tax before exceptional items and INR60,768m net income. Group KPI network sites are 181,376, while the India-mobile operating review's 154,097 is a narrower scope."
add_series("bharti_airtel", "total_customers", dict(zip(airtel_years, [357.428,372.354,413.822,403.645,422.100,469.864,489.729,518.446,561.970,590.514])), scope="group total customer base across consolidated operations; includes mobile and non-mobile customer categories disclosed in KPI table", source_ids=override_sources(override_sources(override_sources(override_sources(override_sources(airtel_customer_sources_with_exact_2020_2024, 2016, airtel_2016_ir_kpi_sources), 2017, airtel_2017_ir_kpi_sources), 2018, airtel_2018_ir_kpi_sources), 2019, airtel_2019_ir_kpi_sources), 2025, airtel_2025_with_annual), note=f"{airtel_fy2016_scope_note} {airtel_fy2017_scope_note} {airtel_fy2018_scope_note} {airtel_fy2019_scope_note} {airtel_fy2020_scope_note} {airtel_fy2021_2022_scope_note}")
add_series("bharti_airtel", "revenue", dict(zip(airtel_years, [965321,942506,826388,807802,846765,1006158,1165469,1539257,1643643,1815110])), scope="consolidated Bharti Airtel; latest comparable basis preferred", source_ids=override_sources(override_sources(override_sources(override_sources(override_sources(airtel_sources_with_exact_2020_2024, 2016, airtel_2016_annual_financial_sources), 2017, airtel_2017_annual_financial_sources), 2018, airtel_2018_annual_financial_sources), 2019, airtel_2019_annual_financial_sources), 2025, airtel_2025_with_annual), note=f"{airtel_fy2016_scope_note} {airtel_fy2017_scope_note} FY2018 later annual-report comparatives recast revenue to INR826,388m from the earlier INR836,879m results-pack basis. {airtel_fy2020_scope_note} {airtel_fy2021_2022_scope_note} FY2023 uses the later recast INR1,539,257m, replacing the earlier INR1,391,448m basis. FY2024 is repeated exactly in four later IR packs. FY2025 uses the latest pack basis with full-period Indus Towers consolidation; the May 2025 release's INR1,729,850m reported-basis figure is excluded.")
add_series("bharti_airtel", "ebitda", dict(zip(airtel_years, [341682,356208,304479,262937,347696,461387,581103,768378,889064,1049994])), scope="consolidated EBITDA; latest comparable basis preferred", source_ids=override_sources(override_sources(override_sources(override_sources(override_sources(airtel_sources_with_exact_2020_2024, 2016, airtel_2016_annual_financial_sources), 2017, airtel_2017_annual_financial_sources), 2018, airtel_2018_annual_financial_sources), 2019, airtel_2019_annual_financial_sources), 2025, airtel_2025_with_annual), note=f"{airtel_fy2016_scope_note} {airtel_fy2017_scope_note} {airtel_fy2020_scope_note} {airtel_fy2021_2022_scope_note} FY2023 later comparable packs recast EBITDA to INR768,378m from the earlier INR717,330m basis.")
add_series("bharti_airtel", "earnings_before_tax", dict(zip(airtel_years, [128463,77232,32669,-17318,-44819,22586,107845,185701,250532,369712])), scope="consolidated annual KPI earnings before tax, with later IR-pack profit-before-tax basis used where explicitly selected", source_ids=override_sources(override_sources(override_sources(override_sources(override_sources(airtel_sources_with_exact_2020_2024, 2016, airtel_2016_annual_financial_sources), 2017, airtel_2017_annual_financial_sources), 2018, airtel_2018_annual_financial_sources), 2019, airtel_2019_annual_financial_sources), 2025, airtel_2025_with_annual), note=f"{airtel_fy2016_scope_note} {airtel_fy2017_scope_note} FY2018 uses the annual KPI earnings-before-tax basis of INR32,669m; the results-pack profit-before-tax line of INR40,601m is a different exceptional-item basis and is excluded. FY2019 uses the annual KPI earnings-before-tax basis of INR-17,318m, repeated in the FY2019, FY2020 and FY2022 annual reports; the FY2019 IR-pack profit-before-tax value of INR-46,606m is a different exceptional-item basis and is excluded. {airtel_fy2020_scope_note} FY2020 uses the IR-pack profit-before-tax basis of INR-44,819m; the annual-report KPI earnings-before-tax value of INR-445,711m is a different exceptional-item definition and remains documented but is not counted as an exact source. {airtel_fy2021_2022_scope_note} FY2021 uses the later consistent comparative profit before tax of INR22,586m, replacing the annual-KPI loss-before-tax value of INR-42,063m. FY2023 later comparable packs recast profit before tax to INR185,701m from the earlier INR172,305m basis.")
add_series("bharti_airtel", "net_profit", dict(zip(airtel_years, [60767,37997,10990,4095,-321832,-150835,42549,82526,77820,337440])), scope="consolidated net profit after exceptional items where disclosed", source_ids=override_sources(override_sources(override_sources(override_sources(override_sources(airtel_sources_with_exact_2020_2024, 2016, airtel_2016_annual_financial_sources), 2017, airtel_2017_annual_financial_sources), 2018, airtel_2018_annual_financial_sources), 2019, airtel_2019_annual_financial_sources), 2025, airtel_2025_with_annual), note=f"{airtel_fy2016_scope_note} {airtel_fy2017_scope_note} FY2018 uses the later exact net income of INR10,990m; the original FY2018 results pack reported INR10,989m and is excluded. {airtel_fy2020_scope_note} {airtel_fy2021_2022_scope_note} FY2023 later comparable packs state INR82,526m after exceptional items instead of the earlier INR83,459m basis. Both are after-exceptional figures on different bases; INR83,459m is not a before-exceptional value. The latest FY2023 before-exceptional figure is INR82,390m.")
add_series("bharti_airtel", "capex", {2016:205919,2017:198745,2018:268176,2019:287427,2020:244866,2021:241685,2022:256616,2023:382145,2024:489268,2025:422904}, scope="consolidated capital expenditure on the performance-at-a-glance basis", source_ids=override_sources(override_sources(override_sources(override_sources(override_sources(airtel_sources_with_exact_2020_2024, 2016, airtel_2016_ir_kpi_sources), 2017, airtel_2017_ir_kpi_sources), 2018, airtel_2018_capex_sources), 2019, airtel_2019_capex_sources), 2025, airtel_2025_ir_sources), note=f"{airtel_fy2016_scope_note} {airtel_fy2017_scope_note} FY2019 stores the repeated IR-pack capex of INR287,427m; the FY2019 annual-report segment-note total of INR327,931m uses a different accounting perimeter and is excluded. {airtel_fy2020_scope_note} {airtel_fy2021_2022_scope_note} FY2023 later comparable packs recast capex to INR382,145m from the earlier INR341,947m basis.")
add_series("bharti_airtel", "net_debt", {2016:835106,2017:913999,2018:1001060,2019:1129899,2020:1245209,2021:1485076,2022:1603073,2023:2042234,2024:1943799,2025:2038384}, scope="consolidated year-end net debt including finance lease obligations where the comparable KPI basis requires it", source_ids=override_sources(override_sources(override_sources(override_sources(override_sources(airtel_sources_with_exact_2020_2024, 2016, airtel_2016_ir_kpi_sources), 2017, airtel_2017_ir_kpi_sources), 2018, airtel_2018_net_debt_sources), 2019, airtel_2019_ir_kpi_sources), 2025, airtel_2025_with_annual), note=f"{airtel_fy2016_scope_note} {airtel_fy2017_scope_note} FY2018 stores comparable net debt including lease obligations (INR1,001,060m); the contemporaneous pre-lease value of INR952,285m remains documented but is excluded. FY2019 stores comparable net debt including INR47,553m lease obligations (INR1,129,899m); the contemporaneous pre-lease net debt of INR1,082,346m remains documented but is excluded from the exact-source set. {airtel_fy2020_scope_note} {airtel_fy2021_2022_scope_note} FY2023 later comparable packs recast net debt to INR2,042,234m from the earlier INR2,131,264m basis.")
add_series("bharti_airtel", "shareholders_equity", {2016:667693,2017:674563,2018:695344,2019:714222,2020:771448,2021:589527,2022:665543,2023:775629,2024:820188,2025:1136718}, scope="consolidated shareholder equity", source_ids=override_sources(override_sources(override_sources(override_sources(override_sources(airtel_sources_with_exact_2020_2024, 2016, airtel_2016_ir_kpi_sources), 2017, airtel_2017_ir_kpi_sources), 2018, airtel_2018_ir_kpi_sources), 2019, airtel_2019_ir_kpi_sources), 2025, airtel_2025_ir_sources), note=f"{airtel_fy2016_scope_note} {airtel_fy2017_scope_note} FY2018 uses later comparable shareholder equity of INR695,344m; the original FY2018 results pack's INR695,322m is excluded. {airtel_fy2020_scope_note} {airtel_fy2021_2022_scope_note} Later official IR packs state FY2023 INR775,629m, FY2024 INR820,188m and FY2025 INR1,136,718m. The FY2025 annual report's INR1,136,719m is excluded from that year's exact-source count.")
add_series("bharti_airtel", "network_towers", dict(zip(airtel_years, [181376,184255,187541,204356,219546,244504,268848,309054,355150,375146])), scope="group KPI network towers reported in performance-at-a-glance packs", source_ids=override_sources(override_sources(override_sources(override_sources(override_sources(airtel_sources_with_exact_2020_2024, 2016, airtel_2016_ir_kpi_sources), 2017, airtel_2017_ir_kpi_sources), 2018, airtel_2018_ir_kpi_sources), 2019, airtel_2019_ir_kpi_sources), 2025, airtel_2025_ir_sources), note=f"{airtel_fy2016_scope_note} {airtel_fy2017_scope_note} {airtel_fy2018_scope_note} {airtel_fy2019_scope_note} {airtel_fy2020_scope_note} {airtel_fy2021_2022_scope_note} FY2020 annual report also showed 194,409 in a narrower India-mobile scope; group KPI value 219,546 is retained. FY2023-FY2025 are bound to exact later quarterly IR packs.")
add_series("bharti_airtel", "mobile_broadband_base_stations", {2016:118197,2017:190860,2018:298014,2019:417613,2020:503883}, scope="India mobile broadband base stations at fiscal year end", source_ids=override_sources(override_sources(override_sources(override_sources(override_sources(airtel_sources, 2016, airtel_2016_network_detail_sources), 2017, airtel_2017_network_detail_sources), 2018, airtel_2018_network_detail_sources), 2019, airtel_2019_network_detail_sources), 2020, airtel_2020_network_detail_sources), note="FY2017 stores the exact 190,860 year-end total repeated in the FY2017 results pack and later annual/results comparatives. The FY2017 annual report's 136,479 figure describes cumulative rollout over two years, not the year-end installed total, and is excluded.")
add_series("bharti_airtel", "total_data_traffic", {2016:0.597,2017:0.903,2018:3.9018,2019:11.733,2020:21.020}, scope="FY2016-FY2017 are consolidated annual headlines; FY2018-FY2020 are India mobile annual data traffic, converted from billion MB to billion GB", source_ids=override_sources(override_sources(override_sources(override_sources(airtel_sources, 2016, airtel_2016_traffic_sources), 2018, airtel_2018_network_detail_sources), 2019, airtel_2019_network_detail_sources), 2020, airtel_2020_network_detail_sources), note="FY2016's 597bn-MB and FY2017's 903bn-MB figures are consolidated annual headlines and are not directly comparable with the later India-mobile series. FY2016 is supported only by the contemporaneous annual report and FY2017 remains below the three-document threshold.")

# Reliance Jio: commercial service launched September 2016; FY2016 is not applicable.
jio_years = list(range(2017,2026))
jio_sources = {y:[f"reliance_jio_ar_{y}", "jio_2022_q4" if y == 2022 else "jio_2024_q4" if y == 2024 else "jio_2025_q4" if y == 2025 else f"reliance_jio_ar_{min(y+1,2025)}"] for y in jio_years}
jio_2024_operating_sources = ["reliance_jio_ar_2024", "jio_2024_q4", "jio_2025_media_release", "jio_2024_factsheet"]
jio_2024_financial_sources = ["reliance_jio_ar_2025", "jio_2025_media_release", "jio_2025_integrated_financials"]
jio_2022_operating_sources = ["reliance_jio_ar_2022", "jio_2022_q4", "jio_2023_q4", "jio_2023_media_release"]
jio_2023_operating_three = ["reliance_jio_ar_2023", "jio_2023_q4", "jio_2023_media_release"]
jio_2025_operating_three = ["reliance_jio_ar_2025", "jio_2025_q4", "jio_2025_media_release"]
jio_2025_financial_three = ["reliance_jio_ar_2025", "jio_2025_media_release", "jio_q2_2026_integrated_filing"]
jio_2017_customer_three = ["reliance_jio_ar_2017", "reliance_jio_ar_2018", "jio_2018_q4_media_release"]
jio_2018_financial_three = ["reliance_jio_ar_2018", "reliance_jio_ar_2019", "jio_2018_q4_media_release"]
jio_2019_operating_three = ["reliance_jio_ar_2019", "reliance_jio_ar_2020", "jio_2019_q4_analyst_presentation", "jio_2019_q4_media_release"]
jio_2019_ebit_three = ["reliance_jio_ar_2019", "reliance_jio_ar_2020", "jio_2019_q4_media_release"]
jio_2019_value_two = ["reliance_jio_ar_2019", "jio_2019_q4_media_release"]
jio_2020_operating_three = ["reliance_jio_ar_2020", "jio_2020_rjil_media_release", "jio_2020_ril_media_release"]
jio_2020_ebitda_three = ["reliance_jio_ar_2021", "reliance_jio_ar_2022", "jio_2021_q4_analyst_presentation"]
jio_2020_financial_two = ["reliance_jio_ar_2021", "reliance_jio_ar_2022"]
jio_2021_financial_three = ["reliance_jio_ar_2021", "reliance_jio_ar_2022", "reliance_jio_ar_2023"]
jio_2021_operating_three = ["reliance_jio_ar_2021", "reliance_jio_ar_2022", "jio_2021_q4_analyst_presentation"]
jio_2021_traffic_three = ["reliance_jio_ar_2021", "reliance_jio_ar_2022", "reliance_jio_ar_2023"]
jio_customer_sources = dict(jio_sources)
for _year, _source_ids in {
    2017: jio_2017_customer_three,
    2018: jio_2018_financial_three,
    2019: jio_2019_operating_three,
    2020: jio_2020_operating_three,
    2021: jio_2021_operating_three,
    2022: jio_2022_operating_sources,
    2023: jio_2023_operating_three,
    2024: jio_2024_operating_sources,
    2025: jio_2025_operating_three,
}.items():
    jio_customer_sources[_year] = _source_ids
add_series("reliance_jio", "total_customers", {2016:None,2017:108.9,2018:186.6,2019:306.7,2020:387.5,2021:426.2,2022:410.2,2023:439.3,2024:481.8,2025:488.2}, scope="Jio total mobile/fixed customer base at fiscal year end", source_ids={2016:["reliance_jio_ar_2016"], **jio_customer_sources}, note="FY2016 predates commercial launch and is not applicable; the FY2022 decline reflects active-base cleanup/churn, not a transcription error.")
add_series("reliance_jio", "churn", {2016:None,2017:None,2018:0.25,2019:None,2020:None,2021:None,2022:None,2023:None,2024:None,2025:None}, unit="percent_per_month", scope="monthly subscriber churn disclosed in the FY2018 year-end operating update", basis="exit_quarter", source_ids=override_sources({y:[f"reliance_jio_ar_{y}"] for y in YEARS}, 2018, ["reliance_jio_ar_2018", "jio_2018_q4_media_release", "jio_2018_standalone_media_release", "reliance_sustainability_2018"]), note="Only FY2018 is populated because four separate official documents state the exact 0.25% monthly churn. Later qualitative or differently timed churn disclosures are not substituted for annual values.")
add_series("reliance_jio", "value_of_sales_and_services", {2016:None,2017:None,2018:23916,2019:46506,2020:69605,2021:90287,2022:100166,2023:119791,2024:132938,2025:154119}, unit="INR_crore", scope="RIL Digital Services segment value of sales/services (gross revenue terminology in older reports)", source_ids={2016:["reliance_jio_ar_2016"],2017:["reliance_jio_ar_2017"], **override_sources(override_sources(override_sources(override_sources(override_sources(override_sources(override_sources(override_sources(jio_sources, 2018, jio_2018_financial_three), 2019, jio_2019_value_two), 2020, jio_2020_financial_two), 2021, jio_2021_financial_three), 2022, ["reliance_jio_ar_2023"]), 2023, ["reliance_jio_ar_2023", "reliance_jio_ar_2024", "jio_q2_2024_media_release"]), 2024, ["reliance_jio_ar_2025", "jio_2025_media_release", "jio_2024_factsheet"]), 2025, jio_2025_financial_three)}, note="FY2019 excludes the later INR48,660 crore presentation basis; only documents stating INR46,506 crore are counted. FY2020 excludes the contemporaneous INR68,462 crore basis and retains the later exact INR69,605 crore comparative repeated in the FY2021 and FY2022 annual reports. FY2021 is repeated exactly in the FY2021, FY2022 and FY2023 annual reports. FY2022 keeps the latest official comparative/restated value of INR100,166 crore; the FY2022 annual report and results release state the earlier INR100,161 crore and are excluded from the exact-source count. FY2024-25 use the RIL Digital Services segment basis consistently. JPL consolidated gross revenue is a different scope and is excluded.")
add_series("reliance_jio", "revenue_from_operations", {2016:None,2017:None,2018:None,2019:None,2020:59407,2021:76642,2022:85122,2023:101961,2024:113176,2025:131336}, unit="INR_crore", scope="RIL Digital Services segment revenue from operations", source_ids=override_sources(override_sources(override_sources(override_sources(override_sources({y:jio_sources.get(y,[f"reliance_jio_ar_{y}"]) for y in YEARS}, 2020, jio_2020_financial_two), 2021, jio_2021_financial_three), 2022, ["reliance_jio_ar_2023"]), 2024, ["reliance_jio_ar_2025"]), 2025, ["reliance_jio_ar_2025"]), note="FY2020 uses the later exact INR59,407 crore comparative repeated in the FY2021 and FY2022 annual reports; the contemporaneous report used a different segment presentation. FY2021 is repeated exactly in the FY2021, FY2022 and FY2023 annual reports. FY2022 uses the exact later comparative in the FY2023 annual report. The Q4 analyst presentations use consolidated JPL revenue (INR109,558 crore for FY2024 and INR128,218 crore for FY2025), not the RIL Digital Services segment values stored here; those documents are intentionally excluded from the exact-source count.")
add_series("reliance_jio", "ebitda", {2016:None,2017:None,2018:None,2019:None,2020:23348,2021:34035,2022:40268,2023:50286,2024:56675,2025:65001}, unit="INR_crore", scope="RIL Digital Services segment EBITDA", source_ids=override_sources(override_sources(override_sources(override_sources(override_sources(override_sources({y:jio_sources.get(y,[f"reliance_jio_ar_{y}"]) for y in YEARS}, 2020, jio_2020_ebitda_three), 2021, jio_2021_operating_three), 2022, ["reliance_jio_ar_2022", "jio_2022_q4", "reliance_jio_ar_2023"]), 2023, ["reliance_jio_ar_2023", "reliance_jio_ar_2024", "jio_2023_q4", "jio_2023_media_release"]), 2024, jio_2024_financial_sources), 2025, jio_2025_financial_three), note="FY2020 stores the later comparable Digital Services EBITDA repeated in the FY2021 and FY2022 annual reports and FY2021 analyst presentation; the contemporaneous FY2020 annual report's earlier INR22,517 crore basis is excluded. FY2022-25 use the RIL Digital Services segment basis consistently; consolidated JPL EBITDA and presentation values on another scope are not counted unless the same document also states the exact segment value.")
add_series("reliance_jio", "ebit", {2018:3174,2019:8784}, unit="INR_crore", scope="Digital Services segment EBIT; EBITDA was not provided in the reviewed early-year summary", source_ids=override_sources(override_sources(jio_sources, 2018, jio_2018_financial_three), 2019, jio_2019_ebit_three))
add_series("reliance_jio", "mobile_arpu", {2016:None,2017:None,2018:None,2019:126.2,2020:130.6,2021:138.2,2022:167.6,2023:178.8,2024:181.7,2025:206.2}, unit="INR_per_user_month", scope="exit-quarter ARPU, not full-year average", basis="exit_quarter", source_ids=override_sources(override_sources(override_sources(override_sources(override_sources(override_sources(override_sources({y:jio_sources.get(y,[f"reliance_jio_ar_{y}"]) for y in YEARS}, 2019, jio_2019_operating_three), 2020, jio_2020_operating_three), 2021, jio_2021_operating_three), 2022, jio_2022_operating_sources), 2023, jio_2023_operating_three), 2024, ["jio_2024_q4", "jio_2025_media_release", "jio_2024_factsheet"]), 2025, ["jio_2025_q4", "jio_2025_media_release", "jio_2025_factsheet"]))
add_series("reliance_jio", "mobile_dou", {2016:None,2017:None,2018:None,2019:10.9,2020:11.3,2021:13.3,2022:19.7,2023:23.1,2024:28.7,2025:33.6}, scope="exit-quarter average data consumption per user per month", basis="exit_quarter", source_ids=override_sources(override_sources(override_sources(override_sources(override_sources(override_sources(override_sources({y:jio_sources.get(y,[f"reliance_jio_ar_{y}"]) for y in YEARS}, 2019, jio_2019_operating_three), 2020, jio_2020_operating_three), 2021, jio_2021_operating_three), 2022, ["reliance_jio_ar_2022", "jio_2022_q4", "jio_2023_q4"]), 2023, ["reliance_jio_ar_2023", "jio_2023_q4", "jio_2024_q4"]), 2024, ["reliance_jio_ar_2024", "jio_2024_q4", "jio_2025_q4"]), 2025, ["reliance_jio_ar_2025", "jio_2025_q4", "jio_2025_media_release", "jio_2025_factsheet"]))
add_series("reliance_jio", "total_data_traffic", {2016:None,2017:None,2018:None,2019:None,2020:None,2021:62.5,2022:91.4,2023:113.3,2024:148.5,2025:184.5}, scope="annual Jio network data traffic", source_ids=override_sources(override_sources(override_sources(override_sources(override_sources({y:jio_sources.get(y,[f"reliance_jio_ar_{y}"]) for y in YEARS}, 2021, jio_2021_traffic_three), 2022, ["reliance_jio_ar_2022", "jio_2022_q4", "jio_2023_media_release"]), 2023, jio_2023_operating_three), 2024, jio_2024_operating_sources), 2025, ["jio_2025_media_release", "jio_q1_2026_media_release", "jio_q2_2026_media_release", "jio_q3_2026_media_release"]), note="FY2025 stores the exact 184.5 billion GB value repeated in the FY2025 annual-results operating table and the Q1-Q3 FY2026 results releases' FY2025 comparative columns. Rounded 185-exabyte disclosures and the later 185.5-bn factsheet value are different precision/date bases and are not counted as exact corroboration.")
add_series("reliance_jio", "5g_network_subscribers", {2023:None,2024:108,2025:191}, scope="5G users on Jio True5G network", source_ids=override_sources(override_sources(jio_sources, 2024, ["reliance_jio_ar_2024", "jio_2024_q4", "jio_2024_factsheet"]), 2025, ["reliance_jio_ar_2025", "jio_2025_q4", "jio_2025_media_release", "jio_2025_factsheet"]))
add_series("reliance_jio", "connected_homes", {2021:None,2022:5,2023:9,2024:12,2025:18}, scope="JioFiber/JioAirFiber connected premises; lower-bound wording in several annual reports", comparator=">=", source_ids=override_sources(override_sources(override_sources(override_sources(jio_sources, 2022, ["reliance_jio_ar_2022", "jio_2022_q4", "jio_rjil_ar_2022"]), 2023, ["reliance_jio_ar_2023"]), 2024, ["reliance_jio_ar_2024", "jio_2024_factsheet"]), 2025, ["reliance_jio_ar_2025", "jio_2025_q4", "jio_2025_factsheet"]), note="FY2024 is aligned to the annual report and factsheet (~12 million); the earlier 11 million Q4 presentation figure is not counted because it reflects a different cut-off/rounding basis.")
add_series("reliance_jio", "5g_base_stations", {2023:0.060,2024:1.0,2025:1.0}, scope="5G sites/cells; FY2023 is sites, FY2024-25 are cells and therefore not a continuous comparable series", comparator=">=", source_ids=override_sources(override_sources(override_sources(jio_sources, 2023, jio_2023_operating_three), 2024, ["reliance_jio_ar_2024", "jio_2024_factsheet", "jio_q2_2024_media_release"]), 2025, ["jio_2025_factsheet"]), note="Metric kept for evidence discovery but scope_break=true in quality audit; FY2023 is a directly corroborated ~60,000-site value, FY2024 is a directly corroborated lower bound of over one million cells, and FY2025 retains only the factsheet because the annual report and Q4 presentation do not repeat the exact cell count.")
add_series("reliance_jio", "spectrum_holdings", {2016:None,2017:None,2018:None,2019:None,2020:None,2021:None,2022:None,2023:None,2024:None,2025:26801}, unit="MHz_uplink_plus_downlink", scope="total Jio spectrum footprint across bands, uplink plus downlink", source_ids=override_sources({y:[f"reliance_jio_ar_{y}"] for y in YEARS}, 2025, ["reliance_jio_ar_2025", "jio_q1_2025_analyst_presentation", "jio_2024_spectrum_acquisition_release", "jio_q1_2025_media_release"]), note="FY2025 is the exact post-June-2024-auction spectrum footprint. Four independent official RIL/Jio documents disclose the same 26,801 MHz uplink-plus-downlink value; earlier years remain unfilled rather than backcast from the current footprint.")

# China Broadnet: nationwide mobile service started in 2022.  It is not a
# listed company and does not publish a comparable consolidated annual-report
# series.  Mobile, broadband, ARPU, traffic and financial gaps are therefore
# explicit rather than filled from MIIT industry totals or provincial network
# companies.  Nationwide cable-TV rows are retained as a separate federated /
# industry scope and must never be treated as China Broadnet-owned customers.
CBN_2022_STATS = ["china_broadnet_nrta_2022", "china_broadnet_jiacreat_filing_2022", "china_broadnet_lianhe_rating_2022"]
CBN_2022_REVENUE = ["china_broadnet_nrta_2022", "china_broadnet_lianhe_rating_2022", "china_broadnet_lianhe_rating_revenue_2022"]
CBN_2023_STATS = ["china_broadnet_nrta_2023", "china_broadnet_crta_2023", "china_broadnet_guangxi_ar_2023"]
CBN_2023_HD = ["china_broadnet_nrta_2023", "china_broadnet_crta_2023", "china_broadnet_cctv_2023"]
CBN_2023_SHARED_NETWORK = ["china_broadnet_digital_china_2023", "china_broadnet_cww_network_2023", "china_broadnet_broker_network_2023"]
CBN_2024_STATS = ["china_broadnet_nrta_2024", "china_broadnet_crta_2024", "china_broadnet_jiangsu_bond_2024"]
CBN_2024_CABLE_REVENUE = ["china_broadnet_nrta_2024", "china_broadnet_crta_2024", "china_broadnet_people_2024"]
CBN_2025_USERS = ["china_broadnet_nrta_2025", "china_broadnet_cww_2025", "china_broadnet_cena_2025"]
CBN_2025_CABLE = ["china_broadnet_nrta_2025", "china_broadnet_nbs_2025", "china_broadnet_szse_filing_2025"]
CBN_2025_TWO_WAY = ["china_broadnet_nrta_2025", "china_broadnet_cww_2025", "china_broadnet_cena_2025"]
CBN_2025_HD = ["china_broadnet_nrta_2025", "china_broadnet_cena_2025", "china_broadnet_zhonghong_2025"]
CBN_2025_REVENUE = ["china_broadnet_nrta_2025", "china_broadnet_cww_2025", "china_broadnet_chinacatv_2025"]
CBN_CABLE_SCOPE = "nationwide cable-TV industry/federated operating system; not China Broadnet consolidated owned customer count"
CBN_SOURCE_GAP_NOTE = "No comparable China Broadnet consolidated disclosure was found; industry aggregates and provincial cable-network company figures are intentionally not substituted."

add_series("china_broadnet", "mobile_subscribers", {y:None for y in YEARS}, scope="China Broadnet nationwide mobile subscriber base excluding IoT; separately disclosed total not found", source_ids={y:[] for y in YEARS}, note=CBN_SOURCE_GAP_NOTE)
add_series("china_broadnet", "5g_network_subscribers", {y:None for y in range(2016, 2022)}, scope="China Broadnet 5G users", source_ids={y:[] for y in range(2016, 2022)}, note="Nationwide commercial mobile service had not launched; not a zero estimate.")
add_series("china_broadnet", "5g_network_subscribers", {2022:5.5}, scope="China Broadnet 5G users", comparator=">", source_ids={2022:CBN_2022_STATS}, note="Official lower bound; three distinct public documents repeat the same nationwide regulator statistic, not three independent measurements.")
add_series("china_broadnet", "5g_network_subscribers", {2023:23}, scope="China Broadnet 5G users", comparator=">", source_ids={2023:CBN_2023_STATS}, note="Official lower bound; three distinct public documents corroborate the value.")
add_series("china_broadnet", "5g_network_subscribers", {2024:32.7546}, scope="China Broadnet 5G users", source_ids={2024:CBN_2024_STATS + ["china_broadnet_people_2024"]}, note="Exact year-end figure appears in four distinct public documents; downstream documents repeat the regulator statistic rather than providing independent measurements.")
add_series("china_broadnet", "5g_network_subscribers", {2025:42}, scope="China Broadnet 5G users", comparator="≈", source_ids={2025:CBN_2025_USERS}, note="Official wording is 'nearly 42 million'; retained as an approximate value, never as an exact closing count.")
add_series("china_broadnet", "fixed_broadband_subscribers", {y:None for y in YEARS}, scope="China Broadnet consolidated nationwide fixed-broadband subscribers", source_ids={y:[] for y in YEARS}, note=CBN_SOURCE_GAP_NOTE)
add_series("china_broadnet", "mobile_arpu", {y:None for y in YEARS}, unit="RMB_per_user_month", scope="China Broadnet mobile ARPU", source_ids={y:[] for y in YEARS}, note=CBN_SOURCE_GAP_NOTE)
add_series("china_broadnet", "broadband_arpu", {y:None for y in YEARS}, unit="RMB_per_user_month", scope="China Broadnet fixed-broadband ARPU", source_ids={y:[] for y in YEARS}, note=CBN_SOURCE_GAP_NOTE)
add_series("china_broadnet", "mobile_dou", {y:None for y in YEARS}, scope="China Broadnet monthly mobile data usage per user", source_ids={y:[] for y in YEARS}, note=CBN_SOURCE_GAP_NOTE)
add_series("china_broadnet", "total_data_traffic", {y:None for y in YEARS}, scope="China Broadnet annual mobile data traffic", source_ids={y:[] for y in YEARS}, note="MIIT totals include China Broadnet from February 2024 but do not disclose a company-specific series; the aggregate is not substituted.")
add_series("china_broadnet", "5g_base_stations", {y:None for y in range(2016, 2022)}, scope="700MHz 5G base stations co-built and shared with China Mobile", source_ids={y:[] for y in range(2016, 2022)}, note="Pre-network years; not a zero estimate.")
add_series("china_broadnet", "5g_base_stations", {2022:0.48}, scope="700MHz 5G base stations co-built and shared with China Mobile; not wholly owned by China Broadnet", source_ids={2022:["china_broadnet_nrta_tech_review_2022", "china_mobile_sd_2022", "china_mobile_results_2022"]}, note="Shared-network scope; never add this row to China Mobile's base-station total.")
add_series("china_broadnet", "5g_base_stations", {2023:0.62}, scope="700MHz 5G base stations co-built and shared with China Mobile; not wholly owned by China Broadnet", source_ids={2023:["china_mobile_ar_2023", "china_mobile_sd_2023", "china_mobile_results_2023"]}, note="Shared-network scope; never add this row to China Mobile's base-station total.")
add_series("china_broadnet", "5g_base_stations", {2024:None, 2025:None}, scope="700MHz 5G base stations co-built and shared with China Mobile", source_ids={2024:[], 2025:[]}, note="Only interim or differently scoped shared-network totals were found; no year-end value is substituted.")
add_series("china_broadnet", "shared_4g_5g_base_stations", {2023:4.0}, scope="China Mobile 4G/5G base stations available to China Broadnet through network sharing", comparator=">", source_ids={2023:CBN_2023_SHARED_NETWORK}, note="Network-access evidence appears in three distinct public documents, but downstream reports share the China Broadnet chairman statement lineage; these are available shared stations, not owned assets.")

add_series("china_broadnet", "cable_tv_actual_users", {2022:200, 2023:202, 2024:208, 2025:207}, scope=CBN_CABLE_SCOPE, source_ids={2022:CBN_2022_STATS, 2023:["china_broadnet_nrta_2023", "china_broadnet_crta_2023", "china_broadnet_shaanxi_ar_2023"], 2024:CBN_2024_CABLE_REVENUE, 2025:CBN_2025_CABLE}, note="Industry/federated scope only; provincial legal entities were not fully consolidated into a single comparable corporate customer base. Corroborating documents can share the same regulator-statistic lineage.")
add_series("china_broadnet", "two_way_digital_cable_tv_users", {2022:98.2, 2023:100, 2024:None, 2025:105}, scope=CBN_CABLE_SCOPE, source_ids={2022:CBN_2022_STATS, 2023:["china_broadnet_nrta_2023", "china_broadnet_crta_2023", "china_broadnet_shaanxi_ar_2023"], 2024:[], 2025:CBN_2025_TWO_WAY}, note="Industry/federated scope; corroborating documents can share the same regulator-statistic lineage.")
add_series("china_broadnet", "hd_uhd_cable_tv_users", {2022:110, 2023:109, 2024:110, 2025:111}, scope=CBN_CABLE_SCOPE, source_ids={2022:CBN_2022_STATS, 2023:CBN_2023_HD, 2024:CBN_2024_STATS, 2025:CBN_2025_HD}, note="Industry/federated scope; corroborating documents can share the same regulator-statistic lineage.")
add_series("china_broadnet", "uhd_cable_tv_users", {2023:42, 2024:45, 2025:56}, scope=CBN_CABLE_SCOPE, source_ids={2023:CBN_2023_HD, 2024:CBN_2024_STATS, 2025:CBN_2025_HD}, note="Industry/federated scope; corroborating documents can share the same regulator-statistic lineage.")
add_series("china_broadnet", "cable_network_industry_revenue", {2022:71955, 2023:None, 2024:73937, 2025:72158}, unit="RMB_million", scope="nationwide cable-TV network industry revenue; not China Broadnet consolidated corporate revenue", source_ids={2022:CBN_2022_REVENUE, 2023:[], 2024:CBN_2024_CABLE_REVENUE, 2025:CBN_2025_REVENUE}, note="Stored only as industry context. Never answer this as China Broadnet corporate revenue; corroborating documents can share the same regulator-statistic lineage.")
for metric_key in ["revenue", "ebitda", "earnings_before_tax", "net_profit", "capex", "net_debt", "shareholders_equity"]:
    add_series("china_broadnet", metric_key, {y:None for y in YEARS}, unit="RMB_million", scope=f"China Broadnet consolidated {METRICS[metric_key][0]}", source_ids={y:[] for y in YEARS}, note=CBN_SOURCE_GAP_NOTE)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "operator_id", "operator", "legal_name", "year", "period", "period_end", "grain",
        "metric_key", "metric_zh", "value", "official_value", "unit", "comparator", "scope",
        "basis", "verification_status", "verification_count", "distinct_source_document_count",
        "distinct_source_document_ids",
        "triple_source_status", "primary_source_id",
        "primary_source_url", "verification_sources", "candidate_sources", "quality_note",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            item = dict(row)
            item["verification_sources"] = json.dumps(item["verification_sources"], ensure_ascii=False)
            item["candidate_sources"] = json.dumps(item["candidate_sources"], ensure_ascii=False)
            item["distinct_source_document_ids"] = json.dumps(item["distinct_source_document_ids"], ensure_ascii=False)
            writer.writerow(item)


def build_coverage(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    required = {
        "china_mobile": ["mobile_subscribers","5g_network_subscribers","fixed_broadband_subscribers","mobile_arpu","mobile_dou","handset_data_traffic","5g_base_stations"],
        "china_telecom": ["mobile_subscribers","5g_network_subscribers","fixed_broadband_subscribers","mobile_arpu","handset_data_traffic","5g_base_stations"],
        "china_unicom": ["mobile_subscribers","5g_network_subscribers","fixed_broadband_subscribers","mobile_arpu","mobile_dou","4g_base_stations","5g_base_stations"],
        "china_broadnet": ["mobile_subscribers","5g_network_subscribers","fixed_broadband_subscribers","mobile_arpu","broadband_arpu","mobile_dou","total_data_traffic","5g_base_stations","cable_tv_actual_users","revenue","ebitda","net_profit","capex"],
        "bharti_airtel": ["total_customers","revenue","ebitda","net_profit","capex","network_towers","total_data_traffic"],
        "reliance_jio": ["total_customers","value_of_sales_and_services","revenue_from_operations","ebitda","mobile_arpu","mobile_dou","total_data_traffic","5g_network_subscribers","connected_homes","5g_base_stations"],
    }
    index = {(r["operator_id"], r["year"], r["metric_key"]): r for r in rows}
    result = []
    for operator_id, metrics in required.items():
        for year in YEARS:
            for metric in metrics:
                row = index.get((operator_id, year, metric))
                if not row:
                    status = "not_collected"
                elif row["value"] is None:
                    status = "not_applicable_precommercial" if (
                        (operator_id == "reliance_jio" and year <= 2016)
                        or (operator_id == "china_broadnet" and year <= 2021 and metric in {"mobile_subscribers", "5g_network_subscribers", "5g_base_stations"})
                    ) else "source_gap_confirmed"
                else:
                    status = "available"
                result.append({"operator_id":operator_id,"operator":OPERATORS[operator_id]["name"],"year":year,"metric_key":metric,"status":status})
    return result


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ORIGINAL_DB.mkdir(parents=True, exist_ok=True)
    rows = sorted(ROWS, key=lambda r: (r["operator_id"], r["year"], r["metric_key"]))
    for row in rows:
        if row["operator_id"] == "reliance_jio" and row["year"] == 2016:
            row["verification_status"] = "not_applicable_precommercial"
            row["basis"] = "precommercial_not_applicable"
        if row["operator_id"] == "china_broadnet" and row["year"] <= 2021 and row["metric_key"] in {"mobile_subscribers", "5g_network_subscribers", "5g_base_stations"}:
            row["verification_status"] = "not_applicable_precommercial"
            row["basis"] = "precommercial_not_applicable"
        if row["operator_id"] == "china_unicom" and row["metric_key"] in {"mobile_subscribers", "fixed_broadband_subscribers"} and row["year"] >= 2023:
            row["verification_status"] = "official_derived_from_verified_rows"
            row["triple_source_status"] = "derived_not_directly_disclosed"
            row["basis"] = "official_year_end_plus_disclosed_net_addition"
            row["comparator"] = "≈"
            row["quality_note"] = "Derived from official prior-year closing value plus official disclosed net additions; rounded to two decimals and not presented as a directly reported exact closing figure."
        if row["operator_id"] == "china_mobile" and row["metric_key"] == "handset_data_traffic":
            row["verification_status"] = "official_derived_from_verified_quarters"
            row["triple_source_status"] = "derived_not_directly_disclosed"
            row["basis"] = "official_quarterly_sum"
            row["quality_note"] = "Derived only by summing the four official quarterly handset-data-traffic values; not treated as a directly disclosed annual value."
    keys = [(r["operator_id"], r["year"], r["metric_key"], r["scope"]) for r in rows]
    duplicate_keys = [list(key) for key, count in Counter(keys).items() if count > 1]
    invalid_source_ids = sorted({sid for r in rows for sid in r["candidate_sources"] if sid not in SOURCES})
    coverage = build_coverage(rows)
    available = [r for r in rows if r["value"] is not None]
    triple_source_rows = [
        r for r in available
        if r["distinct_source_document_count"] >= 3 and "derived" not in r["verification_status"]
    ]
    status_counts = Counter(r["verification_status"] for r in rows)
    operator_counts = Counter(r["operator"] for r in available)
    triple_source_operator_counts = Counter(r["operator"] for r in triple_source_rows)
    metric_counts = Counter(r["metric_key"] for r in available)
    quality = {
        "generated_at": BUILD_TIME,
        "status": "fail" if duplicate_keys or invalid_source_ids else ("pass" if len(triple_source_rows) == len(available) else "backlog_open"),
        "row_count": len(rows),
        "available_value_rows": len(available),
        "three_distinct_source_certified_rows": len(triple_source_rows),
        "below_three_source_rows": len(available) - len(triple_source_rows),
        "source_count": len(SOURCES),
        "duplicate_key_count": len(duplicate_keys),
        "duplicate_keys": duplicate_keys,
        "invalid_source_ids": invalid_source_ids,
        "verification_status_counts": dict(sorted(status_counts.items())),
        "available_rows_by_operator": dict(sorted(operator_counts.items())),
        "three_source_certified_rows_by_operator": dict(sorted(triple_source_operator_counts.items())),
        "available_rows_by_metric": dict(sorted(metric_counts.items())),
        "scope_breaks": [
            "A formal three-source claim requires at least three distinct underlying source documents; mirrored URLs, evidence sections, and snapshots of one document count once.",
            "5G package subscribers and 5G network subscribers are distinct metrics.",
            "China Telecom and China Unicom 5G base-station values describe a shared network and must not be added together.",
            "Airtel network-tower scope changes around FY2020; the narrower 194,409 and group KPI 219,546 values are documented, with group KPI retained.",
            "Airtel FY2019 group KPI packs report 204,356 towers while the India-mobile manufactured-capital disclosure reports 181,079; the group KPI is retained and the two scopes must not be mixed.",
            "Airtel FY2019 annual KPI earnings before tax is INR-17,318m, while the results-pack profit-before-tax line is INR-46,606m; both are official but use different exceptional-item definitions.",
            "Airtel FY2018 later comparatives recast revenue, net profit and shareholder equity, add finance lease obligations to net debt, and use a wider group-tower KPI than the India-mobile manufactured-capital section.",
            "Jio FY2023 reports 5G sites while FY2024 onward reports 5G cells; growth is not calculated across the break.",
            "Airtel latest comparative basis restates FY2023-FY2025 financials; latest official comparative basis is retained.",
            "Airtel FY2021 profit before tax is retained on the later four-pack comparative basis of INR22,586m; the earlier INR-42,063m loss-before-tax basis remains documented in the row note.",
            "Airtel FY2020 uses the IR-pack profit-before-tax basis of INR-44,819m; the annual-report KPI INR-445,711m uses a different exceptional-item definition. FY2020 total customers also changed from an earlier 423.287m to the later 422.100m basis.",
            "Airtel FY2022 exact comparatives explicitly exclude the consolidation impact of erstwhile Bharti Infratel/Indus Towers; FY2023 onward uses a later recast basis, so direct growth across the boundary needs a scope warning.",
            "Jio value of sales/services is not the same as revenue from operations; both are stored separately.",
            "Airtel and Jio use total_customers because their group disclosures include non-mobile categories; these rows are not mobile-subscriber counts.",
        ],
    }
    conflicts = [
        {"operator_id":"bharti_airtel","years":"2023-2025","metric":"financials","type":"restatement_or_scope_change","selected_basis":"latest official comparative basis","detail":"Later investor packs changed comparative consolidated figures; latest like-for-like official comparatives are retained and earlier values remain documented in row notes."},
        {"operator_id":"bharti_airtel","years":"2016","metric":"revenue","type":"restatement_or_rounding_change","selected_basis":"annual KPI revenue INR 965,321 million","detail":"Three later annual KPI tables repeat INR 965,321 million. The contemporaneous FY2016 IR pack reported INR 965,320 million and is excluded from the exact-source set."},
        {"operator_id":"bharti_airtel","years":"2016","metric":"earnings_before_tax","type":"definition_conflict","selected_basis":"annual KPI earnings before tax INR 128,463 million","detail":"Three later annual KPI tables repeat INR 128,463 million. The contemporaneous FY2016 IR pack reports INR 106,723 million as profit before tax before exceptional items, a different definition."},
        {"operator_id":"bharti_airtel","years":"2016","metric":"net_profit","type":"restatement_or_rounding_change","selected_basis":"annual KPI net profit INR 60,767 million","detail":"Three later annual KPI tables repeat INR 60,767 million. The contemporaneous FY2016 IR pack reported INR 60,768 million and is excluded from the exact-source set."},
        {"operator_id":"bharti_airtel","years":"2016","metric":"network_towers","type":"scope_conflict","selected_basis":"group KPI 181,376","detail":"The India-mobile operating review reports 154,097 network towers. Three full-year performance-at-a-glance packs repeat the broader group KPI of 181,376, which is retained."},
        {"operator_id":"bharti_airtel","years":"2016","metric":"total_data_traffic","type":"scope_break","selected_basis":"consolidated annual headline 0.597 billion GB","detail":"FY2016 is a consolidated traffic headline supported by one underlying document; FY2018-FY2020 are India-mobile traffic. The FY2016 row remains below the three-document threshold and must not be used as a continuous like-for-like series point."},
        {"operator_id":"bharti_airtel","years":"2019","metric":"network_towers","type":"scope_conflict","selected_basis":"group KPI 204,356","detail":"The FY2019 India-mobile manufactured-capital section reports 181,079 network towers. The group performance-at-a-glance series reports 204,356 and is retained for cross-year comparability."},
        {"operator_id":"bharti_airtel","years":"2019","metric":"total_customers","type":"restatement_or_scope_change","selected_basis":"403.645 million repeated by three independent official documents","detail":"The later FY2023 annual report alone gives 402.418 million for FY2019. It is preserved as a later single-document restatement but cannot replace the three-document exact basis."},
        {"operator_id":"bharti_airtel","years":"2019","metric":"earnings_before_tax","type":"definition_conflict","selected_basis":"annual KPI earnings before tax INR -17,318 million","detail":"Three annual reports repeat INR -17,318 million on the annual KPI basis; the contemporaneous IR-pack profit-before-tax line of INR -46,606 million uses a different exceptional-item presentation and is excluded from the exact-source set."},
        {"operator_id":"bharti_airtel","years":"2019","metric":"capex","type":"scope_conflict","selected_basis":"IR-pack consolidated capex INR 287,427 million","detail":"Three IR packs repeat INR 287,427 million. The annual-report segment note totals INR 327,931 million on a different accounting perimeter and is excluded."},
        {"operator_id":"bharti_airtel","years":"2019","metric":"net_debt","type":"definition_change","selected_basis":"comparable net debt including finance lease obligations INR 1,129,899 million","detail":"The pre-lease net debt subtotal is INR 1,082,346 million; adding disclosed lease obligations of INR 47,553 million gives the comparable KPI used by later reports."},
        {"operator_id":"bharti_airtel","years":"2018","metric":"revenue","type":"restatement_or_scope_change","selected_basis":"later comparative INR 826,388 million","detail":"The original FY2018 results pack reported INR 836,879 million; three later annual reports repeat INR 826,388 million, which is retained."},
        {"operator_id":"bharti_airtel","years":"2018","metric":"earnings_before_tax","type":"definition_conflict","selected_basis":"annual KPI earnings before tax INR 32,669 million","detail":"Later annual KPI tables repeat INR 32,669 million. The FY2018 results-pack profit-before-tax line is INR 40,601 million on a different exceptional-item presentation."},
        {"operator_id":"bharti_airtel","years":"2018","metric":"net_profit","type":"restatement_or_rounding_change","selected_basis":"later comparative INR 10,990 million","detail":"The original FY2018 results pack reported INR 10,989 million; three later annual reports repeat INR 10,990 million."},
        {"operator_id":"bharti_airtel","years":"2018","metric":"net_debt","type":"definition_change","selected_basis":"comparable net debt including finance lease obligations INR 1,001,060 million","detail":"The contemporaneous pre-lease net debt was INR 952,285 million. Later comparative KPI tables include finance lease obligations and repeat INR 1,001,060 million."},
        {"operator_id":"bharti_airtel","years":"2018","metric":"shareholders_equity","type":"restatement_or_rounding_change","selected_basis":"later comparative INR 695,344 million","detail":"The original FY2018 results pack stated INR 695,322 million; later official comparisons consistently state INR 695,344 million."},
        {"operator_id":"bharti_airtel","years":"2018","metric":"network_towers","type":"scope_conflict","selected_basis":"group KPI 187,541","detail":"The India-mobile manufactured-capital disclosure reports 165,748 towers. The group performance-at-a-glance value is retained for cross-year comparability."},
        {"operator_id":"bharti_airtel","years":"2017","metric":"revenue","type":"restatement_or_scope_change","selected_basis":"later comparable INR 942,506 million","detail":"The FY2017 and FY2018 results packs reported INR 954,684 million. The FY2019 pack and later annual KPI tables restated/reclassified the comparable value to INR 942,506 million, which is retained."},
        {"operator_id":"bharti_airtel","years":"2017","metric":"earnings_before_tax","type":"definition_conflict","selected_basis":"annual KPI earnings before tax INR 77,232 million","detail":"The results packs report INR 88,929 million as profit before tax before exceptional items. Three later annual KPI tables repeat INR 77,232 million after exceptional items, which is retained."},
        {"operator_id":"bharti_airtel","years":"2017","metric":"network_towers","type":"scope_conflict","selected_basis":"group KPI 184,255","detail":"The India-mobile operating review reports 162,046 network towers. Three full-year performance-at-a-glance packs repeat the broader group KPI of 184,255, which is retained."},
        {"operator_id":"bharti_airtel","years":"2017","metric":"total_data_traffic","type":"scope_break","selected_basis":"consolidated annual headline 0.903 billion GB","detail":"FY2017 is a consolidated traffic headline; FY2018-FY2020 are India-mobile traffic. The FY2017 row remains below the three-document threshold and must not be used as a continuous like-for-like series point."},
        {"operator_id":"bharti_airtel","years":"2021","metric":"earnings_before_tax","type":"restatement_or_scope_change","selected_basis":"INR 22,586 million from four later official comparative tables","detail":"The earlier stored INR -42,063 million loss-before-tax basis is retained in the row note but replaced by the value repeated consistently across four FY2023-24 investor packs."},
        {"operator_id":"bharti_airtel","years":"2020","metric":"earnings_before_tax","type":"definition_conflict","selected_basis":"IR-pack profit before tax INR -44,819 million","detail":"Three FY2022-23 investor packs repeat INR -44,819 million. Annual-report KPI tables show INR -445,711 million under a different exceptional-item definition; that value is documented but not counted as exact corroboration."},
        {"operator_id":"bharti_airtel","years":"2020","metric":"total_customers","type":"restatement_or_scope_change","selected_basis":"later comparative 422.100 million customers","detail":"The FY2022-23 Q1 pack still states 423.287 million; Q2, Q3 and the FY2023 annual report consistently state 422.100 million, which is retained."},
        {"operator_id":"bharti_airtel","years":"2022-2023","metric":"financials_and_group_kpis","type":"scope_break","selected_basis":"retain each year's exact official basis with warning","detail":"Four FY2023-24 packs explicitly exclude the Indus consolidation impact for FY2022, while FY2023 onward is stored on the later recast basis; no unqualified growth comparison is valid across the boundary."},
        {"operator_id":"bharti_airtel","years":"2020","metric":"network_towers","type":"scope_conflict","selected_basis":"group KPI 219,546","detail":"The same reporting set also presents 194,409 under a narrower mobile-network scope."},
        {"operator_id":"reliance_jio","years":"2020","metric":"value_of_sales_and_services","type":"presentation_basis_conflict","selected_basis":"INR 69,605 crore from later official three-year table","detail":"An older narrative cited INR 68,462 crore under an earlier presentation basis."},
        {"operator_id":"reliance_jio","years":"2023-2025","metric":"5g_base_stations","type":"scope_break","selected_basis":"retain disclosed figure with scope label","detail":"FY2023 reports sites; FY2024-25 report cells. No cross-break growth calculation is valid."},
        {"operator_id":"china_telecom/china_unicom","years":"2020-2025","metric":"5g_base_stations","type":"shared_network","selected_basis":"same shared-network figure retained for both with warning","detail":"The figures describe co-built/shared mid-band stations and must never be summed across the two operators."},
        {"operator_id":"china_mobile/china_telecom/china_unicom","years":"2019-2025","metric":"5g_subscribers","type":"definition_change","selected_basis":"package and network users stored as separate metrics","detail":"5G package subscribers and active/network subscribers are not interchangeable."},
        {"operator_id":"china_unicom","years":"2023-2025","metric":"mobile_subscribers/fixed_broadband_subscribers","type":"official_derived","selected_basis":"prior official closing plus disclosed official net addition","detail":"Derived values are marked approximate; they are not presented as directly disclosed exact closings."},
        {"operator_id":"china_broadnet","years":"2022-2025","metric":"5g_network_subscribers","type":"disclosure_precision_change","selected_basis":"retain regulator wording and comparator for each year","detail":"FY2022-23 are lower bounds, FY2024 is exact, and FY2025 is approximate; they must not all be presented as exact closings."},
        {"operator_id":"china_mobile/china_broadnet","years":"2022-2025","metric":"5g_base_stations","type":"shared_network","selected_basis":"same 700MHz co-built/shared network with explicit scope warning","detail":"China Broadnet rows describe access to the China Mobile co-built 700MHz network and must never be added to China Mobile's total or treated as wholly owned assets."},
        {"operator_id":"china_broadnet","years":"2022-2025","metric":"cable_tv_actual_users/cable_network_industry_revenue","type":"industry_scope","selected_basis":"retain as separately labelled nationwide cable-industry context","detail":"The nationwide cable figures cover a federated industry system and are not a consolidated China Broadnet corporate customer or revenue series."},
    ]
    payload = {
        "dataset_id": "global_top5_operators_2016_2025",
        "generated_at": BUILD_TIME,
        "ranking_basis": "FY2025/latest-available officially reported group customer scale; scopes are mixed and the ranking is used only to select research subjects.",
        "non_duplication_policy": "China Mobile/Telecom/Unicom financial rows are referenced from the existing quarterly database and are not copied. This dataset adds operating history for those three, disclosed China Broadnet history plus explicit corporate gaps, and complete disclosed history for Airtel/Jio.",
        "operators": OPERATORS,
        "metrics": {k:{"metric_zh":v[0],"default_unit":v[1]} for k,v in METRICS.items()},
        "rows": rows,
    }
    (OUT / "annual_metrics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(OUT / "annual_metrics.csv", rows)
    china_financial_metrics = {"revenue", "ebitda", "ebit", "earnings_before_tax", "net_profit", "capex", "net_debt", "shareholders_equity"}
    china_rows = [
        r for r in rows
        if r["operator_id"] in {"china_mobile", "china_telecom", "china_unicom", "china_broadnet"}
        and r["metric_key"] not in china_financial_metrics
    ]
    china_payload = {
        "dataset_id": "china_carriers_annual_operating_metrics_2016_2025",
        "generated_at": BUILD_TIME,
        "relationship": "Operating-metric sidecar to quarterly_metrics.json; existing financial rows are not duplicated.",
        "metrics": {k:{"metric_zh":v[0],"default_unit":v[1]} for k,v in METRICS.items()},
        "rows": china_rows,
    }
    (ORIGINAL_DB / "annual_operating_metrics_2016_2025.json").write_text(json.dumps(china_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(ORIGINAL_DB / "annual_operating_metrics_2016_2025.csv", china_rows)
    china_source_ids = {sid for row in china_rows for sid in row["candidate_sources"]}
    china_sources = [SOURCES[sid] for sid in sorted(china_source_ids) if sid in SOURCES]
    (ORIGINAL_DB / "annual_operating_metrics_2016_2025_sources.json").write_text(
        json.dumps({"generated_at": BUILD_TIME, "sources": china_sources}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    china_available = [row for row in china_rows if row["value"] is not None]
    china_triple = [row for row in china_available if row["distinct_source_document_count"] >= 3]
    china_manifest = {
        "id": "china_carriers_annual_operating_metrics_2016_2025",
        "title": "中国四家基础电信运营商2016–2025年度运营指标补充库",
        "generated_at": BUILD_TIME,
        "row_count": len(china_rows),
        "operators": ["中国移动", "中国电信", "中国联通", "中国广电"],
        "relationship": "quarterly_metrics.json remains the financial fact source; this sidecar adds only operating KPIs.",
        "entrypoints": ["annual_operating_metrics_2016_2025.json", "annual_operating_metrics_2016_2025.csv", "annual_operating_metrics_2016_2025_sources.json"],
        "quality": {
            "status": "pass" if len(china_triple) == len(china_available) else "backlog_open",
            "available_value_rows": len(china_available),
            "three_distinct_source_certified_rows": len(china_triple),
            "below_three_source_rows": len(china_available) - len(china_triple),
        },
    }
    (ORIGINAL_DB / "annual_operating_metrics_2016_2025_manifest.json").write_text(json.dumps(china_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    parent_manifest_path = ORIGINAL_DB / "manifest.json"
    parent_manifest = json.loads(parent_manifest_path.read_text(encoding="utf-8"))
    parent_entrypoints = list(parent_manifest.get("entrypoints") or [])
    for name in [
        "annual_operating_metrics_2016_2025_manifest.json",
        "annual_operating_metrics_2016_2025.json",
        "annual_operating_metrics_2016_2025.csv",
        "annual_operating_metrics_2016_2025_sources.json",
    ]:
        if name not in parent_entrypoints:
            parent_entrypoints.append(name)
    parent_manifest["entrypoints"] = parent_entrypoints
    parent_manifest["updated_at"] = BUILD_TIME
    parent_quality = dict(parent_manifest.get("quality") or {})
    parent_quality["china_carrier_operating_sidecar"] = china_manifest["quality"]
    parent_note = "中国移动、中国电信、中国联通、中国广电年度运营指标侧表已加入入口；三来源按底层文档身份去重，同一报告的镜像网址只计一次；中国广电的全国有线电视行业口径不等同于集团合并口径。"
    parent_notes = parent_quality.setdefault("notes", [])
    if parent_note not in parent_notes:
        parent_notes.append(parent_note)
    parent_manifest["quality"] = parent_quality
    parent_manifest_path.write_text(json.dumps(parent_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (OUT / "sources.json").open("w", encoding="utf-8") as handle:
        json.dump({"generated_at":BUILD_TIME,"sources":list(SOURCES.values())}, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    with (OUT / "coverage.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["operator_id","operator","year","metric_key","status"])
        writer.writeheader(); writer.writerows(coverage)
    (OUT / "quality_audit.json").write_text(json.dumps(quality, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "conflicts_and_scope_breaks.json").write_text(json.dumps({"generated_at":BUILD_TIME,"items":conflicts}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (OUT / "conflicts_and_scope_breaks.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["operator_id","years","metric","type","selected_basis","detail"])
        writer.writeheader(); writer.writerows(conflicts)
    missing = Counter(r["operator"] for r in coverage if r["status"] != "available")
    quality_md = "\n".join([
        "# 全球重点六家运营商数据库质量审计", "",
        f"- 结论：`{quality['status']}`", f"- 明细行：{len(rows)}", f"- 有值行：{len(available)}", f"- 来源条目：{len(SOURCES)}",
        f"- 重复键：{len(duplicate_keys)}", f"- 无效来源引用：{len(invalid_source_ids)}", "",
        "## 全库核验等级", "", *[f"- `{name}`: {count}" for name,count in sorted(status_counts.items())], "",
        "## 三来源认证行（按运营商）", "", *[f"- {name}: {count}" for name,count in sorted(triple_source_operator_counts.items())], "",
        "## 缺口（含不适用）", "", *[f"- {name}: {count}" for name,count in sorted(missing.items())], "",
        "## 关键口径断点", "", *[f"- {item}" for item in quality["scope_breaks"]], "",
        "缺口保留为 `source_gap_confirmed` 或 `not_applicable_precommercial`，没有插值和估算。", "",
    ])
    (OUT / "quality_audit.md").write_text(quality_md, encoding="utf-8")
    summary = "\n".join([
        "# 全球重点六家运营商 2016–2025 数据摘要", "",
        "本库保留原五家客户规模研究对象，并按中国内地第四家基础电信运营商口径加入中国广电。各公司披露范围并不完全一致，排名只用于确定研究对象；中国广电不纳入原五家排名。中国三家上市运营商既有财务数据不复制，中国广电只收录可核验的公开值并保留集团未披露缺口；Airtel 与 Jio 收录可获得的完整财务及运营历史。", "",
        "## 2025 年末客户规模", "",
        "| 排名 | 运营商 | 客户数（百万） | 口径 |", "|---:|---|---:|---|",
        "| 1 | 中国移动 | 1,005.0 | 移动客户 |", "| 2 | Bharti Airtel | 590.5 | 集团总客户口径 |", "| 3 | Reliance Jio | 488.2 | 移动及固网总客户 |", "| 4 | 中国电信 | 438.7 | 移动客户 |", "| 5 | 中国联通 | ≈357.3 | 由官方期初与净增推导的移动出账用户 |", "| 补充 | 中国广电 | ≈42.0 | 广电5G用户；非集团总客户口径，不参与原排名 |", "",
        "## 使用边界", "", "- 排名用于确定研究对象，不代表收入、市值或网络资产排名。", "- 5G套餐用户与5G网络用户不合并。", "- 共建共享基站不在运营商间相加。", "- 财年结束日在中国公司与印度公司之间不同，比较时必须使用 `period_end`。", "- 所有缺口、重述和口径断点见 `quality_audit.md` 与逐行 `quality_note`。", "",
    ])
    (OUT / "summary.md").write_text(summary, encoding="utf-8")
    readme = "\n".join([
        "# 全球重点六家运营商 2016–2025 数据库", "",
        "## 入口", "", "- `annual_metrics.json`：主数据和元数据。", "- `annual_metrics.csv`：长表。", "- `sources.json`：官方来源登记。", "- `coverage.csv`：逐运营商、逐年、逐指标覆盖/缺口。", "- `quality_audit.json` / `quality_audit.md`：质量门禁。", "- `conflicts_and_scope_breaks.json` / `.csv`：重述、冲突、推导值与口径断点。", "- `summary.md`：研究对象与使用边界。", "",
        "## 与原数据库的关系", "", "中国移动、中国电信、中国联通的财务数据继续以 `quarterly_competitor_metrics_2026-06-18/quarterly_metrics.json` 为唯一事实源；中国广电及四家内地运营商的新增运营指标写入该原数据库目录的 `annual_operating_metrics_2016_2025.*`。本目录沿用历史兼容 ID `global_top5_operators_2016_2025`，但内容现为六家整合视图。Airtel 与 Jio 为新增主体，财务和运营数据均在本库。", "",
        "## 重建", "", "```bash", "python3 scripts/build_global_top5_operator_database.py", "```", "",
    ])
    (OUT / "README.md").write_text(readme, encoding="utf-8")
    manifest = {
        "id":"global_top5_operators_2016_2025", "title":"全球重点六家运营商2016–2025财务与运营数据库",
        "summary":"保留原五家研究对象并补入中国广电；中国三家链接既有财务库，中国广电保留公开值及明确缺口，Airtel/Jio收录完整披露历史。",
        "source_type":"official_public_multi_source", "updated_at":BUILD_TIME,
        "tags":["global_carriers","10_year_history","subscribers","5g","broadband","arpu","traffic","base_stations","financials"],
        "entrypoints":["README.md","summary.md","annual_metrics.json","annual_metrics.csv","sources.json","coverage.csv","quality_audit.json","quality_audit.md","conflicts_and_scope_breaks.json","conflicts_and_scope_breaks.csv"],
        "row_count":len(rows), "quality":{
            "status":quality["status"],
            "source_count":len(SOURCES),
            "available_value_rows":len(available),
            "three_distinct_source_certified_rows":len(triple_source_rows),
            "three_source_certified_rows_by_operator":dict(sorted(triple_source_operator_counts.items())),
            "below_three_source_rows":len(available)-len(triple_source_rows),
        },
        "linked_existing_datasets":["quarterly_competitor_metrics_2026-06-18"],
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out":str(OUT),"rows":len(rows),"available":len(available),"sources":len(SOURCES),"quality":quality["status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

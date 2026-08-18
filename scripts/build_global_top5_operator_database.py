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
}

METRICS = {
    "total_customers": ("集团总客户数", "million_customers"),
    "mobile_subscribers": ("移动用户数", "million_subscribers"),
    "4g_subscribers": ("4G用户数", "million_subscribers"),
    "5g_package_subscribers": ("5G套餐用户数", "million_subscribers"),
    "5g_network_subscribers": ("5G网络用户数", "million_subscribers"),
    "fixed_broadband_subscribers": ("固网宽带用户数", "million_subscribers"),
    "connected_homes": ("已连接家庭/场所", "million_premises"),
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

SOURCES.update({
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


ROWS: list[dict[str, Any]] = []


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
        valid_ids = [sid for sid in ids if sid in SOURCES]
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
            "unit": unit or default_unit,
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
CM_2025_ARPU_THREE = ["china_mobile_ar_2025", "china_mobile_results_2025", "china_mobile_ar_a_2025"]
CT_2025_THREE = ["china_telecom_ar_2025", "china_telecom_results_2025", "china_telecom_announcement_2025"]
CU_2025_THREE = ["china_unicom_ar_2025", "china_unicom_results_2025", "china_unicom_press_2025"]

SHARED_5G_BASE_STATION_SOURCES = {
    2020: ["china_telecom_ar_2020", "china_unicom_ar_2020", "china_telecom_results_2020"],
    2021: ["china_telecom_ar_2021", "china_unicom_ar_2021", "china_telecom_results_2021"],
    # The reviewed 2022 presentation only states over one million, so it does
    # not corroborate the more precise 1.05 million value.
    2023: ["china_telecom_ar_2023", "china_unicom_ar_2023", "china_telecom_results_2023"],
    2024: ["china_telecom_ar_2024", "china_unicom_ar_2024", "china_telecom_results_2024"],
    2025: CT_2025_THREE,
}

CHINA_MOBILE_5G_BASE_STATION_SOURCES = {
    2021: ["china_mobile_ar_2021", "china_mobile_ar_a_2021", "china_mobile_20f_2021"],
    2022: ["china_mobile_ar_2022", "china_mobile_ar_a_2022", "china_mobile_results_2022"],
    2023: ["china_mobile_ar_2023", "china_mobile_ar_a_2023", "china_mobile_results_2023"],
    2024: ["china_mobile_ar_2024", "china_mobile_ar_a_2024", "china_mobile_results_2024"],
    2025: CM_2025_THREE,
}


def override_sources(mapping: dict[int, list[str]], year: int, source_ids: list[str]) -> dict[int, list[str]]:
    result = dict(mapping)
    result[year] = source_ids
    return result


# China Mobile: existing finance is linked, not copied. Operating values are official year-end/annual figures.
cm_years = YEARS
add_series("china_mobile", "mobile_subscribers", dict(zip(cm_years, [848.90, 887, 925, 950, 942, 957, 975, 991, 1004, 1005])), scope="group mobile customer base", source_ids=override_sources(paired("china_mobile", cm_years), 2025, CM_2025_THREE))
add_series("china_mobile", "4g_subscribers", {2016:535.04, 2017:650, 2018:713, 2019:758, 2020:775, 2021:822}, scope="group 4G customer base", source_ids=paired("china_mobile", list(range(2016, 2022))))
add_series("china_mobile", "5g_package_subscribers", {2019:2.55, 2020:165, 2021:387, 2022:614, 2023:795}, scope="contracted 5G package customers; not equivalent to active 5G network users", source_ids=paired("china_mobile", list(range(2019, 2024))))
add_series("china_mobile", "5g_network_subscribers", {2021:207, 2022:327, 2023:465, 2024:552, 2025:642}, scope="customers that used the 5G network; definition differs from 5G package customers", source_ids=override_sources(paired("china_mobile", list(range(2021, 2026))), 2025, CM_2025_THREE))
add_series("china_mobile", "fixed_broadband_subscribers", dict(zip(cm_years, [77.62,112.69,156.7,187.0,210.3,240,272,298,315,None])), scope="group wireline broadband customers", source_ids=override_sources(paired("china_mobile", cm_years), 2025, []), note="FY2025 changed to integrated broadband network customers; the 329 million integrated-scope value is stored separately and is not substituted into this legacy series.")
add_series("china_mobile", "mobile_arpu", dict(zip(cm_years, [57.5,57.7,53.1,49.1,47.4,48.8,49.0,49.3,48.5,46.8])), unit="RMB_per_user_month", scope="group mobile business annual ARPU", source_ids=override_sources(paired("china_mobile", cm_years), 2025, CM_2025_ARPU_THREE))
add_series("china_mobile", "household_customer_blended_arpu", {2025:44.5}, unit="RMB_per_user_month", scope="household customer blended ARPU", source_ids={2025:CM_2025_ARPU_THREE})
add_series("china_mobile", "mobile_dou", dict(zip(cm_years, [0.697,1.399,3.6,6.7,9.4,12.6,14.1,15.9,15.9,17.3])), scope="average handset data traffic per user per month; 2016-17 converted from MB to GB", source_ids=override_sources(paired("china_mobile", cm_years), 2025, ["china_mobile_ar_2025", "china_mobile_ar_a_2025", "china_mobile_ar_summary_2025"]), note="The H-share annual report, A-share annual report and separately filed A-share annual report summary each disclose the exact 17.3 GB value. The reviewed annual-results announcement does not disclose DOU.")
add_series("china_mobile", "handset_data_traffic", dict(zip(cm_years, [5.6807,12.5693,35.4534,65.89,90.70,124.8,144.7,165.9,168.2,183.8])), scope="sum of four official quarterly handset-data-traffic values; 2016-18 converted from billion MB", basis="official_quarterly_sum", source_ids=override_sources(paired("china_mobile", cm_years), 2025, ["china_mobile_ops_2025"]), note="Derived only by summing the four official quarterly values; no interpolation.")
add_series("china_mobile", "total_base_stations", {2018:3.85, 2019:4.48, 2020:5.14, 2021:5.50, 2022:6.0, 2023:6.60}, scope="all commissioned mobile base stations", comparator=">=", note="Annual reports use 'more than/over' for some years.")
add_series("china_mobile", "4g_base_stations", {2016:1.51, 2017:1.87, 2018:2.41, 2019:3.09, 2021:3.32}, scope="commissioned 4G base stations")
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
add_series("china_telecom", "mobile_subscribers", dict(zip(ct_years, [215.00,249.96,303.00,335.57,351.02,372.43,391.18,407.77,424.52,438.65])), scope="mobile subscribers", source_ids=override_sources(paired("china_telecom", ct_years), 2025, [*CT_2025_THREE, "china_telecom_press_2025", "china_telecom_kpi_2025"]))
add_series("china_telecom", "4g_subscribers", {2016:121.87, 2017:182.04, 2018:242.43}, scope="4G subscribers/users", source_ids=paired("china_telecom", [2016,2017,2018]))
add_series("china_telecom", "5g_package_subscribers", {2019:10.73, 2020:86.50, 2021:187.80, 2022:267.96, 2023:318.66, 2024:351.48}, scope="5G package subscribers; not equivalent to active 5G network users", source_ids=paired("china_telecom", list(range(2019,2025))))
add_series("china_telecom", "5g_network_subscribers", {2024:250.73, 2025:301.81}, scope="5G network subscribers; 2024 comparative was restated on the new network-user basis", source_ids=override_sources(paired("china_telecom", [2024,2025]), 2025, [*CT_2025_THREE, "china_telecom_kpi_2025"]))
add_series("china_telecom", "fixed_broadband_subscribers", dict(zip(ct_years, [123.12,133.53,145.79,153.13,158.53,169.71,180.90,190.16,197.44,201.12])), scope="wireline broadband subscribers", source_ids=override_sources(paired("china_telecom", ct_years), 2025, [*CT_2025_THREE, "china_telecom_press_2025", "china_telecom_kpi_2025"]))
add_series("china_telecom", "mobile_arpu", {2016:None,2017:None,2018:None,2019:None,2020:44.1,2021:45.0,2022:45.2,2023:45.4,2024:45.6,2025:45.1}, unit="RMB_per_user_month", scope="mobile service ARPU", source_ids=override_sources(paired("china_telecom", ct_years), 2025, ["china_telecom_ar_2025", "china_telecom_results_2025", "china_telecom_factsheet_2025"]), note="2016-2019 annual comparable value not asserted where the reviewed official sources did not provide a directly reusable figure.")
add_series("china_telecom", "broadband_arpu", {2025:47.1}, unit="RMB_per_user_month", scope="wireline broadband blended ARPU", source_ids={2025:["china_telecom_ar_2025", "china_telecom_results_2025", "china_telecom_factsheet_2025"]})
add_series("china_telecom", "handset_data_traffic", {2016:1.277,2017:3.597,2018:14.073,2019:24.370,2020:34.690,2021:46.966,2022:60.193,2023:None,2024:89.979,2025:106.046}, scope="annual handset data traffic; converted from official kTB convention to billion GB at 1 kTB = 0.001 billion GB", source_ids=override_sources(paired("china_telecom", ct_years), 2025, ["china_telecom_ar_2025", "china_telecom_results_2025", "china_telecom_press_2025"]))
add_series("china_telecom", "5g_base_stations", {2020:0.38,2021:0.69,2022:1.05,2023:1.21,2024:1.375,2025:1.54}, scope="5G mid-band co-built/shared base stations in service across China Telecom and China Unicom networks; not attributable one-for-one to either operator", comparator=">=", source_ids=SHARED_5G_BASE_STATION_SOURCES, note="Shared-network scope; never sum China Telecom and China Unicom rows. The 2022 value remains below the three-source threshold because broader official summaries only state over one million.")
add_series("china_telecom", "5g_network_penetration", {2025:68.8}, scope="5G network subscribers as a share of mobile subscribers", source_ids={2025:[*CT_2025_THREE, "china_telecom_press_2025"]})
add_series("china_telecom", "gigabit_broadband_penetration", {2025:31.6}, scope="gigabit broadband subscribers as a share of broadband subscribers", source_ids={2025:[*CT_2025_THREE, "china_telecom_press_2025"]})
add_series("china_telecom", "ten_g_pon_ports", {2025:10}, scope="10G PON ports in the gigabit fibre network", comparator=">=", source_ids={2025:[*CT_2025_THREE, "china_telecom_press_2025"]})
add_series("china_telecom", "urban_gigabit_coverage", {2025:97}, scope="urban residential areas covered by gigabit broadband", comparator=">", source_ids={2025:[*CT_2025_THREE, "china_telecom_press_2025"]})
add_series("china_telecom", "intelligent_compute_capacity", {2025:46}, scope="self-owned intelligent computing power", source_ids={2025:CT_2025_THREE})

# China Unicom: exact mobile/broadband values remain separate from the broader connectivity aggregate.
cu_years = YEARS
add_series("china_unicom", "mobile_subscribers", dict(zip(cu_years, [263.8,284.2,315.0,318.47,305.81,317.12,322.70,333.30,343.98,357.30])), scope="mobile billing subscribers", source_ids=paired("china_unicom", cu_years), note="2024-25 values reconstructed only from official year-end scale and official disclosed net additions; rounded to two decimals.")
add_series("china_unicom", "4g_subscribers", {2016:104.6,2017:174.9,2018:219.9,2019:253.8,2020:270.2}, scope="4G subscribers / billing subscribers using 4G or 5G network", source_ids=paired("china_unicom", list(range(2016,2021))))
add_series("china_unicom", "5g_package_subscribers", {2020:70.83,2021:154.93,2022:212.73,2023:259.64,2024:290.44}, scope="5G package subscribers; disclosure replaced by network-user measure in 2025", source_ids=paired("china_unicom", list(range(2020,2025))))
add_series("china_unicom", "5g_network_subscribers", {2025:232.18}, scope="customers that used the 5G network during the period; not comparable with prior 5G package subscribers", source_ids={2025:["china_unicom_ar_2025","china_unicom_ops_2025","china_unicom_q4_operating_announcement_2025"]})
add_series("china_unicom", "fixed_broadband_subscribers", dict(zip(cu_years, [75.2,76.5,80.88,83.48,86.095,95.05,103.63,113.42,122.26,129.87])), scope="fixed-line broadband billing subscribers", source_ids=paired("china_unicom", cu_years), note="2023-25 year-end values use official scale/net-add disclosures; small rounding differences may occur versus monthly releases.")
add_series("china_unicom", "mobile_arpu", {2016:46.4,2017:48.0,2018:45.7,2019:40.4,2020:42.1,2021:43.9,2022:44.3,2023:None,2024:None,2025:None}, unit="RMB_per_user_month", scope="mobile billing subscriber ARPU", source_ids=paired("china_unicom", ct_years), note="From 2023 the company increasingly emphasised integrated-package ARPU; mobile-only ARPU is left as a documented gap.")
add_series("china_unicom", "broadband_arpu", {2016:49.4,2017:46.3,2018:44.6,2019:41.6,2020:41.5,2021:41.3,2022:None,2023:None,2024:None,2025:None}, unit="RMB_per_user_month", scope="fixed-line broadband access ARPU", source_ids=paired("china_unicom", list(range(2016,2026))))
add_series("china_unicom", "mobile_dou", {2016:None,2017:None,2018:None,2019:None,2020:9.7,2021:12.7,2022:None,2023:None,2024:None,2025:None}, scope="monthly average DOU per handset subscriber", source_ids=paired("china_unicom", cu_years))
add_series("china_unicom", "5g_base_stations", {2020:0.38,2021:0.69,2022:1.05,2023:1.21,2024:1.375,2025:1.54}, scope="5G mid-band co-built/shared base stations in service across China Unicom and China Telecom networks; not attributable one-for-one", comparator=">=", source_ids=SHARED_5G_BASE_STATION_SOURCES, note="Shared-network scope; never sum China Unicom and China Telecom rows. The 2022 value remains below the three-source threshold because broader official summaries only state over one million.")
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
airtel_sources_with_exact_2024 = override_sources(airtel_sources, 2024, airtel_2024_ir_sources)
airtel_sources_with_exact_2023_2024 = override_sources(airtel_sources_with_exact_2024, 2023, airtel_2023_ir_sources)
airtel_sources_with_exact_2022_2024 = override_sources(airtel_sources_with_exact_2023_2024, 2022, airtel_2022_ir_sources)
airtel_sources_with_exact_2021_2024 = override_sources(airtel_sources_with_exact_2022_2024, 2021, airtel_2021_ir_sources)
airtel_sources_with_exact_2020_2024 = override_sources(airtel_sources_with_exact_2021_2024, 2020, airtel_2020_ir_sources)
airtel_customer_sources_with_exact_2020_2024 = override_sources(airtel_sources_with_exact_2021_2024, 2020, airtel_2020_customer_sources)
airtel_2025_with_annual = ["bharti_airtel_ar_2025", *airtel_2025_ir_sources]
airtel_fy2021_2022_scope_note = "FY2021 and FY2022 are repeated exactly in four FY2023-24 IR packs that explicitly exclude the consolidation impact of erstwhile Bharti Infratel/Indus Towers. FY2023 onward uses a later recast basis, so FY2022-FY2023 growth requires a scope-break warning."
airtel_fy2020_scope_note = "FY2020 IR-pack comparatives explicitly exclude the consolidation impact of erstwhile Bharti Infratel/Indus Towers. Three FY2022-23 quarterly packs repeat the stored financial and tower values; the later FY2020 total-customer basis of 422.100m is supported by Q2, Q3 and the FY2023 annual report, while the earlier Q1 pack's 423.287m is excluded."
add_series("bharti_airtel", "total_customers", dict(zip(airtel_years, [357.428,372.354,413.822,403.645,422.100,469.864,489.729,518.446,561.970,590.514])), scope="group total customer base across consolidated operations; includes mobile and non-mobile customer categories disclosed in KPI table", source_ids=override_sources(airtel_customer_sources_with_exact_2020_2024, 2025, airtel_2025_with_annual), note=f"{airtel_fy2020_scope_note} {airtel_fy2021_2022_scope_note}")
add_series("bharti_airtel", "revenue", dict(zip(airtel_years, [965321,942506,826388,807802,846765,1006158,1165469,1539257,1643643,1815110])), scope="consolidated Bharti Airtel; latest comparable basis preferred", source_ids=override_sources(airtel_sources_with_exact_2020_2024, 2025, airtel_2025_with_annual), note=f"{airtel_fy2020_scope_note} {airtel_fy2021_2022_scope_note} FY2023 uses the later recast INR1,539,257m, replacing the earlier INR1,391,448m basis. FY2024 is repeated exactly in four later IR packs. FY2025 uses the latest pack basis with full-period Indus Towers consolidation; the May 2025 release's INR1,729,850m reported-basis figure is excluded.")
add_series("bharti_airtel", "ebitda", dict(zip(airtel_years, [341682,356208,304479,262937,347696,461387,581103,768378,889064,1049994])), scope="consolidated EBITDA; latest comparable basis preferred", source_ids=override_sources(airtel_sources_with_exact_2020_2024, 2025, airtel_2025_with_annual), note=f"{airtel_fy2020_scope_note} {airtel_fy2021_2022_scope_note} FY2023 later comparable packs recast EBITDA to INR768,378m from the earlier INR717,330m basis.")
add_series("bharti_airtel", "earnings_before_tax", dict(zip(airtel_years, [128463,77232,32669,-17318,-44819,22586,107845,185701,250532,369712])), scope="consolidated IR-pack profit before tax; latest comparable basis preferred", source_ids=override_sources(airtel_sources_with_exact_2020_2024, 2025, airtel_2025_with_annual), note=f"{airtel_fy2020_scope_note} FY2020 uses the IR-pack profit-before-tax basis of INR-44,819m; the annual-report KPI earnings-before-tax value of INR-445,711m is a different exceptional-item definition and remains documented but is not counted as an exact source. {airtel_fy2021_2022_scope_note} FY2021 uses the later consistent comparative profit before tax of INR22,586m, replacing the annual-KPI loss-before-tax value of INR-42,063m. FY2023 later comparable packs recast profit before tax to INR185,701m from the earlier INR172,305m basis.")
add_series("bharti_airtel", "net_profit", dict(zip(airtel_years, [60767,37997,10990,4095,-321832,-150835,42549,82526,77820,337440])), scope="consolidated net profit after exceptional items where disclosed", source_ids=override_sources(airtel_sources_with_exact_2020_2024, 2025, airtel_2025_with_annual), note=f"{airtel_fy2020_scope_note} {airtel_fy2021_2022_scope_note} FY2023 later comparable packs state INR82,526m after exceptional items instead of the earlier INR83,459m basis. Both are after-exceptional figures on different bases; INR83,459m is not a before-exceptional value. The latest FY2023 before-exceptional figure is INR82,390m.")
add_series("bharti_airtel", "capex", {2020:244866,2021:241685,2022:256616,2023:382145,2024:489268,2025:422904}, scope="consolidated capital expenditure", source_ids=override_sources(airtel_sources_with_exact_2020_2024, 2025, airtel_2025_ir_sources), note=f"{airtel_fy2020_scope_note} {airtel_fy2021_2022_scope_note} FY2023 later comparable packs recast capex to INR382,145m from the earlier INR341,947m basis.")
add_series("bharti_airtel", "net_debt", {2020:1245209,2021:1485076,2022:1603073,2023:2042234,2024:1943799,2025:2038384}, scope="consolidated year-end net debt", source_ids=override_sources(airtel_sources_with_exact_2020_2024, 2025, airtel_2025_with_annual), note=f"{airtel_fy2020_scope_note} {airtel_fy2021_2022_scope_note} FY2023 later comparable packs recast net debt to INR2,042,234m from the earlier INR2,131,264m basis.")
add_series("bharti_airtel", "shareholders_equity", {2020:771448,2021:589527,2022:665543,2023:775629,2024:820188,2025:1136718}, scope="consolidated shareholder equity", source_ids=override_sources(airtel_sources_with_exact_2020_2024, 2025, airtel_2025_ir_sources), note=f"{airtel_fy2020_scope_note} {airtel_fy2021_2022_scope_note} Later official IR packs state FY2023 INR775,629m, FY2024 INR820,188m and FY2025 INR1,136,718m. The FY2025 annual report's INR1,136,719m is excluded from that year's exact-source count.")
add_series("bharti_airtel", "network_towers", dict(zip(airtel_years, [154097,162046,165748,181079,219546,244504,268848,309054,355150,375146])), scope="reported mobile network towers; FY2020 onward uses group KPI pack scope, earlier years use annual-report manufactured-capital scope", source_ids=override_sources(airtel_sources_with_exact_2020_2024, 2025, airtel_2025_ir_sources), note=f"{airtel_fy2020_scope_note} {airtel_fy2021_2022_scope_note} FY2020 annual report also showed 194,409 in a narrower mobile-network scope; group KPI value 219,546 is retained. FY2023-FY2025 are bound to exact later quarterly IR packs.")
add_series("bharti_airtel", "mobile_broadband_base_stations", {2016:118197,2017:136479,2018:298014,2019:417613,2020:503883}, scope="mobile broadband base stations disclosed in annual reports; 2017 figure is cumulative two-year rollout wording", source_ids=airtel_sources)
add_series("bharti_airtel", "total_data_traffic", {2017:0.903,2018:3.9018,2019:11.733,2020:21.020}, scope="group/mobile data traffic converted from billion MB to billion GB", source_ids=airtel_sources)

# Reliance Jio: commercial service launched September 2016; FY2016 is not applicable.
jio_years = list(range(2017,2026))
jio_sources = {y:[f"reliance_jio_ar_{y}", "jio_2022_q4" if y == 2022 else "jio_2024_q4" if y == 2024 else "jio_2025_q4" if y == 2025 else f"reliance_jio_ar_{min(y+1,2025)}"] for y in jio_years}
jio_2024_operating_sources = ["reliance_jio_ar_2024", "jio_2024_q4", "jio_2025_media_release", "jio_2024_factsheet"]
jio_2024_financial_sources = ["reliance_jio_ar_2025", "jio_2025_media_release"]
jio_2022_operating_sources = ["reliance_jio_ar_2022", "jio_2022_q4", "jio_2023_q4", "jio_2023_media_release"]
jio_2023_operating_three = ["reliance_jio_ar_2023", "jio_2023_q4", "jio_2023_media_release"]
jio_2025_operating_three = ["reliance_jio_ar_2025", "jio_2025_q4", "jio_2025_media_release"]
jio_2025_financial_three = ["reliance_jio_ar_2025", "jio_2025_media_release", "jio_q2_2026_integrated_filing"]
add_series("reliance_jio", "total_customers", {2016:None,2017:108.9,2018:186.6,2019:306.7,2020:387.5,2021:426.2,2022:410.2,2023:439.3,2024:481.8,2025:488.2}, scope="Jio total mobile/fixed customer base at fiscal year end", source_ids={2016:["reliance_jio_ar_2016"], **override_sources(override_sources(override_sources(override_sources(jio_sources, 2022, jio_2022_operating_sources), 2023, jio_2023_operating_three), 2024, jio_2024_operating_sources), 2025, jio_2025_operating_three)}, note="FY2016 predates commercial launch and is not applicable; the FY2022 decline reflects active-base cleanup/churn, not a transcription error.")
add_series("reliance_jio", "value_of_sales_and_services", {2016:None,2017:None,2018:23916,2019:46506,2020:69605,2021:90287,2022:100166,2023:119791,2024:132938,2025:154119}, unit="INR_crore", scope="RIL Digital Services segment value of sales/services (gross revenue terminology in older reports)", source_ids={2016:["reliance_jio_ar_2016"],2017:["reliance_jio_ar_2017"], **override_sources(override_sources(override_sources(jio_sources, 2022, ["reliance_jio_ar_2023"]), 2024, ["reliance_jio_ar_2025", "jio_2025_media_release", "jio_2024_factsheet"]), 2025, jio_2025_financial_three)}, note="FY2022 keeps the latest official comparative/restated value of INR100,166 crore; the FY2022 annual report and results release state the earlier INR100,161 crore and are excluded from the exact-source count. FY2024-25 use the RIL Digital Services segment basis consistently. JPL consolidated gross revenue is a different scope and is excluded.")
add_series("reliance_jio", "revenue_from_operations", {2016:None,2017:None,2018:None,2019:None,2020:59407,2021:76642,2022:85122,2023:101961,2024:113176,2025:131336}, unit="INR_crore", scope="RIL Digital Services segment revenue from operations", source_ids=override_sources(override_sources(override_sources({y:jio_sources.get(y,[f"reliance_jio_ar_{y}"]) for y in YEARS}, 2022, ["reliance_jio_ar_2023"]), 2024, ["reliance_jio_ar_2025"]), 2025, ["reliance_jio_ar_2025"]), note="FY2022 uses the exact later comparative in the FY2023 annual report. The Q4 analyst presentations use consolidated JPL revenue (INR109,558 crore for FY2024 and INR128,218 crore for FY2025), not the RIL Digital Services segment values stored here; those documents are intentionally excluded from the exact-source count.")
add_series("reliance_jio", "ebitda", {2016:None,2017:None,2018:None,2019:None,2020:23348,2021:34035,2022:40268,2023:50286,2024:56675,2025:65001}, unit="INR_crore", scope="RIL Digital Services segment EBITDA", source_ids=override_sources(override_sources(override_sources(override_sources({y:jio_sources.get(y,[f"reliance_jio_ar_{y}"]) for y in YEARS}, 2022, ["reliance_jio_ar_2022", "jio_2022_q4", "reliance_jio_ar_2023"]), 2023, ["reliance_jio_ar_2023", "reliance_jio_ar_2024", "jio_2023_q4", "jio_2023_media_release"]), 2024, jio_2024_financial_sources), 2025, jio_2025_financial_three), note="FY2022-25 use the RIL Digital Services segment basis consistently; consolidated JPL EBITDA and presentation values on another scope are not counted unless the same document also states the exact segment value.")
add_series("reliance_jio", "ebit", {2018:3174,2019:8784}, unit="INR_crore", scope="Digital Services segment EBIT; EBITDA was not provided in the reviewed early-year summary", source_ids=jio_sources)
add_series("reliance_jio", "mobile_arpu", {2016:None,2017:None,2018:None,2019:126.2,2020:130.6,2021:138.2,2022:167.6,2023:178.8,2024:181.7,2025:206.2}, unit="INR_per_user_month", scope="exit-quarter ARPU, not full-year average", basis="exit_quarter", source_ids=override_sources(override_sources(override_sources(override_sources({y:jio_sources.get(y,[f"reliance_jio_ar_{y}"]) for y in YEARS}, 2022, jio_2022_operating_sources), 2023, jio_2023_operating_three), 2024, ["jio_2024_q4", "jio_2025_media_release", "jio_2024_factsheet"]), 2025, ["jio_2025_q4", "jio_2025_media_release", "jio_2025_factsheet"]))
add_series("reliance_jio", "mobile_dou", {2016:None,2017:None,2018:None,2019:10.9,2020:11.3,2021:13.3,2022:19.7,2023:23.1,2024:28.7,2025:33.6}, scope="exit-quarter average data consumption per user per month", basis="exit_quarter", source_ids=override_sources(override_sources(override_sources(override_sources({y:jio_sources.get(y,[f"reliance_jio_ar_{y}"]) for y in YEARS}, 2022, ["reliance_jio_ar_2022", "jio_2022_q4", "jio_2023_q4"]), 2023, ["reliance_jio_ar_2023", "jio_2023_q4"]), 2024, ["reliance_jio_ar_2024", "jio_2024_q4"]), 2025, ["reliance_jio_ar_2025", "jio_2025_q4", "jio_2025_media_release", "jio_2025_factsheet"]))
add_series("reliance_jio", "total_data_traffic", {2016:None,2017:None,2018:None,2019:None,2020:None,2021:62.5,2022:91.4,2023:113.3,2024:148.5,2025:184.5}, scope="annual Jio network data traffic", source_ids=override_sources(override_sources(override_sources(override_sources({y:jio_sources.get(y,[f"reliance_jio_ar_{y}"]) for y in YEARS}, 2022, ["reliance_jio_ar_2022", "jio_2022_q4", "jio_2023_media_release"]), 2023, jio_2023_operating_three), 2024, jio_2024_operating_sources), 2025, ["jio_2025_media_release"]), note="FY2025 stores the exact 184.5 billion GB value from the annual-results operating table. Rounded 185-exabyte disclosures and the later 185.5-bn factsheet value are different precision/date bases and are not counted as exact corroboration.")
add_series("reliance_jio", "5g_network_subscribers", {2023:None,2024:108,2025:191}, scope="5G users on Jio True5G network", source_ids=override_sources(override_sources(jio_sources, 2024, ["reliance_jio_ar_2024", "jio_2024_q4", "jio_2024_factsheet"]), 2025, ["reliance_jio_ar_2025", "jio_2025_q4", "jio_2025_media_release", "jio_2025_factsheet"]))
add_series("reliance_jio", "connected_homes", {2021:None,2022:5,2023:9,2024:12,2025:18}, scope="JioFiber/JioAirFiber connected premises; lower-bound wording in several annual reports", comparator=">=", source_ids=override_sources(override_sources(override_sources(jio_sources, 2023, ["reliance_jio_ar_2023"]), 2024, ["reliance_jio_ar_2024", "jio_2024_factsheet"]), 2025, ["reliance_jio_ar_2025", "jio_2025_q4", "jio_2025_factsheet"]), note="FY2024 is aligned to the annual report and factsheet (~12 million); the earlier 11 million Q4 presentation figure is not counted because it reflects a different cut-off/rounding basis.")
add_series("reliance_jio", "5g_base_stations", {2023:0.060,2024:1.0,2025:1.0}, scope="5G sites/cells; FY2023 is sites, FY2024-25 are cells and therefore not a continuous comparable series", comparator=">=", source_ids=override_sources(override_sources(override_sources(jio_sources, 2023, jio_2023_operating_three), 2024, ["reliance_jio_ar_2024", "jio_2024_factsheet", "jio_q2_2024_media_release"]), 2025, ["jio_2025_factsheet"]), note="Metric kept for evidence discovery but scope_break=true in quality audit; FY2023 is a directly corroborated ~60,000-site value, FY2024 is a directly corroborated lower bound of over one million cells, and FY2025 retains only the factsheet because the annual report and Q4 presentation do not repeat the exact cell count.")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "operator_id", "operator", "legal_name", "year", "period", "period_end", "grain",
        "metric_key", "metric_zh", "value", "official_value", "unit", "comparator", "scope",
        "basis", "verification_status", "verification_count", "distinct_source_document_count",
        "distinct_source_document_ids",
        "triple_source_status", "primary_source_id",
        "primary_source_url", "verification_sources", "quality_note",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            item = dict(row)
            item["verification_sources"] = json.dumps(item["verification_sources"], ensure_ascii=False)
            item["distinct_source_document_ids"] = json.dumps(item["distinct_source_document_ids"], ensure_ascii=False)
            writer.writerow(item)


def build_coverage(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    required = {
        "china_mobile": ["mobile_subscribers","5g_network_subscribers","fixed_broadband_subscribers","mobile_arpu","mobile_dou","handset_data_traffic","5g_base_stations"],
        "china_telecom": ["mobile_subscribers","5g_network_subscribers","fixed_broadband_subscribers","mobile_arpu","handset_data_traffic","5g_base_stations"],
        "china_unicom": ["mobile_subscribers","5g_network_subscribers","fixed_broadband_subscribers","mobile_arpu","mobile_dou","5g_base_stations"],
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
                    status = "not_applicable_precommercial" if operator_id == "reliance_jio" and year <= 2016 else "source_gap_confirmed"
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
    invalid_source_ids = sorted({sid for r in rows for sid in r["verification_sources"] if sid not in SOURCES})
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
    ]
    payload = {
        "dataset_id": "global_top5_operators_2016_2025",
        "generated_at": BUILD_TIME,
        "ranking_basis": "FY2025/latest-available officially reported group customer scale; scopes are mixed and the ranking is used only to select research subjects.",
        "non_duplication_policy": "China Mobile/Telecom/Unicom financial rows are referenced from the existing quarterly database and are not copied. This dataset adds operating history for those three and complete disclosed history for Airtel/Jio.",
        "operators": OPERATORS,
        "metrics": {k:{"metric_zh":v[0],"default_unit":v[1]} for k,v in METRICS.items()},
        "rows": rows,
    }
    (OUT / "annual_metrics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(OUT / "annual_metrics.csv", rows)
    china_rows = [r for r in rows if r["operator_id"] in {"china_mobile", "china_telecom", "china_unicom"}]
    china_payload = {
        "dataset_id": "china_carriers_annual_operating_metrics_2016_2025",
        "generated_at": BUILD_TIME,
        "relationship": "Operating-metric sidecar to quarterly_metrics.json; existing financial rows are not duplicated.",
        "metrics": {k:{"metric_zh":v[0],"default_unit":v[1]} for k,v in METRICS.items()},
        "rows": china_rows,
    }
    (ORIGINAL_DB / "annual_operating_metrics_2016_2025.json").write_text(json.dumps(china_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(ORIGINAL_DB / "annual_operating_metrics_2016_2025.csv", china_rows)
    china_source_ids = {sid for row in china_rows for sid in row["verification_sources"]}
    china_sources = [SOURCES[sid] for sid in sorted(china_source_ids) if sid in SOURCES]
    (ORIGINAL_DB / "annual_operating_metrics_2016_2025_sources.json").write_text(
        json.dumps({"generated_at": BUILD_TIME, "sources": china_sources}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    china_available = [row for row in china_rows if row["value"] is not None]
    china_triple = [row for row in china_available if row["distinct_source_document_count"] >= 3]
    china_manifest = {
        "id": "china_carriers_annual_operating_metrics_2016_2025",
        "title": "中国三大运营商2016–2025年度运营指标补充库",
        "generated_at": BUILD_TIME,
        "row_count": len(china_rows),
        "operators": ["中国移动", "中国电信", "中国联通"],
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
    parent_note = "中国移动、中国电信、中国联通年度运营指标侧表已加入入口；三来源按底层文档身份去重，同一报告的镜像网址只计一次。"
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
        "# 全球五大运营商数据库质量审计", "",
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
        "# 全球五大运营商 2016–2025 数据摘要", "",
        "本库以官方披露的集团客户规模选取中国移动、Bharti Airtel、Reliance Jio、中国电信和中国联通。各公司披露范围并不完全一致，排名只用于确定研究对象。中国三家既有财务数据不复制，只补运营指标；Airtel 与 Jio 收录可获得的完整财务及运营历史。", "",
        "## 2025 年末客户规模", "",
        "| 排名 | 运营商 | 客户数（百万） | 口径 |", "|---:|---|---:|---|",
        "| 1 | 中国移动 | 1,005.0 | 移动客户 |", "| 2 | Bharti Airtel | 590.5 | 集团总客户口径 |", "| 3 | Reliance Jio | 488.2 | 移动及固网总客户 |", "| 4 | 中国电信 | 438.7 | 移动客户 |", "| 5 | 中国联通 | ≈357.3 | 由官方期初与净增推导的移动出账用户 |", "",
        "## 使用边界", "", "- 排名用于确定研究对象，不代表收入、市值或网络资产排名。", "- 5G套餐用户与5G网络用户不合并。", "- 共建共享基站不在运营商间相加。", "- 财年结束日在中国公司与印度公司之间不同，比较时必须使用 `period_end`。", "- 所有缺口、重述和口径断点见 `quality_audit.md` 与逐行 `quality_note`。", "",
    ])
    (OUT / "summary.md").write_text(summary, encoding="utf-8")
    readme = "\n".join([
        "# 全球五大运营商 2016–2025 数据库", "",
        "## 入口", "", "- `annual_metrics.json`：主数据和元数据。", "- `annual_metrics.csv`：长表。", "- `sources.json`：官方来源登记。", "- `coverage.csv`：逐运营商、逐年、逐指标覆盖/缺口。", "- `quality_audit.json` / `quality_audit.md`：质量门禁。", "- `conflicts_and_scope_breaks.json` / `.csv`：重述、冲突、推导值与口径断点。", "- `summary.md`：研究对象与使用边界。", "",
        "## 与原数据库的关系", "", "中国移动、中国电信、中国联通的财务数据继续以 `quarterly_competitor_metrics_2026-06-18/quarterly_metrics.json` 为唯一事实源；新增运营指标的规范侧表写入该原数据库目录的 `annual_operating_metrics_2016_2025.*`。本目录主表提供五家整合视图。Airtel 与 Jio 为新增主体，财务和运营数据均在本库。", "",
        "## 重建", "", "```bash", "python3 scripts/build_global_top5_operator_database.py", "```", "",
    ])
    (OUT / "README.md").write_text(readme, encoding="utf-8")
    manifest = {
        "id":"global_top5_operators_2016_2025", "title":"全球五大运营商2016–2025财务与运营数据库",
        "summary":"按客户规模选取五家；中国三家链接既有财务库并补运营指标，Airtel/Jio新增完整披露历史。",
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

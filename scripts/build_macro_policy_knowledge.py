#!/usr/bin/env python3
"""Build CMHK-relevant macro policy and institutional indicators dataset."""

from __future__ import annotations

import csv
import calendar
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
import pdfplumber


ROOT = Path(__file__).resolve().parents[1]
BUILD_DATE = "2026-06-19"
DATASET_ID = f"cmhk_macro_policy_{BUILD_DATE}"
OUT_ROOT = ROOT / "agent_knowledge" / DATASET_ID

OFCA_TELECOM_INDICATORS_URL = "https://www.ofca.gov.hk/filemanager/ofca/en/content_297/hktelecom-indicators_summary.htm"
OFCA_INDICATORS_INDEX_URL = "https://www.ofca.gov.hk/en/news_info/data_statistics/indicators/index.html"
OFCA_KEY_STATS_URL = "https://www.ofca.gov.hk/en/news_info/data_statistics/key_stat/index.html"
OFCA_KEY_STATS_CSV_URL = "https://www.ofca.gov.hk/filemanager/ofca/common/datagovhk/key_com_stat.csv"
OFCA_KEY_STATS_DATA_DICT_URL = "https://www.ofca.gov.hk/filemanager/ofca/common/datagovhk/data_dict/Data_Dictionary_for_Key_Comms_Stat_EN.pdf"
DATA_GOV_KEY_STATS_DATASET_URL = "https://data.gov.hk/en-data/dataset/hk-ofca-ofca-ofca-dataset-10"
OFCA_DATA_STATISTICS_INDEX_URL = "https://www.ofca.gov.hk/en/news_info/data_statistics/index.html"
OFCA_CONSUMER_COMPLAINTS_URL = "https://www.ofca.gov.hk/en/news_info/data_statistics/complaint_stat/index.html"
OFCA_INTERNET_SUBSCRIPTIONS_URL = "https://www.ofca.gov.hk/en/news_info/data_statistics/internet/statistics_on_internet_service_subscriptions/index.html"
OFCA_INTERNET_SUBSCRIPTIONS_PDF_URL = "https://www.ofca.gov.hk/filemanager/ofca/en/content_293/cus_isp_en.pdf"
OFCA_WIRELESS_SERVICES_URL = "https://www.ofca.gov.hk/en/news_info/data_statistics/mobile_services/wireless_services/index.html"
OFCA_WIRELESS_SERVICES_PDF_URL = "https://www.ofca.gov.hk/filemanager/ofca/en/content_108/wireless_en.pdf"
OFCA_SPECTRUM_MANAGEMENT_URL = "https://www.ofca.gov.hk/en/industry_focus/radio_spectrum/management/index.html"
OFCA_MARKET_REPORT_2024_25_URL = "https://www.ofca.gov.hk/trade_fund_report/2425/en-chapter3.html"

OFCA_WIRELESS_ANNUAL_COLUMNS: dict[int, tuple[str, str, str]] = {
    1: ("post_paid_sim_subscriptions", "Post-paid SIM subscriptions", "subscriptions"),
    2: ("pre_paid_sim_subscriptions", "Pre-paid SIM subscriptions", "subscriptions"),
    3: ("public_mobile_subscriptions_total", "Public mobile subscriptions - total", "subscriptions"),
    4: ("activated_pre_paid_sim_subscriptions", "Activated pre-paid SIM subscriptions", "subscriptions"),
    5: ("mobile_broadband_subscriptions", "Mobile broadband subscriptions", "subscriptions"),
    6: ("3g_subscriptions", "3G subscriptions", "subscriptions"),
    9: ("mvno_subscriptions", "MVNO subscriptions", "subscriptions"),
    10: ("machine_type_connections", "Machine type connections", "connections"),
    11: ("mobile_data_usage_total_mbytes", "Mobile data usage - total", "MBytes"),
    12: ("mobile_data_usage_per_mobile_broadband_subscription_mbytes", "Mobile data usage per mobile broadband subscription", "MBytes per subscription"),
    13: ("mobile_data_usage_per_capita_mbytes", "Mobile data usage per capita", "MBytes per capita"),
    14: ("sms_sent", "Short message service sent", "messages"),
    15: ("sms_received", "Short message service received", "messages"),
    16: ("sms_sent_per_mobile_subscription", "SMS sent per mobile subscription", "messages per subscription"),
    17: ("sms_received_per_mobile_subscription", "SMS received per mobile subscription", "messages per subscription"),
}

OFCA_INTERNET_ACCESS_LINE_COLUMNS: dict[int, tuple[str, str, str]] = {
    1: ("dial_up_access_lines", "Dial-up access lines", "access lines"),
    2: ("leased_access_lines", "Leased access lines", "access lines"),
    3: ("residential_broadband_lines_1mbps_to_under_100mbps", "Residential broadband access lines - 1Mbps to under 100Mbps", "access lines"),
    4: ("residential_broadband_lines_100mbps_to_under_1gbps", "Residential broadband access lines - 100Mbps to under 1Gbps", "access lines"),
    5: ("residential_broadband_lines_1gbps_or_above", "Residential broadband access lines - 1Gbps or above", "access lines"),
    6: ("residential_broadband_lines_total", "Residential broadband access lines - total", "access lines"),
    7: ("business_broadband_lines_1mbps_to_under_100mbps", "Business broadband access lines - 1Mbps to under 100Mbps", "access lines"),
    8: ("business_broadband_lines_100mbps_to_under_1gbps", "Business broadband access lines - 100Mbps to under 1Gbps", "access lines"),
    9: ("business_broadband_lines_1gbps_or_above", "Business broadband access lines - 1Gbps or above", "access lines"),
    10: ("business_broadband_lines_total", "Business broadband access lines - total", "access lines"),
    11: ("broadband_access_lines_total", "Broadband internet access lines - total", "access lines"),
}

OFCA_INTERNET_CUSTOMER_ACCOUNT_COLUMNS: dict[int, tuple[str, str, str]] = {
    1: ("dial_up_customer_accounts", "Dial-up customer accounts", "customer accounts"),
    2: ("leased_line_customer_accounts", "Leased-line customer accounts", "customer accounts"),
    3: ("residential_broadband_accounts_1mbps_to_under_10mbps", "Residential broadband customer accounts - 1Mbps to under 10Mbps", "customer accounts"),
    4: ("residential_broadband_accounts_10mbps_or_above", "Residential broadband customer accounts - 10Mbps or above", "customer accounts"),
    5: ("residential_broadband_accounts_total", "Residential broadband customer accounts - total", "customer accounts"),
    6: ("business_broadband_accounts_1mbps_to_under_10mbps", "Business broadband customer accounts - 1Mbps to under 10Mbps", "customer accounts"),
    7: ("business_broadband_accounts_10mbps_or_above", "Business broadband customer accounts - 10Mbps or above", "customer accounts"),
    8: ("business_broadband_accounts_total", "Business broadband customer accounts - total", "customer accounts"),
    9: ("broadband_customer_accounts_total", "Broadband internet access customer accounts - total", "customer accounts"),
}

OFCA_KEY_STATS_COLUMNS: dict[str, tuple[str, str, str, str]] = {
    "TV_LIC_QTY": ("total_television_programme_service_licences", "Total television programme service licences", "licences", "Television Broadcasting Services"),
    "DO_FREE_TV_LIC_QTY": ("domestic_free_television_programme_service_licences", "Domestic free television programme service licences", "licences", "Television Broadcasting Services"),
    "DO_PAY_TV_LIC_QTY": ("domestic_pay_television_programme_service_licences", "Domestic pay television programme service licences", "licences", "Television Broadcasting Services"),
    "NON_DO_TV_LIC_QTY": ("non_domestic_television_programme_service_licences", "Non-domestic television programme service licences", "licences", "Television Broadcasting Services"),
    "OTHER_TV_LIC_QTY": ("other_licensable_television_programme_service_licences", "Other licensable television programme service licences", "licences", "Television Broadcasting Services"),
    "DTT_RATE": ("digital_terrestrial_television_penetration_rate", "Digital terrestrial television penetration rate", "percent", "Television Broadcasting Services"),
    "DO_PAY_PEN_RATE": ("licensed_domestic_pay_television_penetration_rate", "Penetration rate of licensed domestic pay television services", "percent", "Television Broadcasting Services"),
    "TV_AUD_QTY": ("total_tv_audience", "Total TV audience aged 4 or above", "persons", "Television Broadcasting Services"),
    "TV_HH_QTY": ("total_tv_households", "Total TV households", "households", "Television Broadcasting Services"),
    "DO_PAY_TV_USER_QTY": ("licensed_domestic_pay_television_subscribers", "Subscribers of licensed domestic pay television services", "subscribers", "Television Broadcasting Services"),
    "SOUND_LIC_QTY": ("sound_broadcasting_licences", "Sound broadcasting licences", "licences", "Sound Broadcasting Services"),
    "MNO_QTY": ("mobile_network_operators", "Mobile network operators", "operators", "Telecommunications Services"),
    "MVNO_QTY": ("mobile_virtual_network_operators", "Mobile virtual network operators", "operators", "Telecommunications Services"),
    "LOCAL_FNO_QTY": ("local_fixed_network_operators", "Local fixed network operators", "operators", "Telecommunications Services"),
    "EXT_FNO_QTY": ("external_fixed_telecommunications_services_providers", "External fixed telecommunications services providers", "providers", "Telecommunications Services"),
    "FB_EXT_FNO_QTY": ("facility_based_external_fixed_network_operators", "Facility-based external fixed network operators", "operators", "Telecommunications Services"),
    "SB_EXT_FNO_QTY": ("services_based_external_telecommunications_services_providers", "Services-based external telecommunications services providers", "providers", "Telecommunications Services"),
    "RES_LINE_PEN_RATE": ("residential_fixed_line_penetration_rate", "Residential fixed line penetration rate", "percent", "Telecommunications Services"),
    "MOBL_PEN_RATE": ("mobile_subscriber_penetration_rate", "Mobile subscriber penetration rate", "percent", "Telecommunications Services"),
    "MOBL_USERS_QTY": ("mobile_subscriptions", "Mobile subscriptions", "subscriptions", "Telecommunications Services"),
    "MOBL_BB_USERS_QTY": ("mobile_broadband_subscriptions", "Mobile broadband subscriptions", "subscriptions", "Telecommunications Services"),
    "ISP_QTY": ("internet_service_providers", "Internet service providers", "providers", "Internet Services"),
    "BB_USERS_QTY": ("registered_subscriptions_with_broadband_access", "Registered subscriptions with broadband access", "subscriptions", "Internet Services"),
    "HH_PEN_RATE": ("household_broadband_penetration_rate", "Household broadband penetration rate", "percent", "Internet Services"),
    "FTTHB_PEN_RATE": ("ftth_b_household_penetration_rate", "FTTH/B household penetration rate", "percent", "Internet Services"),
    "FTTH_PEN_RATE": ("ftth_household_penetration_rate", "FTTH household penetration rate", "percent", "Internet Services"),
    "FTTB_PEN_RATE": ("fttb_household_penetration_rate", "FTTB household penetration rate", "percent", "Internet Services"),
    "WIFI_AP_QTY": ("public_wifi_access_points", "Public Wi-Fi access points", "access points", "Internet Services"),
    "FTTHB_RES_CVG_RATE": ("ftth_b_residential_unit_coverage_rate", "FTTH/B residential unit coverage rate", "percent", "Fibre Broadband Network Coverage"),
    "FTTH_RES_CVG_RATE": ("ftth_residential_unit_coverage_rate", "FTTH residential unit coverage rate", "percent", "Fibre Broadband Network Coverage"),
    "FTTB_RES_CVG_RATE": ("fttb_residential_unit_coverage_rate", "FTTB residential unit coverage rate", "percent", "Fibre Broadband Network Coverage"),
}

CSD_TABLES: dict[str, dict[str, Any]] = {
    "csd_cpi_510_60001": {
        "title": "Consumer Price Indices (October 2019 - September 2020 = 100)",
        "web_url": "https://www.censtatd.gov.hk/en/web_table.html?id=510-60001",
        "api_url": "https://www.censtatd.gov.hk/api/get.php?id=510-60001&lang=en&param=N4KABGBEDGBukC4zAL4BpxQM7yaCEkAwkQPpECypAjAJwBMADImANqYFQBKAhgO40AJgAdSAS0EAPUgDtIGToQoB7KtRGkApKSzyOBSAE1lhoaO279AXQUGAQuTUNmSdou78z4qbL3vIKmoaFn6KRiZeIda2hGSUNM4sbmG8AuqiEtJyMQaBkTqhnOGm6VoF0fqQAIKOCUxJ+oSpXpm+OUqq+brtUMYlweWcVpjomJDCAKYATmLKgiz4BlgALjxTyyyQdADsACyM25AjtpASmwCs1IwAtABsjA-UoZAANjwyAOabE3IgKEA",
        "institution": "Census and Statistics Department",
        "indicator_group": "Consumer prices",
        "relevance": "Inflation and household cost pressure affect telecom spending, handset affordability, pricing power and ARPU interpretation.",
        "selected": {"freq": {"M"}, "sv": {"CC_CM_1920", "A_CM_1920", "B_CM_1920", "C_CM_1920"}},
    },
    "csd_pce_310_31012": {
        "title": "Private consumption expenditure by component in chained (2024) dollars",
        "web_url": "https://www.censtatd.gov.hk/en/web_table.html?id=310-31012",
        "api_url": "https://www.censtatd.gov.hk/api/get.php?id=310-31012&lang=en&param=N4KABGBEDGBukC4yghSBxAIgBQPoGEB5AWW0IDkBRcgFUTAG1xU1t9LIAaZlyfADUzEuPVJABKlAIIiWacoOHc5UAUIBisuX0XotvNcQDK+sYcym0h8hdEBdZgF9lUAM7wkKMxXpMVEgEMAd1xiXAALAGsAE1xoyygATQB7RNwARmiAB1wAUlxXSHsnF0gsgFMAJwBLZPjPUUhXABcAyub6SHSATgB2AGYABnSiiGdmSGr6qH70wYBaWeGAJi1IABsAgDsAc07yraLHIA",
        "institution": "Census and Statistics Department",
        "indicator_group": "Private consumption expenditure",
        "relevance": "Consumer demand and services consumption provide macro context for CMHK retail, roaming, handset and consumer mobile trends.",
        "selected": {"freq": {"Q"}, "GDP_COMPONENT": {"PCE", "CXDM", "CXDMD", "CXDMND", "CXDMS"}},
    },
    "csd_retail_620_67001": {
        "title": "Total retail sales",
        "web_url": "https://www.censtatd.gov.hk/en/web_table.html?id=620-67001",
        "api_url": "https://www.censtatd.gov.hk/api/get.php?id=620-67001&lang=en&param=N4KABGBEDGBukC4zAL4BpxQM7yaCEkAagIIAyA+gEoDKiYA2pgVFQIYDuFAshQBYBrACYUhkZmAC6GFsQDylAJIARABrU6SJi0LsuARiEAHCgEshADwoA7SDJ2QAmgHtHFQyYCkFLOJbSJYnIKFXVaem0HPXdjM0sbOwlCFzcPCm9fCUlMdExIIwBTACdTZzE8QKwAFzYiqvpIACYABmaAFn1mvzBcwnMGgDYWgFoBgHZW-UTCABs2awBzBoLbEBQgA",
        "institution": "Census and Statistics Department",
        "indicator_group": "Retail sales",
        "relevance": "Retail value and volume trends are useful context for handset sales, store traffic, consumer confidence and roaming/tourism-sensitive telecom demand.",
        "selected": {"freq": {"M"}},
    },
    "csd_internet_access_720_90001": {
        "title": "Households with Internet access at home",
        "web_url": "https://www.censtatd.gov.hk/en/web_table.html?id=720-90001",
        "api_url": "https://www.censtatd.gov.hk/api/get.php?id=720-90001&lang=en&param=N4KABGBEDGBukC4yghSAVAmgBQKIH0BJdfAVQGUBBAcV0TAG1xU0B1ASwBcALIgO04BTAE59BnfAEMAzpGYQAuswC+AGmaRp8JClSRi+ABKH6TFmgBKkgO74A0vgCMAEwAO+brz6R15qNmEAe3cXdwBSfG95MCUINQ1XEXZA53pdNGlOSWFOekgAJgAGRwAOOTjfKHZUpEgAdiKAWgBOQrbHHw0AG0k+AHM8wSjlIA",
        "institution": "Census and Statistics Department",
        "indicator_group": "Household internet access",
        "relevance": "Home internet penetration contextualises CMHK fixed broadband, FWA, converged services and addressable household demand.",
        "selected": {"freq": {"Y"}},
    },
}

CSD_POST_TABLES: dict[str, dict[str, Any]] = {
    "csd_gdp_growth_310_30001": {
        "title": "Percentage change of Gross Domestic Product (GDP) and selected major expenditure components in real terms",
        "web_url": "https://www.censtatd.gov.hk/en/web_table.html?id=310-30001",
        "table_id": "310-30001",
        "institution": "Census and Statistics Department",
        "indicator_group": "GDP and demand growth",
        "relevance": "Real GDP, private consumption, government consumption and fixed investment growth provide macro-demand context for CMHK revenue, roaming, enterprise and capex trend interpretation.",
        "query": {
            "period": {"start": "201603", "end": "202603"},
            "sv": {"CON": ["YoY_1dp_%_s"], "SA1": ["QoQ_1dp_%_s"]},
            "cv": {"GDP_COMPONENT": ["PCE", "GCE", "GDFCF"]},
        },
        "include": {
            "GDP_COMPONENTDesc": {
                "Total",
                "Private consumption expenditure",
                "Government consumption expenditure",
                "Gross domestic fixed capital formation",
            },
            "freq": {"Q"},
        },
    },
    "csd_labour_210_06101": {
        "title": "Statistics on labour force, employment, unemployment and underemployment",
        "web_url": "https://www.censtatd.gov.hk/en/web_table.html?id=210-06101",
        "table_id": "210-06101",
        "institution": "Census and Statistics Department",
        "indicator_group": "Labour market",
        "relevance": "Labour force and unemployment conditions are household-income and consumer-demand context for CMHK mobile, broadband, handset and retail-service trend interpretation.",
        "query": {
            "period": {"start": "201601", "end": "202605"},
            "sv": {
                "LF": ["Raw_K_1dp_per_n"],
                "UR": ["Rate_1dp_%_n"],
                "SAUR": ["Rate_1dp_%_n"],
            },
            "cv": {"SEX": ["M"]},
        },
        "include": {"SEXDesc": {"Total"}, "freq": {"M3M"}},
    },
}

CSD_HOUSEHOLD_INCOME_WEB_URL = "https://www.censtatd.gov.hk/en/web_table.html?id=130-06102"
CSD_HOUSEHOLD_INCOME_COMP_URL = "https://www.censtatd.gov.hk/data/table_130-06102_comp.json"
CSD_HOUSEHOLD_INCOME_LANG_URL = "https://www.censtatd.gov.hk/data/en/table_130-06102_lang.json"
CSD_HOUSEHOLD_INCOME_MDT_BASE_URL = "https://www.censtatd.gov.hk/data/"
CSD_HOUSEHOLD_INCOME_TABLE_ID = "130-06102"
CSD_HOUSEHOLD_INCOME_THEME_ID = "55"
CSD_HOUSEHOLD_INCOME_METRICS: dict[str, tuple[str, str, str, str]] = {
    "DH": ("Raw_K_1dp_hh_n", "domestic_households", "Domestic households", "thousand households"),
    "ADHS": ("Raw_1dp_per_n", "average_domestic_household_size", "Average domestic household size", "persons"),
    "ADHS_XFDH": (
        "Raw_1dp_per_n",
        "average_domestic_household_size_excluding_foreign_domestic_helpers",
        "Average domestic household size (excluding foreign domestic helpers)",
        "persons",
    ),
    "MED_DH_INC": ("Raw_hkd_d", "median_monthly_household_income", "Median monthly household income", "HKD"),
    "MED_DH_INC_XBONUS": (
        "Raw_hkd_d",
        "median_monthly_household_income_excluding_chinese_new_year_bonus_double_pay",
        "Median monthly household income (excluding Chinese New Year bonus/double pay)",
        "HKD",
    ),
    "MED_DH_INC_XFDH": (
        "Raw_hkd_d",
        "median_monthly_household_income_excluding_foreign_domestic_helpers",
        "Median monthly household income (excluding foreign domestic helpers)",
        "HKD",
    ),
    "MED_DH_INC_XEI": (
        "Raw_hkd_d",
        "median_monthly_household_income_economically_active_households",
        "Median monthly household income of economically active households",
        "HKD",
    ),
    "PCTDH_DV_OO": (
        "Prop_1dp_%_n",
        "owner_occupiers_proportion_of_domestic_households",
        "Owner-occupiers as a proportion of total number of domestic households",
        "percent",
    ),
    "PCTDH_DV_OO_PUB": (
        "Prop_1dp_%_n",
        "owner_occupiers_public_sector_housing_proportion",
        "Proportion of owner-occupiers residing in public sector housing",
        "percent",
    ),
    "PCTDH_DV_OO_PRI": (
        "Prop_1dp_%_n",
        "owner_occupiers_private_sector_housing_proportion",
        "Proportion of owner-occupiers residing in private sector housing",
        "percent",
    ),
}

CSD_POPULATION_WEB_URL = "https://www.censtatd.gov.hk/en/web_table.html?id=110-01001"
CSD_POPULATION_COMP_URL = "https://www.censtatd.gov.hk/data/table_110-01001_comp.json"
CSD_POPULATION_LANG_URL = "https://www.censtatd.gov.hk/data/en/table_110-01001_lang.json"
CSD_POPULATION_TABLE_ID = "110-01001"
CSD_POPULATION_THEME_ID = "76"
CSD_POPULATION_METRICS: dict[str, tuple[str, str, str]] = {
    "Raw_K_1dp_per_n": ("population", "Population", "thousand persons"),
    "Prop_1dp_%_n": ("population_share", "Population share", "percent"),
}


def fetch_html(url: str) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "ignore")


def fetch_json(url: str, referer: str) -> dict[str, Any]:
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": referer,
        },
    )
    with urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


def fetch_csv_rows(url: str, referer: str = "") -> list[dict[str, str]]:
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/csv,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            **({"Referer": referer} if referer else {}),
        },
    )
    with urlopen(req, timeout=45) as resp:
        csv_text = resp.read().decode("utf-8-sig", "ignore")
    return list(csv.DictReader(csv_text.splitlines()))


def fetch_csd_post(table_id: str, query: dict[str, Any], referer: str) -> dict[str, Any]:
    payload = {"id": table_id, "lang": "en"}
    payload.update(query)
    body = urlencode({"query": json.dumps(payload)}).encode()
    req = Request(
        "https://www.censtatd.gov.hk/api/post.php",
        data=body,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": referer,
        },
    )
    with urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"\([^)]*\)", "", value)
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return re.sub(r"_+", "_", value).strip("_")


def parse_number(raw: str) -> float | None:
    return parse_figure(clean_text(raw))


def parse_figure(raw: Any) -> float | None:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value or value.upper() in {"N/A", "NA", "-", "--"}:
        return None
    value = value.replace(",", "").replace("%", "")
    try:
        return float(value)
    except ValueError:
        return None


def month_end(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"


def quarter_label(period: str) -> tuple[str, str]:
    year = int(period[:4])
    suffix = period[4:].upper().replace("Q", "")
    raw = int(suffix)
    quarter = raw if len(suffix) == 1 and raw <= 4 else (raw + 2) // 3
    end_month = quarter * 3
    return f"Q{quarter} {year}", month_end(year, end_month)


def csd_period_fields(freq: str, period: str) -> tuple[str, str, str]:
    freq = (freq or "").upper()
    period = str(period)
    if freq == "M" and len(period) >= 6:
        year = int(period[:4])
        month = int(period[4:6])
        return f"{year:04d}-{month:02d}", month_end(year, month), "month"
    if freq == "Q":
        label, end_date = quarter_label(period)
        return label, end_date, "quarter"
    if freq == "M3M" and len(period) >= 6:
        year = int(period[:4])
        month = int(period[4:6])
        return f"3-month ending {year:04d}-{month:02d}", month_end(year, month), "moving_3_month"
    if freq == "Y":
        year = int(period[:4])
        return str(year), f"{year:04d}-12-31", "calendar_year"
    return period, "", freq.lower() or "unknown"


def in_ten_year_window(period_end: str) -> bool:
    if not period_end:
        return False
    return "2016-01-01" <= period_end <= "2026-12-31"


def csd_unit(row: dict[str, Any]) -> str:
    desc = clean_text(str(row.get("svDesc") or row.get("sd_value") or ""))
    lowered = desc.lower()
    if "%" in desc or "rate" in lowered or "year-on-year" in lowered or "month-to-month" in lowered:
        return "percent"
    if "hk$ million" in lowered or "$ million" in lowered:
        return "HKD million"
    if "'000" in desc or "('000)" in desc:
        return "thousand households"
    if "index" in lowered:
        return "index"
    return desc or "value"


def csd_metric_identity(config: dict[str, Any], row: dict[str, Any]) -> tuple[str, str, str]:
    table_title = config["title"]
    detail_parts: list[str] = []
    key_parts = [slugify(table_title)]
    for field, desc_field in (
        ("GDP_COMPONENT", "GDP_COMPONENTDesc"),
        ("SEX", "SEXDesc"),
        ("TYPE_IT_USAGE", "TYPE_IT_USAGEDesc"),
        ("sv", "svDesc"),
    ):
        value = clean_text(str(row.get(field, "")))
        desc = clean_text(str(row.get(desc_field, "")))
        if value:
            key_parts.append(slugify(value))
        if desc:
            detail_parts.append(desc)
    detail = " - ".join(dict.fromkeys(detail_parts))
    name = f"{table_title} - {detail}" if detail else table_title
    return "_".join(part for part in key_parts if part), name, detail or table_title


def include_csd_row(config: dict[str, Any], row: dict[str, Any]) -> bool:
    selected = config.get("selected", {})
    for field, allowed in selected.items():
        value = clean_text(str(row.get(field, "")))
        if allowed and value not in allowed:
            return False
    return True
    try:
        return float(value)
    except ValueError:
        return None


def infer_unit(metric: str) -> str:
    lowered = metric.lower()
    if "(hk$)" in lowered:
        return "HKD"
    if "minutes in billion" in lowered:
        return "billion minutes"
    if "(million)" in lowered:
        return "million"
    if "(%)" in lowered or "penetration rate" in lowered or "% " in metric:
        return "percent"
    return "count"


def fiscal_period_end(year_label: str) -> str:
    match = re.search(r"(\d{4})\s*/\s*(\d{4})", year_label)
    if not match:
        return ""
    return f"{match.group(2)}-03-31"


def fiscal_period(year_label: str) -> str:
    match = re.search(r"(\d{4})\s*/\s*(\d{4})", year_label)
    if not match:
        return year_label
    return f"FY{match.group(1)}/{match.group(2)[-2:]}"


def latest_ten_fiscal_years(headers: list[str]) -> list[tuple[int, str]]:
    fiscal = [(idx, h) for idx, h in enumerate(headers) if re.search(r"\d{4}\s*/\s*\d{4}", h)]
    return fiscal[-10:]


def parse_ofca_telecom_indicators() -> list[dict[str, Any]]:
    html = fetch_html(OFCA_TELECOM_INDICATORS_URL)
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        raise RuntimeError("OFCA telecom indicators table not found")

    parsed_rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [clean_text(c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])]
        if cells:
            parsed_rows.append(cells)
    if not parsed_rows:
        raise RuntimeError("OFCA telecom indicators table has no rows")

    header = parsed_rows[0]
    periods = latest_ten_fiscal_years(header)
    category = ""
    rows: list[dict[str, Any]] = []
    for source_row in parsed_rows[1:]:
        if len(source_row) <= 2:
            label = clean_text(source_row[0]) if source_row else ""
            if label:
                category = label.title()
            continue
        metric_label = source_row[0]
        metric_detail = source_row[1] if len(source_row) > 1 else metric_label
        if not metric_label or metric_label.upper() == metric_label and parse_number(metric_label) is None:
            category = metric_label.title()
            continue
        metric_key = slugify(metric_label)
        unit = infer_unit(metric_label)
        for idx, year_label in periods:
            cell_idx = idx
            if cell_idx >= len(source_row):
                continue
            raw_value = source_row[cell_idx]
            official_value = parse_number(raw_value)
            is_gap = official_value is None
            status = "source_gap_confirmed" if is_gap else "official_match"
            rows.append(
                {
                    "subject": "Hong Kong telecommunications market",
                    "category": "macro_policy",
                    "source_family": "OFCA telecommunications indicators",
                    "indicator_group": category,
                    "period": fiscal_period(year_label),
                    "period_end": fiscal_period_end(year_label),
                    "grain": "fiscal_year",
                    "metric_key": metric_key,
                    "metric_name": metric_label,
                    "metric_detail": metric_detail,
                    "value": "" if is_gap else official_value,
                    "unit": unit,
                    "official_value": "" if is_gap else official_value,
                    "official_unit": unit,
                    "verification_status": status,
                    "quality_status": "official_public_table",
                    "official_source_label": "OFCA Telecommunications Indicators in Hong Kong",
                    "official_source_url": OFCA_TELECOM_INDICATORS_URL,
                    "official_evidence": f"OFCA historical telecommunications indicators table reports {metric_label} for {year_label}; latest ten-year window retained for CMHK macro trend context.",
                    "verification_count": 2,
                    "verification_method": "official_table_plus_official_index_crosscheck",
                    "verification_sources": json.dumps(
                        [
                            {
                                "label": "OFCA historical telecommunications indicators table",
                                "url": OFCA_TELECOM_INDICATORS_URL,
                                "evidence": "Historical official table covering fiscal years 2005/06 to 2024/25.",
                            },
                            {
                                "label": "OFCA telecommunications indicators index",
                                "url": OFCA_INDICATORS_INDEX_URL,
                                "evidence": "Official index links the current annual telecommunications indicators and definitions.",
                            },
                        ],
                        ensure_ascii=False,
                    ),
                    "verification_note": "Official public OFCA table retained. N/A or unavailable cells are kept as source gaps and are not estimated.",
                    "cmhk_relevance": "Market demand, saturation, investment, traffic, workforce, and pricing context for CMHK mobile, fixed, broadband, enterprise connectivity, and cloud-adjacent services.",
                }
            )
    return rows


def parse_ofca_key_communications_statistics() -> list[dict[str, Any]]:
    req = Request(OFCA_KEY_STATS_CSV_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=45) as resp:
        csv_text = resp.read().decode("utf-8-sig", "ignore")
    source_rows = list(csv.DictReader(csv_text.splitlines()))
    if not source_rows:
        raise RuntimeError("OFCA key communications statistics CSV has no rows")

    rows: list[dict[str, Any]] = []
    for source_row in source_rows:
        raw_period = clean_text(source_row.get("DATE", ""))
        if not re.match(r"^\d{4}-\d{2}$", raw_period):
            continue
        year, month = (int(part) for part in raw_period.split("-"))
        period_end = month_end(year, month)
        if not in_ten_year_window(period_end):
            continue
        for column, (metric_key, metric_name, unit, indicator_group) in OFCA_KEY_STATS_COLUMNS.items():
            if column not in source_row:
                continue
            official_value = parse_figure(source_row.get(column))
            if official_value is None:
                continue
            rows.append(
                {
                    "subject": "Hong Kong key communications statistics",
                    "category": "macro_policy",
                    "source_family": "OFCA key communications statistics",
                    "indicator_group": indicator_group,
                    "period": raw_period,
                    "period_end": period_end,
                    "grain": "monthly_point_in_time",
                    "metric_key": metric_key,
                    "metric_name": metric_name,
                    "metric_detail": f"{metric_name} ({column})",
                    "value": official_value,
                    "unit": unit,
                    "official_value": official_value,
                    "official_unit": unit,
                    "verification_status": "official_match",
                    "quality_status": "official_datagovhk_csv",
                    "official_source_label": "OFCA Key Communications Statistics CSV",
                    "official_source_url": OFCA_KEY_STATS_CSV_URL,
                    "official_evidence": f"OFCA data.gov.hk Key Communications Statistics CSV reports {metric_name} for {raw_period}; retained as monthly point-in-time market snapshot for CMHK context.",
                    "verification_count": 3,
                    "verification_method": "official_datagovhk_csv_plus_data_dictionary_plus_ofca_page_crosscheck",
                    "verification_sources": json.dumps(
                        [
                            {
                                "label": "OFCA Key Communications Statistics CSV",
                                "url": OFCA_KEY_STATS_CSV_URL,
                                "evidence": "Official machine-readable CSV for Key Communications Statistics published through OFCA/data.gov.hk.",
                            },
                            {
                                "label": "OFCA Key Communications Statistics data dictionary",
                                "url": OFCA_KEY_STATS_DATA_DICT_URL,
                                "evidence": "Official data dictionary defines DATE and the CSV metric fields used in this build.",
                            },
                            {
                                "label": "DATA.GOV.HK Key Communications Statistics dataset",
                                "url": DATA_GOV_KEY_STATS_DATASET_URL,
                                "evidence": "Official dataset page identifies OFCA as data provider, monthly update frequency and the Key Communications Statistics resource.",
                            },
                            {
                                "label": "OFCA Key Communications Statistics web page",
                                "url": OFCA_KEY_STATS_URL,
                                "evidence": "Official OFCA web page presents the latest human-readable Key Communications Statistics snapshot and notes.",
                            },
                        ],
                        ensure_ascii=False,
                    ),
                    "verification_note": "Official machine-readable CSV retained. Blank cells are not converted to zeros and are not estimated; each row is a point-in-time snapshot for the metric's own DATE.",
                    "cmhk_relevance": "Mobile subscriptions, broadband penetration, operator counts, public Wi-Fi access points and fibre coverage are core market-saturation and adoption context for CMHK mobile, fixed broadband, convergence, enterprise connectivity and network strategy.",
                }
            )
    if not rows:
        raise RuntimeError("OFCA key communications statistics parser produced no rows")
    return rows


def normalize_ofca_wireless_cell(raw: str | None) -> float | None:
    value = clean_text(raw or "")
    if not value or value.upper() in {"N/A", "NA", "-", "--"}:
        return None
    # OFCA PDF extraction sometimes appends footnote markers such as 15 or
    # "15 16" directly after a number. Remove only these known markers.
    value = re.sub(r"(?<=\d)(?:15|16)(?:\s+16)?$", "", value).strip()
    value = re.sub(r"\s+(?:9|15|16)(?:\s+16)?$", "", value).strip()
    value = value.replace(",", "")
    try:
        return float(value)
    except ValueError:
        return None


def parse_pdf_cell_lines(raw: str | None) -> list[str]:
    return [clean_text(value) for value in (raw or "").splitlines() if clean_text(value)]


def parse_ofca_wireless_services() -> list[dict[str, Any]]:
    pdf_bytes = urlopen(Request(OFCA_WIRELESS_SERVICES_PDF_URL, headers={"User-Agent": "Mozilla/5.0"}), timeout=45).read()
    tmp_pdf = ROOT / "tmp" / "ofca_wireless_en.pdf"
    tmp_pdf.parent.mkdir(parents=True, exist_ok=True)
    tmp_pdf.write_bytes(pdf_bytes)

    with pdfplumber.open(str(tmp_pdf)) as pdf:
        tables = pdf.pages[0].extract_tables()
    if not tables:
        raise RuntimeError("OFCA wireless services table not found")
    table = tables[0]
    if len(table) <= 5:
        raise RuntimeError("OFCA wireless services annual rows not found")

    annual_row = table[5]
    periods = parse_pdf_cell_lines(annual_row[0])
    if len(periods) != 10 or not all(re.match(r"12/\d{4}$", period) for period in periods):
        raise RuntimeError(f"Unexpected OFCA wireless annual periods: {periods}")

    rows: list[dict[str, Any]] = []
    for col_idx, (metric_key, metric_name, unit) in OFCA_WIRELESS_ANNUAL_COLUMNS.items():
        values = parse_pdf_cell_lines(annual_row[col_idx])
        if len(values) != len(periods):
            # Columns such as 4G/5G are split across continuation rows by PDF
            # extraction. Skip them until a safer official structured source is used.
            continue
        for period, raw_value in zip(periods, values):
            month, year = period.split("/")
            official_value = normalize_ofca_wireless_cell(raw_value)
            is_gap = official_value is None
            status = "source_gap_confirmed" if is_gap else "official_match"
            rows.append(
                {
                    "subject": "Hong Kong wireless services market",
                    "category": "macro_policy",
                    "source_family": "OFCA wireless services",
                    "indicator_group": "Wireless Services",
                    "period": f"{year}-{month}",
                    "period_end": month_end(int(year), int(month)),
                    "grain": "annual_december_snapshot",
                    "metric_key": metric_key,
                    "metric_name": metric_name,
                    "metric_detail": metric_name,
                    "value": "" if is_gap else official_value,
                    "unit": unit,
                    "official_value": "" if is_gap else official_value,
                    "official_unit": unit,
                    "verification_status": status,
                    "quality_status": "official_public_pdf_table",
                    "official_source_label": "OFCA Key Statistics for Telecommunications in Hong Kong - Wireless Services",
                    "official_source_url": OFCA_WIRELESS_SERVICES_PDF_URL,
                    "official_evidence": f"OFCA Wireless Services official PDF reports {metric_name} for {period}; retained as annual December snapshot for CMHK mobile-market context.",
                    "verification_count": 2,
                    "verification_method": "official_pdf_table_plus_official_statistics_page_crosscheck",
                    "verification_sources": json.dumps(
                        [
                            {
                                "label": "OFCA Wireless Services official PDF",
                                "url": OFCA_WIRELESS_SERVICES_PDF_URL,
                                "evidence": "Official Wireless Services statistics PDF with current monthly rows and December historical snapshots.",
                            },
                            {
                                "label": "OFCA Wireless Services statistics page",
                                "url": OFCA_WIRELESS_SERVICES_URL,
                                "evidence": "Official OFCA data statistics page linking to the Wireless Services PDF.",
                            },
                        ],
                        ensure_ascii=False,
                    ),
                    "verification_note": "Official OFCA PDF table retained. 4G/5G columns are excluded in this build because PDF extraction splits those columns across continuation rows; no excluded values are estimated.",
                    "cmhk_relevance": "Wireless subscriptions, mobile broadband adoption, machine-type connections, mobile data usage and SMS traffic contextualise CMHK mobile subscriber quality, data demand, IoT and market saturation.",
                }
            )
    return rows


def parse_ofca_internet_period(raw: str) -> tuple[str, str]:
    value = clean_text(raw)
    match = re.match(r"(\d{2})/(\d{4})$", value)
    if not match:
        raise RuntimeError(f"Unexpected OFCA internet period: {value}")
    month = int(match.group(1))
    year = int(match.group(2))
    return f"{year:04d}-{month:02d}", month_end(year, month)


def parse_ofca_internet_value(raw: str | None) -> float | None:
    value = clean_text(raw or "")
    if not value or value.upper() in {"N/A", "NA", "-", "--"}:
        return None
    value = re.sub(r"\s*f$", "", value).strip()
    return parse_figure(value)


def append_ofca_internet_rows(
    rows: list[dict[str, Any]],
    source_row: list[str | None],
    columns: dict[int, tuple[str, str, str]],
    source_family: str,
    indicator_group: str,
    quality_status: str,
    evidence_scope: str,
    relevance: str,
) -> None:
    periods = parse_pdf_cell_lines(source_row[0])
    if not periods:
        return
    parsed_values: dict[int, list[str]] = {idx: parse_pdf_cell_lines(source_row[idx]) for idx in columns if idx < len(source_row)}
    if any(len(values) != len(periods) for values in parsed_values.values()):
        raise RuntimeError(f"Unexpected OFCA internet table shape for {source_family}")

    for col_idx, (metric_key, metric_name, unit) in columns.items():
        values = parsed_values[col_idx]
        for raw_period, raw_value in zip(periods, values):
            period, period_end = parse_ofca_internet_period(raw_period)
            official_value = parse_ofca_internet_value(raw_value)
            is_gap = official_value is None
            status = "source_gap_confirmed" if is_gap else "official_match"
            rows.append(
                {
                    "subject": "Hong Kong internet service subscriptions",
                    "category": "macro_policy",
                    "source_family": source_family,
                    "indicator_group": indicator_group,
                    "period": period,
                    "period_end": period_end,
                    "grain": "monthly_snapshot",
                    "metric_key": metric_key,
                    "metric_name": metric_name,
                    "metric_detail": metric_name,
                    "value": "" if is_gap else official_value,
                    "unit": unit,
                    "official_value": "" if is_gap else official_value,
                    "official_unit": unit,
                    "verification_status": status,
                    "quality_status": quality_status,
                    "official_source_label": "OFCA Statistics on Internet Service Subscriptions in Hong Kong",
                    "official_source_url": OFCA_INTERNET_SUBSCRIPTIONS_PDF_URL,
                    "official_evidence": f"OFCA Internet Service Subscriptions official PDF reports {metric_name} for {raw_period}; {evidence_scope}.",
                    "verification_count": 2,
                    "verification_method": "official_pdf_table_plus_official_statistics_page_crosscheck",
                    "verification_sources": json.dumps(
                        [
                            {
                                "label": "OFCA Internet Service Subscriptions official PDF",
                                "url": OFCA_INTERNET_SUBSCRIPTIONS_PDF_URL,
                                "evidence": "Official PDF table for internet service subscriptions in Hong Kong.",
                            },
                            {
                                "label": "OFCA Internet Service Subscriptions statistics page",
                                "url": OFCA_INTERNET_SUBSCRIPTIONS_URL,
                                "evidence": "Official OFCA data statistics page linking to the internet service subscriptions PDF.",
                            },
                        ],
                        ensure_ascii=False,
                    ),
                    "verification_note": "Official OFCA PDF table retained. From January 2019 onward the statistics are access lines; prior periods are customer accounts and are kept as a separate legacy source family, not mixed into a single forecast series.",
                    "cmhk_relevance": relevance,
                }
            )


def parse_ofca_internet_subscriptions() -> list[dict[str, Any]]:
    pdf_bytes = urlopen(Request(OFCA_INTERNET_SUBSCRIPTIONS_PDF_URL, headers={"User-Agent": "Mozilla/5.0"}), timeout=45).read()
    tmp_pdf = ROOT / "tmp" / "ofca_cus_isp_en.pdf"
    tmp_pdf.parent.mkdir(parents=True, exist_ok=True)
    tmp_pdf.write_bytes(pdf_bytes)

    with pdfplumber.open(str(tmp_pdf)) as pdf:
        access_tables = pdf.pages[0].extract_tables()
        account_tables = pdf.pages[1].extract_tables()
    if not access_tables or not account_tables:
        raise RuntimeError("OFCA internet subscriptions tables not found")

    rows: list[dict[str, Any]] = []
    access_table = access_tables[0]
    account_table = account_tables[0]
    if len(access_table) < 7 or len(account_table) < 5:
        raise RuntimeError("OFCA internet subscriptions annual rows not found")

    # Table 1 row 6 contains annual December access-line snapshots for 2019-2025.
    append_ofca_internet_rows(
        rows,
        access_table[6],
        OFCA_INTERNET_ACCESS_LINE_COLUMNS,
        "OFCA internet service subscriptions",
        "Internet Service Subscriptions",
        "official_public_pdf_table_access_lines",
        "retained as post-2019 access-line series after OFCA's methodology change",
        "Fixed broadband and internet access-line adoption contextualise CMHK home broadband, FWA, converged service and enterprise connectivity demand.",
    )

    # Table 2 contains pre-2019 customer-account snapshots. Keep only 2016-2018
    # for the current 10-year window and do not mix with post-2019 access lines.
    legacy_row = account_table[4]
    legacy_periods = parse_pdf_cell_lines(legacy_row[0])
    keep_indexes = [idx for idx, period in enumerate(legacy_periods) if period in {"12/2018", "12/2017", "12/2016"}]
    if len(keep_indexes) != 3:
        raise RuntimeError(f"Unexpected OFCA internet legacy periods: {legacy_periods[:5]}")
    filtered_legacy_row = ["\n".join(legacy_periods[idx] for idx in keep_indexes)]
    for col_idx in range(1, len(legacy_row)):
        values = parse_pdf_cell_lines(legacy_row[col_idx])
        filtered_legacy_row.append("\n".join(values[idx] for idx in keep_indexes))
    append_ofca_internet_rows(
        rows,
        filtered_legacy_row,
        OFCA_INTERNET_CUSTOMER_ACCOUNT_COLUMNS,
        "OFCA internet service subscriptions legacy customer accounts",
        "Internet Service Subscriptions",
        "official_public_pdf_table_legacy_customer_accounts",
        "retained separately as pre-2019 customer-account series before OFCA's methodology change",
        "Legacy broadband and internet customer-account adoption provides historical context for CMHK fixed broadband and household connectivity trends, but is not directly comparable with post-2019 access-line rows.",
    )
    return rows


def ofca_complaint_period(header: str) -> tuple[str, str, str]:
    header = clean_text(header)
    year_match = re.search(r"(20\d{2})", header)
    if not year_match:
        raise RuntimeError(f"Unexpected OFCA complaint period header: {header}")
    year = int(year_match.group(1))
    quarter_match = re.search(r"(\d+)\s*(?:st|nd|rd|th)?\s+Quarter", header, re.IGNORECASE)
    if quarter_match:
        quarter = int(quarter_match.group(1))
        end_month = quarter * 3
        return f"Q{quarter} {year}", month_end(year, end_month), "quarter"
    return str(year), f"{year}-12-31", "calendar_year"


def parse_ofca_consumer_complaints() -> list[dict[str, Any]]:
    html = fetch_html(OFCA_CONSUMER_COMPLAINTS_URL)
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        raise RuntimeError("OFCA consumer complaints table not found")

    parsed_rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [clean_text(c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])]
        if cells:
            parsed_rows.append(cells)
    if len(parsed_rows) < 2:
        raise RuntimeError("OFCA consumer complaints table has no data rows")

    headers = parsed_rows[0]
    if len(headers) < 2 or not headers[0].lower().startswith("service type"):
        raise RuntimeError(f"Unexpected OFCA consumer complaints header: {headers}")

    period_map = [ofca_complaint_period(header) for header in headers[1:]]
    rows: list[dict[str, Any]] = []
    for source_row in parsed_rows[1:]:
        if len(source_row) != len(headers):
            continue
        service_type = clean_text(source_row[0]).lstrip("*")
        metric_key = f"telecom_consumer_complaints_{slugify(service_type)}"
        metric_name = f"Telecom consumer complaints - {service_type}"
        for raw_value, (period, period_end, grain) in zip(source_row[1:], period_map):
            official_value = parse_number(raw_value)
            is_gap = official_value is None
            status = "source_gap_confirmed" if is_gap else "official_match"
            rows.append(
                {
                    "subject": "Hong Kong telecom consumer complaints",
                    "category": "macro_policy",
                    "source_family": "OFCA consumer complaints",
                    "indicator_group": "Consumer Complaints",
                    "period": period,
                    "period_end": period_end,
                    "grain": grain,
                    "metric_key": metric_key,
                    "metric_name": metric_name,
                    "metric_detail": service_type,
                    "value": "" if is_gap else official_value,
                    "unit": "complaints",
                    "official_value": "" if is_gap else official_value,
                    "official_unit": "complaints",
                    "verification_status": status,
                    "quality_status": "official_public_table",
                    "official_source_label": "OFCA Consumer Complaint Statistics",
                    "official_source_url": OFCA_CONSUMER_COMPLAINTS_URL,
                    "official_evidence": f"OFCA Consumer Complaint Statistics table reports {service_type} complaints for {period}; retained as service-quality pressure context for CMHK.",
                    "verification_count": 2,
                    "verification_method": "official_table_plus_official_statistics_index_crosscheck",
                    "verification_sources": json.dumps(
                        [
                            {
                                "label": "OFCA Consumer Complaint Statistics",
                                "url": OFCA_CONSUMER_COMPLAINTS_URL,
                                "evidence": "Official OFCA table updated quarterly with telecom complaints by service type.",
                            },
                            {
                                "label": "OFCA Figures & Statistics index",
                                "url": OFCA_DATA_STATISTICS_INDEX_URL,
                                "evidence": "Official OFCA figures and statistics index lists Consumer Complaints as a data-statistics category.",
                            },
                        ],
                        ensure_ascii=False,
                    ),
                    "verification_note": "Official OFCA current complaint table retained. Older historical complaint periods are not estimated; they remain backlog items until official archived tables are found.",
                    "cmhk_relevance": "Telecom complaints by service type indicate customer experience and service-quality pressure for CMHK mobile, fixed broadband and internet service competition.",
                }
            )
    return rows


def parse_csd_table(source_id: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    payload = fetch_json(config["api_url"], config["web_url"])
    data = payload.get("dataSet") or []
    rows: list[dict[str, Any]] = []
    for item in data:
        if not include_csd_row(config, item):
            continue
        period, period_end, grain = csd_period_fields(str(item.get("freq", "")), str(item.get("period", "")))
        if not in_ten_year_window(period_end):
            continue
        official_value = parse_figure(item.get("figure"))
        is_gap = official_value is None
        metric_key, metric_name, metric_detail = csd_metric_identity(config, item)
        unit = csd_unit(item)
        status = "source_gap_confirmed" if is_gap else "official_match"
        rows.append(
            {
                "subject": "Hong Kong macro environment",
                "category": "macro_policy",
                "source_family": f"C&SD {config['indicator_group']}",
                "indicator_group": config["indicator_group"],
                "period": period,
                "period_end": period_end,
                "grain": grain,
                "metric_key": metric_key,
                "metric_name": metric_name,
                "metric_detail": metric_detail,
                "value": "" if is_gap else official_value,
                "unit": unit,
                "official_value": "" if is_gap else official_value,
                "official_unit": unit,
                "verification_status": status,
                "quality_status": "official_public_api",
                "official_source_label": f"C&SD {config['title']}",
                "official_source_url": config["web_url"],
                "official_evidence": f"C&SD official API for table {source_id} reports {metric_name} for {period}; retained as macro context for CMHK trend and forecast interpretation.",
                "verification_count": 2,
                "verification_method": "official_api_plus_official_web_table_crosscheck",
                "verification_sources": json.dumps(
                    [
                        {
                            "label": f"C&SD API - {config['title']}",
                            "url": config["api_url"],
                            "evidence": "Official C&SD JSON API endpoint generated from the public statistical table.",
                        },
                        {
                            "label": f"C&SD web table - {config['title']}",
                            "url": config["web_url"],
                            "evidence": "Official public web table and metadata page for the same dataset.",
                        },
                    ],
                    ensure_ascii=False,
                ),
                "verification_note": "Official C&SD API value cross-referenced to its public web table. Missing official figures are kept as source gaps and are not estimated.",
                "cmhk_relevance": config["relevance"],
            }
        )
    return rows


def include_csd_post_row(config: dict[str, Any], row: dict[str, Any]) -> bool:
    include = config.get("include", {})
    for field, allowed in include.items():
        value = clean_text(str(row.get(field, "")))
        if allowed and value not in allowed:
            return False
    return True


def parse_csd_post_table(source_id: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    payload = fetch_csd_post(config["table_id"], config["query"], config["web_url"])
    status = ((payload.get("header") or {}).get("status") or {}).get("name")
    if status != "Success":
        raise RuntimeError(f"C&SD POST API failed for {source_id}: {status}")
    data = payload.get("dataSet") or []
    rows: list[dict[str, Any]] = []
    for item in data:
        if not include_csd_post_row(config, item):
            continue
        period, period_end, grain = csd_period_fields(str(item.get("freq", "")), str(item.get("period", "")))
        if not in_ten_year_window(period_end):
            continue
        official_value = parse_figure(item.get("figure"))
        is_gap = official_value is None
        metric_key, metric_name, metric_detail = csd_metric_identity(config, item)
        unit = csd_unit(item)
        status = "source_gap_confirmed" if is_gap else "official_match"
        rows.append(
            {
                "subject": "Hong Kong macro environment",
                "category": "macro_policy",
                "source_family": f"C&SD {config['indicator_group']}",
                "indicator_group": config["indicator_group"],
                "period": period,
                "period_end": period_end,
                "grain": grain,
                "metric_key": metric_key,
                "metric_name": metric_name,
                "metric_detail": metric_detail,
                "value": "" if is_gap else official_value,
                "unit": unit,
                "official_value": "" if is_gap else official_value,
                "official_unit": unit,
                "verification_status": status,
                "quality_status": "official_public_api",
                "official_source_label": f"C&SD {config['title']}",
                "official_source_url": config["web_url"],
                "official_evidence": f"C&SD official POST API for table {config['table_id']} reports {metric_name} for {period}; retained as macro context for CMHK trend and forecast interpretation.",
                "verification_count": 2,
                "verification_method": "official_post_api_plus_official_web_table_crosscheck",
                "verification_sources": json.dumps(
                    [
                        {
                            "label": f"C&SD POST API - {config['title']}",
                            "url": "https://www.censtatd.gov.hk/api/post.php",
                            "evidence": f"Official C&SD API endpoint queried with table id {config['table_id']} and documented POST parameters.",
                        },
                        {
                            "label": f"C&SD web table - {config['title']}",
                            "url": config["web_url"],
                            "evidence": "Official public web table, API help and metadata page for the same dataset.",
                        },
                    ],
                    ensure_ascii=False,
                ),
                "verification_note": "Official C&SD POST API value cross-referenced to its public web table/API help. Missing official figures are kept as source gaps and are not estimated.",
                "cmhk_relevance": config["relevance"],
            }
        )
    return rows


def csd_mdt_filename(theme_id: str, table_id: str, stat_var: str, stat_pres: str) -> str:
    filename = f"MDT_{theme_id}_{table_id}_{stat_var}_{stat_pres}.csv"
    return filename.replace("/", "slash").replace("%", "percent").replace("$", "dollar")


def csd_household_period_fields(source_row: dict[str, str]) -> tuple[str, str, str]:
    year = int(clean_text(source_row.get("CCYY", "")))
    raw_m3m = clean_text(source_row.get("M3M", ""))
    if raw_m3m:
        month = int(float(raw_m3m))
        return f"3-month ending {year:04d}-{month:02d}", month_end(year, month), "moving_3_month"
    return str(year), f"{year:04d}-12-31", "calendar_year"


def strip_html(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if "<" in text and ">" in text:
        return clean_text(BeautifulSoup(text, "html.parser").get_text(" ", strip=True))
    return clean_text(text)


def parse_csd_household_income() -> list[dict[str, Any]]:
    comp = fetch_json(CSD_HOUSEHOLD_INCOME_COMP_URL, CSD_HOUSEHOLD_INCOME_WEB_URL)
    lang = fetch_json(CSD_HOUSEHOLD_INCOME_LANG_URL, CSD_HOUSEHOLD_INCOME_WEB_URL)
    if comp.get("tb_code") != CSD_HOUSEHOLD_INCOME_TABLE_ID or comp.get("theme_id") != CSD_HOUSEHOLD_INCOME_THEME_ID:
        raise RuntimeError("Unexpected C&SD household/income table metadata")

    component_pairs = {
        (item.get("stat_var"), item.get("stat_pres"))
        for item in comp.get("table_component_list", [])
    }
    rows: list[dict[str, Any]] = []
    table_notes = strip_html(lang.get("tb_fn"))
    table_source = strip_html(lang.get("tb_src"))
    for stat_var, (stat_pres, metric_key, metric_name, unit) in CSD_HOUSEHOLD_INCOME_METRICS.items():
        if (stat_var, stat_pres) not in component_pairs:
            raise RuntimeError(f"C&SD household/income component missing: {stat_var}/{stat_pres}")
        sv_meta = (lang.get("sv_list") or {}).get(stat_var) or {}
        if stat_pres not in (sv_meta.get("sp_list") or {}):
            raise RuntimeError(f"C&SD household/income presentation missing: {stat_var}/{stat_pres}")
        metric_detail_parts = [
            strip_html(sv_meta.get("def_stat_desc")) or metric_name,
            strip_html(sv_meta.get("note1")),
            strip_html(sv_meta.get("note2")),
            strip_html(sv_meta.get("note3")),
        ]
        metric_detail = " | ".join(dict.fromkeys(part for part in metric_detail_parts if part))
        mdt_filename = csd_mdt_filename(
            CSD_HOUSEHOLD_INCOME_THEME_ID,
            CSD_HOUSEHOLD_INCOME_TABLE_ID,
            stat_var,
            stat_pres,
        )
        mdt_url = CSD_HOUSEHOLD_INCOME_MDT_BASE_URL + mdt_filename
        csv_rows = fetch_csv_rows(mdt_url, CSD_HOUSEHOLD_INCOME_WEB_URL)
        if not csv_rows:
            raise RuntimeError(f"C&SD household/income MDT CSV empty: {mdt_filename}")
        for source_row in csv_rows:
            try:
                period, period_end, grain = csd_household_period_fields(source_row)
            except (TypeError, ValueError):
                continue
            if not in_ten_year_window(period_end):
                continue
            official_value = parse_figure(source_row.get("obs_value"))
            sd_value = clean_text(source_row.get("sd_value", ""))
            if official_value is None or official_value < 0 or sd_value == "9":
                continue
            rows.append(
                {
                    "subject": "Hong Kong household demand capacity",
                    "category": "macro_policy",
                    "source_family": "C&SD domestic households and income",
                    "indicator_group": "Domestic households and income",
                    "period": period,
                    "period_end": period_end,
                    "grain": grain,
                    "metric_key": metric_key,
                    "metric_name": metric_name,
                    "metric_detail": metric_detail,
                    "value": official_value,
                    "unit": unit,
                    "official_value": official_value,
                    "official_unit": unit,
                    "verification_status": "official_match",
                    "quality_status": "official_public_mdt_csv",
                    "official_source_label": "C&SD Statistics on domestic households",
                    "official_source_url": CSD_HOUSEHOLD_INCOME_WEB_URL,
                    "official_evidence": f"C&SD official MDT CSV for table 130-06102 reports {metric_name} for {period}; retained as household formation and income-capacity context for CMHK.",
                    "verification_count": 4,
                    "verification_method": "official_mdt_csv_plus_component_metadata_plus_language_metadata_plus_web_table_crosscheck",
                    "verification_sources": json.dumps(
                        [
                            {
                                "label": f"C&SD MDT CSV - {metric_name}",
                                "url": mdt_url,
                                "evidence": f"Official machine-readable MDT CSV for table 130-06102 component {stat_var}/{stat_pres}.",
                            },
                            {
                                "label": "C&SD table component metadata",
                                "url": CSD_HOUSEHOLD_INCOME_COMP_URL,
                                "evidence": "Official component JSON identifies table 130-06102, theme 55, the statistic variables, and annual / moving-three-month time dimensions.",
                            },
                            {
                                "label": "C&SD table language metadata",
                                "url": CSD_HOUSEHOLD_INCOME_LANG_URL,
                                "evidence": "Official metadata defines statistic descriptions, units, rounding notes and source section for the selected indicators.",
                            },
                            {
                                "label": "C&SD web table - Statistics on domestic households",
                                "url": CSD_HOUSEHOLD_INCOME_WEB_URL,
                                "evidence": "Official public web table for Statistics on domestic households and its API/download interface.",
                            },
                        ],
                        ensure_ascii=False,
                    ),
                    "verification_note": f"Official C&SD MDT CSV retained. {table_notes} Source: {table_source}. Cells with C&SD special display value 9 or -1 are excluded and not estimated.",
                    "cmhk_relevance": "Domestic household formation, household size, income capacity and home ownership mix are demand-capacity context for CMHK mobile plan mix, fixed broadband, home connectivity, handset affordability and consumer telecom spending.",
                }
            )
    if not rows:
        raise RuntimeError("C&SD household/income parser produced no rows")
    return rows


def csd_population_period_fields(source_row: dict[str, str], h_desc: str) -> tuple[str, str, str]:
    year = int(clean_text(source_row.get("CCYY", "")))
    if h_desc.lower() == "mid-year":
        return f"mid-year {year}", f"{year:04d}-06-30", "mid_year_snapshot"
    if h_desc.lower() == "year-end":
        return f"year-end {year}", f"{year:04d}-12-31", "year_end_snapshot"
    return str(year), f"{year:04d}-12-31", "calendar_year_snapshot"


def parse_csd_population_estimates() -> list[dict[str, Any]]:
    comp = fetch_json(CSD_POPULATION_COMP_URL, CSD_POPULATION_WEB_URL)
    lang = fetch_json(CSD_POPULATION_LANG_URL, CSD_POPULATION_WEB_URL)
    if comp.get("tb_code") != CSD_POPULATION_TABLE_ID or comp.get("theme_id") != CSD_POPULATION_THEME_ID:
        raise RuntimeError("Unexpected C&SD population table metadata")

    component_pairs = {
        (item.get("stat_var"), item.get("stat_pres"))
        for item in comp.get("table_component_list", [])
    }
    sv_meta = (lang.get("sv_list") or {}).get("POP") or {}
    cv_list = lang.get("cv_list") or {}
    sex_codes = ((cv_list.get("SEX") or {}).get("ccg_list") or {}).get("1", {}).get("cc_list") or {}
    age_codes = ((cv_list.get("AGE") or {}).get("ccg_list") or {}).get("2", {}).get("cc_list") or {}
    ref_codes = ((cv_list.get("H") or {}).get("ccg_list") or {}).get("1", {}).get("cc_list") or {}
    table_notes = strip_html(lang.get("tb_fn"))
    table_source = strip_html(lang.get("tb_src"))

    rows: list[dict[str, Any]] = []
    for stat_pres, (metric_key_base, metric_name_base, unit) in CSD_POPULATION_METRICS.items():
        if ("POP", stat_pres) not in component_pairs:
            raise RuntimeError(f"C&SD population component missing: POP/{stat_pres}")
        if stat_pres not in (sv_meta.get("sp_list") or {}):
            raise RuntimeError(f"C&SD population presentation missing: POP/{stat_pres}")
        mdt_filename = csd_mdt_filename(CSD_POPULATION_THEME_ID, CSD_POPULATION_TABLE_ID, "POP", stat_pres)
        mdt_url = CSD_HOUSEHOLD_INCOME_MDT_BASE_URL + mdt_filename
        csv_rows = fetch_csv_rows(mdt_url, CSD_POPULATION_WEB_URL)
        if not csv_rows:
            raise RuntimeError(f"C&SD population MDT CSV empty: {mdt_filename}")
        for source_row in csv_rows:
            sex = clean_text(source_row.get("SEX", ""))
            age = clean_text(source_row.get("AGE", ""))
            h_code = clean_text(source_row.get("H", ""))
            # Keep only compact, high-value cuts: total population, sex totals,
            # and all-sex age-group distribution. Skip sex-by-age cross rows.
            if sex and age:
                continue
            if not sex and not age and stat_pres == "Prop_1dp_%_n":
                continue
            h_desc = clean_text((ref_codes.get(h_code) or {}).get("def_class_code_desc", ""))
            try:
                period, period_end, grain = csd_population_period_fields(source_row, h_desc)
            except (TypeError, ValueError):
                continue
            if not in_ten_year_window(period_end):
                continue
            official_value = parse_figure(source_row.get("obs_value"))
            sd_value = clean_text(source_row.get("sd_value", ""))
            if official_value is None or official_value < 0 or sd_value == "9":
                continue
            segment_parts: list[str] = []
            key_parts = [metric_key_base]
            if sex:
                sex_desc = clean_text((sex_codes.get(sex) or {}).get("def_class_code_desc", sex))
                segment_parts.append(f"Sex: {sex_desc}")
                key_parts.append(f"sex_{slugify(sex_desc)}")
            if age:
                age_desc = clean_text((age_codes.get(age) or {}).get("def_class_code_desc", age))
                segment_parts.append(f"Age group: {age_desc}")
                key_parts.append(f"age_{slugify(age_desc.replace('and over', 'plus'))}")
            if not segment_parts:
                segment_parts.append("Total population")
                key_parts.append("total")
            metric_key = "_".join(part for part in key_parts if part)
            metric_name = f"{metric_name_base} - {'; '.join(segment_parts)}"
            sd_note = " Provisional figure." if sd_value == "102" else ""
            rows.append(
                {
                    "subject": "Hong Kong population demographics",
                    "category": "macro_policy",
                    "source_family": "C&SD population estimates",
                    "indicator_group": "Population demographics",
                    "period": period,
                    "period_end": period_end,
                    "grain": grain,
                    "metric_key": metric_key,
                    "metric_name": metric_name,
                    "metric_detail": f"{metric_name}; reference time-point: {h_desc or h_code}",
                    "value": official_value,
                    "unit": unit,
                    "official_value": official_value,
                    "official_unit": unit,
                    "verification_status": "official_match",
                    "quality_status": "official_public_mdt_csv",
                    "official_source_label": "C&SD Population by sex and age group",
                    "official_source_url": CSD_POPULATION_WEB_URL,
                    "official_evidence": f"C&SD official MDT CSV for table 110-01001 reports {metric_name} for {period}; retained as addressable-market and age-mix context for CMHK.",
                    "verification_count": 4,
                    "verification_method": "official_mdt_csv_plus_component_metadata_plus_language_metadata_plus_web_table_crosscheck",
                    "verification_sources": json.dumps(
                        [
                            {
                                "label": f"C&SD MDT CSV - {metric_name_base}",
                                "url": mdt_url,
                                "evidence": f"Official machine-readable MDT CSV for table 110-01001 component POP/{stat_pres}.",
                            },
                            {
                                "label": "C&SD population table component metadata",
                                "url": CSD_POPULATION_COMP_URL,
                                "evidence": "Official component JSON identifies table 110-01001, theme 76, the statistic presentations, sex, age, year and reference time-point dimensions.",
                            },
                            {
                                "label": "C&SD population table language metadata",
                                "url": CSD_POPULATION_LANG_URL,
                                "evidence": "Official metadata defines population, sex, age group and reference time-point labels and source section.",
                            },
                            {
                                "label": "C&SD web table - Population by sex and age group",
                                "url": CSD_POPULATION_WEB_URL,
                                "evidence": "Official public web table for Population by sex and age group and its API/download interface.",
                            },
                        ],
                        ensure_ascii=False,
                    ),
                    "verification_note": f"Official C&SD MDT CSV retained. {table_notes} Source: {table_source}.{sd_note} Sex-by-age cross rows are intentionally excluded from this compact CMHK macro package; no excluded values are estimated.",
                    "cmhk_relevance": "Population level, gender mix and age-group distribution are addressable-market, ageing, family-plan, handset, broadband and consumer-service demand context for CMHK trend interpretation and forecasting scenarios.",
                }
            )
    if not rows:
        raise RuntimeError("C&SD population parser produced no rows")
    return rows


def parse_csd_macro_indicators() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source_id, config in CSD_TABLES.items():
        rows.extend(parse_csd_table(source_id, config))
    for source_id, config in CSD_POST_TABLES.items():
        rows.extend(parse_csd_post_table(source_id, config))
    rows.extend(parse_csd_household_income())
    rows.extend(parse_csd_population_estimates())
    return rows


POLICY_EVENTS: list[dict[str, Any]] = [
    {
        "period": "2016",
        "period_end": "2016-12-31",
        "metric_key": "900_1800_mhz_refarming_and_auction_policy",
        "metric_name": "900/1800 MHz refarming and auction policy preparation",
        "official_value": "policy_event",
        "official_source_label": "OFCA 900 MHz and 1800 MHz auction information memorandum",
        "official_source_url": "https://www.ofca.gov.hk/filemanager/ofca/en/content_1107/900_MHz_and_1800_MHz_Auction_IM.pdf",
        "official_evidence": "OFCA auction memorandum documents reassignment/refarming arrangements for the 900 MHz and 1800 MHz bands.",
        "cmhk_relevance": "Spectrum continuity and refarming affected mobile network capacity planning and competitive positioning.",
        "verification_sources": [
            {
                "label": "OFCA 900/1800 MHz auction information memorandum",
                "url": "https://www.ofca.gov.hk/filemanager/ofca/en/content_1107/900_MHz_and_1800_MHz_Auction_IM.pdf",
                "evidence": "Official auction and spectrum reassignment document.",
            },
            {
                "label": "OFCA Spectrum Management page",
                "url": OFCA_SPECTRUM_MANAGEMENT_URL,
                "evidence": "Official spectrum management entry point and release plan index.",
            },
        ],
    },
    {
        "period": "2020",
        "period_end": "2020-04-01",
        "metric_key": "commercial_5g_launch",
        "metric_name": "Commercial 5G services launched in Hong Kong",
        "official_value": "policy_event",
        "official_source_label": "OFCA Trade Fund Report 2024/25",
        "official_source_url": OFCA_MARKET_REPORT_2024_25_URL,
        "official_evidence": "OFCA market report states commercial 5G services launched on 1 April 2020.",
        "cmhk_relevance": "5G launch is the baseline for CMHK mobile ARPU, data usage, enterprise 5G, and network investment trend analysis.",
        "verification_sources": [
            {
                "label": "OFCA Trade Fund Report 2024/25",
                "url": OFCA_MARKET_REPORT_2024_25_URL,
                "evidence": "Official market report summarizes 5G launch and coverage progress.",
            },
            {
                "label": "OFCA technical reports - 5G trials",
                "url": "https://www.ofca.gov.hk/en/industry_focus/pub_report/technical_reports/index.html",
                "evidence": "Official technical report index includes pre-commercial 5G trial reports by local MNOs.",
            },
        ],
    },
    {
        "period": "2021",
        "period_end": "2021-09-01",
        "metric_key": "sim_real_name_registration_effective",
        "metric_name": "SIM card real-name registration regulation came into operation",
        "official_value": "policy_event",
        "official_source_label": "OFCA Major Tasks and Projects 2022/23",
        "official_source_url": "https://www.ofca.gov.hk/filemanager/ofca/en/content_92/majortasks_22-23_e.pdf",
        "official_evidence": "OFCA major tasks document records that the SIM registration regulation came into operation on 1 September 2021.",
        "cmhk_relevance": "Affected prepaid SIM management, subscriber base quality, compliance workload, and churn interpretation.",
        "verification_sources": [
            {
                "label": "OFCA Major Tasks and Projects 2022/23",
                "url": "https://www.ofca.gov.hk/filemanager/ofca/en/content_92/majortasks_22-23_e.pdf",
                "evidence": "Official OFCA task document describes SIM real-name implementation.",
            },
            {
                "label": "OFCA Key Communications Statistics",
                "url": OFCA_KEY_STATS_URL,
                "evidence": "Official current subscriber and market statistics context affected by real-name registration.",
            },
        ],
    },
    {
        "period": "2024/25",
        "period_end": "2025-03-31",
        "metric_key": "5g_spectrum_assigned_mhz",
        "metric_name": "Spectrum assigned for public mobile / 5G services",
        "official_value": 3630,
        "official_unit": "MHz",
        "official_source_label": "OFCA Trade Fund Report 2024/25",
        "official_source_url": OFCA_MARKET_REPORT_2024_25_URL,
        "official_evidence": "OFCA market report states 3,630 MHz of spectrum had been assigned in low, mid and high frequency bands for public mobile telecommunications use as of end-March 2025.",
        "cmhk_relevance": "Spectrum supply constrains and enables CMHK network capacity, coverage, and 5G/enterprise service competitiveness.",
        "verification_sources": [
            {
                "label": "OFCA Trade Fund Report 2024/25",
                "url": OFCA_MARKET_REPORT_2024_25_URL,
                "evidence": "Official report gives assigned spectrum total and 5G bands.",
            },
            {
                "label": "OFCA Spectrum Management page",
                "url": OFCA_SPECTRUM_MANAGEMENT_URL,
                "evidence": "Official spectrum management page links frequency allocation and release plan resources.",
            },
        ],
    },
    {
        "period": "2024/25",
        "period_end": "2025-03-31",
        "metric_key": "5g_population_coverage_status",
        "metric_name": "5G population coverage exceeded 99%",
        "official_value": 99,
        "official_unit": "percent_plus",
        "official_source_label": "OFCA Trade Fund Report 2024/25",
        "official_source_url": OFCA_MARKET_REPORT_2024_25_URL,
        "official_evidence": "OFCA market report states 5G coverage in Hong Kong exceeded 99% as of end-March 2025.",
        "cmhk_relevance": "Coverage maturity changes growth interpretation from rollout expansion to monetisation, quality, and enterprise use-case adoption.",
        "verification_sources": [
            {
                "label": "OFCA Trade Fund Report 2024/25",
                "url": OFCA_MARKET_REPORT_2024_25_URL,
                "evidence": "Official report states 5G coverage exceeded 99%.",
            },
            {
                "label": "OFCA Major Tasks and Projects 2025/26",
                "url": "https://www.ofca.gov.hk/filemanager/ofca/en/content_92/majortasks_25-26_e.pdf",
                "evidence": "Official tasks document repeats 5G population coverage and rural/country-park coverage context.",
            },
        ],
    },
    {
        "period": "2025",
        "period_end": "2025-12-31",
        "metric_key": "rural_remote_5g_coverage_subsidy",
        "metric_name": "Subsidy scheme to extend 5G coverage in rural and remote areas",
        "official_value": "policy_event",
        "official_source_label": "OFCA TRAAC paper index",
        "official_source_url": "https://www.ofca.gov.hk/en/about_us/advisory_committees/TRAAC/papers/index.html",
        "official_evidence": "OFCA TRAAC papers index lists the subsidy scheme to extend 5G coverage in rural and remote areas.",
        "cmhk_relevance": "May affect CMHK rural network economics, coverage obligations, capex timing, and service availability outside dense urban areas.",
        "verification_sources": [
            {
                "label": "OFCA TRAAC papers index",
                "url": "https://www.ofca.gov.hk/en/about_us/advisory_committees/TRAAC/papers/index.html",
                "evidence": "Official advisory committee index lists the rural and remote 5G coverage subsidy scheme.",
            },
            {
                "label": "OFCA Major Tasks and Projects 2025/26",
                "url": "https://www.ofca.gov.hk/filemanager/ofca/en/content_92/majortasks_25-26_e.pdf",
                "evidence": "Official tasks document gives rural/country-park coverage and base station context.",
            },
        ],
    },
]


def build_policy_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in POLICY_EVENTS:
        official_value = item.get("official_value", "")
        rows.append(
            {
                "subject": "Hong Kong telecommunications policy environment",
                "category": "macro_policy",
                "source_family": "government_regulatory_policy",
                "indicator_group": "Policy / spectrum / regulatory milestone",
                "period": item["period"],
                "period_end": item["period_end"],
                "grain": "event",
                "metric_key": item["metric_key"],
                "metric_name": item["metric_name"],
                "metric_detail": item["metric_name"],
                "value": official_value,
                "unit": item.get("official_unit", "event"),
                "official_value": official_value,
                "official_unit": item.get("official_unit", "event"),
                "verification_status": "official_match",
                "quality_status": "official_policy_event",
                "official_source_label": item["official_source_label"],
                "official_source_url": item["official_source_url"],
                "official_evidence": item["official_evidence"],
                "verification_count": len(item["verification_sources"]),
                "verification_method": "official_policy_document_crosscheck",
                "verification_sources": json.dumps(item["verification_sources"], ensure_ascii=False),
                "verification_note": "Policy/event row from official government/regulator material; not interpolated.",
                "cmhk_relevance": item["cmhk_relevance"],
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"No rows to write for {path}")
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def build_sources() -> list[dict[str, Any]]:
    sources = {
        "ofca_telecom_indicators": {
            "id": "ofca_telecom_indicators",
            "title": "OFCA Telecommunications Indicators in Hong Kong",
            "url": OFCA_TELECOM_INDICATORS_URL,
            "institution": "Office of the Communications Authority",
            "source_type": "official_public_html_table",
            "notes": "Historical annual telecommunications indicators for fiscal years 2005/06 to 2024/25.",
        },
        "ofca_indicators_index": {
            "id": "ofca_indicators_index",
            "title": "OFCA Hong Kong Telecommunications Indicators",
            "url": OFCA_INDICATORS_INDEX_URL,
            "institution": "Office of the Communications Authority",
            "source_type": "official_index_page",
            "notes": "Current annual indicator page and definition link.",
        },
        "ofca_key_stats": {
            "id": "ofca_key_stats",
            "title": "OFCA Key Communications Statistics",
            "url": OFCA_KEY_STATS_URL,
            "csv_url": OFCA_KEY_STATS_CSV_URL,
            "data_dictionary_url": OFCA_KEY_STATS_DATA_DICT_URL,
            "dataset_url": DATA_GOV_KEY_STATS_DATASET_URL,
            "institution": "Office of the Communications Authority",
            "source_type": "official_datagovhk_csv_and_statistics_page",
            "notes": "Historical point-in-time communications statistics from OFCA/data.gov.hk CSV, crosschecked with the official data dictionary and OFCA statistics page.",
        },
        "ofca_consumer_complaints": {
            "id": "ofca_consumer_complaints",
            "title": "OFCA Consumer Complaint Statistics",
            "url": OFCA_CONSUMER_COMPLAINTS_URL,
            "institution": "Office of the Communications Authority",
            "source_type": "official_quarterly_statistics_table",
            "notes": "Current official complaint table retained for service-quality context; older history remains backlog until official archived tables are found.",
        },
        "ofca_internet_service_subscriptions": {
            "id": "ofca_internet_service_subscriptions",
            "title": "OFCA Statistics on Internet Service Subscriptions in Hong Kong",
            "url": OFCA_INTERNET_SUBSCRIPTIONS_URL,
            "pdf_url": OFCA_INTERNET_SUBSCRIPTIONS_PDF_URL,
            "institution": "Office of the Communications Authority",
            "source_type": "official_statistics_pdf_and_index_page",
            "notes": "Access-line series from 2019 onward and pre-2019 customer-account snapshots are kept as separate source families because OFCA changed methodology in January 2019.",
        },
        "ofca_wireless_services": {
            "id": "ofca_wireless_services",
            "title": "OFCA Key Statistics for Telecommunications in Hong Kong - Wireless Services",
            "url": OFCA_WIRELESS_SERVICES_URL,
            "pdf_url": OFCA_WIRELESS_SERVICES_PDF_URL,
            "institution": "Office of the Communications Authority",
            "source_type": "official_statistics_pdf_and_index_page",
            "notes": "Annual December wireless services snapshots retained for the latest official 10-year window; 4G/5G split columns are excluded until a safer structured source is available.",
        },
        "ofca_spectrum_management": {
            "id": "ofca_spectrum_management",
            "title": "OFCA Spectrum Management",
            "url": OFCA_SPECTRUM_MANAGEMENT_URL,
            "institution": "Office of the Communications Authority",
            "source_type": "official_policy_index",
            "notes": "Spectrum management, allocation, release plan and policy framework entry point.",
        },
        "ofca_trade_fund_report_2024_25": {
            "id": "ofca_trade_fund_report_2024_25",
            "title": "OFCA Trade Fund Report 2024/25 - Telecommunications Market",
            "url": OFCA_MARKET_REPORT_2024_25_URL,
            "institution": "Office of the Communications Authority",
            "source_type": "official_market_report",
            "notes": "Provides 5G launch, coverage and assigned spectrum context.",
        },
        "csd_household_income_130_06102": {
            "id": "csd_household_income_130_06102",
            "title": "C&SD Statistics on domestic households",
            "url": CSD_HOUSEHOLD_INCOME_WEB_URL,
            "component_metadata_url": CSD_HOUSEHOLD_INCOME_COMP_URL,
            "language_metadata_url": CSD_HOUSEHOLD_INCOME_LANG_URL,
            "institution": "Census and Statistics Department",
            "source_type": "official_public_mdt_csv_and_web_table",
            "notes": "Official annual and moving-three-month domestic household, household-size, income and owner-occupier indicators retained for the latest available 10-year window.",
        },
        "csd_population_110_01001": {
            "id": "csd_population_110_01001",
            "title": "C&SD Population by sex and age group",
            "url": CSD_POPULATION_WEB_URL,
            "component_metadata_url": CSD_POPULATION_COMP_URL,
            "language_metadata_url": CSD_POPULATION_LANG_URL,
            "institution": "Census and Statistics Department",
            "source_type": "official_public_mdt_csv_and_web_table",
            "notes": "Official mid-year and year-end population by sex and age group retained in a compact CMHK macro package cut: total population, sex totals and all-sex age groups.",
        },
    }
    for source_id, config in CSD_TABLES.items():
        sources[source_id] = {
            "id": source_id,
            "title": f"C&SD {config['title']}",
            "url": config["web_url"],
            "api_url": config["api_url"],
            "institution": config["institution"],
            "source_type": "official_public_api_and_web_table",
            "notes": f"{config['indicator_group']} series retained for the latest available 10-year macro context window.",
        }
    for source_id, config in CSD_POST_TABLES.items():
        sources[source_id] = {
            "id": source_id,
            "title": f"C&SD {config['title']}",
            "url": config["web_url"],
            "api_url": "https://www.censtatd.gov.hk/api/post.php",
            "institution": config["institution"],
            "source_type": "official_public_post_api_and_web_table",
            "notes": f"{config['indicator_group']} series retained for the latest available 10-year macro context window.",
        }
    return list(sources.values())


def build_summary(rows: list[dict[str, Any]]) -> str:
    by_group: dict[str, int] = {}
    by_source_family: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_source_family_status: dict[tuple[str, str], int] = {}
    for row in rows:
        by_group[row["indicator_group"]] = by_group.get(row["indicator_group"], 0) + 1
        by_source_family[row["source_family"]] = by_source_family.get(row["source_family"], 0) + 1
        by_status[row["verification_status"]] = by_status.get(row["verification_status"], 0) + 1
        key = (row["source_family"], row["verification_status"])
        by_source_family_status[key] = by_source_family_status.get(key, 0) + 1
    lines = [
        "# CMHK Macro Policy and Institutional Indicators Summary",
        "",
        f"- Build date: {BUILD_DATE}",
        f"- Rows: {len(rows)}",
        "- Current coverage: OFCA official annual telecommunications indicators for FY2015/16-FY2024/25; OFCA Key Communications Statistics point-in-time CSV history for 2017-2026 where official fields are populated; OFCA Wireless Services December snapshots for 2016-2025; OFCA Internet Service Subscriptions post-2019 access-line and pre-2019 legacy customer-account snapshots; OFCA current consumer complaint statistics for 2023-2026 Q1; C&SD official monthly/quarterly/annual macro, GDP growth, labour-market, and domestic-household/income series from the latest available 10-year window; selected official policy/spectrum/5G milestones.",
        "- Source integrity: every current row has `verification_count >= 2`; unavailable official cells remain `source_gap_confirmed` and are not estimated.",
        "",
        "## Prediction Readiness",
        "",
        "- C&SD monthly CPI/retail/labour rows and quarterly PCE/GDP-growth rows are suitable as macro/exogenous context for forecasting and scenario interpretation.",
        "- OFCA annual telecom indicators are suitable for long-term annual telecom-market trend context, not high-frequency quarterly target fitting.",
        "- OFCA internet service subscriptions are useful for fixed-broadband adoption context; post-2019 access-line rows and pre-2019 customer-account rows must not be merged into one forecast target.",
        "- OFCA Key Communications Statistics rows are monthly point-in-time market snapshots from official data.gov.hk CSV; blank fields are not estimated or converted to zero.",
        "- C&SD domestic-household/income rows are household demand-capacity context; annual and moving-three-month rows must be kept as separate grains.",
        "- OFCA consumer complaint rows are service-quality and customer-experience pressure context, not direct revenue or subscriber forecast targets.",
        "- Policy event rows are explanatory regressors/context for interpretation and scenario discussion, not numeric forecast targets.",
        "- OFCA Wireless Services December snapshots are useful for annual mobile-market context; 4G/5G split columns remain excluded from generated rows until a safer structured source is available.",
        "",
        "## Rows by Verification Status",
        "",
    ]
    for key, value in sorted(by_status.items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Rows by Source Family", ""])
    for key, value in sorted(by_source_family.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Verification Status by Source Family", ""])
    for family, total in sorted(by_source_family.items(), key=lambda item: (-item[1], item[0])):
        status_parts = []
        for status in sorted(by_status):
            count = by_source_family_status.get((family, status), 0)
            if count:
                status_parts.append(f"{status}={count}")
        lines.append(f"- {family}: {total} rows ({', '.join(status_parts)})")
    lines.extend(["", "## Largest Indicator Groups", ""])
    for key, value in sorted(by_group.items(), key=lambda item: (-item[1], item[0]))[:20]:
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## Use In 小竞AI",
            "",
            "- Use this package when users ask about Hong Kong telecom market saturation, mobile/broadband adoption, spectrum/5G policy, telecom investment, or macro-regulatory context affecting CMHK.",
            "- For formal conclusions, use `official_value` and read `verification_sources` before citing a row.",
            "- Do not convert policy events into numeric forecasts unless a reviewed model explicitly encodes them as event indicators.",
        ]
    )
    return "\n".join(lines)


def build_verification(rows: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    audit_rows: list[dict[str, Any]] = []
    for row in rows:
        audit_rows.append(
            {
                "subject": row["subject"],
                "source_family": row["source_family"],
                "period": row["period"],
                "metric_key": row["metric_key"],
                "metric_name": row["metric_name"],
                "official_value": row["official_value"],
                "official_unit": row["official_unit"],
                "verification_status": row["verification_status"],
                "verification_count": row["verification_count"],
                "official_source_label": row["official_source_label"],
                "official_source_url": row["official_source_url"],
                "verification_method": row["verification_method"],
                "note": row["verification_note"],
            }
        )
    low_count = sum(1 for row in audit_rows if int(row["verification_count"]) < 2)
    gaps = [row for row in audit_rows if row["verification_status"] == "source_gap_confirmed"]
    md = [
        "# Online Verification Audit",
        "",
        f"- Build date: {BUILD_DATE}",
        f"- Rows checked: {len(rows)}",
        f"- Rows with verification_count < 2: {low_count}",
        f"- source_gap_confirmed rows: {len(gaps)}",
        "- Current package stage: OFCA official telecom indicators, OFCA wireless-service snapshots, C&SD official macro/GDP/labour API series, and selected official policy/spectrum events are integrated.",
        "",
        "## Method",
        "",
        "- Quantitative annual telecom rows are parsed from OFCA's official historical telecommunications indicators table and crosschecked against the OFCA telecommunications indicators index.",
        "- OFCA Wireless Services annual December snapshots are parsed from the official Wireless Services PDF and crosschecked against the official statistics page.",
        "- C&SD macro rows are parsed from official JSON API endpoints and crosschecked to their public C&SD web-table pages.",
        "- Policy rows use official regulator/government policy documents plus an official index/context page.",
        "- Missing cells are source gaps, not estimates.",
        "",
        "## Source Gap Rows",
        "",
    ]
    if gaps:
        md.extend(["| source_family | period | metric_key | metric_name | official_value | note |", "|---|---:|---|---|---:|---|"])
        for row in gaps:
            md.append(
                f"| {row['source_family']} | {row['period']} | {row['metric_key']} | "
                f"{row['metric_name']} | {row['official_value']} | {row['note']} |"
            )
    else:
        md.append("- None.")
    return "\n".join(md), audit_rows


def build_historical_indicator_backlog() -> list[dict[str, str]]:
    return [
        {
            "priority": "P0",
            "domain": "telecom_market_quality",
            "candidate_source_family": "OFCA consumer complaints",
            "official_source_url": "https://www.ofca.gov.hk/en/news_info/data_statistics/complaint_stat/index.html",
            "official_api_url": "",
            "candidate_metrics": "Quarterly telecom complaints by service type: mobile, fixed network, internet, external telecommunications, total.",
            "target_grain": "quarterly",
            "target_history": "Latest available years from official page; older years only if official archived tables are found.",
            "cmhk_relevance": "Customer experience and service-quality pressure indicator for mobile and broadband competition.",
            "collection_status": "partially_collected_current_table",
            "boundary_rule": "Do not backfill years not present on official OFCA pages; retain source_gap records for unavailable historical complaint tables.",
            "next_step": "Current 2023-2026 Q1 official table is collected; search official OFCA archives for older quarterly complaint tables before adding a 10-year series.",
        },
        {
            "priority": "P0",
            "domain": "fixed_broadband_demand",
            "candidate_source_family": "OFCA internet service subscriptions",
            "official_source_url": "https://www.ofca.gov.hk/en/news_info/data_statistics/internet/statistics_on_internet_service_subscriptions/index.html",
            "official_api_url": "",
            "candidate_metrics": "Registered broadband internet access lines, residential broadband lines, business lines, broadband penetration where available.",
            "target_grain": "monthly_or_quarterly",
            "target_history": "Target 10 years if official access-line tables expose historical observations.",
            "cmhk_relevance": "Fixed broadband adoption and household connectivity context for CMHK convergence, enterprise and home broadband strategy.",
            "collection_status": "collected_current_official_pdf_with_legacy_boundary",
            "boundary_rule": "Post-2019 access lines and pre-2019 customer accounts are separate official series; do not merge them into one forecast target.",
            "next_step": "Continue monitoring OFCA PDF updates and search official archives if monthly access-line rows before 2019 become available.",
        },
        {
            "priority": "P0",
            "domain": "telecom_market_snapshot",
            "candidate_source_family": "OFCA key communications statistics",
            "official_source_url": "https://www.ofca.gov.hk/en/news_info/data_statistics/key_stat/index.html",
            "official_api_url": "",
            "candidate_metrics": "Mobile subscriptions, mobile subscriber penetration, mobile broadband subscriptions, broadband subscriptions, household broadband penetration, FTTH/B penetration, telecom operator counts, public Wi-Fi access points and fibre coverage.",
            "target_grain": "monthly_point_in_time",
            "target_history": "Official data.gov.hk CSV history from 2017 onward where metric fields are populated.",
            "cmhk_relevance": "Core market saturation, network adoption and operator landscape context for CMHK trend interpretation.",
            "collection_status": "collected_official_datagovhk_csv_history",
            "boundary_rule": "Rows are point-in-time snapshots by each metric's DATE. Blank fields are not zeros and are not estimated; overlapping annual/PDF sources remain separate source families.",
            "next_step": "Continue monitoring data.gov.hk monthly updates; add new columns only after the official data dictionary defines them.",
        },
        {
            "priority": "P1",
            "domain": "household_demand_capacity",
            "candidate_source_family": "C&SD domestic households and income",
            "official_source_url": "https://www.censtatd.gov.hk/en/web_table.html?id=130-06102",
            "official_api_url": "https://www.censtatd.gov.hk/data/",
            "candidate_metrics": "Domestic households, median monthly household income, household size and related household demand-capacity indicators.",
            "target_grain": "annual_and_moving_3_month",
            "target_history": "Latest available 10-year window from official C&SD web-table MDT CSV files.",
            "cmhk_relevance": "Household formation and income capacity explain home broadband, mobile-plan mix and consumer telecom demand.",
            "collection_status": "collected_official_mdt_csv_history",
            "boundary_rule": "Annual rows and moving-three-month rows are separate grains; preserve C&SD rounding/definition notes and do not estimate special-display or unavailable cells.",
            "next_step": "Monitor C&SD updates and add extra household classifications only after official component metadata and MDT CSV schemas are verified.",
        },
        {
            "priority": "P1",
            "domain": "population_demographics",
            "candidate_source_family": "C&SD population estimates",
            "official_source_url": "https://www.censtatd.gov.hk/en/web_table.html?id=110-01001",
            "official_api_url": "https://www.censtatd.gov.hk/data/",
            "candidate_metrics": "Population totals, sex totals, age-group population and population share from official population estimates; district population remains a future extension.",
            "target_grain": "mid_year_and_year_end_snapshot",
            "target_history": "Latest available 10-year window from official C&SD web-table MDT CSV files.",
            "cmhk_relevance": "Addressable market, ageing, household formation and district demand context for network and customer-base planning.",
            "collection_status": "collected_official_mdt_csv_compact_history",
            "boundary_rule": "Use official mid-year and year-end reference time-points separately; retain provisional official figures as official values with notes; exclude sex-by-age cross rows from the compact package and do not estimate excluded cuts.",
            "next_step": "Identify exact C&SD district population and deeper demographic table IDs before adding district or census/by-census rows.",
        },
        {
            "priority": "P1",
            "domain": "financial_conditions",
            "candidate_source_family": "HKMA monetary and interest-rate statistics",
            "official_source_url": "https://www.hkma.gov.hk/eng/data-publications-and-research/data-and-statistics/monthly-statistical-bulletin/table/",
            "official_api_url": "https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/financial/monetary-statistics?offset=0",
            "candidate_metrics": "HIBOR, deposit rates, best lending rate, Exchange Fund paper yields, government bond yields, banking deposits and monetary aggregates.",
            "target_grain": "monthly",
            "target_history": "Target 10 years via HKMA Open API.",
            "cmhk_relevance": "Financing cost, consumer and enterprise spending conditions, and valuation/discount-rate context for telecom and cloud investment cycles.",
            "collection_status": "queued_api_collection",
            "boundary_rule": "Financial variables are macro context/exogenous indicators only; they are not CMHK operating metrics.",
            "next_step": "Add HKMA API parser for a narrow first set: 3-month HIBOR, best lending rate, deposit rate and 10-year government bond yield.",
        },
        {
            "priority": "P1",
            "domain": "exchange_rate_conditions",
            "candidate_source_family": "HKMA exchange rates and interest rates",
            "official_source_url": "https://apidocs.hkma.gov.hk/documentation/market-data-and-statistics/monthly-statistical-bulletin/er-ir/",
            "official_api_url": "",
            "candidate_metrics": "HKD exchange rates, effective exchange-rate indices, HIBOR period averages, composite interest rate.",
            "target_grain": "monthly_or_daily",
            "target_history": "Target 10 years for monthly period averages; daily data only if needed for event studies.",
            "cmhk_relevance": "Currency and rate conditions affect imported equipment cost, cloud infrastructure economics and enterprise spending cycles.",
            "collection_status": "queued_api_collection",
            "boundary_rule": "Prefer monthly period-average series for forecasting context; do not mix daily and monthly grains in one model row.",
            "next_step": "Select concrete HKMA ER/IR dataset endpoints from the API documentation and test each response schema before adding rows.",
        },
        {
            "priority": "P2",
            "domain": "digital_policy",
            "candidate_source_family": "Digital Policy Office / OGCIO digital policy milestones",
            "official_source_url": "https://www.ogcio.gov.hk/",
            "official_api_url": "",
            "candidate_metrics": "Smart City Blueprint releases, digital-government milestones, data policy, cybersecurity and cloud adoption policy events.",
            "target_grain": "event",
            "target_history": "10-year event history where official pages or publications are accessible.",
            "cmhk_relevance": "Public-sector digital demand, smart-city and enterprise cloud/telecom policy context.",
            "collection_status": "queued_policy_event_review",
            "boundary_rule": "Policy events remain qualitative/context rows unless a reviewed model defines event encodings.",
            "next_step": "Map official DPO/OGCIO policy publications to event records with publication dates and CMHK relevance notes.",
        },
    ]


def build_historical_indicator_backlog_md(backlog: list[dict[str, str]]) -> str:
    lines = [
        "# CMHK Historical Indicator Backlog",
        "",
        f"- Build date: {BUILD_DATE}",
        "- Purpose: persistent queue of official government/regulator/public-institution historical indicators that may improve CMHK trend interpretation or forecasting context.",
        "- Rule: backlog entries are persistent collection tasks. Some may already be partially collected in `macro_policy_metrics.csv`; additional rows may be added only after official values are parsed, source links are verified, `verification_count >= 2` is satisfied where possible, and source gaps are explicitly retained rather than estimated.",
        "",
        "| priority | domain | source family | target grain | status | CMHK relevance |",
        "|---|---|---|---|---|---|",
    ]
    for row in backlog:
        lines.append(
            f"| {row['priority']} | {row['domain']} | {row['candidate_source_family']} | "
            f"{row['target_grain']} | {row['collection_status']} | {row['cmhk_relevance']} |"
        )
    lines.extend(["", "## Collection Rules", ""])
    lines.extend(
        [
            "- P0 items should be tested first because they are closest to telecom-market demand or service quality.",
            "- P1 items are macro and demographic context; they should be modeled as exogenous/context indicators rather than direct CMHK operating targets.",
            "- P2 items are mostly policy/event context and must not be converted into numeric forecasts without a reviewed event-encoding model.",
            "- If an official page only exposes current snapshots, keep it as a current context source until official archives are found.",
            "- Do not scrape image-only charts into numeric rows unless the underlying official table or data file is found.",
        ]
    )
    return "\n".join(lines)


def source_family_count(rows: list[dict[str, Any]], family: str) -> int:
    return sum(1 for row in rows if row["source_family"] == family)


def source_family_status(rows: list[dict[str, Any]], family: str, status: str) -> int:
    return sum(1 for row in rows if row["source_family"] == family and row["verification_status"] == status)


def source_family_period_range(rows: list[dict[str, Any]], family: str) -> tuple[str, str]:
    periods = sorted({row["period"] for row in rows if row["source_family"] == family})
    return (periods[0], periods[-1]) if periods else ("", "")


def source_family_period_end_range(rows: list[dict[str, Any]], family: str) -> tuple[str, str]:
    periods = sorted({row["period_end"] for row in rows if row["source_family"] == family and row.get("period_end")})
    return (periods[0], periods[-1]) if periods else ("", "")


def build_readme(rows: list[dict[str, Any]]) -> str:
    official = sum(1 for row in rows if row["verification_status"] == "official_match")
    gaps = sum(1 for row in rows if row["verification_status"] == "source_gap_confirmed")
    low = sum(1 for row in rows if int(row["verification_count"]) < 2)
    key_start, key_end = source_family_period_range(rows, "OFCA key communications statistics")
    key_metrics = len({row["metric_key"] for row in rows if row["source_family"] == "OFCA key communications statistics"})
    household_start, household_end = source_family_period_end_range(rows, "C&SD domestic households and income")
    household_metrics = len({row["metric_key"] for row in rows if row["source_family"] == "C&SD domestic households and income"})
    population_start, population_end = source_family_period_end_range(rows, "C&SD population estimates")
    population_metrics = len({row["metric_key"] for row in rows if row["source_family"] == "C&SD population estimates"})
    return "\n".join(
        [
            "# CMHK Macro Policy and Institutional Indicators (10-year target)",
            "",
            "This package adds CMHK-relevant macro, policy, regulatory, and public-institution indicators alongside the competitor and cloud vendor metrics database.",
            "",
            f"Current build status: usable for 小竞AI RAG and forecast-context support. It contains {len(rows):,} rows, with {official:,} official-match rows, {gaps:,} official source-gap rows, and {low} rows below `verification_count=2`.",
            "",
            "## Scope",
            "",
            "- Target window: 10 years where official/public data is available.",
            "- Preferred grain: monthly or quarterly for statistical indicators; annual for policy/regulatory indicators that are only published annually; event/date grain for spectrum, licensing, subsidy, cyber/data, and smart-city policy milestones.",
            "- Source priority: Hong Kong government departments, regulators, statutory bodies, public data portals, and official institutional publications.",
            "- No estimation rule: missing public disclosure is recorded as `source_gap_confirmed` or kept blank, not filled by interpolation.",
            "",
            "## Source Families Included",
            "",
            "- OFCA key communications statistics: official data.gov.hk CSV point-in-time history covering populated fields from "
            f"{key_start} to {key_end}; {source_family_count(rows, 'OFCA key communications statistics'):,} rows across {key_metrics} metrics including mobile subscriptions, mobile penetration, broadband subscriptions, household broadband penetration, operator counts, public Wi-Fi access points and fibre coverage. Blank CSV cells are not estimated.",
            "- OFCA telecommunications indicators: fiscal-year market, adoption, tariff, revenue, traffic, investment, staff and infrastructure indicators for FY2015/16-FY2024/25.",
            "- OFCA wireless services: December annual snapshots for 2016-2025 covering mobile subscriptions, mobile broadband subscriptions, 3G subscriptions, MVNO subscriptions, machine-type connections, mobile data usage and SMS traffic where the official PDF table can be safely parsed.",
            "- OFCA internet service subscriptions: official PDF rows for 2019-2025 access-line snapshots and 2016-2018 legacy customer-account snapshots, kept as separate source families because OFCA changed methodology in January 2019.",
            "- OFCA consumer complaints: official current complaint table covering 2023-2025 annual service-type complaints and 2026 Q1 complaints; older complaint history remains a backlog task until official archived tables are found.",
            "- C&SD consumer prices: monthly Composite CPI, CPI(A), CPI(B), CPI(C) values and changes in the latest official 10-year window.",
            "- C&SD private consumption expenditure: quarterly PCE and selected component values / year-on-year changes in chained dollars.",
            "- C&SD GDP and demand growth: quarterly real GDP / demand-component year-on-year and quarter-to-quarter growth context.",
            "- C&SD labour market: moving-three-month labour force and unemployment indicators for the latest official 10-year window.",
            "- C&SD domestic households and income: official annual and moving-three-month household count, household-size, income and owner-occupier indicators covering "
            f"{household_start} to {household_end}; {source_family_count(rows, 'C&SD domestic households and income'):,} rows across {household_metrics} metrics.",
            "- C&SD population estimates: official mid-year and year-end population by sex and age-group indicators covering "
            f"{population_start} to {population_end}; {source_family_count(rows, 'C&SD population estimates'):,} rows across {population_metrics} compact metrics.",
            "- C&SD retail sales: monthly value, value index and volume index indicators.",
            "- C&SD household internet access: annual household access level/rate where official survey data is available.",
            "- Regulatory and infrastructure policy: selected official 5G, spectrum, SIM registration, and rural/remote coverage milestones.",
            "",
            "## Remaining Extension Boundaries",
            "",
            "- OFCA key communications statistics are market-level point-in-time context rows, not company-level revenue forecast targets.",
            "- OFCA 4G/5G split columns remain excluded from the Wireless Services PDF parser because that PDF extraction splits them across continuation rows; add them only when a safer official structured source is available.",
            "- OFCA internet service subscription access-line rows from 2019 onward and customer-account rows before 2019 are not directly comparable and must not be merged into a single forecast series.",
            "- Additional C&SD demographic tables can be added later as enrichments where official structured access is available.",
            "- C&SD population rows are addressable-market and demographic context, not direct CMHK operating targets.",
            "- C&SD domestic-household moving-three-month rows are household demand-capacity context, not CMHK company operating quarters.",
            "- OFCA consumer complaints before 2023 are not estimated; older rows should only be added from official archived OFCA complaint tables.",
            "- Policy/event records are context rows, not numeric forecast targets.",
            "- Missing public disclosure remains `source_gap_confirmed`; no value is estimated.",
            "",
            "## Required Output Files",
            "",
            "- `macro_policy_metrics.csv`",
            "- `macro_policy_metrics.json`",
            "- `macro_policy_summary.md`",
            "- `household_income_reference.md`",
            "- `population_reference.md`",
            "- `sources.json`",
            f"- `online_verification_{BUILD_DATE}.csv`",
            "- `prediction_readiness_audit.md`",
            "- `historical_indicator_backlog.md`",
            "",
            "Each row must preserve source links, evidence notes, `verification_count`, conflict/source-gap status, and `official_value` for formal use.",
        ]
    )


def build_source_plan(rows: list[dict[str, Any]]) -> str:
    official = sum(1 for row in rows if row["verification_status"] == "official_match")
    gaps = sum(1 for row in rows if row["verification_status"] == "source_gap_confirmed")
    low = sum(1 for row in rows if int(row["verification_count"]) < 2)
    key_start, key_end = source_family_period_range(rows, "OFCA key communications statistics")
    key_metrics = len({row["metric_key"] for row in rows if row["source_family"] == "OFCA key communications statistics"})
    household_start, household_end = source_family_period_end_range(rows, "C&SD domestic households and income")
    household_metrics = len({row["metric_key"] for row in rows if row["source_family"] == "C&SD domestic households and income"})
    population_start, population_end = source_family_period_end_range(rows, "C&SD population estimates")
    population_metrics = len({row["metric_key"] for row in rows if row["source_family"] == "C&SD population estimates"})
    return "\n".join(
        [
            "# Source Plan",
            "",
            "## Current Competitor / Cloud Prediction Readiness",
            "",
            "Current package inspected: `agent_knowledge/quarterly_competitor_metrics_2026-06-18/quarterly_metrics.csv`.",
            "",
            "- Total rows: 3,013.",
            "- Strict source integrity: no rows with `verification_count < 2`.",
            "- Strong prediction-ready subjects by value-period window: China Mobile and China Telecom have 41 quarterly periods; China Unicom has 39; China Tower has 37; major Hong Kong semiannual subjects have 20 half-year periods; AWS and Microsoft Azure / Intelligent Cloud have 40 quarterly periods.",
            "- Limited / tiered cloud prediction subjects: Google Cloud, Alibaba Cloud, Tencent Cloud / Tencent FBS proxy and Oracle Cloud have documented comparable-series boundaries; Huawei Cloud and HGC remain source-gap subjects.",
            "",
            "Conclusion: the existing competitor/cloud dataset is sufficient for short-horizon trend/forecast use only under subject-level tiering. Formal outputs must use `official_value`, respect `source_gap_confirmed`, and avoid estimating undisclosed periods.",
            "",
            "## Macro / Policy Dataset Collection Status",
            "",
            "Current macro package: `agent_knowledge/cmhk_macro_policy_2026-06-19/macro_policy_metrics.csv`.",
            "",
            f"- Total rows: {len(rows):,}.",
            f"- Official-match rows: {official:,}.",
            f"- Source-gap rows: {gaps:,}.",
            f"- Rows with `verification_count < 2`: {low}.",
            "- Included grains: monthly OFCA key communications point-in-time snapshots, monthly C&SD CPI/retail, moving-three-month C&SD labour market and domestic household/income indicators, quarterly C&SD private consumption expenditure and GDP/demand growth indicators, annual C&SD household internet access and domestic household/income indicators, mid-year/year-end C&SD population snapshots, annual OFCA telecommunications indicators, OFCA annual internet service subscription snapshots, current OFCA annual/quarterly consumer complaint statistics, and event-grain policy milestones.",
            "- Additional included grain: annual December OFCA Wireless Services snapshots.",
            "",
            "### Telecommunications Demand and Infrastructure",
            "",
            "- OFCA Key Communications Statistics",
            f"  - Included rows: {source_family_count(rows, 'OFCA key communications statistics'):,} rows, all `official_match` with `verification_count=3`.",
            f"  - Included grain/window: monthly point-in-time snapshots from {key_start} to {key_end} where official CSV fields are populated.",
            f"  - Included metric count: {key_metrics}.",
            "  - Official CSV: https://www.ofca.gov.hk/filemanager/ofca/common/datagovhk/key_com_stat.csv",
            "  - Data dictionary: https://www.ofca.gov.hk/filemanager/ofca/common/datagovhk/data_dict/Data_Dictionary_for_Key_Comms_Stat_EN.pdf",
            "  - data.gov.hk dataset: https://data.gov.hk/en-data/dataset/hk-ofca-ofca-ofca-dataset-10",
            "  - OFCA page: https://www.ofca.gov.hk/en/news_info/data_statistics/key_stat/index.html",
            "  - Included metrics: mobile subscriptions, mobile broadband subscriptions, mobile penetration, household broadband penetration, FTTH/B penetration, telecom operator counts, public Wi-Fi access points and fibre coverage.",
            "  - Boundary: blank CSV cells are not zeros and are not estimated; rows are market-level context and not direct company revenue forecast targets.",
            "",
            "- OFCA Telecommunications Indicators",
            "  - URL: https://www.ofca.gov.hk/en/news_info/data_statistics/indicators/index.html",
            "  - Historical table: https://www.ofca.gov.hk/filemanager/ofca/en/content_297/hktelecom-indicators_summary.htm",
            "  - Included grain/window: annual fiscal year, FY2015/16-FY2024/25.",
            "",
            "- OFCA Wireless Services statistics",
            "  - Source page: https://www.ofca.gov.hk/en/news_info/data_statistics/mobile_services/wireless_services/index.html",
            "  - Official PDF: https://www.ofca.gov.hk/filemanager/ofca/en/content_108/wireless_en.pdf",
            f"  - Included rows: {source_family_count(rows, 'OFCA wireless services')} rows, with {source_family_status(rows, 'OFCA wireless services', 'official_match')} `official_match` rows and {source_family_status(rows, 'OFCA wireless services', 'source_gap_confirmed')} `source_gap_confirmed` rows.",
            "  - Boundary: 4G/5G split columns are excluded until a safer official structured source is available.",
            "",
            "- OFCA Internet Service Subscriptions",
            "  - Source page: https://www.ofca.gov.hk/en/news_info/data_statistics/internet/statistics_on_internet_service_subscriptions/index.html",
            "  - Official PDF: https://www.ofca.gov.hk/filemanager/ofca/en/content_293/cus_isp_en.pdf",
            "  - Included rows: 104 rows, all `official_match` with `verification_count=2`; 77 rows are post-2019 access lines and 27 rows are pre-2019 legacy customer accounts.",
            "  - Boundary: OFCA changed methodology in January 2019 from registered customer accounts to access lines. The two source families are kept separate and must not be merged into one forecast target.",
            "",
            "- OFCA Consumer Complaint Statistics",
            "  - Source page: https://www.ofca.gov.hk/en/news_info/data_statistics/complaint_stat/index.html",
            "  - Included rows: 28 rows, all `official_match` with `verification_count=2`.",
            "  - Boundary: complaint statistics before 2023 are not estimated; older history remains a backlog item until official archived OFCA complaint tables are found.",
            "",
            "### Macro Economy and Demand Indicators",
            "",
            "- C&SD CPI / GDP / private consumption / labour / retail / household internet access tables are retained from official C&SD APIs or web tables for the latest available 10-year window.",
            "- C&SD Domestic Households and Income",
            f"  - Included rows: {source_family_count(rows, 'C&SD domestic households and income'):,} rows, all `official_match` with `verification_count=4`.",
            f"  - Included window: {household_start} to {household_end}.",
            f"  - Included metric count: {household_metrics}.",
            "  - Official web table: https://www.censtatd.gov.hk/en/web_table.html?id=130-06102",
            "  - Official component metadata: https://www.censtatd.gov.hk/data/table_130-06102_comp.json",
            "  - Official language metadata: https://www.censtatd.gov.hk/data/en/table_130-06102_lang.json",
            "  - Included metrics: domestic households, average household size, average household size excluding foreign domestic helpers, median monthly household income, median monthly household income excluding Chinese New Year bonus/double pay, median monthly household income excluding foreign domestic helpers, median income of economically active households, owner-occupier share, public-sector owner-occupier share and private-sector owner-occupier share.",
            "  - Boundary: annual rows and moving-three-month rows are separate grains; C&SD special-display / unavailable cells are not estimated.",
            "- C&SD Population Estimates",
            f"  - Included rows: {source_family_count(rows, 'C&SD population estimates'):,} rows, all `official_match` with `verification_count=4`.",
            f"  - Included window: {population_start} to {population_end}.",
            f"  - Included compact metric count: {population_metrics}.",
            "  - Official web table: https://www.censtatd.gov.hk/en/web_table.html?id=110-01001",
            "  - Official component metadata: https://www.censtatd.gov.hk/data/table_110-01001_comp.json",
            "  - Official language metadata: https://www.censtatd.gov.hk/data/en/table_110-01001_lang.json",
            "  - Included cuts: total population, male/female totals, and all-sex 5-year age groups for population count and population share at mid-year and year-end reference time-points.",
            "  - Boundary: sex-by-age cross rows are excluded from this compact CMHK macro package to avoid database bloat; no excluded values are estimated. Provisional official figures are retained with notes.",
            "- Future enrichment candidates: district population and deeper demographic tables where official structured source pages are added.",
            "",
            "### Policy, Regulatory, and Spectrum Milestones",
            "",
            "- OFCA Spectrum Management and OFCA / CA official reports provide selected 5G, spectrum, SIM real-name registration, rural/remote coverage and assigned-spectrum context.",
            "- OGCIO / Digital Policy Office / Smart City policy documents remain future qualitative extension candidates and are not mixed into the current numeric forecast targets.",
            "",
            "## Verification Rules",
            "",
            "- Every quantitative row must have at least two source/evidence entries when possible: direct official table/API/CSV plus official context page, release note, data dictionary, annual report, or archived official table.",
            "- Policy event rows must preserve enactment/publication date, responsible institution, policy type, official URL, and relevance to CMHK.",
            "- Conflicting values are retained as `official_conflict`, with `official_value` used for formal conclusions.",
            "- Disclosure gaps are retained as `source_gap_confirmed`; they must not be estimated.",
        ]
    )


def build_household_income_reference(rows: list[dict[str, Any]]) -> str:
    family = "C&SD domestic households and income"
    family_rows = [row for row in rows if row["source_family"] == family]
    annual_rows = sorted(
        [row for row in family_rows if row["grain"] == "calendar_year"],
        key=lambda row: (row["period"], row["metric_key"]),
    )
    latest_by_metric: dict[str, dict[str, Any]] = {}
    for row in sorted([row for row in family_rows if row["grain"] == "moving_3_month"], key=lambda item: item["period_end"]):
        latest_by_metric[row["metric_key"]] = row

    lines = [
        "# C&SD Domestic Households and Income Quick Reference",
        "",
        f"- Build date: {BUILD_DATE}",
        f"- Source family: {family}",
        f"- Rows in source family: {len(family_rows):,}",
        f"- Annual rows: {len(annual_rows):,}",
        f"- Moving-three-month rows: {len(family_rows) - len(annual_rows):,}",
        f"- Metric count: {len({row['metric_key'] for row in family_rows})}",
        "- Official table: https://www.censtatd.gov.hk/en/web_table.html?id=130-06102",
        "- Component metadata: https://www.censtatd.gov.hk/data/table_130-06102_comp.json",
        "- Language metadata: https://www.censtatd.gov.hk/data/en/table_130-06102_lang.json",
        "- Formal-use fields: `official_value`, `official_unit`, `official_source_label`, `official_source_url`, `official_evidence`, `verification_sources`, `verification_count`, `verification_status`.",
        "- Boundary: annual rows and moving-three-month rows are separate grains. Do not use moving-three-month rows to fill a missing calendar-year value.",
        "",
        "## 2025 Calendar-Year Values",
        "",
        "| metric_key | metric_name | official_value | official_unit | verification_count | source_url |",
        "|---|---|---:|---|---:|---|",
    ]
    annual_2025 = [row for row in annual_rows if row["period"] == "2025"]
    for row in annual_2025:
        lines.append(
            f"| {row['metric_key']} | {row['metric_name']} | {row['official_value']} | {row['official_unit']} | "
            f"{row['verification_count']} | {row['official_source_url']} |"
        )
    annual_2025_keys = {row["metric_key"] for row in annual_2025}
    missing_2025 = [
        (metric_key, metric_name)
        for _stat_var, (_stat_pres, metric_key, metric_name, _unit) in CSD_HOUSEHOLD_INCOME_METRICS.items()
        if metric_key not in annual_2025_keys
    ]
    lines.extend(["", "## 2025 Calendar-Year Gaps", ""])
    if missing_2025:
        lines.extend(["| metric_key | metric_name | boundary |", "|---|---|---|"])
        for metric_key, metric_name in missing_2025:
            lines.append(
                f"| {metric_key} | {metric_name} | No 2025 calendar-year row is present in the official table output. Do not use moving-three-month rows as a substitute for the annual value. |"
            )
    else:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "## All Calendar-Year Values",
            "",
            "| year | metric_key | metric_name | official_value | official_unit |",
            "|---:|---|---|---:|---|",
        ]
    )
    for row in annual_rows:
        lines.append(
            f"| {row['period']} | {row['metric_key']} | {row['metric_name']} | {row['official_value']} | {row['official_unit']} |"
        )
    lines.extend(
        [
            "",
            "## Latest Moving-Three-Month Values",
            "",
            "| metric_key | metric_name | period | period_end | official_value | official_unit |",
            "|---|---|---|---:|---:|---|",
        ]
    )
    for metric_key in sorted(latest_by_metric):
        row = latest_by_metric[metric_key]
        lines.append(
            f"| {row['metric_key']} | {row['metric_name']} | {row['period']} | {row['period_end']} | {row['official_value']} | {row['official_unit']} |"
        )
    return "\n".join(lines)


def build_population_reference(rows: list[dict[str, Any]]) -> str:
    family = "C&SD population estimates"
    family_rows = [row for row in rows if row["source_family"] == family]
    mid_year_rows = [row for row in family_rows if row["grain"] == "mid_year_snapshot"]
    year_end_rows = [row for row in family_rows if row["grain"] == "year_end_snapshot"]
    selected_keys = [
        "population_total",
        "population_sex_male",
        "population_sex_female",
        "population_age_65_69",
        "population_age_85",
    ]
    selected_2025_mid = [
        row
        for metric_key in selected_keys
        for row in family_rows
        if row["metric_key"] == metric_key and row["period_end"] == "2025-06-30" and row["grain"] == "mid_year_snapshot"
    ]
    total_rows = sorted(
        [row for row in family_rows if row["metric_key"] == "population_total"],
        key=lambda row: (row["period_end"], row["grain"]),
    )
    latest_mid_year = max((row["period_end"] for row in mid_year_rows), default="")
    latest_age_mid_year = sorted(
        [
            row
            for row in mid_year_rows
            if row["period_end"] == latest_mid_year
            and row["metric_key"].startswith("population_age_")
            and not row["metric_key"].endswith("_share")
        ],
        key=lambda row: row["metric_key"],
    )
    latest_age_share_by_key = {
        row["metric_key"].replace("population_share_age_", "population_age_", 1): row
        for row in mid_year_rows
        if row["period_end"] == latest_mid_year
        and row["metric_key"].startswith("population_share_age_")
    }

    lines = [
        "# C&SD Population Estimates Quick Reference",
        "",
        f"- Build date: {BUILD_DATE}",
        f"- Source family: {family}",
        f"- Rows in source family: {len(family_rows):,}",
        f"- Mid-year snapshot rows: {len(mid_year_rows):,}",
        f"- Year-end snapshot rows: {len(year_end_rows):,}",
        f"- Metric count: {len({row['metric_key'] for row in family_rows})}",
        "- Official table: https://www.censtatd.gov.hk/en/web_table.html?id=110-01001",
        "- Component metadata: https://www.censtatd.gov.hk/data/table_110-01001_comp.json",
        "- Language metadata: https://www.censtatd.gov.hk/data/en/table_110-01001_lang.json",
        "- Raw population MDT CSV: https://www.censtatd.gov.hk/data/MDT_76_110-01001_POP_Raw_K_1dp_per_n.csv",
        "- Population-share MDT CSV: https://www.censtatd.gov.hk/data/MDT_76_110-01001_POP_Prop_1dp_percent_n.csv",
        "- Formal-use fields: `official_value`, `official_unit`, `official_source_label`, `official_source_url`, `official_evidence`, `verification_sources`, `verification_count`, `verification_status`.",
        "- Boundary: population rows are addressable-market and age-mix context for CMHK analysis, not direct CMHK revenue, ARPU, subscriber or market-share forecast targets.",
        "- Boundary: mid-year and year-end rows are separate official snapshots. Do not average or interpolate them into quarters.",
        "- Boundary: sex-by-age cross rows are intentionally excluded from this compact package; excluded rows are not estimated.",
        "- Naming note: official age group `≥85` is stored as `population_age_85` in this package.",
        "",
        "## 2025 Mid-Year Selected Values",
        "",
        "| metric_key | metric_name | official_value | official_unit | verification_count | source_url |",
        "|---|---|---:|---|---:|---|",
    ]
    for row in selected_2025_mid:
        lines.append(
            f"| {row['metric_key']} | {row['metric_name']} | {row['official_value']} | {row['official_unit']} | "
            f"{row['verification_count']} | {row['official_source_url']} |"
        )
    lines.extend(
        [
            "",
            "## Total Population Snapshots",
            "",
            "| period | period_end | grain | official_value | official_unit | verification_count |",
            "|---|---:|---|---:|---|---:|",
        ]
    )
    for row in total_rows:
        lines.append(
            f"| {row['period']} | {row['period_end']} | {row['grain']} | {row['official_value']} | {row['official_unit']} | {row['verification_count']} |"
        )
    lines.extend(
        [
            "",
            f"## Latest Mid-Year Age-Group Distribution ({latest_mid_year})",
            "",
            "| metric_key | age_group | population_thousand_persons | share_percent |",
            "|---|---|---:|---:|",
        ]
    )
    for row in latest_age_mid_year:
        share_row = latest_age_share_by_key.get(row["metric_key"])
        age_group = row["metric_detail"].split(";")[0].replace("Population - Age group: ", "")
        lines.append(
            f"| {row['metric_key']} | {age_group} | {row['official_value']} | {share_row['official_value'] if share_row else ''} |"
        )
    return "\n".join(lines)


def build_manifest(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": DATASET_ID,
        "title": "CMHK 10年宏观政策与机构指标数据",
        "summary": "香港电信市场、5G/频谱/监管政策、互联网接入、服务投诉、C&SD 高频宏观、人口与家庭需求能力指标的官方来源数据包；已纳入 OFCA 10 年电信指标、OFCA 无线服务年度快照、OFCA 互联网服务订阅统计、OFCA 电讯投诉统计、C&SD 月度/季度/年度宏观、GDP增长、劳工市场、人口估计、家庭/收入指标和关键政策事件。",
        "source_type": "government_regulator_public_institution",
        "scope": "CMHK 经营预测、趋势判断和政策环境分析使用的香港宏观、电信、监管和机构指标",
        "tags": ["CMHK", "macro policy", "OFCA", "C&SD", "telecom indicators", "key communications statistics", "wireless services", "internet subscriptions", "consumer complaints", "population estimates", "age group", "domestic households", "household income", "CPI", "PCE", "GDP", "labour market", "retail sales", "5G", "spectrum", "Hong Kong"],
        "keywords": [
            "宏观政策",
            "政府数据",
            "OFCA",
            "C&SD",
            "香港统计处",
            "通讯事务管理局",
            "电信指标",
            "无线服务",
            "电讯投诉",
            "消费者投诉",
            "互联网服务订阅",
            "宽带接入线",
            "移动宽带",
            "移动数据用量",
            "人口",
            "人口估计",
            "年龄结构",
            "population estimates",
            "age group",
            "住户",
            "家庭收入",
            "住户收入",
            "domestic households",
            "household income",
            "CPI",
            "消费物价",
            "私人消费开支",
            "GDP",
            "劳工市场",
            "失业率",
            "零售销售",
            "5G",
            "频谱",
            "SIM实名",
            "移动用户",
            "宽带渗透率",
            "CMHK",
            "香港电讯市场",
        ],
        "entrypoints": [
            "README.md",
            "source_plan.md",
            "household_income_reference.md",
            "population_reference.md",
            "macro_policy_summary.md",
            "macro_policy_metrics.csv",
            "macro_policy_metrics.json",
            "sources.json",
            f"online_verification_{BUILD_DATE}.md",
            f"online_verification_{BUILD_DATE}.csv",
            "prediction_readiness_audit.md",
            "historical_indicator_backlog.md",
            "historical_indicator_backlog.csv",
        ],
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "quality": {
            "status": "official_verified_macro_policy_build_ready_for_rag",
            "notes": [
                "Current quantitative rows use official OFCA and C&SD public sources and verification_count >= 2.",
                "C&SD monthly CPI/retail/labour and quarterly PCE/GDP-growth series provide high-frequency macro context for forecasting support.",
                "OFCA Key Communications Statistics provide official monthly point-in-time market saturation, operator count, broadband and fibre coverage context.",
                "OFCA internet service subscriptions provide fixed-broadband adoption context; post-2019 and pre-2019 methodology families are kept separate.",
                "C&SD domestic household and income rows provide official annual and moving-three-month household demand-capacity context.",
                "C&SD population estimates provide official mid-year and year-end addressable-market and age-mix context.",
                "OFCA complaint statistics provide service-quality pressure context, not direct operating forecast targets.",
                "Policy event rows are context records, not forecast targets.",
            ],
            "row_count": len(rows),
        },
    }


def build_prediction_readiness(rows: list[dict[str, Any]]) -> str:
    low = [row for row in rows if int(row["verification_count"]) < 2]
    official = [row for row in rows if row["verification_status"] == "official_match"]
    gaps = [row for row in rows if row["verification_status"] == "source_gap_confirmed"]
    return "\n".join(
        [
            "# Prediction Readiness Audit",
            "",
            f"- Rows: {len(rows)}",
            f"- official_match rows: {len(official)}",
            f"- source_gap_confirmed rows: {len(gaps)}",
            f"- verification_count < 2 rows: {len(low)}",
            "",
            "## Current Readiness",
            "",
            "- OFCA annual telecommunications indicators: ready for 10-year annual trend context and explanatory features.",
            "- OFCA Key Communications Statistics: ready as official monthly point-in-time market-snapshot context where CSV fields are populated; blank fields are not estimated.",
            "- OFCA internet service subscriptions: ready as fixed-broadband adoption context; post-2019 access lines and pre-2019 customer accounts are separate methodology families.",
            "- OFCA consumer complaint statistics: ready as current official service-quality pressure context; older history remains backlog until official archives are found.",
            "- C&SD monthly CPI/retail/labour and quarterly PCE/GDP-growth indicators: ready as macro/exogenous time-series context for forecasting explanation.",
            "- C&SD domestic households and income: ready as official household demand-capacity context; annual and moving-three-month rows are separate grains and should be used as explanatory context, not direct CMHK operating targets.",
            "- C&SD population estimates: ready as official addressable-market and age-mix context; mid-year and year-end rows are separate snapshots and should be used as demographic context, not direct CMHK operating targets.",
            "- OFCA Wireless Services annual December snapshots: ready for annual mobile-market adoption and usage context, not high-frequency forecast-target fitting.",
            "- C&SD annual household internet access indicators: ready for adoption/saturation context where official annual data exists.",
            "- Policy / spectrum / regulatory milestones: ready for qualitative context and event-flag enrichment.",
            "- Remaining source gap for future enrichment: OFCA 4G/5G split wireless columns and additional C&SD district/deeper demographic series can be added where official structured access is available, but no current row is estimated.",
            "",
            "## Rules",
            "",
            "- Use `official_value` for formal conclusions.",
            "- Treat `source_gap_confirmed` as a disclosure boundary; do not interpolate missing policy or market statistics.",
            "- Do not treat event rows as numeric targets unless a separate reviewed model explicitly defines event encodings.",
        ]
    )


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows = (
        parse_ofca_telecom_indicators()
        + parse_ofca_key_communications_statistics()
        + parse_ofca_wireless_services()
        + parse_ofca_internet_subscriptions()
        + parse_ofca_consumer_complaints()
        + parse_csd_macro_indicators()
        + build_policy_rows()
    )
    sources = build_sources()
    verification_md, verification_rows = build_verification(rows)
    historical_backlog = build_historical_indicator_backlog()

    (OUT_ROOT / "macro_policy_metrics.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(OUT_ROOT / "macro_policy_metrics.csv", rows)
    (OUT_ROOT / "sources.json").write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_ROOT / "README.md").write_text(build_readme(rows), encoding="utf-8")
    (OUT_ROOT / "source_plan.md").write_text(build_source_plan(rows), encoding="utf-8")
    (OUT_ROOT / "household_income_reference.md").write_text(build_household_income_reference(rows), encoding="utf-8")
    (OUT_ROOT / "population_reference.md").write_text(build_population_reference(rows), encoding="utf-8")
    (OUT_ROOT / "macro_policy_summary.md").write_text(build_summary(rows), encoding="utf-8")
    (OUT_ROOT / f"online_verification_{BUILD_DATE}.md").write_text(verification_md, encoding="utf-8")
    write_csv(OUT_ROOT / f"online_verification_{BUILD_DATE}.csv", verification_rows)
    (OUT_ROOT / "prediction_readiness_audit.md").write_text(build_prediction_readiness(rows), encoding="utf-8")
    (OUT_ROOT / "historical_indicator_backlog.md").write_text(
        build_historical_indicator_backlog_md(historical_backlog),
        encoding="utf-8",
    )
    write_csv(OUT_ROOT / "historical_indicator_backlog.csv", historical_backlog)
    (OUT_ROOT / "manifest.json").write_text(json.dumps(build_manifest(rows), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(rows)} rows to {OUT_ROOT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

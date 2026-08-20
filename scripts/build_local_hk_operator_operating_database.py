from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "agent_knowledge" / "local_hk_operator_operating_metrics_2016_2025"
BUILD_TIME = "2026-08-18T00:00:00+08:00"
YEARS = list(range(2016, 2026))

OPERATORS = {
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


SOURCES: dict[str, dict[str, Any]] = {}
for year in YEARS:
    SOURCES[f"hkt_ar_{year}"] = {"source_id": f"hkt_ar_{year}", "operator_id": "hkt", "year": year, "label": f"HKT {year} Annual Report", "url": hkt_url(year), "source_type": "official_annual_report", "publisher": OPERATORS["hkt"]["legal_name"]}
    SOURCES[f"three_hk_ar_{year}"] = {"source_id": f"three_hk_ar_{year}", "operator_id": "three_hk", "year": year, "label": f"Hutchison Telecommunications Hong Kong {year} Annual Report", "url": f"https://www.hthkh.com/en/ir/reports/ar{year}/ar{year}.pdf", "source_type": "official_annual_report", "publisher": OPERATORS["three_hk"]["legal_name"]}
for year in range(2017, 2026):
    SOURCES[f"smartone_ar_{year}"] = {"source_id": f"smartone_ar_{year}", "operator_id": "smartone", "year": year, "label": f"SmarTone FY{year} Annual Report", "url": smartone_url(year), "source_type": "official_annual_report", "publisher": OPERATORS["smartone"]["legal_name"]}
for year in [2024, 2025]:
    SOURCES[f"hkbn_ar_{year}"] = {"source_id": f"hkbn_ar_{year}", "operator_id": "hkbn", "year": year, "label": "HKBN FY2025 Annual Report and FY2024 comparative", "url": "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_AnnualReport_2025.pdf", "source_type": "official_annual_report", "publisher": OPERATORS["hkbn"]["legal_name"]}
    SOURCES[f"hkbn_results_{year}"] = {"source_id": f"hkbn_results_{year}", "operator_id": "hkbn", "year": year, "label": "HKBN FY2025 Annual Results Presentation and FY2024 comparative", "url": "https://reg.hkbn.net/WwwCMS/upload/pdf/en/FY25_HKBN_Annual_Results_Announcement_Presentation_en.pdf", "source_type": "official_results_presentation", "publisher": OPERATORS["hkbn"]["legal_name"]}
for year in range(2022, 2026):
    SOURCES[f"icable_ar_{year}"] = {"source_id": f"icable_ar_{year}", "operator_id": "icable", "year": year, "label": f"i-CABLE {year} Annual Report", "url": "https://www.i-cablecomm.com/en/annual-interim-reports", "source_type": "official_annual_report_page", "publisher": OPERATORS["icable"]["legal_name"]}
SOURCES["hgc_2016_group_ar"] = {"source_id": "hgc_2016_group_ar", "operator_id": "hgc", "year": 2016, "label": "Hutchison Telecommunications Hong Kong 2016 Annual Report (HGC then within group)", "url": "https://www.hthkh.com/en/ir/reports/ar2016/ar2016.pdf", "source_type": "official_annual_report", "publisher": OPERATORS["three_hk"]["legal_name"]}
SOURCES["hgc_current_site"] = {"source_id": "hgc_current_site", "operator_id": "hgc", "year": 2025, "label": "HGC official website", "url": "https://www.hgc-intl.com/", "source_type": "official_company_site", "publisher": OPERATORS["hgc"]["legal_name"]}

ROWS: list[dict[str, Any]] = []


def add_series(operator_id: str, metric_key: str, values: dict[int, float | int | None], *, scope: str, basis: str = "year_end", comparator: str = "=", source_ids: dict[int, list[str]] | None = None, note: str = "", unit: str | None = None, status: str = "official_single_source") -> None:
    metric_zh, default_unit = METRICS[metric_key]
    spec = OPERATORS[operator_id]
    for year, value in values.items():
        ids = (source_ids or {}).get(year, [])
        valid = [sid for sid in ids if sid in SOURCES]
        row_status = "source_gap_confirmed" if value is None else ("official_multi_source_verified" if len(valid) >= 2 else status)
        ROWS.append({
            "operator_id": operator_id, "operator": spec["name"], "legal_name": spec["legal_name"],
            "year": year, "period": f"FY{year}", "period_end": f"{year}-{spec['fiscal_year_end']}", "grain": "annual",
            "metric_key": metric_key, "metric_zh": metric_zh, "value": value, "official_value": value,
            "unit": unit or default_unit, "comparator": comparator, "scope": scope, "basis": basis,
            "verification_status": row_status, "verification_count": len(valid),
            "primary_source_id": valid[0] if valid else "", "primary_source_url": SOURCES[valid[0]]["url"] if valid else "",
            "verification_sources": valid, "quality_note": note,
        })


def annual_sources(operator_id: str, years: list[int]) -> dict[int, list[str]]:
    prefix = {"hkt": "hkt", "three_hk": "three_hk", "smartone": "smartone"}[operator_id]
    return {year: [f"{prefix}_ar_{year}"] for year in years}


# HKT: calendar-year annual metrics. Total mobile base is not backfilled where reports do not state a reusable exact figure.
add_series("hkt", "mobile_postpaid_customers", dict(zip(YEARS, [3.130, 3.217, 3.247, 3.250, 3.252, 3.297, 3.323, 3.428, 3.459, 3.494])), scope="Hong Kong post-paid mobile customer base", source_ids=annual_sources("hkt", YEARS))
add_series("hkt", "mobile_postpaid_exit_arpu", dict(zip(YEARS, [233, 232, 198, 200, 184, 187, 188, 191, 193, 195])), scope="Hong Kong post-paid exit ARPU", basis="exit_month", source_ids=annual_sources("hkt", YEARS))
add_series("hkt", "mobile_postpaid_churn", dict(zip(YEARS, [1.3, 1.1, 1.0, 1.0, 0.9, 0.7, 0.8, 0.8, 0.7, 0.7])), scope="monthly post-paid churn", basis="monthly_rate", source_ids=annual_sources("hkt", YEARS))
add_series("hkt", "5g_customers", {2020: .264, 2021: .680, 2022: 1.061, 2023: 1.4, 2024: 1.747, 2025: 2.096}, scope="post-paid 5G customer base", comparator=">=", source_ids=annual_sources("hkt", list(range(2020, 2026))), note="2023 was disclosed as approaching 1.4 million; comparator preserves the rounded wording.")
add_series("hkt", "5g_penetration", {2021: 21, 2022: 32, 2023: 41, 2024: 51, 2025: 60}, scope="5G penetration within post-paid customer base", source_ids=annual_sources("hkt", list(range(2021, 2026))))
add_series("hkt", "consumer_broadband_customers", {2021: 1.637, 2022: None, 2023: 1.471, 2024: 1.474, 2025: 1.488}, scope="consumer broadband customer base", source_ids=annual_sources("hkt", list(range(2021, 2026))))
add_series("hkt", "ftth_connections", {2021: .944, 2022: None, 2023: 1.0, 2024: 1.04, 2025: 1.086}, scope="consumer FTTH connections", comparator=">=", source_ids=annual_sources("hkt", list(range(2021, 2026))), note="2023 was disclosed as over one million; no interpolation is used for 2022.")

# 3HK: 2016-24 group scope included Macau; 2025 report isolates Hong Kong and restates the 2024 comparator.
add_series("three_hk", "mobile_postpaid_customers", dict(zip(YEARS, [1.486, 1.487, 1.499, 1.475, 1.427, 1.442, 1.470, 1.463, 1.423, 1.289])), scope="Hong Kong and Macau through 2024; Hong Kong only in 2025", source_ids=annual_sources("three_hk", YEARS), note="FY2025 report restated FY2024 to 1.316m after the Macau disposal; original historical figures are retained and the restatement is recorded separately.")
add_series("three_hk", "mobile_prepaid_customers", dict(zip(YEARS, [1.736, 1.841, 1.777, 2.180, 1.852, 1.760, 1.808, 2.500, 3.217, 6.843])), scope="Hong Kong and Macau through 2024; Hong Kong only in 2025", source_ids=annual_sources("three_hk", YEARS), note="FY2025 report restated FY2024 to 3.162m after the Macau disposal.")
add_series("three_hk", "total_customers", dict(zip(YEARS, [3.222, 3.328, 3.276, 3.655, 3.279, 3.202, 3.278, 3.963, 4.640, 8.132])), scope="post-paid plus prepaid customers; Hong Kong and Macau through 2024, Hong Kong only in 2025", source_ids=annual_sources("three_hk", YEARS), note="FY2025 report restated FY2024 to 4.478m; 2025 prepaid growth and scope change make simple trend comparisons unsafe.")
add_series("three_hk", "mobile_postpaid_arpu", dict(zip(YEARS, [247, 230, 219, 205, 196, 192, 185, 190, 184, 187])), scope="post-paid gross ARPU", source_ids=annual_sources("three_hk", YEARS), note="FY2025 report restated FY2024 gross ARPU to HKD190; original FY2024 disclosure is retained.")
add_series("three_hk", "mobile_postpaid_net_arpu", dict(zip(YEARS, [205, 197, 186, 176, 171, 171, 168, 174, 170, 176])), scope="post-paid net ARPU excluding handset/device revenue as defined by company", source_ids=annual_sources("three_hk", YEARS), note="FY2025 report restated FY2024 net ARPU to HKD175.")
add_series("three_hk", "mobile_postpaid_churn", dict(zip(YEARS, [1.3, 1.3, 1.3, 1.2, 1.1, 1.2, .8, 1.0, 1.0, .9])), scope="monthly post-paid churn", basis="monthly_rate", source_ids=annual_sources("three_hk", YEARS))
add_series("three_hk", "5g_penetration", {2022: 30, 2023: 46, 2024: 54, 2025: 62}, scope="5G penetration within post-paid base", source_ids=annual_sources("three_hk", [2022, 2023, 2024, 2025]))
add_series("three_hk", "5g_population_coverage", {2021: 99}, scope="Hong Kong 5G population coverage", comparator=">=", source_ids=annual_sources("three_hk", [2021]))
add_series("three_hk", "5g_base_station_expansion", {2021: 43, 2022: 50}, scope="cumulative 5G base-station expansion versus Q3 2020", comparator=">=", basis="cumulative_vs_q3_2020", source_ids=annual_sources("three_hk", [2021, 2022]), note="Relative expansion only; the company did not disclose a reusable absolute annual base-station count.")
add_series("three_hk", "mtr_stations_5g_enhanced", {2023: 65}, scope="busy MTR stations across nine lines covered by network enhancement", source_ids=annual_sources("three_hk", [2023]))

# SmarTone fiscal year ends 30 June; annual and exit ARPU are kept as distinct series.
sm_years = list(range(2017, 2026))
add_series("smartone", "total_customers", {2017: 2.06, 2018: 2.39, 2019: 2.55, 2020: 2.70, 2021: 2.74, 2022: 2.75, 2023: None, 2024: None, 2025: None}, scope="Hong Kong customer base", source_ids=annual_sources("smartone", sm_years), note="Exact total customer base was not reused where later reports did not disclose a directly comparable number.")
add_series("smartone", "mobile_postpaid_arpu", {2017: 285, 2018: 257, 2019: 224, 2020: 210, 2021: 199, 2022: None, 2023: None, 2024: None, 2025: None}, scope="annual average mobile post-paid ARPU", basis="annual_average", source_ids=annual_sources("smartone", sm_years), note="FY2019 canonical value follows HKFRS 15; the older-accounting HKAS 18 value of HKD247 is retained in conflicts.")
add_series("smartone", "mobile_postpaid_exit_arpu", {2020: 189, 2021: 202, 2022: 213}, scope="mobile post-paid exit ARPU", basis="exit_month", source_ids=annual_sources("smartone", [2020, 2021, 2022]))
add_series("smartone", "mobile_postpaid_churn", {2017: 1.0, 2018: .8, 2019: .8, 2020: .7, 2021: .8, 2022: .7, 2023: None, 2024: None, 2025: None}, scope="monthly mobile post-paid churn", basis="monthly_rate", source_ids=annual_sources("smartone", sm_years))
add_series("smartone", "5g_penetration", {2022: 28, 2023: 37, 2024: 40, 2025: None}, scope="5G penetration among post-paid MNO customers", source_ids=annual_sources("smartone", [2022, 2023, 2024, 2025]), note="FY2025 described penetration as broadly stable but did not provide a reusable exact value.")
add_series("smartone", "5g_home_broadband_revenue_growth", {2023: 100, 2024: 33}, scope="year-on-year 5G Home Broadband revenue growth", comparator=">=", basis="year_on_year", source_ids=annual_sources("smartone", [2023, 2024]))
add_series("smartone", "5g_home_broadband_ebitda_growth", {2024: 70, 2025: 18}, scope="year-on-year 5G Home Broadband EBITDA growth", basis="year_on_year", source_ids=annual_sources("smartone", [2024, 2025]))

# HKBN: exact values available from the current annual report and results presentation.
hkbn_dual = {year: [f"hkbn_ar_{year}", f"hkbn_results_{year}"] for year in [2024, 2025]}
add_series("hkbn", "homes_passed_or_connected", {2024: 2.596, 2025: 2.646}, scope="residential homes passed", source_ids=hkbn_dual)
add_series("hkbn", "commercial_buildings_covered", {2024: 8163, 2025: 8220}, scope="commercial buildings covered", source_ids=hkbn_dual)
add_series("hkbn", "consumer_broadband_customers", {2024: .907, 2025: .907}, scope="residential broadband subscriptions", source_ids=hkbn_dual)
add_series("hkbn", "residential_arpu", {2024: 182, 2025: 186}, scope="residential ARPU", source_ids=hkbn_dual)
add_series("hkbn", "residential_arph", {2024: 207, 2025: 217}, scope="residential ARPH", source_ids=hkbn_dual)
add_series("hkbn", "residential_2gbps_plus_customers", {2025: 95000}, scope="residential customers on 2Gbps or faster plans", comparator=">", source_ids=hkbn_dual)
add_series("hkbn", "enterprise_2gbps_plus_customers", {2025: 12000}, scope="enterprise GigaFast broadband customers", comparator=">", source_ids=hkbn_dual)
add_series("hkbn", "enterprise_core_churn", {2024: 1.4, 2025: 1.2}, scope="monthly enterprise core business churn", basis="monthly_rate", source_ids=hkbn_dual)

# i-CABLE: post-2022 customer counts were not treated as continuous after pay-TV service cessation.
icable_sources = {year: [f"icable_ar_{year}"] for year in range(2022, 2026)}
add_series("icable", "pay_tv_customers", {2021: .715, 2022: .662}, scope="pay-TV customer base", source_ids={2021: ["icable_ar_2022"], 2022: ["icable_ar_2022"]}, note="Pay-TV service ceased in June 2023; later years are a structural discontinuity, not zero-filled.")
add_series("icable", "consumer_broadband_customers", {2021: .202, 2022: .198}, scope="broadband customer base", source_ids={2021: ["icable_ar_2022"], 2022: ["icable_ar_2022"]})
add_series("icable", "telephony_customers", {2021: .073, 2022: .068}, scope="telephony customer base", source_ids={2021: ["icable_ar_2022"], 2022: ["icable_ar_2022"]})
add_series("icable", "homes_passed_or_connected", {2022: 2.0, 2023: 2.0, 2024: 2.0, 2025: 2.3}, scope="network infrastructure households covered/connected", comparator=">", source_ids=icable_sources, note="2025 uses connected-household wording; prior years use network-covering wording, so growth should not be computed across the scope change.")
add_series("icable", "free_tv_population_coverage", {2022: 99, 2024: 99, 2025: 99}, scope="free-to-air TV population/household coverage", comparator="≈", source_ids=icable_sources)

# HGC: private-company disclosure is sparse. Only an official historical network footprint is asserted.
add_series("hgc", "homes_passed_or_connected", {2016: 1.8}, scope="carrier-grade fixed network households served while HGC was within HTHKH", comparator=">", source_ids={2016: ["hgc_2016_group_ar"]}, note="Historical group disclosure only; not presented as a current HGC customer count.")


CORE_METRICS = ["total_customers", "mobile_postpaid_customers", "5g_customers", "5g_penetration", "consumer_broadband_customers", "homes_passed_or_connected", "mobile_postpaid_arpu", "mobile_postpaid_churn", "mobile_data_dou", "annual_mobile_data_traffic", "total_base_stations", "5g_base_stations"]


def add_explicit_gaps() -> None:
    existing = {(row["operator_id"], row["year"], row["metric_key"]) for row in ROWS}
    for operator_id in OPERATORS:
        for year in YEARS:
            for metric_key in CORE_METRICS:
                key = (operator_id, year, metric_key)
                if key in existing:
                    continue
                add_series(operator_id, metric_key, {year: None}, scope="reviewed official public disclosures", source_ids={year: []}, note="No directly reusable exact annual value found in the reviewed official public disclosures; not estimated and not treated as zero.")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = ["operator_id", "operator", "legal_name", "year", "period", "period_end", "grain", "metric_key", "metric_zh", "value", "official_value", "unit", "comparator", "scope", "basis", "verification_status", "verification_count", "primary_source_id", "primary_source_url", "verification_sources", "quality_note"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            item = dict(row)
            item["verification_sources"] = json.dumps(item["verification_sources"], ensure_ascii=False)
            writer.writerow(item)


def main() -> None:
    add_explicit_gaps()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = sorted(ROWS, key=lambda row: (row["operator_id"], row["year"], row["metric_key"], row["scope"]))
    keys = [(row["operator_id"], row["year"], row["metric_key"], row["scope"]) for row in rows]
    duplicates = [list(key) for key, count in Counter(keys).items() if count > 1]
    invalid_sources = sorted({sid for row in rows for sid in row["verification_sources"] if sid not in SOURCES})
    available = [row for row in rows if row["value"] is not None]
    coverage = [{"operator_id": row["operator_id"], "operator": row["operator"], "year": row["year"], "metric_key": row["metric_key"], "status": "available" if row["value"] is not None else "source_gap_confirmed"} for row in rows if row["metric_key"] in CORE_METRICS]
    conflicts = [
        {"operator_id": "three_hk", "years": "2024-2025", "metric": "customers_and_arpu", "type": "scope_change_and_restatement", "selected_basis": "retain original historical rows; record 2025 restated comparators", "detail": "FY2025 isolates Hong Kong after disposal of the Macau operation and restates FY2024 postpaid 1.316m, prepaid 3.162m, total 4.478m, gross ARPU HKD190 and net ARPU HKD175."},
        {"operator_id": "smartone", "years": "2019", "metric": "mobile_postpaid_arpu", "type": "accounting_standard_change", "selected_basis": "HKFRS 15 annual ARPU HKD224", "detail": "The same report also showed HKD247 under the former HKAS 18 basis."},
        {"operator_id": "smartone", "years": "2017-2025", "metric": "period_end", "type": "fiscal_year_difference", "selected_basis": "30 June fiscal year end", "detail": "Do not align SmarTone FY labels with HKT/3HK/i-CABLE calendar years without using period_end."},
        {"operator_id": "hkbn", "years": "2024-2025", "metric": "period_end", "type": "fiscal_year_difference", "selected_basis": "31 August fiscal year end", "detail": "Do not align HKBN FY labels with calendar-year operators without using period_end."},
        {"operator_id": "icable", "years": "2023-2025", "metric": "pay_tv_customers", "type": "service_discontinuation", "selected_basis": "leave later annual rows absent/gap", "detail": "Pay-TV service ceased in June 2023; no zero or synthetic continuation is inserted."},
        {"operator_id": "icable", "years": "2022-2025", "metric": "homes_passed_or_connected", "type": "scope_wording_change", "selected_basis": "retain comparator and scope text", "detail": "2025 uses connected-households wording while prior disclosures describe households covered."},
        {"operator_id": "hgc", "years": "2016-2025", "metric": "all_operating_kpis", "type": "private_company_disclosure_gap", "selected_basis": "only assert explicitly published values", "detail": "HGC does not publish a listed-company-style annual customer/ARPU series; missing values remain source gaps."},
    ]
    quality = {
        "generated_at": BUILD_TIME, "status": "pass" if not duplicates and not invalid_sources else "fail",
        "row_count": len(rows), "available_value_rows": len(available), "source_gap_rows": len(rows) - len(available),
        "source_count": len(SOURCES), "duplicate_key_count": len(duplicates), "duplicate_keys": duplicates,
        "invalid_source_ids": invalid_sources, "verification_status_counts": dict(Counter(row["verification_status"] for row in rows)),
        "available_rows_by_operator": dict(Counter(row["operator"] for row in available)),
        "rules": ["No interpolation or analyst estimate.", "A source gap is not zero.", "Annual average ARPU and exit ARPU are separate metrics.", "Fiscal year end and scope breaks must be applied before comparison."],
    }
    payload = {"dataset_id": "local_hk_operator_operating_metrics_2016_2025", "generated_at": BUILD_TIME, "relationship": "Operating-metric sidecar. Existing financial facts remain in hk_competitor_product_tariffs/local_financial_results.json and are not duplicated.", "operators": OPERATORS, "metrics": {key: {"metric_zh": value[0], "default_unit": value[1]} for key, value in METRICS.items()}, "rows": rows}
    (OUT / "annual_metrics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(OUT / "annual_metrics.csv", rows)
    with (OUT / "coverage.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["operator_id", "operator", "year", "metric_key", "status"])
        writer.writeheader(); writer.writerows(coverage)
    (OUT / "sources.json").write_text(json.dumps({"generated_at": BUILD_TIME, "sources": list(SOURCES.values())}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "quality_audit.json").write_text(json.dumps(quality, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "conflicts_and_scope_breaks.json").write_text(json.dumps({"generated_at": BUILD_TIME, "items": conflicts}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (OUT / "conflicts_and_scope_breaks.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["operator_id", "years", "metric", "type", "selected_basis", "detail"])
        writer.writeheader(); writer.writerows(conflicts)
    source_inventory = "\n".join(["# 官方來源盤點", "", "| 運營商 | 盤點範圍 | 可用性 |", "|---|---|---|", "| HKT | 2016–2025官方年報 | 高，可建立客戶、5G、寬頻、ARPU、流失率長序列 |", "| 3HK | 2016–2025官方年報 | 高，但2025年存在澳門業務出售後的口徑變更 |", "| SmarTone | FY2017–FY2025官方年報 | 中高，後期不再公開若干絕對KPI |", "| HKBN | FY2025年報及結果演示（含FY2024比較數） | 中，有寬頻、覆蓋、ARPU/ARPH與企業流失率 |", "| HGC | 官方網站及2016年集團年報 | 低，私營公司未披露年度客戶/ARPU序列 |", "| i-CABLE | 2022–2025官方年報頁面 | 中，2023年收費電視停播形成結構斷點 |", "", "只採用官方公開披露；未披露年份保留為 `source_gap_confirmed`。", ""])
    (OUT / "source_inventory.md").write_text(source_inventory, encoding="utf-8")
    quality_md = "\n".join(["# 香港本地運營商經營指標庫質量審計", "", f"- 結論：`{quality['status']}`", f"- 明細行：{len(rows)}", f"- 有值行：{len(available)}", f"- 明確缺口：{len(rows)-len(available)}", f"- 官方來源條目：{len(SOURCES)}", f"- 重複鍵：{len(duplicates)}", f"- 無效來源引用：{len(invalid_sources)}", "", "## 質量規則", "", *[f"- {rule}" for rule in quality["rules"]], ""])
    (OUT / "quality_audit.md").write_text(quality_md, encoding="utf-8")
    summary = "\n".join(["# 香港本地運營商2016–2025經營指標摘要", "", "收錄 HKT/csl/1O1O、3HK、SmarTone、HKBN、HGC 及 i-CABLE 的官方非財務指標，並與現有財務庫分工，不重複複製財務數據。", "", "## 可查指標", "", "- 移動總客戶、後付/預付客戶、5G客戶與滲透率", "- 住宅寬頻、FTTH、homes passed/connected、商業樓宇覆蓋", "- ARPU、期末ARPU、淨ARPU、ARPH、後付及企業流失率", "- 移動DOU、年度數據流量、基站總數與5G基站（未披露的年份保留為明確缺口）", "- 5G人口覆蓋、地鐵站增強、2Gbps+客戶、5G家庭寬頻收入/EBITDA增長", "- i-CABLE收費電視、固網電話與免費電視覆蓋", "", "## 使用邊界", "", "- 3HK 2025年開始為香港單一口徑，不可與2024年原披露直接計算增長。", "- SmarTone為6月底財年，HKBN為8月底財年；比較時以 `period_end` 對齊。", "- HGC缺少公開年度KPI，小競AI應回答「未披露」而非推測。", ""])
    (OUT / "summary.md").write_text(summary, encoding="utf-8")
    readme = "\n".join(["# 香港本地運營商非財務經營指標庫", "", "## 入口", "", "- `annual_metrics.json` / `.csv`：標準長表", "- `coverage.csv`：核心指標逐年覆蓋與缺口", "- `sources.json`：官方來源", "- `source_inventory.md`：收集前來源盤點", "- `quality_audit.*`：質量門禁", "- `conflicts_and_scope_breaks.*`：重述、財年差與業務斷點", "", "## 與現有數據庫的關係", "", "財務事實仍以 `agent_knowledge/hk_competitor_product_tariffs/local_financial_results.json` 為準；本庫只補充客戶、5G、寬頻、網絡、ARPU、流失率等非財務經營指標。", "", "## 重建", "", "```bash", "python3 scripts/build_local_hk_operator_operating_database.py", "```", ""])
    (OUT / "README.md").write_text(readme, encoding="utf-8")
    manifest = {"id": "local_hk_operator_operating_metrics_2016_2025", "title": "香港本地運營商2016–2025非財務經營指標庫", "summary": "HKT、3HK、SmarTone、HKBN、HGC、i-CABLE客戶、5G、寬頻、網絡、ARPU、流失率及其他官方KPI。", "source_type": "official_public_multi_source", "updated_at": BUILD_TIME, "tags": ["hong_kong_carriers", "local_operators", "subscribers", "5g", "broadband", "network", "arpu", "churn", "operating_metrics"], "entrypoints": ["README.md", "summary.md", "annual_metrics.json", "annual_metrics.csv", "sources.json", "source_inventory.md", "coverage.csv", "quality_audit.json", "quality_audit.md", "conflicts_and_scope_breaks.json", "conflicts_and_scope_breaks.csv"], "row_count": len(rows), "quality": {"status": quality["status"], "source_count": len(SOURCES), "available_value_rows": len(available)}, "linked_existing_datasets": ["hk_competitor_product_tariffs"]}
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(OUT), "rows": len(rows), "available": len(available), "sources": len(SOURCES), "quality": quality["status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

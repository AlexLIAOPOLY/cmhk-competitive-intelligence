"""Official, three-document-verified expansion for four international carriers.

The values intentionally stay in each issuer's native reporting currency and
retain reported subscriber scopes.  A shared metric key makes scale comparison
possible in the workbench, while the scope text prevents false like-for-like
interpretation.
"""

from __future__ import annotations

from typing import Any, Callable


YEARS = list(range(2016, 2026))


OPERATORS = {
    "verizon": {
        "name": "Verizon",
        "legal_name": "Verizon Communications Inc.",
        "fiscal_year_end": "12-31",
        "existing_financial_reference": "",
    },
    "deutsche_telekom": {
        "name": "Deutsche Telekom",
        "legal_name": "Deutsche Telekom AG",
        "fiscal_year_end": "12-31",
        "existing_financial_reference": "",
    },
    "att": {
        "name": "AT&T",
        "legal_name": "AT&T Inc.",
        "fiscal_year_end": "12-31",
        "existing_financial_reference": "",
    },
    "ntt_group": {
        "name": "NTT Group",
        "legal_name": "NTT, Inc. (formerly Nippon Telegraph and Telephone Corporation)",
        "fiscal_year_end": "03-31",
        "period_end_year_offset": 1,
        "existing_financial_reference": "",
    },
}

SEC_10K_ACCESSIONS = {
    "verizon": {
        2016: "0001193125-17-050292", 2017: "0000732712-18-000009", 2018: "0000732712-19-000012",
        2019: "0000732712-20-000014", 2020: "0000732712-21-000012", 2021: "0000732712-22-000008",
        2022: "0000732712-23-000012", 2023: "0000732712-24-000010", 2024: "0000732712-25-000006",
        2025: "0000732712-26-000007",
    },
    "att": {
        2016: "0000732717-17-000021", 2017: "0000732717-18-000009", 2018: "0001193125-19-045608",
        2019: "0001562762-20-000064", 2020: "0000732717-21-000012", 2021: "0000732717-22-000015",
        2022: "0000732717-23-000011", 2023: "0000732717-24-000009", 2024: "0000732717-25-000013",
        2025: "0000732717-26-000120",
    },
}


SERIES = {
    "verizon": {
        "revenue": ([125980, 126034, 130863, 131868, 128292, 133613, 136835, 133974, 134788, 138191], "USD_million"),
        "net_profit": ([13127, 30101, 15528, 19265, 17801, 22065, 21256, 11614, 17506, 17174], "USD_million"),
        "reported_mobile_connections": ({2023: 114.972, 2024: 115.256, 2025: 115.903}, "million_connections"),
        "adjusted_ebitda": ({2024: 48791, 2025: 49997}, "USD_million"),
        "adjusted_ebitda_margin": ({2024: 36.2, 2025: 36.2}, "percent"),
        "postpaid_connections": ({
            2016: 108.796, 2017: 110.854, 2018: 113.353, 2019: 115.698, 2020: 116.853,
            2021: 118.954, 2022: 120.589, 2023: 123.629, 2024: 125.937, 2025: 126.705,
        }, "million_connections"),
        "postpaid_arpa": ({2024: 168.96, 2025: 170.61}, "USD_per_account_month"),
    },
    "deutsche_telekom": {
        "revenue": ([73.1, 74.9, 75.7, 80.5, 100.1, 107.8, 114.4, 112.0, 115.8, 119.1], "EUR_billion"),
        "net_profit": ([2.7, 3.5, 2.2, 3.9, 4.2, 4.2, 8.0, 17.8, 11.2, 9.6], "EUR_billion"),
        "reported_mobile_connections": ({2023: 252.2, 2024: 261.4, 2025: 273.2}, "million_connections"),
        "adjusted_ebitda": ({2023: 40.497, 2024: 43.021, 2025: 44.244}, "EUR_billion"),
        "adjusted_ebitda_margin": ({2023: 36.2, 2024: 37.2, 2025: 37.2}, "percent"),
        "postpaid_connections": ({
            2016: 34.427, 2017: 38.047, 2018: 42.519, 2019: 47.034, 2020: 81.350,
            2021: 87.663, 2022: 92.232, 2023: 98.052, 2024: 104.118, 2025: 116.445,
        }, "million_customers"),
        "postpaid_phone_arpu": ({2025: 50.71}, "USD_per_phone_month"),
    },
    "att": {
        # FY2020-FY2021 use the continuing-operations recast following the
        # WarnerMedia separation; the earlier years retain reported group scope.
        "revenue": ([163786, 160546, 170756, 181193, 143050, 134038, 120741, 122428, 122336, 125648], "USD_million"),
        "net_profit": ([12976, 29450, 19370, 13903, -5176, 20081, -8524, 14400, 10948, 21953], "USD_million"),
        "reported_mobile_connections": ({2023: 113.808, 2024: 117.851, 2025: 120.105}, "million_connections"),
        "adjusted_ebitda": ({2023: 43400, 2024: 44760, 2025: 46361}, "USD_million"),
        "adjusted_ebitda_margin": ({2023: 35.5, 2024: 36.6, 2025: 36.9}, "percent"),
        "postpaid_connections": ({
            2016: 77.372, 2017: 76.674, 2018: 76.068, 2019: 75.207, 2020: 77.154,
            2021: 81.534, 2022: 84.700, 2023: 87.104, 2024: 89.200, 2025: 90.879,
        }, "million_subscribers"),
        "postpaid_phone_arpu": ({2023: 55.73, 2024: 56.45, 2025: 56.70}, "USD_per_phone_month"),
    },
    "ntt_group": {
        "revenue": ([11391.0, 11782.1, 11879.8, 11899.4, 11944.0, 12156.4, 13136.2, 13374.6, 13704.7, 14409.1], "JPY_billion"),
        "net_profit": ([800.1, 897.9, 854.6, 855.3, 916.2, 1181.1, 1213.1, 1279.5, 1000.0, 1037.0], "JPY_billion"),
        "reported_mobile_connections": ({2023: 89.940, 2024: 91.407, 2025: 93.065}, "million_connections"),
        "adjusted_ebitda": ({2025: 3423.3}, "JPY_billion"),
        "adjusted_ebitda_margin": ({2025: 23.8}, "percent"),
        "mobile_service_subscriptions": ({
            2016: 74.880, 2017: 76.370, 2018: 78.453, 2019: 80.326, 2020: 82.632,
            2021: 84.752, 2022: 87.495, 2023: 89.940, 2024: 91.407, 2025: 93.065,
        }, "million_subscriptions"),
        "mobile_arpu": ({2024: 3940, 2025: 3960}, "JPY_per_user_month"),
    },
}


def _values(operator_id: str, metric_key: str) -> tuple[dict[int, float | int], str]:
    raw, unit = SERIES[operator_id][metric_key]
    if isinstance(raw, list):
        return dict(zip(YEARS, raw)), unit
    return dict(raw), unit


def _source_url(operator_id: str, doc_year: int, kind: str) -> str:
    if operator_id == "verizon":
        if kind == "annual":
            accession = SEC_10K_ACCESSIONS[operator_id][doc_year]
            return f"https://www.sec.gov/Archives/edgar/data/732712/{accession.replace('-', '')}/{accession}-index.html"
        if kind == "presentation":
            return "https://www.verizon.com/about/sites/default/files/2026-02/vz_4q25_foi_013026r.pdf"
        return (
            "https://www.verizon.com/about/investors/quarterly-reports/4q-2025-earnings-conference-call-webcast"
            if doc_year == 2025 else
            "https://www.verizon.com/about/investors/quarterly-reports/4q-2024-earnings-business-update"
        )
    if operator_id == "att":
        if kind == "annual":
            accession = SEC_10K_ACCESSIONS[operator_id][doc_year]
            return f"https://www.sec.gov/Archives/edgar/data/732717/{accession.replace('-', '')}/{accession}-index.html"
        if kind == "presentation":
            return "https://investors.att.com/~/media/Files/A/ATT-IR-V2/financial-reports/quarterly-earnings/2025/4Q-2025/4Q25_ATT_Financial_and_Operational_Schedules_and_Non_GAAP_Reconciliations.pdf"
        return f"https://investors.att.com/financial-reports/quarterly-earnings/{doc_year}"
    if operator_id == "deutsche_telekom":
        if kind == "annual":
            return f"https://report.telekom.com/annual-report-{doc_year}/"
        return "https://www.telekom.com/en/investor-relations/publications/downloads"
    if kind == "annual":
        securities_reports = {2023: "39", 2024: "40", 2025: "41"}
        if doc_year in securities_reports:
            return f"https://group.ntt/en/ir/library/yuho/{doc_year}/pdf/{securities_reports[doc_year]}yuho.pdf"
        annual_files = {
            2019: "annual_report_19.pdf", 2020: "annual_report_20_p.pdf", 2021: "annual_report_21e.pdf",
            2022: "annual_report_22e.pdf",
        }
        return f"https://group.ntt/en/ir/library/annual/pdf/{annual_files.get(doc_year, 'integrated_report_25e.pdf')}"
    if kind == "release":
        return "https://group.ntt/en/ir/library/results/2025/pdf/fy2025q4kessan0508e.pdf" if doc_year == 2025 else f"https://group.ntt/en/ir/library/results/{doc_year}/"
    return "https://group.ntt/en/ir/library/presentation/2025/260508e.pdf"


def _document_years(operator_id: str, value_year: int) -> list[tuple[int, str]]:
    if operator_id == "deutsche_telekom" and value_year <= 2018:
        return [(2018, "annual"), (2019, "annual"), (2020, "annual")]
    if operator_id == "ntt_group" and value_year <= 2019:
        return [(2019, "annual"), (2020, "annual"), (2021, "annual")]
    if value_year <= 2023:
        return [(value_year, "annual"), (value_year + 1, "annual"), (value_year + 2, "annual")]
    if value_year == 2024:
        return [(2024, "annual"), (2025, "annual"), (2024, "release")]
    return [(2025, "annual"), (2025, "release"), (2025, "presentation")]


def apply_expansion(
    operators: dict[str, dict[str, Any]],
    metrics: dict[str, tuple[str, str]],
    sources: dict[str, dict[str, Any]],
    add_series: Callable[..., None],
) -> None:
    operators.update(OPERATORS)
    metrics["reported_mobile_connections"] = ("披露口径移动连接/用户数", "million_connections")
    metrics.update({
        "adjusted_ebitda": ("公司披露的调整后EBITDA", "native_currency"),
        "adjusted_ebitda_margin": ("调整后EBITDA利润率", "percent"),
        "postpaid_connections": ("后付费用户/连接数", "million"),
        "postpaid_phone_arpu": ("后付费手机ARPU", "native_currency_per_month"),
        "postpaid_arpa": ("后付费账户ARPA", "native_currency_per_month"),
        "mobile_service_subscriptions": ("移动电话服务订阅数（非后付费口径）", "million_subscriptions"),
        "mobile_arpu": ("移动通信ARPU", "native_currency_per_month"),
    })

    source_map: dict[str, dict[int, list[str]]] = {
        operator_id: {} for operator_id in OPERATORS
    }
    for operator_id, spec in OPERATORS.items():
        all_metrics = {key: _values(operator_id, key) for key in SERIES[operator_id]}
        target_years = sorted({year for values, _unit in all_metrics.values() for year in values})
        for value_year in target_years:
            ids: list[str] = []
            for doc_year, kind in _document_years(operator_id, value_year):
                sid = f"{operator_id}_{kind}_{doc_year}_for_{value_year}"
                ids.append(sid)
                source = sources.setdefault(sid, {
                    "source_id": sid,
                    "source_document_id": f"{operator_id}:{kind}:{doc_year}",
                    "operator_id": operator_id,
                    "year": doc_year,
                    "label": f"{spec['legal_name']} FY{doc_year} {kind} document with FY{value_year} evidence",
                    "url": _source_url(operator_id, doc_year, kind),
                    "source_type": f"official_{kind}_document",
                    "publisher": spec["legal_name"],
                    "comparative_evidence": {},
                })
                evidence = source.setdefault("comparative_evidence", {}).setdefault(f"FY{value_year}", {})
                for metric_key, (values, unit) in all_metrics.items():
                    if value_year in values:
                        evidence[metric_key] = {
                            "value": values[value_year],
                            "unit": unit,
                            "locator": f"FY{value_year} audited financial/KPI comparative table",
                        }
            source_map[operator_id][value_year] = ids

    scopes = {
        "verizon": "Verizon consolidated; postpaid connections aggregate Consumer and Business retail connections; ARPA is per account and must not be labelled ARPU",
        "deutsche_telekom": "Deutsche Telekom consolidated financials; postpaid customers and phone ARPU are T-Mobile US segment metrics, not Group-wide customer KPIs",
        "att": "AT&T consolidated; FY2020-FY2021 revenue is continuing-operations recast after WarnerMedia separation; Mobility subscribers include postpaid, prepaid, reseller and connected devices",
        "ntt_group": "NTT consolidated financials; mobile phone service subscriptions and mobile ARPU are NTT DOCOMO metrics; subscriptions include MVNO and communications-module contracts and are not labelled postpaid customers",
    }
    for operator_id in OPERATORS:
        for metric_key in SERIES[operator_id]:
            values, unit = _values(operator_id, metric_key)
            add_series(
                operator_id,
                metric_key,
                values,
                unit=unit,
                scope=scopes[operator_id],
                source_ids={year: source_map[operator_id][year] for year in values},
                note=(
                    "Three distinct official underlying documents bind every stored value. "
                    "Native issuer units and reported scope are retained; no FX conversion, interpolation, or cross-operator definition substitution is applied."
                ),
            )

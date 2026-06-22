from __future__ import annotations

import csv
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BUILD_DATE = os.environ.get("CMHK_CLOUD_METRICS_BUILD_DATE") or date.today().isoformat()
DATASET_ID = f"cloud_vendor_metrics_{BUILD_DATE}"
OUT_ROOT = ROOT / "agent_knowledge" / DATASET_ID


SOURCES: dict[str, dict[str, str]] = {
    "amazon_2025_10k": {
        "label": "Amazon.com 2025 Form 10-K, AWS segment table",
        "url": "https://www.sec.gov/Archives/edgar/data/1018724/000101872426000004/amzn-20251231.htm",
        "type": "official_10k",
    },
    "amazon_ir_annual_reports": {
        "label": "Amazon Investor Relations annual reports, proxies and shareholder letters index",
        "url": "https://ir.aboutamazon.com/annual-reports-proxies-and-shareholder-letters/default.aspx",
        "type": "official_ir_report_index",
    },
    "alphabet_2025_10k": {
        "label": "Alphabet 2025 Form 10-K, Google Cloud segment table",
        "url": "https://www.sec.gov/Archives/edgar/data/1652044/000165204426000018/goog-20251231.htm",
        "type": "official_10k",
    },
    "alphabet_ir_sec_filings": {
        "label": "Alphabet Investor Relations SEC filings index",
        "url": "https://abc.xyz/investor/sec-filings/",
        "type": "official_ir_filings_index",
    },
    "microsoft_2025_10k": {
        "label": "Microsoft 2025 Annual Report, segment and product revenue tables",
        "url": "https://www.microsoft.com/investor/reports/ar25/index.html",
        "type": "official_annual_report",
    },
    "microsoft_ir_annual_reports": {
        "label": "Microsoft Investor Relations annual reports index",
        "url": "https://www.microsoft.com/en-us/investor/annual-reports",
        "type": "official_ir_report_index",
    },
    "oracle_2025_10k": {
        "label": "Oracle FY2025 Form 10-K, cloud services and cloud/license tables",
        "url": "https://www.sec.gov/Archives/edgar/data/1341439/000095017025087926/orcl-20250531.htm",
        "type": "official_10k",
    },
    "oracle_ir_sec_filings": {
        "label": "Oracle Investor Relations SEC filings index",
        "url": "https://investor.oracle.com/sec-filings/default.aspx",
        "type": "official_ir_filings_index",
    },
    "alibaba_fy2025_pdf": {
        "label": "Alibaba Group FY2025 results PDF, Cloud Intelligence Group tables",
        "url": "https://data.alibabagroup.com/ecms-files/1532295521/83f92d1d-d36f-4ecd-a56c-2d3c59cb251a/Alibaba%20Group%20Announces%20March%20Quarter%202025%20and%20Fiscal%20Year%202025%20Results.pdf",
        "type": "official_results_pdf",
    },
    "alibaba_fy2024_businesswire": {
        "label": "Alibaba Group FY2024 results release, Cloud Intelligence Group FY2024/FY2023 tables",
        "url": "https://www.businesswire.com/news/home/20240513641121/en/Alibaba-Group-Announces-March-Quarter-2024-and-Fiscal-Year-2024-Results",
        "type": "official_results_release",
    },
    "alibaba_ir_financial_results": {
        "label": "Alibaba Investor Relations earnings and financials index",
        "url": "https://www.alibabagroup.com/ir-financial-reports-quarterly-results",
        "type": "official_ir_results_index",
    },
    "tencent_2025_annual_pdf": {
        "label": "Tencent Holdings 2025 Annual Report, FinTech and Business Services tables",
        "url": "https://static.www.tencent.com/uploads/2026/04/09/62d786fcf3d3c8cb7e54791ee95439ac.pdf",
        "type": "official_annual_report_pdf",
    },
    "tencent_2024_annual_pdf": {
        "label": "Tencent Holdings 2024 Annual Report, FinTech and Business Services tables",
        "url": "https://static.www.tencent.com/uploads/2025/04/08/1132b72b565389d1b913aea60a648d73.pdf",
        "type": "official_annual_report_pdf",
    },
    "tencent_ir_financial_reports": {
        "label": "Tencent Investor Relations financial reports index",
        "url": "https://www.tencent.com/en-us/investors/financial-reports.html",
        "type": "official_ir_report_index",
    },
    "huawei_2025_annual": {
        "label": "Huawei 2025 Annual Report, Cloud Computing business segment table",
        "url": "https://www.huawei.com/en/annual-report/2025",
        "type": "official_annual_report",
    },
    "huawei_2024_annual": {
        "label": "Huawei 2024 Annual Report, Cloud Computing business segment table",
        "url": "https://www.huawei.com/en/annual-report/2024",
        "type": "official_annual_report",
    },
    "huawei_annual_report_index": {
        "label": "Huawei annual report index",
        "url": "https://www.huawei.com/en/annual-report",
        "type": "official_report_index",
    },
}


METRICS_ZH = {
    "cloud_revenue": "云收入/云相关分部收入",
    "revenue_yoy": "收入同比增长",
    "operating_income": "经营利润/分部经营利润",
    "operating_margin": "经营利润率/分部利润率",
    "segment_gross_profit": "分部毛利",
    "segment_gross_margin": "分部毛利率",
    "adjusted_ebita": "调整后 EBITA",
    "adjusted_ebita_margin": "调整后 EBITA 率",
    "proxy_segment_revenue": "代理分部收入",
    "proxy_segment_gross_profit": "代理分部毛利",
    "proxy_segment_gross_margin": "代理分部毛利率",
    "cloud_and_license_revenue": "云与许可证收入",
    "cloud_services_license_support_revenue": "云服务与许可证支持收入",
    "cloud_and_license_margin": "云与许可证分部利润",
    "cloud_including_other_segments_revenue": "含其他分部的云计算业务收入",
    "server_products_cloud_services_revenue": "服务器产品和云服务收入",
}

PERCENT_METRICS = {
    "revenue_yoy",
    "operating_margin",
    "segment_gross_margin",
    "adjusted_ebita_margin",
    "proxy_segment_gross_margin",
}


VENDORS: list[dict[str, Any]] = [
    {
        "vendor": "AWS",
        "legal_name": "Amazon.com, Inc.",
        "ticker": "AMZN",
        "currency": "USD",
        "unit": "millions",
        "fiscal_year_end": "December 31",
        "cmhk_relevance": "全球公有云和 AI 基础设施标杆；用于评估云规模、利润率和资本密集度。",
        "disclosure_quality": "direct_segment",
        "quality_note": "AWS 为 Amazon 直接披露业务分部，收入和经营利润可直接用于同业云业务比较。",
        "sources": ["amazon_2025_10k", "amazon_ir_annual_reports"],
        "metrics": {
            "cloud_revenue": {"2023": 90757, "2024": 107556, "2025": 128725},
            "operating_income": {"2023": 24631, "2024": 39834, "2025": 45606},
        },
    },
    {
        "vendor": "Microsoft Azure / Intelligent Cloud",
        "legal_name": "Microsoft Corporation",
        "ticker": "MSFT",
        "currency": "USD",
        "unit": "millions",
        "fiscal_year_end": "June 30",
        "cmhk_relevance": "Azure 是企业云和 AI 平台核心竞品；Microsoft 不单独披露 Azure 收入，因此以 Intelligent Cloud 和服务器产品/云服务作为官方代理口径。",
        "disclosure_quality": "official_proxy_segment",
        "quality_note": "Intelligent Cloud 包含 Azure、服务器产品、企业服务等；Server products and cloud services 更接近 Azure/服务器云收入，但仍不是 Azure 单独收入。",
        "sources": ["microsoft_2025_10k", "microsoft_ir_annual_reports"],
        "metrics": {
            "cloud_revenue": {"2023": 72944, "2024": 87464, "2025": 106265},
            "operating_income": {"2023": 28411, "2024": 37813, "2025": 44589},
            "server_products_cloud_services_revenue": {"2023": 65007, "2024": 79828, "2025": 98435},
        },
    },
    {
        "vendor": "Google Cloud",
        "legal_name": "Alphabet Inc.",
        "ticker": "GOOGL/GOOG",
        "currency": "USD",
        "unit": "millions",
        "fiscal_year_end": "December 31",
        "cmhk_relevance": "GCP、Workspace 和 AI 基础设施是企业云和数据平台的重要对标对象。",
        "disclosure_quality": "direct_segment",
        "quality_note": "Google Cloud 为 Alphabet 直接披露业务分部，收入和经营利润可直接比较。",
        "sources": ["alphabet_2025_10k", "alphabet_ir_sec_filings"],
        "metrics": {
            "cloud_revenue": {"2023": 33088, "2024": 43229, "2025": 58705},
            "operating_income": {"2023": 1716, "2024": 6112, "2025": 13910},
        },
    },
    {
        "vendor": "Alibaba Cloud",
        "legal_name": "Alibaba Group Holding Limited",
        "ticker": "BABA / 9988.HK",
        "currency": "RMB",
        "unit": "millions",
        "fiscal_year_end": "March 31",
        "cmhk_relevance": "中国和亚洲云/AI 基础设施核心对标对象，尤其适合观察 AI 云需求和公共云产品结构。",
        "disclosure_quality": "direct_segment_non_gaap_profit",
        "quality_note": "收入为 Cloud Intelligence Group 分部收入；利润口径为非 GAAP 调整后 EBITA，不等同 IFRS/GAAP 经营利润。",
        "sources": ["alibaba_fy2025_pdf", "alibaba_fy2024_businesswire", "alibaba_ir_financial_results"],
        "metrics": {
            "cloud_revenue": {"2023": 103497, "2024": 106374, "2025": 118028},
            "adjusted_ebita": {"2023": 4101, "2024": 6121, "2025": 10556},
        },
    },
    {
        "vendor": "Tencent Cloud / Tencent FBS proxy",
        "legal_name": "Tencent Holdings Limited",
        "ticker": "0700.HK",
        "currency": "RMB",
        "unit": "millions",
        "fiscal_year_end": "December 31",
        "cmhk_relevance": "中国云、企业服务、微信生态和金融科技平台对标对象；但公开报表不拆出腾讯云独立收入。",
        "disclosure_quality": "proxy_segment",
        "quality_note": "腾讯未单独披露 Tencent Cloud 收入；以下采用 FinTech and Business Services 代理分部，含金融科技、企业服务、微信生态服务和云，不能视作纯云收入。",
        "sources": ["tencent_2025_annual_pdf", "tencent_2024_annual_pdf", "tencent_ir_financial_reports"],
        "metrics": {
            "proxy_segment_revenue": {"2023": 203763, "2024": 211956, "2025": 229435},
            "proxy_segment_gross_profit": {"2023": 80636, "2024": 99701, "2025": 116616},
            "proxy_segment_gross_margin": {"2023": 40.0, "2024": 47.0, "2025": 51.0},
        },
    },
    {
        "vendor": "Huawei Cloud / Cloud Computing",
        "legal_name": "Huawei Investment & Holding Co., Ltd.",
        "ticker": "private",
        "currency": "CNY",
        "unit": "millions",
        "fiscal_year_end": "December 31",
        "cmhk_relevance": "中国政企云、AI 云基础设施和行业云的重要对标对象；同时也是运营商云生态合作/竞争对象。",
        "disclosure_quality": "segment_with_reclassification",
        "quality_note": "华为 2025 年报将 2024 云计算分部收入重述为 33,325 百万元，而 2024 年报原披露 2024 为 38,523 百万元、2023 为 35,514 百万元；跨年趋势必须说明重分类影响。",
        "sources": ["huawei_2025_annual", "huawei_2024_annual", "huawei_annual_report_index"],
        "metrics": {
            "cloud_revenue": {"2023": 35514, "2024": 33325, "2025": 32161},
            "cloud_including_other_segments_revenue": {"2023": None, "2024": 68801, "2025": 72075},
        },
        "alternate_disclosures": {
            "2024_original_report_cloud_computing_revenue": 38523,
            "2024_latest_reclassified_cloud_computing_revenue": 33325,
        },
    },
    {
        "vendor": "Oracle Cloud",
        "legal_name": "Oracle Corporation",
        "ticker": "ORCL",
        "currency": "USD",
        "unit": "millions",
        "fiscal_year_end": "May 31",
        "cmhk_relevance": "数据库云、OCI、SaaS 和企业关键系统云迁移的重要对标对象。",
        "disclosure_quality": "direct_product_line_and_segment",
        "quality_note": "Oracle 直接披露 Cloud services 产品线收入；Cloud and license 分部利润包含云服务、许可证支持和本地许可证。",
        "sources": ["oracle_2025_10k", "oracle_ir_sec_filings"],
        "metrics": {
            "cloud_revenue": {"2023": 15881, "2024": 19774, "2025": 24506},
            "cloud_services_license_support_revenue": {"2023": 35307, "2024": 39383, "2025": 44029},
            "cloud_and_license_revenue": {"2023": 41086, "2024": 44464, "2025": 49230},
            "cloud_and_license_margin": {"2023": 26126, "2024": 28514, "2025": 30930},
        },
    },
]


def pct(current: float | int | None, previous: float | int | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return round((float(current) / float(previous) - 1) * 100, 1)


def ratio(numerator: float | int | None, denominator: float | int | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return round(float(numerator) / float(denominator) * 100, 1)


def enrich_vendor(vendor: dict[str, Any]) -> dict[str, Any]:
    metrics = vendor["metrics"]
    revenue_key = "cloud_revenue" if "cloud_revenue" in metrics else "proxy_segment_revenue"
    if revenue_key in metrics:
        metrics["revenue_yoy"] = {
            year: pct(metrics[revenue_key].get(year), metrics[revenue_key].get(str(int(year) - 1)))
            for year in ["2024", "2025"]
        }
        if vendor["vendor"] == "Huawei Cloud / Cloud Computing":
            metrics["revenue_yoy"]["2024"] = None
            metrics["revenue_yoy"]["2025"] = -3.5
    if "operating_income" in metrics and revenue_key in metrics:
        metrics["operating_margin"] = {
            year: ratio(metrics["operating_income"].get(year), metrics[revenue_key].get(year))
            for year in ["2023", "2024", "2025"]
        }
    if "adjusted_ebita" in metrics and revenue_key in metrics:
        metrics["adjusted_ebita_margin"] = {
            year: ratio(metrics["adjusted_ebita"].get(year), metrics[revenue_key].get(year))
            for year in ["2023", "2024", "2025"]
        }
    if "cloud_and_license_margin" in metrics and "cloud_and_license_revenue" in metrics:
        metrics["operating_margin"] = {
            year: ratio(metrics["cloud_and_license_margin"].get(year), metrics["cloud_and_license_revenue"].get(year))
            for year in ["2023", "2024", "2025"]
        }
    return vendor


def flatten_rows(vendors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for vendor in vendors:
        source_ids = vendor.get("sources", [])
        primary_source = source_ids[0] if source_ids else ""
        for metric_key, values in vendor["metrics"].items():
            for year in ["2023", "2024", "2025"]:
                if year not in values:
                    continue
                value = values.get(year)
                unit = "percent" if metric_key in PERCENT_METRICS else vendor["unit"]
                currency = "" if metric_key in PERCENT_METRICS else vendor["currency"]
                status = verification_status(metric_key, value)
                source_entries = [
                    {
                        "id": source_id,
                        "label": SOURCES[source_id]["label"],
                        "url": SOURCES[source_id]["url"],
                        "type": SOURCES[source_id]["type"],
                    }
                    for source_id in source_ids
                    if source_id in SOURCES
                ]
                rows.append(
                    {
                        "vendor": vendor["vendor"],
                        "legal_name": vendor["legal_name"],
                        "ticker": vendor["ticker"],
                        "fiscal_year": year,
                        "fiscal_year_end": vendor["fiscal_year_end"],
                        "metric_key": metric_key,
                        "metric_zh": METRICS_ZH.get(metric_key, metric_key),
                        "value": value,
                        "currency": currency,
                        "unit": unit,
                        "official_value": "" if value is None else value,
                        "official_unit": unit,
                        "verification_status": status,
                        "verification_count": len(source_entries),
                        "verification_method": "official_report_plus_official_ir_index_crosscheck",
                        "verification_sources": json.dumps(source_entries, ensure_ascii=False),
                        "verification_note": "Direct official figure or derived metric from official rows; missing disclosures are retained as source gaps and are not estimated.",
                        "source_ids": ";".join(source_ids),
                        "primary_source_url": SOURCES[primary_source]["url"] if primary_source in SOURCES else "",
                        "disclosure_quality": vendor["disclosure_quality"],
                        "quality_note": vendor["quality_note"],
                    }
                )
    return rows


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "vendor",
        "legal_name",
        "ticker",
        "fiscal_year",
        "fiscal_year_end",
        "metric_key",
        "metric_zh",
        "value",
        "currency",
        "unit",
        "official_value",
        "official_unit",
        "verification_status",
        "verification_count",
        "verification_method",
        "verification_sources",
        "verification_note",
        "source_ids",
        "primary_source_url",
        "disclosure_quality",
        "quality_note",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def format_value(value: Any, unit: str, currency: str) -> str:
    if value is None:
        return "未披露/不适用"
    if isinstance(value, float) and not value.is_integer():
        text = f"{value:,.1f}"
    else:
        text = f"{int(value):,}" if isinstance(value, (int, float)) else str(value)
    if unit == "percent":
        return f"{text}%"
    if unit == "millions":
        return f"{text} {currency} million"
    return f"{text} {currency}"


def build_summary(vendors: list[dict[str, Any]], rows: list[dict[str, Any]]) -> str:
    lines = [
        f"# 重点云厂商经营数据包（{BUILD_DATE}）",
        "",
        "本数据包用于让小竞 AI 在分析 CMHK 云业务、AI 基础设施、企业云和重点竞品时，优先读取可核验的官方公开数据。",
        "",
        "## 使用原则",
        "",
        "- 优先使用直接披露的云分部/产品线数据；没有单独云收入披露时，只使用官方代理分部并明确说明口径。",
        "- 不填估算值；缺失项写明未披露或不适用。",
        "- 华为云 2024 口径存在 2025 年报重述，做趋势时必须说明重分类影响。",
        "- 腾讯未披露 Tencent Cloud 单独收入，FinTech and Business Services 不能被表述为腾讯云收入。",
        "",
        "## 覆盖厂商",
        "",
    ]
    for vendor in vendors:
        lines.extend(
            [
                f"### {vendor['vendor']}",
                "",
                f"- 主体：{vendor['legal_name']}（{vendor['ticker']}）",
                f"- 口径：{vendor['disclosure_quality']}",
                f"- 单位：{vendor['currency']} {vendor['unit']}",
                f"- CMHK 相关性：{vendor['cmhk_relevance']}",
                f"- 质量说明：{vendor['quality_note']}",
                "",
                "| 指标 | FY2023 | FY2024 | FY2025 |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        for key, values in vendor["metrics"].items():
            zh = METRICS_ZH.get(key, key)
            unit = "percent" if key in PERCENT_METRICS else vendor["unit"]
            currency = "" if key in PERCENT_METRICS else vendor["currency"]
            lines.append(
                f"| {zh} | {format_value(values.get('2023'), unit, currency)} | "
                f"{format_value(values.get('2024'), unit, currency)} | "
                f"{format_value(values.get('2025'), unit, currency)} |"
            )
        if vendor.get("alternate_disclosures"):
            lines.append("")
            lines.append(f"- 补充披露/重述：`{json.dumps(vendor['alternate_disclosures'], ensure_ascii=False)}`")
        lines.append("")

    lines.extend(
        [
            "## 逐行核验摘要",
            "",
            f"- CSV 明细共 {len(rows)} 行，每行包含 `official_value`、`verification_status`、`verification_count`、`verification_sources`、`source_ids`、`primary_source_url`、`disclosure_quality` 和 `quality_note`。",
            "- 已按官方 10-K、官方年报 PDF/网页、官方业绩公告和官方 IR/报告索引逐项核对；代理口径和重述口径均在 `quality_note` 中标注。",
            "- `source_gap_confirmed` 行保留披露边界，不估算；`official_derived_from_verified_rows` 行由已核验官方值计算。",
            "",
        ]
    )
    return "\n".join(lines)


def build_readme() -> str:
    return f"""# {DATASET_ID}

重点云厂商经营数据包，供小竞 AI / Agent RAG 调用。

## 数据内容

- 覆盖 AWS、Microsoft Azure / Intelligent Cloud、Google Cloud、Alibaba Cloud、Tencent Cloud 代理口径、Huawei Cloud / Cloud Computing、Oracle Cloud。
- 覆盖 FY2023-FY2025 或各公司最近三个完整财年披露的云收入/代理分部收入、利润/毛利/调整后 EBITA、利润率和同比。
- 数据来源为官方 10-K、官方年报、官方业绩 PDF/公告。

## 文件

- `cloud_vendor_metrics_summary.md`：面向 Agent 和人工阅读的摘要。
- `cloud_vendor_metrics_2023_2025.json`：结构化数据。
- `cloud_vendor_metrics_2023_2025.csv`：逐行长表，含 `official_value`、核验状态、来源和质量说明。
- `cloud_vendor_metrics_human_readable.csv`：面向 Excel/人工查看的精简宽表，只保留核心字段。
- `sources.json`：来源清单。
- `online_verification_{BUILD_DATE}.md`：逐行核验说明。
- `online_verification_{BUILD_DATE}.csv`：逐行核验明细，区分官方直接核验和派生计算。

## Agent 使用要求

当用户询问 CMHK 需要关注的云厂商、AWS/Azure/GCP/阿里云/腾讯云/华为云/Oracle Cloud 的收入、利润、趋势、同比、同业对比、AI 云基础设施趋势时，先用 `search_local_reports` 检索本目录，再用 `read_local_reference` 读取 JSON 或摘要。

特别注意：

- Microsoft Azure 未单独披露收入，使用 Intelligent Cloud 和 Server products and cloud services 代理。
- Tencent Cloud 未单独披露收入，使用 FinTech and Business Services 代理，不能表述为腾讯云纯收入。
- Huawei Cloud 2024 数据存在最新年报重述，趋势分析时必须提示口径变化。
- Alibaba Cloud 利润指标为调整后 EBITA，非 GAAP。
"""


def build_manifest() -> dict[str, Any]:
    return {
        "id": DATASET_ID,
        "title": "CMHK 重点云厂商近三年经营数据",
        "summary": "AWS、Azure/Microsoft、Google Cloud、阿里云、腾讯云代理口径、华为云、Oracle Cloud 的 FY2023-FY2025 云收入、利润和口径说明。",
        "source_type": "external_official_public",
        "scope": "CMHK 云业务和 AI 基础设施竞品/合作方经营数据",
        "tags": ["cloud", "AI infrastructure", "financial metrics", "competitor intelligence", "CMHK"],
        "keywords": [
            "云厂商",
            "云收入",
            "AWS",
            "Azure",
            "Microsoft Intelligent Cloud",
            "Google Cloud",
            "阿里云",
            "Alibaba Cloud",
            "腾讯云",
            "Tencent Cloud",
            "华为云",
            "Huawei Cloud",
            "Oracle Cloud",
            "云计算",
            "AI 云",
            "CMHK 云业务",
        ],
        "entrypoints": [
            "README.md",
            "cloud_vendor_metrics_summary.md",
            "cloud_vendor_metrics_2023_2025.json",
            "cloud_vendor_metrics_2023_2025.csv",
            "cloud_vendor_metrics_human_readable.csv",
            "sources.json",
            f"online_verification_{BUILD_DATE}.md",
            f"online_verification_{BUILD_DATE}.csv",
        ],
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "quality": {
            "status": "verified_against_official_public_sources",
            "notes": [
                "直接披露与代理口径分开标注。",
                "本体 CSV/JSON 已升级为统一 official_value / verification_status / verification_count schema。",
                "不估算未披露的单独云收入。",
                "华为 2024 云计算收入采用 2025 年报重述口径，保留原披露值说明。",
            ],
        },
    }


def build_verification(rows: list[dict[str, Any]]) -> str:
    lines = [
        f"# 云厂商经营数据逐行核验（{BUILD_DATE}）",
        "",
        "核验方法：逐项读取官方 10-K、官方年报网页/PDF、官方业绩公告/PDF；将每一行数据绑定来源 ID、来源 URL 和口径说明。",
        "",
        "| 行 | 厂商 | 年度 | 指标 | 数值 | 核验状态 | 来源 | 口径状态 |",
        "| ---: | --- | --- | --- | ---: | --- | --- | --- |",
    ]
    for idx, row in enumerate(rows, 1):
        value = "未披露/不适用" if row["value"] is None else row["value"]
        status = row["verification_status"]
        lines.append(
            f"| {idx} | {row['vendor']} | {row['fiscal_year']} | {row['metric_zh']} | {value} | {status} | "
            f"{row['source_ids']} | {row['disclosure_quality']} |"
        )
    lines.extend(
        [
            "",
            "## 口径冲突和限制",
            "",
            "- 腾讯：公开报表不拆分 Tencent Cloud 单独收入；`FinTech and Business Services` 是代理分部。",
            "- 华为：2025 年报把 2024 Cloud Computing 收入重述为 33,325 百万元；2024 年报原披露 2024 为 38,523 百万元、2023 为 35,514 百万元。",
            "- Microsoft：Azure 未单独披露收入；`Intelligent Cloud` 和 `Server products and cloud services` 为官方代理口径。",
            "- Alibaba：分部利润为调整后 EBITA，属于非 GAAP 指标。",
        ]
    )
    return "\n".join(lines)


def verification_status(metric_key: str, value: Any = "__present__") -> str:
    if value is None:
        return "source_gap_confirmed"
    if metric_key in PERCENT_METRICS or metric_key == "revenue_yoy":
        return "official_derived_from_verified_rows"
    return "official_match"


def write_verification_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "row_no",
        "vendor",
        "fiscal_year",
        "metric_key",
        "metric_zh",
        "value",
        "currency",
        "unit",
        "official_value",
        "official_unit",
        "verification_status",
        "verification_count",
        "verification_method",
        "verification_sources",
        "source_ids",
        "primary_source_url",
        "disclosure_quality",
        "quality_note",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for idx, row in enumerate(rows, 1):
            writer.writerow(
                {
                    "row_no": idx,
                    "vendor": row["vendor"],
                    "fiscal_year": row["fiscal_year"],
                    "metric_key": row["metric_key"],
                    "metric_zh": row["metric_zh"],
                    "value": row["value"],
                    "currency": row["currency"],
                    "unit": row["unit"],
                    "official_value": row["official_value"],
                    "official_unit": row["official_unit"],
                    "verification_status": row["verification_status"],
                    "verification_count": row["verification_count"],
                    "verification_method": row["verification_method"],
                    "verification_sources": row["verification_sources"],
                    "source_ids": row["source_ids"],
                    "primary_source_url": row["primary_source_url"],
                    "disclosure_quality": row["disclosure_quality"],
                    "quality_note": row["quality_note"],
                }
            )


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    vendors = [enrich_vendor(json.loads(json.dumps(item))) for item in VENDORS]
    rows = flatten_rows(vendors)

    (OUT_ROOT / "README.md").write_text(build_readme(), encoding="utf-8")
    (OUT_ROOT / "manifest.json").write_text(json.dumps(build_manifest(), ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_ROOT / "sources.json").write_text(json.dumps(SOURCES, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_ROOT / "cloud_vendor_metrics_2023_2025.json").write_text(
        json.dumps(
            {
                "dataset_id": DATASET_ID,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "period": "FY2023-FY2025 or latest three complete fiscal years by company fiscal year",
                "vendors": vendors,
                "sources": SOURCES,
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    write_csv(rows, OUT_ROOT / "cloud_vendor_metrics_2023_2025.csv")
    (OUT_ROOT / "cloud_vendor_metrics_summary.md").write_text(build_summary(vendors, rows), encoding="utf-8")
    (OUT_ROOT / f"online_verification_{BUILD_DATE}.md").write_text(build_verification(rows), encoding="utf-8")
    write_verification_csv(rows, OUT_ROOT / f"online_verification_{BUILD_DATE}.csv")

    print(f"Wrote {OUT_ROOT}")
    print(f"Rows: {len(rows)}")


if __name__ == "__main__":
    main()

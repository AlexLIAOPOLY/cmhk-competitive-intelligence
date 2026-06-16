from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
BUILD_DATE = os.environ.get("CMHK_METRICS_BUILD_DATE") or date.today().isoformat()
OUT_ROOT = ROOT / "agent_knowledge" / f"core_company_metrics_{BUILD_DATE}"


@dataclass(frozen=True)
class CompanySpec:
    subject: str
    legal_name: str
    ticker: str | None
    stockanalysis_slug: str | None
    listed: bool
    notes: str = ""


COMPANIES = [
    CompanySpec("中国移动", "China Mobile Limited", "0941.HK", "0941", True),
    CompanySpec("中国电信", "China Telecom Corporation Limited", "0728.HK", "0728", True),
    CompanySpec("中国联通", "China Unicom (Hong Kong) Limited", "0762.HK", "0762", True),
    CompanySpec("中国铁塔", "China Tower Corporation Limited", "0788.HK", "0788", True),
    CompanySpec("HKT / csl / 1O1O", "HKT Trust and HKT Limited", "6823.HK", "6823", True),
    CompanySpec("3HK / Hutchison", "Hutchison Telecommunications Hong Kong Holdings Limited", "0215.HK", "0215", True),
    CompanySpec("SmarTone", "SmarTone Telecommunications Holdings Limited", "0315.HK", "0315", True),
    CompanySpec("HKBN", "HKBN Ltd.", "1310.HK", "1310", True),
    CompanySpec(
        "HGC",
        "HGC Global Communications Limited",
        None,
        None,
        False,
        "非上市主体，未稳定公开三年完整财务报表；只记录公开可核验说明，不填造财务数值。",
    ),
    CompanySpec("i-CABLE", "i-CABLE Communications Limited", "1097.HK", "1097", True),
]


METRIC_MAP = {
    "Revenue": ("revenue", "营业收入/收益"),
    "Revenue Growth (YoY)": ("revenue_growth_yoy", "收入同比增长"),
    "Cost of Revenue": ("cost_of_revenue", "营业成本/销售成本"),
    "Gross Profit": ("gross_profit", "毛利"),
    "Gross Margin": ("gross_margin", "毛利率"),
    "Operating Income": ("operating_income", "经营利润/营业利润"),
    "Operating Margin": ("operating_margin", "经营利润率"),
    "Pretax Income": ("pretax_income", "税前利润"),
    "Income Tax": ("income_tax", "所得税"),
    "Net Income": ("net_income", "净利润/股东应占利润"),
    "Net Income Growth": ("net_income_growth", "净利润同比增长"),
    "Net Margin": ("net_margin", "净利率"),
    "EBITDA": ("ebitda", "EBITDA"),
    "EBITDA Margin": ("ebitda_margin", "EBITDA率"),
    "EPS (Basic)": ("eps_basic", "每股基本盈利"),
    "EPS (Diluted)": ("eps_diluted", "每股摊薄盈利"),
    "Operating Cash Flow": ("operating_cash_flow", "经营现金流"),
    "Capital Expenditures": ("capital_expenditures", "资本开支"),
    "Free Cash Flow": ("free_cash_flow", "自由现金流"),
    "Free Cash Flow Margin": ("free_cash_flow_margin", "自由现金流率"),
    "Cash & Equivalents": ("cash_and_equivalents", "现金及等价物"),
    "Total Assets": ("total_assets", "总资产"),
    "Total Debt": ("total_debt", "总债务"),
    "Net Cash / Debt": ("net_cash_debt", "净现金/净债务"),
}

IMPORTANT_KEYS = [
    "revenue",
    "revenue_growth_yoy",
    "gross_profit",
    "gross_margin",
    "operating_income",
    "operating_margin",
    "net_income",
    "net_margin",
    "ebitda",
    "ebitda_margin",
    "operating_cash_flow",
    "capital_expenditures",
    "free_cash_flow",
    "cash_and_equivalents",
    "total_assets",
    "total_debt",
]


def fetch(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
    }
    with httpx.Client(headers=headers, follow_redirects=True, timeout=30) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def parse_stockanalysis_page(url: str) -> tuple[dict[str, dict[str, str]], str]:
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    unit_match = re.search(r"Financials in millions ([A-Z]{3})", text)
    unit = f"millions {unit_match.group(1)}" if unit_match else "millions"
    table = soup.find("table")
    if not table:
        raise RuntimeError(f"未找到财务表：{url}")
    rows = table.find_all("tr")
    if not rows:
        raise RuntimeError(f"财务表为空：{url}")
    headers = [cell.get_text(" ", strip=True) for cell in rows[0].find_all(["th", "td"])]
    fiscal_columns: list[tuple[int, str]] = []
    for idx, header in enumerate(headers):
        match = re.fullmatch(r"FY\s+(\d{4})", header)
        if match and match.group(1) in {"2023", "2024", "2025"}:
            fiscal_columns.append((idx, match.group(1)))

    parsed: dict[str, dict[str, str]] = {}
    for tr in rows[1:]:
        cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
        if not cells:
            continue
        label = cells[0]
        metric = METRIC_MAP.get(label)
        if not metric:
            continue
        key, _zh = metric
        parsed[key] = {}
        for idx, year in fiscal_columns:
            parsed[key][year] = cells[idx] if idx < len(cells) else ""
    return parsed, unit


def merge_metric_pages(slug: str) -> tuple[dict[str, dict[str, str]], list[dict[str, str]], str]:
    pages = [
        ("income_statement", f"https://stockanalysis.com/quote/hkg/{slug}/financials/"),
        ("balance_sheet", f"https://stockanalysis.com/quote/hkg/{slug}/financials/balance-sheet/"),
        ("cash_flow", f"https://stockanalysis.com/quote/hkg/{slug}/financials/cash-flow-statement/"),
    ]
    merged: dict[str, dict[str, str]] = {}
    sources: list[dict[str, str]] = []
    units: list[str] = []
    for source_type, url in pages:
        parsed, unit = parse_stockanalysis_page(url)
        merged.update(parsed)
        units.append(unit)
        sources.append({"label": f"StockAnalysis {source_type}", "url": url, "type": "normalized_financials"})
    unit = next((item for item in units if item and item != "millions"), units[0] if units else "millions")
    return merged, sources, unit


def load_official_sources() -> dict[str, list[dict[str, str]]]:
    path = ROOT / "carrier_performance_sources.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, list[dict[str, str]]] = {}
    companies = data.get("companies") or {}
    for subject, payload in companies.items():
        items = []
        for item in payload.get("sources") or []:
            if item.get("type") == "broker_view":
                continue
            label = str(item.get("label") or "").strip()
            url = str(item.get("url") or "").strip()
            source_type = str(item.get("type") or "").strip()
            if label and url:
                items.append({"label": label, "url": url, "type": source_type or "project_source"})
        out[subject] = items
    return out


def pct_change(current: str, previous: str) -> str:
    def as_float(value: str) -> float | None:
        clean = value.replace(",", "").replace("%", "").strip()
        if clean in {"", "-"}:
            return None
        try:
            return float(clean)
        except ValueError:
            return None

    cur = as_float(current)
    prev = as_float(previous)
    if cur is None or prev in {None, 0}:
        return ""
    return f"{(cur / prev - 1) * 100:.1f}%"


def build_company_record(spec: CompanySpec, official_sources: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
    record: dict[str, Any] = {
        "subject": spec.subject,
        "legal_name": spec.legal_name,
        "ticker": spec.ticker,
        "period": "FY2023-FY2025",
        "unit": None,
        "metrics": {},
        "sources": official_sources.get(spec.subject, []),
        "quality_notes": [],
    }
    if not spec.listed or not spec.stockanalysis_slug:
        record["unit"] = "not disclosed"
        record["quality_notes"].append(spec.notes)
        return record
    try:
        metrics, sources, unit = merge_metric_pages(spec.stockanalysis_slug)
        record["metrics"] = {key: metrics.get(key, {}) for key in IMPORTANT_KEYS if metrics.get(key)}
        record["unit"] = unit
        record["sources"].extend(sources)
        if "revenue" in metrics and "net_income" in metrics:
            record["three_year_trend"] = {
                "revenue_2023_to_2025": pct_change(metrics["revenue"].get("2025", ""), metrics["revenue"].get("2023", "")),
                "net_income_2023_to_2025": pct_change(metrics["net_income"].get("2025", ""), metrics["net_income"].get("2023", "")),
            }
        record["quality_notes"].append(
            "三年财务表采用 StockAnalysis 对港股公告的标准化表格；回答正式结论时应优先引用官方年报/业绩公告复核关键数。"
        )
    except Exception as exc:
        record["quality_notes"].append(f"抓取标准化财务表失败：{exc}")
    return record


def write_csv(records: list[dict[str, Any]], path: Path) -> None:
    rows: list[dict[str, str]] = []
    for record in records:
        for metric_key, by_year in (record.get("metrics") or {}).items():
            zh = METRIC_MAP.get(next((k for k, v in METRIC_MAP.items() if v[0] == metric_key), ""), (metric_key, metric_key))[1]
            for year in ["2023", "2024", "2025"]:
                rows.append(
                    {
                        "subject": record["subject"],
                        "legal_name": record["legal_name"],
                        "ticker": record.get("ticker") or "",
                        "metric_key": metric_key,
                        "metric_zh": zh,
                        "year": year,
                        "value": by_year.get(year, ""),
                        "unit": record.get("unit") or "",
                    }
                )
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["subject", "legal_name", "ticker", "metric_key", "metric_zh", "year", "value", "unit"])
        writer.writeheader()
        writer.writerows(rows)


def markdown_table(record: dict[str, Any]) -> str:
    lines = [
        f"## {record['subject']}",
        "",
        f"- 主体：{record['legal_name']}",
        f"- 股票/状态：{record.get('ticker') or '非上市或未公开完整财务表'}",
        f"- 期间：{record['period']}",
        f"- 单位：{record.get('unit') or '未识别'}",
    ]
    if record.get("three_year_trend"):
        trend = record["three_year_trend"]
        lines.append(f"- 三年趋势：收入 2023-2025 变化 {trend.get('revenue_2023_to_2025') or 'N/A'}；净利润 2023-2025 变化 {trend.get('net_income_2023_to_2025') or 'N/A'}")
    lines.append("")
    metrics = record.get("metrics") or {}
    if metrics:
        lines.extend(["| 指标 | 2023 | 2024 | 2025 |", "| --- | ---: | ---: | ---: |"])
        metric_lookup = {v[0]: v[1] for v in METRIC_MAP.values()}
        for key in IMPORTANT_KEYS:
            if key not in metrics:
                continue
            by_year = metrics[key]
            lines.append(f"| {metric_lookup.get(key, key)} | {by_year.get('2023', '')} | {by_year.get('2024', '')} | {by_year.get('2025', '')} |")
    else:
        lines.append("未找到可稳定公开抓取的三年完整财务表；不得补写估算值。")
    lines.append("")
    if record.get("quality_notes"):
        lines.append("数据质量说明：")
        for note in record["quality_notes"]:
            lines.append(f"- {note}")
    lines.append("")
    lines.append("来源：")
    for index, item in enumerate(record.get("sources") or [], 1):
        lines.append(f"- [{index}] {item.get('label')} ({item.get('type')}): {item.get('url')}")
    return "\n".join(lines).strip()


def write_markdown(records: list[dict[str, Any]], path: Path) -> None:
    generated_at = f"{BUILD_DATE}T{datetime.now().strftime('%H:%M:%S')}"
    lines = [
        "# 主体公司近三年核心经营/财务数据包",
        "",
        f"- 生成时间：{generated_at}",
        "- 覆盖主体：中国移动、中国电信、中国联通、中国铁塔、HKT / csl / 1O1O、3HK / Hutchison、SmarTone、HKBN、HGC、i-CABLE。",
        "- 覆盖期间：FY2023-FY2025。",
        "- 券商观点：按用户要求不纳入本数据包。",
        "- 使用规则：趋势分析优先读取 JSON/CSV；面向用户回答时使用本 Markdown 的主体表格和来源说明；对关键结论应说明本地标准化数据与官方公告口径是否一致。",
        "",
    ]
    for record in records:
        lines.append(markdown_table(record))
        lines.append("")
        lines.append("---")
        lines.append("")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def write_readme(path: Path) -> None:
    text = f"""# core_company_metrics_{BUILD_DATE}

这是一份供小竞 AI / Agent 使用的主体公司近三年核心经营与财务数据包。

## 文件

- `core_metrics_summary.md`：人工可读摘要，按公司列出 FY2023-FY2025 主要数据、趋势和来源。
- `core_metrics_2023_2025.json`：结构化数据，适合 Agent 做趋势分析、同业比较和口径检查。
- `core_metrics_2023_2025.csv`：长表格式，适合表格分析。
- `sources.json`：所有官方/标准化财务表来源链接和数据质量说明。

## Agent 使用要求

1. 用户询问主体公司历史经营/财务趋势、收入、利润、毛利率、EBITDA、资本开支、现金流、同业对比时，优先检索并读取本文件夹。
2. 先用 `core_metrics_2023_2025.json` 或 `core_metrics_2023_2025.csv` 获取结构化数值，再用 `core_metrics_summary.md` 获取口径说明和来源。
3. 不使用券商观点作为事实依据；本数据包已按用户要求剔除券商观点。
4. HGC 为非上市主体，公开三年完整财务数据不足；回答时必须说明不可比，不得估算。
5. 对关键结论要带来源；若本地标准化数据与联网官方公告有差异，要明确列出差异和建议采用口径。
"""
    path.write_text(text, encoding="utf-8")


def write_manifest(path: Path) -> None:
    manifest = {
        "id": f"core-company-metrics-{BUILD_DATE}",
        "title": f"主体公司近三年核心经营/财务数据包（{BUILD_DATE}）",
        "summary": "覆盖中国移动、中国电信、中国联通、中国铁塔、HKT / csl / 1O1O、3HK / Hutchison、SmarTone、HKBN、HGC、i-CABLE 的 FY2023-FY2025 主要经营和财务指标，用于趋势分析、同业对比、问数和图表。",
        "source_type": "external_normalized",
        "scope": "公开年报、业绩公告和 StockAnalysis 标准化财务表；不包含券商观点。",
        "tags": ["finance", "carrier", "core_metrics", "trend", "competitor"],
        "keywords": [
            "近三年",
            "核心数据",
            "趋势",
            "收入",
            "净利润",
            "毛利率",
            "EBITDA",
            "资本开支",
            "现金流",
            "中国移动",
            "中国电信",
            "中国联通",
            "中国铁塔",
            "HKT",
            "3HK",
            "SmarTone",
            "HKBN",
            "HGC",
            "i-CABLE",
        ],
        "entrypoints": [
            "README.md",
            "core_metrics_summary.md",
            "core_metrics_2023_2025.json",
            "core_metrics_2023_2025.csv",
            "sources.json",
        ],
        "updated_at": BUILD_DATE,
        "quality": "关键结论应优先用官方年报或业绩公告复核；HGC 非上市主体公开三年完整财务数据不足，不得估算。",
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    official_sources = load_official_sources()
    records = [build_company_record(spec, official_sources) for spec in COMPANIES]
    payload = {
        "generated_at": f"{BUILD_DATE}T{datetime.now().strftime('%H:%M:%S')}",
        "period": "FY2023-FY2025",
        "excluded": ["broker_view"],
        "companies": records,
    }
    (OUT_ROOT / "core_metrics_2023_2025.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(records, OUT_ROOT / "core_metrics_2023_2025.csv")
    write_markdown(records, OUT_ROOT / "core_metrics_summary.md")
    sources = {
        "generated_at": payload["generated_at"],
        "sources_by_company": {record["subject"]: record.get("sources") or [] for record in records},
        "quality_notes_by_company": {record["subject"]: record.get("quality_notes") or [] for record in records},
    }
    (OUT_ROOT / "sources.json").write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8")
    write_readme(OUT_ROOT / "README.md")
    write_manifest(OUT_ROOT / "manifest.json")
    print(OUT_ROOT)


if __name__ == "__main__":
    main()

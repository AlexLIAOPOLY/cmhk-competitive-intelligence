#!/usr/bin/env python3
"""Audit common disclosure coverage and strict three-source evidence across CMHK data.

The user-facing quality rule is deliberately stricter than the legacy
``verification_count`` field: three sections, snapshots, or labels pointing to
the same URL are one source document.  Existing values are never deleted by
this audit; values below the threshold are recorded as a collection backlog.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from source_document_identity import canonical_source_document_identity, is_derived_value


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "agent_knowledge"
OUT = KNOWLEDGE / "knowledge_integrity_audits"
AUDIT_DATE = date.today().isoformat()


def latest_quarterly_dataset_path() -> Path:
    candidates = [
        folder
        for folder in KNOWLEDGE.glob("quarterly_competitor_metrics_*")
        if folder.is_dir() and (folder / "quarterly_metrics.csv").exists()
    ]
    if not candidates:
        return KNOWLEDGE / "quarterly_competitor_metrics_2026-06-18"
    return max(candidates, key=lambda folder: folder.name)


LATEST_QUARTERLY = latest_quarterly_dataset_path()


DATASETS = [
    {
        "id": LATEST_QUARTERLY.name,
        "path": LATEST_QUARTERLY / "quarterly_metrics.csv",
        "kind": "embedded_urls",
        "value": "official_value",
        "metric": "metric_key",
        "subject": "subject",
        "period": "period",
    },
    {
        "id": "cmhk_macro_policy_2026-06-19",
        "path": KNOWLEDGE / "cmhk_macro_policy_2026-06-19" / "macro_policy_metrics.csv",
        "kind": "embedded_urls",
        "value": "official_value",
        "metric": "metric_key",
        "subject": "subject",
        "period": "period",
    },
    {
        "id": "global_top5_operators_2016_2025",
        "path": KNOWLEDGE / "global_top5_operators_2016_2025" / "annual_metrics.csv",
        "kind": "source_ids",
        "registry": KNOWLEDGE / "global_top5_operators_2016_2025" / "sources.json",
        "value": "official_value",
        "metric": "metric_key",
        "subject": "operator",
        "period": "period",
    },
    {
        "id": "local_hk_operator_operating_metrics_2016_2025",
        "path": KNOWLEDGE / "local_hk_operator_operating_metrics_2016_2025" / "annual_metrics.csv",
        "kind": "source_ids",
        "registry": KNOWLEDGE / "local_hk_operator_operating_metrics_2016_2025" / "sources.json",
        "value": "official_value",
        "metric": "metric_key",
        "subject": "operator",
        "period": "period",
    },
    {
        "id": "competitor_product_tariffs",
        "path": KNOWLEDGE / "competitor_product_tariffs" / "product_tariffs_formal_agent_records.csv",
        "kind": "tariff",
        "value": "月费_HKD",
        "metric": "产品类别",
        "subject": "品牌",
        "period": "期间",
    },
]


# Baseline covers fields commonly published by listed carriers, cloud vendors,
# regulators/statistics agencies, and telecom product pages.  It is an audit
# vocabulary, not permission to estimate an undisclosed value.
COMMON_DISCLOSURES = {
    LATEST_QUARTERLY.name: [
        ("revenue", "收入", "financial", "high"),
        ("service_revenue", "服务收入", "financial", "high"),
        ("operating_income", "经营利润", "financial", "high"),
        ("ebitda", "EBITDA", "financial", "high"),
        ("ebitda_margin", "EBITDA利润率", "financial", "high"),
        ("net_income", "净利润", "financial", "high"),
        ("capital_expenditures", "资本开支", "financial", "high"),
        ("operating_cash_flow", "经营现金流", "financial", "medium"),
        ("free_cash_flow", "自由现金流", "financial", "medium"),
        ("net_debt", "净负债", "financial", "medium"),
        ("dividend_per_share", "每股股息", "financial", "medium"),
        ("employees", "员工数", "financial", "low"),
        ("cloud_revenue", "云收入", "cloud", "high"),
        ("cloud_revenue_growth", "云收入增长", "cloud", "high"),
        ("cloud_operating_income", "云经营利润", "cloud", "high"),
        ("cloud_operating_margin", "云经营利润率", "cloud", "high"),
        ("remaining_performance_obligations", "剩余履约义务/RPO", "cloud", "medium"),
        ("cloud_backlog", "云订单积压", "cloud", "medium"),
        ("cloud_regions", "云区域数", "cloud", "low"),
        ("availability_zones", "可用区数", "cloud", "low"),
        ("data_centers", "数据中心数", "cloud", "low"),
    ],
    "global_top5_operators_2016_2025": [
        ("mobile_subscribers", "移动用户", "operating", "high"),
        ("4g_subscribers", "4G用户", "operating", "medium"),
        ("5g_package_subscribers", "5G套餐用户", "operating", "high"),
        ("5g_network_subscribers", "5G网络用户", "operating", "high"),
        ("fixed_broadband_subscribers", "固网宽带用户", "operating", "high"),
        ("mobile_arpu", "移动ARPU", "operating", "high"),
        ("broadband_arpu", "宽带ARPU", "operating", "medium"),
        ("household_customer_blended_arpu", "家庭客户综合ARPU", "operating", "medium"),
        ("mobile_dou", "户均移动流量DOU", "operating", "high"),
        ("handset_data_traffic", "手机数据流量", "operating", "high"),
        ("total_base_stations", "基站总数", "network", "medium"),
        ("4g_base_stations", "4G基站", "network", "medium"),
        ("5g_base_stations", "5G基站", "network", "high"),
        ("churn", "用户流失率", "operating", "medium"),
        ("5g_population_coverage", "5G人口覆盖率", "network", "medium"),
        ("spectrum_holdings", "频谱持有量", "network", "low"),
        ("iot_connections", "物联网连接", "operating", "high"),
        ("integrated_broadband_network_customers", "融合宽带网络客户", "operating", "medium"),
        ("gigabit_broadband_customers", "千兆宽带客户", "operating", "medium"),
        ("mobile_broadband_integration_rate", "移动宽带融合率", "operating", "medium"),
        ("government_enterprise_customers", "政企客户", "operating", "medium"),
        ("total_connectivity_subscribers", "连接用户总规模", "operating", "medium"),
        ("integrated_subscriber_penetration", "融合用户渗透率", "operating", "medium"),
        ("integrated_package_arpu", "融合套餐ARPU", "operating", "medium"),
        ("5g_network_penetration", "5G网络用户渗透率", "operating", "high"),
        ("gigabit_broadband_penetration", "千兆宽带渗透率", "operating", "medium"),
        ("mobile_population_coverage", "移动网络人口覆盖率", "network", "medium"),
        ("5g_a_deployment_cities", "5G-A部署城市", "network", "medium"),
        ("ten_g_pon_ports", "10G PON端口", "network", "low"),
        ("urban_gigabit_coverage", "城市千兆覆盖率", "network", "medium"),
        ("households_gigabit_coverage", "千兆网络覆盖家庭", "network", "medium"),
        ("intelligent_compute_capacity", "智能算力", "digital", "medium"),
        ("cloud_ai_product_users", "云AI产品用户", "digital", "medium"),
    ],
    "local_hk_operator_operating_metrics_2016_2025": [
        ("total_customers", "总客户", "operating", "high"),
        ("mobile_postpaid_customers", "后付用户", "operating", "high"),
        ("mobile_prepaid_customers", "预付用户", "operating", "medium"),
        ("5g_customers", "5G用户", "operating", "high"),
        ("5g_penetration", "5G渗透率", "operating", "medium"),
        ("consumer_broadband_customers", "住宅宽带用户", "operating", "high"),
        ("ftth_connections", "FTTH连接", "operating", "medium"),
        ("homes_passed_or_connected", "覆盖/连接住户", "network", "medium"),
        ("mobile_postpaid_arpu", "后付ARPU", "operating", "high"),
        ("mobile_postpaid_churn", "后付流失率", "operating", "medium"),
        ("mobile_data_dou", "户均移动流量DOU", "operating", "high"),
        ("annual_mobile_data_traffic", "年度移动数据流量", "operating", "high"),
        ("total_base_stations", "基站总数", "network", "medium"),
        ("5g_base_stations", "5G基站", "network", "high"),
        ("5g_population_coverage", "5G人口覆盖率", "network", "medium"),
        ("spectrum_holdings", "频谱持有量", "network", "low"),
    ],
    "cmhk_macro_policy_2026-06-19": [
        ("population", "人口", "demography", "high"),
        ("households", "住户数", "demography", "medium"),
        ("median_monthly_household_income", "住户月入中位数", "economy", "high"),
        ("nominal_gdp", "名义GDP", "economy", "high"),
        ("real_gdp_growth", "实际GDP增长", "economy", "high"),
        ("consumer_price_index", "消费物价指数", "economy", "high"),
        ("unemployment_rate", "失业率", "economy", "high"),
        ("retail_sales", "零售销售", "economy", "medium"),
        ("mobile_subscriptions", "移动用户/登记数", "telecom_market", "high"),
        ("fixed_broadband_subscriptions", "固定宽带登记数", "telecom_market", "high"),
        ("5g_subscriptions", "5G登记数", "telecom_market", "high"),
        ("mobile_data_traffic", "移动数据流量", "telecom_market", "high"),
        ("mobile_number_porting", "携号转网", "telecom_market", "medium"),
        ("telecom_complaints", "电讯投诉", "telecom_market", "medium"),
        ("spectrum_assignments", "频谱分配", "telecom_market", "medium"),
    ],
    "competitor_product_tariffs": [
        ("月费_HKD", "月费", "pricing", "high"),
        ("平均月费_HKD", "平均月费", "pricing", "high"),
        ("公开价格_HKD", "公开价格", "pricing", "medium"),
        ("合约月数", "合约期", "terms", "high"),
        ("本地数据_GB", "本地数据量", "allowance", "high"),
        ("漫游数据_GB", "漫游数据量", "allowance", "high"),
        ("宽频速度_Mbps", "宽带速度", "service", "high"),
        ("限速_Mbps", "FUP后限速", "service", "medium"),
        ("本地语音", "本地语音", "allowance", "medium"),
        ("附加收费_HKD", "附加/行政/安装费用", "pricing", "medium"),
        ("网络代际", "网络代际", "service", "medium"),
        ("客户分段", "客户分段/资格", "terms", "medium"),
        ("生效日期", "生效日期", "terms", "high"),
        ("终止日期", "终止日期", "terms", "medium"),
        ("设备费用_HKD", "设备/路由器费用", "pricing", "medium"),
        ("漫游覆盖", "漫游覆盖地区", "service", "medium"),
        ("优惠赠品", "回赠/赠品", "promotion", "low"),
    ],
}

# Canonical audit concepts can be represented by a more specific source metric
# key.  Alias matching prevents the gap report from treating an already
# collected series as absent merely because its schema name is more precise.
METRIC_ALIASES = {
    "cloud_revenue_growth": ["cloud_revenue_growth_yoy"],
    "real_gdp_growth": ["percentage_change_of_gross_domestic_product_and_selected_major_expenditure_components_in_real_terms_con"],
    "consumer_price_index": [
        "consumer_price_indices_a_cm_1920",
        "consumer_price_indices_b_cm_1920",
        "consumer_price_indices_c_cm_1920",
        "consumer_price_indices_cc_cm_1920",
    ],
    "unemployment_rate": ["statistics_on_labour_force_employment_unemployment_and_underemployment_ur"],
    "retail_sales": ["total_retail_sales_val_rs", "total_retail_sales_val_idx_rs", "total_retail_sales_vol_idx_rs"],
    "fixed_broadband_subscriptions": [
        "registered_subscriptions_with_broadband_access",
        "broadband_access_lines_total",
        "broadband_customer_accounts_total",
    ],
    "mobile_data_traffic": ["mobile_data_usage_total_mbytes"],
    "telecom_complaints": ["telecom_consumer_complaints_total"],
    "spectrum_assignments": ["5g_spectrum_assigned_mhz"],
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def is_value(value: Any) -> bool:
    return str(value or "").strip().lower() not in {"", "n/a", "na", "none", "null", "-"}


def normalized_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not re.match(r"^https?://", raw, re.I):
        return ""
    parts = urlsplit(raw)
    # Fragments only identify a location inside the same source document.
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))


def source_registry(path: Path | None) -> dict[str, dict[str, Any]]:
    if not path or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("sources", []) if isinstance(payload, dict) else payload
    return {str(item.get("source_id") or item.get("id")): item for item in entries if isinstance(item, dict)}


def parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(str(value or "[]"))
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def source_documents_for_row(
    row: dict[str, str], config: dict[str, Any], registry: dict[str, dict[str, Any]]
) -> tuple[set[str], set[str]]:
    """Return canonical document identities and their known URLs.

    ``source_document_id`` takes precedence over URL so mirrors of one
    disclosure cannot inflate the independent-document count. Legacy rows fall
    back to normalized URLs.
    """
    documents: set[str] = set()
    urls: set[str] = set()
    primary_urls = {
        url
        for field in ["official_source_url", "primary_source_url", "来源URL"]
        if (url := normalized_url(row.get(field)))
    }
    urls.update(primary_urls)
    if config["kind"] == "embedded_urls":
        source_urls: set[str] = set()
        for item in parse_json_list(row.get("verification_sources")):
            if isinstance(item, dict):
                url = normalized_url(item.get("url"))
                if url:
                    urls.add(url)
                    source_urls.add(url)
                if identity := canonical_source_document_identity(item, fallback_url=url):
                    documents.add(identity)
        documents.update(f"url:{url}" for url in primary_urls - source_urls)
    elif config["kind"] == "source_ids":
        for source_id in parse_json_list(row.get("verification_sources")):
            item = registry.get(str(source_id), {})
            if url := normalized_url(item.get("url")):
                urls.add(url)
                documents.add(canonical_source_document_identity(item, fallback_url=url))
        if not documents:
            documents.update(f"url:{url}" for url in primary_urls)
    else:
        documents.update(f"url:{url}" for url in primary_urls)
    # Archive snapshots are evidence preservation for the same page, not an
    # independent source, and are intentionally not counted here.
    return documents, urls


def row_key(row: dict[str, str], config: dict[str, Any]) -> str:
    parts = [row.get(config["subject"], ""), row.get(config["period"], ""), row.get(config["metric"], "")]
    if config["id"] == "competitor_product_tariffs":
        parts.extend([row.get("套餐名称", ""), row.get("记录键", "")])
    return " | ".join(str(item).strip() for item in parts if str(item).strip())


def audit_dataset(config: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, str]]]:
    rows = read_csv(config["path"])
    registry = source_registry(config.get("registry"))
    available = [row for row in rows if is_value(row.get(config["value"]))]
    backlog: list[dict[str, Any]] = []
    distinct_counts: Counter[int] = Counter()
    legacy_inflation = 0
    certified = 0
    for row in available:
        documents, urls = source_documents_for_row(row, config, registry)
        count = len(documents)
        distinct_counts[count] += 1
        try:
            legacy = int(float(str(row.get("verification_count") or row.get("核验次数") or 0)))
        except ValueError:
            legacy = 0
        if legacy >= 3 and count < 3:
            legacy_inflation += 1
        derived = is_derived_value(row)
        if count >= 3 and not derived:
            certified += 1
        else:
            backlog.append({
                "dataset_id": config["id"],
                "row_key": row_key(row, config),
                "subject": row.get(config["subject"], ""),
                "period": row.get(config["period"], ""),
                "metric_key": row.get(config["metric"], ""),
                "official_value": row.get(config["value"], ""),
                "unit": row.get("official_unit") or row.get("unit") or row.get("计价单位") or "",
                "legacy_verification_count": legacy,
                "distinct_source_document_count": count,
                "sources_needed": 3 - count,
                "triple_source_status": "derived_not_directly_disclosed" if derived else "needs_additional_distinct_sources",
                "known_source_urls": json.dumps(sorted(urls), ensure_ascii=False),
            })
    summary = {
        "dataset_id": config["id"],
        "row_count": len(rows),
        "available_value_rows": len(available),
        "source_gap_or_blank_rows": len(rows) - len(available),
        "three_distinct_source_certified_rows": certified,
        "below_three_source_rows": len(available) - certified,
        "three_source_coverage_pct": round(certified * 100 / len(available), 2) if available else 0,
        "legacy_count_ge3_but_distinct_lt3": legacy_inflation,
        "distinct_source_count_distribution": json.dumps(dict(sorted(distinct_counts.items())), ensure_ascii=False),
        "quality_gate_status": "pass" if available and certified == len(available) else "backlog_open",
        "primary_csv": config["path"].relative_to(ROOT).as_posix(),
    }
    return summary, backlog, rows


def disclosure_catalog(all_rows: dict[str, list[dict[str, str]]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for dataset_id, expected in COMMON_DISCLOSURES.items():
        rows = all_rows[dataset_id]
        config = next(item for item in DATASETS if item["id"] == dataset_id)
        metric_field = config["metric"]
        value_field = config["value"]
        headers = set(rows[0]) if rows else set()
        metric_counts = Counter(row.get(metric_field, "") for row in rows if is_value(row.get(value_field)))
        subjects_by_metric: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            if is_value(row.get(value_field)):
                subjects_by_metric[row.get(metric_field, "")].add(row.get(config["subject"], ""))
        for metric_key, metric_zh, group, priority in expected:
            if dataset_id == "competitor_product_tariffs":
                present = metric_key in headers
                values = sum(1 for row in rows if is_value(row.get(metric_key))) if present else 0
                subject_count = len({row.get(config["subject"], "") for row in rows if present and is_value(row.get(metric_key))})
            else:
                candidates = [metric_key, *METRIC_ALIASES.get(metric_key, [])]
                present = any(candidate in metric_counts for candidate in candidates)
                values = sum(metric_counts.get(candidate, 0) for candidate in candidates)
                subject_count = len(set().union(*(subjects_by_metric.get(candidate, set()) for candidate in candidates)))
            result.append({
                "dataset_id": dataset_id,
                "disclosure_group": group,
                "metric_key": metric_key,
                "metric_zh": metric_zh,
                "priority": priority,
                "schema_present": "yes" if (present or metric_key in headers) else "no",
                "available_value_rows": values,
                "subjects_with_values": subject_count,
                "collection_status": "present" if values else "missing_common_disclosure",
                "collection_rule": "Only write a value after >=3 distinct source documents; never estimate a source gap.",
            })
    return result


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str] | None = None) -> None:
    rows = list(rows)
    if fields is None:
        fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(summaries: list[dict[str, Any]], backlog: list[dict[str, Any]], catalog: list[dict[str, Any]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    prefix = f"cross_database_common_disclosure_audit_{AUDIT_DATE}"
    summary_csv = OUT / f"{prefix}.csv"
    summary_json = OUT / f"{prefix}.json"
    summary_md = OUT / f"{prefix}.md"
    backlog_csv = OUT / f"triple_source_backlog_{AUDIT_DATE}.csv"
    catalog_csv = OUT / f"common_disclosure_catalog_{AUDIT_DATE}.csv"
    write_csv(summary_csv, summaries)
    write_csv(backlog_csv, backlog)
    write_csv(catalog_csv, catalog)
    payload = {
        "audit_date": AUDIT_DATE,
        "strict_rule": "Each formal numeric value requires at least three distinct source document URLs. Multiple sections or snapshots of one URL count once.",
        "datasets": summaries,
        "backlog_rows": len(backlog),
        "common_disclosures_checked": len(catalog),
        "missing_common_disclosures": sum(row["collection_status"] == "missing_common_disclosure" for row in catalog),
    }
    summary_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        f"# 全数据库常见披露与三来源审计（{AUDIT_DATE}）",
        "",
        "## 严格口径",
        "",
        "- 单个正式数值至少需要 3 个不同来源文档 URL。",
        "- 同一 PDF/网页内的多个章节、标签或归档快照只计 1 个来源。",
        "- 未达到门槛的现有值保留，但列入补证清单；未披露值不估算、不当作 0。",
        "",
        "## 数据库结果",
        "",
        "| 数据库 | 有值行 | 三源通过 | 待补证 | 覆盖率 | 旧计数虚高 | 状态 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in summaries:
        lines.append(
            f"| {row['dataset_id']} | {row['available_value_rows']} | {row['three_distinct_source_certified_rows']} | "
            f"{row['below_three_source_rows']} | {row['three_source_coverage_pct']}% | "
            f"{row['legacy_count_ge3_but_distinct_lt3']} | {row['quality_gate_status']} |"
        )
    missing = [row for row in catalog if row["collection_status"] == "missing_common_disclosure"]
    lines.extend(["", "## 常见披露字段缺口", ""])
    for row in missing:
        lines.append(f"- `{row['dataset_id']}`：{row['metric_zh']} (`{row['metric_key']}`)，优先级 {row['priority']}。")
    lines.extend(["", "完整逐行补证任务见 `" + backlog_csv.name + "`；完整字段基线见 `" + catalog_csv.name + "`。", ""])
    summary_md.write_text("\n".join(lines), encoding="utf-8")

    manifest_path = OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    entrypoints = list(manifest.get("entrypoints") or [])
    for name in [summary_md.name, summary_csv.name, summary_json.name, backlog_csv.name, catalog_csv.name]:
        if name not in entrypoints:
            entrypoints.append(name)
    manifest.update({
        "id": "knowledge_integrity_audits",
        "title": "小竞AI知识库完整性审计",
        "summary": "统一检查业务知识库的常见披露字段、严格三来源文档门槛、来源缺口和小竞AI使用边界。",
        "updated_at": AUDIT_DATE,
        "entrypoints": entrypoints,
        "quality": {
            "status": "backlog_open" if backlog else "pass",
            "datasets_checked": len(summaries),
            "available_value_rows": sum(row["available_value_rows"] for row in summaries),
            "three_distinct_source_certified_rows": sum(row["three_distinct_source_certified_rows"] for row in summaries),
            "below_three_source_rows": len(backlog),
            "missing_common_disclosures": len(missing),
            "notes": [
                "三来源按不同文档URL去重，不以旧verification_count直接代替。",
                "未通过的现有值保留为可追溯资料，但小竞AI不得称为三来源验证。",
                "新增正式数值必须先通过三来源文档门槛。",
            ],
        },
        "last_audit_path": summary_md.relative_to(ROOT).as_posix(),
    })
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    summaries: list[dict[str, Any]] = []
    backlog: list[dict[str, Any]] = []
    all_rows: dict[str, list[dict[str, str]]] = {}
    for config in DATASETS:
        summary, row_backlog, rows = audit_dataset(config)
        summaries.append(summary)
        backlog.extend(row_backlog)
        all_rows[config["id"]] = rows
    catalog = disclosure_catalog(all_rows)
    write_outputs(summaries, backlog, catalog)
    print(json.dumps({
        "datasets": len(summaries),
        "available_values": sum(row["available_value_rows"] for row in summaries),
        "three_source_certified": sum(row["three_distinct_source_certified_rows"] for row in summaries),
        "backlog": len(backlog),
        "common_disclosures": len(catalog),
        "missing_common_disclosures": sum(row["collection_status"] == "missing_common_disclosure" for row in catalog),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

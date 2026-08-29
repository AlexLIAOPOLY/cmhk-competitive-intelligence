from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cmhk.intelligence.executive import build_executive_intelligence_snapshot

GLOBAL_OPERATOR_SOURCE = (
    ROOT / "agent_knowledge/global_top5_operators_2016_2025/annual_metrics.csv"
)
GLOBAL_OPERATOR_SOURCES = (
    ROOT / "agent_knowledge/global_top5_operators_2016_2025/sources.json"
)
LOCAL_HK_SOURCE = (
    ROOT / "agent_knowledge/local_hk_operator_operating_metrics_2016_2025/annual_metrics.csv"
)
CLOUD_VENDOR_SOURCE = (
    ROOT / "agent_knowledge/cloud_vendor_metrics_2026-06-17/cloud_vendor_metrics_2016_2025.csv"
)
CLOUD_VENDOR_SOURCES = (
    ROOT / "agent_knowledge/cloud_vendor_metrics_2026-06-17/sources.json"
)
SOURCES = (
    GLOBAL_OPERATOR_SOURCE,
    LOCAL_HK_SOURCE,
    CLOUD_VENDOR_SOURCE,
)
REQUESTED_OVERVIEW_SOURCES = (
    ROOT / "agent_knowledge/quarterly_competitor_metrics_2026-06-18/quarterly_metrics.json",
    ROOT / "agent_knowledge/cloud_vendor_metrics_2026-06-17/cloud_vendor_metrics_2016_2025.json",
    ROOT / "agent_knowledge/executive_intelligence_reference/online_gap_audit_2026-08-25.json",
    ROOT / "agent_knowledge/requested_overview_010304_2016_2025/annual_facts.json",
)
REQUESTED_OVERVIEW_DATASET_ID = "requested_overview_010304_2016_2025"
KNOWLEDGE_BASE_META = {
    GLOBAL_OPERATOR_SOURCE: {
        "label": "全球重点运营商年度知识库",
        "type": "财务 + 运营指标",
        "scope": "内地四家 + 印度两家 + 国际四家 · 2016–2025",
    },
    LOCAL_HK_SOURCE: {
        "label": "香港本地运营商年度知识库",
        "type": "客户 + 网络 + 运营指标",
        "scope": "香港本地运营商 · 2016–2025",
    },
    CLOUD_VENDOR_SOURCE: {
        "label": "全球云厂商十年经营知识库",
        "type": "云收入 + 利润 + 资本开支 + 披露缺口",
        "scope": "八家重点云厂商 · FY2016–FY2025 · 原生财政年度",
    },
}
OUTPUT = ROOT / "web/static/competitor-workbench-data.json"
BLOCKED_STATUSES = {
    "source_gap_confirmed",
    "needs_official_row_crosscheck",
    "not_applicable_business_scope",
    "not_applicable_precommercial",
    "scope_not_comparable",
}
FULL_AUDIT_OPERATOR_IDS = {
    "cmhk",
    "hkt",
    "three_hk",
    "smartone",
    "hkbn",
    "hgc",
    "icable",
}
COMPANY_GROUPS = {
    "中国移动": "内地运营商",
    "中国电信": "内地运营商",
    "中国联通": "内地运营商",
    "中国广电": "内地运营商",
    "Bharti Airtel": "国际运营商",
    "Reliance Jio": "国际运营商",
    "Verizon": "国际运营商",
    "Deutsche Telekom": "国际运营商",
    "AT&T": "国际运营商",
    "NTT Group": "国际运营商",
}
UNIT_LABELS = {
    "percent": "%",
    "million_subscribers": "百万户",
    "million_customers": "百万户",
    "million_base_stations": "百万座",
    "base_stations": "座",
    "HKD_per_user_month": "港元/户/月",
    "CNY_per_user_month": "元/户/月",
    "GB_per_user_month": "GB/户/月",
    "million_households": "百万户",
    "INR_per_user_month": "印度卢比/户/月",
    "INR_million": "百万印度卢比",
    "INR_crore": "千万印度卢比",
    "billion_GB": "十亿GB",
    "million_connections": "百万连接",
    "USD_million": "百万美元",
    "EUR_billion": "十亿欧元",
    "JPY_billion": "十亿日元",
    "HKD_million": "百万港元",
    "CNY_100million": "亿元",
    "RMB_millions": "百万人民币",
    "CNY_millions": "百万人民币",
    "USD_millions": "百万美元",
    "hundred_million_subscribers": "亿户",
}
COMPARISON_ALIASES = {
    ("NTT Group", "mobile_service_subscriptions"): {
        "metric": "postpaid_connections",
        "unit": "million_subscribers",
        "scopePrefix": "替代口径（非后付费）：NTT DOCOMO移动电话服务订阅数，包含MVNO及通信模块合同；",
        "notePrefix": "为四家国际运营商十年趋势比较映射到“后付费用户数”；仅作规模替代观察，不代表NTT披露了后付费客户数。",
    },
}
SIMPLIFIED_TITLE_REPLACEMENTS = (
    ("寬頻", "宽带"),
    ("戶", "户"),
    ("數據", "数据"),
    ("客戶", "客户"),
    ("業務", "业务"),
    ("網絡", "网络"),
    ("固網", "固网"),
    ("電視", "电视"),
    ("電話", "电话"),
    ("樓宇", "楼宇"),
    ("覆蓋", "覆盖"),
    ("連接", "连接"),
    ("免費", "免费"),
    ("收費", "收费"),
    ("企業", "企业"),
    ("商業", "商业"),
    ("增長", "增长"),
    ("滲透", "渗透"),
    ("擴展", "扩展"),
    ("移動", "移动"),
    ("後付", "后付"),
    ("預付", "预付"),
    ("淨", "净"),
)


def text(row: dict, key: str) -> str:
    return str(row.get(key) or row.get("\ufeff" + key) or "").strip()


def json_list(value: str) -> list:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def source_urls(items: list, registry: dict[str, str] | None = None) -> list[str]:
    registry = registry or {}
    urls: list[str] = []
    for item in items:
        if isinstance(item, dict):
            candidate = str(item.get("url") or "").strip()
        else:
            key = str(item or "").strip()
            candidate = registry.get(key, key if key.startswith(("https://", "http://")) else "")
        if candidate.startswith(("https://", "http://")) and candidate not in urls:
            urls.append(candidate)
    return urls


def source_count(value: str, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def local_issuer_or_exchange_source(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    suffixes = (
        "hkt.com", "hthkh.com", "smartone.com", "smartoneholdings.com",
        "hkbn.net", "hgc.com.hk", "i-cablecomm.com", "hkexnews.hk", "irasia.com",
    )
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in suffixes)


def simplified_title(value: str) -> str:
    for traditional, simplified in SIMPLIFIED_TITLE_REPLACEMENTS:
        value = value.replace(traditional, simplified)
    return value


def add_requested_overview_cells(
    cells: list[dict],
    company_meta: dict[str, dict],
    metric_meta: dict[str, dict],
    availability: dict[tuple[str, str], set[int]],
) -> None:
    snapshot = build_executive_intelligence_snapshot()
    audit = json.loads(REQUESTED_OVERVIEW_SOURCES[2].read_text(encoding="utf-8"))
    evidence_notes = {
        (str(item.get("entity") or ""), str(item.get("metric") or ""), str(item.get("period") or "")): str(item.get("evidence_note") or "")
        for item in (audit.get("historical_public_facts") or [])
        if isinstance(item, dict)
    }
    domain_meta = {
        "local": ("01", "香港运营商"),
        "mainland": ("03", "内地运营商"),
        "cloud": ("04", "全球云厂商"),
    }
    unit_keys = {
        "百万港元": "HKD_million",
        "百万户": "million_customers",
        "亿元": "CNY_100million",
        "亿户": "hundred_million_subscribers",
        "百万美元": "USD_million",
    }
    for domain in snapshot.get("domains") or []:
        domain_id = str(domain.get("id") or "")
        if domain_id not in domain_meta:
            continue
        index, group = domain_meta[domain_id]
        for focus in domain.get("focuses") or []:
            focus_id = str(focus.get("id") or "")
            metric = f"overview_{index}_{focus_id}"
            metric_label = f"{focus.get('label') or focus_id}（{index}）"
            for entity in focus.get("items") or []:
                company = str(entity.get("name") or "")
                company_meta.setdefault(company, {"id": company, "label": company, "group": group})
                for point in entity.get("trend") or []:
                    value = point.get("value")
                    if value is None:
                        continue
                    source_urls = list(dict.fromkeys(str(url) for url in (point.get("source_urls") or []) if url))
                    verification_count = int(point.get("verification_count") or 0)
                    year = int(str(point.get("label") or "").removeprefix("FY"))
                    unit = unit_keys.get(str(point.get("unit") or ""), str(point.get("unit") or ""))
                    meta = metric_meta.setdefault(metric, {
                        "key": metric,
                        "label": metric_label,
                        "unit": unit,
                        "unitLabel": UNIT_LABELS.get(unit, unit),
                        "units": [],
                        "unitLabels": {},
                    })
                    if unit not in meta["units"]:
                        meta["units"].append(unit)
                    meta["unitLabels"][unit] = UNIT_LABELS.get(unit, unit)
                    availability[(company, metric)].add(year)
                    fully_verified = verification_count >= 3 and len(source_urls) >= 3
                    cells.append({
                        "dataset": REQUESTED_OVERVIEW_DATASET_ID,
                        "company": company,
                        "metric": metric,
                        "year": year,
                        "value": float(value),
                        "unit": unit,
                        "comparator": "=",
                        "period": f"FY{year}",
                        "periodEnd": f"{year}-12-31",
                        "scope": f"战略总览{index}；{focus.get('label') or focus_id}绝对值；沿用公司原生披露口径",
                        "basis": "三份不同官方文件核验" if fully_verified else "官方数值已入库；来源数量不足不影响展示",
                        "status": "official_three_distinct_sources_verified" if fully_verified else str(point.get("verification_status") or "official_source_count_below_three_displayed"),
                        "source": source_urls[0] if source_urls else "",
                        "sources": source_urls,
                        "verificationCount": verification_count,
                        "note": evidence_notes.get((company, focus_id if focus_id != "net_profit" else "net_income", f"FY{year}"), "") or ("不展示增速或利润率；不同单位不直接比较。" if fully_verified else "来源质量仅作提示，不再作为前端隐藏条件；已有数值必须展示。"),
                    })


def main() -> None:
    cells: list[dict] = []
    gaps: list[dict] = []
    company_meta: dict[str, dict] = {}
    metric_meta: dict[str, dict] = {}
    availability: dict[tuple[str, str], set[int]] = defaultdict(set)
    global_source_payload = json.loads(GLOBAL_OPERATOR_SOURCES.read_text(encoding="utf-8"))
    global_source_urls = {
        str(item.get("source_id") or item.get("id") or ""): str(item.get("url") or "")
        for item in (global_source_payload.get("sources") or [])
        if isinstance(item, dict)
    }
    cloud_source_payload = json.loads(CLOUD_VENDOR_SOURCES.read_text(encoding="utf-8"))
    cloud_source_urls = {
        str(source_id): str(item.get("url") or "")
        for source_id, item in cloud_source_payload.items()
        if isinstance(item, dict)
    }
    for source in SOURCES:
        with source.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                is_cloud = source == CLOUD_VENDOR_SOURCE
                status = text(row, "verification_status")
                raw = text(row, "official_value")
                company = text(row, "vendor") if is_cloud else text(row, "operator")
                metric = text(row, "metric_key")
                try:
                    year = int(text(row, "fiscal_year") if is_cloud else text(row, "year"))
                except (TypeError, ValueError):
                    continue
                if not company or not metric:
                    continue
                native_unit = text(row, "unit")
                if is_cloud and native_unit == "millions":
                    native_unit = f"{text(row, 'currency')}_millions"
                unit = "million_subscribers" if metric == "postpaid_connections" else native_unit
                company_meta.setdefault(company, {
                    "id": company,
                    "label": company,
                    "group": (
                        "全球云厂商"
                        if is_cloud
                        else ("香港运营商" if source == LOCAL_HK_SOURCE else COMPANY_GROUPS.get(company, "国际运营商"))
                    ),
                })
                meta = metric_meta.setdefault(metric, {
                    "key": metric,
                    "label": simplified_title(text(row, "metric_zh") or metric),
                    "unit": unit,
                    "unitLabel": UNIT_LABELS.get(unit, unit),
                    "units": [],
                    "unitLabels": {},
                })
                if unit not in meta["units"]:
                    meta["units"].append(unit)
                meta["unitLabels"][unit] = UNIT_LABELS.get(unit, unit)
                if not raw:
                    if source == CLOUD_VENDOR_SOURCE:
                        reviewed_sources = source_urls(
                            json_list(text(row, "verification_sources")), cloud_source_urls
                        )
                        gaps.append({
                            "dataset": source.parent.name,
                            "company": company,
                            "metric": metric,
                            "year": year,
                            "unit": unit,
                            "period": f"FY{year}",
                            "periodEnd": f"{year}-12-31",
                            "status": status,
                            "searchStatus": (
                                "scope_not_comparable"
                                if status == "scope_not_comparable"
                                else "targeted_public_search_no_direct_value"
                            ),
                            "reasonCode": text(row, "gap_reason_code") or "official_public_material_no_direct_value",
                            "reason": text(row, "gap_reason") or text(row, "quality_note") or text(row, "verification_note"),
                            "reviewedSources": reviewed_sources,
                            "reviewedSourceCount": source_count(
                                text(row, "verification_count"), len(reviewed_sources)
                            ),
                        })
                    if source == GLOBAL_OPERATOR_SOURCE:
                        source_ids = json_list(text(row, "candidate_sources"))
                        reviewed_sources = source_urls(source_ids, global_source_urls)
                        precommercial = status == "not_applicable_precommercial"
                        scope_not_comparable = status == "scope_not_comparable"
                        gaps.append({
                            "dataset": source.parent.name,
                            "company": company,
                            "metric": metric,
                            "year": year,
                            "unit": unit,
                            "period": text(row, "period"),
                            "periodEnd": text(row, "period_end"),
                            "status": status,
                            "searchStatus": (
                                "not_applicable_precommercial"
                                if precommercial
                                else "scope_not_comparable"
                                if scope_not_comparable
                                else "targeted_public_search_no_direct_value"
                            ),
                            "reasonCode": (
                                "not_applicable_precommercial"
                                if precommercial
                                else "scope_not_comparable"
                                if scope_not_comparable
                                else "official_public_material_no_direct_value"
                            ),
                            "reason": text(row, "quality_note"),
                            "reviewedSources": reviewed_sources,
                            "reviewedSourceCount": len(reviewed_sources),
                        })
                    if source == LOCAL_HK_SOURCE and text(row, "operator_id") in FULL_AUDIT_OPERATOR_IDS and text(row, "audit_outcome") == "source_gap_confirmed":
                        reviewed_sources = source_urls(json_list(text(row, "reviewed_source_urls")))
                        reason_code = text(row, "gap_reason_code")
                        search_status = (
                            "not_applicable_business_scope"
                            if reason_code == "not_applicable_business_scope"
                            else "not_applicable_precommercial"
                            if reason_code == "precommercial_kpi_not_defined"
                            else "scope_not_comparable"
                            if reason_code == "metric_definition_not_comparable"
                            else "targeted_public_search_no_direct_value"
                        )
                        gaps.append({
                            "dataset": source.parent.name,
                            "company": company,
                            "metric": metric,
                            "year": year,
                            "unit": unit,
                            "period": text(row, "period"),
                            "periodEnd": text(row, "period_end"),
                            "status": status,
                            "searchStatus": search_status,
                            "reasonCode": reason_code,
                            "reason": text(row, "gap_reason") or text(row, "quality_note"),
                            "reviewedSources": reviewed_sources,
                            "reviewedSourceCount": source_count(text(row, "reviewed_source_count"), len(reviewed_sources)),
                            "relatedPublicMetric": text(row, "related_public_metric"),
                            "relatedPublicValue": text(row, "related_public_value"),
                            "relatedPublicUnit": text(row, "related_public_unit"),
                            "relatedPublicComparator": text(row, "related_public_comparator"),
                            "relatedPublicNote": text(row, "related_public_note"),
                        })
                    continue
                try:
                    value = float(raw.replace(",", ""))
                except (TypeError, ValueError):
                    continue
                if status in BLOCKED_STATUSES:
                    continue
                availability[(company, metric)].add(year)
                verification_sources = json_list(text(row, "verification_sources"))
                reviewed_sources = source_urls(json_list(text(row, "reviewed_source_urls")))
                strict_source_urls = source_urls(
                    verification_sources,
                    (
                        cloud_source_urls
                        if source == CLOUD_VENDOR_SOURCE
                        else (global_source_urls if source == GLOBAL_OPERATOR_SOURCE else None)
                    ),
                )
                primary_source = text(row, "primary_source_url")
                all_source_urls = list(dict.fromkeys(
                    url for url in [primary_source, *strict_source_urls, *reviewed_sources] if url
                ))
                verification_count = source_count(text(row, "verification_count"), len(verification_sources))
                distinct_source_count = source_count(
                    text(row, "distinct_source_document_count"),
                    len(all_source_urls),
                )
                reviewed_source_count = source_count(
                    text(row, "reviewed_source_count"),
                    len(reviewed_sources),
                )
                if source == LOCAL_HK_SOURCE and not local_issuer_or_exchange_source(primary_source):
                    source_authority = (
                        "distributed_company_press_release"
                        if status == "official_single_source"
                        else "public_reported_company_statement"
                    )
                    usage_policy = "可显示和比较，但须标注为新闻稿分发、媒体或公共机构转述，不得写成发行人官网披露。"
                elif status == "operational_zero_from_precommercial_timeline":
                    source_authority = "derived_verified_timeline"
                    usage_policy = "仅表示经核验的商用前状态，不是发行人发布的KPI。"
                else:
                    source_authority = "issuer_or_exchange_official"
                    usage_policy = "可按原始披露期间与口径用于正式比较。"
                cell = {
                    "dataset": source.parent.name,
                    "company": company,
                    "metric": metric,
                    "year": year,
                    "value": value,
                    "unit": unit,
                    "comparator": text(row, "comparator") or "=",
                    "period": f"FY{year}" if is_cloud else text(row, "period"),
                    "periodEnd": f"{year}-12-31" if is_cloud else text(row, "period_end"),
                    "scope": text(row, "scope") or text(row, "quality_note"),
                    "basis": text(row, "basis"),
                    "status": status,
                    "source": primary_source,
                    "sources": all_source_urls,
                    "verificationSources": verification_sources,
                    "verificationCount": verification_count,
                    "distinctSourceDocumentCount": distinct_source_count,
                    "reviewedSources": reviewed_sources,
                    "reviewedSourceCount": reviewed_source_count,
                    "sourceAuthority": source_authority,
                    "usagePolicy": usage_policy,
                    "note": text(row, "quality_note"),
                }
                if unit != native_unit:
                    cell["nativeUnit"] = native_unit
                cells.append(cell)
                alias = COMPARISON_ALIASES.get((company, metric))
                if alias:
                    alias_metric = alias["metric"]
                    alias_unit = alias["unit"]
                    availability[(company, alias_metric)].add(year)
                    cells.append({
                        "dataset": source.parent.name,
                        "company": company,
                        "metric": alias_metric,
                        "year": year,
                        "value": value,
                        "unit": alias_unit,
                        "comparator": text(row, "comparator") or "=",
                        "period": text(row, "period"),
                        "periodEnd": text(row, "period_end"),
                        "scope": f"{alias['scopePrefix']}{text(row, 'scope')}",
                        "basis": text(row, "basis"),
                        "status": status,
                        "source": primary_source,
                        "sources": all_source_urls,
                        "verificationSources": verification_sources,
                        "verificationCount": verification_count,
                        "distinctSourceDocumentCount": distinct_source_count,
                        "reviewedSources": reviewed_sources,
                        "reviewedSourceCount": reviewed_source_count,
                        "sourceAuthority": source_authority,
                        "usagePolicy": usage_policy,
                        "note": f"{alias['notePrefix']}{text(row, 'quality_note')}",
                        "derivedFromMetric": metric,
                    })
    add_requested_overview_cells(cells, company_meta, metric_meta, availability)
    # A valid official value must remain visible even when the issuer disclosed
    # only one year.  History length is presentation metadata, not a data gate.
    active_companies = {cell["company"] for cell in cells} | {gap["company"] for gap in gaps}
    active_metrics = {cell["metric"] for cell in cells} | {gap["metric"] for gap in gaps}
    knowledge_bases = []
    for source in SOURCES:
        dataset_id = source.parent.name
        dataset_cells = [cell for cell in cells if cell["dataset"] == dataset_id]
        dataset_gaps = [gap for gap in gaps if gap["dataset"] == dataset_id]
        knowledge_bases.append({
            "id": dataset_id,
            **KNOWLEDGE_BASE_META[source],
            "companyCount": len({cell["company"] for cell in dataset_cells}),
            "metricCount": len({cell["metric"] for cell in dataset_cells}),
            "cellCount": len(dataset_cells),
            "gapCount": len(dataset_gaps),
        })
    overview_cells = [cell for cell in cells if cell["dataset"] == REQUESTED_OVERVIEW_DATASET_ID]
    knowledge_bases.append({
        "id": REQUESTED_OVERVIEW_DATASET_ID,
        "label": "战略总览01/03/04十年数据",
        "type": "营收 + EBITDA + 净利润 + 后付费用户数 + 云收入/利润/资本开支",
        "scope": "01香港电讯市场 + 03内地运营商 + 04全球云厂商 · 2016–2025 · 已有数值不因来源数量隐藏",
        "companyCount": len({cell["company"] for cell in overview_cells}),
        "metricCount": len({cell["metric"] for cell in overview_cells}),
        "cellCount": len(overview_cells),
    })
    digest = hashlib.sha256()
    for source in SOURCES:
        digest.update(source.name.encode("utf-8"))
        digest.update(source.read_bytes())
    for source in REQUESTED_OVERVIEW_SOURCES:
        digest.update(source.name.encode("utf-8"))
        digest.update(source.read_bytes())
    payload = {
        "generatedAt": datetime.fromtimestamp(
            max(source.stat().st_mtime for source in SOURCES + REQUESTED_OVERVIEW_SOURCES),
            tz=timezone.utc,
        ).isoformat(),
        "evidenceVersion": digest.hexdigest(),
        "sourceDatasets": [source.parent.name for source in SOURCES] + [REQUESTED_OVERVIEW_DATASET_ID],
        "knowledgeBases": knowledge_bases,
        "companies": [value for key, value in sorted(company_meta.items()) if key in active_companies],
        "metrics": [value for key, value in sorted(metric_meta.items(), key=lambda item: item[1]["label"]) if key in active_metrics],
        "cells": cells,
        "gaps": gaps,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUTPUT} companies={len(payload['companies'])} metrics={len(payload['metrics'])} cells={len(cells)} gaps={len(gaps)}")


if __name__ == "__main__":
    main()

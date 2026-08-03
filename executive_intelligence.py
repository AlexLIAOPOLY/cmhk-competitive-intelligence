from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
LOCAL_PATH = ROOT / "agent_knowledge/hk_competitor_product_tariffs/current_plans.json"
INTERNATIONAL_PATH = ROOT / "agent_knowledge/quarterly_competitor_metrics_2026-06-18/quarterly_metrics.json"
CLOUD_PATH = ROOT / "agent_knowledge/cloud_vendor_metrics_2026-06-17/cloud_vendor_metrics_2023_2025.json"
MACRO_PATH = ROOT / "agent_knowledge/cmhk_macro_policy_2026-06-19/macro_policy_metrics.json"

DOMAIN_PATHS = (LOCAL_PATH, INTERNATIONAL_PATH, CLOUD_PATH, MACRO_PATH)
INTERNATIONAL_SUBJECTS = ("中国移动", "中国电信", "中国联通", "中国铁塔")


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace("%", "").strip()
    if not text or text in {"-", "N/A", "null"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _period_rank(value: Any) -> tuple[int, int]:
    match = re.search(r"Q([1-4])\s+(20\d{2})", str(value or ""))
    if match:
        return int(match.group(2)), int(match.group(1))
    year = re.search(r"(20\d{2})", str(value or ""))
    return (int(year.group(1)), 0) if year else (0, 0)


def _source(label: str, url: Any) -> dict[str, str] | None:
    clean_url = str(url or "").strip()
    if not clean_url.startswith(("https://", "http://")):
        return None
    return {"label": label, "url": clean_url}


def _dedupe_sources(items: list[dict[str, str] | None]) -> list[dict[str, str]]:
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for item in items:
        if not item or item["url"] in seen:
            continue
        seen.add(item["url"])
        result.append(item)
    return result


def _local_domain(rows: list[dict[str, Any]]) -> dict[str, Any]:
    category_labels = {
        "business_mobile_4g": "企业移动4G",
        "business_mobile_5g": "企业移动5G",
        "home_5g_broadband": "5G家宽",
        "home_fibre_broadband": "光纤家宽",
        "mobile_consumer_5g": "个人5G",
        "mobile_consumer_roaming": "个人漫游",
        "prepaid_mobile": "预付卡",
        "roaming_data_pack": "漫游数据包",
        "wifi_pass": "Wi-Fi通行证",
    }
    by_brand: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        brand = str(row.get("brand") or "").strip()
        if brand:
            by_brand.setdefault(brand, []).append(row)

    entities: list[dict[str, Any]] = []
    brand_profiles: dict[str, dict[str, Any]] = {}
    for brand, brand_rows in by_brand.items():
        categories = sorted({str(row.get("product_category") or "") for row in brand_rows if row.get("product_category")})
        fees = [fee for fee in (_number(row.get("average_monthly_fee_hkd")) for row in brand_rows) if fee and fee > 0]
        fee_range = (min(fees), max(fees)) if fees else None
        source_url = next((str(row.get("source_url") or "") for row in brand_rows if row.get("source_url")), "")
        brand_profiles[brand] = {"categories": set(categories), "fee_range": fee_range}
        fee_text = "未结构化月费"
        if fee_range:
            fee_text = f"平均月费 HK${fee_range[0]:.0f}–{fee_range[1]:.0f}"
        entities.append(
            {
                "name": brand,
                "value": len(brand_rows),
                "unit": "项方案",
                "detail": f"{len(categories)} 个产品赛道 · {fee_text}",
                "source_url": source_url,
            }
        )
    entities.sort(key=lambda item: item["value"], reverse=True)

    overlaps: list[dict[str, Any]] = []
    brands = sorted(brand_profiles)
    for index, first in enumerate(brands):
        for second in brands[index + 1 :]:
            first_profile = brand_profiles[first]
            second_profile = brand_profiles[second]
            shared = sorted(first_profile["categories"] & second_profile["categories"])
            if not shared:
                continue
            fee_overlap = None
            if first_profile["fee_range"] and second_profile["fee_range"]:
                low = max(first_profile["fee_range"][0], second_profile["fee_range"][0])
                high = min(first_profile["fee_range"][1], second_profile["fee_range"][1])
                if low <= high:
                    fee_overlap = (low, high)
            overlaps.append(
                {
                    "pair": f"{first} × {second}",
                    "shared": shared,
                    "fee_overlap": fee_overlap,
                    "score": len(shared) * 100 + ((fee_overlap[1] - fee_overlap[0]) if fee_overlap else 0),
                }
            )
    overlaps.sort(key=lambda item: item["score"], reverse=True)
    lead = overlaps[0] if overlaps else None
    if lead:
        shared_label = "、".join(category_labels.get(category, category.replace("_", " ")) for category in lead["shared"][:2])
        fee_label = ""
        if lead["fee_overlap"]:
            fee_label = f"，重叠月费带 HK${lead['fee_overlap'][0]:.0f}–{lead['fee_overlap'][1]:.0f}"
        insight = f"{lead['pair']} 共享 {shared_label}{fee_label}，是当前最密集的产品交锋面。"
    else:
        insight = "本地竞对方案已按品牌、产品赛道与月费带统一对齐。"

    sources = _dedupe_sources([_source(item["name"], item["source_url"]) for item in entities])
    return {
        "id": "local",
        "index": "01",
        "title": "本地竞对",
        "kicker": "资费与产品交锋",
        "metric": {"value": len(rows), "unit": "项", "label": "在售资费方案"},
        "context": f"覆盖 {len(by_brand)} 家本地竞对",
        "insight": insight,
        "entities": entities,
        "relations": [
            {
                "title": item["pair"],
                "detail": f"共享 {len(item['shared'])} 个产品赛道" + (
                    f" · 月费重叠 HK${item['fee_overlap'][0]:.0f}–{item['fee_overlap'][1]:.0f}"
                    if item["fee_overlap"] else ""
                ),
                "kind": "数据关系",
            }
            for item in overlaps[:4]
        ],
        "sources": sources,
    }


def _latest_metric(rows: list[dict[str, Any]], subject_key: str, subject: str, metric: str) -> dict[str, Any] | None:
    candidates = [row for row in rows if row.get(subject_key) == subject and row.get("metric_key") == metric and _number(row.get("value")) is not None]
    if not candidates:
        return None
    period_key = "period" if subject_key == "subject" else "fiscal_year"
    return max(candidates, key=lambda row: _period_rank(row.get(period_key)))


def _international_domain(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("rows") or []
    entities: list[dict[str, Any]] = []
    for subject in INTERNATIONAL_SUBJECTS:
        row = _latest_metric(rows, "subject", subject, "revenue_growth_yoy")
        if not row:
            continue
        value = _number(row.get("value")) or 0
        entities.append(
            {
                "name": subject,
                "value": value,
                "unit": "%",
                "detail": f"{row.get('period') or '最新期'}营收同比",
                "source_url": str(row.get("official_source_url") or ""),
            }
        )
    entities.sort(key=lambda item: item["value"], reverse=True)
    leader = entities[0] if entities else {"name": "-", "value": 0}
    positive = [item for item in entities if item["value"] >= 0]
    negative = [item for item in entities if item["value"] < 0]
    insight = f"{leader['name']}以 {leader['value']:.2f}% 领跑；{len(positive)} 家正增长、{len(negative)} 家负增长，基础设施与综合运营商节奏出现分化。"
    return {
        "id": "international",
        "index": "02",
        "title": "国际竞对",
        "kicker": "经营增速与投入",
        "metric": {"value": f"{leader['value']:.2f}", "unit": "%", "label": "最新营收增速领先值"},
        "context": f"统一对标 {len(entities)} 家运营商",
        "insight": insight,
        "entities": entities,
        "relations": [
            {"title": item["name"], "detail": f"最新营收同比 {item['value']:+.2f}%", "kind": "同口径对标"}
            for item in entities
        ],
        "sources": _dedupe_sources([_source(item["name"], item["source_url"]) for item in entities]),
    }


def _cloud_domain(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("rows") or []
    vendors = [str(vendor.get("vendor") or "") for vendor in payload.get("vendors") or []]
    entities: list[dict[str, Any]] = []
    for vendor in vendors:
        row = _latest_metric(rows, "vendor", vendor, "revenue_yoy")
        if not row:
            continue
        value = _number(row.get("value"))
        if value is None:
            continue
        entities.append(
            {
                "name": vendor.replace(" / Intelligent Cloud", "").replace(" / Tencent FBS proxy", ""),
                "value": value,
                "unit": "%",
                "detail": f"FY{row.get('fiscal_year')} 云业务营收同比",
                "source_url": str(row.get("primary_source_url") or ""),
            }
        )
    entities.sort(key=lambda item: item["value"], reverse=True)
    leader = entities[0] if entities else {"name": "-", "value": 0}
    second_tier = [item for item in entities[1:] if item["value"] >= 15]
    tier_names = "、".join(item["name"] for item in second_tier[:3])
    insight = f"{leader['name']}以 {leader['value']:.1f}% 领跑；{tier_names or '其余厂商'}构成第二增长梯队，云端竞争继续向规模与盈利并重演进。"
    return {
        "id": "cloud",
        "index": "03",
        "title": "云厂商",
        "kicker": "增长梯队与云网融合",
        "metric": {"value": f"{leader['value']:.1f}", "unit": "%", "label": "FY2025 增速领先值"},
        "context": f"覆盖 {len(entities)} 家全球云厂商",
        "insight": insight,
        "entities": entities,
        "relations": [
            {"title": item["name"], "detail": f"FY2025 营收同比 {item['value']:+.1f}%", "kind": "增长梯队"}
            for item in entities
        ],
        "sources": _dedupe_sources([_source(item["name"], item["source_url"]) for item in entities]),
    }


def _macro_domain(rows: list[dict[str, Any]]) -> dict[str, Any]:
    wanted = {
        "mobile_subscriptions": "移动用户",
        "mobile_data_usage_total_mbytes": "移动数据总量",
        "median_monthly_household_income": "家庭月入中位数",
        "annual_telecom_investment": "电信业投资",
        "telecom_consumer_complaints_total": "电讯投诉",
        "5g_population_coverage_status": "5G人口覆盖",
    }
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        metric = str(row.get("metric_key") or "")
        if metric not in wanted or _number(row.get("value")) is None:
            continue
        current = latest.get(metric)
        if not current or str(row.get("period_end") or "") > str(current.get("period_end") or ""):
            latest[metric] = row

    subscriptions = _number((latest.get("mobile_subscriptions") or {}).get("value")) or 0
    coverage = _number((latest.get("5g_population_coverage_status") or {}).get("value")) or 0
    entities: list[dict[str, Any]] = []
    for metric, label in wanted.items():
        row = latest.get(metric)
        if not row:
            continue
        value = _number(row.get("value")) or 0
        unit = str(row.get("unit") or "")
        display_value: float | str = value
        display_unit = unit
        if metric == "mobile_subscriptions":
            display_value, display_unit = round(value / 10_000, 1), "万"
        elif metric == "annual_telecom_investment":
            display_value, display_unit = round(value / 100, 2), "亿港元"
        elif metric == "mobile_data_usage_total_mbytes":
            display_value, display_unit = round(value / 1_000_000_000, 1), "十亿MB"
        elif unit == "percent_plus":
            display_unit = "%+"
        entities.append(
            {
                "name": label,
                "value": display_value,
                "unit": display_unit,
                "detail": f"截至 {row.get('period_end') or '-'}",
                "source_url": str(row.get("official_source_url") or ""),
            }
        )
    insight = f"移动连接达 {subscriptions / 10_000:.1f} 万、5G人口覆盖超过 {coverage:.0f}%；高渗透市场下，竞争重点由连接数量转向套餐价值、流量与企业服务。"
    return {
        "id": "macro",
        "index": "04",
        "title": "宏观政策",
        "kicker": "市场底盘与监管变量",
        "metric": {"value": f"{subscriptions / 10_000:.1f}", "unit": "万", "label": "香港移动用户"},
        "context": f"宏观与政策明细 {len(rows):,} 条",
        "insight": insight,
        "entities": entities,
        "relations": [
            {"title": item["name"], "detail": f"{item['value']} {item['unit']} · {item['detail']}", "kind": "官方指标"}
            for item in entities
        ],
        "sources": _dedupe_sources([_source(item["name"], item["source_url"]) for item in entities]),
    }


@lru_cache(maxsize=4)
def _build_cached(signature: tuple[int, ...]) -> dict[str, Any]:
    del signature
    local = _local_domain(_read_json(LOCAL_PATH))
    international = _international_domain(_read_json(INTERNATIONAL_PATH))
    cloud = _cloud_domain(_read_json(CLOUD_PATH))
    macro = _macro_domain(_read_json(MACRO_PATH))
    domains = [local, international, cloud, macro]
    relations = [
        {
            "from": "macro",
            "to": "local",
            "title": "高渗透市场放大套餐价值竞争",
            "detail": f"香港移动用户 {macro['metric']['value']} 万；本地库同步呈现 {local['metric']['value']} 项在售方案。",
            "kind": "跨库推断",
        },
        {
            "from": "international",
            "to": "cloud",
            "title": "云增速显著高于运营商增速",
            "detail": f"云厂商领先增速 {cloud['metric']['value']}%，运营商领先增速 {international['metric']['value']}%，增长重心持续向云服务偏移。",
            "kind": "同期间对照",
        },
        {
            "from": "local",
            "to": "cloud",
            "title": "本地连接产品与云服务形成共同竞争面",
            "detail": "本地竞对已覆盖5G、家宽与企业移动赛道；云厂商增长梯队为企业云网融合提供外部参照。",
            "kind": "战略推断",
        },
        {
            "from": "macro",
            "to": "international",
            "title": "投资效率成为共同约束",
            "detail": "香港电信业投资与国际运营商增长分化需联合观察，重点穿透资本开支、覆盖与收入转化效率。",
            "kind": "分析框架",
        },
    ]
    return {
        "domains": domains,
        "relations": relations,
        "method": "同字段对齐、产品集合交集、价格区间重叠及同期间增速对标；跨库结论标注推断类型。",
        "source_record_count": sum(int(domain["metric"]["value"]) if domain["id"] == "local" else len(domain["entities"]) for domain in domains),
    }


def build_executive_intelligence_snapshot() -> dict[str, Any]:
    signature = tuple(path.stat().st_mtime_ns for path in DOMAIN_PATHS)
    return _build_cached(signature)

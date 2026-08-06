from __future__ import annotations

import json
import hashlib
import re
from functools import lru_cache
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
LOCAL_PATH = ROOT / "agent_knowledge/hk_competitor_product_tariffs/current_plans.json"
INTERNATIONAL_PATH = ROOT / "agent_knowledge/quarterly_competitor_metrics_2026-06-18/quarterly_metrics.json"
CLOUD_PATH = ROOT / "agent_knowledge/cloud_vendor_metrics_2026-06-17/cloud_vendor_metrics_2023_2025.json"
MACRO_PATH = ROOT / "agent_knowledge/cmhk_macro_policy_2026-06-19/macro_policy_metrics.json"
AI_ANALYSIS_PATH = ROOT / "agent_knowledge/executive_intelligence_refresh/ai_analysis.json"
REFRESH_STATE_PATH = ROOT / "agent_knowledge/executive_intelligence_refresh/latest.json"

DOMAIN_PATHS = (LOCAL_PATH, INTERNATIONAL_PATH, CLOUD_PATH, MACRO_PATH, AI_ANALYSIS_PATH, REFRESH_STATE_PATH)
INTERNATIONAL_SUBJECTS = ("中国移动", "中国电信", "中国联通", "中国铁塔")
SAFE_VERIFICATION_STATUSES = {
    "official_match",
    "official_only",
    "official_derived_from_verified_rows",
    "multi_source_or_multi_snapshot_verified",
}


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_json_optional(path: Path, default: Any) -> Any:
    try:
        return _read_json(path)
    except (OSError, json.JSONDecodeError):
        return default


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


def _verified_number(row: dict[str, Any] | None) -> float | None:
    """Return the official value when a published row contains one."""
    if not row:
        return None
    official = _number(row.get("official_value"))
    return official if official is not None else _number(row.get("value"))


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


def _median(values: list[float]) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _focus_metric(items: list[dict[str, Any]], label: str, unit: str, mode: str = "max") -> dict[str, Any]:
    values = [float(item["value"]) for item in items if _number(item.get("value")) is not None]
    if not values:
        return {"value": "-", "unit": unit, "label": label}
    value = min(values) if mode == "min" else max(values)
    return {"value": round(value, 2), "unit": unit, "label": label}


def _format_price(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "-"
    return f"{number:.0f}" if number.is_integer() else f"{number:.1f}"


def _local_price_insight(items: list[dict[str, Any]]) -> str:
    """Turn the current price distribution into a decision-ready judgement."""
    comparable = [item for item in items if _number(item.get("value")) is not None]
    if not comparable:
        return "当前没有可用于价格判断的品牌月费中位数。"

    ordered = sorted(comparable, key=lambda item: float(item["value"]))
    lowest = ordered[0]
    highest = ordered[-1]
    lowest_value = float(lowest["value"])
    highest_value = float(highest["value"])
    spread = highest_value - lowest_value
    spread_rate = (spread / highest_value * 100) if highest_value else 0
    ladder = "、".join(
        f"{item['name']}{_format_price(item['value'])}"
        for item in ordered
    )

    category_ranges: dict[str, list[float]] = {}
    for component in lowest.get("components") or []:
        category = str(component.get("detail") or "").strip()
        value = _number(component.get("value"))
        if category and value is not None:
            category_ranges.setdefault(category, []).append(value)
    category_note = ""
    if len(category_ranges) > 1:
        category_parts = []
        for category, values in category_ranges.items():
            low_value = min(values)
            high_value = max(values)
            range_text = (
                _format_price(low_value)
                if low_value == high_value
                else f"{_format_price(low_value)}–{_format_price(high_value)}"
            )
            category_parts.append(
                f"{category}{range_text}"
            )
        category_note = (
            f"其中{lowest['name']}的最低值来自"
            + "、".join(category_parts)
            + "，低价入口与主产品不是同一类，不能直接等同为主产品最低价。"
        )

    return (
        f"按品牌月费中位数，{lowest['name']}最低为{_format_price(lowest_value)}港元/月，"
        f"{highest['name']}最高为{_format_price(highest_value)}港元/月，"
        f"价差{_format_price(spread)}港元（约{spread_rate:.0f}%）；"
        f"当前价格梯度为{ladder}港元/月。"
        f"{category_note}"
    )


def _component(label: Any, value: Any = None, unit: Any = "", detail: Any = "") -> dict[str, Any]:
    item = {"label": str(label or "").strip()}
    if value is not None:
        item["value"] = value
    if str(unit or "").strip():
        item["unit"] = str(unit).strip()
    if str(detail or "").strip():
        item["detail"] = str(detail).strip()
    return item


def _dedupe_components(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        label = str(item.get("label") or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
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

    brand_profiles: dict[str, dict[str, Any]] = {}
    for brand, brand_rows in by_brand.items():
        categories = sorted({str(row.get("product_category") or "") for row in brand_rows if row.get("product_category")})
        fees = [
            fee for fee in (
                _number(row.get("average_monthly_fee_hkd")) or _number(row.get("monthly_fee_hkd"))
                for row in brand_rows
            ) if fee and fee > 0
        ]
        fee_range = (min(fees), max(fees)) if fees else None
        source_url = next((str(row.get("source_url") or "") for row in brand_rows if row.get("source_url")), "")
        brand_profiles[brand] = {
            "rows": brand_rows,
            "categories": set(categories),
            "fees": fees,
            "fee_range": fee_range,
            "source_url": source_url,
        }

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
    overlaps_by_brand: dict[str, list[dict[str, Any]]] = {brand: [] for brand in brands}
    for overlap in overlaps:
        first, second = overlap["pair"].split(" × ", 1)
        overlaps_by_brand[first].append({**overlap, "peer": second})
        overlaps_by_brand[second].append({**overlap, "peer": first})

    scale_items: list[dict[str, Any]] = []
    track_items: list[dict[str, Any]] = []
    price_items: list[dict[str, Any]] = []
    overlap_items: list[dict[str, Any]] = []
    for brand, profile in brand_profiles.items():
        categories = sorted(profile["categories"])
        labels = [category_labels.get(category, category.replace("_", " ")) for category in categories]
        fees = profile["fees"]
        fee_range = profile["fee_range"]
        median_fee = _median(fees)
        brand_overlaps = sorted(overlaps_by_brand.get(brand, []), key=lambda item: item["score"], reverse=True)
        shared_categories = set().union(*(set(item["shared"]) for item in brand_overlaps)) if brand_overlaps else set()
        strongest = brand_overlaps[0] if brand_overlaps else None
        plan_components = _dedupe_components([
            _component(
                row.get("plan_name") or row.get("plan_family") or "未命名方案",
                _number(row.get("average_monthly_fee_hkd")) or _number(row.get("monthly_fee_hkd")),
                "港元/月",
                category_labels.get(str(row.get("product_category") or ""), str(row.get("product_category") or "")),
            )
            for row in profile["rows"]
        ])
        duplicate_records = max(0, len(profile["rows"]) - len(plan_components))
        fee_text = (
            f"月费 HK${fee_range[0]:.0f}–{fee_range[1]:.0f}"
            if fee_range else "月费未完整结构化"
        )
        duplicate_text = f"；另有 {duplicate_records} 条重复记录需在总量判断前去重" if duplicate_records else ""
        scale_items.append({
            "name": brand,
            "value": len(profile["rows"]),
            "unit": "项",
            "detail": f"覆盖 {len(categories)} 个赛道",
            "analysis": (
                f"{len(profile['rows'])} 条在售记录对应 {len(plan_components)} 个唯一方案，"
                f"集中于{'、'.join(labels) or '未分类产品'}，{fee_text}{duplicate_text}。"
            ),
            "components": plan_components,
            "component_count": len(plan_components),
            "record_count": len(profile["rows"]),
            "source_url": profile["source_url"],
        })
        track_items.append({
            "name": brand,
            "value": len(categories),
            "unit": "个赛道",
            "detail": "、".join(labels[:4]) or "未分类",
            "analysis": f"覆盖 {len(categories)} 个产品赛道，重点包括{'、'.join(labels[:3]) or '未分类产品'}。",
            "components": [_component(label) for label in labels],
            "component_count": len(labels),
            "source_url": profile["source_url"],
        })
        price_items.append({
            "name": brand,
            "value": round(median_fee, 1) if median_fee is not None else None,
            "unit": "港元/月",
            "low": round(fee_range[0], 1) if fee_range else None,
            "high": round(fee_range[1], 1) if fee_range else None,
            "detail": f"月费带 HK${fee_range[0]:.0f}–{fee_range[1]:.0f}" if fee_range else "月费尚未结构化",
            "analysis": (
                f"结构化平均月费中位数为 HK${median_fee:.0f}，覆盖区间 HK${fee_range[0]:.0f}–{fee_range[1]:.0f}。"
                if median_fee is not None and fee_range else "当前品牌缺少可比月费，不进行估算。"
            ),
            "components": plan_components,
            "component_count": len(plan_components),
            "source_url": profile["source_url"],
        })
        overlap_items.append({
            "name": brand,
            "value": len(shared_categories),
            "unit": "个重叠赛道",
            "peers": len(brand_overlaps),
            "detail": f"与 {len(brand_overlaps)} 家竞对发生赛道交集",
            "analysis": (
                f"最强交锋对象为 {strongest['peer']}，共享 {len(strongest['shared'])} 个赛道"
                + (f"，月费重叠 HK${strongest['fee_overlap'][0]:.0f}–{strongest['fee_overlap'][1]:.0f}。" if strongest.get("fee_overlap") else "。")
                if strongest else "当前未发现结构化赛道交集。"
            ),
            "components": [
                _component(
                    item["peer"],
                    len(item["shared"]),
                    "个重叠赛道",
                    "、".join(category_labels.get(category, category.replace("_", " ")) for category in item["shared"]),
                )
                for item in brand_overlaps
            ],
            "component_count": len(brand_overlaps),
            "source_url": profile["source_url"],
        })

    scale_items.sort(key=lambda item: item["value"], reverse=True)
    track_items.sort(key=lambda item: item["value"], reverse=True)
    price_items.sort(key=lambda item: (_number(item.get("value")) is not None, _number(item.get("value")) or 0), reverse=True)
    overlap_items.sort(key=lambda item: (item["value"], item["peers"]), reverse=True)
    lead = overlaps[0] if overlaps else None
    if lead:
        shared_label = "、".join(category_labels.get(category, category.replace("_", " ")) for category in lead["shared"][:2])
        fee_label = ""
        if lead["fee_overlap"]:
            fee_label = f"，重叠月费带 HK${lead['fee_overlap'][0]:.0f}–{lead['fee_overlap'][1]:.0f}"
        insight = f"{lead['pair']} 共享 {shared_label}{fee_label}，是当前最密集的产品交锋面。"
    else:
        insight = "本地竞对方案已按品牌、产品赛道与月费带统一对齐。"

    focuses = [
        {
            "id": "scale", "label": "方案规模", "visual": "columns",
            "metric": {"value": len(rows), "unit": "项", "label": "在售资费方案"},
            "context": f"覆盖 {len(by_brand)} 家本地竞对",
            "insight": f"{scale_items[0]['name']}以 {scale_items[0]['value']} 项方案居首，方案数量反映当前产品陈列广度。" if scale_items else "暂无方案数据。",
            "items": scale_items,
        },
        {
            "id": "track", "label": "产品赛道", "visual": "rows",
            "metric": _focus_metric(track_items, "单一竞对最多覆盖", "个赛道"),
            "context": f"共识别 {len(category_labels)} 类标准赛道",
            "insight": f"{track_items[0]['name']}覆盖 {track_items[0]['value']} 个赛道，产品广度领先。" if track_items else "暂无赛道数据。",
            "items": track_items,
        },
        {
            "id": "price", "label": "月费区间", "visual": "ranges",
            "metric": _focus_metric(price_items, "最低月费中位数", "港元/月", mode="min"),
            "context": "只比较已结构化平均月费",
            "insight": _local_price_insight(price_items),
            "items": price_items,
        },
        {
            "id": "overlap", "label": "竞对重叠", "visual": "network",
            "metric": _focus_metric(overlap_items, "最多重叠赛道", "个"),
            "context": f"识别 {len(overlaps)} 组品牌交集",
            "insight": insight,
            "items": overlap_items,
        },
    ]
    entities = scale_items
    sources = _dedupe_sources([_source(item["name"], item["source_url"]) for item in scale_items])
    return {
        "id": "local",
        "index": "01",
        "title": "本地竞对",
        "kicker": "资费与产品交锋",
        "metric": {"value": len(rows), "unit": "项", "label": "在售资费方案"},
        "context": f"覆盖 {len(by_brand)} 家本地竞对",
        "insight": insight,
        "entities": entities,
        "focuses": focuses,
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
    candidates = [
        row for row in rows
        if row.get(subject_key) == subject
        and row.get("metric_key") == metric
        and _verified_number(row) is not None
        and str(row.get("verification_status") or "") in SAFE_VERIFICATION_STATUSES
    ]
    if not candidates:
        return None
    period_key = "period" if subject_key == "subject" else "fiscal_year"
    return max(candidates, key=lambda row: _period_rank(row.get(period_key)))


def _metric_history(rows: list[dict[str, Any]], subject_key: str, subject: str, metric: str) -> list[dict[str, Any]]:
    period_key = "period" if subject_key == "subject" else "fiscal_year"
    candidates = [
        row for row in rows
        if row.get(subject_key) == subject
        and row.get("metric_key") == metric
        and _verified_number(row) is not None
        and str(row.get("verification_status") or "") in SAFE_VERIFICATION_STATUSES
    ]
    return sorted(candidates, key=lambda row: _period_rank(row.get(period_key)))


def _international_domain(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("rows") or []
    growth_items: list[dict[str, Any]] = []
    momentum_items: list[dict[str, Any]] = []
    disclosure_items: list[dict[str, Any]] = []
    for subject in INTERNATIONAL_SUBJECTS:
        row = _latest_metric(rows, "subject", subject, "revenue_growth_yoy")
        if not row:
            continue
        value = _verified_number(row) or 0
        history = _metric_history(rows, "subject", subject, "revenue_growth_yoy")
        previous_value = _verified_number(history[-2]) if len(history) > 1 else None
        change = value - previous_value if previous_value is not None else None
        source_url = str(row.get("official_source_url") or "")
        growth_items.append({
            "name": subject,
            "value": round(value, 2),
            "unit": "%",
            "period": str(row.get("period") or ""),
            "detail": f"{row.get('period') or '最新期'}营收同比",
            "analysis": f"{row.get('period') or '最新期'}营收同比 {value:+.2f}%；该值反映最新披露期的收入扩张或收缩速度。",
            "components": [_component(row.get("period") or "最新期", round(value, 2), "%", row.get("metric_zh") or "营收同比")],
            "component_count": 1,
            "source_url": source_url,
        })
        momentum_items.append({
            "name": subject,
            "value": round(change, 2) if change is not None else None,
            "unit": "个百分点",
            "detail": (
                f"较{history[-2].get('period')} {'改善' if change >= 0 else '回落'} {abs(change):.2f} 个百分点"
                if change is not None else "缺少上一可比期"
            ),
            "analysis": (
                f"营收增速由 {previous_value:+.2f}% 变为 {value:+.2f}%，动量{'转强' if change > 0 else '转弱' if change < 0 else '持平'}。"
                if change is not None else "当前只有一个可比期，不推断增长动量。"
            ),
            "trend": [
                {"label": str(item.get("period") or ""), "value": _verified_number(item)}
                for item in history[-4:]
            ],
            "components": [
                _component(item.get("period") or "未标期间", _verified_number(item), "%", item.get("metric_zh") or "营收同比")
                for item in history[-4:]
            ],
            "component_count": len(history[-4:]),
            "source_url": source_url,
        })
        subject_rows = [item for item in rows if item.get("subject") == subject and _verified_number(item) is not None]
        latest_rank = max((_period_rank(item.get("period")) for item in subject_rows), default=(0, 0))
        latest_rows = [item for item in subject_rows if _period_rank(item.get("period")) == latest_rank]
        latest_period = str(latest_rows[0].get("period") or "-") if latest_rows else "-"
        verified = sum(1 for item in latest_rows if str(item.get("verification_status") or "").startswith("official"))
        disclosure_items.append({
            "name": subject,
            "value": len(latest_rows),
            "unit": "项披露",
            "detail": f"{latest_period} · {verified} 项官方匹配",
            "analysis": (
                f"{latest_period}包含 {len(latest_rows)} 项可核验指标，{verified} 项为官方匹配；"
                f"指标组合包括{'、'.join(str(item.get('metric_zh') or item.get('metric_key') or '') for item in latest_rows[:4])}。"
            ),
            "components": _dedupe_components([
                _component(
                    item.get("metric_zh") or item.get("metric_key") or "未命名指标",
                    _verified_number(item),
                    item.get("official_unit") or item.get("unit") or "",
                    item.get("period") or latest_period,
                )
                for item in latest_rows
            ]),
            "component_count": len(latest_rows),
            "source_url": str((latest_rows[0] if latest_rows else row).get("official_source_url") or ""),
        })
    growth_items.sort(key=lambda item: item["value"], reverse=True)
    momentum_items.sort(key=lambda item: (_number(item.get("value")) is not None, _number(item.get("value")) or 0), reverse=True)
    disclosure_items.sort(key=lambda item: item["value"], reverse=True)
    leader = growth_items[0] if growth_items else {"name": "-", "value": 0}
    gap_items = []
    for item in growth_items:
        gap = float(leader["value"]) - float(item["value"])
        gap_items.append({
            **item,
            "value": round(gap, 2),
            "unit": "个百分点",
            "detail": "当前领先" if gap == 0 else f"较 {leader['name']} 落后 {gap:.2f} 个百分点",
            "analysis": "当前为营收增速领先基准。" if gap == 0 else f"以同期间营收增速衡量，较领先者 {leader['name']} 存在 {gap:.2f} 个百分点差距。",
            "components": [
                _component(item["name"], item["value"], "%", item.get("period") or "最新期"),
                _component(leader["name"], leader["value"], "%", leader.get("period") or "最新期"),
            ],
            "component_count": 2,
        })
    positive = [item for item in growth_items if item["value"] >= 0]
    negative = [item for item in growth_items if item["value"] < 0]
    insight = f"{leader['name']}以 {leader['value']:.2f}% 领跑；{len(positive)} 家正增长、{len(negative)} 家负增长，基础设施与综合运营商节奏出现分化。"
    focuses = [
        {
            "id": "growth", "label": "营收增速", "visual": "diverging",
            "metric": {"value": f"{leader['value']:.2f}", "unit": "%", "label": "最新营收增速领先值"},
            "context": f"统一对标 {len(growth_items)} 家运营商", "insight": insight, "items": growth_items,
        },
        {
            "id": "momentum", "label": "增长动量", "visual": "trends",
            "metric": _focus_metric(momentum_items, "最佳动量变化", "个百分点"),
            "context": "最新期相对上一可比期",
            "insight": "增长动量比较增速的环期变化；正值代表改善，负值代表回落，不等同于绝对收入增长。",
            "items": momentum_items,
        },
        {
            "id": "gap", "label": "领先差距", "visual": "rows",
            "metric": _focus_metric(gap_items, "最大领先差距", "个百分点"),
            "context": f"以 {leader['name']} 为当前基准",
            "insight": "差距统一以最新营收同比领先值为0基准，数值越大表示与领先者距离越远。",
            "items": gap_items,
        },
        {
            "id": "disclosure", "label": "原始披露", "visual": "disclosure",
            "metric": {"value": sum(item["value"] for item in disclosure_items), "unit": "项", "label": "最新期结构化披露"},
            "context": "仅计数据库内有数值记录",
            "insight": "披露项数用于判断可分析深度，结论仍需结合具体口径与官方来源，不把披露多等同于经营更好。",
            "items": disclosure_items,
        },
    ]
    return {
        "id": "international",
        "index": "02",
        "title": "国际竞对",
        "kicker": "经营增速与投入",
        "metric": {"value": f"{leader['value']:.2f}", "unit": "%", "label": "最新营收增速领先值"},
        "context": f"统一对标 {len(growth_items)} 家运营商",
        "insight": insight,
        "entities": growth_items,
        "focuses": focuses,
        "relations": [
            {"title": item["name"], "detail": f"最新营收同比 {item['value']:+.2f}%", "kind": "同口径对标"}
            for item in growth_items
        ],
        "sources": _dedupe_sources([_source(item["name"], item["source_url"]) for item in growth_items]),
    }


def _cloud_domain(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("rows") or []
    vendors = [str(vendor.get("vendor") or "") for vendor in payload.get("vendors") or []]
    growth_items: list[dict[str, Any]] = []
    trend_items: list[dict[str, Any]] = []
    profit_items: list[dict[str, Any]] = []
    disclosure_items: list[dict[str, Any]] = []
    profit_keys = ("operating_margin", "adjusted_ebita_margin", "proxy_segment_gross_margin")
    for vendor in vendors:
        row = _latest_metric(rows, "vendor", vendor, "revenue_yoy")
        if not row:
            continue
        value = _verified_number(row)
        if value is None:
            continue
        name = vendor.replace(" / Intelligent Cloud", "").replace(" / Tencent FBS proxy", "").replace(" / Cloud Computing", "")
        source_url = str(row.get("primary_source_url") or "")
        growth_items.append({
            "name": name, "value": round(value, 1), "unit": "%",
            "period": f"FY{row.get('fiscal_year')}",
            "detail": f"FY{row.get('fiscal_year')} 云业务营收同比",
            "analysis": f"FY{row.get('fiscal_year')}云业务营收同比为 {value:+.1f}%，反映该披露口径下的最新业务扩张速度。",
            "components": [_component(f"FY{row.get('fiscal_year')}云业务营收同比", round(value, 1), "%")],
            "component_count": 1,
            "source_url": source_url,
        })
        history = _metric_history(rows, "vendor", vendor, "revenue_yoy")
        previous = _verified_number(history[-2]) if len(history) > 1 else None
        change = value - previous if previous is not None else None
        trend_items.append({
            "name": name,
            "value": round(change, 1) if change is not None else None,
            "unit": "个百分点",
            "detail": f"FY{history[-2].get('fiscal_year')}→FY{row.get('fiscal_year')}" if previous is not None else "缺少上一财年",
            "analysis": (
                f"营收增速由 {previous:.1f}% 变为 {value:.1f}%，同比增速{'加快' if change > 0 else '放缓' if change < 0 else '持平'} {abs(change):.1f} 个百分点。"
                if change is not None else "缺少上一财年可比增速，不推断趋势。"
            ),
            "trend": [{"label": f"FY{item.get('fiscal_year')}", "value": _verified_number(item)} for item in history[-3:]],
            "components": [
                _component(f"FY{item.get('fiscal_year')}", _verified_number(item), "%", item.get("metric_zh") or "云业务营收同比")
                for item in history[-3:]
            ],
            "component_count": len(history[-3:]),
            "source_url": source_url,
        })
        profit_row = None
        for key in profit_keys:
            profit_row = _latest_metric(rows, "vendor", vendor, key)
            if profit_row:
                break
        profit_value = _verified_number(profit_row)
        profit_label = str(profit_row.get("metric_zh") or "利润率") if profit_row else "未披露可比利润率"
        profit_items.append({
            "name": name,
            "value": round(profit_value, 1) if profit_value is not None else None,
            "unit": "%",
            "detail": f"FY{profit_row.get('fiscal_year')} · {profit_label}" if profit_row else "保留披露缺口",
            "analysis": (
                f"最新披露的{profit_label}为 {profit_value:.1f}%；不同厂商可能采用经营利润率、调整后EBITA率或代理分部毛利率，需按标签理解。"
                if profit_value is not None else "数据库未取得可比利润率，未进行估算或跨口径替代。"
            ),
            "components": (
                [_component(profit_label, round(profit_value, 1), "%", f"FY{profit_row.get('fiscal_year')}")]
                if profit_value is not None and profit_row else [_component("未取得可比利润率", detail="不跨口径估算")]
            ),
            "component_count": 1,
            "source_url": str((profit_row or row).get("primary_source_url") or ""),
        })
        vendor_rows = [item for item in rows if item.get("vendor") == vendor and _verified_number(item) is not None]
        latest_year = max((int(str(item.get("fiscal_year") or 0)) for item in vendor_rows), default=0)
        latest_rows = [item for item in vendor_rows if int(str(item.get("fiscal_year") or 0)) == latest_year]
        direct_count = sum(1 for item in latest_rows if str(item.get("disclosure_quality") or "").startswith("direct"))
        quality = str((latest_rows[0] if latest_rows else row).get("disclosure_quality") or "未标注")
        disclosure_items.append({
            "name": name, "value": len(latest_rows), "unit": "项披露",
            "detail": f"FY{latest_year} · {quality}",
            "analysis": (
                f"FY{latest_year}包含 {len(latest_rows)} 项指标，其中 {direct_count} 项为直接分部口径；"
                f"具体覆盖{'、'.join(str(item.get('metric_zh') or item.get('metric_key') or '') for item in latest_rows[:4])}。"
            ),
            "components": _dedupe_components([
                _component(
                    item.get("metric_zh") or item.get("metric_key") or "未命名指标",
                    _verified_number(item),
                    item.get("unit") or "",
                    f"FY{latest_year} · {item.get('disclosure_quality') or '未标口径'}",
                )
                for item in latest_rows
            ]),
            "component_count": len(latest_rows),
            "source_url": str((latest_rows[0] if latest_rows else row).get("primary_source_url") or ""),
        })
    growth_items.sort(key=lambda item: item["value"], reverse=True)
    trend_items.sort(key=lambda item: (_number(item.get("value")) is not None, _number(item.get("value")) or 0), reverse=True)
    profit_items.sort(key=lambda item: (_number(item.get("value")) is not None, _number(item.get("value")) or 0), reverse=True)
    disclosure_items.sort(key=lambda item: item["value"], reverse=True)
    leader = growth_items[0] if growth_items else {"name": "-", "value": 0}
    second_tier = [item for item in growth_items[1:] if item["value"] >= 15]
    tier_names = "、".join(item["name"] for item in second_tier[:3])
    insight = f"{leader['name']}以 {leader['value']:.1f}% 领跑；{tier_names or '其余厂商'}构成第二增长梯队，云端竞争继续向规模与盈利并重演进。"
    best_trend = next((item for item in trend_items if _number(item.get("value")) is not None), None)
    best_profit = next((item for item in profit_items if _number(item.get("value")) is not None), None)
    focuses = [
        {
            "id": "growth", "label": "业务增速", "visual": "columns",
            "metric": {"value": f"{leader['value']:.1f}", "unit": "%", "label": "FY2025 增速领先值"},
            "context": f"覆盖 {len(growth_items)} 家全球云厂商", "insight": insight, "items": growth_items,
        },
        {
            "id": "trend", "label": "增长趋势", "visual": "trends",
            "metric": {"value": best_trend["value"] if best_trend else "-", "unit": "个百分点", "label": "最大增速变化"},
            "context": "FY2025 相对 FY2024",
            "insight": "此处比较增速变化而非增速绝对值，可区分高增长继续加速与高基数下放缓。",
            "items": trend_items,
        },
        {
            "id": "profit", "label": "盈利能力", "visual": "diverging",
            "metric": {"value": best_profit["value"] if best_profit else "-", "unit": "%", "label": "已披露最高利润率"},
            "context": "按各厂商披露口径标注",
            "insight": "利润率口径并不完全相同，图中保留经营利润率、调整后EBITA率或代理分部毛利率标签，不做伪同口径结论。",
            "items": profit_items,
        },
        {
            "id": "disclosure", "label": "业绩披露", "visual": "disclosure",
            "metric": {"value": sum(item["value"] for item in disclosure_items), "unit": "项", "label": "FY2025 结构化披露"},
            "context": "直接分部与代理口径分别保留",
            "insight": "披露视图展示可分析指标数量和口径质量；代理分部不冒充纯云业务数据。",
            "items": disclosure_items,
        },
    ]
    return {
        "id": "cloud",
        "index": "03",
        "title": "云厂商",
        "kicker": "增长梯队与云网融合",
        "metric": {"value": f"{leader['value']:.1f}", "unit": "%", "label": "FY2025 增速领先值"},
        "context": f"覆盖 {len(growth_items)} 家全球云厂商",
        "insight": insight,
        "entities": growth_items,
        "focuses": focuses,
        "relations": [
            {"title": item["name"], "detail": f"FY2025 营收同比 {item['value']:+.1f}%", "kind": "增长梯队"}
            for item in growth_items
        ],
        "sources": _dedupe_sources([_source(item["name"], item["source_url"]) for item in growth_items]),
    }


def _macro_domain(rows: list[dict[str, Any]]) -> dict[str, Any]:
    focus_specs = [
        {
            "id": "market", "label": "市场规模", "title": "移动服务订户及连接",
            "keys": [
                ("mobile_subscriptions", "移动服务订户及连接"),
                ("mobile_broadband_subscriptions", "移动宽带用户"),
                ("broadband_access_lines_total", "宽带接入线"),
                ("household_broadband_penetration_rate", "家庭宽带渗透率"),
            ],
        },
        {
            "id": "traffic", "label": "流量需求", "title": "移动数据总量",
            "keys": [
                ("mobile_data_usage_total_mbytes", "移动数据总量"),
                ("mobile_data_usage_per_mobile_broadband_subscription_mbytes", "每移动宽带用户流量"),
                ("mobile_data_usage_per_capita_mbytes", "人均移动流量"),
                ("post_paid_sim_subscriptions", "后付费SIM"),
            ],
        },
        {
            "id": "spending", "label": "消费能力", "title": "家庭月入中位数",
            "keys": [
                ("median_monthly_household_income", "家庭月入中位数"),
                ("total_retail_sales_val_rs", "零售销售额"),
                ("private_consumption_expenditure_by_component_in_chained_dollars_pce_con", "私人消费开支"),
                ("consumer_price_indices_a_cm_1920", "甲类消费物价指数"),
            ],
        },
        {
            "id": "governance", "label": "投入监管", "title": "电信业投资",
            "keys": [
                ("annual_telecom_investment", "电信业投资"),
                ("telecom_consumer_complaints_total", "电讯投诉"),
                ("5g_population_coverage_status", "5G人口覆盖"),
                ("5g_spectrum_assigned_mhz", "5G相关频谱"),
            ],
        },
    ]
    wanted = {key: label for focus in focus_specs for key, label in focus["keys"]}
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        metric = str(row.get("metric_key") or "")
        if metric not in wanted or _number(row.get("value")) is None:
            continue
        current = latest.get(metric)
        if not current or str(row.get("period_end") or "") > str(current.get("period_end") or ""):
            latest[metric] = row

    def display_metric(metric: str, label: str) -> dict[str, Any] | None:
        row = latest.get(metric)
        if not row:
            return None
        value = _number(row.get("value")) or 0
        unit = str(row.get("unit") or "")
        raw_unit = unit
        raw_value_text = f"{value:g}"
        display_value: float | str = value
        display_unit = unit
        if metric in {"mobile_subscriptions", "mobile_broadband_subscriptions", "broadband_access_lines_total", "post_paid_sim_subscriptions"}:
            display_value, display_unit = round(value / 10_000, 1), "万"
            raw_value_text = f"{value:,.0f}"
        elif metric == "annual_telecom_investment":
            display_value, display_unit = round(value / 100, 2), "亿港元"
            raw_unit = "百万港元"
        elif metric == "mobile_data_usage_total_mbytes":
            display_value, display_unit = round(value / 1_000_000_000, 1), "十亿MB"
        elif metric in {"mobile_data_usage_per_mobile_broadband_subscription_mbytes", "mobile_data_usage_per_capita_mbytes"}:
            display_value, display_unit = round(value / 1024, 1), "GB"
        elif metric in {"total_retail_sales_val_rs", "private_consumption_expenditure_by_component_in_chained_dollars_pce_con"}:
            display_value, display_unit = round(value / 100, 1), "亿港元"
            raw_unit = "百万港元"
        elif unit == "percent_plus":
            display_unit = "%+"
        elif unit == "HKD":
            display_unit = "港元"
        elif unit == "complaints":
            display_unit = "宗"
        elif unit == "percent":
            display_unit = "%"
        return {
            "name": label,
            "value": display_value,
            "unit": display_unit,
            "detail": f"截至 {row.get('period_end') or '-'}",
            "analysis": f"官方指标 {row.get('metric_name') or label} 最新值为 {display_value} {display_unit}；原始记录为 {raw_value_text} {raw_unit}。",
            "components": [
                _component(row.get("metric_name") or label, display_value, display_unit, f"截至 {row.get('period_end') or '-'}")
            ],
            "component_count": 1,
            "source_url": str(row.get("official_source_url") or ""),
        }

    focuses: list[dict[str, Any]] = []
    all_items: list[dict[str, Any]] = []
    for spec in focus_specs:
        items = [item for key, label in spec["keys"] if (item := display_metric(key, label))]
        all_items.extend(items)
        lead = items[0] if items else {"value": "-", "unit": ""}
        if spec["id"] == "market":
            insight = "移动连接规模与家庭宽带渗透率共同反映市场饱和度；高渗透下应更关注存量价值而非单纯用户数。"
        elif spec["id"] == "traffic":
            insight = "总流量、每用户流量与后付费SIM规模共同判断网络需求和可变现流量基础。"
        elif spec["id"] == "spending":
            insight = "家庭收入、零售及私人消费用于判断套餐升级承受力；消费物价指数用于识别实际购买力压力。"
        else:
            insight = "投资、投诉、覆盖与频谱共同约束网络竞争：投入需转化为体验，投诉反映服务风险。"
        focuses.append({
            "id": spec["id"], "label": spec["label"], "visual": "kpis",
            "metric": {"value": lead["value"], "unit": lead["unit"], "label": spec["title"]},
            "context": f"{len(items)} 项最新官方指标",
            "insight": insight,
            "items": items,
        })
    entities = all_items
    subscriptions = _number((latest.get("mobile_subscriptions") or {}).get("value")) or 0
    coverage = _number((latest.get("5g_population_coverage_status") or {}).get("value")) or 0
    insight = f"移动服务订户及连接达 {subscriptions / 10_000:.1f} 万、5G人口覆盖超过 {coverage:.0f}%；该数包含机器类型连接，不等同于独立用户人数。"
    return {
        "id": "macro",
        "index": "04",
        "title": "宏观政策",
        "kicker": "市场底盘与监管变量",
        "metric": {"value": f"{subscriptions / 10_000:.1f}", "unit": "万", "label": "移动服务订户及连接"},
        "context": f"宏观与政策明细 {len(rows):,} 条",
        "insight": insight,
        "entities": entities,
        "focuses": focuses,
        "relations": [
            {"title": item["name"], "detail": f"{item['value']} {item['unit']} · {item['detail']}", "kind": "官方指标"}
            for item in entities
        ],
        "sources": _dedupe_sources([_source(item["name"], item["source_url"]) for item in entities]),
    }


def _analysis_evidence_snapshot(domains: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the exact source-backed payload used to generate model summaries."""
    evidence_domains: list[dict[str, Any]] = []
    for domain in domains:
        focuses = []
        for focus in domain.get("focuses") or []:
            focuses.append(
                {
                    "id": focus.get("id"),
                    "label": focus.get("label"),
                    "metric": focus.get("metric"),
                    "insight": focus.get("insight"),
                    "items": [
                        {
                            "name": item.get("name"),
                            "value": item.get("value"),
                            "unit": item.get("unit"),
                            "detail": item.get("detail"),
                            "analysis": item.get("analysis"),
                            "components": item.get("components") or [],
                            "component_count": item.get("component_count"),
                            "record_count": item.get("record_count"),
                            "source_url": item.get("source_url"),
                        }
                        for item in (focus.get("items") or [])[:8]
                    ],
                }
            )
        evidence_domains.append(
            {
                "id": domain.get("id"),
                "title": domain.get("title"),
                "metric": domain.get("metric"),
                "deterministic_insight": domain.get("insight"),
                "focuses": focuses,
                "agent_verified_facts": (domain.get("ai_analysis") or [])[:8],
            }
        )
    return {"domains": evidence_domains, "relations": []}


def _content_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@lru_cache(maxsize=4)
def _build_cached(signature: tuple[int, ...]) -> dict[str, Any]:
    del signature
    local = _local_domain(_read_json(LOCAL_PATH))
    international = _international_domain(_read_json(INTERNATIONAL_PATH))
    cloud = _cloud_domain(_read_json(CLOUD_PATH))
    macro = _macro_domain(_read_json(MACRO_PATH))
    domains = [local, international, cloud, macro]
    ai_payload = _read_json_optional(AI_ANALYSIS_PATH, {})
    ai_domains = ai_payload.get("domains") if isinstance(ai_payload, dict) else {}
    for domain in domains:
        domain["ai_analysis"] = list((ai_domains or {}).get(domain["id"]) or [])
    evidence = _analysis_evidence_snapshot(domains)
    evidence_hash = _content_hash(evidence)
    model_analysis = ai_payload.get("model_analysis") or {} if isinstance(ai_payload, dict) else {}
    model_analysis_fresh = bool(
        str(model_analysis.get("evidence_hash") or "")
        and str(model_analysis.get("evidence_hash") or "") == evidence_hash
    )
    model_summaries = {
        str(item.get("domain") or ""): item
        for item in (model_analysis.get("summaries") or [])
        if isinstance(item, dict)
    } if model_analysis_fresh else {}
    for domain in domains:
        domain["ai_summary"] = model_summaries.get(domain["id"], {})
        focus_summaries = {
            str(item.get("id") or ""): item
            for item in (domain["ai_summary"].get("focuses") or [])
            if isinstance(item, dict)
        }
        for focus in domain.get("focuses") or []:
            focus_summary = focus_summaries.get(str(focus.get("id") or ""), {})
            focus["ai_summary"] = focus_summary
            entity_summaries = {
                str(item.get("name") or ""): item
                for item in (focus_summary.get("entities") or [])
                if isinstance(item, dict)
            }
            for entity in focus.get("items") or []:
                entity["ai_summary"] = entity_summaries.get(str(entity.get("name") or ""), {})
        domain["ai_updated_at"] = str(ai_payload.get("generated_at_hkt") or "") if isinstance(ai_payload, dict) else ""
        domain["ai_run_id"] = str(ai_payload.get("agent_run_id") or "") if isinstance(ai_payload, dict) else ""
    deterministic_relations = [
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
            "detail": (
                f"云厂商 {cloud['entities'][0].get('period', '最新财年')} 领先增速 {cloud['metric']['value']}%，"
                f"运营商 {international['entities'][0].get('period', '最新季度')} 领先增速 {international['metric']['value']}%；"
                "报告期间与业务口径不同，只作方向性参照。"
            ),
            "kind": "跨期间方向参照",
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
    model_discoveries = [
        item for item in (model_analysis.get("discoveries") or [])
        if isinstance(item, dict)
        and item.get("from") in {"local", "international", "cloud", "macro"}
        and item.get("to") in {"local", "international", "cloud", "macro"}
        and item.get("from") != item.get("to")
        and str(item.get("title") or "").strip()
        and str(item.get("detail") or "").strip()
    ] if model_analysis_fresh else []
    relations = [
        {
            "from": item["from"],
            "to": item["to"],
            "title": str(item["title"]).strip(),
            "detail": str(item["detail"]).strip(),
            "kind": str(item.get("kind") or "AI综合研判").strip(),
            "source_urls": list(item.get("source_urls") or []),
            "origin": "ai",
        }
        for item in model_discoveries[:4]
    ] if len(model_discoveries) >= 4 else deterministic_relations
    refresh_state = _read_json_optional(REFRESH_STATE_PATH, {})
    return {
        "domains": domains,
        "relations": relations,
        "method": "四库指标只使用通过质量门禁的记录；AI分析只使用Agent发布层accepted事实。跨期间、代理口径和战略推断均单独标注。",
        "refresh": refresh_state if isinstance(refresh_state, dict) else {},
        "ai": {
            "agent_run_id": ai_payload.get("agent_run_id", "") if isinstance(ai_payload, dict) else "",
            "updated_at": ai_payload.get("generated_at_hkt", "") if isinstance(ai_payload, dict) else "",
            "domain_counts": ai_payload.get("domain_counts", {}) if isinstance(ai_payload, dict) else {},
            "model_analysis": model_analysis,
            "evidence_hash": evidence_hash,
            "model_analysis_fresh": model_analysis_fresh,
            "discoveries_generated": bool(len(model_discoveries) >= 4),
        },
        "source_record_count": sum(int(domain["metric"]["value"]) if domain["id"] == "local" else len(domain["entities"]) for domain in domains),
    }


def build_executive_intelligence_snapshot() -> dict[str, Any]:
    signature = tuple(path.stat().st_mtime_ns if path.exists() else 0 for path in DOMAIN_PATHS)
    return _build_cached(signature)


def build_executive_intelligence_evidence_snapshot() -> dict[str, Any]:
    """Expose the source-only evidence pack used for AI freshness checks."""
    snapshot = build_executive_intelligence_snapshot()
    return _analysis_evidence_snapshot(snapshot.get("domains") or [])

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
    captured_at = max((str(row.get("captured_at_hkt") or "") for row in rows), default="")
    captured_display = captured_at[:16].replace("T", " ") if captured_at else ""
    data_time_note = (
        f"数据采集于 {captured_display}（香港时间）"
        if captured_display else "数据库未记录更新日期"
    )
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
            "unit": "条记录",
            "detail": f"销售 {len(categories)} 类套餐",
            "analysis": (
                f"数据库有 {len(profile['rows'])} 条在售套餐记录，按套餐名称去重后为 {len(plan_components)} 个，"
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
            "unit": "类套餐",
            "detail": "、".join(labels[:4]) or "未分类",
            "analysis": f"销售 {len(categories)} 类套餐，主要包括{'、'.join(labels[:3]) or '未分类产品'}。",
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
            "detail": f"月费范围 HK${fee_range[0]:.0f}–{fee_range[1]:.0f}" if fee_range else "数据库内没有可计算的月费",
            "analysis": (
                f"数据库内可计算月费的中位数为 HK${median_fee:.0f}，月费范围为 HK${fee_range[0]:.0f}–{fee_range[1]:.0f}。"
                if median_fee is not None and fee_range else "当前品牌缺少可比月费，不进行估算。"
            ),
            "components": plan_components,
            "component_count": len(plan_components),
            "source_url": profile["source_url"],
        })
        overlap_items.append({
            "name": brand,
            "value": len(shared_categories),
            "unit": "类共同套餐",
            "peers": len(brand_overlaps),
            "detail": f"与 {len(brand_overlaps)} 家运营商销售同类套餐",
            "analysis": (
                f"与 {strongest['peer']} 共同销售 {len(strongest['shared'])} 类套餐"
                + (f"，双方月费范围均覆盖 HK${strongest['fee_overlap'][0]:.0f}–{strongest['fee_overlap'][1]:.0f}。" if strongest.get("fee_overlap") else "。")
                if strongest else "数据库当前未发现共同销售的套餐类型。"
            ),
            "components": [
                _component(
                    item["peer"],
                    len(item["shared"]),
                    "类共同套餐",
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
            fee_label = f"，双方月费范围均覆盖 HK${lead['fee_overlap'][0]:.0f}–{lead['fee_overlap'][1]:.0f}"
        pair_label = str(lead["pair"]).replace(" × ", " 与 ")
        insight = f"{pair_label} 都销售{shared_label}{fee_label}。"
    else:
        insight = "数据库已按运营商、套餐类型和月费范围整理本地在售套餐。"

    focuses = [
        {
            "id": "scale", "label": "在售记录数", "visual": "columns",
            "metric": {"value": len(rows), "unit": "条", "label": "数据库收录的在售套餐记录"},
            "context": f"比较 {len(by_brand)} 家本地运营商；{data_time_note}",
            "insight": f"数据库目前收录 {scale_items[0]['name']} 的在售套餐记录最多，共 {scale_items[0]['value']} 条；点击公司可查看去重后的套餐。" if scale_items else "数据库暂无在售套餐记录。",
            "items": scale_items,
        },
        {
            "id": "track", "label": "套餐类型", "visual": "rows",
            "metric": {
                **_focus_metric(track_items, "套餐类型", "类"),
                "label": f"{track_items[0]['name']}覆盖的套餐类型" if track_items else "覆盖的套餐类型",
            },
            "context": f"数据库共归为 {len(category_labels)} 类套餐；{data_time_note}",
            "insight": f"{track_items[0]['name']}目前销售 {track_items[0]['value']} 类套餐，是数据库中覆盖套餐类型最多的运营商。" if track_items else "数据库暂无套餐类型数据。",
            "items": track_items,
        },
        {
            "id": "price", "label": "月费（港元/月）", "visual": "ranges",
            "metric": {
                **_focus_metric(price_items, "月费中位数", "港元/月", mode="min"),
                "label": f"{price_items[-1]['name']}月费中位数" if price_items else "月费中位数",
            },
            "context": f"只比较数据库中可计算的平均月费；{data_time_note}",
            "insight": _local_price_insight(price_items),
            "items": price_items,
        },
        {
            "id": "overlap", "label": "同类套餐竞争", "visual": "network",
            "metric": {
                **_focus_metric(overlap_items, "共同销售的套餐类型", "类"),
                "label": f"{overlap_items[0]['name']}与其他运营商共同销售的套餐类型" if overlap_items else "共同销售的套餐类型",
            },
            "context": f"比较 {len(overlaps)} 组运营商的套餐类型与月费范围；{data_time_note}",
            "insight": insight,
            "items": overlap_items,
        },
    ]
    entities = scale_items
    sources = _dedupe_sources([_source(item["name"], item["source_url"]) for item in scale_items])
    return {
        "id": "local",
        "index": "01",
        "title": "本地运营商",
        "kicker": "在售套餐与月费",
        "metric": {"value": len(rows), "unit": "条", "label": "数据库收录的在售套餐记录"},
        "context": data_time_note,
        "data_time": data_time_note,
        "insight": insight,
        "entities": entities,
        "focuses": focuses,
        "relations": [
            {
                "title": item["pair"],
                "detail": f"共同销售 {len(item['shared'])} 类套餐" + (
                    f" · 双方月费范围均覆盖 HK${item['fee_overlap'][0]:.0f}–{item['fee_overlap'][1]:.0f}"
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
    investment_items: list[dict[str, Any]] = []
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
            "unit": "个百分点" if change is not None else "",
            "detail": (
                f"较{history[-2].get('period')} {'改善' if change >= 0 else '回落'} {abs(change):.2f} 个百分点"
                if change is not None else "缺少上一可比期"
            ),
            "analysis": (
                f"营收增速由 {previous_value:+.2f}% 变为 {value:+.2f}%，较上期{'增加' if change > 0 else '减少' if change < 0 else '没有变化'} {abs(change):.2f} 个百分点。"
                if change is not None else "当前只有一个可比期，无法计算增速较上期的变化。"
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
        capex_row = _latest_metric(rows, "subject", subject, "capital_expenditures")
        revenue_row = _latest_metric(rows, "subject", subject, "revenue")
        capex_value = _verified_number(capex_row)
        revenue_value = _verified_number(revenue_row)
        capex_period = str((capex_row or {}).get("period") or "")
        revenue_period = str((revenue_row or {}).get("period") or "")
        periods_match = bool(capex_period and capex_period == revenue_period)
        intensity = (
            abs(capex_value) / revenue_value * 100
            if capex_value is not None and revenue_value not in (None, 0) and periods_match
            else None
        )
        investment_items.append({
            "name": subject,
            "value": round(intensity, 2) if intensity is not None else None,
            "unit": "%" if intensity is not None else "",
            "period": capex_period or revenue_period,
            "detail": (
                f"{capex_period}资本开支占营收"
                if intensity is not None else "缺少同期间官方资本开支或营收"
            ),
            "analysis": (
                f"{capex_period}资本开支为人民币{abs(capex_value) / 100:.1f}亿元，"
                f"占同期营收{intensity:.2f}%；该比例只表示资本开支相对营收的大小，不代表投资回报。"
                if intensity is not None else "当前缺少同期间、同币种的官方资本开支与营收，无法计算资本开支占营收比例。"
            ),
            "components": (
                [
                    _component("资本开支", round(abs(capex_value) / 100, 1), "亿元人民币", capex_period),
                    _component("同期营收", round(revenue_value / 100, 1), "亿元人民币", revenue_period),
                ]
                if intensity is not None else [_component("资本开支占营收", detail="缺少同期间官方数据")]
            ),
            "component_count": 2 if intensity is not None else 1,
            "source_url": str((capex_row or revenue_row or row).get("official_source_url") or ""),
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
    investment_items.sort(key=lambda item: (_number(item.get("value")) is not None, _number(item.get("value")) or 0), reverse=True)
    disclosure_items.sort(key=lambda item: item["value"], reverse=True)
    leader = growth_items[0] if growth_items else {"name": "-", "value": 0}
    momentum_leader = next((item for item in momentum_items if _number(item.get("value")) is not None), None)
    investment_leader = next((item for item in investment_items if _number(item.get("value")) is not None), None)
    investment_comparable = [item for item in investment_items if _number(item.get("value")) is not None]
    if len(investment_comparable) >= 2:
        investment_low = investment_comparable[-1]
        investment_gap = float(investment_leader["value"]) - float(investment_low["value"])
        investment_period = str(investment_leader.get("period") or "最新期")
        investment_peers = "、".join(
            f"{item['name']}{float(item['value']):.2f}%"
            for item in investment_comparable[1:]
        )
        investment_insight = (
            f"{investment_period}{investment_leader['name']}资本开支/营收为{investment_leader['value']:.2f}%，"
            f"高于{investment_peers}；"
            f"三家公司最高与最低相差{investment_gap:.2f}个百分点；该比例不代表投资回报。"
        )
    else:
        investment_insight = "当前只有不足两家公司同时具备同期间资本开支和营收，无法横向比较该比例。"
    positive = [item for item in growth_items if item["value"] >= 0]
    negative = [item for item in growth_items if item["value"] < 0]
    momentum_comparable = [item for item in momentum_items if _number(item.get("value")) is not None]
    if momentum_comparable:
        improving = [item for item in momentum_comparable if float(item["value"]) > 0]
        slowing = [item for item in momentum_comparable if float(item["value"]) < 0]
        if len(improving) == len(momentum_comparable):
            momentum_insight = f"{len(improving)} 家公司的营收同比增速均较上一可比期加快。"
        elif len(slowing) == len(momentum_comparable):
            momentum_insight = f"{len(slowing)} 家公司的营收同比增速均较上一可比期放缓。"
        else:
            momentum_insight = f"{len(improving)} 家加快、{len(slowing)} 家放缓；各公司均与自己的上一可比期相比。"
    else:
        momentum_insight = "当前缺少两个可比期间的营收增速，不作增长节奏判断。"
    if disclosure_items:
        disclosure_leader = disclosure_items[0]
        disclosure_laggard = disclosure_items[-1]
        disclosure_insight = (
            f"{disclosure_leader['name']}最新期有{disclosure_leader['value']}项可核验披露，"
            f"{disclosure_laggard['name']}为{disclosure_laggard['value']}项；后者可支持的横向判断更有限。"
        )
    else:
        disclosure_insight = "当前没有可核验的结构化披露，不作横向判断。"
    insight = f"各公司最近披露期中，{leader['name']}营收同比增长最高，为 {leader['value']:.2f}%；{len(positive)} 家增长、{len(negative)} 家下降。各公司披露期可能不同，需结合图中期间阅读。"
    focuses = [
        {
            "id": "growth", "label": "营收同比（%）", "visual": "diverging",
            "metric": {"value": f"{leader['value']:.2f}", "unit": "%", "label": f"{leader['name']} {leader.get('period') or '最近披露期'}营收同比增长"},
            "context": f"比较 {len(growth_items)} 家公司最近披露的营收同比数据", "insight": insight, "items": growth_items,
        },
        {
            "id": "momentum", "label": "增速较上期变化", "visual": "trends",
            "metric": {
                "value": momentum_leader["value"] if momentum_leader else "-",
                "unit": "个百分点",
                "label": f"{momentum_leader['name']}增速变化" if momentum_leader else "增速变化",
            },
            "context": "最新期相对上一可比期",
            "insight": momentum_insight,
            "items": momentum_items,
        },
        {
            "id": "investment", "label": "资本开支/营收（%）", "visual": "rows",
            "metric": {
                "value": investment_leader["value"] if investment_leader else "-",
                "unit": "%",
                "label": f"{investment_leader['name']}资本开支/营收" if investment_leader else "资本开支/营收",
            },
            "context": "同期间资本开支占营收比例",
            "insight": investment_insight,
            "items": investment_items,
        },
        {
            "id": "disclosure", "label": "可核验指标数", "visual": "disclosure",
            "metric": {"value": sum(item["value"] for item in disclosure_items), "unit": "项", "label": "最新期结构化披露"},
            "context": "仅计数据库内有数值记录",
            "insight": disclosure_insight,
            "items": disclosure_items,
        },
    ]
    return {
        "id": "international",
        "index": "02",
        "title": "国际电讯企业",
        "kicker": "营收增长与资本开支",
        "metric": {"value": f"{leader['value']:.2f}", "unit": "%", "label": f"{leader['name']} {leader.get('period') or '最近披露期'}营收同比增长"},
        "context": f"比较 {len(growth_items)} 家公司最近披露的营收同比数据",
        "insight": insight,
        "entities": growth_items,
        "focuses": focuses,
        "relations": [
            {"title": item["name"], "detail": f"{item.get('period') or '最近披露期'}营收同比 {item['value']:+.2f}%", "kind": "公司披露数据"}
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
        disclosure_quality = str(row.get("disclosure_quality") or "")
        if disclosure_quality.startswith("direct"):
            growth_scope = "公司直接披露的云业务口径"
        elif "proxy" in disclosure_quality:
            growth_scope = "代理分部口径，可能包含非云业务"
        elif "reclassification" in disclosure_quality:
            growth_scope = "含重分类的分部口径"
        else:
            growth_scope = "公司披露口径"
        growth_items.append({
            "name": name, "value": round(value, 1), "unit": "%",
            "period": f"FY{row.get('fiscal_year')}",
            "detail": f"FY{row.get('fiscal_year')} · {growth_scope}",
            "analysis": f"FY{row.get('fiscal_year')}该披露口径的收入同比变化为 {value:+.1f}%；{growth_scope}。不同口径不可直接视为纯云业务排名。",
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
            "unit": "个百分点" if change is not None else "",
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
            "unit": "%" if profit_value is not None else "",
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
        quality_labels = {
            "direct_product_line_and_segment": "直接产品线及分部口径",
            "official_proxy_segment": "官方代理分部口径",
            "direct_segment_non_gaap_profit": "直接分部口径（利润为非GAAP）",
            "proxy_segment": "代理分部口径",
            "segment_with_reclassification": "含重分类的分部口径",
            "direct_segment": "直接分部口径",
        }
        quality = quality_labels.get(
            str((latest_rows[0] if latest_rows else row).get("disclosure_quality") or ""),
            "数据库未标注口径",
        )
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
                    f"FY{latest_year} · {quality_labels.get(str(item.get('disclosure_quality') or ''), '数据库未标注口径')}",
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
    tier_names = "、".join(f"{item['name']} {item['value']:.1f}%" for item in second_tier[:3])
    insight = f"各公司最近披露财年中，{leader['name']}披露的收入同比变化为 {leader['value']:.1f}%" + (f"；其后为 {tier_names}。" if tier_names else "。") + "各公司业务范围可能不同。"
    best_trend = next((item for item in trend_items if _number(item.get("value")) is not None), None)
    focuses = [
        {
            "id": "growth", "label": "披露收入同比（%）", "visual": "columns",
            "metric": {"value": f"{leader['value']:.1f}", "unit": "%", "label": f"{leader['name']} {leader.get('period') or '最近财年'}收入同比变化"},
            "context": f"覆盖 {len(growth_items)} 家全球云厂商", "insight": insight, "items": growth_items,
        },
        {
            "id": "trend", "label": "增速较上年变化", "visual": "trends",
            "metric": {
                "value": best_trend["value"] if best_trend else "-",
                "unit": "个百分点",
                "label": f"{best_trend['name']}增速变化" if best_trend else "增速变化",
            },
            "context": "FY2025 相对 FY2024",
            "insight": "这里比较每家公司 FY2025 与 FY2024 的收入同比增速差值；正数表示增速加快，负数表示增速放缓。",
            "items": trend_items,
        },
        {
            "id": "profit", "label": "已披露利润率（%）", "visual": "diverging",
            "metric": {
                "value": sum(1 for item in profit_items if _number(item.get("value")) is not None),
                "unit": "家",
                "label": "有利润率披露的厂商",
            },
            "context": "按各厂商披露口径标注",
            "insight": "各公司披露的是经营利润率、调整后EBITA率或代理分部毛利率，口径不同，因此不作为同一指标排名。",
            "items": profit_items,
        },
        {
            "id": "disclosure", "label": "可核验指标数", "visual": "disclosure",
            "metric": {"value": sum(item["value"] for item in disclosure_items), "unit": "项", "label": "FY2025 结构化披露"},
            "context": "直接分部与代理口径分别保留",
            "insight": "这里统计数据库中各公司可核验的指标数量，并逐项注明直接分部或代理分部口径。",
            "items": disclosure_items,
        },
    ]
    return {
        "id": "cloud",
        "index": "03",
        "title": "云厂商",
        "kicker": "营收增速与已披露利润率",
        "metric": {"value": f"{leader['value']:.1f}", "unit": "%", "label": f"{leader['name']} {leader.get('period') or '最近财年'}收入同比变化"},
        "context": f"覆盖 {len(growth_items)} 家全球云厂商",
        "insight": insight,
        "entities": growth_items,
        "focuses": focuses,
        "relations": [
            {"title": item["name"], "detail": f"FY2025 披露收入同比 {item['value']:+.1f}%", "kind": "公司披露数据"}
            for item in growth_items
        ],
        "sources": _dedupe_sources([_source(item["name"], item["source_url"]) for item in growth_items]),
    }


def _macro_domain(rows: list[dict[str, Any]]) -> dict[str, Any]:
    focus_specs = [
        {
            "id": "market", "label": "用户与连接", "title": "移动服务订户及连接",
            "keys": [
                ("mobile_subscriptions", "移动服务订户及连接"),
                ("mobile_broadband_subscriptions", "移动宽带用户"),
                ("broadband_access_lines_total", "宽带接入线"),
                ("household_broadband_penetration_rate", "家庭宽带渗透率"),
            ],
        },
        {
            "id": "traffic", "label": "移动数据用量", "title": "移动数据总量",
            "keys": [
                ("mobile_data_usage_total_mbytes", "移动数据总量"),
                ("mobile_data_usage_per_mobile_broadband_subscription_mbytes", "每移动宽带用户流量"),
                ("mobile_data_usage_per_capita_mbytes", "人均移动流量"),
                ("post_paid_sim_subscriptions", "后付费SIM"),
            ],
        },
        {
            "id": "spending", "label": "家庭收入与消费", "title": "家庭月入中位数",
            "keys": [
                ("median_monthly_household_income", "家庭月入中位数"),
                ("total_retail_sales_val_rs", "零售销售额"),
                ("private_consumption_expenditure_by_component_in_chained_dollars_pce_con", "私人消费开支"),
                ("consumer_price_indices_a_cm_1920", "甲类消费物价指数"),
            ],
        },
        {
            "id": "governance", "label": "网络投入与服务", "title": "香港电信业投资",
            "keys": [
                ("annual_telecom_investment", "电信业投资"),
                ("telecom_consumer_complaints_total", "电讯投诉"),
                ("5g_population_coverage_status", "5G网络覆盖的人口比例"),
                ("5g_spectrum_assigned_mhz", "公共移动及5G服务已分配频谱"),
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
            display_value, display_unit = round(value / 100_000_000, 1), "亿MB"
        elif metric in {"mobile_data_usage_per_mobile_broadband_subscription_mbytes", "mobile_data_usage_per_capita_mbytes"}:
            display_value, display_unit = round(value / 1024, 1), "GB"
        elif metric in {"total_retail_sales_val_rs", "private_consumption_expenditure_by_component_in_chained_dollars_pce_con"}:
            display_value, display_unit = round(value / 100, 1), "亿港元"
            raw_unit = "百万港元"
        elif unit == "percent_plus":
            display_value, display_unit = f"超过{value:g}%", ""
        elif unit == "HKD":
            display_unit = "港元"
        elif unit == "complaints":
            display_unit = "宗"
        elif unit == "percent":
            display_unit = "%"
        elif unit == "index":
            display_unit = "点"
        period_note = f"截至 {row.get('period_end') or '-'}"
        if metric == "telecom_consumer_complaints_total":
            period_note += "；数据库未标明统计周期"
        if metric == "consumer_price_indices_a_cm_1920":
            period_note += "；基期为2019年10月至2020年9月=100"
        source_name = str(row.get("metric_name") or "")
        source_note = f"来源原名：{source_name}。" if source_name and source_name != label else ""
        return {
            "name": label,
            "value": display_value,
            "unit": display_unit,
            "detail": period_note,
            "analysis": f"{label}最新值为 {display_value}{display_unit}（{period_note}）。{source_note}数据库原始记录为 {raw_value_text} {raw_unit}。",
            "components": [
                _component(label, display_value, display_unit, period_note)
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
            insight = "这里分别展示移动服务订户及连接、移动宽带订户、固定宽带接入线和家庭宽带渗透率；移动连接包含机器类型连接，不等同于人数。"
        elif spec["id"] == "traffic":
            insight = "这里分别展示移动数据总量、每个移动宽带订户用量、人均用量和后付费SIM数量；各指标统计对象不同。"
        elif spec["id"] == "spending":
            insight = "这里分别展示家庭月入中位数、零售销售额、私人消费开支和甲类消费物价指数；金额与指数不可直接相加或互相替代。"
        else:
            insight = "这里分别展示香港电信业投资、电讯投诉、5G人口覆盖和已分配频谱；投诉记录的统计周期需以来源说明为准。"
        focuses.append({
            "id": spec["id"], "label": spec["label"],
            "visual": "governance" if spec["id"] == "governance" else "kpis",
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
        "title": "香港电讯市场",
        "kicker": "用户、用量、投入与服务",
        "metric": {"value": f"{subscriptions / 10_000:.1f}", "unit": "万", "label": "移动服务订户及连接"},
        "context": f"数据库有 {len(rows):,} 条市场与监管记录",
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
            "title": "香港连接规模与本地套餐记录",
            "detail": f"移动服务订户及连接 {macro['metric']['value']} 万（含机器类型连接）；本地数据库有 {local['metric']['value']} 条在售套餐记录。两者统计对象不同，不直接比较。",
            "kind": "数据并列",
        },
        {
            "from": "international",
            "to": "cloud",
            "title": "云厂商与电讯企业披露口径不同",
            "detail": (
                f"云厂商页面最高值为 {cloud['metric']['value']}%，国际电讯企业页面最高值为 {international['metric']['value']}%；"
                "报告期间和业务范围不同，不作高低排名。"
            ),
            "kind": "不可直接比较",
        },
        {
            "from": "local",
            "to": "cloud",
            "title": "本地套餐与云厂商指标分别展示",
            "detail": "本地页面统计在售套餐类型与月费；云厂商页面统计各公司披露的收入与利润率。两组数据没有共同统计口径。",
            "kind": "数据边界",
        },
        {
            "from": "macro",
            "to": "international",
            "title": "香港行业投资与公司资本开支分别统计",
            "detail": "香港页面展示全行业电信业投资；国际企业页面展示各公司资本开支占营收比例。统计范围不同，不直接比较。",
            "kind": "数据边界",
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
        "method": "页面只使用通过质量检查的数据库记录；不同期间、代理分部口径和不可直接比较的数据均单独说明。",
        "refresh": refresh_state if isinstance(refresh_state, dict) else {},
        "ai": {
            "agent_run_id": ai_payload.get("agent_run_id", "") if isinstance(ai_payload, dict) else "",
            "updated_at": ai_payload.get("generated_at_hkt", "") if isinstance(ai_payload, dict) else "",
            "domain_counts": ai_payload.get("domain_counts", {}) if isinstance(ai_payload, dict) else {},
            "model_analysis": model_analysis if model_analysis_fresh else {},
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

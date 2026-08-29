from __future__ import annotations

import json
import hashlib
import re
from functools import lru_cache
from datetime import datetime
from pathlib import Path
from typing import Any

from cmhk.data.local_financial_results import DATABASE_PATH as CANONICAL_LOCAL_FINANCIAL_PATH


ROOT = Path(__file__).resolve().parents[2]
LOCAL_PATH = ROOT / "agent_knowledge/hk_competitor_product_tariffs/current_plans.json"
INTERNATIONAL_PATH = ROOT / "agent_knowledge/quarterly_competitor_metrics_2026-06-18/quarterly_metrics.json"
LEGACY_LOCAL_FINANCIAL_PATH = ROOT / "agent_knowledge/hk_competitor_product_tariffs/local_financial_results.json"
LOCAL_FINANCIAL_PATH = (
    CANONICAL_LOCAL_FINANCIAL_PATH
    if CANONICAL_LOCAL_FINANCIAL_PATH.exists()
    else LEGACY_LOCAL_FINANCIAL_PATH
)
GLOBAL_OPERATOR_PATH = ROOT / "agent_knowledge/global_top5_operators_2016_2025/annual_metrics.json"
GLOBAL_OPERATOR_SOURCES_PATH = ROOT / "agent_knowledge/global_top5_operators_2016_2025/sources.json"
LOCAL_OPERATING_PATH = ROOT / "agent_knowledge/local_hk_operator_operating_metrics_2016_2025/annual_metrics.json"
LOCAL_OPERATING_SOURCES_PATH = ROOT / "agent_knowledge/local_hk_operator_operating_metrics_2016_2025/sources.json"
CLOUD_PATH = ROOT / "agent_knowledge/cloud_vendor_metrics_2026-06-17/cloud_vendor_metrics_2023_2025.json"
MACRO_PATH = ROOT / "agent_knowledge/cmhk_macro_policy_2026-06-19/macro_policy_metrics.json"
AI_ANALYSIS_PATH = ROOT / "agent_knowledge/executive_intelligence_refresh/ai_analysis.json"
REFRESH_STATE_PATH = ROOT / "agent_knowledge/executive_intelligence_refresh/latest.json"
DISPLAY_REFERENCE_PATH = ROOT / "agent_knowledge/executive_intelligence_reference/display_reference_data.json"
ONLINE_GAP_AUDIT_PATH = ROOT / "agent_knowledge/executive_intelligence_reference/online_gap_audit_2026-08-25.json"
INSIGHT_FORMAT_VERSION = "strategic_operating_judgement_v9"

DOMAIN_PATHS = (LOCAL_PATH, LOCAL_FINANCIAL_PATH, INTERNATIONAL_PATH, GLOBAL_OPERATOR_PATH, GLOBAL_OPERATOR_SOURCES_PATH, LOCAL_OPERATING_PATH, LOCAL_OPERATING_SOURCES_PATH, CLOUD_PATH, MACRO_PATH, AI_ANALYSIS_PATH, REFRESH_STATE_PATH, DISPLAY_REFERENCE_PATH, ONLINE_GAP_AUDIT_PATH)
INTERNATIONAL_SUBJECTS = ("中国移动", "中国电信", "中国联通", "中国铁塔")
SAFE_VERIFICATION_STATUSES = {
    "official_match",
    "official_only",
    "official_single_source",
    "official_single_source_user_accepted_display",
    "official_two_distinct_sources_verified",
    "official_source_count_below_three_displayed",
    "official_derived_from_reported_quarters",
    "official_derived_from_verified_rows",
    "multi_source_or_multi_snapshot_verified",
    "official_three_distinct_sources_verified",
}
def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_json_optional(path: Path, default: Any) -> Any:
    try:
        return _read_json(path)
    except (OSError, json.JSONDecodeError):
        return default


def _display_reference_data() -> dict[str, Any]:
    payload = _read_json_optional(DISPLAY_REFERENCE_PATH, {})
    return payload if isinstance(payload, dict) else {}


def _fx_sources() -> list[tuple[str, str]]:
    return [
        (str(item.get("label") or ""), str(item.get("url") or ""))
        for item in (_display_reference_data().get("sources") or [])
        if isinstance(item, dict) and item.get("label") and item.get("url")
    ]


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


def _million_usd(value: float | None, currency: str, year: int = 2024) -> float | None:
    if value is None:
        return None
    code = str(currency or "").upper()
    if code == "USD":
        return value
    if code not in {"RMB", "CNY"}:
        return None
    rates = _display_reference_data().get("cny_per_usd_annual_average") or {}
    rate = _number(rates.get(str(int(year))))
    return value / rate if rate else None


def _verified_number(row: dict[str, Any] | None) -> float | None:
    """Return the official value when a published row contains one."""
    if not row:
        return None
    official = _number(row.get("official_value"))
    return official if official is not None else _number(row.get("value"))


def _period_rank(value: Any) -> tuple[int, int]:
    text = str(value or "")
    iso = re.search(r"(20\d{2})-(\d{2})(?:-\d{2})?", text)
    if iso:
        return int(iso.group(1)), int(iso.group(2))
    match = re.search(r"Q([1-4])\s+(20\d{2})", text, re.I)
    if match:
        return int(match.group(2)), int(match.group(1))
    half = re.search(r"H([12])\s+(20\d{2})", text, re.I)
    if half:
        return int(half.group(2)), 6 if half.group(1) == "1" else 12
    year = re.search(r"(20\d{2})", text)
    if year and re.search(r"(?:\bFY\s*|\bannual\b)", text, re.I):
        return int(year.group(1)), 12
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


def _financial_metric(report: dict[str, Any], metric_key: str) -> dict[str, Any] | None:
    return next(
        (
            metric for metric in report.get("metrics") or []
            if str(metric.get("metric_key") or "") == metric_key
        ),
        None,
    )


def _financial_metric_number(report: dict[str, Any], metric_key: str) -> float | None:
    metric = _financial_metric(report, metric_key)
    if not metric:
        return None
    match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", str(metric.get("value") or ""))
    return float(match.group().replace(",", "")) if match else None


def _local_financial_focus(reports: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not reports:
        return None
    periods: dict[str, list[dict[str, Any]]] = {}
    for report in reports:
        periods.setdefault(str(report.get("period") or "期间待核"), []).append(report)
    comparison_period, comparable = max(
        periods.items(),
        key=lambda entry: (len(entry[1]), _period_rank(entry[0])),
    )
    revenues = sorted(
        (
            (value, report) for report in comparable
            if (value := _financial_metric_number(report, "revenue")) is not None
        ),
        key=lambda entry: entry[0], reverse=True,
    )
    profits = sorted(
        (
            (value, report) for report in comparable
            if (value := _financial_metric_number(report, "net_profit")) is not None
        ),
        key=lambda entry: entry[0], reverse=True,
    )
    if len(revenues) >= 2 and len(profits) >= 2:
        revenue_high, revenue_low = revenues[0], revenues[-1]
        profit_high, profit_low = profits[0], profits[-1]
        insight = (
            f"同为{comparison_period}，{revenue_high[1].get('company')}收入{revenue_high[0]:,.0f}m、"
            f"{revenue_low[1].get('company')}为{revenue_low[0]:,.0f}m；净利润从"
            f"{profit_high[1].get('company')}的{profit_high[0]:,.0f}m到"
            f"{profit_low[1].get('company')}的{profit_low[0]:,.0f}m，表明规模差距伴随利润转化明显分层。"
        )
    else:
        insight = (
            f"已收录{len(reports)}家公司最新官方财报，但同期间收入与净利润可比样本不足，"
            "披露完整度差异仍是判断本地竞争结构的主要边界。"
        )
    return {
        "id": "financials",
        "label": "重要财务指标",
        "visual": "financial",
        "metric": {"value": len(reports), "unit": "家公司", "label": "已入库最新官方财报"},
        "context": (
            f"最新披露 {reports[0].get('publication_date') or '日期待核'}；"
            "每日 03:00（香港时间）自动检查"
        ),
        "headline": "本地业绩呈现规模与盈利分层",
        "insight": insight,
        "items": [
            {
                "name": report.get("company") or "未标明公司",
                "value": int(report.get("core_metric_count") or len(report.get("metrics") or [])),
                "unit": "项核心指标",
                "period": report.get("period") or "期间待核",
                "publication_date": report.get("publication_date") or "",
                "detail": (
                    f"{report.get('period') or '期间待核'} · "
                    f"{report.get('publication_date') or '披露日期待核'}"
                ),
                "analysis": (
                    f"{report.get('company') or '该公司'}最新官方财报披露"
                    f"{len(report.get('metrics') or [])}项核心指标；仅与同期间、同币种和同口径数据比较。"
                ),
                "components": [
                    {
                        "label": metric.get("metric") or metric.get("metric_key") or "指标",
                        "value": metric.get("value") or "—",
                        "detail": report.get("period") or "",
                        "metric_key": metric.get("metric_key") or "",
                    }
                    for metric in report.get("metrics") or []
                ],
                "component_count": len(report.get("metrics") or []),
                "source_url": report.get("source_url") or "",
            }
            for report in reports
        ],
    }


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

    def norm(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip()).casefold()

    def plan_key(row: dict[str, Any]) -> tuple[Any, ...]:
        return (
            norm(row.get("product_category")),
            norm(row.get("plan_name") or row.get("plan_family")),
            _number(row.get("monthly_fee_hkd")),
            _number(row.get("local_data_gb")),
            _number(row.get("broadband_speed_mbps")),
            _number(row.get("contract_months")),
        )

    def short_product_label(row: dict[str, Any]) -> str:
        category = category_labels.get(
            str(row.get("product_category") or ""),
            str(row.get("product_category") or "产品").replace("_", " "),
        )
        details = [category]
        if _number(row.get("local_data_gb")) is not None:
            details.append(f"{_format_price(row.get('local_data_gb'))}GB")
        if _number(row.get("broadband_speed_mbps")) is not None:
            details.append(f"{_format_price(row.get('broadband_speed_mbps'))}Mbps")
        if _number(row.get("contract_months")) is not None:
            details.append(f"{_format_price(row.get('contract_months'))}个月")
        return "｜".join(details)

    brand_profiles: dict[str, dict[str, Any]] = {}
    for brand, brand_rows in by_brand.items():
        unique: dict[tuple[Any, ...], dict[str, Any]] = {}
        for row in brand_rows:
            unique.setdefault(plan_key(row), row)
        unique_rows = list(unique.values())
        source_url = next((str(row.get("source_url") or "") for row in brand_rows if row.get("source_url")), "")
        brand_profiles[brand] = {"rows": brand_rows, "unique_rows": unique_rows, "source_url": source_url}

    overlaps: list[dict[str, Any]] = []
    brands = sorted(brand_profiles)
    for index, first in enumerate(brands):
        for second in brands[index + 1 :]:
            first_by_category: dict[str, list[float]] = {}
            second_by_category: dict[str, list[float]] = {}
            for profile, bucket in ((brand_profiles[first], first_by_category), (brand_profiles[second], second_by_category)):
                for row in profile["unique_rows"]:
                    category = str(row.get("product_category") or "")
                    fee = _number(row.get("monthly_fee_hkd"))
                    tariff_type = str(row.get("tariff_type") or "")
                    if category and fee is not None and fee > 0 and tariff_type != "monthly_add_on_fee":
                        bucket.setdefault(category, []).append(fee)
            category_overlaps = []
            for category in sorted(set(first_by_category) & set(second_by_category)):
                low = max(min(first_by_category[category]), min(second_by_category[category]))
                high = min(max(first_by_category[category]), max(second_by_category[category]))
                if low <= high:
                    category_overlaps.append({"category": category, "low": low, "high": high})
            if category_overlaps:
                overlaps.append({"pair": f"{first} 与 {second}", "categories": category_overlaps})
    overlaps.sort(key=lambda item: len(item["categories"]), reverse=True)
    overlaps_by_brand: dict[str, list[dict[str, Any]]] = {brand: [] for brand in brands}
    for overlap in overlaps:
        first, second = overlap["pair"].split(" 与 ", 1)
        overlaps_by_brand[first].append({**overlap, "peer": second})
        overlaps_by_brand[second].append({**overlap, "peer": first})

    scale_items: list[dict[str, Any]] = []
    mobile_items: list[dict[str, Any]] = []
    fibre_items: list[dict[str, Any]] = []
    overlap_items: list[dict[str, Any]] = []
    for brand, profile in brand_profiles.items():
        unique_rows = profile["unique_rows"]
        categories = sorted({str(row.get("product_category") or "") for row in unique_rows if row.get("product_category")})
        labels = [category_labels.get(category, category.replace("_", " ")) for category in categories]
        brand_overlaps = sorted(overlaps_by_brand.get(brand, []), key=lambda item: len(item["categories"]), reverse=True)
        shared_categories = {item["category"] for overlap in brand_overlaps for item in overlap["categories"]}
        plan_components = [
            _component(
                short_product_label(row),
                _number(row.get("monthly_fee_hkd")),
                "港元/月",
            )
            for row in unique_rows
        ]
        duplicate_records = max(0, len(profile["rows"]) - len(plan_components))
        scale_items.append({
            "name": brand,
            "value": len(plan_components),
            "unit": "个产品",
            "detail": f"{data_time_note} · {len(profile['rows'])} 条数据库记录",
            "analysis": (
                f"数据库有 {len(profile['rows'])} 条记录，按产品类型、名称、月费、数据量、宽带速度及合约期去重后为 {len(plan_components)} 个在售产品；"
                f"记录含重复，不能当作 {len(profile['rows'])} 种产品。"
            ),
            "components": plan_components,
            "component_count": len(plan_components),
            "record_count": len(profile["rows"]),
            "source_url": profile["source_url"],
        })
        mobile_rows = [row for row in unique_rows if row.get("product_category") == "mobile_consumer_5g" and row.get("tariff_type") == "monthly_plan_fee" and (_number(row.get("monthly_fee_hkd")) or 0) > 0]
        mobile_fees = [_number(row.get("monthly_fee_hkd")) for row in mobile_rows]
        mobile_fees = [fee for fee in mobile_fees if fee is not None]
        mobile_median = _median(mobile_fees)
        mobile_items.append({
            "name": brand, "value": round(mobile_median, 1) if mobile_median is not None else None,
            "unit": "港元/月",
            "low": round(min(mobile_fees), 1) if mobile_fees else None,
            "high": round(max(mobile_fees), 1) if mobile_fees else None,
            "detail": f"{data_time_note} · 个人5G月费 HK${min(mobile_fees):.0f}–{max(mobile_fees):.0f}" if mobile_fees else f"{data_time_note} · 未披露个人5G月费",
            "analysis": (
                f"个人5G月费中位数为 HK${mobile_median:.0f}，范围为 HK${min(mobile_fees):.0f}–{max(mobile_fees):.0f}。"
                if mobile_median is not None else "数据库没有可计算的个人5G月费，不作估算。"
            ),
            "components": [_component(short_product_label(row), _number(row.get("monthly_fee_hkd")), "港元/月") for row in mobile_rows] or [_component("个人5G月费", detail="未披露")],
            "component_count": len(mobile_rows), "source_url": profile["source_url"],
        })
        fibre_rows = [row for row in unique_rows if row.get("product_category") == "home_fibre_broadband" and (_number(row.get("monthly_fee_hkd")) or 0) > 0 and (_number(row.get("broadband_speed_mbps")) or 0) > 0]
        fibre_values = [float(_number(row.get("monthly_fee_hkd"))) / float(_number(row.get("broadband_speed_mbps"))) * 1000 for row in fibre_rows]
        fibre_median = _median(fibre_values)
        fibre_items.append({
            "name": brand, "value": round(fibre_median, 1) if fibre_median is not None else None, "unit": "港元/千兆/月",
            "detail": f"{data_time_note} · 按每1000Mbps折算" if fibre_values else f"{data_time_note} · 未披露可计算的家宽速度与月费",
            "analysis": (f"按每1000Mbps折算，月费中位数为 {fibre_median:.1f} 港元；安装费、优惠和覆盖地区未计入。" if fibre_median is not None else "数据库缺少同一产品的速度与月费，不作估算。"),
            "components": [
                _component(
                    short_product_label(row),
                    round(value, 1),
                    "港元/千兆/月",
                    " · ".join(filter(None, [
                        f"原月费 HK${_format_price(row.get('monthly_fee_hkd'))}",
                        f"速度 {_format_price(row.get('broadband_speed_mbps'))}Mbps",
                        f"合约期 {_format_price(row.get('contract_months'))}个月" if _number(row.get("contract_months")) is not None else "合约期未披露",
                    ])),
                )
                for row, value in zip(fibre_rows, fibre_values)
            ] or [_component("家宽每1000Mbps价格", detail="未披露")],
            "component_count": len(fibre_rows), "source_url": profile["source_url"],
        })
        overlap_items.append({
            "name": brand,
            "value": len(shared_categories),
            "unit": "类产品价格区间重合",
            "peers": len(brand_overlaps),
            "detail": f"与 {len(brand_overlaps)} 家运营商的同类产品月费区间重合",
            "analysis": (
                "；".join(
                    f"与{item['peer']}的"
                    + "、".join(
                        f"{category_labels.get(entry['category'], entry['category'])}月费区间在 HK${entry['low']:.0f}–{entry['high']:.0f} 重合"
                        for entry in item["categories"]
                    )
                    for item in brand_overlaps
                ) + "。"
                if brand_overlaps else "数据库当前未发现同类产品月费区间重合。"
            ),
            "components": [
                _component(
                    item["peer"],
                    len(item["categories"]), "类产品",
                    "、".join(f"{category_labels.get(entry['category'], entry['category'])}月费区间 HK${entry['low']:.0f}–{entry['high']:.0f} 重合" for entry in item["categories"]),
                )
                for item in brand_overlaps
            ] or [_component("同类套餐价格重合", detail="未发现")],
            "component_count": len(brand_overlaps),
            "source_url": profile["source_url"],
        })

    scale_items.sort(key=lambda item: item["value"], reverse=True)
    mobile_items.sort(key=lambda item: (_number(item.get("value")) is not None, -(_number(item.get("value")) or 0)), reverse=True)
    fibre_items.sort(key=lambda item: (_number(item.get("value")) is not None, -(_number(item.get("value")) or 0)), reverse=True)
    overlap_items.sort(key=lambda item: (item["value"], item["peers"]), reverse=True)
    comparable_mobile = [item for item in mobile_items if _number(item.get("value")) is not None]
    if len(comparable_mobile) >= 2:
        mobile_low, mobile_high = comparable_mobile[0], comparable_mobile[-1]
        overlap_low = max(float(mobile_low.get("low") or 0), float(mobile_high.get("low") or 0))
        overlap_high = min(float(mobile_low.get("high") or 0), float(mobile_high.get("high") or 0))
        overlap_note = f"双方月费区间在{overlap_low:.0f}至{overlap_high:.0f}港元重合" if overlap_low <= overlap_high else "双方月费区间没有重合"
        mobile_insight = (
            f"仅{mobile_low['name']}和{mobile_high['name']}有可比月费：中位数分别为{float(mobile_low['value']):.0f}和{float(mobile_high['value']):.0f}港元，相差{float(mobile_high['value']) - float(mobile_low['value']):.0f}港元；{overlap_note}，这说明仅靠低价难以拉开差距。"
        )
    else:
        mobile_insight = "个人5G可比月费不足，不判断价格区隔。"
    comparable_fibre = [item for item in fibre_items if _number(item.get("value")) is not None]
    fibre_insight = (
        f"按每1000Mbps折算，{comparable_fibre[0]['name']}月费中位数为{comparable_fibre[0]['value']:.1f}港元，"
        f"{comparable_fibre[-1]['name']}为{comparable_fibre[-1]['value']:.1f}港元，约为前者的{float(comparable_fibre[-1]['value']) / float(comparable_fibre[0]['value']):.1f}倍。"
        "安装费、合约优惠和覆盖地区未纳入，不能直接视为客户最终总成本。"
        if len(comparable_fibre) >= 2 else "家宽速度与月费的可比方案不足，不判断价格优势。"
    )
    lead = overlaps[0] if overlaps else None
    if lead:
        entry = lead["categories"][0]
        insight = f"{lead['pair']}的{category_labels.get(entry['category'], entry['category'])}月费区间在 HK${entry['low']:.0f}–{entry['high']:.0f} 重合；这说明同类价格区隔有限。"
    else:
        insight = "数据库已按运营商、套餐类型和月费范围整理本地在售套餐。"

    unique_plan_count = sum(int(item["component_count"]) for item in scale_items)
    top_three = scale_items[:3]
    scale_insight = (
        f"{top_three[0]['name']}、{top_three[1]['name']}、{top_three[2]['name']}去重后分别有"
        f"{top_three[0]['value']}、{top_three[1]['value']}、{top_three[2]['value']}个在售产品，"
        f"而{scale_items[-2]['name']}和{scale_items[-1]['name']}为{scale_items[-2]['value']}、{scale_items[-1]['value']}个，数量形成两层；"
        f"头部三家最多只差{top_three[0]['value'] - top_three[-1]['value']}个，这说明产品数量差距难以成为头部之间的主要区隔。"
        if unique_plan_count and len(scale_items) >= 5 else "数据库暂无足够运营商形成产品数量关系判断。"
    )
    focuses = [
        {
            "id": "scale", "label": "在售产品组合", "visual": "columns",
            "metric": {"value": unique_plan_count, "unit": "个产品", "label": "去重后在售产品"},
            "context": f"比较 {len(by_brand)} 家本地运营商；{data_time_note}",
            "insight": scale_insight,
            "items": scale_items,
        },
        {
            "id": "mobile_price", "label": "个人5G月费", "visual": "ranges",
            "metric": {**_focus_metric(mobile_items, "个人5G月费中位数", "港元/月", mode="min"), "label": "可比品牌中较低的月费中位数"},
            "context": data_time_note, "insight": mobile_insight, "items": mobile_items,
        },
        {
            "id": "fibre_value", "label": "家宽每千兆价格", "visual": "rows",
            "metric": {**_focus_metric(fibre_items, "每1000Mbps月费中位数", "港元/千兆/月", mode="min"), "label": "较低的每1000Mbps月费中位数"},
            "context": data_time_note, "insight": fibre_insight, "items": fibre_items,
        },
        {
            "id": "overlap", "label": "同类价格重合", "visual": "network",
            "metric": {
                **_focus_metric(overlap_items, "价格区间重合的产品类型", "类"), "label": "与其他运营商价格区间重合的产品类型",
            },
            "context": f"比较 {len(overlaps)} 组运营商的产品类型与月费范围；{data_time_note}",
            "insight": insight,
            "items": overlap_items,
        },
    ]
    for focus in focuses:
        focus["headline"] = {
            "scale": "在售产品集中于三家", "mobile_price": "个人月费区隔有限",
            "fibre_value": "家宽折算价格相差近四倍", "overlap": "同类产品月费区间重合",
        }[focus["id"]]
    entities = scale_items
    financial_payload = _read_json_optional(LOCAL_FINANCIAL_PATH, {})
    financial_reports = [
        report for report in financial_payload.get("reports", [])
        if report.get("verification_status") == "official_document_extracted"
    ]
    financial_reports.sort(
        key=lambda report: (str(report.get("publication_date") or ""), _period_rank(report.get("period"))),
        reverse=True,
    )
    financial_focus = _local_financial_focus(financial_reports)
    if financial_focus:
        focuses.insert(0, financial_focus)
    newest_financial = financial_reports[0] if financial_reports else None
    if newest_financial:
        financial_note = (
            f"最新官方财报为{newest_financial['company']} {newest_financial['period']}，"
            f"披露于{newest_financial.get('publication_date') or '日期待核'}；核心指标已结构化入库。"
        )
    else:
        financial_note = "本地官方财报尚无通过结构化门禁的新记录。"
    financial_relations = []
    for report in financial_reports[:4]:
        metric_text = "、".join(
            f"{item.get('metric')} {item.get('value')}"
            for item in (report.get("metrics") or [])[:3]
        )
        financial_relations.append(
            {
                "title": f"{report.get('company')} {report.get('period')}",
                "detail": metric_text or "官方财报已入库",
                "kind": "最新财报",
            }
        )
    sources = _dedupe_sources(
        [_source(item["name"], item["source_url"]) for item in scale_items]
        + [_source(f"{report.get('company')} {report.get('period')} 官方财报", report.get("source_url")) for report in financial_reports]
    )
    return {
        "id": "local",
        "index": "01",
        "title": "本地运营商",
        "kicker": "产品组合与价格区隔",
        "metric": {"value": unique_plan_count, "unit": "个产品", "label": "去重后在售产品"},
        "context": f"{data_time_note}；{financial_note}",
        "data_time": data_time_note,
        "latest_financial_results": financial_reports,
        "insight": insight,
        "entities": entities,
        "focuses": focuses,
        "relations": financial_relations + [
            {
                "title": item["pair"],
                "detail": f"{len(item['categories'])} 类同类套餐月费区间重合",
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


def _metric_for_fiscal_year(
    rows: list[dict[str, Any]], subject_key: str, subject: str, metric: str, fiscal_year: str
) -> dict[str, Any] | None:
    return next(
        (
            row for row in rows
            if row.get(subject_key) == subject
            and row.get("metric_key") == metric
            and str(row.get("fiscal_year") or "") == fiscal_year
            and _verified_number(row) is not None
            and str(row.get("verification_status") or "") in SAFE_VERIFICATION_STATUSES
        ),
        None,
    )


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


def _row_source_urls(row: dict[str, Any] | None, source_registry: dict[str, str] | None = None) -> list[str]:
    if not row:
        return []
    raw = row.get("verification_sources") or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = []
    urls: list[str] = []
    for source in raw if isinstance(raw, list) else []:
        if isinstance(source, dict):
            url = str(source.get("url") or "")
        else:
            url = str((source_registry or {}).get(str(source), ""))
        if url.startswith(("https://", "http://")):
            urls.append(url)
    primary = str(row.get("primary_source_url") or row.get("official_source_url") or "")
    if primary.startswith(("https://", "http://")):
        urls.append(primary)
    return list(dict.fromkeys(urls))


def _row_provenance_urls(
    row: dict[str, Any] | None, source_registry: dict[str, str] | None = None
) -> list[str]:
    """Return verified URLs plus labelled candidate documents for traceability."""

    urls = _row_source_urls(row, source_registry)
    if not row:
        return urls
    raw = row.get("candidate_sources") or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = []
    for source_id in raw if isinstance(raw, list) else []:
        url = str((source_registry or {}).get(str(source_id), ""))
        if url.startswith(("https://", "http://")):
            urls.append(url)
    return list(dict.fromkeys(urls))


def _annual_financial_value(
    rows: list[dict[str, Any]], subject: str, metric: str, year: int
) -> dict[str, Any] | None:
    subject_rows = [
        row for row in rows
        if row.get("subject") == subject
        and row.get("metric_key") == metric
        and str(row.get("verification_status") or "") in SAFE_VERIFICATION_STATUSES
        and _verified_number(row) is not None
    ]
    period_sets = ([f"H1 {year}", f"H2 {year}"], [f"Q{i} {year}" for i in range(1, 5)])
    selected: list[dict[str, Any]] = []
    for periods in period_sets:
        candidate = [next((row for row in subject_rows if row.get("period") == period), None) for period in periods]
        if all(candidate):
            selected = [row for row in candidate if row]
            break
    if not selected:
        return None
    urls = list(dict.fromkeys(url for row in selected for url in _row_source_urls(row)))
    if subject == "HKT / csl / 1O1O" and year == 2025:
        urls = list(dict.fromkeys(urls + [
            "https://www.hkt.com/api-service/assets/e-2025_Annual_Report.pdf",
            "https://www.hkt.com/api-service/assets/c01-2025_Annual_Results.pdf",
            "https://www.hkt.com/api-service/assets/e-2026.02.09_(2025_Annual_Results_Announcement).pdf",
        ]))
    value = sum(float(_verified_number(row) or 0) for row in selected)
    return {
        "value": value,
        "unit": str(selected[0].get("official_unit") or selected[0].get("unit") or ""),
        "period": f"FY{year}",
        "source_urls": urls,
        "source_url": urls[0] if urls else "",
        "verification_count": len(urls),
        "verification_status": (
            "official_three_distinct_sources_verified"
            if len(urls) >= 3
            else "official_source_count_below_three_displayed"
            if urls
            else "official_value_without_source_url_displayed"
        ),
    }


def _financial_report_year(report: dict[str, Any]) -> int | None:
    match = re.fullmatch(r"FY\s*(20\d{2})", str(report.get("period") or "").strip(), re.I)
    return int(match.group(1)) if match else None


def _financial_report_metric_value(report: dict[str, Any], metric: str) -> float | None:
    report_key = {"net_income": "net_profit"}.get(metric, metric)
    item = next(
        (entry for entry in (report.get("metrics") or []) if entry.get("metric_key") == report_key),
        None,
    )
    if not item:
        return None
    raw = str(item.get("value") or "").strip()
    match = re.search(r"-?\s*(?:HK\$)?\s*([\d,]+(?:\.\d+)?)", raw, re.I)
    if not match:
        return None
    value = float(match.group(1).replace(",", ""))
    if raw.startswith("-") or (raw.startswith("(") and raw.endswith(")")):
        value *= -1
    lowered = raw.lower()
    if "billion" in lowered:
        value *= 1000
    elif "thousand" in lowered:
        value /= 1000
    return value


def _official_local_financial_reports(payload: dict[str, Any]) -> list[dict[str, Any]]:
    reports = [
        report for report in (payload.get("reports") or [])
        if report.get("verification_status") == "official_document_extracted"
    ]
    reports.sort(
        key=lambda report: (str(report.get("publication_date") or ""), _period_rank(report.get("period"))),
        reverse=True,
    )
    return reports


def _direct_annual_financial_value(
    reports: list[dict[str, Any]], company: str, metric: str, year: int
) -> dict[str, Any] | None:
    aliases = {
        "HKT": {"HKT"},
        "SmarTone": {"SmarTone"},
        "3HK": {"3HK", "3HK / Hutchison", "Hutchison"},
    }
    report = next((
        item for item in reports
        if str(item.get("company") or "") in aliases.get(company, {company})
        and _financial_report_year(item) == year
    ), None)
    value = _financial_report_metric_value(report or {}, metric)
    if report is None or value is None:
        return None
    source_url = str(report.get("source_url") or "")
    return {
        "value": value,
        "unit": "millions HKD",
        "period": f"FY{year}",
        "source_urls": [source_url] if source_url else [],
        "source_url": source_url,
        "verification_count": 1 if source_url else 0,
        "verification_status": "official_document_extracted",
    }


def _audited_historical_financial_value(
    company: str, metric: str, year: int
) -> dict[str, Any] | None:
    """Return a source-backed annual value retained for display despite a short source list."""
    audit = _read_json_optional(ONLINE_GAP_AUDIT_PATH, {})
    fact = next((
        item for item in (audit.get("historical_public_facts") or [])
        if isinstance(item, dict)
        and str(item.get("entity") or "") == company
        and str(item.get("metric") or "") == metric
        and str(item.get("period") or "") == f"FY{year}"
        and _number(item.get("value")) is not None
    ), None)
    if not fact:
        return None
    source_urls = [
        str(url) for url in (fact.get("source_urls") or [])
        if str(url).startswith(("https://", "http://"))
    ]
    return {
        "value": float(_number(fact.get("value")) or 0),
        "unit": str(fact.get("unit") or "millions HKD"),
        "period": f"FY{year}",
        "source_urls": source_urls,
        "source_url": source_urls[0] if source_urls else "",
        "verification_count": len(source_urls),
        "verification_status": str(
            fact.get("verification_status")
            or "official_source_count_below_three_displayed"
        ),
    }


def _annual_financial_trend(
    rows: list[dict[str, Any]], subject: str, metric: str, *, divisor: float = 1.0, unit: str,
    start_year: int = 2016, end_year: int = 2025,
    direct_reports: list[dict[str, Any]] | None = None, company: str = "",
) -> list[dict[str, Any]]:
    trend: list[dict[str, Any]] = []
    for year in range(start_year, end_year + 1):
        annual = (
            _direct_annual_financial_value(direct_reports or [], company, metric, year)
            or _annual_financial_value(rows, subject, metric, year)
            or _audited_historical_financial_value(company, metric, year)
        )
        trend.append({
            "label": f"FY{year}",
            "value": round(float(annual["value"]) / divisor, 3) if annual else None,
            "unit": unit if annual else "",
            "verification_count": int((annual or {}).get("verification_count") or 0),
            "verification_status": str((annual or {}).get("verification_status") or ""),
            "source_urls": list((annual or {}).get("source_urls") or []),
        })
    return trend


def _strict_annual_row(
    rows: list[dict[str, Any]], operator: str, metric: str, year: int
) -> dict[str, Any] | None:
    return next((
        row for row in rows
        if row.get("operator") == operator
        and row.get("metric_key") == metric
        and int(row.get("year") or 0) == year
        and row.get("verification_status") == "official_three_distinct_sources_verified"
        and int(row.get("distinct_source_document_count") or row.get("verification_count") or 0) >= 3
        and _verified_number(row) is not None
    ), None)


def _published_annual_row(
    rows: list[dict[str, Any]], operator: str, metric: str, year: int
) -> dict[str, Any] | None:
    """Return an official direct or explicitly official-derived annual row."""
    return next((
        row for row in rows
        if row.get("operator") == operator
        and row.get("metric_key") == metric
        and int(row.get("year") or 0) == year
        and row.get("verification_status") in SAFE_VERIFICATION_STATUSES
        and _verified_number(row) is not None
    ), None)


def _international_domain(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("rows") or []
    growth_items: list[dict[str, Any]] = []
    momentum_items: list[dict[str, Any]] = []
    investment_items: list[dict[str, Any]] = []
    margin_items: list[dict[str, Any]] = []
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
            "analysis": f"{row.get('period') or '最新期'}营收同比 {value:+.2f}%。",
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
                f"{capex_period}资本开支为人民币{abs(capex_value) / 100:.1f}亿元，占同期营收{intensity:.2f}%。"
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
        margin_row = _latest_metric(rows, "subject", subject, "operating_margin")
        margin_value = _verified_number(margin_row)
        margin_period = str((margin_row or {}).get("period") or "")
        margin_items.append({
            "name": subject, "value": round(margin_value, 2) if margin_value is not None else None,
            "unit": "%" if margin_value is not None else "", "period": margin_period,
            "detail": f"{margin_period}经营利润率" if margin_value is not None else "数据库未披露经营利润率",
            "analysis": (f"{margin_period}经营利润率为 {margin_value:.2f}%。" if margin_value is not None else "未披露经营利润率。"),
            "components": [_component("经营利润率", round(margin_value, 2), "%", margin_period)] if margin_value is not None else [_component("经营利润率", detail="未披露")],
            "component_count": 1,
            "source_url": str((margin_row or row).get("official_source_url") or ""),
        })
    growth_items.sort(key=lambda item: item["value"], reverse=True)
    momentum_items.sort(key=lambda item: (_number(item.get("value")) is not None, _number(item.get("value")) or 0), reverse=True)
    investment_items.sort(key=lambda item: (_number(item.get("value")) is not None, _number(item.get("value")) or 0), reverse=True)
    margin_items.sort(key=lambda item: (_number(item.get("value")) is not None, _number(item.get("value")) or 0), reverse=True)
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
            f"三家公司最高与最低相差{investment_gap:.2f}个百分点；当前数据只说明投入比例不同，不代表投资回报。"
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
            momentum_insight = f"{len(slowing)} 家公司的营收同比增速均较上一可比期放缓，说明收入扩张压力同步上升。"
        else:
            momentum_insight = f"{len(improving)} 家加快、{len(slowing)} 家放缓；各公司均与自己的上一可比期相比。"
    else:
        momentum_insight = "当前缺少两个可比期间的营收增速，不作增长节奏判断。"
    margin_comparable = [item for item in margin_items if _number(item.get("value")) is not None]
    margin_insight = (
        f"只有{len(margin_comparable)}家公司披露可比经营利润率；{margin_comparable[0]['name']}为{margin_comparable[0]['value']:.2f}%，"
        f"{margin_comparable[-1]['name']}为{margin_comparable[-1]['value']:.2f}%，相差{float(margin_comparable[0]['value']) - float(margin_comparable[-1]['value']):.2f}个百分点，这说明盈利缓冲明显不同。"
        if len(margin_comparable) >= 2 else "经营利润率披露不足，不跨口径替代。"
    )
    growth_facts = "、".join(f"{item['name']}{float(item['value']):+.2f}%" for item in growth_items)
    insight = f"Q1 2026，{growth_facts}；两家公司已同比下降，另外两家增幅也低于2%，这说明行业收入扩张承压。"
    largest_slowing = sorted(
        [item for item in momentum_comparable if float(item["value"]) < 0],
        key=lambda item: float(item["value"]),
    )[:2]
    if largest_slowing and len(largest_slowing) >= 2:
        momentum_insight = (
            "四家公司增速均较Q4 2025下降；"
            + "、".join(f"{item['name']}回落{abs(float(item['value'])):.2f}个百分点" for item in largest_slowing)
            + "，这说明放缓已扩散至全部公司，行业收入增长同步承压。"
        )
    focuses = [
        {
            "id": "growth", "label": "营收增长", "visual": "diverging",
            "metric": {"value": f"{leader['value']:.2f}", "unit": "%", "label": f"{leader['name']} {leader.get('period') or '最近披露期'}营收同比增长"},
            "context": f"比较 {len(growth_items)} 家公司最近披露的营收同比数据", "insight": insight, "items": growth_items,
        },
        {
            "id": "momentum", "label": "增长变化", "visual": "trends",
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
            "id": "investment", "label": "资本投入占比", "visual": "rows",
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
            "id": "margin", "label": "经营利润率", "visual": "diverging",
            "metric": {"value": margin_comparable[0]["value"] if margin_comparable else "-", "unit": "%", "label": f"{margin_comparable[0]['name']}经营利润率" if margin_comparable else "经营利润率"},
            "context": "各公司最近可核验披露期", "insight": margin_insight, "items": margin_items,
        },
    ]
    for focus in focuses:
        focus["headline"] = {
            "growth": "两家已负增长，行业扩张转弱", "momentum": "放缓已扩散至全部公司",
            "investment": "资本投入占比相近", "margin": "利润缓冲差距超过一倍",
        }[focus["id"]]
    return {
        "id": "international",
        "index": "02",
        "title": "内地电讯企业",
        "kicker": "增长、利润与资本投入",
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


def _requested_hong_kong_domain(
    financial_payload: dict[str, Any], operating_payload: dict[str, Any], operating_sources: dict[str, Any],
    local_financial_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    financial_rows = financial_payload.get("rows") or []
    operating_rows = operating_payload.get("rows") or []
    financial_reports = _official_local_financial_reports(local_financial_payload or {})
    source_registry = {
        str(source.get("source_id") or ""): str(source.get("url") or "")
        for source in (operating_sources.get("sources") or [])
    }
    entities = (
        ("CMHK", "CMHK", "CMHK"),
        ("HKT", "HKT / csl / 1O1O", "HKT"),
        ("SmarTone", "SmarTone", "SmarTone"),
        ("3HK", "3HK / Hutchison", "3HK"),
    )
    cmhk_reference_ppt = {
        "period": "2026首7月",
        "revenue_m_hkd": 4544.6,
        "contribution_margin_m_hkd": 3410.0,
        "net_profit_m_hkd": 583.2,
        "five_g_penetration_pct": 62.6,
        "capability_export_projects": 12,
        "annualized_roa_pct": 5.65,
        "annualized_receivables_to_revenue_pct": 4.10,
    }
    overview_report_companies = {"HKT", "SmarTone", "3HK", "3HK / Hutchison", "Hutchison"}
    latest_annual_year = max(
        [2025] + [
            year for report in financial_reports
            if str(report.get("company") or "") in overview_report_companies
            and (year := _financial_report_year(report)) is not None
        ]
    )
    annual_start_year = latest_annual_year - 9
    baseline_annual_window = latest_annual_year == 2025

    def cmhk_reference_components() -> list[dict[str, Any]]:
        period = cmhk_reference_ppt["period"]
        return [
            _component("主营业务收入", cmhk_reference_ppt["revenue_m_hkd"], "百万港元", f"累计｜{period}"),
            _component("收入贡献毛益", cmhk_reference_ppt["contribution_margin_m_hkd"], "百万港元", f"累计｜{period}"),
            _component("净利润", cmhk_reference_ppt["net_profit_m_hkd"], "百万港元", f"累计｜{period}"),
            _component("5G客户渗透率", cmhk_reference_ppt["five_g_penetration_pct"], "%", f"期末值｜{period}"),
            _component("能力出海项目", cmhk_reference_ppt["capability_export_projects"], "个", f"累计完成｜{period}"),
            _component("总资产收益率", cmhk_reference_ppt["annualized_roa_pct"], "%", f"年化｜{period}"),
            _component("应收账款占收比", cmhk_reference_ppt["annualized_receivables_to_revenue_pct"], "%", f"年化｜{period}"),
        ]

    def operating_row(operator: str, metric: str, year: int = 2025) -> dict[str, Any] | None:
        return next((
            row for row in operating_rows
            if row.get("operator") == operator
            and row.get("metric_key") == metric
            and int(row.get("year") or 0) == year
            and row.get("verification_status") == "official_three_distinct_sources_verified"
            and len(_row_source_urls(row, source_registry)) >= 3
            and _verified_number(row) is not None
        ), None)

    revenue_items: list[dict[str, Any]] = []
    ebitda_items: list[dict[str, Any]] = []
    profit_items: list[dict[str, Any]] = []
    postpaid_items: list[dict[str, Any]] = []
    for name, subject, operator in entities:
        available_years = [
            year for year in range(latest_annual_year, annual_start_year - 1, -1)
            if (
                _direct_annual_financial_value(financial_reports, operator, "revenue", year)
                or _annual_financial_value(financial_rows, subject, "revenue", year)
            )
        ]
        operator_year = available_years[0] if available_years else latest_annual_year
        revenue = (
            _direct_annual_financial_value(financial_reports, operator, "revenue", operator_year)
            or _annual_financial_value(financial_rows, subject, "revenue", operator_year)
        )
        ebitda = (
            _direct_annual_financial_value(financial_reports, operator, "ebitda", operator_year)
            or _annual_financial_value(financial_rows, subject, "ebitda", operator_year)
        )
        profit = (
            _direct_annual_financial_value(financial_reports, operator, "net_income", operator_year)
            or _annual_financial_value(financial_rows, subject, "net_income", operator_year)
        )
        annual_period = f"FY{operator_year}"
        missing_note = "CMHK未公开独立公司口径，保留缺口" if name == "CMHK" else "官方公开数据待补"
        if name == "CMHK":
            revenue = {
                "value": cmhk_reference_ppt["revenue_m_hkd"],
                "source_url": "",
                "verification_count": 1,
            }
            profit = {
                "value": cmhk_reference_ppt["net_profit_m_hkd"],
                "source_url": "",
                "verification_count": 1,
            }
        revenue_items.append({
            "name": name, "value": round(float(revenue["value"]), 1) if revenue else None,
            "unit": "百万港元" if revenue else "", "period": cmhk_reference_ppt["period"] if name == "CMHK" else annual_period,
            "detail": (f"{cmhk_reference_ppt['period']}累计 · 用户提供参考PPT" if name == "CMHK" else ("FY2025营收 · 三份不同官方文件核验" if baseline_annual_window else f"{annual_period}营收 · 官方全年财报")) if revenue else missing_note,
            "analysis": (f"{cmhk_reference_ppt['period']}主营业务收入为{cmhk_reference_ppt['revenue_m_hkd']:,.1f}百万港元；该值为首7月累计，不与FY2025全年值直接排名。" if name == "CMHK" and baseline_annual_window else f"{cmhk_reference_ppt['period']}主营业务收入为{cmhk_reference_ppt['revenue_m_hkd']:,.1f}百万港元；该值为首7月累计，不与全年值直接排名。" if name == "CMHK" else f"FY2025营收为{float(revenue['value']):,.1f}百万港元；沿用公司原披露财年。" if baseline_annual_window else f"{annual_period}营收为{float(revenue['value']):,.1f}百万港元；沿用公司最新正式全年披露。") if revenue else f"{missing_note}，不以母集团或其他运营商数据替代。",
            "components": cmhk_reference_components() if name == "CMHK" else ([_component("营收", round(float(revenue["value"]), 1), "百万港元", annual_period)] if revenue else [_component("营收", detail=missing_note)]),
            "component_count": len(cmhk_reference_components()) if name == "CMHK" else 1, "source_url": str((revenue or {}).get("source_url") or ""),
            "verification_count": int((revenue or {}).get("verification_count") or 0),
            "trend": _annual_financial_trend(financial_rows, subject, "revenue", unit="百万港元", start_year=annual_start_year, end_year=latest_annual_year, direct_reports=financial_reports, company=operator),
        })
        ebitda_items.append({
            "name": name, "value": round(float(ebitda["value"]), 1) if ebitda else None,
            "unit": "百万港元" if ebitda else "", "period": annual_period,
            "detail": ("FY2025 EBITDA金额" if baseline_annual_window else f"{annual_period} EBITDA金额") if ebitda else missing_note,
            "analysis": f"{'FY2025' if baseline_annual_window else annual_period} EBITDA为{float(ebitda['value']):,.1f}百万港元；只展示金额，不混入利润率。" if ebitda else f"{missing_note}，不估算EBITDA。",
            "components": [_component("EBITDA", round(float(ebitda["value"]), 1), "百万港元", annual_period)] if ebitda else [_component("EBITDA", detail=missing_note)],
            "component_count": 1, "source_url": str((ebitda or {}).get("source_url") or ""),
            "verification_count": int((ebitda or {}).get("verification_count") or 0),
            "trend": _annual_financial_trend(financial_rows, subject, "ebitda", unit="百万港元", start_year=annual_start_year, end_year=latest_annual_year, direct_reports=financial_reports, company=operator),
        })
        profit_items.append({
            "name": name, "value": round(float(profit["value"]), 1) if profit else None,
            "unit": "百万港元" if profit else "", "period": cmhk_reference_ppt["period"] if name == "CMHK" else annual_period,
            "detail": f"{cmhk_reference_ppt['period']}累计 · 用户提供参考PPT" if name == "CMHK" else (("FY2025净利润金额" if baseline_annual_window else f"{annual_period}净利润金额") if profit else missing_note),
            "analysis": (f"{cmhk_reference_ppt['period']}净利润为{cmhk_reference_ppt['net_profit_m_hkd']:,.1f}百万港元；为累计值，不与FY2025全年利润直接排名。" if name == "CMHK" and baseline_annual_window else f"{cmhk_reference_ppt['period']}净利润为{cmhk_reference_ppt['net_profit_m_hkd']:,.1f}百万港元；为累计值，不与全年利润直接排名。" if name == "CMHK" else f"FY2025净利润为{float(profit['value']):,.1f}百万港元；只展示金额，不混入同比增速。" if baseline_annual_window else f"{annual_period}净利润为{float(profit['value']):,.1f}百万港元；只展示金额，不混入同比增速。") if profit else f"{missing_note}，不估算净利润。",
            "components": [_component("净利润", round(float(profit["value"]), 1), "百万港元", cmhk_reference_ppt["period"] if name == "CMHK" else annual_period)] if profit else [_component("净利润", detail=missing_note)],
            "component_count": 1, "source_url": str((profit or {}).get("source_url") or ""),
            "verification_count": int((profit or {}).get("verification_count") or 0),
            "trend": _annual_financial_trend(financial_rows, subject, "net_income", unit="百万港元", start_year=annual_start_year, end_year=latest_annual_year, direct_reports=financial_reports, company=operator),
        })
        customer = operating_row(operator, "mobile_postpaid_customers")
        customer_value = _verified_number(customer)
        postpaid_items.append({
            "name": name, "value": round(customer_value, 3) if customer_value is not None else None,
            "unit": "百万户" if customer_value is not None else "", "period": "FY2025",
            "detail": "FY2025后付费用户数" if customer_value is not None else missing_note,
            "analysis": f"FY2025后付费用户数为{customer_value:.3f}百万户；不混入ARPU或总客户口径。" if customer_value is not None else f"{missing_note}；不以总客户或预付客户替代。",
            "components": [_component("后付费用户数", round(customer_value, 3), "百万户", "FY2025")] if customer_value is not None else [_component("后付费用户数", detail=missing_note)],
            "component_count": 1,
            "source_url": str((customer or {}).get("primary_source_url") or ""),
            "verification_count": len(_row_source_urls(customer, source_registry)) if customer else 0,
            "trend": [
                {
                    "label": f"FY{year}",
                    "value": round(float(value), 3) if (value := _verified_number(row)) is not None else None,
                    "unit": "百万户" if value is not None else "",
                    "verification_count": len(_row_source_urls(row, source_registry)) if row else 0,
                    "source_urls": _row_source_urls(row, source_registry),
                }
                for year in range(annual_start_year, latest_annual_year + 1)
                for row in [operating_row(operator, "mobile_postpaid_customers", year)]
            ],
        })

    def focus(fid: str, label: str, items: list[dict[str, Any]], headline: str, context: str) -> dict[str, Any]:
        available = [item for item in items if _number(item.get("value")) is not None]
        lead = max(available, key=lambda item: float(item["value"])) if available else {"name": "-", "value": "-", "unit": ""}
        comparable = (
            [item for item in available if str(item.get("period") or "") == f"FY{latest_annual_year}"]
            if fid in {"revenue", "ebitda", "net_profit"}
            else available
        )
        if len(comparable) < 2 and fid in {"revenue", "ebitda", "net_profit"}:
            period_counts: dict[str, int] = {}
            for item in available:
                period = str(item.get("period") or "")
                if period.startswith("FY"):
                    period_counts[period] = period_counts.get(period, 0) + 1
            comparison_period = max(
                (period for period, count in period_counts.items() if count >= 2),
                key=_period_rank,
                default="",
            )
            comparable = [item for item in available if item.get("period") == comparison_period]
        comparison_lead = max(comparable, key=lambda item: float(item["value"])) if comparable else lead
        low = min(comparable, key=lambda item: float(item["value"])) if comparable else comparison_lead
        if len(comparable) >= 2:
            prefix = f"{comparison_lead['name']}为{comparison_lead['value']}{comparison_lead.get('unit') or ''}，{low['name']}为{low['value']}{low.get('unit') or ''}；"
            implication = {
                "revenue": f"这表明{comparison_lead['name']}的经营资源底盘最厚，更能承担网络与获客投入，{low['name']}的资源容错较窄；规模不等同效率。",
                "ebitda": f"这表明{comparison_lead['name']}的经营造血代理最强，持续投入与价格竞争缓冲更厚，{low['name']}的防守容错更窄。",
                "net_profit": f"这表明{comparison_lead['name']}盈利状态最稳、自我融资与再投资空间最厚，{low['name']}的盈利防线明显承压。",
                "postpaid": f"这表明{comparison_lead['name']}的客户经营底盘更厚，{low['name']}的续约与交叉销售基础较窄；未结合ARPU不判断客户价值。",
            }[fid]
            insight = prefix + implication
        else:
            insight = "当前可比原值不足两家；这一口径缺口限制客户价值和客户质量的穿透比较，不能由总用户或5G用户替代。"
        return {"id": fid, "label": label, "visual": "rows", "headline": headline,
                "metric": {"value": lead["value"], "unit": lead.get("unit") or "", "label": f"{lead['name']} FY2025" if available and baseline_annual_window else f"{lead['name']} {lead.get('period') or f'FY{latest_annual_year}'}" if available else "官方公开数据待补"},
                "context": context, "insight": insight, "items": items}

    focuses = [
        focus("revenue", "营收", revenue_items, "HKT资源底盘最厚", "CMHK为2026首7月累计；其他公司当前卡片显示FY2025" if baseline_annual_window else f"CMHK为2026首7月累计；其他公司显示各自最新正式全年期；年度窗口FY{annual_start_year}–FY{latest_annual_year}"),
        focus("ebitda", "EBITDA", ebitda_items, "HKT造血能力最强", "2016–2025原表；当前卡片显示FY2025" if baseline_annual_window else f"年度窗口FY{annual_start_year}–FY{latest_annual_year}；各公司显示各自最新正式全年期"),
        focus("net_profit", "净利润", profit_items, "HKT稳健三港承压", "CMHK为2026首7月累计；其他公司当前卡片显示FY2025" if baseline_annual_window else f"CMHK为2026首7月累计；其他公司显示各自最新正式全年期；年度窗口FY{annual_start_year}–FY{latest_annual_year}"),
        focus("postpaid", "后付费用户数", postpaid_items, "HKT客户底盘更稳", "只展示公司原生后付费用户数"),
    ]
    return {"id": "local", "index": "01", "title": "本地运营商", "kicker": "CMHK｜HKT｜SmarTone｜3HK",
            "metric": focuses[0]["metric"], "context": "CMHK补充2026首7月累计值；其他公司保留2016–2025财年窗口" if baseline_annual_window else f"CMHK补充2026首7月累计值；正式全年窗口自动滚动为FY{annual_start_year}–FY{latest_annual_year}",
            "insight": "营收、EBITDA、净利润与后付费用户数只展示绝对值；缺口不填充。",
            "entities": revenue_items, "focuses": focuses, "relations": [],
            "sources": _dedupe_sources([_source(item["name"], item.get("source_url")) for items in (revenue_items, ebitda_items, profit_items, postpaid_items) for item in items]),
            "latest_financial_results": financial_reports}


def _component_list(customer_value: float | None, arpu_value: float | None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if customer_value is not None:
        items.append(_component("后付用户数", round(customer_value, 3), "百万户", "FY2025"))
    if arpu_value is not None:
        items.append(_component("后付ARPU", round(arpu_value, 1), "港元/月", "FY2025"))
    return items


def _requested_mainland_domain(
    financial_payload: dict[str, Any],
    operating_payload: dict[str, Any],
    source_registry: dict[str, str],
) -> dict[str, Any]:
    financial_rows = financial_payload.get("rows") or []
    operating_rows = operating_payload.get("rows") or []
    operators = ("中国移动", "中国电信", "中国联通")
    revenue_items: list[dict[str, Any]] = []
    ebitda_items: list[dict[str, Any]] = []
    profit_items: list[dict[str, Any]] = []
    mobile_customer_items: list[dict[str, Any]] = []
    for operator in operators:
        revenue = _annual_financial_value(financial_rows, operator, "revenue", 2025)
        ebitda = _annual_financial_value(financial_rows, operator, "ebitda", 2025)
        profit = _annual_financial_value(financial_rows, operator, "net_income", 2025)
        gap = "官方公开数据待补"
        revenue_item = _financial_item(operator, revenue, "营收", "亿元", gap)
        revenue_item["trend"] = _annual_financial_trend(financial_rows, operator, "revenue", divisor=100, unit="亿元", company=operator)
        revenue_items.append(revenue_item)
        ebitda_item = _financial_item(operator, ebitda, "EBITDA", "亿元", gap)
        ebitda_item["trend"] = _annual_financial_trend(financial_rows, operator, "ebitda", divisor=100, unit="亿元", company=operator)
        ebitda_items.append(ebitda_item)
        profit_item = _financial_item(operator, profit, "净利润", "亿元", gap)
        profit_item["trend"] = _annual_financial_trend(financial_rows, operator, "net_income", divisor=100, unit="亿元", company=operator)
        profit_items.append(profit_item)
        mobile_customer = _published_annual_row(operating_rows, operator, "mobile_subscribers", 2025)
        mobile_customer_value = _verified_number(mobile_customer)
        mobile_customer_sources = _row_provenance_urls(
            mobile_customer, source_registry
        )
        is_derived = str((mobile_customer or {}).get("verification_status") or "") == "official_derived_from_verified_rows"
        missing_mobile_detail = "未见FY2025集团移动客户总数；5G用户数不作替代"
        mobile_customer_items.append({
            "name": operator,
            "value": round(mobile_customer_value / 100, 4) if mobile_customer_value is not None else None,
            "unit": "亿户" if mobile_customer_value is not None else "",
            "period": "FY2025",
            "detail": (
                "FY2025移动出账用户约值 · 官方期初加全年净增推导"
                if is_derived else "FY2025移动客户 · 官方披露"
            ) if mobile_customer_value is not None else missing_mobile_detail,
            "analysis": (
                f"FY2025移动出账用户约{mobile_customer_value / 100:.4g}亿户；由FY2024官方期末值加FY2025官方全年净增推导，不表述为直接披露的精确期末数。"
                if is_derived else
                f"FY2025移动客户为{mobile_customer_value / 100:.4g}亿户；沿用公司移动客户/移动用户官方口径。"
                if mobile_customer_value is not None else
                "官网、年报、业绩公告与业绩演示复核后，未见FY2025集团移动客户总数；5G用户数不作替代。"
            ),
            "components": [_component("移动客户数", round(mobile_customer_value / 100, 4), "亿户", "FY2025")] if mobile_customer_value is not None else [_component("移动客户数", detail=missing_mobile_detail)],
            "component_count": 1,
            "source_url": mobile_customer_sources[0] if mobile_customer_sources else "",
            "source_urls": mobile_customer_sources,
            "verification_count": int((mobile_customer or {}).get("distinct_source_document_count") or 0),
            "verification_status": str((mobile_customer or {}).get("verification_status") or ""),
            "comparator": "≈" if is_derived else "=",
            "trend": [
                {
                    "label": f"FY{year}",
                    "value": round(float(value) / 100, 4) if (value := _verified_number(row)) is not None else None,
                    "unit": "亿户" if value is not None else "",
                    "verification_count": int((row or {}).get("distinct_source_document_count") or 0),
                    "verification_status": str((row or {}).get("verification_status") or ""),
                    "source_urls": _row_provenance_urls(row, source_registry),
                }
                for year in range(2016, 2026)
                for row in [_published_annual_row(operating_rows, operator, "mobile_subscribers", year)]
            ],
        })

    def focus(fid: str, label: str, items: list[dict[str, Any]], context: str) -> dict[str, Any]:
        available = [item for item in items if _number(item.get("value")) is not None]
        lead = max(available, key=lambda item: float(item["value"])) if available else {"name": "-", "value": "-", "unit": ""}
        low = min(available, key=lambda item: float(item["value"])) if available else lead
        if len(available) >= 2:
            prefix = f"{lead['name']}为{lead['value']}{lead.get('unit') or ''}，{low['name']}为{low['value']}{low.get('unit') or ''}；"
            implication = {
                "revenue": f"这表明{lead['name']}的经营资源底盘最厚，更能承担网络与获客投入，{low['name']}的资源容错较窄；规模不等同效率。",
                "ebitda": f"这表明{lead['name']}的经营造血代理最强，持续投入与价格竞争缓冲更厚，{low['name']}的防守容错更窄。",
                "net_profit": f"这表明{lead['name']}盈利状态最稳、自我融资与再投资空间最厚，{low['name']}的盈利防线明显承压。",
                "postpaid": f"这表明{lead['name']}的客户经营底盘更厚，交叉销售与网络规模摊薄基础更广，{low['name']}的底盘较窄；未结合ARPU不判断客户价值。",
            }[fid]
            insight = prefix + implication
        else:
            insight = "当前不足两家公司具备可比移动客户原值；客户覆盖底盘无法形成稳健横向判断，5G用户数也不能替代集团移动客户总数。"
        headline = {
            "revenue": "中国移动资源底盘最强",
            "ebitda": "中国移动造血能力最强",
            "net_profit": "中国移动盈利韧性最强",
            "postpaid": "中国移动客户底盘最厚",
        }[fid]
        return {"id": fid, "label": label, "visual": "rows", "headline": headline, "metric": {"value": lead["value"], "unit": lead.get("unit") or "", "label": f"{lead['name']} FY2025" if available else "官方公开数据待补"}, "context": context, "insight": insight, "items": items}
    focuses = [focus("revenue", "营收", revenue_items, "2016–2025原表；当前卡片显示FY2025"), focus("ebitda", "EBITDA", ebitda_items, "FY2025 EBITDA金额"), focus("net_profit", "净利润", profit_items, "FY2025净利润金额"), focus("postpaid", "移动客户数", mobile_customer_items, "公司披露的移动客户/移动用户；联通约值为官方期初加全年净增推导")]
    return {"id": "mainland", "index": "03", "title": "内地运营商", "kicker": "移动｜电信｜联通", "metric": focuses[0]["metric"], "context": "2016–2025十年窗口；全部卡片只展示绝对数", "insight": "营收、EBITDA、净利润与移动客户数只展示绝对值；移动客户数沿用各公司官方口径，推导值明确标约。", "entities": revenue_items, "focuses": focuses, "relations": [], "sources": _dedupe_sources([_source(item["name"], item.get("source_url")) for items in (revenue_items, ebitda_items, profit_items, mobile_customer_items) for item in items])}


def _financial_item(name: str, row: dict[str, Any] | None, label: str, unit: str, gap: str) -> dict[str, Any]:
    original_value = _number((row or {}).get("value"))
    value = original_value / 100 if original_value is not None and unit == "亿元" else original_value
    source_count = int((row or {}).get("verification_count") or (row or {}).get("distinct_source_document_count") or 0)
    return {"name": name, "value": round(value, 2) if value is not None else None, "unit": unit if value is not None else "", "period": "FY2025", "detail": f"FY2025{label} · 官方披露 · {source_count}个来源" if value is not None else gap,
            "analysis": f"FY2025{label}为{value:,.2f}{unit}；沿用公司原披露口径。" if value is not None else gap,
            "components": [_component(label, round(value, 2), unit, "FY2025")] if value is not None else [_component(label, detail=gap)], "component_count": 1,
            "source_url": str((row or {}).get("source_url") or ""), "verification_count": source_count,
            "verification_status": str((row or {}).get("verification_status") or "")}


def _legacy_merged_international_domain(payload: dict[str, Any]) -> dict[str, Any]:
    """Build domain 02 from the merged international and India carrier group."""
    requested = ("Bharti Airtel", "Reliance Jio", "Verizon", "Deutsche Telekom", "AT&T", "NTT Group")
    rows = [
        row for row in (payload.get("rows") or [])
        if row.get("operator") in requested
        and str(row.get("verification_status") or "") in SAFE_VERIFICATION_STATUSES
        and _verified_number(row) is not None
    ]

    def row_for(operator: str, metric: str, year: int) -> dict[str, Any] | None:
        return next((
            row for row in rows
            if row.get("operator") == operator
            and row.get("metric_key") == metric
            and int(row.get("year") or 0) == year
        ), None)

    def item(operator: str, metric: str, year: int, *, value: float, unit: str, detail: str, analysis: str, trend: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        row = row_for(operator, metric, year) or {}
        result = {
            "name": operator,
            "value": round(value, 2),
            "unit": unit,
            "period": f"FY{year}",
            "detail": detail,
            "analysis": analysis,
            "components": [_component(row.get("metric_zh") or metric, round(value, 2), unit, f"FY{year}")],
            "component_count": 1,
            "source_url": str(row.get("primary_source_url") or ""),
            "verification_count": int(row.get("distinct_source_document_count") or 0),
        }
        if trend:
            result["trend"] = trend
            result["components"] = [_component(point["label"], point["value"], unit, metric) for point in trend]
            result["component_count"] = len(trend)
        return result

    connections: list[dict[str, Any]] = []
    connection_growth: list[dict[str, Any]] = []
    revenue_growth: list[dict[str, Any]] = []
    profit_margin: list[dict[str, Any]] = []
    for operator in requested:
        connection_metric = "total_customers" if operator in {"Bharti Airtel", "Reliance Jio"} else "reported_mobile_connections"
        revenue_metric = "value_of_sales_and_services" if operator == "Reliance Jio" else "revenue"
        profit_metric = "ebitda" if operator == "Reliance Jio" else "net_profit"
        connection_rows = [row_for(operator, connection_metric, year) for year in (2023, 2024, 2025)]
        connection_values = [_verified_number(row) for row in connection_rows]
        latest_connections = connection_values[-1]
        if latest_connections is not None:
            scope = str((connection_rows[-1] or {}).get("scope") or "")
            connections.append(item(
                operator, connection_metric, 2025,
                value=latest_connections, unit="百万连接",
                detail="FY2025官方披露口径；三份底层文件核验",
                analysis=f"FY2025披露口径移动连接/用户数为{latest_connections:.3f}百万；{scope}。",
                trend=[{"label": f"FY{year}", "value": value} for year, value in zip((2023, 2024, 2025), connection_values) if value is not None],
            ))
        if connection_values[-2] not in (None, 0) and connection_values[-1] is not None:
            growth = (connection_values[-1] / connection_values[-2] - 1) * 100
            connection_growth.append(item(
                operator, connection_metric, 2025,
                value=growth, unit="%",
                detail="FY2025较FY2024连接规模变化",
                analysis=f"按同公司连续两年披露口径计算，FY2025移动连接/用户规模同比{growth:+.2f}%；跨公司客户定义不完全相同。",
            ))
        revenues = [_verified_number(row_for(operator, revenue_metric, year)) for year in (2024, 2025)]
        if revenues[0] not in (None, 0) and revenues[1] is not None:
            growth = (revenues[1] / revenues[0] - 1) * 100
            revenue_growth.append(item(
                operator, revenue_metric, 2025,
                value=growth, unit="%",
                detail="FY2025较FY2024原币营收变化",
                analysis=f"在公司本币和原披露口径内，FY2025营收同比{growth:+.2f}%；未做汇率换算。",
            ))
        revenue = revenues[-1]
        profit = _verified_number(row_for(operator, profit_metric, 2025))
        if revenue not in (None, 0) and profit is not None:
            margin = profit / revenue * 100
            margin_label = "EBITDA/销售及服务价值" if operator == "Reliance Jio" else "归母净利润/营收"
            profit_margin.append(item(
                operator, profit_metric, 2025,
                value=margin, unit="%",
                detail=f"FY2025{margin_label}",
                analysis=f"按同公司同年度原币数据计算，FY2025已披露利润率为{margin:.2f}%；Reliance Jio使用EBITDA口径，其余公司使用归母净利润口径。",
            ))

    connections.sort(key=lambda value: float(value["value"]), reverse=True)
    connection_growth.sort(key=lambda value: float(value["value"]), reverse=True)
    revenue_growth.sort(key=lambda value: float(value["value"]), reverse=True)
    profit_margin.sort(key=lambda value: float(value["value"]), reverse=True)
    leader = connections[0] if connections else {"name": "-", "value": 0}
    revenue_leader = revenue_growth[0] if revenue_growth else {"name": "-", "value": 0}
    margin_leader = profit_margin[0] if profit_margin else {"name": "-", "value": 0}
    connection_growth_leader = connection_growth[0] if connection_growth else {"name": "-", "value": 0}
    connection_low = connections[-1] if connections else {"name": "-", "value": 0}
    connection_growth_low = connection_growth[-1] if connection_growth else {"name": "-", "value": 0}
    revenue_low = revenue_growth[-1] if revenue_growth else {"name": "-", "value": 0}
    margin_low = profit_margin[-1] if profit_margin else {"name": "-", "value": 0}
    scope_warning = "六家公司连接口径不同，只比较披露规模；财务变化在各自本币内计算，Reliance Jio利润率采用EBITDA口径，其余采用归母净利润口径。"
    focuses = [
        {
            "id": "scale", "label": "移动连接规模", "visual": "columns",
            "headline": "Bharti Airtel披露规模居前",
            "metric": {"value": leader["value"], "unit": "百万连接", "label": f"{leader['name']} FY2025披露规模"},
            "context": "六家运营商FY2025官方披露口径",
            "insight": f"{leader['name']}为{leader['value']:.2f}百万连接，{connection_low['name']}为{connection_low['value']:.2f}百万连接；差距表明披露规模分层明显，但客户与设备范围不可直接等同。",
            "items": connections,
        },
        {
            "id": "connection_growth", "label": "连接规模变化", "visual": "diverging",
            "headline": "六家连接规模均保持增长",
            "metric": {"value": connection_growth_leader["value"], "unit": "%", "label": f"{connection_growth_leader['name']} FY2025同比"},
            "context": "同公司FY2025对FY2024",
            "insight": f"六家均增长，{connection_growth_leader['name']}为{connection_growth_leader['value']:.2f}%，{connection_growth_low['name']}为{connection_growth_low['value']:.2f}%；这说明连接扩张同向但强弱分化。",
            "items": connection_growth,
        },
        {
            "id": "revenue_growth", "label": "营收变化", "visual": "diverging",
            "headline": "原币营收均实现增长",
            "metric": {"value": revenue_leader["value"], "unit": "%", "label": f"{revenue_leader['name']} FY2025原币营收同比"},
            "context": "同公司原币FY2025对FY2024",
            "insight": f"六家原币营收均增长，{revenue_leader['name']}为{revenue_leader['value']:.2f}%，{revenue_low['name']}为{revenue_low['value']:.2f}%；这表明收入扩张同向但增速分层。",
            "items": revenue_growth,
        },
        {
            "id": "profit_margin", "label": "已披露利润率", "visual": "rows",
            "headline": "盈利缓冲存在明显分层",
            "metric": {"value": margin_leader["value"], "unit": "%", "label": f"{margin_leader['name']} FY2025已披露利润率"},
            "context": "FY2025同公司原币口径；Jio为EBITDA率，其余为归母净利率",
            "insight": f"{margin_leader['name']}已披露利润率为{margin_leader['value']:.2f}%，{margin_low['name']}为{margin_low['value']:.2f}%；利润定义不同，只用于观察各公司自身盈利缓冲。",
            "items": profit_margin,
        },
    ]
    return {
        "id": "international",
        "index": "02",
        "title": "国际运营商",
        "kicker": "连接规模、增长与盈利",
        "metric": {"value": leader["value"], "unit": "百万连接", "label": f"{leader['name']} FY2025披露规模"},
        "context": "Bharti Airtel、Reliance Jio、Verizon、Deutsche Telekom、AT&T、NTT Group；全部展示值经三份不同底层官方文件核验",
        "insight": scope_warning,
        "entities": connections,
        "focuses": focuses,
        "relations": [
            {"title": value["name"], "detail": f"FY2025披露规模 {value['value']:.2f} 百万连接", "kind": "三来源认证"}
            for value in connections
        ],
        "sources": _dedupe_sources([_source(value["name"], value["source_url"]) for value in connections]),
    }


def _cloud_domain(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("rows") or []
    vendors = [str(vendor.get("vendor") or "") for vendor in payload.get("vendors") or []]
    revenue_amount_items: list[dict[str, Any]] = []
    profit_amount_items: list[dict[str, Any]] = []
    growth_items: list[dict[str, Any]] = []
    trend_items: list[dict[str, Any]] = []
    profit_items: list[dict[str, Any]] = []
    margin_change_items: list[dict[str, Any]] = []
    capex_items: list[dict[str, Any]] = []
    profit_keys = ("operating_margin", "adjusted_ebita_margin", "proxy_segment_gross_margin")
    profit_amount_keys = ("cloud_operating_profit", "operating_income", "adjusted_ebita", "proxy_segment_gross_profit", "cloud_and_license_margin")
    comparison_year_candidates = sorted({
        str(row.get("fiscal_year") or "")
        for row in rows
        if str(row.get("metric_key") or "") in {"cloud_revenue", "proxy_segment_revenue"}
        and _verified_number(row) is not None
        and str(row.get("verification_status") or "") in SAFE_VERIFICATION_STATUSES
    })
    comparison_year = comparison_year_candidates[-1] if comparison_year_candidates else "2024"

    def amount_trend(vendor: str, metric_keys: tuple[str, ...]) -> list[dict[str, Any]]:
        trend: list[dict[str, Any]] = []
        for year in range(2016, 2026):
            row = next((
                candidate for key in metric_keys
                if (candidate := _metric_for_fiscal_year(rows, "vendor", vendor, key, str(year)))
                and _verified_number(candidate) is not None
            ), None)
            original = _verified_number(row)
            value = _million_usd(original, str((row or {}).get("currency") or ""), year)
            trend.append({
                "label": f"FY{year}", "value": round(value, 1) if value is not None else None,
                "unit": "百万美元" if value is not None else "",
                "source_urls": _row_source_urls(row),
                "verification_count": int((row or {}).get("verification_count") or 0),
            })
        return trend

    for vendor in vendors:
        row = _metric_for_fiscal_year(rows, "vendor", vendor, "revenue_yoy", comparison_year)
        value = _verified_number(row)
        name = vendor.replace(" / Intelligent Cloud", "").replace(" / Tencent FBS proxy", "").replace(" / Cloud Computing", "")
        name = {
            "China Mobile Cloud": "中国移动云",
            "Google Cloud": "Google",
            "Microsoft Azure": "Azure",
            "Alibaba Cloud": "Alibaba",
            "Tencent Cloud": "腾讯",
            "Huawei Cloud": "Huawei",
            "Oracle Cloud": "Oracle",
        }.get(name, name)
        source_url = str((row or {}).get("primary_source_url") or "")
        disclosure_quality = str((row or {}).get("disclosure_quality") or "")
        if disclosure_quality.startswith("direct"):
            growth_scope = "公司直接披露的云业务口径"
        elif "proxy" in disclosure_quality:
            growth_scope = "代理分部口径，可能包含非云业务"
        elif "reclassification" in disclosure_quality:
            growth_scope = "含重分类的分部口径"
        else:
            growth_scope = "公司披露口径"
        revenue_row = _metric_for_fiscal_year(rows, "vendor", vendor, "cloud_revenue", comparison_year)
        if _verified_number(revenue_row) is None and vendor.startswith("Tencent Cloud"):
            revenue_row = _metric_for_fiscal_year(rows, "vendor", vendor, "proxy_segment_revenue", comparison_year)
        revenue_value = _verified_number(revenue_row)
        revenue_currency = str((revenue_row or {}).get("currency") or "")
        revenue_usd = _million_usd(revenue_value, revenue_currency, int(comparison_year))
        revenue_components = (
            [_component("云业务收入", round(revenue_usd, 1), "百万美元", f"FY{comparison_year} · 原值{revenue_value:,.1f}百万{revenue_currency} · {comparison_year}年均汇率")]
            if revenue_usd is not None else []
        )
        revenue_amount_items.append({
            "name": name,
            "value": round(revenue_usd, 1) if revenue_usd is not None else None,
            "unit": "百万美元" if revenue_usd is not None else "",
            "period": f"FY{comparison_year}",
            "detail": f"FY{comparison_year}云收入金额 · 统一折算美元" if revenue_usd is not None else "三来源云收入金额待补",
            "analysis": (
                f"FY{comparison_year}云收入折算为{revenue_usd:,.1f}百万美元（原值{revenue_value:,.1f}百万{revenue_currency}）；只展示收入金额。"
                if revenue_usd is not None else "未收录通过三份独立来源核验的云收入金额，保留缺口。"
            ),
            "components": revenue_components or [_component("云收入", detail="官方公开数据待补")],
            "component_count": 1,
            "source_url": str((revenue_row or row or {}).get("primary_source_url") or ""),
            "trend": amount_trend(vendor, ("cloud_revenue", "proxy_segment_revenue")),
        })
        if value is not None and row:
            growth_items.append({
                "name": name, "value": round(value, 1), "unit": "%",
                "period": f"FY{row.get('fiscal_year')}",
                "detail": f"FY{row.get('fiscal_year')} · {growth_scope}",
                "analysis": f"FY{row.get('fiscal_year')}该披露口径的收入同比变化为 {value:+.1f}%；{growth_scope}。不同口径不可直接视为纯云业务排名。",
                "components": revenue_components + [_component(f"FY{row.get('fiscal_year')}云业务收入同比", round(value, 1), "%")],
                "component_count": len(revenue_components) + 1,
                "source_url": source_url,
            })
            history = [
                item for item in _metric_history(rows, "vendor", vendor, "revenue_yoy")
                if str(item.get("fiscal_year") or "") <= comparison_year
            ]
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
        profit_label = {
            "operating_margin": "经营利润率",
            "adjusted_ebita_margin": "调整后EBITA率",
            "proxy_segment_gross_margin": "代理分部毛利率",
        }.get(str((profit_row or {}).get("metric_key") or ""), "利润率") if profit_row else "未披露利润率"
        profit_items.append({
            "name": name,
            "value": round(profit_value, 1) if profit_value is not None else None,
            "unit": "%" if profit_value is not None else "",
            "detail": f"FY{profit_row.get('fiscal_year')} · {profit_label}" if profit_row else "保留披露缺口",
            "analysis": (
                f"FY{profit_row.get('fiscal_year')}披露的{profit_label}为 {profit_value:.1f}%；不同利润口径不可直接比较。"
                if profit_value is not None and profit_row else "未披露利润率。"
            ),
            "components": (
                [_component(profit_label, round(profit_value, 1), "%", f"FY{profit_row.get('fiscal_year')}")]
                if profit_value is not None and profit_row else [_component("利润率", detail="未披露")]
            ),
            "component_count": 1,
            "source_url": str((profit_row or row or {}).get("primary_source_url") or ""),
        })
        profit_amount_row = next((
            candidate for key in profit_amount_keys
            if (candidate := _metric_for_fiscal_year(rows, "vendor", vendor, key, comparison_year))
            and _verified_number(candidate) is not None
        ), None)
        profit_amount_original = _verified_number(profit_amount_row)
        profit_amount_currency = str((profit_amount_row or {}).get("currency") or "")
        profit_amount_usd = _million_usd(profit_amount_original, profit_amount_currency, int(comparison_year))
        profit_amount_label = {
            "cloud_operating_profit": "云业务经营利润",
            "operating_income": "云分部经营利润",
            "adjusted_ebita": "云业务调整后EBITA",
            "proxy_segment_gross_profit": "代理分部毛利",
            "cloud_and_license_margin": "云与许可证分部利润",
        }.get(str((profit_amount_row or {}).get("metric_key") or ""), "云利润")
        profit_amount_items.append({
            "name": name,
            "value": round(profit_amount_usd, 1) if profit_amount_usd is not None else None,
            "unit": "百万美元" if profit_amount_usd is not None else "",
            "period": f"FY{comparison_year}",
            "detail": f"FY{comparison_year}{profit_amount_label} · 统一折算美元" if profit_amount_usd is not None else "三来源云利润金额待补",
            "analysis": (
                f"FY{comparison_year}{profit_amount_label}折算为{profit_amount_usd:,.1f}百万美元（原值{profit_amount_original:,.1f}百万{profit_amount_currency}）；只展示金额，利润定义按厂商原披露标注。"
                if profit_amount_usd is not None else "未收录通过三份独立来源核验的云利润金额，保留缺口。"
            ),
            "components": [_component(profit_amount_label, round(profit_amount_usd, 1), "百万美元", f"FY{comparison_year}")] if profit_amount_usd is not None else [_component("云利润", detail="官方公开数据待补")],
            "component_count": 1,
            "source_url": str((profit_amount_row or row or {}).get("primary_source_url") or ""),
            "trend": amount_trend(vendor, profit_amount_keys),
        })
        profit_history = _metric_history(rows, "vendor", vendor, str((profit_row or {}).get("metric_key") or "")) if profit_row else []
        previous_profit = _verified_number(profit_history[-2]) if len(profit_history) > 1 else None
        margin_change = profit_value - previous_profit if profit_value is not None and previous_profit is not None else None
        margin_change_items.append({
            "name": name, "value": round(margin_change, 1) if margin_change is not None else None,
            "unit": "个百分点" if margin_change is not None else "",
            "detail": f"FY{profit_history[-2].get('fiscal_year')}→FY{profit_row.get('fiscal_year')} · {profit_label}" if margin_change is not None else "缺少同口径上一财年",
            "analysis": (
                f"{profit_label}由 {previous_profit:.1f}% 变为 {profit_value:.1f}%，变化 {margin_change:+.1f} 个百分点；"
                f"利润转化{'改善' if margin_change > 0 else '减弱' if margin_change < 0 else '持平'}。"
                if margin_change is not None else "缺少同一利润率口径的连续两年数据。"
            ),
            "trend": [{"label": f"FY{item.get('fiscal_year')}", "value": _verified_number(item)} for item in profit_history[-3:]],
            "components": [_component(f"FY{item.get('fiscal_year')}", _verified_number(item), "%", profit_label) for item in profit_history[-3:]] or [_component(profit_label, detail="未披露连续两年")],
            "component_count": len(profit_history[-3:]), "source_url": str((profit_row or row or {}).get("primary_source_url") or ""),
        })
        capex_row = _latest_metric(rows, "vendor", vendor, "group_capex")
        capex_original = _verified_number(capex_row)
        capex_currency = str((capex_row or {}).get("currency") or "")
        capex_year = int(str((capex_row or {}).get("fiscal_year") or comparison_year))
        capex_value = _million_usd(capex_original, capex_currency, capex_year)
        capex_unit = "百万美元" if capex_value is not None else ""
        capex_items.append({
            "name": name,
            "value": round(capex_value, 1) if capex_value is not None else None,
            "unit": capex_unit,
            "period": f"FY{capex_row.get('fiscal_year')}" if capex_row else "",
            "detail": (
                f"FY{capex_row.get('fiscal_year')} · 母公司集团口径 · 统一折算美元"
                if capex_value is not None and capex_row else "原表尚未收录集团资本开支"
            ),
            "analysis": (
                f"FY{capex_row.get('fiscal_year')}集团资本开支折算为 {capex_value:,.1f} 百万美元（原值{capex_original:,.1f}百万{capex_currency}）；"
                "该值是母公司集团投入，不是云业务单独CAPEX，且不跨币种排名。"
                if capex_value is not None and capex_row else "原表尚未收录可通过三份独立来源核验的集团资本开支，保留缺口。"
            ),
            "components": (
                [_component("集团资本开支", round(capex_value, 1), capex_unit, f"FY{capex_row.get('fiscal_year')}")]
                if capex_value is not None and capex_row else [_component("集团资本开支", detail="官方公开数据待补")]
            ),
            "component_count": 1,
            "source_url": str((capex_row or row or {}).get("primary_source_url") or ""),
            "trend": amount_trend(vendor, ("group_capex",)),
        })
    if not any(item.get("name") == "Huawei" for item in growth_items):
        vendor = next((value for value in vendors if value.startswith("Huawei Cloud")), "Huawei Cloud / Cloud Computing")
        revenue_row = _metric_for_fiscal_year(rows, "vendor", vendor, "cloud_revenue", comparison_year)
        revenue_value = _verified_number(revenue_row)
        currency = str((revenue_row or {}).get("currency") or "CNY")
        revenue_usd = _million_usd(revenue_value, currency, int(comparison_year))
        source_url = str((revenue_row or {}).get("primary_source_url") or "")
        growth_items.append({
            "name": "Huawei", "value": None, "unit": "", "period": f"FY{comparison_year}",
            "detail": f"FY{comparison_year}云业务收入已披露；同比增速缺口",
            "analysis": f"FY{comparison_year}云业务收入折算为{revenue_usd:,.1f}百万美元（原值{revenue_value:,.1f}百万{currency}）；同比增速缺口不估算。" if revenue_usd is not None else "云业务收入及同比增速均待三来源补齐。",
            "components": [_component("云业务收入", round(revenue_usd, 1), "百万美元", f"FY{comparison_year} · 原值{revenue_value:,.1f}百万{currency} · {comparison_year}年均汇率"), _component("云业务收入同比", detail="官方公开数据待补")] if revenue_usd is not None else [_component("云业务收入及同比", detail="官方公开数据待补")],
            "component_count": 2 if revenue_usd is not None else 1, "source_url": source_url,
        })
        revenue_amount_items.append({
            "name": "Huawei", "value": round(revenue_usd, 1) if revenue_usd is not None else None,
            "unit": "百万美元" if revenue_usd is not None else "", "period": f"FY{comparison_year}",
            "detail": f"FY{comparison_year}云收入金额 · 统一折算美元" if revenue_usd is not None else "三来源云收入金额待补",
            "analysis": f"FY{comparison_year}云收入折算为{revenue_usd:,.1f}百万美元（原值{revenue_value:,.1f}百万{currency}）；只展示收入金额。" if revenue_usd is not None else "三来源云收入金额待补。",
            "components": [_component("云收入", round(revenue_usd, 1), "百万美元", f"FY{comparison_year}")] if revenue_usd is not None else [_component("云收入", detail="官方公开数据待补")],
            "component_count": 1, "source_url": source_url,
            "trend": amount_trend(vendor, ("cloud_revenue", "proxy_segment_revenue")),
        })
        profit_amount_items.append({"name": "Huawei", "value": None, "unit": "", "period": f"FY{comparison_year}", "detail": "三来源云利润金额待补",
                                    "analysis": "原表尚未收录公开披露的云利润金额，保留缺口。", "components": [_component("云利润", detail="官方公开数据待补")], "component_count": 1, "source_url": source_url,
                                    "trend": amount_trend(vendor, profit_amount_keys)})
        for bucket, label in ((profit_items, "云业务利润或利润率"), (capex_items, "集团资本开支")):
            bucket.append({"name": "Huawei", "value": None, "unit": "", "period": "", "detail": "官方公开数据待补",
                           "analysis": f"原表尚未收录可通过三份不同来源核验的{label}，保留缺口。",
                           "components": [_component(label, detail="官方公开数据待补")], "component_count": 1, "source_url": source_url,
                           "trend": amount_trend(vendor, ("group_capex",)) if bucket is capex_items else []})
    growth_items.sort(key=lambda item: (_number(item.get("value")) is not None, _number(item.get("value")) or 0), reverse=True)
    revenue_amount_items.sort(key=lambda item: (_number(item.get("value")) is not None, _number(item.get("value")) or 0), reverse=True)
    profit_amount_items.sort(key=lambda item: (_number(item.get("value")) is not None, _number(item.get("value")) or 0), reverse=True)
    trend_items.sort(key=lambda item: (_number(item.get("value")) is not None, _number(item.get("value")) or 0), reverse=True)
    profit_items.sort(key=lambda item: (_number(item.get("value")) is not None, _number(item.get("value")) or 0), reverse=True)
    margin_change_items.sort(key=lambda item: (_number(item.get("value")) is not None, _number(item.get("value")) or 0), reverse=True)
    capex_items.sort(key=lambda item: (_number(item.get("value")) is not None, _number(item.get("value")) or 0), reverse=True)
    leader = growth_items[0] if growth_items else {"name": "-", "value": 0}
    revenue_amount_leader = next((item for item in revenue_amount_items if _number(item.get("value")) is not None), {"name": "-", "value": "-"})
    profit_amount_leader = next((item for item in profit_amount_items if _number(item.get("value")) is not None), {"name": "-", "value": "-"})
    direct_growth = [item for item in growth_items if "直接披露" in str(item.get("detail") or "")]
    short_cloud_name = lambda name: str(name).replace(" Cloud", "").replace("Microsoft Azure", "Azure").replace("Tencent", "腾讯")
    direct_growth_text = "、".join(f"{short_cloud_name(item['name'])}{item['value']:.1f}%" for item in direct_growth[:4])
    proxy_names = "、".join(short_cloud_name(item["name"]) for item in growth_items if "代理分部" in str(item.get("detail") or ""))
    insight = (
        f"直接披露云收入的厂商中，{direct_growth_text}；这说明即使口径相同，厂商扩张速度仍不同，不能用单一行业增速概括。"
        + (f"{proxy_names}采用代理分部口径，不参与同一排名。" if proxy_names else "")
    )
    best_trend = next((item for item in trend_items if _number(item.get("value")) is not None), None)
    aws_profit = next((item for item in profit_items if item["name"] == "AWS" and _number(item.get("value")) is not None), None)
    proxy_profit = next((item for item in profit_items if "代理分部" in str(item.get("detail") or "") and _number(item.get("value")) is not None), None)
    profit_insight = (
        f"AWS披露经营利润率{aws_profit['value']:.1f}%，{proxy_profit['name']}披露代理分部毛利率{proxy_profit['value']:.1f}%；"
        "两者利润口径不同，这说明数值不可直接比较，只能分别观察各自的利润转化变化。"
        if aws_profit and proxy_profit else "各厂商利润率口径不同，这说明数值不可直接比较，只能分别观察各自变化。"
    )
    comparable_margin_changes = [item for item in margin_change_items if _number(item.get("value")) is not None]
    margin_change_insight = (
        f"{comparable_margin_changes[0]['name']}同口径利润率提高 {comparable_margin_changes[0]['value']:+.1f} 个百分点，"
        f"{comparable_margin_changes[-1]['name']}下降 {abs(float(comparable_margin_changes[-1]['value'])):.1f} 个百分点；差距说明收入增长不等于利润转化同步改善。"
        if len(comparable_margin_changes) >= 2 else "缺少同口径连续两年利润率，不判断增长质量变化。"
    )
    comparable_trends = [item for item in trend_items if _number(item.get("value")) is not None]
    disclosed_capex = [item for item in capex_items if _number(item.get("value")) is not None]
    capex_leader = disclosed_capex[0] if disclosed_capex else {"name": "-", "value": "-"}
    revenue_tail = next((item for item in reversed(revenue_amount_items) if _number(item.get("value")) is not None), revenue_amount_leader)
    aws_profit_amount = next((item for item in profit_amount_items if item["name"] == "AWS" and _number(item.get("value")) is not None), None)
    google_profit_amount = next((item for item in profit_amount_items if item["name"] == "Google" and _number(item.get("value")) is not None), None)
    capex_tail = next((item for item in reversed(disclosed_capex) if _number(item.get("value")) is not None), capex_leader)
    accelerating = [item for item in comparable_trends if float(item["value"]) > 0]
    slowing = [item for item in comparable_trends if float(item["value"]) < 0]
    trend_insight = (
        f"FY{comparison_year}相对FY{int(comparison_year) - 1}，{len(comparable_trends)}家可比厂商中{len(accelerating)}家收入增速提高"
        + (f"，只有{'、'.join(short_cloud_name(item['name']) for item in slowing)}放缓" if len(slowing) == 1 else f"、{len(slowing)}家放缓")
        + f"；{short_cloud_name(best_trend['name'])}提高{float(best_trend['value']):.1f}个百分点最多，这说明提速并非少数现象。"
        if best_trend and comparable_trends else "缺少连续两年收入增速，不判断增长变化。"
    )
    focuses = [
        {
            "id": "revenue", "label": "云收入", "visual": "columns",
            "metric": {"value": revenue_amount_leader["value"], "unit": "百万美元", "label": f"{revenue_amount_leader['name']} FY{comparison_year}云收入"},
            "context": f"FY{comparison_year}最新已核验披露 · 覆盖 {len(revenue_amount_items)} 家全球云厂商 · 统一折算百万美元",
            "insight": f"{revenue_amount_leader['name']}云收入{revenue_amount_leader['value']:g}百万美元、{revenue_tail['name']}为{revenue_tail['value']:g}百万美元；这表明{revenue_amount_leader['name']}的云业务生态底盘最厚，持续投入能力更强，{revenue_tail['name']}资源弹性较窄。",
            "items": revenue_amount_items,
        },
        {
            "id": "profit", "label": "云利润", "visual": "columns",
            "metric": {"value": profit_amount_leader["value"], "unit": "百万美元", "label": f"{profit_amount_leader['name']} FY{comparison_year}云利润"},
            "context": "按各厂商原生利润定义标注 · 统一折算百万美元",
            "insight": (
                f"同属经营利润披露的AWS为{aws_profit_amount['value']:g}百万美元、Google为{google_profit_amount['value']:g}百万美元；"
                "这表明AWS的云业务自我造血能力更强，可用更厚盈利缓冲支撑再投资与价格竞争；其他利润定义不混入这一判断。"
                if aws_profit_amount and google_profit_amount else
                "各厂商利润定义不同；页面保留原披露口径和缺口，不把异口径利润混入同一判断。"
            ),
            "items": profit_amount_items,
        },
        {
            "id": "investment", "label": "资本开支", "visual": "rows",
            "metric": {"value": capex_leader["value"], "unit": "百万美元", "label": f"{capex_leader['name']} {capex_leader.get('period') or '最新披露期'}集团资本开支"},
            "context": "各公司最新已核验披露期 · 母公司集团口径 · 统一折算百万美元 · 原币明细保留",
            "insight": f"{capex_leader['name']}集团资本开支{capex_leader['value']:g}百万美元、{capex_tail['name']}为{capex_tail['value']:g}百万美元；这表明{capex_leader['name']}的基础设施扩容弹药更足，{capex_tail['name']}集团投入空间较窄，但不代表云投入效率。",
            "items": capex_items,
        },
    ]
    for focus in focuses:
        focus["headline"] = {
            "revenue": "AWS生态底盘领先",
            "profit": "AWS自我造血能力最强", "investment": "AWS扩容弹药最足",
        }[focus["id"]]
    return {
        "id": "cloud",
        "index": "04",
        "title": "全球云厂商",
        "kicker": "收入｜利润｜集团资本开支",
        "metric": {"value": revenue_amount_leader["value"], "unit": "百万美元", "label": f"{revenue_amount_leader['name']} FY{comparison_year}云收入"},
        "context": f"2016–2025十年窗口；收入与利润采用FY{comparison_year}最新已核验披露，资本开支采用各公司最新已披露期",
        "insight": "云收入、云利润和集团资本开支只展示绝对值；原币和原生利润定义保留在明细。",
        "entities": revenue_amount_items,
        "focuses": focuses,
        "relations": [
            {"title": item["name"], "detail": (f"FY{comparison_year} 云收入 {item['value']:,.1f} 百万美元" if _number(item.get("value")) is not None else f"FY{comparison_year} 云收入金额待三来源补齐"), "kind": "公司披露数据"}
            for item in revenue_amount_items
        ],
        "sources": _dedupe_sources([_source(item["name"], item["source_url"]) for item in growth_items] + [_source(label, url) for label, url in _fx_sources()]),
    }


def _macro_domain(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def readable_value(metric: str, value: float | None) -> tuple[Any, str]:
        if value is None:
            return None, ""
        if metric in {"mobile_subscriptions", "mobile_broadband_subscriptions"}:
            return int(round(value)), "个连接"
        if metric == "mobile_subscriber_penetration_rate":
            return round(value, 1), "%"
        if metric == "mobile_data_usage_total_mbytes":
            return round(value / 100_000_000, 1), "亿MB"
        if metric == "mobile_data_usage_per_mobile_broadband_subscription_mbytes":
            return round(value, 1), "MB/连接"
        if metric == "median_monthly_household_income":
            return int(round(value)), "港元/月"
        if metric == "annual_telecom_investment":
            return value, "百万港元"
        if metric == "telecom_consumer_complaints_total":
            return int(round(value)), "宗"
        return value, ""

    def history(metric: str, name_contains: str = "") -> list[dict[str, Any]]:
        matches = [row for row in rows if row.get("metric_key") == metric and _number(row.get("value")) is not None and str(row.get("verification_status") or "") in SAFE_VERIFICATION_STATUSES and (not name_contains or name_contains in str(row.get("metric_name") or ""))]
        return sorted(matches, key=lambda row: str(row.get("period_end") or ""))

    def yoy_item(metric: str, label: str, same_grain: bool = False, name_contains: str = "") -> dict[str, Any] | None:
        series = history(metric, name_contains)
        if not series:
            return None
        latest = series[-1]
        if same_grain:
            for candidate in reversed(series):
                candidate_date = str(candidate.get("period_end") or "")
                try:
                    prior_date = datetime.fromisoformat(candidate_date).replace(year=datetime.fromisoformat(candidate_date).year - 1).date().isoformat()
                except ValueError:
                    continue
                if any(str(row.get("period_end") or "") == prior_date and str(row.get("grain") or "") == str(candidate.get("grain") or "") for row in series):
                    latest = candidate
                    break
        latest_value = _number(latest.get("value"))
        latest_date = str(latest.get("period_end") or "")
        try:
            previous_date = datetime.fromisoformat(latest_date).replace(year=datetime.fromisoformat(latest_date).year - 1).date().isoformat()
        except ValueError:
            previous_date = ""
        grain = str(latest.get("grain") or "")
        previous = next((row for row in reversed(series[:-1]) if str(row.get("period_end") or "") == previous_date and (not same_grain or str(row.get("grain") or "") == grain)), None)
        previous_value = _number((previous or {}).get("value"))
        change = ((latest_value / previous_value - 1) * 100) if latest_value is not None and previous_value not in (None, 0) else None
        meanings = {
            "手机卡/设备": "同一客户可有多张卡，联网设备也会单独登记",
            "移动宽带": "登记数量不等同独立客户人数",
            "每百人登记": "该指标同时受多卡及联网设备影响",
            "移动数据总量": "变化反映整体数据需求强度",
            "每个移动宽带连接用量": "变化反映单连接使用强度",
            "家庭月入中位数": "变化是家庭购买力代理",
            "电讯业投资": "变化反映行业网络投入规模",
            "电讯投诉": "变化反映服务压力，不证明单一原因",
        }
        latest_display, component_unit = readable_value(metric, latest_value)
        previous_display, _ = readable_value(metric, previous_value)
        if metric in {"mobile_subscriptions", "mobile_broadband_subscriptions"}:
            latest_text = f"{int(latest_display):,}个连接"
        elif metric == "mobile_data_usage_total_mbytes":
            latest_text = f"{latest_display:,.1f}亿MB"
        elif metric == "mobile_data_usage_per_mobile_broadband_subscription_mbytes":
            latest_text = f"{latest_display:,.1f}MB/连接"
        elif metric == "median_monthly_household_income":
            latest_text = f"{int(latest_display):,}港元/月"
        else:
            latest_text = f"{latest_display:g}{component_unit}" if isinstance(latest_display, (int, float)) else str(latest_display or "未披露")
        return {
            "name": label, "value": round(change, 1) if change is not None else None, "unit": "%" if change is not None else "",
            "detail": f"{latest_date} 对比 {previous_date}" if change is not None else f"截至 {latest_date} · 缺少同周期上年值",
            "analysis": (f"{latest_date}为{latest_text}，同比{change:+.1f}%；{meanings.get(label, '变化反映该指标的年度趋势')}。" if change is not None else f"截至{latest_date}缺少同周期上年值。"),
            "components": [_component(latest_date, latest_display, component_unit), _component(previous_date, previous_display, component_unit)] if previous else [_component(latest_date, latest_display, component_unit)],
            "component_count": 2 if previous else 1, "source_url": str(latest.get("official_source_url") or ""),
        }

    connection_items = [item for item in [yoy_item("mobile_subscriptions", "手机卡/设备"), yoy_item("mobile_broadband_subscriptions", "移动宽带"), yoy_item("mobile_subscriber_penetration_rate", "每百人登记")] if item]
    traffic_items = [item for item in [yoy_item("mobile_data_usage_total_mbytes", "移动数据总量"), yoy_item("mobile_data_usage_per_mobile_broadband_subscription_mbytes", "每个移动宽带连接用量")] if item]
    income_item = yoy_item("median_monthly_household_income", "家庭月入中位数")
    cpi_series = history("consumer_price_indices_a_cm_1920", "Year-on-year % change")
    cpi_item = None
    if cpi_series:
        income_period = str((income_item or {}).get("detail") or "").split(" 对比 ", 1)[0]
        row = next((item for item in reversed(cpi_series) if str(item.get("period_end") or "") == income_period), cpi_series[-1])
        value = _number(row.get("value"))
        cpi_item = {"name": "甲类消费物价同比", "value": round(value, 1) if value is not None else None, "unit": "%", "detail": f"截至 {row.get('period_end')}", "analysis": f"截至 {row.get('period_end')}甲类消费物价同比为 {value:.1f}%；它是购买力压力代理，不等于电讯消费支出。", "components": [_component("甲类消费物价同比", value, "%", row.get("period_end"))], "component_count": 1, "source_url": str(row.get("official_source_url") or "")}
    purchasing_items = [item for item in [income_item, cpi_item] if item]
    periods_align = bool(income_item and cpi_item and str(income_item.get("detail") or "").startswith(str(cpi_item.get("detail") or "").replace("截至 ", "")))
    if periods_align and income_item and cpi_item and _number(income_item.get("value")) is not None and _number(cpi_item.get("value")) is not None:
        gap = float(income_item["value"]) - float(cpi_item["value"])
        income_period = str(income_item.get("detail") or "").split(" 对比 ", 1)[0]
        purchasing_analysis = (
            f"{income_period}家庭月入同比{float(income_item['value']):+.1f}%，甲类消费物价同比{float(cpi_item['value']):+.1f}%，"
            f"两者相减的购买力代理为{gap:+.1f}%；这说明家庭购买力承压，但电讯消费行为未单独统计。"
        )
        purchasing_items.insert(0, {"name": "购买力代理变化", "value": round(gap, 1), "unit": "%", "detail": f"{income_item['detail']} · 收入增幅减物价增幅", "analysis": purchasing_analysis, "components": [_component("家庭月入同比", income_item["value"], "%"), _component("甲类消费物价同比", cpi_item["value"], "%")], "component_count": 2, "source_url": income_item["source_url"]})
    investment_item = yoy_item("annual_telecom_investment", "电讯业投资")
    complaints_item = yoy_item("telecom_consumer_complaints_total", "电讯投诉", same_grain=True)
    service_items = [item for item in [investment_item, complaints_item] if item]
    for metric, label, unit in (("5g_population_coverage_status", "5G人口覆盖", "%"), ("5g_spectrum_assigned_mhz", "已分配公共移动及5G频谱", "MHz")):
        series = history(metric)
        if series:
            row = series[-1]
            value = _number(row.get("value"))
            plus = metric == "5g_population_coverage_status" and str(row.get("unit") or "") == "percent_plus"
            display_value = f"超过{value:g}%" if plus else value
            display_unit = "" if plus else unit
            service_items.append({"name": label, "value": display_value, "unit": display_unit, "detail": f"截至 {row.get('period_end')}", "analysis": f"截至 {row.get('period_end')}{label}{'超过' if plus else '为 '}{value:g}{unit}；这是网络供给背景，不单独证明服务质量改善。", "components": [_component(label, display_value, display_unit, row.get("period_end"))], "component_count": 1, "source_url": str(row.get("official_source_url") or "")})

    traffic_total = next((item for item in traffic_items if item["name"] == "移动数据总量"), None)
    traffic_per = next((item for item in traffic_items if item["name"] == "每个移动宽带连接用量"), None)
    traffic_insight = (f"总流量同比 {traffic_total['value']:+.1f}%，每连接流量同比 {traffic_per['value']:+.1f}%；差距说明增量更偏连接规模，而非单连接使用强度。" if traffic_total and traffic_per and _number(traffic_total.get("value")) is not None and _number(traffic_per.get("value")) is not None else "缺少同周期数据，不判断流量增长来源。")
    purchasing_gap = purchasing_items[0] if purchasing_items and purchasing_items[0]["name"] == "购买力代理变化" else None
    focuses = [
        {"id": "connections", "label": "登记数量", "visual": "diverging", "metric": {**_focus_metric(connection_items, "手机卡/设备同比", "%"), "label": "手机卡/设备同比"}, "context": "最新月对比上年同月", "insight": (f"手机卡及联网设备登记数、移动宽带登记数、每百人移动登记数同比分别为{connection_items[0]['value']:+.1f}%、{connection_items[1]['value']:+.1f}%、{connection_items[2]['value']:+.1f}%；同一客户可有多张卡，联网设备也会单独登记，因此这些增幅不能当作客户人数增长。" if len(connection_items) >= 3 and all(_number(item.get('value')) is not None for item in connection_items[:3]) else "缺少同月上年数据，无法比较登记数量变化。"), "items": connection_items},
        {"id": "traffic", "label": "流量增长", "visual": "diverging", "metric": {**_focus_metric(traffic_items, "移动数据总量同比", "%"), "label": "移动数据总量同比"}, "context": "最新年度对比上年", "insight": traffic_insight, "items": traffic_items},
        {"id": "purchasing", "label": "家庭购买力", "visual": "diverging", "metric": {"value": purchasing_gap["value"] if purchasing_gap else "-", "unit": "%", "label": "购买力代理变化"}, "context": "收入与物价的同周期变化", "insight": (purchasing_gap["analysis"] if purchasing_gap else "缺少同周期收入与物价数据，不判断购买力变化。"), "items": purchasing_items},
        {"id": "service", "label": "投入与投诉", "visual": "kpis", "metric": {"value": investment_item["value"] if investment_item else "-", "unit": "%", "label": "电讯业投资同比"}, "context": "投资和投诉各自与同周期上年比较", "insight": (f"电讯业投资在截至2025年3月的财政年度增长{investment_item['value']:.1f}%；2025年全年投诉增长{complaints_item['value']:.1f}%。两项数据期间不同，这说明它们只能分别反映投入与服务压力，不能比较差距或建立关系。" if investment_item and complaints_item and _number(investment_item.get("value")) is not None and _number(complaints_item.get("value")) is not None else "投资与投诉缺少同周期对照，不建立因果关系。"), "items": service_items},
    ]
    for focus in focuses:
        focus["headline"] = {
            "connections": "登记增加不等于客户增加", "traffic": "总量增长高于单连接",
            "purchasing": "购买力代理指标下降", "service": "投入与投诉不可直接关联",
        }[focus["id"]]
    entities = [item for focus in focuses for item in focus["items"]]
    lead_connection = connection_items[0] if connection_items else {"value": "-"}
    insight = "登记数量、流量、购买力和服务压力分别判断；手机卡及联网设备登记数不等于独立客户人数。"
    return {
        "id": "macro",
        "index": "04",
        "title": "香港电讯市场",
        "kicker": "需求、购买力与服务压力",
        "metric": {"value": lead_connection["value"], "unit": "%", "label": "手机卡/设备同比"},
        "context": "香港官方市场与监管数据",
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
                            "verification_count": item.get("verification_count"),
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


def _reader_percent_units(value: Any) -> Any:
    """Use one compact percent notation throughout the reader-facing board."""
    if isinstance(value, dict):
        return {key: _reader_percent_units(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_reader_percent_units(item) for item in value]
    if isinstance(value, str):
        return value.replace(" 个百分点", "%").replace("个百分点", "%")
    return value


def _reader_facing_copy(value: Any) -> Any:
    """Normalize legacy analysis wording before it reaches the board."""
    if isinstance(value, dict):
        return {key: _reader_facing_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_reader_facing_copy(item) for item in value]
    if isinstance(value, str):
        return value.replace("增长梯队", "增速层次")
    return value


def _requested_international_domain(payload: dict[str, Any]) -> dict[str, Any]:
    """Build strategic-overview domain 02 from the four requested carriers."""
    requested = ("Verizon", "Deutsche Telekom", "AT&T", "NTT Group")
    rows = [
        row for row in (payload.get("rows") or [])
        if row.get("operator") in requested
        and row.get("verification_status") == "official_three_distinct_sources_verified"
        and int(row.get("distinct_source_document_count") or 0) >= 3
    ]

    def row_for(operator: str, metric: str, year: int) -> dict[str, Any] | None:
        return next((row for row in rows if row.get("operator") == operator
                     and row.get("metric_key") == metric and int(row.get("year") or 0) == year), None)

    def history(operator: str, metric: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for year in range(2016, 2026):
            row = row_for(operator, metric, year)
            value = _verified_number(row)
            if value is None:
                continue
            result.append({
                "label": f"FY{year}",
                "value": value,
                "verification_count": int((row or {}).get("distinct_source_document_count") or 0),
                "verification_status": str((row or {}).get("verification_status") or ""),
                "source_urls": _row_source_urls(row),
            })
        return result

    def make_item(
        operator: str, metric: str, value: float, unit: str, detail: str, analysis: str,
        *, trend: list[dict[str, Any]] | None = None,
        components: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        row = row_for(operator, metric, 2025) or {}
        result = {
            "name": operator, "value": round(value, 2), "unit": unit, "period": "FY2025",
            "detail": detail, "analysis": analysis,
            "components": components or [_component(row.get("metric_zh") or metric, round(value, 2), unit, "FY2025")],
            "component_count": len(components or [None]),
            "source_url": str(row.get("primary_source_url") or ""),
            "verification_count": int(row.get("distinct_source_document_count") or 0),
            "verification_status": str(row.get("verification_status") or ""),
            "source_urls": _row_source_urls(row),
        }
        if trend:
            result["trend"] = trend
        return result

    conversion_reference = _display_reference_data().get("international_2025_conversion") or {}
    native_units = {
        operator: str((conversion_reference.get(operator) or {}).get("native_unit") or "")
        for operator in requested
    }
    usd_per_native = {
        operator: float((conversion_reference.get(operator) or {}).get("usd_billions_per_native_unit") or 0)
        for operator in requested
    }

    def usd_billions(operator: str, value: float) -> float:
        return value * usd_per_native[operator]

    def usd_trend(operator: str, metric: str) -> list[dict[str, Any]]:
        return [
            {**point, "value": round(usd_billions(operator, float(point["value"])), 2)}
            for point in history(operator, metric)
        ]
    revenue_items: list[dict[str, Any]] = []
    ebitda_items: list[dict[str, Any]] = []
    profit_items: list[dict[str, Any]] = []
    postpaid_items: list[dict[str, Any]] = []
    for operator in requested:
        unit = native_units[operator]
        revenue = _verified_number(row_for(operator, "revenue", 2025))
        if revenue is not None:
            revenue_usd = usd_billions(operator, revenue)
            revenue_items.append(make_item(
                operator, "revenue", revenue_usd, "十亿美元",
                f"FY2025约{revenue_usd:.2f}十亿美元 · 原披露{revenue:g} {unit}",
                "金额及十年趋势均按统一汇率折算为十亿美元。",
                trend=usd_trend(operator, "revenue"),
            ))

        ebitda = _verified_number(row_for(operator, "adjusted_ebitda", 2025))
        if ebitda is not None:
            ebitda_usd = usd_billions(operator, ebitda)
            ebitda_items.append(make_item(
                operator, "adjusted_ebitda", ebitda_usd, "十亿美元",
                f"FY2025约{ebitda_usd:.2f}十亿美元 · 原披露{ebitda:g} {unit}",
                "只展示调整后EBITDA绝对值；Deutsche Telekom为EBITDA AL，非GAAP调整项不完全相同。",
                trend=usd_trend(operator, "adjusted_ebitda"),
            ))

        profit = _verified_number(row_for(operator, "net_profit", 2025))
        if profit is not None:
            profit_usd = usd_billions(operator, profit)
            profit_items.append(make_item(
                operator, "net_profit", profit_usd, "十亿美元",
                f"FY2025约{profit_usd:.2f}十亿美元 · 原披露{profit:g} {unit}",
                "按统一汇率折算为十亿美元，原币金额保留在明细中。",
                trend=usd_trend(operator, "net_profit"),
            ))

        subscriber_metric = "mobile_service_subscriptions" if operator == "NTT Group" else "postpaid_connections"
        arpu_metric = {"Verizon": "postpaid_arpa", "NTT Group": "mobile_arpu"}.get(operator, "postpaid_phone_arpu")
        subscribers = _verified_number(row_for(operator, subscriber_metric, 2025))
        arpu = _verified_number(row_for(operator, arpu_metric, 2025))
        if subscribers is None or arpu is None:
            continue
        arpu_usd = arpu * usd_per_native["NTT Group"] if operator == "NTT Group" else arpu
        if operator == "Verizon":
            detail = f"后付费连接 {subscribers:.3f}百万 · ARPA ${arpu_usd:.2f}/账户/月"
            warning = "Verizon披露的是ARPA（每账户），不写成ARPU。"
        elif operator == "NTT Group":
            detail = f"移动电话服务订阅 {subscribers:.3f}百万（替代口径） · 移动ARPU约${arpu_usd:.2f}/用户/月 · 原披露¥{arpu:.0f}"
            warning = "NTT未披露后付费口径；替代值包含MVNO与通信模块合约，不与后付费用户直接等同。"
        else:
            detail = f"后付费用户 {subscribers:.3f}百万 · 后付费手机ARPU ${arpu:.2f}/用户/月"
            warning = ("Deutsche Telekom用户数为T-Mobile US分部后付费总客户，ARPU为后付费手机口径。"
                       if operator == "Deutsche Telekom" else "AT&T用户数为美国Mobility后付费总客户，ARPU为后付费手机口径。")
        postpaid_items.append(make_item(
            operator, subscriber_metric, subscribers, "百万", detail, warning,
            trend=history(operator, subscriber_metric),
                components=[_component("后付费用户数", subscribers, "百万", "FY2025"),
                        _component("ARPU/ARPA", round(arpu_usd, 2), "美元/月", "FY2025")],
        ))

    def leader_metric(items: list[dict[str, Any]]) -> dict[str, Any]:
        leader = max(items, key=lambda item: float(item["value"]))
        return {
            "value": leader["value"],
            "unit": leader["unit"],
            "label": f"{leader['name']} FY2025",
        }

    focuses = [
        {"id": "revenue", "label": "营收", "visual": "rows", "headline": "Verizon资源底盘领先",
         "metric": leader_metric(revenue_items),
         "context": "统一为十亿美元；原币明细保留", "insight": "Verizon为138.19十亿美元、NTT Group为96.34十亿美元；这表明Verizon的跨国经营资源底盘更厚，更能承担网络、渠道与获客投入，但营收不等同盈利能力。", "items": revenue_items},
        {"id": "ebitda", "label": "EBITDA", "visual": "rows", "headline": "美德双强造血",
         "metric": leader_metric(ebitda_items),
         "context": "统一为十亿美元；非GAAP调整项存在公司差异", "insight": "Verizon与Deutsche Telekom均约50.00十亿美元，NTT Group为22.89十亿美元；这表明美德两家的经营造血代理更强，网络投入与价战容错更厚。", "items": ebitda_items},
        {"id": "net_profit", "label": "净利润", "visual": "rows", "headline": "AT&T自我融资最强",
         "metric": leader_metric(profit_items),
         "context": "统一为十亿美元", "insight": "AT&T净利润21.95十亿美元、NTT Group为6.93十亿美元；这表明AT&T当期自我融资、再投资与周期防守空间更厚，但绝对值不等同盈利效率。", "items": profit_items},
        {"id": "postpaid_arpu", "label": "后付费用户数", "visual": "rows", "headline": "Verizon客户经营信号最强",
         "metric": leader_metric(postpaid_items),
         "context": "Verizon为ARPA；NTT为移动电话服务订阅替代口径", "insight": "Verizon 126.70百万连接、ARPA 170.61美元/月；NTT Group 93.06百万手机订阅、ARPU 26.48美元/月。Verizon在自身口径下同时呈现大规模与高账户价值信号；NTT为替代口径，不可混排。", "items": postpaid_items},
    ]
    all_items = revenue_items + ebitda_items + profit_items + postpaid_items
    return {
        "id": "international", "index": "02", "title": "国际运营商",
        "kicker": "营收、EBITDA、净利润与后付费用户价值",
        "metric": {"value": 10, "unit": "年", "label": "FY2016–FY2025财务历史"},
        "context": "Verizon、Deutsche Telekom、AT&T、NTT Group；展示值经三份不同底层官方文件核验",
        "insight": "对比金额统一为十亿美元，ARPU统一为美元/月；Verizon为ARPA，NTT的用户口径已单独标注。",
        "entities": revenue_items, "focuses": focuses,
        "relations": [{"title": item["name"], "detail": "四项指标口径已校准", "kind": "三来源认证"} for item in revenue_items],
        "sources": _dedupe_sources(
            [_source(item["name"], item["source_url"]) for item in all_items]
            + [_source(label, url) for label, url in _fx_sources()]
        ),
    }


def _apply_online_gap_audit(domains: list[dict[str, Any]]) -> dict[str, Any]:
    audit = _read_json_optional(ONLINE_GAP_AUDIT_PATH, {})
    if not isinstance(audit, dict):
        audit = {}
    facts = {
        (str(item.get("domain") or ""), str(item.get("focus") or ""), str(item.get("entity") or "")): item
        for item in (audit.get("verified_public_facts") or [])
        if isinstance(item, dict)
    }
    classifications = {
        (str(item.get("domain") or ""), str(item.get("focus") or ""), str(item.get("entity") or "")): item
        for item in (audit.get("gap_classifications") or [])
        if isinstance(item, dict)
    }
    status_counts: dict[str, int] = {}
    for domain in domains:
        added_sources: list[dict[str, str] | None] = []
        for focus in domain.get("focuses") or []:
            for entity in focus.get("items") or []:
                key = (str(domain.get("id") or ""), str(focus.get("id") or ""), str(entity.get("name") or ""))
                fact = facts.get(key)
                if fact:
                    source_urls = [str(url) for url in (fact.get("source_urls") or []) if str(url).startswith(("http://", "https://"))]
                    value = _number(fact.get("value"))
                    entity.update({
                        "value": value,
                        "unit": str(fact.get("unit") or ""),
                        "period": str(fact.get("period") or entity.get("period") or ""),
                        "detail": (
                            f"{fact.get('period') or ''}{focus.get('label') or ''} · {len(source_urls)}个官方证据入口交叉核验"
                            if len(source_urls) >= 2 else
                            f"{fact.get('period') or ''}{focus.get('label') or ''} · 1个官方披露入口，按要求上屏"
                        ),
                        "analysis": str(fact.get("evidence_note") or ""),
                        "components": [_component(
                            focus.get("label") or entity.get("name"), value, fact.get("unit"), fact.get("period")
                        )],
                        "component_count": 1,
                        "source_url": source_urls[0] if source_urls else "",
                        "source_urls": source_urls,
                        "verification_count": len(source_urls),
                        "verification_status": str(fact.get("verification_status") or ""),
                        "gap_status": "",
                    })
                    for point in entity.get("trend") or []:
                        if point.get("label") == fact.get("period"):
                            point.update({"value": value, "unit": fact.get("unit"), "verification_count": len(source_urls), "source_urls": source_urls})
                    added_sources.extend(_source(f"{entity.get('name')} {focus.get('label')} 官方文件", url) for url in source_urls)
                    continue
                if _number(entity.get("value")) is not None:
                    continue
                classification = classifications.get(key) or {}
                status = str(classification.get("status") or "knowledge_pending")
                label = str(classification.get("display") or "本地库待核验")
                note = str(classification.get("note") or "当前本地知识库未完成同口径核验；不代表互联网未披露。")
                source_urls = [str(url) for url in (classification.get("source_urls") or []) if str(url).startswith(("http://", "https://"))]
                detail = (
                    f"{label} · 官网、年报、业绩公告与业绩演示复核至2026-08-25"
                    if status == "public_not_found"
                    else f"{label} · 不得表述为互联网未披露"
                )
                entity.update({
                    "gap_status": status,
                    "gap_label": label,
                    "detail": detail,
                    "analysis": note,
                    "source_url": source_urls[0] if source_urls else str(entity.get("source_url") or ""),
                    "source_urls": source_urls,
                })
                for component in entity.get("components") or []:
                    if component.get("value") is None:
                        component["detail"] = label
                status_counts[status] = status_counts.get(status, 0) + 1
                added_sources.extend(_source(f"{entity.get('name')} {focus.get('label')} 缺口复核", url) for url in source_urls)
            if domain.get("id") == "cloud" and focus.get("id") == "investment":
                available = [item for item in (focus.get("items") or []) if _number(item.get("value")) is not None]
                if available:
                    leader = max(available, key=lambda item: float(item["value"]))
                    tail = min(available, key=lambda item: float(item["value"]))
                    focus["metric"] = {
                        "value": leader["value"],
                        "unit": leader["unit"],
                        "label": f"{leader['name']} {leader.get('period') or '最新披露期'}集团资本开支",
                    }
                    focus["insight"] = (
                        f"{leader['name']}集团资本开支{leader['value']:g}百万美元、{tail['name']}为{tail['value']:g}百万美元；"
                        f"这表明{leader['name']}的基础设施扩容弹药更足，{tail['name']}的集团投入空间较窄；"
                        "集团投入不等同云业务单独投入，也不能证明投入转化效率。"
                    )
        domain["sources"] = _dedupe_sources(list(domain.get("sources") or []) + added_sources)
    return {
        "audited_at_hkt": str(audit.get("audited_at_hkt") or ""),
        "policy": str(audit.get("policy") or ""),
        "gap_status_counts": status_counts,
        "verified_public_fact_count": len(facts),
    }


@lru_cache(maxsize=4)
def _build_cached(signature: tuple[int, ...]) -> dict[str, Any]:
    del signature
    financial_payload = _read_json(INTERNATIONAL_PATH)
    global_payload = _read_json(GLOBAL_OPERATOR_PATH)
    local = _requested_hong_kong_domain(
        financial_payload, _read_json(LOCAL_OPERATING_PATH), _read_json(LOCAL_OPERATING_SOURCES_PATH),
        _read_json_optional(LOCAL_FINANCIAL_PATH, {}),
    )
    # 第二数据域沿用原有布局，展示合并后的六家国际运营商。
    international = _requested_international_domain(global_payload)
    global_source_registry = {
        str(item.get("source_id") or item.get("id") or ""): str(item.get("url") or "")
        for item in (_read_json(GLOBAL_OPERATOR_SOURCES_PATH).get("sources") or [])
        if isinstance(item, dict)
    }
    mainland = _requested_mainland_domain(
        financial_payload, global_payload, global_source_registry
    )
    cloud = _cloud_domain(_read_json(CLOUD_PATH))
    domains = [local, international, mainland, cloud]
    online_gap_audit = _apply_online_gap_audit(domains)
    ai_payload = _read_json_optional(AI_ANALYSIS_PATH, {})
    ai_domains = ai_payload.get("domains") if isinstance(ai_payload, dict) else {}
    for domain in domains:
        domain["ai_analysis"] = list((ai_domains or {}).get(domain["id"]) or [])
    domains = _reader_percent_units(domains)
    evidence = _analysis_evidence_snapshot(domains)
    evidence_hash = _content_hash(evidence)
    def displayed_fy(domain: dict[str, Any]) -> str:
        years = re.findall(r"FY(20\d{2})", json.dumps(domain, ensure_ascii=False))
        return f"FY{max(years)}" if years else "最新披露期"

    local_period = displayed_fy(local)
    international_period = displayed_fy(international)
    mainland_period = displayed_fy(mainland)
    cloud_period = displayed_fy(cloud)
    model_analysis = ai_payload.get("model_analysis") or {} if isinstance(ai_payload, dict) else {}
    model_analysis_fresh = bool(
        str(model_analysis.get("evidence_hash") or "")
        and str(model_analysis.get("evidence_hash") or "") == evidence_hash
        and str(model_analysis.get("insight_format") or "") == INSIGHT_FORMAT_VERSION
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
    domains = _reader_percent_units(domains)
    deterministic_relations = [
        {
            "from": "mainland",
            "to": "local",
            "title": f"{local_period}香港与内地财务口径分开",
            "detail": f"香港运营商与内地运营商均采用{local_period}/{mainland_period}最新已核验披露，但主体范围及货币不同；后付客户与移动/5G用户也不是同一口径。",
            "kind": "不可直接比较",
        },
        {
            "from": "international",
            "to": "cloud",
            "title": f"{cloud_period}云收入与运营商财务分口径",
            "detail": (
                f"云厂商页面采用{cloud_period}最新已核验云收入与利润绝对值，国际运营商页面采用{international_period}财务及用户价值指标；"
                "业务范围和计量单位不同，不作高低排名。"
            ),
            "kind": "不可直接比较",
        },
        {
            "from": "local",
            "to": "cloud",
            "title": f"{local_period}香港财务与云收入边界不同",
            "detail": f"香港运营商使用{local_period}公司财务及后付口径；云厂商使用{cloud_period}云业务或代理分部收入与利润，集团CAPEX另取各公司最新已披露期，不能混合排名。",
            "kind": "数据边界",
        },
        {
            "from": "mainland",
            "to": "international",
            "title": f"{mainland_period}内地与国际用户口径分开",
            "detail": f"内地页按{mainland_period}披露区分移动用户总数、5G网络用户和5G套餐客户；国际页采用{international_period}各公司原生连接/订阅及ARPU口径，两者不直接相加或排名。",
            "kind": "数据边界",
        },
    ]
    model_discoveries = [
        item for item in (model_analysis.get("discoveries") or [])
        if isinstance(item, dict)
        and item.get("from") in {"local", "international", "mainland", "cloud"}
        and item.get("to") in {"local", "international", "mainland", "cloud"}
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
    relations = _reader_facing_copy(_reader_percent_units(relations))
    refresh_state = _read_json_optional(REFRESH_STATE_PATH, {})
    ui_domain_ids = [str(domain.get("id") or "") for domain in domains]
    summary_domain_ids = [
        str(item.get("domain") or "")
        for item in (model_analysis.get("summaries") or [])
        if isinstance(item, dict)
    ]
    focus_count = sum(len(domain.get("focuses") or []) for domain in domains)
    summarized_focus_count = sum(
        len(item.get("focuses") or [])
        for item in (model_analysis.get("summaries") or [])
        if isinstance(item, dict)
    )
    ui_contract = {
        "domain_ids": ui_domain_ids,
        "summary_domain_ids": summary_domain_ids,
        "focuses_expected": focus_count,
        "focuses_summarized": summarized_focus_count,
        "model_analysis_fresh": model_analysis_fresh,
        "aligned": bool(
            model_analysis_fresh
            and summary_domain_ids == ui_domain_ids
            and summarized_focus_count == focus_count
            and len(model_discoveries) >= 4
        ),
        "last_checked_at_hkt": (
            str(refresh_state.get("completed_at_hkt") or refresh_state.get("started_at_hkt") or "")
            if isinstance(refresh_state, dict) else ""
        ),
    }
    return {
        "domains": domains,
        "relations": relations,
        "method": "页面数值只从本地知识库取用；本地库待核验不等于互联网未披露，只有完成官网、年报、业绩公告与业绩演示复核的空值才标记为未见公开披露。",
        "data_audit": online_gap_audit,
        "refresh": refresh_state if isinstance(refresh_state, dict) else {},
        "ui_contract": ui_contract,
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

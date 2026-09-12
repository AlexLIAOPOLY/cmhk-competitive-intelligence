"""Server-side Feishu subscriptions and controlled delivery for CMHK content."""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from cmhk.services.news_text import simplified_news_text
from cmhk.services.news_topics import normalize_news_topics, topic_score
from cmhk.integrations.feishu_runtime import lark_cli_env, portable_lark_argv
from cmhk.integrations.feishu_card_text import without_markdown_bold_markers
from cmhk.reporting.weekly_quality import weekly_text_has_navigation_noise


HKT_OFFSET = "+08:00"
HKT = ZoneInfo("Asia/Hong_Kong")
SERVICE_LABELS = {
    "weekly": "战略双周报",
    "performance": "运营商业绩摘要",
    "news": "战略新闻",
}
VALID_SERVICES = frozenset(SERVICE_LABELS)
VALID_DELIVERY_MODES = frozenset({"text", "audio", "both", "pdf", "pdf_audio"})
FREQUENCY_LABELS = {
    "twice_daily": "每天两次",
    "once_daily": "每天一次（上午）",
}
VALID_FREQUENCIES = frozenset(FREQUENCY_LABELS)
VALID_NEWS_ITEM_LIMITS = frozenset({5, 10, 15, 20})
NEWS_REGION_LABELS = {"hong_kong": "香港本地新闻优先", "international": "国际新闻优先"}
NEWS_CATEGORY_LABELS = {
    "公司动态": "公司动态",
    "竞对动态": "竞对动态",
    "政策监管": "政策监管",
    "行业动态": "行业动态",
    "市场/产品类": "市场与产品",
    "基础设施/网络/技术类": "网络与技术",
    "宏观经济&国际形势&地缘政治&其他国际性质关注词汇": "宏观与国际",
}
VALID_NEWS_CATEGORIES = frozenset(NEWS_CATEGORY_LABELS)
NEWS_CATEGORIES_PER_PUSH = 4
DEFAULT_NEWS_CATEGORIES = ("公司动态", "竞对动态", "政策监管", "市场/产品类")
LEGACY_FREQUENCY_MAP = {
    "immediate": "twice_daily",
    "daily": "once_daily",
    "weekly": "once_daily",
}
REPORT_MODE_LABELS = {
    "pdf": "仅 PDF",
    "pdf_audio": "PDF + 单独语音",
    "audio": "仅语音",
}
VALID_REPORT_MODES = frozenset(REPORT_MODE_LABELS)
REPORT_CADENCE_LABEL = "按后台月度排期自动生成并推送"
REPORT_SCHEDULE_DEFAULT_DAYS = (15, 30)
REPORT_SCHEDULE_DEFAULT_TIME = "09:00"
WEEKLY_DELIVERY_MIN_ITEMS = 4
WEEKLY_DELIVERY_MIN_DETAIL_CHARS = 90
WEEKLY_DELIVERY_MIN_DETAIL_SENTENCES = 2
STRATEGIC_SCAN_TIMES_DEFAULT = ("03:00", "14:00")
NEWS_DELIVERY_TIMES_DEFAULT = ("08:00", "18:30")
OPEN_ID_RE = re.compile(r"^ou_[A-Za-z0-9]+$")
CHAT_ID_RE = re.compile(r"^oc_[A-Za-z0-9]+$")
MESSAGE_ID_RE = re.compile(r"^om_[A-Za-z0-9]+$")
IMAGE_KEY_RE = re.compile(r"^img_[A-Za-z0-9_-]+$")
NEWS_DIGEST_PREFIX = "CMHK_NEWS_DIGEST_V1\n"
NEWS_CRAWL_REF_PREFIX = "strategic-crawl:"


def _now_hkt() -> str:
    return datetime.now(HKT).isoformat(timespec="seconds")


def _normalize_news_frequency(value: str) -> str:
    raw = str(value or "").strip()
    return LEGACY_FREQUENCY_MAP.get(raw, raw)


def _news_sort_timestamp(item: dict[str, Any]) -> float:
    raw = str(item.get("published_at") or item.get("source_date") or item.get("search_date") or "").strip()
    if not raw:
        return float("-inf")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return float("-inf")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=HKT)
    return parsed.timestamp()


def _news_identity_keys(item: dict[str, Any]) -> set[str]:
    from cmhk.services.news_delivery_dedupe import identity_keys
    return identity_keys(item)


def _news_primary_key(item: dict[str, Any]) -> str:
    keys = _news_identity_keys(item)
    for prefix in ("url:", "id:", "title:"):
        match = next((key for key in sorted(keys) if key.startswith(prefix)), "")
        if match:
            return match
    return "payload:" + hashlib.sha256(
        json.dumps(item, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def _deduplicate_news_items(
    items: list[dict[str, Any]],
    *,
    excluded_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    seen = set(excluded_keys or ())
    unique: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        keys = _news_identity_keys(item)
        duplicate = bool(keys & seen)
        seen.update(keys)
        if duplicate:
            continue
        unique.append(item)
    return unique


def _decode_strategic_news_digest(body: Any) -> list[dict[str, Any]]:
    text = str(body or "")
    if not text.startswith(NEWS_DIGEST_PREFIX):
        return []
    try:
        payload = json.loads(text[len(NEWS_DIGEST_PREFIX):])
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if isinstance(payload, dict):
        payload = payload.get("items") or []
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def normalize_news_categories(value: Any, *, default_all: bool = True) -> list[str]:
    """Normalize persisted/Card 2 category values in the canonical display order."""
    raw = value
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("["):
            try:
                raw = json.loads(text)
            except (ValueError, TypeError, json.JSONDecodeError):
                raw = []
        else:
            raw = [item.strip() for item in text.split(",") if item.strip()]
    if not isinstance(raw, (list, tuple, set)):
        raw = []
    selected = {str(item).strip() for item in raw if str(item).strip() in VALID_NEWS_CATEGORIES}
    if not selected and default_all:
        selected = set(VALID_NEWS_CATEGORIES)
    return [category for category in NEWS_CATEGORY_LABELS if category in selected]


def _news_categories_for_push(categories: list[str], *, seed: str = "") -> list[str]:
    """Draw per delivery, leaving the complete saved preferences intact."""
    if len(categories) <= NEWS_CATEGORIES_PER_PUSH:
        return list(categories)
    selected = (random.Random(seed) if seed else random).sample(categories, NEWS_CATEGORIES_PER_PUSH)
    return [category for category in NEWS_CATEGORY_LABELS if category in selected]


def filter_news_by_categories(
    items: list[dict[str, Any]],
    categories: Any,
    *,
    limit: int | None = None,
    selection_seed: str = "",
    region_preference: str | None = None,
    topics: Any = None,
) -> list[dict[str, Any]]:
    """Sample at most four subscribed sections; local news leads when sampled.

    The input is the already reviewed news pool. Within each section, prefer
    fresh reporting and avoid repeating an identical URL/title across sections.
    Hong Kong news leads in every section except the explicitly international
    macro section. International news fills any remaining capacity so a local
    shortage does not unnecessarily reduce the personal digest.
    """
    requested = normalize_news_categories(categories)
    selected = set(_news_categories_for_push(requested, seed=selection_seed))
    ordered = sorted((item for item in items if isinstance(item, dict)),
                     key=_news_sort_timestamp, reverse=True)
    seen = set()
    unique = []
    for item in ordered:
        identity = str(item.get("news_id") or item.get("source_url") or item.get("url") or item.get("title") or "").strip()
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        unique.append(item)
    preferred = [item for item in unique if str(item.get("category") or "").strip() in selected]
    if limit is None:
        return preferred
    count = max(0, int(limit))
    buckets: dict[str, list[dict[str, Any]]] = {}
    for item in preferred:
        buckets.setdefault(str(item.get("category") or "").strip(), []).append(item)
    # Section order follows its freshest reviewed event, with subscribed
    # competitor news guaranteed the first available slot, not the entire digest.
    section_order = list(buckets)
    if "竞对动态" in section_order:
        section_order.remove("竞对动态")
        section_order.insert(0, "竞对动态")
    # Rank within this delivery's selection; never modify saved preferences.
    section_order = section_order[:NEWS_CATEGORIES_PER_PUSH]
    selected = set(section_order)
    macro_category = "宏观经济&国际形势&地缘政治&其他国际性质关注词汇"
    primary_buckets: dict[str, list[dict[str, Any]]] = {}
    fallback_buckets: dict[str, list[dict[str, Any]]] = {}
    for section in section_order:
        section_items = buckets[section]
        local = [item for item in section_items if str(item.get("region") or "").strip() == "香港本地"]
        international = [item for item in section_items if str(item.get("region") or "").strip() == "国际/行业"]
        unclassified = [
            item for item in section_items
            if str(item.get("region") or "").strip() not in {"香港本地", "国际/行业"}
        ]
        if region_preference in NEWS_REGION_LABELS:
            primary_buckets[section] = local if region_preference == "hong_kong" else international
            fallback_buckets[section] = [*(international if region_preference == "hong_kong" else local), *unclassified]
        elif section == macro_category:
            # This section is intentionally international-facing. Preserve
            # freshness inside each region while allowing international news
            # to lead and occupy more of this section's personal selection.
            primary_buckets[section] = [*international, *local, *unclassified]
            fallback_buckets[section] = []
        else:
            primary_buckets[section] = local
            fallback_buckets[section] = [*international, *unclassified]

    def round_robin(
        active_buckets: dict[str, list[dict[str, Any]]],
        item_limit: int,
    ) -> list[dict[str, Any]]:
        picked: list[dict[str, Any]] = []
        while len(picked) < item_limit and any(active_buckets.values()):
            for section in section_order:
                if active_buckets[section] and len(picked) < item_limit:
                    picked.append(active_buckets[section].pop(0))
        return picked

    chosen = []
    for tier in (primary_buckets, fallback_buckets):
        # Topic priority is real selection behavior, within the saved region
        # and subscribed sections. All candidates still pass normal quality gates.
        focused = {section: sorted([item for item in rows if topic_score(item, topics)],
                                  key=lambda item: topic_score(item, topics), reverse=True)
                   for section, rows in tier.items()}
        remaining = {section: [item for item in rows if not topic_score(item, topics)] for section, rows in tier.items()}
        chosen.extend(round_robin(focused, count - len(chosen)))
        chosen.extend(round_robin(remaining, count - len(chosen)))
    result = []
    for item in chosen[:count]:
        item = {**item, "subscription_preferred": str(item.get("category") or "").strip() in selected}
        item.pop("subscription_topic_score", None)
        if normalize_news_topics(topics):
            item["subscription_topic_score"] = topic_score(item, topics)
        result.append(item)
    return result


PREFERENCE_FIELD_LABELS = {
    "services": "订阅内容",
    "report_mode": "报告接收方式",
    "news_categories": "新闻兴趣板块",
    "news_topics": "优先关注主题",
    "frequency": "新闻推送频率",
    "news_item_limit": "每次新闻条数",
    "news_region_preference": "新闻地域偏好",
    "news_delivery_times": "新闻接收时间",
    "status": "订阅状态",
}


def _preference_snapshot(
    *,
    services: Any,
    report_mode: Any,
    news_categories: Any,
    frequency: Any,
    news_item_limit: Any,
    news_delivery_times: Any,
    status: Any = "active",
    news_region_preference: str = "hong_kong",
    news_topics: Any = None,
) -> dict[str, Any]:
    return {
        "services": sorted(str(item) for item in (services or []) if str(item) in VALID_SERVICES),
        "report_mode": str(report_mode or "pdf"),
        "news_categories": normalize_news_categories(news_categories, default_all=False),
        "news_topics": normalize_news_topics(news_topics),
        "frequency": _normalize_news_frequency(str(frequency or "once_daily")),
        "news_item_limit": int(news_item_limit or 10),
        "news_region_preference": news_region_preference,
        "news_delivery_times": _normalize_news_delivery_times(news_delivery_times),
        "status": str(status or "active"),
    }


def _preference_value_text(field: str, value: Any) -> str:
    if field == "services":
        return "、".join(SERVICE_LABELS.get(str(item), str(item)) for item in (value or [])) or "无"
    if field == "report_mode":
        return REPORT_MODE_LABELS.get(str(value), str(value))
    if field == "news_categories":
        return "、".join(NEWS_CATEGORY_LABELS.get(str(item), str(item)) for item in (value or [])) or "无"
    if field == "news_topics":
        return "、".join(t["name"] for t in normalize_news_topics(value)) or "未额外指定主题"
    if field == "frequency":
        return FREQUENCY_LABELS.get(str(value), str(value))
    if field == "news_region_preference":
        return NEWS_REGION_LABELS.get(str(value), "香港本地新闻优先")
    if field == "news_item_limit":
        return f"{int(value or 0)} 条"
    if field == "news_delivery_times":
        return " / ".join(str(item) for item in (value or [])) or "无"
    if field == "status":
        return {"active": "启用", "paused": "暂停"}.get(str(value), str(value))
    return str(value or "")


def _preference_changes(
    before: dict[str, Any] | None,
    after: dict[str, Any],
) -> list[dict[str, str]]:
    if before is None:
        return []
    changes: list[dict[str, str]] = []
    for field, label in PREFERENCE_FIELD_LABELS.items():
        if before.get(field) == after.get(field):
            continue
        changes.append({
            "field": field,
            "label": label,
            "before": _preference_value_text(field, before.get(field)),
            "after": _preference_value_text(field, after.get(field)),
        })
    return changes


def news_category_summary(categories: Any) -> str:
    normalized = normalize_news_categories(categories)
    if set(normalized) == VALID_NEWS_CATEGORIES:
        return "全部板块"
    return "、".join(NEWS_CATEGORY_LABELS[item] for item in normalized)


def _card_form_scalar(value: Any) -> str:
    """Normalize Card 2.0 single-select values from real callback payloads."""
    if isinstance(value, (list, tuple)):
        return _card_form_scalar(value[0]) if len(value) == 1 else ""
    if isinstance(value, dict):
        return _card_form_scalar(value.get("value"))
    return str(value or "").strip()


def _card_time_scalar(value: Any) -> str:
    match = re.search(r"(?:^|\s)((?:[01]\d|2[0-3]):[0-5]\d)(?:\s|$)", _card_form_scalar(value))
    return match.group(1) if match else ""


def _normalize_strategic_scan_times(value: Any) -> list[str]:
    values = value if isinstance(value, (list, tuple)) else str(value or "").split(",")
    normalized: list[str] = []
    for item in values:
        raw = str(item or "").strip()
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", raw):
            continue
        if raw not in normalized:
            normalized.append(raw)
    return sorted(normalized) or list(STRATEGIC_SCAN_TIMES_DEFAULT)


def _normalize_news_delivery_times(value: Any) -> list[str]:
    values = value
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            values = json.loads(value)
        except (ValueError, TypeError, json.JSONDecodeError):
            values = []
    if not isinstance(values, (list, tuple)):
        values = str(value or "").split(",")
    normalized: list[str] = []
    for item in values:
        raw = str(item or "").strip()
        if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", raw) and raw not in normalized:
            normalized.append(raw)
    normalized.sort()
    if len(normalized) != 2:
        return list(NEWS_DELIVERY_TIMES_DEFAULT)
    morning = normalized[0] if "08:00" <= normalized[0] < "12:00" else NEWS_DELIVERY_TIMES_DEFAULT[0]
    return [morning, max(normalized[1], "14:00")]


def _validated_news_delivery_times(value: Any) -> list[str]:
    values = value
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            values = json.loads(value)
        except (ValueError, TypeError, json.JSONDecodeError):
            values = []
    if not isinstance(values, (list, tuple)):
        values = str(value or "").split(",")
    raw_values = [str(item or "").strip() for item in values]
    if (
        len(raw_values) != 2
        or any(not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", item) for item in raw_values)
        or len(set(raw_values)) != 2
    ):
        raise ValueError("每日个人推送时间必须是两个不同的有效时间")
    return sorted(raw_values)


def _news_delivery_due_at(*, crawl_date: str, delivery_time: str, completed_at: str) -> str:
    scheduled = datetime.fromisoformat(f"{crawl_date}T{delivery_time}:00").replace(tzinfo=HKT)
    try:
        completed = datetime.fromisoformat(str(completed_at or "").replace("Z", "+00:00"))
        if completed.tzinfo is None:
            completed = completed.replace(tzinfo=HKT)
        completed = completed.astimezone(HKT)
    except ValueError:
        completed = datetime.now(HKT)
    return max(scheduled, completed).isoformat(timespec="seconds")


def _command_env(environ: dict[str, str] | None = None) -> dict[str, str]:
    return lark_cli_env(environ)


def _json_payload(process: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "飞书命令执行失败").strip()[-1200:]
        raise RuntimeError(detail)
    raw = (process.stdout or "").strip()
    payload = json.loads(raw or "{}")
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise RuntimeError(str(payload.get("error") or "飞书返回格式异常"))
    return payload


def _report_schedule_card_line(label: str, schedule: dict[str, Any] | None) -> str:
    current = schedule or {
        "enabled": False,
        "days_text": "、".join(str(day) for day in REPORT_SCHEDULE_DEFAULT_DAYS) + " 日",
        "time": REPORT_SCHEDULE_DEFAULT_TIME,
    }
    state = "" if current.get("enabled") else "（已暂停）"
    return f"**{label}：**每月 {current.get('days_text') or '未设置'} {current.get('time') or '未设置'}（香港时间）{state}"


def subscription_entry_card(
    *,
    image_key: str = "",
    recipient_name: str = "",
    report_schedule: dict[str, Any] | None = None,
    performance_schedule: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Card 2.0 form used as the colleague-facing self-service entry point."""
    salutation = f"尊敬的 {recipient_name.strip()}，您好！" if recipient_name.strip() else "您好！"
    introduction = (
        f"{salutation}我是战略竞对中心管家小竞。"
        "为帮助战略部宣传和推广战略情报产品，您可以按需选择战略双周报、运营商业绩摘要或战略新闻，"
        "报告按后台设定的月度排期自动生成并推送；战略新闻爬虫每日香港时间 03:00 和 14:00 执行，"
        "个人默认在 08:00 和 18:30 推送，但只有对应爬虫完成审核后才会发送。"
        "感谢您的配合！"
    )
    return {
        "schema": "2.0",
        "config": {
            # Feishu rejects interactive cards sent to a group when
            # update_multi is false (300302). The shared card itself is not
            # mutated after submission; each click is still persisted by the
            # callback operator_id and acknowledged in that user's DM.
            "update_multi": True,
            "width_mode": "default",
            "summary": {"content": "订阅战略情报 · 新闻每日 03:00 / 14:00 扫描"},
        },
        "header": {
            "title": {"tag": "plain_text", "content": "订阅战略情报"},
            "template": "wathet",
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 16px 12px",
            "vertical_spacing": "8px",
            "elements": [
                *(
                    [
                        {
                            "tag": "img",
                            "img_key": image_key,
                            "alt": {"tag": "plain_text", "content": "战略情报订阅"},
                            "scale_type": "fit_horizontal",
                            "corner_radius": "8px",
                            "preview": False,
                            "margin": "0px 0px 4px 0px",
                        }
                    ]
                    if IMAGE_KEY_RE.fullmatch(image_key)
                    else []
                ),
                {
                    "tag": "markdown",
                    "content": introduction,
                },
                {
                    "tag": "form",
                    "name": "subscriptionForm",
                    "direction": "vertical",
                    "vertical_spacing": "8px",
                    "elements": [
                        {"tag": "markdown", "content": "**01 · 选择订阅内容**"},
                        {
                            "tag": "multi_select_static",
                            "name": "services",
                            "required": True,
                            "width": "fill",
                            "placeholder": {"tag": "plain_text", "content": "选择一项或多项"},
                            "options": [
                                {"text": {"tag": "plain_text", "content": "战略双周报"}, "value": "weekly"},
                                {"text": {"tag": "plain_text", "content": "运营商业绩摘要"}, "value": "performance"},
                                {"text": {"tag": "plain_text", "content": "战略新闻"}, "value": "news"},
                            ],
                        },
                        {"tag": "hr"},
                        {"tag": "markdown", "content": "**02 · 报告设置**\n<font color='grey'>适用于战略双周报和运营商业绩摘要。</font>"},
                        {
                            "tag": "markdown",
                            "content": "**定期推送日期（后台设置）**\n"
                            + _report_schedule_card_line("战略双周报", report_schedule)
                            + "\n"
                            + _report_schedule_card_line("运营商业绩摘要", performance_schedule),
                        },
                        {"tag": "markdown", "content": "**报告接收方式**"},
                        {
                            "tag": "select_static",
                            "name": "report_mode",
                            "required": False,
                            "width": "fill",
                            "placeholder": {"tag": "plain_text", "content": "选择接收方式"},
                            "options": [
                                {"text": {"tag": "plain_text", "content": "仅 PDF"}, "value": "pdf"},
                                {"text": {"tag": "plain_text", "content": "PDF + 单独语音"}, "value": "pdf_audio"},
                                {"text": {"tag": "plain_text", "content": "仅语音"}, "value": "audio"},
                            ],
                        },
                        {"tag": "hr"},
                        {"tag": "markdown", "content": "**03 · 战略新闻设置**\n<font color='grey'>仅订阅战略新闻时生效；以下选项不影响报告推送。</font>"},
                        {"tag": "markdown", "content": "**感兴趣的战略新闻板块（可多选）**"},
                        {
                            "tag": "multi_select_static",
                            "name": "news_categories",
                            "required": False,
                            "width": "fill",
                            "placeholder": {"tag": "plain_text", "content": "请选择感兴趣的板块，可全部选择"},
                            "options": [
                                {"text": {"tag": "plain_text", "content": label}, "value": category}
                                for category, label in NEWS_CATEGORY_LABELS.items()
                            ],
                        },
                        {"tag": "markdown", "content": "<font color='grey'>所选板块全部保存。每次从有新内容的已选板块中挑选最多4个，优先近期较少推送的板块；竞对动态入选后优先展示。只选今天或昨天发布的新闻，排除近期已发内容，按设置条数持续补选；确实无足够合格新闻时显示缺额原因。按你选择的地域偏好优先推荐，优先地域不足时用另一地域的合格新闻补足。缺少已审核新闻时可能少于4个板块。未选则使用默认4个。</font>", "text_size": "notation"},
                        {"tag": "markdown", "content": "**战略新闻频率**\n<font color='grey'>选择每天一次时，只在上午推送，并使用下方第一次时间。</font>"},
                        {
                            "tag": "select_static",
                            "name": "news_frequency",
                            "required": False,
                            "width": "fill",
                            "placeholder": {"tag": "plain_text", "content": "选择战略新闻频率"},
                            "options": [
                                {"text": {"tag": "plain_text", "content": "每天两次"}, "value": "twice_daily"},
                                {"text": {"tag": "plain_text", "content": "每天一次（上午）"}, "value": "once_daily"},
                            ],
                        },
                        {"tag": "markdown", "content": "**新闻地域偏好**"},
                        {"tag": "select_static", "name": "news_region_preference", "width": "fill",
                         "initial_option": "hong_kong", "required": False,
                         "options": [{"text": {"tag": "plain_text", "content": label}, "value": key}
                                     for key, label in NEWS_REGION_LABELS.items()]},
                        {"tag": "markdown", "content": "**每次战略新闻条数**"},
                        {
                            "tag": "select_static",
                            "name": "news_item_limit",
                            "required": False,
                            "width": "fill",
                            "placeholder": {"tag": "plain_text", "content": "选择每次接收条数"},
                            "options": [
                                {"text": {"tag": "plain_text", "content": f"精选 {count} 条"}, "value": str(count)}
                                for count in sorted(VALID_NEWS_ITEM_LIMITS)
                            ],
                        },
                        {"tag": "markdown", "content": "**期待收到战略新闻的时间（香港）**\n早间早于08:00、下午早于14:00将自动调整到下限；无效时间使用08:00 / 18:30，成功消息会说明调整结果。"},
                        {"tag": "markdown", "content": "第一次：上午08:00至11:59（每天一次使用此时间）"},
                        {
                            "tag": "picker_time",
                            "name": "news_delivery_time_morning",
                            "required": False,
                            "width": "fill",
                            "initial_time": NEWS_DELIVERY_TIMES_DEFAULT[0],
                        },
                        {"tag": "markdown", "content": "第二次：不早于14:00（仅每天两次使用）"},
                        {
                            "tag": "picker_time",
                            "name": "news_delivery_time_afternoon",
                            "required": False,
                            "width": "fill",
                            "initial_time": NEWS_DELIVERY_TIMES_DEFAULT[1],
                        },
                        {
                            "tag": "markdown",
                            "content": "<font color='grey'>每天一次默认上午08:00推送，可选上午时间；每天两次使用早、下午两个时间。</font>",
                            "text_size": "notation",
                        },
                        {"tag": "hr"},
                        {
                            "tag": "button",
                            "name": "saveSubscriptions",
                            "text": {"tag": "plain_text", "content": "确认订阅"},
                            "type": "primary_filled",
                            "width": "fill",
                            "form_action_type": "submit",
                        },
                    ],
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "暂停全部订阅"},
                    "type": "text",
                    "size": "small",
                    "confirm": {
                        "title": {"tag": "plain_text", "content": "暂停全部订阅？"},
                        "text": {"tag": "plain_text", "content": "之后仍可重新选择并恢复。"},
                    },
                    "behaviors": [
                        {"type": "callback", "value": {"action": "cmhk_subscription_pause_all_v1"}}
                    ],
                },
            ],
        },
    }


def subscription_confirmation_card(
    *,
    image_key: str = "",
    is_preference_update: bool = False,
    display_name: str,
    service_labels: str,
    report_mode_label: str,
    frequency_label: str,
    category_labels: str,
    news_item_limit: int,
    news_region_preference: str = "hong_kong",
    news_delivery_times: Any = None,
    adjustments: list[str] | None = None,
) -> dict[str, Any]:
    """Compact Card 2.0 receipt sent after a subscription is saved."""
    name = re.sub(r"\s+", " ", str(display_name or "").strip())[:80] or "您好"
    services = str(service_labels or "-").strip()[:180] or "-"
    report_mode = str(report_mode_label or "-").strip()[:80] or "-"
    frequency = str(frequency_label or "-").strip()[:80] or "-"
    categories = str(category_labels or "-").strip()[:300] or "-"
    try:
        item_limit = int(news_item_limit)
    except (TypeError, ValueError):
        item_limit = 10
    delivery_times = _normalize_news_delivery_times(news_delivery_times)
    title = "兴趣偏好已更新" if is_preference_update else "订阅已生效"
    subtitle = "新的战略情报偏好已保存" if is_preference_update else "战略情报偏好已保存"
    tag_text = "已更新" if is_preference_update else "已开启"
    lead = (
        f"**{name}，修改成功**\n后续内容将按以下最新偏好发送给你。"
        if is_preference_update
        else f"**{name}，设置完成**\n后续内容将按以下偏好发送给你。"
    )
    return {
        "schema": "2.0",
        "config": {
            "update_multi": True,
            "width_mode": "default",
            "summary": {"content": f"{title} · {services}"},
            "style": {
                "text_size": {
                    "body": {"default": "normal", "pc": "normal", "mobile": "normal"},
                    "caption": {"default": "notation", "pc": "notation", "mobile": "notation"},
                }
            },
        },
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "subtitle": {"tag": "plain_text", "content": subtitle},
            "template": "green",
            "text_tag_list": [
                {
                    "tag": "text_tag",
                    "text": {"tag": "plain_text", "content": tag_text},
                    "color": "green",
                }
            ],
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 16px 12px",
            "vertical_spacing": "10px",
            "elements": [
                *([{"tag": "markdown", "content": "**已自动调整并保存：**\n" + "\n".join(adjustments)}] if adjustments else []),
                *(
                    [
                        {
                            "tag": "img",
                            "img_key": image_key,
                            "alt": {"tag": "plain_text", "content": "订阅成功庆祝图"},
                            "scale_type": "fit_horizontal",
                            "corner_radius": "8px",
                            "preview": False,
                        }
                    ]
                    if IMAGE_KEY_RE.fullmatch(image_key)
                    else []
                ),
                {
                    "tag": "markdown",
                    "content": lead,
                },
                {
                    "tag": "column_set",
                    "flex_mode": "none",
                    "columns": [
                        {
                            "tag": "column",
                            "width": "weighted",
                            "weight": 1,
                            "background_style": "green-50",
                            "padding": "12px",
                            "vertical_spacing": "10px",
                            "elements": [
                                {"tag": "markdown", "content": f"**订阅内容**\n{services}"},
                                {
                                    "tag": "div",
                                    "fields": [
                                        {
                                            "is_short": True,
                                            "text": {
                                                "tag": "lark_md",
                                                "content": f"**报告形式**\n{report_mode}",
                                            },
                                        },
                                        {
                                            "is_short": True,
                                            "text": {
                                                "tag": "lark_md",
                                                "content": f"**战略新闻**\n{frequency} · 最新 {item_limit} 条\n{NEWS_REGION_LABELS.get(news_region_preference, NEWS_REGION_LABELS['hong_kong'])}",
                                            },
                                        },
                                    ],
                                },
                                {"tag": "markdown", "content": f"**已订阅兴趣板块**\n{categories}"},
                                {"tag": "markdown", "content": "所选板块全部保留；每次从有新内容的已选板块中挑选最多4个，优先近期较少推送的板块。只选今天或昨天发布的新闻，排除近期已发内容，按设置条数持续补选；确实无足够合格新闻时显示缺额原因。按你选择的地域偏好优先推荐，优先地域不足时用另一地域的合格新闻补足。抽中板块缺少已审核新闻时，实际覆盖可能少于4个。"},
                                {"tag": "markdown", "content": f"**期待收到时间（香港）**\n{' / '.join(delivery_times)}"},
                            ],
                        }
                    ],
                },
                {
                    "tag": "markdown",
                    "content": (
                        f"<font color='grey'>报告节奏：{REPORT_CADENCE_LABEL}。"
                        "需要调整时，重新提交订阅卡片即可覆盖当前选择。</font>"
                    ),
                    "text_size": "notation",
                },
            ],
        },
    }


def encode_strategic_news_digest(items: list[dict[str, Any]]) -> str:
    """Persist a structured digest through the existing text queue column."""
    return NEWS_DIGEST_PREFIX + json.dumps(items, ensure_ascii=False, separators=(",", ":"))


def _news_business_impact(item: dict[str, Any]) -> str:
    explicit = str(item.get("business_impact") or item.get("inclusion_reason") or "").strip()
    if explicit:
        return explicit[:220]
    category = str(item.get("category") or "")
    if category == "竞对动态":
        return "反映相关运营商或企业的经营与技术布局变化，需持续跟踪其对竞争格局的影响。"
    if category == "政策监管":
        return "可能影响合规要求与市场环境，需评估对本地业务和客户需求的传导。"
    if "宏观" in category or "地缘" in category:
        return "反映外部经营环境变化，需关注对投资节奏、客户需求及供应链的潜在影响。"
    return "反映行业技术、投资或商业化方向变化，需关注对网络、算力与产品布局的影响。"


def strategic_news_card(
    *,
    title: str,
    body: str,
    published_at: str = "",
    image_key: str = "",
) -> dict[str, Any]:
    """Build the direct-message card used for personal strategic-news subscriptions."""
    clean_title = re.sub(r"\s+", " ", str(title or "CMHK战略订阅")).strip()[:120] or "CMHK战略订阅"
    elements: list[dict[str, Any]] = []
    if IMAGE_KEY_RE.fullmatch(str(image_key or "")):
        elements.append({
            "tag": "img",
            "img_key": image_key,
            "alt": {"tag": "plain_text", "content": f"{clean_title}配图"},
            "scale_type": "fit_horizontal",
            "preview": False,
        })
    if str(body).startswith(NEWS_DIGEST_PREFIX):
        try:
            parsed = json.loads(str(body)[len(NEWS_DIGEST_PREFIX):])
        except (ValueError, TypeError, json.JSONDecodeError):
            parsed = []
        digest = parsed if isinstance(parsed, dict) else {}
        raw_items = digest.get("items", []) if digest else parsed
        items = [item for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
        if not items:
            elements.append({'tag': 'markdown', 'content': '本轮暂无未向你推送的新事件。'})
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            grouped.setdefault(str(item.get("category") or "战略动态").strip() or "战略动态", []).append(item)
        ordered_categories = [category for category in NEWS_CATEGORY_LABELS if category in grouped]
        ordered_categories.extend(category for category in grouped if category not in NEWS_CATEGORY_LABELS)
        if "竞对动态" in ordered_categories and any(item.get("subscription_preferred", True) for item in grouped["竞对动态"]):
            ordered_categories.remove("竞对动态")
            ordered_categories.insert(0, "竞对动态")
        ordered_categories.sort(key=lambda category: not any(item.get("subscription_preferred", True) for item in grouped[category]))
        colors = {"公司动态": "blue", "竞对动态": "blue", "政策监管": "violet",
                  "行业动态": "blue", "市场/产品类": "purple", "基础设施/网络/技术类": "violet"}
        for group_category in ordered_categories:
            category_items = grouped[group_category]
            category_label = NEWS_CATEGORY_LABELS.get(group_category, group_category)
            color = colors.get(group_category, "purple")
            group_elements = [{"tag": "markdown", "content": f"<font color='{color}'>**{category_label} · {len(category_items)} 条**</font>"}]
            for item_index, item in enumerate(category_items):
                if item_index:
                    group_elements.append({"tag": "hr"})
                item_title = re.sub(r"\s+", " ", simplified_news_text(item.get("title") or "未命名动态")).strip()[:180]
                summary = simplified_news_text(item.get("digest_summary") or item.get("summary")).strip()
                source = simplified_news_text(item.get("source") or "来源待核").strip()[:100]
                published = str(item.get("published_at") or item.get("source_date") or "").strip()
                try:
                    published_text = datetime.fromisoformat(published.replace("Z", "+00:00")).astimezone(HKT).strftime("%m月%d日 %H:%M")
                except ValueError:
                    published_text = published[:16] or "时间待核"
                from cmhk.services.news_delivery_assets import article_url
                import html
                def prose(value):
                    return re.sub(r"([\\*\[\]`])", r"\\\1", html.escape(simplified_news_text(value), quote=False))
                url = article_url(item.get('news_url') or item.get('source_url') or item.get('url'))
                thumbnail = str(item.get('image_key') or '')
                if (thumbnail == image_key or item.get('image_kind') not in ('source', 'related')
                        or not item.get('image_source_url')):
                    thumbnail = ''
                if thumbnail and not IMAGE_KEY_RE.fullmatch(thumbnail):
                    raise ValueError('新闻原图标识无效')
                group_elements.append({
                    'tag': 'interactive_container', 'width': 'fill', 'has_border': False,
                    'padding': '8px 0px',
                    'behaviors': [{'type': 'open_url', 'default_url': url}],
                    'elements': [{'tag': 'column_set', 'flex_mode': 'none', 'horizontal_spacing': '12px',
                        'columns': [
                            {'tag': 'column', 'width': 'weighted', 'weight': 1, 'vertical_spacing': '8px',
                             'elements': [
                                 {'tag': 'markdown', 'text_size': 'heading-3',
                                  'content': f"<font color='blue'>**{prose(item_title)}**</font>"},
                                 {'tag': 'markdown', 'content': prose(summary)},
                                 {'tag': 'markdown', 'text_size': 'notation',
                                  'content': f"<font color='grey'>{prose(source)} · {published_text}</font>"},
                             ]},
                            {'tag': 'column', 'width': '80px', 'vertical_align': 'top', 'elements': [
                                {'tag': 'img', 'img_key': thumbnail,
                                 'alt': {'tag': 'plain_text', 'content': item_title},
                                 'scale_type': 'crop_center', 'size': '80px 80px',
                                 'corner_radius': '4px', 'preview': False},
                            ]},
                        ]}],
                })
                if not thumbnail:
                    group_elements[-1]['elements'][0]['columns'].pop()
            elements.append({"tag": "column_set", "flex_mode": "none", "columns": [{
                "tag": "column", "width": "weighted", "weight": 1,
                "background_style": f"{color}-50", "padding": "12px", "vertical_spacing": "8px",
                "elements": group_elements,
            }]})
    else:
        clean_body = str(body or "").strip()
        if len(clean_body) > 12000:
            clean_body = clean_body[:11997].rstrip() + "…"
        elements.append({"tag": "markdown", "content": clean_body})
    elements.extend([
        {"tag": "hr"},
        {"tag": "column_set", "flex_mode": "none", "columns": [
            {"tag": "column", "width": "weighted", "weight": 1, "elements": [
                {"tag": "button", "type": "default", "size": "small", "width": "fill",
                 "text": {"tag": "plain_text", "content": label},
                 "behaviors": [{"type": "callback", "value": {"action": action}}]}
            ]} for label, action in [
                ("修改兴趣偏好", "cmhk_news_preferences_v1"),
                ("取消订阅", "cmhk_news_unsubscribe_v1"),
            ]
        ]},
    ])
    return {
        "schema": "2.0",
        "config": {"width_mode": "default", "enable_forward": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": clean_title},
        },
        "body": {"direction": "vertical", "padding": "12px", "vertical_spacing": "12px", "elements": elements},
    }


class SubscriptionService:
    def __init__(
        self,
        *,
        runtime_root: Path | str,
        config_path: Path | str | None = None,
        db_path: Path | str | None = None,
        environ: dict[str, str] | None = None,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.runtime_root = Path(runtime_root)
        self.config_path = Path(config_path or (self.runtime_root / "config" / "project_monitor.json"))
        self.db_path = Path(db_path or (self.runtime_root / "var" / "subscriptions" / "subscriptions.sqlite3"))
        self.environ = dict(environ or os.environ)
        self.command_runner = command_runner
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @property
    def config(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            payload = {}
        return payload if isinstance(payload, dict) else {}

    @property
    def entry_profile(self) -> str:
        subscriptions = self.config.get("subscriptions") if isinstance(self.config.get("subscriptions"), dict) else {}
        bot = self.config.get("bot") if isinstance(self.config.get("bot"), dict) else {}
        return str(
            self.environ.get("CMHK_FEISHU_ENTRY_PROFILE")
            or subscriptions.get("entry_profile")
            or bot.get("profile")
            or ""
        )

    @property
    def delivery_profile(self) -> str:
        subscriptions = self.config.get("subscriptions") if isinstance(self.config.get("subscriptions"), dict) else {}
        return str(
            self.environ.get("CMHK_FEISHU_DELIVERY_PROFILE")
            or subscriptions.get("delivery_profile")
            or self.entry_profile
        )

    @property
    def primary_delivery_open_id(self) -> str:
        subscriptions = self.config.get("subscriptions") if isinstance(self.config.get("subscriptions"), dict) else {}
        return str(subscriptions.get("primary_delivery_open_id") or "")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=20)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as db, db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS news_control_cards (
                    message_id TEXT PRIMARY KEY, chat_id TEXT NOT NULL,
                    open_id TEXT NOT NULL, profile TEXT NOT NULL, purpose TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS subscribers (
                    open_id TEXT PRIMARY KEY,
                    callback_open_id TEXT NOT NULL DEFAULT '',
                    union_id TEXT NOT NULL DEFAULT '',
                    display_name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    frequency TEXT NOT NULL DEFAULT 'immediate',
                    report_mode TEXT NOT NULL DEFAULT 'pdf',
                    news_item_limit INTEGER NOT NULL DEFAULT 10,
                    news_categories TEXT NOT NULL DEFAULT '[]',
                    news_delivery_times TEXT NOT NULL DEFAULT '["08:00","18:30"]',
                    source_chat_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS subscriptions (
                    open_id TEXT NOT NULL REFERENCES subscribers(open_id) ON DELETE CASCADE,
                    service TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (open_id, service)
                );
                CREATE TABLE IF NOT EXISTS deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id TEXT NOT NULL,
                    open_id TEXT NOT NULL,
                    service TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    content_ref TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    message_ids TEXT NOT NULL DEFAULT '[]',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS deliveries_batch_idx ON deliveries(batch_id);
                CREATE TABLE IF NOT EXISTS subscription_entry_cards (
                    message_id TEXT PRIMARY KEY,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    target_name TEXT NOT NULL DEFAULT '',
                    chat_id TEXT NOT NULL,
                    source_profile TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS subscription_group_responses (
                    message_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    callback_open_id TEXT NOT NULL,
                    delivery_open_id TEXT NOT NULL,
                    union_id TEXT NOT NULL DEFAULT '',
                    display_name TEXT NOT NULL,
                    avatar_url TEXT NOT NULL DEFAULT '',
                    source_profile TEXT NOT NULL DEFAULT '',
                    department_names TEXT NOT NULL DEFAULT '[]',
                    job_title TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    last_error TEXT NOT NULL DEFAULT '',
                    responded_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (message_id, callback_open_id)
                );
                CREATE TABLE IF NOT EXISTS subscription_preference_submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    message_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    callback_open_id TEXT NOT NULL,
                    delivery_open_id TEXT NOT NULL,
                    union_id TEXT NOT NULL DEFAULT '',
                    display_name TEXT NOT NULL,
                    preferences TEXT NOT NULL,
                    changes TEXT NOT NULL DEFAULT '[]',
                    is_initial INTEGER NOT NULL DEFAULT 0,
                    submitted_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS subscription_preference_submissions_person_idx
                    ON subscription_preference_submissions(delivery_open_id, submitted_at DESC);
                CREATE TABLE IF NOT EXISTS subscription_invite_candidates (
                    callback_open_id TEXT PRIMARY KEY,
                    delivery_open_id TEXT NOT NULL,
                    union_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    source_profile TEXT NOT NULL DEFAULT '',
                    avatar_url TEXT NOT NULL DEFAULT '',
                    department_names TEXT NOT NULL DEFAULT '[]',
                    job_title TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'admin_resolved',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS subscription_invitations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    callback_open_id TEXT NOT NULL,
                    delivery_open_id TEXT NOT NULL,
                    union_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    source_profile TEXT NOT NULL DEFAULT '',
                    avatar_url TEXT NOT NULL DEFAULT '',
                    message_id TEXT NOT NULL UNIQUE,
                    chat_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    invited_by TEXT NOT NULL DEFAULT 'local_admin',
                    sent_at TEXT NOT NULL,
                    responded_at TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS subscription_directory_people (
                    directory_open_id TEXT PRIMARY KEY,
                    union_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    en_name TEXT NOT NULL DEFAULT '',
                    enterprise_email TEXT NOT NULL DEFAULT '',
                    avatar_url TEXT NOT NULL DEFAULT '',
                    job_title TEXT NOT NULL DEFAULT '',
                    department_names TEXT NOT NULL DEFAULT '[]',
                    source_profile TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    synced_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS subscription_directory_people_name_idx
                    ON subscription_directory_people(display_name);
                CREATE INDEX IF NOT EXISTS subscription_invitations_target_idx
                    ON subscription_invitations(callback_open_id, sent_at DESC);
                CREATE TABLE IF NOT EXISTS pending_subscription_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    delivery_id INTEGER NOT NULL REFERENCES deliveries(id) ON DELETE CASCADE,
                    open_id TEXT NOT NULL,
                    service TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    content_ref TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    body TEXT NOT NULL DEFAULT '',
                    frequency TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    dispatched_at TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS pending_subscription_due_idx
                    ON pending_subscription_deliveries(status, due_at);
                CREATE TABLE IF NOT EXISTS news_crawl_dispatches (
                    open_id TEXT NOT NULL,
                    dispatch_key TEXT NOT NULL,
                    crawl_slot TEXT NOT NULL,
                    crawl_date TEXT NOT NULL,
                    frequency TEXT NOT NULL,
                    delivery_id INTEGER,
                    status TEXT NOT NULL DEFAULT 'sending',
                    message_ids TEXT NOT NULL DEFAULT '[]',
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (open_id, dispatch_key)
                );
                CREATE INDEX IF NOT EXISTS news_crawl_dispatches_slot_idx
                    ON news_crawl_dispatches(crawl_slot, status);
                CREATE TABLE IF NOT EXISTS news_crawl_item_pool (
                    crawl_slot TEXT NOT NULL,
                    crawl_date TEXT NOT NULL,
                    delivery_window TEXT NOT NULL,
                    item_key TEXT NOT NULL,
                    item_json TEXT NOT NULL,
                    sort_timestamp REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (crawl_slot, item_key)
                );
                CREATE INDEX IF NOT EXISTS news_crawl_item_pool_date_idx
                    ON news_crawl_item_pool(crawl_date, delivery_window, sort_timestamp DESC);
                CREATE TABLE IF NOT EXISTS news_delivery_receipts (
                    open_id TEXT NOT NULL, batch_id TEXT NOT NULL,
                    logical_day TEXT NOT NULL, send_day TEXT NOT NULL,
                    items_json TEXT NOT NULL, card_json TEXT NOT NULL, audit_json TEXT NOT NULL,
                    status TEXT NOT NULL, message_id TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
                    PRIMARY KEY(open_id, batch_id)
                );
                CREATE INDEX IF NOT EXISTS news_delivery_receipts_day_idx
                    ON news_delivery_receipts(open_id, send_day, logical_day);
                CREATE TABLE IF NOT EXISTS news_recipient_item_history (
                    open_id TEXT NOT NULL,
                    crawl_date TEXT NOT NULL,
                    item_key TEXT NOT NULL,
                    dispatch_key TEXT NOT NULL,
                    crawl_slot TEXT NOT NULL,
                    delivery_id INTEGER NOT NULL REFERENCES deliveries(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (open_id, crawl_date, item_key)
                );
                CREATE INDEX IF NOT EXISTS news_recipient_item_history_dispatch_idx
                    ON news_recipient_item_history(open_id, dispatch_key);
                CREATE TABLE IF NOT EXISTS report_automation_schedule (
                    service TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    days_json TEXT NOT NULL DEFAULT '[15,30]',
                    time_hm TEXT NOT NULL DEFAULT '09:00',
                    timezone TEXT NOT NULL DEFAULT 'Asia/Hong_Kong',
                    last_slot TEXT NOT NULL DEFAULT '',
                    last_status TEXT NOT NULL DEFAULT 'never',
                    last_report_path TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT '',
                    last_started_at TEXT NOT NULL DEFAULT '',
                    last_completed_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS subscription_admin_preferences (
                    preference_key TEXT PRIMARY KEY,
                    preference_value TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                """
            )
            db.execute(
                """INSERT OR IGNORE INTO report_automation_schedule(
                       service, enabled, days_json, time_hm, timezone, updated_at
                   ) VALUES('weekly', 0, '[15,30]', '09:00', 'Asia/Hong_Kong', ?)""",
                (_now_hkt(),),
            )
            db.execute(
                """INSERT OR IGNORE INTO report_automation_schedule(
                       service, enabled, days_json, time_hm, timezone, updated_at
                   ) VALUES('performance', 0, '[15,30]', '09:00', 'Asia/Hong_Kong', ?)""",
                (_now_hkt(),),
            )
            db.execute(
                """INSERT OR IGNORE INTO report_automation_schedule(
                       service, enabled, days_json, time_hm, timezone, updated_at
                   ) VALUES('news', 0, '[]', '00:00', 'Asia/Hong_Kong', ?)""",
                (_now_hkt(),),
            )
            from cmhk.services.news_round_progress import initialize as initialize_news_rounds
            initialize_news_rounds(db)
            columns = {str(row[1]) for row in db.execute("PRAGMA table_info(subscribers)").fetchall()}
            if "callback_open_id" not in columns:
                db.execute("ALTER TABLE subscribers ADD COLUMN callback_open_id TEXT NOT NULL DEFAULT ''")
            if "union_id" not in columns:
                db.execute("ALTER TABLE subscribers ADD COLUMN union_id TEXT NOT NULL DEFAULT ''")
            if "frequency" not in columns:
                db.execute("ALTER TABLE subscribers ADD COLUMN frequency TEXT NOT NULL DEFAULT 'immediate'")
            if "report_mode" not in columns:
                db.execute("ALTER TABLE subscribers ADD COLUMN report_mode TEXT NOT NULL DEFAULT 'pdf'")
            if "news_topics" not in columns:
                db.execute("ALTER TABLE subscribers ADD COLUMN news_topics TEXT NOT NULL DEFAULT '[]'")
            if "news_region_preference" not in columns:
                db.execute("ALTER TABLE subscribers ADD COLUMN news_region_preference TEXT NOT NULL DEFAULT 'hong_kong'")
            if "news_item_limit" not in columns:
                db.execute("ALTER TABLE subscribers ADD COLUMN news_item_limit INTEGER NOT NULL DEFAULT 10")
            if "news_categories" not in columns:
                db.execute("ALTER TABLE subscribers ADD COLUMN news_categories TEXT NOT NULL DEFAULT '[]'")
            if "original_news_categories" not in columns:
                db.execute("ALTER TABLE subscribers ADD COLUMN original_news_categories TEXT NOT NULL DEFAULT '[]'")
            if "original_news_categories_source" not in columns:
                db.execute("ALTER TABLE subscribers ADD COLUMN original_news_categories_source TEXT NOT NULL DEFAULT ''")
            if "news_delivery_times" not in columns:
                db.execute(
                    "ALTER TABLE subscribers ADD COLUMN news_delivery_times TEXT NOT NULL DEFAULT '[\"08:00\",\"18:30\"]'"
                )
            if "default_preferences" not in columns:
                db.execute("ALTER TABLE subscribers ADD COLUMN default_preferences TEXT NOT NULL DEFAULT '{}'")
            for row in db.execute("SELECT * FROM subscribers WHERE default_preferences='{}'").fetchall():
                services = [r[0] for r in db.execute("SELECT service FROM subscriptions WHERE open_id=? AND active=1", (row["open_id"],))]
                defaults = {key: row[key] for key in ("status", "frequency", "report_mode", "news_item_limit", "news_region_preference")}
                defaults.update(
                    services=services,
                    news_categories=normalize_news_categories(row["news_categories"]),
                    news_topics=normalize_news_topics(row["news_topics"]),
                    news_delivery_times=_normalize_news_delivery_times(row["news_delivery_times"]),
                )
                db.execute("UPDATE subscribers SET default_preferences=? WHERE open_id=?", (json.dumps(defaults, ensure_ascii=False), row["open_id"]))
            for row in db.execute("SELECT open_id, news_delivery_times FROM subscribers").fetchall():
                times_json = json.dumps(
                    _normalize_news_delivery_times(row["news_delivery_times"]),
                    separators=(",", ":"),
                )
                if times_json != str(row["news_delivery_times"] or ""):
                    db.execute(
                        "UPDATE subscribers SET news_delivery_times=? WHERE open_id=?",
                        (times_json, str(row["open_id"])),
                    )
            db.execute(
                "UPDATE subscribers SET news_item_limit=10 WHERE news_item_limit NOT IN (5,10,15,20)"
            )
            db.execute(
                """UPDATE subscribers SET frequency=CASE frequency
                       WHEN 'immediate' THEN 'twice_daily'
                       WHEN 'daily' THEN 'once_daily'
                       WHEN 'weekly' THEN 'once_daily'
                       ELSE frequency END
                   WHERE frequency IN ('immediate', 'daily', 'weekly')"""
            )
            db.execute(
                "UPDATE subscribers SET frequency='once_daily' WHERE frequency NOT IN ('once_daily', 'twice_daily')"
            )
            legacy_pending_ids = [
                int(row[0])
                for row in db.execute(
                    """SELECT delivery_id FROM pending_subscription_deliveries
                       WHERE service='news' AND status='queued'
                         AND frequency NOT IN ('scheduled_after_crawl', 'crawl_retry', 'schedule_retry')"""
                ).fetchall()
            ]
            if legacy_pending_ids:
                placeholders = ",".join("?" for _ in legacy_pending_ids)
                db.execute(
                    f"UPDATE deliveries SET status='superseded', error='已改为战略爬虫完成后推送' WHERE id IN ({placeholders})",
                    legacy_pending_ids,
                )
                db.execute(
                    """UPDATE pending_subscription_deliveries
                       SET status='superseded', last_error='已改为战略爬虫完成后推送'
                       WHERE service='news' AND status='queued'
                         AND frequency NOT IN ('scheduled_after_crawl', 'crawl_retry', 'schedule_retry')"""
                )
            pending_columns = {
                str(row[1])
                for row in db.execute("PRAGMA table_info(pending_subscription_deliveries)").fetchall()
            }
            if "attempts" not in pending_columns:
                db.execute("ALTER TABLE pending_subscription_deliveries ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
            if "last_error" not in pending_columns:
                db.execute("ALTER TABLE pending_subscription_deliveries ADD COLUMN last_error TEXT NOT NULL DEFAULT ''")
            migrations = {
                "subscription_entry_cards": {
                    "source_profile": "TEXT NOT NULL DEFAULT ''",
                    "target_name": "TEXT NOT NULL DEFAULT ''",
                },
                "subscription_invite_candidates": {
                    "source_profile": "TEXT NOT NULL DEFAULT ''",
                    "avatar_url": "TEXT NOT NULL DEFAULT ''",
                    "department_names": "TEXT NOT NULL DEFAULT '[]'",
                    "job_title": "TEXT NOT NULL DEFAULT ''",
                },
                "subscription_invitations": {
                    "source_profile": "TEXT NOT NULL DEFAULT ''",
                    "avatar_url": "TEXT NOT NULL DEFAULT ''",
                },
                "subscription_group_responses": {
                    "union_id": "TEXT NOT NULL DEFAULT ''",
                    "source_profile": "TEXT NOT NULL DEFAULT ''",
                    "department_names": "TEXT NOT NULL DEFAULT '[]'",
                    "job_title": "TEXT NOT NULL DEFAULT ''",
                    "last_error": "TEXT NOT NULL DEFAULT ''",
                },
                "subscription_directory_people": {
                    "enterprise_email": "TEXT NOT NULL DEFAULT ''",
                },
            }
            for table, additions in migrations.items():
                existing = {str(row[1]) for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
                for column, declaration in additions.items():
                    if column not in existing:
                        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
            db.execute(
                """INSERT INTO subscription_group_responses(
                       message_id, chat_id, callback_open_id, delivery_open_id,
                       display_name, avatar_url, status, responded_at, updated_at
                   )
                   SELECT c.message_id, c.chat_id,
                          COALESCE(NULLIF(s.callback_open_id, ''), s.open_id), s.open_id,
                          s.display_name, '',
                          CASE WHEN s.status='paused' THEN 'paused' ELSE 'accepted' END,
                          s.updated_at, s.updated_at
                   FROM subscription_entry_cards c
                   JOIN subscribers s ON s.source_chat_id=c.chat_id AND s.updated_at>=c.created_at
                   WHERE c.target_type='chat'
                   ON CONFLICT(message_id, callback_open_id) DO NOTHING"""
            )

    def _run(self, argv: list[str], *, timeout: float = 45) -> subprocess.CompletedProcess[str]:
        if self.command_runner is not None:
            return self.command_runner(argv, timeout=timeout)
        return subprocess.run(
            portable_lark_argv(argv, self.environ),
            cwd=self.runtime_root,
            env=_command_env(self.environ),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )

    def _lark(self, argv: list[str], *, timeout: float = 45) -> dict[str, Any]:
        return _json_payload(self._run(argv, timeout=timeout))

    @property
    def directory_profile(self) -> str:
        subscriptions = self.config.get("subscriptions") if isinstance(self.config.get("subscriptions"), dict) else {}
        return str(
            self.environ.get("CMHK_FEISHU_DIRECTORY_PROFILE")
            or subscriptions.get("directory_profile")
            or self.delivery_profile
        )

    def resolve_user(self, open_id: str, *, source_profile: str = "") -> dict[str, str]:
        if not OPEN_ID_RE.fullmatch(open_id):
            raise ValueError("无效的飞书 open_id")
        callback_profile = source_profile or self.entry_profile
        payload = self._lark([
            "lark-cli", "contact", "+get-user", "--user-id", open_id,
            "--user-id-type", "open_id", "--as", "bot", "--profile", callback_profile,
            "--format", "json",
        ])
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        user = data.get("user") if isinstance(data.get("user"), dict) else {}
        if str(user.get("open_id") or "") != open_id:
            raise RuntimeError("飞书用户身份回读不一致")
        name = str(user.get("name") or user.get("en_name") or "").strip()[:120]
        if not name:
            raise RuntimeError("飞书用户缺少显示名称")
        union_id = str(user.get("union_id") or "")
        if not union_id.startswith("on_"):
            raise RuntimeError("订阅点击者缺少可跨应用解析的 union_id")
        delivery_payload = self._lark([
            "lark-cli", "contact", "+get-user", "--user-id", union_id,
            "--user-id-type", "union_id", "--as", "bot", "--profile", self.delivery_profile,
            "--format", "json",
        ])
        delivery_data = delivery_payload.get("data") if isinstance(delivery_payload.get("data"), dict) else {}
        delivery_user = delivery_data.get("user") if isinstance(delivery_data.get("user"), dict) else {}
        delivery_open_id = str(delivery_user.get("open_id") or "")
        if not OPEN_ID_RE.fullmatch(delivery_open_id) or str(delivery_user.get("union_id") or "") != union_id:
            raise RuntimeError("组织推送应用无法解析该订阅者，请确认应用可用范围")
        avatar = user.get("avatar") if isinstance(user.get("avatar"), dict) else {}
        return {
            "display_name": name,
            "callback_open_id": open_id,
            "union_id": union_id,
            "open_id": delivery_open_id,
            "source_profile": callback_profile,
            "avatar_url": str(avatar.get("avatar_72") or avatar.get("avatar_240") or ""),
            "job_title": str(user.get("job_title") or "")[:160],
        }

    def save_subscriptions(
        self,
        open_id: str,
        display_name: str,
        services: list[str],
        source_chat_id: str = "",
        callback_open_id: str = "",
        union_id: str = "",
        frequency: str = "once_daily",
        report_mode: str = "pdf",
        news_item_limit: int = 10,
        news_categories: Any = None,
        news_region_preference: str | None = None,
        news_delivery_times: Any = None,
        news_topics: Any = None,
        record_original_categories: bool = True,
        submission_context: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if news_region_preference is not None and news_region_preference not in NEWS_REGION_LABELS:
            raise ValueError("新闻地域偏好必须为香港本地或国际新闻")
        adjustments: list[str] = []
        normalized = sorted({str(item) for item in services if str(item) in VALID_SERVICES})
        if not normalized:
            raise ValueError("至少选择一个订阅服务")
        frequency = _normalize_news_frequency(frequency)
        if frequency not in VALID_FREQUENCIES:
            frequency = "once_daily"
            adjustments.append("未选择有效新闻频率，已按每天一次保存。")
        if report_mode not in VALID_REPORT_MODES:
            report_mode = "pdf"
            adjustments.append("未选择有效报告形式，已按仅PDF保存。")
        try:
            news_item_limit = int(news_item_limit)
        except (TypeError, ValueError):
            news_item_limit = 0
        if news_item_limit not in VALID_NEWS_ITEM_LIMITS:
            news_item_limit = 10
            adjustments.append("未选择有效新闻条数，已按每次10条保存。")
        normalized_categories = normalize_news_categories(
            DEFAULT_NEWS_CATEGORIES if news_categories is None else news_categories, default_all=False)
        if "news" in normalized and not normalized_categories:
            normalized_categories = list(DEFAULT_NEWS_CATEGORIES)
            adjustments.append("未选择有效兴趣板块，已使用默认4个板块。")
        categories_json = json.dumps(normalized_categories, ensure_ascii=False, separators=(",", ":"))
        delivery_times_supplied = news_delivery_times is not None
        normalized_delivery_times = list(NEWS_DELIVERY_TIMES_DEFAULT)
        if delivery_times_supplied:
            raw_times = news_delivery_times if isinstance(news_delivery_times, (list, tuple)) else str(news_delivery_times).split(",")
            for index, (label, minimum) in enumerate((("早间", "08:00"), ("下午", "14:00"))):
                raw = str(raw_times[index] or "").strip() if index < len(raw_times) else ""
                if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", raw):
                    adjustments.append(f"{label}时间无效，已使用{normalized_delivery_times[index]}。")
                else:
                    normalized_delivery_times[index] = max(raw, minimum)
                    if raw < minimum:
                        adjustments.append(f"{label}时间{raw}早于下限，已调整为{minimum}（香港时间）。")
            if normalized_delivery_times[0] >= normalized_delivery_times[1]:
                normalized_delivery_times = list(NEWS_DELIVERY_TIMES_DEFAULT)
                adjustments.append("两次时间顺序不合适，已调整为08:00 / 18:30（香港时间）。")
            elif normalized_delivery_times[0] >= "12:00":
                normalized_delivery_times[0] = NEWS_DELIVERY_TIMES_DEFAULT[0]
                adjustments.append("第一次推送固定使用上午时间，已调整为08:00（香港时间）。")
        delivery_times_json = json.dumps(normalized_delivery_times, separators=(",", ":"))
        now = _now_hkt()
        final_snapshot = _preference_snapshot(
            services=normalized,
            report_mode=report_mode,
            news_categories=normalized_categories,
            frequency=frequency,
            news_item_limit=news_item_limit,
            news_region_preference=news_region_preference,
            news_delivery_times=normalized_delivery_times,
            status="active",
        )
        submission_changes: list[dict[str, str]] = []
        submission_initial = False
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM subscribers WHERE open_id=?",
                (open_id,),
            ).fetchone()
            news_region_preference = news_region_preference or (existing["news_region_preference"] if existing else "hong_kong")
            final_snapshot["news_region_preference"] = news_region_preference
            normalized_topics = normalize_news_topics(news_topics if news_topics is not None else (existing["news_topics"] if existing else []), strict=True)
            final_snapshot["news_topics"] = normalized_topics
            before_snapshot: dict[str, Any] | None = None
            if existing is not None:
                before_services = [
                    str(row[0])
                    for row in db.execute(
                        "SELECT service FROM subscriptions WHERE open_id=? AND active=1 ORDER BY service",
                        (open_id,),
                    ).fetchall()
                ]
                before_snapshot = _preference_snapshot(
                    services=before_services,
                    report_mode=existing["report_mode"],
                    news_categories=existing["news_categories"],
                    frequency=existing["frequency"],
                    news_item_limit=existing["news_item_limit"],
                    news_region_preference=existing["news_region_preference"],
                    news_topics=existing["news_topics"],
                    news_delivery_times=existing["news_delivery_times"],
                    status=existing["status"],
                )
            db.execute(
                """INSERT INTO subscribers(open_id, callback_open_id, union_id, display_name, status, frequency, report_mode, news_item_limit, news_categories, news_delivery_times, source_chat_id, created_at, updated_at)
                   VALUES(?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(open_id) DO UPDATE SET display_name=excluded.display_name,
                   callback_open_id=excluded.callback_open_id, union_id=excluded.union_id,
                   status='active', frequency=excluded.frequency, report_mode=excluded.report_mode,
                   news_item_limit=excluded.news_item_limit, news_categories=excluded.news_categories,
                   news_delivery_times=CASE WHEN ?=1 THEN excluded.news_delivery_times ELSE subscribers.news_delivery_times END,
                   source_chat_id=excluded.source_chat_id,
                   updated_at=excluded.updated_at""",
                (
                    open_id, callback_open_id, union_id, display_name, frequency, report_mode,
                    news_item_limit, categories_json, delivery_times_json, source_chat_id, now, now,
                    int(delivery_times_supplied),
                ),
            )
            db.execute("UPDATE subscribers SET news_region_preference=?, news_topics=? WHERE open_id=?",
                       (news_region_preference, json.dumps(normalized_topics, ensure_ascii=False), open_id))
            if record_original_categories and news_categories is not None:
                db.execute("""UPDATE subscribers SET original_news_categories=?,
                           original_news_categories_source='submitted' WHERE open_id=?""",
                           (json.dumps(normalize_news_categories(news_categories, default_all=False), ensure_ascii=False), open_id))
            for service in VALID_SERVICES:
                db.execute(
                    """INSERT INTO subscriptions(open_id, service, active, updated_at) VALUES(?, ?, ?, ?)
                       ON CONFLICT(open_id, service) DO UPDATE SET active=excluded.active, updated_at=excluded.updated_at""",
                    (open_id, service, int(service in normalized), now),
                )
            if submission_context:
                submission_changes = _preference_changes(before_snapshot, final_snapshot)
                submission_initial = before_snapshot is None
                db.execute(
                    """INSERT OR IGNORE INTO subscription_preference_submissions(
                           event_id, message_id, chat_id, target_type,
                           callback_open_id, delivery_open_id, union_id, display_name,
                           preferences, changes, is_initial, submitted_at
                       ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(submission_context.get("event_id") or ""),
                        str(submission_context.get("message_id") or ""),
                        str(submission_context.get("chat_id") or ""),
                        str(submission_context.get("target_type") or "user"),
                        str(submission_context.get("callback_open_id") or callback_open_id or open_id),
                        open_id,
                        str(submission_context.get("union_id") or union_id),
                        display_name,
                        json.dumps(final_snapshot, ensure_ascii=False, separators=(",", ":")),
                        json.dumps(submission_changes, ensure_ascii=False, separators=(",", ":")),
                        int(submission_initial),
                        now,
                    ),
                )
        return {
            "adjustments": adjustments,
            "open_id": open_id,
            "display_name": display_name,
            "services": normalized,
            "frequency": frequency,
            "frequency_label": FREQUENCY_LABELS[frequency],
            "news_frequency": frequency,
            "news_frequency_label": FREQUENCY_LABELS[frequency],
            "news_item_limit": news_item_limit,
            "news_region_preference": news_region_preference,
            "news_categories": normalized_categories,
            "news_topics": normalized_topics,
            "news_category_labels": [NEWS_CATEGORY_LABELS[item] for item in normalized_categories],
            "news_delivery_times": normalized_delivery_times,
            "news_delivery_times_text": " / ".join(normalized_delivery_times),
            "report_cadence": "biweekly_on_publish",
            "report_cadence_label": REPORT_CADENCE_LABEL,
            "report_mode": report_mode,
            "report_mode_label": REPORT_MODE_LABELS[report_mode],
            "preference_changes": submission_changes,
            "preference_submission_initial": submission_initial,
            "updated_at": now,
        }

    def _handle_news_control(self, event: dict[str, Any], action: str) -> dict[str, Any]:
        open_id, message_id, chat_id, event_id = (
            str(event.get(key) or "") for key in ("operator_id", "message_id", "chat_id", "event_id")
        )
        if not (OPEN_ID_RE.fullmatch(open_id) and MESSAGE_ID_RE.fullmatch(message_id)
                and CHAT_ID_RE.fullmatch(chat_id) and event_id):
            raise ValueError("新闻设置回调缺少有效身份")
        with closing(self._connect()) as db:
            origin = db.execute("SELECT * FROM news_control_cards WHERE message_id=? AND chat_id=?",
                                (message_id, chat_id)).fetchone()
            if origin is None or origin["open_id"] != open_id:
                raise ValueError("只能管理本人收到的新闻卡片订阅")
            expected = "confirm" if action == "cmhk_news_unsubscribe_confirm_v1" else "news"
            if origin["purpose"] != expected:
                raise ValueError("请使用对应的新闻设置入口")
        profile = str(origin["profile"])
        identity = self.resolve_user(open_id, source_profile=profile)
        with closing(self._connect()) as db:
            subscriber = db.execute("SELECT * FROM subscribers WHERE open_id=?", (identity["open_id"],)).fetchone()
            services = [row[0] for row in db.execute(
                "SELECT service FROM subscriptions WHERE open_id=? AND active=1", (identity["open_id"],))]
        if subscriber is None:
            raise ValueError("未找到你的订阅设置")
        if action == "cmhk_news_preferences_v1":
            card = subscription_entry_card(
                recipient_name=identity["display_name"],
                report_schedule=self.report_schedule_snapshot(),
                performance_schedule=self.performance_schedule_snapshot(),
            )
            card["header"]["title"]["content"] = "修改兴趣偏好"
            values = {"services": services, "news_categories": normalize_news_categories(subscriber["news_categories"]),
                      "report_mode": subscriber["report_mode"], "news_frequency": subscriber["frequency"],
                      "news_item_limit": str(subscriber["news_item_limit"]),
                      "news_region_preference": subscriber["news_region_preference"]}
            times = _normalize_news_delivery_times(subscriber["news_delivery_times"])
            def fill(node):
                if isinstance(node, dict):
                    name = node.get("name")
                    if name in values:
                        node["selected_values" if node.get("tag") == "multi_select_static" else "initial_option"] = values[name]
                    if name in {"news_delivery_time_morning", "news_delivery_time_afternoon"}:
                        node["initial_time"] = times[0 if name.endswith("morning") else 1]
                    for value in node.values():
                        fill(value)
                elif isinstance(node, list):
                    for value in node:
                        fill(value)
            fill(card)
            status = "news_preferences_sent"
        elif action == "cmhk_news_unsubscribe_v1":
            elements = [{"tag": "markdown", "content": "请选择要取消的订阅（可多选），未选择的订阅继续保留。"}]
            if services:
                elements.extend([
                    {"tag": "form", "name": "unsubscribeForm", "elements": [
                        {"tag": "multi_select_static", "name": "cancel_services", "required": True,
                         "width": "fill", "placeholder": {"tag": "plain_text", "content": "选择要取消的订阅"},
                         "options": [{"text": {"tag": "plain_text", "content": label}, "value": service}
                                     for service, label in SERVICE_LABELS.items() if service in services]},
                        {"tag": "button", "name": "confirmUnsubscribe", "type": "danger",
                         "form_action_type": "submit", "text": {"tag": "plain_text", "content": "确认取消所选订阅"},
                         "behaviors": [{"type": "callback", "value": {
                             "action": "cmhk_news_unsubscribe_confirm_v1", "scope": "selected"}}]},
                    ]},
                    {"tag": "hr"},
                    {"tag": "button", "type": "danger", "text": {"tag": "plain_text", "content": "全部取消"},
                     "confirm": {"title": {"tag": "plain_text", "content": "取消全部订阅？"},
                                 "text": {"tag": "plain_text", "content": "将停止战略新闻、战略双周报和运营商业绩摘要的后续推送。"}},
                     "behaviors": [{"type": "callback", "value": {
                         "action": "cmhk_news_unsubscribe_confirm_v1", "scope": "all"}}]},
                ])
            else:
                elements = [{"tag": "markdown", "content": "你目前没有生效中的订阅，无需取消。"}]
            card = {"schema": "2.0", "header": {"template": "blue", "title": {
                "tag": "plain_text", "content": "取消订阅"}}, "body": {"elements": elements}}
            status = "news_unsubscribe_confirmation_sent"
        else:
            value = json.loads(str(event.get("action_value") or "{}"))
            # Previously delivered confirmation cards cancel news only.
            scope = value.get("scope", "news")
            if scope == "all":
                selected = list(SERVICE_LABELS)
            elif scope == "news":
                selected = ["news"]
            elif scope == "selected":
                try:
                    form = json.loads(str(event.get("form_value") or "{}"))
                except (ValueError, TypeError) as exc:
                    raise ValueError("取消订阅表单无效，请重新选择") from exc
                selected = form.get("cancel_services") if isinstance(form, dict) else None
                if isinstance(selected, str):
                    selected = [item for item in selected.split(",") if item]
                if (not isinstance(selected, list) or not selected
                        or any(not isinstance(item, str) or item not in VALID_SERVICES for item in selected)):
                    raise ValueError("请至少选择一个有效的订阅内容")
            else:
                raise ValueError("取消订阅范围无效")
            with closing(self._connect()) as db, db:
                db.executemany("UPDATE subscriptions SET active=0, updated_at=? WHERE open_id=? AND service=?",
                               [(_now_hkt(), identity["open_id"], service) for service in set(selected)])
                remaining = {row[0] for row in db.execute(
                    "SELECT service FROM subscriptions WHERE open_id=? AND active=1", (identity["open_id"],))}
            cancelled_text = "、".join(label for service, label in SERVICE_LABELS.items() if service in selected)
            remaining_text = "、".join(label for service, label in SERVICE_LABELS.items() if service in remaining) or "无"
            card = {"schema": "2.0", "header": {"template": "green", "title": {
                "tag": "plain_text", "content": "✓ 取消订阅成功"}}, "body": {"elements": [
                {"tag": "markdown", "content": f"**已取消：**{cancelled_text}\n\n**仍保留：**{remaining_text}"},
                {"tag": "hr"},
                {"tag": "markdown", "content": "后续将停止已取消内容的推送。你可以随时通过订阅入口重新订阅。"},
            ]}}
            status = "news_unsubscribed"
        sent = self._send_interactive_card(open_id, card,
                    idempotency_key="news-control-" + hashlib.sha256(event_id.encode()).hexdigest()[:30], profile=profile)
        self._verify_message(sent, profile=profile)
        return {"status": status, "source_profile": profile, "open_id": identity["open_id"],
                "confirmation_message_id": sent, "preserve_source_card": True}

    def subscription_validation_feedback(self, event: dict[str, Any], error: ValueError) -> dict[str, Any] | None:
        """Acknowledge a rejected controlled form without changing subscriptions."""
        if event.get("type") != "card.action.trigger" or event.get("action_tag") != "button":
            return None
        try:
            form = json.loads(str(event.get("form_value") or "{}"))
        except (ValueError, TypeError):
            return None
        if not isinstance(form, dict) or "services" not in form:
            return None
        open_id, message_id, chat_id, event_id = (
            str(event.get(key) or "") for key in ("operator_id", "message_id", "chat_id", "event_id")
        )
        if not (OPEN_ID_RE.fullmatch(open_id) and MESSAGE_ID_RE.fullmatch(message_id)
                and CHAT_ID_RE.fullmatch(chat_id) and event_id):
            return None
        with closing(self._connect()) as db:
            origin = db.execute("SELECT * FROM subscription_entry_cards WHERE message_id=? AND chat_id=?",
                                (message_id, chat_id)).fetchone()
        if origin is None or (origin["target_type"] == "user" and origin["target_id"] != open_id):
            return None
        profile = str(origin["source_profile"] or self.entry_profile)
        identity = self.resolve_user(open_id, source_profile=profile)
        reason = str(error)[:300]
        now = _now_hkt()
        with closing(self._connect()) as db, db:
            if str(origin["target_type"] or "") == "chat":
                db.execute(
                    """INSERT INTO subscription_group_responses(
                           message_id, chat_id, callback_open_id, delivery_open_id,
                           union_id, display_name, avatar_url, source_profile,
                           department_names, job_title, status, last_error, responded_at, updated_at
                       ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'needs_correction', ?, ?, ?)
                       ON CONFLICT(message_id, callback_open_id) DO UPDATE SET
                           delivery_open_id=excluded.delivery_open_id,
                           union_id=excluded.union_id,
                           display_name=excluded.display_name,
                           avatar_url=excluded.avatar_url,
                           source_profile=excluded.source_profile,
                           department_names=excluded.department_names,
                           job_title=excluded.job_title,
                           status=excluded.status,
                           last_error=excluded.last_error,
                           responded_at=excluded.responded_at,
                           updated_at=excluded.updated_at""",
                    (
                        message_id, chat_id, identity["callback_open_id"], identity["open_id"],
                        identity["union_id"], identity["display_name"], identity.get("avatar_url", ""),
                        profile, json.dumps(identity.get("department_names") or [], ensure_ascii=False),
                        identity.get("job_title", ""), reason, now, now,
                    ),
                )
            else:
                db.execute("""UPDATE subscription_invitations SET status='needs_correction', last_error=?,
                           responded_at=?, updated_at=? WHERE message_id=? AND callback_open_id=?""",
                           (reason, now, now, message_id, identity["callback_open_id"]))
        card = {"schema": "2.0", "header": {"template": "orange", "title": {
            "tag": "plain_text", "content": "订阅未保存，请修改后重试"}}, "body": {"elements": [
                {"tag": "div", "text": {"tag": "plain_text", "content": reason}},
                {"tag": "markdown", "content": "请回到刚才的订阅表单调整选项，再点击**确认订阅**。本次未改变已有订阅；保存成功后会收到订阅成功卡片。"},
            ]}}
        sent = self._send_interactive_card(identity["callback_open_id"], card, profile=profile,
            idempotency_key="subreject-" + hashlib.sha256(event_id.encode()).hexdigest()[:30])
        self._verify_message(sent, profile=profile)
        return {"status": "subscription_rejected", "source_profile": profile,
                "open_id": identity["open_id"], "display_name": identity["display_name"],
                "error": reason, "confirmation_message_id": sent, "preserve_source_card": True}

    def handle_card_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        if str(event.get("type") or "") != "card.action.trigger" or str(event.get("action_tag") or "") != "button":
            return None
        try:
            action = json.loads(str(event.get("action_value") or "{}"))
        except (ValueError, TypeError, json.JSONDecodeError):
            action = {}
        action_name = str(action.get("action") or "") if isinstance(action, dict) else ""
        if action_name in {"cmhk_news_preferences_v1", "cmhk_news_unsubscribe_v1",
                           "cmhk_news_unsubscribe_confirm_v1"}:
            return self._handle_news_control(event, action_name)
        is_pause = action_name == "cmhk_subscription_pause_all_v1"
        form_raw = str(event.get("form_value") or "")
        if not form_raw and not is_pause and action_name != "cmhk_subscription_save_v1":
            return None
        services: list[str] = []
        frequency = "once_daily"
        report_mode = "pdf"
        news_item_limit = 10
        news_region_preference = None
        news_categories = list(NEWS_CATEGORY_LABELS)
        news_delivery_times = list(NEWS_DELIVERY_TIMES_DEFAULT)
        if not is_pause:
            try:
                form = json.loads(form_raw or "{}")
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                raise ValueError("订阅卡片没有返回有效表单") from exc
            if not isinstance(form, dict) or "services" not in form:
                return None
            selected = form.get("services")
            if isinstance(selected, str):
                selected = [item for item in selected.split(",") if item]
            if not isinstance(selected, list):
                raise ValueError("订阅服务选择格式无效")
            services = [str(item) for item in selected]
            selected_categories = form.get("news_categories")
            if isinstance(selected_categories, str):
                selected_categories = [item for item in selected_categories.split(",") if item]
            news_categories = normalize_news_categories(
                DEFAULT_NEWS_CATEGORIES if selected_categories is None else selected_categories,
                default_all=False,
            )
            delivery_plan = _card_form_scalar(form.get("delivery_plan"))
            if delivery_plan:
                plan_match = re.fullmatch(r"(immediate|daily|weekly|once_daily|twice_daily)_(pdf_audio|pdf|audio)", delivery_plan)
                frequency, report_mode = plan_match.groups() if plan_match else ("", "")
                frequency = _normalize_news_frequency(frequency)
            else:
                frequency = _normalize_news_frequency(
                    _card_form_scalar(form.get("news_frequency") or form.get("frequency"))
                )
                report_mode = _card_form_scalar(form.get("report_mode")) or "pdf"
            news_item_limit = _card_form_scalar(form.get("news_item_limit")) or 10
            news_region_preference = _card_form_scalar(form.get("news_region_preference")) or None
            news_delivery_times = [
                _card_time_scalar(form.get("news_delivery_time_morning")) if "news_delivery_time_morning" in form else NEWS_DELIVERY_TIMES_DEFAULT[0],
                _card_time_scalar(form.get("news_delivery_time_afternoon")) if "news_delivery_time_afternoon" in form else NEWS_DELIVERY_TIMES_DEFAULT[1],
            ]
        open_id = str(event.get("operator_id") or "")
        chat_id = str(event.get("chat_id") or "")
        message_id = str(event.get("message_id") or "")
        event_id = str(event.get("event_id") or "")
        if (
            not event_id
            or not OPEN_ID_RE.fullmatch(open_id)
            or not CHAT_ID_RE.fullmatch(chat_id)
            or not MESSAGE_ID_RE.fullmatch(message_id)
        ):
            raise ValueError("订阅回调缺少有效事件、用户或消息身份")
        with closing(self._connect()) as db, db:
            published = db.execute(
                "SELECT source_profile, target_type, target_id, created_at FROM subscription_entry_cards WHERE message_id=? AND chat_id=?",
                (message_id, chat_id),
            ).fetchone()
        if published is None:
            raise ValueError("订阅回调并非来自后台已发布的受控卡片")
        source_profile = str(published["source_profile"] or self.entry_profile)
        if str(published["target_type"]) == "user" and str(published["target_id"]) != open_id:
            raise ValueError("订阅回调用户与受邀人不一致")
        identity = self.resolve_user(open_id, source_profile=source_profile)

        def record_invitation_response(status: str) -> None:
            now = _now_hkt()
            with closing(self._connect()) as db, db:
                if str(published["target_type"] or "") == "chat":
                    directory = db.execute(
                        """SELECT display_name, avatar_url, department_names, job_title
                           FROM subscription_directory_people
                           WHERE union_id=? AND active=1
                           ORDER BY synced_at DESC LIMIT 1""",
                        (identity["union_id"],),
                    ).fetchone()
                    display_name = str(directory["display_name"] or "") if directory else ""
                    avatar_url = str(directory["avatar_url"] or "") if directory else ""
                    department_names = str(directory["department_names"] or "[]") if directory else "[]"
                    job_title = str(directory["job_title"] or "") if directory else ""
                    db.execute(
                        """INSERT INTO subscription_group_responses(
                               message_id, chat_id, callback_open_id, delivery_open_id, union_id,
                               display_name, avatar_url, source_profile, department_names, job_title,
                               status, last_error, responded_at, updated_at
                           ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?)
                           ON CONFLICT(message_id, callback_open_id) DO UPDATE SET
                               delivery_open_id=excluded.delivery_open_id,
                               union_id=excluded.union_id,
                               display_name=excluded.display_name,
                               avatar_url=excluded.avatar_url,
                               source_profile=excluded.source_profile,
                               department_names=excluded.department_names,
                               job_title=excluded.job_title,
                               status=excluded.status,
                               last_error='',
                               responded_at=excluded.responded_at,
                               updated_at=excluded.updated_at""",
                        (
                            message_id, chat_id, identity["callback_open_id"], identity["open_id"],
                            identity["union_id"], display_name or identity["display_name"],
                            avatar_url or identity.get("avatar_url", ""), source_profile,
                            department_names, job_title or identity.get("job_title", ""),
                            status, now, now,
                        ),
                    )
                    return
                updated = db.execute(
                    """UPDATE subscription_invitations
                       SET status=?, responded_at=?, updated_at=?, last_error=''
                       WHERE message_id=? AND callback_open_id=?""",
                    (status, now, now, message_id, identity["callback_open_id"]),
                )
                if updated.rowcount:
                    return
                db.execute(
                    """INSERT INTO subscription_invitations(
                           callback_open_id, delivery_open_id, union_id, display_name,
                           source_profile, avatar_url, message_id, chat_id,
                           status, invited_by, sent_at, responded_at, updated_at
                       ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 'card_callback', ?, ?, ?)""",
                    (
                        identity["callback_open_id"], identity["open_id"], identity["union_id"],
                        identity["display_name"], source_profile, identity.get("avatar_url", ""),
                        message_id, chat_id, status, str(published["created_at"] or now), now, now,
                    ),
                )

        if is_pause:
            with closing(self._connect()) as db, db:
                existing = db.execute(
                    "SELECT display_name FROM subscribers WHERE open_id=?",
                    (identity["open_id"],),
                ).fetchone()
                if existing is None:
                    raise ValueError("你目前没有可暂停的订阅")
                db.execute(
                    "UPDATE subscribers SET status='paused', updated_at=? WHERE open_id=?",
                    (_now_hkt(), identity["open_id"]),
                )
            record_invitation_response("paused")
            confirmation = self._send_markdown(
                identity["callback_open_id"],
                "#### 订阅已暂停\n\n你的全部战略情报推送已暂停。需要恢复时，重新提交订阅卡片即可。",
                idempotency_key=f"subpause-{event_id}"[:50],
                profile=source_profile,
            )
            self._verify_message(confirmation, profile=source_profile)
            return {
                "status": "subscription_paused",
                "source_profile": source_profile,
                "open_id": identity["open_id"],
                "display_name": identity["display_name"],
                "services": [],
                "confirmation_message_id": confirmation,
                "updated_at": _now_hkt(),
            }
        saved = self.save_subscriptions(
            identity["open_id"], identity["display_name"], services, chat_id,
            callback_open_id=identity["callback_open_id"], union_id=identity["union_id"],
            frequency=frequency,
            report_mode=report_mode,
            news_item_limit=news_item_limit,
            news_region_preference=news_region_preference,
            news_categories=news_categories,
            news_delivery_times=news_delivery_times,
            submission_context={
                "event_id": event_id,
                "message_id": message_id,
                "chat_id": chat_id,
                "target_type": str(published["target_type"] or "user"),
                "callback_open_id": identity["callback_open_id"],
                "union_id": identity["union_id"],
            },
        )
        # A person's latest submission is their restore point; admin edits never replace it.
        with closing(self._connect()) as db, db:
            defaults = {key: saved[key] for key in ("services", "frequency", "report_mode", "news_item_limit", "news_categories", "news_delivery_times", "news_region_preference", "news_topics")}
            defaults["status"] = "active"
            db.execute("UPDATE subscribers SET default_preferences=? WHERE open_id=?", (json.dumps(defaults, ensure_ascii=False), identity["open_id"]))
        record_invitation_response("accepted")
        labels = "、".join(SERVICE_LABELS[item] for item in saved["services"])
        category_labels = "、".join(saved["news_category_labels"])
        subscriptions_config = (
            self.config.get("subscriptions")
            if isinstance(self.config.get("subscriptions"), dict)
            else {}
        )
        confirmation_keys = (
            subscriptions_config.get("confirmation_image_keys")
            if isinstance(subscriptions_config.get("confirmation_image_keys"), dict)
            else {}
        )
        preference_updated_keys = (
            subscriptions_config.get("preference_updated_image_keys")
            if isinstance(subscriptions_config.get("preference_updated_image_keys"), dict)
            else {}
        )
        is_preference_update = not bool(saved.get("preference_submission_initial"))
        selected_image_keys = preference_updated_keys if is_preference_update else confirmation_keys
        confirmation_image_key = str(
            selected_image_keys.get(source_profile) or selected_image_keys.get("default") or ""
        )
        confirmation = self._send_interactive_card(
            identity["callback_open_id"],
            subscription_confirmation_card(
                image_key=confirmation_image_key,
                is_preference_update=is_preference_update,
                display_name=identity["display_name"],
                service_labels=labels,
                report_mode_label=saved["report_mode_label"],
                frequency_label=saved["frequency_label"],
                category_labels=category_labels,
                news_item_limit=saved["news_item_limit"],
                news_region_preference=saved["news_region_preference"],
                news_delivery_times=saved["news_delivery_times"],
                adjustments=saved["adjustments"],
            ),
            idempotency_key=f"suback-{event_id}"[:50],
            profile=source_profile,
        )
        self._verify_message(confirmation, profile=source_profile)
        saved["confirmation_message_id"] = confirmation
        saved["feedback_kind"] = "preference_updated" if is_preference_update else "subscription_started"
        return {"status": "subscription_saved", "source_profile": source_profile, **saved}

    def list_summary(self, *, delivery_limit: int | None = None) -> dict[str, Any]:
        from cmhk.services.subscription_chat import admin_chat_history, preference_points
        with closing(self._connect()) as db, db:
            chat_history = admin_chat_history(db, self.delivery_profile)
            rows = db.execute(
                """SELECT s.open_id, s.callback_open_id, s.union_id, s.display_name, s.status, s.frequency, s.report_mode, s.news_item_limit, s.news_region_preference, s.news_categories, s.news_topics, s.original_news_categories, s.original_news_categories_source, s.news_delivery_times, s.default_preferences,
                          s.source_chat_id, s.created_at, s.updated_at,
                          GROUP_CONCAT(CASE WHEN x.active=1 THEN x.service END) AS services
                   FROM subscribers s LEFT JOIN subscriptions x ON x.open_id=s.open_id
                   GROUP BY s.open_id ORDER BY s.updated_at DESC"""
            ).fetchall()
            delivery_query = """SELECT d.*,
                          COALESCE(
                              NULLIF((SELECT s.display_name FROM subscribers s
                                      WHERE s.open_id=d.open_id LIMIT 1), ''),
                              NULLIF((SELECT c.display_name FROM subscription_invite_candidates c
                                      WHERE c.delivery_open_id=d.open_id ORDER BY c.updated_at DESC LIMIT 1), ''),
                              NULLIF((SELECT p.display_name FROM subscription_directory_people p
                                      WHERE p.directory_open_id=d.open_id ORDER BY p.synced_at DESC LIMIT 1), ''),
                              NULLIF((SELECT i.display_name FROM subscription_invitations i
                                      WHERE i.delivery_open_id=d.open_id ORDER BY i.id DESC LIMIT 1), ''),
                              ''
                          ) AS recipient_name
                   FROM deliveries d ORDER BY d.id DESC"""
            delivery_params: tuple[int, ...] = ()
            if delivery_limit is not None:
                delivery_query += " LIMIT ?"
                delivery_params = (max(1, min(delivery_limit, 2000)),)
            deliveries = db.execute(delivery_query, delivery_params).fetchall()
            delivery_total = int(db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0])
            invitations = db.execute(
                "SELECT * FROM subscription_invitations ORDER BY id DESC"
            ).fetchall()
            group_cards = db.execute(
                """SELECT c.* FROM subscription_entry_cards c
                   WHERE c.target_type='chat'
                   ORDER BY c.created_at DESC"""
            ).fetchall()
            group_responses = db.execute(
                """SELECT r.* FROM subscription_group_responses r
                   JOIN subscription_entry_cards c ON c.message_id=r.message_id
                   WHERE c.target_type='chat'
                   ORDER BY r.updated_at DESC"""
            ).fetchall()
            preference_submissions = db.execute(
                """SELECT * FROM subscription_preference_submissions
                   ORDER BY submitted_at DESC, id DESC"""
            ).fetchall()
            news_rounds = [dict(r) for r in db.execute("SELECT * FROM news_round_progress ORDER BY updated_at DESC")]
            directory_people = db.execute(
                """SELECT directory_open_id, union_id, display_name, en_name, avatar_url,
                          job_title, department_names, source_profile
                   FROM subscription_directory_people WHERE active=1
                   ORDER BY synced_at DESC"""
            ).fetchall()
            invite_candidates = db.execute(
                """SELECT callback_open_id, delivery_open_id, union_id, display_name, avatar_url,
                          job_title, department_names, source_profile
                   FROM subscription_invite_candidates ORDER BY updated_at DESC"""
            ).fetchall()
        subscribers = []
        counts = {key: 0 for key in VALID_SERVICES}
        latest_group_response_by_delivery: dict[str, dict[str, Any]] = {}
        for response_row in group_responses:
            response = dict(response_row)
            latest_group_response_by_delivery.setdefault(str(response["delivery_open_id"]), response)
        for row in rows:
            services = sorted(filter(None, str(row["services"] or "").split(",")))
            try:
                default_preferences = json.loads(str(row["default_preferences"] or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                default_preferences = {}
            if not isinstance(default_preferences, dict):
                default_preferences = {}
            if default_preferences:
                default_preferences = {
                    "services": sorted(
                        service for service in default_preferences.get("services", [])
                        if service in VALID_SERVICES
                    ),
                    "news_categories": normalize_news_categories(default_preferences.get("news_categories")),
                    "news_topics": normalize_news_topics(default_preferences.get("news_topics")),
                    "report_mode": str(default_preferences.get("report_mode") or "pdf"),
                    "frequency": _normalize_news_frequency(str(default_preferences.get("frequency") or "once_daily")),
                    "news_item_limit": int(default_preferences.get("news_item_limit") or 10),
                    "news_region_preference": default_preferences.get("news_region_preference", "hong_kong"),
                    "news_delivery_times": _normalize_news_delivery_times(default_preferences.get("news_delivery_times")),
                    "status": str(default_preferences.get("status") or "active"),
                }
            response_evidence = latest_group_response_by_delivery.get(str(row["open_id"]))
            is_group_card_submission = bool(
                response_evidence
                and str(response_evidence.get("chat_id") or "") == str(row["source_chat_id"] or "")
                and str(response_evidence.get("updated_at") or "") == str(row["updated_at"] or "")
            )
            if row["status"] == "active":
                for service in services:
                    if service in counts:
                        counts[service] += 1
            subscribers.append({
                **dict(row),
                "services": services,
                "latest_news_round": next((r for r in news_rounds if r["open_id"] == row["open_id"]), None),
                "default_preferences": default_preferences,
                "news_categories": normalize_news_categories(row["news_categories"]),
                "news_topics": normalize_news_topics(row["news_topics"]),
                "original_news_categories": normalize_news_categories(row["original_news_categories"], default_all=False),
                "news_category_labels": [
                    NEWS_CATEGORY_LABELS[item]
                    for item in normalize_news_categories(row["news_categories"])
                ],
                "news_delivery_times": _normalize_news_delivery_times(row["news_delivery_times"]),
                "news_delivery_times_text": " / ".join(_normalize_news_delivery_times(row["news_delivery_times"])),
                "news_frequency": str(row["frequency"]),
                "news_frequency_label": FREQUENCY_LABELS.get(str(row["frequency"]), str(row["frequency"])),
                "frequency_label": FREQUENCY_LABELS.get(str(row["frequency"]), str(row["frequency"])),
                "report_mode_label": REPORT_MODE_LABELS.get(str(row["report_mode"]), str(row["report_mode"])),
                "report_cadence": "biweekly_on_publish",
                "report_cadence_label": REPORT_CADENCE_LABEL,
                "preference_source": "group_card" if is_group_card_submission else "current_config",
                "preference_source_label": "群卡本人提交" if is_group_card_submission else "当前配置",
                "preference_message_id": str(response_evidence.get("message_id") or "") if is_group_card_submission else "",
            })
        for subscriber in subscribers:
            current_preferences = _preference_snapshot(**{
                field: subscriber[field] for field in PREFERENCE_FIELD_LABELS
            })
            subscriber["preference_points"] = preference_points(current_preferences)
            subscriber["chat_history"] = chat_history.get(subscriber["open_id"], [])
            last_choice = next((item for item in subscriber["chat_history"]
                                if item["intent"] in {"update", "confirm"}), None)
            subscriber["preference_confirmed_at"] = (
                last_choice["created_at"] if last_choice and last_choice["intent"] == "confirm"
                and last_choice["points"] == subscriber["preference_points"] else None
            )
        card_actions = self.config.get("card_actions") if isinstance(self.config.get("card_actions"), dict) else {}
        primary_name = str(card_actions.get("primary_handler_expected_name") or "").strip()
        primary_open_ids = {
            value for value in (
                self.primary_delivery_open_id,
                str(card_actions.get("primary_handler_open_id") or ""),
            ) if value
        }
        delivery_items = []
        for item in deliveries:
            delivery = dict(item)
            if not str(delivery.get("recipient_name") or "").strip() and primary_name and str(delivery.get("open_id") or "") in primary_open_ids:
                delivery["recipient_name"] = primary_name
            delivery["recipient_open_id"] = str(delivery.get("open_id") or "")
            delivery["message_ids"] = json.loads(delivery.get("message_ids") or "[]")
            delivery_items.append(delivery)
        submission_items: list[dict[str, Any]] = []
        submissions_by_message_person: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in preference_submissions:
            submission = dict(row)
            try:
                preferences = json.loads(str(submission.get("preferences") or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                preferences = {}
            try:
                changes = json.loads(str(submission.get("changes") or "[]"))
            except (TypeError, ValueError, json.JSONDecodeError):
                changes = []
            submission["preferences"] = preferences if isinstance(preferences, dict) else {}
            submission["changes"] = changes if isinstance(changes, list) else []
            submission["is_initial"] = bool(submission.get("is_initial"))
            submission_items.append(submission)
            key = (str(submission.get("message_id") or ""), str(submission.get("delivery_open_id") or ""))
            submissions_by_message_person.setdefault(key, []).append(submission)

        invitation_items: list[dict[str, Any]] = []
        for row in invitations:
            invitation = dict(row)
            invitation["submissions"] = submissions_by_message_person.get(
                (str(invitation.get("message_id") or ""), str(invitation.get("delivery_open_id") or "")),
                [],
            )
            invitation_items.append(invitation)
        subscriber_identity_by_delivery = {
            str(row["open_id"]): {
                "union_id": str(row["union_id"] or ""),
                "callback_open_id": str(row["callback_open_id"] or ""),
            }
            for row in rows
        }
        directory_by_union: dict[str, dict[str, Any]] = {}
        for row in directory_people:
            profile = dict(row)
            union_id = str(profile.get("union_id") or "")
            if union_id:
                directory_by_union.setdefault(union_id, profile)
        candidates_by_identity: dict[str, dict[str, Any]] = {}
        for row in invite_candidates:
            profile = dict(row)
            for key in (
                str(profile.get("union_id") or ""),
                str(profile.get("callback_open_id") or ""),
                str(profile.get("delivery_open_id") or ""),
            ):
                if key:
                    candidates_by_identity.setdefault(key, profile)

        responses_by_message: dict[str, list[dict[str, Any]]] = {}
        for row in group_responses:
            response = dict(row)
            subscriber_identity = subscriber_identity_by_delivery.get(
                str(response.get("delivery_open_id") or ""), {}
            )
            union_id = str(response.get("union_id") or subscriber_identity.get("union_id") or "")
            candidate = (
                candidates_by_identity.get(union_id)
                or candidates_by_identity.get(str(response.get("callback_open_id") or ""))
                or candidates_by_identity.get(str(response.get("delivery_open_id") or ""))
                or {}
            )
            directory = directory_by_union.get(union_id, {})
            profile = directory or candidate
            response["union_id"] = union_id
            response["display_name"] = str(
                profile.get("display_name") or response.get("display_name") or "飞书用户"
            )
            response["en_name"] = str(directory.get("en_name") or "")
            response["avatar_url"] = str(
                directory.get("avatar_url")
                or candidate.get("avatar_url")
                or response.get("avatar_url")
                or ""
            )
            response["directory_open_id"] = str(directory.get("directory_open_id") or "")
            raw_departments = (
                directory.get("department_names")
                or response.get("department_names")
                or candidate.get("department_names")
                or "[]"
            )
            try:
                department_names = json.loads(raw_departments) if isinstance(raw_departments, str) else raw_departments
            except (TypeError, ValueError, json.JSONDecodeError):
                department_names = []
            response["department_names"] = department_names if isinstance(department_names, list) else []
            response["job_title"] = str(
                directory.get("job_title")
                or response.get("job_title")
                or candidate.get("job_title")
                or ""
            )
            response["submissions"] = submissions_by_message_person.get(
                (str(response.get("message_id") or ""), str(response.get("delivery_open_id") or "")),
                [],
            )
            responses_by_message.setdefault(str(response["message_id"]), []).append(response)

        group_invitation_by_target: dict[str, dict[str, Any]] = {}
        for row in group_cards:
            item = dict(row)
            target_id = str(item.get("target_id") or item.get("chat_id") or item.get("message_id"))
            group = group_invitation_by_target.get(target_id)
            if group is None:
                group = item | {
                    "target_name": str(item.get("target_name") or target_id or "飞书群聊"),
                    "message_ids": [],
                    "responses_by_person": {},
                }
                group_invitation_by_target[target_id] = group
            group["message_ids"].append(str(item["message_id"]))
            for response in responses_by_message.get(str(item["message_id"]), []):
                person_key = str(
                    response.get("union_id")
                    or response.get("delivery_open_id")
                    or response.get("callback_open_id")
                )
                existing_response = group["responses_by_person"].get(person_key)
                if existing_response is None:
                    group["responses_by_person"][person_key] = response
                else:
                    known_events = {
                        str(item.get("event_id") or "")
                        for item in existing_response.get("submissions", [])
                    }
                    existing_response.setdefault("submissions", []).extend(
                        item for item in response.get("submissions", [])
                        if str(item.get("event_id") or "") not in known_events
                    )

        group_invitation_items = []
        for group in list(group_invitation_by_target.values())[:30]:
            responses = list(group.pop("responses_by_person").values())
            group["responses"] = responses
            group["message_count"] = len(group["message_ids"])
            group["response_count"] = len(responses)
            group["accepted_count"] = sum(1 for response in responses if response.get("status") == "accepted")
            group["paused_count"] = sum(1 for response in responses if response.get("status") == "paused")
            group["latest_response_at"] = max(
                (str(response.get("updated_at") or "") for response in responses),
                default="",
            )
            group["status"] = "responded" if responses else "verified"
            group_invitation_items.append(group)
        return {
            "services": [{"key": key, "label": SERVICE_LABELS[key], "subscriber_count": counts[key]} for key in ("weekly", "performance", "news")],
            "news_categories": [
                {"key": key, "label": label}
                for key, label in NEWS_CATEGORY_LABELS.items()
            ],
            "subscribers": subscribers,
            "deliveries": delivery_items,
            "delivery_history": {
                "total": delivery_total,
                "returned": len(delivery_items),
                "newest_at": str(delivery_items[0].get("created_at") or "") if delivery_items else "",
                "oldest_at": str(delivery_items[-1].get("created_at") or "") if delivery_items else "",
            },
            "invite_candidates": self.list_invite_candidates(),
            "group_invitations": group_invitation_items,
            "invitations": invitation_items,
            "preference_submissions": submission_items,
            "invitation_history": {
                "total": len(invitations),
                "newest_at": str(invitations[0]["sent_at"] or "") if invitations else "",
                "oldest_at": str(invitations[-1]["sent_at"] or "") if invitations else "",
            },
            "invitation_counts": {
                status: sum(1 for item in invitations if str(item["status"]) == status)
                for status in ("pending", "accepted", "paused", "failed")
            },
            "invitation_permissions": self.invitation_permission_snapshot(),
            "active_subscriber_count": sum(1 for row in subscribers if row["status"] == "active"),
            "report_schedule": self.report_schedule_snapshot(),
            "performance_schedule": self.performance_schedule_snapshot(),
            "weekly_report_preference": self.weekly_report_preference(),
            "performance_report_preference": self.performance_report_preference(),
            "strategic_news_schedule": self.strategic_news_schedule_snapshot(),
            "updated_at": _now_hkt(),
        }

    def strategic_news_schedule_snapshot(self) -> dict[str, Any]:
        configured = self.environ.get("CMHK_STRATEGY_SCAN_TIMES")
        if not configured:
            configured = self.config.get("strategic_scan_times") or STRATEGIC_SCAN_TIMES_DEFAULT
        times = _normalize_strategic_scan_times(configured)
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT enabled, updated_at FROM report_automation_schedule WHERE service='news'"
            ).fetchone()
        return {
            "service": "news",
            "enabled": True,
            "times": times,
            "times_text": " / ".join(times),
            "timezone": "Asia/Hong_Kong",
            "timezone_label": "香港时间",
            "dispatch_rule": "个人按本人设定时间推送，且必须等对应爬虫完成",
            "updated_at": str(row["updated_at"] or "") if row else "",
        }

    def update_news_schedule(self, *, enabled: bool) -> dict[str, Any]:
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE report_automation_schedule SET enabled=?, updated_at=? WHERE service='news'",
                (1 if enabled else 0, _now_hkt()),
            )
        return self.strategic_news_schedule_snapshot()

    def _report_preference(self, service: str) -> dict[str, Any]:
        if service not in {"weekly", "performance"}:
            raise ValueError("报告版本服务无效")
        preference_key = f"{service}_report_path"
        with closing(self._connect()) as db:
            row = db.execute(
                """SELECT preference_value, updated_at
                   FROM subscription_admin_preferences
                   WHERE preference_key=?""",
                (preference_key,),
            ).fetchone()
        return {
            "path": str(row["preference_value"] or "") if row else "",
            "updated_at": str(row["updated_at"] or "") if row else "",
        }

    def _update_report_preference(self, service: str, report_path: Any) -> dict[str, Any]:
        if service not in {"weekly", "performance"}:
            raise ValueError("报告版本服务无效")
        normalized = str(report_path or "").strip()
        candidate = Path(normalized) if normalized else None
        if candidate and (candidate.is_absolute() or ".." in candidate.parts):
            label = "周报" if service == "weekly" else "业绩摘要"
            raise ValueError(f"{label}版本路径无效")
        updated_at = _now_hkt()
        preference_key = f"{service}_report_path"
        with closing(self._connect()) as db, db:
            db.execute(
                """INSERT INTO subscription_admin_preferences(
                       preference_key, preference_value, updated_at
                   ) VALUES(?, ?, ?)
                   ON CONFLICT(preference_key) DO UPDATE SET
                       preference_value=excluded.preference_value,
                       updated_at=excluded.updated_at""",
                (preference_key, normalized, updated_at),
            )
        return {"path": normalized, "updated_at": updated_at}

    def weekly_report_preference(self) -> dict[str, Any]:
        return self._report_preference("weekly")

    def update_weekly_report_preference(self, report_path: Any) -> dict[str, Any]:
        return self._update_report_preference("weekly", report_path)

    def performance_report_preference(self) -> dict[str, Any]:
        return self._report_preference("performance")

    def update_performance_report_preference(self, report_path: Any) -> dict[str, Any]:
        return self._update_report_preference("performance", report_path)

    def automatic_delivery_enabled(self, service: str) -> bool:
        if service not in {"news", "weekly", "performance"}:
            return False
        if service == "news":
            return True
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT enabled FROM report_automation_schedule WHERE service=?",
                (service,),
            ).fetchone()
        return bool(row["enabled"]) if row else False

    @staticmethod
    def _normalize_schedule_days(days: Any) -> list[int]:
        values = days if isinstance(days, (list, tuple)) else re.split(r"[,，\s]+", str(days or ""))
        normalized: list[int] = []
        for value in values:
            if value in {None, ""}:
                continue
            try:
                day = int(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("执行日期请填写 1 至 31 的整数") from exc
            if not 1 <= day <= 31:
                raise ValueError("执行日期必须在 1 至 31 日之间")
            if day not in normalized:
                normalized.append(day)
        if not normalized:
            raise ValueError("请至少设置一个每月执行日期")
        return sorted(normalized)

    @staticmethod
    def _normalize_schedule_time(value: Any) -> str:
        raw = str(value or "").strip()
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", raw):
            raise ValueError("执行时间必须使用 HH:MM 格式")
        return raw

    def _report_schedule_snapshot(self, service: str, *, now: datetime | None = None) -> dict[str, Any]:
        if service not in {"weekly", "performance"}:
            raise ValueError("报告排期服务无效")
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT * FROM report_automation_schedule WHERE service=?",
                (service,),
            ).fetchone()
        data = dict(row) if row else {}
        try:
            days = self._normalize_schedule_days(json.loads(str(data.get("days_json") or "[]")))
        except (ValueError, TypeError, json.JSONDecodeError):
            days = list(REPORT_SCHEDULE_DEFAULT_DAYS)
        time_hm = str(data.get("time_hm") or REPORT_SCHEDULE_DEFAULT_TIME)
        current = (now or datetime.now(HKT)).astimezone(HKT)
        next_run = ""
        if bool(data.get("enabled")):
            for offset in range(0, 70):
                candidate_date = (current + timedelta(days=offset)).date()
                if candidate_date.day not in days:
                    continue
                candidate = datetime.fromisoformat(f"{candidate_date.isoformat()}T{time_hm}:00+08:00")
                candidate_slot = f"{candidate_date.isoformat()}@{time_hm}"
                if candidate >= current and candidate_slot != str(data.get("last_slot") or ""):
                    next_run = candidate.isoformat(timespec="minutes")
                    break
        return {
            "service": service,
            "enabled": bool(data.get("enabled")),
            "days": days,
            "days_text": "、".join(str(day) for day in days) + " 日",
            "time": time_hm,
            "timezone": "Asia/Hong_Kong",
            "next_run_at": next_run,
            "last_slot": str(data.get("last_slot") or ""),
            "last_status": str(data.get("last_status") or "never"),
            "last_report_path": str(data.get("last_report_path") or ""),
            "last_error": str(data.get("last_error") or ""),
            "last_started_at": str(data.get("last_started_at") or ""),
            "last_completed_at": str(data.get("last_completed_at") or ""),
            "updated_at": str(data.get("updated_at") or ""),
        }

    def report_schedule_snapshot(self, *, now: datetime | None = None) -> dict[str, Any]:
        return self._report_schedule_snapshot("weekly", now=now)

    def performance_schedule_snapshot(self, *, now: datetime | None = None) -> dict[str, Any]:
        return self._report_schedule_snapshot("performance", now=now)

    def _update_report_schedule(self, service: str, *, days: Any, time_hm: Any, enabled: bool) -> dict[str, Any]:
        if service not in {"weekly", "performance"}:
            raise ValueError("报告排期服务无效")
        normalized_days = self._normalize_schedule_days(days)
        normalized_time = self._normalize_schedule_time(time_hm)
        with closing(self._connect()) as db, db:
            db.execute(
                """UPDATE report_automation_schedule
                   SET enabled=?, days_json=?, time_hm=?, updated_at=?
                   WHERE service=?""",
                (1 if enabled else 0, json.dumps(normalized_days), normalized_time, _now_hkt(), service),
            )
        return self._report_schedule_snapshot(service)

    def update_report_schedule(self, *, days: Any, time_hm: Any, enabled: bool) -> dict[str, Any]:
        return self._update_report_schedule("weekly", days=days, time_hm=time_hm, enabled=enabled)

    def update_performance_schedule(self, *, days: Any, time_hm: Any, enabled: bool) -> dict[str, Any]:
        return self._update_report_schedule("performance", days=days, time_hm=time_hm, enabled=enabled)

    def report_schedule_due(self, *, now: datetime | None = None) -> dict[str, Any]:
        current = (now or datetime.now(HKT)).astimezone(HKT)
        schedule = self.report_schedule_snapshot(now=current)
        slot = f"{current.date().isoformat()}@{schedule['time']}"
        due = bool(
            schedule["enabled"]
            and current.day in schedule["days"]
            and current.strftime("%H:%M") >= schedule["time"]
            and schedule["last_slot"] != slot
        )
        return {**schedule, "due": due, "slot": slot if due else ""}

    def performance_schedule_due(self, *, now: datetime | None = None) -> dict[str, Any]:
        current = (now or datetime.now(HKT)).astimezone(HKT)
        schedule = self.performance_schedule_snapshot(now=current)
        slot = f"{current.date().isoformat()}@{schedule['time']}"
        due = bool(
            schedule["enabled"]
            and current.day in schedule["days"]
            and current.strftime("%H:%M") >= schedule["time"]
            and schedule["last_slot"] != slot
        )
        return {**schedule, "due": due, "slot": slot if due else ""}

    def _validate_weekly_delivery_artifact(self, report_path: Path) -> dict[str, Any]:
        """Fail closed unless the exact Word file has a publishable quality audit."""
        sidecar_path = Path(str(report_path) + ".quality.json")
        if not sidecar_path.exists():
            raise RuntimeError(
                f"周报发布质量门禁失败：{report_path.name} 缺少同名质量审计文件，已停止推送"
            )
        try:
            payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"周报发布质量门禁失败：{sidecar_path.name} 无法读取，已停止推送"
            ) from exc
        if not isinstance(payload, dict):
            raise RuntimeError("周报发布质量门禁失败：质量审计不是 JSON 对象，已停止推送")

        report_sha256 = hashlib.sha256(report_path.read_bytes()).hexdigest()
        if str(payload.get("reportFile") or "") != report_path.name:
            raise RuntimeError("周报发布质量门禁失败：质量审计绑定的文件名与待推送 Word 不一致")
        if str(payload.get("reportSha256") or "").lower() != report_sha256:
            raise RuntimeError("周报发布质量门禁失败：质量审计哈希与待推送 Word 不一致")
        if int(payload.get("reportBytes") or -1) != report_path.stat().st_size:
            raise RuntimeError("周报发布质量门禁失败：质量审计记录的文件大小与待推送 Word 不一致")
        if str(payload.get("reviewStatus") or "").lower() != "passed":
            raise RuntimeError("周报发布质量门禁失败：独立审稿未通过")
        if str(payload.get("generationMode") or "").lower() != "normal":
            raise RuntimeError("周报发布质量门禁失败：本轮处于受限生成模式")
        if payload.get("limitations") or payload.get("qualityWarnings"):
            raise RuntimeError("周报发布质量门禁失败：质量审计仍有局限或警告")

        items = payload.get("items")
        if not isinstance(items, list) or len(items) < WEEKLY_DELIVERY_MIN_ITEMS:
            raise RuntimeError(
                f"周报发布质量门禁失败：合格条目少于 {WEEKLY_DELIVERY_MIN_ITEMS} 篇"
            )
        if payload.get("included") != len(items):
            raise RuntimeError("周报发布质量门禁失败：质量审计条目计数不一致")
        weak_items: list[str] = []
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                weak_items.append(f"W{index:03d}")
                continue
            detail_chars = item.get("detailChars")
            detail_sentences = item.get("detailSentences")
            if (
                not isinstance(detail_chars, int)
                or isinstance(detail_chars, bool)
                or detail_chars < WEEKLY_DELIVERY_MIN_DETAIL_CHARS
                or not isinstance(detail_sentences, int)
                or isinstance(detail_sentences, bool)
                or detail_sentences < WEEKLY_DELIVERY_MIN_DETAIL_SENTENCES
            ):
                weak_items.append(str(item.get("id") or f"W{index:03d}"))
        if weak_items:
            examples = "、".join(weak_items[:8])
            suffix = "等" if len(weak_items) > 8 else ""
            raise RuntimeError(
                "周报发布质量门禁失败："
                f"{examples}{suffix} 未达到每篇至少 {WEEKLY_DELIVERY_MIN_DETAIL_CHARS} 字且 "
                f"{WEEKLY_DELIVERY_MIN_DETAIL_SENTENCES} 句完整事实的正式版标准"
            )
        try:
            report_text = self._report_text(report_path)
        except (OSError, KeyError, ValueError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
            raise RuntimeError("周报发布质量门禁失败：待推送 Word 正文无法解析") from exc
        if weekly_text_has_navigation_noise(report_text):
            raise RuntimeError(
                "周报发布质量门禁失败：正文含网页排序、导航或营销按钮噪声"
            )
        return {
            "report_sha256": report_sha256,
            "quality_sidecar": sidecar_path.name,
            "included": len(items),
            "min_detail_chars": min(int(item["detailChars"]) for item in items),
            "min_detail_sentences": min(int(item["detailSentences"]) for item in items),
        }

    def validate_selected_report(self, path: str) -> dict[str, Any]:
        """Validate the actual administrator-selected document, including legacy copies.

        This is a file-readability check, not an independent editorial approval.
        Automatic weekly publication continues to require its bound quality audit.
        """
        report_path, relative = self._resolve_report(path)
        try:
            report_text = self._report_text(report_path)
        except (OSError, KeyError, ValueError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
            raise ValueError(f"所选文件无法读取：{report_path.name}，请重新上传有效的 Word 文档") from exc
        if not report_text.strip():
            raise ValueError(f"所选文件正文为空：{report_path.name}")
        return {"path": relative, "validation": "manual_document", "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest()}

    def _validate_user_edited_weekly_artifact(self, report_path: Path) -> dict[str, Any]:
        """Allow an explicitly selected editor copy only when its formal source is auditable."""
        metadata_path = self.runtime_root / "data" / "reporting" / "report_file_metadata.json"
        try:
            metadata_payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("周报编辑稿来源校验失败：无法读取报告编辑记录，已停止推送") from exc
        if not isinstance(metadata_payload, dict):
            raise RuntimeError("周报编辑稿来源校验失败：报告编辑记录格式无效，已停止推送")

        try:
            report_key = report_path.resolve().relative_to(self.runtime_root.resolve()).as_posix()
        except ValueError as exc:
            raise RuntimeError("周报编辑稿来源校验失败：文件不在受控报告目录中") from exc
        metadata = metadata_payload.get(report_key)
        metadata = metadata if isinstance(metadata, dict) else {}
        source_key = str(metadata.get("sourcePath") or "").strip()
        if (
            not metadata.get("isEdited")
            or str(metadata.get("reportType") or "") != "weekly"
            or int(metadata.get("editorRevision") or 0) < 1
            or not source_key
            or source_key == report_key
        ):
            raise RuntimeError("周报编辑稿来源校验失败：所选文件不是页面编辑器保存的周报版本")

        source_path = (self.runtime_root / source_key).resolve()
        if self.runtime_root.resolve() not in source_path.parents or not source_path.is_file():
            raise RuntimeError("周报编辑稿来源校验失败：对应的正式源周报不存在")
        source_gate = self._validate_weekly_delivery_artifact(source_path)
        recorded_source_sha = str(metadata.get("sourceSha256") or "").lower()
        if recorded_source_sha and recorded_source_sha != source_gate["report_sha256"]:
            raise RuntimeError("周报编辑稿来源校验失败：正式源周报已变化，请重新打开并保存编辑稿")

        try:
            report_text = self._report_text(report_path)
        except (OSError, KeyError, ValueError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
            raise RuntimeError("周报编辑稿校验失败：Word 正文无法解析") from exc
        if not report_text.strip():
            raise RuntimeError("周报编辑稿校验失败：Word 正文为空")
        if weekly_text_has_navigation_noise(report_text):
            raise RuntimeError("周报编辑稿校验失败：正文含网页排序、导航或营销按钮噪声")
        return {
            **source_gate,
            "user_edited": True,
            "edited_report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
            "source_report_path": source_key,
            "editor_revision": int(metadata.get("editorRevision") or 0),
        }

    def run_due_weekly_report(self, *, now: datetime | None = None, dry_run: bool = False) -> dict[str, Any]:
        current = (now or datetime.now(HKT)).astimezone(HKT)
        due = self.report_schedule_due(now=current)
        if dry_run or not due["due"]:
            return {"ok": True, "dry_run": dry_run, **due}
        subscribers = self._subscribers_for("weekly")
        if not subscribers:
            return {
                "ok": True,
                "due": False,
                "skipped": "no_active_subscribers",
                "schedule_enabled": True,
                "slot": str(due["slot"]),
            }
        slot = str(due["slot"])
        started_at = _now_hkt()
        with closing(self._connect()) as db, db:
            cursor = db.execute(
                """UPDATE report_automation_schedule
                   SET last_slot=?, last_status='running', last_error='', last_started_at=?, updated_at=?
                   WHERE service='weekly' AND last_slot<>?""",
                (slot, started_at, started_at, slot),
            )
        if cursor.rowcount != 1:
            return {"ok": True, "due": False, "skipped": "already_claimed", "slot": slot}
        try:
            existing_reports = {
                path.resolve(): path.stat().st_mtime_ns
                for path in self.runtime_root.glob("*.docx")
                if "周报" in path.name
                and "业绩摘要" not in path.name
                and "template" not in path.name.lower()
                and not path.name.startswith("~$")
            }
            process = self._run(
                [sys.executable, str(self.runtime_root / "generate_weekly_report.py")],
                timeout=2400,
            )
            if process.returncode != 0:
                detail = (process.stderr or process.stdout or "周报生成失败").strip()[-1200:]
                raise RuntimeError(detail)
            candidates = [
                path for path in self.runtime_root.glob("*.docx")
                if "周报" in path.name
                and "业绩摘要" not in path.name
                and "template" not in path.name.lower()
                and not path.name.startswith("~$")
                and (
                    path.resolve() not in existing_reports
                    or path.stat().st_mtime_ns > existing_reports[path.resolve()]
                )
            ]
            if not candidates:
                raise RuntimeError("周报生成完成但未找到本轮新生成的当天 Word 周报，已停止推送")
            report_path = max(candidates, key=lambda item: (item.stat().st_mtime_ns, item.name))
            relative_path = report_path.relative_to(self.runtime_root).as_posix()
            quality_gate = self._validate_weekly_delivery_artifact(report_path)
            if any(item.get("report_mode") in {"audio", "pdf_audio"} for item in subscribers):
                try:
                    from tts_service import synthesize_report_audio

                    audio_result = synthesize_report_audio(report_path, force=False)
                    if not audio_result.get("ok", True):
                        raise RuntimeError(str(audio_result.get("error") or "周报语音生成失败"))
                except Exception as exc:
                    raise RuntimeError(f"周报已生成，但订阅语音生成失败：{exc}") from exc
            rechecked_quality_gate = self._validate_weekly_delivery_artifact(report_path)
            if rechecked_quality_gate["report_sha256"] != quality_gate["report_sha256"]:
                raise RuntimeError("周报发布质量门禁失败：语音生成期间 Word 已变化，已停止推送")
            delivery = self.push(
                service="weekly",
                mode="pdf_audio",
                path=relative_path,
                confirm_bulk=True,
                queue_failures=True,
                batch_key=f"weekly-schedule:{slot}:{quality_gate['report_sha256']}",
            )
            final_status = "queued" if delivery["queued_count"] else "verified"
            completed_at = _now_hkt()
            with closing(self._connect()) as db, db:
                db.execute(
                    """UPDATE report_automation_schedule
                       SET last_status=?, last_report_path=?, last_error='', last_completed_at=?, updated_at=?
                       WHERE service='weekly' AND last_slot=?""",
                    (final_status, relative_path, completed_at, completed_at, slot),
                )
            return {
                "ok": True,
                "slot": slot,
                "status": final_status,
                "report_path": relative_path,
                "quality_gate": quality_gate,
                "delivery": delivery,
            }
        except Exception as exc:
            completed_at = _now_hkt()
            with closing(self._connect()) as db, db:
                db.execute(
                    """UPDATE report_automation_schedule
                       SET last_status='failed', last_error=?, last_completed_at=?, updated_at=?
                       WHERE service='weekly' AND last_slot=?""",
                    (str(exc)[:1200], completed_at, completed_at, slot),
                )
            return {"ok": False, "slot": slot, "status": "failed", "error": str(exc)[:1200]}

    def run_due_performance_report(self, *, now: datetime | None = None, dry_run: bool = False) -> dict[str, Any]:
        """Deliver the selected performance summary, or the newest formal version, once per saved slot."""
        current = (now or datetime.now(HKT)).astimezone(HKT)
        due = self.performance_schedule_due(now=current)
        if dry_run or not due["due"]:
            return {"ok": True, "dry_run": dry_run, **due}
        subscribers = self._subscribers_for("performance")
        if not subscribers:
            return {
                "ok": True,
                "due": False,
                "skipped": "no_active_subscribers",
                "schedule_enabled": True,
                "slot": str(due["slot"]),
            }
        slot = str(due["slot"])
        started_at = _now_hkt()
        with closing(self._connect()) as db, db:
            cursor = db.execute(
                """UPDATE report_automation_schedule
                   SET last_slot=?, last_status='running', last_error='', last_started_at=?, updated_at=?
                   WHERE service='performance' AND last_slot<>?""",
                (slot, started_at, started_at, slot),
            )
        if cursor.rowcount != 1:
            return {"ok": True, "due": False, "skipped": "already_claimed", "slot": slot}
        try:
            preferred_path = str(self.performance_report_preference().get("path") or "")
            report_path: Path | None = None
            if preferred_path:
                try:
                    preferred, _ = self._resolve_report(preferred_path)
                    if "业绩摘要" not in preferred.name:
                        raise ValueError("所选文件不是业绩摘要")
                    report_path = preferred
                except ValueError:
                    self.update_performance_report_preference("")
            if report_path is None:
                candidates = [
                    path for path in self.runtime_root.glob("*.docx")
                    if "业绩摘要" in path.name
                    and "编辑稿" not in path.name
                    and "template" not in path.name.lower()
                    and not path.name.startswith("~$")
                ]
                if not candidates:
                    raise RuntimeError("当前没有可供定时推送的业绩摘要")
                report_path = max(candidates, key=lambda item: (item.stat().st_mtime_ns, item.name))
            relative_path = report_path.relative_to(self.runtime_root.resolve()).as_posix()
            if any(item.get("report_mode") in {"audio", "pdf_audio"} for item in subscribers):
                try:
                    from tts_service import synthesize_report_audio

                    audio_result = synthesize_report_audio(report_path, force=False)
                    if not audio_result.get("ok", True):
                        raise RuntimeError(str(audio_result.get("error") or "业绩摘要语音生成失败"))
                except Exception as exc:
                    raise RuntimeError(f"业绩摘要语音准备失败：{exc}") from exc
            delivery = self.push(
                service="performance",
                mode="pdf_audio",
                path=relative_path,
                confirm_bulk=True,
                queue_failures=True,
                batch_key=f"performance-schedule:{slot}:{hashlib.sha256(report_path.read_bytes()).hexdigest()}",
            )
            final_status = "queued" if delivery["queued_count"] else "verified"
            completed_at = _now_hkt()
            with closing(self._connect()) as db, db:
                db.execute(
                    """UPDATE report_automation_schedule
                       SET last_status=?, last_report_path=?, last_error='', last_completed_at=?, updated_at=?
                       WHERE service='performance' AND last_slot=?""",
                    (final_status, relative_path, completed_at, completed_at, slot),
                )
            return {
                "ok": True,
                "slot": slot,
                "status": final_status,
                "report_path": relative_path,
                "selection": "manual" if preferred_path and relative_path == preferred_path else "automatic",
                "delivery": delivery,
            }
        except Exception as exc:
            completed_at = _now_hkt()
            with closing(self._connect()) as db, db:
                db.execute(
                    """UPDATE report_automation_schedule
                       SET last_status='failed', last_error=?, last_completed_at=?, updated_at=?
                       WHERE service='performance' AND last_slot=?""",
                    (str(exc)[:1200], completed_at, completed_at, slot),
                )
            return {"ok": False, "slot": slot, "status": "failed", "error": str(exc)[:1200]}

    def invitation_permission_snapshot(self) -> dict[str, Any]:
        app_id = str((self.config.get("bot") or {}).get("app_id") or self.entry_profile)
        with closing(self._connect()) as db:
            directory = db.execute(
                """SELECT COUNT(*) AS people_count, MAX(synced_at) AS synced_at
                   FROM subscription_directory_people WHERE active=1"""
            ).fetchone()
        people_count = int(directory["people_count"] or 0) if directory else 0
        return {
            "mode": "authorized_directory",
            "status": "ready" if self.directory_profile and people_count > 0 else "limited",
            "summary": "通过已授权的飞书通讯录应用搜索姓名并显示头像；只有授权范围内且可由推送应用解析的人员才能被邀请。",
            "required_scopes": [
                {"scope": "contact:user.base:readonly", "purpose": "回读姓名、open_id 与 union_id", "level": "required"},
                {"scope": "im:message:send_as_bot", "purpose": "逐人发送订阅邀请卡片", "level": "required"},
                {"scope": "contact:contact.base:readonly", "purpose": "从限定通讯录范围读取候选人", "level": "recommended"},
            ],
            "not_requested": ["contact:contact:access_as_app", "任何通讯录写权限"],
            "availability_note": "应用可用范围与通讯录权限范围都必须包含受邀人；后台不会越过任一范围。",
            "directory_profile": self.directory_profile,
            "people_count": people_count,
            "synced_at": str(directory["synced_at"] or "") if directory else "",
            "console_url": f"https://open.feishu.cn/app/{app_id}/permission" if app_id else "",
            "updated_at": _now_hkt(),
        }

    def _directory_get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        return self._lark([
            "lark-cli", "api", "GET", path,
            "--params", json.dumps(params, ensure_ascii=False),
            "--as", "bot", "--profile", self.directory_profile, "--format", "json",
        ], timeout=60)

    def refresh_people_directory(self) -> dict[str, Any]:
        departments: dict[str, str] = {}
        page_token = ""
        for _ in range(20):
            params: dict[str, Any] = {
                "department_id_type": "open_department_id",
                "fetch_child": True,
                "page_size": 50,
            }
            if page_token:
                params["page_token"] = page_token
            payload = self._directory_get("/open-apis/contact/v3/departments/0/children", params)
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            for item in data.get("items") or []:
                if not isinstance(item, dict):
                    continue
                status = item.get("status") if isinstance(item.get("status"), dict) else {}
                name = str(item.get("name") or "").strip()
                department_id = str(item.get("open_department_id") or "")
                if (
                    department_id.startswith("od-")
                    and name
                    and int(item.get("member_count") or 0) > 0
                    and not status.get("is_deleted")
                    and "已撤销" not in name
                ):
                    departments[department_id] = name
            if not data.get("has_more"):
                break
            page_token = str(data.get("page_token") or "")
            if not page_token:
                break

        people: dict[str, dict[str, Any]] = {}
        for department_id, department_name in departments.items():
            page_token = ""
            for _ in range(30):
                params = {
                    "department_id": department_id,
                    "department_id_type": "open_department_id",
                    "user_id_type": "open_id",
                    "page_size": 50,
                }
                if page_token:
                    params["page_token"] = page_token
                payload = self._directory_get("/open-apis/contact/v3/users/find_by_department", params)
                data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                for user in data.get("items") or []:
                    if not isinstance(user, dict):
                        continue
                    open_id = str(user.get("open_id") or "")
                    union_id = str(user.get("union_id") or "")
                    name = str(user.get("name") or user.get("en_name") or "").strip()[:120]
                    if not OPEN_ID_RE.fullmatch(open_id) or not union_id.startswith("on_") or not name:
                        continue
                    avatar = user.get("avatar") if isinstance(user.get("avatar"), dict) else {}
                    record = people.setdefault(open_id, {
                        "directory_open_id": open_id,
                        "union_id": union_id,
                        "display_name": name,
                        "en_name": str(user.get("en_name") or "")[:120],
                        "enterprise_email": str(
                            user.get("enterprise_email") or user.get("email") or ""
                        ).strip().lower()[:240],
                        "avatar_url": str(avatar.get("avatar_72") or avatar.get("avatar_240") or ""),
                        "job_title": str(user.get("job_title") or "")[:160],
                        "department_names": set(),
                    })
                    record["department_names"].add(department_name)
                if not data.get("has_more"):
                    break
                page_token = str(data.get("page_token") or "")
                if not page_token:
                    break

        now = _now_hkt()
        with closing(self._connect()) as db, db:
            db.execute("UPDATE subscription_directory_people SET active=0")
            for person in people.values():
                department_names = sorted(person["department_names"])
                job_title = str(person["job_title"] or "").strip()
                db.execute(
                    """INSERT INTO subscription_directory_people(
                           directory_open_id, union_id, display_name, en_name, enterprise_email, avatar_url,
                           job_title, department_names, source_profile, active, synced_at
                       ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                       ON CONFLICT(directory_open_id) DO UPDATE SET
                           union_id=excluded.union_id, display_name=excluded.display_name,
                           en_name=excluded.en_name, enterprise_email=excluded.enterprise_email,
                           avatar_url=excluded.avatar_url,
                           job_title=excluded.job_title, department_names=excluded.department_names,
                           source_profile=excluded.source_profile, active=1, synced_at=excluded.synced_at""",
                    (
                        person["directory_open_id"], person["union_id"], person["display_name"],
                        person["en_name"], person["enterprise_email"], person["avatar_url"], job_title,
                        json.dumps(department_names, ensure_ascii=False), self.directory_profile, now,
                    ),
                )
        return {"people_count": len(people), "department_count": len(departments), "synced_at": now}

    def search_people_directory(self, query: str, *, limit: int = 30) -> list[dict[str, Any]]:
        needle = str(query or "").strip()
        if not needle or len(needle) > 50:
            raise ValueError("请输入 1 至 50 个字符的姓名关键字")
        pattern = f"%{needle.replace('%', '').replace('_', '')}%"
        with closing(self._connect()) as db:
            rows = db.execute(
                """SELECT directory_open_id, union_id, display_name, en_name, enterprise_email, avatar_url,
                          job_title, department_names, source_profile, synced_at
                   FROM subscription_directory_people
                   WHERE active=1 AND (display_name LIKE ? OR en_name LIKE ? OR enterprise_email LIKE ?)
                   ORDER BY display_name LIMIT ?""",
                (pattern, pattern, pattern, max(1, min(int(limit), 50))),
            ).fetchall()
        return [dict(row) | {"department_names": json.loads(row["department_names"] or "[]")} for row in rows]

    def search_chat_directory(self, query: str, *, limit: int = 30) -> list[dict[str, Any]]:
        """Search normal group chats visible to the delivery bot."""
        needle = str(query or "").strip()
        if not needle or len(needle) > 50:
            raise ValueError("请输入 1 至 50 个字符的检索关键字")
        needle_folded = needle.casefold()
        matches: list[dict[str, Any]] = []
        page_token = ""
        for _ in range(20):
            params: dict[str, Any] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            payload = self._lark([
                "lark-cli", "api", "GET", "/open-apis/im/v1/chats",
                "--params", json.dumps(params, ensure_ascii=False),
                "--as", "bot", "--profile", self.delivery_profile, "--format", "json",
            ], timeout=60)
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            for item in data.get("items") or []:
                if not isinstance(item, dict):
                    continue
                chat_id = str(item.get("chat_id") or "")
                name = str(item.get("name") or "").strip()[:160]
                description = str(item.get("description") or "").strip()[:300]
                if (
                    not CHAT_ID_RE.fullmatch(chat_id)
                    or str(item.get("chat_mode") or "") != "group"
                    or str(item.get("chat_status") or "") != "normal"
                    or not name
                    or needle_folded not in f"{name}\n{description}".casefold()
                ):
                    continue
                matches.append({
                    "chat_id": chat_id,
                    "name": name,
                    "description": description,
                    "external": bool(item.get("external")),
                })
            if len(matches) >= limit or not data.get("has_more"):
                break
            page_token = str(data.get("page_token") or "")
            if not page_token:
                break
        return sorted(
            matches,
            key=lambda item: (
                not str(item["name"]).casefold().startswith(needle_folded),
                str(item["name"]).casefold(),
            ),
        )[:max(1, min(int(limit), 50))]

    def resolve_chat_target(self, chat_id: str) -> dict[str, Any]:
        """Resolve one live group from the delivery bot's current visible-chat scope."""
        if not CHAT_ID_RE.fullmatch(str(chat_id)):
            raise ValueError("目标群ID无效")
        page_token = ""
        for _ in range(20):
            params: dict[str, Any] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            payload = self._lark([
                "lark-cli", "api", "GET", "/open-apis/im/v1/chats",
                "--params", json.dumps(params, ensure_ascii=False),
                "--as", "bot", "--profile", self.delivery_profile, "--format", "json",
            ], timeout=60)
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            for item in data.get("items") or []:
                if not isinstance(item, dict) or str(item.get("chat_id") or "") != chat_id:
                    continue
                name = str(item.get("name") or "").strip()[:160]
                if (
                    str(item.get("chat_mode") or "") != "group"
                    or str(item.get("chat_status") or "") != "normal"
                    or not name
                ):
                    raise ValueError("目标群当前不可用")
                return {
                    "chat_id": chat_id,
                    "name": name,
                    "description": str(item.get("description") or "").strip()[:300],
                    "external": bool(item.get("external")),
                }
            if not data.get("has_more"):
                break
            page_token = str(data.get("page_token") or "")
            if not page_token:
                break
        raise ValueError("目标群不在推送应用当前可见范围")

    def avatar_source_url(self, open_id: str) -> str:
        if not OPEN_ID_RE.fullmatch(str(open_id)):
            raise ValueError("飞书头像身份无效")
        with closing(self._connect()) as db:
            row = db.execute(
                """SELECT avatar_url FROM subscription_directory_people
                   WHERE active=1 AND avatar_url<>'' AND (directory_open_id=? OR (union_id<>'' AND union_id IN (
                       SELECT union_id FROM subscribers WHERE open_id=? OR callback_open_id=?
                       UNION SELECT union_id FROM subscription_invite_candidates
                       WHERE callback_open_id=? OR delivery_open_id=?
                   ))) ORDER BY synced_at DESC LIMIT 1""",
                (open_id, open_id, open_id, open_id, open_id),
            ).fetchone()
            url = str(row["avatar_url"] or "") if row else ""
            if not url:
                row = db.execute(
                    """SELECT avatar_url FROM subscription_invite_candidates
                       WHERE avatar_url<>'' AND (callback_open_id=? OR delivery_open_id=?)
                       ORDER BY updated_at DESC LIMIT 1""",
                    (open_id, open_id),
                ).fetchone()
                url = str(row["avatar_url"] or "") if row else ""
            if not url:
                row = db.execute(
                    """SELECT avatar_url FROM subscription_group_responses
                       WHERE avatar_url<>'' AND (callback_open_id=? OR delivery_open_id=?)
                       ORDER BY updated_at DESC LIMIT 1""",
                    (open_id, open_id),
                ).fetchone()
                url = str(row["avatar_url"] or "") if row else ""
        if not url.startswith("https://") or "feishucdn.com/" not in url:
            raise ValueError("该人员没有可用的飞书头像")
        return url

    def add_directory_candidates(self, directory_open_ids: list[str]) -> dict[str, Any]:
        normalized = list(dict.fromkeys(str(item) for item in directory_open_ids))
        if not normalized or len(normalized) > 30:
            raise ValueError("每次请选择 1 至 30 位候选人")
        placeholders = ",".join("?" for _ in normalized)
        with closing(self._connect()) as db:
            rows = db.execute(
                f"""SELECT * FROM subscription_directory_people
                     WHERE active=1 AND directory_open_id IN ({placeholders})""",
                normalized,
            ).fetchall()
        if len(rows) != len(normalized):
            raise ValueError("候选人不在当前飞书通讯录授权范围，请刷新后重试")
        now = _now_hkt()
        with closing(self._connect()) as db, db:
            for row in rows:
                directory_open_id = str(row["directory_open_id"])
                union_id = str(row["union_id"])
                if self.directory_profile == self.delivery_profile:
                    delivery_open_id = directory_open_id
                else:
                    payload = self._lark([
                        "lark-cli", "contact", "+get-user", "--user-id", union_id,
                        "--user-id-type", "union_id", "--as", "bot", "--profile", self.delivery_profile,
                        "--format", "json",
                    ])
                    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                    user = data.get("user") if isinstance(data.get("user"), dict) else {}
                    delivery_open_id = str(user.get("open_id") or "")
                if not OPEN_ID_RE.fullmatch(delivery_open_id):
                    raise RuntimeError(f"推送应用无法解析候选人：{row['display_name']}")
                db.execute(
                    """INSERT INTO subscription_invite_candidates(
                           callback_open_id, delivery_open_id, union_id, display_name,
                           source_profile, avatar_url, department_names, job_title, source, created_at, updated_at
                       ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'directory', ?, ?)
                       ON CONFLICT(callback_open_id) DO UPDATE SET
                           delivery_open_id=excluded.delivery_open_id, union_id=excluded.union_id,
                           display_name=excluded.display_name, source_profile=excluded.source_profile,
                           avatar_url=excluded.avatar_url, department_names=excluded.department_names,
                           job_title=excluded.job_title, source='directory', updated_at=excluded.updated_at""",
                    (
                        directory_open_id, delivery_open_id, union_id, str(row["display_name"]),
                        str(row["source_profile"]), str(row["avatar_url"]), str(row["department_names"]),
                        str(row["job_title"]), now, now,
                    ),
                )
        return {"added_count": len(rows), "candidates": self.list_invite_candidates()}

    def list_invite_candidates(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as db:
            rows = db.execute(
                """SELECT callback_open_id, delivery_open_id, union_id, display_name, source_profile,
                          avatar_url, department_names, job_title, source, created_at, updated_at
                   FROM subscription_invite_candidates ORDER BY display_name, callback_open_id"""
            ).fetchall()
            subscribers = db.execute(
                """SELECT callback_open_id, open_id AS delivery_open_id, union_id, display_name,
                          created_at, updated_at
                   FROM subscribers WHERE callback_open_id<>''"""
            ).fetchall()
        merged: dict[str, dict[str, Any]] = {
            str(row["callback_open_id"]): dict(row) | {
                "department_names": json.loads(row["department_names"] or "[]")
            }
            for row in rows
        }
        for row in subscribers:
            key = str(row["callback_open_id"])
            merged.setdefault(key, dict(row) | {
                "source": "subscriber", "source_profile": self.entry_profile,
                "avatar_url": "", "department_names": [], "job_title": "",
            })
        deduplicated: dict[str, dict[str, Any]] = {}
        for candidate in merged.values():
            identity_key = str(candidate.get("union_id") or candidate["callback_open_id"])
            existing = deduplicated.get(identity_key)
            if existing is None or (
                candidate.get("source") == "directory" and existing.get("source") != "directory"
            ):
                deduplicated[identity_key] = candidate
        merged = {str(item["callback_open_id"]): item for item in deduplicated.values()}
        with closing(self._connect()) as db:
            for candidate in merged.values():
                directory = db.execute(
                    """SELECT directory_open_id, avatar_url, department_names, job_title
                       FROM subscription_directory_people
                       WHERE active=1 AND (directory_open_id=? OR (union_id<>'' AND union_id=?))
                       ORDER BY synced_at DESC LIMIT 1""",
                    (candidate["callback_open_id"], str(candidate.get("union_id") or "")),
                ).fetchone()
                if directory:
                    candidate["directory_open_id"] = str(directory["directory_open_id"])
                    candidate["avatar_url"] = str(directory["avatar_url"] or candidate.get("avatar_url") or "")
                    candidate["department_names"] = json.loads(directory["department_names"] or "[]")
                    candidate["job_title"] = str(directory["job_title"] or candidate.get("job_title") or "")
                if not candidate.get("avatar_url"):
                    response = db.execute(
                        """SELECT avatar_url FROM subscription_group_responses
                           WHERE avatar_url<>'' AND (callback_open_id=? OR delivery_open_id=?)
                           ORDER BY updated_at DESC LIMIT 1""",
                        (candidate["callback_open_id"], candidate.get("delivery_open_id", "")),
                    ).fetchone()
                    if response:
                        candidate["avatar_url"] = str(response["avatar_url"])
                personal = db.execute(
                    """SELECT status, sent_at, responded_at, updated_at, message_id, last_error,
                              'personal' AS response_source
                       FROM subscription_invitations
                       WHERE callback_open_id=? ORDER BY id DESC LIMIT 1""",
                    (candidate["callback_open_id"],),
                ).fetchone()
                group_response = db.execute(
                    """SELECT r.status, c.created_at AS sent_at, r.responded_at, r.updated_at,
                              r.message_id, r.last_error, 'group' AS response_source,
                              c.target_id AS source_chat_id, c.target_name AS source_chat_name
                       FROM subscription_group_responses r
                       JOIN subscription_entry_cards c ON c.message_id=r.message_id
                       LEFT JOIN subscribers s ON s.open_id=r.delivery_open_id
                       WHERE c.target_type='chat' AND (
                           r.callback_open_id=? OR r.delivery_open_id=?
                           OR (?<>'' AND COALESCE(NULLIF(r.union_id, ''), s.union_id)=?)
                       )
                       ORDER BY r.updated_at DESC LIMIT 1""",
                    (
                        str(candidate.get("callback_open_id") or ""),
                        str(candidate.get("delivery_open_id") or ""),
                        str(candidate.get("union_id") or ""),
                        str(candidate.get("union_id") or ""),
                    ),
                ).fetchone()
                response_candidates = [
                    dict(row) for row in (personal, group_response)
                    if row is not None and str(row["responded_at"] or "")
                ]
                if response_candidates:
                    latest = max(
                        response_candidates,
                        key=lambda item: str(item.get("updated_at") or item.get("responded_at") or ""),
                    )
                else:
                    latest = dict(personal) if personal else None
                candidate["latest_invitation"] = latest
        return sorted(merged.values(), key=lambda item: (str(item["display_name"]).casefold(), str(item["callback_open_id"])))

    def register_invite_candidate(self, callback_open_id: str) -> dict[str, Any]:
        identity = self.resolve_user(callback_open_id)
        now = _now_hkt()
        with closing(self._connect()) as db, db:
            db.execute(
                """INSERT INTO subscription_invite_candidates(
                       callback_open_id, delivery_open_id, union_id, display_name,
                       source_profile, avatar_url, source, created_at, updated_at
                   ) VALUES(?, ?, ?, ?, ?, ?, 'admin_resolved', ?, ?)
                   ON CONFLICT(callback_open_id) DO UPDATE SET
                       delivery_open_id=excluded.delivery_open_id, union_id=excluded.union_id,
                       display_name=excluded.display_name, source_profile=excluded.source_profile,
                       avatar_url=excluded.avatar_url, updated_at=excluded.updated_at""",
                (
                    identity["callback_open_id"], identity["open_id"], identity["union_id"],
                    identity["display_name"], identity["source_profile"], identity["avatar_url"], now, now,
                ),
            )
        return dict(identity) | {"registered": True, "updated_at": now}

    def invite_users(
        self,
        callback_open_ids: list[str],
        *,
        confirm_invite: bool = False,
        invited_by: str = "local_admin",
    ) -> dict[str, Any]:
        if not confirm_invite:
            raise ValueError("发送订阅邀请需要管理员二次确认")
        normalized = list(dict.fromkeys(str(item) for item in callback_open_ids))
        if not normalized or len(normalized) > 30:
            raise ValueError("每次请选择 1 至 30 位受邀人")
        candidates = {item["callback_open_id"]: item for item in self.list_invite_candidates()}
        unknown = [item for item in normalized if item not in candidates]
        if unknown:
            raise ValueError("受邀人不在已解析的受控名单，请先读取并加入候选人")
        results = []
        for callback_open_id in normalized:
            candidate = candidates[callback_open_id]
            try:
                source_profile = str(candidate.get("source_profile") or self.entry_profile)
                with closing(self._connect()) as db:
                    directory_row = db.execute(
                        "SELECT en_name FROM subscription_directory_people WHERE union_id=? AND active=1 LIMIT 1",
                        (str(candidate.get("union_id") or ""),),
                    ).fetchone()
                directory_name = str(directory_row["en_name"] or "").strip() if directory_row else ""
                source_name = directory_name or str(candidate.get("display_name") or "")
                english_name = " ".join(re.findall(r"[A-Za-z]+(?:['-][A-Za-z]+)*", source_name))
                recipient_name = english_name or str(candidate.get("display_name") or "同事")
                sent = self._send_entry_card_to_user(
                    callback_open_id,
                    invitation=True,
                    profile=source_profile,
                    recipient_name=recipient_name,
                )
                now = _now_hkt()
                with closing(self._connect()) as db, db:
                    db.execute(
                        """INSERT INTO subscription_invitations(
                               callback_open_id, delivery_open_id, union_id, display_name,
                               source_profile, avatar_url, message_id, chat_id,
                               status, invited_by, sent_at, updated_at
                           ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
                        (
                            callback_open_id, str(candidate["delivery_open_id"]), str(candidate["union_id"]),
                            str(candidate["display_name"]), source_profile, str(candidate.get("avatar_url") or ""),
                            sent["message_id"], sent["chat_id"],
                            invited_by[:120], now, now,
                        ),
                    )
                results.append(dict(sent) | {"callback_open_id": callback_open_id, "display_name": candidate["display_name"], "status": "pending"})
            except Exception as exc:
                now = _now_hkt()
                error = str(exc)[:1200]
                failed_id = "failed_" + hashlib.sha256(
                    f"{callback_open_id}:{now}:{error}".encode()
                ).hexdigest()[:24]
                with closing(self._connect()) as db, db:
                    db.execute(
                        """INSERT INTO subscription_invitations(
                               callback_open_id, delivery_open_id, union_id, display_name,
                               source_profile, avatar_url, message_id, chat_id,
                               status, invited_by, sent_at, last_error, updated_at
                           ) VALUES(?, ?, ?, ?, ?, ?, ?, '', 'failed', ?, ?, ?, ?)""",
                        (
                            callback_open_id, str(candidate["delivery_open_id"]), str(candidate["union_id"]),
                            str(candidate["display_name"]), str(candidate.get("source_profile") or self.entry_profile),
                            str(candidate.get("avatar_url") or ""), failed_id, invited_by[:120], now, error, now,
                        ),
                    )
                results.append({"callback_open_id": callback_open_id, "display_name": candidate["display_name"], "status": "failed", "error": error})
        return {
            "requested_count": len(normalized),
            "sent_count": sum(1 for item in results if item["status"] == "pending"),
            "failed_count": sum(1 for item in results if item["status"] == "failed"),
            "results": results,
        }

    def invite_target(
        self,
        target_id: str,
        *,
        target_type: str = "",
        confirm_invite: bool = False,
    ) -> dict[str, Any]:
        """Send an invitation after deriving person/group mode from the target ID."""
        if not confirm_invite:
            raise ValueError("发送订阅邀请需要管理员二次确认")
        normalized_id = str(target_id or "").strip()
        inferred_type = str(target_type or "").strip()
        if not inferred_type:
            if CHAT_ID_RE.fullmatch(normalized_id):
                inferred_type = "chat"
            elif OPEN_ID_RE.fullmatch(normalized_id):
                inferred_type = "user"
        if inferred_type == "user":
            result = self.invite_users(
                [normalized_id],
                confirm_invite=True,
                invited_by="local_admin",
            )
            return {"target_type": "user", "target_id": normalized_id, **result}
        if inferred_type != "chat":
            raise ValueError("无法判断邀请目标是个人还是群聊")
        chat = self.resolve_chat_target(normalized_id)
        sent = self._send_entry_card(
            target_id=normalized_id,
            target_type="chat",
            key_context="invite-group",
            profile=self.delivery_profile,
            target_name=chat["name"],
        )
        return {
            **sent,
            "target_name": chat["name"],
            "external": chat["external"],
            "status": "pending",
        }

    def reset_subscriber(self, open_id: str) -> dict[str, Any]:
        with closing(self._connect()) as db:
            row = db.execute("SELECT default_preferences FROM subscribers WHERE open_id=?", (open_id,)).fetchone()
        if row is None:
            raise ValueError("订阅者不存在")
        defaults = json.loads(row["default_preferences"])
        if not defaults.get("services"):
            raise ValueError("该订阅者尚无可恢复的默认选项")
        return self.update_subscriber(open_id, **defaults)

    def update_subscriber(
        self,
        open_id: str,
        *,
        services: list[str],
        status: str = "active",
        frequency: str = "once_daily",
        report_mode: str = "pdf",
        news_item_limit: int = 10,
        news_categories: Any = None,
        news_region_preference: str | None = None,
        news_delivery_times: Any = None,
        news_topics: Any = None,
    ) -> dict[str, Any]:
        if status not in {"active", "paused"}:
            raise ValueError("订阅者状态只能是 active 或 paused")
        with closing(self._connect()) as db, db:
            row = db.execute(
                "SELECT display_name, source_chat_id, callback_open_id, union_id, news_categories, news_delivery_times FROM subscribers WHERE open_id=?",
                (open_id,),
            ).fetchone()
        if row is None:
            raise ValueError("订阅者不存在")
        with closing(self._connect()) as db, db:
            current = db.execute("SELECT * FROM subscribers WHERE open_id=?", (open_id,)).fetchone()
            if current["default_preferences"] == "{}":
                defaults = {key: current[key] for key in ("status", "frequency", "report_mode", "news_item_limit", "news_region_preference")}
                defaults["services"] = [r[0] for r in db.execute("SELECT service FROM subscriptions WHERE open_id=? AND active=1", (open_id,))]
                defaults["news_categories"] = normalize_news_categories(current["news_categories"])
                defaults["news_topics"] = normalize_news_topics(current["news_topics"])
                defaults["news_delivery_times"] = _normalize_news_delivery_times(current["news_delivery_times"])
                db.execute("UPDATE subscribers SET default_preferences=? WHERE open_id=?", (json.dumps(defaults, ensure_ascii=False), open_id))
        result = self.save_subscriptions(
            open_id,
            str(row["display_name"]),
            services,
            str(row["source_chat_id"]),
            callback_open_id=str(row["callback_open_id"]),
            union_id=str(row["union_id"]),
            frequency=frequency,
            report_mode=report_mode,
            news_item_limit=news_item_limit,
            news_region_preference=news_region_preference,
            record_original_categories=False,
            news_topics=news_topics,
            news_categories=(
                news_categories
                if news_categories is not None
                else normalize_news_categories(row["news_categories"])
            ),
            news_delivery_times=(
                news_delivery_times
                if news_delivery_times is not None
                else _normalize_news_delivery_times(row["news_delivery_times"])
            ),
        )
        with closing(self._connect()) as db, db:
            db.execute("UPDATE subscribers SET status=?, updated_at=? WHERE open_id=?", (status, _now_hkt(), open_id))
        result["status"] = status
        return result

    def available_targets(self) -> list[dict[str, str]]:
        targets = []
        for item in self.config.get("targets") or []:
            if not isinstance(item, dict) or item.get("role") == "incident":
                continue
            chat_id = str(item.get("chat_id") or "")
            if CHAT_ID_RE.fullmatch(chat_id):
                targets.append({"chat_id": chat_id, "name": str(item.get("expected_name") or chat_id), "role": str(item.get("role") or "")})
        return targets

    def publish_entry_card(self, *, target_id: str, target_type: str = "chat") -> dict[str, Any]:
        if target_type == "chat":
            allowed = {item["chat_id"] for item in self.available_targets()}
            if target_id not in allowed:
                raise ValueError("目标群不在订阅入口发布白名单")
            target_args = ["--chat-id", target_id]
        elif target_type == "user":
            primary = str(((self.config.get("card_actions") or {}).get("primary_handler_open_id") or ""))
            subscriptions = self.config.get("subscriptions") if isinstance(self.config.get("subscriptions"), dict) else {}
            delivery_primary = str(subscriptions.get("primary_delivery_open_id") or "")
            if target_id not in {primary, delivery_primary} or not OPEN_ID_RE.fullmatch(delivery_primary):
                raise ValueError("测试卡片只允许发送给系统管理员")
            target_id = delivery_primary
            target_args = ["--user-id", target_id]
        else:
            raise ValueError("目标类型无效")
        return self._send_entry_card(target_id=target_id, target_type=target_type)

    def _send_entry_card_to_user(
        self,
        callback_open_id: str,
        *,
        invitation: bool = False,
        profile: str = "",
        recipient_name: str = "",
    ) -> dict[str, Any]:
        if not OPEN_ID_RE.fullmatch(callback_open_id):
            raise ValueError("受邀人 open_id 无效")
        return self._send_entry_card(
            target_id=callback_open_id,
            target_type="user",
            key_context="invite" if invitation else "test",
            profile=profile or self.entry_profile,
            recipient_name=recipient_name,
        )

    def _send_entry_card(
        self,
        *,
        target_id: str,
        target_type: str,
        key_context: str = "publish",
        profile: str = "",
        recipient_name: str = "",
        target_name: str = "",
    ) -> dict[str, Any]:
        source_profile = profile or self.delivery_profile
        if target_type == "chat":
            if not CHAT_ID_RE.fullmatch(target_id):
                raise ValueError("目标群ID无效")
            target_args = ["--chat-id", target_id]
        elif target_type == "user":
            if not OPEN_ID_RE.fullmatch(target_id):
                raise ValueError("目标用户 open_id 无效")
            target_args = ["--user-id", target_id]
        else:
            raise ValueError("目标类型无效")
        subscriptions = self.config.get("subscriptions") if isinstance(self.config.get("subscriptions"), dict) else {}
        poster_keys = subscriptions.get("poster_image_keys") if isinstance(subscriptions.get("poster_image_keys"), dict) else {}
        image_key = str(poster_keys.get(source_profile) or poster_keys.get("default") or "")
        card = subscription_entry_card(
            image_key=image_key,
            recipient_name=recipient_name,
            report_schedule=self.report_schedule_snapshot(),
            performance_schedule=self.performance_schedule_snapshot(),
        )
        card = without_markdown_bold_markers(card)
        card_version = hashlib.sha256(
            json.dumps(card, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()[:12]
        key = hashlib.sha256(
            f"subscription-entry:{key_context}:{target_type}:{target_id}:{datetime.now().isoformat(timespec='microseconds')}:{card_version}".encode()
        ).hexdigest()[:32]
        payload = self._lark([
            "lark-cli", "im", "+messages-send", *target_args,
            "--msg-type", "interactive", "--content", json.dumps(card, ensure_ascii=False, separators=(",", ":")),
            "--idempotency-key", key, "--as", "bot", "--profile", source_profile, "--format", "json",
        ])
        message_id = self._message_id(payload)
        self._verify_message(message_id, profile=source_profile)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        chat_id = str(data.get("chat_id") or "")
        if not CHAT_ID_RE.fullmatch(chat_id):
            raise RuntimeError("订阅卡片发送成功但没有返回有效会话ID")
        with closing(self._connect()) as db, db:
            db.execute(
                """INSERT INTO subscription_entry_cards(message_id, target_type, target_id, target_name, chat_id, source_profile, created_at)
                   VALUES(?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(message_id) DO UPDATE SET target_type=excluded.target_type,
                   target_id=excluded.target_id, target_name=excluded.target_name, chat_id=excluded.chat_id,
                   source_profile=excluded.source_profile, created_at=excluded.created_at""",
                (message_id, target_type, target_id, target_name, chat_id, source_profile, _now_hkt()),
            )
        return {"message_id": message_id, "chat_id": chat_id, "target_id": target_id, "target_type": target_type, "verified": True}

    def _message_id(self, payload: dict[str, Any]) -> str:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        message_id = str(data.get("message_id") or "")
        if not message_id.startswith("om_"):
            raise RuntimeError("飞书发送成功但没有返回消息ID")
        return message_id

    def _send_markdown(self, open_id: str, text: str, *, idempotency_key: str, profile: str = "") -> str:
        payload = self._lark([
            "lark-cli", "im", "+messages-send", "--user-id", open_id, "--markdown", text,
            "--idempotency-key", idempotency_key[:50], "--as", "bot", "--profile", profile or self.delivery_profile, "--format", "json",
        ])
        return self._message_id(payload)

    def _send_interactive_card(
        self,
        open_id: str,
        card: dict[str, Any],
        *,
        idempotency_key: str,
        profile: str = "",
        preserve_markdown_bold: bool = False,
    ) -> str:
        if not preserve_markdown_bold:
            card = without_markdown_bold_markers(card)
        payload = self._lark([
            "lark-cli", "im", "+messages-send", "--user-id", open_id,
            "--msg-type", "interactive", "--content", json.dumps(card, ensure_ascii=False, separators=(",", ":")),
            "--idempotency-key", idempotency_key[:50], "--as", "bot",
            "--profile", profile or self.delivery_profile, "--format", "json",
        ])
        message_id = self._message_id(payload)
        actions = set()
        form_names = set()
        def inspect(node):
            if isinstance(node, dict):
                if node.get("tag") == "button":
                    for behavior in node.get("behaviors", []):
                        if behavior.get("type") == "callback":
                            actions.add(str((behavior.get("value") or {}).get("action") or ""))
                if node.get("tag") == "form":
                    form_names.add(node.get("name"))
                for value in node.values():
                    inspect(value)
            elif isinstance(node, list):
                for value in node:
                    inspect(value)
        inspect(card)
        chat_id = str((payload.get("data") or {}).get("chat_id") or "")
        source_profile = profile or self.delivery_profile
        purpose = "confirm" if 'cmhk_news_unsubscribe_confirm_v1' in actions else "news" if 'cmhk_news_preferences_v1' in actions else ""
        if purpose or 'subscriptionForm' in form_names:
            if not CHAT_ID_RE.fullmatch(chat_id):
                raise RuntimeError("设置卡片发送后缺少会话身份")
            with closing(self._connect()) as db, db:
                if purpose:
                    db.execute("INSERT OR REPLACE INTO news_control_cards VALUES(?,?,?,?,?)",
                               (message_id, chat_id, open_id, source_profile, purpose))
                else:
                    db.execute("INSERT OR REPLACE INTO subscription_entry_cards(message_id,target_type,target_id,target_name,chat_id,source_profile,created_at) VALUES(?,?,?,?,?,?,?)",
                               (message_id, "user", open_id, "", chat_id, source_profile, _now_hkt()))
        return message_id

    def _send_audio(self, open_id: str, audio_path: Path, *, idempotency_key: str, profile: str = "") -> str:
        relative = audio_path.relative_to(self.runtime_root)
        payload = self._lark([
            "lark-cli", "im", "+messages-send", "--user-id", open_id, "--audio", str(relative),
            "--idempotency-key", idempotency_key[:50], "--as", "bot", "--profile", profile or self.delivery_profile, "--format", "json",
        ], timeout=120)
        return self._message_id(payload)

    def _send_file(self, open_id: str, file_path: Path, *, idempotency_key: str, profile: str = "") -> str:
        relative = file_path.relative_to(self.runtime_root)
        payload = self._lark([
            "lark-cli", "im", "+messages-send", "--user-id", open_id, "--file", str(relative),
            "--idempotency-key", idempotency_key[:50], "--as", "bot", "--profile", profile or self.delivery_profile, "--format", "json",
        ], timeout=180)
        return self._message_id(payload)

    def _delivery_filename(self, report_path: Path, service: str, media_type: str) -> str:
        """Return the human-readable filename recipients see in Feishu."""
        service_label = SERVICE_LABELS.get(service, "战略情报")
        report_stem = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", report_path.stem).strip(" ._")
        report_stem = report_stem or "正式报告"
        prefix = f"CMHK_{service_label}_"
        if report_stem.startswith((service_label, f"CMHK_{service_label}")):
            prefix = "CMHK_" if not report_stem.startswith("CMHK_") else ""
        suffix = ".pdf" if media_type == "pdf" else "_音频.opus"
        max_stem_length = max(12, 120 - len(prefix) - len(suffix))
        return f"{prefix}{report_stem[:max_stem_length]}{suffix}"

    def _named_delivery_copy(
        self,
        source_path: Path,
        report_path: Path,
        service: str,
        media_type: str,
    ) -> Path:
        """Stage a named copy without renaming the source report or cached media."""
        outbound_dir = self.runtime_root / "var" / "subscriptions" / "outbound"
        outbound_dir.mkdir(parents=True, exist_ok=True)
        target = outbound_dir / self._delivery_filename(report_path, service, media_type)
        if (
            not target.exists()
            or target.stat().st_size != source_path.stat().st_size
            or target.stat().st_mtime_ns < source_path.stat().st_mtime_ns
        ):
            pending = target.with_name(f".{target.name}.tmp")
            shutil.copy2(source_path, pending)
            pending.replace(target)
        return target

    def _verify_message(self, message_id: str, *, profile: str = "") -> None:
        payload = self._lark([
            "lark-cli", "im", "+messages-mget", "--message-ids", message_id,
            "--no-reactions", "--as", "bot", "--profile", profile or self.delivery_profile, "--format", "json",
        ])
        raw = json.dumps(payload, ensure_ascii=False)
        if message_id not in raw:
            raise RuntimeError("飞书消息发送后回读未找到原消息")

    def _report_text(self, path: Path) -> str:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml)
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        paragraphs = []
        for paragraph in root.iter(f"{ns}p"):
            text = "".join(node.text or "" for node in paragraph.iter(f"{ns}t")).strip()
            if text:
                paragraphs.append(text)
        return "\n\n".join(paragraphs)

    def _text_chunks(self, title: str, text: str, limit: int = 5800) -> list[str]:
        paragraphs = [item.strip() for item in text.split("\n\n") if item.strip()]
        chunks: list[str] = []
        current = f"#### {title}\n\n"
        for paragraph in paragraphs:
            remaining = paragraph
            while remaining:
                room = limit - len(current) - 2
                if room <= 0:
                    chunks.append(current.rstrip())
                    current = f"#### {title}（续）\n\n"
                    room = limit - len(current) - 2
                piece = remaining[:room]
                current += piece + "\n\n"
                remaining = remaining[len(piece):]
                if remaining:
                    chunks.append(current.rstrip())
                    current = f"#### {title}（续）\n\n"
        if current.strip():
            chunks.append(current.rstrip())
        return chunks

    def _find_audio(self, report_path: Path) -> Path:
        from tts_service import safe_audio_stem

        audio_dir = self.runtime_root / "audio"
        # TTS removes punctuation such as the parentheses in Word's numbered
        # filenames (for example ``周报 (3).docx`` -> ``周报 3.mp3``). Accept
        # both the literal report stem and the TTS-safe stem, and use the most
        # recently generated file when both forms exist.
        stems = tuple(dict.fromkeys((report_path.stem, safe_audio_stem(report_path))))
        candidates = [
            audio_dir / f"{stem}{suffix}"
            for stem in stems
            for suffix in (".opus", ".ogg", ".mp3", ".wav")
        ]
        existing = [item for item in candidates if item.exists()]
        if not existing:
            raise ValueError("该报告尚无可推送语音，请先在报告库生成音频")
        source = max(existing, key=lambda item: item.stat().st_mtime_ns)
        if source.suffix.lower() in {".opus", ".ogg"}:
            return source
        target_dir = self.runtime_root / "var" / "subscriptions" / "media"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{report_path.stem}.opus"
        if not target.exists() or target.stat().st_mtime < source.stat().st_mtime:
            process = self._run(["ffmpeg", "-y", "-i", str(source), "-c:a", "libopus", "-b:a", "48k", str(target)], timeout=300)
            if process.returncode != 0 or not target.exists():
                raise RuntimeError("报告语音转换为飞书 Opus 格式失败")
        return target

    def _report_pdf(self, report_path: Path) -> Path:
        from cmhk.reporting.pdf_preview import convert_docx_to_pdf_preview, pdf_preview_path

        preview_dir = self.runtime_root / "web" / "static" / "report-previews"
        target = pdf_preview_path(report_path, preview_dir)
        if not target.exists() or target.stat().st_mtime < report_path.stat().st_mtime:
            target = convert_docx_to_pdf_preview(report_path, preview_dir=preview_dir)
        if not target.exists() or target.suffix.lower() != ".pdf":
            raise RuntimeError("报告 PDF 未生成")
        return target

    def _subscribers_for(self, service: str) -> list[dict[str, str]]:
        with closing(self._connect()) as db, db:
            rows = db.execute(
                """SELECT s.open_id, s.frequency, s.report_mode, s.news_item_limit, s.news_region_preference, s.news_categories, s.news_topics FROM subscribers s JOIN subscriptions x ON x.open_id=s.open_id
                   WHERE s.status='active' AND x.service=? AND x.active=1 ORDER BY s.open_id""",
                (service,),
            ).fetchall()
        return [
            {
                "open_id": str(row["open_id"]),
                # Reports are event-driven: the approved biweekly artifact is sent
                # when it is published. Only strategic news uses a selectable cadence.
                "frequency": _normalize_news_frequency(str(row["frequency"] or "once_daily")) if service == "news" else "immediate",
                "report_mode": str(row["report_mode"] or "pdf"),
                "news_item_limit": int(row["news_item_limit"] or 10),
                "news_region_preference": row["news_region_preference"],
                "news_categories": normalize_news_categories(row["news_categories"]),
                "news_topics": normalize_news_topics(row["news_topics"]),
            }
            for row in rows
        ]

    def _resolve_report(self, path: str) -> tuple[Path, str]:
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("报告路径无效")
        report_path = (self.runtime_root / relative).resolve()
        if (
            self.runtime_root.resolve() not in report_path.parents
            or report_path.suffix.lower() != ".docx"
            or not report_path.exists()
        ):
            raise ValueError("报告文件不存在或不允许推送")
        return report_path, str(relative)

    def _deliver_one(
        self,
        *,
        open_id: str,
        service: str,
        mode: str,
        content_ref: str,
        title: str,
        body: str,
        batch_id: str,
        profile: str,
        prepared_news_only: bool = False,
    ) -> list[str]:
        report_path: Path | None = None
        if service in {"weekly", "performance"}:
            report_path, _ = self._resolve_report(content_ref)
        text_chunks: list[str] = []
        pdf: Path | None = None
        audio: Path | None = None
        # Resolve and prepare every requested artifact before sending the first
        # message. A missing audio file must not leave an untracked PDF in the
        # recipient's chat and then queue the whole PDF+audio pair for retry.
        if mode in {"text", "both"} and service != "news":
            text = self._report_text(report_path)  # type: ignore[arg-type]
            text_chunks = self._text_chunks(title, text)
        if mode in {"pdf", "pdf_audio"}:
            pdf = self._report_pdf(report_path)  # type: ignore[arg-type]
            pdf = self._named_delivery_copy(pdf, report_path, service, "pdf")  # type: ignore[arg-type]
        if mode in {"audio", "both", "pdf_audio"}:
            audio = self._find_audio(report_path)  # type: ignore[arg-type]
            audio = self._named_delivery_copy(audio, report_path, service, "audio")  # type: ignore[arg-type]

        message_ids: list[str] = []
        if mode in {"text", "both"}:
            if service == "news":
                from cmhk.services.news_delivery_guard import deliver_news
                return deliver_news(self, open_id=open_id, content_ref=content_ref, title=title,
                                    body=body, batch_id=batch_id, profile=profile,
                                    prepared_only=prepared_news_only)
            else:
                for index, chunk in enumerate(text_chunks, start=1):
                    message_ids.append(self._send_markdown(
                        open_id,
                        chunk,
                        idempotency_key=f"{batch_id}-t{index}-{open_id[-6:]}",
                        profile=profile,
                    ))
        if mode in {"pdf", "pdf_audio"}:
            message_ids.append(self._send_file(
                open_id,
                pdf,  # type: ignore[arg-type]
                idempotency_key=f"{batch_id}-p-{open_id[-6:]}",
                profile=profile,
            ))
        if mode in {"audio", "both", "pdf_audio"}:
            message_ids.append(self._send_audio(
                open_id,
                audio,  # type: ignore[arg-type]
                idempotency_key=f"{batch_id}-a-{open_id[-6:]}",
                profile=profile,
            ))
        for message_id in message_ids:
            self._verify_message(message_id, profile=profile)
        return message_ids

    def due_count(self, *, now: datetime | None = None) -> int:
        current = (now or datetime.now(HKT)).astimezone(HKT).isoformat(timespec="seconds")
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT COUNT(*) FROM pending_subscription_deliveries WHERE status='queued' AND due_at<=?",
                (current,),
            ).fetchone()
        return int(row[0] if row else 0)

    def flush_due(self, *, now: datetime | None = None, limit: int = 100,
                  pending_id: int | None = None, prepared_news_only: bool = True) -> dict[str, Any]:
        current = (now or datetime.now(HKT)).astimezone(HKT).isoformat(timespec="seconds")
        with closing(self._connect()) as db:
            rows = db.execute(
                """SELECT p.*, d.batch_id FROM pending_subscription_deliveries p
                   JOIN deliveries d ON d.id=p.delivery_id
                   WHERE p.status='queued' AND p.due_at<=? AND (? IS NULL OR p.id=?)
                   ORDER BY p.due_at, p.id LIMIT ?""",
                (current, pending_id, pending_id, max(1, min(limit, 500))),
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            message_ids: list[str] = []
            status = "verified"
            error = ""
            service = str(row["service"])
            open_id = str(row["open_id"])
            active_recipients = {item["open_id"]: item for item in self._subscribers_for(service)}
            gate_open = self.automatic_delivery_enabled(service) and open_id in active_recipients
            content_ref = str(row["content_ref"] or "")
            morning_only = (service == "news" and content_ref.startswith(NEWS_CRAWL_REF_PREFIX)
                            and content_ref.rsplit("@", 1)[-1] >= "12:00"
                            and active_recipients.get(open_id, {}).get("frequency") == "once_daily")
            gate_open = gate_open and not morning_only
            if not gate_open:
                status = "cancelled"
                error = "接收人已改为每天一次，仅保留上午推送" if morning_only else "自动推送已暂停或接收人已取消该项订阅"
                with closing(self._connect()) as db, db:
                    db.execute(
                        "UPDATE deliveries SET status='cancelled', message_ids='[]', error=? WHERE id=?",
                        (error, int(row["delivery_id"])),
                    )
                    db.execute(
                        """UPDATE pending_subscription_deliveries
                           SET status='cancelled', dispatched_at=?, last_error=? WHERE id=?""",
                        (_now_hkt(), error, int(row["id"])),
                    )
                    content_ref = str(row["content_ref"] or "")
                    if service == "news" and content_ref.startswith(NEWS_CRAWL_REF_PREFIX):
                        db.execute(
                            """UPDATE news_crawl_dispatches
                               SET status='cancelled', message_ids='[]', last_error=?, updated_at=?
                               WHERE open_id=? AND crawl_slot=?""",
                            (
                                error,
                                _now_hkt(),
                                open_id,
                                content_ref.removeprefix(NEWS_CRAWL_REF_PREFIX),
                            ),
                        )
                results.append({
                    "pending_id": int(row["id"]),
                    "open_id": open_id,
                    "status": status,
                    "message_ids": [],
                    "error": error,
                })
                continue
            try:
                message_ids = self._deliver_one(
                    open_id=str(row["open_id"]),
                    service=str(row["service"]),
                    mode=str(row["mode"]),
                    content_ref=str(row["content_ref"]),
                    title=str(row["title"]),
                    body=str(row["body"]),
                    batch_id=str(row["batch_id"]),
                    profile=self.delivery_profile,
                    prepared_news_only=prepared_news_only,
                )
            except Exception as exc:
                status = "retrying"
                error = str(exc)[:900]
            with closing(self._connect()) as db, db:
                state = db.execute("SELECT status,last_error FROM pending_subscription_deliveries WHERE id=?", (row['id'],)).fetchone()
                if not message_ids and state and state['status'] in ('exhausted', 'cancelled'):
                    status, error = state['status'], state['last_error']
                db.execute(
                    "UPDATE deliveries SET status=?, message_ids=?, error=? WHERE id=?",
                    (status, json.dumps(message_ids), error, int(row["delivery_id"])),
                )
                if status == "verified":
                    db.execute(
                        """UPDATE pending_subscription_deliveries
                           SET status='verified', dispatched_at=?, last_error=''
                           WHERE id=?""",
                        (_now_hkt(), int(row["id"])),
                    )
                elif status not in ('exhausted', 'cancelled'):
                    # News preparation and transport failures must not impose a
                    # fifteen-minute delay on a card that becomes ready meanwhile.
                    retry_at = ((now or datetime.now(HKT)).astimezone(HKT) + timedelta(
                        seconds=15 if service == "news" else 900)).isoformat(timespec="seconds")
                    db.execute(
                        """UPDATE pending_subscription_deliveries
                           SET status='queued', attempts=attempts+1, last_error=?, due_at=?
                           WHERE id=?""",
                        (error, retry_at, int(row["id"])),
                    )
                content_ref = str(row["content_ref"] or "")
                if str(row["service"]) == "news" and content_ref.startswith(NEWS_CRAWL_REF_PREFIX):
                    crawl_slot = content_ref.removeprefix(NEWS_CRAWL_REF_PREFIX)
                    db.execute(
                        """UPDATE news_crawl_dispatches
                           SET status=?, message_ids=?, last_error=?, updated_at=?
                           WHERE open_id=? AND crawl_slot=?""",
                        (
                            status,
                            json.dumps(message_ids),
                            error,
                            _now_hkt(),
                            str(row["open_id"]),
                            crawl_slot,
                        ),
                    )
            if status == "verified" and service == "news":
                from cmhk.services.news_round_progress import reconcile_round
                reconcile_round(self, open_id, content_ref, now=now)
            results.append({
                "pending_id": int(row["id"]),
                "open_id": str(row["open_id"]),
                "status": status,
                "message_ids": message_ids,
                "error": error,
            })
        return {
            "checked_at": current,
            "processed_count": len(results),
            "verified_count": sum(1 for item in results if item["status"] == "verified"),
            "retrying_count": sum(1 for item in results if item["status"] == "retrying"),
            "failed_count": 0,
            "remaining_due_count": self.due_count(now=now),
            "results": results,
        }

    def select_personal_news(self, items: list[dict], *, open_id: str) -> list[dict]:
        """Manual latest-content selection uses the same short history as automatic news."""
        from cmhk.services.news_delivery_guard import delivered_history
        from cmhk.services.news_delivery_selection import select_recent_news
        day = _now_hkt()[:10]
        with closing(self._connect()) as db:
            subscriber = db.execute(
                "SELECT news_categories,news_item_limit,news_region_preference,news_topics FROM subscribers WHERE open_id=?", (open_id,),
            ).fetchone()
            if not subscriber:
                return []
            history = delivered_history(db, open_id=open_id, batch_id="", logical_day=day, send_day=day)
        return select_recent_news(items, subscriber['news_categories'], limit=subscriber['news_item_limit'],
                                  region_preference=subscriber["news_region_preference"], topics=subscriber["news_topics"], history=history, send_day=day, seed=f"{open_id}:{day}:manual")

    def dispatch_news_after_crawl(
        self,
        *,
        crawl_slot: str,
        slot_label: str,
        items: list[dict[str, Any]],
        completed_at: str = "",
    ) -> dict[str, Any]:
        """Queue a personal digest only after its crawler round is complete."""
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}@\d{2}:\d{2}", str(crawl_slot or "")):
            raise ValueError("战略爬虫轮次标识无效")
        if not self.automatic_delivery_enabled("news"):
            return {
                "crawl_slot": crawl_slot,
                "completed_at": completed_at or _now_hkt(),
                "schedule_enabled": False,
                "skipped": "schedule_disabled",
                "recipient_count": 0,
                "verified_count": 0,
                "retrying_count": 0,
                "skipped_count": 0,
                "results": [],
            }
        clean_items = sorted(
            (item for item in items if isinstance(item, dict)),
            key=_news_sort_timestamp,
            reverse=True,
        )
        crawl_date = crawl_slot[:10]
        crawl_time = crawl_slot[11:]
        delivery_window = "morning" if crawl_time < "12:00" else "afternoon"
        effective_completed_at = completed_at or _now_hkt()
        content_ref = f"{NEWS_CRAWL_REF_PREFIX}{crawl_slot}"
        period_name = "CMHK战略早茶" if "晨间" in slot_label else "CMHK战略下午茶"
        pool_created_at = _now_hkt()
        with closing(self._connect()) as db:
            for item in _deduplicate_news_items(clean_items):
                db.execute(
                    """INSERT OR REPLACE INTO news_crawl_item_pool(
                           crawl_slot, crawl_date, delivery_window, item_key,
                           item_json, sort_timestamp, created_at
                       ) VALUES(?, ?, ?, ?, ?, ?, ?)""",
                    (
                        crawl_slot,
                        crawl_date,
                        delivery_window,
                        _news_primary_key(item),
                        json.dumps(item, ensure_ascii=False, separators=(",", ":")),
                        _news_sort_timestamp(item),
                        pool_created_at,
                    ),
                )
            db.commit()
        with closing(self._connect()) as db:
            rows = db.execute(
                """SELECT s.open_id, s.frequency, s.news_item_limit, s.news_region_preference, s.news_categories, s.news_topics, s.news_delivery_times FROM subscribers s
                   JOIN subscriptions x ON x.open_id=s.open_id
                   WHERE s.status='active' AND x.service='news' AND x.active=1
                   ORDER BY s.open_id"""
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            open_id = str(row["open_id"])
            frequency = _normalize_news_frequency(str(row["frequency"] or "once_daily"))
            if frequency not in VALID_FREQUENCIES:
                frequency = "once_daily"
            if frequency == "once_daily" and delivery_window == "afternoon":
                results.append({
                    "open_id": open_id,
                    "frequency": frequency,
                    "status": "skipped",
                    "reason": "once_daily_morning_only",
                    "message_ids": [],
                })
                continue
            news_item_limit = int(row["news_item_limit"] or 10)
            if news_item_limit not in VALID_NEWS_ITEM_LIMITS:
                news_item_limit = 10
            news_categories = normalize_news_categories(row["news_categories"])
            news_region_preference = row["news_region_preference"]
            push_news_categories = []
            delivery_times = _normalize_news_delivery_times(row["news_delivery_times"])
            delivery_time = delivery_times[0] if delivery_window == "morning" else delivery_times[1]
            due_at = _news_delivery_due_at(
                crawl_date=crawl_date,
                delivery_time=delivery_time,
                completed_at=effective_completed_at,
            )
            year, month, day = crawl_date.split("-")
            title = f"{period_name}订阅｜{year}年{month}月{day}日"
            dispatch_key = (
                f"twice_daily:{crawl_date}:{delivery_window}"
                if frequency == "twice_daily"
                else f"once_daily:{crawl_date}"
            )
            now = _now_hkt()
            batch_id = hashlib.sha256(f"news-crawl:{crawl_slot}:{open_id}".encode()).hexdigest()[:24]
            with closing(self._connect()) as db:
                # Claim the daily window and create its durable outbox row in
                # one transaction. A process exit must never leave a claimed
                # day/window without the message that still needs delivery.
                # Older releases keyed twice-daily sends by the exact clock
                # time, so keep the legacy-window check inside the same lock.
                db.execute("BEGIN IMMEDIATE")
                legacy_claimed = db.execute(
                    """SELECT 1 FROM news_crawl_dispatches
                       WHERE open_id=? AND crawl_date=?
                         AND CASE WHEN substr(crawl_slot,12,5)<'12:00' THEN 'morning'
                                  ELSE 'afternoon' END=? LIMIT 1""",
                    (open_id, crawl_date, delivery_window),
                ).fetchone() is not None
                cursor = db.execute(
                    """INSERT OR IGNORE INTO news_crawl_dispatches(
                           open_id, dispatch_key, crawl_slot, crawl_date, frequency,
                           status, created_at, updated_at
                       ) SELECT ?, ?, ?, ?, ?, 'queued', ?, ?
                         WHERE ?=0""",
                    (
                        open_id, dispatch_key, crawl_slot, crawl_date, frequency,
                        now, now, int(legacy_claimed),
                    ),
                )
                claimed = cursor.rowcount == 1
                if claimed:
                    seen_keys = {
                        str(item[0])
                        for item in db.execute(
                            """SELECT h.item_key
                               FROM news_recipient_item_history h
                               JOIN news_crawl_dispatches d
                                 ON d.open_id=h.open_id AND d.dispatch_key=h.dispatch_key
                               WHERE h.open_id=? AND h.crawl_date=? AND d.status<>'cancelled'""",
                            (open_id, crawl_date),
                        ).fetchall()
                    }
                    # Compatibility with cards queued before the item-history
                    # ledger existed: their durable outbox bodies remain authoritative.
                    legacy_rows = db.execute(
                        """SELECT p.body
                           FROM pending_subscription_deliveries p
                           JOIN news_crawl_dispatches d ON d.delivery_id=p.delivery_id
                           WHERE p.open_id=? AND d.crawl_date=? AND d.status<>'cancelled'""",
                        (open_id, crawl_date),
                    ).fetchall()
                    for legacy_row in legacy_rows:
                        for legacy_item in _decode_strategic_news_digest(legacy_row[0]):
                            seen_keys.update(_news_identity_keys(legacy_item))

                    from cmhk.services.news_delivery_guard import delivered_history
                    from cmhk.services.news_delivery_selection import fresh_news, original_crawl_pool, select_recent_news
                    selection_day = max(crawl_date, due_at[:10])
                    history = delivered_history(db, open_id=open_id, batch_id=batch_id,
                                                logical_day=crawl_date, send_day=selection_day)
                    candidates = _deduplicate_news_items(
                        fresh_news(clean_items + original_crawl_pool(db, content_ref), selection_day),
                        excluded_keys=seen_keys)
                    recipient_items = select_recent_news(
                        candidates, news_categories, limit=news_item_limit, history=history,
                        region_preference=news_region_preference, topics=row["news_topics"],
                        send_day=selection_day, seed=f"{open_id}:{crawl_date}:{content_ref}")
                    push_news_categories = list(dict.fromkeys(item['category'] for item in recipient_items))
                    body = encode_strategic_news_digest(recipient_items)
                    local_item_count = sum(
                        str(item.get("region") or "").strip() == "香港本地"
                        for item in recipient_items
                    )
                    international_item_count = sum(
                        str(item.get("region") or "").strip() == "国际/行业"
                        for item in recipient_items
                    )
                    cursor = db.execute(
                        """INSERT INTO deliveries(batch_id, open_id, service, mode, content_ref, status, message_ids, error, created_at)
                           VALUES(?, ?, 'news', 'text', ?, 'queued', '[]', '', ?)""",
                        (batch_id, open_id, content_ref, now),
                    )
                    delivery_id = int(cursor.lastrowid)
                    for item in recipient_items:
                        for item_key in _news_identity_keys(item) or {_news_primary_key(item)}:
                            db.execute(
                                """INSERT OR REPLACE INTO news_recipient_item_history(
                                       open_id, crawl_date, item_key, dispatch_key,
                                       crawl_slot, delivery_id, created_at
                                   ) VALUES(?, ?, ?, ?, ?, ?, ?)""",
                                (
                                    open_id, crawl_date, item_key, dispatch_key,
                                    crawl_slot, delivery_id, now,
                                ),
                            )
                    db.execute(
                        """UPDATE news_crawl_dispatches SET delivery_id=?, updated_at=?
                           WHERE open_id=? AND dispatch_key=?""",
                        (delivery_id, now, open_id, dispatch_key),
                    )
                    db.execute(
                        """INSERT INTO pending_subscription_deliveries(
                               delivery_id, open_id, service, mode, content_ref, title, body,
                               frequency, due_at, status, created_at
                           ) VALUES(?, ?, 'news', 'text', ?, ?, ?, 'scheduled_after_crawl', ?, 'queued', ?)""",
                        (delivery_id, open_id, content_ref, title, body, due_at, now),
                    )
                db.commit()
            if not claimed:
                results.append({
                    "open_id": open_id,
                    "frequency": frequency,
                    "status": "skipped",
                    "reason": "daily_limit_reached",
                    "message_ids": [],
                })
                continue
            results.append({
                "open_id": open_id,
                "frequency": frequency,
                "news_item_limit": news_item_limit,
                "news_region_preference": news_region_preference,
                "news_categories": news_categories,
                "news_topics": normalize_news_topics(row["news_topics"]),
                "push_news_categories": push_news_categories,
                "news_category_labels": [NEWS_CATEGORY_LABELS[item] for item in news_categories],
                "local_item_count": local_item_count,
                "international_item_count": international_item_count,
                "news_delivery_times": delivery_times,
                "delivery_time": delivery_time,
                "status": "queued",
                "due_at": due_at,
                "message_ids": [],
                "error": "",
            })
        return {
            "crawl_slot": crawl_slot,
            "completed_at": effective_completed_at,
            "schedule_enabled": True,
            "recipient_count": len(results),
            "verified_count": sum(1 for item in results if item["status"] == "verified"),
            "retrying_count": sum(1 for item in results if item["status"] == "retrying"),
            "queued_count": sum(1 for item in results if item["status"] == "queued"),
            "skipped_count": sum(1 for item in results if item["status"] == "skipped"),
            "results": results,
        }

    def push(
        self,
        *,
        service: str,
        mode: str,
        path: str = "",
        title: str = "",
        body: str = "",
        test_open_id: str = "",
        target_open_id: str = "",
        confirm_bulk: bool = False,
        queue_failures: bool = False,
        batch_key: str = "",
        allow_user_edited: bool = False,
        manual_report_selection: bool = False,
    ) -> dict[str, Any]:
        if service not in VALID_SERVICES or mode not in VALID_DELIVERY_MODES:
            raise ValueError("推送服务或交付方式无效")
        if service == "news" and mode != "text":
            raise ValueError("战略新闻目前只支持文字推送")
        if service in {"weekly", "performance"} and mode not in {"pdf", "pdf_audio", "audio"}:
            raise ValueError("周报和业绩摘要只支持 PDF、PDF 加独立语音或仅语音")
        # News review/transport recovery must keep its original durable request.
        queue_failures = queue_failures or service == "news"
        recipients = self._subscribers_for(service)
        send_profile = self.delivery_profile
        if target_open_id:
            if not OPEN_ID_RE.fullmatch(target_open_id):
                raise ValueError("手动推送接收人格式无效")
            recipients = [item for item in recipients if item["open_id"] == target_open_id]
            if not recipients:
                raise ValueError("该订阅者未启用此项服务，无法手动推送")
        elif test_open_id:
            card_actions = self.config.get("card_actions") if isinstance(self.config.get("card_actions"), dict) else {}
            primary_test_open_id = str(card_actions.get("primary_handler_open_id") or "")
            subscriptions = self.config.get("subscriptions") if isinstance(self.config.get("subscriptions"), dict) else {}
            primary_delivery_open_id = str(subscriptions.get("primary_delivery_open_id") or "")
            if test_open_id not in {primary_test_open_id, primary_delivery_open_id}:
                raise ValueError("测试推送只允许发送给系统管理员")
            if not OPEN_ID_RE.fullmatch(primary_delivery_open_id):
                raise ValueError("组织推送应用缺少管理员身份映射")
            recipients = [{"open_id": primary_delivery_open_id, "frequency": "immediate", "report_mode": mode}]
            send_profile = self.delivery_profile
        elif not confirm_bulk:
            raise ValueError("批量推送必须在后台完成二次确认")
        if not recipients:
            raise ValueError("当前没有该服务的有效订阅者")
        report_path: Path | None = None
        content_ref = ""
        if service in {"weekly", "performance"}:
            report_path, content_ref = self._resolve_report(path)
            if manual_report_selection:
                self.validate_selected_report(path)
            elif service == "weekly":
                if allow_user_edited:
                    self._validate_user_edited_weekly_artifact(report_path)
                else:
                    self._validate_weekly_delivery_artifact(report_path)
            title = title.strip() or report_path.stem
        else:
            title = title.strip() or "战略新闻"
            body = body.strip()
            if not body:
                raise ValueError("新闻推送正文不能为空")
            content_ref = title
        default_batch = (f"news:{mode}:{content_ref}:{hashlib.sha256(body.encode()).hexdigest()}:{_now_hkt()[:10]}"
                         if service == "news" else f"{service}:{mode}:{content_ref}:{_now_hkt()}")
        batch_source = batch_key or default_batch
        batch_id = hashlib.sha256(batch_source.encode()).hexdigest()[:24]
        results = []
        for recipient in recipients:
            open_id = recipient["open_id"]
            frequency = (
                _normalize_news_frequency(recipient["frequency"])
                if service == "news"
                else "immediate"
            )
            if service == "news" and frequency not in VALID_FREQUENCIES:
                frequency = "once_daily"
            effective_mode = mode
            if service in {"weekly", "performance"} and mode == "pdf_audio":
                preference = recipient.get("report_mode") if recipient.get("report_mode") in VALID_REPORT_MODES else "pdf"
                effective_mode = preference
            message_ids: list[str] = []
            status = "sending"
            error = ""
            with closing(self._connect()) as db, db:
                cursor = db.execute(
                    """INSERT INTO deliveries(batch_id, open_id, service, mode, content_ref, status, message_ids, error, created_at)
                       VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (batch_id, open_id, service, effective_mode, content_ref, status, json.dumps(message_ids), error, _now_hkt()),
                )
                delivery_id = int(cursor.lastrowid)
                due_at = ""
            try:
                message_ids = self._deliver_one(
                    open_id=open_id,
                    service=service,
                    mode=effective_mode,
                    content_ref=content_ref,
                    title=title,
                    body=body,
                    batch_id=batch_id,
                    profile=send_profile,
                )
                status = "verified"
            except Exception as exc:
                status = "retrying" if queue_failures else "failed"
                error = str(exc)[:900]
            with closing(self._connect()) as db, db:
                db.execute(
                    "UPDATE deliveries SET status=?, message_ids=?, error=? WHERE id=?",
                    (status, json.dumps(message_ids), error, delivery_id),
                )
                if status == "retrying":
                    due_at = (datetime.now(HKT) + timedelta(minutes=15)).isoformat(timespec="seconds")
                    db.execute(
                        """INSERT INTO pending_subscription_deliveries(
                               delivery_id, open_id, service, mode, content_ref, title, body,
                               frequency, due_at, status, created_at
                           ) VALUES(?, ?, ?, ?, ?, ?, ?, 'schedule_retry', ?, 'queued', ?)""",
                        (delivery_id, open_id, service, effective_mode, content_ref, title, body, due_at, _now_hkt()),
                    )
            results.append({
                "open_id": open_id,
                "frequency": frequency,
                "mode": effective_mode,
                "status": status,
                "due_at": due_at,
                "message_ids": message_ids,
                "error": error,
            })
        return {
            "batch_id": batch_id,
            "service": service,
            "mode": mode,
            "recipient_count": len(results),
            "verified_count": sum(1 for item in results if item["status"] == "verified"),
            "queued_count": sum(1 for item in results if item["status"] in {"queued", "retrying"}),
            "failed_count": sum(1 for item in results if item["status"] == "failed"),
            "results": results,
        }

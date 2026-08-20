"""Server-side Feishu subscriptions and controlled delivery for CMHK content."""
from __future__ import annotations

import hashlib
import json
import os
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
    "once_daily": "每天一次",
}
VALID_FREQUENCIES = frozenset(FREQUENCY_LABELS)
VALID_NEWS_ITEM_LIMITS = frozenset({5, 10, 15, 20})
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
STRATEGIC_SCAN_TIMES_DEFAULT = ("09:00", "14:00")
OPEN_ID_RE = re.compile(r"^ou_[A-Za-z0-9]+$")
CHAT_ID_RE = re.compile(r"^oc_[A-Za-z0-9]+$")
MESSAGE_ID_RE = re.compile(r"^om_[A-Za-z0-9]+$")
IMAGE_KEY_RE = re.compile(r"^img_[A-Za-z0-9_-]+$")
NEWS_DIGEST_PREFIX = "CMHK_NEWS_DIGEST_V1\n"
NEWS_CRAWL_REF_PREFIX = "strategic-crawl:"


def _now_hkt() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


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


def filter_news_by_categories(
    items: list[dict[str, Any]],
    categories: Any,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return the globally newest items matching one recipient's interest profile."""
    normalized = normalize_news_categories(categories)
    selected = set(normalized)
    ordered = sorted(
        (item for item in items if isinstance(item, dict)),
        key=_news_sort_timestamp,
        reverse=True,
    )
    # The legacy/all profile deliberately retains an occasional historical
    # uncategorized row so existing subscribers do not lose content on upgrade.
    if selected != VALID_NEWS_CATEGORIES:
        ordered = [item for item in ordered if str(item.get("category") or "").strip() in selected]
    if limit is None:
        return ordered
    return ordered[:max(0, int(limit))]


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


def _command_env(environ: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(environ or os.environ)
    env["LARK_CLI_NO_PROXY"] = "1"
    env["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"] = "1"
    env["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"] = "1"
    for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        env.pop(key, None)
    return env


def _json_payload(process: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "飞书命令执行失败").strip()[-1200:]
        raise RuntimeError(detail)
    raw = (process.stdout or "").strip()
    payload = json.loads(raw or "{}")
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise RuntimeError(str(payload.get("error") or "飞书返回格式异常"))
    return payload


def subscription_entry_card(*, image_key: str = "", recipient_name: str = "") -> dict[str, Any]:
    """Card 2.0 form used as the colleague-facing self-service entry point."""
    salutation = f"尊敬的 {recipient_name.strip()}，您好！" if recipient_name.strip() else "您好！"
    introduction = (
        f"{salutation}我是战略竞对中心管家小竞。"
        "为帮助战略部宣传和推广战略情报产品，您可以按需选择战略双周报、运营商业绩摘要或战略新闻，"
        "报告按后台设定的月度排期自动生成并推送；战略新闻爬虫每日香港时间 09:00 和 14:00 执行，"
        "完成审核后推送，您可以选择每天一次或每天两次。"
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
            "summary": {"content": "订阅战略情报 · 新闻每日 09:00 / 14:00 扫描"},
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
                        {"tag": "markdown", "content": "**订阅内容**"},
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
                        {"tag": "markdown", "content": "**报告接收方式**"},
                        {
                            "tag": "select_static",
                            "name": "report_mode",
                            "required": True,
                            "width": "fill",
                            "placeholder": {"tag": "plain_text", "content": "选择接收方式"},
                            "options": [
                                {"text": {"tag": "plain_text", "content": "仅 PDF"}, "value": "pdf"},
                                {"text": {"tag": "plain_text", "content": "PDF + 单独语音"}, "value": "pdf_audio"},
                                {"text": {"tag": "plain_text", "content": "仅语音"}, "value": "audio"},
                            ],
                        },
                        {"tag": "markdown", "content": "**战略新闻频率**"},
                        {
                            "tag": "select_static",
                            "name": "news_frequency",
                            "required": True,
                            "width": "fill",
                            "placeholder": {"tag": "plain_text", "content": "选择战略新闻频率"},
                            "options": [
                                {"text": {"tag": "plain_text", "content": "每天两次"}, "value": "twice_daily"},
                                {"text": {"tag": "plain_text", "content": "每天一次"}, "value": "once_daily"},
                            ],
                        },
                        {"tag": "markdown", "content": "**感兴趣的战略新闻板块（可多选）**"},
                        {
                            "tag": "multi_select_static",
                            "name": "news_categories",
                            "required": True,
                            "width": "fill",
                            "placeholder": {"tag": "plain_text", "content": "选择一个或多个兴趣板块"},
                            "options": [
                                {"text": {"tag": "plain_text", "content": label}, "value": category}
                                for category, label in NEWS_CATEGORY_LABELS.items()
                            ],
                        },
                        {"tag": "markdown", "content": "**每次战略新闻条数**"},
                        {
                            "tag": "select_static",
                            "name": "news_item_limit",
                            "required": True,
                            "width": "fill",
                            "placeholder": {"tag": "plain_text", "content": "选择每次接收条数"},
                            "options": [
                                {"text": {"tag": "plain_text", "content": f"最新 {count} 条"}, "value": str(count)}
                                for count in sorted(VALID_NEWS_ITEM_LIMITS)
                            ],
                        },
                        {
                            "tag": "markdown",
                            "content": "<font color='grey'>周报按后台月度排期自动生成并推送，业绩摘要随正式报告发布；战略新闻每日香港时间 09:00、14:00 扫描，爬虫完成审核后推送。每天一次仅接收当日首轮结果，新闻始终以文字消息发送。</font>",
                            "text_size": "notation",
                        },
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


def strategic_news_card(*, title: str, body: str, published_at: str = "") -> dict[str, Any]:
    """Strategic-news card matching the established CMHK group digest format."""
    clean_title = re.sub(r"\s+", " ", str(title or "CMHK战略订阅")).strip()[:120] or "CMHK战略订阅"
    date_label = str(published_at or _now_hkt())[:16].replace("T", " ")
    elements: list[dict[str, Any]] = []
    if str(body).startswith(NEWS_DIGEST_PREFIX):
        try:
            parsed = json.loads(str(body)[len(NEWS_DIGEST_PREFIX):])
        except (ValueError, TypeError, json.JSONDecodeError):
            parsed = []
        items = [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []
        top_titles = "；".join(str(item.get("title") or "").strip()[:42] for item in items[:3] if item.get("title"))
        elements.append({
            "tag": "markdown",
            "content": f"**今日关键信号**\n重点涉及：{top_titles}。" if top_titles else "**本轮结果**  暂无可展示新闻。",
        })
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            grouped.setdefault(str(item.get("category") or "战略动态").strip() or "战略动态", []).append(item)
        ordered_categories = [category for category in NEWS_CATEGORY_LABELS if category in grouped]
        ordered_categories.extend(category for category in grouped if category not in NEWS_CATEGORY_LABELS)
        index = 0
        for group_category in ordered_categories:
            category_items = grouped[group_category]
            elements.append({
                "tag": "markdown",
                "content": f"### {NEWS_CATEGORY_LABELS.get(group_category, group_category)} · {len(category_items)} 条",
            })
            for item in category_items:
                index += 1
                item_title = re.sub(r"\s+", " ", str(item.get("title") or "未命名动态")).strip()[:180]
                summary = str(item.get("summary") or "").strip()[:260]
                category = str(item.get("category") or "战略动态").strip()[:80]
                region = str(item.get("region") or "未分类").strip()[:40]
                source = str(item.get("source") or "来源待核").strip()[:100]
                published = str(item.get("published_at") or item.get("source_date") or "").strip()
                try:
                    published_text = datetime.fromisoformat(published.replace("Z", "+00:00")).astimezone().strftime("%m月%d日 %H:%M")
                except ValueError:
                    published_text = published[:16] or "时间待核"
                url = str(item.get("source_url") or item.get("url") or "").strip()
                linked_title = f"[**{item_title}**]({url})" if url.startswith(("http://", "https://")) else f"**{item_title}**"
                lines = [f"**{index:02d}｜{category} · {region}**", linked_title]
                if summary:
                    lines.append(summary)
                lines.append(f"**业务影响：** {_news_business_impact(item)}")
                lines.append(f"<font color='grey'>{source} · {published_text}</font>")
                elements.extend([{"tag": "hr"}, {"tag": "markdown", "content": "\n".join(lines)}])
        elements.extend([
            {"tag": "hr"},
            {"tag": "note", "elements": [{"tag": "plain_text", "content": f"已完整列出本批 {len(items)} 条战略新闻。"}]},
        ])
    else:
        clean_body = str(body or "").strip()
        if len(clean_body) > 12000:
            clean_body = clean_body[:11997].rstrip() + "…"
        elements.append({"tag": "markdown", "content": clean_body})
    return {
        "config": {"wide_screen_mode": True, "enable_forward": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": clean_title},
            "subtitle": {"tag": "plain_text", "content": f"截至 {date_label} · 香港时间"},
        },
        "elements": elements,
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
        return str(subscriptions.get("entry_profile") or bot.get("profile") or "")

    @property
    def delivery_profile(self) -> str:
        subscriptions = self.config.get("subscriptions") if isinstance(self.config.get("subscriptions"), dict) else {}
        return str(subscriptions.get("delivery_profile") or self.entry_profile)

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
                    display_name TEXT NOT NULL,
                    avatar_url TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    responded_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (message_id, callback_open_id)
                );
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
                   ) VALUES('news', 0, '[]', '00:00', 'Asia/Hong_Kong', ?)""",
                (_now_hkt(),),
            )
            columns = {str(row[1]) for row in db.execute("PRAGMA table_info(subscribers)").fetchall()}
            if "callback_open_id" not in columns:
                db.execute("ALTER TABLE subscribers ADD COLUMN callback_open_id TEXT NOT NULL DEFAULT ''")
            if "union_id" not in columns:
                db.execute("ALTER TABLE subscribers ADD COLUMN union_id TEXT NOT NULL DEFAULT ''")
            if "frequency" not in columns:
                db.execute("ALTER TABLE subscribers ADD COLUMN frequency TEXT NOT NULL DEFAULT 'immediate'")
            if "report_mode" not in columns:
                db.execute("ALTER TABLE subscribers ADD COLUMN report_mode TEXT NOT NULL DEFAULT 'pdf'")
            if "news_item_limit" not in columns:
                db.execute("ALTER TABLE subscribers ADD COLUMN news_item_limit INTEGER NOT NULL DEFAULT 10")
            if "news_categories" not in columns:
                db.execute("ALTER TABLE subscribers ADD COLUMN news_categories TEXT NOT NULL DEFAULT '[]'")
            all_categories_json = json.dumps(list(NEWS_CATEGORY_LABELS), ensure_ascii=False, separators=(",", ":"))
            for row in db.execute("SELECT open_id, news_categories FROM subscribers").fetchall():
                categories = normalize_news_categories(row["news_categories"])
                serialized = json.dumps(categories, ensure_ascii=False, separators=(",", ":"))
                if serialized != str(row["news_categories"] or ""):
                    db.execute(
                        "UPDATE subscribers SET news_categories=? WHERE open_id=?",
                        (serialized or all_categories_json, str(row["open_id"])),
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
                    "SELECT delivery_id FROM pending_subscription_deliveries WHERE service='news' AND status='queued'"
                ).fetchall()
            ]
            if legacy_pending_ids:
                placeholders = ",".join("?" for _ in legacy_pending_ids)
                db.execute(
                    f"UPDATE deliveries SET status='superseded', error='已改为战略爬虫完成后推送' WHERE id IN ({placeholders})",
                    legacy_pending_ids,
                )
                db.execute(
                    "UPDATE pending_subscription_deliveries SET status='superseded', last_error='已改为战略爬虫完成后推送' WHERE service='news' AND status='queued'"
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
            argv,
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
        return str(subscriptions.get("directory_profile") or self.delivery_profile)

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
    ) -> dict[str, Any]:
        normalized = sorted({str(item) for item in services if str(item) in VALID_SERVICES})
        if not normalized:
            raise ValueError("至少选择一个订阅服务")
        frequency = _normalize_news_frequency(frequency)
        if frequency not in VALID_FREQUENCIES:
            raise ValueError("接收频率无效")
        if report_mode not in VALID_REPORT_MODES:
            raise ValueError("报告接收形式无效")
        try:
            news_item_limit = int(news_item_limit)
        except (TypeError, ValueError) as exc:
            raise ValueError("每次战略新闻条数无效") from exc
        if news_item_limit not in VALID_NEWS_ITEM_LIMITS:
            raise ValueError("每次战略新闻条数无效")
        normalized_categories = normalize_news_categories(
            news_categories,
            default_all=news_categories is None,
        )
        if "news" in normalized and not normalized_categories:
            raise ValueError("至少选择一个战略新闻兴趣板块")
        categories_json = json.dumps(normalized_categories, ensure_ascii=False, separators=(",", ":"))
        now = _now_hkt()
        with closing(self._connect()) as db, db:
            db.execute(
                """INSERT INTO subscribers(open_id, callback_open_id, union_id, display_name, status, frequency, report_mode, news_item_limit, news_categories, source_chat_id, created_at, updated_at)
                   VALUES(?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(open_id) DO UPDATE SET display_name=excluded.display_name,
                   callback_open_id=excluded.callback_open_id, union_id=excluded.union_id,
                   status='active', frequency=excluded.frequency, report_mode=excluded.report_mode,
                   news_item_limit=excluded.news_item_limit, news_categories=excluded.news_categories,
                   source_chat_id=excluded.source_chat_id,
                   updated_at=excluded.updated_at""",
                (open_id, callback_open_id, union_id, display_name, frequency, report_mode, news_item_limit, categories_json, source_chat_id, now, now),
            )
            for service in VALID_SERVICES:
                db.execute(
                    """INSERT INTO subscriptions(open_id, service, active, updated_at) VALUES(?, ?, ?, ?)
                       ON CONFLICT(open_id, service) DO UPDATE SET active=excluded.active, updated_at=excluded.updated_at""",
                    (open_id, service, int(service in normalized), now),
                )
        return {
            "open_id": open_id,
            "display_name": display_name,
            "services": normalized,
            "frequency": frequency,
            "frequency_label": FREQUENCY_LABELS[frequency],
            "news_frequency": frequency,
            "news_frequency_label": FREQUENCY_LABELS[frequency],
            "news_item_limit": news_item_limit,
            "news_categories": normalized_categories,
            "news_category_labels": [NEWS_CATEGORY_LABELS[item] for item in normalized_categories],
            "report_cadence": "biweekly_on_publish",
            "report_cadence_label": REPORT_CADENCE_LABEL,
            "report_mode": report_mode,
            "report_mode_label": REPORT_MODE_LABELS[report_mode],
            "updated_at": now,
        }

    def handle_card_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        if str(event.get("type") or "") != "card.action.trigger" or str(event.get("action_tag") or "") != "button":
            return None
        try:
            action = json.loads(str(event.get("action_value") or "{}"))
        except (ValueError, TypeError, json.JSONDecodeError):
            action = {}
        action_name = str(action.get("action") or "") if isinstance(action, dict) else ""
        is_pause = action_name == "cmhk_subscription_pause_all_v1"
        form_raw = str(event.get("form_value") or "")
        if not form_raw and not is_pause and action_name != "cmhk_subscription_save_v1":
            return None
        services: list[str] = []
        frequency = "once_daily"
        report_mode = "pdf"
        news_item_limit = 10
        news_categories = list(NEWS_CATEGORY_LABELS)
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
                selected_categories,
                default_all=selected_categories is None,
            )
            if "news" in services and not news_categories:
                raise ValueError("请至少选择一个感兴趣的战略新闻板块")
            delivery_plan = _card_form_scalar(form.get("delivery_plan"))
            if delivery_plan:
                plan_match = re.fullmatch(r"(immediate|daily|weekly|once_daily|twice_daily)_(pdf_audio|pdf|audio)", delivery_plan)
                if not plan_match:
                    raise ValueError("请选择有效的接收方式与频率")
                frequency, report_mode = plan_match.groups()
                frequency = _normalize_news_frequency(frequency)
            else:
                frequency = _normalize_news_frequency(
                    _card_form_scalar(form.get("news_frequency") or form.get("frequency"))
                )
                report_mode = _card_form_scalar(form.get("report_mode")) or "pdf"
            try:
                news_item_limit = int(_card_form_scalar(form.get("news_item_limit")) or 10)
            except ValueError as exc:
                raise ValueError("请选择有效的每次战略新闻条数") from exc
            if frequency not in VALID_FREQUENCIES:
                raise ValueError("请选择有效的接收频率")
            if report_mode not in VALID_REPORT_MODES:
                raise ValueError("请选择有效的报告接收形式")
            if news_item_limit not in VALID_NEWS_ITEM_LIMITS:
                raise ValueError("请选择有效的每次战略新闻条数")
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
                    db.execute(
                        """INSERT INTO subscription_group_responses(
                               message_id, chat_id, callback_open_id, delivery_open_id,
                               display_name, avatar_url, status, responded_at, updated_at
                           ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(message_id, callback_open_id) DO UPDATE SET
                               delivery_open_id=excluded.delivery_open_id,
                               display_name=excluded.display_name,
                               avatar_url=excluded.avatar_url,
                               status=excluded.status,
                               responded_at=excluded.responded_at,
                               updated_at=excluded.updated_at""",
                        (
                            message_id, chat_id, identity["callback_open_id"], identity["open_id"],
                            identity["display_name"], identity.get("avatar_url", ""), status, now, now,
                        ),
                    )
                    return
                updated = db.execute(
                    """UPDATE subscription_invitations
                       SET status=?, responded_at=?, updated_at=?
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
            news_categories=news_categories,
        )
        record_invitation_response("accepted")
        labels = "、".join(SERVICE_LABELS[item] for item in saved["services"])
        category_labels = "、".join(saved["news_category_labels"])
        confirmation = self._send_markdown(
            identity["callback_open_id"],
            f"#### 订阅已生效\n\n{identity['display_name']}，你当前订阅：**{labels}**。\n\n报告形式：**{saved['report_mode_label']}**\n\n报告节奏：**{REPORT_CADENCE_LABEL}**\n\n战略新闻频率：**{saved['frequency_label']}**\n\n兴趣板块：**{category_labels}**\n\n每次战略新闻：**从兴趣板块中选取最新 {saved['news_item_limit']} 条并分类展示**。以后重新提交订阅卡片即可覆盖选择。",
            idempotency_key=f"suback-{event_id}"[:50],
            profile=source_profile,
        )
        self._verify_message(confirmation, profile=source_profile)
        saved["confirmation_message_id"] = confirmation
        return {"status": "subscription_saved", "source_profile": source_profile, **saved}

    def list_summary(self, *, delivery_limit: int = 80) -> dict[str, Any]:
        with closing(self._connect()) as db, db:
            rows = db.execute(
                """SELECT s.open_id, s.callback_open_id, s.union_id, s.display_name, s.status, s.frequency, s.report_mode, s.news_item_limit, s.news_categories,
                          s.source_chat_id, s.created_at, s.updated_at,
                          GROUP_CONCAT(CASE WHEN x.active=1 THEN x.service END) AS services
                   FROM subscribers s LEFT JOIN subscriptions x ON x.open_id=s.open_id
                   GROUP BY s.open_id ORDER BY s.updated_at DESC"""
            ).fetchall()
            deliveries = db.execute(
                """SELECT d.*,
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
                   FROM deliveries d ORDER BY d.id DESC LIMIT ?""",
                (max(1, min(delivery_limit, 300)),),
            ).fetchall()
            invitations = db.execute(
                "SELECT * FROM subscription_invitations ORDER BY id DESC LIMIT 200"
            ).fetchall()
            group_cards = db.execute(
                """SELECT c.*,
                          COUNT(r.callback_open_id) AS response_count,
                          SUM(CASE WHEN r.status='accepted' THEN 1 ELSE 0 END) AS accepted_count,
                          SUM(CASE WHEN r.status='paused' THEN 1 ELSE 0 END) AS paused_count,
                          MAX(r.updated_at) AS latest_response_at
                   FROM subscription_entry_cards c
                   LEFT JOIN subscription_group_responses r ON r.message_id=c.message_id
                   WHERE c.target_type='chat'
                   GROUP BY c.message_id
                   ORDER BY c.created_at DESC LIMIT 30"""
            ).fetchall()
            group_responses = db.execute(
                """SELECT r.* FROM subscription_group_responses r
                   JOIN subscription_entry_cards c ON c.message_id=r.message_id
                   WHERE c.target_type='chat'
                   ORDER BY r.updated_at DESC LIMIT 300"""
            ).fetchall()
        subscribers = []
        counts = {key: 0 for key in VALID_SERVICES}
        latest_group_response_by_delivery: dict[str, dict[str, Any]] = {}
        for response_row in group_responses:
            response = dict(response_row)
            latest_group_response_by_delivery.setdefault(str(response["delivery_open_id"]), response)
        for row in rows:
            services = sorted(filter(None, str(row["services"] or "").split(",")))
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
                "news_categories": normalize_news_categories(row["news_categories"]),
                "news_category_labels": [
                    NEWS_CATEGORY_LABELS[item]
                    for item in normalize_news_categories(row["news_categories"])
                ],
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
        responses_by_message: dict[str, list[dict[str, Any]]] = {}
        for row in group_responses:
            response = dict(row)
            responses_by_message.setdefault(str(response["message_id"]), []).append(response)
        group_invitation_items = []
        for row in group_cards:
            item = dict(row)
            item["target_name"] = str(item.get("target_name") or item.get("target_id") or "飞书群聊")
            item["status"] = "responded" if int(item.get("response_count") or 0) else "verified"
            item["responses"] = responses_by_message.get(str(item["message_id"]), [])
            group_invitation_items.append(item)
        return {
            "services": [{"key": key, "label": SERVICE_LABELS[key], "subscriber_count": counts[key]} for key in ("weekly", "performance", "news")],
            "news_categories": [
                {"key": key, "label": label}
                for key, label in NEWS_CATEGORY_LABELS.items()
            ],
            "subscribers": subscribers,
            "deliveries": delivery_items,
            "invite_candidates": self.list_invite_candidates(),
            "group_invitations": group_invitation_items,
            "invitations": [dict(item) for item in invitations],
            "invitation_counts": {
                status: sum(1 for item in invitations if str(item["status"]) == status)
                for status in ("pending", "accepted", "paused", "failed")
            },
            "invitation_permissions": self.invitation_permission_snapshot(),
            "active_subscriber_count": sum(1 for row in subscribers if row["status"] == "active"),
            "report_schedule": self.report_schedule_snapshot(),
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
            "enabled": bool(row["enabled"]) if row else False,
            "times": times,
            "times_text": " / ".join(times),
            "timezone": "Asia/Hong_Kong",
            "timezone_label": "香港时间",
            "dispatch_rule": "爬虫完成审核后推送",
            "updated_at": str(row["updated_at"] or "") if row else "",
        }

    def update_news_schedule(self, *, enabled: bool) -> dict[str, Any]:
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE report_automation_schedule SET enabled=?, updated_at=? WHERE service='news'",
                (1 if enabled else 0, _now_hkt()),
            )
        return self.strategic_news_schedule_snapshot()

    def automatic_delivery_enabled(self, service: str) -> bool:
        if service not in {"news", "weekly"}:
            return False
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

    def report_schedule_snapshot(self, *, now: datetime | None = None) -> dict[str, Any]:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT * FROM report_automation_schedule WHERE service='weekly'"
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
            "service": "weekly",
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

    def update_report_schedule(self, *, days: Any, time_hm: Any, enabled: bool) -> dict[str, Any]:
        normalized_days = self._normalize_schedule_days(days)
        normalized_time = self._normalize_schedule_time(time_hm)
        with closing(self._connect()) as db, db:
            db.execute(
                """UPDATE report_automation_schedule
                   SET enabled=?, days_json=?, time_hm=?, updated_at=?
                   WHERE service='weekly'""",
                (1 if enabled else 0, json.dumps(normalized_days), normalized_time, _now_hkt()),
            )
        return self.report_schedule_snapshot()

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
                timeout=1200,
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
            report_path = max(candidates, key=lambda item: item.stat().st_mtime_ns)
            relative_path = report_path.relative_to(self.runtime_root).as_posix()
            if any(item.get("report_mode") in {"audio", "pdf_audio"} for item in subscribers):
                try:
                    from tts_service import synthesize_report_audio

                    audio_result = synthesize_report_audio(report_path, force=True)
                    if not audio_result.get("ok", True):
                        raise RuntimeError(str(audio_result.get("error") or "周报语音生成失败"))
                except Exception as exc:
                    raise RuntimeError(f"周报已生成，但订阅语音生成失败：{exc}") from exc
            delivery = self.push(
                service="weekly",
                mode="pdf_audio",
                path=relative_path,
                confirm_bulk=True,
                queue_failures=True,
                batch_key=f"weekly-schedule:{slot}",
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
            return {"ok": True, "slot": slot, "status": final_status, "report_path": relative_path, "delivery": delivery}
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
                           directory_open_id, union_id, display_name, en_name, avatar_url,
                           job_title, department_names, source_profile, active, synced_at
                       ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                       ON CONFLICT(directory_open_id) DO UPDATE SET
                           union_id=excluded.union_id, display_name=excluded.display_name,
                           en_name=excluded.en_name, avatar_url=excluded.avatar_url,
                           job_title=excluded.job_title, department_names=excluded.department_names,
                           source_profile=excluded.source_profile, active=1, synced_at=excluded.synced_at""",
                    (
                        person["directory_open_id"], person["union_id"], person["display_name"],
                        person["en_name"], person["avatar_url"], job_title,
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
                """SELECT directory_open_id, union_id, display_name, en_name, avatar_url,
                          job_title, department_names, source_profile, synced_at
                   FROM subscription_directory_people
                   WHERE active=1 AND (display_name LIKE ? OR en_name LIKE ?)
                   ORDER BY display_name LIMIT ?""",
                (pattern, pattern, max(1, min(int(limit), 50))),
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
                   WHERE directory_open_id=? AND active=1""",
                (open_id,),
            ).fetchone()
            if row is None:
                row = db.execute(
                    "SELECT avatar_url FROM subscription_invite_candidates WHERE callback_open_id=?",
                    (open_id,),
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
                latest = db.execute(
                    """SELECT status, sent_at, responded_at, message_id FROM subscription_invitations
                       WHERE callback_open_id=? ORDER BY id DESC LIMIT 1""",
                    (candidate["callback_open_id"],),
                ).fetchone()
                candidate["latest_invitation"] = dict(latest) if latest else None
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
    ) -> dict[str, Any]:
        if status not in {"active", "paused"}:
            raise ValueError("订阅者状态只能是 active 或 paused")
        with closing(self._connect()) as db, db:
            row = db.execute(
                "SELECT display_name, source_chat_id, callback_open_id, union_id, news_categories FROM subscribers WHERE open_id=?",
                (open_id,),
            ).fetchone()
        if row is None:
            raise ValueError("订阅者不存在")
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
            news_categories=(
                news_categories
                if news_categories is not None
                else normalize_news_categories(row["news_categories"])
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
        card = subscription_entry_card(image_key=image_key, recipient_name=recipient_name)
        card_version = hashlib.sha256(
            json.dumps(card, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()[:12]
        key = hashlib.sha256(
            f"subscription-entry:{key_context}:{target_type}:{target_id}:{datetime.now().isoformat(timespec='microseconds')}:{card_version}".encode()
        ).hexdigest()[:32]
        payload = self._lark([
            "lark-cli", "im", "+messages-send", *target_args,
            "--msg-type", "interactive", "--content", json.dumps(card, ensure_ascii=False),
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
    ) -> str:
        payload = self._lark([
            "lark-cli", "im", "+messages-send", "--user-id", open_id,
            "--msg-type", "interactive", "--content", json.dumps(card, ensure_ascii=False),
            "--idempotency-key", idempotency_key[:50], "--as", "bot",
            "--profile", profile or self.delivery_profile, "--format", "json",
        ])
        return self._message_id(payload)

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
        audio_dir = self.runtime_root / "audio"
        candidates = [audio_dir / f"{report_path.stem}{suffix}" for suffix in (".opus", ".ogg", ".mp3", ".wav")]
        source = next((item for item in candidates if item.exists()), None)
        if source is None:
            raise ValueError("该报告尚无可推送语音，请先在报告库生成音频")
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
        from report_pdf_preview import convert_docx_to_pdf_preview, pdf_preview_path

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
                """SELECT s.open_id, s.frequency, s.report_mode, s.news_item_limit, s.news_categories FROM subscribers s JOIN subscriptions x ON x.open_id=s.open_id
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
                "news_categories": normalize_news_categories(row["news_categories"]),
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
    ) -> list[str]:
        report_path: Path | None = None
        if service in {"weekly", "performance"}:
            report_path, _ = self._resolve_report(content_ref)
        message_ids: list[str] = []
        if mode in {"text", "both"}:
            if service == "news":
                message_ids.append(self._send_interactive_card(
                    open_id,
                    strategic_news_card(title=title, body=body),
                    idempotency_key=f"{batch_id}-n-{open_id[-6:]}",
                    profile=profile,
                ))
            else:
                text = self._report_text(report_path)  # type: ignore[arg-type]
                for index, chunk in enumerate(self._text_chunks(title, text), start=1):
                    message_ids.append(self._send_markdown(
                        open_id,
                        chunk,
                        idempotency_key=f"{batch_id}-t{index}-{open_id[-6:]}",
                        profile=profile,
                    ))
        if mode in {"pdf", "pdf_audio"}:
            pdf = self._report_pdf(report_path)  # type: ignore[arg-type]
            pdf = self._named_delivery_copy(pdf, report_path, service, "pdf")  # type: ignore[arg-type]
            message_ids.append(self._send_file(
                open_id,
                pdf,
                idempotency_key=f"{batch_id}-p-{open_id[-6:]}",
                profile=profile,
            ))
        if mode in {"audio", "both", "pdf_audio"}:
            audio = self._find_audio(report_path)  # type: ignore[arg-type]
            audio = self._named_delivery_copy(audio, report_path, service, "audio")  # type: ignore[arg-type]
            message_ids.append(self._send_audio(
                open_id,
                audio,
                idempotency_key=f"{batch_id}-a-{open_id[-6:]}",
                profile=profile,
            ))
        for message_id in message_ids:
            self._verify_message(message_id, profile=profile)
        return message_ids

    def due_count(self, *, now: datetime | None = None) -> int:
        current = (now or datetime.now().astimezone()).astimezone().isoformat(timespec="seconds")
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT COUNT(*) FROM pending_subscription_deliveries WHERE status='queued' AND due_at<=?",
                (current,),
            ).fetchone()
        return int(row[0] if row else 0)

    def flush_due(self, *, now: datetime | None = None, limit: int = 100) -> dict[str, Any]:
        current = (now or datetime.now().astimezone()).astimezone().isoformat(timespec="seconds")
        with closing(self._connect()) as db:
            rows = db.execute(
                """SELECT p.*, d.batch_id FROM pending_subscription_deliveries p
                   JOIN deliveries d ON d.id=p.delivery_id
                   WHERE p.status='queued' AND p.due_at<=?
                   ORDER BY p.due_at, p.id LIMIT ?""",
                (current, max(1, min(limit, 500))),
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            message_ids: list[str] = []
            status = "verified"
            error = ""
            service = str(row["service"])
            open_id = str(row["open_id"])
            active_open_ids = {item["open_id"] for item in self._subscribers_for(service)}
            gate_open = self.automatic_delivery_enabled(service) and open_id in active_open_ids
            if not gate_open:
                status = "cancelled"
                error = "自动推送已暂停或接收人已取消该项订阅"
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
                )
            except Exception as exc:
                status = "retrying"
                error = str(exc)[:900]
            with closing(self._connect()) as db, db:
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
                else:
                    retry_at = ((now or datetime.now().astimezone()).astimezone() + timedelta(minutes=15)).isoformat(timespec="seconds")
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

    def dispatch_news_after_crawl(
        self,
        *,
        crawl_slot: str,
        slot_label: str,
        items: list[dict[str, Any]],
        completed_at: str = "",
    ) -> dict[str, Any]:
        """Push one crawler-completion digest using each subscriber's daily count."""
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
        content_ref = f"{NEWS_CRAWL_REF_PREFIX}{crawl_slot}"
        period_name = "CMHK战略早茶" if "晨间" in slot_label else "CMHK战略下午茶"
        with closing(self._connect()) as db:
            rows = db.execute(
                """SELECT s.open_id, s.frequency, s.news_item_limit, s.news_categories FROM subscribers s
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
            news_item_limit = int(row["news_item_limit"] or 10)
            if news_item_limit not in VALID_NEWS_ITEM_LIMITS:
                news_item_limit = 10
            news_categories = normalize_news_categories(row["news_categories"])
            recipient_items = filter_news_by_categories(
                clean_items,
                news_categories,
                limit=news_item_limit,
            )
            category_label = news_category_summary(news_categories)
            title = (
                f"{period_name}｜最新{len(recipient_items)}条战略新闻｜{category_label}"
                if recipient_items
                else f"{period_name}｜关注板块暂无新增"
            )
            body = encode_strategic_news_digest(recipient_items)
            dispatch_key = (
                f"twice_daily:{crawl_date}:{delivery_window}"
                if frequency == "twice_daily"
                else f"once_daily:{crawl_date}"
            )
            now = _now_hkt()
            with closing(self._connect()) as db:
                # Serialize the legacy-row check and canonical claim. Older
                # releases keyed twice-daily sends by the exact clock time, so
                # a same-day schedule change (for example 13:30 -> 14:00)
                # could otherwise send the same afternoon digest twice.
                db.execute("BEGIN IMMEDIATE")
                legacy_claimed = False
                if frequency == "twice_daily":
                    legacy_claimed = db.execute(
                        """SELECT 1 FROM news_crawl_dispatches
                           WHERE open_id=? AND crawl_date=? AND frequency='twice_daily'
                             AND CASE
                                   WHEN substr(crawl_slot, 12, 5) < '12:00' THEN 'morning'
                                   ELSE 'afternoon'
                                 END=?
                           LIMIT 1""",
                        (open_id, crawl_date, delivery_window),
                    ).fetchone() is not None
                cursor = db.execute(
                    """INSERT OR IGNORE INTO news_crawl_dispatches(
                           open_id, dispatch_key, crawl_slot, crawl_date, frequency,
                           status, created_at, updated_at
                       ) SELECT ?, ?, ?, ?, ?, 'sending', ?, ?
                         WHERE ?=0""",
                    (
                        open_id, dispatch_key, crawl_slot, crawl_date, frequency,
                        now, now, int(legacy_claimed),
                    ),
                )
                claimed = cursor.rowcount == 1
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
            batch_id = hashlib.sha256(f"news-crawl:{crawl_slot}:{open_id}".encode()).hexdigest()[:24]
            with closing(self._connect()) as db, db:
                cursor = db.execute(
                    """INSERT INTO deliveries(batch_id, open_id, service, mode, content_ref, status, message_ids, error, created_at)
                       VALUES(?, ?, 'news', 'text', ?, 'sending', '[]', '', ?)""",
                    (batch_id, open_id, content_ref, now),
                )
                delivery_id = int(cursor.lastrowid)
                db.execute(
                    """UPDATE news_crawl_dispatches SET delivery_id=?, updated_at=?
                       WHERE open_id=? AND dispatch_key=?""",
                    (delivery_id, now, open_id, dispatch_key),
                )
            message_ids: list[str] = []
            status = "verified"
            error = ""
            try:
                message_ids = self._deliver_one(
                    open_id=open_id,
                    service="news",
                    mode="text",
                    content_ref=content_ref,
                    title=title,
                    body=body,
                    batch_id=batch_id,
                    profile=self.delivery_profile,
                )
            except Exception as exc:
                status = "retrying"
                error = str(exc)[:900]
            with closing(self._connect()) as db, db:
                db.execute(
                    "UPDATE deliveries SET status=?, message_ids=?, error=? WHERE id=?",
                    (status, json.dumps(message_ids), error, delivery_id),
                )
                db.execute(
                    """UPDATE news_crawl_dispatches
                       SET status=?, message_ids=?, last_error=?, updated_at=?
                       WHERE open_id=? AND dispatch_key=?""",
                    (status, json.dumps(message_ids), error, _now_hkt(), open_id, dispatch_key),
                )
                if status == "retrying":
                    retry_at = (datetime.now().astimezone() + timedelta(minutes=15)).isoformat(timespec="seconds")
                    db.execute(
                        """INSERT INTO pending_subscription_deliveries(
                               delivery_id, open_id, service, mode, content_ref, title, body,
                               frequency, due_at, status, created_at
                           ) VALUES(?, ?, 'news', 'text', ?, ?, ?, 'crawl_retry', ?, 'queued', ?)""",
                        (delivery_id, open_id, content_ref, title, body, retry_at, _now_hkt()),
                    )
            results.append({
                "open_id": open_id,
                "frequency": frequency,
                "news_item_limit": news_item_limit,
                "news_categories": news_categories,
                "news_category_labels": [NEWS_CATEGORY_LABELS[item] for item in news_categories],
                "status": status,
                "message_ids": message_ids,
                "error": error,
            })
        return {
            "crawl_slot": crawl_slot,
            "completed_at": completed_at or _now_hkt(),
            "schedule_enabled": True,
            "recipient_count": len(results),
            "verified_count": sum(1 for item in results if item["status"] == "verified"),
            "retrying_count": sum(1 for item in results if item["status"] == "retrying"),
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
    ) -> dict[str, Any]:
        if service not in VALID_SERVICES or mode not in VALID_DELIVERY_MODES:
            raise ValueError("推送服务或交付方式无效")
        if service == "news" and mode != "text":
            raise ValueError("战略新闻目前只支持文字推送")
        if service in {"weekly", "performance"} and mode not in {"pdf", "pdf_audio", "audio"}:
            raise ValueError("周报和业绩摘要只支持 PDF、PDF 加独立语音或仅语音")
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
            title = title.strip() or report_path.stem
        else:
            title = title.strip() or "战略新闻"
            body = body.strip()
            if not body:
                raise ValueError("新闻推送正文不能为空")
            content_ref = title
        batch_source = batch_key or f"{service}:{mode}:{content_ref}:{_now_hkt()}"
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
                    due_at = (datetime.now().astimezone() + timedelta(minutes=15)).isoformat(timespec="seconds")
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

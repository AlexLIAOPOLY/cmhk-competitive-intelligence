"""Server-side Feishu subscriptions and controlled delivery for CMHK content."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import zipfile
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree


HKT_OFFSET = "+08:00"
SERVICE_LABELS = {
    "weekly": "战略双周报",
    "performance": "运营商业绩摘要",
    "news": "战略新闻",
}
VALID_SERVICES = frozenset(SERVICE_LABELS)
VALID_DELIVERY_MODES = frozenset({"text", "audio", "both", "pdf", "pdf_audio"})
FREQUENCY_LABELS = {
    "immediate": "即时接收",
    "daily": "每天 18:00",
    "weekly": "每周五 18:00",
}
VALID_FREQUENCIES = frozenset(FREQUENCY_LABELS)
OPEN_ID_RE = re.compile(r"^ou_[A-Za-z0-9]+$")
CHAT_ID_RE = re.compile(r"^oc_[A-Za-z0-9]+$")
MESSAGE_ID_RE = re.compile(r"^om_[A-Za-z0-9]+$")


def _now_hkt() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _next_due_at(frequency: str, now: datetime | None = None) -> str:
    current = (now or datetime.now().astimezone()).astimezone()
    if frequency == "daily":
        due = current.replace(hour=18, minute=0, second=0, microsecond=0)
        if due <= current:
            due += timedelta(days=1)
    elif frequency == "weekly":
        days = (4 - current.weekday()) % 7
        due = (current + timedelta(days=days)).replace(hour=18, minute=0, second=0, microsecond=0)
        if due <= current:
            due += timedelta(days=7)
    else:
        due = current
    return due.isoformat(timespec="seconds")


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


def subscription_entry_card() -> dict[str, Any]:
    """Card 2.0 form used as the colleague-facing self-service entry point."""
    return {
        "schema": "2.0",
        "config": {
            "update_multi": True,
            "width_mode": "default",
            "summary": {"content": "CMHK战略情报订阅中心 · 自助选择推送服务"},
        },
        "header": {
            "title": {"tag": "plain_text", "content": "CMHK战略情报订阅中心"},
            "subtitle": {"tag": "plain_text", "content": "按需订阅 · 可随时重新选择"},
            "template": "wathet",
            "icon": {"tag": "standard_icon", "token": "file-form_colorful"},
            "text_tag_list": [
                {"tag": "text_tag", "text": {"tag": "plain_text", "content": "自助订阅"}, "color": "wathet"}
            ],
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 20px 12px",
            "vertical_spacing": "12px",
            "elements": [
                {
                    "tag": "markdown",
                    "content": "**选择希望接收的内容**\n提交后，机器人会把正式内容单独推送给你；再次提交会覆盖原选择。",
                },
                {
                    "tag": "form",
                    "name": "subscriptionForm",
                    "direction": "vertical",
                    "vertical_spacing": "12px",
                    "elements": [
                        {
                            "tag": "multi_select_static",
                            "name": "services",
                            "required": True,
                            "width": "fill",
                            "placeholder": {"tag": "plain_text", "content": "请选择一个或多个订阅服务"},
                            "options": [
                                {"text": {"tag": "plain_text", "content": "战略双周报（PDF / 可选独立语音）"}, "value": "weekly"},
                                {"text": {"tag": "plain_text", "content": "运营商业绩摘要"}, "value": "performance"},
                                {"text": {"tag": "plain_text", "content": "战略新闻"}, "value": "news"},
                            ],
                        },
                        {
                            "tag": "select_static",
                            "name": "frequency",
                            "required": True,
                            "width": "fill",
                            "placeholder": {"tag": "plain_text", "content": "请选择接收频率"},
                            "options": [
                                {"text": {"tag": "plain_text", "content": "即时接收"}, "value": "immediate"},
                                {"text": {"tag": "plain_text", "content": "每天 18:00"}, "value": "daily"},
                                {"text": {"tag": "plain_text", "content": "每周五 18:00"}, "value": "weekly"},
                            ],
                        },
                        {
                            "tag": "button",
                            "name": "saveSubscriptions",
                            "text": {"tag": "plain_text", "content": "保存我的订阅"},
                            "type": "primary_filled",
                            "width": "fill",
                            "form_action_type": "submit",
                        },
                    ],
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "暂停我的全部订阅"},
                    "type": "default",
                    "width": "fill",
                    "confirm": {
                        "title": {"tag": "plain_text", "content": "暂停全部订阅？"},
                        "text": {"tag": "plain_text", "content": "之后可重新提交上方表单恢复。"},
                    },
                    "behaviors": [
                        {"type": "callback", "value": {"action": "cmhk_subscription_pause_all_v1"}}
                    ],
                },
                {
                    "tag": "markdown",
                    "content": "<font color='grey'>仅记录你的飞书身份与订阅选择，不收集额外个人信息。</font>",
                    "text_size": "notation",
                },
            ],
        },
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
                    chat_id TEXT NOT NULL,
                    source_profile TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
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
                """
            )
            columns = {str(row[1]) for row in db.execute("PRAGMA table_info(subscribers)").fetchall()}
            if "callback_open_id" not in columns:
                db.execute("ALTER TABLE subscribers ADD COLUMN callback_open_id TEXT NOT NULL DEFAULT ''")
            if "union_id" not in columns:
                db.execute("ALTER TABLE subscribers ADD COLUMN union_id TEXT NOT NULL DEFAULT ''")
            if "frequency" not in columns:
                db.execute("ALTER TABLE subscribers ADD COLUMN frequency TEXT NOT NULL DEFAULT 'immediate'")
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
        frequency: str = "immediate",
    ) -> dict[str, Any]:
        normalized = sorted({str(item) for item in services if str(item) in VALID_SERVICES})
        if not normalized:
            raise ValueError("至少选择一个订阅服务")
        if frequency not in VALID_FREQUENCIES:
            raise ValueError("接收频率无效")
        now = _now_hkt()
        with closing(self._connect()) as db, db:
            db.execute(
                """INSERT INTO subscribers(open_id, callback_open_id, union_id, display_name, status, frequency, source_chat_id, created_at, updated_at)
                   VALUES(?, ?, ?, ?, 'active', ?, ?, ?, ?)
                   ON CONFLICT(open_id) DO UPDATE SET display_name=excluded.display_name,
                   callback_open_id=excluded.callback_open_id, union_id=excluded.union_id,
                   status='active', frequency=excluded.frequency,
                   source_chat_id=excluded.source_chat_id, updated_at=excluded.updated_at""",
                (open_id, callback_open_id, union_id, display_name, frequency, source_chat_id, now, now),
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
        frequency = "immediate"
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
            frequency = str(form.get("frequency") or "")
            if frequency not in VALID_FREQUENCIES:
                raise ValueError("请选择有效的接收频率")
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
                "SELECT source_profile, target_type, target_id FROM subscription_entry_cards WHERE message_id=? AND chat_id=?",
                (message_id, chat_id),
            ).fetchone()
        if published is None:
            raise ValueError("订阅回调并非来自后台已发布的受控卡片")
        source_profile = str(published["source_profile"] or self.entry_profile)
        if str(published["target_type"]) == "user" and str(published["target_id"]) != open_id:
            raise ValueError("订阅回调用户与受邀人不一致")
        identity = self.resolve_user(open_id, source_profile=source_profile)
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
                db.execute(
                    """UPDATE subscription_invitations
                       SET status='paused', responded_at=?, updated_at=?
                       WHERE message_id=? AND callback_open_id=?""",
                    (_now_hkt(), _now_hkt(), message_id, identity["callback_open_id"]),
                )
            confirmation = self._send_markdown(
                identity["callback_open_id"],
                "#### 订阅已暂停\n\n你的全部战略情报推送已暂停。需要恢复时，重新提交订阅卡片即可。",
                idempotency_key=f"subpause-{event_id}"[:50],
                profile=source_profile,
            )
            self._verify_message(confirmation, profile=source_profile)
            return {
                "status": "subscription_paused",
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
        )
        with closing(self._connect()) as db, db:
            db.execute(
                """UPDATE subscription_invitations
                   SET status='accepted', responded_at=?, updated_at=?
                   WHERE message_id=? AND callback_open_id=?""",
                (_now_hkt(), _now_hkt(), message_id, identity["callback_open_id"]),
            )
        labels = "、".join(SERVICE_LABELS[item] for item in saved["services"])
        confirmation = self._send_markdown(
            identity["callback_open_id"],
            f"#### 订阅已生效\n\n{identity['display_name']}，你当前订阅：**{labels}**。\n\n接收频率：**{saved['frequency_label']}**。以后重新提交订阅卡片即可覆盖选择。",
            idempotency_key=f"suback-{event_id}"[:50],
            profile=source_profile,
        )
        self._verify_message(confirmation, profile=source_profile)
        saved["confirmation_message_id"] = confirmation
        return {"status": "subscription_saved", **saved}

    def list_summary(self, *, delivery_limit: int = 80) -> dict[str, Any]:
        with closing(self._connect()) as db, db:
            rows = db.execute(
                """SELECT s.open_id, s.callback_open_id, s.union_id, s.display_name, s.status, s.frequency,
                          s.source_chat_id, s.created_at, s.updated_at,
                          GROUP_CONCAT(CASE WHEN x.active=1 THEN x.service END) AS services
                   FROM subscribers s LEFT JOIN subscriptions x ON x.open_id=s.open_id
                   GROUP BY s.open_id ORDER BY s.updated_at DESC"""
            ).fetchall()
            deliveries = db.execute(
                "SELECT * FROM deliveries ORDER BY id DESC LIMIT ?", (max(1, min(delivery_limit, 300)),)
            ).fetchall()
            invitations = db.execute(
                "SELECT * FROM subscription_invitations ORDER BY id DESC LIMIT 200"
            ).fetchall()
        subscribers = []
        counts = {key: 0 for key in VALID_SERVICES}
        for row in rows:
            services = sorted(filter(None, str(row["services"] or "").split(",")))
            if row["status"] == "active":
                for service in services:
                    if service in counts:
                        counts[service] += 1
            subscribers.append({
                **dict(row),
                "services": services,
                "frequency_label": FREQUENCY_LABELS.get(str(row["frequency"]), str(row["frequency"])),
            })
        return {
            "services": [{"key": key, "label": SERVICE_LABELS[key], "subscriber_count": counts[key]} for key in ("weekly", "performance", "news")],
            "subscribers": subscribers,
            "deliveries": [dict(item) | {"message_ids": json.loads(item["message_ids"] or "[]")} for item in deliveries],
            "invite_candidates": self.list_invite_candidates(),
            "invitations": [dict(item) for item in invitations],
            "invitation_counts": {
                status: sum(1 for item in invitations if str(item["status"]) == status)
                for status in ("pending", "accepted", "paused", "failed")
            },
            "invitation_permissions": self.invitation_permission_snapshot(),
            "active_subscriber_count": sum(1 for row in subscribers if row["status"] == "active"),
            "updated_at": _now_hkt(),
        }

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
                        person["en_name"], person["avatar_url"], person["job_title"],
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
                sent = self._send_entry_card_to_user(
                    callback_open_id, invitation=True, profile=source_profile
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

    def update_subscriber(
        self,
        open_id: str,
        *,
        services: list[str],
        status: str = "active",
        frequency: str = "immediate",
    ) -> dict[str, Any]:
        if status not in {"active", "paused"}:
            raise ValueError("订阅者状态只能是 active 或 paused")
        with closing(self._connect()) as db, db:
            row = db.execute(
                "SELECT display_name, source_chat_id, callback_open_id, union_id FROM subscribers WHERE open_id=?",
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
            if target_id != primary or not OPEN_ID_RE.fullmatch(target_id):
                raise ValueError("测试卡片只允许发送给系统管理员")
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
    ) -> dict[str, Any]:
        if not OPEN_ID_RE.fullmatch(callback_open_id):
            raise ValueError("受邀人 open_id 无效")
        return self._send_entry_card(
            target_id=callback_open_id,
            target_type="user",
            key_context="invite" if invitation else "test",
            profile=profile or self.entry_profile,
        )

    def _send_entry_card(
        self,
        *,
        target_id: str,
        target_type: str,
        key_context: str = "publish",
        profile: str = "",
    ) -> dict[str, Any]:
        source_profile = profile or self.entry_profile
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
        card = subscription_entry_card()
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
                """INSERT INTO subscription_entry_cards(message_id, target_type, target_id, chat_id, source_profile, created_at)
                   VALUES(?, ?, ?, ?, ?, ?)
                   ON CONFLICT(message_id) DO UPDATE SET target_type=excluded.target_type,
                   target_id=excluded.target_id, chat_id=excluded.chat_id,
                   source_profile=excluded.source_profile, created_at=excluded.created_at""",
                (message_id, target_type, target_id, chat_id, source_profile, _now_hkt()),
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
                """SELECT s.open_id, s.frequency FROM subscribers s JOIN subscriptions x ON x.open_id=s.open_id
                   WHERE s.status='active' AND x.service=? AND x.active=1 ORDER BY s.open_id""",
                (service,),
            ).fetchall()
        return [
            {
                "open_id": str(row["open_id"]),
                "frequency": str(row["frequency"] or "immediate"),
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
            text = body if service == "news" else self._report_text(report_path)  # type: ignore[arg-type]
            for index, chunk in enumerate(self._text_chunks(title, text), start=1):
                message_ids.append(self._send_markdown(
                    open_id,
                    chunk,
                    idempotency_key=f"{batch_id}-t{index}-{open_id[-6:]}",
                    profile=profile,
                ))
        if mode in {"pdf", "pdf_audio"}:
            pdf = self._report_pdf(report_path)  # type: ignore[arg-type]
            message_ids.append(self._send_file(
                open_id,
                pdf,
                idempotency_key=f"{batch_id}-p-{open_id[-6:]}",
                profile=profile,
            ))
        if mode in {"audio", "both", "pdf_audio"}:
            audio = self._find_audio(report_path)  # type: ignore[arg-type]
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

    def push(
        self,
        *,
        service: str,
        mode: str,
        path: str = "",
        title: str = "",
        body: str = "",
        test_open_id: str = "",
        confirm_bulk: bool = False,
    ) -> dict[str, Any]:
        if service not in VALID_SERVICES or mode not in VALID_DELIVERY_MODES:
            raise ValueError("推送服务或交付方式无效")
        if service == "news" and mode != "text":
            raise ValueError("战略新闻目前只支持文字推送")
        if service in {"weekly", "performance"} and mode not in {"pdf", "pdf_audio"}:
            raise ValueError("周报和业绩摘要只支持 PDF，语音可作为独立消息附加")
        recipients = self._subscribers_for(service)
        send_profile = self.delivery_profile
        if test_open_id:
            card_actions = self.config.get("card_actions") if isinstance(self.config.get("card_actions"), dict) else {}
            primary_test_open_id = str(card_actions.get("primary_handler_open_id") or "")
            if test_open_id != primary_test_open_id:
                raise ValueError("测试推送只允许发送给系统管理员")
            recipients = [{"open_id": test_open_id, "frequency": "immediate"}]
            send_profile = self.entry_profile
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
        batch_id = hashlib.sha256(f"{service}:{mode}:{content_ref}:{_now_hkt()}".encode()).hexdigest()[:24]
        results = []
        for recipient in recipients:
            open_id = recipient["open_id"]
            frequency = recipient["frequency"] if recipient["frequency"] in VALID_FREQUENCIES else "immediate"
            message_ids: list[str] = []
            status = "queued" if frequency != "immediate" else "sending"
            error = ""
            with closing(self._connect()) as db, db:
                cursor = db.execute(
                    """INSERT INTO deliveries(batch_id, open_id, service, mode, content_ref, status, message_ids, error, created_at)
                       VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (batch_id, open_id, service, mode, content_ref, status, json.dumps(message_ids), error, _now_hkt()),
                )
                delivery_id = int(cursor.lastrowid)
                if frequency != "immediate":
                    due_at = _next_due_at(frequency)
                    db.execute(
                        """INSERT INTO pending_subscription_deliveries(
                               delivery_id, open_id, service, mode, content_ref, title, body,
                               frequency, due_at, status, created_at
                           ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)""",
                        (delivery_id, open_id, service, mode, content_ref, title, body, frequency, due_at, _now_hkt()),
                    )
                else:
                    due_at = ""
            if frequency == "immediate":
                try:
                    message_ids = self._deliver_one(
                        open_id=open_id,
                        service=service,
                        mode=mode,
                        content_ref=content_ref,
                        title=title,
                        body=body,
                        batch_id=batch_id,
                        profile=send_profile,
                    )
                    status = "verified"
                except Exception as exc:
                    status = "failed"
                    error = str(exc)[:900]
                with closing(self._connect()) as db, db:
                    db.execute(
                        "UPDATE deliveries SET status=?, message_ids=?, error=? WHERE id=?",
                        (status, json.dumps(message_ids), error, delivery_id),
                    )
            results.append({
                "open_id": open_id,
                "frequency": frequency,
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
            "queued_count": sum(1 for item in results if item["status"] == "queued"),
            "failed_count": sum(1 for item in results if item["status"] == "failed"),
            "results": results,
        }

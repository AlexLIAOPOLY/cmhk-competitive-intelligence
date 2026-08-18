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
from datetime import datetime
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
VALID_DELIVERY_MODES = frozenset({"text", "audio", "both"})
OPEN_ID_RE = re.compile(r"^ou_[A-Za-z0-9]+$")
CHAT_ID_RE = re.compile(r"^oc_[A-Za-z0-9]+$")
MESSAGE_ID_RE = re.compile(r"^om_[A-Za-z0-9]+$")


def _now_hkt() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


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
                                {"text": {"tag": "plain_text", "content": "战略双周报（文字 / 语音）"}, "value": "weekly"},
                                {"text": {"tag": "plain_text", "content": "运营商业绩摘要"}, "value": "performance"},
                                {"text": {"tag": "plain_text", "content": "战略新闻"}, "value": "news"},
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
                    created_at TEXT NOT NULL
                );
                """
            )
            columns = {str(row[1]) for row in db.execute("PRAGMA table_info(subscribers)").fetchall()}
            if "callback_open_id" not in columns:
                db.execute("ALTER TABLE subscribers ADD COLUMN callback_open_id TEXT NOT NULL DEFAULT ''")
            if "union_id" not in columns:
                db.execute("ALTER TABLE subscribers ADD COLUMN union_id TEXT NOT NULL DEFAULT ''")

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

    def resolve_user(self, open_id: str) -> dict[str, str]:
        if not OPEN_ID_RE.fullmatch(open_id):
            raise ValueError("无效的飞书 open_id")
        payload = self._lark([
            "lark-cli", "contact", "+get-user", "--user-id", open_id,
            "--user-id-type", "open_id", "--as", "bot", "--profile", self.entry_profile,
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
        return {"display_name": name, "callback_open_id": open_id, "union_id": union_id, "open_id": delivery_open_id}

    def save_subscriptions(self, open_id: str, display_name: str, services: list[str], source_chat_id: str = "", callback_open_id: str = "", union_id: str = "") -> dict[str, Any]:
        normalized = sorted({str(item) for item in services if str(item) in VALID_SERVICES})
        if not normalized:
            raise ValueError("至少选择一个订阅服务")
        now = _now_hkt()
        with closing(self._connect()) as db, db:
            db.execute(
                """INSERT INTO subscribers(open_id, callback_open_id, union_id, display_name, status, source_chat_id, created_at, updated_at)
                   VALUES(?, ?, ?, ?, 'active', ?, ?, ?)
                   ON CONFLICT(open_id) DO UPDATE SET display_name=excluded.display_name,
                   callback_open_id=excluded.callback_open_id, union_id=excluded.union_id,
                   status='active', source_chat_id=excluded.source_chat_id, updated_at=excluded.updated_at""",
                (open_id, callback_open_id, union_id, display_name, source_chat_id, now, now),
            )
            for service in VALID_SERVICES:
                db.execute(
                    """INSERT INTO subscriptions(open_id, service, active, updated_at) VALUES(?, ?, ?, ?)
                       ON CONFLICT(open_id, service) DO UPDATE SET active=excluded.active, updated_at=excluded.updated_at""",
                    (open_id, service, int(service in normalized), now),
                )
        return {"open_id": open_id, "display_name": display_name, "services": normalized, "updated_at": now}

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
                "SELECT 1 FROM subscription_entry_cards WHERE message_id=? AND chat_id=?",
                (message_id, chat_id),
            ).fetchone()
        if published is None:
            raise ValueError("订阅回调并非来自后台已发布的受控卡片")
        identity = self.resolve_user(open_id)
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
            confirmation = self._send_markdown(
                identity["callback_open_id"],
                "#### 订阅已暂停\n\n你的全部战略情报推送已暂停。需要恢复时，重新提交订阅卡片即可。",
                idempotency_key=f"subpause-{event_id}"[:50],
                profile=self.entry_profile,
            )
            self._verify_message(confirmation, profile=self.entry_profile)
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
        )
        labels = "、".join(SERVICE_LABELS[item] for item in saved["services"])
        confirmation = self._send_markdown(
            identity["callback_open_id"],
            f"#### 订阅已生效\n\n{identity['display_name']}，你当前订阅：**{labels}**。\n\n以后重新提交订阅卡片即可覆盖选择。",
            idempotency_key=f"suback-{event_id}"[:50],
            profile=self.entry_profile,
        )
        self._verify_message(confirmation, profile=self.entry_profile)
        saved["confirmation_message_id"] = confirmation
        return {"status": "subscription_saved", **saved}

    def list_summary(self, *, delivery_limit: int = 80) -> dict[str, Any]:
        with closing(self._connect()) as db, db:
            rows = db.execute(
                """SELECT s.open_id, s.callback_open_id, s.union_id, s.display_name, s.status,
                          s.source_chat_id, s.created_at, s.updated_at,
                          GROUP_CONCAT(CASE WHEN x.active=1 THEN x.service END) AS services
                   FROM subscribers s LEFT JOIN subscriptions x ON x.open_id=s.open_id
                   GROUP BY s.open_id ORDER BY s.updated_at DESC"""
            ).fetchall()
            deliveries = db.execute(
                "SELECT * FROM deliveries ORDER BY id DESC LIMIT ?", (max(1, min(delivery_limit, 300)),)
            ).fetchall()
        subscribers = []
        counts = {key: 0 for key in VALID_SERVICES}
        for row in rows:
            services = sorted(filter(None, str(row["services"] or "").split(",")))
            if row["status"] == "active":
                for service in services:
                    if service in counts:
                        counts[service] += 1
            subscribers.append({**dict(row), "services": services})
        return {
            "services": [{"key": key, "label": SERVICE_LABELS[key], "subscriber_count": counts[key]} for key in ("weekly", "performance", "news")],
            "subscribers": subscribers,
            "deliveries": [dict(item) | {"message_ids": json.loads(item["message_ids"] or "[]")} for item in deliveries],
            "active_subscriber_count": sum(1 for row in subscribers if row["status"] == "active"),
            "updated_at": _now_hkt(),
        }

    def update_subscriber(self, open_id: str, *, services: list[str], status: str = "active") -> dict[str, Any]:
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
        key = hashlib.sha256(f"subscription-entry:{target_type}:{target_id}:{datetime.now().date()}".encode()).hexdigest()[:32]
        payload = self._lark([
            "lark-cli", "im", "+messages-send", *target_args,
            "--msg-type", "interactive", "--content", json.dumps(subscription_entry_card(), ensure_ascii=False),
            "--idempotency-key", key, "--as", "bot", "--profile", self.entry_profile, "--format", "json",
        ])
        message_id = self._message_id(payload)
        self._verify_message(message_id, profile=self.entry_profile)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        chat_id = str(data.get("chat_id") or "")
        if not CHAT_ID_RE.fullmatch(chat_id):
            raise RuntimeError("订阅卡片发送成功但没有返回有效会话ID")
        with closing(self._connect()) as db, db:
            db.execute(
                """INSERT INTO subscription_entry_cards(message_id, target_type, target_id, chat_id, created_at)
                   VALUES(?, ?, ?, ?, ?)
                   ON CONFLICT(message_id) DO UPDATE SET target_type=excluded.target_type,
                   target_id=excluded.target_id, chat_id=excluded.chat_id, created_at=excluded.created_at""",
                (message_id, target_type, target_id, chat_id, _now_hkt()),
            )
        return {"message_id": message_id, "target_id": target_id, "target_type": target_type, "verified": True}

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

    def _subscribers_for(self, service: str) -> list[str]:
        with closing(self._connect()) as db, db:
            rows = db.execute(
                """SELECT s.open_id FROM subscribers s JOIN subscriptions x ON x.open_id=s.open_id
                   WHERE s.status='active' AND x.service=? AND x.active=1 ORDER BY s.open_id""",
                (service,),
            ).fetchall()
        return [str(row["open_id"]) for row in rows]

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
        recipients = self._subscribers_for(service)
        send_profile = self.delivery_profile
        if test_open_id:
            card_actions = self.config.get("card_actions") if isinstance(self.config.get("card_actions"), dict) else {}
            primary_test_open_id = str(card_actions.get("primary_handler_open_id") or "")
            if test_open_id != primary_test_open_id:
                raise ValueError("测试推送只允许发送给系统管理员")
            recipients = [test_open_id]
            send_profile = self.entry_profile
        elif not confirm_bulk:
            raise ValueError("批量推送必须在后台完成二次确认")
        if not recipients:
            raise ValueError("当前没有该服务的有效订阅者")
        report_path: Path | None = None
        content_ref = ""
        if service in {"weekly", "performance"}:
            relative = Path(path)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("报告路径无效")
            report_path = (self.runtime_root / relative).resolve()
            if self.runtime_root.resolve() not in report_path.parents or report_path.suffix.lower() != ".docx" or not report_path.exists():
                raise ValueError("报告文件不存在或不允许推送")
            title = title.strip() or report_path.stem
            content_ref = str(relative)
        else:
            title = title.strip() or "战略新闻"
            body = body.strip()
            if not body:
                raise ValueError("新闻推送正文不能为空")
            content_ref = title
        batch_id = hashlib.sha256(f"{service}:{mode}:{content_ref}:{_now_hkt()}".encode()).hexdigest()[:24]
        results = []
        for open_id in recipients:
            message_ids: list[str] = []
            status = "verified"
            error = ""
            try:
                if mode in {"text", "both"}:
                    text = body if service == "news" else self._report_text(report_path)  # type: ignore[arg-type]
                    for index, chunk in enumerate(self._text_chunks(title, text), start=1):
                        message_ids.append(self._send_markdown(open_id, chunk, idempotency_key=f"{batch_id}-t{index}-{open_id[-6:]}", profile=send_profile))
                if mode in {"audio", "both"}:
                    audio = self._find_audio(report_path)  # type: ignore[arg-type]
                    message_ids.append(self._send_audio(open_id, audio, idempotency_key=f"{batch_id}-a-{open_id[-6:]}", profile=send_profile))
                for message_id in message_ids:
                    self._verify_message(message_id, profile=send_profile)
            except Exception as exc:
                status = "failed"
                error = str(exc)[:900]
            with closing(self._connect()) as db, db:
                db.execute(
                    """INSERT INTO deliveries(batch_id, open_id, service, mode, content_ref, status, message_ids, error, created_at)
                       VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (batch_id, open_id, service, mode, content_ref, status, json.dumps(message_ids), error, _now_hkt()),
                )
            results.append({"open_id": open_id, "status": status, "message_ids": message_ids, "error": error})
        return {
            "batch_id": batch_id,
            "service": service,
            "mode": mode,
            "recipient_count": len(results),
            "verified_count": sum(1 for item in results if item["status"] == "verified"),
            "failed_count": sum(1 for item in results if item["status"] == "failed"),
            "results": results,
        }

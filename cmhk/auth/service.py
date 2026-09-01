from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import ssl
import subprocess
import threading
import time
import uuid
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse


ROLE_LABELS = {
    "UNCONFIGURED": "待分配",
    "ADMIN": "系统管理员",
    "LEADER": "领导",
    "ANALYST": "情报分析",
    "CONTENT": "内容运营",
    "OPERATIONS": "系统运维",
}

MODULE_LABELS = {
    "dashboard": "战略总览",
    "monitoring": "战略监控体系",
    "news": "新闻采集",
    "review": "新闻审核",
    "competitor": "竞对分析",
    "weekly": "战略周报",
    "performance": "业绩摘要",
    "subscriptions": "订阅与推送",
    "ai": "小竞AI",
    "log": "任务日志",
    "fault": "报警处置",
    "organization": "组织管理",
}

ROLE_MODULES = {
    "UNCONFIGURED": [],
    "ADMIN": list(MODULE_LABELS),
    "LEADER": ["dashboard"],
    "ANALYST": ["dashboard", "monitoring", "competitor", "weekly", "performance", "ai"],
    "CONTENT": ["dashboard", "news", "review", "weekly", "performance", "subscriptions"],
    "OPERATIONS": ["dashboard", "monitoring", "subscriptions", "log", "fault"],
}

_API_MODULE_PREFIXES = (
    ("/api/auth/", None),
    ("/api/executive-intelligence/regenerate", "competitor"),
    ("/api/executive-intelligence", "dashboard"),
    ("/api/strategic-briefs", "dashboard"),
    ("/api/status", "dashboard"),
    ("/api/scheduler-overview", "monitoring"),
    ("/api/company-metrics", "competitor"),
    ("/api/executive-company-benchmarks", "competitor"),
    ("/api/competitor", "competitor"),
    ("/api/data-curation", "competitor"),
    ("/api/curation-quality", "competitor"),
    ("/api/news-review", "review"),
    ("/api/news", "news"),
    ("/api/strategic-news", "news"),
    ("/api/weekly-report", "weekly"),
    ("/api/generate-carrier", "performance"),
    ("/api/generate", "weekly"),
    ("/api/report-audio", "weekly"),
    ("/api/report-file", "weekly"),
    ("/api/audio/generate", "weekly"),
    ("/api/delete-files", "weekly"),
    ("/api/subscriptions", "subscriptions"),
    ("/api/ai-", "ai"),
    ("/api/chat", "ai"),
    ("/api/agent", "ai"),
    ("/api/rag", "ai"),
    ("/api/task", "log"),
    ("/api/crawl", "log"),
    ("/api/log-report.pdf", "log"),
    ("/api/alert-report.pdf", "fault"),
    ("/api/fault", "fault"),
    ("/api/project-incidents", "fault"),
)

_API_ANY_MODULE_PREFIXES = (
    ("/api/weekly-report-preference", ("weekly", "subscriptions")),
    ("/api/performance-report-preference", ("performance", "subscriptions")),
    ("/api/report-editor", ("weekly", "performance")),
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _load_env_file(path: str) -> None:
    target = Path(path).expanduser() if path else None
    if not target or not target.is_file():
        return
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _auth_env_file_path(configured_path: str) -> str:
    """Prefer a launchd-safe private mirror over a protected Desktop path."""
    configured = str(configured_path or "").strip()
    if not configured:
        return ""
    runtime_path = str(
        os.environ.get("CMHK_AUTH_RUNTIME_ENV_FILE")
        or (
            Path.home()
            / "Library"
            / "Application Support"
            / "CMHK"
            / "auth"
            / "runtime.env"
        )
    )
    runtime_target = Path(runtime_path).expanduser()
    return str(runtime_target) if runtime_target.is_file() else configured


class AuthService:
    cookie_name = "cmhk_session"
    oauth_cookie_name = "cmhk_feishu_oauth"

    def __init__(self, root: Path):
        _load_env_file(_auth_env_file_path(os.environ.get("CMHK_AUTH_ENV_FILE", "")))
        self.root = root
        self.state_dir = root / "var" / "auth"
        self.users_path = self.state_dir / "users.json"
        self.sessions_path = self.state_dir / "sessions.json"
        self.audit_path = self.state_dir / "admin-audit.json"
        self.operation_audit_path = self.state_dir / "operation-audit.jsonl"
        self.directory_cache_path = self.state_dir / "feishu-directory-cache.json"
        self.lock = threading.RLock()
        self.require_login = os.environ.get("CMHK_AUTH_REQUIRE_LOGIN", "1") == "1"
        self.allow_dev_login = os.environ.get("CMHK_AUTH_ALLOW_DEV_LOGIN", "0") == "1"
        self.bootstrap_first_feishu_admin = os.environ.get("CMHK_AUTH_BOOTSTRAP_FIRST_FEISHU_ADMIN", "0") == "1"
        self.app_id = (os.environ.get("CMHK_FEISHU_APP_ID") or os.environ.get("FEISHU_APP_ID") or "").strip()
        self.app_secret = (os.environ.get("CMHK_FEISHU_APP_SECRET") or os.environ.get("FEISHU_APP_SECRET") or "").strip()
        self.tenant_key = (os.environ.get("CMHK_FEISHU_TENANT_KEY") or os.environ.get("FEISHU_TENANT_KEY") or "").strip()
        self.redirect_uri = (
            os.environ.get("CMHK_FEISHU_REDIRECT_URI")
            or os.environ.get("FEISHU_REDIRECT_URI")
            or ""
        ).strip()
        self.trust_proxy_headers = os.environ.get("CMHK_AUTH_TRUST_PROXY_HEADERS", "0") == "1"
        configured_audit_origin = str(
            os.environ.get("CMHK_AUDIT_RUNTIME_ORIGIN") or "local"
        ).strip().lower()
        self.audit_runtime_origin = (
            configured_audit_origin
            if configured_audit_origin in {"local", "server"}
            else "local"
        )
        self.email_domain = (os.environ.get("CMHK_AUTH_EMAIL_DOMAIN") or "hk.chinamobile.com").strip().lower().lstrip("@")
        self.allowed_origins = {
            item.strip() for item in os.environ.get("CMHK_AUTH_ALLOWED_ORIGINS", "").split(",") if item.strip()
        }
        self.oauth_attempts: dict[str, list[float]] = {}
        self._tenant_token_cache: tuple[str, float] = ("", 0.0)
        self._custom_attr_cache: tuple[list[dict[str, Any]], float] = ([], 0.0)
        self._directory_search_cache: tuple[list[dict[str, str]], float] = ([], 0.0)
        self._directory_refresh_in_progress = False
        self._profile_refresh_in_progress = False
        self._profile_refresh_completed_at = ""
        certificate_file = os.environ.get("SSL_CERT_FILE") or "/etc/ssl/cert.pem"
        ssl_context = ssl.create_default_context(cafile=certificate_file if Path(certificate_file).is_file() else None)
        self._url_opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=ssl_context),
        )
        self._ensure_state()

    @property
    def feishu_configured(self) -> bool:
        return bool(self.app_id and self.app_secret)

    def _read(self, path: Path, fallback: Any) -> Any:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return fallback if value is None else value
        except (OSError, ValueError, TypeError):
            return fallback

    def _write(self, path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(path)

    def _ensure_state(self) -> None:
        with self.lock:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            users_exist = self.users_path.exists()
            users = self._read(self.users_path, []) if users_exist else []
            if not isinstance(users, list):
                users = []
            changed = not users_exist
            if not users_exist:
                configured = os.environ.get("CMHK_AUTH_USERS_JSON", "").strip()
                if configured:
                    try:
                        raw_users = json.loads(configured)
                    except ValueError as exc:
                        raise RuntimeError("CMHK_AUTH_USERS_JSON 不是有效 JSON") from exc
                    if not isinstance(raw_users, list):
                        raise RuntimeError("CMHK_AUTH_USERS_JSON 必须是数组")
                    for index, item in enumerate(raw_users):
                        if not isinstance(item, dict):
                            continue
                        role = str(item.get("role") or "UNCONFIGURED")
                        users.append({
                            "id": str(item.get("id") or index + 1),
                            "account": str(item.get("account") or item.get("email") or f"user-{index + 1}").lower(),
                            "email": str(item.get("email") or "").lower(),
                            "name": str(item.get("name") or item.get("email") or "用户"),
                            "department": str(item.get("department") or ""),
                            "role": role if role in ROLE_LABELS else "UNCONFIGURED",
                            "status": "disabled" if item.get("status") == "disabled" else "active",
                            "module_overrides": item.get("module_overrides") if isinstance(item.get("module_overrides"), dict) else {},
                            "credential_source": "configured",
                            "created_at": _now_iso(),
                        })
            if self.allow_dev_login:
                existing_accounts = {str(item.get("account") or "") for item in users if isinstance(item, dict)}
                dev_users = (
                    ("local-admin", "本地管理员", "战略部", "ADMIN"),
                    ("local-leader", "领导测试", "管理层", "LEADER"),
                    ("local-analyst", "情报分析测试", "战略部", "ANALYST"),
                    ("local-content", "内容运营测试", "战略部", "CONTENT"),
                    ("local-operations", "系统运维测试", "信息技术部", "OPERATIONS"),
                )
                missing_dev_users = [item for item in dev_users if item[0] not in existing_accounts]
                if missing_dev_users:
                    users.extend({
                        "id": account,
                        "account": account,
                        "email": "",
                        "name": name,
                        "department": department,
                        "role": role,
                        "status": "active",
                        "module_overrides": {},
                        "credential_source": "development_seed",
                        "created_at": _now_iso(),
                    } for account, name, department, role in missing_dev_users)
                    changed = True
            if changed:
                self._write(self.users_path, users)
            if not self.sessions_path.exists():
                self._write(self.sessions_path, [])
            if not self.audit_path.exists():
                self._write(self.audit_path, [])
            if not self.operation_audit_path.exists():
                self.operation_audit_path.touch(mode=0o600)

    def _users(self) -> list[dict[str, Any]]:
        value = self._read(self.users_path, [])
        return value if isinstance(value, list) else []

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _clean_sessions(self) -> list[dict[str, Any]]:
        now = time.time()
        sessions = [item for item in self._read(self.sessions_path, []) if float(item.get("expires_at", 0)) > now]
        self._write(self.sessions_path, sessions[-500:])
        return sessions

    def _cookies(self, handler) -> SimpleCookie:
        cookie = SimpleCookie()
        try:
            cookie.load(handler.headers.get("Cookie", ""))
        except Exception:
            pass
        return cookie

    def _secure_request(self, handler) -> bool:
        proto = handler.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip()
        return proto == "https" or os.environ.get("CMHK_AUTH_COOKIE_SECURE") == "1"

    def _cookie(self, handler, name: str, value: str, max_age: int, path: str = "/") -> str:
        parts = [f"{name}={quote(value)}", f"Path={path}", "HttpOnly", "SameSite=Lax", f"Max-Age={max_age}"]
        if self._secure_request(handler):
            parts.append("Secure")
        return "; ".join(parts)

    @staticmethod
    def _loopback_hostname(value: str) -> bool:
        try:
            hostname = urlparse(value if "://" in value else f"//{value}").hostname
        except ValueError:
            return False
        return str(hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}

    def _origin(self, handler) -> str:
        forwarded_proto = handler.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip().lower()
        proto = forwarded_proto if forwarded_proto in {"http", "https"} else "http"
        host = str(handler.headers.get("Host") or "127.0.0.1:8765").split(",", 1)[0].strip()
        if self.trust_proxy_headers:
            forwarded_host = str(handler.headers.get("X-Forwarded-Host") or "").split(",", 1)[0].strip()
            if forwarded_host:
                host = forwarded_host
        if not host or any(character in host for character in "\r\n/\\"):
            host = "127.0.0.1:8765"
        return f"{proto}://{host}"

    def _callback_uri(self, handler) -> str:
        request_callback = self._origin(handler) + "/api/auth/feishu/callback"
        if not self.redirect_uri:
            return request_callback
        # A copied workstation configuration must never send an intranet/server
        # login back to localhost. Keep the explicit loopback URI only when the
        # browser is itself accessing the service through a loopback host.
        if self._loopback_hostname(self.redirect_uri) and not self._loopback_hostname(self._origin(handler)):
            return request_callback
        return self.redirect_uri

    def _same_origin(self, handler) -> bool:
        origin = handler.headers.get("Origin", "").strip()
        if not origin:
            return True
        return origin == self._origin(handler) or origin in self.allowed_origins

    @staticmethod
    def _safe_next(value: str) -> str:
        return value if value.startswith("/") and not value.startswith("//") else "/"

    def _effective_modules(self, user: dict[str, Any]) -> dict[str, bool]:
        defaults = set(ROLE_MODULES.get(str(user.get("role")), []))
        overrides = user.get("module_overrides") if isinstance(user.get("module_overrides"), dict) else {}
        return {
            key: bool(overrides[key]) if key in overrides else key in defaults
            for key in MODULE_LABELS
        }

    def _public_user(self, user: dict[str, Any] | None) -> dict[str, Any] | None:
        if not user:
            return None
        modules = self._effective_modules(user)
        return {
            "id": str(user.get("id") or ""),
            "account": str(user.get("account") or ""),
            "email": str(user.get("email") or ""),
            "name": str(user.get("name") or "用户"),
            "department": str(user.get("department") or ""),
            "title": str(user.get("title") or ""),
            "avatarUrl": str(user.get("avatar_url") or ""),
            "role": str(user.get("role") or "UNCONFIGURED"),
            "roleLabel": ROLE_LABELS.get(str(user.get("role")), "待分配"),
            "status": "disabled" if user.get("status") == "disabled" else "active",
            "authProvider": "feishu" if user.get("credential_source") == "feishu_sso" else "local",
            "developmentAccount": user.get("credential_source") == "development_seed",
            "permissions": {"manageOrganization": modules["organization"], "modules": modules},
        }

    def current_user(self, handler) -> dict[str, Any] | None:
        morsel = self._cookies(handler).get(self.cookie_name)
        if not morsel:
            return None
        token_hash = self._hash(morsel.value)
        with self.lock:
            session = next(
                (item for item in self._read(self.sessions_path, []) if item.get("token_hash") == token_hash and float(item.get("expires_at", 0)) > time.time()),
                None,
            )
            if not session:
                return None
            user = next((item for item in self._users() if str(item.get("id")) == str(session.get("user_id"))), None)
            return self._public_user(user) if user and user.get("status") == "active" else None

    def current_actor(self, handler) -> dict[str, Any] | None:
        """Return the authenticated actor plus server-only Feishu identity fields."""
        public = self.current_user(handler)
        if not public:
            return None
        with self.lock:
            user = next((item for item in self._users() if str(item.get("id")) == str(public.get("id"))), None)
        if not user:
            return None
        return {
            **public,
            "feishuOpenId": str(user.get("feishu_open_id") or ""),
            "feishuUnionId": str(user.get("feishu_union_id") or ""),
        }

    def public_user_by_feishu_open_id(self, open_id: str) -> dict[str, Any] | None:
        open_id = str(open_id or "").strip()
        if not open_id:
            return None
        with self.lock:
            user = next((item for item in self._users() if str(item.get("feishu_open_id") or "") == open_id), None)
        return self._public_user(user)

    def public_user_by_feishu_union_id(self, union_id: str) -> dict[str, Any] | None:
        """Resolve the same person across different Feishu application Open IDs."""
        union_id = str(union_id or "").strip()
        if not union_id:
            return None
        with self.lock:
            user = next((item for item in self._users() if str(item.get("feishu_union_id") or "") == union_id), None)
        return self._public_user(user)

    def feishu_profile_by_open_id(self, open_id: str, union_id: str = "") -> dict[str, str]:
        """Resolve an event operator Open ID to the organization display profile."""
        open_id = str(open_id or "").strip()
        union_id = str(union_id or "").strip()
        if not open_id:
            return {}
        known = (
            self.public_user_by_feishu_open_id(open_id)
            or self.public_user_by_feishu_union_id(union_id)
            or {}
        )
        fallback = {
            "id": str(known.get("id") or open_id),
            "open_id": open_id,
            "name": str(known.get("name") or ""),
            "avatar_url": str(known.get("avatarUrl") or ""),
        }
        if not self.feishu_configured:
            return fallback if known else {}
        try:
            payload = self._json_request(
                "https://open.feishu.cn/open-apis/contact/v3/users/"
                + quote(open_id)
                + "?user_id_type=open_id&department_id_type=open_department_id",
                token=self._tenant_access_token(),
            )
        except Exception:
            return fallback
        user = payload.get("data", {}).get("user", {})
        if not isinstance(user, dict):
            user = {}
        avatar = user.get("avatar") if isinstance(user.get("avatar"), dict) else {}
        return {
            "id": str(known.get("id") or open_id),
            "open_id": open_id,
            "name": str(user.get("name") or known.get("name") or ""),
            "avatar_url": str(
                avatar.get("avatar_240")
                or avatar.get("avatar_72")
                or known.get("avatarUrl")
                or ""
            ),
        }

    def feishu_sheet_edit_audit_events(
        self,
        *,
        spreadsheet_token: str,
        oldest: int,
        latest: int,
    ) -> list[dict[str, Any]]:
        """Read official historical file-edit actors for one Feishu Sheet."""
        if not self.feishu_configured:
            return []
        items: list[dict[str, Any]] = []
        page_token = ""
        for _ in range(20):
            params: dict[str, Any] = {
                "user_id_type": "open_id",
                "oldest": int(oldest),
                "latest": int(latest),
                "event_name": "space_edit_doc",
                "object_type": 6,
                "object_value": str(spreadsheet_token),
                "page_size": 200,
            }
            if page_token:
                params["page_token"] = page_token
            payload = self._json_request(
                "https://open.feishu.cn/open-apis/admin/v1/audit_infos?"
                + urlencode(params),
                token=self._tenant_access_token(),
            )
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            items.extend(item for item in data.get("items", []) if isinstance(item, dict))
            if not data.get("has_more") or not data.get("page_token"):
                break
            page_token = str(data["page_token"])
        return items

    def record_operation(
        self,
        *,
        actor: dict[str, Any] | None,
        action: str,
        target: str = "",
        result: str = "success",
        source: str = "local_app",
        origin: str = "",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append a standalone, administrator-readable operation audit event."""
        actor = actor or {}
        event = {
            "id": str(uuid.uuid4()),
            "at": _now_iso(),
            "actor_id": str(actor.get("id") or ""),
            "actor_open_id": str(actor.get("feishuOpenId") or ""),
            "actor_name": str(actor.get("name") or actor.get("account") or "未知用户")[:120],
            "actor_avatar_url": str(actor.get("avatarUrl") or "")[:1000],
            "actor_role": str(actor.get("role") or ""),
            "action": str(action or "unknown")[:120],
            "target": str(target or "")[:240],
            "result": "failure" if result == "failure" else "success",
            "source": source if source in {"feishu_sheet", "feishu_card"} else "local_app",
            "origin": (
                origin
                if origin in {"local", "ngrok", "server"}
                else self.audit_runtime_origin
            ),
            "details": details if isinstance(details, dict) else {},
        }
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self.lock:
            self.operation_audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.operation_audit_path.open("a", encoding="utf-8") as handle:
                handle.write(line)
            os.chmod(self.operation_audit_path, 0o600)
        return event

    @staticmethod
    def _ngrok_hostname(value: str) -> bool:
        try:
            hostname = str(
                urlparse(value if "://" in value else f"//{value}").hostname
                or ""
            ).lower()
        except ValueError:
            return False
        return hostname.endswith((".ngrok-free.app", ".ngrok.app", ".ngrok.io"))

    def operation_origin(self, handler=None) -> str:
        """Return the audited runtime entry point without trusting public headers alone."""
        if handler is not None:
            try:
                direct_client = str(handler.client_address[0] or "")
            except (AttributeError, IndexError, TypeError):
                direct_client = ""
            forwarded_proto = str(
                handler.headers.get("X-Forwarded-Proto") or ""
            ).split(",", 1)[0].strip().lower()
            forwarded_host = str(
                handler.headers.get("X-Forwarded-Host") or ""
            ).split(",", 1)[0].strip()
            request_host = str(handler.headers.get("Host") or "").split(",", 1)[0].strip()
            if (
                direct_client in {"127.0.0.1", "::1"}
                and forwarded_proto == "https"
                and self._ngrok_hostname(forwarded_host or request_host)
                and self._ngrok_hostname(request_host)
            ):
                return "ngrok"
        return self.audit_runtime_origin

    def operation_audit(self, *, limit: int | None = 200) -> list[dict[str, Any]]:
        try:
            lines = self.operation_audit_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        events: list[dict[str, Any]] = []
        maximum = None if limit is None else max(1, min(1000, int(limit or 200)))
        for line in reversed(lines):
            try:
                item = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(item, dict):
                events.append(item)
            if maximum is not None and len(events) >= maximum:
                break
        return events

    def _create_session(self, handler, user: dict[str, Any]) -> str:
        token = secrets.token_urlsafe(32)
        lifetime = 7 * 24 * 60 * 60
        with self.lock:
            sessions = self._clean_sessions()
            sessions.append({
                "token_hash": self._hash(token),
                "user_id": str(user.get("id")),
                "created_at": time.time(),
                "expires_at": time.time() + lifetime,
                "user_agent": handler.headers.get("User-Agent", "")[:180],
            })
            self._write(self.sessions_path, sessions[-500:])
        return self._cookie(handler, self.cookie_name, token, lifetime)

    def _delete_session(self, handler) -> None:
        morsel = self._cookies(handler).get(self.cookie_name)
        if not morsel:
            return
        token_hash = self._hash(morsel.value)
        with self.lock:
            sessions = [item for item in self._read(self.sessions_path, []) if item.get("token_hash") != token_hash]
            self._write(self.sessions_path, sessions)

    def _oauth_secret(self) -> bytes:
        return (self.app_secret or os.environ.get("CMHK_AUTH_STATE_SECRET") or "local-development-state-secret").encode("utf-8")

    def _oauth_state(self, next_path: str) -> tuple[str, str]:
        state = secrets.token_urlsafe(24)
        body = _b64url(json.dumps({"state": state, "next": self._safe_next(next_path), "expires": time.time() + 600}).encode("utf-8"))
        signature = _b64url(hmac.new(self._oauth_secret(), body.encode("ascii"), hashlib.sha256).digest())
        return state, body + "." + signature

    def _verify_oauth_state(self, value: str, state: str) -> dict[str, Any] | None:
        try:
            body, signature = value.split(".", 1)
            expected = _b64url(hmac.new(self._oauth_secret(), body.encode("ascii"), hashlib.sha256).digest())
            if not hmac.compare_digest(signature, expected):
                return None
            payload = json.loads(_b64url_decode(body))
            if payload.get("state") != state or float(payload.get("expires", 0)) < time.time():
                return None
            return payload
        except (ValueError, TypeError, json.JSONDecodeError):
            return None

    def _json_request(self, url: str, *, method: str = "GET", payload: dict[str, Any] | None = None, token: str = "") -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Accept": "application/json", "Content-Type": "application/json; charset=utf-8"}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with self._url_opener.open(request, timeout=20) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, ValueError) as exc:
            raise RuntimeError("飞书认证服务暂不可用") from exc
        if not isinstance(result, dict) or int(result.get("code") or 0) != 0:
            raise RuntimeError("飞书认证返回失败")
        return result

    def _tenant_access_token(self) -> str:
        token, expires_at = self._tenant_token_cache
        if token and expires_at > time.time() + 60:
            return token
        if not self.feishu_configured:
            raise RuntimeError("飞书应用凭证未配置")
        payload = self._json_request(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            method="POST",
            payload={"app_id": self.app_id, "app_secret": self.app_secret},
        )
        token = str(payload.get("tenant_access_token") or "")
        if not token:
            raise RuntimeError("飞书应用授权未返回凭证")
        self._tenant_token_cache = (token, time.time() + max(60, int(payload.get("expire") or 7200) - 120))
        return token

    def _custom_attr_definitions(self, token: str) -> list[dict[str, Any]]:
        definitions, expires_at = self._custom_attr_cache
        if definitions and expires_at > time.time():
            return definitions
        payload = self._json_request(
            "https://open.feishu.cn/open-apis/contact/v3/custom_attrs?page_size=100",
            token=token,
        )
        items = payload.get("data", {}).get("items", [])
        definitions = [item for item in items if isinstance(item, dict)]
        self._custom_attr_cache = (definitions, time.time() + 3600)
        return definitions

    @staticmethod
    def _custom_attr_name(definition: dict[str, Any]) -> str:
        names = definition.get("i18n_name") if isinstance(definition.get("i18n_name"), list) else []
        simplified = next((item for item in names if isinstance(item, dict) and item.get("locale") == "zh_cn"), None)
        fallback = next((item for item in names if isinstance(item, dict) and item.get("locale") == "default"), None)
        return str((simplified or fallback or {}).get("value") or definition.get("name") or "").strip()

    def _simplified_position(self, directory_user: dict[str, Any], token: str) -> str:
        values = {
            str(item.get("id") or ""): str((item.get("value") or {}).get("text") or "").strip()
            for item in directory_user.get("custom_attrs") or []
            if isinstance(item, dict) and isinstance(item.get("value"), dict)
        }
        if values:
            definitions = self._custom_attr_definitions(token)
            field = next((
                item for item in definitions
                if re.search(r"(?:简中|简体).*(?:岗位|职位)|simplified.*position", self._custom_attr_name(item), re.I)
            ), None)
            value = values.get(str((field or {}).get("id") or ""), "")
            if value:
                return re.split(r"[,，、;；\n]+", value, maxsplit=1)[0].strip()[:80]
        return str(directory_user.get("job_title") or directory_user.get("title") or "").strip()[:80]

    def _feishu_profile_by_email(self, email: str) -> dict[str, str]:
        normalized = str(email or "").strip().lower()
        if not normalized.endswith("@" + self.email_domain):
            return {}
        token = self._tenant_access_token()
        payload = self._json_request(
            "https://open.feishu.cn/open-apis/contact/v3/users/batch_get_id?user_id_type=open_id",
            method="POST",
            payload={"emails": [normalized], "include_resigned": False},
            token=token,
        )
        entries = payload.get("data", {}).get("user_list", [])
        matched = next((
            item for item in entries
            if isinstance(item, dict)
            and str(item.get("email") or "").strip().lower() == normalized
            and item.get("user_id")
        ), None)
        if not matched:
            return {}
        detail = self._json_request(
            "https://open.feishu.cn/open-apis/contact/v3/users/"
            + quote(str(matched["user_id"]))
            + "?user_id_type=open_id&department_id_type=open_department_id",
            token=token,
        )
        directory_user = detail.get("data", {}).get("user", {})
        if not isinstance(directory_user, dict):
            return {}
        avatar = directory_user.get("avatar") if isinstance(directory_user.get("avatar"), dict) else {}
        return {
            "title": self._simplified_position(directory_user, token),
            "avatar_url": str(avatar.get("avatar_240") or avatar.get("avatar_72") or avatar.get("avatar_origin") or ""),
        }

    def _enrich_feishu_identity(self, identity: dict[str, Any], access_token: str) -> dict[str, Any]:
        open_id = str(identity.get("open_id") or "")
        if not open_id:
            return identity
        url = (
            "https://open.feishu.cn/open-apis/contact/v3/users/"
            + quote(open_id)
            + "?user_id_type=open_id&department_id_type=open_department_id"
        )
        try:
            payload = self._json_request(url, token=access_token)
            directory_user = payload.get("data", {}).get("user", {})
            if not isinstance(directory_user, dict):
                return identity
            departments = directory_user.get("department_ids") if isinstance(directory_user.get("department_ids"), list) else []
            token = self._tenant_access_token()
            position = self._simplified_position(directory_user, token)
            result = dict(identity)
            result.update({
                "name": directory_user.get("name") or identity.get("name"),
                "enterprise_email": directory_user.get("enterprise_email") or identity.get("enterprise_email") or "",
                "avatar_url": (directory_user.get("avatar") or {}).get("avatar_240") or identity.get("avatar_url") or "",
                "job_title": position or identity.get("job_title") or "",
                "department_ids": [str(item) for item in departments],
            })
            cached_profile = self._cached_directory_profile(str(result.get("name") or ""))
            if cached_profile:
                result["avatar_url"] = cached_profile.get("avatar_url") or result.get("avatar_url") or ""
                result["job_title"] = result.get("job_title") or cached_profile.get("title") or ""
                result["department"] = cached_profile.get("department") or result.get("department") or ""
            return result
        except Exception:
            return dict(identity)

    def _cached_directory_profile(self, name: str) -> dict[str, str]:
        """Read the refreshed Feishu directory cache without triggering a network sync."""
        db_path = self.root / "var" / "subscriptions" / "subscriptions.sqlite3"
        if not name.strip() or not db_path.is_file():
            return {}
        try:
            with sqlite3.connect(db_path, timeout=3) as connection:
                row = connection.execute(
                    """SELECT avatar_url, job_title, department_names
                       FROM subscription_directory_people
                       WHERE active=1 AND display_name=? LIMIT 1""",
                    (name.strip(),),
                ).fetchone()
        except sqlite3.Error:
            return {}
        if not row:
            return {}
        try:
            departments = json.loads(row[2] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            departments = []
        departments = [str(item).strip() for item in departments if str(item).strip()]
        return {
            "avatar_url": str(row[0] or ""),
            "title": str(row[1] or "").strip(),
            "department": " / ".join(departments),
        }

    def _refresh_missing_feishu_profiles(self) -> None:
        """Sync authoritative Feishu position and backfill other missing profile fields."""
        candidates = [item for item in self._users() if item.get("credential_source") == "feishu_sso"]
        for candidate in candidates:
            email = str(candidate.get("email") or "").strip().lower()
            try:
                enterprise_profile = self._feishu_profile_by_email(email)
            except RuntimeError:
                enterprise_profile = {}
            if enterprise_profile:
                with self.lock:
                    users = self._users()
                    target = next((item for item in users if str(item.get("id")) == str(candidate.get("id"))), None)
                    if target and (
                        target.get("title") != enterprise_profile.get("title", "")
                        or (not target.get("avatar_url") and enterprise_profile.get("avatar_url"))
                    ):
                        target["title"] = enterprise_profile.get("title", "")
                        target["avatar_url"] = target.get("avatar_url") or enterprise_profile.get("avatar_url") or ""
                        target["directory_profile_synced_at"] = _now_iso()
                        self._write(self.users_path, users)
                if candidate.get("department") and candidate.get("avatar_url"):
                    continue
            query = str(candidate.get("email") or candidate.get("name") or "").strip()
            if len(query) < 2:
                continue
            try:
                matches = self._search_directory_users(query)
            except (ValueError, RuntimeError):
                continue
            match = next((item for item in matches if str(item.get("email") or "").lower() == email), None)
            if not match:
                continue
            with self.lock:
                users = self._users()
                target = next((item for item in users if str(item.get("id")) == str(candidate.get("id"))), None)
                if not target:
                    continue
                target["department"] = match.get("department") or target.get("department") or ""
                target["title"] = match.get("title") or target.get("title") or ""
                target["avatar_url"] = match.get("avatar_url") or target.get("avatar_url") or ""
                target["directory_profile_synced_at"] = _now_iso()
                self._write(self.users_path, users)

    def _schedule_missing_feishu_profile_refresh(self) -> None:
        """Refresh Feishu profiles without holding the organization page response open."""
        with self.lock:
            if self._profile_refresh_in_progress:
                return
            self._profile_refresh_in_progress = True

        def refresh() -> None:
            try:
                self._refresh_missing_feishu_profiles()
            except Exception as exc:
                logging.warning("飞书成员资料后台刷新失败，继续使用最近本地资料：%s", exc)
            finally:
                with self.lock:
                    self._profile_refresh_in_progress = False
                    self._profile_refresh_completed_at = _now_iso()

        threading.Thread(
            target=refresh,
            name="feishu-profile-refresh",
            daemon=True,
        ).start()

    def _directory_users_from_openapi(self) -> list[dict[str, str]]:
        cached, expires_at = self._directory_search_cache
        if cached and expires_at > time.time():
            return cached
        disk_cache = self._read(self.directory_cache_path, {})
        disk_users = disk_cache.get("users") if isinstance(disk_cache, dict) else None
        disk_expires = float(disk_cache.get("expires_at") or 0) if isinstance(disk_cache, dict) else 0
        now = time.time()
        if isinstance(disk_users, list) and disk_users and disk_expires > now:
            users = [item for item in disk_users if isinstance(item, dict)]
            self._directory_search_cache = (users, disk_expires)
            return users

        stale_seconds = max(
            3600,
            int(os.environ.get("CMHK_FEISHU_DIRECTORY_STALE_SECONDS", "604800")),
        )
        if isinstance(disk_users, list) and disk_users and disk_expires + stale_seconds > now:
            users = [item for item in disk_users if isinstance(item, dict)]
            self._directory_search_cache = (users, now + 60)
            self._schedule_directory_refresh()
            return users

        return self._refresh_directory_users_from_openapi()

    def _schedule_directory_refresh(self) -> None:
        with self.lock:
            if self._directory_refresh_in_progress:
                return
            self._directory_refresh_in_progress = True

        def refresh() -> None:
            try:
                self._refresh_directory_users_from_openapi()
            except Exception as exc:
                logging.warning("飞书通讯录后台刷新失败，继续使用最近缓存：%s", exc)
            finally:
                with self.lock:
                    self._directory_refresh_in_progress = False

        threading.Thread(
            target=refresh,
            name="feishu-directory-refresh",
            daemon=True,
        ).start()

    def _refresh_directory_users_from_openapi(self) -> list[dict[str, str]]:
        token = self._tenant_access_token()
        departments: dict[str, str] = {}
        page_token = ""
        for _ in range(40):
            params: dict[str, Any] = {
                "department_id_type": "open_department_id",
                "fetch_child": "true",
                "page_size": 50,
            }
            if page_token:
                params["page_token"] = page_token
            payload = self._json_request(
                "https://open.feishu.cn/open-apis/contact/v3/departments/0/children?" + urlencode(params),
                token=token,
            )
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            for item in data.get("items") or []:
                if not isinstance(item, dict):
                    continue
                department_id = str(item.get("open_department_id") or "")
                name = str(item.get("name") or "").strip()
                status = item.get("status") if isinstance(item.get("status"), dict) else {}
                if department_id.startswith("od-") and name and not status.get("is_deleted"):
                    departments[department_id] = name
            if not data.get("has_more"):
                break
            page_token = str(data.get("page_token") or "")
            if not page_token:
                break

        people: dict[str, dict[str, Any]] = {}
        for department_id, department_name in departments.items():
            page_token = ""
            for _ in range(40):
                params = {
                    "department_id": department_id,
                    "department_id_type": "open_department_id",
                    "user_id_type": "open_id",
                    "page_size": 50,
                }
                if page_token:
                    params["page_token"] = page_token
                payload = self._json_request(
                    "https://open.feishu.cn/open-apis/contact/v3/users/find_by_department?" + urlencode(params),
                    token=token,
                )
                data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                for item in data.get("items") or []:
                    if not isinstance(item, dict) or item.get("is_activated") is False:
                        continue
                    email = str(item.get("enterprise_email") or item.get("email") or "").strip().lower()
                    name = str(item.get("name") or item.get("en_name") or "").strip()
                    open_id = str(item.get("open_id") or "")
                    if not email.endswith("@" + self.email_domain) or not name:
                        continue
                    avatar = item.get("avatar") if isinstance(item.get("avatar"), dict) else {}
                    key = open_id or email
                    record = people.setdefault(key, {
                        "name": name,
                        "email": email,
                        "department_names": set(),
                        "title": str(item.get("job_title") or item.get("title") or "").strip(),
                        "avatar_url": str(avatar.get("avatar_240") or avatar.get("avatar_72") or avatar.get("avatar_origin") or "").strip(),
                    })
                    record["department_names"].add(department_name)
                if not data.get("has_more"):
                    break
                page_token = str(data.get("page_token") or "")
                if not page_token:
                    break
        users = [{
            "name": str(item["name"]),
            "email": str(item["email"]),
            "department": " / ".join(sorted(item["department_names"])),
            "title": str(item["title"]),
            "avatar_url": str(item["avatar_url"]),
        } for item in people.values()]
        cache_seconds = max(600, int(os.environ.get("CMHK_FEISHU_DIRECTORY_CACHE_SECONDS", "21600")))
        expires_at = time.time() + cache_seconds
        self._directory_search_cache = (users, expires_at)
        self._write(self.directory_cache_path, {
            "version": 1,
            "expires_at": expires_at,
            "users": users,
        })
        return users

    def _search_directory_users(self, query: str) -> list[dict[str, str]]:
        keyword = query.strip()
        if len(keyword) < 2 or len(keyword) > 50:
            raise ValueError("请输入 2-50 个字符搜索飞书成员")
        try:
            entries = self._directory_users_from_openapi()
        except RuntimeError as exc:
            raise RuntimeError("飞书应用通讯录读取失败，请检查服务器应用凭证、权限和可用范围") from exc
        needle = keyword.casefold()
        matches = [
            item for item in entries
            if needle in f"{item.get('name', '')}\n{item.get('email', '')}".casefold()
        ]
        return sorted(
            matches,
            key=lambda item: (
                not str(item.get("name") or "").casefold().startswith(needle),
                str(item.get("name") or "").casefold(),
            ),
        )[:20]

    def _upsert_feishu_user(self, identity: dict[str, Any]) -> dict[str, Any]:
        open_id = str(identity.get("open_id") or "")
        union_id = str(identity.get("union_id") or "")
        raw_email = str(identity.get("enterprise_email") or identity.get("email") or "").lower()
        email = raw_email if raw_email.endswith("@" + self.email_domain) else ""
        with self.lock:
            users = self._users()
            user = next((item for item in users if (open_id and item.get("feishu_open_id") == open_id) or (union_id and item.get("feishu_union_id") == union_id)), None)
            if not user and email:
                user = next((item for item in users if item.get("allow_feishu_email_binding") is True and str(item.get("email") or "").lower() == email), None)
            if not user:
                first_feishu = not any(item.get("credential_source") == "feishu_sso" for item in users)
                user = {
                    "id": "fs-" + self._hash(open_id or union_id or email)[:16],
                    "account": "feishu_" + self._hash(open_id or union_id or email)[:12],
                    "email": email,
                    "name": str(identity.get("name") or identity.get("en_name") or "飞书用户")[:80],
                    "department": "",
                    "role": "ADMIN" if self.bootstrap_first_feishu_admin and first_feishu else "UNCONFIGURED",
                    "status": "active",
                    "module_overrides": {},
                    "credential_source": "feishu_sso",
                    "created_at": _now_iso(),
                }
                users.append(user)
            if user.get("status") != "active":
                raise RuntimeError("该账号已停用")
            user["feishu_open_id"] = open_id
            user["feishu_union_id"] = union_id
            user["feishu_user_id"] = str(identity.get("user_id") or "")
            user["feishu_tenant_key"] = str(identity.get("tenant_key") or "")
            user["name"] = str(identity.get("name") or identity.get("en_name") or user.get("name") or "飞书用户")[:80]
            user["email"] = email or str(user.get("email") or "")
            user["department"] = str(identity.get("department") or user.get("department") or "")[:160]
            user["avatar_url"] = str(identity.get("avatar_url") or user.get("avatar_url") or "")
            user["title"] = str(identity.get("job_title") or identity.get("title") or user.get("title") or "")[:80]
            user["last_login_at"] = _now_iso()
            self._write(self.users_path, users)
            return user

    def _send_json(self, handler, status: int, payload: dict[str, Any], headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.send_header("Referrer-Policy", "no-referrer")
        for key, value in (headers or {}).items():
            handler.send_header(key, value)
        handler.end_headers()
        handler.wfile.write(body)

    def _redirect(self, handler, location: str, cookies: list[str] | None = None) -> None:
        handler.send_response(302)
        handler.send_header("Location", location)
        handler.send_header("Cache-Control", "no-store")
        for cookie in cookies or []:
            handler.send_header("Set-Cookie", cookie)
        handler.end_headers()

    def _read_body(self, handler) -> dict[str, Any]:
        try:
            length = min(int(handler.headers.get("Content-Length", "0") or 0), 1024 * 1024)
            value = json.loads(handler.rfile.read(length).decode("utf-8")) if length else {}
            return value if isinstance(value, dict) else {}
        except (ValueError, UnicodeDecodeError):
            raise ValueError("请求格式不正确")

    @staticmethod
    def _loopback(handler) -> bool:
        host = str(handler.headers.get("Host") or "").split(":", 1)[0].lower()
        return (
            str(handler.client_address[0]) in {"127.0.0.1", "::1"}
            and host in {"127.0.0.1", "localhost", "[::1]"}
            and not handler.headers.get("X-Forwarded-For")
        )

    def _role_modules(self) -> dict[str, dict[str, bool]]:
        return {role: {module: module in set(modules) for module in MODULE_LABELS} for role, modules in ROLE_MODULES.items()}

    def _allow_oauth_start(self, handler) -> bool:
        now = time.time()
        client = str(handler.client_address[0])
        with self.lock:
            recent = [stamp for stamp in self.oauth_attempts.get(client, []) if stamp > now - 3600]
            if len(recent) >= 20:
                self.oauth_attempts[client] = recent
                return False
            recent.append(now)
            self.oauth_attempts[client] = recent
            return True

    def handle(self, handler, method: str, parsed) -> bool:
        path = parsed.path
        if not path.startswith("/api/auth/"):
            return False
        if method == "POST" and not self._same_origin(handler):
            self._send_json(handler, 403, {"ok": False, "message": "请求来源不受信任"})
            return True
        if path == "/api/auth/config" and method == "GET":
            dev_accounts = []
            if self.allow_dev_login and self._loopback(handler):
                dev_accounts = [self._public_user(item) for item in self._users() if item.get("status") == "active"]
            self._send_json(handler, 200, {
                "ok": True,
                "requireLogin": self.require_login,
                "devMode": bool(dev_accounts),
                "feishu": {"configured": self.feishu_configured, "callbackUri": self._callback_uri(handler)},
                "devAccounts": dev_accounts,
            })
            return True
        if path == "/api/auth/me" and method == "GET":
            user = self.current_user(handler)
            self._send_json(handler, 200, {"ok": True, "authenticated": bool(user), "user": user})
            return True
        if path == "/api/auth/feishu/start" and method == "GET":
            if not self._allow_oauth_start(handler):
                self._send_json(handler, 429, {"ok": False, "message": "飞书登录请求过于频繁，请稍后再试"})
                return True
            if not self.feishu_configured:
                self._send_json(handler, 503, {"ok": False, "message": "飞书登录尚未完成服务器配置"})
                return True
            if not self.tenant_key:
                self._send_json(handler, 503, {"ok": False, "message": "飞书租户校验尚未配置"})
                return True
            query = parse_qs(parsed.query)
            state, cookie_value = self._oauth_state(str((query.get("next") or ["/"])[0]))
            authorization_url = "https://accounts.feishu.cn/open-apis/authen/v1/authorize?" + urlencode({
                "app_id": self.app_id,
                "redirect_uri": self._callback_uri(handler),
                "scope": "auth:user.id:read",
                "state": state,
            })
            self._redirect(handler, authorization_url, [self._cookie(handler, self.oauth_cookie_name, cookie_value, 600, "/api/auth/feishu")])
            return True
        if path == "/api/auth/feishu/callback" and method == "GET":
            query = parse_qs(parsed.query)
            if query.get("error"):
                self._redirect(handler, "/static/login.html?feishu_error=authorization_cancelled")
                return True
            oauth_cookie = self._cookies(handler).get(self.oauth_cookie_name)
            verified = self._verify_oauth_state(oauth_cookie.value if oauth_cookie else "", str((query.get("state") or [""])[0]))
            code = str((query.get("code") or [""])[0])
            if not verified or not code:
                self._redirect(handler, "/static/login.html?feishu_error=invalid_state")
                return True
            try:
                token_payload = self._json_request(
                    "https://open.feishu.cn/open-apis/authen/v2/oauth/token",
                    method="POST",
                    payload={"grant_type": "authorization_code", "client_id": self.app_id, "client_secret": self.app_secret, "code": code, "redirect_uri": self._callback_uri(handler)},
                )
                access_token = str(token_payload.get("access_token") or "")
                identity_payload = self._json_request("https://open.feishu.cn/open-apis/authen/v1/user_info", token=access_token)
                identity = identity_payload.get("data") if isinstance(identity_payload.get("data"), dict) else {}
                if not identity.get("open_id") or not identity.get("tenant_key"):
                    raise RuntimeError("飞书用户身份不完整")
                if self.tenant_key and str(identity.get("tenant_key")) != self.tenant_key:
                    self._redirect(handler, "/static/login.html?feishu_error=wrong_tenant")
                    return True
                identity = self._enrich_feishu_identity(identity, access_token)
                user = self._upsert_feishu_user(identity)
                self._redirect(handler, self._safe_next(str(verified.get("next") or "/")), [
                    self._create_session(handler, user),
                    self._cookie(handler, self.oauth_cookie_name, "", 0, "/api/auth/feishu"),
                ])
            except Exception:
                self._redirect(handler, "/static/login.html?feishu_error=exchange_failed")
            return True
        if path == "/api/auth/dev-login" and method == "POST":
            if not self.allow_dev_login or not self._loopback(handler):
                self._send_json(handler, 404, {"ok": False, "message": "本地测试登录不可用"})
                return True
            try:
                payload = self._read_body(handler)
            except ValueError as exc:
                self._send_json(handler, 400, {"ok": False, "message": str(exc)})
                return True
            account = str(payload.get("account") or "").lower()
            user = next((item for item in self._users() if str(item.get("account") or "").lower() == account and item.get("status") == "active"), None)
            if not user:
                self._send_json(handler, 401, {"ok": False, "message": "本地测试账号不存在"})
                return True
            self._send_json(handler, 200, {"ok": True, "user": self._public_user(user)}, {"Set-Cookie": self._create_session(handler, user)})
            return True
        if path == "/api/auth/logout" and method == "POST":
            self._delete_session(handler)
            self._send_json(handler, 200, {"ok": True}, {"Set-Cookie": self._cookie(handler, self.cookie_name, "", 0)})
            return True
        if path == "/api/auth/admin/users" and method == "GET":
            admin = self.current_user(handler)
            if not admin:
                self._send_json(handler, 401, {"ok": False, "message": "请先登录"})
                return True
            if not admin["permissions"]["manageOrganization"]:
                self._send_json(handler, 403, {"ok": False, "message": "当前账号无权管理组织"})
                return True
            query = parse_qs(parsed.query)
            refresh_profiles = str((query.get("profile_refresh") or ["background"])[0]).strip().lower() != "skip"
            if refresh_profiles:
                self._schedule_missing_feishu_profile_refresh()
            users = []
            for item in self._users():
                public = self._public_user(item) or {}
                public["current"] = public.get("id") == admin.get("id")
                public["modules"] = public.get("permissions", {}).get("modules", {})
                users.append(public)
            departments = sorted({str(item.get("department") or "") for item in users if item.get("department")})
            self._send_json(handler, 200, {
                "ok": True,
                "users": users,
                "departments": departments,
                "roles": ROLE_LABELS,
                "modules": MODULE_LABELS,
                "roleModules": self._role_modules(),
                "profileRefresh": {
                    "running": self._profile_refresh_in_progress,
                    "completedAt": self._profile_refresh_completed_at,
                },
            })
            return True
        if path == "/api/auth/admin/audit" and method == "GET":
            admin = self.current_user(handler)
            if not admin:
                self._send_json(handler, 401, {"ok": False, "message": "请先登录"})
                return True
            if not admin["permissions"]["manageOrganization"]:
                self._send_json(handler, 403, {"ok": False, "message": "当前账号无权查看操作审计"})
                return True
            query = parse_qs(parsed.query)
            raw_limit = str((query.get("limit") or ["200"])[0]).strip().lower()
            if raw_limit == "all":
                limit = None
            else:
                try:
                    limit = max(1, min(1000, int(raw_limit)))
                except (TypeError, ValueError):
                    limit = 200
            self._send_json(handler, 200, {"ok": True, "events": self.operation_audit(limit=limit)})
            return True
        if path == "/api/auth/admin/directory/search" and method == "GET":
            admin = self.current_user(handler)
            if not admin or not admin["permissions"]["manageOrganization"]:
                self._send_json(handler, 403 if admin else 401, {"ok": False, "message": "当前账号无权搜索飞书组织"})
                return True
            query = str((parse_qs(parsed.query).get("q") or [""])[0])
            try:
                matches = self._search_directory_users(query)
                existing = {str(item.get("email") or "").lower() for item in self._users()}
                self._send_json(handler, 200, {"ok": True, "users": [{**item, "added": item["email"] in existing} for item in matches], "departments": [], "chats": [], "warnings": []})
            except (ValueError, RuntimeError) as exc:
                self._send_json(handler, 502 if isinstance(exc, RuntimeError) else 400, {"ok": False, "message": str(exc)})
            return True
        if path == "/api/auth/admin/users/import" and method == "POST":
            admin = self.current_actor(handler)
            if not admin or not admin["permissions"]["manageOrganization"]:
                self._send_json(handler, 403 if admin else 401, {"ok": False, "message": "当前账号无权添加成员"})
                return True
            try:
                payload = self._read_body(handler)
                email = str(payload.get("email") or "").strip().lower()
                if not email.endswith("@" + self.email_domain):
                    raise ValueError("只能添加 CMHK 企业邮箱成员")
                matches = self._search_directory_users(email)
                match = next((item for item in matches if item["email"] == email), None)
                if not match:
                    raise ValueError("飞书通讯录中未找到该企业邮箱")
                with self.lock:
                    users = self._users()
                    if any(str(item.get("email") or "").lower() == email for item in users):
                        self._send_json(handler, 409, {"ok": False, "message": "该成员已经在权限名单中"})
                        return True
                    user = {
                        "id": "pending-" + self._hash(email)[:16],
                        "account": "feishu_pending_" + self._hash(email)[:12],
                        "email": email,
                        "name": match["name"],
                        "department": match["department"],
                        "title": match.get("title", ""),
                        "avatar_url": match.get("avatar_url", ""),
                        "role": "UNCONFIGURED",
                        "status": "active",
                        "module_overrides": {},
                        "credential_source": "feishu_sso",
                        "allow_feishu_email_binding": True,
                        "provisioned_by_admin": True,
                        "created_at": _now_iso(),
                    }
                    users.append(user)
                    self._write(self.users_path, users)
                self.record_operation(
                    actor=admin,
                    action="organization.user_import",
                    target=str(user.get("id") or email),
                    origin=self.operation_origin(handler),
                    details={"email": email, "name": str(user.get("name") or "")},
                )
                self._send_json(handler, 201, {"ok": True, "user": self._public_user(user)})
            except ValueError as exc:
                self._send_json(handler, 400, {"ok": False, "message": str(exc)})
            except RuntimeError as exc:
                self._send_json(handler, 502, {"ok": False, "message": str(exc)})
            return True
        user_path = path.removeprefix("/api/auth/admin/users/") if path.startswith("/api/auth/admin/users/") else ""
        if user_path and method == "DELETE":
            admin = self.current_actor(handler)
            if not admin:
                self._send_json(handler, 401, {"ok": False, "message": "请先登录"})
                return True
            if not admin["permissions"]["manageOrganization"]:
                self._send_json(handler, 403, {"ok": False, "message": "当前账号无权删除成员"})
                return True
            with self.lock:
                users = self._users()
                target = next((item for item in users if str(item.get("id")) == user_path), None)
                if not target:
                    self._send_json(handler, 404, {"ok": False, "message": "成员不存在"})
                    return True
                if str(target.get("id")) == str(admin.get("id")):
                    self._send_json(handler, 409, {"ok": False, "message": "不能删除当前登录管理员"})
                    return True
                enterprise_admins = [
                    item for item in users
                    if item.get("credential_source") == "feishu_sso"
                    and item.get("status") == "active"
                    and self._effective_modules(item).get("organization")
                ]
                if target in enterprise_admins and len(enterprise_admins) == 1:
                    self._send_json(handler, 409, {"ok": False, "message": "必须保留至少一名飞书企业管理员"})
                    return True
                removed = {
                    "id": str(target.get("id") or ""),
                    "name": str(target.get("name") or ""),
                    "email": str(target.get("email") or ""),
                    "role": str(target.get("role") or ""),
                }
                self._write(self.users_path, [item for item in users if item is not target])
                sessions = [item for item in self._read(self.sessions_path, []) if str(item.get("user_id")) != str(target.get("id"))]
                self._write(self.sessions_path, sessions)
                audit = self._read(self.audit_path, [])
                audit.append({"at": _now_iso(), "by": admin.get("id"), "target": target.get("id"), "before": removed, "after": {"deleted": True}})
                self._write(self.audit_path, audit[-1000:])
                self.record_operation(
                    actor=admin,
                    action="organization.user_delete",
                    target=str(target.get("id") or ""),
                    origin=self.operation_origin(handler),
                    details=removed,
                )
            self._send_json(handler, 200, {"ok": True, "deleted": removed})
            return True
        if user_path and method == "POST":
            admin = self.current_actor(handler)
            if not admin:
                self._send_json(handler, 401, {"ok": False, "message": "请先登录"})
                return True
            if not admin["permissions"]["manageOrganization"]:
                self._send_json(handler, 403, {"ok": False, "message": "当前账号无权管理组织"})
                return True
            try:
                payload = self._read_body(handler)
            except ValueError as exc:
                self._send_json(handler, 400, {"ok": False, "message": str(exc)})
                return True
            with self.lock:
                users = self._users()
                target = next((item for item in users if str(item.get("id")) == user_path), None)
                if not target:
                    self._send_json(handler, 404, {"ok": False, "message": "成员不存在"})
                    return True
                role = str(payload.get("role") or target.get("role") or "UNCONFIGURED")
                if role not in ROLE_LABELS:
                    self._send_json(handler, 400, {"ok": False, "message": "角色不存在"})
                    return True
                status = "disabled" if payload.get("status") == "disabled" else "active"
                requested = payload.get("modules") if isinstance(payload.get("modules"), dict) else self._effective_modules(target)
                if any(not isinstance(value, bool) for key, value in requested.items() if key in MODULE_LABELS):
                    self._send_json(handler, 400, {"ok": False, "message": "页签权限必须是布尔值"})
                    return True
                defaults = set(ROLE_MODULES[role])
                overrides = {key: bool(requested[key]) for key in MODULE_LABELS if key in requested and bool(requested[key]) != (key in defaults)}
                effective_after = {key: bool(requested[key]) if key in requested else key in defaults for key in MODULE_LABELS}
                if str(target.get("id")) == str(admin.get("id")) and (status == "disabled" or not effective_after["organization"]):
                    self._send_json(handler, 409, {"ok": False, "message": "不能停用当前管理员或移除自己的组织管理权限"})
                    return True
                active_admins = [item for item in users if item.get("status") == "active" and self._effective_modules(item).get("organization")]
                if target in active_admins and len(active_admins) == 1 and (status == "disabled" or not effective_after["organization"]):
                    self._send_json(handler, 409, {"ok": False, "message": "组织中必须保留至少一名管理员"})
                    return True
                before = {"role": target.get("role"), "status": target.get("status"), "title": target.get("title", ""), "module_overrides": target.get("module_overrides", {})}
                target["role"] = role
                target["status"] = status
                target["module_overrides"] = overrides
                target["updated_at"] = _now_iso()
                target["updated_by"] = admin.get("id")
                self._write(self.users_path, users)
                audit = self._read(self.audit_path, [])
                after = {"role": role, "status": status, "title": target.get("title", ""), "module_overrides": overrides}
                audit.append({"at": target["updated_at"], "by": admin.get("id"), "target": target.get("id"), "before": before, "after": after})
                self._write(self.audit_path, audit[-1000:])
                self.record_operation(
                    actor=admin,
                    action="organization.user_update",
                    target=str(target.get("id") or ""),
                    origin=self.operation_origin(handler),
                    details={"before": before, "after": after},
                )
            self._send_json(handler, 200, {"ok": True, "user": self._public_user(target)})
            return True
        self._send_json(handler, 404, {"ok": False, "message": "认证接口不存在"})
        return True

    def module_for_api(self, path: str) -> str:
        for prefix, module in _API_MODULE_PREFIXES:
            if path.startswith(prefix):
                return module or ""
        return ""

    def authorize_api(self, handler, path: str, method: str = "GET") -> bool:
        if path == "/api/health" and method == "GET" and self._loopback(handler):
            return True
        if not self.require_login:
            return True
        user = self.current_user(handler)
        if not user:
            self._send_json(handler, 401, {"ok": False, "message": "登录状态已失效，请重新登录"})
            return False
        if user.get("role") == "LEADER" and method != "GET":
            self._send_json(handler, 403, {"ok": False, "message": "领导账号仅可查看战略总览"})
            return False
        if method == "GET" and path.startswith(("/api/crawl-runs", "/api/crawl-run-log")):
            modules = user["permissions"]["modules"]
            if modules.get("news") or modules.get("log"):
                return True
        for prefix, accepted_modules in _API_ANY_MODULE_PREFIXES:
            if not path.startswith(prefix):
                continue
            modules = user["permissions"]["modules"]
            if any(modules.get(module, False) for module in accepted_modules):
                return True
            labels = "或".join(MODULE_LABELS[module] for module in accepted_modules)
            self._send_json(handler, 403, {"ok": False, "message": f"当前账号无权使用{labels}"})
            return False
        module = self.module_for_api(path)
        if not module:
            self._send_json(handler, 403, {"ok": False, "message": "当前接口尚未配置访问权限"})
            return False
        if module and not user["permissions"]["modules"].get(module, False):
            self._send_json(handler, 403, {"ok": False, "message": f"当前账号无权使用{MODULE_LABELS[module]}"})
            return False
        return True

    def authorize_resource(self, handler, path: str) -> bool:
        public_static = {
            "/static/login.html",
            "/static/login.css",
            "/static/login.js",
            "/static/assets/china-mobile-blue-logo.png",
            "/static/assets/cmhk-login-background.jpg",
            "/static/assets/login-hong-kong-network-bg-v1.webp",
        }
        if path in public_static or not self.require_login:
            return True
        user = self.current_user(handler)
        if not user:
            self._redirect(handler, "/static/login.html?next=" + quote(path or "/"))
            return False
        modules = user["permissions"]["modules"]
        required: tuple[str, ...] = ()
        if path.endswith("competitor-workbench-data.json") or "company-data" in path:
            required = ("competitor",)
        elif path.endswith("news-run-items.json"):
            required = ("news",)
        elif "/report-previews/" in path:
            required = ("weekly", "performance")
        elif "executive-dashboard" in path:
            required = ("monitoring",)
        elif "subscription-admin" in path:
            required = ("subscriptions",)
        elif path.startswith(("/outputs/", "/audio/")):
            required = ("weekly", "performance")
        elif path.startswith("/generated-charts/"):
            required = ("competitor", "weekly", "performance", "ai")
        elif path.startswith(("/references/", "/references-raw/")):
            required = ("ai",)
        if required and not any(modules.get(module, False) for module in required):
            self._send_json(handler, 403, {"ok": False, "message": "当前账号无权读取该资源"})
            return False
        return True

    def authorize_page(self, handler, path: str) -> bool:
        if not self.require_login or path in {"/static/login.html", "/login.html"}:
            return True
        user = self.current_user(handler)
        if not user:
            self._redirect(handler, "/static/login.html?next=" + quote(path or "/"))
            return False
        page_module = "monitoring" if "executive-dashboard" in path else "competitor" if "company-data" in path else "dashboard"
        if not user["permissions"]["modules"].get(page_module, False):
            self._send_json(handler, 403, {"ok": False, "message": f"当前账号无权查看{MODULE_LABELS[page_module]}"})
            return False
        return True

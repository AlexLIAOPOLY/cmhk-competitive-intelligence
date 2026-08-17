"""CMHK AI Token Hub: a small, server-side demo-to-pilot product layer.

The module deliberately keeps provider credentials on the server and stores
only usage metadata. It is isolated from the existing crawl and Feishu write
paths so the product can be tested without changing production operations.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from ai_config import INTERNAL_AI_BASE_URL, is_internal_ai_base_url, load_ai_config
from ai_rate_limit import wait_for_internal_ai_slot

ROOT = Path(__file__).resolve().parent
TOKEN_HUB_DIR = ROOT / "var" / "token_hub"
DB_PATH = TOKEN_HUB_DIR / "token_hub.sqlite3"
DB_LOCK = threading.RLock()

PLANS = (
    {"id": "starter", "name": "个人试用", "price_hkd": 0, "credits": 10000, "description": "体验繁中、英文和普通话 AI 助手"},
    {"id": "team", "name": "团队协作", "price_hkd": 99, "credits": 1000000, "description": "适合小团队客服、翻译和文件处理"},
    {"id": "business", "name": "企业治理", "price_hkd": 399, "credits": 5000000, "description": "统一额度、预算和用量审计"},
)

MODEL_TASKS = (
    {
        "id": "customer_service",
        "name": "客服與銷售",
        "description": "繁中客服、銷售話術、客戶回覆與需求澄清",
        "system_prompt": "優先使用繁體中文，保持專業、簡潔、可執行；涉及價格、付款或合約時先標示需要人工確認。",
    },
    {
        "id": "translation",
        "name": "翻譯與改寫",
        "description": "中英互譯、香港用語、本地化和語氣調整",
        "system_prompt": "保留原意和專有名詞，按香港商務語境使用繁體中文；如原文有歧義，先指出歧義再給出版本。",
    },
    {
        "id": "lead_research",
        "name": "線索研判",
        "description": "把公開線索整理成行業、痛點、下一步和風險",
        "system_prompt": "只根據提供的資料做判斷，明確區分事實、推測和待核實項；輸出適合銷售跟進的下一步。",
    },
    {
        "id": "long_context",
        "name": "長文與知識庫",
        "description": "長文件摘要、條款抽取、內部知識問答",
        "system_prompt": "先給結論，再列出依據和不確定性；不能從未提供的文件內容臆造答案。",
    },
    {
        "id": "code_automation",
        "name": "程式與自動化",
        "description": "SQL、Python、接口調試和運營自動化",
        "system_prompt": "先說明假設和風險，再給可執行的程式或步驟；涉及生產資料時優先使用乾跑和最小權限。",
    },
)

TASK_DEFAULT_MODEL_IDS = {
    "customer_service": "Qwen3-30B-A3B-Instruct-2507",
    "translation": "deepseek-v4",
    "lead_research": "MiniMax-M2.1",
    "long_context": "DeepSeek-V4-Pro",
    "code_automation": "Kimi-Code",
}

PUBLIC_API_PRICES = (
    {
        "provider": "Google",
        "model": "Gemini 2.5 Flash-Lite",
        "input_usd_per_million": 0.10,
        "output_usd_per_million": 0.40,
        "cache_input_usd_per_million": 0.01,
        "note": "Standard；Batch 輸入 $0.05、輸出 $0.20；Grounding 另有搜尋費用與配額。",
        "source_url": "https://ai.google.dev/gemini-api/docs/pricing",
        "verified_at": "2026-08-15",
    },
    {
        "provider": "DeepSeek",
        "model": "deepseek-v4-flash",
        "input_usd_per_million": 0.22,
        "output_usd_per_million": 0.66,
        "cache_input_usd_per_million": 0.007,
        "note": "官方 off-peak；peak cache hit $0.014、cache miss $0.44、輸出 $1.32，按供應商時段計費。",
        "source_url": "https://api-docs.deepseek.com/quick_start/pricing",
        "verified_at": "2026-08-15",
    },
    {
        "provider": "OpenAI",
        "model": "GPT-5 mini",
        "input_usd_per_million": 0.25,
        "output_usd_per_million": 2.00,
        "cache_input_usd_per_million": None,
        "note": "官方 GPT-5 開發者頁列出的標準輸入/輸出價；快取、服務等級和工具可能另有規則。",
        "source_url": "https://openai.com/gpt-5/",
        "verified_at": "2026-08-15",
    },
    {
        "provider": "Anthropic",
        "model": "Claude Haiku 4.5",
        "input_usd_per_million": 1.00,
        "output_usd_per_million": 5.00,
        "cache_input_usd_per_million": 0.10,
        "note": "官方 Claude 價格頁；提示快取、Web search、Code execution 和服務等級另計。",
        "source_url": "https://claude.com/pricing",
        "verified_at": "2026-08-15",
    },
)

EXTERNAL_PROVIDER_CATALOG = (
    {
        "id": "deepseek_public",
        "provider": "DeepSeek 公网 API",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "allowed_hosts": ("api.deepseek.com",),
        "input_usd_per_million": 0.44,
        "output_usd_per_million": 1.32,
        "off_peak_input_usd_per_million": 0.22,
        "off_peak_output_usd_per_million": 0.66,
        "source_url": "https://api-docs.deepseek.com/quick_start/pricing",
        "note": "预算与审计按官方 peak 价格封顶；off-peak 参考为 $0.22/$0.66。必须由平台团队配置服务器端密钥和数据外发审批。",
    },
)

TARIFF_BANDS = (
    {
        "id": "valley",
        "name": "谷时",
        "windows": "00:00–08:00",
        "windows_hkt": ((0, 8),),
        "note": "运营规划时段，不等同于已批准的内部电价。",
    },
    {
        "id": "shoulder",
        "name": "平时",
        "windows": "08:00–18:00、22:00–24:00",
        "windows_hkt": ((8, 18), (22, 24)),
        "note": "运营规划时段，不等同于已批准的内部电价。",
    },
    {
        "id": "peak",
        "name": "峰时",
        "windows": "18:00–22:00",
        "windows_hkt": ((18, 22),),
        "note": "运营规划时段，不等同于已批准的内部电价。",
    },
)

DEFAULT_OVERFLOW_POLICY = {
    "enabled": False,
    "provider_id": "deepseek_public",
    "trigger_queue_depth": 20,
    "trigger_latency_ms": 8000,
    "max_monthly_hkd": 0,
    "max_request_tokens": 0,
    "require_sanitized": True,
}

USD_HKD_ASSUMPTION = 7.8
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
NON_CHAT_MODEL_MARKERS = ("embedding", "reranker", "ocr", "asr", "tts", "voxcpm", "bge")
MODEL_DISCOVERY_CACHE: dict[str, Any] = {"expires_at": 0.0, "models": []}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _configured_model_ids() -> list[str]:
    """Return model ids explicitly exposed by the internal gateway configuration.

    The comma-separated environment variable is intentionally optional. It lets
    operations register additional model ids without putting provider keys or
    external endpoints into the application. Every id still resolves to the
    single server-side internal gateway in ``ai_config.py``.
    """
    config = load_ai_config(include_key=False)
    candidates = [str(config.get("model") or "deepseek-v4").strip()]
    candidates.extend(
        item.strip()
        for item in str(os.environ.get("CMHK_INTERNAL_AI_MODELS") or "").split(",")
        if item.strip()
    )
    model_ids: list[str] = []
    for model_id in candidates:
        if model_id and MODEL_ID_RE.fullmatch(model_id) and model_id not in model_ids:
            model_ids.append(model_id)
    return model_ids or ["deepseek-v4"]


def _discover_internal_model_ids() -> list[str]:
    """Discover chat-capable model ids from the internal OpenAI-compatible gateway.

    Discovery is server-side, cached briefly, and fails closed to the configured
    model. Models intended for embeddings, OCR, speech or reranking are not
    offered as chat routes because a text chat call would be misleading.
    """
    now = time.monotonic()
    cached = MODEL_DISCOVERY_CACHE.get("models") or []
    if float(MODEL_DISCOVERY_CACHE.get("expires_at") or 0) > now and cached:
        return list(cached)
    config = load_ai_config(include_key=True)
    api_key = str(config.get("api_key") or "").strip()
    base_url = str(config.get("base_url") or INTERNAL_AI_BASE_URL).rstrip("/")
    model_ids = _configured_model_ids()
    if api_key and is_internal_ai_base_url(base_url):
        request = urllib.request.Request(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
            for item in payload.get("data") or []:
                model_id = str((item or {}).get("id") or "").strip()
                if not model_id or not MODEL_ID_RE.fullmatch(model_id):
                    continue
                if any(marker in model_id.lower() for marker in NON_CHAT_MODEL_MARKERS):
                    continue
                if model_id not in model_ids:
                    model_ids.append(model_id)
        except Exception:
            pass
    MODEL_DISCOVERY_CACHE.update({"expires_at": now + 300, "models": list(model_ids)})
    return model_ids


def _sync_discovered_model_catalog() -> list[str]:
    discovered = _discover_internal_model_ids()
    if not discovered:
        return []
    with DB_LOCK, db_connection() as conn:
        now = _now()
        for model_id in discovered:
            conn.execute(
                """
                INSERT OR IGNORE INTO model_catalog(
                    model_id, display_name, provider, enabled, note, created_at, updated_at
                ) VALUES (?, ?, 'internal', 1, ?, ?, ?)
                """,
                (
                    model_id,
                    f"公司内网 · {model_id}",
                    "由内网模型目录发现；切换前仍需完成任务级质量、延迟和容量压测。",
                    now,
                    now,
                ),
            )
            conn.execute("UPDATE model_catalog SET enabled = 1, updated_at = ? WHERE model_id = ?", (now, model_id))
        for row in conn.execute("SELECT model_id FROM model_catalog").fetchall():
            existing_id = str(row["model_id"] or "")
            if any(marker in existing_id.lower() for marker in NON_CHAT_MODEL_MARKERS):
                conn.execute("UPDATE model_catalog SET enabled = 0, updated_at = ? WHERE model_id = ?", (now, existing_id))
    return discovered


def _apply_task_defaults(discovered: list[str]) -> None:
    if not discovered:
        return
    discovered_set = set(discovered)
    with DB_LOCK, db_connection() as conn:
        now = _now()
        for task_id, preferred_model in TASK_DEFAULT_MODEL_IDS.items():
            if preferred_model not in discovered_set:
                continue
            row = conn.execute("SELECT model_id, source FROM model_routes WHERE task_id = ?", (task_id,)).fetchone()
            if not row or str(row["source"] or "system") != "system":
                continue
            if str(row["model_id"]) == preferred_model:
                continue
            conn.execute(
                "UPDATE model_routes SET model_id = ?, source = 'system', updated_at = ? WHERE task_id = ?",
                (preferred_model, now, task_id),
            )


def _task(task_id: str) -> dict[str, str]:
    task = next((item for item in MODEL_TASKS if item["id"] == task_id), None)
    if not task:
        raise ValueError("任务类型不存在")
    return task


def _optional_cost(value: Any, field_name: str) -> float | None:
    if value in {None, "", "null"}:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name}必须是非负数字") from exc
    if parsed < 0 or parsed > 100000:
        raise ValueError(f"{field_name}必须在 0 至 100000 之间")
    return round(parsed, 6)


def _current_tariff_band(now_hkt: datetime | None = None) -> dict[str, Any]:
    current = now_hkt or datetime.now(ZoneInfo("Asia/Hong_Kong"))
    hour = current.hour + current.minute / 60
    for band in TARIFF_BANDS:
        if any(start <= hour < end for start, end in band["windows_hkt"]):
            return band
    return TARIFF_BANDS[0]


def _external_provider_config(provider_id: str | None = None) -> dict[str, Any]:
    configured_provider_id = str(os.environ.get("CMHK_EXTERNAL_AI_PROVIDER") or "").strip()
    provider_id = str(provider_id or configured_provider_id).strip()
    provider = next((item for item in EXTERNAL_PROVIDER_CATALOG if item["id"] == provider_id), None)
    api_key = str(os.environ.get("CMHK_EXTERNAL_AI_API_KEY") or "").strip()
    if not provider:
        return {
            "configured": False,
            "provider_id": provider_id or None,
            "adapter_id": None,
            "status": "未配置",
            "reason": "尚未配置获批的外部供应商。",
        }
    base_url = str(os.environ.get("CMHK_EXTERNAL_AI_BASE_URL") or provider["base_url"]).strip().rstrip("/")
    parsed = urlparse(base_url)
    allowed = parsed.scheme == "https" and parsed.hostname in provider["allowed_hosts"] and not parsed.query and not parsed.fragment
    configured = bool(api_key and allowed and configured_provider_id == provider["id"])
    reason = ""
    if not configured:
        if configured_provider_id and configured_provider_id != provider["id"]:
            reason = "服务器端配置的供应商与当前策略不一致。"
        elif not api_key:
            reason = "需要服务器端 API Key；密钥不会写入数据库或浏览器。"
        elif not allowed:
            reason = "Base URL 必须是 HTTPS 且匹配获批官方域名。"
    return {
        "configured": configured,
        "provider_id": provider["id"],
        "adapter_id": provider["id"],
        "provider": provider["provider"],
        "model": str(os.environ.get("CMHK_EXTERNAL_AI_MODEL") or provider["model"]).strip(),
        "base_url_host": parsed.hostname or "",
        "status": "已配置，可在审批后启用" if configured else ("未配置" if not configured_provider_id else "配置不完整"),
        "reason": reason,
        "source_url": provider["source_url"],
        "input_usd_per_million": provider["input_usd_per_million"],
        "output_usd_per_million": provider["output_usd_per_million"],
        "off_peak_input_usd_per_million": provider.get("off_peak_input_usd_per_million"),
        "off_peak_output_usd_per_million": provider.get("off_peak_output_usd_per_million"),
        "pricing_basis": "官方 peak 价格封顶",
    }


def get_overflow_policy() -> dict[str, Any]:
    init_db()
    with DB_LOCK, db_connection() as conn:
        row = conn.execute("SELECT * FROM overflow_policy WHERE id = 1").fetchone()
    policy = dict(row) if row else dict(DEFAULT_OVERFLOW_POLICY)
    policy["enabled"] = bool(policy.get("enabled"))
    policy["require_sanitized"] = bool(policy.get("require_sanitized"))
    external = _external_provider_config(str(policy.get("provider_id") or ""))
    policy["external_provider"] = external
    spend = _external_spend_this_month()
    policy["spend_this_month_usd"] = spend["usd"]
    policy["spend_this_month_hkd"] = spend["hkd"]
    policy["remaining_monthly_hkd"] = max(0.0, float(policy.get("max_monthly_hkd") or 0) - spend["hkd"]) if float(policy.get("max_monthly_hkd") or 0) > 0 else None
    policy["effective"] = bool(policy["enabled"] and external.get("configured"))
    if policy["enabled"] and not external.get("configured"):
        policy["effective_reason"] = "已打开策略但供应商尚未完成服务器端配置；系统不会外发请求。"
    else:
        policy["effective_reason"] = "紧急外部算力已配置并可按策略启用。" if policy["effective"] else "紧急外部算力目前关闭。"
    return policy


def update_overflow_policy(payload: dict[str, Any]) -> dict[str, Any]:
    provider_id = str(payload.get("provider_id") or DEFAULT_OVERFLOW_POLICY["provider_id"]).strip()
    if provider_id not in {item["id"] for item in EXTERNAL_PROVIDER_CATALOG}:
        raise ValueError("外部供应商不在获批适配器目录")
    enabled = bool(payload.get("enabled"))
    if enabled:
        external = _external_provider_config(provider_id)
        if external.get("provider_id") != provider_id or not external.get("configured"):
            raise ValueError("启用前必须配置获批供应商的服务器端 API Key 和 HTTPS 官方域名")
    try:
        queue_depth = max(1, min(100000, int(payload.get("trigger_queue_depth", DEFAULT_OVERFLOW_POLICY["trigger_queue_depth"]))))
        latency_ms = max(100, min(600000, int(payload.get("trigger_latency_ms", DEFAULT_OVERFLOW_POLICY["trigger_latency_ms"]))))
        max_monthly_hkd = _optional_cost(payload.get("max_monthly_hkd", DEFAULT_OVERFLOW_POLICY["max_monthly_hkd"]), "每月外部预算")
        max_request_tokens = max(0, min(100000000, int(payload.get("max_request_tokens", DEFAULT_OVERFLOW_POLICY["max_request_tokens"]))))
    except (TypeError, ValueError) as exc:
        raise ValueError("紧急算力阈值或预算格式不正确") from exc
    if enabled and (not max_monthly_hkd or max_monthly_hkd <= 0):
        raise ValueError("启用紧急外部算力前必须设置每月外部预算上限")
    if enabled and max_request_tokens <= 0:
        raise ValueError("启用紧急外部算力前必须设置单次 token 上限")
    init_db()
    with DB_LOCK, db_connection() as conn:
        now = _now()
        conn.execute(
            """
            UPDATE overflow_policy SET enabled = ?, provider_id = ?, trigger_queue_depth = ?,
                trigger_latency_ms = ?, max_monthly_hkd = ?, max_request_tokens = ?,
                require_sanitized = 1, updated_at = ? WHERE id = 1
            """,
            (int(enabled), provider_id, queue_depth, latency_ms, max_monthly_hkd or 0, max_request_tokens, now),
        )
    return {"ok": True, "policy": get_overflow_policy()}


def update_model_tariff_costs(model_id: str, costs: dict[str, Any]) -> dict[str, Any]:
    model_id = str(model_id or "").strip()
    if not model_id:
        raise ValueError("模型 ID 不能为空")
    init_db()
    with DB_LOCK, db_connection() as conn:
        model = conn.execute("SELECT model_id FROM model_catalog WHERE model_id = ? AND enabled = 1", (model_id,)).fetchone()
        if not model:
            raise ValueError("模型尚未在内部模型目录启用")
        now = _now()
        for band in TARIFF_BANDS:
            band_id = band["id"]
            raw = costs.get(band_id) or {}
            if not isinstance(raw, dict):
                raise ValueError("分时成本格式不正确")
            input_cost = _optional_cost(raw.get("input_usd_per_million"), f"{band['name']}输入成本")
            output_cost = _optional_cost(raw.get("output_usd_per_million"), f"{band['name']}输出成本")
            conn.execute(
                """
                INSERT INTO model_tariff_costs(model_id, band_id, input_cost_usd_per_million, output_cost_usd_per_million, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(model_id, band_id) DO UPDATE SET
                    input_cost_usd_per_million = excluded.input_cost_usd_per_million,
                    output_cost_usd_per_million = excluded.output_cost_usd_per_million,
                    updated_at = excluded.updated_at
                """,
                (model_id, band_id, input_cost, output_cost, now),
            )
    return {"ok": True, "model_id": model_id, "costs": get_model_tariff_costs(model_id)}


def get_model_tariff_costs(model_id: str | None = None) -> list[dict[str, Any]]:
    init_db()
    with DB_LOCK, db_connection() as conn:
        if model_id:
            rows = conn.execute(
                "SELECT * FROM model_tariff_costs WHERE model_id = ? ORDER BY model_id, band_id", (model_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM model_tariff_costs ORDER BY model_id, band_id").fetchall()
    return [dict(row) for row in rows]


def _internal_cost_rates(model_id: str, band_id: str) -> tuple[float | None, float | None]:
    """Return the approved internal rate for a model and HKT tariff band.

    A blank tariff remains blank. The older flat model-catalog fields are only
    used as a compatibility fallback for models registered before the tariff
    editor existed; the UI labels these as needing finance/platform review.
    """
    init_db()
    with DB_LOCK, db_connection() as conn:
        tariff = conn.execute(
            "SELECT input_cost_usd_per_million, output_cost_usd_per_million FROM model_tariff_costs WHERE model_id = ? AND band_id = ?",
            (model_id, band_id),
        ).fetchone()
        if tariff and (tariff["input_cost_usd_per_million"] is not None or tariff["output_cost_usd_per_million"] is not None):
            return tariff["input_cost_usd_per_million"], tariff["output_cost_usd_per_million"]
        catalog = conn.execute(
            "SELECT input_cost_usd_per_million, output_cost_usd_per_million FROM model_catalog WHERE model_id = ?",
            (model_id,),
        ).fetchone()
    if not catalog:
        return None, None
    return catalog["input_cost_usd_per_million"], catalog["output_cost_usd_per_million"]


def _cost_usd(input_tokens: int, output_tokens: int, input_rate: Any, output_rate: Any) -> float | None:
    if input_rate is None or output_rate is None:
        return None
    return round(
        (max(0, int(input_tokens)) / 1_000_000) * float(input_rate)
        + (max(0, int(output_tokens)) / 1_000_000) * float(output_rate),
        8,
    )


def _external_spend_this_month() -> dict[str, float]:
    now_hkt = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    month_start = now_hkt.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")
    init_db()
    with DB_LOCK, db_connection() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0), COALESCE(SUM(cost_hkd), 0) FROM usage WHERE route_type = 'external' AND created_at >= ?",
            (month_start,),
        ).fetchone()
    return {"usd": float(row[0] or 0), "hkd": float(row[1] or 0)}


def _estimate_tokens(text: str) -> int:
    # This is a conservative preflight estimate only; final accounting uses
    # the gateway's usage object when it is returned.
    return max(1, int(len(str(text).encode("utf-8")) / 3.5))


def _sanitize_external_text(text: str) -> str:
    """Redact common direct identifiers and bearer-style secrets before egress."""
    sanitized = str(text or "")
    sanitized = re.sub(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "[已脱敏邮箱]", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"(?<!\d)(?:\+?852[-\s]?)?[2-9]\d{3}[-\s]?\d{4}(?!\d)", "[已脱敏电话]", sanitized)
    sanitized = re.sub(r"(?<!\d)\d{8,20}(?!\d)", "[已脱敏编号]", sanitized)
    sanitized = re.sub(r"(?i)\b(?:bearer|api[_ -]?key|token)\s*[:=]?\s*[A-Za-z0-9._~+/=-]{8,}", "[已脱敏凭证]", sanitized)
    return sanitized


def _connect() -> sqlite3.Connection:
    TOKEN_HUB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def db_connection():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with DB_LOCK, db_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                segment TEXT NOT NULL DEFAULT '个人',
                credits INTEGER NOT NULL DEFAULT 10000,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                action TEXT NOT NULL,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                task_id TEXT NOT NULL DEFAULT 'customer_service',
                model_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT NOT NULL,
                source TEXT NOT NULL,
                industry TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                score INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT '新线索',
                evidence TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(company_name, source)
            );
            CREATE TABLE IF NOT EXISTS crawl_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                records INTEGER NOT NULL DEFAULT 0,
                detail TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                plan_id TEXT NOT NULL,
                amount_hkd INTEGER NOT NULL DEFAULT 0,
                credits INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'demo-paid',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS model_catalog (
                model_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT 'internal',
                enabled INTEGER NOT NULL DEFAULT 1,
                input_cost_usd_per_million REAL,
                output_cost_usd_per_million REAL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS model_routes (
                task_id TEXT PRIMARY KEY,
                model_id TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'system',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS model_tariff_costs (
                model_id TEXT NOT NULL,
                band_id TEXT NOT NULL,
                input_cost_usd_per_million REAL,
                output_cost_usd_per_million REAL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(model_id, band_id)
            );
            CREATE TABLE IF NOT EXISTS overflow_policy (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                enabled INTEGER NOT NULL DEFAULT 0,
                provider_id TEXT NOT NULL DEFAULT 'deepseek_public',
                trigger_queue_depth INTEGER NOT NULL DEFAULT 20,
                trigger_latency_ms INTEGER NOT NULL DEFAULT 8000,
                max_monthly_hkd REAL NOT NULL DEFAULT 0,
                max_request_tokens INTEGER NOT NULL DEFAULT 0,
                require_sanitized INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            );
            """
        )
        usage_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(usage)").fetchall()}
        if "task_id" not in usage_columns:
            conn.execute("ALTER TABLE usage ADD COLUMN task_id TEXT NOT NULL DEFAULT 'customer_service'")
        if "model_id" not in usage_columns:
            conn.execute("ALTER TABLE usage ADD COLUMN model_id TEXT NOT NULL DEFAULT ''")
        if "provider" not in usage_columns:
            conn.execute("ALTER TABLE usage ADD COLUMN provider TEXT NOT NULL DEFAULT 'internal'")
        if "route_type" not in usage_columns:
            conn.execute("ALTER TABLE usage ADD COLUMN route_type TEXT NOT NULL DEFAULT 'internal'")
        if "cost_usd" not in usage_columns:
            conn.execute("ALTER TABLE usage ADD COLUMN cost_usd REAL")
        if "cost_hkd" not in usage_columns:
            conn.execute("ALTER TABLE usage ADD COLUMN cost_hkd REAL")
        if "tariff_band" not in usage_columns:
            conn.execute("ALTER TABLE usage ADD COLUMN tariff_band TEXT NOT NULL DEFAULT 'shoulder'")
        if "data_classification" not in usage_columns:
            conn.execute("ALTER TABLE usage ADD COLUMN data_classification TEXT NOT NULL DEFAULT 'internal'")
        if "fallback_reason" not in usage_columns:
            conn.execute("ALTER TABLE usage ADD COLUMN fallback_reason TEXT NOT NULL DEFAULT ''")
        route_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(model_routes)").fetchall()}
        if "source" not in route_columns:
            conn.execute("ALTER TABLE model_routes ADD COLUMN source TEXT NOT NULL DEFAULT 'system'")
        conn.execute(
            """
            INSERT OR IGNORE INTO overflow_policy(
                id, enabled, provider_id, trigger_queue_depth, trigger_latency_ms,
                max_monthly_hkd, max_request_tokens, require_sanitized, updated_at
            ) VALUES (1, 0, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                DEFAULT_OVERFLOW_POLICY["provider_id"],
                DEFAULT_OVERFLOW_POLICY["trigger_queue_depth"],
                DEFAULT_OVERFLOW_POLICY["trigger_latency_ms"],
                DEFAULT_OVERFLOW_POLICY["max_monthly_hkd"],
                DEFAULT_OVERFLOW_POLICY["max_request_tokens"],
                _now(),
            ),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users(id, display_name, segment, credits, created_at) VALUES (?, ?, ?, ?, ?)",
            ("demo-user", "演示企业用户", "SME", 10000, _now()),
        )
        config_model = _configured_model_ids()[0]
        for model_id in _configured_model_ids():
            conn.execute(
                """
                INSERT OR IGNORE INTO model_catalog(
                    model_id, display_name, provider, enabled, note, created_at, updated_at
                ) VALUES (?, ?, 'internal', 1, ?, ?, ?)
                """,
                (model_id, f"公司内网 · {model_id}", "仅向公司内网网关发起调用，实际成本待录入", _now(), _now()),
            )
            conn.execute("UPDATE model_catalog SET enabled = 1, updated_at = ? WHERE model_id = ?", (_now(), model_id))
        for task in MODEL_TASKS:
            conn.execute(
                "INSERT OR IGNORE INTO model_routes(task_id, model_id, source, updated_at) VALUES (?, ?, 'system', ?)",
                (task["id"], config_model, _now()),
            )
        for plan in PLANS:
            conn.execute(
                "INSERT OR IGNORE INTO leads(company_name, source, industry, url, score, evidence, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("Cyberport AI 社群", "seed", "AI生态", "https://www.cyberport.hk/en/digital_tech/ai/", 98, "公开 AI 社群入口，可作为生态伙伴和试点渠道", _now(), _now()),
            )
            break


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def get_plans() -> list[dict[str, Any]]:
    return [dict(plan) for plan in PLANS]


def get_model_lab() -> dict[str, Any]:
    """Return routing, tariff, overflow and public price data for the model lab.

    Public prices are reference data unless a separately approved server-side
    adapter is configured. No credential is ever returned to the browser.
    """
    init_db()
    discovered = _sync_discovered_model_catalog()
    _apply_task_defaults(discovered)
    config = load_ai_config(include_key=False)
    current_model = str(config.get("model") or "deepseek-v4")
    with DB_LOCK, db_connection() as conn:
        model_rows = conn.execute(
            "SELECT * FROM model_catalog ORDER BY provider, display_name, model_id"
        ).fetchall()
        route_rows = conn.execute("SELECT * FROM model_routes").fetchall()
    route_map = {str(row["task_id"]): dict(row) for row in route_rows}
    models = []
    for row in model_rows:
        item = dict(row)
        item["enabled"] = bool(item.get("enabled"))
        item["available"] = bool(item["enabled"])
        item["is_current"] = item["model_id"] == current_model
        models.append(item)
    tasks = []
    for item in MODEL_TASKS:
        route = route_map.get(item["id"]) or {"model_id": current_model, "source": "system", "updated_at": ""}
        tasks.append({**item, "selected_model_id": route["model_id"], "route_source": route.get("source", "system"), "updated_at": route["updated_at"]})
    current_band = _current_tariff_band()
    tariff_bands = [
        {
            "id": band["id"],
            "name": band["name"],
            "windows": band["windows"],
            "note": band["note"],
            "current": band["id"] == current_band["id"],
        }
        for band in TARIFF_BANDS
    ]
    external_providers = [_external_provider_config(item["id"]) for item in EXTERNAL_PROVIDER_CATALOG]
    return {
        "tasks": tasks,
        "models": models,
        "public_api_prices": [dict(item) for item in PUBLIC_API_PRICES],
        "tariff_bands": tariff_bands,
        "tariff_costs": get_model_tariff_costs(),
        "external_providers": external_providers,
        "overflow_policy": get_overflow_policy(),
        "economics": {
            "current_band_id": current_band["id"],
            "current_band_name": current_band["name"],
            "formula": "月度请求数 × (输入 tokens ÷ 1,000,000 × 输入成本 + 输出 tokens ÷ 1,000,000 × 输出成本)",
            "cost_currency": "USD / 1M tokens",
            "note": "峰、平、谷是运营规划时段；内部成本必须由平台或财务录入，未录入不作便宜与否结论。",
        },
        "assumptions": {
            "usd_hkd": USD_HKD_ASSUMPTION,
            "formula": "requests × (input_tokens ÷ 1,000,000 × input_price + output_tokens ÷ 1,000,000 × output_price)",
            "note": "内部模型的真实成本尚未由财务或平台团队录入；未录入前不能判定外部 API 一定更便宜。",
        },
        "internal_config": {
            "provider": str(config.get("provider") or "internal"),
            "model": current_model,
            "has_api_key": bool(config.get("has_api_key")),
            "base_url_is_internal": is_internal_ai_base_url(str(config.get("base_url") or "")),
        },
    }


def register_internal_model(
    model_id: str,
    display_name: str = "",
    input_cost_usd_per_million: Any = None,
    output_cost_usd_per_million: Any = None,
    note: str = "",
) -> dict[str, Any]:
    """Register a model id that is served by the existing internal gateway."""
    model_id = str(model_id or "").strip()
    if not MODEL_ID_RE.fullmatch(model_id):
        raise ValueError("模型 ID 只可包含英文字母、数字、点、底线、冒号或短横线")
    if model_id not in _discover_internal_model_ids():
        raise ValueError("模型 ID 未在公司内网网关的 /models 目录发现，请先确认模型已部署并可用")
    display_name = str(display_name or "").strip()[:120] or f"公司内网 · {model_id}"
    note = str(note or "").strip()[:240] or "由内部网关提供；请先确认该模型 ID 在网关可用。"
    input_cost = _optional_cost(input_cost_usd_per_million, "输入成本")
    output_cost = _optional_cost(output_cost_usd_per_million, "输出成本")
    init_db()
    with DB_LOCK, db_connection() as conn:
        now = _now()
        conn.execute(
            """
            INSERT INTO model_catalog(
                model_id, display_name, provider, enabled,
                input_cost_usd_per_million, output_cost_usd_per_million,
                note, created_at, updated_at
            ) VALUES (?, ?, 'internal', 1, ?, ?, ?, ?, ?)
            ON CONFLICT(model_id) DO UPDATE SET
                display_name = excluded.display_name,
                enabled = 1,
                input_cost_usd_per_million = excluded.input_cost_usd_per_million,
                output_cost_usd_per_million = excluded.output_cost_usd_per_million,
                note = excluded.note,
                updated_at = excluded.updated_at
            """,
            (model_id, display_name, input_cost, output_cost, note, now, now),
        )
        row = conn.execute("SELECT * FROM model_catalog WHERE model_id = ?", (model_id,)).fetchone()
    return {"ok": True, "model": dict(row) if row else {}}


def set_model_route(task_id: str, model_id: str) -> dict[str, Any]:
    task = _task(str(task_id or ""))
    model_id = str(model_id or "").strip()
    if not model_id:
        raise ValueError("模型 ID 不能为空")
    init_db()
    with DB_LOCK, db_connection() as conn:
        model = conn.execute(
            "SELECT * FROM model_catalog WHERE model_id = ? AND enabled = 1", (model_id,)
        ).fetchone()
        if not model:
            raise ValueError("模型尚未在内部模型目录启用")
        now = _now()
        conn.execute(
            """
            INSERT INTO model_routes(task_id, model_id, source, updated_at) VALUES (?, ?, 'manual', ?)
            ON CONFLICT(task_id) DO UPDATE SET model_id = excluded.model_id, source = 'manual', updated_at = excluded.updated_at
            """,
            (task["id"], model_id, now),
        )
    return {"ok": True, "task_id": task["id"], "task_name": task["name"], "model_id": model_id, "updated_at": now}


def _resolve_route(task_id: str, model_id: str | None = None) -> tuple[dict[str, str], str]:
    task = _task(str(task_id or "customer_service"))
    init_db()
    with DB_LOCK, db_connection() as conn:
        selected = str(model_id or "").strip()
        if selected:
            row = conn.execute(
                "SELECT model_id FROM model_catalog WHERE model_id = ? AND enabled = 1", (selected,)
            ).fetchone()
            if not row:
                raise ValueError("模型尚未在内部模型目录启用")
            return task, selected
        row = conn.execute("SELECT model_id FROM model_routes WHERE task_id = ?", (task["id"],)).fetchone()
        if row:
            return task, str(row["model_id"])
    return task, _configured_model_ids()[0]


def get_user(user_id: str = "demo-user") -> dict[str, Any]:
    init_db()
    with DB_LOCK, db_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _row(row) or {"id": user_id, "display_name": "演示企业用户", "segment": "SME", "credits": 0}


def subscribe(user_id: str, plan_id: str) -> dict[str, Any]:
    init_db()
    plan = next((item for item in PLANS if item["id"] == plan_id), None)
    if not plan:
        raise ValueError("套餐不存在")
    order_id = "TH-" + datetime.now().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:8].upper()
    with DB_LOCK, db_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users(id, display_name, segment, credits, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, "演示企业用户", "个人", 0, _now()),
        )
        conn.execute("UPDATE users SET credits = credits + ?, segment = ? WHERE id = ?", (plan["credits"], "企业" if plan_id == "business" else "SME", user_id))
        conn.execute(
            "INSERT INTO orders(id, user_id, plan_id, amount_hkd, credits, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (order_id, user_id, plan_id, plan["price_hkd"], plan["credits"], "demo-paid", _now()),
        )
    return {
        "ok": True,
        "order": {"id": order_id, "status": "demo-paid", "amount_hkd": plan["price_hkd"], "credits": plan["credits"]},
        "plan": plan,
        "user": get_user(user_id),
    }


def list_leads(limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    with DB_LOCK, db_connection() as conn:
        rows = conn.execute("SELECT * FROM leads ORDER BY score DESC, updated_at DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()
        return [dict(row) for row in rows]


def list_crawl_runs(limit: int = 10) -> list[dict[str, Any]]:
    init_db()
    with DB_LOCK, db_connection() as conn:
        rows = conn.execute("SELECT * FROM crawl_runs ORDER BY id DESC LIMIT ?", (max(1, min(limit, 50)),)).fetchall()
        return [dict(row) for row in rows]


def list_orders(limit: int = 30) -> list[dict[str, Any]]:
    init_db()
    with DB_LOCK, db_connection() as conn:
        rows = conn.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 100)),)).fetchall()
        return [dict(row) for row in rows]


def update_lead_status(lead_id: int, status: str) -> dict[str, Any]:
    allowed = {"新线索", "已联系", "试用中", "已转化", "已忽略"}
    if status not in allowed:
        raise ValueError("线索状态不受支持")
    init_db()
    with DB_LOCK, db_connection() as conn:
        cursor = conn.execute("UPDATE leads SET status = ?, updated_at = ? WHERE id = ?", (status, _now(), int(lead_id)))
        if cursor.rowcount != 1:
            raise ValueError("线索不存在")
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (int(lead_id),)).fetchone()
    return {"ok": True, "lead": _row(row)}


def summary() -> dict[str, Any]:
    init_db()
    with DB_LOCK, db_connection() as conn:
        lead_count = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        active_count = conn.execute("SELECT COUNT(*) FROM leads WHERE status != '已忽略'").fetchone()[0]
        usage_today = conn.execute("SELECT COALESCE(SUM(input_tokens + output_tokens), 0) FROM usage WHERE date(created_at) = date('now', 'localtime')").fetchone()[0]
        order_count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        demo_revenue = conn.execute("SELECT COALESCE(SUM(amount_hkd), 0) FROM orders WHERE status = 'demo-paid'").fetchone()[0]
        last_run = conn.execute("SELECT * FROM crawl_runs ORDER BY id DESC LIMIT 1").fetchone()
    now_hkt = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    next_crawl = now_hkt.replace(hour=5, minute=0, second=0, microsecond=0)
    if next_crawl <= now_hkt:
        next_crawl += timedelta(days=1)
    return {"lead_count": lead_count, "active_leads": active_count, "usage_today": usage_today, "order_count": order_count, "demo_revenue_hkd": demo_revenue, "last_crawl": _row(last_run), "next_crawl_at": next_crawl.isoformat(timespec="minutes")}


def _call_model(question: str, task_id: str = "customer_service", model_id: str | None = None) -> tuple[str, int, int, str, str]:
    task, selected_model = _resolve_route(task_id, model_id)
    config = load_ai_config(include_key=True)
    api_key = str(config.get("api_key") or "").strip()
    if not api_key:
        raise RuntimeError("公司内网模型尚未配置 API Key")
    base_url = str(config.get("base_url") or INTERNAL_AI_BASE_URL).rstrip("/")
    body = {
        "model": selected_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是 CMHK AI Token Hub 的香港企业助手。用繁体中文或用户语言回答，答案简洁、可执行；"
                    "不要声称自己能处理付款或真实订单。当前任务是："
                    f"{task['name']}。{task['system_prompt']}"
                ),
            },
            {"role": "user", "content": question[:4000]},
        ],
        "temperature": 0.2,
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    wait_for_internal_ai_slot("token-hub")
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:400]
        raise RuntimeError(f"模型服务暂不可用（HTTP {exc.code}）：{detail}") from exc
    choices = payload.get("choices") or []
    content = str(((choices[0].get("message") or {}).get("content") or "").strip() if choices else "")
    usage = payload.get("usage") or {}
    return (
        content or "模型没有返回内容。",
        int(usage.get("prompt_tokens") or 0),
        int(usage.get("completion_tokens") or 0),
        selected_model,
        task["id"],
    )


def _external_budget_preflight(question: str, policy: dict[str, Any], provider: dict[str, Any]) -> int:
    """Apply budget and per-request guards before any external network call."""
    estimated_input = _estimate_tokens(question) + 120
    max_request_tokens = int(policy.get("max_request_tokens") or 0)
    if max_request_tokens <= 0:
        raise RuntimeError("紧急外部算力未设置单次 token 上限，系统拒绝外发")
    if estimated_input >= max_request_tokens:
        raise RuntimeError("问题长度已超过紧急外部算力的单次 token 上限")
    max_monthly_hkd = float(policy.get("max_monthly_hkd") or 0)
    if max_monthly_hkd <= 0:
        raise RuntimeError("紧急外部算力未设置每月预算上限，系统拒绝外发")
    spend = _external_spend_this_month()
    remaining_usd = max_monthly_hkd / USD_HKD_ASSUMPTION - spend["usd"]
    input_rate = float(provider["input_usd_per_million"])
    output_rate = float(provider["output_usd_per_million"])
    input_guard = estimated_input / 1_000_000 * input_rate
    if remaining_usd <= input_guard:
        raise RuntimeError("本月外部预算余额不足，系统拒绝外发")
    output_budget = int((remaining_usd - input_guard) * 1_000_000 / output_rate)
    return max(1, min(max_request_tokens - estimated_input, output_budget))


def _call_external_model(question: str, task_id: str, policy: dict[str, Any]) -> tuple[str, int, int, str, str, str]:
    task = _task(task_id)
    provider_id = str(policy.get("provider_id") or "").strip()
    provider_config = _external_provider_config(provider_id)
    if not provider_config.get("configured"):
        raise RuntimeError(f"紧急外部算力不可用：{provider_config.get('reason') or '供应商配置不完整'}")
    provider = next((item for item in EXTERNAL_PROVIDER_CATALOG if item["id"] == provider_id), None)
    if not provider:
        raise RuntimeError("紧急外部算力供应商不在获批适配器目录")
    outbound_question = _sanitize_external_text(question[:4000])
    max_tokens = _external_budget_preflight(outbound_question, policy, provider)
    api_key = str(os.environ.get("CMHK_EXTERNAL_AI_API_KEY") or "").strip()
    base_url = str(os.environ.get("CMHK_EXTERNAL_AI_BASE_URL") or provider["base_url"]).strip().rstrip("/")
    body = {
        "model": provider_config["model"],
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是 CMHK AI Token Hub 的紧急公开/脱敏内容助手。用繁体中文或用户语言回答，答案简洁、可执行；"
                    "不要声称自己能处理付款或真实订单。当前任务是："
                    f"{task['name']}。{task['system_prompt']}"
                ),
            },
            {"role": "user", "content": outbound_question},
        ],
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:400]
        raise RuntimeError(f"紧急外部模型暂不可用（HTTP {exc.code}）：{detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("紧急外部模型连接超时或网络不可用") from exc
    choices = payload.get("choices") or []
    message = (choices[0].get("message") or {}) if choices else {}
    content = message.get("content") or ""
    if isinstance(content, list):
        content = "".join(str(part.get("text") or "") if isinstance(part, dict) else str(part) for part in content)
    usage = payload.get("usage") or {}
    return (
        str(content).strip() or "外部模型没有返回内容。",
        int(usage.get("prompt_tokens") or 0),
        int(usage.get("completion_tokens") or 0),
        str(provider_config["model"]),
        task["id"],
        provider_id,
    )


def chat(
    user_id: str,
    question: str,
    task_id: str = "customer_service",
    model_id: str | None = None,
    allow_external: bool = False,
    data_classification: str = "internal",
    force_external: bool = False,
) -> dict[str, Any]:
    init_db()
    if not question.strip():
        raise ValueError("问题不能为空")
    user = get_user(user_id)
    if int(user.get("credits") or 0) <= 0:
        raise ValueError("Token 额度不足，请先选择套餐")
    classification = str(data_classification or "internal").strip().lower()
    if classification not in {"internal", "sanitized", "public"}:
        raise ValueError("数据级别只支持 internal、sanitized 或 public")
    if force_external and not allow_external:
        raise ValueError("强制外部算力前必须明确允许公开或脱敏内容外发")
    policy = get_overflow_policy()
    if (allow_external or force_external) and classification == "internal":
        raise ValueError("当前内容标记为内部数据，不能发送到外部算力")
    route_type = "internal"
    provider = "internal"
    fallback_reason = ""
    tariff_band = _current_tariff_band()["id"]
    if force_external:
        if not policy.get("effective"):
            raise RuntimeError(f"紧急外部算力未启用：{policy.get('effective_reason') or '策略不可用'}")
        answer, input_tokens, output_tokens, model, resolved_task_id, provider = _call_external_model(question, task_id, policy)
        route_type = "external"
        fallback_reason = "manual_emergency"
    else:
        try:
            answer, input_tokens, output_tokens, model, resolved_task_id = _call_model(question, task_id, model_id)
        except (RuntimeError, urllib.error.URLError, TimeoutError) as internal_error:
            if not allow_external or classification == "internal" or not policy.get("effective"):
                raise
            answer, input_tokens, output_tokens, model, resolved_task_id, provider = _call_external_model(question, task_id, policy)
            route_type = "external"
            fallback_reason = "internal_call_failed"
    consumed = max(1, input_tokens + output_tokens)
    if route_type == "external":
        provider_item = next((item for item in EXTERNAL_PROVIDER_CATALOG if item["id"] == provider), None)
        input_rate = provider_item["input_usd_per_million"] if provider_item else None
        output_rate = provider_item["output_usd_per_million"] if provider_item else None
    else:
        input_rate, output_rate = _internal_cost_rates(model, tariff_band)
    cost_usd = _cost_usd(input_tokens, output_tokens, input_rate, output_rate)
    cost_hkd = round(cost_usd * USD_HKD_ASSUMPTION, 6) if cost_usd is not None else None
    with DB_LOCK, db_connection() as conn:
        conn.execute("UPDATE users SET credits = MAX(0, credits - ?) WHERE id = ?", (consumed, user_id))
        conn.execute(
            """
            INSERT INTO usage(
                user_id, action, input_tokens, output_tokens, task_id, model_id,
                provider, route_type, cost_usd, cost_hkd, tariff_band,
                data_classification, fallback_reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                "企业助手",
                input_tokens,
                output_tokens,
                resolved_task_id,
                model,
                provider,
                route_type,
                cost_usd,
                cost_hkd,
                tariff_band,
                classification,
                fallback_reason,
                _now(),
            ),
        )
    return {
        "ok": True,
        "answer": answer,
        "model": model,
        "task_id": resolved_task_id,
        "provider": provider,
        "route_type": route_type,
        "tariff_band": tariff_band,
        "fallback_reason": fallback_reason or None,
        "cost_usd": cost_usd,
        "cost_hkd": cost_hkd,
        "consumed": consumed,
        "user": get_user(user_id),
    }


init_db()

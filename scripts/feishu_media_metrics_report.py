#!/usr/bin/env python3
"""Collect CMHK Feishu publication metrics and send one table-only report."""

from __future__ import annotations

import argparse
import html
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_config import load_ai_config  # noqa: E402
from ai_key_rotation import open_llm_request  # noqa: E402
from cmhk.integrations.feishu_runtime import lark_cli_env, resolve_lark_cli  # noqa: E402


HKT = ZoneInfo("Asia/Hong_Kong")
DEFAULT_CONFIG = ROOT / "config" / "feishu_media_metrics.local.json"
DEFAULT_STATE = ROOT / "var" / "feishu_media_metrics" / "state.json"
DEFAULT_IMAGE = ROOT / "var" / "feishu_media_metrics" / "latest_report.png"
NO_PROXY_KEYS = (
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "ALL_PROXY",
    "https_proxy",
    "http_proxy",
    "all_proxy",
)
LARK_RATE_LIMIT_MAX_ATTEMPTS = 5
LARK_RATE_LIMIT_BACKOFF_SECONDS = 1.0
LARK_RATE_LIMIT_BACKOFF_CAP_SECONDS = 8.0


class ReportError(RuntimeError):
    pass


@dataclass
class CommandResult:
    payload: dict[str, Any]
    stderr: str


def _safe_error(text: str) -> str:
    value = str(text or "").strip().replace("\n", " ")
    return value[:500]


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _cli_payload(text: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _is_rate_limit_error(payload: dict[str, Any] | None, text: str) -> bool:
    error = payload.get("error") if isinstance(payload, dict) else None
    error = error if isinstance(error, dict) else {}
    code = error.get("code")
    subtype = str(error.get("subtype") or "").lower()
    message = f"{error.get('message') or ''} {text}".lower()
    return code == 429 or subtype == "rate_limit" or "http 429" in message


def _rate_limit_backoff(attempt: int) -> float:
    base = min(
        LARK_RATE_LIMIT_BACKOFF_CAP_SECONDS,
        LARK_RATE_LIMIT_BACKOFF_SECONDS * (2**attempt),
    )
    return base + random.uniform(0.0, base * 0.25)


def run_lark(args: list[str], *, profile: str | None = None, timeout: int = 180) -> CommandResult:
    env = lark_cli_env()
    command = [resolve_lark_cli(), *args]
    if profile:
        command.extend(["--profile", profile])
    for attempt in range(LARK_RATE_LIMIT_MAX_ATTEMPTS):
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        raw_error = completed.stderr or completed.stdout
        payload = _cli_payload(completed.stdout) or _cli_payload(completed.stderr)
        rate_limited = (
            completed.returncode != 0 or (isinstance(payload, dict) and payload.get("ok") is False)
        ) and _is_rate_limit_error(payload, raw_error)
        if rate_limited and attempt + 1 < LARK_RATE_LIMIT_MAX_ATTEMPTS:
            time.sleep(_rate_limit_backoff(attempt))
            continue
        if completed.returncode != 0:
            raise ReportError(f"飞书命令失败：{_safe_error(raw_error)}")
        if payload is None:
            raise ReportError("飞书命令未返回有效 JSON")
        if payload.get("ok") is False:
            error = payload.get("error") or {}
            raise ReportError(f"飞书接口失败：{_safe_error(error.get('message') or payload)}")
        return CommandResult(payload=payload, stderr=completed.stderr)
    raise ReportError("飞书命令重试次数已耗尽")


def _data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def get_chat(chat_id: str, profile: str) -> dict[str, Any]:
    result = run_lark(
        ["im", "chats", "get", "--as", "bot", "--params", json.dumps({"chat_id": chat_id}), "--format", "json"],
        profile=profile,
    )
    return _data(result.payload)


def require_group(chat: dict[str, Any], expected_name: str, *, tenant_only: bool) -> int:
    checks = {
        "name": chat.get("name") == expected_name,
        "chat_mode": chat.get("chat_mode") == "group",
        "chat_status": chat.get("chat_status") == "normal",
    }
    if tenant_only:
        checks.update(
            {
                "chat_tag": chat.get("chat_tag") == "tenant",
                "external": chat.get("external") is False,
            }
        )
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise ReportError(f"群聊安全校验失败：{', '.join(failed)}")
    count = int(chat.get("user_count") or 0)
    if count <= 0:
        raise ReportError("群成员人数无效")
    return count


def require_preview_chat(chat: dict[str, Any]) -> None:
    if chat.get("chat_mode") not in {"p2p", "group"} or chat.get("chat_status") != "normal":
        raise ReportError("个人预览会话安全校验失败")
    if chat.get("chat_mode") == "group":
        raise ReportError("个人预览目标意外解析为群聊，已停止发送")


def get_read_count(message_id: str, profile: str) -> int:
    params = {"message_id": message_id, "user_id_type": "open_id", "page_size": 100}
    result = run_lark(
        [
            "im",
            "messages",
            "read_users",
            "--as",
            "bot",
            "--params",
            json.dumps(params),
            "--page-all",
            "--page-limit",
            "30",
            "--format",
            "json",
        ],
        profile=profile,
        timeout=300,
    )
    items = _data(result.payload).get("items") or []
    return len({str(item.get("user_id")) for item in items if item.get("user_id")})


def get_message_metadata(message_ids: list[str], profile: str) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for offset in range(0, len(message_ids), 50):
        batch = message_ids[offset : offset + 50]
        result = run_lark(
            [
                "im",
                "+messages-mget",
                "--as",
                "bot",
                "--message-ids",
                ",".join(batch),
                "--format",
                "json",
            ],
            profile=profile,
        )
        data = _data(result.payload)
        items = data.get("items") or data.get("messages") or []
        metadata.update({str(item.get("message_id")): item for item in items if item.get("message_id")})
    return metadata


def list_chat_messages(chat_id: str, profile: str, start: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    page_token = ""
    for _ in range(100):
        args = [
            "im",
            "+chat-messages-list",
            "--as",
            "bot",
            "--chat-id",
            chat_id,
            "--start",
            start,
            "--sort",
            "asc",
            "--page-size",
            "50",
            "--format",
            "json",
        ]
        if page_token:
            args.extend(["--page-token", page_token])
        result = run_lark(args, profile=profile)
        data = _data(result.payload)
        messages.extend(data.get("messages") or data.get("items") or [])
        if not data.get("has_more"):
            return messages
        next_token = str(data.get("page_token") or "")
        if not next_token or next_token == page_token:
            raise ReportError("CMHK 历史消息分页游标无效")
        page_token = next_token
    raise ReportError("CMHK 历史消息超过安全分页上限")


def compact_card_title(message: dict[str, Any]) -> str:
    content = html.unescape(str(message.get("content") or ""))
    match = re.search(r'<card\s+title=["\']([^"\']+)["\']', content)
    return html.unescape(match.group(1)).strip() if match else ""


def tracked_publication_title(title: str, discovery: dict[str, Any]) -> bool:
    value = str(title or "").strip()
    markers = [str(item) for item in discovery.get("title_markers") or ["科普系列"]]
    if any(marker and marker in value for marker in markers):
        return True
    if discovery.get("include_series_launch", True):
        return ("正式啟動" in value or "正式启动" in value) and "小科" in value and "小新" in value
    return False


def publication_display_title(title: str) -> str:
    value = str(title or "").strip()
    match = re.match(r"^【([^】]+)】\s*(.+)$", value)
    if not match:
        return value
    heading, subject = match.groups()
    series = re.search(r"(?:^|｜)([^｜]+?)科普系列(?:$|｜)", heading)
    if series:
        return f"{series.group(1)}科普｜{subject}"
    if "正式啟動" in heading or "正式启动" in heading:
        return "引子篇｜系列正式启动"
    return subject


def get_card_payload(message_id: str, profile: str) -> dict[str, Any]:
    result = run_lark(
        [
            "api",
            "GET",
            f"/open-apis/im/v1/messages/{message_id}",
            "--as",
            "bot",
            "--params",
            json.dumps({"card_msg_content_type": "user_card_content", "user_id_type": "open_id"}),
            "--format",
            "json",
        ],
        profile=profile,
    )
    items = _data(result.payload).get("items") or []
    item = items[0] if items else {}
    content = ((item.get("body") or {}).get("content") or "")
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ReportError(f"正式发布卡片内容无效：{message_id}") from exc
    return payload if isinstance(payload, dict) else {}


def drive_token_from_card(payload: dict[str, Any]) -> str:
    url = str((payload.get("card_link") or {}).get("url") or "")
    match = re.search(r"/file/([A-Za-z0-9_-]+)", url)
    return match.group(1) if match else ""


def discover_publications(config: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    seeded = list(config.get("publications") or [])
    discovery = config.get("auto_discovery") or {}
    if discovery.get("enabled", True) is False:
        return seeded
    sender = config["sender"]
    profile = str(sender["profile"])
    source_chat_id = str(config["source_chat"]["chat_id"])
    history = list_chat_messages(source_chat_id, profile, str(discovery.get("start") or "2026-08-01"))
    active_messages = {
        str(item.get("message_id")): item
        for item in history
        if item.get("deleted") is not True
        and item.get("chat_id") == source_chat_id
        and str((item.get("sender") or {}).get("id") or "") == str(sender["app_id"])
    }
    discovered = []
    for publication in state.get("discovered_publications") or []:
        messages = publication.get("messages") or []
        if messages and str(messages[0].get("message_id") or "") in active_messages:
            discovered.append(publication)
    known_ids = {
        str(message.get("message_id") or "")
        for publication in [*seeded, *discovered]
        for message in publication.get("messages") or []
    }
    known_titles = {str(publication.get("title") or "") for publication in [*seeded, *discovered]}
    ordered = sorted(
        active_messages.values(),
        key=lambda item: (int(item.get("message_position") or 0), str(item.get("message_id") or "")),
    )
    for item in ordered:
        message_id = str(item.get("message_id") or "")
        if message_id in known_ids or item.get("msg_type") != "interactive":
            continue
        exact_title = compact_card_title(item)
        if not tracked_publication_title(exact_title, discovery):
            continue
        title = publication_display_title(exact_title)
        if not title or title in known_titles:
            continue
        card = get_card_payload(message_id, profile)
        messages = [{"message_id": message_id, "label": ""}]
        position = int(item.get("message_position") or 0)
        companion = next(
            (
                candidate
                for candidate in ordered
                if candidate.get("msg_type") == "media"
                and int(candidate.get("message_position") or 0) == position + 1
            ),
            None,
        )
        if companion:
            messages[0]["label"] = "图文"
            companion_id = str(companion.get("message_id") or "")
            messages.append({"message_id": companion_id, "label": "视频"})
            known_ids.add(companion_id)
        publication = {
            "title": title,
            "source_title": exact_title,
            "messages": messages,
            "drive_file_token": drive_token_from_card(card),
            "drive_file_type": "file",
            "discovered_at": datetime.now(HKT).isoformat(timespec="seconds"),
        }
        discovered.append(publication)
        known_ids.add(message_id)
        known_titles.add(title)
    state["discovered_publications"] = discovered
    state["auto_discovery"] = {
        "last_scan_at": datetime.now(HKT).isoformat(timespec="seconds"),
        "history_messages": len(history),
        "tracked_publications": len(seeded) + len(discovered),
        "discovered_publications": len(discovered),
    }
    return [*seeded, *discovered]


def get_file_statistics(token: str, file_type: str, *, profile: str = "") -> dict[str, int]:
    params = {"file_token": token, "file_type": file_type}
    identity = os.environ.get("CMHK_FEISHU_DRIVE_IDENTITY", "user").strip().lower()
    if identity not in {"user", "bot"}:
        raise ReportError("CMHK_FEISHU_DRIVE_IDENTITY 只能是 user 或 bot")
    configured_profile = os.environ.get("CMHK_FEISHU_DRIVE_PROFILE", "").strip()
    effective_profile = configured_profile or (profile if identity == "bot" else "")
    result = run_lark(
        ["drive", "file.statistics", "get", "--as", identity, "--params", json.dumps(params), "--format", "json"],
        profile=effective_profile or None,
    )
    statistics = _data(result.payload).get("statistics") or {}
    return {name: int(statistics.get(name) or 0) for name in ("uv", "pv", "uv_today", "pv_today")}


def pct(numerator: int, denominator: int, digits: int) -> str:
    if denominator <= 0:
        return "0%"
    return f"{numerator / denominator * 100:.{digits}f}%"


def collect(config: dict[str, Any], state: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    sender = config["sender"]
    profile = str(sender["profile"])
    source = config["source_chat"]
    source_chat = get_chat(str(source["chat_id"]), profile)
    group_count = require_group(source_chat, str(source["name"]), tenant_only=True)
    cached = state.setdefault("metrics", {})
    publications = discover_publications(config, state)
    first_message_ids = [str(item["messages"][0]["message_id"]) for item in publications]
    metadata = get_message_metadata(first_message_ids, profile)
    rows: list[dict[str, Any]] = []
    for publication in publications:
        title = str(publication["title"])
        first_message_id = str(publication["messages"][0]["message_id"])
        message_meta = metadata.get(first_message_id) or {}
        sender_meta = message_meta.get("sender") or {}
        if message_meta.get("chat_id") != source["chat_id"] or sender_meta.get("id") != sender["app_id"]:
            raise ReportError(f"原消息来源校验失败：{title}")
        published_at = str(message_meta.get("create_time") or "").strip()
        if not published_at:
            published_at = str((cached.get(title) or {}).get("published_at") or "").strip()
        if not published_at:
            raise ReportError(f"无法读取发布时间：{title}")
        message_results: list[dict[str, Any]] = []
        for message in publication.get("messages") or []:
            message_id = str(message["message_id"])
            prior = ((cached.get(title) or {}).get("messages") or {}).get(message_id)
            try:
                count = get_read_count(message_id, profile)
            except ReportError:
                if not prior:
                    raise
                count = int(prior["read_count"])
            message_results.append(
                {"message_id": message_id, "label": str(message.get("label") or ""), "read_count": count}
            )
        drive_stats = None
        token = str(publication.get("drive_file_token") or "")
        if token:
            try:
                drive_stats = get_file_statistics(
                    token,
                    str(publication.get("drive_file_type") or "file"),
                    profile=profile,
                )
            except ReportError:
                drive_stats = (cached.get(title) or {}).get("drive")
                if not drive_stats:
                    raise
        primary_read = int(message_results[0]["read_count"])
        rows.append(
            {
                "title": title,
                "published_at": published_at,
                "messages": message_results,
                "drive": drive_stats,
                "primary_read": primary_read,
            }
        )
        cached[title] = {
            "messages": {item["message_id"]: item for item in message_results},
            "drive": drive_stats,
            "published_at": published_at,
            "updated_at": datetime.now(HKT).isoformat(timespec="seconds"),
        }
    state["group_count"] = group_count
    state["updated_at"] = datetime.now(HKT).isoformat(timespec="seconds")
    return rows, group_count


def render_markdown(rows: list[dict[str, Any]], group_count: int) -> str:
    lines = [
        "| 发布内容 | 发布时间 | 消息已读人数 / 比例 | 文件打开人数 / 占全群 | 文件打开 / 已读 |",
        "|---|---|---:|---:|---:|",
    ]
    for row in rows:
        message_bits = []
        for item in row["messages"]:
            prefix = str(item.get("label") or "")
            value = f"{int(item['read_count']):,}人（{pct(int(item['read_count']), group_count, 1)}）"
            message_bits.append(f"{prefix}{value}" if prefix else value)
        message_text = "；".join(message_bits)
        drive = row.get("drive")
        if drive:
            uv = int(drive.get("uv") or 0)
            file_group = f"{uv:,}人（{pct(uv, group_count, 2)}）"
            file_read = pct(uv, int(row["primary_read"]), 2)
        else:
            file_group = "无法统计"
            file_read = "无法统计"
        lines.append(f"| {row['title']} | {row['published_at']} | {message_text} | {file_group} | {file_read} |")
    return "\n".join(lines)


def table_cells(rows: list[dict[str, Any]], group_count: int) -> list[list[str]]:
    result = []
    for row in rows:
        message_bits = []
        for item in row["messages"]:
            prefix = str(item.get("label") or "")
            value = f"{int(item['read_count']):,}人（{pct(int(item['read_count']), group_count, 1)}）"
            message_bits.append(f"{prefix}{value}" if prefix else value)
        drive = row.get("drive")
        if drive:
            uv = int(drive.get("uv") or 0)
            file_group = f"{uv:,}人（{pct(uv, group_count, 2)}）"
            file_read = pct(uv, int(row["primary_read"]), 2)
        else:
            file_group = "无法统计"
            file_read = "无法统计"
        published = str(row["published_at"])
        if published.startswith("20") and len(published) >= 16:
            published = f"{int(published[5:7])}月{int(published[8:10])}日 {published[11:16]}"
        result.append([str(row["title"]), published, "\n".join(message_bits), file_group, file_read])
    return result


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/System/Library/Fonts/STHeiti Medium.ttc" if bold else "/System/Library/Fonts/STHeiti Light.ttc"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size, index=0)
    return ImageFont.load_default(size=size)


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        current = ""
        for char in paragraph:
            candidate = current + char
            if current and draw.textbbox((0, 0), candidate, font=font)[2] > width:
                lines.append(current)
                current = char
            else:
                current = candidate
        lines.append(current)
    return lines or [""]


def render_image(rows: list[dict[str, Any]], group_count: int, output: Path) -> Path:
    margin = 48
    header_height = 112
    row_height = 190
    width = 1920
    height = max(780, margin + header_height + row_height * len(rows) + margin)
    columns = [410, 300, 510, 360, 244]
    headers = ["发布内容", "发布时间", "消息已读人数 / 比例", "文件打开人数 / 占全群", "文件打开 / 已读"]
    image = Image.new("RGB", (width, height), "#F4F7FC")
    draw = ImageDraw.Draw(image)
    header_font = _font(30, bold=True)
    body_font = _font(30)
    body_bold = _font(30, bold=True)
    x0, y0 = margin, 48
    table_width = sum(columns)
    draw.rounded_rectangle((x0, y0, x0 + table_width, y0 + header_height + row_height * len(rows)), radius=18, fill="#FFFFFF", outline="#CBD5E1", width=2)
    draw.rounded_rectangle((x0, y0, x0 + table_width, y0 + header_height), radius=18, fill="#E8F0FF")
    draw.rectangle((x0, y0 + header_height - 18, x0 + table_width, y0 + header_height), fill="#E8F0FF")
    x = x0
    for index, (title, col_width) in enumerate(zip(headers, columns)):
        draw.text((x + 24, y0 + 31), title, fill="#155EEF" if index == 0 else "#172B4D", font=header_font)
        x += col_width
    cells = table_cells(rows, group_count)
    for row_index, row in enumerate(cells):
        top = y0 + header_height + row_index * row_height
        if row_index % 2:
            draw.rectangle((x0, top, x0 + table_width, top + row_height), fill="#F8FAFD")
        draw.line((x0, top, x0 + table_width, top), fill="#CBD5E1", width=2)
        x = x0
        for col_index, (text, col_width) in enumerate(zip(row, columns)):
            padding = 24
            font = body_bold if col_index == 0 else body_font
            wrapped = _wrap_text(draw, text, font, col_width - padding * 2)
            line_height = 43
            total = len(wrapped) * line_height
            text_y = top + max(20, (row_height - total) // 2)
            fill = "#162A47" if col_index == 0 else "#1F2937"
            for line in wrapped:
                draw.text((x + padding, text_y), line, fill=fill, font=font)
                text_y += line_height
            x += col_width
    x = x0
    for col_width in columns[:-1]:
        x += col_width
        draw.line((x, y0, x, y0 + header_height + row_height * len(rows)), fill="#CBD5E1", width=2)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)
    return output


def _extract_json_object(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    start, end = value.find("{"), value.rfind("}")
    if start < 0 or end < start:
        raise ReportError("DeepSeek-V4-Pro 未返回有效校验结果")
    return json.loads(value[start : end + 1])


def validate_with_model(markdown: str, rows: list[dict[str, Any]], group_count: int, model: str) -> None:
    from ai_response_compat import final_chat_message_text, load_json_response, prepare_structured_chat_body

    ai = load_ai_config(include_key=True)
    api_key = str(ai.get("api_key") or "").strip()
    if not api_key:
        raise ReportError("公司内部模型 API Key 未配置")
    base_url = str(ai.get("base_url") or "").rstrip("/")
    expected_cells = []
    for row in rows:
        messages = []
        for item in row["messages"]:
            count = int(item["read_count"])
            messages.append(
                {
                    "label": item.get("label") or "",
                    "count": count,
                    "ratio": pct(count, group_count, 1),
                }
            )
        drive = row.get("drive")
        expected_cells.append(
            {
                "title": row["title"],
                "published_at": row["published_at"],
                "messages": messages,
                "file_open": (
                    {
                        "uv": int(drive.get("uv") or 0),
                        "group_ratio": pct(int(drive.get("uv") or 0), group_count, 2),
                        "read_ratio": pct(int(drive.get("uv") or 0), int(row["primary_read"]), 2),
                    }
                    if drive
                    else "无法统计"
                ),
            }
        )
    facts = {"group_count": group_count, "expected_cells": expected_cells}
    body = prepare_structured_chat_body({
        **dict(ai.get("extra_parameters") or {}),
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是数据完整性校验器。只比较 expected_cells 与 Markdown 表格，不改写内容。"
                    "expected_cells 已包含所有最终人数和百分比。检查五个列名、所有行、发布时间、人数、"
                    "百分比、千位分隔和无法统计是否完全一致。只报告真正不一致；一致的单元格不是问题。"
                    "仅返回 JSON：{\"ok\":true,\"issues\":[]} 或 {\"ok\":false,\"issues\":[\"...\"]}。"
                ),
            },
            {"role": "user", "content": json.dumps({"facts": facts, "markdown": markdown}, ensure_ascii=False)},
        ],
        "temperature": 0,
    })
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with open_llm_request(
            request,
            timeout=120,
            config=ai,
            requested_key=api_key,
            model=model,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        raise ReportError(f"DeepSeek-V4-Pro 校验失败：{type(exc).__name__}") from exc
    content = final_chat_message_text(payload, operation="飞书传播数据校验")
    verdict = load_json_response(content, operation="飞书传播数据校验")
    if not isinstance(verdict, dict):
        raise ReportError("DeepSeek-V4-Pro 未返回JSON对象")
    if verdict.get("ok") is not True or verdict.get("issues"):
        raise ReportError(f"DeepSeek-V4-Pro 拒绝发送：{_safe_error(verdict.get('issues'))}")


def upload_image(path: Path, config: dict[str, Any]) -> str:
    sender = config["sender"]
    relative = path.resolve().relative_to(ROOT.resolve())
    result = run_lark(
        [
            "im",
            "images",
            "create",
            "--as",
            "bot",
            "--data",
            json.dumps({"image_type": "message"}),
            "--file",
            f"./{relative}",
            "--format",
            "json",
        ],
        profile=str(sender["profile"]),
    )
    image_key = str(_data(result.payload).get("image_key") or "")
    if not image_key:
        raise ReportError("飞书图片上传未返回 image_key")
    return image_key


def send_report(chat_id: str, image_path: Path, config: dict[str, Any], slot: str, as_of: datetime) -> tuple[str, str]:
    sender = config["sender"]
    image_key = upload_image(image_path, config)
    brief = f"截至 {as_of.year}年{as_of.month}月{as_of.day}日 {as_of:%H:%M}（香港时间）"
    post = {
        "zh_cn": {
            "content": [
                [{"tag": "text", "text": brief}],
                [{"tag": "img", "image_key": image_key}],
            ]
        }
    }
    result = run_lark(
        [
            "im",
            "+messages-send",
            "--as",
            "bot",
            "--chat-id",
            chat_id,
            "--msg-type",
            "post",
            "--content",
            json.dumps(post, ensure_ascii=False),
            "--idempotency-key",
            f"cmhk-media-metrics-{slot}-{uuid.uuid4().hex[:10]}",
        ],
        profile=str(sender["profile"]),
    )
    data = _data(result.payload)
    message_id = str(data.get("message_id") or data.get("messageId") or "")
    if not message_id:
        raise ReportError("飞书发送成功但未返回 message_id")
    return message_id, image_key


def readback(message_id: str, expected_chat_id: str, config: dict[str, Any], brief: str, image_key: str) -> None:
    sender = config["sender"]
    result = run_lark(
        ["im", "+messages-mget", "--as", "bot", "--message-ids", message_id],
        profile=str(sender["profile"]),
    )
    data = _data(result.payload)
    items = data.get("items") or data.get("messages") or []
    item = items[0] if items else data
    serialized = json.dumps(item, ensure_ascii=False)
    if str(item.get("chat_id") or item.get("chatId") or "") != expected_chat_id:
        raise ReportError("发送回读的目标会话不一致")
    if item.get("deleted") is True:
        raise ReportError("发送回读显示消息已撤回")
    if item.get("msg_type") not in {"post", None}:
        raise ReportError("发送回读的消息类型不是 post")
    if brief not in serialized:
        raise ReportError("发送回读缺少截至时间")
    if image_key not in serialized:
        raise ReportError("发送回读缺少横版表格图片")


def execute(config_path: Path, state_path: Path, mode: str, *, slot: str | None = None) -> dict[str, Any]:
    config = load_json(config_path)
    if not isinstance(config, dict):
        raise ReportError(f"配置文件不存在或无效：{config_path}")
    state = load_json(state_path, {}) or {}
    rows, group_count = collect(config, state)
    markdown = render_markdown(rows, group_count)
    validate_with_model(markdown, rows, group_count, str(config.get("model") or "DeepSeek-V4-Pro"))
    image_path = render_image(rows, group_count, DEFAULT_IMAGE)
    save_json(state_path, state)
    if mode == "dry-run":
        return {"ok": True, "mode": mode, "markdown": markdown, "image": str(image_path), "group_count": group_count}
    sender = config["sender"]
    if mode == "preview":
        target = config["preview_chat"]
        require_preview_chat(get_chat(str(target["chat_id"]), str(sender["profile"])))
    elif mode == "group":
        target = config["destination_chat"]
        require_group(get_chat(str(target["chat_id"]), str(sender["profile"])), str(target["name"]), tenant_only=False)
    else:
        raise ReportError(f"未知模式：{mode}")
    actual_slot = slot or datetime.now(HKT).strftime("%Y%m%d-%H%M")
    sent_slots = state.setdefault("sent_slots", {})
    if mode == "group" and actual_slot in sent_slots:
        return {"ok": True, "mode": mode, "skipped": True, "message_id": sent_slots[actual_slot]}
    as_of = datetime.now(HKT)
    brief = f"截至 {as_of.year}年{as_of.month}月{as_of.day}日 {as_of:%H:%M}（香港时间）"
    message_id, image_key = send_report(str(target["chat_id"]), image_path, config, actual_slot, as_of)
    readback(message_id, str(target["chat_id"]), config, brief, image_key)
    if mode == "group":
        verified_at = datetime.now(HKT).isoformat(timespec="seconds")
        sent_slots[actual_slot] = message_id
        state.setdefault("slot_deliveries", {})[actual_slot] = {
            "message_id": message_id,
            "chat_id": str(target["chat_id"]),
            "verified_at_hkt": verified_at,
            "readback_verified": True,
        }
        save_json(state_path, state)
    return {"ok": True, "mode": mode, "message_id": message_id, "markdown": markdown}


def due_slots(now: datetime, state: dict[str, Any]) -> list[tuple[str, datetime]]:
    sent = state.get("sent_slots") or {}
    result = []
    for hour in (10, 17):
        scheduled = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        slot = scheduled.strftime("%Y%m%d-%H00")
        if scheduled <= now and slot not in sent:
            result.append((slot, scheduled))
    return result


def daemon(config_path: Path, state_path: Path) -> None:
    while True:
        now = datetime.now(HKT)
        state = load_json(state_path, {}) or {}
        for slot, scheduled in due_slots(now, state):
            if now - scheduled <= timedelta(hours=12):
                execute(config_path, state_path, "group", slot=slot)
                state = load_json(state_path, {}) or {}
        time.sleep(30)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--send-preview", action="store_true")
    modes.add_argument("--send-group", action="store_true")
    modes.add_argument("--daemon", action="store_true")
    args = parser.parse_args()
    try:
        if args.daemon:
            daemon(args.config, args.state)
            return 0
        mode = "preview" if args.send_preview else "group" if args.send_group else "dry-run"
        result = execute(args.config, args.state, mode)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(json.dumps({"ok": False, "error": _safe_error(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

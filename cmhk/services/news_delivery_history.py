"""Read-only personal news delivery history; never reconstruct a sent card."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def _json(value, kind):
    try:
        parsed = json.loads(value or "null")
    except (TypeError, ValueError):
        return kind()
    return parsed if isinstance(parsed, kind) else kind()


def _hkt_day(value):
    try:
        stamp = datetime.fromisoformat(str(value))
        return stamp.astimezone(ZoneInfo("Asia/Hong_Kong")).date().isoformat() if stamp.tzinfo else stamp.date().isoformat()
    except ValueError:
        return ""


def _card_text(value):
    """Extract persisted display text without exposing card actions/configuration."""
    if isinstance(value, list):
        return [text for child in value for text in _card_text(child)]
    if not isinstance(value, dict):
        return []
    if value.get("tag") in {"markdown", "plain_text", "lark_md"}:
        return [str(value["content"])] if value.get("content") else []
    return [text for key in ("body", "elements", "columns", "text", "header", "title")
            if key in value for text in _card_text(value[key])]


def news_delivery_history(db_path: Path, *, selected_date: str = "", delivery_id: int | None = None):
    selected_date = selected_date or datetime.now(ZoneInfo("Asia/Hong_Kong")).date().isoformat()
    if selected_date != "all":
        if date.fromisoformat(selected_date).isoformat() != selected_date:
            raise ValueError("日期格式应为 YYYY-MM-DD")
    detail_fields = ", p.body, r.items_json, r.card_json, r.audit_json" if delivery_id is not None else ""
    query = """SELECT d.*, p.title, p.due_at, p.dispatched_at, p.attempts,
        p.last_error AS pending_error, c.crawl_date, c.crawl_slot,
        r.logical_day, r.status AS receipt_status, r.message_id AS receipt_message_id,
        r.updated_at AS receipt_updated_at,
        COALESCE(NULLIF(s.display_name,''),
          (SELECT NULLIF(display_name,'') FROM subscription_invite_candidates WHERE delivery_open_id=d.open_id ORDER BY updated_at DESC LIMIT 1),
          (SELECT NULLIF(display_name,'') FROM subscription_directory_people WHERE directory_open_id=d.open_id ORDER BY synced_at DESC LIMIT 1),
          (SELECT NULLIF(display_name,'') FROM subscription_invitations WHERE delivery_open_id=d.open_id ORDER BY id DESC LIMIT 1), '') AS recipient_name
        """ + detail_fields + """
        FROM deliveries d
        LEFT JOIN subscribers s ON s.open_id=d.open_id
        LEFT JOIN pending_subscription_deliveries p ON p.id=(SELECT MAX(id) FROM pending_subscription_deliveries WHERE delivery_id=d.id)
        LEFT JOIN news_crawl_dispatches c ON c.rowid=(SELECT MAX(rowid) FROM news_crawl_dispatches WHERE delivery_id=d.id)
        LEFT JOIN news_delivery_receipts r ON r.open_id=d.open_id AND r.batch_id=d.batch_id
        WHERE d.service='news'"""
    params = ()
    if delivery_id is not None:
        query += " AND d.id=?"
        params = (delivery_id,)
    query += " ORDER BY d.id DESC"
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True, timeout=10)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(query, params).fetchall()
    items = []
    for row in rows:
        raw = dict(row)
        task_date = raw.get("crawl_date") or raw.get("logical_day") or _hkt_day(raw["created_at"])
        message_ids = _json(raw["message_ids"], list)
        if raw.get("receipt_message_id") and raw["receipt_message_id"] not in message_ids:
            message_ids.append(raw["receipt_message_id"])
        status = raw["status"]
        if raw.get("receipt_status") == "verified" and message_ids:
            status = "verified"
        elif raw.get("receipt_status") == "sent" and message_ids and status != "verified":
            status = "sent"
        group = "verified" if status == "verified" else "pending" if status in {"queued", "sending", "retrying", "prepared", "sent"} else "issue"
        item = {key: raw[key] for key in ("id", "open_id", "recipient_name", "batch_id", "content_ref", "created_at", "mode")}
        item.update(task_date=task_date, status=status, status_group=group, message_ids=message_ids,
                    title=raw.get("title") or "战略新闻订阅推送", crawl_slot=raw.get("crawl_slot") or "",
                    due_at=raw.get("due_at") or "", retry_count=raw.get("attempts") or 0,
                    delivered_at=raw.get("dispatched_at") or "",
                    verified_at=raw.get("receipt_updated_at") if raw.get("receipt_status") == "verified" else "",
                    error=raw["error"] or raw.get("pending_error") or "",
                    has_receipt=bool(raw.get("receipt_status")))
        if delivery_id is not None:
            receipt_items = _json(raw.get("items_json"), list)
            card = _json(raw.get("card_json"), dict)
            audit = _json(raw.get("audit_json"), dict)
            item.update(news_items=[entry for entry in receipt_items if isinstance(entry, dict)],
                        card_text="\n\n".join(_card_text(card)),
                        content_source="receipt" if raw.get("receipt_status") else "unavailable",
                        receipt_status=raw.get("receipt_status") or "",
                        prepared_at=audit.get("prepared_at") or "",
                        input_count=audit.get("input_count"), selected_count=audit.get("selected_count"))
            if not item["has_receipt"] and raw.get("body"):
                from cmhk.services.subscriptions import _decode_strategic_news_digest
                item["news_items"] = _decode_strategic_news_digest(raw["body"])
                item["content_source"] = "candidate_archive"
        items.append(item)
    if delivery_id is not None:
        if not items:
            raise LookupError("找不到该战略新闻推送记录")
        return {"ok": True, "delivery": items[0]}
    dates = sorted({item["task_date"] for item in items if item["task_date"]}, reverse=True)
    filtered = [item for item in items if selected_date == "all" or item["task_date"] == selected_date]
    return {"ok": True, "date": selected_date, "dates": dates, "deliveries": filtered,
            "summary": {"total": len(filtered), "recipients": len({item["open_id"] for item in filtered}),
                        **{key: sum(item["status_group"] == key for item in filtered)
                           for key in ("verified", "pending", "issue")}}}

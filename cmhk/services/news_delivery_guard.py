"""Durable, per-recipient news send guard shared by automatic and manual sends."""
from __future__ import annotations

import fcntl
import hashlib
import json
from contextlib import closing
from datetime import datetime
from zoneinfo import ZoneInfo

from cmhk.services.news_delivery_dedupe import deduplicate_events


def delivered_history(db, *, open_id: str, batch_id: str, logical_day: str, send_day: str) -> list[dict]:
    from cmhk.services.subscriptions import _decode_strategic_news_digest
    items = []
    for row in db.execute(
        """SELECT items_json FROM news_delivery_receipts
           WHERE open_id=? AND batch_id<>? AND status IN ('sending','sent','verified')
             AND (logical_day=? OR send_day=?)""", (open_id, batch_id, logical_day, send_day),
    ).fetchall():
        items.extend(json.loads(row[0]))
    # Upgrade compatibility: old outbox bodies are the original sent selections.
    # Do not count future queued cards, cancelled sends, or this batch against itself.
    for row in db.execute(
        """SELECT p.body FROM pending_subscription_deliveries p
           JOIN deliveries d ON d.id=p.delivery_id
           LEFT JOIN news_crawl_dispatches c ON c.delivery_id=d.id
           WHERE p.open_id=? AND d.batch_id<>? AND d.service='news' AND d.status='verified'
             AND (c.crawl_date=? OR substr(COALESCE(NULLIF(p.dispatched_at,''),d.created_at),1,10)=?)
             AND NOT EXISTS (SELECT 1 FROM news_delivery_receipts r
                             WHERE r.open_id=d.open_id AND r.batch_id=d.batch_id)""",
        (open_id, batch_id, logical_day, send_day),
    ).fetchall():
        items.extend(_decode_strategic_news_digest(row[0]))
    return items


def deliver_news(service, *, open_id: str, content_ref: str, title: str, body: str,
                 batch_id: str, profile: str) -> list[str]:
    from cmhk.services.news_digest_editor import prepare_digest
    from cmhk.services.subscriptions import NEWS_DIGEST_PREFIX, _decode_strategic_news_digest, strategic_news_card

    lock_dir = service.db_path.parent / "news-send-locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / (hashlib.sha256(open_id.encode()).hexdigest() + ".lock")
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("该接收人的新闻正在发送，本条等待重试") from exc
        now = datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(timespec="seconds")
        send_day = now[:10]
        logical_day = content_ref[len("strategic-crawl:"):][:10] if content_ref.startswith("strategic-crawl:") else send_day
        with closing(service._connect()) as db:
            receipt = db.execute("SELECT * FROM news_delivery_receipts WHERE open_id=? AND batch_id=?",
                                 (open_id, batch_id)).fetchone()
            uncertain = db.execute(
                "SELECT 1 FROM news_delivery_receipts WHERE open_id=? AND batch_id<>? AND status='sending' LIMIT 1",
                (open_id, batch_id),
            ).fetchone()
            history = delivered_history(db, open_id=open_id, batch_id=batch_id,
                                        logical_day=logical_day, send_day=send_day)
        if receipt and receipt["message_id"]:
            # A readback failure must retry verification, never send the card again.
            service._verify_message(receipt["message_id"], profile=profile)
            with closing(service._connect()) as db, db:
                db.execute("UPDATE news_delivery_receipts SET status='verified', updated_at=? WHERE open_id=? AND batch_id=?",
                           (now, open_id, batch_id))
            return [str(receipt["message_id"])]
        if uncertain:
            raise RuntimeError("该接收人有待确认的新闻发送，请先恢复原消息回执")
        if receipt and receipt["status"] == "sending":
            # The request may have reached Feishu. Keep precisely the same content
            # and idempotency key on transport recovery, including across midnight.
            card = json.loads(receipt["card_json"])
        else:
            structured = body.startswith(NEWS_DIGEST_PREFIX)
            if structured:
                payload = json.loads(body[len(NEWS_DIGEST_PREFIX):])
                entries = payload.get("items") if isinstance(payload, dict) else payload
                if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
                    raise ValueError("新闻推送数据格式无效")
            candidates = _decode_strategic_news_digest(body) if structured else [
                {"news_id": "text:" + hashlib.sha256(body.encode()).hexdigest(), "title": body[:240], "summary": body}]
            selected, decisions = deduplicate_events(candidates, history, service.runtime_root)
            if selected and structured:
                prepared = prepare_digest(selected, service.runtime_root)
                rendered_body = NEWS_DIGEST_PREFIX + json.dumps(prepared, ensure_ascii=False)
            elif selected:
                rendered_body = body
            else:
                rendered_body = NEWS_DIGEST_PREFIX + json.dumps({"items": [], "overview": "本轮暂无未向你推送的新事件。"}, ensure_ascii=False)
            subscriptions = service.config.get("subscriptions") or {}
            image_keys = subscriptions.get("news_image_keys") or {}
            period = "afternoon" if "下午茶" in title else "morning" if "早茶" in title else ""
            card = strategic_news_card(title=title, body=rendered_body, image_key=str(image_keys.get(period) or ""))
            with closing(service._connect()) as db, db:
                db.execute(
                    """INSERT INTO news_delivery_receipts(open_id,batch_id,logical_day,send_day,items_json,
                           card_json,audit_json,status,message_id,updated_at)
                       VALUES(?,?,?,?,?,?,?,'prepared','',?)
                       ON CONFLICT(open_id,batch_id) DO UPDATE SET send_day=excluded.send_day,
                           items_json=excluded.items_json,card_json=excluded.card_json,audit_json=excluded.audit_json,
                           status='prepared',updated_at=excluded.updated_at""",
                    (open_id, batch_id, logical_day, send_day, json.dumps(selected, ensure_ascii=False),
                     json.dumps(card, ensure_ascii=False), json.dumps({"input_count": len(candidates),
                     "selected_count": len(selected), "history_count": len(history), "decisions": decisions}, ensure_ascii=False), now),
                )
        with closing(service._connect()) as db, db:
            db.execute("UPDATE news_delivery_receipts SET status='sending',updated_at=? WHERE open_id=? AND batch_id=?",
                       (now, open_id, batch_id))
        message_id = service._send_interactive_card(open_id, card, idempotency_key=f"{batch_id}-n-{open_id[-6:]}",
                                                    profile=profile, preserve_markdown_bold=True)
        # Persist the external receipt before any fallible readback operation.
        sent_at = datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(timespec="seconds")
        with closing(service._connect()) as db, db:
            db.execute("UPDATE news_delivery_receipts SET status='sent',message_id=?,send_day=?,updated_at=? WHERE open_id=? AND batch_id=?",
                       (message_id, sent_at[:10], sent_at, open_id, batch_id))
        service._verify_message(message_id, profile=profile)
        with closing(service._connect()) as db, db:
            db.execute("UPDATE news_delivery_receipts SET status='verified',updated_at=? WHERE open_id=? AND batch_id=?",
                       (now, open_id, batch_id))
        return [message_id]

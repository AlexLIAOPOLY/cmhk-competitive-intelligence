"""Durable, per-recipient news send guard shared by automatic and manual sends."""
from __future__ import annotations

import fcntl
import hashlib
import json
import time
from contextlib import closing
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from cmhk.services.news_delivery_dedupe import VERSION as DEDUPE_VERSION, deduplicate_events, exact_unique
from cmhk.services.news_digest_editor import EDITOR_VERSION
from cmhk.services.news_summary_quality import VERSION as SUMMARY_VERSION
from cmhk.services.news_delivery_assets import prepare_news_assets
from cmhk.services.news_image_quality import policy_key, require_reviewed_images
from cmhk.services.news_push_skill import TEMPLATE_VERSION, skill_contract, text_model
from cmhk.services.news_delivery_selection import POLICY_VERSION, original_crawl_pool, select_recent_news


class NewsNotPrepared(RuntimeError):
    """The sending lane must never wait for model work."""


def preparation_key(*, body: str, title: str, history: list[dict], send_day: str, context: str = "") -> str:
    encoded = json.dumps([POLICY_VERSION, DEDUPE_VERSION, EDITOR_VERSION, SUMMARY_VERSION, text_model(), TEMPLATE_VERSION, policy_key(), skill_contract()[1], context, body, title, send_day, sorted(
        json.dumps(item, ensure_ascii=False, sort_keys=True) for item in history
    )], ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def recipient_contract(service, open_id: str, profile: str) -> str:
    with closing(service._connect()) as db:
        recipient = db.execute('SELECT news_categories,news_item_limit,frequency,news_delivery_times '
                               'FROM subscribers WHERE open_id=?', (open_id,)).fetchone()
    return json.dumps([profile, dict(recipient) if recipient else {},
                       (service.config.get('subscriptions') or {}).get('news_image_keys') or {}],
                      ensure_ascii=False, sort_keys=True)


def prepared_for(service, row, *, send_day: str) -> bool:
    """Check persisted readiness without calling AI or sending anything."""
    with closing(service._connect()) as db:
        receipt = db.execute("SELECT * FROM news_delivery_receipts WHERE open_id=? AND batch_id=?",
                             (row['open_id'], row['batch_id'])).fetchone()
        if not receipt:
            return False
        if receipt['message_id'] or receipt['status'] == 'sending':
            return True  # Recover the original external request, never rebuild it.
        if receipt['status'] != 'prepared':
            return False
        history = delivered_history(db, open_id=row['open_id'], batch_id=row['batch_id'],
                                    logical_day=receipt['logical_day'], send_day=send_day)
    key = preparation_key(body=row['body'], title=row['title'], history=history, send_day=send_day,
                          context=recipient_contract(service, row['open_id'], service.delivery_profile))
    try:
        return json.loads(receipt['audit_json']).get('preparation_key') == key
    except (ValueError, TypeError, AttributeError):
        return False


def delivered_history(db, *, open_id: str, batch_id: str, logical_day: str, send_day: str) -> list[dict]:
    from cmhk.services.subscriptions import _decode_strategic_news_digest
    items = []
    first_day = (date.fromisoformat(send_day) - timedelta(days=2)).isoformat()
    for row in db.execute(
        """SELECT items_json, audit_json FROM news_delivery_receipts
           WHERE open_id=? AND batch_id<>? AND status IN ('sending','sent','verified')
             AND (logical_day=? OR send_day BETWEEN ? AND ?)""",
        (open_id, batch_id, logical_day, first_day, send_day),
    ).fetchall():
        entries = json.loads(row[0])
        assets = {asset.get('news_id'): asset for asset in json.loads(row[1]).get('assets', [])
                  if asset.get('news_id')}
        # Older receipts already archived resolved URLs in their asset audit.
        # Recover those aliases read-only without touching any sent messages.
        entries = [{**item, **({'news_url': assets[item['news_id']]['news_url']}
                   if assets.get(item.get('news_id'), {}).get('news_url') else {})} for item in entries]
        items.extend(entries)
    # Upgrade compatibility: old outbox bodies are the original sent selections.
    # Do not count future queued cards, cancelled sends, or this batch against itself.
    for row in db.execute(
        """SELECT p.body FROM pending_subscription_deliveries p
           JOIN deliveries d ON d.id=p.delivery_id
           LEFT JOIN news_crawl_dispatches c ON c.delivery_id=d.id
           WHERE p.open_id=? AND d.batch_id<>? AND d.service='news' AND d.status='verified'
             AND (c.crawl_date=? OR substr(COALESCE(NULLIF(p.dispatched_at,''),d.created_at),1,10) BETWEEN ? AND ?)
             AND NOT EXISTS (SELECT 1 FROM news_delivery_receipts r
                             WHERE r.open_id=d.open_id AND r.batch_id=d.batch_id)""",
        (open_id, batch_id, logical_day, first_day, send_day),
    ).fetchall():
        items.extend(_decode_strategic_news_digest(row[0]))
    return items


def build_card_pages(*, title: str, items: list[dict], banner: str) -> dict:
    from cmhk.services.subscriptions import NEWS_DIGEST_PREFIX, strategic_news_card
    require_reviewed_images(items, banner)
    groups = [items[start:start + 10] for start in range(0, len(items), 10)] or [[]]
    while True:
        pages = []
        for index, group in enumerate(groups):
            label = title if len(groups) == 1 else f'{title}（{index + 1}/{len(groups)}）'
            page = strategic_news_card(title=label, body=NEWS_DIGEST_PREFIX + json.dumps({'items': group}, ensure_ascii=False), image_key=banner)
            if len(json.dumps(page, ensure_ascii=False, separators=(',', ':')).encode()) > 30000:
                if len(group) < 2:
                    raise ValueError('单条新闻超过卡片大小上限，保留批次重试')
                middle = len(group) // 2
                groups[index:index + 1] = [group[:middle], group[middle:]]
                break
            pages.append(page)
        else:
            return pages[0] if len(pages) == 1 else {'cards': pages}


def deliver_news(service, *, open_id: str, content_ref: str, title: str, body: str,
                 batch_id: str, profile: str, prepare_only: bool = False,
                 prepared_only: bool = False) -> list[str]:
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
            if prepare_only:
                return []
            # A readback failure must retry verification, never send the card again.
            message_ids = json.loads(receipt['audit_json']).get('message_ids') or [str(receipt['message_id'])]
            for message_id in message_ids:
                service._verify_message(message_id, profile=profile)
            with closing(service._connect()) as db, db:
                db.execute("UPDATE news_delivery_receipts SET status='verified', updated_at=? WHERE open_id=? AND batch_id=?",
                           (now, open_id, batch_id))
            return message_ids
        if uncertain:
            raise RuntimeError("该接收人有待确认的新闻发送，请先恢复原消息回执")
        key = preparation_key(body=body, title=title, history=history, send_day=send_day,
                              context=recipient_contract(service, open_id, profile))
        ready = (receipt and receipt['status'] == 'prepared'
                 and json.loads(receipt['audit_json']).get('preparation_key') == key)
        if receipt and (receipt["status"] == "sending" or ready):
            # The request may have reached Feishu. Keep precisely the same content
            # and idempotency key on transport recovery, including across midnight.
            card = json.loads(receipt["card_json"])
        else:
            if prepared_only:
                raise NewsNotPrepared("新闻卡片尚未准备完成，后台继续整理，完成后立即补发")
            structured = body.startswith(NEWS_DIGEST_PREFIX)
            if structured:
                payload = json.loads(body[len(NEWS_DIGEST_PREFIX):])
                entries = payload.get("items") if isinstance(payload, dict) else payload
                if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
                    raise ValueError("新闻推送数据格式无效")
            candidates = _decode_strategic_news_digest(body) if structured else [
                {"news_id": "text:" + hashlib.sha256(body.encode()).hexdigest(), "title": body[:240], "summary": body}]
            input_count = len(candidates)
            replacements = []
            if structured:
                with closing(service._connect()) as db:
                    subscriber = db.execute(
                        "SELECT news_categories,news_item_limit FROM subscribers WHERE open_id=?",
                        (open_id,),
                    ).fetchone()
                    # A prepared old card may have picked only exhausted sections.
                    # Re-select from the original reviewed pool, never a later batch.
                    candidates = candidates + original_crawl_pool(db, content_ref)
                categories = subscriber['news_categories'] if subscriber else list({item.get('category') for item in candidates})
                wanted_count = int(subscriber['news_item_limit']) if subscriber else len(candidates)
                pool = candidates
                candidates = select_recent_news(
                    pool, categories, limit=wanted_count,
                    history=history, send_day=send_day, seed=f"{open_id}:{logical_day}:{content_ref}",
                )
                replacements = select_recent_news(
                    pool, categories, limit=min(60, wanted_count * 3),
                    history=history, send_day=send_day, seed=f"{open_id}:{logical_day}:{content_ref}",
                )
            selected, decisions = deduplicate_events(candidates, history, service.runtime_root)
            subscriptions = service.config.get('subscriptions') or {}
            image_keys = subscriptions.get('news_image_keys') or {}
            period = 'afternoon' if '下午茶' in title else 'morning'
            banner = str(image_keys.get(period) or '')
            prepared_items = []
            summary_reviews = []
            preparation_issues = []
            if selected and structured:
                from cmhk.services.news_delivery_assets import save
                progress_path = service.db_path.parent / 'news-preparation-progress' / (hashlib.sha256(
                    f'{open_id}:{batch_id}'.encode()).hexdigest() + '.json')
                original_selected = list(selected)
                delivered_selected = []
                wanted = min(wanted_count, len(original_selected))
                tried = set()
                for item in [*original_selected, *replacements]:
                    identity = item.get('news_id') or item.get('source_url') or item.get('title')
                    if identity in tried:
                        continue
                    tried.add(identity)
                    if len(prepared_items) >= wanted:
                        break
                    stage = 'assets'
                    started = time.time()
                    try:
                        # Replacements use the same reviewed round/preferences
                        # and must pass semantic history checks too.
                        if item not in original_selected:
                            checked, extra = deduplicate_events([item], history + prepared_items, service.runtime_root)
                            decisions.extend(extra)
                            if not checked:
                                continue
                        asset = prepare_news_assets([item], service, profile=profile, fallback_image_key=banner)[0]
                        if not exact_unique([asset], history + prepared_items):
                            continue
                        stage = 'summary'
                        prepared = prepare_digest([asset], service.runtime_root)
                        prepared_items.extend(prepared['items'])
                        delivered_selected.append(item)
                        summary_reviews.extend(prepared.get('summary_reviews', []))
                    except Exception as exc:
                        # The 2026-09-12 recovery policy permits replacement or
                        # fewer reviewed stories, never fabricated text/images.
                        preparation_issues.append({'news_id': identity, 'title': item.get('title'),
                            'stage': stage, 'error_type': type(exc).__name__, 'error': str(exc)[:500],
                            'elapsed_seconds': round(time.time() - started, 1)})
                    save(progress_path, {'batch_id': batch_id, 'content_ref': content_ref,
                        'model': text_model(), 'prepared_count': len(prepared_items), 'target_count': wanted,
                        'updated_at': datetime.now(ZoneInfo('Asia/Hong_Kong')).isoformat(timespec='seconds'),
                        'issues': preparation_issues})
                if not prepared_items and preparation_issues:
                    raise NewsNotPrepared('本轮新闻暂无完成审核的图文，原批次保留：' + preparation_issues[-1]['error'])
                # Only actually delivered stories enter recipient history.
                selected = delivered_selected
                rendered_body = NEWS_DIGEST_PREFIX + json.dumps({'items': prepared_items}, ensure_ascii=False)
            elif selected:
                rendered_body = body
            else:
                rendered_body = NEWS_DIGEST_PREFIX + json.dumps({'items': []}, ensure_ascii=False)
            card = (build_card_pages(title=title, items=prepared_items, banner=banner) if structured
                    else strategic_news_card(title=title, body=rendered_body, image_key=banner))
            prepared_at = datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(timespec="seconds")
            with closing(service._connect()) as db, db:
                db.execute(
                    """INSERT INTO news_delivery_receipts(open_id,batch_id,logical_day,send_day,items_json,
                           card_json,audit_json,status,message_id,updated_at)
                       VALUES(?,?,?,?,?,?,?,'prepared','',?)
                       ON CONFLICT(open_id,batch_id) DO UPDATE SET send_day=excluded.send_day,
                           items_json=excluded.items_json,card_json=excluded.card_json,audit_json=excluded.audit_json,
                           status='prepared',updated_at=excluded.updated_at""",
                    (open_id, batch_id, logical_day, send_day, json.dumps(selected, ensure_ascii=False),
                     json.dumps(card, ensure_ascii=False), json.dumps({"input_count": input_count, "eligible_count": len(candidates),
                     "selection_policy": POLICY_VERSION, "template_version": TEMPLATE_VERSION,
                     "editor_version": EDITOR_VERSION, "summary_policy": SUMMARY_VERSION,
                     "summary_reviews": summary_reviews,
                     "preparation_issues": preparation_issues, "text_model": text_model(),
                     "skill_hash": skill_contract()[1],
                     "assets": [{k: item.get(k) for k in ("news_id", "news_url", "image_key", "image_kind",
                         "image_source_url", "image_page_url", "image_sha256", "image_policy_key",
                         "image_review_status", "image_review")} for item in prepared_items],
                     "selected_count": len(selected), "history_count": len(history), "decisions": decisions,
                     "preparation_key": key, "prepared_at": prepared_at}, ensure_ascii=False), prepared_at),
                )
        if prepare_only:
            return []
        with closing(service._connect()) as db, db:
            db.execute("UPDATE news_delivery_receipts SET status='sending',updated_at=? WHERE open_id=? AND batch_id=?",
                       (now, open_id, batch_id))
        pages = card.get('cards') or [card]
        with closing(service._connect()) as db:
            audit = json.loads(db.execute('SELECT audit_json FROM news_delivery_receipts WHERE open_id=? AND batch_id=?',
                                         (open_id, batch_id)).fetchone()[0])
        message_ids = audit.get('message_ids') or []
        for index, page in enumerate(pages):
            if index < len(message_ids):
                continue
            # Keep the historic first-page key, and distinct short keys thereafter.
            token = f'{batch_id}-n-{open_id[-6:]}' if index == 0 else hashlib.sha256(
                f'{batch_id}:{open_id}:page:{index}'.encode()).hexdigest()[:40]
            message_id = service._send_interactive_card(open_id, page, idempotency_key=token,
                                                       profile=profile, preserve_markdown_bold=True)
            message_ids.append(message_id)
            audit['message_ids'] = message_ids
            with closing(service._connect()) as db, db:
                db.execute('UPDATE news_delivery_receipts SET audit_json=?,updated_at=? WHERE open_id=? AND batch_id=?',
                           (json.dumps(audit, ensure_ascii=False), now, open_id, batch_id))
        # Persist all external receipts before any fallible readback operation.
        sent_at = datetime.now(ZoneInfo('Asia/Hong_Kong')).isoformat(timespec='seconds')
        with closing(service._connect()) as db, db:
            db.execute("UPDATE news_delivery_receipts SET status='sent',message_id=?,send_day=?,updated_at=? WHERE open_id=? AND batch_id=?",
                       (message_ids[0], sent_at[:10], sent_at, open_id, batch_id))
        for message_id in message_ids:
            service._verify_message(message_id, profile=profile)
        with closing(service._connect()) as db, db:
            db.execute("UPDATE news_delivery_receipts SET status='verified',updated_at=? WHERE open_id=? AND batch_id=?",
                       (now, open_id, batch_id))
        return message_ids

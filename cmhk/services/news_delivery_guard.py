"""Durable, per-recipient news send guard shared by automatic and manual sends."""
from __future__ import annotations

import fcntl
import hashlib
import json
import time
from contextlib import closing
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from cmhk.services.news_delivery_dedupe import VERSION as DEDUPE_VERSION, deduplicate_for_delivery as deduplicate_events, exact_unique
from cmhk.services.news_digest_editor import EDITOR_VERSION
from cmhk.services.news_summary_quality import VERSION as SUMMARY_VERSION, MAX_SUMMARY_CHARS, SummaryQualityError, repeats_title
from cmhk.services.news_delivery_assets import prepare_news_assets
from cmhk.services.news_image_quality import policy_key, require_reviewed_images
from cmhk.services.news_push_skill import TEMPLATE_VERSION, skill_contract, text_model
from cmhk.services.news_preparation_budget import bounded_preparation, candidate_budget, expired
from cmhk.services.news_text import simplified_news_text
from cmhk.services.news_round_progress import excluded_items, remaining_count, record_attempt, item_key, finish_without_card, stopped_reason
from cmhk.services.news_delivery_selection import POLICY_VERSION, original_crawl_pool, select_recent_news, prioritize_preparation


class NewsNotPrepared(RuntimeError):
    """The sending lane must never wait for model work."""


class NewsRoundStopped(RuntimeError):
    """The user stopped this original round, including manual recovery."""


def require_active_round(service, content_ref):
    with closing(service._connect()) as db:
        reason = stopped_reason(db, content_ref)
    if reason:
        raise NewsRoundStopped(reason)


def preparation_key(*, body: str, title: str, history: list[dict], send_day: str, context: str = "") -> str:
    encoded = json.dumps([POLICY_VERSION, DEDUPE_VERSION, EDITOR_VERSION, SUMMARY_VERSION, text_model(), TEMPLATE_VERSION, policy_key(), skill_contract()[1], context, body, title, send_day, sorted(
        json.dumps(item, ensure_ascii=False, sort_keys=True) for item in history
    )], ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def recipient_contract(service, open_id: str, profile: str) -> str:
    with closing(service._connect()) as db:
        recipient = db.execute('SELECT news_categories,news_item_limit,news_region_preference,news_topics,frequency,news_delivery_times '
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


def needs_more_preparation(service, row):
    with closing(service._connect()) as db:
        receipt = db.execute("SELECT audit_json FROM news_delivery_receipts WHERE open_id=? AND batch_id=? AND status='prepared'",
                             (row['open_id'], row['batch_id'])).fetchone()
    try:
        return bool(receipt and json.loads(receipt[0]).get('can_prepare_more'))
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
    for item in items:
        summary = simplified_news_text(item.get('digest_summary') or item.get('summary')).strip()
        if not summary or len(summary) > MAX_SUMMARY_CHARS or repeats_title(item.get('title', ''), summary):
            raise SummaryQualityError('待发简介超100字或重复标题，需要重新生成或换稿')
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


@bounded_preparation
def deliver_news(service, *, open_id: str, content_ref: str, title: str, body: str,
                 batch_id: str, profile: str, prepare_only: bool = False,
                 prepared_only: bool = False, continue_preparation: bool = False) -> list[str]:
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
        require_active_round(service, content_ref)
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
        if receipt and (receipt["status"] == "sending" or (ready and not (prepare_only and continue_preparation))):
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
                        "SELECT news_categories,news_item_limit,news_region_preference,news_topics FROM subscribers WHERE open_id=?",
                        (open_id,),
                    ).fetchone()
                    # A prepared old card may have picked only exhausted sections.
                    # Re-select from the original reviewed pool, never a later batch.
                    candidates = candidates + original_crawl_pool(db, content_ref)
                    exhausted = excluded_items(db, open_id, content_ref)
                    attempts = {r[0]: r[1] for r in db.execute(
                        'SELECT item_key,attempts FROM news_candidate_attempts WHERE open_id=? AND content_ref=?',
                        (open_id, content_ref))}
                    candidates = [item for item in candidates if item_key(item) not in exhausted]
                    requested_count = int(subscriber['news_item_limit']) if subscriber else len(candidates)
                    wanted_count = remaining_count(db, open_id, content_ref, requested_count)
                categories = subscriber['news_categories'] if subscriber else list({item.get('category') for item in candidates})
                pool = candidates
                replacements = select_recent_news(
                    pool, categories, region_preference=subscriber["news_region_preference"] if subscriber else None, limit=500,
                    history=history, send_day=send_day, seed=f"{open_id}:{logical_day}:{content_ref}",
                    topics=subscriber["news_topics"] if subscriber else None,
                )
                replacements = prioritize_preparation(replacements, runtime_root=service.runtime_root, attempts=attempts)
                candidates = replacements[:wanted_count]
            selected, decisions = deduplicate_events(candidates, history, service.runtime_root)
            kept_keys = {item_key(item) for item in selected}
            review_errors = {str(row.get('news_id')): row for row in decisions if row.get('status') == 'skipped_review_error'}
            for item in candidates:
                if item_key(item) not in kept_keys:
                    failure = review_errors.get(item_key(item))
                    record_attempt(service, open_id, content_ref, item,
                                   error=(f"事件去重审核失败: {failure.get('error_type', '')}: {failure.get('error', '')}"
                                          if failure else '与已发或同卡事件重复'), duplicate=failure is None)
            subscriptions = service.config.get('subscriptions') or {}
            image_keys = subscriptions.get('news_image_keys') or {}
            period = 'afternoon' if '下午茶' in title else 'morning'
            banner = str(image_keys.get(period) or '')
            prepared_items = []
            summary_reviews = []
            can_prepare_more = False
            preparation_issues = [row for row in decisions if row.get('status') == 'skipped_review_error']
            if structured:
                from cmhk.services.news_delivery_assets import save
                progress_path = service.db_path.parent / 'news-preparation-progress' / (hashlib.sha256(
                    f'{open_id}:{batch_id}'.encode()).hexdigest() + '.json')
                original_selected = list(selected)
                delivered_selected = []
                wanted = wanted_count
                tried = {row.get('news_id') for row in preparation_issues}
                for item in [*original_selected, *replacements]:
                    identity = item.get('news_id') or item.get('source_url') or item.get('title')
                    if identity in tried:
                        continue
                    if len(prepared_items) >= wanted or expired():
                        break
                    tried.add(identity)
                    stage = 'assets'
                    started = time.time()
                    try:
                        with candidate_budget():
                            # Replacements use the same reviewed round/preferences
                            # and must pass semantic history checks too.
                            if item not in original_selected:
                                checked, extra = deduplicate_events([item], history + prepared_items, service.runtime_root)
                                decisions.extend(extra)
                                if not checked:
                                    failures = [r for r in extra if r.get('status') == 'skipped_review_error']
                                    record_attempt(service, open_id, content_ref, item,
                                        error=('补选事件去重审核失败: ' + '; '.join(
                                            f"{r.get('error_type', '')}: {r.get('error', '')}" for r in failures)
                                            if failures else '补选事件与已发或同卡事件重复'), duplicate=not failures)
                                    continue
                            asset = prepare_news_assets([item], service, profile=profile, fallback_image_key=banner)[0]
                            if not exact_unique([asset], history + prepared_items):
                                record_attempt(service, open_id, content_ref, item, error='原文地址与已发重复', duplicate=True)
                                continue
                            stage = 'summary'
                            prepared = prepare_digest([asset], service.runtime_root)
                            prepared_items.extend(prepared['items'])
                            delivered_selected.append(item)
                            summary_reviews.extend(prepared.get('summary_reviews', []))
                    except Exception as exc:
                        record_attempt(service, open_id, content_ref, item, error=f'{stage}: {type(exc).__name__}: {exc}')
                        # The 2026-09-12 recovery policy permits replacement or
                        # fewer reviewed stories, never fabricated text/images.
                        preparation_issues.append({'news_id': identity, 'title': item.get('title'),
                            'stage': stage, 'error_type': type(exc).__name__, 'error': str(exc)[:500],
                            'elapsed_seconds': round(time.time() - started, 1)})
                    save(progress_path, {'batch_id': batch_id, 'content_ref': content_ref,
                        'model': text_model(), 'prepared_count': len(prepared_items), 'target_count': wanted,
                        'updated_at': datetime.now(ZoneInfo('Asia/Hong_Kong')).isoformat(timespec='seconds'),
                        'issues': preparation_issues})
                if not prepared_items:
                    with closing(service._connect()) as db:
                        excluded = excluded_items(db, open_id, content_ref)
                    retryable = [i for i in replacements if item_key(i) not in excluded]
                    if (preparation_issues or expired()) and retryable and wanted_count:
                        raise NewsNotPrepared('原轮次仍有候选，继续补选：' + (preparation_issues[-1].get('error', '审核失败') if preparation_issues else '本次准备预算已用完'))
                    finish_without_card(service, open_id, content_ref, batch_id,
                                        '原批次暂无更多合格新事件；保存真实缺额，未发送空卡')
                    return []
                # Only actually delivered stories enter recipient history.
                selected = delivered_selected
                with closing(service._connect()) as db:
                    excluded = excluded_items(db, open_id, content_ref)
                done = {item_key(i) for i in selected}
                can_prepare_more = len(selected) < wanted_count and any(
                    item_key(i) not in excluded | done for i in replacements)
                # A retry that hits a temporary outage must not shrink an
                # unchanged, still-valid prepared card before its due time.
                if ready and continue_preparation and len(selected) < len(json.loads(receipt['items_json'])):
                    return []
                rendered_body = NEWS_DIGEST_PREFIX + json.dumps({'items': prepared_items}, ensure_ascii=False)
            elif selected:
                rendered_body = body
            else:
                rendered_body = NEWS_DIGEST_PREFIX + json.dumps({'items': []}, ensure_ascii=False)
            card = (build_card_pages(title=title, items=prepared_items, banner=banner) if structured
                    else strategic_news_card(title=title, body=rendered_body, image_key=banner))
            prepared_at = datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(timespec="seconds")
            require_active_round(service, content_ref)
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
                     "requested_count": requested_count if structured else input_count, "remaining_target": wanted_count if structured else input_count,
                     "can_prepare_more": can_prepare_more,
                     "slice_budget_exhausted": expired(), "selected_count": len(selected), "history_count": len(history), "decisions": decisions,
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
            require_active_round(service, content_ref)
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

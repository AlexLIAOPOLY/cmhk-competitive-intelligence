"""Count actual deliveries per reviewed round and resume shortages durably."""
from __future__ import annotations
import json
from contextlib import closing
from datetime import datetime

from cmhk.services.news_delivery_dedupe import exact_unique
from cmhk.services.news_delivery_selection import original_crawl_pool, select_recent_news

MAX_CANDIDATE_ATTEMPTS = 2
CONSOLIDATED_DELIVERY_REASON = '本轮已集中发送，不再连续补发；未满足条数保留为真实缺额'


def previously_sent_round(db, open_id, content_ref, batch_id=''):
    if not content_ref.startswith('strategic-crawl:'):
        return False
    return db.execute('''SELECT 1 FROM news_delivery_receipts r JOIN deliveries d
        ON d.open_id=r.open_id AND d.batch_id=r.batch_id
        WHERE d.open_id=? AND d.content_ref=? AND d.batch_id<>?
        AND r.status IN ('sent','verified') LIMIT 1''', (open_id,content_ref,batch_id)).fetchone() is not None


def cancel_unsent_supplements(db, open_id, content_ref, stamp):
    # Keep uncertain or partially sent original requests available for receipt
    # recovery. Only wholly unsent follow-up batches are cancelled.
    pending = db.execute('''SELECT p.id,p.delivery_id FROM pending_subscription_deliveries p
        JOIN deliveries d ON d.id=p.delivery_id LEFT JOIN news_delivery_receipts r
        ON r.open_id=d.open_id AND r.batch_id=d.batch_id
        WHERE p.open_id=? AND p.content_ref=? AND p.status='queued'
        AND (r.status IS NULL OR r.status NOT IN ('sending','sent','verified'))''',
        (open_id,content_ref)).fetchall()
    for row in pending:
        db.execute("UPDATE pending_subscription_deliveries SET status='cancelled',last_error=?,dispatched_at=? WHERE id=?",
                   (CONSOLIDATED_DELIVERY_REASON,stamp,row[0]))
        db.execute("UPDATE deliveries SET status='cancelled',error=? WHERE id=?",(CONSOLIDATED_DELIVERY_REASON,row[1]))


def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS news_round_controls (
            content_ref TEXT PRIMARY KEY, status TEXT NOT NULL,
            reason TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS news_candidate_attempts (
            open_id TEXT NOT NULL, content_ref TEXT NOT NULL, item_key TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, error TEXT NOT NULL,
            updated_at TEXT NOT NULL, PRIMARY KEY(open_id, content_ref, item_key));
        CREATE TABLE IF NOT EXISTS news_round_progress (
            open_id TEXT NOT NULL, content_ref TEXT NOT NULL, requested_count INTEGER NOT NULL,
            delivered_count INTEGER NOT NULL, remaining_count INTEGER NOT NULL,
            status TEXT NOT NULL, detail_json TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY(open_id, content_ref));
    """)


def stopped_reason(db, content_ref):
    row = db.execute("SELECT reason FROM news_round_controls WHERE content_ref=? AND status='stopped'",
                     (content_ref,)).fetchone()
    return str(row[0]) if row else ''


def stop_round(service, content_ref, reason):
    """Persist an explicit stop for this round; later crawl slots are unaffected."""
    from cmhk.services.subscriptions import _now_hkt
    with closing(service._connect()) as db, db:
        db.execute('BEGIN IMMEDIATE')
        db.execute("INSERT INTO news_round_controls VALUES(?,'stopped',?,?) ON CONFLICT(content_ref) DO UPDATE SET status='stopped',reason=excluded.reason,updated_at=excluded.updated_at",
                   (content_ref, reason, _now_hkt()))
        recipients = [r[0] for r in db.execute('SELECT DISTINCT open_id FROM pending_subscription_deliveries WHERE content_ref=?', (content_ref,))]
        db.execute("UPDATE deliveries SET status='cancelled',error=? WHERE id IN (SELECT delivery_id FROM pending_subscription_deliveries WHERE content_ref=? AND status='queued') AND status NOT IN ('verified','sent','sending')",
                   (reason, content_ref))
        db.execute("UPDATE pending_subscription_deliveries SET status='cancelled',last_error=? WHERE content_ref=? AND status='queued'", (reason, content_ref))
    for open_id in recipients:
        reconcile_round(service, open_id, content_ref)
    return {'content_ref': content_ref, 'status': 'stopped', 'recipients': len(recipients)}


def item_key(item):
    return str(item.get('news_id') or item.get('source_url') or item.get('title') or '')


def excluded_items(db, open_id, content_ref):
    return {r[0] for r in db.execute('''SELECT item_key FROM news_candidate_attempts
        WHERE open_id=? AND content_ref=? AND (status='duplicate' OR (status='failed' AND attempts>=?))''',
        (open_id, content_ref, MAX_CANDIDATE_ATTEMPTS))}


def record_attempt(service, open_id, content_ref, item, *, error='', duplicate=False):
    from cmhk.services.subscriptions import _now_hkt
    if not content_ref.startswith('strategic-crawl:'):
        return
    transient = any(x in error.lower() for x in ('timeout', 'timed out', 'connectionerror', 'aiqueuebusy', '限流', '超时', '其他准备任务处理中', 'apikeypool', '429', 'temporarily', 'budget', '预算'))
    with closing(service._connect()) as db, db:
        db.execute('''INSERT INTO news_candidate_attempts VALUES(?,?,?,1,?,?,?)
            ON CONFLICT(open_id,content_ref,item_key) DO UPDATE SET attempts=attempts+1,
            status=excluded.status,error=excluded.error,updated_at=excluded.updated_at''',
            (open_id, content_ref, item_key(item), 'duplicate' if duplicate else 'deferred' if transient else 'failed', error[:500], _now_hkt()))


def delivered_items(db, open_id, content_ref):
    rows = db.execute('''SELECT r.items_json FROM news_delivery_receipts r
        JOIN deliveries d ON d.open_id=r.open_id AND d.batch_id=r.batch_id
        WHERE d.open_id=? AND d.content_ref=? AND r.status='verified' ''', (open_id, content_ref))
    return exact_unique([item for row in rows for item in json.loads(row[0])])


def remaining_count(db, open_id, content_ref, requested):
    if not content_ref.startswith('strategic-crawl:'):
        return requested
    return max(0, requested - len(delivered_items(db, open_id, content_ref)))


def finish_without_card(service, open_id, content_ref, batch_id, reason):
    """An exhausted selection produces a visible shortage, never an empty IM."""
    from cmhk.services.subscriptions import _now_hkt
    stamp = _now_hkt()
    with closing(service._connect()) as db, db:
        db.execute("""INSERT INTO news_delivery_receipts(open_id,batch_id,logical_day,send_day,items_json,card_json,audit_json,status,message_id,updated_at)
            VALUES(?,?,?,?, '[]','{}',?,'exhausted','',?)
            ON CONFLICT(open_id,batch_id) DO UPDATE SET items_json='[]',card_json='{}',
            audit_json=excluded.audit_json,status='exhausted',updated_at=excluded.updated_at
            WHERE news_delivery_receipts.status NOT IN ('sending','sent','verified')""",
            (open_id,batch_id,content_ref[16:26] if content_ref.startswith('strategic-crawl:') else stamp[:10],
             stamp[:10],json.dumps({'shortfall_reason':reason},ensure_ascii=False),stamp))
        db.execute("UPDATE deliveries SET status='exhausted',error=? WHERE open_id=? AND batch_id=?",
                   (reason, open_id, batch_id))
        db.execute("""UPDATE pending_subscription_deliveries SET status='exhausted',last_error=?
            WHERE delivery_id IN (SELECT id FROM deliveries WHERE open_id=? AND batch_id=?)""",
                   (reason, open_id, batch_id))
    reconcile_round(service, open_id, content_ref)


def reconcile_round(service, open_id, content_ref, *, now=None):
    """Atomic recovery after a send or restart. No AI or external calls here."""
    from cmhk.services.subscriptions import HKT
    from cmhk.services.news_delivery_guard import delivered_history
    if not content_ref.startswith('strategic-crawl:'):
        return {}
    now = (now or datetime.now(HKT)).astimezone(HKT)
    stamp = now.isoformat(timespec='seconds')
    with closing(service._connect()) as db, db:
        db.execute('BEGIN IMMEDIATE')
        stop_reason = stopped_reason(db, content_ref)
        subscriber = db.execute('''SELECT s.* FROM subscribers s JOIN subscriptions x ON x.open_id=s.open_id
            WHERE s.open_id=? AND s.status='active' AND x.service='news' AND x.active=1''', (open_id,)).fetchone()
        if not subscriber:
            return {}
        # Original date/time/frequency are kept; never turn yesterday's deficit
        # into a new morning round or send an afternoon to a once-daily reader.
        if (subscriber['frequency']=='once_daily' and content_ref.rsplit('@',1)[-1]>='12:00'):
            return {}
        original = db.execute('''SELECT p.*,d.batch_id FROM pending_subscription_deliveries p
            JOIN deliveries d ON d.id=p.delivery_id WHERE p.open_id=? AND p.content_ref=?
            ORDER BY p.id LIMIT 1''', (open_id, content_ref)).fetchone()
        if not original:
            return {}
        sent = delivered_items(db, open_id, content_ref)
        dispatch_closed = previously_sent_round(db, open_id, content_ref)
        if dispatch_closed:
            cancel_unsent_supplements(db, open_id, content_ref, stamp)
        wanted = int(subscriber['news_item_limit'])
        remaining = max(0, wanted-len(sent))
        pending = db.execute("SELECT 1 FROM pending_subscription_deliveries WHERE open_id=? AND content_ref=? AND status='queued'",
                             (open_id, content_ref)).fetchone()
        history = delivered_history(db, open_id=open_id, batch_id='', logical_day=content_ref[16:26], send_day=stamp[:10])
        excluded = excluded_items(db, open_id, content_ref)
        pool = [i for i in original_crawl_pool(db, content_ref) if item_key(i) not in excluded]
        candidates = select_recent_news(pool, subscriber['news_categories'], limit=500, history=history,
            send_day=stamp[:10], seed=f'{open_id}:{content_ref}:continuation', region_preference=subscriber['news_region_preference'], topics=subscriber['news_topics'], personal_skill=subscriber['news_personal_skill'])
        from cmhk.services.personal_news_skill import normalize_personal_skill
        points = normalize_personal_skill(subscriber['news_personal_skill'])
        if points:
            from cmhk.services.personal_news_allocator import cached_eligible
            candidates = cached_eligible(candidates, root=service.runtime_root,
                profile=service.delivery_profile, open_id=open_id, points=points)
        issues = [dict(r) for r in db.execute('''SELECT item_key,attempts,status,error FROM news_candidate_attempts
            WHERE open_id=? AND content_ref=?''', (open_id, content_ref))]
        status = ('stopped' if stop_reason else 'complete' if not remaining else
                  'closed' if dispatch_closed else 'preparing' if pending else 'exhausted')
        reason = (f'本轮已发送{len(sent)}/{wanted}条；继续准备剩余{remaining}条' if status in ('preparing','continuing')
                  else f'本轮已发送{len(sent)}/{wanted}条；当前原审核批次无更多符合兴趣、时效、去重及图文要求的候选，缺{remaining}条' if remaining
                  else f'本轮已发送{len(sent)}/{wanted}条')
        if stop_reason:
            reason = f'本轮已发送{len(sent)}/{wanted}条；{stop_reason}'
        elif dispatch_closed and remaining:
            reason = f'本轮已发送{len(sent)}/{wanted}条，缺{remaining}条；{CONSOLIDATED_DELIVERY_REASON}'
        detail = {'reason':reason,'eligible_remaining':len(candidates),'issues':issues}
        failures = [dict(r) for r in db.execute(
            "SELECT id,attempts,last_error FROM pending_subscription_deliveries WHERE open_id=? AND content_ref=? AND status='queued' AND last_error<>''",
            (open_id, content_ref))]
        if failures:
            detail['preparation_errors'] = failures
            detail['reason'] += '；准备受阻：' + failures[-1]['last_error'][:300]
        message_ids = list(dict.fromkeys(mid for r in db.execute(
            "SELECT message_ids FROM deliveries WHERE open_id=? AND content_ref=? AND status='verified'",
            (open_id,content_ref)) for mid in json.loads(r[0])))
        db.execute("""UPDATE news_crawl_dispatches SET status=?,message_ids=?,last_error=?,updated_at=?
                            WHERE open_id=? AND crawl_slot=?""", ('stopped' if stop_reason else 'verified' if not remaining else 'closed' if dispatch_closed else 'partial' if sent else 'queued' if pending or candidates else 'exhausted',
            json.dumps(message_ids),reason if remaining else '',stamp,open_id,content_ref.removeprefix('strategic-crawl:')))
        db.execute('''INSERT INTO news_round_progress VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(open_id,content_ref) DO UPDATE SET requested_count=excluded.requested_count,
            delivered_count=excluded.delivered_count,remaining_count=excluded.remaining_count,
            status=excluded.status,detail_json=excluded.detail_json,updated_at=excluded.updated_at''',
            (open_id,content_ref,wanted,len(sent),remaining,status,json.dumps(detail,ensure_ascii=False),stamp))
        return dict(open_id=open_id,content_ref=content_ref,requested_count=wanted,delivered_count=len(sent),
                    remaining_count=remaining,status=status,**detail)


def reconcile_recent_rounds(service, now=None):
    from cmhk.services.subscriptions import HKT
    now = (now or datetime.now(HKT)).astimezone(HKT)
    with closing(service._connect()) as db:
        rounds = db.execute('''SELECT DISTINCT open_id,content_ref FROM pending_subscription_deliveries
            WHERE service='news' AND substr(content_ref,17,10)=? AND status IN ('queued','verified','exhausted')''',
            (now.date().isoformat(),)).fetchall()
    return [reconcile_round(service,*row,now=now) for row in rounds]

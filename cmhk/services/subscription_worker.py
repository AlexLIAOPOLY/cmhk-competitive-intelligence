"""Prepare personal cards early and send due cards on an independent clock."""
from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from cmhk.services.news_delivery_guard import deliver_news, prepared_for
from cmhk.services.subscriptions import HKT, SubscriptionService

from cmhk.services.news_push_skill import PREPARATION_LEAD_MINUTES, TEMPLATE_VERSION, skill_contract, text_model
POLL_SECONDS = 1


class SubscriptionDeliveryWorker:
    def __init__(self, runtime_root):
        self.service = SubscriptionService(runtime_root=runtime_root)
        # Slow AI calls and slow recipients cannot occupy the sending lane.
        self.preparers = ThreadPoolExecutor(max_workers=3, thread_name_prefix="news-prepare")
        self.senders = ThreadPoolExecutor(max_workers=8, thread_name_prefix="subscription-send")
        self.preparing = {}
        self.sending = {}
        self.retry_after = {}
        self.errors = {}
        self.failure_counts = {}
        self.retry_at = {}
        try:
            previous = json.loads((self.service.db_path.parent / 'delivery-worker.json').read_text())
            self.failure_counts = {int(k): int(v) for k, v in previous.get('failure_counts', {}).items()}
            self.retry_at = {int(k): float(v) for k, v in previous.get('retry_at', {}).items()}
            self.retry_after = {k: time.monotonic() + max(0, v - time.time()) for k, v in self.retry_at.items()}
        except (OSError, ValueError, TypeError):
            pass
        self.state = {"status": "starting"}
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, name="subscription-clock", daemon=True)

    def start(self):
        self.thread.start()
        return self

    def _prepare(self, row):
        # This operation persists the exact card, without contacting Feishu IM.
        deliver_news(self.service, open_id=row['open_id'], content_ref=row['content_ref'],
                     title=row['title'], body=row['body'], batch_id=row['batch_id'],
                     profile=self.service.delivery_profile, prepare_only=True)

    def tick(self, now=None):
        now = (now or datetime.now(HKT)).astimezone(HKT)
        current = now.isoformat(timespec="seconds")
        for jobs in (self.preparing, self.sending):
            for identifier, future in list(jobs.items()):
                if future.done():
                    del jobs[identifier]
                    try:
                        future.result()
                        self.errors.pop(identifier, None)
                        self.failure_counts.pop(identifier, None)
                        self.retry_at.pop(identifier, None)
                        self.retry_after.pop(identifier, None)
                    except Exception as exc:
                        self.errors[identifier] = str(exc)[:500]
                        failures = self.failure_counts.get(identifier, 0) + 1
                        self.failure_counts[identifier] = failures
                        delay = min(300, 15 * (2 ** min(failures - 1, 5))) + random.uniform(0, 5)
                        self.retry_after[identifier] = time.monotonic() + delay
                        self.retry_at[identifier] = time.time() + delay
                        with closing(self.service._connect()) as db, db:
                            db.execute("UPDATE pending_subscription_deliveries SET attempts=attempts+1,last_error=? WHERE id=? AND status='queued'",
                                       (self.errors[identifier], identifier))
                            db.execute("UPDATE deliveries SET error=? WHERE id=(SELECT delivery_id FROM pending_subscription_deliveries WHERE id=? AND status='queued')",
                                       (self.errors[identifier], identifier))
                        logging.warning("个人新闻准备失败，保留原批次重试：id=%s %s", identifier, exc)
        with closing(self.service._connect()) as db:
            rows = [dict(row) for row in db.execute(
                """SELECT p.*, d.batch_id FROM pending_subscription_deliveries p
                   JOIN deliveries d ON d.id=p.delivery_id
                   WHERE p.status='queued' ORDER BY p.due_at,p.id""")]
        queued_ids = {row['id'] for row in rows}
        self.errors = {k: v for k, v in self.errors.items() if k in queued_ids}
        rows.sort(key=lambda row: (self.failure_counts.get(row['id'], 0), row['due_at'], row['id']))
        enabled = self.service.automatic_delivery_enabled('news')
        active = {row['open_id']: row for row in self.service._subscribers_for('news')}
        ready_count = due_count = late_unprepared = 0
        for row in rows:
            identifier = row['id']
            due = datetime.fromisoformat(row['due_at'])
            is_due = due <= now
            due_count += int(is_due)
            news = row['service'] == 'news'
            recipient = active.get(row['open_id'])
            morning_only = (news and row['content_ref'].startswith('strategic-crawl:')
                            and row['content_ref'].rsplit('@', 1)[-1] >= '12:00'
                            and recipient and recipient['frequency'] == 'once_daily')
            allowed = enabled and recipient and not morning_only
            ready = not news or prepared_for(self.service, row, send_day=now.date().isoformat())
            ready_count += int(news and ready)
            # Use all available lead time once a reviewed strategic round arrives.
            # The independent sending clock still honors each person's due_at.
            upcoming = (row['content_ref'].startswith('strategic-crawl:')
                        or due - now <= timedelta(minutes=PREPARATION_LEAD_MINUTES))
            if news and allowed and not ready and upcoming:
                late_unprepared += int(is_due)
                if (identifier not in self.preparing and identifier not in self.sending
                        and len(self.preparing) < 3
                        and self.retry_after.get(identifier, 0) <= time.monotonic()):
                    self.preparing[identifier] = self.preparers.submit(self._prepare, row)
            if (is_due and (ready or (news and not allowed))
                    and identifier not in self.sending and identifier not in self.preparing
                    and len(self.sending) < 8):
                self.sending[identifier] = self.senders.submit(
                    self.service.flush_due, pending_id=identifier, prepared_news_only=True)
        self.state = {
            'status': 'running', 'pid': os.getpid(), 'checked_at': current,
            'poll_seconds': POLL_SECONDS, 'preparation_lead_minutes': PREPARATION_LEAD_MINUTES,
            'prepare_as_soon_as_queued': True, 'template_version': TEMPLATE_VERSION, 'text_model': text_model(),
            'skill_hash': skill_contract()[1], 'queued_count': len(rows),
            'prepared_count': ready_count, 'due_count': due_count,
            'preparing_count': len(self.preparing), 'sending_count': len(self.sending),
            'deadline_unprepared_count': late_unprepared,
            'preparation_errors': dict(self.errors),
            'failure_counts': dict(self.failure_counts), 'retry_at': dict(self.retry_at),
        }
        target = self.service.db_path.parent / 'delivery-worker.json'
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.state, ensure_ascii=False, indent=2))
        temporary.replace(target)
        return self.state

    def run(self):
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception:
                logging.exception("个人新闻独立发送时钟异常")
            self.stop.wait(POLL_SECONDS)


_workers = {}
_lock = threading.Lock()


def start_subscription_worker(runtime_root: Path):
    with _lock:
        key = str(Path(runtime_root).resolve())
        worker = _workers.get(key)
        if worker is None or not worker.thread.is_alive():
            worker = SubscriptionDeliveryWorker(runtime_root).start()
            _workers[key] = worker
        return worker

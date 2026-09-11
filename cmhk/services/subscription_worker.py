"""Prepare personal cards early and send due cards on an independent clock."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from cmhk.services.news_delivery_guard import deliver_news, prepared_for
from cmhk.services.subscriptions import HKT, SubscriptionService

PREPARATION_LEAD_MINUTES = 30
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
                    except Exception as exc:
                        self.errors[identifier] = str(exc)[:500]
                        self.retry_after[identifier] = time.monotonic() + 15
                        logging.warning("个人新闻准备失败，保留原批次重试：id=%s %s", identifier, exc)
        with closing(self.service._connect()) as db:
            rows = [dict(row) for row in db.execute(
                """SELECT p.*, d.batch_id FROM pending_subscription_deliveries p
                   JOIN deliveries d ON d.id=p.delivery_id
                   WHERE p.status='queued' ORDER BY p.due_at,p.id""")]
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
            # Start on the day of delivery as soon as the reviewed crawl is queued.
            # Thirty minutes is the latest preparation window, not a reason to idle
            # for hours while already-reviewed source material is available.
            upcoming = due.date() <= now.date() or due - now <= timedelta(minutes=PREPARATION_LEAD_MINUTES)
            if news and allowed and not ready and upcoming:
                late_unprepared += int(due - now <= timedelta(minutes=PREPARATION_LEAD_MINUTES))
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
            'prepare_as_soon_as_queued': True, 'queued_count': len(rows),
            'prepared_count': ready_count, 'due_count': due_count,
            'preparing_count': len(self.preparing), 'sending_count': len(self.sending),
            'deadline_unprepared_count': late_unprepared,
            'preparation_errors': dict(self.errors),
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

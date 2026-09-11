import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import Future
from datetime import datetime
from pathlib import Path
from unittest import mock

from cmhk.services.news_delivery_dedupe import exact_unique
from cmhk.services.news_delivery_guard import deliver_news
from cmhk.services.subscription_worker import SubscriptionDeliveryWorker
from cmhk.services.subscriptions import SubscriptionService, encode_strategic_news_digest


class InlinePool:
    def submit(self, function, *args, **kwargs):
        result = Future()
        try:
            result.set_result(function(*args, **kwargs))
        except Exception as exc:
            result.set_exception(exc)
        return result


class SubscriptionClockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.service = SubscriptionService(runtime_root=self.root)
        self.service.save_subscriptions('ou_one', '甲', ['news'], frequency='twice_daily',
                                        news_delivery_times=['08:00', '18:30'])
        self.service.save_subscriptions('ou_two', '乙', ['news'], frequency='once_daily',
                                        news_delivery_times=['09:00', '18:30'])
        self.service.update_news_schedule(enabled=True)
        self.item = {'news_id': 'one', 'title': '已经审核的本轮新闻', 'category': '公司动态',
                     'published_at': '2026-09-11T05:00:00+08:00',
                     'summary': '已经完成审核的新闻事实，保留原有来源和事件日期。'}
        self.service.dispatch_news_after_crawl(crawl_slot='2026-09-11@03:00', slot_label='晨间扫描',
                                              items=[self.item], completed_at='2026-09-11T05:23:00+08:00')
        self.worker = SubscriptionDeliveryWorker(self.root)
        self.worker.preparers.shutdown()
        self.worker.senders.shutdown()
        self.worker.preparers = InlinePool()
        self.worker.senders = InlinePool()
        self.worker.service = self.service
        for target, implementation in (
            ('cmhk.services.news_delivery_guard.deduplicate_events',
             lambda items, history, root: (exact_unique(items, history), [])),
            ('cmhk.services.news_digest_editor.prepare_digest',
             lambda items, root: {'items': items, 'overview': '本轮新闻综述'}),
        ):
            patch = mock.patch(target, side_effect=implementation)
            patch.start()
            self.addCleanup(patch.stop)
        self.send = mock.patch.object(self.service, '_send_interactive_card',
                                      side_effect=lambda oid, *a, **k: 'om_' + oid).start()
        self.verify = mock.patch.object(self.service, '_verify_message').start()
        self.addCleanup(mock.patch.stopall)

    def tick(self, at):
        now = datetime.fromisoformat('2026-09-11T' + at + '+08:00')
        with mock.patch('cmhk.services.news_delivery_guard.datetime') as guard_clock, \
                mock.patch('cmhk.services.subscriptions.datetime') as send_clock:
            guard_clock.now.return_value = send_clock.now.return_value = now
            return self.worker.tick(now=now)

    def test_prepare_early_then_send_at_each_personal_time_without_ai(self):
        self.tick('05:24:00')
        self.send.assert_not_called()
        self.verify.assert_not_called()
        with sqlite3.connect(self.service.db_path) as db:
            self.assertEqual(db.execute("select count(*) from news_delivery_receipts where status='prepared'").fetchone()[0], 2)
        with mock.patch('cmhk.services.news_delivery_guard.deduplicate_events', side_effect=AssertionError('AI at send time')), \
                mock.patch('cmhk.services.news_digest_editor.prepare_digest', side_effect=AssertionError('AI at send time')):
            self.tick('07:59:59')
            self.send.assert_not_called()
            self.tick('08:00:00')
            self.assertEqual(self.send.call_count, 1)
            self.tick('08:59:59')
            self.assertEqual(self.send.call_count, 1)
            self.tick('09:00:00')
            self.assertEqual(self.send.call_count, 2)

    def test_persisted_preparation_survives_restart(self):
        self.tick('07:30:00')
        self.worker.preparing.clear()
        self.worker.service = SubscriptionService(runtime_root=self.root)
        with mock.patch.object(self.worker.service, '_send_interactive_card', self.send), \
                mock.patch.object(self.worker.service, '_verify_message', self.verify), \
                mock.patch('cmhk.services.news_digest_editor.prepare_digest', side_effect=AssertionError('restarted AI')):
            self.tick('08:00:00')
        self.assertEqual(self.send.call_count, 1)

    def test_default_due_flush_never_starts_ai_for_unprepared_card(self):
        with mock.patch('cmhk.services.news_delivery_guard.deduplicate_events') as model:
            result = self.service.flush_due(now=datetime.fromisoformat('2026-09-11T08:00:00+08:00'))
        model.assert_not_called()
        self.send.assert_not_called()
        self.assertEqual(result['retrying_count'], 1)

    def test_failed_preparation_keeps_original_batch_and_does_not_block_ready_person(self):
        self.tick('07:30:00')
        with sqlite3.connect(self.service.db_path) as db:
            db.execute("delete from news_delivery_receipts where open_id='ou_two'")
        with mock.patch('cmhk.services.news_digest_editor.prepare_digest', side_effect=TimeoutError('AI limited')):
            self.tick('08:00:00')
            self.tick('08:00:01')
        self.assertEqual(self.send.call_count, 1)
        self.assertTrue(self.worker.state['preparation_errors'])
        with sqlite3.connect(self.service.db_path) as db:
            row = db.execute("select status,content_ref,due_at from pending_subscription_deliveries where open_id='ou_two'").fetchone()
        self.assertEqual(row, ('queued', 'strategic-crawl:2026-09-11@03:00', '2026-09-11T09:00:00+08:00'))

    def test_changed_history_invalidates_preparation_before_sending(self):
        self.tick('07:30:00')
        with mock.patch('cmhk.services.news_delivery_guard.datetime') as clock:
            clock.now.return_value = datetime.fromisoformat('2026-09-11T07:40:00+08:00')
            deliver_news(self.service, open_id='ou_one', content_ref='manual', title='人工新闻',
                         body=encode_strategic_news_digest([self.item]), batch_id='manual', profile='test')
        self.tick('07:45:00')
        self.tick('08:00:00')
        with sqlite3.connect(self.service.db_path) as db:
            automatic = db.execute("select items_json from news_delivery_receipts where open_id='ou_one' and batch_id<>'manual'").fetchone()[0]
        self.assertEqual(json.loads(automatic), [])

    def test_unsubscribe_after_preparation_cancels_without_send(self):
        self.tick('07:30:00')
        self.service.save_subscriptions('ou_one', '甲', ['weekly'])
        self.tick('08:00:00')
        self.send.assert_not_called()
        with sqlite3.connect(self.service.db_path) as db:
            self.assertEqual(db.execute("select status from pending_subscription_deliveries where open_id='ou_one'").fetchone()[0], 'cancelled')

    def test_slow_ai_runs_outside_the_clock_and_sending_pool(self):
        entered, release = threading.Event(), threading.Event()
        from concurrent.futures import ThreadPoolExecutor
        self.worker.preparers = ThreadPoolExecutor(max_workers=1)
        try:
            def slow(row):
                entered.set()
                release.wait(3)
            with mock.patch.object(self.worker, '_prepare', side_effect=slow):
                self.tick('07:30:00')
                self.assertTrue(entered.wait(1))
                # The clock remains available even while an AI worker is blocked.
                self.assertEqual(self.tick('07:30:01')['checked_at'], '2026-09-11T07:30:01+08:00')
        finally:
            release.set()
            self.worker.preparers.shutdown()

    def test_one_slow_recipient_does_not_delay_another_due_card(self):
        self.tick('07:30:00')
        with sqlite3.connect(self.service.db_path) as db:
            db.execute("update pending_subscription_deliveries set due_at='2026-09-11T08:00:00+08:00'")
        from concurrent.futures import ThreadPoolExecutor
        self.worker.senders = ThreadPoolExecutor(max_workers=8)
        entered, release, second_sent = threading.Event(), threading.Event(), threading.Event()
        def send(oid, *args, **kwargs):
            if oid == 'ou_one':
                entered.set()
                release.wait(3)
            else:
                second_sent.set()
            return 'om_' + oid
        self.send.side_effect = send
        try:
            self.tick('08:00:00')
            self.assertTrue(entered.wait(1))
            self.assertTrue(second_sent.wait(1))
        finally:
            release.set()
            self.worker.senders.shutdown()


if __name__ == '__main__':
    unittest.main()

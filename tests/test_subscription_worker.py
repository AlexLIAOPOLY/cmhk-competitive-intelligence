import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import nullcontext
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
        from tests.news_push_fixtures import prepared_assets
        assets = mock.patch('cmhk.services.news_delivery_guard.prepare_news_assets', side_effect=prepared_assets)
        assets.start()
        self.addCleanup(assets.stop)
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
            guard_clock.fromisoformat.side_effect = send_clock.fromisoformat.side_effect = datetime.fromisoformat
            return self.worker.tick(now=now)

    def test_prepare_on_reviewed_batch_arrival_then_send_only_at_each_person_time(self):
        self.tick('05:24:00')
        self.tick('06:59:59')
        with sqlite3.connect(self.service.db_path) as db:
            self.assertEqual(db.execute('select count(*) from news_delivery_receipts').fetchone()[0], 2)
        self.tick('07:00:00')
        self.send.assert_not_called()
        with sqlite3.connect(self.service.db_path) as db:
            self.assertEqual(db.execute("select open_id from news_delivery_receipts where status='prepared' order by open_id").fetchall(), [('ou_one',), ('ou_two',)])
        self.tick('07:59:59')
        self.send.assert_not_called()
        # At 08:00 one person's sending lane and another's preparation coexist.
        self.tick('08:00:00')
        self.assertEqual(self.send.call_count, 1)
        with mock.patch('cmhk.services.news_digest_editor.prepare_digest', side_effect=AssertionError('AI at send time')):
            self.tick('08:59:59')
            self.assertEqual(self.send.call_count, 1)
            self.tick('09:00:00')
            self.assertEqual(self.send.call_count, 2)
        self.assertEqual(self.worker.state['preparation_lead_minutes'], 60)
        self.assertTrue(self.worker.state['prepare_as_soon_as_queued'])

    def test_persisted_preparation_survives_restart(self):
        self.tick('07:30:00')
        self.worker.preparing.clear()
        self.worker.service = SubscriptionService(runtime_root=self.root)
        with mock.patch.object(self.worker.service, '_send_interactive_card', self.send), \
                mock.patch.object(self.worker.service, '_verify_message', self.verify), \
                mock.patch('cmhk.services.news_digest_editor.prepare_digest', side_effect=AssertionError('restarted AI')):
            self.tick('08:00:00')
        self.assertEqual(self.send.call_count, 1)

    def test_partial_preparation_continues_before_due_and_sends_twenty_at_due(self):
        self.service.save_subscriptions('ou_two','乙',['weekly'])
        self.service.save_subscriptions('ou_one','甲',['news'],frequency='twice_daily',news_item_limit=20,
                                        news_categories=['公司动态'],news_delivery_times=['08:00','18:30'])
        with self.service._connect() as db, db:
            for table in ('pending_subscription_deliveries','deliveries','news_crawl_dispatches','news_crawl_item_pool'):
                db.execute('DELETE FROM '+table)
        items=[{**self.item,'news_id':str(i),'title':f'独立企业{i}公布项目',
                'source_url':f'https://example.test/{i}'} for i in range(20)]
        self.service.dispatch_news_after_crawl(crawl_slot='2026-09-11@03:00',slot_label='晨间扫描',
                                              items=items,completed_at='2026-09-11T05:23:00+08:00')
        edited=[]
        def editor(items,root):
            edited.extend(items);return {'items':items,'summary_reviews':[]}
        with mock.patch('cmhk.services.news_digest_editor.prepare_digest',side_effect=editor), \
             mock.patch('cmhk.services.news_delivery_guard.expired',side_effect=lambda:len(edited)>=6):
            self.tick('07:00:00')
        with self.service._connect() as db:
            receipt=db.execute('SELECT items_json,audit_json FROM news_delivery_receipts').fetchone()
            self.assertEqual(len(json.loads(receipt[0])),6)
            self.assertTrue(json.loads(receipt[1])['can_prepare_more'])
        self.send.assert_not_called()
        # A ready partial receipt must not idle through the remaining lead time.
        continued=[]
        def continuation_editor(items,root):
            continued.extend(items);return {'items':items,'summary_reviews':[]}
        with mock.patch('cmhk.services.news_digest_editor.prepare_digest',side_effect=continuation_editor):
            self.tick('07:10:00')
        self.tick('07:59:59')
        with self.service._connect() as db:
            self.assertEqual(len(json.loads(db.execute('SELECT items_json FROM news_delivery_receipts').fetchone()[0])),20)
        self.assertEqual(len(edited), 6)
        self.assertEqual(len(continued), 14)
        self.assertEqual(len({item['news_id'] for item in edited + continued}), 20)
        self.send.assert_not_called()
        self.send.side_effect=['om_page1','om_page2']
        with mock.patch('cmhk.services.news_digest_editor.prepare_digest',side_effect=AssertionError('AI in send lane')):
            self.tick('08:00:00')
        self.assertEqual(self.send.call_count,2)
        with self.service._connect() as db:
            self.assertEqual(db.execute('SELECT delivered_count FROM news_round_progress').fetchone()[0],20)

    def test_new_template_rerenders_unsent_checkpoint_without_ai_or_asset_work(self):
        self.tick('07:00:00')
        with mock.patch('cmhk.services.news_delivery_guard.TEMPLATE_VERSION', 'next-version'), \
                mock.patch('cmhk.services.news_digest_editor.prepare_digest', side_effect=AssertionError('AI must not rerun')), \
                mock.patch('cmhk.services.news_delivery_guard.prepare_news_assets', side_effect=AssertionError('assets must not rerun')):
            self.tick('07:10:00')
            self.tick('07:10:01')
        with self.service._connect() as db:
            audit = json.loads(db.execute(
                "SELECT audit_json FROM news_delivery_receipts WHERE open_id='ou_one'"
            ).fetchone()[0])
        self.assertEqual(audit['template_version'], 'next-version')
        self.assertFalse(self.worker.state['preparation_errors'])
        self.send.assert_not_called()

    def test_zero_delivery_failure_is_visible_before_any_receipt_exists(self):
        from cmhk.services.news_round_progress import reconcile_recent_rounds
        with sqlite3.connect(self.service.db_path) as db:
            db.execute("UPDATE pending_subscription_deliveries SET attempts=10,last_error='个人选稿格式错误' WHERE open_id='ou_one'")
        result=reconcile_recent_rounds(self.service,datetime.fromisoformat('2026-09-11T08:30:00+08:00'))
        own=next(row for row in result if row['open_id']=='ou_one')
        self.assertEqual(own['delivered_count'],0)
        self.assertEqual(own['status'],'preparing')
        self.assertEqual(own['preparation_errors'][0]['attempts'],10)
        self.assertIn('个人选稿格式错误',own['reason'])
        self.send.assert_not_called()

    def test_partial_personal_selection_sends_valid_items_then_closes_without_supplements(self):
        from cmhk.services.personal_news_allocator import allocate_news
        from cmhk.services.news_round_progress import reconcile_recent_rounds
        points=['关注行业中的新进展。']
        self.service.save_subscriptions('ou_one','甲',['news'],news_personal_skill=points,news_item_limit=5)
        second={**self.item,'news_id':'two','title':'第二个独立候选事件'}
        def judged(context):
            return {'reader_requirements':context['reader_requirements'],'items':[
                {'id':c['id'],'decision':'prefer','score':90,'reason':'报道的具体行业进展符合当前个人阅读要求。'} for c in context['candidates']]}
        # Valid cached first story, broken remaining selection; no image or
        # summary tests are bypassed by treating the second as approved.
        allocate_news([self.item],root=self.root,profile=self.service.delivery_profile,
                      open_id='ou_one',points=points,model_call=judged)
        with sqlite3.connect(self.service.db_path) as db:
            db.execute("UPDATE pending_subscription_deliveries SET body=? WHERE open_id='ou_one'",
                       (encode_strategic_news_digest([self.item,second]),))
            db.execute("INSERT INTO news_crawl_item_pool VALUES(?,?,?,?,?,?,?)",
                       ('2026-09-11@03:00','2026-09-11','morning','two',json.dumps(second),0,'2026-09-11T05:23:00+08:00'))
        with mock.patch('cmhk.services.personal_news_allocator._model',side_effect=TimeoutError('unavailable')):
            self.tick('08:00:00');self.tick('08:00:01')
        self.assertEqual(self.send.call_count,1)
        with sqlite3.connect(self.service.db_path) as db:
            receipt=db.execute("SELECT items_json,audit_json,status FROM news_delivery_receipts WHERE open_id='ou_one'").fetchone()
        self.assertEqual([i['news_id'] for i in json.loads(receipt[0])],['one'])
        self.assertTrue(json.loads(receipt[1])['can_prepare_more'])
        self.assertEqual(receipt[2],'verified')
        progress=reconcile_recent_rounds(self.service,datetime.fromisoformat('2026-09-11T08:01:00+08:00'))
        own=next(row for row in progress if row['open_id']=='ou_one')
        self.assertEqual(own['delivered_count'],1)
        self.assertGreater(own['remaining_count'],0)
        self.assertEqual(own['status'],'closed')
        self.assertIn('不再连续补发',own['reason'])

    def test_preference_change_rebuilds_prepared_card_before_sending(self):
        self.tick('07:00:00')
        self.service.save_subscriptions('ou_one', '甲', ['news'], frequency='twice_daily',
                                        news_categories=['政策监管'], news_delivery_times=['08:00', '18:30'])
        self.tick('07:20:00')
        self.tick('08:00:00')
        with sqlite3.connect(self.service.db_path) as db:
            row = db.execute("select items_json from news_delivery_receipts where open_id='ou_one'").fetchone()
        self.assertEqual(json.loads(row[0]), [])
        self.send.assert_not_called()

    def test_late_material_prepares_immediately_then_sends_once(self):
        with mock.patch('ai_dispatch.request_context', return_value=nullcontext()) as admission:
            self.tick('08:20:00')
        self.assertIn('interactive', [call.kwargs['priority'] for call in admission.call_args_list])
        self.send.assert_not_called()
        self.tick('08:20:01')
        self.assertEqual(self.send.call_count, 1)
        self.tick('08:20:02')
        self.tick('08:20:03')
        self.assertEqual(self.send.call_count, 1)

    def test_once_daily_afternoon_queue_is_cancelled_without_preparing(self):
        with sqlite3.connect(self.service.db_path) as db:
            db.execute("update pending_subscription_deliveries set content_ref='strategic-crawl:2026-09-11@14:00',"
                       "due_at='2026-09-11T18:30:00+08:00' where open_id='ou_two'")
            db.execute("delete from pending_subscription_deliveries where open_id='ou_one'")
        with mock.patch('cmhk.services.news_delivery_guard.prepare_news_assets') as assets:
            self.tick('17:30:00')
            self.tick('18:30:00')
        assets.assert_not_called()
        self.send.assert_not_called()

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

    def test_preparation_failure_is_durable_and_restart_retains_backoff(self):
        with mock.patch.object(self.worker, '_prepare', side_effect=TimeoutError('model unavailable')):
            self.tick('07:00:00')
            self.tick('07:00:01')
        with sqlite3.connect(self.service.db_path) as db:
            rows = db.execute('select attempts,last_error,due_at from pending_subscription_deliveries order by id').fetchall()
        self.assertTrue(all(row[0] == 1 and row[1] == 'model unavailable' for row in rows))
        self.assertEqual(rows[0][2], '2026-09-11T08:00:00+08:00')
        restarted = SubscriptionDeliveryWorker(self.root)
        try:
            self.assertEqual(restarted.failure_counts, self.worker.failure_counts)
            self.assertEqual(restarted.retry_at, self.worker.retry_at)
            with mock.patch.object(restarted, '_prepare') as prepare:
                restarted.tick(datetime.fromisoformat('2026-09-11T07:00:02+08:00'))
                prepare.assert_not_called()
        finally:
            restarted.preparers.shutdown(); restarted.senders.shutdown()

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
        with sqlite3.connect(self.service.db_path) as db:
            db.execute("update pending_subscription_deliveries set due_at='2026-09-11T08:00:00+08:00'")
        self.tick('07:30:00')
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
            # Keep the simulated day in force until both background senders ran.
            with mock.patch('cmhk.services.news_delivery_guard.datetime') as guard_clock, \
                    mock.patch('cmhk.services.subscriptions.datetime') as send_clock:
                now = datetime.fromisoformat('2026-09-11T08:00:00+08:00')
                guard_clock.now.return_value = send_clock.now.return_value = now
                self.worker.tick(now=now)
                self.assertTrue(entered.wait(1))
                self.assertTrue(second_sent.wait(1))
                release.set()
                self.worker.senders.shutdown()
        finally:
            release.set()
            self.worker.senders.shutdown()


if __name__ == '__main__':
    unittest.main()

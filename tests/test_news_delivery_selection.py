import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from cmhk.services.news_delivery_dedupe import identity_keys
from cmhk.services.news_delivery_guard import delivered_history, deliver_news, prepared_for
from cmhk.services.news_delivery_selection import fresh_news, select_recent_news, prioritize_preparation, POLICY_VERSION
from cmhk.services.subscriptions import SubscriptionService, NEWS_CATEGORY_LABELS, encode_strategic_news_digest


def article(identifier, category="公司动态", published="2026-09-11T06:00:00+08:00"):
    return {"news_id": identifier, "title": identifier, "category": category,
            "published_at": published, "source_url": "https://example.test/" + identifier,
            "summary": "已审核的独立新闻事实。", "region": "香港本地"}


class SelectionTests(unittest.TestCase):
    def test_retry_rotation_preserves_alternatives_and_region_order_within_each_tier(self):
        with tempfile.TemporaryDirectory() as temp:
            items = [article('hk-timeout'), article('hk-new'),
                     {**article('global-new'), 'region': '国际/行业'}, article('hk-retry')]
            selected = prioritize_preparation(items, runtime_root=Path(temp),
                attempts={'hk-timeout': 8, 'hk-retry': 1})
        self.assertEqual([i['news_id'] for i in selected], ['hk-new', 'global-new', 'hk-retry', 'hk-timeout'])
        self.assertEqual({id(i) for i in selected}, {id(i) for i in items})

    def test_only_matching_short_reviewed_cache_is_a_preparation_hint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); directory = root / 'var/subscriptions/news-editor'
            directory.mkdir(parents=True)
            items = [article('unready'), article('long'), article('ready'), article('rejected')]
            for item in items[1:]:
                summary = '这条简介提供了原文支持的具体措施和实施范围，便于了解新闻事实。'
                if item['news_id'] == 'long': summary *= 8
                cached = {'items': [{**item, 'digest_summary': summary, 'image_key': 'img_test'}],
                          'summary_reviews': [{'accepted': item['news_id'] != 'rejected'}]}
                (directory / (item['news_id']+'.json')).write_text(json.dumps(cached))
            (directory / 'broken.json').write_text('{')
            selected = prioritize_preparation(items, runtime_root=root, attempts={})
            self.assertEqual([i['news_id'] for i in selected], ['ready', 'unready', 'long', 'rejected'])
            changed = {**items[2], 'summary': '来源证据已经改变'}
            self.assertEqual(prioritize_preparation([items[0], changed], runtime_root=root, attempts={}), [items[0], changed])

    def test_hong_kong_calendar_age_uses_publication_not_discovery(self):
        items = [article("today"), article("yesterday", published="2026-09-10"),
                 article("old", published="2026-09-09T23:59:59+08:00"),
                 article("utc", published="2026-09-09T17:00:00Z"),
                 article("future", published="2026-09-12"),
                 {**article("unknown", published=""), "search_date": "2026-09-11"},
                 article("bad", published="not-a-date")]
        self.assertEqual([x["news_id"] for x in fresh_news(items, "2026-09-11")],
                         ["today", "yesterday", "utc"])

    def test_expired_empty_sections_are_replaced_and_less_covered_sections_lead(self):
        categories = list(NEWS_CATEGORY_LABELS)
        pool = [article("fresh-" + str(i), category) for i, category in enumerate(categories[1:])]
        pool += [article("old-company", published="2026-09-04")]
        history = [article("seen-" + str(i), category) for i, category in enumerate(categories[1:3])]
        selected = select_recent_news(pool, categories, limit=10, history=history,
                                      send_day="2026-09-11", seed="rotation")
        self.assertEqual({x["category"] for x in selected}, set(categories[3:]))
        self.assertEqual(len(selected), 4)
        self.assertEqual(selected, select_recent_news(pool, categories, limit=10, history=history,
                         send_day="2026-09-11", seed="rotation"))

    def test_four_subscriptions_keep_shortfall_without_outside_items(self):
        previous = article("seen", published="2026-09-10")
        alias = {**previous, "news_id": "rewritten", "title": "different-title",
                 "source_url": previous["source_url"] + "?utm_source=repeat"}
        selected = select_recent_news([alias, article("new"), article("outside", "行业动态")],
            list(NEWS_CATEGORY_LABELS)[:3] + ["市场/产品类"], limit=10, history=[previous],
            send_day="2026-09-11")
        self.assertEqual([x["news_id"] for x in selected], ["new"])


class DeliverySelectionTests(unittest.TestCase):
    def setUp(self):
        from tests.news_push_fixtures import prepared_assets
        assets = mock.patch('cmhk.services.news_delivery_guard.prepare_news_assets', side_effect=prepared_assets)
        assets.start()
        self.addCleanup(assets.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = SubscriptionService(runtime_root=Path(self.temp.name))
        self.service.save_subscriptions("ou_test123", "测试", ["news"], frequency="twice_daily",
                                        news_categories=list(NEWS_CATEGORY_LABELS))
        self.service.update_news_schedule(enabled=True)
        self.clock = mock.patch("cmhk.services.news_delivery_guard.datetime").start()
        self.clock.now.return_value = datetime.fromisoformat("2026-09-11T08:00:00+08:00")
        mock.patch("cmhk.services.news_digest_editor.prepare_digest",
                   side_effect=lambda items, root: {"items": items, "overview": "已审核"}).start()
        mock.patch("cmhk.services.news_delivery_guard.deduplicate_events",
                   side_effect=lambda items, history, root: (items, [])).start()
        self.send = mock.patch.object(self.service, "_send_interactive_card", return_value="om_test123").start()
        mock.patch.object(self.service, "_verify_message").start()
        self.addCleanup(mock.patch.stopall)

    def seed_receipt(self, batch, day, items, status="verified"):
        with sqlite3.connect(self.service.db_path) as db:
            db.execute("""INSERT INTO news_delivery_receipts
                (open_id,batch_id,logical_day,send_day,items_json,card_json,audit_json,status,message_id,updated_at)
                VALUES('ou_test123',?,?,?,?, '{}','{}',?,'',?)""",
                (batch, day, day, json.dumps(items), status, day + "T08:00:00+08:00"))

    def test_short_history_covers_previous_two_days_and_ignores_future_queue(self):
        for day in ["08", "09", "10", "11"]:
            self.seed_receipt(day, "2026-09-" + day, [article(day)])
        self.seed_receipt("queued", "2026-09-11", [article("queued")], "prepared")
        with self.service._connect() as db:
            history = delivered_history(db, open_id="ou_test123", batch_id="11",
                                        logical_day="2026-09-11", send_day="2026-09-11")
        self.assertEqual({x["news_id"] for x in history}, {"09", "10"})

    def test_automatic_queue_rotates_before_limit_using_yesterdays_real_receipt(self):
        old = article("yesterday-sent", published="2026-09-10")
        self.seed_receipt("previous", "2026-09-10", [old])
        self.service.dispatch_news_after_crawl(crawl_slot="2026-09-11@03:00", slot_label="晨间扫描",
            completed_at="2026-09-11T06:00:00+08:00",
            items=[old, article("ancient", published="2026-09-04"), article("new-policy", "政策监管")])
        with self.service._connect() as db:
            payload = db.execute("SELECT body FROM pending_subscription_deliveries").fetchone()[0]
        self.assertIn("new-policy", payload)
        self.assertNotIn("yesterday-sent", payload)
        self.assertNotIn("ancient", payload)

    def test_old_queued_card_reselects_original_pool_and_prepare_never_sends(self):
        old = article("old", published="2026-09-09")
        fresh = article("new-policy", "政策监管")
        self.service.dispatch_news_after_crawl(crawl_slot="2026-09-11@03:00", slot_label="晨间扫描",
            completed_at="2026-09-11T06:00:00+08:00", items=[old, fresh])
        with self.service._connect() as db:
            row = dict(db.execute("SELECT p.*,d.batch_id FROM pending_subscription_deliveries p JOIN deliveries d ON d.id=p.delivery_id").fetchone())
        row["body"] = encode_strategic_news_digest([old])
        args = {k: row[k] for k in ["open_id", "content_ref", "title", "body", "batch_id"]}
        deliver_news(self.service, **args, profile=self.service.delivery_profile, prepare_only=True)
        self.send.assert_not_called()
        with self.service._connect() as db:
            receipt = db.execute("SELECT items_json,audit_json FROM news_delivery_receipts").fetchone()
        self.assertEqual([x["news_id"] for x in json.loads(receipt[0])], ["new-policy"])
        self.assertEqual(json.loads(receipt[1])["selection_policy"], POLICY_VERSION)
        self.assertTrue(prepared_for(self.service, row, send_day="2026-09-11"))
        self.assertFalse(prepared_for(self.service, row, send_day="2026-09-12"))

    def test_manual_latest_selection_checks_history_before_limit(self):
        old = article("seen", published="2026-09-10")
        self.seed_receipt("auto", "2026-09-10", [old])
        with mock.patch("cmhk.services.subscriptions._now_hkt", return_value="2026-09-11T08:00:00+08:00"):
            selected = self.service.select_personal_news([old, article("new", "行业动态")], open_id="ou_test123")
        self.assertEqual([x["news_id"] for x in selected], ["new"])

    def test_dedupe_transport_failures_keep_their_cause_and_remain_retryable(self):
        from cmhk.services.news_delivery_guard import NewsNotPrepared
        from cmhk.services.news_round_progress import excluded_items
        item = article('temporarily-busy')
        ref = 'strategic-crawl:2026-09-11@03:00'
        self.service.dispatch_news_after_crawl(crawl_slot=ref.removeprefix('strategic-crawl:'),
            slot_label='晨间扫描', completed_at='2026-09-11T06:00:00+08:00', items=[item])
        with self.service._connect() as db:
            row = dict(db.execute('SELECT p.*,d.batch_id FROM pending_subscription_deliveries p JOIN deliveries d ON d.id=p.delivery_id').fetchone())
        def busy(items, history, root):
            return [], [{'news_id': i['news_id'], 'status': 'skipped_review_error',
                         'error_type': 'AIQueueBusy', 'error': 'timed out'} for i in items]
        with mock.patch('cmhk.services.news_delivery_guard.deduplicate_events', side_effect=busy):
            for _ in range(3):
                with self.assertRaises(NewsNotPrepared):
                    deliver_news(self.service, **{k:row[k] for k in ('open_id','content_ref','title','body','batch_id')},
                                 profile=self.service.delivery_profile, prepare_only=True)
        with self.service._connect() as db:
            self.assertEqual(excluded_items(db, row['open_id'], ref), set())
            failure = db.execute('SELECT status,error FROM news_candidate_attempts').fetchone()
            self.assertEqual(failure['status'], 'deferred')
            self.assertIn('AIQueueBusy', failure['error'])
        self.send.assert_not_called()

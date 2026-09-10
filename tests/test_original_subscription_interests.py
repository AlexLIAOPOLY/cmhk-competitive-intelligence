import json
import unittest
from contextlib import closing
from cmhk.services.subscriptions import NEWS_CATEGORY_LABELS, SubscriptionService
from tests import test_subscription_service as fixtures


class OriginalInterestTests(unittest.TestCase):
    setUp = fixtures.SubscriptionServiceTests.setUp
    tearDown = fixtures.SubscriptionServiceTests.tearDown

    def test_original_choices_survive_admin_edit_and_restart(self):
        original = list(NEWS_CATEGORY_LABELS)
        saved = self.service.save_subscriptions('ou_delivery123', '测试用户', ['news'], news_categories=original)
        row = self.service.list_summary()['subscribers'][0]
        self.assertEqual(row['original_news_categories'], original)
        self.assertEqual(len(row['news_categories']), 7)
        self.service.update_subscriber('ou_delivery123', services=['news'], news_categories=['公司动态'])
        reloaded = SubscriptionService(runtime_root=self.root, command_runner=self.lark)
        row = reloaded.list_summary()['subscribers'][0]
        self.assertEqual(row['original_news_categories'], original)
        self.assertEqual(row['news_categories'], ['公司动态'])
        reloaded.save_subscriptions('ou_delivery123', '测试用户', ['news'], news_categories=['政策监管'])
        self.assertEqual(reloaded.list_summary()['subscribers'][0]['original_news_categories'], ['政策监管'])

    def test_legacy_profile_is_not_reduced_on_restart(self):
        self.service.save_subscriptions('ou_delivery123', '测试用户', ['news'])
        original = list(NEWS_CATEGORY_LABELS)
        with closing(self.service._connect()) as db, db:
            db.execute("UPDATE subscribers SET news_categories=?, original_news_categories='[]', original_news_categories_source=''", (json.dumps(original),))
        reloaded = SubscriptionService(runtime_root=self.root, command_runner=self.lark)
        row = reloaded.list_summary()['subscribers'][0]
        self.assertEqual(row['original_news_categories'], [])
        self.assertEqual(row['original_news_categories_source'], '')
        self.assertEqual(len(row['news_categories']), 7)

    def test_unknown_original_choices_are_not_inferred(self):
        self.service.save_subscriptions('ou_delivery123', '测试用户', ['news'])
        row = self.service.list_summary()['subscribers'][0]
        self.assertEqual(row['original_news_categories'], [])
        self.assertEqual(row['original_news_categories_source'], '')

    def test_dispatch_samples_per_window_without_changing_saved_choices(self):
        from datetime import datetime
        from unittest import mock
        original = list(NEWS_CATEGORY_LABELS)
        self.service.save_subscriptions('ou_delivery123', '测试用户', ['news'],
            news_categories=original, frequency='twice_daily', news_item_limit=20)
        self.service.update_news_schedule(enabled=True)
        samples = set()
        with mock.patch.object(self.service, '_deliver_one', return_value=['om_test123']) as deliver:
            for day in range(1, 5):
                for time, label, due in [('03:00', '晨间扫描', '08:00'), ('14:00', '午后扫描', '18:30')]:
                    slot = f'2099-01-{day:02}@{time}'
                    items = [
                        {'title': f'{slot}-{category}', 'category': category}
                        for category in original
                    ]
                    result = self.service.dispatch_news_after_crawl(crawl_slot=slot, slot_label=label, items=items)
                    selected = result['results'][0]['push_news_categories']
                    self.assertEqual(len(selected), 4)
                    self.assertEqual(result['results'][0]['news_categories'], original)
                    self.service.flush_due(now=datetime.fromisoformat(f'2099-01-{day:02}T{due}:00+08:00'))
                    body = json.loads(deliver.call_args.kwargs['body'].removeprefix('CMHK_NEWS_DIGEST_V1\n'))
                    self.assertEqual({item['category'] for item in body}, set(selected))
                    count = deliver.call_count
                    repeat = self.service.dispatch_news_after_crawl(crawl_slot=slot, slot_label=label, items=items)
                    self.assertEqual(repeat['skipped_count'], 1)
                    self.assertEqual(deliver.call_count, count)
                    samples.add(tuple(selected))
        self.assertGreater(len(samples), 1)
        self.assertEqual(self.service.list_summary()['subscribers'][0]['news_categories'], original)

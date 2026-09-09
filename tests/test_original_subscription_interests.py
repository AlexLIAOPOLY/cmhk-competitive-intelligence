import json
import unittest
from contextlib import closing
from cmhk.services.subscriptions import NEWS_CATEGORY_LABELS, SubscriptionService
from tests import test_subscription_service as fixtures


class OriginalInterestTests(unittest.TestCase):
    setUp = fixtures.SubscriptionServiceTests.setUp
    tearDown = fixtures.SubscriptionServiceTests.tearDown

    def test_original_choices_survive_reduction_admin_edit_and_restart(self):
        original = list(NEWS_CATEGORY_LABELS)
        saved = self.service.save_subscriptions('ou_delivery123', '测试用户', ['news'], news_categories=original)
        row = self.service.list_summary()['subscribers'][0]
        self.assertEqual(row['original_news_categories'], original)
        self.assertEqual(len(row['news_categories']), 4)
        self.service.update_subscriber('ou_delivery123', services=['news'], news_categories=['公司动态'])
        reloaded = SubscriptionService(runtime_root=self.root, command_runner=self.lark)
        row = reloaded.list_summary()['subscribers'][0]
        self.assertEqual(row['original_news_categories'], original)
        self.assertEqual(row['news_categories'], ['公司动态'])
        reloaded.save_subscriptions('ou_delivery123', '测试用户', ['news'], news_categories=['政策监管'])
        self.assertEqual(reloaded.list_summary()['subscribers'][0]['original_news_categories'], ['政策监管'])

    def test_legacy_over_limit_profile_is_captured_before_reduction(self):
        self.service.save_subscriptions('ou_delivery123', '测试用户', ['news'])
        original = list(NEWS_CATEGORY_LABELS)
        with closing(self.service._connect()) as db, db:
            db.execute("UPDATE subscribers SET news_categories=?, original_news_categories='[]', original_news_categories_source=''", (json.dumps(original),))
        reloaded = SubscriptionService(runtime_root=self.root, command_runner=self.lark)
        row = reloaded.list_summary()['subscribers'][0]
        self.assertEqual(row['original_news_categories'], original)
        self.assertEqual(row['original_news_categories_source'], 'legacy_before_reduction')
        self.assertEqual(len(row['news_categories']), 4)

    def test_unknown_original_choices_are_not_inferred(self):
        self.service.save_subscriptions('ou_delivery123', '测试用户', ['news'])
        row = self.service.list_summary()['subscribers'][0]
        self.assertEqual(row['original_news_categories'], [])
        self.assertEqual(row['original_news_categories_source'], '')

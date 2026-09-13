import json
import sqlite3
import unittest
from unittest.mock import Mock

from cmhk.services.news_delivery_guard import build_card_pages
from cmhk.services.news_delivery_history import _card_text
from tests import test_news_delivery_dedupe as guard_fixtures


class NewsPagedDeliveryTests(unittest.TestCase):
    setUp = guard_fixtures.DeliveryGuardTests.setUp
    send_news = guard_fixtures.DeliveryGuardTests.send_news

    def items(self):
        self.service.save_subscriptions('ou_test123', '测试用户', ['news'], frequency='twice_daily',
                                        news_categories=['公司动态'], news_item_limit=20)
        return [{'news_id': str(i), 'title': f'独立新闻 {i}', 'category': '公司动态',
                 'published_at': '2026-09-10', 'source_url': f'https://publisher.example/{i}',
                 'summary': f'企业{i}推出新服务，首批面向制造业客户开放，并安排专门团队提供部署支持。'} for i in range(20)]

    def large_items(self):
        return [{**item, 'source_url': item['source_url'] + '?details=' + 'x' * 850}
                for item in self.items()]

    def test_twenty_short_items_use_one_card_when_they_fit(self):
        items = self.items()
        self.send_news('single', items)
        self.assertEqual(self.send.call_count, 1)
        card = self.send.call_args.args[1]
        self.assertNotIn('（1/2）', card['header']['title']['content'])
        text = '\n'.join(_card_text(card))
        self.assertTrue(all(item['summary'] in text for item in items))

    def test_twenty_items_split_without_truncating_prose_or_repeating_sent_page(self):
        items = self.large_items()
        self.send.side_effect = ['om_page1', TimeoutError('page two timeout')]
        with self.assertRaises(TimeoutError):
            self.send_news('twenty', items)
        first, uncertain = self.send.call_args_list
        self.assertIn('（1/2）', first.args[1]['header']['title']['content'])
        self.assertIn('（2/2）', uncertain.args[1]['header']['title']['content'])
        self.assertNotEqual(first.kwargs['idempotency_key'], uncertain.kwargs['idempotency_key'])
        self.send.side_effect = None
        self.send.return_value = 'om_page2'
        self.assertEqual(self.send_news('twenty', items), ['om_page1', 'om_page2'])
        self.assertEqual(self.send.call_count, 3)
        self.assertEqual(self.send.call_args, uncertain)
        self.assertEqual(self.send_news('twenty', items), ['om_page1', 'om_page2'])
        self.assertEqual(self.send.call_count, 3)
        for call in self.send.call_args_list:
            self.assertLessEqual(len(json.dumps(call.args[1], ensure_ascii=False, separators=(',', ':')).encode()), 30000)
        with sqlite3.connect(self.service.db_path) as db:
            card = json.loads(db.execute('select card_json from news_delivery_receipts').fetchone()[0])
        text = '\n'.join(_card_text(card))
        self.assertTrue(all(item['summary'] in text for item in items))

    def test_all_page_ids_are_recovered_after_final_readback_failure(self):
        items = self.large_items()
        self.send.side_effect = ['om_page1', 'om_page2']
        self.verify.side_effect = [None, RuntimeError('readback failed')]
        with self.assertRaises(RuntimeError):
            self.send_news('readback', items)
        self.verify.side_effect = None
        self.assertEqual(self.send_news('readback', items), ['om_page1', 'om_page2'])
        self.assertEqual(self.send.call_count, 2)
        self.assertEqual([c.args[0] for c in self.verify.call_args_list[-2:]], ['om_page1', 'om_page2'])

    def test_oversized_rows_are_split_at_article_boundaries(self):
        from tests.news_push_fixtures import prepared_assets
        items = [{**item, 'image_kind': 'related',
                  'news_url': item['source_url'] + '?long=' + 'a' * 3000}
                 for item in prepared_assets(self.items())]
        from cmhk.services.news_delivery_guard import NewsCardCapacityError
        with self.assertRaises(NewsCardCapacityError) as raised:
            build_card_pages(title='战略下午茶', items=items, banner='img_banner')
        kept=items[:raised.exception.item_count]
        self.assertLess(len(kept),len(items))
        bundle = build_card_pages(title='战略下午茶', items=kept, banner='img_banner')
        self.assertLessEqual(len(bundle['cards']), 2)
        for card in bundle['cards']:
            self.assertLessEqual(len(json.dumps(card, ensure_ascii=False, separators=(',', ':')).encode()), 30000)
        text = '\n'.join(_card_text(bundle))
        self.assertNotIn('相关资料图', text)
        self.assertTrue(all(item['title'] in text for item in kept))

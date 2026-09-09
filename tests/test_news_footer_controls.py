import json
import unittest
from contextlib import closing
from tests import test_subscription_service as fixtures
from cmhk.services.subscriptions import strategic_news_card


class NewsFooterTests(unittest.TestCase):
    setUp = fixtures.SubscriptionServiceTests.setUp
    tearDown = fixtures.SubscriptionServiceTests.tearDown

    def send_news(self):
        self.service.save_subscriptions('ou_delivery123', '测试用户', ['news', 'weekly'], 'oc_test123')
        card = strategic_news_card(title='新闻', body='新闻正文')
        self.service._send_interactive_card('ou_delivery123', card, idempotency_key='news')
        return card

    def event(self, action, operator='ou_delivery123'):
        return {'type': 'card.action.trigger', 'action_tag': 'button', 'operator_id': operator,
                'message_id': 'om_test123', 'chat_id': 'oc_test123', 'event_id': action,
                'action_value': json.dumps({'action': action})}

    def test_two_independent_subtle_buttons(self):
        card = self.send_news()
        columns = card['body']['elements'][-1]['columns']
        buttons = [c['elements'][0] for c in columns]
        self.assertEqual([b['text']['content'] for b in buttons], ['修改兴趣偏好', '取消订阅'])
        self.assertTrue(all(b['type'] == 'default' and b['size'] == 'small' and b['width'] == 'fill' for b in buttons))

    def test_preferences_arrive_as_new_prefilled_card(self):
        self.send_news()
        result = self.service.handle_card_event(self.event('cmhk_news_preferences_v1'))
        self.assertEqual(result['status'], 'news_preferences_sent')
        self.assertTrue(result['preserve_source_card'])
        with closing(self.service._connect()) as db:
            self.assertIsNotNone(db.execute('SELECT * FROM subscription_entry_cards WHERE message_id=?', ('om_test123',)).fetchone())

    def test_unsubscribe_requires_separate_confirmation_and_keeps_reports(self):
        self.send_news()
        with self.assertRaisesRegex(ValueError, '对应'):
            self.service.handle_card_event(self.event('cmhk_news_unsubscribe_confirm_v1'))
        result = self.service.handle_card_event(self.event('cmhk_news_unsubscribe_v1'))
        self.assertEqual(result['status'], 'news_unsubscribe_confirmation_sent')
        with closing(self.service._connect()) as db:
            self.assertEqual(db.execute("SELECT active FROM subscriptions WHERE service='news'").fetchone()[0], 1)
        result = self.service.handle_card_event(self.event('cmhk_news_unsubscribe_confirm_v1'))
        self.assertEqual(result['status'], 'news_unsubscribed')
        with closing(self.service._connect()) as db:
            values = dict(db.execute('SELECT service,active FROM subscriptions'))
        self.assertEqual(values['news'], 0)
        self.assertEqual(values['weekly'], 1)

    def test_another_user_cannot_manage_recipient(self):
        self.send_news()
        with self.assertRaisesRegex(ValueError, '本人'):
            self.service.handle_card_event(self.event('cmhk_news_preferences_v1', operator='ou_other'))

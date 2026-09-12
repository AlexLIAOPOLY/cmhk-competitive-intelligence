import json
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch as mock_patch

from cmhk.services.subscription_chat import EVENT_KEY, SubscriptionChat, snapshot, validated_patch, validate_grounding, interpret
from cmhk.services.subscriptions import SubscriptionService
from cmhk.services.news_delivery_guard import recipient_contract


def plan(field='news_region_preference', value='international', operation='set'):
    return {'intent': 'update', 'changes': [{'field': field, 'value': value, 'operation': operation}], 'question': ''}


class SubscriptionChatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'config').mkdir()
        (self.root / 'config/project_monitor.json').write_text(json.dumps({'subscriptions': {'delivery_profile': 'testbot'}}))
        self.service = SubscriptionService(runtime_root=self.root)
        for user in ('ou_alice', 'ou_bob'):
            self.service.save_subscriptions(user, user, ['news', 'weekly'], frequency='twice_daily',
                report_mode='pdf_audio', news_item_limit=20, news_categories=['公司动态', '竞对动态'],
                news_delivery_times=['09:00', '19:00'], union_id='on_' + user)
        self.service._send_markdown = Mock(return_value='om_receipt')
        self.service._verify_message = Mock()
        self.model = Mock(return_value=plan())
        self.chat = SubscriptionChat(self.service, interpreter=self.model)

    def event(self, user='ou_alice', mid='om_first', **kw):
        return {'type': EVENT_KEY, 'sender_type': 'user', 'chat_type': 'p2p', 'message_type': 'text',
                'sender_id': user, 'message_id': mid, 'chat_id': 'oc_' + user.replace('_', ''),
                'content': '我希望多收一些国际新闻', **kw}

    def get(self, user='ou_alice'):
        with closing(self.service._connect()) as db:
            return snapshot(db, user)[1]

    def job(self):
        with closing(self.service._connect()) as db:
            return dict(db.execute('SELECT * FROM subscription_chat_inbox ORDER BY id DESC LIMIT 1').fetchone())

    def run_event(self, event=None):
        self.chat.enqueue(event or self.event(), 'testbot')
        self.assertTrue(self.chat.drain_one())

    def test_only_explicit_field_changes_and_named_recipient_receives_reply(self):
        before = self.get()
        bob = self.get('ou_bob')
        self.run_event()
        self.assertEqual(self.get(), {**before, 'news_region_preference': 'international'})
        self.assertEqual(self.get('ou_bob'), bob)
        self.assertEqual(self.service._send_markdown.call_args.args[0], 'ou_alice')
        self.assertIn('已成功更新你的喜好', self.job()['reply'])
        self.assertEqual(self.job()['status'], 'complete')

    def test_repeat_event_and_new_event_id_do_not_reapply_or_resend(self):
        self.run_event()
        self.assertEqual(self.chat.enqueue(self.event(event_id='newdelivery'), 'testbot')['status'], 'chat_duplicate')
        self.assertFalse(self.chat.drain_one())
        self.assertEqual(self.model.call_count, 1)
        self.assertEqual(self.service._send_markdown.call_count, 1)

    def test_bot_group_foreign_profile_malformed_identity_never_reach_ai(self):
        for changes in ({'sender_type': 'bot'}, {'chat_type': 'group'}, {'sender_id': 'ou_fake;UPDATE'}, {'type': 'wrong'}):
            self.assertEqual(self.chat.enqueue(self.event(**changes), 'testbot')['status'], 'ignored')
        self.assertEqual(self.chat.enqueue(self.event(), 'anotherbot')['status'], 'ignored')
        self.assertFalse(self.chat.drain_one())
        self.model.assert_not_called()

    def test_unknown_user_does_not_create_or_change_subscriptions(self):
        self.run_event(self.event(user='ou_unknown'))
        self.assertIsNone(self.get('ou_unknown'))
        self.model.assert_not_called()
        self.assertIn('先打开订阅邀请卡', self.job()['reply'])

    def test_model_failure_leaves_all_preferences_unchanged_and_replies(self):
        before = self.get()
        self.model.side_effect = RuntimeError('secret must never echo')
        self.run_event()
        self.assertEqual(self.get(), before)
        self.assertIn('暂时不可用', self.job()['reply'])
        self.assertNotIn('secret', self.job()['reply'])

    def test_invalid_unsupported_patch_is_atomic(self):
        before = self.get()
        self.model.return_value = {**plan(), 'changes': plan()['changes'] + plan('news_item_limit', '17')['changes']}
        self.run_event()
        self.assertEqual(self.get(), before)
        self.assertIn('未保存', self.job()['reply'])

    def test_model_cannot_change_identity_services_or_status(self):
        for field in ('open_id', 'services', 'status', 'source_chat_id', 'display_name', 'news_item_limit; DROP TABLE subscribers'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validated_patch(plan(field, 'ou_bob'), self.get())

    def test_question_with_partial_update_never_writes_any_fields(self):
        before = self.get()
        self.model.return_value = {**plan(), 'question': '还要修改时间吗？'}
        self.run_event()
        self.assertEqual(self.get(), before)
        self.assertIn('未保存', self.job()['reply'])

    def test_foreign_or_invented_count_and_time_are_rejected(self):
        current = self.get()
        for patch in ({'news_item_limit': 15}, {'news_delivery_times': ['09:30', '19:00']}, {'frequency': 'twice_daily'}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                validate_grounding(patch, current, '每天一次，每次5条，上午八点半收', [])
        validate_grounding({'news_item_limit': 5, 'frequency': 'once_daily', 'news_delivery_times': ['08:30', '19:00']},
                           current, '每天一次，每次五条，上午八点半收', [])

    def test_explicit_afternoon_time_preserves_unmentioned_morning(self):
        validate_grounding({'news_delivery_times': ['09:00', '18:15']}, self.get(), '下午六点一刻收', [])

    def test_model_response_is_bound_to_current_request_and_exact_source(self):
        for stale in ('token', 'original', ''):
            def transport(request, **kwargs):
                body = json.loads(request.data)
                request_data = json.loads(body['messages'][-1]['content'])
                result = {**plan(), 'token': request_data['token'], 'original': request_data['original']}
                if stale:
                    result[stale] = 'some other request'
                response = MagicMock()
                response.__enter__.return_value.read.return_value = json.dumps({'choices': [
                    {'finish_reason': 'stop', 'message': {'content': json.dumps(result)}}]}).encode()
                return response
            with self.subTest(stale=stale), mock_patch('ai_config.load_ai_config', return_value={'base_url': 'https://example.invalid/v1'}), mock_patch('ai_key_rotation.open_llm_request', side_effect=transport):
                if stale:
                    with self.assertRaises(ValueError):
                        interpret('我希望多收一些国际新闻', self.get(), [])
                else:
                    self.assertEqual(interpret('我希望多收一些国际新闻', self.get(), []), plan())

    def test_explicit_nonmutation_and_unsupported_exclusivity_are_enforced_before_model(self):
        before = self.get()
        for i, text in enumerate(('不要修改，只举个例子：我希望多收一些国际新闻', '只收国际新闻', '排除香港本地新闻')):
            self.run_event(self.event(mid='om_guard' + str(i), content=text))
            self.assertEqual(self.get(), before)
        self.model.assert_not_called()

    def test_delayed_older_message_cannot_overwrite_newer_request(self):
        self.run_event(self.event(create_time='1800000001000'))
        self.model.return_value = plan('news_region_preference', 'hong_kong')
        self.run_event(self.event(mid='om_late', create_time='1800000000000'))
        self.assertEqual(self.get()['news_region_preference'], 'international')
        self.assertEqual(self.model.call_count, 1)
        self.assertIn('较早的消息', self.job()['reply'])
        # Another person's clock does not suppress this person's request.
        self.run_event(self.event(user='ou_bob', mid='om_other', create_time='1800000000000'))
        self.assertEqual(self.model.call_count, 2)

    def test_worker_does_not_process_inbox_belonging_to_another_application(self):
        self.chat.enqueue(self.event(), 'testbot')
        with closing(self.service._connect()) as db, db:
            db.execute("UPDATE subscription_chat_inbox SET profile='anotherbot'")
        self.assertFalse(self.chat.drain_one())
        self.model.assert_not_called()
        self.assertEqual(self.service.list_summary()['subscribers'][0]['chat_history'], [])

    def test_add_and_remove_categories_preserve_unmentioned_interests(self):
        self.model.return_value = plan('news_categories', '["基础设施/网络/技术类"]', 'add')
        self.run_event()
        self.assertEqual(self.get()['news_categories'], ['公司动态', '竞对动态', '基础设施/网络/技术类'])
        self.model.return_value = plan('news_categories', '["竞对动态"]', 'remove')
        self.run_event(self.event(mid='om_second'))
        self.assertEqual(self.get()['news_categories'], ['公司动态', '基础设施/网络/技术类'])

    def test_show_and_clarify_never_modify(self):
        before = self.get()
        for intent in ('show', 'clarify', 'help'):
            self.model.return_value = {'intent': intent, 'changes': [], 'question': '每天一次还是两次？'}
            self.run_event(self.event(mid='om_' + intent))
            self.assertEqual(self.get(), before)

    def test_paused_subscriber_stays_paused(self):
        with closing(self.service._connect()) as db, db:
            db.execute("UPDATE subscribers SET status='paused' WHERE open_id='ou_alice'")
        self.run_event()
        self.assertEqual(self.get()['status'], 'paused')

    def test_restart_pending_inbox_recovers(self):
        self.chat.enqueue(self.event(), 'testbot')
        self.chat = SubscriptionChat(self.service, interpreter=self.model)
        self.assertTrue(self.chat.drain_one())
        self.assertEqual(self.get()['news_region_preference'], 'international')

    def test_restart_after_save_before_send_does_not_reapply(self):
        self.chat.enqueue(self.event(), 'testbot')
        self.chat._prepare(self.job())
        self.chat = SubscriptionChat(self.service, interpreter=self.model)
        self.chat.drain_one()
        self.assertEqual(self.model.call_count, 1)
        with closing(self.service._connect()) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM subscription_preference_submissions').fetchone()[0], 1)

    def test_readback_failure_retries_existing_reply_without_send(self):
        self.service._verify_message.side_effect = [RuntimeError(), None]
        self.run_event()
        self.assertEqual(self.job()['status'], 'reply_pending')
        with closing(self.service._connect()) as db, db:
            db.execute('UPDATE subscription_chat_inbox SET retry_at=0')
        SubscriptionChat(self.service, interpreter=self.model).drain_one()
        self.assertEqual(self.service._send_markdown.call_count, 1)
        self.assertEqual(self.job()['status'], 'complete')

    def test_send_retry_uses_same_idempotency_key(self):
        self.service._send_markdown.side_effect = [TimeoutError(), 'om_receipt']
        self.run_event()
        with closing(self.service._connect()) as db, db:
            db.execute('UPDATE subscription_chat_inbox SET retry_at=0')
        self.chat.drain_one()
        self.assertEqual(self.model.call_count, 1)
        self.assertEqual(self.service._send_markdown.call_args_list[0], self.service._send_markdown.call_args_list[1])

    def test_expired_uncertain_send_does_not_duplicate(self):
        self.service._send_markdown.side_effect = TimeoutError()
        self.run_event()
        with closing(self.service._connect()) as db, db:
            db.execute('UPDATE subscription_chat_inbox SET retry_at=0,send_started=?', (time.time()-901,))
        self.chat.drain_one()
        self.assertEqual(self.service._send_markdown.call_count, 1)
        self.assertEqual(self.job()['status'], 'delivery_unknown')

    def test_concurrent_admin_edit_prevents_stale_overwrite(self):
        def edit(*args):
            with closing(self.service._connect()) as db, db:
                db.execute("UPDATE subscribers SET news_item_limit=5 WHERE open_id='ou_alice'")
            return plan()
        self.model.side_effect = edit
        self.run_event()
        self.assertEqual(self.get()['news_item_limit'], 5)
        self.assertEqual(self.get()['news_region_preference'], 'hong_kong')
        self.assertIn('刚有更新', self.job()['reply'])

    def test_clarification_context_is_personal_and_latest_turn_only(self):
        self.model.return_value = {'intent': 'clarify', 'changes': [], 'question': '要几条？'}
        self.run_event()
        self.run_event(self.event(user='ou_bob', mid='om_bob'))
        self.assertEqual(self.model.call_args.args[2], [])
        self.model.return_value = plan()
        self.run_event(self.event(mid='om_answer'))
        self.assertEqual(len(self.model.call_args.args[2]), 1)
        self.run_event(self.event(mid='om_third'))
        self.assertEqual(self.model.call_args.args[2], [])

    def test_persistent_ordered_admin_points_history_and_other_user_isolation(self):
        self.run_event()
        self.service = SubscriptionService(runtime_root=self.root)
        people = {r['open_id']: r for r in self.service.list_summary()['subscribers']}
        self.assertTrue(any('国际新闻优先' in p for p in people['ou_alice']['preference_points']))
        self.assertEqual(len(people['ou_alice']['chat_history']), 1)
        self.assertEqual(people['ou_bob']['chat_history'], [])
        self.assertEqual(people['ou_alice']['chat_history'][0]['changes'][0]['field'], 'news_region_preference')
        self.assertTrue(people['ou_alice']['chat_history'][0]['points'])

    def test_confirm_numbered_list_then_revise_marks_only_latest_version(self):
        self.run_event()
        self.assertIn('1. 订阅内容', self.job()['reply'])
        self.assertIn('8. 订阅状态', self.job()['reply'])
        self.run_event(self.event(mid='om_confirm', content='行'))
        self.assertEqual(self.job()['intent'], 'confirm')
        self.assertIn('已确认你的喜好', self.job()['reply'])
        people = {p['open_id']: p for p in self.service.list_summary()['subscribers']}
        self.assertTrue(people['ou_alice']['preference_confirmed_at'])
        self.assertIsNone(people['ou_bob']['preference_confirmed_at'])
        self.model.return_value = plan('news_item_limit', '5')
        self.run_event(self.event(mid='om_revision', content='每次只收5条'))
        people = {p['open_id']: p for p in self.service.list_summary()['subscribers']}
        self.assertIsNone(people['ou_alice']['preference_confirmed_at'])
        self.assertEqual(people['ou_alice']['news_item_limit'], 5)
        self.run_event(self.event(mid='om_confirm2', content='确认'))
        people = {p['open_id']: p for p in self.service.list_summary()['subscribers']}
        self.assertTrue(people['ou_alice']['preference_confirmed_at'])
        self.assertIn('5 条', self.job()['reply'])

    def test_confirmation_cannot_accept_an_unseen_admin_change(self):
        self.run_event()
        with closing(self.service._connect()) as db, db:
            db.execute("UPDATE subscribers SET news_item_limit=5 WHERE open_id='ou_alice'")
        self.run_event(self.event(mid='om_staleconfirmation', content='确认'))
        self.assertEqual(self.job()['intent'], 'show')
        self.assertIn('先核对', self.job()['reply'])
        self.assertIn('5 条', self.job()['reply'])

    def test_preparation_contract_invalidated_for_only_changed_person(self):
        before = {u: recipient_contract(self.service, u, 'testbot') for u in ('ou_alice', 'ou_bob')}
        self.run_event()
        self.assertNotEqual(recipient_contract(self.service, 'ou_alice', 'testbot'), before['ou_alice'])
        self.assertEqual(recipient_contract(self.service, 'ou_bob', 'testbot'), before['ou_bob'])

    def test_thirty_interleaved_requests_survive_restarts_without_crossing(self):
        expected = {'ou_alice': 20, 'ou_bob': 20}
        for i in range(30):
            user = 'ou_alice' if i % 2 == 0 else 'ou_bob'
            count = [5, 10, 15, 20][i % 4]
            self.model.return_value = plan('news_item_limit', str(count))
            self.chat = SubscriptionChat(self.service, interpreter=self.model)
            self.run_event(self.event(user=user, mid='om_sequence' + str(i)))
            expected[user] = count
            for person in expected:
                self.assertEqual(self.get(person)['news_item_limit'], expected[person])
            self.assertEqual(self.service._send_markdown.call_args.args[0], user)

    def test_attachment_and_oversized_text_do_not_enter_model(self):
        self.run_event(self.event(message_type='image'))
        self.run_event(self.event(mid='om_long', content='a' * 2001))
        self.model.assert_not_called()


if __name__ == '__main__':
    unittest.main()

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
        for stale in ('request_context', ''):
            def transport(request, **kwargs):
                body = json.loads(request.data)
                request_data = json.loads(body['messages'][-1]['content'])
                self.assertNotIn('current', request_data)
                self.assertEqual(set(request_data), {'本次要求', '本人近期对话', '自主安排', '本人已保存主题', '本人阅读要求'})
                result = {**plan(), 'request_context': request_data}
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

    def test_same_delegation_with_different_context_cannot_reuse_response(self):
        def transport(request, **kwargs):
            data = json.loads(json.loads(request.data)['messages'][-1]['content'])
            data['本人已保存主题'] = ['新能源汽车电池技术']
            result = {**plan('news_topics', [{'name':'新能源汽车电池技术','terms':['电池']}], 'add'),
                      'request_context': data}
            response = MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps({'choices': [
                {'finish_reason':'stop','message':{'content':json.dumps(result)}}]}).encode()
            return response
        with mock_patch('ai_config.load_ai_config', return_value={'base_url':'https://example.invalid/v1'}), mock_patch('ai_key_rotation.open_llm_request', side_effect=transport):
            with self.assertRaises(ValueError):
                interpret('你定', {**self.get(), 'news_topics':[{'name':'人工智能','terms':['AI']}]}, [])

    def test_explicit_nonmutation_and_unsupported_exclusivity_are_enforced_before_model(self):
        before = self.get()
        for i, text in enumerate(('不要修改，只举个例子：我希望多收一些国际新闻', '只收国际新闻', '排除香港本地新闻')):
            self.run_event(self.event(mid='om_guard' + str(i), content=text))
            self.assertEqual(self.get(), before)
        self.model.assert_not_called()

    def test_same_stateless_time_result_merges_each_person_without_copying_saved_values(self):
        source = '上午八点半收'
        def transport(request, **kwargs):
            data = json.loads(json.loads(request.data)['messages'][-1]['content'])
            result = {**plan('news_delivery_times', '["08:30","19:00"]'), 'request_context': data}
            response = MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps({'choices': [
                {'finish_reason': 'stop', 'message': {'content': json.dumps(result)}}]}).encode()
            return response
        with mock_patch('ai_config.load_ai_config', return_value={'base_url': 'https://example.invalid/v1'}), mock_patch('ai_key_rotation.open_llm_request', side_effect=transport):
            for afternoon in ('18:30', '19:00', '21:00'):
                current = {**self.get(), 'news_delivery_times': ['09:00', afternoon]}
                proposal = interpret(source, current, [])
                self.assertEqual(validated_patch(proposal, current)['news_delivery_times'], ['08:30', afternoon])

    def test_time_slot_omitted_by_parser_preserves_own_saved_time(self):
        current = {**self.get(), 'news_delivery_times': ['10:15', '22:00']}
        self.assertEqual(validated_patch(plan('news_delivery_times', '["09:30",""]'), current)['news_delivery_times'], ['09:30', '22:00'])

    def test_missing_explicit_fields_or_unchanged_wrong_time_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_grounding({'news_region_preference': 'international'}, self.get(), '国际新闻优先，每次5条，上午八点半', [])
        with self.assertRaises(ValueError):
            validate_grounding({'news_delivery_times': ['09:00', '19:00']}, self.get(), '上午八点半收', [])

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

    def test_context_retains_own_recent_turns_only(self):
        self.model.return_value = {'intent': 'clarify', 'changes': [], 'question': '要几条？'}
        self.run_event()
        self.run_event(self.event(user='ou_bob', mid='om_bob'))
        self.assertEqual(self.model.call_args.args[2], [])
        self.model.return_value = plan()
        self.run_event(self.event(mid='om_answer'))
        self.assertEqual(len(self.model.call_args.args[2]), 1)
        self.run_event(self.event(mid='om_third'))
        self.assertEqual([r['intent'] for r in self.model.call_args.args[2]], ['clarify', 'update'])

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
        self.assertIn('10. 订阅状态', self.job()['reply'])
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

    def test_free_topics_saved_numbered_and_isolated_across_restart(self):
        from cmhk.services.news_topics import normalize_news_topics
        topics = [{'name': 'AI', 'terms': ['AI', '人工智能']}]
        before = self.get(); bob = self.get('ou_bob')
        contract = {u: recipient_contract(self.service, u, 'testbot') for u in ('ou_alice','ou_bob')}
        self.model.return_value = plan('news_topics', json.dumps(topics), 'add')
        self.run_event(self.event(content='多看AI新闻'))
        expected = normalize_news_topics(topics)
        self.assertEqual(self.get(), {**before, 'news_topics': expected})
        self.assertEqual(self.get('ou_bob'), bob)
        self.assertNotEqual(contract['ou_alice'], recipient_contract(self.service, 'ou_alice', 'testbot'))
        self.assertEqual(contract['ou_bob'], recipient_contract(self.service, 'ou_bob', 'testbot'))
        self.assertIn('1. 人工智能（AI）', self.job()['reply'])
        self.chat = SubscriptionChat(self.service, interpreter=self.model)
        self.run_event(self.event(mid='om_topicconfirm', content='确认'))
        self.assertEqual(self.get()['news_topics'], expected)
        person = next(p for p in self.service.list_summary()['subscribers'] if p['open_id']=='ou_alice')
        self.assertTrue(person['preference_confirmed_at'])
        self.assertEqual(person['news_topics'], expected)

    def test_topic_refinement_changes_only_requested_topic_and_default_reset(self):
        ai = {'name':'AI','terms':['人工智能','AI']}
        ev = {'name':'新能源汽车','terms':['电动车','新能源汽车']}
        self.model.return_value = plan('news_topics', json.dumps([ai,ev]), 'add')
        self.run_event()
        medical = {'name':'AI医疗应用','terms':['AI&医疗','人工智能&医疗']}
        self.model.return_value = {'intent':'update','question':'','changes':[
            *plan('news_topics',json.dumps([ai]),'remove')['changes'],
            *plan('news_topics',json.dumps([medical]),'add')['changes']]}
        self.run_event(self.event(mid='om_refine',content='AI改成医疗应用，其他保留'))
        self.assertEqual([t['name'] for t in self.get()['news_topics']], ['新能源汽车','AI医疗应用'])
        self.service.save_subscriptions('ou_alice','Alice',['news'],news_item_limit=5)
        self.assertEqual(len(self.get()['news_topics']),2)  # Old cards/forms omit new fields.
        self.service.reset_subscriber('ou_alice')
        self.assertEqual(self.get()['news_topics'], [])

    def test_topic_matching_boundaries_compound_focus_and_roundtrip(self):
        from cmhk.services.news_topics import topic_score, normalize_news_topics
        ai = [{'name':'AI','terms':['AI','人工智能']}]
        self.assertEqual(topic_score({'title':'Thailand train maintenance'}, ai),0)
        self.assertEqual(topic_score({'title':'生成式AI助力企业'}, ai),1)
        med = [{'name':'AI医疗应用','terms':['AI&医疗','人工智能&医疗']}]
        self.assertEqual(topic_score({'title':'AI改善网络，手机新品发布'}, med),0)
        self.assertEqual(topic_score({'title':'AI已进入诊室','summary':'用于医疗诊断'}, med),1)
        value = normalize_news_topics(ai)
        self.assertEqual(normalize_news_topics(json.dumps(value),strict=True),value)

    def test_topic_priority_affects_manual_and_automatic_selection_per_user(self):
        from cmhk.services.subscriptions import _decode_strategic_news_digest
        items = [dict(news_id='other',title='新套餐推出',summary='电信公司推出新套餐',category='竞对动态',region='香港本地',published_at='2026-09-12T09:00:00+08:00',source_url='https://example.test/other'),
                 dict(news_id='ai',title='AI大模型发布',summary='人工智能研发取得进展',category='公司动态',region='香港本地',published_at='2026-09-12T08:00:00+08:00',source_url='https://example.test/ai')]
        self.model.return_value=plan('news_topics',json.dumps([{'name':'AI','terms':['AI','人工智能']}]),'add')
        self.run_event()
        with mock_patch('cmhk.services.subscriptions._now_hkt',return_value='2026-09-12T10:00:00+08:00'):
            self.assertEqual(self.service.select_personal_news(items,open_id='ou_alice')[0]['news_id'],'ai')
            self.assertEqual(self.service.select_personal_news(items,open_id='ou_bob')[0]['news_id'],'other')
        result=self.service.dispatch_news_after_crawl(crawl_slot='2026-09-12@14:00',slot_label='午后扫描',items=items,completed_at='2026-09-12T15:00:00+08:00')
        self.assertEqual(result['queued_count'],2)
        with closing(self.service._connect()) as db:
            rows=db.execute('SELECT open_id,body FROM pending_subscription_deliveries').fetchall()
        first={r['open_id']:_decode_strategic_news_digest(r['body'])[0]['news_id'] for r in rows}
        self.assertEqual(first,{'ou_alice':'ai','ou_bob':'other'})

    def test_topic_priority_preserves_region_freshness_history_and_section_limit(self):
        from cmhk.services.news_delivery_selection import select_recent_news
        from cmhk.services.subscriptions import NEWS_CATEGORY_LABELS
        items=[dict(news_id=f'n{i}',title=('AI技术进展' if i==6 else f'其他事件{i}'),summary='不同事件',category=category,region='香港本地',published_at='2026-09-12T09:00:00+08:00') for i,category in enumerate(NEWS_CATEGORY_LABELS)]
        topics=[{'name':'AI','terms':['AI','人工智能']}]
        selected=select_recent_news(items,list(NEWS_CATEGORY_LABELS),limit=4,history=[],send_day='2026-09-12',topics=topics)
        self.assertEqual(selected[0]['news_id'],'n6')
        self.assertLessEqual(len(set(r['category'] for r in selected)),4)
        history=[items[6]]
        selected=select_recent_news(items,list(NEWS_CATEGORY_LABELS),limit=4,history=history,send_day='2026-09-12',topics=topics)
        self.assertNotIn('n6',[r['news_id'] for r in selected])
        items[6]['region']='国际/行业'
        selected=select_recent_news(items,list(NEWS_CATEGORY_LABELS),limit=1,history=[],send_day='2026-09-12',topics=topics,region_preference='hong_kong')
        self.assertNotEqual(selected[0]['news_id'],'n6')

    def test_topic_crosses_old_section_checklist_without_adding_unrelated_items(self):
        from cmhk.services.news_delivery_selection import select_recent_news
        def item(key,title,category):
            return dict(news_id=key,title=title,category=category,region='香港本地',published_at='2026-09-12T08:00:00+08:00')
        items=[item('company','公司财报','公司动态'),item('ai','AI医疗研究','行业动态'),item('outside','酒店促销','行业动态')]
        topics=[{'name':'AI','terms':['AI','人工智能']}]
        rows=select_recent_news(items,['公司动态'],limit=5,history=[],send_day='2026-09-12',topics=topics,region_preference='hong_kong')
        self.assertEqual([r['news_id'] for r in rows],['ai','company'])
        rows=select_recent_news(items,['公司动态'],limit=5,history=[],send_day='2026-09-12')
        self.assertEqual([r['news_id'] for r in rows],['company'])

    def test_saved_dialog_context_never_exposes_reply_preferences_to_model(self):
        captured=[]
        def transport(request, **kwargs):
            data=json.loads(json.loads(request.data)['messages'][-1]['content']);captured.append(data)
            result={'request_context':data,'intent':'help','changes':[],'question':'','reply':'明白，我可以继续帮你安排。'}
            response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(result)}}]}).encode();return response
        context=[{'text':'多看AI新闻','intent':'update','reply':'本人旧设置SECRET 09:30'}, {'text':'怎么选','intent':'clarify','reply':'想侧重AI产品还是应用？'}]
        with mock_patch('ai_config.load_ai_config',return_value={'base_url':'https://example.invalid/v1'}),mock_patch('ai_key_rotation.open_llm_request',side_effect=transport):
            interpret('你定',self.get(),context)
        self.assertNotIn('SECRET',json.dumps(captured))
        self.assertTrue(captured[0]['自主安排'])
        self.assertEqual(captured[0]['本人近期对话'][0]['text'],'多看AI新闻')

    def test_equivalent_single_topic_object_is_accepted_but_foreign_fields_rejected(self):
        topic={'name':'量子通信','terms':['量子通信','量子密钥']}
        for value in (json.dumps(topic), topic, [topic]):
            self.assertEqual(validated_patch(plan('news_topics',value,'add'),self.get())['news_topics'],[topic])
        for topic in ({'name':'AI','terms':['&&']},{'name':'AI','terms':['AI'],'open_id':'ou_bob'}):
            with self.assertRaises(ValueError):
                validated_patch(plan('news_topics',topic,'add'),self.get())

    def test_removing_topics_by_saved_name_is_equivalent_and_cannot_target_others(self):
        topics=[{'name':'量子通信','terms':['量子通信','量子密钥']},{'name':'AI医疗','terms':['AI&医疗']}]
        current={**self.get(),'news_topics':topics}
        for value in ('量子通信','"量子通信"','["量子通信"]'):
            self.assertEqual(validated_patch(plan('news_topics',value,'remove'),current)['news_topics'],topics[1:])
        self.assertEqual(self.get('ou_bob')['news_topics'],[])

    def test_past_saved_time_cannot_override_admin_time_on_new_request(self):
        current={**self.get(),'news_delivery_times':['10:00','19:00']}
        validate_grounding({'news_delivery_times':['10:00','18:00']},current,'下午六点收',[{'text':'上午九点收','intent':'update'}])
        with self.assertRaises(ValueError):
            validate_grounding({'news_delivery_times':['09:00','18:00']},current,'下午六点收',[{'text':'上午九点收','intent':'update'}])


if __name__ == '__main__':
    unittest.main()

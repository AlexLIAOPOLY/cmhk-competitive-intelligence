import copy
import unittest

from cmhk.intelligence import news_selection_agent as agent
from cmhk.intelligence.news_acceptance_repair import repair_review


class EventRepresentativeTests(unittest.TestCase):
    def setUp(self):
        # The actual pair that returned both "accept" and duplicate_of in protocol 4.
        self.targets = [dict(news_id='NEWS-34A88ECAB2AFFD',
            title='T-Mobile、Verizon和AT&T推出iPhone 18 Pro免费获取方案',
            summary='T-Mobile、Verizon和AT&T相继公布合约套餐，用户可通过特定计划免费获得新机。',
            app_before='待审核', weekly_before='待审核'),
            dict(news_id='NEWS-71EA3B79EBB3D3',
            title='iPhone 18 Pro预购优惠汇总',
            summary='T-Mobile、Verizon、AT&T等运营商推出以旧换新和分期优惠，最高可节省1300美元。',
            app_before='待审核', weekly_before='待审核')]
        self.provisional = [dict(news_id=t['news_id'], app_status='接受', weekly_status='不接受')
                            for t in self.targets]
        self.payload = dict(event_groups=[dict(event='美国运营商iPhone 18 Pro合约优惠',
            news_ids=[t['news_id'] for t in self.targets],
            app=dict(accept_id=self.targets[0]['news_id'], reason='具体运营商合约促销，可比较终端补贴',
                     evidence=self.targets[0]['summary'], impact='比较运营商终端补贴策略',
                     signal='产品资费', confidence=.8),
            weekly=dict(accept_id=None, reason='海外促销未提供管理决策所需的具体经营数据', confidence=.9))])

    def normalize(self, payload=None, targets=None, provisional=None):
        return agent._normalized_acceptance_review(payload or self.payload,
            targets or self.targets, provisional or self.provisional)

    def test_real_conflicting_pair_has_one_authoritative_model_choice(self):
        result = self.normalize()
        self.assertEqual([r['app_status'] for r in result], ['接受', '不接受'])
        self.assertEqual(result[1]['acceptance_review']['app']['duplicate_of'], self.targets[0]['news_id'])
        self.assertEqual([r['weekly_status'] for r in result], ['不接受', '不接受'])
        self.assertEqual(result[0]['summary'], self.targets[0]['summary'])
        ambiguous = copy.deepcopy(self.payload)
        ambiguous['decisions'] = [dict(news_id=t['news_id'], app_status='接受') for t in self.targets]
        with self.assertRaisesRegex(ValueError, '双重结论歧义'):
            self.normalize(ambiguous)

    def test_unknown_outside_group_and_ambiguous_representatives_are_rejected(self):
        for value in ('UNKNOWN', [t['news_id'] for t in self.targets], '', 'null'):
            with self.subTest(value=value):
                payload = copy.deepcopy(self.payload)
                payload['event_groups'][0]['app']['accept_id'] = value
                with self.assertRaises(ValueError):
                    self.normalize(payload)
        payload = copy.deepcopy(self.payload)
        second = copy.deepcopy(payload['event_groups'][0])
        payload['event_groups'][0]['news_ids'] = [self.targets[0]['news_id']]
        second['news_ids'] = [self.targets[1]['news_id']]
        payload['event_groups'].append(second)
        with self.assertRaisesRegex(ValueError, '同一事件组'):
            self.normalize(payload)

    def test_original_rejections_manual_fields_and_representative_source_remain_protected(self):
        payload = copy.deepcopy(self.payload)
        payload['event_groups'][0]['weekly']['accept_id'] = self.targets[0]['news_id']
        with self.assertRaisesRegex(ValueError, '不得新增'):
            self.normalize(payload)
        targets = copy.deepcopy(self.targets)
        targets[1]['weekly_before'] = '接受'
        self.assertEqual(self.normalize(targets=targets)[1]['weekly_status'], '接受')
        payload = copy.deepcopy(self.payload)
        payload['event_groups'][0]['app']['accept_id'] = self.targets[1]['news_id']
        with self.assertRaisesRegex(ValueError, '原文事实'):
            self.normalize(payload)
        payload['event_groups'][0]['app']['accept_id'] = None
        self.assertEqual([r['app_status'] for r in self.normalize(payload)], ['不接受', '不接受'])

    def test_terminal_punctuation_is_equivalent_but_original_quote_is_kept(self):
        payload = copy.deepcopy(self.payload)
        submitted = self.targets[0]['summary'].rstrip('。') + '..'
        payload['event_groups'][0]['app']['evidence'] = submitted
        proof = self.normalize(payload)[0]['acceptance_review']['app']
        self.assertEqual(proof['evidence'], submitted)
        self.assertEqual(proof['source_evidence'], self.targets[0]['summary'].rstrip('。'))
        payload['event_groups'][0]['app']['evidence'] = submitted.replace('免费', '收费')
        with self.assertRaisesRegex(ValueError, '原文事实'):
            self.normalize(payload)

    def test_all_field_errors_are_reported_before_any_repair_request(self):
        payload = copy.deepcopy(self.payload)
        payload['event_groups'][0]['app']['signal'] = '经营指标'
        payload['event_groups'][0]['weekly'] = dict(accept_id=self.targets[0]['news_id'], reason='管理判断')
        provisional = [dict(p, weekly_status='接受') for p in self.provisional]
        with self.assertRaises(ValueError) as caught:
            self.normalize(payload, provisional=provisional)
        message = str(caught.exception)
        for text in ('实际指标数值', '/app', '/weekly', 'evidence', 'impact', 'signal'):
            self.assertIn(text, message)

    def test_event_raw_drafts_repair_only_invalid_group_and_keep_attempt_evidence(self):
        targets = copy.deepcopy(self.targets)
        targets.append(dict(self.targets[0], news_id='INDEPENDENT'))
        provisional = self.provisional + [dict(news_id='INDEPENDENT', app_status='接受', weekly_status='不接受')]
        original = copy.deepcopy(self.payload)
        additional = copy.deepcopy(original['event_groups'][0])
        additional.update(event='独立事件', news_ids=['INDEPENDENT'])
        additional['app']['accept_id'] = 'INDEPENDENT'
        original['event_groups'].append(additional)
        original['event_groups'][0]['app']['accept_id'] = ['ambiguous']
        checkpoint, calls, session = {}, [], {'acceptance_review': provisional}
        def invoke(examples, subset):
            calls.append([t['news_id'] for t in subset])
            if len(calls) == 1:
                return original, 'model'
            self.assertEqual(session['acceptance_review_repair']['unvalidated_draft']['event_groups'], original['event_groups'][:1])
            return self.payload, 'model'
        result, _ = repair_review([], targets, provisional, cached={}, checkpoint=checkpoint,
            checkpoint_key='protocol6', checkpoint_callback=None, session=session,
            invoke=invoke, validate=agent._normalized_acceptance_review,
            blocked_error=agent.NewsSelectionQualityBlocked)
        self.assertEqual([len(c) for c in calls], [3, 2])
        self.assertEqual(result['event_groups'][0], additional)
        self.assertEqual(checkpoint['protocol6:repair']['attempt_history'][0]['response'], original)
        self.assertEqual(len(checkpoint['protocol6:repair']['attempt_history']), 2)
        agent._normalized_acceptance_review(result, targets, provisional)


if __name__ == '__main__':
    unittest.main()

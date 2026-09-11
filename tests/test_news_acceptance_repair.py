import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from cmhk.intelligence import news_selection_agent as agent
from cmhk.intelligence.news_acceptance_repair import repair_review
from tests import test_news_selection_acceptance_review as acceptance_fixture
from tests import test_news_event_review as event_fixture
from cmhk.intelligence import news_acceptance_repair as repair
import strategic_briefing as briefing


class RepairTests(unittest.TestCase):
    setUp = acceptance_fixture.AcceptanceReviewTests.setUp
    review_payload = acceptance_fixture.AcceptanceReviewTests.review_payload

    def paired_payload(self):
        payload = self.review_payload()
        payload['event_groups'] = [dict(event=f'独立套餐{i}', news_ids=[f'N-{i}', f'N-{i+1}'])
                                   for i in (0, 2, 4)]
        for i, row in enumerate(payload['decisions']):
            row.update(app_status='不接受' if i % 2 else '接受',
                       app_duplicate_of=f'N-{i-1}' if i % 2 else '')
        return payload

    def test_all_invalid_groups_share_one_repair_with_their_actual_draft(self):
        draft = self.paired_payload()
        draft['decisions'][1]['app_status'] = '接受'
        draft['decisions'][3]['app_duplicate_of'] = 'unknown'
        repaired = self.paired_payload()
        repaired['event_groups'] = repaired['event_groups'][:2]
        repaired['decisions'] = repaired['decisions'][:4]
        session, calls, checkpoint = {'acceptance_review': self.primary}, [], {}
        def invoke(examples, targets):
            calls.append([t['news_id'] for t in targets])
            if len(calls) == 1:
                return draft, 'm'
            context = session['acceptance_review_repair']
            self.assertEqual(len(context['validation_issues']), 2)
            self.assertEqual(context['unvalidated_draft']['decisions'], draft['decisions'][:4])
            self.assertIn('同一事件同字段重复接受', context['validation_issues'][0]['error'])
            self.assertIn('已接受代表', context['validation_issues'][1]['error'])
            return repaired, 'm'
        result, _ = repair_review([], self.targets, self.primary,
            cached={}, checkpoint_key='r', checkpoint=checkpoint, checkpoint_callback=None,
            session=session, invoke=invoke, validate=agent._normalized_acceptance_review,
            blocked_error=agent.NewsSelectionQualityBlocked)
        self.assertEqual(calls, [[f'N-{i}' for i in range(6)], [f'N-{i}' for i in range(4)]])
        self.assertEqual(result['decisions'][:2], draft['decisions'][4:])
        self.assertNotIn('acceptance_review_repair', session)
        agent._normalized_acceptance_review(result, self.targets, self.primary)

    def test_changing_union_of_bad_groups_does_not_reset_candidate_budget(self):
        draft = self.paired_payload()
        draft['decisions'][1]['app_status'] = '接受'
        draft['decisions'][3]['app_status'] = '接受'
        calls, checkpoint = [], {}
        def invoke(examples, targets):
            calls.append([t['news_id'] for t in targets])
            if len(calls) == 1:
                return draft, 'm'
            candidate_ids = {t['news_id'] for t in targets}
            result = copy.deepcopy(draft)
            result['decisions'][1]['app_status'] = '不接受'
            result['decisions'] = [r for r in result['decisions'] if r['news_id'] in candidate_ids]
            result['event_groups'] = [g for g in result['event_groups'] if set(g['news_ids']) <= candidate_ids]
            return result, 'm'
        args = dict(cached={}, checkpoint_key='r', checkpoint=checkpoint, checkpoint_callback=None,
                    session={'acceptance_review': self.primary}, invoke=invoke,
                    validate=agent._normalized_acceptance_review, blocked_error=agent.NewsSelectionQualityBlocked)
        for _ in range(2):
            with self.assertRaises(agent.NewsSelectionQualityBlocked):
                repair_review([], self.targets, self.primary, **args)
        self.assertEqual([len(c) for c in calls], [6, 4, 2])
        self.assertEqual(checkpoint['r:repair']['news_attempts']['N-3'], 3)
        self.assertTrue(checkpoint['r:repair']['blocked'])

    def test_only_conflicting_event_repaired_and_progress_survives_restart(self):
        original = self.review_payload()
        original['event_groups'] = [dict(event='套餐甲', news_ids=['N-0', 'N-1']),
                                    dict(event='套餐乙', news_ids=['N-2', 'N-3', 'N-4', 'N-5'])]
        for row in original['decisions']:
            if row['news_id'] == 'N-2':
                row.update(app_status='接受', app_duplicate_of='')
            elif row['news_id'] in ['N-3', 'N-4', 'N-5']:
                row['app_duplicate_of'] = 'N-2'
        original['decisions'][1].update(app_status='接受', app_duplicate_of='')
        repaired = copy.deepcopy(original)
        repaired['event_groups'] = repaired['event_groups'][:1]
        repaired['decisions'] = repaired['decisions'][:2]
        repaired['decisions'][1].update(app_status='不接受', app_duplicate_of='N-0')
        checkpoint, calls = {}, []
        def invoke(examples, targets):
            calls.append([t['news_id'] for t in targets])
            if len(calls) == 1:
                return original, 'm'
            if len(calls) == 2:
                raise ConnectionError('interrupted')
            return repaired, 'm'
        args = dict(cached={}, checkpoint_key='r', checkpoint=checkpoint, checkpoint_callback=None,
                    session={'acceptance_review': self.primary}, invoke=invoke,
                    validate=agent._normalized_acceptance_review, blocked_error=agent.NewsSelectionQualityBlocked)
        with self.assertRaises(ConnectionError):
            repair_review([], self.targets, self.primary, **args)
        self.assertEqual(checkpoint['r:repair']['requests'], 2)
        result, _ = repair_review([], self.targets, self.primary, **args)
        self.assertEqual([len(c) for c in calls], [6, 2, 2])
        self.assertEqual(result['decisions'][:4], original['decisions'][2:])
        agent._normalized_acceptance_review(result, self.targets, self.primary)

    def test_same_invalid_group_is_durably_blocked_without_further_calls(self):
        invalid = self.review_payload()
        invalid['decisions'][1].update(app_status='接受', app_duplicate_of='')
        call = Mock(return_value=(invalid, 'm'))
        checkpoint = {}
        args = dict(cached={}, checkpoint_key='r', checkpoint=checkpoint, checkpoint_callback=None,
                    session={'acceptance_review': self.primary}, invoke=call,
                    validate=agent._normalized_acceptance_review, blocked_error=agent.NewsSelectionQualityBlocked)
        for _ in range(2):
            with self.assertRaisesRegex(agent.NewsSelectionQualityBlocked, '同一事件同字段重复接受'):
                repair_review([], self.targets, self.primary, **args)
        self.assertEqual(call.call_count, 3)
        self.assertNotIn('payload', checkpoint['r:repair'])


class DiagnosticMigrationTests(unittest.TestCase):
    def setUp(self):
        event_fixture.EventRepresentativeTests.setUp(self)
        self.valid_pair = copy.deepcopy(self.payload)
        good = copy.deepcopy(self.payload['event_groups'][0])
        good.update(event='独立已验证事件', news_ids=['GOOD'])
        good['app']['accept_id'] = 'GOOD'
        self.payload['event_groups'].append(good)
        self.targets.append(dict(self.targets[0], news_id='GOOD'))
        self.provisional.append(dict(news_id='GOOD', app_status='接受', weekly_status='不接受'))
        self.payload['event_groups'][0]['app']['evidence'] = '不是实际原文的错误引用'
        self.old = dict(blocked=True, status='needs_review', requests=3,
            scope_attempts={'original-scope': 3},
            news_attempts={t['news_id']: 1 if t['news_id']=='GOOD' else 3 for t in self.targets},
            draft=copy.deepcopy(self.payload), model='old-model', last_error='旧诊断只含首个错误',
            attempt_history=[dict(request=i, response=copy.deepcopy(self.payload)) for i in (1,2,3)])
        self.checkpoint = {'same:repair': copy.deepcopy(self.old)}
        self.session = {'acceptance_review': self.provisional, 'quality_feedback': '原反馈'}
        self.args = dict(cached={}, checkpoint=self.checkpoint, checkpoint_key='same',
            checkpoint_callback=None, session=self.session,
            validate=agent._normalized_acceptance_review, blocked_error=agent.NewsSelectionQualityBlocked)

    def run_repair(self, invoke):
        return repair_review(['old preference examples'], self.targets, self.provisional,
                             invoke=invoke, **self.args)

    def test_old_blocked_draft_gets_one_durable_repair_and_keeps_good_group(self):
        def invoke(examples, subset):
            self.assertEqual(examples, [])
            self.assertEqual({t['news_id'] for t in subset}, {t['news_id'] for t in self.targets[:2]})
            state = self.checkpoint['same:repair']
            self.assertEqual(state['requests'], 4)
            self.assertTrue(state['diagnostic_migration']['used'])
            self.assertEqual(state['attempt_history'], self.old['attempt_history'])
            return self.valid_pair, 'new-model'
        call = Mock(side_effect=invoke)
        result, _ = self.run_repair(call)
        state = self.checkpoint['same:repair']
        self.assertEqual(state['attempt_history'][:3], self.old['attempt_history'])
        self.assertEqual(state['scope_attempts']['original-scope'], 3)
        self.assertEqual(state['news_attempts']['GOOD'], 1)
        self.assertTrue(all(state['news_attempts'][t['news_id']]==4 for t in self.targets[:2]))
        self.assertEqual(result['event_groups'][0], self.payload['event_groups'][1])
        self.assertEqual(state['diagnostic_revision'], repair.DIAGNOSTIC_REVISION)
        self.assertFalse(state['blocked'])
        self.run_repair(call)
        self.assertEqual(call.call_count, 1)

    def test_failed_migration_is_never_reawarded_even_after_revision_changes(self):
        self.checkpoint['same:repair']['diagnostic_revision'] = 2
        invalid = dict(event_groups=self.payload['event_groups'][:1])
        call = Mock(return_value=(invalid, 'same-model'))
        for revision in (3, 3, 4):
            with patch.object(repair, 'DIAGNOSTIC_REVISION', revision):
                with self.assertRaises(agent.NewsSelectionQualityBlocked):
                    self.run_repair(call)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(self.checkpoint['same:repair']['requests'], 4)
        self.assertEqual(self.checkpoint['same:repair']['attempt_history'][:3], self.old['attempt_history'])

    def test_revision_two_weekly_schema_has_one_migration_with_original_ledger(self):
        self.checkpoint['same:repair']['diagnostic_revision'] = 2
        before = copy.deepcopy(self.checkpoint['same:repair'])
        call = Mock(return_value=(self.valid_pair, 'streamed-model'))
        result, _ = self.run_repair(call)
        state = self.checkpoint['same:repair']
        migration = state['diagnostic_migration']
        self.assertEqual((migration['from_revision'], migration['to_revision']), (2, 3))
        self.assertEqual(migration['requests_before'], 3)
        self.assertEqual(migration['scope_attempts_before'], before['scope_attempts'])
        self.assertEqual(migration['news_attempts_before'], before['news_attempts'])
        self.assertEqual(state['attempt_history'][:3], before['attempt_history'])
        self.assertEqual(state['requests'], 4)
        agent._normalized_acceptance_review(result, self.targets, self.provisional)
        self.run_repair(call)
        self.assertEqual(call.call_count, 1)

    def test_already_validated_migration_checkpoint_is_unchanged_with_cached_payload(self):
        valid = copy.deepcopy(self.payload)
        valid['event_groups'][0] = self.valid_pair['event_groups'][0]
        self.checkpoint['same:repair'].update(draft=valid, diagnostic_revision=2,
            blocked=False, status='validated', requests=4,
            diagnostic_migration={'used': True, 'from_revision': 1, 'to_revision': 2})
        self.args['cached'] = {'payload': valid, 'model': 'prior-model'}
        before = copy.deepcopy(self.checkpoint)
        call = Mock()
        self.run_repair(call)
        self.assertEqual(self.checkpoint, before)
        call.assert_not_called()

    def test_network_failure_consumes_migration_before_inference(self):
        call = Mock(side_effect=ConnectionError('interrupted'))
        with self.assertRaises(ConnectionError):
            self.run_repair(call)
        with self.assertRaises(agent.NewsSelectionQualityBlocked):
            self.run_repair(call)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(self.checkpoint['same:repair']['requests'], 4)

    def test_total_budget_and_current_diagnostics_cannot_be_bypassed(self):
        for changes in ({'requests':12}, {'diagnostic_revision':repair.DIAGNOSTIC_REVISION}, {'attempt_history':[]}):
            with self.subTest(changes=changes):
                self.checkpoint['same:repair'] = dict(copy.deepcopy(self.old), **changes)
                call = Mock()
                with self.assertRaises(agent.NewsSelectionQualityBlocked):
                    self.run_repair(call)
                call.assert_not_called()

    def test_existing_draft_is_validated_before_consuming_any_allowance(self):
        self.checkpoint['same:repair']['draft']['event_groups'][0] = self.valid_pair['event_groups'][0]
        call = Mock()
        self.run_repair(call)
        call.assert_not_called()
        self.assertEqual(self.checkpoint['same:repair']['requests'], 3)
        self.assertNotIn('diagnostic_migration', self.checkpoint['same:repair'])
        self.assertFalse(self.checkpoint['same:repair']['blocked'])


class ExhaustedStateTests(unittest.TestCase):
    def test_completed_sheet_write_only_retries_missing_local_receipts(self):
        now = datetime(2026, 9, 11, 9, 0, tzinfo=briefing.HKT)
        slot = '2026-09-11@03:00'
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / '2026-09-11@03-00.json'
            path.write_text(json.dumps(dict(slot=slot, status='completed', completed_at=now.isoformat(),
                task_run_id='parent', message_id='original', selection_agent=dict(status='completed',
                readback_verified=True, task_run_id='child'), selection_agent_recovery=dict(status='completed'))))
            state = dict(selection_agent_retries={slot: dict(attempts=13, next_retry_at='stale', error='old',
                                                            outcome_synchronized=False)})
            with (patch.object(briefing, 'RUNS_DIR', Path(td)),
                  patch.object(briefing, 'amend_operational_crawl_run', autospec=True) as amend,
                  patch('cmhk.intelligence.news_review_sheet.complete_selection_batch',
                        side_effect=[OSError('temporary'), None]) as complete,
                  patch.object(agent, 'run_news_selection_agent') as run):
                briefing._recover_pending_selection_agents(now, state)
                self.assertFalse(state['selection_agent_retries'][slot]['outcome_synchronized'])
                briefing._recover_pending_selection_agents(now, state)
                briefing._recover_pending_selection_agents(now, state)
            self.assertEqual(complete.call_count, 2)
            self.assertIn('逐格回读', amend.call_args.kwargs['progress_detail'])
            self.assertEqual(amend.call_args.kwargs['summary_updates']['selection_agent_error'], '')
            self.assertEqual(amend.call_args.kwargs['summary_updates']['selection_agent_next_retry_at'], '')
            self.assertTrue(state['selection_agent_retries'][slot]['outcome_synchronized'])
            self.assertEqual(json.loads(path.read_text())['message_id'], 'original')
            run.assert_not_called()

    def test_exhausted_state_reconciles_all_routes_without_model_or_send(self):
        now = datetime(2026, 9, 11, 9, 0, tzinfo=briefing.HKT)
        slot = '2026-09-11@03:00'
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / '2026-09-11@03-00.json'
            path.write_text(json.dumps(dict(slot=slot, status='completed', completed_at=now.isoformat(),
                task_run_id='parent', message_id='original', selection_agent=dict(status='retry_pending'),
                review_sheet=dict(readback_verified=True, sheet_id='s', new_items=[dict(news_id='N-1')]))))
            state = dict(selection_agent_retries={slot: dict(attempts=12, next_retry_at='stale', error='duplicate')})
            with (patch.object(briefing, 'RUNS_DIR', Path(td)),
                  patch.object(briefing, 'amend_operational_crawl_run') as amend,
                  patch('cmhk.intelligence.news_review_sheet.fail_selection_batch') as fail,
                  patch.object(agent, 'run_news_selection_agent') as run):
                self.assertEqual(briefing._recover_pending_selection_agents(now, state), [])
                self.assertEqual(briefing._recover_pending_selection_agents(now, state), [])
            updated = json.loads(path.read_text())
            self.assertEqual(updated['message_id'], 'original')
            self.assertEqual(updated['selection_agent']['status'], 'exhausted')
            self.assertEqual(updated['selection_agent_recovery']['next_retry_at'], '')
            self.assertIn('已停止', state['last_selection_agent_error'])
            run.assert_not_called()
            amend.assert_called_once()
            fail.assert_called_once()
            self.assertFalse(fail.call_args.kwargs['record_attempt'])


if __name__ == '__main__':
    unittest.main()

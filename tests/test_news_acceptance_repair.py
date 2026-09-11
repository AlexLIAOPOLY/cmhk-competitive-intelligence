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
                  patch.object(briefing, 'amend_operational_crawl_run') as amend,
                  patch('cmhk.intelligence.news_review_sheet.complete_selection_batch',
                        side_effect=[OSError('temporary'), None]) as complete,
                  patch.object(agent, 'run_news_selection_agent') as run):
                briefing._recover_pending_selection_agents(now, state)
                self.assertFalse(state['selection_agent_retries'][slot]['outcome_synchronized'])
                briefing._recover_pending_selection_agents(now, state)
                briefing._recover_pending_selection_agents(now, state)
            self.assertEqual(complete.call_count, 2)
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

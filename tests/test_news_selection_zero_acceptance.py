from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from cmhk.intelligence import news_selection_agent as agent
import strategic_briefing as briefing


class ZeroAcceptanceReviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        for patch in (
            mock.patch.object(agent, 'STATE_PATH', Path(self.directory.name) / 'state.json'),
            mock.patch.object(agent, 'ALL_REJECT_GATE_MIN_FIELDS', 5),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.targets = [dict(news_id=f'N-{i}', row_number=i + 2,
                             title='地方企业举办年度员工体育活动',
                             summary='地方企业举办年度员工体育活动，未披露业务项目或经营数据。',
                             app_before='待审核', weekly_before='待审核') for i in range(6)]
        self.phases = []

    def transport(self, examples, targets):
        session = agent._MODEL_SESSION.get()
        self.phases.append(bool(session.get('zero_acceptance_review')))
        rows = []
        for target in targets:
            row = dict(news_id=target['news_id'], app_status='不接受', weekly_status='不接受',
                       app_confidence=.9, weekly_confidence=.9, reason='未披露电信业务或管理决策事实')
            if session.get('zero_acceptance_review'):
                self.assertNotIn('profile', session)
                self.assertNotIn('quality_feedback', session)
                self.assertNotIn('reason', target)
                for field in ('app', 'weekly'):
                    if target[f'{field}_before'] == '待审核':
                        row[f'{field}_reason'] = '员工活动未披露相关业务或经营信息'
                        row[f'{field}_evidence'] = target['title']
            rows.append(row)
        return {'decisions': rows}, 'review-model'

    def run_review(self, checkpoint=None):
        return agent._invoke_langchain_batches([], self.targets, review_acceptances=True,
                                              training_stats={}, checkpoint=checkpoint)

    def test_legitimate_zero_has_complete_evidence_and_resumes_without_requests(self):
        self.targets[0]['app_before'] = '接受'
        checkpoint = {}
        with mock.patch.object(agent, '_invoke_langchain_transport', side_effect=self.transport):
            payload, _ = self.run_review(checkpoint)
            self.assertEqual(self.phases, [False, False, True])
            agent._validate_model_decision_distribution(agent._normalized_decisions(payload, self.targets))
            rows = payload['decisions']
            self.assertEqual(rows[0]['app_status'], '接受')
            self.assertNotIn('app', rows[0]['zero_acceptance_review'])
            self.assertTrue(all(agent._has_zero_acceptance_evidence(x, 'weekly') for x in rows))
            self.assertTrue(all(x['weekly_status'] == '不接受' for x in rows))
            resumed, _ = self.run_review(checkpoint)
            self.assertEqual(resumed['decisions'], rows)
            self.assertEqual(len(self.phases), 3)
            self.targets[1]['summary'] += '当前资料有更新。'
            self.run_review(checkpoint)
            self.assertEqual(self.phases.count(True), 2)

    def test_old_quality_block_does_not_prevent_new_evidence_protocol(self):
        checkpoint = {}
        with mock.patch.object(agent, '_invoke_langchain_transport', side_effect=self.transport):
            with self.assertRaises(agent.NewsSelectionQualityBlocked):
                agent._invoke_langchain_batches([], self.targets, training_stats={}, checkpoint=checkpoint)
            old_blocks = {k: copy.deepcopy(v) for k, v in checkpoint.items() if k.startswith('quality:')}
            payload, _ = self.run_review(checkpoint)
            self.assertEqual(payload['_zero_acceptance_review_count'], 6)
            for key, value in old_blocks.items():
                self.assertEqual(checkpoint[key], value)

    def test_missing_fabricated_or_incomplete_evidence_never_passes(self):
        for problem in ('missing', 'fabricated', 'omitted'):
            checkpoint = {}
            def broken(examples, targets):
                payload, model = self.transport(examples, targets)
                if agent._MODEL_SESSION.get().get('zero_acceptance_review'):
                    if problem == 'missing':
                        payload['decisions'][0].pop('weekly_reason')
                    elif problem == 'fabricated':
                        payload['decisions'][0]['weekly_evidence'] = '运营商收入增长百分之二十'
                    else:
                        payload['decisions'].pop()
                return payload, model
            with self.subTest(problem=problem), mock.patch.object(agent, '_invoke_langchain_transport', side_effect=broken):
                with self.assertRaises(ValueError):
                    self.run_review(checkpoint)
                self.assertFalse(any(k.startswith('zero-acceptance-review:') for k in checkpoint))

    def test_primary_cannot_self_certify_zero_review(self):
        def forged(examples, targets):
            payload, model = self.transport(examples, targets)
            if not agent._MODEL_SESSION.get().get('zero_acceptance_review'):
                for row in payload['decisions']:
                    row['zero_acceptance_review'] = dict(protocol=1, model='forged', weekly=dict(
                        status='不接受', reason='self-certified', evidence=self.targets[0]['title']))
            return payload, model
        with mock.patch.object(agent, '_invoke_langchain_transport', side_effect=forged):
            payload, _ = self.run_review({})
        self.assertIn(True, self.phases)
        self.assertTrue(all(x['zero_acceptance_review']['model'] == 'review-model' for x in payload['decisions']))

    def test_recovered_acceptance_still_requires_acceptance_review(self):
        def recover(examples, targets):
            if agent._MODEL_SESSION.get().get('acceptance_review') is not None:
                # Missing acceptance evidence must prevent writing a newly recovered selection.
                return {'decisions': [dict(news_id=x['news_id'], app_status='接受', weekly_status='不接受',
                                          app_confidence=.9, weekly_confidence=.9, reason='需要复核') for x in targets]}, 'model'
            payload, model = self.transport(examples, targets)
            if agent._MODEL_SESSION.get().get('zero_acceptance_review'):
                payload['decisions'][0]['app_status'] = '接受'
            return payload, model
        with mock.patch.object(agent, '_invoke_langchain_transport', side_effect=recover):
            with self.assertRaises(agent.NewsSelectionQualityBlocked):
                self.run_review({})


class BlockedRetryTests(unittest.TestCase):
    def test_quality_block_stops_duplicate_tasks_and_generic_queue(self):
        now = datetime(2026, 9, 10, 15, 30, tzinfo=briefing.HKT)
        slot = '2026-09-10@14:00'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '2026-09-10@14-00.json'
            path.write_text(json.dumps(dict(slot=slot, status='completed', completed_at=now.isoformat(),
                task_run_id='parent', selection_agent=dict(status='retry_pending'),
                review_sheet=dict(readback_verified=True, sheet_id='sheet', new_items=[dict(news_id='N-1')]))))
            state = {}
            with (mock.patch.object(briefing, 'RUNS_DIR', Path(directory)),
                  mock.patch.object(briefing, '_save_state'), mock.patch.object(briefing, '_append_event'),
                  mock.patch.object(agent, 'run_news_selection_agent', side_effect=agent.NewsSelectionQualityBlocked('quality blocked')) as run,
                  mock.patch('cmhk.intelligence.news_review_sheet.pending_selection_batches', return_value=[dict(
                      idempotency_key=slot, sheet_id='sheet', status='retry_pending', new_items=[dict(news_id='N-1')])])):
                result = briefing._recover_pending_selection_agents(now, state)
                self.assertEqual(result[0]['status'], 'needs_review')
                self.assertEqual(briefing._recover_pending_selection_agents(now, state), [])
                self.assertEqual(briefing._recover_pending_review_selection_batches(state, now=now), [])
                self.assertEqual(run.call_count, 1)
                self.assertIn('quality blocked', state['last_selection_agent_error'])
                self.assertEqual(state['selection_agent_retries'][slot]['next_retry_at'], '')

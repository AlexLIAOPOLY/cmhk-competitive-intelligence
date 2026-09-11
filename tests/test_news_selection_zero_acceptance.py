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
            self.assertEqual(self.phases, [False, False, True, True])
            agent._validate_model_decision_distribution(agent._normalized_decisions(payload, self.targets))
            rows = payload['decisions']
            self.assertEqual(rows[0]['app_status'], '接受')
            self.assertNotIn('app', rows[0]['zero_acceptance_review'])
            self.assertTrue(all(agent._has_zero_acceptance_evidence(x, 'weekly') for x in rows))
            self.assertTrue(all(x['weekly_status'] == '不接受' for x in rows))
            resumed, _ = self.run_review(checkpoint)
            self.assertEqual(resumed['decisions'], rows)
            self.assertEqual(len(self.phases), 4)
            self.targets[1]['summary'] += '当前资料有更新。'
            self.run_review(checkpoint)
            self.assertEqual(self.phases.count(True), 3)

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
                with self.assertRaises(agent.NewsSelectionQualityBlocked):
                    self.run_review(checkpoint)
                self.assertFalse(any(k.startswith('zero-acceptance-review:') and v.get('payload') for k,v in checkpoint.items()))
                progress=next(v for k,v in checkpoint.items() if k.endswith(':progress'))
                self.assertEqual(progress['requests'],3)
                self.assertEqual(progress['repairs'],2)
                batch=next(iter(progress['batches'].values()))
                self.assertEqual(len(batch['attempt_history']),3)
                self.assertIsInstance(batch['attempt_history'][0]['response'],dict)

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

    def test_large_zero_review_is_bounded_and_preserves_nonpending_fields(self):
        self.targets = [dict(self.targets[0], news_id=f'N-{i}', app_before='接受') for i in range(179)]
        self.targets[0]['weekly_before'] = '接受'
        payload = {'decisions': [dict(news_id=t['news_id'], app_status='接受', weekly_status='不接受',
            app_confidence=.9, weekly_confidence=.9, reason='原机器判断') for t in self.targets]}
        checkpoint, calls = {}, []
        def bounded(examples, targets):
            calls.append([t['news_id'] for t in targets])
            if len(targets)>30:
                raise agent.TruncatedModelOutput('whole-batch evidence cannot fit')
            return self.transport(examples, targets)
        token = agent._MODEL_SESSION.set({'preferences':False, 'quality_feedback':'prior'})
        try:
            with mock.patch.object(agent, 'MODEL_BATCH_SIZE', 100), mock.patch.object(agent, '_invoke_langchain', side_effect=bounded):
                result = agent._review_zero_acceptances([], self.targets, payload, checkpoint=checkpoint)
        finally:
            agent._MODEL_SESSION.reset(token)
        self.assertEqual([len(batch) for batch in calls], [30]*5+[28])
        self.assertEqual({n for batch in calls for n in batch}, {t['news_id'] for t in self.targets[1:]})
        self.assertEqual(len(result['decisions']),179)
        self.assertTrue(all(x['app_status']=='接受' for x in result['decisions']))
        self.assertEqual(result['decisions'][0]['weekly_status'],'接受')
        self.assertTrue(all(agent._has_zero_acceptance_evidence(x,'weekly') for x in result['decisions'][1:]))

    def test_truncation_or_interruption_resumes_only_unfinished_chunks(self):
        self.targets = [dict(self.targets[0], news_id=f'N-{i}') for i in range(40)]
        payload = {'decisions': [dict(news_id=t['news_id'], app_status='不接受', weekly_status='不接受',
            app_confidence=.9, weekly_confidence=.9, reason='原判断') for t in self.targets]}
        for failure in (ConnectionError, agent.TruncatedModelOutput):
            with self.subTest(failure=failure.__name__):
                checkpoint, calls, persisted = {}, [], []
                def interrupted(examples, targets):
                    calls.append([t['news_id'] for t in targets])
                    if len(calls)==2:
                        raise failure('only unfinished chunk may resume')
                    return self.transport(examples, targets)
                token=agent._MODEL_SESSION.set({'preferences':False,'quality_feedback':'prior'})
                try:
                    with mock.patch.object(agent,'MODEL_BATCH_SIZE',5), mock.patch.object(agent,'_invoke_langchain',side_effect=interrupted):
                        if failure is ConnectionError:
                            with self.assertRaises(failure):
                                agent._review_zero_acceptances([],self.targets,payload,checkpoint=checkpoint,
                                    checkpoint_callback=lambda *args:persisted.append(copy.deepcopy(checkpoint)))
                        else:
                            agent._review_zero_acceptances([],self.targets,payload,checkpoint=checkpoint,
                                checkpoint_callback=lambda *args:persisted.append(copy.deepcopy(checkpoint)))
                        first_checkpoint=copy.deepcopy(checkpoint)
                        self.assertTrue(any(v.get('payload') for v in first_checkpoint.values()))
                        self.assertEqual(persisted[-1],first_checkpoint)
                        result=agent._review_zero_acceptances([],self.targets,payload,checkpoint=checkpoint)
                        for key,value in first_checkpoint.items():
                            if value.get('payload'):
                                self.assertEqual(checkpoint[key],value)
                        agent._review_zero_acceptances([],self.targets,payload,checkpoint=checkpoint)
                finally:
                    agent._MODEL_SESSION.reset(token)
                self.assertEqual(len(calls),9)  # Eight chunks plus the one failed request.
                self.assertEqual(calls.count(calls[0]),1)
                self.assertEqual(calls[1],calls[2])
                self.assertEqual(len(result['decisions']),40)

    def test_terminal_quote_and_all_field_errors_use_the_same_source_matcher(self):
        targets=[dict(self.targets[0],title='2026全球工业互联网大会聚焦AI兴工')]
        token=agent._MODEL_SESSION.set({'zero_acceptance_review':1})
        try:
            payload,_=self.transport([],targets)
        finally:
            agent._MODEL_SESSION.reset(token)
        payload['decisions'][0]['weekly_evidence']=targets[0]['title']+'。'
        reviewed=agent._normalized_zero_acceptance_review(payload,targets)
        proof=reviewed[0]['zero_acceptance_review']['weekly']
        self.assertEqual(proof['evidence'],targets[0]['title']+'。')
        self.assertEqual(proof['source_evidence'],targets[0]['title'])
        payload['decisions'][0].update(app_reason='',app_evidence='捏造内容',weekly_evidence='另一篇无关标题')
        with self.assertRaises(ValueError) as caught:
            agent._normalized_zero_acceptance_review(payload,targets)
        for text in ('app','weekly','reason','evidence'):
            self.assertIn(text,str(caught.exception))

    def test_normal_chunks_do_not_consume_stage_repair_allowance(self):
        self.targets=[dict(self.targets[0],news_id=f'N-{i}') for i in range(179)]
        payload={'decisions':[dict(news_id=t['news_id'],app_status='不接受',weekly_status='不接受',
            app_confidence=.9,weekly_confidence=.9,reason='原判断') for t in self.targets]}
        checkpoint,counts={},{}
        def repair_three_chunks(examples,targets):
            key=targets[0]['news_id']; counts[key]=counts.get(key,0)+1
            result,model=self.transport(examples,targets)
            if key in ('N-0','N-18','N-36') and counts[key]==1:
                result['decisions'][0]['weekly_reason']=''
            elif counts[key]>1:
                feedback=agent._MODEL_SESSION.get()['zero_acceptance_review_repair']
                self.assertIn('weekly',feedback['validation_error'])
                self.assertEqual(feedback['unvalidated_draft']['decisions'][0]['weekly_reason'],'')
            return result,model
        token=agent._MODEL_SESSION.set({'preferences':False})
        try:
            with mock.patch.object(agent,'_invoke_langchain',side_effect=repair_three_chunks):
                result=agent._review_zero_acceptances([],self.targets,payload,checkpoint=checkpoint)
        finally:
            agent._MODEL_SESSION.reset(token)
        progress=next(v for k,v in checkpoint.items() if k.endswith(':progress'))
        self.assertEqual(progress['batch_count'],10)
        self.assertEqual(progress['requests'],13)
        self.assertEqual(progress['repairs'],3)
        self.assertEqual(len(result['decisions']),179)

    def test_stage_repair_budget_cannot_be_reset_by_resume(self):
        progress={'repairs':12,'batches':{'failed':{'requests':1,'last_error':'missing evidence'}}}
        token=agent._MODEL_SESSION.set({'preferences':False})
        try:
            with mock.patch.object(agent,'_invoke_langchain') as invoke:
                for _ in range(2):
                    with self.assertRaises(agent.NewsSelectionQualityBlocked):
                        agent._review_zero_batch([],self.targets,progress=progress,batch_key='failed',
                            save=lambda:None,session=agent._MODEL_SESSION.get())
                invoke.assert_not_called()
        finally:
            agent._MODEL_SESSION.reset(token)
        self.assertEqual(progress['repairs'],12)

    def test_validated_progress_recovers_before_main_batch_cache_is_saved(self):
        payload={'decisions':[dict(news_id=t['news_id'],app_status='不接受',weekly_status='不接受',
            app_confidence=.9,weekly_confidence=.9,reason='原判断') for t in self.targets]}
        checkpoint,calls={},[]
        def invoke(examples,targets):
            calls.append([t['news_id'] for t in targets])
            return self.transport(examples,targets)
        def crash_after_atomic_progress(*args):
            progress=next((v for k,v in checkpoint.items() if k.endswith(':progress')), {})
            if any(v.get('status')=='validated' and v.get('payload') for v in progress.get('batches',{}).values()):
                raise ConnectionError('crash before caller copies main batch cache')
        token=agent._MODEL_SESSION.set({'preferences':False})
        try:
            with mock.patch.object(agent,'_invoke_langchain',side_effect=invoke):
                with self.assertRaises(ConnectionError):
                    agent._review_zero_acceptances([],self.targets,payload,checkpoint=checkpoint,
                        checkpoint_callback=crash_after_atomic_progress)
                self.assertFalse(any(v.get('payload') for v in checkpoint.values()))
                progress=next(v for k,v in checkpoint.items() if k.endswith(':progress'))
                self.assertTrue(next(iter(progress['batches'].values()))['payload'])
                result=agent._review_zero_acceptances([],self.targets,payload,checkpoint=checkpoint)
                self.assertEqual(len(result['decisions']),6)
                self.assertEqual(len(calls),2)
                progress=next(v for k,v in checkpoint.items() if k.endswith(':progress'))
                self.assertEqual(progress['requests'],2)
        finally:
            agent._MODEL_SESSION.reset(token)

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

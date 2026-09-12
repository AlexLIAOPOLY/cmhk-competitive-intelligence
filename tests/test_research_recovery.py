import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from data_curation import daily_research as daily, research_recovery as recovery
from data_curation.research_model import ResearchChatDeepSeek
from ai_rate_limit import RateLimitedChatDeepSeek
from ai_key_rotation import APIKeyPoolUnavailable
import executive_intelligence_pipeline as pipeline
from tests.ai_stream_fixture import sse_response


class RecoveryTests(unittest.TestCase):
    def test_empty_slot_wrong_target_reopens_saved_missing_conclusion(self):
        from data_curation.research_final_review import review_run
        from data_curation.research_contracts import VERSION
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'agent_knowledge/hk_competitor_product_tariffs/local_financial_results.json'
            source.parent.mkdir(parents=True)
            source.write_text(json.dumps({'reports': [{'company': 'HKT', 'period': 'FY2025',
                'metrics': [{'metric_key': 'revenue', 'value': None, 'unit': 'millions HKD'}]}]}))
            run = root / 'curation_data/research_runs/test'
            run.mkdir(parents=True)
            task = {'key': 'hong-kong', 'title': '香港', 'companies': ['HKT']}
            report = {'company': 'HKT', 'metrics': ['收入'], 'status': 'partial', 'contract_version': VERSION,
                'review_completed': True, 'reviewed_metrics': ['收入'], 'review_search_completed': True,
                'baseline': {'_contracts': {'收入': {'enabled': True, 'has_baseline': False, 'target_period_end': '2026-12-31'}}},
                'pages': {}, 'items': [{'company': 'HKT', 'metric': '收入', 'status': 'missing', 'reason': '未来全年未发布'}]}
            (run / 'manifest.json').write_text(json.dumps({'run_id': 'test', 'plan': [task]}))
            (run / 'hong-kong.json').write_text(json.dumps({**task, 'reports': [report]}))
            collector = Mock(return_value=({'official': {'opened': True, 'official': True, 'text': 'HKT annual revenue'}}, []))
            harness = Mock()
            harness.extract.side_effect = lambda c,m,p,save,**kw: save({'company':c,'metric':m,'status':'missing','reason':'已检查正确年度'})
            review_run(run, model_factory=lambda: None, collector=collector, harness_factory=lambda *args: harness)
            collector.assert_called_once()
            self.assertEqual(collector.call_args.args[3]['_contracts']['收入']['target_period_end'], '2025-12-31')
            harness.extract.assert_called_once()

    def test_incomplete_model_output_remains_pending_with_a_finite_budget(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            for reason in ['模型输出被截断；本次未提交任何记录', '工具参数不完整',
                           '响应未正常完成', '模型未使用结构化提交工具']:
                with self.subTest(reason=reason):
                    (directory / 'candidate_facts.jsonl').write_text(json.dumps(
                        {'research_status':'error', 'reasons':[reason]}))
                    summary = {'publication':{'status':'completed'}, 'recovery':{'attempts':1}}
                    result = recovery.schedule(summary, directory, datetime.now(daily.HKT))
                    self.assertEqual(result['status'], 'retry_pending')
                    self.assertEqual(result['phase'], 'final_review')
                    summary['recovery']['attempts'] = recovery.MAX_ATTEMPTS
                    result = recovery.schedule(summary, directory, datetime.now(daily.HKT))
                    self.assertEqual(result['status'], 'exhausted')
                    self.assertEqual(result['next_retry_at'], '')

    def test_retry_budget_delays_and_cancel_survive_restarts(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            (directory / 'candidate_facts.jsonl').write_text(json.dumps({'research_status':'error','reasons':['APIKeyPoolUnavailable']}))
            now = datetime(2026, 9, 11, 10, tzinfo=daily.HKT)
            summary = {'publication': {'status':'completed'}, 'recovery': {'attempts':0}}
            for attempt in range(7):
                summary['recovery']['attempts'] = attempt
                summary['recovery'] = recovery.schedule(summary, directory, now)
                self.assertFalse(recovery.due(summary, now))
                self.assertEqual(recovery.due(summary, now + timedelta(hours=2)), attempt < 6)
            self.assertEqual(summary['recovery']['status'], 'exhausted')
            self.assertEqual(summary['recovery']['next_retry_at'], '')
            summary['publication']['cancelled_by_user'] = True
            self.assertEqual(recovery.schedule(summary, directory, now)['status'], 'cancelled')

    def test_quality_failure_is_not_a_network_retry(self):
        with tempfile.TemporaryDirectory() as td:
            summary = {'publication': {'status':'error','error':'审核资料存在口径冲突'}}
            self.assertEqual(recovery.schedule(summary, Path(td), datetime.now(daily.HKT))['status'], 'needs_review')
            for error in ['URLError: name or service not known', 'HTTP Error 500: Internal Server Error', 'unexpected EOF']:
                summary['publication']['error'] = error
                self.assertEqual(recovery.schedule(summary, Path(td), datetime.now(daily.HKT))['status'], 'retry_pending')
            summary['publication'] = {'status':'completed'}
            summary['recovery'] = {'status':'interrupted','attempts':2}
            self.assertEqual(recovery.schedule(summary, Path(td), datetime.now(daily.HKT))['status'], 'completed')

    def test_failed_publication_validation_replaces_stale_review_phase_without_retry(self):
        with tempfile.TemporaryDirectory() as td:
            now = datetime(2026, 9, 11, 11, tzinfo=daily.HKT)
            error = 'AI分析分类缺少输入数值证据：international.net_profit'
            summary = {
                'status': 'partial',
                'final_review': {'status': 'completed'},
                'publication': {'status': 'error', 'result_status': 'failed_validation',
                                'error': '', 'model_analysis': {'error': error}},
                'recovery': {'status': 'running', 'phase': 'final_review', 'attempts': 4,
                             'max_attempts': 6, 'next_retry_at': ''},
            }
            result = recovery.schedule(summary, Path(td), now)
            self.assertEqual(result, {
                'status': 'needs_review', 'phase': 'publication', 'attempts': 4,
                'max_attempts': 6, 'next_retry_at': '', 'error': error,
            })
            summary['recovery'] = result
            self.assertFalse(recovery.due(summary, now))
            self.assertFalse(recovery.due(summary, now + timedelta(days=1)))
            self.assertEqual(recovery.schedule(summary, Path(td), now + timedelta(days=1)), result)

    def test_unfinished_final_review_error_keeps_review_phase(self):
        with tempfile.TemporaryDirectory() as td:
            summary = {
                'final_review': {'status': 'error'},
                'publication': {'status': 'error', 'error': '最终审核资料存在口径冲突'},
                'recovery': {'status': 'running', 'phase': 'final_review', 'attempts': 4},
            }
            result = recovery.schedule(summary, Path(td), datetime.now(daily.HKT))
            self.assertEqual(result['status'], 'needs_review')
            self.assertEqual(result['phase'], 'final_review')
            self.assertEqual(result['attempts'], 4)
            self.assertEqual(result['next_retry_at'], '')

    def test_dead_worker_is_delayed_then_resumed_with_the_same_budget(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            directory = root / 'curation_data/research_runs/research_20260911'
            directory.mkdir(parents=True)
            summary = {'publication': {'status':'running'}, 'recovery': {'status':'running','attempts':2}}
            (directory / 'manifest.json').write_text(json.dumps(summary))
            now = datetime(2026, 9, 11, 10, tzinfo=daily.HKT)
            with (patch.object(daily, 'running_worker', return_value=False),
                  patch.object(daily, 'worker_python', side_effect=AssertionError('wait before restarting'))):
                result = daily.dispatch(root, now)
            self.assertEqual(result['recovery']['status'], 'retry_pending')
            self.assertEqual(result['recovery']['attempts'], 2)
            saved = json.loads((directory / 'manifest.json').read_text())
            self.assertTrue(recovery.due(saved, now + timedelta(minutes=11)))

    def test_retry_keeps_original_model_proof_rejected_by_old_preflight(self):
        from data_curation.research_contracts import VERSION
        from data_curation.research_final_review import review_run
        from data_curation.review_store import ReviewStore
        from tests.test_research_kpi import tables
        from tests.test_research_storage import fact
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tables(root)
            directory = root / 'curation_data/research_runs/research_test'
            directory.mkdir(parents=True)
            task = {'key':'hong-kong','title':'香港','companies':['HKT']}
            original = fact(research_status='conflict', decision='review',
                preflight_original={'decision':'accepted','status':'ok','research_status':'verified'},
                write_preflight={'status':'rejected','reason':'old unit notation'})
            summary = {'run_id':'research_test','plan':[task], 'status':'partial','final_review':{'status':'completed'}}
            (directory / 'manifest.json').write_text(json.dumps(summary))
            (directory / 'candidate_facts.jsonl').write_text(json.dumps(original))
            report = {'company':'HKT','status':'partial','metrics':['收入'],'items':[{'company':'HKT','metric':'收入','status':'conflict'}],
                      'pages':{},'review_completed':True,'reviewed_metrics':['收入'], 'contract_version': VERSION}
            (directory / 'hong-kong.json').write_text(json.dumps({**task,'reports':[report]}))
            store = ReviewStore(directory, {'key':'final-review'}, 'research_test', ['HKT'], 1)
            store.save(report, evidence_changed=True)
            store.complete()
            result = review_run(directory, retry_errors=True, model_factory=lambda: self.fail('proof already exists'))
            self.assertEqual(result['accepted'], 1)
            saved = json.loads((directory / 'verified_facts.jsonl').read_text())
            self.assertEqual(saved['evidence_hash'], original['evidence_hash'])
            self.assertEqual(saved['value'], original['value'])

    def test_publication_only_retry_does_not_repeat_research(self):
        from data_curation.research_contracts import VERSION
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            directory = root / 'curation_data/research_runs/research_20260911'
            directory.mkdir(parents=True)
            summary = dict(run_id='research_20260911', status='partial', architecture='six_research_agents_v1', contract_version=VERSION,
                           final_review={'status':'completed'}, publication={'status':'error','error':'timeout'})
            (directory / 'manifest.json').write_text(json.dumps(summary))
            registry = Mock()
            def publish_current_phase(**kwargs):
                live = json.loads((directory / 'manifest.json').read_text())
                self.assertEqual(live['recovery']['phase'], 'publication')
                self.assertEqual(live['recovery']['error'], '')
                self.assertEqual(live['final_review']['status'], 'completed')
                return {'ok': True, 'status': 'completed'}
            with (patch.object(daily, 'ROOT', root), patch.object(daily, '_live_registry', return_value=registry),
                  patch.object(daily, '_research_task_id', return_value='original'),
                  patch.object(daily, 'run_research', side_effect=AssertionError('must not replay research')),
                  patch('data_curation.research_final_review.review_run', side_effect=AssertionError('must not replay review')),
                  patch.object(pipeline, 'run_pipeline_with_recovery', side_effect=publish_current_phase) as publish):
                result = daily.execute(root, summary['run_id'])
            self.assertEqual(result['recovery']['status'], 'completed')
            self.assertEqual(result['recovery']['attempts'], 1)
            registry.resume_crawl_run.assert_called_once()
            self.assertEqual(publish.call_args.kwargs['task_run_id'], 'original')

    def test_model_route_keeps_tool_options_and_never_changes_original_model(self):
        model = ResearchChatDeepSeek(model='primary', api_key='test', base_url='https://example.test', max_retries=0)
        routes = []
        def generate(candidate, messages, **kwargs):
            routes.append((candidate.model_name, kwargs))
            if candidate.model_name == 'primary':
                raise APIKeyPoolUnavailable(120, 3)
            return 'model-result'
        with (patch('data_curation.research_model.configured_research_models', return_value=['primary','backup']),
              patch.object(RateLimitedChatDeepSeek, '_generate', new=generate)):
            self.assertEqual(model._generate([], tools=['submit_metric']), 'model-result')
        self.assertEqual(routes, [('primary', {'tools':['submit_metric']}), ('backup', {'tools':['submit_metric']})])
        self.assertEqual(model.model_name, 'primary')

    def test_macro_refresh_reuses_only_matching_live_readback(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            macro = root / 'macro.json'
            macro.write_text('{"rows":[1]}')
            with (patch.object(pipeline, 'ROOT', root), patch.object(pipeline, 'MACRO_PATH', macro),
                  patch.object(pipeline, '_task_event'),
                  patch.object(pipeline, '_refresh_builder_domain', return_value={'ok':True,'validation':{'rows':1}}) as build):
                pipeline.refresh_research_macro('research_test')
                self.assertTrue(pipeline.refresh_research_macro('research_test')['reused'])
                self.assertEqual(build.call_count, 1)
                macro.write_text('{"rows":[2]}')
                pipeline.refresh_research_macro('research_test')
                self.assertEqual(build.call_count, 2)

    def test_valid_ai_domain_survives_later_failure_without_model_replay(self):
        evidence = {'domains':[{'id':'local','focuses':[]}, {'id':'cloud','focuses':[]}]}
        calls = []
        fail = True
        def request(req, **kwargs):
            body = json.loads(req.data)
            domain = 'local' if '只分析 local' in body['messages'][1]['content'] else 'cloud'
            calls.append(domain)
            if domain == 'cloud' and fail:
                raise TimeoutError('temporary timeout')
            return sse_response({'items':[
                {'domain':domain, 'headline':'经营结构', 'analysis':'市场存在差异', 'risk':'口径不同', 'focuses':[], 'source_urls':[]}
            ]}, model=body['model'])
        with tempfile.TemporaryDirectory() as td:
            checkpoint = Path(td) / 'ai.json'
            with (patch('ai_config.load_ai_config', return_value={'api_key':'test'}),
                  patch('ai_rate_limit.wait_for_internal_ai_slot'), patch.object(pipeline, 'open_llm_request', side_effect=request)):
                with self.assertRaisesRegex(ValueError, 'temporary timeout'):
                    pipeline.generate_model_domain_summaries(evidence, checkpoint_path=checkpoint)
                fail = False
                result = pipeline.generate_model_domain_summaries(evidence, checkpoint_path=checkpoint)
            self.assertEqual(calls, ['local', 'cloud', 'cloud', 'cloud', 'cloud'])
            self.assertEqual([s['domain'] for s in result['summaries']], ['local','cloud'])

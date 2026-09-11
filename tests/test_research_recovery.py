import io
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


class RecoveryTests(unittest.TestCase):
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

    def test_publication_only_retry_does_not_repeat_research(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            directory = root / 'curation_data/research_runs/research_20260911'
            directory.mkdir(parents=True)
            summary = dict(run_id='research_20260911', status='partial', architecture='six_research_agents_v1',
                           final_review={'status':'completed'}, publication={'status':'error','error':'timeout'})
            (directory / 'manifest.json').write_text(json.dumps(summary))
            registry = Mock()
            with (patch.object(daily, 'ROOT', root), patch.object(daily, '_live_registry', return_value=registry),
                  patch.object(daily, '_research_task_id', return_value='original'),
                  patch.object(daily, 'run_research', side_effect=AssertionError('must not replay research')),
                  patch('data_curation.research_final_review.review_run', side_effect=AssertionError('must not replay review')),
                  patch.object(pipeline, 'run_pipeline_with_recovery', return_value={'ok':True,'status':'completed'}) as publish):
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
            return io.BytesIO(json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'items':[
                {'domain':domain, 'headline':'经营结构', 'analysis':'市场存在差异', 'risk':'口径不同', 'focuses':[], 'source_urls':[]}
            ]})}}]}).encode())
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

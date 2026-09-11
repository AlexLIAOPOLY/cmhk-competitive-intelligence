import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from cmhk.services.news_digest_editor import prepare_digest


class NewsDigestEditorTests(unittest.TestCase):
    def setUp(self):
        # This suite tests editorial transport/cache behavior. Source-grounded
        # quality and real integration are covered in test_news_summary_quality.
        quality = patch('cmhk.services.news_digest_editor.review_summaries', return_value=[])
        quality.start()
        self.addCleanup(quality.stop)

    def test_recipient_subset_reuses_exact_source_prose_without_another_model_call(self):
        overview = '运营商推出面向企业的新套餐，产品竞争进一步聚焦企业服务。具体定价与客户采用情况仍需持续观察。'
        prose = {'summary': '运营商公布面向企业客户的新套餐，首批服务对象为制造企业。',
                 'analysis': '企业套餐可能带来差异化服务竞争，需跟踪价格、服务范围及客户采用情况，尚不能判断收入影响。'}
        items = [{'title': '企业套餐甲', 'source_summary': '已核实事件甲'},
                 {'title': '企业套餐乙', 'source_summary': '已核实事件乙'}]
        model = Mock(side_effect=[
            {'overview': overview, 'items': [{**prose, 'id': '0'}, {**prose, 'id': '1'}]},
            {'overview': overview, 'items': [{**prose, 'id': '0'}]},
        ])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_digest(items, root, model_call=model)
            selected = prepare_digest([items[1]], root, model_call=model)
            self.assertEqual(selected['items'][0]['digest_summary'], prose['summary'])
            self.assertEqual(model.call_count, 1)
            self.assertNotIn('overview', selected)
            # Equal title with corrected source evidence must be fully re-edited.
            prepare_digest([{**items[1], 'source_summary': '更正后的事实'}], root, model_call=model)
            self.assertEqual(model.call_args.kwargs['response_format']['json_schema']['name'], 'personal_news_editor')
            self.assertEqual(model.call_count, 2)

    def test_truncated_output_retries_with_larger_budget_before_caching(self):
        from cmhk.intelligence.agent_harness import TruncatedModelOutput
        output = {'overview': '运营商推出面向企业的新套餐，产品竞争进一步聚焦企业服务。具体定价与客户采用情况仍需持续观察。',
                  'items': [{'id': '0', 'summary': '运营商公布面向企业客户的新套餐，首批服务对象为制造企业。',
                             'analysis': '企业套餐可能带来差异化服务竞争，需跟踪价格、服务范围及客户采用情况，尚不能判断收入影响。'}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('strategic_briefing.DATA_DIR', root), patch(
                    'strategic_briefing._call_internal_ai_transport',
                    side_effect=[TruncatedModelOutput('truncated'), output]) as transport:
                result = prepare_digest([{'title': '企业套餐发布'}], root)
                self.assertEqual(result['status'], 'model_generated')
                self.assertEqual(transport.call_count, 2)
                first, second = transport.call_args_list
                self.assertGreater(second.kwargs['max_tokens'], first.kwargs['max_tokens'])
                prepare_digest([{'title': '企业套餐发布'}], root)
                self.assertEqual(transport.call_count, 2)

    def test_caches_complete_editorial_result_without_changing_news_identity(self):
        items = [{'title': '运营商发布新套餐', 'url': 'https://example.test/1', 'summary': '新套餐面向企业。'}]
        output = {'overview': '运营商推出面向企业的新套餐，产品竞争进一步聚焦企业服务。具体定价与客户采用情况仍需持续观察。',
                  'items': [{'id': '0', 'summary': '运营商公布面向企业客户的新套餐，现有资料尚未披露资费与生效日期。',
                             'analysis': '企业套餐可能带来差异化服务竞争，需跟踪价格、服务范围及客户采用情况，尚不能判断收入影响。'}]}
        model = Mock(return_value=output)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = prepare_digest(items, root, model_call=model)
            second = prepare_digest(items, root, model_call=model)
            self.assertEqual(first, second)
            self.assertEqual(first['items'][0]['url'], items[0]['url'])
            self.assertEqual(first['items'][0]['title'], items[0]['title'])
            self.assertEqual(model.call_count, 1)
            changed = [{**items[0], 'summary': '更正：该套餐仍在计划中。'}]
            prepare_digest(changed, root, model_call=model)
            self.assertEqual(model.call_count, 2)

    def test_incomplete_model_output_fails_before_cache_or_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                prepare_digest([{'title': '新闻'}], root, model_call=Mock(return_value={'overview': '太短', 'items': []}))
            self.assertEqual(list((root / 'var/subscriptions/news-editor').glob('*.json')), [])

    def test_malformed_batch_regenerates_real_single_results_and_resumes_completed_items(self):
        from strategic_briefing import AIInvalidStructuredResponse
        articles = [{'title': name, 'source_summary': name + '的已核实事实'} for name in ('新闻甲', '新闻乙')]
        calls, fail = [], True
        def model(system, user, **kwargs):
            payload = json.loads(user)
            if 'items' in payload:
                calls.append('batch')
                raise AIInvalidStructuredResponse('{"items":"malformed JSON"}', 'items 应为 array')
            article = payload['article']
            calls.append(article['title'])
            if fail and article['title'] == '新闻乙':
                raise TimeoutError('second article unavailable')
            self.assertEqual(kwargs['response_format']['json_schema']['name'], 'personal_news_editor_single')
            return {'id': '0', 'summary': article['title'] + '公布新的企业服务方案，首批服务对象为制造企业。'}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(TimeoutError):
                prepare_digest(articles, root, model_call=model)
            fail = False
            result = prepare_digest(articles, root, model_call=model)
            self.assertEqual(calls, ['batch', '新闻甲', '新闻乙', '新闻乙'])
            self.assertEqual([x['title'] for x in result['items']], ['新闻甲', '新闻乙'])
            self.assertTrue(all(x['digest_summary'].startswith(x['title']) for x in result['items']))
            prepare_digest(articles, root, model_call=model)
            self.assertEqual(len(calls), 4)

    def test_malformed_single_array_requires_new_valid_model_response(self):
        from strategic_briefing import AIInvalidStructuredResponse
        model = Mock(side_effect=[AIInvalidStructuredResponse('{"items":"broken"}', 'array required'),
                                  {'id': '0', 'summary': '运营商公布新的企业服务方案，首批服务对象为制造企业。'}])
        with tempfile.TemporaryDirectory() as directory:
            result = prepare_digest([{'title': '企业服务'}], Path(directory), model_call=model)
            self.assertEqual(result['status'], 'model_generated')
            self.assertEqual(model.call_count, 2)
            self.assertIn('article', json.loads(model.call_args.args[1]))

    def test_empty_digest_never_calls_model(self):
        model = Mock()
        self.assertEqual(prepare_digest([], Path('/unused'), model_call=model)['items'], [])
        model.assert_not_called()

    def test_editorial_commentary_is_rejected_before_caching(self):
        output = {'overview': '1. 企业服务：运营商计划推出工业园区专网试点，服务制造企业，具体商业化进展取决于后续试点安排与付费合同。',
                  'items': [{'id': '0', 'summary': '某团体提出创科教育倡议，应分开看既有预算与本次建议，不能写成已经获政府采纳。',
                             'analysis': '若倡议转为学校的常态课程，可能出现持续服务需求，但采购与预算安排仍是关键约束，需观察试点合同。'}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, '编辑提醒'):
                prepare_digest([{'title': '创科教育倡议'}], root, model_call=Mock(return_value=output))
            self.assertFalse((root / 'var/subscriptions/news-editor').exists())

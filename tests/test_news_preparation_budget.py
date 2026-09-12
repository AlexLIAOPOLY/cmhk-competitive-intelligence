import fcntl
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from cmhk.services.news_delivery_dedupe import deduplicate_for_delivery
from cmhk.services.news_preparation_budget import bounded_preparation, candidate_budget, deadline, expired, acquire_story_lock
from cmhk.services.news_push_skill import compatible_skill_hashes, skill_contract


class PreparationBudgetTests(unittest.TestCase):
    def test_nested_work_cannot_extend_total_deadline_and_context_is_reset(self):
        with patch('cmhk.services.news_preparation_budget.time.monotonic', return_value=100):
            @bounded_preparation
            def run():
                self.assertEqual(deadline(900), 700)
                with candidate_budget():
                    self.assertEqual(deadline(900), 280)
                    with patch('cmhk.services.news_preparation_budget.time.monotonic', return_value=281):
                        self.assertTrue(expired())
                self.assertEqual(deadline(900), 700)
            run()
            self.assertEqual(deadline(900), 1000)
            self.assertFalse(expired())

    def test_busy_shared_story_does_not_block_other_candidates(self):
        with tempfile.TemporaryFile() as handle:
            @bounded_preparation
            def run():
                with patch('cmhk.services.news_preparation_budget.fcntl.flock', side_effect=BlockingIOError), \
                     patch('cmhk.services.news_preparation_budget.time.monotonic', side_effect=[100, 106]):
                    with self.assertRaisesRegex(TimeoutError, '换选'):
                        acquire_story_lock(handle)
            run()

    def test_bad_dedupe_batch_is_skipped_without_recursive_model_fanout(self):
        items=[{'news_id':str(i),'title':'新闻 '+str(i),'summary':'不同主体发生各自事件 '+str(i)} for i in range(8)]
        calls=[]
        def model(system, prompt, **kwargs):
            data=json.loads(prompt);calls.append(data)
            if data['candidates'][0]['title']=='新闻 0':
                return {'decisions':[]}
            return {'decisions':[{'id':x['id'],'duplicate_of':'','reason':'不同事件'} for x in data['candidates']]}
        with tempfile.TemporaryDirectory() as root, patch('strategic_briefing._call_internal_ai_transport', side_effect=model):
            kept,audit=deduplicate_for_delivery(items,[],Path(root))
        self.assertEqual(kept,items[4:])
        self.assertEqual(len(calls),2)
        self.assertEqual(len(calls[-1]['history']),4)
        self.assertEqual(sum(x.get('status')=='skipped_review_error' for x in audit),4)

    def test_one_contradictory_row_does_not_discard_three_valid_reviews(self):
        items=[{'news_id':str(i),'title':'独立新闻 '+str(i),'summary':'各个不同企业分别发布产品 '+str(i)} for i in range(4)]
        rows=[{'id':'c'+str(i),'duplicate_of':'','reason':'不同事件'} for i in range(4)]
        rows[1].update(duplicate_of='c0',reason='不同事件，不应合并',evidence=items[1]['summary'],matched_evidence=items[0]['summary'])
        with tempfile.TemporaryDirectory() as root, patch('strategic_briefing._call_internal_ai_transport',return_value={'decisions':rows}) as model:
            kept,audit=deduplicate_for_delivery(items,[],Path(root))
        self.assertEqual(kept,[items[0],items[2],items[3]])
        self.assertEqual(audit[1]['status'],'skipped_review_error')
        self.assertEqual(audit[1]['news_id'],'1')
        model.assert_called_once()

    def test_fully_quoted_decisions_are_decoded_without_rewriting_or_model_retry(self):
        from strategic_briefing import AIInvalidStructuredResponse
        items=[{'title':'公司甲推出新产品','summary':'新产品首批覆盖工厂客户'}, {'title':'机场新增运输航线','summary':'航线每日执行两班'}]
        rows=[{'id':'c0','duplicate_of':'','reason':'不同事件'},{'id':'c1','duplicate_of':'','reason':'不同事件'}]
        error=AIInvalidStructuredResponse(json.dumps({'decisions':json.dumps(rows,ensure_ascii=False)},ensure_ascii=False),'decisions 应为 array')
        with tempfile.TemporaryDirectory() as root, patch('strategic_briefing._call_internal_ai_transport',side_effect=error) as model:
            kept,audit=deduplicate_for_delivery(items,[],Path(root))
        self.assertEqual(kept,items)
        self.assertEqual(audit,rows)
        model.assert_called_once()

    def test_delivery_replacement_checks_all_history_in_one_bounded_request(self):
        item={'news_id':'new','title':'新的机场建设计划','summary':'新机场计划新建两条跑道'}
        history=[{'news_id':str(i),'title':f'企业{i}独立项目','summary':f'第{i}个已发历史事件'} for i in range(25)]
        with tempfile.TemporaryDirectory() as root, patch('strategic_briefing._call_internal_ai_transport',return_value={'id':'c0','duplicate_of':'','reason':'新的独立事件','evidence':'','matched_evidence':''}) as model:
            kept,audit=deduplicate_for_delivery([item],history,Path(root))
        self.assertEqual(kept,[item])
        model.assert_called_once()
        self.assertEqual(len(json.loads(model.call_args.args[1])['history']),25)

    def test_quality_compatibility_is_exact_and_unknown_edits_invalidate(self):
        self.assertIn('6b9f1b4144950450749a9b85b9cd54ea1e6546dc2aaf5b4f202e3253dd228eb4',compatible_skill_hashes())
        with patch('cmhk.services.news_push_skill.skill_contract', return_value=('changed substantive rules','unknown')):
            self.assertEqual(compatible_skill_hashes(),('unknown',))

    def test_approved_asset_compatibility_requires_the_same_source_facts(self):
        from cmhk.services.news_delivery_assets import fingerprint, prepare_news_assets, save
        from cmhk.services.news_image_quality import compatible_policy_keys
        item={'title':'某公司新服务','summary':'服务面向制造企业','source_url':'https://example.org/article','published_at':'2026-09-12'}
        with tempfile.TemporaryDirectory() as root:
            root=Path(root); service=Mock(runtime_root=root)
            old=compatible_policy_keys()[1]
            key=fingerprint([old,item['source_url'],item['published_at'],'sender',item['title'],item['summary'],None])
            asset={'news_url':item['source_url'],'image_key':'img_approved','image_kind':'source',
                   'image_source_url':'https://example.org/photo.jpg','image_page_url':item['source_url'],
                   'image_sha256':'a'*64,'image_policy_key':old,'image_review_status':'accepted'}
            save(root/'var/subscriptions/news-assets'/(key+'.json'),asset)
            with patch('cmhk.services.news_delivery_assets.source_metadata',side_effect=AssertionError('must reuse approved proof')):
                self.assertEqual(prepare_news_assets([item],service,profile='sender',fallback_image_key='img_banner')[0]['image_key'],'img_approved')
                with self.assertRaises(AssertionError):
                    prepare_news_assets([{**item,'summary':'不同事实'}],service,profile='sender',fallback_image_key='img_banner')

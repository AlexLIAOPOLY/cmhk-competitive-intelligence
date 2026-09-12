"""Reader requirements across preferences, preparation slices and real receipts."""
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from cmhk.services.news_digest_editor import _validate, prepare_digest
from cmhk.services.news_summary_quality import SummaryQualityError
from cmhk.services.news_text import simplified_news_text
from cmhk.services.news_delivery_dedupe import exact_unique
from cmhk.services.news_delivery_guard import deliver_news
from cmhk.services.news_round_progress import reconcile_round, remaining_count, record_attempt
from cmhk.services.subscriptions import SubscriptionService, subscription_entry_card, filter_news_by_categories, HKT
from tests.news_push_fixtures import prepared_assets

class ReaderContractTests(unittest.TestCase):
    def test_100_is_allowed_101_rewrites_once_and_cached_output_is_simplified(self):
        item={'title':'企業推出新方案', 'source_summary':'面向製造業，新增庫存管理、工單調度和員工培訓。'}
        good='企業首批服務製造業，提供庫存管理及員工培訓，並保留 iPhone API 專名。'
        self.assertEqual(len(_validate({'items':[{'id':'0','summary':'甲'*100}]},[item])['items'][0]['digest_summary']),100)
        with self.assertRaises(SummaryQualityError):
            _validate({'items':[{'id':'0','summary':'甲'*101}]},[item])
        with tempfile.TemporaryDirectory() as tmp, patch('cmhk.services.news_digest_editor.review_summaries',return_value=[]) as review:
            model=Mock(side_effect=[{'items':[{'id':'0','summary':'甲'*101}]},{'items':[{'id':'0','summary':good}]}])
            result=prepare_digest([item],Path(tmp),model_call=model)
            self.assertEqual(model.call_count,2)
            self.assertIn('100字',json.loads(model.call_args.args[1])['revision_required'])
            self.assertEqual(result['items'][0]['digest_summary'],simplified_news_text(good))
            self.assertIn('iPhone API',result['items'][0]['digest_summary'])
            self.assertEqual(result['items'][0]['source_summary'],item['source_summary'])
            self.assertEqual(prepare_digest([item],Path(tmp),model_call=model),result)
            self.assertEqual(model.call_count,2)

    def test_two_overlength_results_stop_without_accepting_or_truncating(self):
        with tempfile.TemporaryDirectory() as tmp:
            model=Mock(return_value={'items':[{'id':'0','summary':'新'*101}]})
            with self.assertRaises(SummaryQualityError):prepare_digest([{'title':'新闻'}],Path(tmp),model_call=model)
            self.assertEqual(model.call_count,2)
            self.assertFalse(list((Path(tmp)/'var/subscriptions/news-editor').glob('*.json')))

    def test_region_persists_omitted_legacy_value_and_changes_all_sections_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            service=SubscriptionService(runtime_root=Path(tmp))
            service.save_subscriptions('ou_test','测试',['news'],news_region_preference='international',news_item_limit=20)
            service.update_subscriber('ou_test',services=['news'],news_item_limit=20)
            saved=service.list_summary()['subscribers'][0]
            self.assertEqual(saved['news_region_preference'],'international')
            self.assertEqual(saved['news_item_limit'],20)
            restarted=SubscriptionService(runtime_root=Path(tmp))
            self.assertEqual(restarted.list_summary()['subscribers'][0]['news_region_preference'],'international')
            with self.assertRaises(ValueError): service.update_subscriber('ou_test',services=['news'],news_region_preference='mainland')
        form=next(x for x in subscription_entry_card()['body']['elements'] if x['tag']=='form')
        field=next(x for x in form['elements'] if x.get('name')=='news_region_preference')
        self.assertEqual([x['value'] for x in field['options']],['hong_kong','international'])
        macro='宏观经济&国际形势&地缘政治&其他国际性质关注词汇'
        for category in ('公司动态',macro):
            pool=[{'news_id':'hk','category':category,'region':'香港本地'}, {'news_id':'world','category':category,'region':'国际/行业'}]
            self.assertEqual(filter_news_by_categories(pool,[category],limit=1,region_preference='international')[0]['news_id'],'world')
            self.assertEqual(filter_news_by_categories(pool,[category],limit=1,region_preference='hong_kong')[0]['news_id'],'hk')

    def test_transient_failures_are_not_misreported_as_exhausted_candidates(self):
        from cmhk.services.news_round_progress import excluded_items
        with tempfile.TemporaryDirectory() as tmp:
            service=SubscriptionService(runtime_root=Path(tmp))
            ref='strategic-crawl:2026-09-12@03:00'
            for _ in range(3):
                record_attempt(service,'ou_test',ref,{'news_id':'busy'},error='assets: TimeoutError: 其他准备任务处理中')
                record_attempt(service,'ou_test',ref,{'news_id':'wrong'},error='assets: ValueError: 图片属于另一家公司')
            with closing(service._connect()) as db:
                self.assertEqual(excluded_items(db,'ou_test',ref),{'wrong'})

    def test_six_of_twenty_resumes_after_restart_and_concurrent_reconcile_never_duplicates(self):
        now=datetime.now(HKT); day=now.date().isoformat(); ref='strategic-crawl:'+day+'@03:00'
        pool=[{'news_id':f'event{i}', 'title':f'独立企业{i}发布服务', 'category':'公司动态','published_at':day,
               'source_url':f'https://example.test/{i}', 'region':'香港本地', 'summary':f'首批服务覆盖制造企业，新增仓储调度和员工培训，第{i}项独立项目已启动。'} for i in range(20)]
        with tempfile.TemporaryDirectory() as tmp:
            service=SubscriptionService(runtime_root=Path(tmp))
            service.save_subscriptions('ou_test','测试',['news'],news_item_limit=20,news_categories=['公司动态'])
            service.dispatch_news_after_crawl(crawl_slot=day+'@03:00',slot_label='晨间扫描',items=pool,completed_at=day+'T06:00:00+08:00')
            def queued():
                with closing(service._connect()) as db:
                    return [dict(r) for r in db.execute("SELECT p.*,d.batch_id FROM pending_subscription_deliveries p JOIN deliveries d ON d.id=p.delivery_id WHERE p.status='queued'")]
            edited=[]
            def editor(items,root):edited.extend(items);return {'items':items,'summary_reviews':[]}
            def prepare(row):return deliver_news(service,open_id=row['open_id'],content_ref=ref,title=row['title'],body=row['body'],batch_id=row['batch_id'],profile=service.delivery_profile,prepare_only=True)
            send=Mock(side_effect=['om_first','om_second','om_third'])
            with patch('cmhk.services.news_delivery_guard.prepare_news_assets',side_effect=prepared_assets), patch('cmhk.services.news_delivery_guard.deduplicate_events',side_effect=lambda items,h,r:(exact_unique(items,h),[])), patch('cmhk.services.news_digest_editor.prepare_digest',side_effect=editor), patch.object(service,'_send_interactive_card',send),patch.object(service,'_verify_message'):
                with patch('cmhk.services.news_delivery_guard.expired',side_effect=lambda:len(edited)>=6):prepare(queued()[0])
                first=queued()[0];service.flush_due(pending_id=first['id'],now=now)
                state=reconcile_round(service,'ou_test',ref,now=now)
                self.assertEqual((state['delivered_count'],state['remaining_count']),(6,14))
                self.assertEqual(len(queued()),1)
                stable_supplement_id = queued()[0]["id"]
                # A fresh service/parallel recovery sees the same unique queued supplement.
                with ThreadPoolExecutor(max_workers=3) as workers:
                    list(workers.map(lambda _:reconcile_round(SubscriptionService(runtime_root=Path(tmp)),'ou_test',ref,now=now),range(3)))
                self.assertEqual(len(queued()),1)
                self.assertEqual(queued()[0]['id'], stable_supplement_id)
                supplement=queued()[0];prepare(supplement);service.flush_due(pending_id=supplement['id'],now=now)
                final=reconcile_round(service,'ou_test',ref,now=now)
                self.assertEqual((final['status'],final['delivered_count'],final['remaining_count']),('complete',20,0))
                self.assertEqual(len(edited),20)
                self.assertEqual(len({x['news_id'] for x in edited}),20)
                self.assertEqual(send.call_count,3) # 6 + 10 + 4, per-card limit preserved
                self.assertEqual(queued(),[])
                with closing(service._connect()) as db:
                    old=db.execute('SELECT message_ids FROM deliveries WHERE id=?',(first['delivery_id'],)).fetchone()[0]
                    self.assertEqual(json.loads(old),['om_first'])

if __name__=='__main__':unittest.main()

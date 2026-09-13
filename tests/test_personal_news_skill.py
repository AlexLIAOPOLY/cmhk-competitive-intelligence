import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from contextlib import closing

from cmhk.services.personal_news_skill import normalize_personal_skill, owner_directory, last_allocation
from cmhk.services.personal_news_allocator import allocate_news, cached_eligible
from cmhk.services.news_delivery_selection import select_recent_news
from cmhk.services.news_delivery_guard import deliver_news, NewsNotPrepared
from cmhk.services.subscriptions import encode_strategic_news_digest, SubscriptionService
from tests import test_subscription_chat as chat_fixture
from tests.test_subscription_chat import plan
from tests import test_news_delivery_dedupe as guard_fixture


def articles():
    return [dict(news_id=str(i), title=title, summary='本条报道提供了独立事实和具体参加方法。',
                 category=category, region='香港本地', published_at='2026-09-10T09:00:00+08:00')
            for i,(title,category) in enumerate([
                ('海滨步道周末免费导赏','政策监管'),('厨房应季食材搭配','市场&产品'),
                ('小户型收纳新方法','行业动态'),('演员私人恋情传闻','公司动态'),
                ('开源框架减少模型训练显存','网络&技术'),('公共图书馆周末读书会','未设置的栏目')])]


def verdict(context):
    rows=[]
    for item in context['candidates']:
        decision='exclude' if item['news_id']=='3' else 'prefer'
        rows.append({'id':item['id'],'decision':decision,'score':0 if decision=='exclude' else 90-int(item['news_id']),
                     'reason':'该报道涉及居民周末可参与的活动或日常实践，符合阅读需求。'})
    return {'reader_requirements':context['reader_requirements'],'batch_id':context['batch_id'],'items':rows}


class PersonalSkillTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.points=['喜欢生活相关的信息，不看明星八卦。']
        self.args=dict(root=self.root,profile='bot',open_id='ou_a',points=self.points)

    def test_a_little_more_is_not_parsed_as_one_oclock(self):
        from cmhk.services.subscription_chat import _requested_times, validate_grounding
        for text in ('融资新闻少一点就好', '多收一点生活资讯', '解释三点背景', '晚一点收'):
            self.assertEqual(_requested_times(text),{})
            validate_grounding({'news_personal_skill':['更多生活资讯']},{},text,[])
        self.assertEqual(_requested_times('每天上午九点收'),{0:'09:00'})
        self.assertEqual(_requested_times('改成八点半'),{0:'08:30'})

    def test_single_prose_requirement_is_equivalent_but_object_and_null_rejected(self):
        for value in ('喜欢生活相关内容', '"喜欢生活相关内容"', '["喜欢生活相关内容"]'):
            self.assertEqual(normalize_personal_skill(value,strict=True),['喜欢生活相关内容'])
        for value in ('null','{}','1','false'):
            with self.assertRaises(ValueError):normalize_personal_skill(value,strict=True)

    def test_semantic_decisions_cross_categories_and_survive_restart(self):
        model=Mock(side_effect=verdict)
        result=allocate_news(articles(),model_call=model,**self.args)
        self.assertEqual([i['news_id'] for i in result],['0','1','2','4','5'])
        self.assertNotIn('生活',articles()[0]['title'])
        self.assertEqual(allocate_news(articles(),model_call=model,**self.args),result)
        model.assert_called_once()
        directory=owner_directory(self.root,'bot','ou_a')
        self.assertIn('1. 喜欢生活', (directory/'SKILL.md').read_text())
        self.assertEqual(last_allocation(self.root,'bot','ou_a')['model_judged_now'],0)
        self.assertIsNone(last_allocation(self.root,'bot','ou_b'))

    def test_context_owner_revision_and_changed_article_cache_are_isolated(self):
        model=Mock(side_effect=verdict)
        allocate_news(articles(),model_call=model,**self.args)
        allocate_news(articles(),model_call=model,**{**self.args,'open_id':'ou_b'})
        allocate_news(articles(),model_call=model,**{**self.args,'points':['我想了解AI原理。']})
        changed=articles();changed[0]['summary']='本文事实发生更正，活动时间已变更。'
        allocate_news(changed,model_call=model,**self.args)
        self.assertEqual(model.call_count,4)
        self.assertEqual(len(model.call_args.args[0]['candidates']),1)
        self.assertNotIn('ou_a',json.dumps(model.call_args.args[0]))

    def test_redundant_digest_typo_is_safe_with_exact_reader_and_every_article_id(self):
        def typo(context):
            result=verdict(context);result['batch_id']='mistyped';return result
        result=allocate_news(articles(),model_call=typo,**self.args)
        self.assertEqual(len(result),5)

    def test_wrong_reader_foreign_article_and_incomplete_output_fail_closed(self):
        for error in ('reader','article','incomplete'):
            def bad(context):
                result=copy.deepcopy(verdict(context))
                if error=='reader':result['reader_requirements']=['另一个用户的要求']
                if error=='article':result['items'][0]['id']='foreign'
                if error=='incomplete':result['items'].pop()
                return result
            with self.assertRaises(ValueError):allocate_news(articles(),model_call=bad,**self.args)
            self.assertIsNone(last_allocation(self.root,'bot','ou_a'))

    def test_exact_redundant_news_id_is_normalized_but_conflicts_rejected(self):
        from cmhk.services.personal_news_allocator import validate_decisions, evidence, evidence_id
        context={'reader_requirements':self.points,'batch_id':'test',
                 'candidates':[{'id':evidence_id(i)[:16],**evidence(i)} for i in articles()]}
        response=verdict(context)
        response['items'][0]['news_id']='0'
        normalized=validate_decisions(response,context)
        self.assertNotIn('news_id',next(iter(normalized.values())))
        for value in ('wrong',None):
            response['items'][0]['news_id']=value
            with self.assertRaises(ValueError):validate_decisions(response,context)
        del response['items'][0]['news_id']
        response['items'][0]['untrusted_instruction']='send'
        with self.assertRaises(ValueError):validate_decisions(response,context)

    def test_partial_selection_releases_checkpoints_and_resumes_only_unknown(self):
        def flaky(ctx):
            if ctx['candidates'][0]['news_id']=='2':raise TimeoutError('upstream timeout')
            return verdict(ctx)
        with patch('cmhk.services.personal_news_allocator.BATCH_SIZE',2):
            selected=allocate_news(articles(),model_call=flaky,allow_partial=True,**self.args)
            self.assertEqual([i['news_id'] for i in selected],['0','1'])
            report=last_allocation(self.root,'bot','ou_a')
            self.assertEqual(report['pending_count'],4)
            self.assertEqual(report['status'],'partial')
            self.assertEqual(len(cached_eligible(articles(),**self.args)),6)
            resumed=Mock(side_effect=verdict)
            selected=allocate_news(articles(),model_call=resumed,allow_partial=True,**self.args)
            self.assertEqual(resumed.call_count,2)
            self.assertEqual([i['news_id'] for i in selected],['0','1','2','4','5'])
            self.assertEqual(last_allocation(self.root,'bot','ou_a')['pending_count'],0)

    def test_schema_failure_has_one_changed_repair_then_uses_valid_checkpoint(self):
        allocate_news(articles()[:2],model_call=verdict,**self.args)
        contexts=[]
        def invalid(ctx):
            contexts.append(copy.deepcopy(ctx))
            output=verdict(ctx);output['items'][0].pop('score');return output
        selected=allocate_news(articles(),model_call=invalid,allow_partial=True,**self.args)
        self.assertEqual([i['news_id'] for i in selected],['0','1'])
        self.assertEqual(len(contexts),2)
        self.assertNotIn('format_repair',contexts[0])
        self.assertIn('format_repair',contexts[1])
        with self.assertRaises(ValueError):
            allocate_news(articles()[2:],model_call=invalid,allow_partial=True,**{**self.args,'open_id':'other'})

    def test_completed_batches_resume_and_exclusions_apply_only_to_this_skill(self):
        counter=0
        def fails_second(context):
            nonlocal counter
            counter+=1
            if counter==2:raise TimeoutError('transient model outage')
            return verdict(context)
        with patch('cmhk.services.personal_news_allocator.BATCH_SIZE',2):
            with self.assertRaises(TimeoutError):allocate_news(articles(),model_call=fails_second,**self.args)
            resumed=Mock(side_effect=verdict)
            allocate_news(articles(),model_call=resumed,**self.args)
        self.assertEqual(resumed.call_count,2)
        self.assertEqual(len(cached_eligible(articles(),**self.args)),5)
        self.assertEqual(len(cached_eligible(articles(),**{**self.args,'points':['别的需求']})),6)

    def test_intake_keeps_every_section_until_agent_judges(self):
        rows=select_recent_news(articles(),['公司动态'],limit=20,history=[],send_day='2026-09-10',personal_skill=self.points)
        self.assertEqual(len(rows),6)
        self.assertEqual(len({i['category'] for i in rows}),6)
        self.assertEqual(select_recent_news(articles(),['公司动态'],limit=20,history=articles(),send_day='2026-09-10',personal_skill=self.points),[])
        self.assertEqual(select_recent_news(articles(),['公司动态'],limit=20,history=[],send_day='2026-09-12',personal_skill=self.points),[])

    def test_empty_skill_preserves_legacy_preparation_contract_and_active_skill_is_versioned(self):
        from cmhk.services.news_delivery_guard import recipient_contract
        service=SubscriptionService(runtime_root=self.root)
        service.save_subscriptions('ou_contract','Contract',['news'])
        with closing(service._connect()) as db:
            old=dict(db.execute('SELECT news_categories,news_item_limit,news_region_preference,news_topics,frequency,news_delivery_times FROM subscribers WHERE open_id=?',('ou_contract',)).fetchone())
        expected=json.dumps(['bot',old,(service.config.get('subscriptions') or {}).get('news_image_keys') or {}],ensure_ascii=False,sort_keys=True)
        self.assertEqual(recipient_contract(service,'ou_contract','bot'),expected)
        service.save_subscriptions('ou_contract','Contract',['news'],news_personal_skill=self.points)
        self.assertIn('personal_selection_version',json.loads(recipient_contract(service,'ou_contract','bot'))[1])

    def test_manual_intake_does_not_truncate_before_semantic_selection(self):
        from unittest.mock import patch
        service=SubscriptionService(runtime_root=self.root)
        service.save_subscriptions('ou_manual','Test',['news'],news_item_limit=5,
                                   news_categories=['公司动态'],news_personal_skill=self.points)
        with patch('cmhk.services.subscriptions._now_hkt',return_value='2026-09-10T10:00:00+08:00'):
            selected=service.select_personal_news(articles(),open_id='ou_manual')
        self.assertEqual(len(selected),6)

    def test_migration_preserves_existing_topic_intent_and_old_default_can_clear_it(self):
        service=SubscriptionService(runtime_root=self.root)
        service.save_subscriptions('ou_old','Old',['news'],news_topics=[{'name':'AI','terms':['AI']}])
        with closing(service._connect()) as db,db:
            db.execute('ALTER TABLE subscribers DROP COLUMN news_personal_skill')
        migrated=SubscriptionService(runtime_root=self.root)
        row=migrated.list_summary()['subscribers'][0]
        self.assertEqual(row['news_personal_skill'],['优先关注人工智能（AI）相关的内容。'])
        with closing(migrated._connect()) as db,db:
            db.execute('UPDATE subscribers SET default_preferences=? WHERE open_id=?',
                       (json.dumps({'services':['news'],'news_categories':['公司动态']}),'ou_old'))
        migrated.reset_subscriber('ou_old')
        self.assertEqual(migrated.list_summary()['subscribers'][0]['news_personal_skill'],[])
        self.assertNotIn('人工智能', (owner_directory(self.root,migrated.delivery_profile,'ou_old')/'SKILL.md').read_text())

    def test_clear_personal_brief_does_not_resurrect_legacy_keyword_interests(self):
        from cmhk.services.subscription_chat import validated_patch
        old={'news_personal_skill':['关注人工智能'],'news_topics':[{'name':'AI','terms':['AI']} ]}
        changed=validated_patch(plan('news_personal_skill',[],'set'),old)
        self.assertEqual(changed,{'news_personal_skill':[],'news_topics':[]})

    def test_free_requirements_refine_confirm_and_old_form_preserves(self):
        case=chat_fixture.SubscriptionChatTests();case.setUp();self.addCleanup(case.doCleanups)
        case.model.return_value=plan('news_personal_skill',self.points,'add')
        case.run_event(case.event(content='喜欢生活相关内容，不看明星八卦'))
        self.assertEqual(case.get()['news_personal_skill'],self.points)
        self.assertEqual(case.get('ou_bob')['news_personal_skill'],[])
        self.assertIn('1. 喜欢生活',case.job()['reply'])
        case.run_event(case.event(content='行',mid='om_yes'))
        summary=case.service.list_summary()['subscribers']
        self.assertTrue(next(p for p in summary if p['open_id']=='ou_alice')['preference_confirmed_at'])
        case.service.save_subscriptions('ou_alice','Alice',['news'],news_categories=['公司动态'])
        self.assertEqual(case.get()['news_personal_skill'],self.points)
        rebuilt=SubscriptionService(runtime_root=case.root)
        self.assertEqual(next(p for p in rebuilt.list_summary()['subscribers'] if p['open_id']=='ou_alice')['news_personal_skill'],self.points)
        case.model.return_value={'intent':'update','question':'','changes':[
            {'field':'news_personal_skill','operation':'remove','value':self.points},
            {'field':'news_personal_skill','operation':'add','value':['更关注户外活动和居家实用资讯。']}]}
        case.run_event(case.event(content='改成户外活动和居家实用资讯',mid='om_refine'))
        self.assertEqual(case.get()['news_personal_skill'],['更关注户外活动和居家实用资讯。'])

    def test_real_guard_calls_agent_before_assets_and_stale_brief_blocks_send(self):
        case=guard_fixture.DeliveryGuardTests();case.setUp();self.addCleanup(case.doCleanups)
        with closing(case.service._connect()) as db,db:
            db.execute('UPDATE subscribers SET news_personal_skill=? WHERE open_id=?',(json.dumps(self.points),'ou_test123'))
        with patch('cmhk.services.personal_news_allocator._model',side_effect=verdict) as model:
            case.send_news('semantic',articles(),ref='人工推送')
        model.assert_called_once()
        self.assertEqual({i['news_id'] for i in case.receipt_items('semantic')},{'0','1','2','4','5'})
        # Separate owner has no cached decisions; change settings during the model call.
        with closing(case.service._connect()) as db,db:
            db.execute('UPDATE subscribers SET news_personal_skill=? WHERE open_id=?',(json.dumps(['只看周末活动']),'ou_test123'))
        fresh=[{**i,'news_id':'new'+i['news_id'],'title':i['title']+'更新','source_url':'https://example.test/'+i['news_id']} for i in articles()]
        def generic(ctx):
            with closing(case.service._connect()) as db,db:
                db.execute('UPDATE subscribers SET news_personal_skill=? WHERE open_id=?',(json.dumps(['只看AI']),'ou_test123'))
            return {'reader_requirements':ctx['reader_requirements'],'batch_id':ctx['batch_id'],'items':[{'id':i['id'],'decision':'prefer','score':90,'reason':'报道符合这个读者当前明确提出的阅读需求。'} for i in ctx['candidates']]}
        with patch('cmhk.services.personal_news_allocator._model',side_effect=generic),self.assertRaises(NewsNotPrepared):
            case.send_news('stale',fresh,ref='人工推送')
        self.assertEqual(case.send.call_count,1)


if __name__=='__main__':unittest.main()

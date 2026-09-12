import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from data_curation import workflow as w
from data_curation.research_freshness import period_key
from data_curation.six_agent_research import validate_fact, company_value_is_bound
from data_curation.research_final_review import review_run


class ResearchReliabilityTests(unittest.TestCase):
    def test_completed_checkpoint_recovers_exact_quarter_table_without_model(self):
        from tests.test_research_tables import URL, TEXT
        from data_curation.research_contracts import VERSION
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / 'agent_knowledge/quarterly_competitor_metrics_2026-06-18/quarterly_metrics.json'
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps({'rows': [{'subject': '中国联通', 'metric_key': 'ebitda',
                'period': 'Q1 2026', 'grain': 'quarter', 'value': 24331, 'unit': 'millions CNY'}]}))
            directory = root / 'curation_data/research_runs/test'; directory.mkdir(parents=True)
            task = {'key': 'mainland', 'title': '内地', 'companies': ['中国联通']}
            report = {'company': '中国联通', 'metrics': ['EBITDA'], 'status': 'partial',
                'contract_version': VERSION, 'review_completed': True, 'reviewed_metrics': ['EBITDA'],
                'pages': {URL: {'opened': True, 'official': True, 'text': TEXT}},
                'items': [{'company': '中国联通', 'metric': 'EBITDA', 'status': 'out_of_scope',
                    'period': 'H1 2026', 'value': '', 'reason': 'wrong period'}]}
            (directory / 'manifest.json').write_text(json.dumps({'run_id': 'test', 'plan': [task]}))
            (directory / 'mainland.json').write_text(json.dumps({**task, 'reports': [report]}))
            with patch('data_curation.research_final_review.company_metric_plan', return_value=['EBITDA']):
                result = review_run(directory, model_factory=lambda: self.fail('no model needed'),
                    collector=lambda *args: self.fail('no repeated search'))
            self.assertEqual(result['accepted'], 1)

    def configured_run(self, temp):
        root = Path(temp)
        template = root / 'agent_knowledge/hk_competitor_product_tariffs/local_financial_results.json'
        template.parent.mkdir(parents=True)
        template.write_text(json.dumps({'reports': [{'company': 'HKT', 'period': 'FY2024',
            'metrics': [{'metric_key': 'revenue', 'value': 100, 'unit': 'millions HKD'}]}]}))
        directory = root / 'curation_data/research_runs/test'
        directory.mkdir(parents=True)
        return directory

    def test_saved_twelve_month_exclusion_recovers_real_proof_without_model_or_search(self):
        from data_curation.research_contracts import VERSION
        with tempfile.TemporaryDirectory() as temp:
            directory = self.configured_run(temp)
            task = {'key': 'hong-kong', 'title': '香港', 'companies': ['HKT']}
            period = 'Twelve Months Ended December 31, 2025'
            text = f'HKT reported revenue of HK$ 123 million for {period}.'
            url = 'https://www.hkt.com/report'
            report = {'company': 'HKT', 'metrics': ['收入'], 'status': 'partial', 'incremental': True,
                'contract_version': VERSION, 'review_completed': True, 'reviewed_metrics': ['收入'],
                'pages': {url: {'opened': True, 'official': True, 'text': text}},
                'items': [{'company': 'HKT', 'metric': '收入', 'status': 'out_of_scope',
                    'period': period, 'value': '123', 'unit': 'HK$ million', 'quote': text, 'source_url': url}]}
            (directory / 'manifest.json').write_text(json.dumps({'run_id': 'test', 'plan': [task]}))
            (directory / 'hong-kong.json').write_text(json.dumps({**task, 'reports': [report]}))
            result = review_run(directory, model_factory=lambda: self.fail('must reuse source proof'),
                collector=lambda *args: self.fail('must not repeat search'))
            self.assertEqual(result['accepted'], 1)

    def test_parent_group_amount_cannot_become_subsidiary_amount(self):
        self.assertFalse(company_value_is_bound('CMHK','RMB538.0 billion','China Mobile Hong Kong Treasury Company Limited. The Company recorded operating revenue of RMB538.0 billion.','https://www.chinamobileltd.com/en/ir/reports/ir2026.pdf'))
        self.assertTrue(company_value_is_bound('CMHK','HK$100 million','China Mobile Hong Kong recorded revenue of HK$100 million.','https://www.chinamobileltd.com/report.pdf'))
        self.assertFalse(company_value_is_bound('Google Cloud','$100 billion','Alphabet revenue was $100 billion. Google Cloud operates worldwide.','https://abc.xyz/report'))
        self.assertTrue(company_value_is_bound('Google Cloud','$10 billion','Google Cloud revenue was $10 billion.','https://abc.xyz/report'))

    def test_full_report_tail_survives_fetch(self):
        class Response:
            url = 'https://official.test/full-report'
            status_code = 200
            headers = {'content-type': 'text/html'}
            text = '<p>' + 'Report introduction ' * 2000 + 'Revenue for 2026 was USD 123 million.</p>'
            def raise_for_status(self): pass
        w._SOURCE_PAGE_CACHE.pop(Response.url, None)
        with patch('httpx.get', return_value=Response()):
            page = w._read_source_page(Response.url, 1)
        self.assertGreater(len(page['text']), 20000)
        self.assertIn('USD 123 million', page['text'])
        self.assertFalse(page['text_truncated'])

    def test_actual_quarter_precedes_different_fiscal_year(self):
        self.assertEqual(period_key('the first quarter (April - June 2026, Q1) of the fiscal year ending March 31, 2027 (FY2026)'), (2026, 6, 'quarter'))
        self.assertEqual(period_key('Three-month period ended June 30, 2026 (FY2027)'), (2026, 6, 'quarter'))

    def test_one_official_source_and_native_currency_are_sufficient(self):
        text = 'KDDI reported revenue of 123 million yen for 2026.'
        url = 'https://www.kddi.com/report'
        fact = dict(company='KDDI', metric='收入', status='verified', value='123', period='2026', unit='million yen', source_url=url, quote=text)
        self.assertEqual(validate_fact(fact, 'KDDI', ['收入'], {url: dict(opened=True, official=True, text=text)})['status'], 'verified')
        self.assertEqual(validate_fact({**fact, 'unit': 'million'}, 'KDDI', ['收入'], {url: dict(opened=True, official=True, text=text)})['status'], 'conflict')

    def test_period_heading_elsewhere_is_bound_to_same_official_document(self):
        url = 'https://www.hkt.com/report'
        text = 'HKT fiscal year ended June 30, 2026. ' + 'Overview. ' * 100 + 'Revenue was HK$ 123 million.'
        fact = dict(company='HKT', metric='收入', status='verified', value='123', period='fiscal year ended June 30, 2026', unit='HK$ million', source_url=url, quote='Revenue was HK$ 123 million.', context_quote='HKT')
        item = validate_fact(fact, 'HKT', ['收入'], {url:dict(opened=True, official=True, text=text)})
        self.assertEqual(item['status'], 'verified')
        self.assertIn(fact['period'], item['period_quote'])
        self.assertIn(item['period_quote'], text)
        self.assertEqual(validate_fact({**fact,'period':'fiscal year ended June 30, 2027'}, 'HKT',['收入'], {url:dict(opened=True,official=True,text=text)})['status'],'conflict')

    def test_native_table_unit_and_approximation_are_not_lost(self):
        url = 'https://www.smartoneholdings.com/report.pdf'
        text = 'SmarTone 2026 Annual Results. All references to $ are to Hong Kong dollars. Revenues $000 6,603,624.'
        fact = dict(company='SmarTone', metric='收入', status='verified', value='6,603,624', period='2026', unit='$000 (Hong Kong dollars)', source_url=url, quote=text)
        self.assertEqual(validate_fact(fact,'SmarTone',['收入'], {url:dict(opened=True,official=True,text=text)})['status'], 'verified')
        text = 'SmarTone 2026 revenue exceeded $100 million.'
        fact.update(value='$100 million', unit='$ million', quote=text)
        self.assertEqual(validate_fact(fact,'SmarTone',['收入'], {url:dict(opened=True,official=True,text=text)})['status'], 'conflict')
        fact['value'] = '100 million'
        self.assertEqual(validate_fact(fact,'SmarTone',['收入'], {url:dict(opened=True,official=True,text=text)})['status'], 'conflict')
        fact['value'] = 'exceeded $100 million'
        self.assertEqual(validate_fact(fact,'SmarTone',['收入'], {url:dict(opened=True,official=True,text=text)})['status'], 'verified')

    def test_final_reviewer_searches_missing_then_saves_without_replaying(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = self.configured_run(temp)
            task = dict(key='hong-kong', title='香港', purpose='研究', companies=['HKT'])
            summary = dict(run_id='test', plan=[task], research_policy='latest_disclosure_incremental_v1')
            (directory/'manifest.json').write_text(json.dumps(summary))
            report = dict(company='HKT', metrics=['收入'], incremental=True, status='partial', baseline={}, pages={}, searches=[], items=[dict(company='HKT', metric='收入', status='missing', value='', reason='未找到')])
            (directory/'hong-kong.json').write_text(json.dumps(dict(task, reports=[report])))
            text = 'HKT reported revenue of HK$ 123 million in 2026.'
            url = 'https://www.hkt.com/report'
            calls = []
            def collect(*args):
                calls.append(args[0]); return {url: dict(opened=True, official=True, text=text)}, [dict(query='HKT 2026 revenue', results=[dict(url=url)])]
            class Harness:
                def __init__(self, *args): pass
                def extract(self, company, metric, pages, save, **kw):
                    save(dict(company=company, metric=metric, status='verified', value='123', period='2026', unit='HK$ million', quote=text, source_url=url))
            result = review_run(directory, model_factory=lambda: None, collector=collect, harness_factory=Harness)
            self.assertEqual(result['outcome_counts'], dict(existing=0, duplicate=0, updated=1, failed=0, excluded=0))
            self.assertEqual(len((directory/'verified_facts.jsonl').read_text().splitlines()), 1)
            review_run(directory, model_factory=lambda: self.fail('must not create model'), collector=collect, harness_factory=Harness)
            self.assertEqual(calls, ['HKT'])

    def test_failed_review_fetch_keeps_archived_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = self.configured_run(temp)
            task = dict(key='hong-kong', title='香港', companies=['HKT'])
            url = 'https://www.hkt.com/report'
            text = 'HKT reported revenue of HK$ 123 million in 2026.'
            report = dict(company='HKT', metrics=['收入'], pages={url:dict(opened=True,official=True,text=text)}, items=[dict(company='HKT',metric='收入',status='missing')])
            (directory/'manifest.json').write_text(json.dumps(dict(run_id='test',plan=[task])))
            (directory/'hong-kong.json').write_text(json.dumps(dict(task,reports=[report])))
            class Harness:
                def __init__(self,*args): pass
                def extract(self,company,metric,pages,save,**kw):
                    self_test.assertEqual(pages[url]['text'],text)
                    save(dict(company=company,metric=metric,status='verified',value='123',period='2026',unit='HK$ million',quote=text,source_url=url))
            self_test = self
            result = review_run(directory,model_factory=lambda:None,collector=lambda *args:({url:dict(opened=False,error='timeout')},[]),harness_factory=Harness)
            self.assertEqual(result['outcome_counts'],dict(existing=0,duplicate=0,updated=1,failed=0,excluded=0))

    def test_model_timeout_enters_bounded_retry_not_immediate_fallback(self):
        import executive_intelligence_pipeline as p
        # No domain payload required: all three primary attempts time out before validation.
        with patch('ai_config.load_ai_config', return_value={'api_key': 'test', 'base_url': 'https://example.test'}), patch('ai_rate_limit.wait_for_internal_ai_slot'), patch.object(p, 'open_llm_request', side_effect=TimeoutError('timed out')) as call, patch.object(p, '_validate_model_summaries', return_value=[]), patch.object(p, '_repair_model_summaries', side_effect=lambda s,e:s), patch.object(p, '_drop_unsupported_numeric_clauses', side_effect=lambda s,e:s):
            p.generate_model_domain_summaries({'domains': []})
            self.assertEqual(call.call_count, 3)

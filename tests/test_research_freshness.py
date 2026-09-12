import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from data_curation.research_freshness import compare_candidate, load_baseline, period_key
from data_curation.six_agent_research import collect_sources


class FreshnessTests(unittest.TestCase):
    def test_stale_disclosure_cannot_be_new_just_because_baseline_is_older(self):
        baseline = {'用户数': [{'period': 'six months ended 31 December 2013', 'value': 1}]}
        item = {'status': 'verified', 'metric': '用户数', 'period': 'six months ended 31 December 2017', 'value': 2}
        with patch('data_curation.research_freshness.datetime') as clock:
            clock.now.return_value.year = 2026
            result = compare_candidate(item, baseline)
            self.assertEqual((result['status'], result['freshness']), ('conflict', 'stale_disclosure'))
            self.assertEqual(compare_candidate({**item, 'period': 'H1 2026'}, baseline)['freshness'], 'new_period')
            self.assertEqual(compare_candidate({**item, 'period': baseline['用户数'][0]['period']}, baseline)['status'], 'no_update')
        self.assertEqual(baseline['用户数'][0]['value'], 1)

    def test_native_fiscal_periods_and_half_year_aliases(self):
        self.assertEqual(period_key('first half of 2026'), period_key("H1'26"))
        self.assertEqual(period_key('six months ended 31 December 2013'), (2013, 12, 'half'))
        self.assertEqual(period_key('the six months ended 28 February 2026'), (2026, 2, 'half'))
        self.assertEqual(period_key('second quarter ended June 30, 2026'), period_key('2Q 2026'))
        self.assertIsNone(period_key('In the first half of the year'))

    def test_existing_values_are_trusted_and_never_replaced(self):
        baseline = {'收入': [{'period': 'H1 2026', 'value': '100', 'unit': 'HKD million'}]}
        item = {'status': 'verified', 'metric': '收入', 'period': 'first half of 2026', 'value': '999'}
        self.assertEqual(compare_candidate(item, baseline)['status'], 'no_update')
        self.assertEqual(baseline['收入'][0]['value'], '100')
        self.assertEqual(compare_candidate({**item, 'period': 'H1 2025'}, baseline)['freshness'], 'older_period')
        self.assertEqual(compare_candidate({**item, 'period': 'Q3 2026'}, baseline)['status'], 'out_of_scope')
        self.assertEqual(compare_candidate({**item, 'period': 'unknown'}, baseline)['status'], 'conflict')

    def test_primary_rows_and_nested_reports_are_baselines_even_without_quality_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / 'agent_knowledge/hk_competitor_product_tariffs/local_financial_results.json'
            p.parent.mkdir(parents=True)
            p.write_text(json.dumps({'reports': [{'company':'HKT', 'period':'H1 2026',
                'metrics':[{'metric':'收入/总收益','value':0}]}]}))
            b = load_baseline(root)['companies']
            self.assertEqual(b['HKT']['收入'][0]['value'], 0)
            self.assertEqual(b['HKT']['收入'][0]['period'], 'H1 2026')
            p.write_text('{broken')
            with self.assertRaises(ValueError):
                load_baseline(root)

    def test_discovery_follows_new_official_report_and_ignores_unofficial_link(self):
        root_url = 'https://official.test/results'
        pages = {root_url: {'opened':True, 'text':'Latest results', 'disclosure_links':[
            {'url':'https://official.test/2026-interim.pdf','title':'2026 interim results'},
            {'url':'https://untrusted.test/report','title':'2026 results'}]},
            'https://official.test/2026-interim.pdf': {'opened':True,'text':'new disclosure'}}
        with patch('data_curation.workflow._company_research_profile', return_value={'official_hosts':['official.test'],'seed_urls':[root_url]}), \
             patch('data_curation.workflow._public_web_search', return_value=([{'url':root_url,'title':'Latest results'}],'test')), \
             patch('data_curation.workflow._read_source_page', side_effect=lambda url, **kw: pages[url]):
            read, searches = collect_sources('HKT', ['收入'], lambda *args: None,
                                             {'收入':[{'period':'H1 2025','value':100}]})
        self.assertIn('https://official.test/2026-interim.pdf', read)
        self.assertNotIn('https://untrusted.test/report', read)
        self.assertIn('latest', searches[0]['query'])

    def test_incremental_primary_write_adds_new_period_and_never_replaces_existing(self):
        from cmhk.data.daily_financial_promotion import promote_daily_financial_facts
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / 'quarterly_metrics.json'
            old = {'subject':'AT&T','period':'Q2 2026','metric_key':'revenue','value':100,
                   'unit':'millions USD','verification_status':'legacy_unrated'}
            database.write_text(json.dumps({'rows':[old], 'subjects':[]}))
            base = {'company':'AT&T','metric':'收入','value':'US$ 200 million','unit':'USD million',
                'source_tier':'official','quality_score':.95,
                'decision':'accepted','status':'ok','freshness':'new_period',
                'entity_supported':True,'metric_supported':True,'value_supported':True,
                'evidence_hash':'test-hash','sources':['https://investors.att.com/results'],'basis':'official release'}
            facts = root / 'verified_facts.jsonl'
            facts.write_text('\n'.join(json.dumps(dict(base, period=p)) for p in ['Q2 2026','Q3 2026']))
            result = promote_daily_financial_facts(database_path=database, local_financial_path=root/'absent.json',
                verified_facts_path=facts, incremental_only=True)
            rows=json.loads(database.read_text())['rows']
            self.assertEqual(result['added_rows'],1)
            self.assertEqual(result['upgraded_rows'],0)
            self.assertEqual(next(row for row in rows if row['period']=='Q2 2026'),old)
            self.assertEqual(next(row for row in rows if row['period']=='Q3 2026')['value'],200)

    def test_native_fiscal_quarter_is_not_assigned_a_calendar_end(self):
        from cmhk.data.daily_financial_promotion import _incremental_rows
        fact = {'company':'Telstra','metric':'收入','period':'Q1 2026', 'value':'AUD 200 million',
            'decision':'accepted','freshness':'new_period', 'entity_supported':True,
            'metric_supported':True,'value_supported':True,'evidence_hash':'hash',
            'sources':['https://telstra.com.au/results']}
        self.assertEqual(_incremental_rows([json.dumps(fact)]), [])

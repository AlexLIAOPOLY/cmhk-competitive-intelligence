import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from data_curation.research_plan import company_metric_plan, research_plan
from data_curation.six_agent_research import collect_sources, run_assignment
from data_curation.research_final_review import review_run


class HomepageScopeTests(unittest.TestCase):
    def test_all_companies_have_only_homepage_tasks(self):
        self.assertEqual(sum(len(company_metric_plan(c)) for t in research_plan() for c in t['companies']), 156)
        self.assertEqual(company_metric_plan('unknown'), [])

    def test_search_boundary_excludes_legacy_topics_and_empty_scope_never_searches(self):
        with patch('data_curation.workflow._public_web_search', return_value=([], 'test')) as search, \
             patch('data_curation.workflow._company_research_profile', return_value={'official_hosts': [], 'seed_urls': []}), \
             patch('data_curation.workflow._read_source_page') as read:
            self.assertEqual(collect_sources('HKT', ['套餐', '促销', '券商观点', 'ARPU'], lambda *a: None), ({}, []))
            search.assert_not_called()
            read.assert_not_called()
            _, records = collect_sources('HKT', ['收入', '套餐', '券商观点'], lambda *a: None)
            self.assertEqual({r['metric'] for r in records}, {'最新披露', '收入'})
            self.assertTrue(all(not any(t in c.args[0] for t in ['套餐', '观点', '促销']) for c in search.call_args_list))

    def test_completed_checkpoint_cannot_restore_removed_topics(self):
        metrics = company_metric_plan('HKT')
        checkpoint = {'reports': [{'company': 'HKT', 'status': 'completed', 'metrics': metrics + ['套餐'],
            'items': [{'metric': m, 'status': 'missing'} for m in metrics + ['套餐']]}]}
        with patch('data_curation.research_harness.ResearchHarness'):
            result = run_assignment({'key': 'hong-kong', 'title': '香港', 'purpose': '研究', 'companies': ['HKT']},
                                    lambda *a: None, checkpoint, model_factory=lambda: object(),
                                    collector=lambda *a: self.fail('completed work should not search'))
        self.assertEqual(result['reports'][0]['metrics'], metrics)
        self.assertNotIn('套餐', [i['metric'] for i in result['reports'][0]['items']])

    def test_final_review_never_collects_removed_topics(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task = {'key': 'hong-kong', 'companies': ['HKT']}
            (root / 'manifest.json').write_text(json.dumps({'run_id': 'scope-test', 'plan': [task]}))
            (root / 'hong-kong.json').write_text(json.dumps({**task, 'reports': [{'company': 'HKT',
                'metrics': ['收入', '套餐', '券商观点'], 'items': [
                    {'company': 'HKT', 'metric': m, 'status': 'missing'} for m in ['收入', '套餐', '券商观点']]}]}))
            calls = []
            def collector(company, metrics, *args):
                calls.extend(metrics)
                return {}, []
            review_run(root, collector=collector, model_factory=lambda: object())
            self.assertEqual(calls, ['收入'])
            saved = json.loads((root / 'hong-kong.json').read_text())
            self.assertEqual([i['metric'] for i in saved['reports'][0]['items']], ['收入'])

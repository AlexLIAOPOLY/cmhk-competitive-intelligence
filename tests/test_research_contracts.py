import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from data_curation.research_contracts import (build_contract, candidate_error, formal_row_error,
    next_period_end, planning_outcome, row_end, search_qualifier)
from data_curation.research_freshness import load_baseline
from data_curation.research_kpi import CARRIER_PATH, prepare_facts, write_formal_facts
from data_curation.research_storage import DOMAIN_PATHS, merge_domain
from data_curation.cleanup_research_series import cleanup
from data_curation.six_agent_research import collect_sources
from tests.test_research_kpi import tables
from tests.test_research_storage import fact


class SeriesContractsTests(unittest.TestCase):
    def test_period_grain_and_field_are_independent_hard_requirements(self):
        baseline = {'收入': [{'period': 'H1 2025', 'value': 100, 'field': 'revenue', 'unit': 'millions HKD'}]}
        for period in ['FY2026', 'Q2 2026', 'month ended June 30, 2026', 'nine months ended September 30, 2026']:
            self.assertTrue(candidate_error('HKT', '收入', period, baseline), period)
        self.assertFalse(candidate_error('HKT', '收入', 'H1 2026', baseline))
        item = {'company': 'HKT', 'metric': '收入', 'period': 'H1 2026'}
        self.assertTrue(formal_row_error(item, {'metric_key':'organic_revenue', 'unit':'millions HKD'}, baseline))
        self.assertTrue(formal_row_error(item, {'metric_key':'revenue', 'unit':'millions USD'}, baseline))
        self.assertFalse(formal_row_error(item, {'metric_key':'revenue', 'unit':'millions HKD'}, baseline))

    def test_native_fiscal_half_and_year_use_actual_end(self):
        rows = [{'period':'H1 2026', 'period_end':"Dec '25 Dec 31, 2025", 'grain':'half_year', 'value':1}]
        contract = build_contract('SmarTone', '收入', rows)
        self.assertEqual(row_end(rows[0]), date(2025, 12, 31))
        self.assertEqual(next_period_end(contract), date(2026, 6, 30))
        self.assertIsNone(planning_outcome('SmarTone', '收入', {'收入':rows}, today=date(2026, 9, 12)))
        rows = [{'period':'FY2026', 'period_end':'2026-03-31', 'grain':'annual', 'value':1}]
        self.assertEqual(next_period_end(build_contract('NTT','收入',rows)), date(2027,3,31))

    def test_daily_wrong_grain_cannot_become_schema_but_valid_period_advances_it(self):
        rows = [{'period':'H1 2025','value':1,'field':'revenue'},
                {'period':'FY2026','value':2,'field':'revenue','daily_fact_id':'wrong'},
                {'period':'H1 2026','value':3,'field':'revenue','daily_fact_id':'good'}]
        c = build_contract('HKT', '收入', rows)
        self.assertEqual((c['grain'],c['latest_period']), ('half','H1 2026'))
        self.assertFalse(build_contract('HKT', '收入', rows[1:])['enabled'])

    def test_skips_network_for_unconfigured_or_unclosed_and_searches_target_period(self):
        baseline = {'收入':[{'period':'H1 2099','value':1,'field':'revenue'}]}
        with patch('data_curation.workflow._public_web_search', side_effect=AssertionError('must not search')):
            self.assertEqual(collect_sources('HKT',['收入'],lambda *a:None,baseline), ({},[]))
            self.assertEqual(collect_sources('HKT',['收入'],lambda *a:None,{}), ({},[]))
        c = build_contract('HKT','收入',[{'period':'H1 2025','value':1}])
        self.assertIn('"six months"',search_qualifier(c))
        self.assertIn('-"full year"',search_qualifier(c))

    def test_cleanup_backups_indexes_idempotence_and_all_write_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good = {'subject':'HKT / csl / 1O1O','period':'H1 2026','period_end':'2026-06-30',
                    'metric_key':'revenue','metric_zh':'收入','grain':'half_year','value':100,'unit':'millions HKD'}
            bad = {**good,'period':'FY2026','grain':'annual','daily_fact_id':'wrong'}
            tables(root, [good,bad])
            table = root / CARRIER_PATH
            payload=json.loads(table.read_text());payload['subjects']=[{'subject':good['subject'],'metrics':{'revenue':{'FY2026':100}},'periods':[]}]
            table.write_text(json.dumps(payload))
            sidecar = root / DOMAIN_PATHS['local']
            sidecar.write_text(json.dumps({'facts':[dict(fact(period='FY2026'), source_url='https://hkt.com/report')]}))
            original=table.read_bytes()
            audit=cleanup(root,apply=True,stamp='test')
            self.assertEqual(audit['formal_rows_removed'],1)
            self.assertEqual(audit['sidecar_facts_removed'],1)
            self.assertEqual((Path(audit['backup']) / CARRIER_PATH).read_bytes(),original)
            saved=json.loads(table.read_text())
            self.assertEqual(saved['rows'],[good])
            self.assertNotIn('FY2026',saved['subjects'][0]['metrics']['revenue'])
            self.assertEqual(cleanup(root)['removed_count'],0)
            old = fact(period='FY2026')
            prepared,receipt=prepare_facts(root,[old],'research_test',allow_replay=True)
            self.assertEqual(prepared[0]['decision'],'excluded')
            self.assertEqual(write_formal_facts(root,[old])['written'],0)
            source=dict(old,source_url=old['sources'][0])
            self.assertFalse(merge_domain(sidecar,[source],domain='local',run_id='old',generated_at='now')['ok'])
            self.assertEqual(json.loads(table.read_text())['rows'],[good])

    def test_closed_period_can_be_missing_without_becoming_new_metric(self):
        baseline={'收入':[{'period':'FY2025','value':None,'field':'revenue'}]}
        c=build_contract('中国广电','收入',baseline['收入'])
        self.assertTrue(c['enabled']);self.assertFalse(c['has_baseline'])
        self.assertIsNone(planning_outcome('中国广电','收入',baseline,today=date(2026,9,12)))

    def test_policy_migration_rechecks_old_no_update_when_target_period_is_due(self):
        from data_curation.six_agent_research import run_assignment
        task={'key':'hong-kong','title':'香港','purpose':'研究','companies':['HKT']}
        checkpoint={'reports':[{'company':'HKT','status':'completed','metrics':['收入'],
            'items':[{'company':'HKT','metric':'收入','status':'no_update','period':'H1 2025'}],
            'pages':{'old':{'opened':True,'official':True,'text':'broad old search'}}}]}
        collector=Mock(return_value=({'new':{'opened':True,'official':True,'text':'revenue'}},[]))
        with patch('data_curation.research_plan.frontend_metric_plan',return_value={'local':['收入']}), \
             patch('data_curation.research_harness.ResearchHarness') as harness:
            harness.return_value.extract.side_effect=lambda c,m,p,save,**kw:save({'company':c,'metric':m,'status':'missing','reason':'target period not yet disclosed'})
            run_assignment(task,lambda *a:None,checkpoint=checkpoint,model_factory=lambda:object(),collector=collector,
                           baseline={'HKT':{'收入':[{'period':'H1 2025','value':100}]}})
        collector.assert_called_once()
        self.assertEqual(collector.call_args.args[1],['收入'])
        harness.return_value.extract.assert_called_once()


if __name__ == '__main__':
    unittest.main()

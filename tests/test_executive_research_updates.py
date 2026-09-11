import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cmhk.intelligence import executive as reader
from data_curation.research_kpi import normalize_fact
from tests.test_research_storage import fact


def disclosure(company, domain, metric, value, unit, period='FY2026', grain='annual'):
    return {'company': company, 'domain': domain, 'metric_key': metric, 'metric_label': metric,
            'value': value, 'unit': unit, 'period': period, 'grain': grain, 'period_end': '2026-06-30',
            'source_url': 'https://issuer.test/annual', 'evidence_hash': 'source-hash', 'storage_verified': True}


def domain(domain_id, focus_id, company, value, unit, period='FY2025'):
    item={'name': company, 'value': value, 'unit': unit, 'period': period, 'components': [], 'trend': []}
    return {'id': domain_id, 'entities': [item], 'focuses': [{'id':focus_id,'items':[item]}], 'sources': []}


class ExecutiveResearchUpdatesTests(unittest.TestCase):
    def test_exact_formal_readback_is_required_and_alias_and_quarter_are_preserved(self):
        run_id='research_20260911'
        source=fact(company='NTT Docomo', metric='净利润', value='176.3 Billions of yen', unit='Billions of yen',
                    period='FY2026/1Q', research_run_id=run_id, basis='Quarterly official net income evidence')
        row=normalize_fact(source)[0]
        with tempfile.TemporaryDirectory() as tmp, patch.object(reader,'ROOT',Path(tmp)):
            folder=Path(tmp)/'curation_data/research_runs'/run_id
            folder.mkdir(parents=True)
            (folder/'manifest.json').write_text(json.dumps({'run_id':run_id,'accepted':1}))
            (folder/'verified_facts.jsonl').write_text(json.dumps(source))
            updates=reader._formal_research_updates({'rows':[row]},{'rows':[]})
            self.assertEqual(len(updates),1)
            self.assertEqual((updates[0]['company'],updates[0]['period'],updates[0]['grain'],updates[0]['value']),
                             ('NTT DOCOMO','Q1 FY2026','quarter',176300))
            for change in ({'value':176301}, {'daily_evidence_hash':'other'}, {'official_source_url':'https://other.test'}):
                self.assertEqual(reader._formal_research_updates({'rows':[{**row,**change}]},{'rows':[]}),[])
            (folder/'manifest.json').write_text(json.dumps({'run_id':run_id,'accepted':2}))
            self.assertEqual(reader._formal_research_updates({'rows':[row]},{'rows':[]}),[])

    def test_annual_updates_keep_entity_scope_and_half_year_stays_out_of_annual_card(self):
        local=domain('local','net_profit','SmarTone',478.9,'百万港元')
        mainland=domain('mainland','postpaid','中国移动',10.05,'亿户')
        updates=[disclosure('SmarTone','local','net_income',524.742,'millions HKD'),
                 disclosure('中国移动','mainland','subscribers',1011000000,'subscribers','H1 2026','half_year'),
                 disclosure('Telstra','international','revenue',22937,'millions AUD')]
        reader._apply_formal_annual_updates([local,mainland],updates,{'rates':[]})
        latest=local['focuses'][0]['items'][0]
        self.assertEqual((latest['value'],latest['period'],latest['unit']),(524.7,'FY2026','百万港元'))
        self.assertEqual(latest['components'][0]['value'],524.742)
        self.assertEqual((mainland['entities'][0]['value'],mainland['entities'][0]['period']),(10.05,'FY2025'))
        self.assertEqual([i['name'] for i in local['entities']],['SmarTone'])

    def test_foreign_annual_amount_never_uses_previous_year_fx(self):
        international=domain('international','revenue','Singtel',10819.53,'百万美元')
        update=disclosure('Singtel','international','revenue',14261,'millions SGD')
        reader._apply_formal_annual_updates([international],[update],{'rates':[{'currency':'SGD','year':2025,'local_per_usd':1.3}]})
        item=international['entities'][0]
        self.assertEqual((item['value'],item['period']),(10819.53,'FY2025'))
        self.assertEqual(item['components'][-1]['value'],14261)
        self.assertIn('该年度平均汇率尚未入库',item['detail'])
        self.assertEqual(item['latest_formal_disclosure']['period'],'FY2026')
        current=domain('international','revenue','Singtel',10819.53,'百万美元')
        reader._apply_formal_annual_updates([current],[update],{'rates':[{'currency':'SGD','year':2026,'local_per_usd':1.25}]})
        self.assertEqual((current['entities'][0]['value'],current['entities'][0]['period']),(11408.8,'FY2026'))

    def test_existing_model_evidence_channel_receives_original_quarter_and_half_year(self):
        import executive_intelligence_pipeline as pipeline
        docomo=disclosure('NTT DOCOMO','international','net_income',176300,'millions JPY','Q1 FY2026','quarter')
        mobile=disclosure('中国移动','mainland','subscribers',1011000000,'subscribers','H1 2026','half_year')
        domains=[domain('international','net_profit','NTT DOCOMO',4411.39,'百万美元'),
                 domain('mainland','postpaid','中国移动',10.05,'亿户')]
        for d,u in zip(domains,[docomo,mobile]):d['ai_analysis']=[u]
        evidence=reader._analysis_evidence_snapshot(domains)
        with patch.object(reader,'build_executive_intelligence_snapshot',return_value={'domains':domains}):
            self.assertEqual(pipeline._analysis_input_snapshot(),evidence)
        self.assertEqual(evidence['domains'][0]['agent_verified_facts'][0]['period'],'Q1 FY2026')
        self.assertEqual(evidence['domains'][1]['agent_verified_facts'][0]['grain'],'half_year')
        self.assertEqual(evidence['domains'][1]['focuses'][0]['items'][0]['period'],'FY2025')
        self.assertEqual(reader._research_company_name('NTT Docomo'),'NTT DOCOMO')
        self.assertEqual(reader._research_company_name('SoftBank'),'SoftBank Corp.')


if __name__=='__main__':unittest.main()

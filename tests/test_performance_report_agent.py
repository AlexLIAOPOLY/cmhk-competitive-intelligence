import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from cmhk.reporting.performance_agent import build_model, FIELDS, fresh_rows, publication_date
from generate_carrier_performance_report import valid_ai_performance_field

NOW = datetime(2026, 9, 10, tzinfo=ZoneInfo('Asia/Hong_Kong'))


class PerformanceAgentTests(unittest.TestCase):
    def setUp(self):
        profile = patch('cmhk.reporting.performance_agent.company_profile', return_value={
            'official_hosts': ['hkt.com'], 'seed_urls': []})
        profile.start()
        self.addCleanup(profile.stop)

    def test_database_first_and_no_unrelated_writes(self):
        baseline = {'sources': ['formal.json'], 'companies': {'HKT': {
            m: [{'period': 'H1 2026', 'value': 100, 'unit': 'HKD million'}]
            for m in ['收入', '资本开支', '净利润', 'EBITDA', '派息']}}}
        queries = []
        def search(query, limit):
            queries.append(query)
            return {'results': [], 'provider': 'test'}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = root / 'formal.json'
            db.write_text(json.dumps(baseline))
            before = db.read_bytes()
            model = build_model(root, ['HKT'], now=NOW, baseline_loader=lambda p: baseline,
                search_client=search, page_reader=lambda u: self.fail('no results'),
                ai_client=lambda packs: ({'companies': []}, 'test'), validator=valid_ai_performance_field,
                progress=lambda t: None)
            self.assertEqual(db.read_bytes(), before)
            self.assertEqual(len(queries), 2)  # Only missing opinions and market reaction.
            self.assertTrue(all('评级' in q or '股价' in q for q in queries))
            self.assertIn('H1 2026', model['table'][1][2])
            self.assertEqual(model['researchAudit']['trigger'], 'report_generation_only')
            self.assertEqual({p.name for p in root.iterdir()}, {'formal.json', 'var'})

    def test_stale_database_and_future_or_undated_pages_are_not_current(self):
        self.assertFalse(fresh_rows([{'period': 'FY2025'}], 'revenue', NOW.date()))
        self.assertFalse(fresh_rows([{'period': '2026-08-01'}], 'broker', NOW.date()))
        self.assertEqual(publication_date({}, {'publication_date': '2026-09-09T12:00:00Z'}).isoformat(), '2026-09-09')
        def search(query, limit):
            return {'results': [{'title': 'HKT future', 'url': 'https://www.hkt.com/a', 'snippet': '2027-01-01 HKT'}]}
        with tempfile.TemporaryDirectory() as temp:
            model = build_model(Path(temp), ['HKT'], now=NOW,
                baseline_loader=lambda p: {'companies': {}, 'sources': []}, search_client=search,
                page_reader=lambda u: {'opened': True, 'text': 'HKT 2027-01-01 新收入100亿元'},
                ai_client=lambda p: ({'companies': []}, 'test'), validator=valid_ai_performance_field, progress=lambda t: None)
            audit_dir = Path(model['researchAudit']['runDirectory'])
            searches = json.loads((audit_dir / 'searches.json').read_text())['searches']
            self.assertTrue(all(not s['results'] for s in searches))
            self.assertEqual(len(model['researchAudit']['unresolved']), 7)

    def test_recent_company_matched_citation_is_accepted(self):
        def search(query, limit):
            return {"results": [{"title": "HKT Trust 2026-09-09", "url": "https://www.hkt.com/broker", "snippet": "机构观点"}]}
        def model(packs):
            return {"companies": [{"company": "HKT", "fields": {"broker": "机构于2026年9月9日维持买入评级，目标价100港元。"},
                                    "sources": {"broker": ["https://www.hkt.com/broker"]}}]}, "test"
        with tempfile.TemporaryDirectory() as temp:
            result = build_model(Path(temp), ["HKT"], now=NOW,
                baseline_loader=lambda p: {"companies": {}, "sources": []}, search_client=search,
                page_reader=lambda u: {"opened": True, "text": "HKT Trust 2026年9月9日 机构维持买入评级 目标价100港元"},
                ai_client=model, validator=valid_ai_performance_field, progress=lambda t: None)
            self.assertTrue(result["researchAudit"]["companies"][0]["fields"]["broker"]["accepted"])

    def test_citation_from_another_field_cannot_support_new_number(self):
        def search(query, limit):
            return {'results': [{'title': 'HKT 2026-09-09', 'url': 'https://www.hkt.com/' + ('broker' if '评级' in query else 'other'), 'snippet': 'HKT 2026-09-09'}]}
        def model(packs):
            return {'companies': [{'company': 'HKT', 'fields': {'dividend': '公司每股派息100港元，保持稳定。'},
                                    'sources': {'dividend': ['https://www.hkt.com/broker']}}]}, 'test'
        with tempfile.TemporaryDirectory() as temp:
            result = build_model(Path(temp), ['HKT'], now=NOW,
                baseline_loader=lambda p: {'companies': {}, 'sources': []}, search_client=search,
                page_reader=lambda u: {'opened': True, 'text': 'HKT 2026-09-09 目标价100港元'},
                ai_client=model, validator=valid_ai_performance_field, progress=lambda t: None)
            self.assertFalse(result['researchAudit']['companies'][0]['fields']['dividend']['accepted'])
            self.assertNotIn('100', result['sections'][0]['items'][0])

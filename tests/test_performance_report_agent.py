import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from cmhk.reporting.performance_agent import build_model, FIELDS, fresh_rows, publication_date, trusted_source, field_text, field_excerpt
from generate_carrier_performance_report import valid_ai_performance_field

NOW = datetime(2026, 9, 10, tzinfo=ZoneInfo('Asia/Hong_Kong'))


class PerformanceAgentTests(unittest.TestCase):
    def setUp(self):
        profile = patch('cmhk.reporting.performance_agent.company_profile', return_value={
            'official_hosts': ['hkt.com'], 'seed_urls': []})
        profile.start()
        self.addCleanup(profile.stop)
        market = patch('cmhk.reporting.performance_agent.market_source_urls', return_value=[])
        market.start()
        self.addCleanup(market.stop)

    def test_financial_sources_are_official_and_views_use_identifiable_publishers(self):
        self.assertTrue(trusted_source("HKT", "https://www.hkt.com/report", "capex"))
        self.assertFalse(trusted_source("HKT", "https://www.bilibili.com/video/x", "capex"))
        self.assertFalse(trusted_source("HKT", "https://finance.yahoo.com/story", "capex"))
        self.assertTrue(trusted_source("HKT", "https://finance.yahoo.com/story", "broker"))
        self.assertTrue(trusted_source('中国铁塔', 'https://doc.irasia.com/listco/hk/chinatower/interim/2026/intrep.pdf', 'dividend'))
        self.assertFalse(trusted_source('中国铁塔', 'https://doc.irasia.com/listco/hk/other/intrep.pdf', 'dividend'))

    def test_database_first_and_no_unrelated_writes(self):
        baseline = {'sources': ['formal.json'], 'companies': {'HKT': {
            m: [{'period': 'H1 2026', 'value': 100, 'unit': 'HKD million'}]
            for m in ['收入', '资本开支', '净利润', 'EBITDA', '派息', '战略升级']}}}
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
            self.assertIn('2026H1', model['table'][1][2])
            self.assertEqual(model['researchAudit']['trigger'], 'report_generation_only')
            self.assertEqual({p.name for p in root.iterdir()}, {'formal.json', 'var'})

    def test_financial_excerpt_reads_late_notes_and_uses_url_publication_date(self):
        text = 'Annual report ' + ('contents ' * 4000) + 'interim dividend 34.80 HK cents'
        self.assertIn('34.80', field_excerpt(text, 'dividend'))
        self.assertEqual(publication_date({'url': 'https://www.hkexnews.hk/2026081300218.pdf'},
            {'text': 'For six months ended 2026-06-30'}).isoformat(), '2026-08-13')
        self.assertEqual(publication_date({'url': 'https://example.com/2026_09_03_1042.pdf'},
            {'document_type': 'pdf', 'text': 'Dividend payment on 2026-09-20'}).isoformat(), '2026-09-03')
        self.assertIsNone(publication_date({'url': 'https://example.com/ir2026/financial.pdf'},
            {'document_type': 'pdf', 'text': 'Incorporated on 3 August 2007. Six months ended 30 June 2026.'}))

    def test_publication_dates_and_exact_amounts_survive_chinese_editing(self):
        cases = [
            ('dividend', '2026年7月29日公告，派发中期股息34.80港仙。', '2026-07-29 interim distribution 34.80 HK cents'),
            ('broker', '瑞银2026年7月29日维持买入，目标价13.40港元。', 'UBS Buy $13.40 Jul 29, 2026'),
            ('broker', '瑞银2026年7月29日维持买入，目标价13.40港元。', '2026.07.29 UBS Buy $13.40'),
            ('dividend', '2025年末期股息每股人民币0.1329元。', '2025 final dividend RMB0.1329 per share'),
            ('strategy', '新项目合约额超过22亿港元，推进人工智能转型。', 'new contract value exceeding HK$2.2 billion AI transformation')]
        for field, text, source in cases:
            self.assertTrue(valid_ai_performance_field(field, text, source)[0])
        self.assertFalse(valid_ai_performance_field('broker', '瑞银目标价提高至99港元。', 'UBS target HK$13.40')[0])

    def test_database_display_deduplicates_and_excludes_processing_notes(self):
        rows = [{'period': 'H1 2026', 'metric': '收入', 'value': 2846, 'unit': 'millions HKD',
                 'scope': 'official_source_count_below_three_displayed'}] * 2
        self.assertEqual(field_text(rows), '2026年上半年 收入 2846 百万港元')

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

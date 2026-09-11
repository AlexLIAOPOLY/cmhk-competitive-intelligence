import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from cmhk.reporting.performance_agent import build_model, FIELDS, fresh_rows, publication_date, trusted_source, field_text, field_excerpt, compact_table_value, assess_field, previous_opinion_sources, revision_pack
from generate_carrier_performance_report import valid_ai_performance_field

NOW = datetime(2026, 9, 10, tzinfo=ZoneInfo('Asia/Hong_Kong'))


class PerformanceAgentTests(unittest.TestCase):
    def test_prior_reviewed_opinion_url_is_reopened_and_expired_page_rejected(self):
        url = 'https://www.hkt.com/comment'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            audit = root / 'var/performance_reports/20260909-accepted/audit.json'
            audit.parent.mkdir(parents=True)
            audit.write_text(json.dumps({'generatedAt': '2026-09-09T12:00:00+08:00', 'companies': [
                {'company': 'HKT', 'fields': {'broker': {'accepted': True, 'sources': [url]}}}]}))
            self.assertEqual(previous_opinion_sources(root, 'HKT', today=NOW.date())[0]['url'], url)
            opened = []
            def reader(u):
                opened.append(u)
                return {'opened': True, 'publication_date': '2020-01-01', 'text': 'HKT Trust old opinion'}
            result = build_model(root, ['HKT'], now=NOW, baseline_loader=lambda _: {'companies': {}, 'sources': []},
                search_client=lambda *a: {'results': []}, page_reader=reader,
                ai_client=lambda _: ({'companies': []}, 'test'), validator=valid_ai_performance_field, progress=lambda _: None)
            self.assertIn(url, opened)
            self.assertFalse(result['researchAudit']['companies'][0]['fields']['broker']['accepted'])

    def test_revision_cannot_reuse_rejected_market_numbers_or_other_field_evidence(self):
        pack = {'company': 'i-CABLE', 'asOf': '2026-09-11', 'missing': ['market'],
                'evidence': {'market': 'old quote', 'profit': 'profit 999'},
                'web_research': {'results': [{'field': 'market', 'text': '2026-09-11 0.0630'},
                                           {'field': 'profit', 'text': 'profit 999'}]}}
        fixed = revision_pack(pack, {'market': '出现事实包之外的数字'})
        self.assertEqual(fixed['evidence'], {'market': ''})
        self.assertEqual(len(fixed['web_research']['results']), 1)
        self.assertNotIn('previousDraft', fixed)

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

    def test_new_annual_filing_supersedes_a_recent_but_older_database_source(self):
        old = {'period': 'H1 2026', 'value': 100, 'unit': 'millions HKD',
               'source_url': 'https://www.hkt.com/2026/02/2026_02_24.pdf'}
        undated_copy = {**old, 'source_url': 'https://www.hkt.com/interim2026.pdf'}
        baseline = {'sources': [], 'companies': {'HKT': {m: [old, undated_copy] for m in ['收入', '净利润', 'EBITDA', '资本开支', '派息']}}}
        url = 'https://www.hkt.com/2026/09/2026_09_03.pdf'
        def search(query, limit):
            return {'results': [{'url': url, 'title': 'HKT Trust 2026 Annual Results Announcement'}]}
        def model(packs):
            return {'companies': [{'company': 'HKT', 'fields': {'revenue': '2026财年收入200百万港元。'},
                                   'sources': {'revenue': [url]}}]}, 'test'
        with tempfile.TemporaryDirectory() as temp:
            result = build_model(Path(temp), ['HKT'], now=NOW, baseline_loader=lambda p: baseline,
                search_client=search, page_reader=lambda u: {'opened': True, 'document_type': 'pdf', 'text': 'HKT Trust 2026 revenue 200 million HKD'},
                ai_client=model, validator=valid_ai_performance_field, progress=lambda t: None)
        self.assertIn('200', result['table'][1][2])
        self.assertIn('FY2026', result['table'][1][1])
        self.assertTrue(result['researchAudit']['companies'][0]['fields']['revenue']['needsResearch'])
        self.assertEqual(baseline['companies']['HKT']['收入'][0]['value'], 100)

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
        self.assertEqual(publication_date({'url': 'https://example.com/2026/09/2026_09_03_1042.pdf'},
            {'document_type': 'pdf', 'text': 'Dividend payment on 2026-09-20'}).isoformat(), '2026-09-03')
        self.assertIsNone(publication_date({'url': 'https://example.com/ir2026/financial.pdf'},
            {'document_type': 'pdf', 'text': 'Incorporated on 3 August 2007. Six months ended 30 June 2026.'}))

    def test_publication_dates_and_exact_amounts_survive_chinese_editing(self):
        cases = [
            ('dividend', '2026年7月29日公告，派发中期股息34.80港仙。', '2026-07-29 interim distribution 34.80 HK cents'),
            ('broker', '瑞银2026年7月29日维持买入，目标价13.40港元。', 'UBS Buy $13.40 Jul 29, 2026'),
            ('broker', '瑞银2026年7月29日维持买入，目标价13.40港元。', '2026.07.29 UBS Buy $13.40'),
            ('dividend', '2025年末期股息每股人民币0.1329元。', '2025 final dividend RMB0.1329 per share'),
            ('market', '2026年9月10日16:08，股价报4.605港元。', 'Sep 10, 2026 at 4:08PM HKT HKD 4.605'),
            ('strategy', '超过26万座数字塔为行业客户提供数智化服务。', 'over 260,000 digital towers serving industry customers'),
            ('strategy', '新项目合约额超过22亿港元，推进人工智能转型。', 'new contract value exceeding HK$2.2 billion AI transformation')]
        for field, text, source in cases:
            self.assertTrue(valid_ai_performance_field(field, text, source)[0])
        self.assertFalse(valid_ai_performance_field('broker', '瑞银目标价提高至99港元。', 'UBS target HK$13.40')[0])

    def test_verbose_supported_views_keep_complete_clauses_and_attribution(self):
        opinion = '瑞银维持买入评级，关注企业业务与现金流增长。' * 12 + '（来源：公开评级页面）'
        ok, text, _ = valid_ai_performance_field('broker', opinion, opinion)
        self.assertTrue(ok)
        self.assertLessEqual(len(text), 160)
        self.assertTrue(text.endswith('。（来源：公开评级页面）'))
        body = '公司推进网络升级和人工智能服务。' * 8 + '同时，' + '企业持续扩大服务覆盖和优化营运效率' * 12
        ok, text, _ = valid_ai_performance_field('strategy', body, body)
        self.assertTrue(ok)
        self.assertNotRegex(text, r'(同时|此外|另外)[。；，]?$')

    def test_verified_dividend_survives_an_unsupported_later_total(self):
        url = 'https://www.hkt.com/results.pdf'
        pack = {'company': 'HKT', 'missing': ['dividend'], 'evidence': {'dividend': ''},
                'web_research': {'results': [{'field': 'dividend', 'url': url, 'title': 'HKT 2026 interim report',
                    'text': '2026 Interim dividend per share 34.80 HK cents', 'publishedAt': ''}]}}
        draft = {'fields': {'dividend': '2026年中期股息每股34.80港仙。股息总额999亿元。'}, 'sources': {'dividend': [url]}}
        ok, text, reason, _ = assess_field(pack, draft, 'dividend', valid_ai_performance_field)
        self.assertTrue(ok)
        self.assertIn('34.80港仙', text)
        self.assertNotIn('999', text)
        draft['fields']['dividend'] = '2026年中期股息每股999港仙。'
        self.assertFalse(assess_field(pack, draft, 'dividend', valid_ai_performance_field)[0])

    def test_table_uses_per_share_dividend_and_keeps_cash_flow_sign(self):
        profits = '2026H1 EBITDA人民币302.52亿元；归属于公司股东的利润人民币74.89亿元'
        self.assertIn('74.89', compact_table_value(profits, 'profit'))
        self.assertEqual(compact_table_value('2026H1 2013.64亿元人民币', 'revenue'), '2026H1 2013.64亿元人民币')
        self.assertEqual(compact_table_value('H1 2026 2013.64亿元人民币', 'revenue'), '2026H1 2013.64亿元人民币')
        self.assertEqual(compact_table_value('1H 2026: RMB48,693 million', 'revenue'), '2026H1: 48,693百万元人民币')
        self.assertEqual(compact_table_value('1H 2026 interim: RMB0.19122 per share', 'dividend'), '2026H1 中期: 每股0.19122元人民币')
        text = '2026年中期董事会决定分配股息146.96亿元，总股本91,507,138,699股，每股派发0.1606元人民币；' + '继续保持稳健的股东回报政策。' * 5
        self.assertEqual(compact_table_value(text, 'dividend'), '2026年中期 每股0.1606元人民币')
        flow = '2026H1资本开支现金流为人民币-324亿元；' + '公司持续推进基础设施建设与资本配置。' * 6
        self.assertEqual(compact_table_value(flow, 'capex'), '2026H1 现金流 人民币-324亿元')

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

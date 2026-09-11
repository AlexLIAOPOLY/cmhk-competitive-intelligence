from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock, patch

import generate_weekly_report as report
from tests.test_biweekly_report_quality import detailed_text, make_item, make_model


class TargetedRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for name, value in {
            'WEEKLY_LLM_CACHE': Path(self.temp.name) / 'cache.json',
            'WEEKLY_AI_QUALITY_AUDIT': Path(self.temp.name) / 'quality.json',
            'WEEKLY_USAGE_AUDIT': Path(self.temp.name) / 'usage.json',
        }.items():
            context = patch.object(report, name, value)
            context.start()
            self.addCleanup(context.stop)

    def thin_item(self):
        item = make_item('W001', 1, title='测试主体公布网络部署')
        item['originalTitle'] = item['title']
        item['detail'] = item['rawDetail'] = item['title'] + '。'
        item['webResearch'] = {'lockedSourceEvidence': {
            'url': 'https://example.test/article',
            'content': detailed_text('测试主体公布网络部署。'),
        }}
        return item

    def response(self, item):
        return {'items': [{'id': item['id'], 'status': 'ok', 'title': item['title'],
                           'detail': item['webResearch']['lockedSourceEvidence']['content']}]}

    def test_repairs_only_thin_item_and_retains_all_selected_news(self):
        thin = self.thin_item()
        model = make_model(thin)
        good = make_item('W002', 2)
        model['sections'][0]['items'].append(good)
        original_body = good['detail']
        with (
            patch.object(report, '_call_weekly_writer_llm', return_value=self.response(thin)) as writer,
            patch.object(report, 'research_weekly_model_online') as research,
        ):
            repaired = report.prepare_human_template_content(model, progress=lambda _: None)
        self.assertEqual(len(repaired['sections'][0]['items']), 2)
        self.assertEqual(good['detail'], original_body)
        self.assertEqual(writer.call_count, 1)
        self.assertEqual(writer.call_args.args[0][0]['id'], 'W001')
        research.assert_not_called()
        report.validate_human_template_content(repaired)

    def test_transient_failure_retries_only_pending_and_preserves_evidence(self):
        thin = self.thin_item()
        locked = deepcopy(thin['webResearch']['lockedSourceEvidence'])
        model = make_model(thin)
        with (
            patch.object(report, '_call_weekly_writer_llm', side_effect=[TimeoutError('timeout'), self.response(thin)]) as writer,
            patch.object(report, 'research_weekly_model_online', side_effect=RuntimeError('offline')) as research,
        ):
            repaired = report.prepare_human_template_content(model, progress=lambda _: None)
        self.assertEqual(writer.call_count, 2)
        self.assertEqual(research.call_count, 1)
        self.assertEqual(thin['webResearch']['lockedSourceEvidence'], locked)
        self.assertEqual([v['status'] for v in repaired['humanTemplateRepairAttempts']], ['pending', 'passed'])

    def test_unsupported_numbers_do_not_pass_and_block_is_audited(self):
        thin = self.thin_item()
        response = self.response(thin)
        response['items'][0]['detail'] += '项目新增投资98765亿元。'
        with (
            patch.object(report, '_call_weekly_writer_llm', return_value=response) as writer,
            patch.object(report, 'research_weekly_model_online', side_effect=RuntimeError('offline')),
            self.assertRaisesRegex(ValueError, '已停止发布'),
        ):
            report.prepare_human_template_content(make_model(thin), progress=lambda _: None)
        self.assertEqual(writer.call_count, 2)
        audit = json.loads(report.WEEKLY_AI_QUALITY_AUDIT.read_text())
        self.assertEqual(audit['reviewStatus'], 'blocked')
        self.assertEqual(len(audit['repairAttempts']), 2)

    def test_validated_checkpoint_reuses_draft_but_changed_evidence_invalidates_it(self):
        item = self.thin_item()
        initial = deepcopy(item)
        response = self.response(item)
        with patch.object(report, '_call_weekly_writer_llm', return_value=response) as writer:
            report.write_weekly_items_once([item], progress=lambda _: None)
            resumed = report.write_weekly_items_once([initial], progress=lambda _: None)
        self.assertEqual(writer.call_count, 1)
        self.assertEqual(resumed[0]['writerStatus'], 'validated_cache_recovery')
        initial['webResearch']['lockedSourceEvidence']['url'] = 'https://example.test/different'
        self.assertIsNone(report._load_weekly_draft_checkpoint(initial))

    def test_recovery_keeps_completed_research_and_writer_when_editing_crashes(self):
        item = self.thin_item()
        selected = make_model(item)
        selected['selectionSource'] = 'feishu_weekly_review'
        researched = deepcopy(selected)
        written = deepcopy(item)
        written['detail'] = detailed_text('测试主体公布网络部署。')
        with (
            patch.object(report, 'build_review_sheet_weekly_model', return_value=selected),
            patch.object(report, 'research_weekly_model_online', return_value=researched),
            patch.object(report, 'write_weekly_items_once', return_value=[written]),
            patch.object(report, 'edit_weekly_items_once', side_effect=RuntimeError('editor crashed')),
        ):
            recovered = report.build_weekly_model([])
        self.assertEqual(recovered['sections'][0]['items'][0]['detail'], written['detail'])
        self.assertEqual(recovered['sections'][0]['items'][0]['webResearch'], researched['sections'][0]['items'][0]['webResearch'])

    def test_complete_reference_is_not_crowded_out_by_two_snippets(self):
        item = self.thin_item()
        item['webResearch']['results'] = [
            {'title': item['title'], 'url': f'https://example.test/{i}', 'snippet': '简讯。'} for i in range(2)
        ] + [{'title': item['title'], 'url': 'https://example.test/full', 'content': '完整参考正文包含部署节点和技术方案。'}]
        facts = report.weekly_writer_fact_package(item)
        self.assertTrue(any('完整参考正文' in fact['value'] for fact in facts if fact['role'] == 'matching_search_reference'))

    def test_unrelated_search_hits_trigger_traditional_keyword_fallback(self):
        item = self.thin_item()
        item['title'] = item['originalTitle'] = 'HGC环电推出商业安全宽频2.0方案'
        queries = []
        def search(query, limit):
            queries.append(query)
            title = '完全无关的网页' if len(queries) == 1 else 'HGC環電商業安全寬頻2.0'
            return {'query': query, 'results': [{'title': title, 'url': 'https://example.test/news'}]}
        researched = report.research_weekly_model_online(make_model(item), search_client=search, progress=lambda _: None)
        self.assertEqual(len(queries), 2)
        self.assertIn('環電', queries[1])
        self.assertIn('2.0', queries[1])
        self.assertEqual(researched['sections'][0]['items'][0]['webResearch']['results'][0]['title'], 'HGC環電商業安全寬頻2.0')

    def test_official_pdf_fulltext_is_available_to_writer(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.iter_bytes.return_value = [b'%PDF-1.7 test']
        page = MagicMock()
        page.extract_text.return_value = detailed_text('完整新闻正文。') * 3
        reader = MagicMock()
        reader.pages = [page]
        with (
            patch.object(report.httpx, 'stream', return_value=response),
            patch('pypdf.PdfReader', return_value=reader),
        ):
            text = report._fetch_search_result_content({'title': '测试主体公布网络部署', 'url': 'https://example.test/news.pdf'}, '测试主体公布网络部署')
        self.assertIn('完整新闻正文', text)


if __name__ == '__main__':
    unittest.main()

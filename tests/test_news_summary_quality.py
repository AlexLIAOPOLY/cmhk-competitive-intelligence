import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cmhk.services.news_summary_quality import (
    SummaryQualityError, enrich_source, extract_article_text, repeats_title,
    review_summaries, validate_review,
)
from cmhk.services.news_digest_editor import prepare_digest


TITLE = '香港宽频企业方案与博云国际达成战略合作 推动AI Agent方案'
ECHO = '香港宽频企业方案与博云国际达成战略合作，共同推动AI Agent解决方案落地。'
SOURCE = '双方计划首批向制造企业提供库存管理服务，并提供员工操作培训。'
SUMMARY = '香港宽频企业方案与博云国际达成合作，计划首批向制造企业提供库存管理服务，并提供员工操作培训。'
REVIEW = {'accepted': True, 'summary_detail': '首批向制造企业提供库存管理服务',
          'source_quote': '首批向制造企业提供库存管理服务', 'reason': '具体客户对象和服务内容均来自原文，标题未包含。'}
# Synthetic source for tests only; never used in live editorial evidence.


class SummaryQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = {'id': '0', 'title': TITLE, 'source_summary': SOURCE}

    def test_rejects_copy_punctuation_and_traditional_variants(self):
        for title, summary in [(TITLE, TITLE + '。'), (TITLE, ECHO),
                ('深港迈向更高水平合作，本港低空经济规范化及特区政府六职系联合招聘',
                 '深港两地迈向更高水平合作；香港低空经济走向规范化发展；特区政府同步展开六个职系的联合招聘工作。'),
                ('香港电讯推出新方案', '香港電訊推出新方案。')]:
            with self.subTest(summary=summary):
                # A lower lexical overlap still needs independent semantic review.
                if title == TITLE or '电讯' in title:
                    self.assertTrue(repeats_title(title, summary))
                with self.assertRaises(SummaryQualityError):
                    review_summaries([{'title': title}], [{'summary': summary}], self.root,
                                     model_call=Mock(return_value={'accepted': False, 'reason': '仅换词重述标题'}))

    def test_short_but_informative_summary_passes_with_exact_evidence_and_cache(self):
        source = {'title': '瑞银将中国联通评级从中性上调至买入',
                  'source_summary': '瑞银将中国联通评级从中性上调至买入，目标价7.10港元。'}
        summary = source['source_summary']
        result = {'accepted': True, 'summary_detail': '目标价7.10港元',
                  'source_quote': '目标价7.10港元', 'reason': '新增来源明确的目标价'}
        model = Mock(return_value=result)
        for _ in range(2):
            self.assertEqual(review_summaries([source], [{'summary': summary}], self.root, model_call=model), [result])
        model.assert_called_once()
        with self.assertRaises(SummaryQualityError):
            review_summaries([{**source, 'source_summary': '目标价已撤回'}], [{'summary': summary}], self.root, model_call=model)

    def test_fabricated_quotes_missing_verdict_and_title_only_details_rejected(self):
        for result in [None, {}, {**REVIEW, 'accepted': 'true'},
                       {**REVIEW, 'source_quote': '投资额为十亿元'},
                       {**REVIEW, 'summary_detail': '库存已经清空'},
                       {**REVIEW, 'summary_detail': '香港宽频企业方案'}]:
            with self.subTest(result=result), self.assertRaises(SummaryQualityError):
                validate_review(result, self.source, SUMMARY)

    def test_semantic_restatement_rejected_by_independent_reviewer(self):
        paraphrase = '这次携手将两家公司的资源结合起来，一起促进智能代理解决方案的应用和部署。'
        self.assertFalse(repeats_title(TITLE, paraphrase))
        model = Mock(return_value={'accepted': False, 'reason': '没有增加功能、客户、时间或其他事实'})
        with self.assertRaises(SummaryQualityError):
            review_summaries([self.source], [{'summary': paraphrase}], self.root, model_call=model)
        model.assert_called_once()
        self.assertFalse(list((self.root / 'var/subscriptions/news-summary-reviews').glob('*.json')))

    def test_original_body_excludes_related_news_and_never_uses_whole_page(self):
        html = ('<nav>菜单</nav><article><p>' + SOURCE + '</p><aside>其他新闻</aside>'
                '<div class="related">推荐投资百亿元</div><figure>图片来自另一事件</figure></article>')
        self.assertEqual(extract_article_text(html.encode()), SOURCE)
        self.assertEqual(extract_article_text(b'<main><div>Only a menu</div></main>'), '')
        schema = json.dumps({'@type': 'NewsArticle', 'articleBody': SOURCE}, ensure_ascii=False)
        self.assertEqual(extract_article_text(('<script type="application/ld+json">' + schema + '</script>').encode()), SOURCE)

    def test_thin_excerpt_enrichment_is_same_original_and_reused(self):
        url = 'https://publisher.example/original'
        with patch('cmhk.services.news_delivery_assets.fetch', return_value=(
                ('<article>' + SOURCE + '</article>').encode(), url, 'text/html')) as fetch:
            for _ in range(2):
                enriched = enrich_source({'news_url': url, 'image_page_url': 'https://unrelated.example/'}, self.source, self.root)
                self.assertEqual(enriched['source_content'], SOURCE)
                self.assertEqual(enriched['source_evidence_url'], url)
            fetch.assert_called_once_with(url)

    def test_editor_rewrites_rejected_title_echo_then_checks_and_caches_real_result(self):
        editor = Mock(side_effect=[{'items': [{'id': '0', 'summary': ECHO}]},
                                  {'id': '0', 'summary': SUMMARY}])
        with patch('strategic_briefing._call_internal_ai', return_value=REVIEW) as reviewer:
            prepared = prepare_digest([self.source], self.root, model_call=editor)
            self.assertEqual(prepared['items'][0]['digest_summary'], SUMMARY)
            self.assertEqual(prepared['summary_reviews'], [REVIEW])
            again = prepare_digest([self.source], self.root, model_call=editor)
            self.assertEqual(again, prepared)
            self.assertEqual(editor.call_count, 2)
            reviewer.assert_called_once()

    def test_editor_quality_failure_never_marks_prepared_and_retry_has_reason(self):
        editor = Mock(side_effect=[{'items': [{'id': '0', 'summary': SUMMARY}]},
                                  {'id': '0', 'summary': SUMMARY}, {'id': '0', 'summary': SUMMARY}])
        with patch('strategic_briefing._call_internal_ai', return_value={'accepted': False, 'reason': '来源不足'}):
            with self.assertRaises(SummaryQualityError):
                prepare_digest([{'title': TITLE}], self.root, model_call=editor)
        self.assertFalse(list((self.root / 'var/subscriptions/news-editor').glob('*.json')))
        self.assertIn('来源不足', json.loads(editor.call_args.args[1])['revision_required'])

    def test_old_editor_cache_cannot_bypass_new_quality_gate(self):
        cache = self.root / 'var/subscriptions/news-editor'
        cache.mkdir(parents=True)
        (cache / 'old.json').write_text(json.dumps({'editor_version': 8, 'inputs': [self.source],
            'model_output': {'items': [{'id': '0', 'summary': ECHO}]}}))
        editor = Mock(return_value={'items': [{'id': '0', 'summary': SUMMARY}]})
        with patch('strategic_briefing._call_internal_ai', return_value=REVIEW):
            self.assertEqual(prepare_digest([self.source], self.root, model_call=editor)['items'][0]['digest_summary'], SUMMARY)
        editor.assert_called_once()

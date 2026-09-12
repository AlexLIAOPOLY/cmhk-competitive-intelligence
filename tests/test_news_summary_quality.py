import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cmhk.services.news_summary_quality import (
    SummaryQualityError, enrich_source, extract_article_text, repeats_title,
    review_summaries, validate_review, quote_options,
)
from cmhk.services.news_digest_editor import prepare_digest


TITLE = '香港宽频企业方案与博云国际达成战略合作 推动AI Agent方案'
ECHO = '香港宽频企业方案与博云国际达成战略合作，共同推动AI Agent解决方案落地。'
SOURCE = '双方计划首批向制造企业提供库存管理服务，并提供员工操作培训。'
SUMMARY = '香港宽频企业方案与博云国际达成合作，计划首批向制造企业提供库存管理服务，并提供员工操作培训。'
REVIEW = {'accepted': True, 'verdict': 'accept', 'summary_detail': '计划首批向制造企业提供库存管理服务',
          'source_quote': '双方计划首批向制造企业提供库存管理服务', 'reason': '具体客户对象和服务内容均来自原文，标题未包含。'}
# Synthetic source for tests only; never used in live editorial evidence.


def indexed(review):
    def respond(system, user, **kwargs):
        payload = json.loads(user)
        return {'verdict': 'accept' if review['accepted'] else 'rewrite', 'reason': review['reason'],
                'summary_detail_index': payload['summary_details'].index(review['summary_detail']) if review['accepted'] else -1,
                'source_quote_index': payload['source_quotes'].index(review['source_quote']) if review['accepted'] else -1}
    return respond


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
        result = {'accepted': True, 'verdict': 'accept', 'summary_detail': '目标价7.10港元',
                  'source_quote': '目标价7.10港元', 'reason': '新增来源明确的目标价'}
        model = Mock(side_effect=indexed(result))
        for _ in range(2):
            self.assertEqual(review_summaries([source], [{'summary': summary}], self.root, model_call=model), [result])
        model.assert_called_once()
        with self.assertRaises(SummaryQualityError):
            review_summaries([{**source, 'source_summary': '目标价已撤回'}], [{'summary': summary}], self.root,
                             model_call=Mock(return_value={'accepted': True, 'reason': 'bad', 'summary_detail_index': 1, 'source_quote_index': 999}))

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
        model = Mock(side_effect=indexed({'accepted': False, 'reason': '没有增加功能、客户、时间或其他事实'}))
        with self.assertRaises(SummaryQualityError):
            review_summaries([self.source], [{'summary': paraphrase}], self.root, model_call=model)
        model.assert_called_once()
        rejected = list((self.root / 'var/subscriptions/news-summary-reviews').glob('*.rejected.json'))
        self.assertEqual(len(rejected), 1)
        self.assertEqual(json.loads(rejected[0].read_text())['status'], 'rejected')

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

    def test_publisher_prose_wins_over_longer_unrelated_article_cards(self):
        html = '<title>Sanctions announced</title><h1>Sanctions announced</h1><div class="wp prose"><p>Sanctions apply to five banks.</p></div>'
        html += '<article><h2>Restaurant news</h2><p>' + 'Food tourism. ' * 100 + '</p></article>'
        self.assertEqual(extract_article_text(html.encode()), 'Sanctions apply to five banks.')

    def test_hk_publishers_body_containers_and_empty_cache_recovery(self):
        for container in ['newsDetail', 'xlCon']:
            html = '<title>公司发布服务</title><div class="' + container + '"><p>' + SOURCE + '</p></div><article><h2>美食推荐</h2>无关</article>'
            self.assertEqual(extract_article_text(html.encode()), SOURCE)
        from cmhk.services.news_delivery_assets import save, fingerprint
        from cmhk.services.news_summary_quality import VERSION
        url = 'https://publisher.example/recover'
        target = self.root / 'var/subscriptions/news-editor-sources' / (fingerprint([VERSION, url]) + '.json')
        import time
        save(target, {'source_content': '', 'fetched_at': time.time()})
        with patch('cmhk.services.news_delivery_assets.fetch', return_value=(html.encode(), url, 'text/html')) as fetch:
            self.assertEqual(enrich_source({'news_url': url}, {}, self.root)['source_content'], SOURCE)
        fetch.assert_called_once()

    def test_rereview_does_not_replay_cached_rejection_and_prefers_pro(self):
        requests = []
        def model(system, user, **kwargs):
            requests.append(json.loads(user))
            self.assertEqual(kwargs['model_override'], 'DeepSeek-V4-Pro')
            self.assertIn('<examples>', system)
            schema = kwargs['response_format']['json_schema']['schema']['properties']
            self.assertNotIn('accepted', schema)
            if len(requests) == 1:
                return {'verdict': 'rewrite', 'reason': '须重新确认事实', 'summary_detail_index': -1, 'source_quote_index': -1}
            self.assertIn('review_attempt', requests[-1])
            return indexed(REVIEW)(system, user, **kwargs)
        with self.assertRaises(SummaryQualityError):
            review_summaries([self.source], [{'summary': SUMMARY}], self.root, model_call=model)
        result = review_summaries([self.source], [{'summary': SUMMARY}], self.root, model_call=model)
        self.assertTrue(result[0]['accepted'])
        self.assertNotEqual(requests[0], requests[1])

    def test_untrusted_ai_summary_cannot_be_its_own_source_evidence(self):
        model = Mock()
        with self.assertRaises(SummaryQualityError):
            review_summaries([{'title': TITLE, 'summary': SUMMARY}], [{'summary': SUMMARY}], self.root, model_call=model)
        model.assert_not_called()

    def test_metadata_excerpt_is_available_to_review_without_inventing_body(self):
        url = 'https://publisher.example/original'
        html = '<meta property="og:title" content="服务在香港开放 支援图片输入"><meta name="description" content="用户可从独立应用使用服务。">'
        with patch('cmhk.services.news_delivery_assets.fetch', return_value=(html.encode(), url, 'text/html')):
            source = enrich_source({'news_url': url}, {}, self.root)
        self.assertEqual(source['source_page_description'], '用户可从独立应用使用服务。')
        self.assertNotIn('source_content', source)

    def test_editor_rewrites_rejected_title_echo_then_checks_and_caches_real_result(self):
        editor = Mock(side_effect=[{'items': [{'id': '0', 'summary': ECHO}]},
                                  {'id': '0', 'summary': SUMMARY}])
        with patch('strategic_briefing._call_internal_ai', side_effect=indexed(REVIEW)) as reviewer:
            prepared = prepare_digest([self.source], self.root, model_call=editor)
            self.assertEqual(prepared['items'][0]['digest_summary'], SUMMARY)
            self.assertEqual(prepared['summary_reviews'], [REVIEW])
            again = prepare_digest([self.source], self.root, model_call=editor)
            self.assertEqual(again, prepared)
            self.assertEqual(editor.call_count, 2)
            reviewer.assert_called_once()

    def test_missing_source_never_marks_prepared_or_wastes_a_prose_retry(self):
        editor = Mock(side_effect=[{'items': [{'id': '0', 'summary': SUMMARY}]},
                                  {'id': '0', 'summary': SUMMARY}, {'id': '0', 'summary': SUMMARY}])
        with patch('strategic_briefing._call_internal_ai', return_value={'accepted': False, 'reason': '来源不足'}) as reviewer:
            with self.assertRaises(SummaryQualityError):
                prepare_digest([{'title': TITLE}], self.root, model_call=editor)
        self.assertFalse(list((self.root / 'var/subscriptions/news-editor').glob('*.json')))
        editor.assert_called_once()
        reviewer.assert_not_called()

    def test_old_editor_cache_cannot_bypass_new_quality_gate(self):
        cache = self.root / 'var/subscriptions/news-editor'
        cache.mkdir(parents=True)
        (cache / 'old.json').write_text(json.dumps({'editor_version': 8, 'inputs': [self.source],
            'model_output': {'items': [{'id': '0', 'summary': ECHO}]}}))
        editor = Mock(return_value={'items': [{'id': '0', 'summary': SUMMARY}]})
        with patch('strategic_briefing._call_internal_ai', side_effect=indexed(REVIEW)):
            self.assertEqual(prepare_digest([self.source], self.root, model_call=editor)['items'][0]['digest_summary'], SUMMARY)
        editor.assert_called_once()

    def test_complete_single_envelope_preserves_real_prose_and_requires_fact_review(self):
        from strategic_briefing import AIInvalidStructuredResponse
        output = {'items': [{'id': '0', 'summary': SUMMARY}]}
        editor = Mock(side_effect=AIInvalidStructuredResponse(json.dumps(output, ensure_ascii=False), 'missing id, summary'))
        with patch('strategic_briefing._call_internal_ai', side_effect=indexed(REVIEW)) as reviewer:
            result = prepare_digest([self.source], self.root, model_call=editor, _single_response=True)
        self.assertEqual(result['items'][0]['digest_summary'], SUMMARY)
        self.assertEqual(result['summary_reviews'], [REVIEW])
        reviewer.assert_called_once()

    def test_review_schema_preserves_literal_traditional_source_evidence(self):
        source = {**self.source, 'source_summary': '首批向製造企業提供庫存管理服務，並提供員工操作培訓。'}
        review = {**REVIEW, 'source_quote': '首批向製造企業提供庫存管理服務'}
        model = Mock(side_effect=indexed(review))
        review_summaries([source], [{'summary': SUMMARY}], self.root, model_call=model)
        schema = model.call_args.kwargs['response_format']['json_schema']['schema']['properties']
        payload = json.loads(model.call_args.args[1])
        self.assertEqual(payload['comparison_title'], source['title'])
        self.assertIn('原文中出现是证据', payload['comparison_rule'])
        self.assertIn(review['source_quote'], payload['source_quotes'])
        self.assertNotIn(REVIEW['source_quote'], payload['source_quotes'])
        self.assertTrue(all(q in SUMMARY for q in payload['summary_details']))
        self.assertEqual(schema['source_quote_index']['type'], 'integer')
        english = 'UBS set the target price at HK$7.10.'
        self.assertIn(english, quote_options('Background sentence. ' * 40 + english, 500))

    def test_incomplete_or_wrong_single_envelope_cannot_be_salvaged(self):
        from strategic_briefing import AIInvalidStructuredResponse
        for content in ['{"items":', json.dumps({'items': json.dumps([{'id': '0', 'summary': SUMMARY}])}),
                        json.dumps({'items': [{'id': 'wrong', 'summary': SUMMARY}]}),
                        json.dumps({'items': [{'id': '0', 'summary': SUMMARY}, {'id': '1', 'summary': SUMMARY}]})]:
            with self.subTest(content=content), self.assertRaises(AIInvalidStructuredResponse):
                prepare_digest([self.source], self.root,
                    model_call=Mock(side_effect=AIInvalidStructuredResponse(content, 'wrong envelope')), _single_response=True)

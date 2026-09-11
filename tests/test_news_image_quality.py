import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from cmhk.services.news_delivery_assets import prepare_news_assets, fingerprint, save
from cmhk.services.news_delivery_guard import build_card_pages, deliver_news
from cmhk.services.news_image_quality import (
    NewsImageUnavailable, extract_candidates, policy_key, require_reviewed_images,
    review_image, search_image_candidates, search_queries, validate_image, _vision_call,
)
from cmhk.services.subscriptions import SubscriptionService, encode_strategic_news_digest
from tests.news_push_fixtures import prepared_assets


class NewsImageQualityTests(unittest.TestCase):
    def setUp(self):
        identity = patch('cmhk.services.news_image_quality._identity_review', return_value={
            'accepted': True, 'reason': '主体和事件独立核对一致'})
        identity.start()
        self.addCleanup(identity.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.item = {'news_id': 'event-1', 'title': '香港宽频与博云签约',
                     'summary': '香港宽频与博云就企业AI合作签约。', 'category': '竞对动态',
                     'source_url': 'https://publisher.example/article', 'published_at': '2026-09-11'}
        self.candidate = {'url': 'https://publisher.example/photo.png',
                          'page_url': self.item['source_url'], 'origin': 'article-body', 'context': '合作签约现场'}
        output = io.BytesIO()
        Image.new('RGB', (640, 480), 'blue').save(output, 'PNG')
        self.data = output.getvalue()
        self.verdict = {'relation': 'event', 'confidence': 0.96, 'reason': '同一签约现场',
                        'visible_content': '双方代表签署协议', 'source_evidence': '正文图注记录本次合作'}

    def test_extracts_article_schema_lazy_body_and_picture_but_excludes_ads_and_logos(self):
        page = '''<title>合作新闻</title><script type="application/ld+json">
          {"@graph":[{"@type":"Organization","logo":"/company.png"},
          {"@type":"NewsArticle","image":[{"url":"/event.jpg","caption":"签约"}]}]}</script>
          <article><figure><img data-src="/body.webp" src="/placeholder.png"><figcaption>现场</figcaption></figure>
          <picture><source srcset="/small.jpg 320w, /large.jpg 1200w"></picture>
          <aside><img src="/sidebar.jpg"></aside><div class="ad-slot"><img src="/random.jpg"></div>
          <img src="/logo.png"><div class="related-news"><img src="/unrelated.jpg"></div></article>
          <footer><img src="/footer.jpg"></footer>'''
        result = extract_candidates(page.encode(), self.item['source_url'])
        self.assertEqual(set(result['image_urls']), {f'https://publisher.example/{f}' for f in
                         ('event.jpg', 'body.webp', 'small.jpg', 'large.jpg')})
        self.assertEqual(next(c for c in result['image_candidates'] if c['url'].endswith('body.webp'))['context'].strip(), '现场')

    def test_share_image_is_only_a_candidate_and_does_not_receive_automatic_approval(self):
        result = extract_candidates(b'<meta property="og:image" content="/tea.jpg">', self.item['source_url'])
        self.assertEqual(result['image_candidates'][0]['origin'], 'share-metadata')
        self.assertNotIn('image_key', result)

    def test_tencent_rich_article_extracts_real_body_photos_and_keeps_ad_filter(self):
        page = b'''<div class="rich_media_content"><div class="nd-img">
        <img data-src="/event.jpg" src="/placeholder.png"></div><p>Signing ceremony</p>
        <div class="ad-slot"><img src="/unrelated.jpg"></div></div>'''
        result = extract_candidates(page, self.item['source_url'])
        self.assertEqual(result['image_urls'], ['https://publisher.example/event.jpg'])
        self.assertIn('Signing ceremony', result['image_candidates'][0]['context'])

    def test_other_article_thumbnail_inside_main_is_excluded_but_full_image_link_remains(self):
        page = '''<main><a href="/news/another-article"><picture><img src="/misleading.jpg"></picture></a>
        <figure><a href="/full.jpg"><img src="/thumbnail.jpg"></a></figure>
        <a href="#gallery"><img src="/event.jpg"></a>
        <div class="context-box__content story-list__holder"><img src="/recommendation.jpg"></div></main>'''
        result = extract_candidates(page.encode(), self.item['source_url'])
        self.assertEqual(set(result['image_urls']), {'https://publisher.example/thumbnail.jpg', 'https://publisher.example/event.jpg'})

    def test_visual_ad_rejection_cached_by_actual_bytes_news_and_policy(self):
        rejected = {**self.verdict, 'relation': 'reject', 'confidence': 1, 'reason': '栏目早茶海报'}
        with patch('cmhk.services.news_image_quality._vision_call', return_value=rejected) as call:
            for _ in range(3):
                result = review_image(self.item, self.candidate, self.data, self.root)
                self.assertFalse(result['accepted'])
            self.assertEqual(call.call_count, 1)
            review_image({**self.item, 'title': '另一事件'}, self.candidate, self.data, self.root)
            self.assertEqual(call.call_count, 2)
            with patch('cmhk.services.news_image_quality.policy_key', return_value='new-policy'):
                review_image(self.item, self.candidate, self.data, self.root)
            self.assertEqual(call.call_count, 2)
            with patch('cmhk.services.news_image_quality.policy_key', return_value='new-visual-policy'), \
                    patch('cmhk.services.news_image_quality.visual_policy_key', return_value='new-visual-policy'):
                review_image(self.item, self.candidate, self.data, self.root)
            self.assertEqual(call.call_count, 3)

    def test_independent_policy_change_rechecks_identity_but_reuses_visual_observations(self):
        with patch('cmhk.services.news_image_quality._vision_call', return_value=self.verdict) as visual, \
                patch('cmhk.services.news_image_quality._identity_review', side_effect=[
                    {'accepted': True, 'reason': '旧复核'}, {'accepted': False, 'reason': '新版发现主体冲突'}]) as identity:
            self.assertTrue(review_image(self.item, self.candidate, self.data, self.root)['accepted'])
            with patch('cmhk.services.news_image_quality.policy_key', return_value='changed-independent'):
                self.assertFalse(review_image(self.item, self.candidate, self.data, self.root)['accepted'])
            self.assertEqual(visual.call_count, 1)
            self.assertEqual(identity.call_count, 2)

    def test_independent_identity_check_overrules_confident_wrong_partner(self):
        with patch('cmhk.services.news_image_quality._vision_call', return_value={
                **self.verdict, 'confidence': 1, 'visible_content': 'HKBN 与 Futong 富通签约'}), \
                patch('cmhk.services.news_image_quality._identity_review', return_value={
                    'accepted': False, 'reason': '新闻是博云，图片却是富通，不是同一合作方'}):
            result = review_image(self.item, self.candidate, self.data, self.root)
        self.assertFalse(result['accepted'])
        self.assertIn('富通', result['independent_review']['reason'])

    def test_independent_review_outage_resumes_without_repeating_visual_work(self):
        with patch('cmhk.services.news_image_quality._vision_call', return_value=self.verdict) as visual, \
                patch('cmhk.services.news_image_quality._identity_review', side_effect=[
                    NewsImageUnavailable('暂时不可用'), {'accepted': True, 'reason': '主体一致'}]):
            with self.assertRaises(NewsImageUnavailable):
                review_image(self.item, self.candidate, self.data, self.root)
            self.assertTrue(review_image(self.item, self.candidate, self.data, self.root)['accepted'])
            self.assertEqual(visual.call_count, 1)

    def test_model_missing_evidence_or_low_confidence_cannot_pass(self):
        for result in [{}, {**self.verdict, 'confidence': True}]:
            with self.subTest(result=result), patch('cmhk.services.news_image_quality._vision_call', return_value=result):
                with self.assertRaises(NewsImageUnavailable):
                    review_image(self.item, self.candidate, self.data, self.root)
        with patch('cmhk.services.news_image_quality._vision_call', return_value={**self.verdict, 'confidence': 0.6}):
            self.assertFalse(review_image(self.item, self.candidate, self.data, self.root)['accepted'])
        with patch('cmhk.services.news_image_quality._vision_call', return_value={**self.verdict, 'source_evidence': ''}):
            different = {**self.item, 'title': '缺少出处的图片'}
            self.assertFalse(review_image(different, self.candidate, self.data, self.root)['accepted'])

    def test_missing_photo_searches_and_uploads_identical_reviewed_bytes_without_visible_caption(self):
        service = SimpleNamespace(runtime_root=self.root, _lark=Mock())
        metadata = {'news_url': self.item['source_url'], 'image_candidates': []}
        with patch('cmhk.services.news_delivery_assets.source_metadata', return_value=metadata), \
                patch('cmhk.services.news_delivery_assets.search_image_candidates', return_value=[self.candidate]) as search, \
                patch('cmhk.services.news_delivery_assets.fetch', return_value=(self.data, self.candidate['url'], 'image/png')), \
                patch('cmhk.services.news_image_quality._vision_call', return_value={**self.verdict, 'relation': 'context'}), \
                patch('cmhk.services.news_delivery_assets.upload_image', return_value='img_verified') as upload:
            items = prepare_news_assets([self.item], service, profile='test', fallback_image_key='img_banner')
        search.assert_called_once()
        self.assertIs(upload.call_args.kwargs['data'], self.data)
        self.assertEqual(items[0]['news_url'], self.item['source_url'])
        card = build_card_pages(title='战略新闻', items=items, banner='img_banner')
        text = json.dumps(card, ensure_ascii=False)
        self.assertEqual(items[0]['image_kind'], 'related')
        self.assertEqual(items[0]['image_source_url'], self.candidate['url'])
        self.assertEqual(items[0]['image_page_url'], self.candidate['page_url'])
        self.assertNotIn('相关资料图', text)
        self.assertEqual(text.count('80px 80px'), 1)
        def check_thumbnail_columns(value):
            if isinstance(value, dict):
                if value.get('tag') == 'column' and value.get('width') == '80px':
                    self.assertEqual([element['tag'] for element in value['elements']], ['img'])
                for child in value.values():
                    check_thumbnail_columns(child)
            elif isinstance(value, list):
                for child in value:
                    check_thumbnail_columns(child)
        check_thumbnail_columns(card)

    def test_rejected_original_uses_next_picture_before_keyword_search(self):
        service = SimpleNamespace(runtime_root=self.root, _lark=Mock())
        candidates = [self.candidate, {**self.candidate, 'url': 'https://publisher.example/real.png'}]
        with patch('cmhk.services.news_delivery_assets.source_metadata', return_value={
                'news_url': self.item['source_url'], 'image_candidates': candidates}), \
                patch('cmhk.services.news_delivery_assets.fetch', return_value=(self.data, '', 'image/png')), \
                patch('cmhk.services.news_image_quality._vision_call', side_effect=[
                    {**self.verdict, 'relation': 'reject'}, self.verdict]), \
                patch('cmhk.services.news_delivery_assets.search_image_candidates') as search, \
                patch('cmhk.services.news_delivery_assets.upload_image', return_value='img_verified') as upload:
            result = prepare_news_assets([self.item], service, profile='test', fallback_image_key='')[0]
        self.assertTrue(result['image_source_url'].endswith('real.png'))
        search.assert_not_called()
        upload.assert_called_once()

    def test_old_unreviewed_asset_cache_and_untrusted_input_image_are_not_reused(self):
        service = SimpleNamespace(runtime_root=self.root, _lark=Mock())
        cache = self.root / 'var/subscriptions/news-assets'
        old = fingerprint([self.item['source_url'], self.item['published_at'], 'test'])
        save(cache / (old + '.json'), {'news_url': self.item['source_url'], 'image_key': 'img_ad',
                                      'image_source_url': self.candidate['url']})
        with patch('cmhk.services.news_delivery_assets.source_metadata', return_value={
                'news_url': self.item['source_url'], 'image_candidates': []}), \
                patch('cmhk.services.news_delivery_assets.search_image_candidates', return_value=[]), \
                patch('cmhk.services.news_delivery_assets.upload_image') as upload:
            with self.assertRaises(NewsImageUnavailable):
                prepare_news_assets([{**self.item, 'image_url': self.candidate['url']}], service, profile='test', fallback_image_key='')
        upload.assert_not_called()

    def test_image_search_resolves_source_page_and_does_not_trust_search_thumbnail(self):
        with patch('cmhk.services.news_image_quality.search_queries', return_value=['HKBN Bocloud agreement photo']), \
                patch('ddgs.DDGS') as engine, \
                patch('cmhk.reporting.web_research.public_web_search', return_value={'results': []}), \
                patch('cmhk.services.news_delivery_assets.source_metadata', return_value={
                    'image_candidates': [self.candidate]}) as metadata:
            engine.return_value.__enter__.return_value.images.return_value = [{
                'url': self.item['source_url'], 'image': 'https://ad.example/untrusted.jpg'}]
            results = list(search_image_candidates(self.item, self.root))
        metadata.assert_called_once_with(self.item['source_url'])
        self.assertEqual(results[0]['url'], self.candidate['url'])
        self.assertEqual(results[0]['search_query'], 'HKBN Bocloud agreement photo')

    def test_bad_dimensions_and_banners_fail_before_visual_call(self):
        for size in ((1, 1), (1000, 120), (120, 1000)):
            output = io.BytesIO()
            Image.new('RGB', size).save(output, 'PNG')
            with self.assertRaises(ValueError):
                validate_image(output.getvalue())

    def test_visual_response_truncation_retries_once_without_approving_partial_output(self):
        first = {'choices': [{'finish_reason': 'length', 'message': {'content': '{"relation":"event"'}}]}
        second = {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(self.verdict)}}]}
        with patch('ai_config.load_ai_config', return_value={'base_url': 'https://model.example/v1'}), \
                patch('ai_key_rotation.open_llm_request', side_effect=[
                    io.BytesIO(json.dumps(first).encode()), io.BytesIO(json.dumps(second).encode())]) as call:
            result = _vision_call(self.item, self.candidate, self.data)
        self.assertEqual(result, self.verdict)
        payloads = [json.loads(c.args[0].data) for c in call.call_args_list]
        self.assertEqual([p['max_tokens'] for p in payloads], [8000, 16000])
        self.assertEqual(payloads[0]['messages'], payloads[1]['messages'])
        self.assertEqual(payloads[0]['response_format']['type'], 'json_schema')
        self.assertTrue(payloads[0]['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,'))

    def test_model_outage_does_not_become_rejection_or_trigger_more_image_requests(self):
        service = SimpleNamespace(runtime_root=self.root, _lark=Mock())
        with patch('cmhk.services.news_delivery_assets.source_metadata', return_value={
                'news_url': self.item['source_url'], 'image_candidates': [self.candidate]}), \
                patch('cmhk.services.news_delivery_assets.fetch', return_value=(self.data, '', 'image/png')), \
                patch('cmhk.services.news_image_quality._vision_call', side_effect=TimeoutError('model unavailable')) as model, \
                patch('cmhk.services.news_delivery_assets.search_image_candidates') as search:
            with self.assertRaises(TimeoutError):
                prepare_news_assets([self.item], service, profile='test', fallback_image_key='')
        model.assert_called_once()
        search.assert_not_called()
        service._lark.assert_not_called()

    def test_search_uses_publisher_english_slug_before_translated_keywords(self):
        item = {**self.item, 'source_url': 'https://news.example/news/pccw-global-and-harmony-tech-innovation-sign-mou/'}
        with patch('strategic_briefing._call_internal_ai', return_value={'queries': ['PCCW 上和科技', '上和科技 圖片']}) as model:
            queries = search_queries(item)
        self.assertEqual(queries[0], 'pccw global and harmony tech innovation sign mou')
        self.assertIn(item['source_url'], model.call_args.args[1])

    def test_interrupted_image_search_resumes_remaining_pages_without_searching_again(self):
        second = {**self.candidate, 'url': 'https://publisher.example/second.png',
                  'page_url': 'https://publisher.example/second'}
        with patch('cmhk.services.news_image_quality.search_queries', return_value=['specific entities']) as queries, \
                patch('ddgs.DDGS') as engine, \
                patch('cmhk.reporting.web_research.public_web_search', return_value={'results': [
                    {'url': self.candidate['page_url']}, {'url': second['page_url']}]}) as search, \
                patch('cmhk.services.news_delivery_assets.source_metadata', side_effect=[
                    {'image_candidates': [self.candidate]}, {'image_candidates': [second]}]) as metadata:
            engine.return_value.__enter__.return_value.images.return_value = []
            first = search_image_candidates(self.item, self.root)
            self.assertEqual(next(first)['url'], self.candidate['url'])
            first.close()  # Simulate a restart while visual review is in progress.
            resumed = list(search_image_candidates(self.item, self.root))
            self.assertEqual([row['url'] for row in resumed], [self.candidate['url'], second['url']])
            self.assertEqual(metadata.call_count, 2)
            search.assert_called_once()
            queries.assert_called_once()

    def test_search_deadline_retains_query_checkpoint_and_never_claims_an_image(self):
        with patch('cmhk.services.news_image_quality.search_queries', return_value=['specific entities']), \
                patch('ddgs.DDGS') as engine:
            with self.assertRaises(NewsImageUnavailable):
                list(search_image_candidates(self.item, self.root, deadline=0))
        engine.assert_not_called()
        checkpoint = json.loads(next((self.root / 'searches').glob('*.json')).read_text())
        self.assertEqual(checkpoint['queries'], ['specific entities'])
        self.assertFalse(checkpoint['complete'])

    def test_multi_page_cards_require_every_image_and_reject_one_missing_image(self):
        items = prepared_assets([{**self.item, 'news_id': str(i)} for i in range(20)])
        card = build_card_pages(title='战略新闻', items=items, banner='img_banner')
        self.assertEqual(len(card['cards']), 2)
        self.assertEqual(json.dumps(card).count('80px 80px'), 20)
        for field in ('image_key', 'image_sha256', 'image_page_url', 'image_review_status', 'image_policy_key'):
            with self.subTest(field=field), self.assertRaises(NewsImageUnavailable):
                build_card_pages(title='战略新闻', items=[*items[:19], {**items[19], field: ''}], banner='img_banner')

    def test_missing_image_never_marks_prepared_or_sends_a_message(self):
        service = SubscriptionService(runtime_root=self.root)
        service._send_interactive_card = Mock()
        with patch('cmhk.services.news_delivery_guard.select_recent_news', return_value=[self.item]), \
                patch('cmhk.services.news_delivery_guard.deduplicate_events', return_value=([self.item], [])), \
                patch('cmhk.services.news_delivery_guard.prepare_news_assets', return_value=[self.item]), \
                patch('cmhk.services.news_digest_editor.prepare_digest', return_value={'items': [self.item]}):
            with self.assertRaises(NewsImageUnavailable):
                deliver_news(service, open_id='ou_test', content_ref='test', title='战略新闻',
                             body=encode_strategic_news_digest([self.item]), batch_id='test-batch', profile='test')
        service._send_interactive_card.assert_not_called()
        with service._connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM news_delivery_receipts').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()

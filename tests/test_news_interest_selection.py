import json
import tempfile
import unittest
from pathlib import Path
from cmhk.services.subscriptions import (filter_news_by_categories, SubscriptionService,
    NEWS_CATEGORY_LABELS, strategic_news_card, NEWS_DIGEST_PREFIX)


def article(name, section, hour=10):
    return {'title': name, 'category': section, 'source_url': 'https://example.test/'+name,
            'published_at': f'2026-09-09T{hour:02d}:00:00+08:00'}


class InterestSelectionTests(unittest.TestCase):
    def test_competitor_first_and_all_selected_sections_covered(self):
        rows = [article('industry'+str(i), '行业动态', 20-i) for i in range(8)]
        rows += [article('competitor','竞对动态',8), article('policy','政策监管',9), article('product','市场/产品类',7)]
        got = filter_news_by_categories(rows, ['行业动态','竞对动态','政策监管','市场/产品类'], limit=5)
        self.assertEqual(got[0]['title'], 'competitor')
        self.assertEqual(len({i['category'] for i in got[:4]}),4)

    def test_no_outside_sections_when_preferred_pool_sufficient(self):
        rows = [article(str(i),'政策监管',i+1) for i in range(6)] + [article('outside','行业动态',22)]
        got = filter_news_by_categories(rows,['政策监管'],limit=5)
        self.assertEqual(len(got),5)
        self.assertEqual({i['category'] for i in got},{'政策监管'})

    def test_shortage_does_not_add_unselected_sections_or_repeat_sources(self):
        rows = [article('one','政策监管'),article('one','政策监管'),article('other','行业动态',20)]
        got = filter_news_by_categories(rows,['政策监管'],limit=5)
        self.assertEqual([i['title'] for i in got],['one'])
        self.assertEqual(filter_news_by_categories(rows,['政策监管'],limit=0),[])

    def test_unsubscribed_competitor_does_not_displace_preference(self):
        rows=[article('comp','竞对动态',20),article('chosen','行业动态',8)]
        self.assertEqual(filter_news_by_categories(rows,['行业动态'],limit=1)[0]['title'],'chosen')

    def test_all_categories_are_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            service=SubscriptionService(runtime_root=Path(directory))
            saved = service.save_subscriptions(open_id='ou_test123',display_name='测试',services=['news'],news_categories=list(NEWS_CATEGORY_LABELS)[:5])
            self.assertEqual(len(saved['news_categories']), 5)
            self.assertIn('竞对动态', saved['news_categories'])
            self.assertFalse(saved['adjustments'])
            self.assertEqual(service.list_summary()['subscribers'][0]['news_categories'], saved['news_categories'])

    def test_overview_only_lead_bold_and_competitor_shown_first(self):
        card=strategic_news_card(title='测试',body=NEWS_DIGEST_PREFIX+json.dumps({'overview':'1. 供给变化：正文保持普通字重。','items':[article('policy','政策监管'),article('comp','竞对动态')]}))
        elements=card['body']['elements']
        self.assertTrue(any(i.get('content')=='1. **供给变化**：正文保持普通字重。' for i in elements))
        first=next(i for i in elements if i['tag']=='column_set')
        self.assertIn('竞对动态',first['columns'][0]['elements'][0]['content'])

    def test_each_delivery_draws_four_and_retry_reuses_same_draw(self):
        categories = list(NEWS_CATEGORY_LABELS)
        rows = [article(str(index), category) for index, category in enumerate(categories)]
        seen = set()
        for day in range(20):
            seed = f'ou_test:2026-09-{day+1:02}:morning'
            result = filter_news_by_categories(rows, categories, limit=20, selection_seed=seed)
            chosen = tuple(sorted(r['category'] for r in result))
            self.assertEqual(len(chosen), 4)
            self.assertTrue(set(chosen).issubset(categories))
            self.assertEqual(result, filter_news_by_categories(rows, categories, limit=20, selection_seed=seed))
            seen.add(chosen)
        self.assertGreater(len(seen), 1)
        self.assertEqual(len(categories), 7)

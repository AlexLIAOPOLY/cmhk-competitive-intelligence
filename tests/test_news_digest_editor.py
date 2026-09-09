import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from cmhk.services.news_digest_editor import prepare_digest


class NewsDigestEditorTests(unittest.TestCase):
    def test_caches_complete_editorial_result_without_changing_news_identity(self):
        items = [{'title': '运营商发布新套餐', 'url': 'https://example.test/1', 'summary': '新套餐面向企业。'}]
        output = {'overview': '运营商推出面向企业的新套餐，产品竞争进一步聚焦企业服务。具体定价与客户采用情况仍需持续观察。',
                  'items': [{'id': '0', 'summary': '运营商公布面向企业客户的新套餐，现有资料尚未披露资费与生效日期。',
                             'analysis': '企业套餐可能带来差异化服务竞争，需跟踪价格、服务范围及客户采用情况，尚不能判断收入影响。'}]}
        model = Mock(return_value=output)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = prepare_digest(items, root, model_call=model)
            second = prepare_digest(items, root, model_call=model)
            self.assertEqual(first, second)
            self.assertEqual(first['items'][0]['url'], items[0]['url'])
            self.assertEqual(first['items'][0]['title'], items[0]['title'])
            self.assertEqual(model.call_count, 1)
            changed = [{**items[0], 'summary': '更正：该套餐仍在计划中。'}]
            prepare_digest(changed, root, model_call=model)
            self.assertEqual(model.call_count, 2)

    def test_incomplete_model_output_fails_before_cache_or_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                prepare_digest([{'title': '新闻'}], root, model_call=Mock(return_value={'overview': '太短', 'items': []}))
            self.assertFalse((root / 'var/subscriptions/news-editor').exists())

    def test_empty_digest_never_calls_model(self):
        model = Mock()
        self.assertEqual(prepare_digest([], Path('/unused'), model_call=model)['items'], [])
        model.assert_not_called()

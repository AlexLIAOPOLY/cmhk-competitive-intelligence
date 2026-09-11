import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import executive_intelligence_pipeline as pipeline
from tests.ai_stream_fixture import sse_response
from tests.test_executive_ai_recovery import DiscoveryIncrementalEvidenceTests


class DiscoveryRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.evidence, self.items = DiscoveryIncrementalEvidenceTests().fixture()
        self.enterContext(patch('ai_config.load_ai_config', return_value={'api_key': 'test-secret'}))
        self.enterContext(patch('ai_rate_limit.wait_for_internal_ai_slot'))
        self.enterContext(patch.object(pipeline, '_executive_model_route', return_value=['primary', 'backup']))

    def stretch(self, count=140):
        items = copy.deepcopy(self.items)
        base = items[0]['detail'][:-1]
        items[0]['detail'] = base + '原' * (count - len(base) - 1) + '。'
        return items

    def test_raw_saved_before_gate_and_revalidated_without_more_http(self):
        items = self.stretch()
        with tempfile.TemporaryDirectory() as td:
            trace = Path(td) / 'attempts.jsonl'
            with patch.object(pipeline, 'MAX_DISCOVERY_DETAIL_PUBLISH_CHARS', 110), \
                 patch.object(pipeline, 'open_llm_request', side_effect=lambda *_a, **_k: sse_response({'items': items}, model='actual')) as request:
                with self.assertRaises(ValueError):
                    pipeline.generate_model_discoveries(self.evidence, attempt_trace_path=trace)
            self.assertEqual(request.call_count, 2)
            saved_path = trace.with_suffix('.discoveries.json')
            saved = json.loads(saved_path.read_text())
            entry = next(iter(saved.values()))
            self.assertEqual(entry['model_route_counts'], {'primary': 1, 'backup': 1})
            self.assertEqual(entry['attempts'][0]['candidate'], items)
            self.assertEqual(entry['attempts'][0]['reported_model'], 'actual')
            self.assertTrue(entry['attempts'][0]['response_id'])
            self.assertTrue(entry['attempts'][0]['response_hash'])
            with patch.object(pipeline, 'open_llm_request') as no_http:
                result = pipeline.generate_model_discoveries(self.evidence, attempt_trace_path=trace)
            no_http.assert_not_called()
            self.assertTrue(result['reused'])
            self.assertEqual(result['presentation_warnings'][0]['characters'], 140)
            after = next(iter(json.loads(saved_path.read_text()).values()))
            self.assertEqual(after['attempts'], entry['attempts'])
            self.assertEqual(after['model_route_counts'], entry['model_route_counts'])
            self.assertEqual(pipeline._validate_model_discoveries(result['discoveries'], self.evidence), result['discoveries'])

    def test_received_response_survives_crash_before_candidate_parse(self):
        with tempfile.TemporaryDirectory() as td:
            trace = Path(td) / 'attempts.jsonl'
            with patch.object(pipeline, 'open_llm_request', return_value=sse_response({'items': self.items})):
                pipeline.generate_model_discoveries(self.evidence, attempt_trace_path=trace)
            saved_path = trace.with_suffix('.discoveries.json')
            saved = json.loads(saved_path.read_text())
            entry = next(iter(saved.values()))
            del entry['selected']
            del entry['attempts'][0]['candidate']
            entry['attempts'][0]['status'] = 'received'
            saved_path.write_text(json.dumps(saved))
            with patch.object(pipeline, 'open_llm_request') as no_http:
                result = pipeline.generate_model_discoveries(self.evidence, attempt_trace_path=trace)
            no_http.assert_not_called()
            self.assertEqual(result['discoveries'], self.items)
            self.assertEqual(next(iter(json.loads(saved_path.read_text()).values()))['model_route_counts'], {'primary': 1})

    def test_invalid_same_evidence_exhausts_routes_and_new_evidence_has_own_budget(self):
        invalid = copy.deepcopy(self.items)
        invalid[0]['detail'] = invalid[0]['detail'].replace('11', '999')
        invalid[0]['source_urls'].append('https://unknown.test/test-secret')
        with tempfile.TemporaryDirectory() as td, patch.object(pipeline, 'open_llm_request', side_effect=lambda *_a, **_k: sse_response({'items': invalid})) as request:
            trace = Path(td) / 'attempts.jsonl'
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, '路由已用完'):
                    pipeline.generate_model_discoveries(self.evidence, attempt_trace_path=trace)
            self.assertEqual(request.call_count, 2)
            self.assertNotIn('test-secret', trace.with_suffix('.discoveries.json').read_text())
            changed = copy.deepcopy(self.evidence)
            changed['domains'][0]['agent_verified_facts'][0]['period'] = 'H1 2027'
            with self.assertRaises(ValueError):
                pipeline.generate_model_discoveries(changed, attempt_trace_path=trace)
            self.assertEqual(request.call_count, 4)

    def test_style_never_bypasses_cause_sources_numbers_or_complete_sentences(self):
        for detail, accepted in [
            ('两域半年利润为11亿元与22亿元，差距表明利润结构不同，均由客户需求驱动。', False),
            ('两域半年利润为11亿元与22亿元，差距表明利润结构不同，无法据此判断差距由客户需求驱动。', True),
            ('两域半年利润为11亿元与22亿元，差距表明利润结构不同，无法判断成本，但差距由客户需求驱动。', False),
        ]:
            items = copy.deepcopy(self.items); items[0]['detail'] = detail
            with self.subTest(detail=detail):
                if accepted:
                    pipeline._validate_model_discoveries(items, self.evidence)
                else:
                    with self.assertRaisesRegex(ValueError, '因果'):
                        pipeline._validate_model_discoveries(items, self.evidence)
        for mode in ('length', 'title', 'number', 'source', 'sentence', 'unfinished'):
            items = self.stretch()
            if mode == 'length': items = self.stretch(161)
            if mode == 'title': items[0]['title'] = '原' * 37
            if mode == 'number': items[0]['detail'] = items[0]['detail'].replace('11', '999')
            if mode == 'source': items[0]['source_urls'] = items[0]['source_urls'][:1]
            if mode == 'sentence': items[0]['detail'] = self.items[0]['detail'] + '保留原值。保留口径。'
            if mode == 'unfinished': items[0]['detail'] = self.items[0]['detail'][:-1]
            items[0]['presentation_warnings'] = [{'allow_all': True}]
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                pipeline._validate_model_discoveries(items, self.evidence)

    def test_reserved_route_survives_crash_without_http_or_refund(self):
        with tempfile.TemporaryDirectory() as td:
            trace = Path(td) / 'attempts.jsonl'
            compact = pipeline._compact_discovery_evidence(self.evidence)
            key = pipeline._content_hash({'schema': 'four_discoveries_v1', 'evidence': compact})
            trace.with_suffix('.discoveries.json').write_text(json.dumps({key: {
                'protocol': 1, 'evidence_hash': key, 'model_route_counts': {'primary': 1},
                'attempts': [{'requested_model': 'primary', 'status': 'running', 'http_calls': 0}]}}))
            with patch.object(pipeline, 'open_llm_request', return_value=sse_response({'items': self.items})) as request:
                pipeline.generate_model_discoveries(self.evidence, attempt_trace_path=trace)
            self.assertEqual(request.call_count, 1)
            self.assertEqual(json.loads(request.call_args.args[0].data)['model'], 'backup')
            after = json.loads(trace.with_suffix('.discoveries.json').read_text())[key]
            self.assertEqual(after['model_route_counts'], {'primary': 1, 'backup': 1})
            self.assertEqual(after['attempts'][0], {'requested_model': 'primary', 'status': 'running', 'http_calls': 0})

    def test_each_route_cannot_hide_extra_transports(self):
        def double_open(request, **kwargs):
            self.assertEqual(kwargs['max_transport_retries'], 0)
            kwargs['open_func'](request, timeout=1)
            return kwargs['open_func'](request, timeout=1)
        with tempfile.TemporaryDirectory() as td, patch.object(pipeline, 'open_llm_request', side_effect=double_open), \
             patch('urllib.request.urlopen', side_effect=lambda *_a, **_k: sse_response({'items': self.items})) as http:
            trace = Path(td) / 'attempts.jsonl'
            with self.assertRaisesRegex(ValueError, '一个HTTP'):
                pipeline.generate_model_discoveries(self.evidence, attempt_trace_path=trace)
            self.assertEqual(http.call_count, 2)  # One per distinct configured model, never two per route.
            entry = next(iter(json.loads(trace.with_suffix('.discoveries.json').read_text()).values()))
            self.assertEqual([a['http_calls'] for a in entry['attempts']], [1, 1])

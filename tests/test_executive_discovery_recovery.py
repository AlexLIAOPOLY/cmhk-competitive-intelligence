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
    def test_initial_route_failures_enter_bounded_patch_without_manual_retry(self):
        invalid = copy.deepcopy(self.items)
        invalid[0]['source_urls'] = []
        packet = {'patches': [{'index': 0, **{k: self.items[0][k] for k in ('title', 'detail', 'source_urls')}}]}
        with tempfile.TemporaryDirectory() as td:
            trace = Path(td) / 'attempts.jsonl'
            with patch.object(pipeline, 'open_llm_request', side_effect=[
                sse_response({'items': invalid}), sse_response({'items': invalid}), sse_response(packet)]) as http:
                result = pipeline.generate_model_discoveries(self.evidence, attempt_trace_path=trace)
            self.assertEqual(http.call_count, 3)
            self.assertEqual(result['discoveries'], self.items)
            state = next(iter(json.loads(trace.with_suffix('.discoveries.json').read_text()).values()))
            self.assertEqual(len(state['repair_history']), 1)
            with patch.object(pipeline, 'open_llm_request') as no_http:
                pipeline.generate_model_discoveries(self.evidence, attempt_trace_path=trace)
            no_http.assert_not_called()

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
            self.assertEqual(request.call_count, 4)  # Two initial routes and at most two local repairs.
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
            for _ in range(3):
                with self.assertRaises(ValueError):
                    pipeline.generate_model_discoveries(self.evidence, attempt_trace_path=trace)
            self.assertEqual(request.call_count, 4)
            self.assertNotIn('test-secret', trace.with_suffix('.discoveries.json').read_text())
            changed = copy.deepcopy(self.evidence)
            changed['domains'][0]['agent_verified_facts'][0]['period'] = 'H1 2027'
            with self.assertRaises(ValueError):
                pipeline.generate_model_discoveries(changed, attempt_trace_path=trace)
            self.assertEqual(request.call_count, 8)

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
            key = pipeline._content_hash({'schema': 'four_discoveries_v1', 'prompt_version': pipeline.STRATEGIC_PROMPT_VERSION, 'evidence': compact})
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

    def seed_bad_packet(self, trace):
        items = copy.deepcopy(self.items)
        items[0]['detail'] = items[0]['detail'][:-1] + '，主要来自市场需求。'
        compact = pipeline._compact_discovery_evidence(self.evidence)
        key = pipeline._content_hash({'schema': 'four_discoveries_v1', 'prompt_version': pipeline.STRATEGIC_PROMPT_VERSION, 'evidence': compact})
        entry = {'protocol': 1, 'evidence_hash': key, 'model_route_counts': {'primary': 1},
                 'selected': {'attempt_index': 0},
                 'attempts': [{'requested_model': 'primary', 'reported_model': 'actual-source',
                               'status': 'passed', 'candidate': items, 'http_calls': 1}]}
        trace.with_suffix('.discoveries.json').write_text(json.dumps({key: entry}))
        return key, items

    def test_bad_items_only_receive_real_patch_and_others_remain_identical(self):
        with tempfile.TemporaryDirectory() as td:
            trace = Path(td) / 'attempts.jsonl'; key, original = self.seed_bad_packet(trace)
            def request(req, **kwargs):
                content = json.loads(req.data)['messages'][1]['content']
                body = json.loads(content[content.index('{'):])
                self.assertEqual(body['task'], 'repair_failed_discoveries_v1')
                self.assertEqual(set(body['allowed_items']), {'0'})
                return sse_response({'patches': [{'index': 0, **{k:self.items[0][k] for k in ('title','detail','source_urls')}}]}, model='actual-patch')
            with patch.object(pipeline, 'open_llm_request', side_effect=request) as http:
                result = pipeline.generate_model_discoveries(self.evidence, attempt_trace_path=trace)
            self.assertEqual(http.call_count, 1)
            self.assertEqual(result['discoveries'][1:], original[1:])
            self.assertEqual(result['model'], 'actual-patch+actual-source')
            state = json.loads(trace.with_suffix('.discoveries.json').read_text())[key]
            self.assertEqual(state['model_route_counts'], {'primary': 1})
            self.assertEqual(len(state['repair_history']), 1)
            with patch.object(pipeline, 'open_llm_request') as no_http:
                pipeline.generate_model_discoveries(self.evidence, attempt_trace_path=trace)
            no_http.assert_not_called()
            # A received SSE packet remains usable even if parsing was interrupted.
            record = state['repair_history'][0]
            for field in ('candidate', 'submitted_patch'): record.pop(field)
            record['status'] = 'running'
            trace.with_suffix('.discoveries.json').write_text(json.dumps({key: state}))
            with patch.object(pipeline, 'open_llm_request') as no_http:
                pipeline.generate_model_discoveries(self.evidence, attempt_trace_path=trace)
            no_http.assert_not_called()

    def test_two_patch_limit_preserves_failures_without_full_route_regeneration(self):
        with tempfile.TemporaryDirectory() as td:
            trace = Path(td) / 'attempts.jsonl'; key, original = self.seed_bad_packet(trace)
            calls = []
            def request(req, **kwargs):
                calls.append(req)
                wrong = copy.deepcopy(self.items[0])
                wrong['detail'] = wrong['detail'][:-1] + ('，均由客户需求驱动。' if len(calls)==1 else '，主要来自市场需求。')
                return sse_response({'patches': [{'index':0, **{k:wrong[k] for k in ('title','detail','source_urls')}}]})
            with patch.object(pipeline, 'open_llm_request', side_effect=request):
                for _ in range(2):
                    with self.assertRaisesRegex(ValueError, '最多2次'):
                        pipeline.generate_model_discoveries(self.evidence, attempt_trace_path=trace)
            self.assertEqual(len(calls), 2)
            state = json.loads(trace.with_suffix('.discoveries.json').read_text())[key]
            self.assertEqual(state['model_route_counts'], {'primary': 1})
            self.assertEqual(len(state['repair_history']), 2)
            self.assertTrue(all(r['candidate'][1:] == original[1:] for r in state['repair_history']))

    def test_saved_canonical_string_index_recovers_at_spent_budget_without_http(self):
        with tempfile.TemporaryDirectory() as td:
            trace = Path(td) / 'attempts.jsonl'; key, original = self.seed_bad_packet(trace)
            saved = json.loads(trace.with_suffix('.discoveries.json').read_text())
            packet = {'patches': [{'index': '0', **{k:self.items[0][k] for k in ('title','detail','source_urls')}}]}
            history = [
                {'status': 'failed', 'http_calls': 1},
                {'status': 'failed', 'http_calls': 1, 'reported_model': 'actual-patch',
                 'before_candidate': original, 'allowed_items': {'0': {}},
                 'submitted_patch': packet,
                 'response': {'choices': [{'message': {'content': json.dumps(packet)}, 'finish_reason': 'stop'}]}}
            ]
            saved[key]['repair_history'] = copy.deepcopy(history)
            trace.with_suffix('.discoveries.json').write_text(json.dumps(saved))
            with patch.object(pipeline, 'open_llm_request') as no_http:
                result = pipeline.generate_model_discoveries(self.evidence, attempt_trace_path=trace)
            no_http.assert_not_called()
            self.assertEqual(result['discoveries'], self.items)
            after = json.loads(trace.with_suffix('.discoveries.json').read_text())[key]
            self.assertEqual(after['repair_history'], history)
            self.assertEqual(after['model_route_counts'], {'primary': 1})
            for invalid in ('00', '0.0', ' 0', '+0', '-0', '4', True, 0.0):
                malformed = copy.deepcopy(packet)
                malformed['patches'][0]['index'] = invalid
                with self.subTest(index=invalid), self.assertRaises(ValueError):
                    pipeline._apply_discovery_model_patch(original, malformed, {'0': {}})

    def test_received_only_bad_packet_is_repaired_without_another_full_route(self):
        with tempfile.TemporaryDirectory() as td:
            trace = Path(td) / 'attempts.jsonl'; key, original = self.seed_bad_packet(trace)
            saved = json.loads(trace.with_suffix('.discoveries.json').read_text())
            old = saved[key]['attempts'][0]
            old.pop('candidate')
            old['status'] = 'received'
            old['response'] = {'choices': [{'message': {'content': json.dumps({'items': original})}, 'finish_reason': 'stop'}]}
            trace.with_suffix('.discoveries.json').write_text(json.dumps(saved))
            packet = {'patches': [{'index': 0, **{k:self.items[0][k] for k in ('title','detail','source_urls')}}]}
            with patch.object(pipeline, 'open_llm_request', return_value=sse_response(packet)) as http:
                result = pipeline.generate_model_discoveries(self.evidence, attempt_trace_path=trace)
            self.assertEqual(http.call_count, 1)
            self.assertEqual(result['discoveries'], self.items)
            after = json.loads(trace.with_suffix('.discoveries.json').read_text())[key]
            self.assertEqual(after['model_route_counts'], {'primary': 1})
            self.assertEqual(after['attempts'][0]['candidate'], original)
            self.assertEqual(len(after['repair_history']), 1)

    def test_typed_facts_bind_company_metric_period_currency_and_exact_source(self):
        evidence = {'domains': [
            {'id': 'local', 'focuses': [{'id': 'net_profit', 'items': [
                {'name':'HKT','value':5286.0,'unit':'百万港元','period':'FY2025','source_url':'https://hkt.test/annual'},
                {'name':'SmarTone','value':4,'unit':'百万港元','period':'FY2024','source_url':'https://smartone.test/annual'}]}]},
            {'id': 'mainland', 'focuses': [{'id': 'net_profit', 'items': [
                {'name':'中国移动','value':1370.95,'unit':'亿元','period':'FY2025','source_url':'https://mobile.test/annual'}]}]}]}
        base = {'from':'local','to':'mainland','title':'利润披露币种不同限制比较',
                'detail':'HKT FY2025净利润为5286.0百万港元，中国移动FY2025净利润为1370.95亿元；币种与口径不同表明不能直接比较。',
                'kind':'AI综合研判','source_urls':['https://hkt.test/annual','https://mobile.test/annual']}
        for mode in ('positive','spaced_thousands','wrong_entity','wrong_metric','wrong_period','ranking','wrong_source'):
            item = copy.deepcopy(base)
            if mode == 'spaced_thousands': item['detail'] = item['detail'].replace('5286.0百万','5,286.0 百万').replace('1370.95亿元','1,370.95 亿元')
            if mode == 'wrong_entity': item['detail'] = item['detail'].replace('HKT','SmarTone')
            if mode == 'wrong_metric': item['detail'] = item['detail'].replace('净利润','营收')
            if mode == 'wrong_period': item['detail'] = item['detail'].replace('FY2025','FY2024')
            if mode == 'ranking': item['title'] = '本地利润领先内地'
            if mode == 'wrong_source': item['source_urls'][0] = 'https://smartone.test/annual'
            with self.subTest(mode=mode):
                if mode in ('positive','spaced_thousands'):
                    pipeline._validate_model_discoveries([item], evidence, require_complete=False)
                else:
                    with self.assertRaises(ValueError):
                        pipeline._validate_model_discoveries([item], evidence, require_complete=False)

    def test_explicit_quarter_half_year_cannot_become_annual_and_subscriber_alias_is_valid(self):
        evidence = {'domains': [
            {'id':'international','agent_verified_facts':[{'company':'NTT DOCOMO','metric_key':'net_income',
                'value':176300,'unit':'millions JPY','period':'Q1 FY2026','grain':'quarter','source_url':'https://docomo.test/q1'}]},
            {'id':'mainland','agent_verified_facts':[{'company':'中国铁塔','metric_key':'net_income',
                'value':7489,'unit':'millions CNY','period':'H1 2026','grain':'half_year','source_url':'https://tower.test/h1'},
                {'company':'中国移动','metric_key':'subscribers','value':100,'unit':'subscribers',
                 'period':'H1 2026','grain':'half_year','source_url':'https://mobile.test/h1'}]}]}
        base = {'from':'international','to':'mainland','title':'不同期间利润披露限制比较',
                'detail':'NTT DOCOMO Q1 FY2026净利润为176300millions JPY，中国铁塔H1 2026净利润为7489millions CNY；期间与币种口径不同表明不能直接比较。',
                'kind':'AI综合研判','source_urls':['https://docomo.test/q1','https://tower.test/h1']}
        pipeline._validate_model_discoveries([base], evidence, require_complete=False)
        for old in ('Q1 FY2026','H1 2026'):
            item = copy.deepcopy(base); item['detail'] = item['detail'].replace(old, 'FY2026全年')
            with self.subTest(old=old), self.assertRaisesRegex(ValueError, '粒度'):
                pipeline._validate_model_discoveries([item], evidence, require_complete=False)
        item = copy.deepcopy(base)
        item['detail'] = item['detail'].replace('中国铁塔H1 2026净利润为7489millions CNY', '中国移动H1 2026客户数为100 subscribers')
        item['source_urls'][1] = 'https://mobile.test/h1'
        pipeline._validate_model_discoveries([item], evidence, require_complete=False)

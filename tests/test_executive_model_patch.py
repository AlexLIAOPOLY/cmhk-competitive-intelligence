from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import executive_intelligence_pipeline as pipeline
from tests.test_executive_ai_recovery import evidence_fixture, summary_fixture
from tests.ai_stream_fixture import sse_response


def one_scope():
    scope = evidence_fixture()
    scope['domains'][0]['focuses'] = scope['domains'][0]['focuses'][:1]
    return scope


def model_response(content, model='actual-source'):
    return sse_response(content, model=model)


class ExecutiveModelPatchTests(unittest.TestCase):
    def setUp(self):
        self.scope = one_scope()
        self.valid = summary_fixture(self.scope)
        self.draft = copy.deepcopy(self.valid)
        self.draft['focuses'][0]['analysis'] *= 5
        self.config = {'api_key': 'test-secret-never-save'}
        self.enterContext(patch('ai_config.load_ai_config', return_value=self.config))
        self.enterContext(patch('ai_rate_limit.wait_for_internal_ai_slot'))
        self.enterContext(patch.object(pipeline, '_executive_model_route', return_value=['requested-primary', 'requested-patch']))

    def test_only_invalid_existing_fields_are_exposed(self):
        options = pipeline._scope_patch_options(self.draft, self.scope)
        self.assertEqual(set(options), {'/focuses/0/analysis'})
        constraints = options['/focuses/0/analysis']
        self.assertEqual(constraints['current_characters'], len(self.draft['focuses'][0]['analysis']))
        self.assertEqual(constraints['target_characters'], [60, 85])
        self.assertEqual(constraints['max_characters'], 120)
        self.assertEqual(constraints['max_sentences'], 2)
        self.assertTrue(constraints['must_change'])
        self.assertEqual(pipeline._scope_patch_options(self.valid, self.scope), {})
        incomplete = copy.deepcopy(self.draft)
        incomplete['focuses'][0]['entities'].pop()
        self.assertEqual(pipeline._scope_patch_options(incomplete, self.scope), {})
        renamed = copy.deepcopy(self.draft)
        renamed['focuses'][0]['entities'][0]['name'] = '另一家公司'
        self.assertEqual(pipeline._scope_patch_options(renamed, self.scope), {})
        absent = copy.deepcopy(self.draft)
        del absent['focuses'][0]['risk']
        self.assertEqual(pipeline._scope_patch_options(absent, self.scope), {})

    def test_explicit_patch_preserves_original_and_every_other_field(self):
        before = copy.deepcopy(self.draft)
        options = pipeline._scope_patch_options(self.draft, self.scope)
        result = pipeline._apply_scope_model_patch(self.draft, {'patches': [
            {'path': '/focuses/0/analysis', 'value': self.valid['focuses'][0]['analysis']}]}, options)
        self.assertEqual(self.draft, before)
        self.assertEqual(result, self.valid)
        pipeline._validate_model_summaries([result], self.scope)

    def test_unknown_cross_entity_identity_duplicate_missing_and_type_paths_rejected(self):
        options = pipeline._scope_patch_options(self.draft, self.scope)
        for path in ('/domain', '/focuses/0/id', '/focuses/0/entities/1/analysis',
                     '/focuses/1/analysis', '/focuses/0/new', '/headline'):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, '路径'):
                pipeline._apply_scope_model_patch(self.draft, {'patches': [{'path': path, 'value': '值'}]}, options)
        for patches in ([{'path': '/focuses/0/analysis', 'value': 12}],
                        [{'path': '/focuses/0/analysis', 'value': '值'}] * 2):
            with self.subTest(patches=patches), self.assertRaises(ValueError):
                pipeline._apply_scope_model_patch(self.draft, {'patches': patches}, options)

    def test_sources_and_labels_options_match_full_gate(self):
        scope = copy.deepcopy(self.scope)
        source = scope['domains'][0]['focuses'][0]['items'][0]
        source['components'] = [{'label': '甲原值', 'value': 10, 'unit': '项',
                                 'source_url': 'https://example.test/component'}]
        candidate = copy.deepcopy(self.valid)
        entity = candidate['focuses'][0]['entities'][0]
        entity['source_urls'] = ['https://example.test/component']
        entity['evidence_labels'] = ['乙原值']
        options = pipeline._scope_patch_options(candidate, scope)
        self.assertEqual(set(options), {'/focuses/0/entities/0/source_urls', '/focuses/0/entities/0/evidence_labels'})
        self.assertEqual(options['/focuses/0/entities/0/source_urls']['allowed_values'], [source['source_url']])
        self.assertEqual(options['/focuses/0/entities/0/evidence_labels']['allowed_values'], ['甲原值'])
        with self.assertRaises(ValueError):
            pipeline._validate_model_summaries([candidate], scope)

    def test_copied_invalid_field_and_omitted_errors_are_rejected(self):
        options = pipeline._scope_patch_options(self.draft, self.scope)
        with self.assertRaisesRegex(ValueError, '照抄'):
            pipeline._apply_scope_model_patch(self.draft, {'patches': [
                {'path': '/focuses/0/analysis', 'value': self.draft['focuses'][0]['analysis']}]}, options)
        draft = copy.deepcopy(self.draft)
        draft['focuses'][0]['entities'][0]['source_urls'] = ['https://unknown.test']
        options = pipeline._scope_patch_options(draft, self.scope)
        with self.assertRaisesRegex(ValueError, '遗漏'):
            pipeline._apply_scope_model_patch(draft, {'patches': [
                {'path': '/focuses/0/analysis', 'value': self.valid['focuses'][0]['analysis']}]}, options)

    def request_factory(self, calls, *, bad_patch=False, final_incomplete=False):
        def request(req, **kwargs):
            body = json.loads(req.data)
            user = body['messages'][1]['content']
            is_patch = '"task": "repair_only_invalid_fields_v1"' in user
            calls.append({'patch': is_patch, 'model': body['model'], 'user': user})
            if is_patch:
                return model_response({'patches': [{'path': '/focuses/0/name' if bad_patch else '/focuses/0/analysis',
                    'value': 'test-secret-never-save Bearer another-secret' if bad_patch else self.valid['focuses'][0]['analysis']}]},
                    model='actual-patch')
            draft = copy.deepcopy(self.draft)
            if final_incomplete and len(calls) == 5:
                draft['focuses'][0]['entities'] = []
            return model_response({'items': [draft]})
        return request

    def test_real_request_schema_full_gate_actual_models_and_durable_checkpoint(self):
        calls = []
        with tempfile.TemporaryDirectory() as td, patch.object(pipeline, 'open_llm_request', side_effect=self.request_factory(calls)):
            checkpoint = Path(td) / 'ai.json'
            result = pipeline.generate_model_domain_summaries(self.scope, checkpoint_path=checkpoint)
            self.assertEqual(len(calls), 6)
            self.assertEqual(sum(c['patch'] for c in calls), 1)
            self.assertEqual(result['model'], 'actual-patch+actual-source')
            self.assertEqual(result['summaries'][0]['focuses'], self.valid['focuses'])
            self.assertEqual(result['summaries'][0]['focuses'][0]['entities'], self.draft['focuses'][0]['entities'])
            cache = json.loads(checkpoint.read_text())
            audit = next(v['patch_audit'] for v in cache.values() if 'patch_audit' in v)
            self.assertEqual(audit['source_reported_model'], 'actual-source')
            self.assertEqual(audit['requested_model'], 'requested-primary')
            self.assertEqual(audit['reported_model'], 'actual-patch')
            self.assertNotEqual(audit['before_hash'], audit['after_hash'])
            saved = json.loads(checkpoint.with_suffix('.drafts.json').read_text())
            entry = next(iter(saved.values()))
            self.assertEqual(len(entry['candidates']), 5)
            self.assertEqual(entry['repair']['status'], 'passed')
            before = len(calls)
            pipeline.generate_model_domain_summaries(self.scope, checkpoint_path=checkpoint)
            self.assertEqual(len(calls), before)

    def test_final_incomplete_model_does_not_replace_complete_earlier_draft(self):
        calls = []
        with tempfile.TemporaryDirectory() as td, patch.object(pipeline, 'open_llm_request', side_effect=self.request_factory(calls, final_incomplete=True)):
            checkpoint = Path(td) / 'ai.json'
            result = pipeline.generate_model_domain_summaries(self.scope, checkpoint_path=checkpoint)
            self.assertEqual(result['summaries'][0]['focuses'], self.valid['focuses'])
            drafts = json.loads(checkpoint.with_suffix('.drafts.json').read_text())
            entry = next(iter(drafts.values()))
            self.assertEqual(entry['candidates'][-1]['eligible_fields'], {})
            self.assertEqual(entry['repair']['status'], 'passed')

    def test_failed_patch_retains_raw_model_and_budget_without_any_repeat_calls(self):
        calls = []
        with tempfile.TemporaryDirectory() as td, patch.object(pipeline, 'open_llm_request', side_effect=self.request_factory(calls, bad_patch=True)):
            checkpoint = Path(td) / 'ai.json'
            with self.assertRaisesRegex(ValueError, '未知、跨实体'):
                pipeline.generate_model_domain_summaries(self.scope, checkpoint_path=checkpoint)
            draft_text = checkpoint.with_suffix('.drafts.json').read_text()
            self.assertNotIn('test-secret-never-save', draft_text)
            self.assertNotIn('another-secret', draft_text)
            repair = next(iter(json.loads(draft_text).values()))['repair']
            self.assertEqual(repair['reported_model'], 'actual-patch')
            self.assertEqual(repair['response']['model'], 'actual-patch')
            self.assertEqual(repair['status'], 'failed')
            self.assertFalse(checkpoint.exists())
            before = len(calls)
            with self.assertRaisesRegex(ValueError, '修订额度已使用'):
                pipeline.generate_model_domain_summaries(self.scope, checkpoint_path=checkpoint)
            self.assertEqual(len(calls), before)
            changed = copy.deepcopy(self.scope)
            changed['domains'][0]['focuses'][0]['items'][0]['value'] = 11
            with self.assertRaises(ValueError):
                pipeline.generate_model_domain_summaries(changed, checkpoint_path=checkpoint)
            self.assertGreater(len(calls), before)

    def test_patch_with_unknown_number_still_fails_full_scope_gate(self):
        with patch.object(pipeline, 'open_llm_request', return_value=model_response({'patches': [
            {'path': '/focuses/0/analysis', 'value': self.valid['focuses'][0]['analysis'].replace('10', '999')}]}, model='actual-patch')):
            with self.assertRaisesRegex(ValueError, '数字') as error:
                pipeline._request_scope_model_patch(self.scope, self.draft, pipeline._scope_patch_options(self.draft, self.scope), self.config)
            self.assertEqual(error.exception.model_patch_attempt['reported_model'], 'actual-patch')

    def test_no_programmatic_deletion_of_numeric_prose_or_unknown_sources(self):
        draft = copy.deepcopy(self.valid)
        draft['focuses'][0]['analysis'] += '其他999项。'
        draft['focuses'][0]['source_urls'].append('https://unknown.test/source')
        with tempfile.TemporaryDirectory() as td, patch.object(pipeline, 'open_llm_request', return_value=model_response({'items': [draft]})):
            with self.assertRaises(ValueError):
                pipeline.generate_model_domain_summaries(self.scope, checkpoint_path=Path(td) / 'ai.json')
            raw = (Path(td) / 'ai.drafts.json').read_text()
            self.assertIn('其他999项', raw)
            self.assertIn('https://unknown.test/source', raw)
            self.assertFalse((Path(td) / 'ai.json').exists())


class ExactNumericAndCausalGateTests(unittest.TestCase):
    def test_legal_grouping_and_decimal_precision(self):
        self.assertEqual(pipeline._numeric_tokens('36,553.0'), {'36553'})
        self.assertEqual(pipeline._numeric_tokens('36553.000'), {'36553'})
        self.assertEqual(pipeline._numeric_tokens('43152.41'), {'43152.41'})
        self.assertNotEqual(pipeline._numeric_tokens('43152.41'), pipeline._numeric_tokens('43152.42'))
        self.assertEqual(pipeline._numeric_tokens([0, -0.0, 10, 20, 1e-7]), {'0', '10', '20', '0.0000001'})
        self.assertNotEqual(pipeline._numeric_tokens('36,55.0'), pipeline._numeric_tokens('3655.0'))
        self.assertIn('invalid-number:36,55.0', pipeline._numeric_tokens('36,55.0'))
        self.assertEqual(pipeline._numeric_tokens('12345678901234567890.123456789'), {'12345678901234567890.123456789'})

    def test_full_scope_preserves_equivalent_thousands_and_rejects_changed_digit(self):
        scope = one_scope()
        scope['domains'][0]['focuses'][0]['items'][0]['value'] = 43152.41
        candidate = summary_fixture(scope)
        candidate['focuses'][0]['analysis'] = candidate['focuses'][0]['analysis'].replace('43152.41', '43,152.410')
        pipeline._validate_model_summaries([candidate], scope)
        candidate['focuses'][0]['entities'][0]['analysis'] = '甲公司43152.42项。'
        with self.assertRaisesRegex(ValueError, '数字'):
            pipeline._validate_model_summaries([candidate], scope)

    def test_each_causal_claim_has_its_own_negation_scope(self):
        cases = [
            ('无法判断差距源于经营效率。', ()), ('无法据此判断差距源于经营效率。', ()),
            ('不能由此推断差距由经营效率驱动。', ()), ('现有事实不能直接证明投入推动增长。', ()),
            ('无法判断36,553.0百万港元的差距源于效率。', ()), ('收入差距不代表效率推动增长。', ()),
            ('差距源于经营效率。', ('源于',)), ('无法判断获客成本，但差距源于经营效率。', ('源于',)),
            ('无法据此判断获客成本，但差距源于经营效率。', ('源于',)),
            ('无法判断获客成本但是差距源于经营效率。', ('源于',)),
            ('无法判断获客成本。差距源于经营效率。', ('源于',)),
            ('无法判断获客成本；差距源于经营效率。', ('源于',)),
            ('无法判断获客成本,差距源于经营效率。', ('源于',)),
            ('差距源于经营效率；无法判断获客成本。', ('源于',)),
            ('无法判断效率推动增长，但资本投入带来规模优势。', ('带来',)),
            ('差距并非由经营效率驱动。', ('驱动',)), ('数据无法披露，差距源于经营效率。', ('源于',)),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(pipeline._unsupported_causal_terms(text), expected)

    def test_full_gate_accepts_inability_to_infer_and_rejects_positive_followup(self):
        scope = one_scope()
        prefix = '甲公司10项与乙公司20项的差距表明客户结构分化，并非同一口径；'
        for suffix, accepted in [('无法判断差距源于经营效率。', True), ('无法据此判断差距源于经营效率。', True),
                                 ('不能据此推断差距由经营效率驱动。', True),
                                 ('无法判断获客成本，但差距源于经营效率。', False)]:
            with self.subTest(suffix=suffix):
                candidate = summary_fixture(scope)
                candidate['analysis'] = candidate['focuses'][0]['analysis'] = prefix + suffix
                if accepted:
                    pipeline._validate_model_summaries([candidate], scope)
                else:
                    with self.assertRaisesRegex(ValueError, '因果词'):
                        pipeline._validate_model_summaries([candidate], scope)

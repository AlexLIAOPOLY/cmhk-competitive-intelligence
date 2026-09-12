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
        unchanged = pipeline._apply_scope_model_patch(self.draft, {'patches': [
            {'path': '/focuses/0/analysis', 'value': self.draft['focuses'][0]['analysis']}]}, options)
        self.assertEqual(unchanged, self.draft)
        with self.assertRaises(ValueError):
            pipeline._validate_model_summaries([unchanged], self.scope)
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
            self.assertEqual(repair['status'], 'stopped')
            self.assertEqual(len(repair['history']), 2)
            self.assertEqual(repair['history'][0]['patch_hash'], repair['history'][1]['patch_hash'])
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

    def seed_repair(self, checkpoint, *, packet=None, status='failed'):
        """Create the deployed protocol-1 shape, with its first HTTP charged."""
        before = pipeline._content_hash(self.draft)
        options = pipeline._scope_patch_options(self.draft, self.scope)
        repair = {'protocol': 1, 'attempted': True, 'status': status,
                  'before_hash': before, 'eligible_fields': options,
                  'error': '上次实际修订仍含证据之外的数字', 'reported_model': 'actual-old-patch'}
        if packet:
            repair['response'] = {'choices': [{'message': {'content': json.dumps(packet, ensure_ascii=False)},
                                               'finish_reason': 'stop'}]}
        key = pipeline._content_hash({'format': pipeline.INSIGHT_FORMAT_VERSION,
                                     'prompt_version': pipeline.STRATEGIC_PROMPT_VERSION,
                                     'checkpoint_protocol': 2, 'scope': self.scope})
        checkpoint.with_suffix('.drafts.json').write_text(json.dumps({key: {
            'evidence_hash': pipeline._content_hash(self.scope), 'repair': repair,
            'candidates': [{'candidate': self.draft, 'candidate_hash': before,
                            'eligible_fields': options, 'requested_model': 'source-alias',
                            'reported_model': 'actual-source'}]}}, ensure_ascii=False))

    def test_legacy_failed_patch_reuses_exact_after_draft_and_counts_first_http(self):
        invalid = self.valid['focuses'][0]['analysis'].replace('10', '999')
        old_patch = {'patches': [{'path': '/focuses/0/analysis', 'value': invalid}]}
        calls = []
        def request(req, **kwargs):
            user = json.loads(req.data)['messages'][1]['content']
            content = json.loads(user[user.index('{'):])
            self.assertEqual(content['task'], 'repair_only_invalid_fields_v1')
            self.assertEqual(content['original_draft']['focuses'][0]['analysis'], invalid)
            self.assertEqual(content['previous_failed_correction']['previous_patch'], old_patch)
            self.assertIn('数字', content['previous_failed_correction']['current_gate_error'])
            options = content['allowed_patches']['/focuses/0/analysis']
            self.assertEqual(options['allowed_numeric_tokens'], ['10', '20'])
            calls.append(content)
            return model_response({'patches': [{'path': '/focuses/0/analysis',
                'value': self.valid['focuses'][0]['analysis']}]}, model='actual-second-patch')
        with tempfile.TemporaryDirectory() as td, patch.object(pipeline, 'open_llm_request', side_effect=request):
            checkpoint = Path(td) / 'ai.json'
            self.seed_repair(checkpoint, packet=old_patch)
            result = pipeline.generate_model_domain_summaries(self.scope, checkpoint_path=checkpoint)
            self.assertEqual(len(calls), 1)
            self.assertEqual(result['summaries'][0]['focuses'], self.valid['focuses'])
            history = next(iter(json.loads(checkpoint.with_suffix('.drafts.json').read_text()).values()))['repair']['history']
            self.assertEqual(len(history), 2)
            self.assertNotIn('candidate', history[0])  # Historical raw record stays immutable.
            self.assertEqual(history[1]['before_candidate']['focuses'][0]['analysis'], invalid)
            self.assertEqual(history[1]['before_hash'], pipeline._content_hash(history[1]['before_candidate']))
            self.assertEqual(history[1]['attempt_number'], 2)
            self.assertEqual(history[0]['protocol'], 1)

    def test_three_attempts_preserve_each_failed_candidate_and_never_reset_on_restart(self):
        calls = []
        values = [self.valid['focuses'][0]['analysis'] * 4,
                  self.valid['focuses'][0]['analysis'] * 3,
                  self.valid['focuses'][0]['analysis'].replace('10', '999')]
        def request(req, **kwargs):
            user = json.loads(req.data)['messages'][1]['content']
            if '"task": "repair_only_invalid_fields_v1"' not in user:
                return model_response({'items': [self.draft]})
            content = json.loads(user[user.index('{'):])
            if calls:
                self.assertEqual(content['original_draft']['focuses'][0]['analysis'], values[len(calls) - 1])
            calls.append(content)
            return model_response({'patches': [{'path': '/focuses/0/analysis', 'value': values[len(calls) - 1]}]})
        with tempfile.TemporaryDirectory() as td, patch.object(pipeline, 'open_llm_request', side_effect=request) as transport:
            checkpoint = Path(td) / 'ai.json'
            with self.assertRaisesRegex(ValueError, '修订额度已使用'):
                pipeline.generate_model_domain_summaries(self.scope, checkpoint_path=checkpoint)
            self.assertEqual(len(calls), 3)
            repair = next(iter(json.loads(checkpoint.with_suffix('.drafts.json').read_text()).values()))['repair']
            self.assertEqual([h['attempt_number'] for h in repair['history']], [1, 2, 3])
            self.assertEqual([h['candidate']['focuses'][0]['analysis'] for h in repair['history']], values)
            before = transport.call_count
            with self.assertRaisesRegex(ValueError, '修订额度已使用'):
                pipeline.generate_model_domain_summaries(self.scope, checkpoint_path=checkpoint)
            self.assertEqual(transport.call_count, before)
            self.assertFalse(checkpoint.exists())

    def test_reserved_http_survives_crash_and_resume_never_regenerates_full_scope(self):
        with tempfile.TemporaryDirectory() as td:
            checkpoint = Path(td) / 'ai.json'
            self.seed_repair(checkpoint, status='running')
            with patch.object(pipeline, 'open_llm_request', return_value=model_response({'patches': [
                {'path': '/focuses/0/analysis', 'value': self.valid['focuses'][0]['analysis']}]})) as request:
                pipeline.generate_model_domain_summaries(self.scope, checkpoint_path=checkpoint)
            self.assertEqual(request.call_count, 1)
            repair = next(iter(json.loads(checkpoint.with_suffix('.drafts.json').read_text()).values()))['repair']
            self.assertEqual(len(repair['history']), 2)
            self.assertEqual(repair['history'][0]['status'], 'running')
            self.assertEqual(repair['history'][1]['attempt_number'], 2)

    def test_different_patch_with_same_error_and_no_progress_stops_early(self):
        calls = []
        def request(req, **kwargs):
            user = json.loads(req.data)['messages'][1]['content']
            if '"task": "repair_only_invalid_fields_v1"' not in user:
                return model_response({'items': [self.draft]})
            suffix = '保持口径。保持原值。' if not calls else '保留原值。保持口径。'
            calls.append(user)
            return model_response({'patches': [{'path': '/focuses/0/analysis',
                'value': self.valid['focuses'][0]['analysis'] + suffix}]})
        with tempfile.TemporaryDirectory() as td, patch.object(pipeline, 'open_llm_request', side_effect=request):
            checkpoint = Path(td) / 'ai.json'
            with self.assertRaisesRegex(ValueError, '重复无进展'):
                pipeline.generate_model_domain_summaries(self.scope, checkpoint_path=checkpoint)
            repair = next(iter(json.loads(checkpoint.with_suffix('.drafts.json').read_text()).values()))['repair']
            self.assertEqual(len(calls), 2)
            self.assertEqual(repair['status'], 'stopped')
            self.assertNotEqual(repair['history'][0]['patch_hash'], repair['history'][1]['patch_hash'])
            self.assertEqual(repair['history'][0]['error'], repair['history'][1]['error'])

    def test_missing_original_draft_cannot_change_input_or_refund_history(self):
        with tempfile.TemporaryDirectory() as td:
            checkpoint = Path(td) / 'ai.json'
            self.seed_repair(checkpoint)
            draft_path = checkpoint.with_suffix('.drafts.json')
            drafts = json.loads(draft_path.read_text())
            next(iter(drafts.values()))['repair']['before_hash'] = 'missing-original'
            draft_path.write_text(json.dumps(drafts))
            with patch.object(pipeline, 'open_llm_request') as request, self.assertRaisesRegex(ValueError, '缺少原始草稿'):
                pipeline.generate_model_domain_summaries(self.scope, checkpoint_path=checkpoint)
            request.assert_not_called()
            self.assertEqual(json.loads(draft_path.read_text()), drafts)

    def test_single_patch_cannot_hide_a_second_transport_or_proxy_retry(self):
        def rotate(req, **kwargs):
            self.assertEqual(kwargs['max_transport_retries'], 0)
            kwargs['open_func'](req, timeout=1)
            return kwargs['open_func'](req, timeout=1)
        with patch.object(pipeline, 'open_llm_request', side_effect=rotate), \
             patch('urllib.request.urlopen', return_value=model_response({})) as http:
            with self.assertRaisesRegex(ValueError, '一个HTTP') as raised:
                pipeline._request_scope_model_patch(self.scope, self.draft,
                    pipeline._scope_patch_options(self.draft, self.scope), self.config)
            self.assertEqual(http.call_count, 1)
            self.assertEqual(raised.exception.model_patch_attempt['http_calls'], 1)

    def test_title_limit_is_a_full_gate_and_prompt_uses_exact_signed_numbers(self):
        candidate = copy.deepcopy(self.valid)
        candidate['focuses'][0]['headline'] = '客户经营结构明显分化' * 4
        with self.assertRaisesRegex(ValueError, '标题超过36字'):
            pipeline._validate_model_summaries([candidate], self.scope)
        scope = copy.deepcopy(self.scope)
        scope['domains'][0]['focuses'][0]['items'][0]['value'] = -25
        option = pipeline._scope_patch_options(candidate, scope)['/focuses/0/headline']
        self.assertEqual(option['max_characters'], 28)
        self.assertEqual(option['target_characters'], [10, 22])
        self.assertIn('-25', option['allowed_numeric_tokens'])
        self.assertNotIn('25', option['allowed_numeric_tokens'])

    def test_operating_synonyms_still_require_meaning_and_relationship(self):
        accepted = [('revenue', 'AWS与Azure云收入底盘远超中国厂商'),
                    ('revenue', '全球云收入底盘由AWS与Azure主导'),
                    ('profit', 'AWS云利润领先Azure，造血能力更强'),
                    ('profit', 'AWS云利润规模领先，造血能力更强')]
        rejected = [('revenue', '云收入远超'), ('revenue', '云收入由AWS主导'),
                    ('revenue', '云收入底盘'), ('profit', '云利润造血能力'),
                    ('profit', 'AWS云利润规模领先'), ('profit', '云利润造血能力数据维护'),
                    ('revenue', '应优先扩大云收入底盘'), ('revenue', '云收入底盘主导披露更新')]
        for focus, title in accepted + rejected:
            with self.subTest(title=title):
                self.assertEqual(not bool(pipeline._focus_headline_style_note('cloud', focus, title)),
                                 (focus, title) in accepted)

    def test_revalidated_model_text_can_pass_spent_budget_without_another_http(self):
        for count, status in [(2, 'stopped'), (3, 'failed'), (3, 'stopped')]:
            with self.subTest(count=count, status=status), tempfile.TemporaryDirectory() as td:
                checkpoint = Path(td) / 'ai.json'
                self.seed_repair(checkpoint)
                draft_path = checkpoint.with_suffix('.drafts.json')
                drafts = json.loads(draft_path.read_text())
                entry = next(iter(drafts.values()))
                old = entry['repair']
                history = [{**old, 'attempt_number': i + 1, 'status': 'failed'} for i in range(count)]
                history[-1].update(status=status, candidate=self.valid,
                                   after_hash=pipeline._content_hash(self.valid))
                entry['repair'] = {**history[-1], 'history': history}
                draft_path.write_text(json.dumps(drafts))
                with patch.object(pipeline, 'open_llm_request') as request:
                    result = pipeline.generate_model_domain_summaries(self.scope, checkpoint_path=checkpoint)
                request.assert_not_called()
                self.assertEqual(result['summaries'][0]['focuses'], self.valid['focuses'])
                stored = next(iter(json.loads(draft_path.read_text()).values()))['repair']
                self.assertEqual(stored['status'], 'passed')
                self.assertEqual(stored['history'], history)
                self.assertEqual(len(stored['history']), count)

    def test_transport_cooldown_preserves_history_and_defers_without_spending_model_edits(self):
        with tempfile.TemporaryDirectory() as td:
            checkpoint = Path(td) / 'ai.json'
            self.seed_repair(checkpoint)
            draft_path = checkpoint.with_suffix('.drafts.json')
            drafts = json.loads(draft_path.read_text())
            entry = next(iter(drafts.values()))
            old = {**entry['repair'], 'reported_model': None, 'error': 'APIKeyPoolUnavailable: shared cooldown', 'http_calls': 0}
            entry['repair'] = {**old, 'history': [dict(old) for _ in range(3)]}
            draft_path.write_text(json.dumps(drafts))
            with patch.object(pipeline, 'open_llm_request', side_effect=TimeoutError('connection timed out')) as request:
                with self.assertRaises(Exception):
                    pipeline.generate_model_domain_summaries(self.scope, checkpoint_path=checkpoint)
            self.assertEqual(request.call_count, 1)
            history = next(iter(json.loads(draft_path.read_text()).values()))['repair']['history']
            self.assertEqual(len(history), 4)
            self.assertEqual(history[-1]['status'], 'deferred_transport')
            with patch.object(pipeline, 'open_llm_request', return_value=model_response({'patches':[
                    {'path':'/focuses/0/analysis','value':self.valid['focuses'][0]['analysis']}]}, model='actual-recovery')) as request:
                result=pipeline.generate_model_domain_summaries(self.scope, checkpoint_path=checkpoint)
            self.assertEqual(request.call_count, 1)
            self.assertEqual(result['summaries'][0]['focuses'], self.valid['focuses'])

    def presentation_draft(self, body_length=138, title_length=29):
        candidate = copy.deepcopy(self.valid)
        focus = candidate['focuses'][0]
        base = focus['analysis'][:-1]
        focus['analysis'] = base + '原' * (body_length - len(base) - 1) + '。'
        focus['headline'] = '客户结构分化' + '原' * (title_length - len('客户结构分化'))
        return candidate

    def test_writing_target_warning_and_publication_limit_are_distinct(self):
        for body, title, warning_count in [(120, 28, 0), (121, 28, 1), (120, 29, 1), (160, 36, 2)]:
            with self.subTest(body=body, title=title):
                candidate = self.presentation_draft(body, title)
                validated = pipeline._validate_model_summaries([candidate], self.scope)[0]
                focus = validated['focuses'][0]
                self.assertEqual(focus['analysis'], candidate['focuses'][0]['analysis'])
                self.assertEqual(len(focus.get('presentation_warnings', [])), warning_count)
                # Cache/final revalidation ignores metadata numbers and rebuilds warnings.
                self.assertEqual(pipeline._validate_model_summaries([validated], self.scope), [validated])
        for body, title in [(161, 28), (120, 37)]:
            with self.subTest(body=body, title=title), self.assertRaisesRegex(ValueError, '发布保护上限'):
                pipeline._validate_model_summaries([self.presentation_draft(body, title)], self.scope)

    def test_style_warning_never_bypasses_facts_sentences_or_sources(self):
        variants = []
        for field, value in [('analysis', self.presentation_draft()['focuses'][0]['analysis'].replace('10', '99')),
                             ('analysis', self.valid['focuses'][0]['analysis'] + '保持原值。保持口径。'),
                             ('analysis', self.valid['focuses'][0]['analysis'][:-1]),
                             ('analysis', self.valid['focuses'][0]['analysis'] + '差距源于经营效率。'),
                             ('source_urls', ['https://unknown.test'])]:
            candidate = self.presentation_draft()
            candidate['focuses'][0][field] = value
            candidate['focuses'][0]['presentation_warnings'] = [{'allow_all': True}]
            variants.append(candidate)
        for candidate in variants:
            with self.subTest(focus=candidate['focuses'][0]), self.assertRaises(ValueError):
                pipeline._validate_model_summaries([candidate], self.scope)
        candidate = self.presentation_draft(120, 28)
        candidate['focuses'][0]['presentation_warnings'] = [{'characters': 999, 'allow_all': True}]
        validated = pipeline._validate_model_summaries([candidate], self.scope)[0]
        self.assertNotIn('presentation_warnings', validated['focuses'][0])

    def test_explicit_unchanged_field_does_not_discard_valid_model_title(self):
        draft = self.presentation_draft(138, 37)
        options = pipeline._scope_patch_options(draft, self.scope)
        options['/focuses/0/analysis'] = {'type': 'string', 'current': draft['focuses'][0]['analysis']}
        packet = {'patches': [
            {'path': '/focuses/0/headline', 'value': self.valid['focuses'][0]['headline']},
            {'path': '/focuses/0/analysis', 'value': draft['focuses'][0]['analysis']}]}
        result = pipeline._apply_scope_model_patch(draft, packet, options)
        validated = pipeline._validate_model_summaries([result], self.scope)[0]
        self.assertEqual(validated['focuses'][0]['headline'], packet['patches'][0]['value'])
        self.assertEqual(validated['focuses'][0]['analysis'], packet['patches'][1]['value'])
        self.assertEqual(validated['focuses'][0]['presentation_warnings'][0]['characters'], 138)

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

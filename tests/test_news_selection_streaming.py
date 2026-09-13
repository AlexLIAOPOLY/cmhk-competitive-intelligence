from __future__ import annotations

import hashlib
import json
import unittest
from unittest import mock

import httpx
from langchain_core.messages import HumanMessage

from cmhk.intelligence import news_selection_agent as agent


def _chunk(content='', *, finish=None, response_id='fresh-news'):
    return ('data: ' + json.dumps({
        'id': response_id, 'object': 'chat.completion.chunk', 'created': 1,
        'model': 'actual-model', 'choices': [{'index': 0, 'delta': {'content': content},
                                             'finish_reason': finish}],
    }) + '\n\n').encode()


class _BrokenStream(httpx.SyncByteStream):
    def __iter__(self):
        yield _chunk('{"decisions":[')
        raise httpx.ReadError('connection closed after first chunk')


class NewsSelectionStreamingTests(unittest.TestCase):
    def setUp(self):
        self.session = {'calls': 0}
        token = agent._MODEL_SESSION.set(self.session)
        self.addCleanup(agent._MODEL_SESSION.reset, token)
        for name in ('wait_for_internal_ai_slot', 'api_key_retry_after'):
            patcher = mock.patch('cmhk.ai.ai_rate_limit.' + name, return_value=0)
            patcher.start()
            self.addCleanup(patcher.stop)

    def invoke(self, responder):
        self.requests = []
        def respond(request):
            self.requests.append(json.loads(request.content))
            return responder(request)
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            model = agent.ChatDeepSeek(model='requested-model', api_key='test-only',
                api_base='https://example.invalid/v1', http_client=client,
                streaming=True, disable_streaming=False, cache=False, max_retries=0,
                include_response_headers=True)
            return agent._selection_model_invoke(model, [HumanMessage(content='review')])

    def test_actual_http_stream_is_aggregated_once_with_identity_and_stop(self):
        answer = '{"decisions":[]}'
        response = self.invoke(lambda _: httpx.Response(200,
            headers={'content-type': 'text/event-stream'},
            content=_chunk(answer[:8]) + _chunk(answer[8:]) + _chunk(finish='stop') + b'data: [DONE]\n\n'))
        self.assertEqual(json.loads(agent._langchain_response_text(response)), {'decisions': []})
        self.assertTrue(self.requests[0]['stream'])
        self.assertEqual((len(self.requests), self.session['calls']), (1, 1))
        evidence = self.session['last_response_evidence']
        self.assertEqual(evidence['response_id'], 'fresh-news')
        self.assertEqual(evidence['reported_model'], 'actual-model')
        self.assertEqual(evidence['finish_reason'], 'stop')
        self.assertEqual(evidence['output_sha256'], hashlib.sha256(answer.encode()).hexdigest())

    def test_half_stream_disconnect_is_not_replayed_or_returned(self):
        with self.assertRaises(httpx.ReadError):
            self.invoke(lambda _: httpx.Response(200, headers={'content-type': 'text/event-stream'},
                                                stream=_BrokenStream()))
        self.assertEqual((len(self.requests), self.session['calls']), (1, 1))
        self.assertNotIn('last_response_evidence', self.session)

    def test_failure_before_first_chunk_is_not_retried_inside_sdk(self):
        with self.assertRaises(Exception):
            self.invoke(lambda _: httpx.Response(503, json={'error': {'message': 'unavailable'}}))
        self.assertEqual((len(self.requests), self.session['calls']), (1, 1))
        self.assertNotIn('last_response_evidence', self.session)

    def test_complete_json_without_stop_is_never_accepted(self):
        with self.assertRaises(agent.TruncatedModelOutput):
            self.invoke(lambda _: httpx.Response(200, headers={'content-type': 'text/event-stream'},
                content=_chunk('{"decisions":[]}') + b'data: [DONE]\n\n'))
        self.assertEqual((len(self.requests), self.session['calls']), (1, 1))

    def test_response_id_change_cannot_merge_different_completions(self):
        with self.assertRaisesRegex(agent.TruncatedModelOutput, 'ID'):
            self.invoke(lambda _: httpx.Response(200, headers={'content-type': 'text/event-stream'},
                content=_chunk('{') + _chunk('}', finish='stop', response_id='another') + b'data: [DONE]\n\n'))
        self.assertEqual((len(self.requests), self.session['calls']), (1, 1))

    def test_length_finish_even_with_json_is_not_accepted(self):
        with self.assertRaises(agent.TruncatedModelOutput):
            self.invoke(lambda _: httpx.Response(200, headers={'content-type': 'text/event-stream'},
                content=_chunk('{"decisions":[]}', finish='length') + b'data: [DONE]\n\n'))
        self.assertEqual((len(self.requests), self.session['calls']), (1, 1))

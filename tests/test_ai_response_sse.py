import copy
import io
import json
import unittest

from cmhk.ai.ai_response_compat import StructuredAIResponseError, final_chat_message_text, read_chat_completion_sse
from tests.ai_stream_fixture import sse_response


def stream_chunks(chunks, *, done=True):
    raw = ''.join('data: '+json.dumps(c, ensure_ascii=False)+'\n\n' for c in chunks)
    if done: raw += 'data: [DONE]\n\n'
    r = io.BytesIO(raw.encode())
    r.headers = {'Content-Type': 'text/event-stream'}
    return r


def chunks_fixture():
    response = sse_response({'结果': '真实内容'}, model='actual-model', response_id='one-request')
    return [json.loads(line[5:]) for line in response.getvalue().decode().splitlines()
            if line.startswith('data: {')]


class ChatCompletionSSETests(unittest.TestCase):
    def test_complete_stream_with_usage_tail_preserves_content_and_identity(self):
        chunks = chunks_fixture()
        chunks.insert(1, {**{k: chunks[0][k] for k in ('id', 'model', 'created')},
                          'choices': [{'index': 0, 'delta': {'reasoning_content': '不得作为答案'}, 'finish_reason': None}]})
        chunks.append({**{k: chunks[0][k] for k in ('id', 'model', 'created')}, 'choices': [], 'usage': {'total_tokens': 10}})
        payload = read_chat_completion_sse(stream_chunks(chunks))
        self.assertEqual(json.loads(final_chat_message_text(payload)), {'结果': '真实内容'})
        self.assertEqual(payload['model'], 'actual-model')
        self.assertEqual(payload['id'], 'one-request')
        self.assertTrue(payload['stream_diagnostics']['done'])
        self.assertEqual(payload['stream_diagnostics']['chunks'], 4)
        self.assertEqual(len(payload['stream_diagnostics']['response_hash']), 64)

    def test_utf8_network_fragments_are_buffered_without_corrupting_model_text(self):
        raw = sse_response({'正文': '企业经营规模不同。'}).getvalue()
        class BytewiseSocket(io.RawIOBase):
            def __init__(self): self.offset = 0
            def readable(self): return True
            def readinto(self, buffer):
                if self.offset >= len(raw): return 0
                buffer[0] = raw[self.offset]
                self.offset += 1
                return 1
        response = io.BufferedReader(BytewiseSocket(), buffer_size=4)
        response.headers = {'Content-Type': 'text/event-stream; charset=utf-8'}
        payload = read_chat_completion_sse(response)
        self.assertEqual(json.loads(final_chat_message_text(payload)), {'正文': '企业经营规模不同。'})

    def test_non_sse_cached_json_is_rejected_with_actual_identity_diagnostics(self):
        response = io.BytesIO(json.dumps({'id': 'old-id', 'model': 'old-model', 'created': 12}).encode())
        response.headers = {'Content-Type': 'application/json'}
        with self.assertRaisesRegex(StructuredAIResponseError, '非流式历史响应') as ctx:
            read_chat_completion_sse(response)
        self.assertEqual(ctx.exception.stream_diagnostics['reported_model'], 'old-model')
        self.assertEqual(ctx.exception.stream_diagnostics['response_id'], 'old-id')

    def test_missing_done_missing_stop_and_length_are_rejected(self):
        for finish, done in [('stop', False), (None, True), ('length', True), ('content_filter', True)]:
            with self.subTest(finish=finish, done=done), self.assertRaises(StructuredAIResponseError):
                read_chat_completion_sse(sse_response('完整JSON仍须终止标记', finish=finish, done=done))

    def test_id_model_created_and_choice_changes_cannot_splice_streams(self):
        for field, value in [('id', 'other-request'), ('model', 'other-model'), ('created', 13)]:
            chunks = chunks_fixture(); chunks[-1][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(StructuredAIResponseError, '身份'):
                read_chat_completion_sse(stream_chunks(chunks))
        for index in (1, -1):
            chunks = chunks_fixture(); chunks[-1]['choices'][0]['index'] = index
            with self.assertRaisesRegex(StructuredAIResponseError, 'choice'):
                read_chat_completion_sse(stream_chunks(chunks))

    def test_partial_transport_failure_carries_audit_and_never_returns_prose(self):
        initial = stream_chunks(chunks_fixture()[:1], done=False).getvalue()
        class BrokenStream(io.BytesIO):
            headers = {'Content-Type': 'text/event-stream'}
            def readline(self, size=-1):
                if self.tell() >= len(initial): raise ConnectionResetError('socket reset')
                return super().readline(size)
        with self.assertRaisesRegex(StructuredAIResponseError, '传输中断') as ctx:
            read_chat_completion_sse(BrokenStream(initial))
        self.assertGreater(ctx.exception.stream_diagnostics['bytes'], 0)
        self.assertFalse(ctx.exception.stream_diagnostics['done'])

    def test_invalid_event_size_timeout_and_post_stop_content_rejected(self):
        response = io.BytesIO(b'data: {bad\n\ndata: [DONE]\n\n'); response.headers = {'Content-Type': 'text/event-stream'}
        with self.assertRaisesRegex(StructuredAIResponseError, '事件JSON'):
            read_chat_completion_sse(response)
        with self.assertRaisesRegex(StructuredAIResponseError, '字节上限'):
            read_chat_completion_sse(sse_response('中文'), max_bytes=4)
        with self.assertRaisesRegex(StructuredAIResponseError, '时限'):
            read_chat_completion_sse(sse_response('中文'), max_seconds=-1)
        chunks = chunks_fixture(); chunks.append(copy.deepcopy(chunks[-1]))
        with self.assertRaisesRegex(StructuredAIResponseError, 'stop后'):
            read_chat_completion_sse(stream_chunks(chunks))

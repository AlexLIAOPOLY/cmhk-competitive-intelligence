"""Complete OpenAI-style SSE fixtures for tests of streaming callers."""
import io
import json
from uuid import uuid4


def sse_response(content, model='primary', *, response_id=None, finish='stop', done=True):
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    identity = {'id': response_id or uuid4().hex, 'model': model, 'created': 1789097863}
    chunks = [{**identity, 'object': 'chat.completion.chunk', 'choices': [
        {'index': 0, 'delta': {'role': 'assistant', 'content': text[:len(text)//2]}, 'finish_reason': None}]},
        {**identity, 'object': 'chat.completion.chunk', 'choices': [
        {'index': 0, 'delta': {'content': text[len(text)//2:]}, 'finish_reason': finish}]}]
    raw = ''.join('data: '+json.dumps(chunk, ensure_ascii=False)+'\n\n' for chunk in chunks)
    if done:
        raw += 'data: [DONE]\n\n'
    response = io.BytesIO(raw.encode())
    response.headers = {'Content-Type': 'text/event-stream; charset=utf-8'}
    return response


def sse_payload_response(payload):
    choice = (payload.get('choices') or [{}])[0]
    return sse_response(choice.get('message', {}).get('content') or '',
                        model=payload.get('model') or 'primary', finish=choice.get('finish_reason') or 'stop')

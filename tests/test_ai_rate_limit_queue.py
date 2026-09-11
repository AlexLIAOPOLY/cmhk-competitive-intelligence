import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

import ai_dispatch as dispatch
from ai_key_rotation import open_llm_request


@pytest.fixture(autouse=True)
def capacity(monkeypatch):
    monkeypatch.setenv('CMHK_INTERNAL_AI_REQUESTS_PER_MINUTE', '1000')
    monkeypatch.setenv('CMHK_INTERNAL_AI_MAX_CONCURRENT', '8')


def test_foreground_can_enter_while_long_report_is_running():
    with dispatch.request_context('report', 'background'), dispatch.model_call('weekly-report-writer'):
        with dispatch.request_context('alice'), dispatch.model_call('competitor-insight'):
            assert dispatch.capacity_status()['active'] == 2
    assert dispatch.capacity_status()['active'] == 0


def test_background_cannot_consume_foreground_reserve(monkeypatch):
    monkeypatch.setenv('CMHK_INTERNAL_AI_REQUESTS_PER_MINUTE', '14')
    for _ in range(10):
        dispatch.wait_for_slot('weekly-report-writer')
    bg = dispatch._Ticket('weekly-report-writer', hold=True)
    try:
        assert not bg.try_acquire()
        with dispatch.request_context('alice'), dispatch.model_call('competitor-insight'):
            assert dispatch.capacity_status()['usedThisMinute'] == 11
    finally:
        bg.close()


def test_foreground_usage_does_not_reduce_background_allocation(monkeypatch):
    monkeypatch.setenv('CMHK_INTERNAL_AI_REQUESTS_PER_MINUTE', '14')
    with dispatch.request_context('alice'):
        for _ in range(4):
            dispatch.wait_for_slot('competitor-insight')
    for _ in range(10):
        dispatch.wait_for_slot('weekly-report-writer')
    assert dispatch.capacity_status()['usedThisMinute'] == 14


def test_background_keeps_rate_and_concurrent_capacity_under_ui_load(monkeypatch):
    monkeypatch.setenv('CMHK_INTERNAL_AI_REQUESTS_PER_MINUTE', '14')
    with dispatch.request_context('alice'):
        for _ in range(12):
            dispatch.wait_for_slot('competitor-insight')
    with dispatch.model_call('weekly-report-writer'):
        assert dispatch.capacity_status()['usedThisMinute'] == 13


def test_same_user_limit_does_not_block_other_user():
    with dispatch.request_context('alice'), dispatch.model_call('one'), dispatch.model_call('two'):
        waiting = dispatch._Ticket('three', hold=True)
        try:
            assert not waiting.try_acquire()
            with dispatch.request_context('bob'), dispatch.model_call('four'):
                assert dispatch.capacity_status()['active'] == 3
        finally:
            waiting.close()


def test_queue_is_bounded_and_cancelled_ticket_is_removed(monkeypatch):
    monkeypatch.setenv('CMHK_INTERNAL_AI_MAX_CONCURRENT', '1')
    monkeypatch.setenv('CMHK_INTERNAL_AI_MAX_QUEUED', '1')
    with dispatch.model_call('report'):
        waiting = dispatch._Ticket('other', hold=True)
        assert not waiting.try_acquire()
        with pytest.raises(dispatch.AIQueueBusy, match='队列已满'):
            with dispatch.model_call('third'):
                pass
        waiting.close()
        assert dispatch.capacity_status()['queued'] == 0


def test_round_robin_between_users_overrides_batch_fifo(monkeypatch):
    monkeypatch.setenv('CMHK_INTERNAL_AI_MAX_CONCURRENT', '1')
    with dispatch.request_context('alice'):
        with dispatch.model_call('first'):
            alice = dispatch._Ticket('second', hold=True)
            assert not alice.try_acquire()
            with dispatch.request_context('bob'):
                bob = dispatch._Ticket('third', hold=True)
            assert not bob.try_acquire()
        try:
            assert not alice.try_acquire()
            assert bob.try_acquire()
            bob.close()
            assert alice.try_acquire()
        finally:
            bob.close()
            alice.close()


def test_async_cancel_does_not_consume_a_future_request():
    async def run():
        with dispatch.request_context('alice'), dispatch.model_call('one'), dispatch.model_call('two'):
            async def blocked():
                async with dispatch.async_model_call('three'):
                    pytest.fail('cancelled request reached model')
            task = asyncio.create_task(blocked())
            await asyncio.sleep(.03)
            assert dispatch.capacity_status()['queued'] == 1
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert dispatch.capacity_status()['queued'] == 0
            assert dispatch.capacity_status()['usedThisMinute'] == 2
    asyncio.run(run())
    assert dispatch.capacity_status()['active'] == 0


def test_waiting_request_emits_heartbeat_and_deadline_releases_queue(monkeypatch):
    monkeypatch.setenv('CMHK_INTERNAL_AI_MAX_CONCURRENT', '1')
    events = []
    with dispatch.model_call('report'):
        with pytest.raises(dispatch.AIQueueBusy, match='排队超时'):
            with dispatch.model_call('other', deadline_monotonic=time.monotonic()+.05, wait_callback=events.append):
                pass
    assert events
    assert dispatch.capacity_status()['queued'] == 0


def test_50_threads_share_capacity_and_all_complete():
    barrier = threading.Barrier(50)
    def user(index):
        barrier.wait(timeout=10)
        with dispatch.request_context(f'user-{index}'), dispatch.model_call('competitor-insight'):
            active = dispatch.capacity_status()['active']
            time.sleep(.02)
            return active
    with ThreadPoolExecutor(max_workers=50) as pool:
        active = list(pool.map(user, range(50)))
    assert 2 <= max(active) <= 7  # One slot stays available to background work.
    status = dispatch.capacity_status()
    assert status['usedThisMinute'] == 50
    assert status['active'] == status['queued'] == 0


def test_process_death_releases_lease_but_retains_rate_charge():
    code = 'from ai_dispatch import model_call; import os; c=model_call("report"); c.__enter__(); os._exit(0)'
    subprocess.run([sys.executable, '-c', code], check=True, timeout=15)
    status = dispatch.capacity_status()
    assert status['active'] == 0
    assert status['usedThisMinute'] == 1


def test_multiple_processes_do_not_multiply_global_capacity(monkeypatch):
    monkeypatch.setenv('CMHK_INTERNAL_AI_MAX_CONCURRENT', '4')
    code = '''from ai_dispatch import model_call,request_context,capacity_status
import os,time,json
with request_context(str(os.getpid())), model_call('insight'):
 print(json.dumps(capacity_status()),flush=True)
 time.sleep(.12)
'''
    children = [subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, text=True) for _ in range(10)]
    statuses = [json.loads(child.communicate(timeout=20)[0]) for child in children]
    assert all(child.returncode == 0 for child in children)
    assert max(item['active'] for item in statuses) <= 3
    assert dispatch.capacity_status()['usedThisMinute'] == 10
    assert dispatch.capacity_status()['active'] == 0


def test_legacy_counter_and_corrupt_state_are_not_reset_to_free_capacity(monkeypatch):
    monkeypatch.setenv('CMHK_INTERNAL_AI_REQUESTS_PER_MINUTE', '14')
    path = dispatch.state_path()
    path.write_text(json.dumps({'window': int(time.time()//60), 'count': 10}))
    ticket = dispatch._Ticket('report', hold=True)
    try:
        assert not ticket.try_acquire()
    finally:
        ticket.close()
    path.write_text('{broken')
    with pytest.raises(dispatch.AIQueueBusy, match='状态暂不可读'):
        dispatch.capacity_status()


def test_large_configured_capacity_is_not_silently_clamped_to_15(monkeypatch):
    monkeypatch.setenv('CMHK_INTERNAL_AI_REQUESTS_PER_MINUTE', '120')
    assert dispatch.limits()['requestsPerMinute'] == 120


def test_streaming_lease_lasts_through_eof_and_partial_close():
    import io
    import urllib.request
    request = urllib.request.Request('http://fixture/v1/chat/completions', data=b'{"stream":true}')
    response = open_llm_request(request, timeout=5, config={'api_key':'fixture'}, open_func=lambda *a,**k:io.BytesIO(b'a\nb\n'))
    assert dispatch.capacity_status()['active'] == 1
    assert list(response) == [b'a\n',b'b\n']
    assert dispatch.capacity_status()['active'] == 0
    with open_llm_request(request, timeout=5, config={'api_key':'fixture'}, open_func=lambda *a,**k:io.BytesIO(b'a\nb\n')) as response:
        assert response.read(1) == b'a'
        assert dispatch.capacity_status()['active'] == 1
    assert dispatch.capacity_status()['active'] == 0


def test_heartbeat_exception_and_transport_failure_release_slots():
    import urllib.request
    request=urllib.request.Request('http://fixture/v1/chat/completions', data=b'{}')
    def fail(*args, **kwargs):
        raise ValueError('fixture rejected')
    with pytest.raises(ValueError):
        open_llm_request(request,timeout=5,config={'api_key':'fixture'},open_func=fail)
    assert dispatch.capacity_status()['active'] == 0


def test_one_user_cannot_fill_everyones_waiting_queue(monkeypatch):
    monkeypatch.setenv('CMHK_INTERNAL_AI_MAX_CONCURRENT', '1')
    monkeypatch.setenv('CMHK_INTERNAL_AI_PER_USER_QUEUED', '2')
    tickets = []
    with dispatch.model_call('report'):
        try:
            with dispatch.request_context('alice'):
                for _ in range(2):
                    ticket = dispatch._Ticket('insight', hold=True)
                    tickets.append(ticket)
                    assert not ticket.try_acquire()
                with pytest.raises(dispatch.AIQueueBusy, match='您的'):
                    dispatch._Ticket('insight', hold=True).try_acquire()
            with dispatch.request_context('bob'):
                bob = dispatch._Ticket('insight', hold=True)
                tickets.append(bob)
                assert not bob.try_acquire()
            assert dispatch.capacity_status()['queued'] == 3
        finally:
            for ticket in tickets:
                ticket.close()


def test_chat_background_thread_keeps_authenticated_subject():
    import hashlib
    import web_app
    subject = 'verified-user-identity'
    observed = []
    def producer():
        observed.append(dispatch.SUBJECT.get())
        yield {'type': 'done'}
    with dispatch.request_context(subject):
        session = web_app.ChatStreamSession('fixture-id', 'fixture-fingerprint', producer)
        session.start()
    list(session.events_after(0))
    assert observed == [hashlib.sha256(subject.encode()).hexdigest()[:24]]
    assert dispatch.SUBJECT.get() == ''


def test_sdk_retries_cannot_bypass_shared_accounting(monkeypatch):
    import httpx
    import ai_rate_limit
    calls = []
    def reply(request):
        calls.append(request)
        return httpx.Response(500, json={'error': {'message': 'fixture failure'}})
    monkeypatch.setattr(ai_rate_limit, 'load_ai_config', lambda **kwargs: {'api_key': 'fixture'})
    monkeypatch.setattr(ai_rate_limit, 'transport_retry_delay', lambda *args: 0)
    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        model = ai_rate_limit.RateLimitedChatDeepSeek(model='fixture',api_key='fixture',base_url='https://example.test/v1',http_client=client,max_retries=8)
        with pytest.raises(Exception):
            model.invoke('fixture')
    assert len(calls) == 3
    assert dispatch.capacity_status()['usedThisMinute'] == 3
    assert dispatch.capacity_status()['active'] == 0


def test_disconnected_browser_removes_queued_request_without_inference(monkeypatch):
    monkeypatch.setenv('CMHK_INTERNAL_AI_MAX_CONCURRENT', '1')
    def disconnected(remaining):
        raise dispatch.AIRequestCancelled('fixture disconnected')
    with dispatch.model_call('report'):
        with pytest.raises(dispatch.AIRequestCancelled):
            with dispatch.model_call('competitor', wait_callback=disconnected):
                pytest.fail('disconnected request reached inference')
        assert dispatch.capacity_status()['queued'] == 0
        assert dispatch.capacity_status()['usedThisMinute'] == 1


def test_interactive_sse_checks_actual_socket_result_through_progress_wrapper():
    import io
    from types import SimpleNamespace
    import web_app
    handler = SimpleNamespace(wfile=io.BytesIO())
    web_app.write_interactive_sse(handler, {'type':'status','message':'queued'})
    assert b'data:' in handler.wfile.getvalue()
    class Disconnected:
        def write(self, value):
            raise BrokenPipeError()
    handler.wfile = Disconnected()
    with pytest.raises(dispatch.AIRequestCancelled):
        web_app.write_interactive_sse(handler, {'type':'status','message':'queued'})


def test_identical_decisions_share_work_and_keep_waiters_informed(tmp_path):
    from cmhk.intelligence.agent_harness import run_durable_agent
    started = threading.Event()
    release = threading.Event()
    waiting = threading.Event()
    calls = []
    def execute(attempt):
        calls.append(attempt)
        started.set()
        assert release.wait(5)
        return {'ok': True}
    def invoke():
        return run_durable_agent(namespace='shared-news', identity='same-evidence', directory=tmp_path,
                                 execute=execute, lock_timeout=5, wait_callback=lambda _: waiting.set())
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(invoke)
        assert started.wait(5)
        second = pool.submit(invoke)
        assert waiting.wait(5)
        release.set()
        assert first.result(5) == second.result(5) == {'ok': True}
    assert calls == [0]

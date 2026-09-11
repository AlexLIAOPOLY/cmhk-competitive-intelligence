#!/usr/bin/env python3
"""Isolated HTTP load test: real application routes, deterministic local model.

No production AI, reports, messages, authentication state or caches are written.
This measures application scheduling, not gateway capacity or answer quality.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import sys
import tempfile
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CONTENT = ('战略指标｜【客户留存差距】持续收窄，后续需要关注服务体验变化\n'
           '竞争格局｜两家公司流失率差距由0.2个百分点收窄至0.1个百分点，竞争呈收敛趋势。\n'
           '公司定位｜HKT和SmarTone在所选年度中均改善客户留存，需要结合共同可比期间判断位置。\n'
           '业务含义｜较低流失率反映后付客户稳定性，但不能单独用来判断公司的整体经营表现。')


def run(users=50, delay=.4):
    import ai_dispatch
    import ai_rate_limit
    import web_app
    import generate_weekly_report as weekly

    lock = threading.Lock()
    counters = {'active': 0, 'peak': 0, 'requests': 0, 'mixedOverlap': False, 'reportActive': 0, 'foregroundActive': 0}
    class Gateway(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            is_report = '正式编辑' in str(body['messages'][0]['content'])
            kind = 'reportActive' if is_report else 'foregroundActive'
            with lock:
                counters['active'] += 1
                counters[kind] += 1
                counters['requests'] += 1
                counters['peak'] = max(counters['peak'], counters['active'])
                counters['mixedOverlap'] |= counters['reportActive'] > 0 and counters['foregroundActive'] > 0
            try:
                time.sleep(delay * (3 if is_report else 1))
                content = json.dumps({'items':[{'id':'W001','status':'ok','title':'隔离压测','detail':'测试内容不保存为报告。仅用于验证并发调度。','used_fact_ids':['F001']}]},ensure_ascii=False) if is_report else CONTENT
                self.send_response(200)
                self.send_header('Content-Type','text/event-stream' if body.get('stream') else 'application/json')
                self.end_headers()
                if body.get('stream'):
                    for part in (content[:35], content[35:]):
                        event = {'id':'fixture','object':'chat.completion.chunk','created':0,'model':'fixture','choices':[{'index':0,'delta':{'content':part},'finish_reason':None}]}
                        self.wfile.write(('data: '+json.dumps(event,ensure_ascii=False)+'\n\n').encode())
                        self.wfile.flush()
                    self.wfile.write(b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
                else:
                    self.wfile.write(json.dumps({'id':'fixture','model':'fixture','object':'chat.completion','choices':[{'index':0,'message':{'role':'assistant','content':content},'finish_reason':'stop'}],'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}},ensure_ascii=False).encode())
            finally:
                with lock:
                    counters['active'] -= 1
                    counters[kind] -= 1
    class QuietApp(web_app.AppHandler):
        def log_message(self,*args):
            pass

    with tempfile.TemporaryDirectory(prefix='cmhk-ai-load-') as directory, ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {
            'CMHK_INTERNAL_AI_RATE_STATE_PATH':str(Path(directory)/'rate.json'),
            'CMHK_INTERNAL_AI_KEY_STATE_PATH':str(Path(directory)/'keys.json'),
            'CMHK_INTERNAL_AI_REQUESTS_PER_MINUTE':'6000',
            'CMHK_INTERNAL_AI_MAX_CONCURRENT':'8',
            'CMHK_INTERNAL_AI_MAX_QUEUED':'200',
        }))
        gateway = ThreadingHTTPServer(('127.0.0.1',0),Gateway)
        app = web_app.AppHTTPServer(('127.0.0.1',0),QuietApp)
        for server in (gateway,app):
            threading.Thread(target=server.serve_forever,daemon=True).start()
            stack.callback(server.server_close)
            stack.callback(server.shutdown)
        config = {'provider':'deepseek','base_url':f'http://127.0.0.1:{gateway.server_port}/v1','model':'fixture','api_key':'fixture-key','api_keys':['fixture-key']}
        for module in (web_app,weekly,ai_rate_limit):
            stack.enter_context(patch.object(module,'load_ai_config',return_value=config))
        stack.enter_context(patch.object(web_app,'is_internal_ai_base_url',return_value=True))
        stack.enter_context(patch.object(web_app.AUTH,'handle',return_value=False))
        stack.enter_context(patch.object(web_app.AUTH,'authorize_api',return_value=True))
        stack.enter_context(patch.object(web_app.AUTH,'current_actor',side_effect=lambda handler:{'id':handler.headers.get('X-Fixture-User','fixture')}))
        stack.enter_context(patch.object(web_app,'record_ui_runtime_incident'))
        dataset = json.loads(web_app.COMPETITOR_WORKBENCH_DATA_PATH.read_text())
        payload = {'companies':['HKT','SmarTone'],'metric':{'key':'mobile_postpaid_churn','label':'流失率'},'years':[2020,2021,2022],'evidenceVersion':dataset['evidenceVersion']}
        start = time.monotonic()
        barrier = threading.Barrier(users+10)
        def user(index):
            barrier.wait(timeout=20)
            began = time.monotonic()
            request_id=f'user-{index}'
            request=urllib.request.Request(f'http://127.0.0.1:{app.server_port}/api/competitor-insight-stream',data=json.dumps({**payload,'requestId':request_id}).encode(),headers={'Content-Type':'application/json','X-Fixture-User':request_id})
            try:
                with urllib.request.urlopen(request,timeout=60) as response:
                    events=[json.loads(line[5:]) for line in response if line.startswith(b'data:')]
                done=next((e for e in events if e.get('type')=='done'),{})
                ok=done.get('requestId')==request_id and len(done.get('insights',[]))==3 and not any(e.get('type')=='error' for e in events)
                return {'kind':'competitor-http','ok':ok,'seconds':time.monotonic()-began,'queueUpdates':sum(e.get('stage')=='queue' for e in events),'errors':[e.get('error') for e in events if e.get('type')=='error']}
            except Exception as exc:
                return {'kind':'competitor-http','ok':False,'error':type(exc).__name__,'seconds':time.monotonic()-began}
        def report(index):
            barrier.wait(timeout=20)
            began=time.monotonic()
            try:
                result=weekly._call_weekly_writer_llm([{'id':'W001','existing_title':'隔离压测','facts':[{'id':'F001','text':'测试事实'}]}])
                return {'kind':'weekly-writer','ok':bool(result.get('items')),'seconds':time.monotonic()-began}
            except Exception as exc:
                return {'kind':'weekly-writer','ok':False,'error':type(exc).__name__,'seconds':time.monotonic()-began}
        def chat(index):
            barrier.wait(timeout=20)
            began=time.monotonic()
            try:
                with ai_dispatch.request_context(f'chat-{index}'):
                    model=ai_rate_limit.RateLimitedChatDeepSeek(model='fixture',api_key='fixture-key',base_url=config['base_url'],timeout=60)
                    result=model.invoke('隔离并发压测')
                return {'kind':'langchain-chat','ok':bool(result.content),'seconds':time.monotonic()-began}
            except Exception as exc:
                return {'kind':'langchain-chat','ok':False,'error':type(exc).__name__,'seconds':time.monotonic()-began}
        with ThreadPoolExecutor(max_workers=users+10) as pool:
            futures=[pool.submit(user,i) for i in range(users)]+[pool.submit(report,i) for i in range(6)]+[pool.submit(chat,i) for i in range(4)]
            rows=[f.result(timeout=90) for f in futures]
        elapsed=time.monotonic()-start
        latencies=sorted(r['seconds'] for r in rows if r['kind']=='competitor-http')
        result={'testType':'isolated-application-load-with-simulated-model','users':users,'requests':len(rows),'success':sum(r['ok'] for r in rows),'elapsedSeconds':round(elapsed,3),'p50Seconds':round(statistics.median(latencies),3),'p95Seconds':round(latencies[min(len(latencies)-1,int(len(latencies)*.95))],3),'model':counters,'finalCapacity':ai_dispatch.capacity_status(),'rows':rows}
        result['passed']=all(r['ok'] for r in rows) and 2<=counters['peak']<=8 and counters['mixedOverlap'] and result['finalCapacity']['active']==result['finalCapacity']['queued']==0 and result['finalCapacity']['usedThisMinute']==len(rows)
        return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--users',type=int,default=50)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not 1<=args.users<=150:
        parser.error('--users must be between 1 and 150')
    logging.basicConfig(level=logging.ERROR)
    result=run(args.users)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in {'rows','finalCapacity'}},ensure_ascii=False))
    raise SystemExit(0 if result['passed'] else 1)

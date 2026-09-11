import json
import shutil
import subprocess
import unittest
from contextlib import ExitStack
from datetime import time
from pathlib import Path
from unittest.mock import patch

import strategic_briefing as briefing
import web_app


class NewsScanTimeDisplayTests(unittest.TestCase):
    def test_status_exports_shared_schedule_including_minutes(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(briefing,'SCAN_TIMES',(time(3,30),time(14,45))))
            for name,value in {
                'current_crawl_result_files':[], 'current_report_files':[],
                'load_unified_task_index':[], 'build_settings_payload':{'summary':{}},
                'build_latest_news_funnel':{}, 'build_today_news_rounds':[],
                'build_crawl_result_visuals':{}, 'build_curation_rejection_visuals':{},
                'load_ai_config':{},
            }.items():
                stack.enter_context(patch.object(web_app,name,return_value=value))
            self.assertEqual(web_app.build_status()['visuals']['newsScanTimes'],[
                {'label':'上午','time':'03:30'},{'label':'下午','time':'14:45'}])

    def test_actual_renderer_uses_schedule_for_pending_and_archive_for_completed_rounds(self):
        node=shutil.which('node')
        if node is None:self.skipTest('Node.js is required to execute the production renderer')
        script=(Path(web_app.__file__).parent/'web/static/app.js').read_text()
        render=script[script.index('function renderCollectionOverview(status) {'):script.index('\nfunction renderInsights(status) {')]
        program=r'''
const assert = require('node:assert/strict');
const host = {dataset: {}, innerHTML: '', querySelectorAll: () => []};
const document = {getElementById: (id) => id === 'dailyAssetGrid' ? host : null};
const escapeHtml = (value) => String(value);
''' + render + r'''
const morning = {key:'2026-09-11-03-00',label:'上午',time:'03:00',status:'已完成',stages:[{label:'新增',value:179}]};
const status = {visuals:{todayNewsRounds:[morning],newsScanTimes:[{label:'上午',time:'03:30'},{label:'下午',time:'14:45'}]}};
renderCollectionOverview(status);
assert.match(host.innerHTML, /<b>上午<\/b><time>03:00<\/time>/);
assert.match(host.innerHTML, /<b>下午<\/b><time>14:45<\/time>/);
assert.match(host.innerHTML, /<em>待运行<\/em>/);
const signature = host.dataset.signature;
status.visuals.newsScanTimes[1].time = '16:10';
renderCollectionOverview(status);
assert.notEqual(host.dataset.signature, signature);
assert.match(host.innerHTML, /<b>下午<\/b><time>16:10<\/time>/);
status.visuals.todayNewsRounds.push({label:'下午',time:'15:00',status:'已完成',stages:[{label:'新增',value:4}]});
renderCollectionOverview(status);
assert.match(host.innerHTML, /<b>下午<\/b><time>15:00<\/time>/);
status.visuals.todayNewsRounds = [morning];
delete status.visuals.newsScanTimes;
renderCollectionOverview(status);
assert.match(host.innerHTML, /<b>下午<\/b><time>—<\/time>/);
assert.doesNotMatch(host.innerHTML, /<time>09:00<\/time>|<time>15:00<\/time>/);
'''
        result=subprocess.run([node,'-e',program],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)

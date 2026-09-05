const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../web/static/workspace-tabs.js'), 'utf8');

function selectedRunsContext(hash = '') {
  const context = vm.createContext({
    state: { newsRuns: [], newsSelectedDate: '', newsSelectedRunIds: [] },
    location: { hash },
    URLSearchParams,
    newsRunDate: (run) => String(run?.started_at_hkt || '').slice(0, 10),
  });
  vm.runInContext(
    source.slice(
      source.indexOf('  function selectedNewsRuns()'),
      source.indexOf('  function strategicNewsBatchKey('),
    ),
    context,
  );
  return context;
}

test('live monitor follows a newly arriving task date when history is not pinned', () => {
  const context = selectedRunsContext('#workspace=news');
  context.state.newsRuns = [
    { crawl_run_id: 'yesterday', started_at_hkt: '2026-09-04T14:00:00+08:00' },
  ];
  assert.equal(context.selectedNewsRuns()[0].crawl_run_id, 'yesterday');

  context.state.newsRuns.unshift(
    { crawl_run_id: 'today-running', started_at_hkt: '2026-09-05T07:30:44+08:00', run_status: 'running' },
  );
  assert.equal(context.selectedNewsRuns()[0].crawl_run_id, 'today-running');
  assert.equal(context.state.newsSelectedDate, '2026-09-05');
});

test('explicit historical date remains pinned during live refresh', () => {
  const context = selectedRunsContext('#workspace=news&newsDate=2026-09-04');
  context.state.newsRuns = [
    { crawl_run_id: 'today-running', started_at_hkt: '2026-09-05T07:30:44+08:00', run_status: 'running' },
    { crawl_run_id: 'yesterday', started_at_hkt: '2026-09-04T14:00:00+08:00' },
  ];
  assert.equal(context.selectedNewsRuns()[0].crawl_run_id, 'yesterday');
  assert.equal(context.state.newsSelectedDate, '2026-09-04');
});

test('scheduler handoff remains visible before the task registry entry exists', () => {
  const context = selectedRunsContext('#workspace=news');
  context.state.schedulerOverview = {
    strategic_monitor: {
      task_visible: true,
      status: 'starting',
      active_task_id: 'slot:2026-09-05@14:00',
      active_phase: '调度已交接',
      active_progress: '调度器已开始启动战略爬虫，等待任务登记。',
      active_heartbeat_at: '2026-09-05T14:00:03+08:00',
      active_started_at: '2026-09-05T14:00:00+08:00',
    },
  };
  const [run] = context.selectedNewsRuns();
  assert.equal(run.crawl_run_id, 'slot:2026-09-05@14:00');
  assert.equal(run.run_status, 'queued');
  assert.equal(context.state.newsSelectedDate, '2026-09-05');
});

test('running AI batch progress maps to the AI stage instead of an earlier stage', () => {
  const context = vm.createContext({
    number: (value) => String(value),
    runCompletionText: () => '已完成',
  });
  vm.runInContext(
    source.slice(
      source.indexOf('  function logLine(content, prefix)'),
      source.indexOf('  function selectedNewsRuns()'),
    ),
    context,
  );
  const stages = context.buildNewsProcess({
    run_status: 'running',
    phase: 'AI批量审核',
    progress_detail: '开始第 135/167 批。',
  }, { content: '[07:31] 新闻发现完成：时间窗内发现 667 条\n' });
  assert.equal(stages.find((stage) => stage.key === 'ai').status, 'current');
  assert.equal(stages.find((stage) => stage.key === 'dedupe').status, 'pending');
});

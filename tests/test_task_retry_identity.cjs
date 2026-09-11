const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../web/static/app.js'), 'utf8');
const context = vm.createContext({ crawlRunTimeValue: task => Date.parse(task.started_at_hkt) });
vm.runInContext(source.slice(source.indexOf('function unifiedTaskTitle('), source.indexOf('function taskAnalysisStatusMarkup(')), context);

test('weekly titles stay stable for fresh runs, retries and old inflated indexes', () => {
  for (const retry_index of [0, 1, 4, 5]) {
    assert.equal(context.unifiedTaskTitle({ kind: 'weekly-report', title: '生成周报', retry_index }), '生成周报');
  }
});

test('recorded retry counts override a stale API and client inference', () => {
  for (const staleApi of [true, false]) {
    const tasks = [3, 0, 1].map((retry_count, index) => ({
      kind: 'weekly-report', title: '生成周报', scope: '战略部每周周报',
      started_at_hkt: `2026-09-11T${10 + index}:00:00+08:00`,
      run_status: 'failed', retry_count,
      ...(staleApi ? { retry_index: index + 3 } : {}),
    }));
    context.annotateClientTaskRetries(tasks);
    assert.deepEqual(tasks.map(task => task.retry_index), [3, 0, 1]);
  }
});

test('legacy crawler retries retain their numbered titles', () => {
  const tasks = [0, 1].map(index => ({
    kind: 'news-selection-agent', title: '新闻自动初筛', scope: '晨间批次',
    started_at_hkt: `2026-09-11T${10 + index}:00:00+08:00`, run_status: index ? 'completed' : 'failed',
  }));
  context.annotateClientTaskRetries(tasks);
  assert.deepEqual(tasks.map(task => task.retry_index), [0, 1]);
  assert.equal(context.unifiedTaskTitle(tasks[1]), '新闻自动初筛2');
});

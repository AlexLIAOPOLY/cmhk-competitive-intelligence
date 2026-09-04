const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../web/static/workspace-tabs.js'), 'utf8');
const context = vm.createContext({});
vm.runInContext(source.slice(source.indexOf('  function newsSelectionReviewHealth('), source.indexOf('  function executiveDomainFactsForDate(')), context);
const health = context.newsSelectionReviewHealth;
const selectionContext = vm.createContext({
  state: { crawlRuns: [] },
  linkedParentRunId: (run) => String(run.parent_crawl_run_id || ''),
  newsRunDate: (run) => String(run.started_at_hkt || '').slice(0, 10),
});
vm.runInContext(
  source.slice(
    source.indexOf('  function selectionRunBatchKey('),
    source.indexOf('  function dailyNewsReviewResults('),
  ),
  selectionContext,
);
const failed = { key: 'critical', label: '异常' };
const runs = [{completed_at_hkt:'2026-09-03T15:17:49+08:00'}];
const snapshot = () => ({available:true,cached:false,updatedAt:'2026-09-03T15:30:00+08:00',rows:[{rollingStatus:'接受',weeklyStatus:'不接受'},{rollingStatus:'不接受',weeklyStatus:'接受'}]});

test('current completed reviews supersede failed historical attempts without altering runs', () => {
  const before = JSON.stringify(runs);
  const result = health(snapshot(), runs, failed);
  assert.equal(result.key, 'healthy');
  assert.match(result.reviewDetail, /2 条新闻/);
  assert.equal(JSON.stringify(runs), before);
});
test('one pending field remains pending, even when all attempts succeeded', () => {
  for (const field of ['rollingStatus','weeklyStatus']) {
    for (const value of ['待审核','','未知']) {
      const review = snapshot(); review.rows[0][field] = value;
      assert.equal(health(review, runs, {key:'healthy'}).key, 'warning');
    }
  }
});
test('a running review with remaining fields stays running', () => {
  const review = snapshot(); review.rows[0].weeklyStatus = '待审核';
  assert.equal(health(review, runs, {key:'running'}).key, 'running');
});
test('cached, unavailable, empty and stale reads never override failure', () => {
  for (const change of [{cached:true},{available:false},{rows:[]},{updatedAt:''},{updatedAt:'2026-09-03T15:00:00+08:00'}]) {
    assert.equal(health({...snapshot(),...change}, runs, failed), failed);
  }
});
test('a new task after the snapshot cannot be hidden by old completed rows', () => {
  assert.equal(health(snapshot(), [{started_at_hkt:'2026-09-03T15:31:00+08:00'}], failed), failed);
});
test('integration uses the selected date review and keeps historical attempt evidence', () => {
  assert.match(source, /newsSelectionReviewHealth\(reviewResults, selectionAttemptRuns, selectionRunHealth\)/);
  assert.match(source, /const reviewResults = dailyNewsReviewResults\(selectedDate\)/);
  assert.match(source, /evidence: selectionAttemptRuns\.map/);
});

test('latest verified rerun supersedes an older result for the same parent and population', () => {
  selectionContext.state.crawlRuns = [
    {
      crawl_run_id: 'old',
      task_kind: 'news-selection-agent',
      parent_crawl_run_id: 'parent-1',
      started_at_hkt: '2026-09-04T14:59:00+08:00',
      completed_at_hkt: '2026-09-04T15:00:00+08:00',
      run_status: 'completed',
      operational_summary: { candidate_count: 178, app_accepted_count: 91, readback_verified: true },
    },
    {
      crawl_run_id: 'new',
      task_kind: 'news-selection-agent',
      parent_crawl_run_id: 'parent-1',
      started_at_hkt: '2026-09-04T15:39:00+08:00',
      completed_at_hkt: '2026-09-04T15:48:00+08:00',
      run_status: 'completed',
      operational_summary: { candidate_count: 178, app_accepted_count: 31, readback_verified: true },
    },
  ];
  const selected = selectionContext.authoritativeSelectionRunsForDate('2026-09-04');
  assert.equal(selected.length, 1);
  assert.equal(selected[0].crawl_run_id, 'new');
  assert.equal(selected[0].operational_summary.app_accepted_count, 31);
});

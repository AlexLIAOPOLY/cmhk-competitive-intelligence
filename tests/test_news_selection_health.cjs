const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../web/static/workspace-tabs.js'), 'utf8');
const context = vm.createContext({});
vm.runInContext(source.slice(source.indexOf('  function newsSelectionReviewHealth('), source.indexOf('  function executiveDomainFactsForDate(')), context);
const health = context.newsSelectionReviewHealth;
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

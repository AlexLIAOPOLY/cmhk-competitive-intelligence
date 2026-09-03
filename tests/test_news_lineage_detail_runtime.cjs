const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '../web/static/workspace-tabs.js'), 'utf8');
function extract(name, next) {
  return script.slice(script.indexOf(`  function ${name}(`), script.indexOf(`  function ${next}(`));
}
function fixture() {
  const run = { crawl_run_id: 'selected-run' };
  const other = { crawl_run_id: 'other-run' };
  const state = {
    newsSelectedDate: '2026-09-03',
    executiveIntelligence: { domains: [] },
    newsRunDetails: {
      'selected-run': {
        crawlItems: [{ title: 'Official source', status: 'completed', urls: ['https://example.com/report'] }],
        agentReviewItems: ['accepted', 'rejected', 'review'].map(decision => ({
          company: 'Test company', metric: decision, value: '10', decision,
          sources: [{ url: 'https://example.com/report' }],
        })),
      },
      'other-run': { crawlItems: [{ title: 'Must not leak', status: 'failed' }], agentReviewItems: [] },
    },
  };
  const ctx = vm.createContext({ state, number: value => String(value ?? 0) });
  vm.runInContext(extract('executiveNodeRecords', 'detailedRecordStatus'), ctx);
  return { ctx, state, run, other };
}

test('crawler records receive only the explicitly selected related runs', () => {
  const { ctx, run } = fixture();
  const rows = ctx.detailedRecordsForNode('main', [run]);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].title, 'Official source');
  assert.equal(rows[0].run, run);
  assert.equal(rows[0].source, 'https://example.com/report');
});

test('extraction and review preserve candidate and decision semantics', () => {
  const { ctx, run } = fixture();
  const candidates = ctx.detailedRecordsForNode('fact-extract', [run]);
  assert.deepEqual(Array.from(candidates, row => row.status), ['candidate', 'candidate', 'candidate']);
  const reviewed = ctx.detailedRecordsForNode('agent', [run]);
  assert.deepEqual(Array.from(reviewed, row => row.status), ['included', 'excluded', 'deferred']);
  assert.ok(reviewed.every(row => row.run === run));
});

test('missing archives and empty dates return empty records without throwing', () => {
  const { ctx } = fixture();
  for (const key of ['main', 'fact-extract', 'agent', 'database-hub', 'database-local', 'insights']) {
    assert.equal(ctx.detailedRecordsForNode(key, []).length, 0);
    assert.equal(ctx.detailedRecordsForNode(key, [{ crawl_run_id: 'missing' }]).length, 0);
    assert.equal(ctx.executiveNodeRecords(key).length, 0);
  }
});

test('detail failures show a closable message rather than an unhandled rejection', () => {
  const dialog = { open: false, shows: 0, showModal() { this.open = true; this.shows++; } };
  const body = { innerHTML: '' };
  const errors = [];
  const ctx = vm.createContext({
    console: { error: (...args) => errors.push(args) },
    document: { querySelector: selector => selector === '#newsLineageDialog' ? dialog : body },
  });
  vm.runInContext(extract('showNewsLineageDetailError', 'bindNewsLineageInteractions'), ctx);
  ctx.showNewsLineageDetailError(new Error('<private detail>'));
  assert.equal(dialog.open, true);
  assert.match(body.innerHTML, /role="alert"/);
  assert.match(body.innerHTML, /method="dialog"/);
  assert.doesNotMatch(body.innerHTML, /private detail/);
  ctx.showNewsLineageDetailError(new Error('again'));
  assert.equal(dialog.shows, 1);
  assert.equal(errors.length, 2);
  assert.ok(script.includes('openActualNewsLineageDetail(node.dataset.newsLineageNode).catch(showNewsLineageDetailError)'));
});

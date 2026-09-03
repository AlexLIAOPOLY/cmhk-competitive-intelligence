const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '../web/static/workspace-tabs.js'), 'utf8');
function fixture(primary = null, details = {}) {
  const state = { fixedSourceSummary: primary, newsRunDetails: details };
  const ctx = vm.createContext({ state, number: String });
  vm.runInContext(script.slice(script.indexOf('  function resolvedFixedSourceSummary('),
    script.indexOf('  function globalSchedulerLineageModel(')), ctx);
  return { ctx, state, text: () => ctx.fixedSourceInputText(ctx.resolvedFixedSourceSummary()) };
}

test('unloaded, failed and invalid counts are unknown, never fabricated zero', () => {
  for (const value of [null, {}, { ok: false }, { uniqueUrls: null },
    { uniqueUrls: -1 }, { uniqueUrls: NaN }, { uniqueUrls: Infinity },
    { uniqueUrls: 1.5 }, { uniqueUrls: '128' }]) {
    assert.equal(fixture(value).text(), '飞书固定链接数量暂不可用');
  }
});

test('empty primary does not mask the current snapshot supplied with run details', () => {
  for (const primary of [null, {}, { ok: false }]) {
    const f = fixture(primary, { missing: {}, bad: null, run: { fixedSourceSummary: { uniqueUrls: 128 } } });
    assert.equal(f.text(), '128 条飞书固定链接');
  }
});

test('an explicit measured zero is valid and takes precedence over the fallback', () => {
  const f = fixture({ uniqueUrls: 0 }, { run: { fixedSourceSummary: { uniqueUrls: 128 } } });
  assert.equal(f.text(), '0 条飞书固定链接');
});

test('initial failure can recover as either detail or retry response arrives', () => {
  const f = fixture();
  assert.equal(f.text(), '飞书固定链接数量暂不可用');
  f.state.newsRunDetails.run = { fixedSourceSummary: { uniqueUrls: 128 } };
  assert.equal(f.text(), '128 条飞书固定链接');
  f.state.fixedSourceSummary = { uniqueUrls: 129 };
  assert.equal(f.text(), '129 条飞书固定链接');
});

test('card and dialog share validated counts and live refresh retries the endpoint', () => {
  assert.ok(script.includes('${fixedSourceInputText(fixedSourceSummary)}＋'));
  assert.ok(script.includes('${fixedSourceInputText(fixedSummary)}＋'));
  assert.ok(script.includes('fixedSourceUrlCount !== undefined'));
  assert.ok(script.includes('["fixedSourceSummary", "/api/fixed-source-summary"]'));
  assert.ok(script.includes('else if (key === "fixedSourceSummary") state.fixedSourceSummary = payload;'));
  assert.ok(!script.includes('Number(fixedSourceSummary.uniqueUrls || 0)'));
  assert.ok(!script.includes('Number(fixedSummary.uniqueUrls || 0)'));
});

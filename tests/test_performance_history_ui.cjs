const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '../web/static/app.js'), 'utf8');
function setup() {
  const context = vm.createContext({
    state: { multiSelect: false, selectedFiles: new Set() },
    document: { body: { classList: { contains: () => false } } },
    escapeHtml: (value) => String(value).replaceAll('&', '&amp;').replaceAll('"', '&quot;'),
    fileType: () => ({ className: 'word', icon: '' }),
    isReportUnread: () => false,
    iconSvg: () => '',
    fileDescription: () => '运营商业绩对标摘要',
  });
  vm.runInContext(source.slice(source.indexOf('const expandedReportHistory ='), source.indexOf('function renderFileList()')), context);
  return context;
}
function report(path, mtime, year = '2026', name = '9月10日运营商业绩摘要.docx') {
  return { path_str: path, name, mtime, mtimeText: `${year}-09-10 17:00:00`, url: `/outputs/${path}`, reportType: 'carrier-performance' };
}
function render(context, files, type = 'performance') {
  const target = {};
  context.renderOutputTable(target, files, '', '', type);
  const rows = [...target.innerHTML.matchAll(/<div class="file-row[^>]+>/g)].map((item) => item[0]);
  return { html: target.innerHTML, rows, visible: rows.filter((row) => !/\shidden\s/.test(row)) };
}

test('same-day library shows the latest report and keeps each historical path', () => {
  const ctx = setup();
  const result = render(ctx, [report('first.docx', 1), report('latest.docx', 3), report('second.docx', 2)]);
  assert.equal(result.rows.length, 3);
  assert.equal(result.visible.length, 1);
  assert.match(result.visible[0], /data-path="latest.docx"/);
  assert.match(result.html, /历史版本（2）/);
  assert.match(result.html, /href="\/outputs\/first.docx" download="9月10日运营商业绩摘要.docx"/);
});

test('expand/collapse survives refresh and preserves distinct selectable versions', () => {
  const ctx = setup();
  const files = [report('first.docx', 1), report('latest.docx', 3)];
  let click;
  let result;
  const key = ctx.performanceReportGroups(files)[0].key;
  const target = { scrollTop: 120, querySelectorAll: (selector) => selector === '[data-report-history]' ? [{ dataset: { reportHistory: key }, addEventListener: (_, fn) => { click = fn; } }] : [] };
  ctx.renderFileList = () => { result = render(ctx, files); };
  ctx.bindOutputTableEvents(target);
  click();
  assert.equal(result.visible.length, 2);
  assert.equal(render(ctx, files).visible.length, 2);
  ctx.state.multiSelect = true;
  ctx.state.selectedFiles.add('first.docx');
  result = render(ctx, files);
  assert.match(result.html, /data-path="first.docx" checked/);
  assert.doesNotMatch(result.html, /data-path="latest.docx" checked/);
  click();
  assert.equal(result.visible.length, 1);
  assert.equal(target.scrollTop, 120);
});

test('custom report names and different years do not collapse into each other', () => {
  const ctx = setup();
  const files = [report('a.docx', 1), report('b.docx', 2, '2025'), report('custom.docx', 3, '2026', '9月10日运营商业绩摘要（董事会用稿）.docx')];
  assert.equal(render(ctx, files).visible.length, 3);
});

test('weekly reports keep their existing ungrouped list', () => {
  const ctx = setup();
  const result = render(ctx, [report('a.docx', 1), report('b.docx', 2)], 'weekly');
  assert.equal(result.visible.length, 2);
  assert.doesNotMatch(result.html, /data-report-history/);
});

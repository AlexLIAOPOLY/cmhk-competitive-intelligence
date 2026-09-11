const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../web/static/app.js'), 'utf8');
const context = vm.createContext({ Intl });
for (const [first, next] of [
  ['compactChineseNumber', 'measureScrollingLabels'],
  ['renderDomainVisual', 'renderDomainCard'],
]) {
  const start = source.indexOf(`  function ${first}(`);
  const end = source.indexOf(`  function ${next}(`, start);
  assert.ok(start >= 0 && end > start);
  vm.runInContext(source.slice(start, end), context);
}
const render = (items, visual) => context.renderDomainVisual(
  { id: 'cloud' }, items, -1, { id: 'revenue', label: '云指标', visual },
);

test('cloud revenue columns pair scaled USD values with the scaled unit', () => {
  const items = [
    { name: 'AWS', value: 128725, unit: '百万美元' },
    { name: 'Azure', value: 106265, unit: '百万美元' },
  ];
  const original = JSON.stringify(items);
  const html = render(items, 'columns');
  assert.ok(html.includes('1,287.25<small>亿美元</small>'));
  assert.ok(html.includes('1,062.65<small>亿美元</small>'));
  assert.ok(!html.includes('百万美元'));
  assert.equal(JSON.stringify(items), original);
});

test('capital expenditure rows and columns preserve the same financial magnitude', () => {
  const items = [{ name: 'Google', value: 52535, unit: '百万美元' }];
  assert.ok(render(items, 'rows').includes('525.35'));
  assert.ok(render(items, 'rows').includes('亿美元'));
  assert.ok(render(items, 'columns').includes('525.35<small>亿美元</small>'));
});

test('column formatting keeps zero, negative signs, and non-scaled units', () => {
  const html = render([
    { name: 'Loss', value: -25, unit: '百万港元' },
    { name: 'Zero', value: 0, unit: '百万美元' },
    { name: 'ARPU', value: 26.46, unit: '美元/月' },
  ], 'columns');
  assert.ok(html.includes('-0.25<small>亿港元</small>'));
  assert.ok(html.includes('0<small>亿美元</small>'));
  assert.ok(html.includes('26.46<small>美元/月</small>'));
});

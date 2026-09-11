const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../web/static/workspace-tabs.js'), 'utf8');
const extract = (name, next) => source.slice(source.indexOf(`  function ${name}(`), source.indexOf(`  function ${next}(`));

test('card copy stays fixed across retries while numeric results can change', () => {
  const context = vm.createContext({});
  vm.runInContext(extract('newsLineageCardContent', 'globalSchedulerLineageModel'), context);
  for (const key of ['strategic','news-search','news-ai','news-dedupe','news-output','news-selection-agent','app-result','weekly-result','news-subscription','research-dispatch','research-hong-kong','research-merge','research-update','research-publish']) {
    const node = {key, research:key.startsWith('research-'), value:11, unit:'动态单位', note:'正常', health:{label:'已完成'}};
    const before = context.newsLineageCardContent(node);
    const after = context.newsLineageCardContent({...node, value:999999, unit:'异常单位', note:'恢复失败原因'.repeat(20000), health:{label:'恢复中'}});
    assert.equal(after.note, before.note);
    assert.equal(after.unit, before.unit);
    assert.equal(after.value, '999999');
    assert.equal(context.newsLineageCardContent({...node,value:'服务异常'.repeat(100)}).value, '—');
    assert.equal(context.newsLineageCardContent({...node,value:'已完成 11 次',cardValue:11}).value, '11');
  }
});

test('every node preview includes all 1562 records in an accessible scrolling region', () => {
  const context = vm.createContext({
    newsLineageFirstScreenModel: () => ({ input: '', action: '', output: '', previews: Array.from({length:1562}, (_,i) => ({title:`record-${i}`, detail:'Complete content'})) }),
    esc: String, number: String, renderNewsMonitoringKeywords: () => '',
  });
  vm.runInContext(extract('renderNewsLineageFirstScreen', 'companyAgentExecutionModel'), context);
  for (const key of ['strategic','news-search','news-ai','news-dedupe','news-output','news-selection-agent','app-result','weekly-result','previous-news','news-db-signal','main','fact-extract','agent','database-hub','database-local','database-international','database-cloud','database-mainland','insights']) {
    const html = context.renderNewsLineageFirstScreen(key);
    assert.equal((html.match(/<article>/g) || []).length, 1565);
    assert.ok(html.includes('record-1561'));
    assert.ok(html.includes('role="region" aria-label="实际对象预览列表" tabindex="0"'));
    assert.ok(!html.includes('首屏显示前'));
  }
});

test('empty preview remains honest and safely escaped', () => {
  const context = vm.createContext({ newsLineageFirstScreenModel: () => ({previews:[]}), esc: () => '', number: String });
  vm.runInContext(extract('renderNewsLineageFirstScreen', 'companyAgentExecutionModel'), context);
  assert.match(context.renderNewsLineageFirstScreen('agent'), /当前归档没有可展示的逐条对象/);
});

test('growing cards move lower neighbours and reflow is stable and reversible', () => {
  const node = (x,y,h) => ({dataset:{x:String(x),y:String(y)},offsetWidth:144,offsetHeight:h,style:{}});
  const top = node(360,460,200), bottom = node(360,600,120), parallel = node(660,500,178);
  const canvas = { dataset:{lineageWidth:'1850',lineageHeight:'755'}, style:{}, querySelectorAll:()=>[top,bottom,parallel], querySelector:()=>null };
  const context = vm.createContext({});
  vm.runInContext(extract('layoutNewsLineageCards','fitNewsLineageToViewport'),context);
  assert.equal(context.layoutNewsLineageCards(canvas),820);
  assert.equal(bottom.dataset.y,'676');
  assert.equal(parallel.dataset.y,'500');
  assert.equal(context.layoutNewsLineageCards(canvas),820);
  top.offsetHeight=120;
  assert.equal(context.layoutNewsLineageCards(canvas),755);
  assert.equal(bottom.dataset.y,'600');
});

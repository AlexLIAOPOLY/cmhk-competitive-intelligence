const assert = require('node:assert/strict');
const fs = require('node:fs');
global.window = {};
eval(fs.readFileSync('web/static/research-diagram.js', 'utf8'));
const {reportPeriod, matrixModel, build, detail, decisionPage} = window.CmhkResearchDiagram;
for (const [value, kind, year] of [['H1 2026','H1','2026'], ['1H2026','H1','2026'], ['2026年上半年','H1','2026'], ['2026 First Half','H1','2026'], ['H2 2025','H2','2025'], ['Q2 2026','Q2','2026'], ['FY2026/1Q','Q1','2026'], ['Q1 FY27 (three months to 30 June 2026)','Q1','2027'], ['FY2025','FY','2025']]) {
  assert.equal(reportPeriod({period:value}).kind, kind, value);
  assert.equal(reportPeriod({period:value}).year, year, value);
}
assert.equal(reportPeriod({period:'1H2026'}).key, reportPeriod({period:'H1 2026'}).key);
assert.equal(reportPeriod({period:'six months ended 28 February 2026'}).kind,'half');
assert.match(reportPeriod({period:'six months ended 28 February 2026'}).label,/2026-02-28/);
assert.equal(reportPeriod({}).key,'unknown');
assert.equal(reportPeriod({status:'no_update',latest_baseline:{period:'H1 2026'}}).kind,'H1');
assert.equal(reportPeriod({status:'error',latest_baseline:{period:'H1 2026'}}).key,'unknown');
assert.notEqual(reportPeriod({period:'FY2026'}).key,reportPeriod({period:'2026'}).key);
const task={key:'hong-kong',title:'香港运营商研究 Agent',purpose:'研究',companies:['HKT']};
const items = ['H1 2026','H2 2026'].map((period,index)=>({id:String(index),company:'HKT',metric:'收入',period,value:String(index+1),status:'verified',write_preflight:{status:'ready'}}));
const snapshot={date:'2026-09-10',plan:[task],run:{run_id:'period_test',status:'completed',research_policy:'latest_disclosure_incremental_v1',publication:{storage_readback:{items:[{company:'HKT',metric:'收入',period:'H1 2026',main_table:{status:'written',period:'H1 2026'}}]}}},agents:[{...task,reports:[{company:'HKT',metrics:['收入'],items}]}],result_items:items,accepted_items:items};
const model=build({nodes:[],edges:[]},snapshot,snapshot.date);
for (const key of ['research-hong-kong','research-merge','research-update','research-dispatch']) {
 const node=model.nodes.find(n=>n.key===key);
 const slices=matrixModel(node,snapshot,snapshot.date)[0].rows[0].cells[0].slices;
 assert.equal(slices.length,2,key);
 assert.equal(slices.find(s=>s.period.kind==='H1').label,'已入库',key);
 assert.equal(slices.find(s=>s.period.kind==='H2').label,'可入库',key);
 assert.equal(slices.find(s=>s.period.kind==='H2').receipts.length,0,key);
 const html=detail(node,snapshot,snapshot.date);
 assert.ok(html.includes('data-matrix-year') && html.includes('data-matrix-kind'));
 assert.equal((html.match(/data-matrix-period=/g)||[]).length,2);
}
const rows=items.map(item=>({dataset:{company:item.company,metric:item.metric,period:reportPeriod(item).key}}));
assert.deepEqual(decisionPage(rows,{company:'HKT',metric:'收入',period:reportPeriod(items[1]).key},0).visible,[rows[1]]);
console.log('Period aliases, fiscal intervals, unknown periods, per-period outcomes and exact navigation: PASS');

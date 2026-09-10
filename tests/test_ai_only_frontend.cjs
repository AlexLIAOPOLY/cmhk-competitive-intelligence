const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/static/app.js', 'utf8');
const extract = (name, next) => source.slice(source.indexOf(`  function ${name}(`), source.indexOf(`  function ${next}(`));
const context = vm.createContext({
  payload: {ai:{model_analysis_fresh:false}},
  insightRefreshState:new Map(), relationRefreshState:new Map(),
  safe:value=>String(value ?? '').replaceAll('<','&lt;').replaceAll('>','&gt;'),
  rail:{}, domainLabels:{local:'本地',cloud:'云'},
  patchElementList:(_rail, markup)=>context.markup=markup,
});
vm.runInContext(extract('renderEntityFocus','renderFocusTabs') + extract('renderRail','renderDomainVisual'), context);
const domain = {id:'local',title:'本地运营商',insight:'RULE DOMAIN'};
const focus = {id:'revenue',label:'收入',insight:'RULE FOCUS',headline:'RULE TITLE',ai_summary:{analysis:'OLD AI',headline:'OLD TITLE'}};
let html = context.renderEntityFocus(domain,null,0,focus,[]);
assert.ok(html.includes('AI 分析待生成'));
for (const forbidden of ['RULE DOMAIN','RULE FOCUS','RULE TITLE','OLD AI','OLD TITLE']) assert.ok(!html.includes(forbidden));
context.payload.ai.model_analysis_fresh=true;
html=context.renderEntityFocus(domain,null,0,focus,[]);
assert.ok(html.includes('OLD AI') && html.includes('OLD TITLE'));
assert.ok(!html.includes('RULE FOCUS'));
focus.ai_summary.origin='evidence_rule';
assert.ok(context.renderEntityFocus(domain,null,0,focus,[]).includes('AI 分析待生成'));
context.insightRefreshState.set('local:revenue',{status:'error',message:'模型校验失败'});
assert.ok(context.renderEntityFocus(domain,null,0,focus,[]).includes('模型校验失败'));
context.renderRail([]);
assert.ok(context.markup.includes('跨库 AI 分析待生成'));
assert.ok(!context.markup.includes('data-intelligence-relation-refresh'));
context.renderRail([{from:'local',to:'cloud',origin:'ai',title:'AI TITLE',detail:'AI DETAIL'}]);
assert.ok(context.markup.includes('AI TITLE') && context.markup.includes('AI 战略解读'));
console.log('AI-only overview: stale/template text excluded, real AI and pending/error states: PASS');

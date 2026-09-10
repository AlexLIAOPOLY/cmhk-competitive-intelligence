const assert = require('node:assert/strict');
const fs = require('node:fs');
global.window = {};
eval(fs.readFileSync('web/static/research-diagram.js', 'utf8'));
const records = ['ready', 'existing', 'duplicate', 'rejected'].map((state, i) => ({
  id: `${i}`, company: 'HKT', metric: `指标${i}`, period: 'H1 2026', value: i,
  status: state === 'ready' ? 'verified' : state === 'rejected' ? 'conflict' : 'no_update',
  write_preflight: {status: state, reason: `真实原因${i}<script>alert(1)</script>`, field: 'revenue', value: i, unit: 'millions HKD'}
}));
const snapshot = {date: '2026-09-10', plan: [{key: 'hong-kong', title: '香港运营商研究 Agent', companies: ['HKT'], purpose: '经营业绩'}],
  run: {run_id: 'research_test', research_policy: 'latest_disclosure_incremental_v1', status: 'partial', accepted: 1, tasks: 4, final_review: {status: 'completed'}, publication: {
    storage_readback: {ok: true, accepted: 1, written: 1, checked_at: 'now', items: [{company: 'HKT', metric: '收入', status: 'written', main_table: {
      status: 'written', subject: 'HKT / csl / 1O1O', path: 'agent_knowledge/quarterly_metrics.json', metric_key: 'revenue', period: 'H1 2026', candidate_value: 0, current_value: 0, unit: 'millions HKD', reason: '正式表数值和来源回读一致'
    }}]}}},
  agents: [{key: 'hong-kong', reports: [{company: 'HKT', metrics: ['收入', '用户数'], items: records}]}], result_items: records,
  final_reviewer: {reports: [{company: 'HKT', items: records}]}};
const renderer = window.CmhkResearchDiagram;
const model = renderer.build({nodes: [], edges: []}, snapshot, snapshot.date);
function detail(key) {return renderer.detail(model.nodes.find(n => n.key === key), snapshot, snapshot.date);}
const review = detail('research-merge');
for (const group of ['可入库', '库内已有 · 不提交', '本轮重复 · 不提交', '不可入库']) assert.ok(review.includes(group));
assert.ok(review.indexOf('终审入库判断') < review.indexOf('本节点结果'));
for (let i = 0; i < 4; i++) assert.ok(review.includes(`真实原因${i}`));
assert.ok(!review.includes('<script>alert'));
assert.ok(review.includes('&lt;script&gt;'));
assert.ok(detail('research-hong-kong').includes('本Agent指标与判断'));
assert.ok(detail('research-dispatch').includes('收入、用户数'));
const storage = detail('research-update');
for (const text of ['正式表入库结果', '已入库', '未入库', '<table>', '实际表文件', 'revenue', 'H1 2026', '<td>0', '正式表数值和来源回读一致']) assert.ok(storage.includes(text), text);
assert.ok(storage.indexOf('<table>') < storage.indexOf('本节点结果'));
assert.ok(!storage.includes('仅保存为资料'));
records[3].write_preflight.reason = 'budget_exceeded: raw diagnostic';
const readableFailure = detail('research-merge');
assert.ok(readableFailure.includes('模型服务额度不足'));
assert.ok(readableFailure.includes('原始判断记录：budget_exceeded: raw diagnostic'));
assert.ok(review.includes('data-research-filter="rejected"'));
assert.ok(review.includes('aria-label="搜索公司、指标或原因"'));
assert.ok(!review.includes('research-decision-grid'));
const list = Array.from({length: 43}, (_, i) => ({dataset: {search: `hkt 收入 ${i}`}}));
assert.equal(renderer.decisionPage(list, '', 0).visible.length, 20);
assert.equal(renderer.decisionPage(list, '', 2).visible.length, 3);
assert.equal(renderer.decisionPage(list, ' HKT ', 9).current, 2);
assert.equal(renderer.decisionPage(list, 'no match', 2).visible.length, 0);
assert.equal(renderer.decisionPage(list, 'no match', 2).current, 0);
console.log('Decision groups, first-section ordering, formal table/zero readback, dispatch and escaping: PASS');

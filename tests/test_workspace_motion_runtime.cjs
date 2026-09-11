const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../web/static/workspace-tabs.js'), 'utf8');

function harness({ storage = new Map(), user = 'viewer', hidden = false, brokenStorage = false, play, allowed = true } = {}) {
  const timers = new Map(), shown = [], signals = [], listeners = {};
  let timerId = 0;
  const document = { visibilityState: hidden ? 'hidden' : 'visible', addEventListener: (name, fn) => { listeners[name] = fn; } };
  const context = vm.createContext({
    console, document,
    window: {
      CMHKAuth: { user: { account: user } },
      localStorage: {
        getItem(key) { if (brokenStorage) throw new Error('storage denied'); return storage.get(key) || null; },
        setItem(key, value) { if (brokenStorage) throw new Error('storage denied'); storage.set(key, value); },
      },
      setTimeout: fn => { timers.set(++timerId, fn); return timerId; },
      clearTimeout: id => timers.delete(id),
    },
    can: () => allowed,
    number: value => String(value),
    markWorkspaceSignal: (...args) => signals.push(args),
    faultStatus: task => ({ key: task.incident_status === 'open' ? 'attention' : 'resolved' }),
    faultSeverity: task => ({ code: task.severity || 'P2', label: '高' }),
    faultCause: task => task.error || '发生异常',
    taskLabel: kind => kind,
    playWorkspaceMotion: async (event, onPresented) => { shown.push(event); onPresented(); if (play) await play(event); },
  });
  vm.runInContext(source.slice(source.indexOf('  const motionState ='), source.indexOf('  const wait =')), context);
  vm.runInContext(source.slice(source.indexOf('  function faultMotionStorageKey('), source.indexOf('  window.CMHKMotion =')), context);
  return {
    context, shown, storage, signals, timers,
    visible(value) { document.visibilityState = value ? 'visible' : 'hidden'; listeners.visibilitychange(); },
    async flush() { const entry = timers.entries().next().value; if (entry) { timers.delete(entry[0]); await entry[1](); } },
  };
}

const faults = (count, prefix = 'old') => Array.from({ length: count }, (_, i) => ({ incident_id: `${prefix}-${i}`, incident_status: 'open', title: `${prefix} ${i}` }));

test('500 initial faults produce one counted summary; refresh and stale baselines cannot replay them', async () => {
  const h = harness();
  const rows = faults(500);
  h.context.observeFaultSignals(rows, { baseline: true });
  assert.equal(h.storage.size, 0, 'not remembered before the popup is presented');
  assert.equal(h.timers.size, 1);
  await h.flush();
  assert.equal(h.shown.length, 1);
  assert.equal(h.shown[0].count, 500);
  assert.match(h.shown[0].detail, /500条报警/);
  h.context.observeFaultSignals([], { baseline: true });
  h.context.observeFaultSignals(rows);
  await h.flush();
  assert.equal(h.shown.length, 1);
  const reload = harness({ storage: h.storage });
  reload.context.observeFaultSignals(rows, { baseline: true });
  await reload.flush();
  assert.equal(reload.shown.length, 0);
  reload.context.observeFaultSignals([...faults(1, 'new'), ...rows]);
  await reload.flush();
  assert.equal(reload.shown.length, 1);
  assert.equal(reload.shown[0].title, 'new 0');
  assert.equal(rows[0].incident_status, 'open', 'popup history does not resolve faults');
});

test('hidden tasks and faults wait for visibility then appear as one mixed stack', async () => {
  const h = harness({ hidden: true });
  h.context.observeFaultSignals(faults(30));
  for (let i = 0; i < 20; i++) h.context.announceWorkspaceEvent({ kind: 'task', title: `task ${i}` });
  assert.equal(h.shown.length, 0);
  assert.equal(h.storage.size, 0);
  assert.equal(h.timers.size, 0);
  h.visible(true);
  await h.flush();
  assert.equal(h.shown.length, 1);
  assert.equal(h.shown[0].count, 50);
  assert.match(h.shown[0].detail, /30条报警 · 20项任务/);
  assert.equal(h.shown[0].kind, 'fault');
  assert(h.signals.some(([module]) => module === 'log'));
  assert(h.signals.some(([module]) => module === 'fault'));
});

test('new bursts while a popup plays become one pending summary, never a long replay queue', async () => {
  let finish;
  const h = harness({ play: () => new Promise(resolve => { finish = resolve; }) });
  h.context.announceWorkspaceEvent({ kind: 'task', title: 'first' });
  const active = h.flush();
  for (let i = 0; i < 80; i++) h.context.announceWorkspaceEvent({ kind: i % 2 ? 'subscription' : 'task' });
  assert.equal(h.shown.length, 1);
  assert.equal(h.timers.size, 0);
  finish(); await active;
  const pending = h.flush();
  assert.equal(h.shown.length, 2);
  assert.equal(h.shown[1].count, 80);
  finish(); await pending;
  assert.equal(h.timers.size, 0);
});

test('visibility change before debounce retains all events without prematurely remembering them', async () => {
  const h = harness();
  h.context.observeFaultSignals(faults(7));
  h.visible(false);
  await h.flush();
  assert.equal(h.shown.length, 0);
  assert.equal(h.storage.size, 0);
  h.visible(true); await h.flush();
  assert.equal(h.shown[0].count, 7);
});

test('storage is scoped to the viewer and unavailable storage still deduplicates within the page', async () => {
  const first = harness();
  first.context.observeFaultSignals(faults(4)); await first.flush();
  const other = harness({ user: 'another-viewer', storage: first.storage });
  other.context.observeFaultSignals(faults(4)); await other.flush();
  assert.equal(other.shown[0].count, 4);
  const restricted = harness({ brokenStorage: true });
  restricted.context.observeFaultSignals(faults(4)); await restricted.flush();
  restricted.context.observeFaultSignals(faults(4), { baseline: true }); await restricted.flush();
  assert.equal(restricted.shown.length, 1);
});

test('resolved faults are quiet and a tab presenting the same batch first suppresses duplicates', async () => {
  const h = harness(), other = harness({ storage: h.storage });
  const rows = faults(4);
  h.context.observeFaultSignals([...rows, { incident_id: 'resolved', incident_status: 'resolved' }]);
  other.context.observeFaultSignals(rows);
  await other.flush(); await h.flush();
  assert.equal(other.shown[0].count, 4);
  assert.equal(h.shown.length, 0);
  const denied = harness({ allowed: false });
  await denied.context.announceWorkspaceEvent({ kind: 'task' });
  assert.equal(denied.timers.size, 0);
});

test('initial and live card rendering share escaped actual status text', () => {
  const ctx = vm.createContext({ esc: value => String(value).replaceAll('<', '&lt;') });
  vm.runInContext(source.slice(source.indexOf('  function lineageStatusIcon('), source.indexOf('  function activeNewsStage(')), ctx);
  for (const [key, label] of [['healthy', '已启动'], ['running', '运行中'], ['warning', '已完成·含失败项'], ['critical', '失败']]) {
    const html = ctx.lineageHealthBadge({ key, label });
    assert(html.includes(`<span>${label}</span>`));
    assert(html.includes('<svg'));
  }
  assert(ctx.lineageHealthBadge({ label: '<img onerror=bad>' }).includes('&lt;img'));
  assert(ctx.lineageHealthBadge(null).includes('无记录'));
  assert.equal(source.split('lineageHealthBadge(node.health)').length - 1, 2);
});

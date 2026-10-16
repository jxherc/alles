import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/money.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
function harness(kind) {
  const nodes = new Map(), writes = [], toasts = [], refreshes = [];
  let acknowledge;
  const get = id => {
    if (!nodes.has(id)) nodes.set(id, { value: '', disabled: false, dataset: {}, setAttribute() {}, removeAttribute() {} });
    return nodes.get(id);
  };
  const ids = kind === 'budget' ? ['bf-cat', 'bf-amt'] : ['gl-name', 'gl-target', 'gl-current', 'gl-monthly'];
  ['groceries', '75.25', '5.25', '10'].slice(0, ids.length).forEach((value, index) => { get(ids[index]).value = value; });
  const context = vm.createContext({
    calendarDateKey: () => '2026-10-16', location: { search: '' }, URLSearchParams, fetch() {},
    document: { getElementById: get }, getDropdownValue: () => 'savings',
    toast: (message, type) => toasts.push({ message, type }),
    api: async (url, options) => { writes.push({ url, ...options }); return new Promise(resolve => { acknowledge = resolve; }); },
  });
  vm.runInContext(source + '\nload = async (_fetch, preserveDrafts) => refreshes.push(preserveDrafts); globalThis.subject = { addGoal, addBudget };', Object.assign(context, { refreshes }));
  return { get, ids, writes, toasts, refreshes, save: kind === 'budget' ? context.subject.addBudget : context.subject.addGoal,
    finish(value = { id: 'saved', ...writes[0].body }) { acknowledge(value); } };
}

for (const kind of ['budget', 'goal']) {
  test(`${kind} submits once while pending and keeps newer draft through refresh`, async () => {
    const h = harness(kind), button = h.get(kind === 'budget' ? 'bf-add' : 'gl-add');
    const first = h.save(); const repeated = h.save();
    assert.equal(h.writes.length, 1);
    assert.equal(button.disabled, true);
    h.get(h.ids[0]).value = 'newer 草稿';
    h.finish(); await first; await repeated;
    assert.equal(h.get(h.ids[0]).value, 'newer 草稿');
    assert.deepEqual(h.refreshes, [true]);
    assert.equal(button.disabled, false);
  });
  test(`${kind} malformed acknowledgment leaves all fields and avoids a false refresh`, async () => {
    const h = harness(kind); const save = h.save(); h.finish({}); await save;
    assert.equal(h.get(h.ids[0]).value, 'groceries');
    assert.equal(h.get(h.ids[1]).value, '75.25');
    assert.deepEqual(h.refreshes, []);
    assert.match(h.toasts.at(-1).message, /not confirmed/);
  });
  test(`${kind} confirmed unchanged input clears only its submitted fields`, async () => {
    const h = harness(kind); h.get('tx-payee').value = 'other draft';
    const save = h.save(); h.finish(); await save;
    for (const id of h.ids) assert.equal(h.get(id).value, '');
    assert.equal(h.get('tx-payee').value, 'other draft');
    assert.deepEqual(h.refreshes, [true]);
  });
}

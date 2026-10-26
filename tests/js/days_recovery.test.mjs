import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { t, tp } from '../../static/js/i18n.js';

const source = readFileSync(new URL('../../static/js/days.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
const response = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });
const event = { id: 'event-1', name: 'original countdown', date: '2026-11-01', target: '2026-11-01', repeat: 'none' };
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
const tick = () => new Promise(resolve => setImmediate(resolve));

function harness(fetcher = async () => response({ events: [event] })) {
  const nodes = new Map(), toasts = [], seen = { focused: '', confirm: async () => true };
  const node = key => {
    if (!nodes.has(key)) nodes.set(key, { value: '', dataset: {}, listeners: {}, disabled: false, isConnected: true,
      addEventListener(name, listener) { this.listeners[name] = listener; },
      setAttribute() {}, removeAttribute() {}, focus() { seen.focused = key; }, querySelectorAll: () => [] });
    return nodes.get(key);
  };
  node('day-name').value = 'original countdown';
  node('day-date').value = '2026-11-01';
  node('day-repeat').dataset.value = 'none';
  const fields = Object.fromEntries(['name', 'date', 'repeat', 'category', 'notes', 'notify_days']
    .map(name => [name, { value: event[name] ?? (name === 'notify_days' ? '-1' : '') }]));
  const buttons = ['save', 'del', 'pin', 'cancel', 'edit'].map(act => { const n = node(act); n.dataset.act = act; return n; });
  const card = { dataset: { id: event.id }, isConnected: true,
    querySelector: selector => fields[selector.match(/data-f="([^"]+)"/)?.[1]],
    querySelectorAll: selector => selector === '[data-act]' ? buttons : [] };
  const grid = { querySelectorAll: selector => selector === '.day-card' ? [card] : [], querySelector: () => null };
  const context = vm.createContext({
    fetch: (...args) => fetcher(...args), window: {}, CSS: { escape: String },
    document: { getElementById: node, activeElement: null },
    toast: (...args) => toasts.push(args), plainError: message => String(message), dlgConfirm: (...args) => seen.confirm(...args),
    initCustomDropdown() {}, initDatePicker() {}, formatDate() {}, formatNumber: String, t, tp,
  });
  vm.runInContext(source + `
    _render = () => {};
    globalThis.subject = { add: _add, loadDays, wire: grid => _wire(grid),
      seed: events => { _events = events; _editing = 'event-1'; },
      state: () => ({ events: _events, editing: _editing }) };
  `, context);
  context.subject.seed([{ ...event }]); context.subject.wire(grid);
  return { ...context.subject, node, fields, toasts, seen };
}

test('pending countdown add submits once and keeps newer name and category', async () => {
  const held = deferred(); let writes = 0;
  const h = harness(async (path, options) => {
    if (!options) return response({ events: [event] });
    writes++; return held.promise;
  });
  const first = h.add(); const repeat = h.add();
  assert.equal(writes, 1); assert.equal(h.node('day-add-btn').disabled, true);
  h.node('day-name').value = 'newer exact name'; h.node('day-category').value = 'newer category';
  held.resolve(response(event)); await first; await repeat;
  assert.equal(h.node('day-name').value, 'newer exact name');
  assert.equal(h.node('day-category').value, 'newer category');
  assert.equal(h.node('day-add-btn').disabled, false);
});

test('unconfirmed countdown create keeps the exact draft and reports an error', async () => {
  for (const payload of [{}, { ...event, name: 'wrong countdown' }]) {
    const h = harness(async () => response(payload));
    await h.add();
    assert.equal(h.node('day-name').value, 'original countdown');
    assert.equal(h.toasts.at(-1)[1], 'error');
  }
});

test('failed and malformed countdown lists preserve loaded records', async () => {
  const h = harness();
  for (const reply of [response({ detail: 'unavailable' }, 503), response({}), response({ events: {} })]) {
    await h.loadDays(async () => reply);
    assert.equal(h.state().events[0].id, 'event-1');
  }
});

test('late countdown list cannot replace a newer navigation read', async () => {
  const held = deferred(); const h = harness();
  const old = h.loadDays(async () => held.promise);
  await h.loadDays(async () => response({ events: [{ ...event, id: 'newer' }] }));
  held.resolve(response({ events: [event] })); await old;
  assert.equal(h.state().events[0].id, 'newer');
});

test('unconfirmed deletion retains countdown and enables deliberate retry', async () => {
  for (const reply of [response({ detail: 'delete unavailable' }, 503), response({})]) {
    const h = harness(async (path, options) => options ? reply : response({ events: [event] }));
    await h.node('del').listeners.click();
    assert.equal(h.state().events[0].id, 'event-1');
    assert.equal(h.toasts.at(-1)[1], 'error');
    assert.equal(h.node('del').disabled, false);
  }
});

test('a saved edit does not close a newer edit typed while waiting', async () => {
  const held = deferred(); let writes = 0;
  const h = harness(async (path, options) => {
    if (!options) return response({ events: [event] });
    writes++; return held.promise;
  });
  const first = h.node('save').listeners.click(); await tick();
  const repeat = h.node('save').listeners.click();
  h.fields.name.value = 'newer unsaved edit';
  held.resolve(response(event)); await first; await repeat;
  assert.equal(writes, 1);
  assert.equal(h.state().editing, 'event-1');
  assert.equal(h.fields.name.value, 'newer unsaved edit');
});

test('delete asks before going busy, so a cancelled confirm hands focus back to the ×', async () => {
  let writes = 0;
  const h = harness(async (path, options) => { if (options) writes++; return response({ events: [event] }); });
  h.seen.confirm = async () => { assert.equal(h.node('del').disabled, false, 'the × is still usable while asking'); return false; };
  await h.node('del').listeners.click();
  assert.equal(writes, 0);
  assert.equal(h.seen.focused, 'del');
});

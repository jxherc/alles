import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { plainError } from '../../static/js/util.js';
import { t, tp } from '../../static/js/i18n.js';

const source = readFileSync(new URL('../../static/js/calendar.js', import.meta.url), 'utf8');
const actual = name => source.match(new RegExp(`^(?:async )?function ${name}\\([^]*?^}`, 'm'))[0];
const response = (body, ok = true) => ({ ok, status: ok ? 200 : 503, json: async () => body });
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
const settle = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };

function harness() {
  const nodes = new Map(), requests = [], toasts = [], overlays = [], created = [];
  const state = { reloads: 0, editor: false, pickerCount: 0, handler: () => response({}), prompts: ['60', 'Synthetic booking'] };
  function node(id = '') {
    const element = { id, value: '', textContent: '', innerHTML: '', dataset: {}, files: [], disabled: false,
      isConnected: true, listeners: {}, classList: { contains: () => false },
      setAttribute() {}, removeAttribute() {}, focus() { document.activeElement = this; }, scrollIntoView() {},
      click() { if (this.id === 'cal-import-file' && !this.disabled) state.pickerCount++; },
      addEventListener(type, callback) { this.listeners[type] = callback; },
      querySelectorAll() { return []; },
      remove() { this.isConnected = false; },
      appendChild(child) { this.children ??= []; this.children.push(child); },
      append(...children) { children.forEach(child => this.appendChild(child)); },
      after() {},
    };
    created.push(element); return element;
  }
  const document = {
    activeElement: null,
    getElementById: id => nodes.get(id) || created.find(element => element.id === id && element.isConnected) || null,
    querySelector: selector => selector === '.cal-editor' && state.editor ? {} : null,
    createElement() {
      const el = node();
      const slot = node(); slot.dataset = { s: '2026-10-16T09:00', e: '2026-10-16T10:00' };
      el.querySelectorAll = selector => selector === '[data-s]' ? [slot] : [];
      el.querySelector = selector => selector === '.cal-scope' ? el : null;
      el.slot = slot;
      return el;
    },
    body: { appendChild: el => overlays.push(el) },
  };
  const context = vm.createContext({ document, nodes, state, Date, Number,
    fetch: async (url, options = {}) => { requests.push({ url, ...options }); return state.handler(url, options); },
    toast: (message, type) => toasts.push({ message, type }), plainError, zoneHeader: () => ({ 'x-alles-time-zone': 'UTC' }),
    withZone: (init = {}) => ({ ...init, headers: { ...(init.headers || {}), 'x-alles-time-zone': 'UTC' } }),
    tr: t, trp: tp, esc: value => String(value),
    dlgPrompt: async (_message, initial) => state.prompts.length ? state.prompts.shift() : initial,
    ymd: () => '2026-10-16', localISO: date => `2026-10-16T${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`,
    loadCalendar: async (_fetcher, canReplace = () => true) => {
      state.reloads++; if (canReplace()) state.editor = false;
    },
  });
  vm.runInContext(`let _editing = null, _cursor = new Date();
    ${source.match(/^const RSVP_LABEL[^]*?\|\| status;$/m)[0]}
    ${['readCalendarResponse', 'sameStoredTime', 'saveCalendarRequest', 'renderAttendees', 'renderInviteSuggestions', 'findTime'].map(actual).join('\n')}
    globalThis.findTime = findTime; globalThis.renderAttendees = renderAttendees;
  `, context);
  function editor(id) {
    for (const old of nodes.values()) old.isConnected = false;
    for (const key of ['cal-inv-name', 'cal-inv-email', 'cal-inv-btn', 'cal-invites', 'cal-inv-suggest']) nodes.set(key, node(key));
    state.editor = true;
    context.event = { id };
    vm.runInContext('_editing = event;', context);
    const start = source.indexOf('  // 8b — invites + rsvp (existing events only)');
    const end = source.indexOf('\n}\n\nconst RSVP_LABEL', start);
    vm.runInContext(`{ const event = globalThis.event; ${source.slice(start, end)} }`, context);
  }
  function importControls() {
    nodes.set('cal-import', node('cal-import'));
    nodes.set('cal-import-file', node('cal-import-file'));
    nodes.set('cal-quick-feedback', node('cal-quick-feedback'));
    const start = source.indexOf("  const imp = document.getElementById('cal-import');");
    const end = source.indexOf('\n}\n\nfunction _syncViewBtns', start);
    vm.runInContext(`{ ${source.slice(start, end)} }`, context);
  }
  return { context, document, nodes, state, requests, toasts, overlays, editor, importControls };
}

function invites(h, postResponse) {
  h.state.handler = (url, options) => {
    if (options.method === 'POST') return postResponse(url, JSON.parse(options.body));
    if (url.endsWith('/attendees')) return response([{ id: url.split('/')[3] + '-existing', name: 'existing', status: 'invited' }]);
    return response({ suggestions: [] });
  };
}

test('late Invite(A) cannot clear B inputs, repaint B attendees, or start A reads', async () => {
  const h = harness(), gate = deferred(); invites(h, () => gate.promise);
  h.editor('A'); await settle();
  h.nodes.get('cal-inv-name').value = 'A pending'; h.nodes.get('cal-inv-email').value = 'a@example.invalid';
  const pending = h.nodes.get('cal-inv-btn').listeners.click();
  h.editor('B'); await settle();
  h.nodes.get('cal-inv-name').value = 'B draft'; h.nodes.get('cal-inv-email').value = 'b@example.invalid';
  const before = h.nodes.get('cal-invites').innerHTML, count = h.requests.length;
  gate.resolve(response({ id: 'A-added', event_id: 'A', name: 'A pending', email: 'a@example.invalid', status: 'invited' }));
  await pending; await settle();
  assert.equal(h.nodes.get('cal-inv-name').value, 'B draft');
  assert.equal(h.nodes.get('cal-inv-email').value, 'b@example.invalid');
  assert.equal(h.nodes.get('cal-invites').innerHTML, before);
  assert.equal(h.requests.length, count, 'stale completion starts no current action');
});

test('pending invite is single-flight and retains newer fields in the same editor', async () => {
  const h = harness(), gate = deferred(); invites(h, () => gate.promise);
  h.editor('A'); await settle();
  h.nodes.get('cal-inv-name').value = 'first'; h.nodes.get('cal-inv-email').value = 'first@example.invalid';
  const button = h.nodes.get('cal-inv-btn'), pending = button.listeners.click();
  h.nodes.get('cal-inv-name').value = 'next'; h.nodes.get('cal-inv-email').value = 'next@example.invalid';
  const duplicate = button.listeners.click();
  gate.resolve(response({ id: 'added', event_id: 'A', name: 'first', email: 'first@example.invalid', status: 'invited' }));
  await Promise.all([pending, duplicate]);
  assert.equal(h.requests.filter(r => r.method === 'POST').length, 1);
  assert.equal(h.nodes.get('cal-inv-name').value, 'next');
  assert.equal(h.nodes.get('cal-inv-email').value, 'next@example.invalid');
  assert.equal(button.disabled, false);
});

for (const [label, result] of [['503', response({ detail: 'synthetic refusal' }, false)], ['malformed', response({ ok: true })]]) {
  test(`invite ${label} retains inputs without refreshing attendees`, async () => {
    const h = harness(); invites(h, () => result); h.editor('A'); await settle();
    h.nodes.get('cal-inv-name').value = 'retain'; h.nodes.get('cal-inv-email').value = 'retain@example.invalid';
    const count = h.requests.length; await h.nodes.get('cal-inv-btn').listeners.click();
    assert.equal(h.nodes.get('cal-inv-name').value, 'retain');
    assert.equal(h.nodes.get('cal-inv-email').value, 'retain@example.invalid');
    assert.equal(h.requests.length, count + 1);
    assert.equal(h.toasts.at(-1)?.type, 'error');
  });

  test(`import ${label} preserves selected file and reports failure`, async () => {
    const h = harness(); h.importControls(); h.state.handler = () => result;
    const file = h.nodes.get('cal-import-file'); file.files = [{ text: async () => 'synthetic ics' }]; file.value = 'fixture.ics';
    await file.listeners.change({ target: file });
    assert.equal(file.value, 'fixture.ics'); assert.equal(h.state.reloads, 0);
    assert.equal(h.toasts.some(toast => toast.type === 'success'), false);
    assert.equal(h.document.getElementById('cal-import-feedback').hidden, false);
    assert.match(h.document.getElementById('cal-import-status').textContent, /wasn't confirmed.*check the calendar/);
  });

  test(`free-slot booking ${label} retains overlay and title without claiming success`, async () => {
    const h = harness(); h.state.handler = (_url, options) => options.method === 'POST' ? result : response({ slots: [{ start: '2026-10-16T09:00', end: '2026-10-16T10:00' }] });
    await h.context.findTime(); const overlay = h.overlays[0]; await overlay.slot.listeners.click();
    assert.equal(overlay.isConnected, true); assert.equal(h.state.reloads, 0);
    assert.equal(h.toasts.some(t => t.type === 'success'), false);
    h.context.dlgPrompt = async (_message, initial) => { assert.equal(initial, 'Synthetic booking'); return null; };
    await overlay.slot.listeners.click();
  });
}

test('confirmed import refreshes events without replacing an open draft', async () => {
  const h = harness(); h.importControls(); h.state.editor = true; h.state.handler = () => response({ imported: 2 });
  const file = h.nodes.get('cal-import-file'); file.files = [{ text: async () => 'synthetic ics' }]; file.value = 'fixture.ics';
  await file.listeners.change({ target: file });
  assert.equal(file.value, ''); assert.equal(h.state.reloads, 1); assert.equal(h.state.editor, true);
  assert.equal(h.toasts.at(-1)?.type, 'success');
});

test('late attendee read cannot start suggestions for a replacement editor', async () => {
  const h = harness(), gate = deferred();
  h.state.handler = url => url === '/api/calendar/A/attendees' ? gate.promise : response(url.endsWith('/attendees') ? [] : { suggestions: [] });
  h.editor('A'); h.editor('B'); await settle(); const count = h.requests.length;
  gate.resolve(response([])); await settle();
  assert.equal(h.requests.length, count);
});

test('late rejected invite stays silent after the editor is replaced', async () => {
  const h = harness(), gate = deferred(); invites(h, () => gate.promise);
  h.editor('A'); await settle(); h.nodes.get('cal-inv-name').value = 'first';
  const pending = h.nodes.get('cal-inv-btn').listeners.click();
  h.editor('A'); await settle(); h.nodes.get('cal-inv-name').value = 'reopened draft';
  gate.resolve(response({ detail: 'old failure' }, false)); await pending;
  assert.equal(h.toasts.length, 0); assert.equal(h.nodes.get('cal-inv-name').value, 'reopened draft');
  assert.equal(h.nodes.get('cal-inv-btn').disabled, false);
});

test('confirmed booking preserves a newer editor draft', async () => {
  const h = harness(), gate = deferred();
  h.state.handler = (_url, options) => options.method === 'POST' ? gate.promise : response({ slots: [{ start: '2026-10-16T09:00', end: '2026-10-16T10:00' }] });
  await h.context.findTime(); const overlay = h.overlays[0], pending = overlay.slot.listeners.click(); await settle();
  h.state.editor = true;
  await overlay.slot.listeners.click();
  assert.equal(h.requests.filter(r => r.method === 'POST').length, 1);
  gate.resolve(response({ id: 'booked', title: 'Synthetic booking', start_dt: '2026-10-16T09:00', end_dt: '2026-10-16T10:00', description: '' }));
  await pending;
  assert.equal(h.state.editor, true); assert.equal(h.state.reloads, 1);
  assert.equal(overlay.isConnected, false); assert.equal(h.toasts.at(-1)?.type, 'success');
});

test('closed booking overlay ignores its late successful response', async () => {
  const h = harness(), gate = deferred();
  h.state.handler = (_url, options) => options.method === 'POST' ? gate.promise : response({ slots: [{ start: '2026-10-16T09:00', end: '2026-10-16T10:00' }] });
  await h.context.findTime(); const overlay = h.overlays[0], pending = overlay.slot.listeners.click(); await settle();
  overlay.remove(); h.state.editor = true;
  gate.resolve(response({ id: 'booked', title: 'Synthetic booking', start_dt: '2026-10-16T09:00', end_dt: '2026-10-16T10:00', description: '' }));
  await pending;
  assert.equal(h.state.reloads, 0); assert.equal(h.toasts.length, 0); assert.equal(h.state.editor, true);
});

test('repeated import activation sends one request and allows explicit retry after rejection', async () => {
  const h = harness(), gate = deferred(); h.importControls(); h.state.handler = () => gate.promise;
  const file = h.nodes.get('cal-import-file'); file.files = [{ text: async () => 'synthetic ics' }]; file.value = 'fixture.ics';
  const pending = file.listeners.change(); await settle(); await h.nodes.get('cal-import').listeners.click();
  assert.equal(h.requests.length, 1);
  gate.resolve(response({ detail: 'synthetic refusal' }, false)); await pending;
  assert.equal(h.nodes.get('cal-import').disabled, false); assert.equal(file.disabled, false);
  h.state.handler = () => response({ imported: 1 });
  await h.document.getElementById('cal-import-retry').listeners.click();
  assert.equal(h.requests.length, 2); assert.equal(file.value, '');
});

test('Import after refusal opens a replacement picker without resending the retained file', async () => {
  const h = harness(); h.importControls(); h.state.handler = () => response({ detail: 'refused file A' }, false);
  const input = h.nodes.get('cal-import-file');
  input.files = [{ name: 'A.ics', text: async () => 'first file A' }]; input.value = 'A.ics';
  await input.listeners.change();
  await h.nodes.get('cal-import').listeners.click();
  assert.equal(h.state.pickerCount, 1, 'normal Import must remain a usable file chooser');
  assert.equal(h.requests.length, 1, 'opening the picker must not resend A');
  input.files = [{ name: 'B.ics', text: async () => 'replacement file B' }]; input.value = 'B.ics';
  h.state.handler = () => response({ imported: 1 });
  await input.listeners.change();
  assert.deepEqual(h.requests.map(request => JSON.parse(request.body).ics), ['first file A', 'replacement file B']);
});

test('refused import exposes separate retained-file retry and replacement actions', async () => {
  const h = harness(); h.importControls(); h.state.handler = () => response({ detail: 'refused' }, false);
  const input = h.nodes.get('cal-import-file');
  input.files = [{ name: 'A.ics', text: async () => 'first file A' }]; input.value = 'A.ics';
  await input.listeners.change();
  const retry = h.document.getElementById('cal-import-retry');
  const choose = h.document.getElementById('cal-import-choose');
  assert.ok(retry && choose, 'both recovery actions must be visible product controls');
  await choose.listeners.click(); assert.equal(h.state.pickerCount, 1); assert.equal(h.requests.length, 1);
  input.files = []; // Canceling a replacement picker must not lose the retained File.
  await input.listeners.change(); assert.equal(h.requests.length, 1);
  h.state.handler = () => response({ imported: 1 });
  retry.focus(); await retry.listeners.click();
  assert.deepEqual(h.requests.map(request => JSON.parse(request.body).ics), ['first file A', 'first file A']);
  assert.equal(h.document.getElementById('cal-import-feedback').hidden, true);
  assert.equal(h.document.activeElement, h.nodes.get('cal-import'));
});

for (const [detail, expected] of [
  ['choose a complete .ics calendar file', /“bad\.ics” isn't a calendar file alles can read/],
  // a real .ics with one broken event is refused too; that's not "not a calendar"
  ["an event in this file is incomplete or has a date that doesn't exist. nothing was imported",
    /couldn't import “bad\.ics”\. an event in this file is incomplete/],
]) {
  test(`import 400 tells the server's reason: ${detail.slice(0, 24)}`, async () => {
    const h = harness(); h.importControls();
    h.state.handler = () => ({ ok: false, status: 400, json: async () => ({ detail }) });
    const file = h.nodes.get('cal-import-file'); file.files = [{ name: 'bad.ics', text: async () => 'synthetic ics' }];
    await file.listeners.change({ target: file });
    assert.equal(h.document.getElementById('cal-import-feedback').hidden, false);
    assert.match(h.document.getElementById('cal-import-status').textContent, expected);
  });
}

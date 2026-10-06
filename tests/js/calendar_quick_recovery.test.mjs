import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { isDeepStrictEqual } from 'node:util';

const source = readFileSync(new URL('../../static/js/calendar.js', import.meta.url), 'utf8');
const html = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
const copy = value => JSON.parse(JSON.stringify(value));
const response = (data, ok = true, status = ok ? 200 : 503) => ({ ok, status, json: async () => copy(data) });
function deferred() { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; }
function actual(name) {
  const body = source.match(new RegExp(`^(?:export )?(?:async )?function ${name}\\([^]*?^}`, 'm'))?.[0];
  assert.ok(body, `exercise maintained ${name}`);
  return body.replace(/^export /, '');
}
const quickStart = source.indexOf("  const quick = document.getElementById('cal-quick');");
const quickEnd = source.indexOf("  const imp = document.getElementById('cal-import');", quickStart);
assert.ok(quickStart >= 0 && quickEnd > quickStart);
const quickBindings = source.slice(quickStart, quickEnd);
const event = id => ({ id, calendar_id: 'owned-calendar', title: id, description: 'saved description',
  source: {}, location: '', guests: '', start_dt: '2026-10-07T13:00', end_dt: null, all_day: false,
  color: '', reminders: [], recurrence: '', recur_interval: 1, recur_byday: '', recur_count: null,
  recur_until: null, recur_except: [], meeting_url: '', created_at: '2026-10-06T12:00:00' });

function harness() {
  const nodes = new Map(), requests = [], records = new Map(), errors = [], opens = [];
  const state = { editor: false, confirm: true, postGate: null, listGate: null,
    postError: false, listError: false, malformed: false, deleteGate: null, lostDeleteAck: false,
    occurrenceValid: true, renders: 0, pickerRefreshes: 0 };
  const document = { activeElement: null, getElementById: id => nodes.get(id) || null,
    querySelector: selector => selector === '.cal-editor' && state.editor ? editor : null };
  function node(id) {
    const value = { id, value: '', hidden: false, readOnly: false, textContent: '', attributes: {}, listeners: {},
      selectionStart: 0, selectionEnd: 0,
      setAttribute(key, text) { this.attributes[key] = text; },
      addEventListener(kind, listener) { this.listeners[kind] = listener; },
      focus() { document.activeElement = this; },
    };
    nodes.set(id, value); return value;
  }
  for (const id of ['cal-quick', 'cal-quick-feedback', 'cal-quick-status', 'cal-title', 'cal-desc', 'retry', 'elsewhere']) node(id);
  nodes.get('cal-quick-feedback').hidden = true;
  if (html.includes('id="cal-quick-undo"')) node('cal-quick-undo').hidden = true;
  const editor = { remove() { state.editor = false; } };
  const fetcher = async (url, options = {}) => {
    const method = options.method || 'GET'; requests.push({ url, method, body: options.body, headers: options.headers });
    if (url === '/api/calendar/quick' && method === 'POST') {
      if (state.postError) return response({ detail: 'synthetic create failure' }, false);
      const saved = event('created-' + (records.size + 1));
      saved.title = JSON.parse(options.body).text;
      records.set(saved.id, copy(saved));
      const receipt = copy(saved);
      if (state.postGate) await state.postGate.promise;
      return response(state.malformed ? { title: saved.title } : receipt);
    }
    if (method === 'DELETE') {
      if (state.deleteGate) await state.deleteGate.promise;
      const id = decodeURIComponent(url.slice('/api/calendar/'.length).split('?')[0]);
      if (!records.has(id)) return response({ detail: 'not found' }, false, 404);
      if (options.body && !isDeepStrictEqual(JSON.parse(options.body), records.get(id))) {
        return response({ detail: 'newer saved event retained' }, false, 409);
      }
      records.delete(id);
      return response(state.lostDeleteAck ? {} : { ok: true });
    }
    if (url === '/api/calendar') {
      const snapshot = [...records.values()].map(copy);
      if (state.listGate) await state.listGate.promise;
      return response(state.listError ? { detail: 'synthetic list failure' } : snapshot, !state.listError);
    }
    if (url === '/api/settings') return response({});
    if (['/api/calendars', '/api/calendar/tasks', '/api/calendar/subscriptions', '/api/calendar/birthdays'].includes(url)) return response([]);
    throw new Error('unexpected synthetic request: ' + method + ' ' + url);
  };
  const context = vm.createContext({ document, window: {}, fetch: fetcher, Date, URLSearchParams,
    localStorage: { getItem: () => null }, nodes, state, opens,
    tr: (key, values = {}) => key + (values.title ? ':' + values.title : ''),
    dlgConfirm: async () => state.confirm, calendarPlacementDate: value => new Date(value),
    _bindNav() {}, _tickWorldClock() {}, resolveCalendarWeekStart: () => 1, _syncViewBtns() {},
    renderSidebar() {}, refreshCalendarPicker() { state.pickerRefreshes++; }, calendarMetadataNotice() {},
    render() { state.renders++; state.editor = false; }, calendarLoadError: message => errors.push(message),
    editorBusy() {}, editorError: message => errors.push(message), chooseScope: async () => 'all',
    hasOccurrence: () => state.occurrenceValid,
  });
  vm.runInContext(`
    let _saving = false, _readDraft = null, _draftSnapshot = '', _cursor = new Date();
    let _events = [], _eventsReady = true, _editing = null, _editOcc = null;
    let _preserveEditorOnRetry = false, _loadSequence = 0, _tasks, _subs, _birthdays;
    let _weekStart, _workStart, _workEnd, _secondaryTz, _viewBooted = true, _view, _lastDefaultView;
    let _calendars = [], _calendarMetadataError = '';
    function openEditor(ev, _day, _time, _allDay, occ) {
      opens.push([ev.id, occ]); state.editor = true; _editing = ev; _editOcc = occ || null;
      nodes.get('cal-title').value = ev.title; nodes.get('cal-desc').value = ev.description;
      _readDraft = () => JSON.stringify([nodes.get('cal-title').value, nodes.get('cal-desc').value]);
      _draftSnapshot = _readDraft();
    }
    ${['readCalendarResponse', 'loadCalendar', 'retryCalendarView', 'openEvent', 'deleteEvent'].map(actual).join('\n')}
    ${quickBindings}
    globalThis.subject = { load: loadCalendar, retry: retryCalendarView, open: openEvent, remove: deleteEvent,
      seed: events => { _events = events; _eventsReady = true; },
      saving: value => { _saving = value; }, ready: value => { _eventsReady = value; },
      state: () => ({ editing: _editing?.id, occurrence: _editOcc, preserving: _preserveEditorOnRetry,
        saving: _saving, draft: _readDraft?.(), snapshot: _draftSnapshot }) };
  `, context);
  const subject = context.subject;
  context.window._navigateTo = async (view, options) => {
    assert.equal(view, 'calendar'); assert.equal(options.preserveRecord, true);
    if (!(await subject.load())) return false;
    const current = subject.state();
    return subject.open(current.editing, current.occurrence);
  };
  return { ...subject, current: subject.state, nodes, document, state, records, requests, errors, opens,
    snapshot: () => copy({ ...subject.state(), title: nodes.get('cal-title').value,
      description: nodes.get('cal-desc').value, active: document.activeElement?.id,
      selection: [nodes.get('cal-desc').selectionStart, nodes.get('cal-desc').selectionEnd] }),
    enter: (text = 'synthetic lunch tomorrow 1pm', overrides = {}) => {
      nodes.get('cal-quick').value = text;
      return nodes.get('cal-quick').listeners.keydown({ key: 'Enter', isComposing: false, preventDefault() {}, ...overrides });
    },
    clickAvailableUndo: async () => {
      const undo = nodes.get('cal-quick-undo');
      if (undo && !undo.hidden && undo.attributes['aria-disabled'] !== 'true') {
        undo.focus(); await undo.listeners.click(); return true;
      }
      return false;
    },
    edit: (ev = event('linked'), occurrence = null) => {
      records.set(ev.id, copy(ev)); subject.seed([...records.values()].map(copy));
      return subject.open(ev.id, occurrence);
    },
  };
}

for (const timing of ['after creation', 'before the creation acknowledgment']) {
  test(`quick-add cannot undo a newer saved edit ${timing}`, async () => {
    const h = harness();
    if (timing.startsWith('before')) h.state.postGate = deferred();
    const pending = h.enter();
    if (h.state.postGate) await Promise.resolve();
    else await pending;
    assert.equal(h.records.size, 1);
    const [id, first] = [...h.records][0];
    const newer = { ...first, title: 'newer saved title', description: 'newer saved description', start_dt: '2026-10-08T14:30' };
    h.records.set(id, copy(newer));
    if (h.state.postGate) { h.state.postGate.resolve(); await pending; }
    const available = await h.clickAvailableUndo();
    assert.deepEqual(h.records.get(id), newer, 'the newer saved event must remain intact');
    assert.equal(available, true, 'keep the accepted quick-undo action');
    const deletes = h.requests.filter(request => request.method === 'DELETE');
    assert.equal(deletes.length, 1);
    assert.equal(deletes[0].headers['content-type'], 'application/json');
    assert.deepEqual(JSON.parse(deletes[0].body), first, 'send the original whole receipt, never the refreshed event');
    assert.equal(h.nodes.get('cal-quick-status').textContent, 'calendar.quick_undo_failed:' + first.title);
    assert.equal(h.nodes.get('cal-quick-undo').hidden, false);
    assert.equal(h.nodes.get('cal-quick-undo').attributes['aria-disabled'], 'false');
  });
}

test('quick-add keeps its confirmed status, busy guard and single pending create', async () => {
  const h = harness(); h.state.postGate = deferred();
  const pending = h.enter(); await Promise.resolve();
  assert.equal(h.nodes.get('cal-quick').readOnly, true);
  await h.enter(); assert.equal(h.requests.filter(r => r.method === 'POST').length, 1);
  h.state.postGate.resolve(); await pending;
  assert.equal(h.nodes.get('cal-quick').value, '');
  assert.equal(h.nodes.get('cal-quick').attributes['aria-busy'], 'false');
  assert.equal(h.nodes.get('cal-quick-status').textContent, 'calendar.added:synthetic lunch tomorrow 1pm');
  assert.equal(h.records.size, 1); assert.equal(h.errors.length, 0);
  assert.equal(h.nodes.get('cal-quick-undo').hidden, false);
});

test('quick-add ignores composition, non-Enter, blank input and an editor save', async () => {
  const h = harness();
  await h.enter('text', { isComposing: true }); await h.enter('text', { key: 'x' }); await h.enter('  ');
  h.saving(true); await h.enter(); assert.equal(h.requests.length, 0);
});

test('canceling replacement preserves the unsaved editor and quick text', async () => {
  const h = harness(); h.edit(); h.nodes.get('cal-desc').value = 'newer unsaved draft';
  h.nodes.get('cal-desc').focus(); h.state.confirm = false; const before = h.snapshot();
  await h.enter('keep quick text');
  assert.deepEqual(h.snapshot(), before); assert.equal(h.nodes.get('cal-quick').value, 'keep quick text');
  assert.equal(h.requests.length, 0); assert.equal(h.nodes.get('cal-quick').readOnly, false);
});

test('an editor changed during quick-add keeps its newer draft and focus', async () => {
  const h = harness(); h.edit(); h.state.postGate = deferred(); const pending = h.enter();
  await Promise.resolve(); h.nodes.get('cal-desc').value = 'typed while create pending'; h.nodes.get('cal-desc').focus();
  const before = h.snapshot(); h.state.postGate.resolve(); await pending;
  assert.deepEqual(h.snapshot(), before); assert.equal(h.state.pickerRefreshes, 1); assert.equal(h.state.renders, 0);
});

for (const kind of ['postError', 'malformed']) {
  test(`${kind} retains quick input without claiming success`, async () => {
    const h = harness(); h.state[kind] = true; await h.enter('  retain this text  ');
    assert.equal(h.nodes.get('cal-quick').value, '  retain this text  ');
    assert.equal(h.nodes.get('cal-quick-status').textContent, 'calendar.quick_unconfirmed');
    assert.equal(h.nodes.get('cal-quick').readOnly, false);
  });
}

test('a failed list refresh preserves the successful create and exposes its existing error', async () => {
  const h = harness(); h.state.listError = true; await h.enter();
  assert.equal(h.records.size, 1); assert.equal(h.errors.length, 1);
  assert.match(h.nodes.get('cal-quick-status').textContent, /^calendar.added:/);
});

test('linked retry keeps newer description focus, selection and unsaved text', async () => {
  const h = harness(); h.edit(); h.state.listGate = deferred(); h.nodes.get('retry').focus();
  const pending = h.retry(); assert.equal(h.current().preserving, true);
  const description = h.nodes.get('cal-desc'); description.focus(); description.value = 'typed while retry pending';
  description.selectionStart = 6; description.selectionEnd = 11; const before = h.snapshot();
  h.state.listGate.resolve(); assert.equal(await pending, true);
  assert.deepEqual(h.snapshot(), { ...before, preserving: false });
  assert.equal(h.opens.length, 1); assert.equal(h.state.renders, 0); assert.equal(h.state.pickerRefreshes, 1);
});

test('same-record reveal leaves existing title, description and external focus alone', () => {
  const h = harness(); h.edit();
  for (const id of ['cal-title', 'cal-desc', 'elsewhere']) {
    h.nodes.get(id).focus(); const before = h.snapshot();
    assert.equal(h.open('linked', null), true); assert.deepEqual(h.snapshot(), before);
  }
  assert.equal(h.opens.length, 1);
});

test('opening a new record or a different occurrence still focuses the new title', () => {
  const h = harness(); h.edit(); h.nodes.get('cal-desc').focus(); h.edit(event('second'));
  assert.equal(h.document.activeElement.id, 'cal-title');
  h.edit({ ...event('series'), recurrence: 'weekly' }, '2026-10-07'); h.nodes.get('cal-desc').focus();
  assert.equal(h.open('series', '2026-10-14'), true); assert.equal(h.document.activeElement.id, 'cal-title');
  assert.equal(h.current().occurrence, '2026-10-14');
});

test('unavailable records and invalid occurrences do not steal focus', () => {
  const h = harness(); h.edit({ ...event('series'), recurrence: 'weekly' }, '2026-10-07');
  h.nodes.get('cal-desc').focus(); const before = h.snapshot();
  assert.equal(h.open('missing'), false); h.ready(false); assert.equal(h.open('series'), false);
  h.ready(true); h.state.occurrenceValid = false; assert.equal(h.open('series', '2026-10-14'), false);
  assert.deepEqual(h.snapshot(), before); assert.equal(h.opens.length, 1);
});

test('failed linked retry retains the newer description and clears retry ownership', async () => {
  const h = harness(); h.edit(); h.state.listGate = deferred(); h.state.listError = true;
  const pending = h.retry(); h.nodes.get('cal-desc').focus(); h.nodes.get('cal-desc').value = 'keep after failure';
  const before = h.snapshot(); h.state.listGate.resolve(); assert.equal(await pending, false);
  assert.deepEqual(h.snapshot(), { ...before, preserving: false }); assert.equal(h.errors.length, 1);
});

test('explicit event-editor deletion still uses its existing delete path', async () => {
  const h = harness(); h.edit(); await h.remove();
  assert.equal(h.records.has('linked'), false);
  assert.equal(h.requests.filter(r => r.method === 'DELETE').length, 1);
  assert.equal(h.requests.find(r => r.method === 'DELETE').body, undefined);
  assert.match(h.requests.find(r => r.method === 'DELETE').url, /^\/api\/calendar\/linked\?scope=all&occ=2026-10-07$/);
  assert.equal(h.errors.length, 0); assert.equal(h.current().saving, false);
});

test('quick undo removes only the unchanged latest receipt and restores its owned focus', async () => {
  const h = harness(); await h.enter('first event'); const first = [...h.records.values()][0];
  await h.enter('latest event'); const latest = [...h.records.values()][1];
  assert.equal(await h.clickAvailableUndo(), true);
  assert.deepEqual(h.records.get(first.id), first); assert.equal(h.records.has(latest.id), false);
  const deleted = h.requests.find(request => request.method === 'DELETE');
  assert.deepEqual(JSON.parse(deleted.body), latest);
  assert.equal(deleted.headers['content-type'], 'application/json');
  assert.equal(h.nodes.get('cal-quick-status').textContent, 'calendar.quick_undone:' + latest.title);
  assert.equal(h.nodes.get('cal-quick-undo').hidden, true);
  assert.equal(h.document.activeElement, h.nodes.get('cal-quick'));
});

test('lost undo acknowledgment retains the exact receipt for the existing 404 retry', async () => {
  const h = harness(); await h.enter(); const original = copy([...h.records.values()][0]);
  h.state.lostDeleteAck = true; assert.equal(await h.clickAvailableUndo(), true);
  assert.equal(h.records.has(original.id), false);
  assert.equal(h.nodes.get('cal-quick-status').textContent, 'calendar.quick_undo_failed:' + original.title);
  assert.equal(h.nodes.get('cal-quick-undo').hidden, false);
  h.state.lostDeleteAck = false; assert.equal(await h.clickAvailableUndo(), true);
  const deletes = h.requests.filter(request => request.method === 'DELETE');
  assert.equal(deletes.length, 2);
  for (const request of deletes) assert.deepEqual(JSON.parse(request.body), original);
  assert.equal(h.nodes.get('cal-quick-status').textContent, 'calendar.quick_undone:' + original.title);
  assert.equal(h.nodes.get('cal-quick-undo').hidden, true);
});

test('declining draft replacement leaves quick undo available without deleting the event', async () => {
  const h = harness(); await h.enter(); const original = copy([...h.records.values()][0]);
  h.edit(); h.nodes.get('cal-desc').value = 'unsaved editor text'; h.state.confirm = false;
  assert.equal(await h.clickAvailableUndo(), true);
  assert.equal(h.requests.some(request => request.method === 'DELETE'), false);
  assert.deepEqual(h.records.get(original.id), original);
  assert.equal(h.nodes.get('cal-desc').value, 'unsaved editor text');
  assert.equal(h.nodes.get('cal-quick-undo').hidden, false);
  assert.equal(h.nodes.get('cal-quick').readOnly, false);
});

test('pending undo remains single-flight and keeps a newer editor draft and focus', async () => {
  const h = harness(); await h.enter(); h.state.deleteGate = deferred();
  const pending = h.clickAvailableUndo(); await Promise.resolve();
  assert.equal(h.nodes.get('cal-quick-undo').attributes['aria-disabled'], 'true');
  assert.equal(await h.clickAvailableUndo(), false);
  h.edit(); h.nodes.get('cal-desc').value = 'typed while undo pending'; h.nodes.get('cal-desc').focus();
  const before = h.snapshot(); h.state.deleteGate.resolve(); await pending;
  assert.deepEqual(h.snapshot(), before);
  assert.equal(h.requests.filter(request => request.method === 'DELETE').length, 1);
  assert.equal(h.nodes.get('cal-quick-undo').hidden, true);
});

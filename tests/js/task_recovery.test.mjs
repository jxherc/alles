import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/tasks.js', import.meta.url), 'utf8')
  .replace(/^import .*;$/gm, '').replaceAll('export ', '');
const scope = 'a'.repeat(64);
function harness(storage = new Map()) {
  const handlers = {}, timers = new Map(); let nextTimer = 0;
  const list = { innerHTML: '', querySelectorAll: () => [] };
  const search = { value: '', addEventListener: (name, fn) => { handlers[name] = fn; } };
  const sessionStorage = {
    get length() { return storage.size; }, key: index => [...storage.keys()][index],
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key),
  };
  const context = vm.createContext({
    document: { querySelectorAll: () => [], getElementById: id => id === 'tasks-list' ? list : id === 'tasks-search' ? search : null, querySelector: () => null },
    window: { addEventListener() {} }, sessionStorage, console,
    tr: key => key, setTimeout: fn => { timers.set(++nextTimer, fn); return nextTimer; }, clearTimeout: id => timers.delete(id),
    fetch: async () => ({ ok: true, json: async () => [] }),
  });
  vm.runInContext(source + `\nrecoverTaskDraft = async () => {}; _draftScopes = ['${scope}']; globalThis.api = { loadTasks, taskValues, taskChanges, persistTaskDraft, clearTaskDraft, readTaskDraft, scopes: value => { _draftScopes = value; } };`, context);
  return { ...context.api, handlers, search, list, storage, sessionStorage, timers };
}
const row = title => ({ id: title, title, tags: [], notes: '', project: '', due_date: null, priority: 0 });
const response = title => ({ ok: true, json: async () => [row(title)] });

for (const oldFails of [false, true]) {
  test(`late ${oldFails ? 'failure' : 'success'} cannot replace a newer task list`, async () => {
    const h = harness(); let release;
    const old = h.loadTasks(() => new Promise((resolve, reject) => { release = oldFails ? () => reject(new Error('old failed')) : () => resolve(response('old')); }));
    await h.loadTasks(async () => response('new'));
    const current = h.list.innerHTML;
    release(); await old;
    assert.match(current, /new/); assert.equal(h.list.innerHTML, current);
  });
}

test('typing invalidates an older response before the debounce fires', async () => {
  const h = harness(); await h.loadTasks(async () => response('initial'));
  const initial = h.list.innerHTML; let release;
  const pending = h.loadTasks(() => new Promise(resolve => { release = () => resolve(response('old')); }));
  h.search.value = 'new query'; h.handlers.input();
  assert.equal(h.timers.size, 1);
  release(); await pending;
  assert.equal(h.list.innerHTML, initial);
});

test('partial changes include only edited fields and preserve multiline notes', () => {
  const h = harness(); const base = h.taskValues(row('task'));
  const changes = h.taskChanges(base, { ...base, notes: 'line one\n中文\n' });
  assert.deepEqual(JSON.parse(JSON.stringify(changes)), { notes: 'line one\n中文\n' });
});

test('drafts round trip only inside the matching owner and tab', () => {
  const h = harness(); const base = h.taskValues(row('task'));
  assert.equal(h.persistTaskDraft('task', base, { ...base, notes: 'draft 中文' }), true);
  assert.equal(h.readTaskDraft('task').values.notes, 'draft 中文');
  assert.equal(harness().readTaskDraft('task'), null);
  h.scopes(['b'.repeat(64)]); assert.equal(h.readTaskDraft('task'), null);
  h.scopes([scope]); assert.equal(h.clearTaskDraft('task'), true); assert.equal(h.readTaskDraft('task'), null);
});

for (const name of ['QuotaExceededError', 'SecurityError']) {
  test(`${name} cannot report a recoverable draft or successful cleanup`, () => {
    const h = harness(); const base = h.taskValues(row('task'));
    assert.equal(h.persistTaskDraft('task', base, { ...base, notes: 'kept' }), true);
    h.sessionStorage.setItem = () => { throw new DOMException('blocked', name); };
    h.sessionStorage.removeItem = () => { throw new DOMException('blocked', name); };
    assert.equal(h.persistTaskDraft('task', base, { ...base, notes: 'new draft' }), false);
    assert.equal(h.clearTaskDraft('task'), false);
    assert.equal(h.readTaskDraft('task').values.notes, 'kept');
  });
}

test('corrupt or mismatched records are not restored as another task', () => {
  const h = harness(); h.storage.set(`alles.tasks.draft.v1:${scope}:task`, '{bad');
  assert.equal(h.readTaskDraft('task'), null);
  h.storage.set(`alles.tasks.draft.v1:${scope}:task`, JSON.stringify({ version: 1, scope, id: 'other', base: row('x'), values: row('x') }));
  assert.equal(h.readTaskDraft('task'), null);
  h.storage.set(`alles.tasks.draft.v1:${scope}:task`, JSON.stringify({ version: 1, scope, id: 'task', base: row('x'), values: { title: 'x', tags: [123] } }));
  assert.equal(h.readTaskDraft('task'), null);
});

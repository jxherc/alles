import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { t, tp } from '../../static/js/i18n.js';

const source = readFileSync(new URL('../../static/js/notes.js', import.meta.url), 'utf8')
  .replace(/^import .*;\n/gm, '').replace(/^export /gm, '');
const note = (id = 'a') => ({ id, title: id, content: `body ${id}`, tags: [], items: [], due: '', hash: `hash-${id}` });
const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });
const tick = () => new Promise(resolve => setImmediate(resolve));

function harness() {
  const elements = new Map(), writes = [], toasts = [], disk = new Map(), pickers = [];
  let held = null, fail = null, created = 0;
  function element(id = '', value = '') {
    const listeners = new Map();
    return {
      id, value, dataset: {}, disabled: false, textContent: '', hidden: false,
      addEventListener: (type, callback) => listeners.set(type, callback),
      click() { return this.disabled ? undefined : listeners.get('click')?.({ target: this, stopPropagation() {} }); },
      setAttribute() {}, removeAttribute() {}, focus() {},
      querySelectorAll(selector) { return selector === '.note-archive-btn' ? this.archives || [] : []; },
      set innerHTML(html) {
        if (id !== 'notes-list') return;
        for (const key of [...elements.keys()]) if (key.startsWith('note-edit-') || ['note-save-btn', 'note-back-btn', 'note-checklist', 'note-add-item', 'note-obsidian-btn'].includes(key)) elements.delete(key);
        for (const match of html.matchAll(/<(input|textarea|button|div)\b[^>]*\bid="([^"]+)"[^>]*>([^<]*)/g)) {
          const value = match[1] === 'textarea' ? match[3] : match[0].match(/\bvalue="([^"]*)"/)?.[1] || '';
          elements.set(match[2], element(match[2], value));
        }
        this.archives = [...html.matchAll(/class="act-btn note-archive-btn" data-id="([^"]+)"/g)].map(match => {
          const button = element(); button.dataset.id = match[1]; return button;
        });
      },
    };
  }
  elements.set('notes-list', element('notes-list'));
  elements.set('note-new-btn', element('note-new-btn'));
  const fetcher = async (url, options = {}) => {
    const method = options.method || 'GET';
    if (method === 'GET') return response(url === '/api/notes/tags' ? [] : [...disk.values()]);
    const body = JSON.parse(options.body || '{}');
    writes.push({ url, method, body });
    if (held?.method === method) {
      const barrier = held; held = null;
      await barrier.promise;
    }
    if (fail) { const status = fail; fail = null; return response({ detail: 'synthetic refusal' }, status); }
    if (method === 'POST' && url === '/api/notes') {
      const value = { ...note(`new-${++created}`), ...body }; disk.set(value.id, value); return response(value);
    }
    const id = decodeURIComponent(url.split('/')[3]);
    if (url.endsWith('/archive')) { disk.delete(id); return response({ id, archived: true }); }
    const previous = disk.get(id);
    assert.ok(previous, `save target ${id} must exist`);
    assert.equal(body.expected_hash, previous.hash, 'save must use its own last receipt');
    const updated = { ...previous, ...body, id: body.title === previous.title ? id : body.title, hash: `saved-${writes.length}` };
    disk.delete(id); disk.set(updated.id, updated); return response(updated);
  };
  const context = vm.createContext({ t, tp,
    document: { getElementById: id => elements.get(id), querySelectorAll: () => [] },
    fetch: fetcher, URLSearchParams, location: { hash: '' }, setTimeout, clearTimeout,
    toast: (message, kind) => toasts.push({ message, kind }),
    initDatePicker: el => { pickers.push(el); },
  });
  vm.runInContext(source + '\nglobalThis.subject = { open: openEditor, save: saveCurrentNote, newNote, load: loadNotes, current: () => _editing };', context);
  return {
    ...context.subject, get: id => elements.get(id), writes, toasts, disk, pickers,
    seed(id = 'a') { const value = note(id); disk.set(id, value); return value; },
    refuse() { fail = 503; },
    hold(method = 'PATCH') { let release; const promise = new Promise(resolve => { release = resolve; }); held = { method, promise }; return release; },
  };
}

test('late Save A cannot rebind editor B or its next write', async () => {
  const h = harness(); h.open(h.seed());
  h.get('note-edit-body').value = 'submitted A';
  const release = h.hold(); const pending = h.get('note-save-btn').click();
  h.open(h.seed('b')); h.get('note-edit-body').value = 'new B draft';
  release(); await pending;
  assert.equal(h.current().id, 'b');
  assert.equal(h.get('note-edit-body').value, 'new B draft');
  await h.get('note-save-btn').click();
  assert.equal(h.writes.at(-1).url, '/api/notes/b');
  assert.equal(h.disk.get('b').content, 'new B draft');
  assert.equal(h.disk.get('a').content, 'submitted A');
});

test('a retitle receipt updates the save target without replacing newer typed fields', async () => {
  const h = harness(); h.open(h.seed()); h.get('note-edit-title').value = 'renamed';
  const release = h.hold(); const pending = h.get('note-save-btn').click();
  h.get('note-edit-body').value = 'typed during save';
  release(); await pending;
  assert.equal(h.get('note-edit-body').value, 'typed during save');
  await h.get('note-save-btn').click();
  assert.equal(h.writes.at(-1).url, '/api/notes/renamed');
  assert.equal(h.disk.get('renamed').content, 'typed during save');
});

test('New saves current input before creating and opening a separate note', async () => {
  const h = harness(); h.open(h.seed()); h.get('note-edit-body').value = 'keep before New';
  await h.newNote();
  assert.equal(h.disk.get('a').content, 'keep before New');
  assert.equal(h.current().id, 'new-1');
  assert.deepEqual(h.writes.map(row => row.method), ['PATCH', 'POST']);
});

test('refused Save or New retains the draft and never announces saved', async () => {
  for (const action of ['save', 'new']) {
    const h = harness(); h.open(h.seed()); h.get('note-edit-body').value = 'keep rejected input'; h.refuse();
    if (action === 'save') await h.get('note-save-btn').click(); else await h.newNote();
    assert.equal(h.current().id, 'a');
    assert.equal(h.get('note-edit-body').value, 'keep rejected input');
    assert.equal(h.writes.length, 1);
    assert.ok(h.toasts.some(row => row.kind === 'error'));
    assert.ok(h.toasts.every(row => row.kind !== 'success'));
  }
});

test('New waits for an existing Save and preserves typing during that save', async () => {
  const h = harness(); h.open(h.seed());
  const release = h.hold(); const pendingSave = h.get('note-save-btn').click();
  h.get('note-edit-body').value = 'newer than submitted snapshot';
  const pendingNew = h.newNote(); await tick();
  assert.equal(h.writes.length, 1, 'same editor must not send competing PATCHes');
  release(); await Promise.all([pendingSave, pendingNew]);
  assert.equal(h.disk.get('a').content, 'newer than submitted snapshot');
  assert.equal(h.current().id, 'new-1');
});

test('edits during New creation are saved before the editor is replaced', async () => {
  const h = harness(); h.open(h.seed());
  const release = h.hold('POST'); const pending = h.newNote(); await tick();
  h.get('note-edit-body').value = 'typed during create'; release(); await pending;
  assert.equal(h.disk.get('a').content, 'typed during create');
  assert.equal(h.current().id, 'new-1');
});

test('repeated New while creating sends one POST', async () => {
  const h = harness(); const release = h.hold('POST');
  const first = h.newNote(); const second = h.newNote(); await tick();
  assert.equal(h.writes.length, 1); release(); await Promise.all([first, second]);
});

test('Back saves typing entered while the initial save was pending', async () => {
  const h = harness(); h.open(h.seed()); const release = h.hold();
  const pending = h.get('note-back-btn').click(); h.get('note-edit-body').value = 'latest before Back';
  release(); await pending;
  assert.equal(h.disk.get('a').content, 'latest before Back');
  assert.equal(h.current(), null);
});

test('late failed save leaves another editor intact and reports no success', async () => {
  const h = harness(); h.open(h.seed()); const release = h.hold(); h.refuse();
  const pending = h.get('note-save-btn').click(); h.open(h.seed('b'));
  h.get('note-edit-body').value = 'keep B after A fails'; release(); await pending;
  assert.equal(h.current().id, 'b');
  assert.equal(h.get('note-edit-body').value, 'keep B after A fails');
  assert.ok(h.toasts.every(row => row.kind !== 'success'));
});

test('Back rechecks its owner after the shared save has settled', async () => {
  const h = harness(); h.open(h.seed()); const release = h.hold();
  const saving = h.save();
  const back = h.get('note-back-btn').click();
  release(); await saving;
  h.open(h.seed('b')); h.get('note-edit-body').value = 'B after shared save';
  await back;
  assert.equal(h.current().id, 'b');
  assert.equal(h.get('note-edit-body').value, 'B after shared save');
});

test('Archive refusal keeps the note, reports failure, and supports a successful retry', async () => {
  const h = harness(); h.seed(); await h.load(); h.refuse();
  const button = h.get('notes-list').archives[0]; await button.click();
  assert.equal(h.disk.has('a'), true);
  assert.ok(h.toasts.some(row => row.kind === 'error'));
  assert.ok(h.toasts.every(row => row.kind !== 'success'));
  await button.click();
  assert.equal(h.disk.has('a'), false);
  assert.equal(h.toasts.at(-1).message, 'archived');
});

test('the due date is the app date picker, and its value is what saves', async () => {
  assert.doesNotMatch(source, /<input[^>]*type="date"/);
  const h = harness(); h.open(h.seed());
  const due = h.get('note-edit-due');
  assert.deepEqual(h.pickers, [due]);
  due.value = '2026-11-02';
  await h.get('note-save-btn').click();
  assert.equal(h.writes.at(-1).body.due, '2026-11-02');
});

test('the due date is named "due date", plus the chosen date once there is one', () => {
  assert.match(source, /<span id="note-due-label" hidden>\$\{t\('notes\.due_date'\)\}<\/span>/);
  assert.doesNotMatch(source, /id="note-edit-due"[^>]*aria-label=/);
  assert.doesNotMatch(source, />\+ checklist item</);
  const fn = source.match(/const nameDue = [^\n]+/)?.[0];
  assert.ok(fn);
  for (const [value, name] of [['', 'note-due-label'], ['2026-11-02', 'note-due-label note-edit-due']]) {
    const attrs = {};
    const due = { value, setAttribute: (key, v) => { attrs[key] = v; } };
    new Function('due', `${fn}; nameDue();`)(due);
    assert.equal(attrs['aria-labelledby'], name, value || 'empty');
  }
  assert.match(source, /due\.addEventListener\('change', nameDue\)/);
});

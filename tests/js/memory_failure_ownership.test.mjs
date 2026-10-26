import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

import { categoryHue } from '../../static/js/color.js';
import { t, tp } from '../../static/js/i18n.js';

// Synthetic DOM and fetch only: this suite never starts Alles or reads owner data.
const source = readFileSync(new URL('../../static/js/memory.js', import.meta.url), 'utf8')
  .replace(/^import .*;\n/gm, '').replace(/^export /gm, '');
const memory = (id = 'one', text = 'known memory', category = 'general') => ({
  id, text, category, pinned: false, scope: 'global', status: 'active',
});
const tick = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };

function harness() {
  const elements = new Map(), calls = [], toasts = [], timers = new Map(), queued = [];
  let document, dialog = null, nextTimer = 0, serial = 0;
  const disk = new Map([['one', memory()]]);
  const settings = { memory_policy: 'ask', memory_auto_inject: true };
  function element(id = '') {
    const listeners = new Map(), classes = new Set();
    const el = {
      id, dataset: {}, value: '', hidden: false, disabled: false, textContent: '', children: [],
      attributes: new Map(), parentNode: null, innerHTMLValue: '',
      classList: { contains: k => classes.has(k), toggle(k, on) { if (on) classes.add(k); else classes.delete(k); } },
      setAttribute(k, v) { this.attributes.set(k, v); }, removeAttribute(k) { this.attributes.delete(k); },
      addEventListener(type, fn) { const handlers = listeners.get(type) || []; handlers.push(fn); listeners.set(type, handlers); },
      async fire(type) { await Promise.all((listeners.get(type) || []).map(fn => fn({ target: this, currentTarget: this, key: 'Enter', preventDefault() {} }))); },
      click() { return this.disabled ? Promise.resolve() : this.onclick ? this.onclick() : this.fire('click'); },
      focus() { document.activeElement = this; },
      appendChild(child) { child.parentNode = this; this.children.push(child); if (child.id) elements.set(child.id, child); return child; },
      insertBefore(child) { return this.appendChild(child); },
      remove() { elements.delete(this.id); if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(child => child !== this); },
      querySelectorAll(selector) {
        return this.children.filter(child => selector === 'button' ? child.tagName === 'button' : selector.startsWith('.') ? child.className?.split(' ').includes(selector.slice(1)) : selector.startsWith('#') && child.id === selector.slice(1));
      },
      querySelector(selector) { return this.querySelectorAll(selector)[0] || null; },
      get innerHTML() { return this.innerHTMLValue; },
      set innerHTML(html) {
        this.innerHTMLValue = html; this.children = [];
        for (const match of html.matchAll(/<button\b([^>]*)>(.*?)<\/button>/gs)) {
          const child = element(); child.tagName = 'button'; child.textContent = match[2];
          for (const attr of match[1].matchAll(/([\w-]+)="([^"]*)"/g)) {
            if (attr[1] === 'class') child.className = attr[2];
            else if (attr[1] === 'id') child.id = attr[2];
            else if (attr[1].startsWith('data-')) child.dataset[attr[1].slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = attr[2];
          }
          child.disabled = /\bdisabled\b/.test(match[1]); this.appendChild(child);
        }
      },
    };
    return el;
  }
  const host = element('host');
  for (const id of ['memory-list', 'mem-category-filter', 'mem-policy-desc', 's-memory-inject-toggle', 'mem-pause-btn', 'mem-extract-btn', 'mem-clear-btn', 'mem-add-btn', 'mem-add-input', 'mem-cat-cycle-btn', 'mem-search', 'mem-undo']) host.appendChild(element(id));
  const undo = element(); undo.tagName = 'button'; elements.get('mem-undo').appendChild(undo);
  document = { getElementById: id => elements.get(id), querySelectorAll: () => [], createElement: tag => Object.assign(element(), { tagName: tag }), activeElement: null, body: host };
  const fetcher = async (url, options = {}) => {
    const method = options.method || 'GET';
    const body = options.body ? JSON.parse(options.body) : null;
    calls.push({ url, method, body });
    const index = queued.findIndex(item => item.url === url && item.method === method);
    if (index >= 0) {
      const item = queued.splice(index, 1)[0];
      if (item.wait) await item.wait;
      if (item.network) throw new Error('synthetic offline');
      if (item.status) return { ok: false, status: item.status, json: async () => ({ detail: 'synthetic refusal' }) };
      if (item.data !== undefined) return { ok: true, json: async () => item.data };
    }
    let data;
    if (url === '/api/settings') { if (body) Object.assign(settings, body); data = { ...settings }; }
    else if (url === '/api/memories/search') data = [...disk.values()].filter(item => item.text.includes(body.query));
    else if (method === 'GET') data = [...disk.values()];
    else if (url === '/api/memories' && method === 'POST') { data = { ...memory(`new-${++serial}`), ...body }; disk.set(data.id, data); }
    else if (url === '/api/memories' && method === 'DELETE') { data = { ok: true, deleted: disk.size }; disk.clear(); }
    else if (url.endsWith('/accept')) { const id = url.split('/').at(-2); data = { ...disk.get(id), status: 'active', trust: 'reviewed' }; disk.set(id, data); }
    else if (method === 'DELETE') { disk.delete(url.split('/').at(-1)); data = { ok: true }; }
    else { const id = url.split('/').at(-1); data = { ...disk.get(id), ...body }; disk.set(id, data); }
    return { ok: true, json: async () => data };
  };
  function openDialog(kind, initial, options = {}) {
    return new Promise(resolve => {
      const current = { kind, draft: initial, error: '', busy: false, async submit() {
        if (this.busy) return; this.busy = true;
        if (kind === 'prompt') { dialog = null; document.activeElement = host; resolve(this.draft); }
        else {
          try { await options.submit({ text: this.draft }); dialog = null; document.activeElement = host; resolve({ text: this.draft }); }
          catch (error) { this.error = error.message; }
        }
        this.busy = false;
      }, cancel() { dialog = null; document.activeElement = host; resolve(null); } };
      dialog = current;
      document.activeElement = element('dialog-input');
    });
  }
  const context = vm.createContext({ t, tp, tr: t, trp: tp,
    document, window: { _currentSession: { id: 'synthetic-session', project_id: 'synthetic-project' } },
    fetch: fetcher, toast: (message, kind) => toasts.push({ message, kind }),
    promptDialog: (_title, initial, options) => openDialog('prompt', initial, options),
    fieldsDialog: (_title, defs, options) => openDialog('fields', defs[0].value, options),
    confirmDialog: async () => true, categoryHue,
    setTimeout(fn, delay) { timers.set(++nextTimer, { fn, delay }); return nextTimer; }, clearTimeout: id => timers.delete(id),
  });
  vm.runInContext(source + '\nglobalThis.subject = { initMemoryPanel, loadMemories };', context);
  return {
    ...context.subject, get: id => elements.get(id), calls, toasts, disk,
    get dialog() { return dialog; },
    get activeElement() { return document.activeElement; },
    button: (kind, id = 'one') => elements.get('memory-list').querySelectorAll(`.mem-${kind}-btn`).find(btn => btn.dataset.id === id),
    queue(url, method = 'GET', options = {}) { queued.push({ url, method, ...options }); },
    hold(url, method, options = {}) { let release; const wait = new Promise(resolve => { release = resolve; }); queued.push({ url, method, wait, ...options }); return release; },
    async init() { context.subject.initMemoryPanel(); await tick(); },
    async search(value) { elements.get('mem-search').value = value; await elements.get('mem-search').fire('input'); },
    async debounce() { const pending = [...timers].filter(([, item]) => item.delay === 300); pending.forEach(([id]) => timers.delete(id)); await Promise.all(pending.map(([, item]) => item.fn())); },
    async category(value) { await elements.get('mem-category-filter').querySelectorAll('.mem-cat-btn').find(btn => btn.dataset.cat === value).click(); },
  };
}

for (const action of ['del', 'pin']) {
  test(`${action}: refused mutation preserves row and reports failure without a refresh`, async () => {
    const h = harness(); await h.init(); const before = h.get('memory-list').innerHTML;
    h.queue('/api/memories/one', action === 'del' ? 'DELETE' : 'PATCH', { status: 503 });
    await h.button(action).click();
    assert.equal(h.get('memory-list').innerHTML, before);
    assert.ok(h.toasts.some(item => item.kind === 'error' && /refusal/.test(item.message)));
    assert.equal(h.calls.filter(call => call.method === 'GET' && call.url === '/api/memories').length, 1);
  });
}

test('one pending row mutation survives rerender without accepting a duplicate', async () => {
  const h = harness(); await h.init(); const release = h.hold('/api/memories/one', 'PATCH');
  const pending = h.button('pin').click(); await h.category('all'); await h.button('pin').click();
  assert.equal(h.calls.filter(call => call.method === 'PATCH').length, 1);
  release(); await pending;
});

test('failed edit retains exact draft in the same dialog and retries once', async () => {
  const h = harness(); await h.init(); const editing = h.button('edit').click(); await tick();
  const dialog = h.dialog; dialog.draft = '  exact unsaved draft  ';
  h.queue('/api/memories/one', 'PATCH', { status: 503 }); await dialog.submit(); await tick();
  assert.equal(h.dialog, dialog); assert.equal(dialog.draft, '  exact unsaved draft  ');
  assert.match(dialog.error, /refusal/); assert.equal(dialog.busy, false);
  await dialog.submit(); await editing;
  assert.equal(h.disk.get('one').text, 'exact unsaved draft'); assert.equal(h.dialog, null);
});

test('late add preserves newer input and only accepts one pending write', async () => {
  const h = harness(); await h.init(); h.get('mem-add-input').value = 'submitted A';
  const release = h.hold('/api/memories', 'POST'); const pending = h.get('mem-add-btn').click();
  h.get('mem-add-input').value = 'newer B'; await h.get('mem-add-input').fire('input');
  await h.get('mem-add-btn').click();
  assert.equal(h.calls.filter(call => call.method === 'POST').length, 1);
  release(); await pending; assert.equal(h.get('mem-add-input').value, 'newer B');
  assert.equal(h.get('mem-add-btn').disabled, false);
});

test('clear then retype the same text still belongs to the newer draft', async () => {
  const h = harness(); await h.init(); h.get('mem-add-input').value = 'same text';
  const release = h.hold('/api/memories', 'POST'); const pending = h.get('mem-add-btn').click();
  h.get('mem-add-input').value = ''; await h.get('mem-add-input').fire('input');
  h.get('mem-add-input').value = 'same text'; await h.get('mem-add-input').fire('input');
  release(); await pending; assert.equal(h.get('mem-add-input').value, 'same text');
});

test('add refusal preserves exact draft and permits retry', async () => {
  const h = harness(); await h.init(); h.get('mem-add-input').value = '  draft with spacing  ';
  h.queue('/api/memories', 'POST', { network: true }); await h.get('mem-add-btn').click();
  assert.equal(h.get('mem-add-input').value, '  draft with spacing  '); assert.equal(h.get('mem-add-btn').disabled, false);
  assert.ok(h.toasts.some(item => item.kind === 'error'));
  await h.get('mem-add-btn').click(); assert.equal(h.disk.size, 2);
});

test('failed read preserves rows, category and draft with an inline retry', async () => {
  const h = harness(); await h.init(); await h.category('general');
  h.get('mem-add-input').value = 'unsaved'; const before = h.get('memory-list').innerHTML;
  h.queue('/api/memories', 'GET', { status: 503 }); await h.loadMemories();
  assert.equal(h.get('memory-list').innerHTML, before); assert.equal(h.get('mem-add-input').value, 'unsaved');
  const error = h.get('mem-load-error'); assert.ok(error); assert.match(error.textContent || error.innerHTML, /refresh|load/);
  await error.querySelector('button').click(); assert.equal(h.get('mem-load-error'), undefined);
});

for (const category of ['all', 'general']) {
  test(`search refusal in ${category} preserves known content and supports retry`, async () => {
    const h = harness(); await h.init(); await h.category(category); const before = h.get('memory-list').innerHTML;
    h.queue('/api/memories/search', 'POST', { status: 503 }); await h.search('known'); await h.debounce();
    assert.equal(h.get('memory-list').innerHTML, before);
    const error = h.get('mem-search-error'); assert.ok(error);
    await error.querySelector('button').click(); assert.equal(h.get('mem-search-error'), undefined);
    assert.match(h.get('memory-list').innerHTML, /known memory/);
  });
}

test('old search response cannot overwrite a newer query or a cleared search', async () => {
  const h = harness(); await h.init();
  const release = h.hold('/api/memories/search', 'POST', { data: [memory('old', 'obsolete result')] });
  await h.search('obsolete'); const old = h.debounce(); await h.search('known'); await h.debounce(); release(); await old;
  assert.match(h.get('memory-list').innerHTML, /known memory/); assert.doesNotMatch(h.get('memory-list').innerHTML, /obsolete result/);
  const release2 = h.hold('/api/memories/search', 'POST', { data: [] });
  await h.search('nothing'); const pending = h.debounce(); await h.search(''); release2(); await pending;
  assert.match(h.get('memory-list').innerHTML, /known memory/);
});

test('stale search failure is ignored and current network failure is recoverable', async () => {
  const h = harness(); await h.init();
  const release = h.hold('/api/memories/search', 'POST', { network: true });
  await h.search('old'); const pending = h.debounce(); await h.search('known'); await h.debounce(); release(); await pending;
  assert.equal(h.get('mem-search-error'), undefined);
  h.queue('/api/memories/search', 'POST', { network: true }); await h.search('new'); await h.debounce();
  assert.ok(h.get('mem-search-error')); assert.match(h.get('memory-list').innerHTML, /known memory/);
});

test('category changes keep the active search result set', async () => {
  const h = harness(); h.disk.set('two', memory('two', 'unrelated fact', 'fact')); await h.init();
  await h.search('known'); await h.debounce(); await h.category('fact');
  assert.doesNotMatch(h.get('memory-list').innerHTML, /unrelated fact/);
});

test('older list response cannot replace a newer confirmed list', async () => {
  const h = harness(); await h.init(); const release = h.hold('/api/memories', 'GET', { data: [memory('old', 'obsolete list')] });
  const old = h.loadMemories(); h.disk.set('two', memory('two', 'newer list')); await h.loadMemories(); release(); await old;
  assert.match(h.get('memory-list').innerHTML, /newer list/); assert.doesNotMatch(h.get('memory-list').innerHTML, /obsolete list/);
});

test('undo refusal retains its action and successful retry removes the memory', async () => {
  const h = harness(); await h.init(); h.get('mem-add-input').value = 'new memory'; await h.get('mem-add-btn').click();
  h.queue('/api/memories/new-1', 'DELETE', { status: 503 }); await h.get('mem-undo').querySelector('button').click();
  assert.equal(h.get('mem-undo').hidden, false); assert.equal(h.disk.has('new-1'), true);
  assert.ok(h.toasts.some(item => item.kind === 'error')); assert.ok(!h.toasts.some(item => item.message === 'memory removed'));
  await h.get('mem-undo').querySelector('button').click(); assert.equal(h.disk.has('new-1'), false);
});

test('confirmed edit followed by refresh refusal closes save and offers only a read retry', async () => {
  const h = harness(); await h.init(); const editing = h.button('edit').click(); await tick(); h.dialog.draft = 'confirmed edit';
  h.queue('/api/memories', 'GET', { status: 503 }); await h.dialog.submit(); await editing;
  assert.equal(h.dialog, null); assert.equal(h.disk.get('one').text, 'confirmed edit');
  assert.match(h.get('memory-list').innerHTML, /confirmed edit/); assert.ok(h.get('mem-load-error'));
  await h.get('mem-load-error').querySelector('button').click(); assert.equal(h.calls.filter(call => call.method === 'PATCH').length, 1);
});

test('clear all permits one pending request and keeps its confirmed removal if refresh fails', async () => {
  const h = harness(); await h.init();
  const release = h.hold('/api/memories', 'DELETE'); const pending = h.get('mem-clear-btn').click(); await tick();
  h.queue('/api/memories', 'GET', { status: 503 }); await h.get('mem-clear-btn').click();
  assert.equal(h.calls.filter(call => call.method === 'DELETE').length, 1);
  release(); await pending;
  assert.match(h.get('memory-list').innerHTML, /no memories/); assert.ok(h.get('mem-load-error'));
});

test('pause has one pending policy write and stays disabled until its receipt', async () => {
  const h = harness(); await h.init(); const release = h.hold('/api/settings', 'PATCH');
  const pending = h.get('mem-pause-btn').click(); await h.get('mem-pause-btn').click();
  assert.equal(h.calls.filter(call => call.method === 'PATCH').length, 1);
  assert.equal(h.get('mem-pause-btn').disabled, true);
  release(); await pending; assert.equal(h.get('mem-pause-btn').disabled, false);
});

test('late undo receipt cannot hide or disable a newer memory undo', async () => {
  const h = harness(); await h.init(); h.get('mem-add-input').value = 'memory A'; await h.get('mem-add-btn').click();
  const release = h.hold('/api/memories/new-1', 'DELETE'); const pending = h.get('mem-undo').querySelector('button').click();
  await h.get('mem-undo').querySelector('button').click();
  h.get('mem-add-input').value = 'memory B'; await h.get('mem-add-btn').click();
  release(); await pending;
  assert.equal(h.calls.filter(call => call.url === '/api/memories/new-1' && call.method === 'DELETE').length, 1);
  assert.equal(h.get('mem-undo').hidden, false); assert.equal(h.get('mem-undo').querySelector('button').disabled, false);
  await h.get('mem-undo').querySelector('button').click(); assert.equal(h.disk.has('new-2'), false);
});

test('initial read failure is caught by init and exposes recovery', async () => {
  const h = harness(); h.queue('/api/memories', 'GET', { network: true }); await h.init();
  assert.ok(h.get('mem-load-error')); assert.doesNotMatch(h.get('memory-list').innerHTML, /no memories/);
  await h.get('mem-load-error').querySelector('button').click(); assert.match(h.get('memory-list').innerHTML, /known memory/);
});

test('malformed successful search data is a recoverable read error', async () => {
  const h = harness(); await h.init(); h.queue('/api/memories/search', 'POST', { data: {} });
  await h.search('known'); await h.debounce(); assert.ok(h.get('mem-search-error'));
  assert.match(h.get('memory-list').innerHTML, /known memory/);
});

test('blank edit remains recoverable and cancel sends no write', async () => {
  const h = harness(); await h.init(); const editing = h.button('edit').click(); await tick();
  h.dialog.draft = '   '; await h.dialog.submit(); assert.ok(h.dialog); assert.match(h.dialog.error, /text/);
  h.dialog.cancel(); await editing; assert.equal(h.calls.filter(call => call.method !== 'GET').length, 0);
});

test('confirmed add followed by failed refresh cannot be retried as another create', async () => {
  const h = harness(); await h.init(); h.get('mem-add-input').value = 'confirmed new memory';
  h.queue('/api/memories', 'GET', { status: 503 }); await h.get('mem-add-btn').click();
  assert.equal(h.get('mem-add-input').value, ''); assert.match(h.get('memory-list').innerHTML, /confirmed new memory/);
  assert.ok(h.get('mem-load-error')); await h.get('mem-load-error').querySelector('button').click();
  assert.equal(h.calls.filter(call => call.method === 'POST').length, 1);
});

test('an older settings read cannot undo a confirmed injection toggle', async () => {
  const h = harness(); await h.init();
  const release = h.hold('/api/settings', 'GET', { data: { memory_policy: 'ask', memory_auto_inject: true } });
  const pending = h.loadMemories(); await h.get('s-memory-inject-toggle').click();
  release(); await pending;
  assert.equal(h.get('s-memory-inject-toggle').attributes.get('aria-checked'), 'false');
});

for (const receipt of [{}, null, [], { id: 'new-1', text: 'exact draft' }, { ...memory('new-1', 'wrong text'), scope: 'project', project_id: 'synthetic-project' }]) {
  test(`malformed add receipt ${JSON.stringify(receipt)} preserves exact draft and known rows`, async () => {
    const h = harness(); await h.init(); h.get('mem-add-input').value = '  exact draft  ';
    const before = h.get('memory-list').innerHTML;
    h.queue('/api/memories', 'POST', { data: receipt }); await h.get('mem-add-btn').click();
    assert.equal(h.get('mem-add-input').value, '  exact draft  ');
    assert.equal(h.get('memory-list').innerHTML, before);
    assert.ok(h.toasts.some(item => item.kind === 'error' && /confirm/.test(item.message)));
    assert.ok(!h.toasts.some(item => item.message === 'remembered'));
    assert.equal(h.calls.filter(call => call.method === 'GET' && call.url === '/api/memories').length, 1);
    await h.get('mem-add-btn').click(); assert.equal(h.disk.get('new-1').text, 'exact draft');
  });
}

for (const receipt of [{}, { ...memory('wrong-id'), pinned: true }, memory()]) {
  test(`invalid pin receipt ${JSON.stringify(receipt)} does not promote a row`, async () => {
    const h = harness(); await h.init(); const before = h.get('memory-list').innerHTML;
    h.queue('/api/memories/one', 'PATCH', { data: receipt }); await h.button('pin').click();
    assert.equal(h.get('memory-list').innerHTML, before);
    assert.ok(h.toasts.some(item => item.kind === 'error' && /confirm/.test(item.message)));
    await h.button('pin').click(); assert.equal(h.disk.get('one').pinned, true);
  });
}

test('malformed edit receipt retains exact dialog draft and successful retry saves it', async () => {
  const h = harness(); await h.init(); const editing = h.button('edit').click(); await tick();
  const dialog = h.dialog; dialog.draft = '  exact edited draft  ';
  h.queue('/api/memories/one', 'PATCH', { data: {} }); await dialog.submit(); await tick();
  assert.equal(h.dialog, dialog); assert.equal(dialog.draft, '  exact edited draft  ');
  assert.match(dialog.error, /confirm/); assert.equal(dialog.busy, false);
  assert.match(h.get('memory-list').innerHTML, /known memory/);
  await dialog.submit(); await editing; assert.equal(h.disk.get('one').text, 'exact edited draft');
});

test('scope receipt must confirm the requested project', async () => {
  const h = harness(); await h.init(); const before = h.get('memory-list').innerHTML;
  h.queue('/api/memories/one', 'PATCH', { data: { ...memory(), scope: 'project', project_id: 'wrong-project' } });
  await h.button('scope').click(); assert.equal(h.get('memory-list').innerHTML, before);
  assert.ok(h.toasts.some(item => item.kind === 'error' && /confirm/.test(item.message)));
  await h.button('scope').click(); assert.equal(h.disk.get('one').project_id, 'synthetic-project');
});

test('accept receipt must confirm the same memory is active', async () => {
  const h = harness(); h.disk.set('one', { ...memory(), status: 'suggested' }); await h.init();
  h.queue('/api/memories/one/accept', 'POST', { data: { ...memory(), status: 'suggested' } });
  await h.button('accept').click(); assert.ok(h.button('accept'));
  assert.ok(!h.toasts.some(item => item.message === 'memory accepted'));
  assert.ok(h.toasts.some(item => item.kind === 'error' && /confirm/.test(item.message)));
  await h.button('accept').click(); assert.equal(h.disk.get('one').status, 'active');
});

test('malformed delete receipt keeps the known row and action for retry', async () => {
  const h = harness(); await h.init(); const before = h.get('memory-list').innerHTML;
  h.queue('/api/memories/one', 'DELETE', { data: {} }); await h.button('del').click();
  assert.equal(h.get('memory-list').innerHTML, before);
  assert.ok(!h.toasts.some(item => item.message === 'memory removed'));
  assert.ok(h.toasts.some(item => item.kind === 'error' && /confirm/.test(item.message)));
  await h.button('del').click(); assert.equal(h.disk.has('one'), false);
});

test('malformed undo receipt keeps undo available without claiming removal', async () => {
  const h = harness(); await h.init(); h.get('mem-add-input').value = 'undo memory'; await h.get('mem-add-btn').click();
  const before = h.get('memory-list').innerHTML;
  h.queue('/api/memories/new-1', 'DELETE', { data: {} }); await h.get('mem-undo').querySelector('button').click();
  assert.equal(h.get('memory-list').innerHTML, before); assert.equal(h.get('mem-undo').hidden, false);
  assert.equal(h.get('mem-undo').querySelector('button').disabled, false);
  assert.ok(!h.toasts.some(item => item.message === 'memory removed'));
  assert.ok(h.toasts.some(item => item.kind === 'error' && /confirm/.test(item.message)));
  await h.get('mem-undo').querySelector('button').click(); assert.equal(h.disk.has('new-1'), false);
});

for (const receipt of [{}, { ok: true }, { ok: true, deleted: -1 }]) {
  test(`malformed clear receipt ${JSON.stringify(receipt)} preserves known rows`, async () => {
    const h = harness(); await h.init(); const before = h.get('memory-list').innerHTML;
    h.queue('/api/memories', 'DELETE', { data: receipt }); await h.get('mem-clear-btn').click();
    assert.equal(h.get('memory-list').innerHTML, before);
    assert.ok(!h.toasts.some(item => /memories cleared/.test(item.message)));
    assert.ok(h.toasts.some(item => item.kind === 'error' && /confirm/.test(item.message)));
    await h.get('mem-clear-btn').click(); assert.equal(h.disk.size, 0);
  });
}

test('cancelled keyboard edit restores focus to its enabled opener', async () => {
  const h = harness(); await h.init(); const opener = h.button('edit'); opener.focus();
  const editing = opener.click(); await tick(); h.dialog.cancel(); await editing;
  assert.equal(h.activeElement, h.button('edit')); assert.equal(h.activeElement.disabled, false);
});

test('successful keyboard edit restores focus after the row is rerendered', async () => {
  const h = harness(); await h.init(); const opener = h.button('edit'); opener.focus();
  const editing = opener.click(); await tick(); h.dialog.draft = 'edited memory'; await h.dialog.submit(); await editing;
  assert.notEqual(h.button('edit'), opener); assert.equal(h.activeElement, h.button('edit'));
});

test('edit completion does not steal newer focus while its refresh is pending', async () => {
  const h = harness(); await h.init(); h.button('edit').focus();
  const editing = h.button('edit').click(); await tick(); h.dialog.draft = 'edited memory';
  const release = h.hold('/api/memories', 'GET'); await h.dialog.submit(); await tick();
  h.get('mem-add-input').focus(); release(); await editing;
  assert.equal(h.activeElement, h.get('mem-add-input'));
});

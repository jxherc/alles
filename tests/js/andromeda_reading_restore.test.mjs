import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8')
  .replace(/^import .*;\n/gm, '').replace(/^export /gm, '');
const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => {
  let resolve;
  const promise = new Promise(yes => { resolve = yes; });
  return { promise, resolve };
};
const response = body => ({ ok: true, json: async () => body });
const url = 'http://127.0.0.1:8000/synthetic-result?edition=1';
const result = { title: 'Synthetic local reading result', url, snippet: 'Owned excerpt' };
const item = { id: 'server-issued-record', url };

function harness() {
  class Element {
    constructor(tag) {
      this.tag = tag; this.children = []; this.attrs = {}; this.handlers = {};
      this.dataset = {}; this.style = {}; this.classList = { add() {}, toggle() {} };
      this.textContent = ''; this.className = ''; this.parent = null;
    }
    get isConnected() { return this.root || !!this.parent?.isConnected; }
    get childElementCount() { return this.children.filter(child => child.tag !== 'text').length; }
    appendChild(child) { child.parent = this; this.children.push(child); return child; }
    append(...children) { children.forEach(child => this.appendChild(child)); }
    replaceChildren() { this.children.forEach(child => { child.parent = null; }); this.children = []; }
    setAttribute(name, value) { this.attrs[name] = value; }
    addEventListener(name, fn) { this.handlers[name] = fn; }
  }
  const nodes = new Map();
  const get = id => {
    if (!nodes.has(id)) { const node = new Element('div'); node.root = true; nodes.set(id, node); }
    return nodes.get(id);
  };
  const requests = [], opens = [];
  let intercept = () => response({ items: [] });
  const context = vm.createContext({
    URL, console,
    document: { getElementById: get, createElement: tag => new Element(tag),
      createTextNode: text => Object.assign(new Element('text'), { textContent: text }) },
    window: { _openRecord: async (...args) => { opens.push(args); return true; } },
    tr: key => key === 'andromeda.save_library' ? 'save to Library' : key,
    formatDate: String, formatDateTime: String,
    fetch: async (path, options = {}) => { requests.push({ path, options }); return intercept(path, options); },
  });
  vm.runInContext(source + '\nglobalThis.subject = { render: renderAndromedaResults };', context);
  const walk = node => [node, ...node.children.flatMap(walk)];
  return {
    requests, opens, get,
    intercept: fn => { intercept = fn; },
    render: (results = [result], category = 'all', restored = true) => context.subject.render(results, 'ready', category, restored),
    buttons: (category = 'all') => walk(get(category === 'news' ? 'andromeda-news' : 'andromeda-results'))
      .filter(node => node.tag === 'button'),
    messages: () => walk(get('andromeda-results')).filter(node => node.className === 'andromeda-library-status'),
  };
}

test('saved web and news results find the exact active or archived record without a save', async () => {
  for (const category of ['all', 'news']) for (const archived of [false, true]) {
    const h = harness();
    h.intercept(path => response({ items: path.includes('archived') === archived ? [item] : [] }));
    h.render([result], category);
    await tick();
    const button = h.buttons(category)[0];
    assert.equal(button.textContent, 'open in Library');
    await button.handlers.click();
    assert.deepEqual(h.opens, [['read', item.id]]);
    assert.equal(h.requests.length, 2);
    assert.ok(h.requests.every(({ options }) => !options.method && options.cache === 'no-store'));
  }
});

test('lookup is batched per restored result render; fresh proposals do not trigger it', async () => {
  const h = harness();
  h.render([{ ...result, id: item.id, saved: true }], 'all', false);
  await tick();
  assert.equal(h.buttons()[0].textContent, 'save to Library');
  assert.equal(h.requests.length, 0);
  h.render([result, { ...result, url: url + '&page=2' }]);
  await tick();
  assert.equal(h.requests.length, 2);
  assert.ok(h.buttons().every(button => button.textContent === 'save to Library'));
});

test('transport normalization matches a fragment but never a different query or title alone', async () => {
  for (const [storedUrl, expected] of [
    [url + '#part', 'open in Library'],
    [url.replace('edition=1', 'edition=2'), 'save to Library'],
    ['http://127.0.0.1:8000/other', 'save to Library'],
  ]) {
    const h = harness();
    h.intercept(path => response({ items: path.includes('archived') ? [] : [{ ...item, title: result.title, url: storedUrl }] }));
    h.render(); await tick();
    assert.equal(h.buttons()[0].textContent, expected);
    assert.ok(h.requests.every(({ options }) => !options.method));
  }
});

test('ambiguous, malformed and unavailable lookups never claim a confirmed saved record', async () => {
  for (const reply of [
    { items: [item, { ...item, id: 'different-record' }] },
    { items: [{ ...item, id: '../wrong' }] },
    { items: [{ ...item, id: null }] },
    { items: null },
    null,
    new Error('owned lookup unavailable'),
  ]) {
    const h = harness();
    h.intercept(path => {
      if (path.includes('archived')) return response({ items: [] });
      if (reply instanceof Error) throw reply;
      return response(reply);
    });
    h.render(); await tick();
    assert.equal(h.buttons()[0].textContent, 'save to Library');
    assert.equal(h.opens.length, 0);
    assert.ok(h.requests.every(({ options }) => !options.method));
  }
});

test('one failed shelf does not promote an incomplete lookup; explicit retry still returns the existing record', async () => {
  const h = harness();
  h.intercept((path, options) => {
    if (options.method === 'POST') return response({ item, duplicate: true });
    if (path.includes('archived')) throw new Error('unavailable');
    return response({ items: [item] });
  });
  h.render(); await tick();
  const button = h.buttons()[0];
  assert.equal(button.textContent, 'save to Library');
  await button.handlers.click();
  assert.equal(button.textContent, 'open in Library');
  assert.equal(h.messages()[0].textContent, 'already in Library');
  assert.equal(h.requests.filter(({ options }) => options.method === 'POST').length, 1);
});

test('duplicate appearances of the same identity across shelves remain unambiguous', async () => {
  const h = harness();
  h.intercept(() => response({ items: [item] }));
  h.render(); await tick();
  assert.equal(h.buttons()[0].textContent, 'open in Library');
});

test('late lookup cannot replace a save acknowledgement or resolve an uncertain save', async () => {
  for (const saveConfirmed of [true, false]) {
    const h = harness(), held = deferred();
    h.intercept((path, options) => {
      if (!options.method) return held.promise;
      return response(saveConfirmed ? { item, duplicate: false } : { item: { ...item, id: 'bad/id' } });
    });
    h.render();
    const button = h.buttons()[0];
    await button.handlers.click();
    held.resolve(response({ items: [{ ...item, id: 'stale-record' }] }));
    await tick();
    assert.equal(button.textContent, saveConfirmed ? 'open in Library' : 'save to Library');
    if (saveConfirmed) {
      await button.handlers.click();
      assert.deepEqual(h.opens, [['read', item.id]]);
    } else {
      assert.match(h.messages()[0].textContent, /retry safely/);
      assert.equal(h.opens.length, 0);
    }
  }
});

test('pending save remains busy until its own acknowledgement', async () => {
  const h = harness(), lookup = deferred(), save = deferred();
  h.intercept((path, options) => options.method ? save.promise : lookup.promise);
  h.render();
  const button = h.buttons()[0];
  const saving = button.handlers.click();
  lookup.resolve(response({ items: [item] }));
  await tick();
  assert.equal(button.textContent, 'save to Library');
  assert.equal(button.attrs['aria-disabled'], 'true');
  assert.equal(h.messages()[0].textContent, 'saving excerpt…');
  await button.handlers.click();
  assert.equal(h.requests.filter(({ options }) => options.method === 'POST').length, 1);
  save.resolve(response({ item, duplicate: true }));
  await saving;
  assert.equal(button.textContent, 'open in Library');
  assert.equal(button.attrs['aria-disabled'], 'false');
});

test('late lookup from a replaced result list cannot label the new results', async () => {
  const h = harness(), held = deferred();
  h.intercept(() => held.promise);
  h.render();
  const oldButton = h.buttons()[0];
  h.render([{ ...result, url: url + '&different=1' }], 'all', false);
  held.resolve(response({ items: [item] }));
  await tick();
  assert.equal(oldButton.textContent, 'save to Library');
  assert.equal(h.buttons()[0].textContent, 'save to Library');
  assert.equal(h.opens.length, 0);
});

test('restore never resurrects a missing record and ignores non-http proposals', async () => {
  const h = harness();
  h.render(); await tick();
  assert.equal(h.buttons()[0].textContent, 'save to Library');
  h.render([{ ...result, url: 'mailto:synthetic@example.invalid' }]);
  await tick();
  assert.equal(h.buttons().length, 0);
  assert.equal(h.opens.length, 0);
});

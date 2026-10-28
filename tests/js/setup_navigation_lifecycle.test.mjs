import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { t as i18nT, tp as i18nTp } from '../../static/js/i18n.js';

const source = readFileSync(new URL('../../static/js/setupwizard.js', import.meta.url), 'utf8')
  .replace(/import\s+[\s\S]*?from\s+['"][^'"]+['"];\r?\n/g, '')
  .replace(/^export /gm, '');
const choicesSource = readFileSync(new URL('../../static/js/kokuen.js', import.meta.url), 'utf8')
  .match(/^export function wireChoiceGroup\([^]*?^}/m)[0].replace(/^export /, '');
const providersSource = readFileSync(new URL('../../static/js/model_providers.js', import.meta.url), 'utf8')
  .replace(/import\s+[\s\S]*?from\s+['"][^'"]+['"];\r?\n/g, '')
  .replace(/^export /gm, '');
const tick = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

// Only DOM identity, selectors, focus and events are modeled. Browser gates own
// layout and native keyboard behavior. Replacing HTML really detaches old nodes.
function harness(code = source) {
  let document;
  class Element {
    constructor(tag, attrs = {}) {
      this.tagName = tag.toUpperCase(); this.attrs = attrs; this.children = [];
      this.dataset = {}; this.style = {}; this.listeners = {}; this.textContent = '';
      this.value = attrs.value || ''; this.disabled = 'disabled' in attrs;
      for (const [key, value] of Object.entries(attrs)) {
        if (key.startsWith('data-')) this.dataset[key.slice(5)] = value;
      }
    }
    get id() { return this.attrs.id || ''; }
    get isConnected() { return this === document.body || Boolean(this.parentElement?.isConnected); }
    get firstElementChild() { return this.children[0] || null; }
    contains(node) { return this === node || this.children.some(child => child.contains(node)); }
    appendChild(child) { child.parentElement = this; this.children.push(child); return child; }
    remove() {
      if (this.contains(document.activeElement)) document.activeElement = document.body;
      this.parentElement.children = this.parentElement.children.filter(child => child !== this);
      this.parentElement = null;
    }
    set innerHTML(html) {
      for (const child of [...this.children]) child.remove();
      this.html = html; this.textContent = '';
      const stack = [this];
      for (const token of html.match(/<[^>]+>|[^<]+/g) || []) {
        if (token.startsWith('</')) { if (stack.length > 1) stack.pop(); continue; }
        if (!token.startsWith('<')) { stack.at(-1).textContent += token; continue; }
        const tag = /^<([\w-]+)/.exec(token)?.[1];
        if (!tag) continue;
        const attrs = {};
        for (const match of token.slice(tag.length + 1, -1).matchAll(/([\w-]+)(?:="([^"]*)"|='([^']*)'|=([^\s>]+))?/g)) {
          attrs[match[1]] = match[2] ?? match[3] ?? match[4] ?? '';
        }
        const child = stack.at(-1).appendChild(new Element(tag, attrs));
        if (!['input', 'br', 'hr', 'img', 'meta'].includes(tag)) stack.push(child);
      }
    }
    get innerHTML() { return this.html || ''; }
    insertAdjacentHTML(position, html) {
      assert.equal(position, 'beforeend');
      const fragment = new Element('div'); fragment.innerHTML = html;
      for (const child of fragment.children) this.appendChild(child);
    }
    matches(selector) {
      if (selector.includes(':not([disabled])')) {
        if (this.disabled) return false;
        selector = selector.replace(':not([disabled])', '');
      }
      const attributes = [...selector.matchAll(/\[([^=\]]+)(?:="([^"]*)")?\]/g)];
      if (attributes.some(([, key, value]) => !(key in this.attrs) || (value !== undefined && this.attrs[key] !== value))) return false;
      const base = selector.replace(/\[[^\]]+\]/g, '');
      if (base.startsWith('#')) return this.id === base.slice(1);
      return !base || base === '*' || this.tagName.toLowerCase() === base;
    }
    querySelectorAll(selector) {
      const descendants = this.children.flatMap(child => [child, ...child.querySelectorAll('*')]);
      return descendants.filter(node => selector.split(',').some(part => node.matches(part.trim())));
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector) || null; }
    hasAttribute(key) { return key in this.attrs; }
    getAttribute(key) { return this.attrs[key] ?? null; }
    setAttribute(key, value) { this.attrs[key] = String(value); }
    removeAttribute(key) { delete this.attrs[key]; }
    focus() { if (this.isConnected && !this.disabled) document.activeElement = this; }
    addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
    async emit(type, event = {}) {
      event = { target: this, preventDefault() {}, ...event };
      for (let node = this; node; node = node.parentElement) {
        for (const listener of node.listeners[type] || []) await listener(event);
      }
    }
    click() { if (this.disabled) return Promise.resolve(); this.focus(); return this.emit('click'); }
  }
  document = { getElementById: id => document.body.querySelector('#' + id) };
  document.body = new Element('body'); document.activeElement = document.body;
  document.body.innerHTML = '<div id="setup-wizard"><button id="setup-skip">exit setup</button><div id="setup-dots"></div><div id="setup-wizard-body"></div></div>';
  const $ = id => document.getElementById(id);
  $('setup-wizard').style.display = 'flex';
  const requests = [], notices = [];
  const context = vm.createContext({ t: i18nT, tp: i18nTp,
    document, HTMLElement: Element, navigator: { language: 'en-US' }, Intl,
    resolvedTimeZone: () => 'UTC', regionName: code => code, pick: async () => null, visible: node => node.isConnected,
    setControlState() {}, toast: (...args) => notices.push(args),
    requestWithRecentOwner: (fetcher, ...args) => fetcher(...args),
    addEndpoint: async () => { throw new Error('unexpected endpoint creation'); },
    fetch: (path, options = {}) => {
      const waiting = deferred();
      requests.push({ path, method: options.method || 'GET',
        body: options.body ? JSON.parse(options.body) : null,
        resolve: payload => waiting.resolve({ ok: true, json: async () => payload }),
        refuse: message => waiting.resolve({ ok: false, json: async () => ({ message }) }),
      });
      return waiting.promise;
    },
  });
  vm.runInContext(choicesSource + '\n' + providersSource + '\n' + code + `
    _state = {
      username: 'saved owner', timezone: 'UTC', access_profile: 'device',
      public_url: '', base_domain: '', trusted_hosts: '', forwarded_allow_ips: '',
      keep_vault_inside_alles: true, vault_preview: '/synthetic/Vault', files_preview: '/synthetic/Files',
      search_provider: 'duckduckgo', searxng_url: '', automatic_backup_enabled: false,
      automatic_backup_dir: '/synthetic/Backups'
    };
    _auth = { enabled: true };
    globalThis.subject = {
      render: step => _setStep(step), state: () => _state, step: () => _step,
      current: () => _formIsCurrent(), save: (...args) => _saveStep(...args),
      update: values => Object.assign(_state, values),
    };
  `, context);
  return { $, context, document, requests, notices, ...context.subject,
    click: id => $(id).click(), root: () => $('setup-wizard-body').firstElementChild,
  };
}

test('form ownership expires on Back/new body or closing the modal', async () => {
  const h = harness(); h.render(1);
  const first = h.current(); assert.equal(first(), true);
  await h.click('sw-back'); assert.equal(first(), false);
  const second = h.current(); assert.equal(second(), true);
  h.$('setup-wizard').style.display = 'none'; assert.equal(second(), false);
});

test('a stale step response cannot replace newer setup state; current saves still update it', async () => {
  const h = harness(); h.render(1);
  const saved = h.state(), current = h.current();
  const stale = h.save('access', { profile: 'device' }, current);
  await h.click('sw-back'); h.update({ username: 'newer owner' });
  h.requests[0].resolve({ setup: { username: 'stale owner' } }); await stale;
  assert.equal(h.state(), saved); assert.equal(h.state().username, 'newer owner');
  const fresh = h.save('basics', { username: 'accepted' });
  h.requests[1].resolve({ setup: { username: 'accepted' } }); await fresh;
  assert.equal(h.state().username, 'accepted');
});

for (const outcome of ['success', 'failure']) {
  test(`an Access save ${outcome} arriving after Back leaves the newer form and status untouched`, async () => {
    const h = harness(); h.render(1);
    const saving = h.click('sw-save'); await tick();
    assert.equal(h.requests[0].body.step, 'access');
    await h.click('sw-back');
    const newer = h.root(), state = h.state();
    h.$('sw-name').value = 'unsaved newer name';
    if (outcome === 'success') h.requests[0].resolve({ setup: { ...state, username: 'old response' } });
    else h.requests[0].refuse('stale refusal');
    await saving;
    assert.equal(h.root(), newer); assert.equal(h.step(), 0);
    assert.equal(h.state(), state); assert.equal(h.$('sw-name').value, 'unsaved newer name');
    assert.equal(h.$('sw-status').textContent, '');
  });
}

test('a Files save finishing after Back cannot fetch companion status or advance the form', async () => {
  const h = harness(); h.render(2);
  const saving = h.click('sw-save'); await tick();
  await h.click('sw-back'); const newer = h.root(), state = h.state();
  h.requests[0].resolve({ setup: { ...state, files_preview: '/synthetic/late' } }); await saving;
  assert.equal(h.requests.length, 1); assert.equal(h.root(), newer);
  assert.equal(h.step(), 1); assert.equal(h.state(), state);
});

for (const outcome of ['success', 'failure']) {
  test(`a late companion status ${outcome} cannot repaint Files over Access`, async () => {
    const h = harness(); h.render(2);
    const saving = h.click('sw-save'); await tick();
    h.requests[0].resolve({ setup: { ...h.state(), files_companion_pending: true } }); await tick();
    assert.equal(h.requests[1].path, '/api/setup/obsidian');
    await h.click('sw-back'); const newer = h.root(), focused = h.document.activeElement;
    if (outcome === 'success') h.requests[1].resolve({ companion_installed: false });
    else h.requests[1].refuse('late companion refusal');
    await saving;
    assert.equal(h.root(), newer); assert.equal(h.step(), 1);
    assert.equal(h.document.activeElement, focused); assert.equal(h.$('sw-status').textContent, '');
  });
}

test('Files intermediate save replaces old controls and focuses a connected control in the new form', async () => {
  const h = harness(); h.render(2);
  const oldButton = h.$('sw-save'), oldRoot = h.root();
  const saving = h.click('sw-save'); await tick();
  h.requests[0].resolve({ setup: { ...h.state(), files_companion_pending: true } }); await tick();
  h.requests[1].resolve({ companion_installed: false }); await saving;
  assert.notEqual(h.root(), oldRoot); assert.equal(oldButton.isConnected, false);
  assert.equal(h.step(), 2); assert.ok(h.$('sw-install-obsidian'));
  assert.ok(h.$('setup-wizard-body').contains(h.document.activeElement));
  assert.equal(h.document.activeElement.isConnected, true);
  assert.equal(h.$('sw-save').disabled, false);
});

test('click and End on selected SearXNG preserve its draft; changing choice still works', async () => {
  const h = harness(); h.update({ search_provider: 'searxng', searxng_url: 'https://saved.invalid' }); h.render(3);
  const field = h.$('sw-searxng-url'); field.value = 'https://draft.invalid';
  const group = h.$('sw-search'), selected = group.querySelector('[data-value="searxng"]');
  await selected.click(); assert.equal(h.$('sw-searxng-url'), field);
  await selected.emit('keydown', { key: 'End' }); await tick();
  assert.equal(h.$('sw-searxng-url'), field); assert.equal(field.value, 'https://draft.invalid');
  await group.querySelector('[data-value="duckduckgo"]').click();
  assert.equal(h.$('sw-searxng-url'), null);
  await selected.click(); assert.ok(h.$('sw-searxng-url'));
});

test('reselecting Public access preserves all unsaved policy fields', async () => {
  const h = harness(); h.update({ access_profile: 'public' }); h.render(1);
  const fields = ['sw-public-url', 'sw-base-domain', 'sw-trusted-hosts', 'sw-proxies']
    .map(id => { const node = h.$(id); node.value = 'unsaved-' + id; return node; });
  const selected = h.$('sw-access').querySelector('[data-value="public"]');
  await selected.click(); await selected.emit('keydown', { key: 'End' }); await tick();
  for (const field of fields) { assert.equal(h.$(field.id), field); assert.equal(field.value, 'unsaved-' + field.id); }
});

test('reselecting a provider preserves URL and key drafts; choosing another provider updates fields', async () => {
  const h = harness(); h.render(3);
  const providers = h.$('sw-models').querySelectorAll('[role="option"]');
  await providers[0].click();
  const url = h.$('sw-model-url'), key = h.$('sw-model-key');
  url.value = 'https://synthetic.invalid/v1'; key.value = 'synthetic-not-a-secret';
  await providers[0].click();
  assert.equal(h.$('sw-model-url'), url); assert.equal(h.$('sw-model-key'), key);
  assert.equal(url.value, 'https://synthetic.invalid/v1'); assert.equal(key.value, 'synthetic-not-a-secret');
  await providers[1].click();
  assert.notEqual(h.$('sw-model-url'), url); assert.equal(h.$('sw-model-key').value, '');
  assert.equal(providers[1].getAttribute('aria-selected'), 'true');
  assert.equal(providers[0].getAttribute('aria-selected'), 'false');
});

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(process.env.A17_MAIL_SOURCE || new URL('../../static/js/mail.js', import.meta.url), 'utf8');
const functionSource = name => {
  const match = source.match(new RegExp(`^(?:export )?(?:async )?function ${name}\\([^]*?^}`, 'm'));
  assert.ok(match, `${name} exists`);
  return match[0].replace(/^export /, '');
};
const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};

// A small DOM double for focus, connection and event ownership, not a layout renderer.
function harness() {
  let document;
  class Node {
    constructor(tag = 'div', attrs = {}) {
      this.tagName = tag.toUpperCase(); this.attrs = attrs; this.children = []; this.dataset = {};
      this.listeners = {}; this.style = {}; this.scrollTop = 0; this.value = attrs.value || '';
      this.disabled = 'disabled' in attrs; this.hidden = 'hidden' in attrs; this.textContent = '';
      for (const [key, value] of Object.entries(attrs)) if (key.startsWith('data-')) this.dataset[key.slice(5)] = value;
      this.classList = { toggle() {}, add() {}, remove() {} };
    }
    get className() { return this.attrs.class || ''; }
    set className(value) { this.attrs.class = value; }
    get isConnected() { return this === document.body || Boolean(this.parentElement?.isConnected); }
    get firstElementChild() { return this.children[0]; }
    contains(node) { return this === node || this.children.some(child => child.contains(node)); }
    appendChild(child) { child.parentElement = this; this.children.push(child); return child; }
    prepend(child) { child.parentElement = this; this.children.unshift(child); }
    remove() {
      if (this.contains(document.activeElement)) document.activeElement = document.body;
      this.parentElement.children = this.parentElement.children.filter(child => child !== this);
      this.parentElement = null;
    }
    replaceChildren() { for (const child of [...this.children]) child.remove(); this.textContent = ''; }
    set innerHTML(html) {
      this.replaceChildren(); this.html = html;
      const stack = [this];
      for (const token of html.match(/<[^>]+>|[^<]+/g) || []) {
        if (token.startsWith('</')) { if (stack.length > 1) stack.pop(); continue; }
        if (!token.startsWith('<')) { stack.at(-1).textContent += token; continue; }
        const tag = /^<([\w-]+)/.exec(token)?.[1]; if (!tag) continue;
        const attrs = {};
        for (const match of token.slice(tag.length + 1, -1).matchAll(/([\w-]+)(?:="([^"]*)"|='([^']*)'|=([^\s>]+))?/g)) attrs[match[1]] = match[2] ?? match[3] ?? match[4] ?? '';
        const child = stack.at(-1).appendChild(new Node(tag, attrs));
        if (!['input', 'br', 'meta', 'img', 'hr'].includes(tag)) stack.push(child);
      }
    }
    get innerHTML() { return this.html || ''; }
    matches(selector) {
      if (selector.endsWith(':not(:disabled)')) return !this.disabled && this.matches(selector.slice(0, -15));
      const attribute = /\[([^=\]]+)(?:="?([^"\]]+)"?)?\]/.exec(selector);
      if (attribute && (!(attribute[1] in this.attrs) || (attribute[2] != null && this.attrs[attribute[1]] !== attribute[2]))) return false;
      const base = selector.replace(/\[[^\]]+\]/g, '');
      if (base.startsWith('#')) return this.attrs.id === base.slice(1);
      if (base.startsWith('.')) return this.className.split(' ').includes(base.slice(1));
      return !base || this.tagName.toLowerCase() === base;
    }
    querySelectorAll(selector) {
      const all = this.children.flatMap(child => [child, ...child.querySelectorAll('*')]);
      return selector === '*' ? all : all.filter(node => selector.split(',').some(part => node.matches(part.trim())));
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector) || null; }
    getClientRects() { return this.isConnected && !this.hidden ? [{}] : []; }
    setAttribute(key, value) { this.attrs[key] = value; }
    getAttribute(key) { return this.attrs[key] ?? null; }
    focus() { document.activeElement = this; }
    scrollIntoView(options) { this.scrolled = options; }
    addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
    async emit(type, event = {}) { for (const fn of this.listeners[type] || []) await fn(event); if (type === 'click') await this.onclick?.(event); }
  }
  document = { createElement: tag => new Node(tag), getElementById: id => document.body.querySelector('#' + id) };
  document.body = new Node('body'); document.activeElement = document.body;
  document.body.innerHTML = '<div id="mail-view"><button id="mail-compose-btn">compose</button><input id="mail-search"><div class="mail-layout"><div id="mail-list"></div><div id="mail-main"></div></div></div>';
  const $ = id => document.getElementById(id);
  const requests = [], confirms = [], changes = [], pending = { request_id: 'pending-save' };
  let confirmation = false;
  const context = vm.createContext({
    document, $, console, URL, location: { href: 'http://synthetic.invalid/?view=mail' },
    esc: value => String(value ?? ''), readRecordTarget: () => null, acctName: () => 'synthetic',
    resolvedTimeZone: () => 'UTC', _si: () => '',
    fromName: value => value, _accountEditor: null, _acEl: null, _mailErrors: [],
    _hideAc: () => { context._acEl = null; }, dlgConfirm: text => { confirms.push(text); return confirmation; },
    mailJson: url => {
      if (url === '/api/mail/vips') return Promise.resolve({ vips: [] });
      const result = deferred(); requests.push({ ...result, url }); return result.promise;
    },
    loadAttachments() {}, mailIdentity: (...args) => JSON.stringify(args),
    changeMail: (...args) => changes.push(args), _mailChanges: new Map(),
    _reloadCurrent: options => { context.retried = options; },
    _accounts: [{ id: 'synthetic' }], _active: 'synthetic', _draftReady: true, _outboxReady: true,
    _draftScopes: ['synthetic-scope'], _outboxScopes: ['synthetic-outbox'],
    _draftPending: pending, _outboxPending: null, _outboxOperation: null,
    _wireRichCompose() {}, _loadAddrBook() {}, paintDraftRecovery() {}, paintOutbox() {},
    getDropdownValue: () => '', serializeForm: root => root.querySelector('#mc-html').innerHTML,
    _initChipField: node => { node._add = value => { node.querySelector('input[type=hidden]').value = value; }; },
  });
  const editorCode = source.slice(source.indexOf('let _messageGeneration'), source.indexOf('let _inited'));
  vm.runInContext(editorCode.replace(/^export /gm, '') + '\n' + functionSource('openMessage') + '\n' + functionSource('compose') + '\nglobalThis.api = { openMessage, compose, mailEditor };', context);
  function rows(entries) {
    $('mail-list').innerHTML = entries.map(({ uid, id, folder = 'INBOX' }) => `<div class="mail-row" ${id ? `data-id="${id}"` : `data-aid="synthetic" data-uid="${uid}" data-folder="${folder}"`}><button class="mail-open">${id || uid}</button></div>`).join('');
    return $('mail-list').querySelectorAll('.mail-open');
  }
  return { context, document, $, rows, requests, confirms, changes, pending, ...context.api,
    confirm: value => { confirmation = value; },
    back: () => $('mail-main').querySelector('.mail-pane-back'),
    open: (uid, trigger) => context.api.openMessage('synthetic', uid, 'INBOX', null, undefined, trigger),
  };
}
const message = uid => ({ uid, from: 'sender@synthetic.invalid', to: 'owner@synthetic.invalid', subject: `message ${uid}`, text: 'synthetic body', html: '', date: '' });
const escape = () => ({ key: 'Escape', preventDefault() { this.defaultPrevented = true; }, stopPropagation() {} });

test('opening a message focuses loading content; back cancels its late response and returns to the exact row', async () => {
  const h = harness(), [other, opener] = h.rows([{ uid: 'other' }, { uid: 'wanted' }]);
  other.focus(); // pointer row opens must not depend on the last keyboard focus.
  const opening = h.open('wanted', opener); await tick();
  assert.ok(h.back()); assert.equal(h.document.activeElement, h.$('mail-main').firstElementChild);
  await h.back().emit('click');
  assert.equal(h.document.activeElement, opener); assert.equal(h.$('mail-main').children.length, 0);
  h.requests[0].resolve(message('wanted')); await opening;
  assert.equal(h.$('mail-main').children.length, 0); assert.equal(h.changes.length, 0);
});

test('reader completion focuses the subject and back finds the same identity after a list refresh', async () => {
  const h = harness(), [opener] = h.rows([{ uid: 'wanted' }]);
  const opening = h.open('wanted', opener); await tick();
  h.requests[0].resolve(message('wanted')); await opening;
  assert.equal(h.document.activeElement, h.$('mail-main').querySelector('.mail-reader-subject'));
  const [, same, wrongFolder] = h.rows([{ uid: 'other' }, { uid: 'wanted' }, { uid: 'wanted', folder: 'Sent' }]);
  await h.back().emit('click');
  assert.equal(h.document.activeElement, same); assert.notEqual(h.document.activeElement, wrongFolder);
});

test('an older response cannot replace the current reader or its return target', async () => {
  const h = harness(), [one, two] = h.rows([{ uid: 'one' }, { uid: 'two' }]);
  const first = h.open('one', one); await tick(); const second = h.open('two', two); await tick();
  h.requests[1].resolve(message('two')); await second;
  h.requests[0].resolve(message('one')); await first;
  assert.equal(h.$('mail-main').querySelector('.mail-reader-subject').textContent, 'message two');
  await h.back().emit('click'); assert.equal(h.document.activeElement, two);
});

test('a message finishing in the background leaves focus moved to the header alone', async () => {
  const h = harness(), [opener] = h.rows([{ uid: 'one' }]);
  const opening = h.open('one', opener); await tick(); h.$('mail-search').focus();
  h.requests[0].resolve(message('one')); await opening;
  assert.equal(h.document.activeElement, h.$('mail-search'));
});

test('message failure keeps a working back path and retry keeps the original row target', async () => {
  const h = harness(), [opener] = h.rows([{ uid: 'one' }]);
  const opening = h.open('one', opener); await tick(); h.requests[0].reject(new Error('offline')); await opening;
  assert.equal(h.document.activeElement, h.$('mail-message-retry')); assert.ok(h.back());
  const retry = h.$('mail-message-retry').emit('click'); await tick(); h.requests[1].resolve(message('one')); await retry;
  await h.back().emit('click'); assert.equal(h.document.activeElement, opener);
});

test('draft back, close and Escape share the unsaved-change guard; cancellation retains pending recovery', async () => {
  for (const action of ['back', 'close', 'escape']) {
    const h = harness(), [opener] = h.rows([{ id: 'draft-one' }]); opener.focus();
    const editor = await h.compose({ id: 'draft-one', body: 'saved text' });
    assert.equal(h.document.activeElement, h.$('mc-subj'));
    h.$('mc-html').innerHTML = 'new unsent text';
    if (action === 'back') await h.back().emit('click');
    else if (action === 'close') await h.$('mc-close').emit('click');
    else { await editor.root.emit('keydown', escape()); await tick(); }
    assert.equal(h.confirms.length, 1, action); assert.equal(h.mailEditor(), editor);
    assert.equal(h.$('mc-html').innerHTML, 'new unsent text'); assert.equal(h.context._draftPending, h.pending);
    h.confirm(true); await h.back().emit('click'); assert.equal(h.document.activeElement, opener);
    assert.equal(h.context._draftPending, h.pending);
  }
});

test('edits made while confirming departure prevent the older confirmation from closing the draft', async () => {
  const h = harness(), [opener] = h.rows([{ id: 'draft-one' }]); opener.focus();
  await h.compose({ id: 'draft-one', body: 'saved' }); h.$('mc-html').innerHTML = 'first edit';
  const confirm = deferred(); h.confirm(confirm.promise);
  const back = h.back().emit('click'); await tick(); h.$('mc-html').innerHTML = 'later edit';
  confirm.resolve(true); await back; assert.equal(h.$('mc-html').innerHTML, 'later edit'); assert.ok(h.mailEditor());
});

test('Escape closes autocomplete first and respects keys already handled by a child control', async () => {
  const h = harness(); h.$('mail-compose-btn').focus(); const editor = await h.compose({ body: 'text' });
  h.context._acEl = {}; await editor.root.emit('keydown', escape()); await tick();
  assert.equal(h.context._acEl, null); assert.equal(h.mailEditor(), editor);
  await editor.root.emit('keydown', { ...escape(), defaultPrevented: true }); await tick();
  assert.equal(h.mailEditor(), editor); assert.equal(h.confirms.length, 0);
});

test('connection warning and retry remain available without replacing an unsaved editor', async () => {
  const h = harness(); h.context._mailErrors = ['showing saved mail; synthetic connection unavailable'];
  h.$('mail-compose-btn').focus(); const editor = await h.compose({ body: 'saved text' });
  h.$('mc-html').innerHTML = 'keep this';
  const warning = h.$('mail-main').querySelector('.mail-pane-warning');
  assert.equal(warning.hidden, false); assert.match(warning.querySelector('p').textContent, /showing saved mail/);
  await warning.querySelector('button').emit('click');
  assert.equal(h.context.retried.force, true); assert.equal(h.mailEditor(), editor);
  assert.equal(h.$('mc-html').innerHTML, 'keep this');
});

test('reply keeps the message return target and an untouched saved draft returns to its refreshed row', async () => {
  const h = harness(), [opener] = h.rows([{ uid: 'one' }]);
  const opening = h.open('one', opener); await tick(); h.requests[0].resolve(message('one')); await opening;
  h.$('mail-reply').focus(); await h.$('mail-reply').emit('click'); await tick();
  assert.ok(h.mailEditor()); await h.back().emit('click'); assert.equal(h.document.activeElement, opener);
  const [draft] = h.rows([{ id: 'saved-draft' }]); draft.focus();
  await h.compose({ id: 'saved-draft', body: 'unchanged draft' });
  const [, refreshed] = h.rows([{ id: 'other-draft' }, { id: 'saved-draft' }]);
  await h.$('mc-close').emit('click');
  assert.equal(h.document.activeElement, refreshed); assert.equal(h.confirms.length, 0);
});

test('back from a new compose restores the compose trigger; removed rows have a usable fallback', async () => {
  const h = harness(); h.$('mail-compose-btn').focus(); await h.compose({ body: 'signature' });
  await h.back().emit('click'); assert.equal(h.document.activeElement, h.$('mail-compose-btn'));
  const [opener] = h.rows([{ uid: 'one' }]);
  const opening = h.open('one', opener); await tick(); h.requests[0].resolve(message('one')); await opening;
  const [remaining] = h.rows([{ uid: 'two' }]); await h.back().emit('click');
  assert.equal(h.document.activeElement, remaining);
});

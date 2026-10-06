// Small DOM double for event and ownership checks; this does not render layout.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
export const mailSource = readFileSync(new URL('../../../static/js/mail.js', import.meta.url), 'utf8');
export const captureSource = readFileSync(new URL('../../../static/js/capture.js', import.meta.url), 'utf8');
export const tick = () => new Promise(resolve => setImmediate(resolve));
export function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
export function functionSource(name, source = mailSource) {
  const match = source.match(new RegExp(`^(?:export )?(?:async )?function ${name}\\([^]*?^}`, 'm'));
  assert.ok(match, `${name} exists`);
  return match[0].replace(/^export /, '');
}
const storage = () => {
  const values = new Map();
  return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
};
export const scope = 'a'.repeat(64);
export const account = { id: 'synthetic', email: 'owner@example.invalid', name: 'synthetic', imap_host: '', imap_port: 993, smtp_host: '', smtp_port: 587, username: '', use_ssl: true, revision: 1 };
export function harness() {
  let document;
  class Node {
    constructor(tag = 'div', attrs = {}) {
      this.tagName = tag.toUpperCase(); this.attrs = attrs; this.children = []; this.dataset = {};
      this.listeners = {}; this.style = {}; this.scrollTop = 0; this.value = attrs.value || '';
      this.disabled = 'disabled' in attrs; this.hidden = 'hidden' in attrs; this.textContent = '';
      for (const [key, value] of Object.entries(attrs)) if (key.startsWith('data-')) this.dataset[key.slice(5)] = value;
      this.classList = { toggle() {}, add() {}, remove() {} };
    }
    get id() { return this.attrs.id || ''; }
    get isContentEditable() { return this.attrs.contenteditable === 'true'; }
    get innerText() { return this.textContent; }
    get className() { return this.attrs.class || ''; }
    set className(value) { this.attrs.class = value; }
    get isConnected() { return this === document.body || Boolean(this.parentElement?.isConnected); }
    get firstElementChild() { return this.children[0] || null; }
    contains(node) { return this === node || this.children.some(child => child.contains(node)); }
    appendChild(child) { child.parentElement = this; this.children.push(child); return child; }
    prepend(child) { child.parentElement = this; this.children.unshift(child); }
    remove() {
      if (this.contains(document.activeElement)) document.activeElement = document.body;
      if (!this.parentElement) return;
      this.parentElement.children = this.parentElement.children.filter(child => child !== this);
      this.parentElement = null;
    }
    replaceChildren() { for (const child of [...this.children]) child.remove(); this.textContent = ''; }
    set innerHTML(html) {
      this.replaceChildren(); this.html = html;
      const stack = [this];
      for (const token of html.match(/<[^>]+>|[^<]+/g) || []) {
        if (token.startsWith('</')) { if (stack.length > 1) stack.pop(); continue; }
        if (!token.startsWith('<')) { const node = stack.at(-1); node.textContent += token; if (node.tagName === 'TEXTAREA') node.value += token; continue; }
        const tag = /^<([\w-]+)/.exec(token)?.[1]; if (!tag) continue;
        const attrs = {};
        for (const match of token.slice(tag.length + 1, -1).matchAll(/([\w-]+)(?:="([^"]*)"|='([^']*)'|=([^\s>]+))?/g)) attrs[match[1]] = match[2] ?? match[3] ?? match[4] ?? '';
        const child = stack.at(-1).appendChild(new Node(tag, attrs));
        if (!['input', 'br', 'meta', 'img', 'hr'].includes(tag)) stack.push(child);
      }
    }
    get innerHTML() { return this.html ?? this.textContent; }
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
    getBoundingClientRect() { return { left: 0, top: 0, bottom: 40, width: 300 }; }
    dispatchEvent(event) { return this.emit(event.type, event); }
    getClientRects() { return this.isConnected && !this.hidden ? [{}] : []; }
    setAttribute(key, value) { this.attrs[key] = value; }
    getAttribute(key) { return this.attrs[key] ?? null; }
    focus() { document.activeElement = this; }
    scrollIntoView(options) { this.scrolled = options; }
    addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
    async emit(type, event = {}) { event = { target: this, currentTarget: this, preventDefault() {}, stopPropagation() {}, ...event }; for (const fn of this.listeners[type] || []) await fn(event); if (type === 'click') await this.onclick?.(event); }
  }
  document = { createElement: tag => new Node(tag), getElementById: id => document.body.querySelector('#' + id) };
  document.body = new Node('body'); document.activeElement = document.body;
  document.body.innerHTML = '<div id="mail-view"><button id="mail-compose-btn">compose</button><input id="mail-search"><div id="mail-outbox-recovery"></div><div id="mail-scheduled"></div><div class="mail-layout"><div id="mail-list"></div><div id="mail-main"></div></div></div>';
  document.querySelectorAll = selector => document.body.querySelectorAll(selector);
  document.querySelector = selector => document.body.querySelector(selector);
  const $ = id => document.getElementById(id);
  const notices = [], confirms = [], writes = [], timers = [];
  let confirmation = false, uuid = 0;
  const context = vm.createContext({
    document, $, console, URL, Date, JSON, AbortSignal, CSS: { escape: String },
    Event: class { constructor(type) { this.type = type; } },
    setTimeout: fn => { timers.push(fn); return timers.length; }, clearTimeout() {},
    requestAnimationFrame() {}, window: { addEventListener() {} },
    location: { href: 'http://synthetic.invalid/?view=mail' },
    esc: value => String(value ?? ''), readRecordTarget: () => null, acctName: () => 'synthetic',
    resolvedTimeZone: () => 'UTC', _si: () => '', formatDate: String, formatTime: String,
    fromName: value => value, _accountEditor: null, _mailErrors: [],
    dlgConfirm: text => { confirms.push(text); return confirmation; }, toast: (...args) => notices.push(args),
    mailJson: async url => {
      if (url === '/api/mail/accounts') return [account];
      if (url === '/api/mail/vips') return { vips: [] };
      if (url === '/api/mail/rules') return { rules: [], recovery_scopes: [scope] };
      if (url === '/api/mail/vacation') return { enabled: false, subject: '', body: '' };
      throw new Error(`unhandled synthetic request ${url}`);
    },
    fetch: async url => {
      if (url === '/api/settings') return { json: async () => ({ mail_signature: '' }) };
      throw new Error(`unhandled synthetic fetch ${url}`);
    },
    loadAttachments() {}, mailIdentity: (...args) => JSON.stringify(args),
    changeMail() {}, _mailChanges: new Map(), _reloadCurrent: async () => {},
    _accounts: [account], _active: account.id, _draftReady: true, _draftScopes: [scope],
    _draftPending: null, _draftBusy: false, _draftReadError: '', _draftStorageError: '',
    _wireRichCompose() {}, paintDraftRecovery() {}, _renderScheduled: async () => {},
    getDropdownValue: node => node?.value || '', populateDropdown: (node, choices, value) => { node.value = value; },
    draftHtml: node => node?.innerHTML || '', draftPreview: value => value,
    savedText: value => value.trim(), savedRequestId: () => `00000000-0000-4000-8000-${String(++uuid).padStart(12, '0')}`,
    reminderTimeFromWall: value => new Date(value + 'Z'), _dpInit() {},
    storePendingDraft: (pending, editor, snapshot) => { writes.push({ pending, snapshot }); editor.pending = pending; editor.pendingSnapshot = snapshot; context._draftPending = pending; },
    savePendingDraft: async () => {}, submitOutgoing: async () => {},
    initMail() {}, showPendingCapture() {}, startMailPoll: async () => {}, syncAccountSelect() {},
    _mailLoadGeneration: 0, _listGeneration: 0, _listContext: '', _lastMsgs: [], _filter: 'inbox', _searchView: '', _labelFilter: '',
    loadDraftRecovery: async () => ({ drafts: [], recovery_scopes: [scope] }), _renderSavedBar() {},
    searchMail: async () => {}, loadCachedMail: async () => {}, loadInbox: async () => {},
    localStorage: storage(), sessionStorage: storage(),
    _accountRecovery: { scopes: [scope], write: null, pending: null, error: '', notice: '' },
    accountRecoveryHtml: '<p id="ma-recovery-status"></p><div id="ma-recovery-actions"></div>',
    readAccountContext: async () => ({ accounts: [account], recovery_scopes: [scope] }), readAccountRecovery() {},
    mountAccountRecovery: () => () => {}, providerHelpHtml: () => '', PRESETS: [], providerForEmail: () => null,
    accountSnapshot: value => JSON.stringify(value), renderOauthBox() {},
    _vacationWrite: null, mailPost: async (url, body) => body,
    _addrBook: [{ email: 'chosen@example.invalid', name: 'Chosen' }],
    pendingStore: async () => ({ pending: null, clear() {}, put() {} }), active: false,
    initDatePickers() {}, createFocusBoundary: () => ({ activate() {}, deactivate() {}, destroy() {} }),
  });
  const run = code => vm.runInContext(code, context);
  const add = (name, source = mailSource) => run(functionSource(name, source));
  run(mailSource.slice(mailSource.indexOf('let _messageGeneration'), mailSource.indexOf('let _inited')).replace(/^export /gm, ''));
  run(mailSource.slice(mailSource.indexOf('const OUTGOING_PREFIX'), mailSource.indexOf('function paintOutbox')));
  run(mailSource.slice(mailSource.indexOf('let _ruleWrite'), mailSource.indexOf('function mountRuleEditor')));
  run("let _acEl = null, _acIdx = -1, _acAdd = null; const _validEmail = value => /^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$/.test(value);");
  // One-line declarations require their complete source line, not the multiline extractor.
  run(mailSource.split('\n').find(line => line.startsWith('function _hideAc()')));
  for (const name of ['_loadAddrBook', '_showAc', '_acNav', '_acPick', '_initChipField', 'serializeForm', 'compose', 'openMessage', 'loadMail', 'accountsPanel', 'acctForm', 'mountRuleEditor', 'rulesPanel', 'loadCategory', 'loadByLabel', 'loadSmart', 'loadDrafts', 'cancelOutgoing', 'finishOutgoing', 'paintOutbox']) add(name);
  for (const name of ['commitMailRecipients', 'clearMailReader']) if (mailSource.includes(`function ${name}(`)) add(name);
  add('openCaptureReview', captureSource);
  run(`_outboxScopes = ['${scope}']; _outboxReady = true;`);
  return { context, run, add, document, $, notices, confirms, writes, timers,
    confirm: value => { confirmation = value; },
    generation: () => run('_messageGeneration'),
    click: node => node.emit('click'),
  };
}
export const message = uid => ({ uid, from: 'sender@example.invalid', to: 'owner@example.invalid', subject: `message ${uid}`, text: 'synthetic body', html: '', date: '' });
export async function reader(h, uid = 'one') {
  h.context.verifiedMessage = message(uid);
  await h.run(`openMessage('synthetic', '${uid}', 'INBOX', verifiedMessage)`);
  return h.$('mail-main').firstElementChild;
}
export const proposal = { kind: 'task', candidate: { title: 'synthetic task', priority: 0, notes: '' }, source: { kind: 'mail', label: 'synthetic source', excerpt: 'exact synthetic body' } };

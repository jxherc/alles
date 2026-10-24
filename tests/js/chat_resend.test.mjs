import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const read = name => readFileSync(new URL(`../../static/js/${name}.js`, import.meta.url), 'utf8');
const sessions = read('sessions');
const chat = read('chat');
const app = read('app');
// edit / regenerate wiring, with the lazy chat.js import swapped for a stub
const wiring = sessions.slice(sessions.indexOf('// once per button'), sessions.indexOf('// lazy md render'))
  .replaceAll("import('./chat.js')", 'chatModule()');
const resend = chat.match(/^export function resendMessage\([^]*?^}/m)[0].replace(/^export /, '');
const stream = chat.slice(chat.indexOf('async function streamReply'));

// just enough DOM: rows in a list, buttons and bubbles inside them
class Node {
  constructor(className = '', text = '') {
    this.className = className; this.textContent = text; this.children = []; this.parentNode = null;
    this.dataset = {}; this.listeners = {}; this.tabIndex = 0; this.style = {}; this.attrs = {};
    this.scrollHeight = 40;
  }
  get isConnected() { return this.parentNode ? this.parentNode.isConnected : this.root === true; }
  get siblings() { return this.parentNode?.children || []; }
  get previousElementSibling() { return this.siblings[this.siblings.indexOf(this) - 1] || null; }
  get nextElementSibling() { return this.siblings[this.siblings.indexOf(this) + 1] || null; }
  get lastElementChild() { return this.children.at(-1) || null; }
  append(...nodes) { for (const node of nodes) { node.remove(); node.parentNode = this; this.children.push(node); } return this; }
  appendChild(node) { this.append(node); return node; }
  remove() { if (this.parentNode) { this.siblings.splice(this.siblings.indexOf(this), 1); this.parentNode = null; } }
  after(node) { node.remove(); node.parentNode = this.parentNode; this.siblings.splice(this.siblings.indexOf(this) + 1, 0, node); }
  contains(node) { for (let at = node; at; at = at.parentNode) if (at === this) return true; return false; }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  removeAttribute(name) { delete this.attrs[name]; }
  replaceWith(node) { const at = this.siblings.indexOf(this); node.remove(); node.parentNode = this.parentNode; this.siblings[at] = node; this.parentNode = null; }
  matches(selector) {
    return selector.split(',').some(part => {
      const [cls, attr] = part.trim().replace(/^#messages\s*>?\s*/, '').split('[');
      if (attr) {
        const key = attr.replace(/]$/, '').replace(/^data-/, '').replace(/-(\w)/g, (_, c) => c.toUpperCase());
        if (!this.dataset[key]) return false;
      }
      return cls.split('.').filter(Boolean).every(name => this.className.split(' ').includes(name));
    });
  }
  descendants() { return this.children.flatMap(child => [child, ...child.descendants()]); }
  querySelectorAll(selector) { return this.descendants().filter(node => node.matches(selector)); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) { for (let node = this; node; node = node.parentNode) if (node.matches(selector)) return node; return null; }
  addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); }
  async fire(type, event = {}) {
    const fired = { stopped: false, stopPropagation() { this.stopped = true; }, preventDefault() {}, ...event };
    for (const callback of this.listeners[type] || []) await callback(fired);
    return fired;
  }
  focus() { Node.doc.activeElement = this; }
}

function userRow(text, id = '') {
  const row = new Node('msg-row');
  if (id) row.dataset.msgId = id;
  const wrap = new Node('user-wrap');
  wrap.append(new Node('user-bubble', text), new Node('user-actions').append(new Node('msg-edit-btn')));
  return row.append(wrap);
}

function aiRow(text, id = '') {
  const row = new Node('msg-row');
  if (id) row.dataset.msgId = id;
  const wrap = new Node('ai-wrap');
  wrap.append(new Node('ai-body', text), new Node('msg-actions').append(new Node('msg-regen-btn act-btn')));
  return row.append(wrap);
}

const tick = () => new Promise(resolve => setTimeout(resolve, 0));

// the server takes or refuses the edit; `gate` holds its answer back
function harness({ history = [], busy = false, online = true, refuse = false, gate = null, busyAfter = Infinity, coarse = false, reread = null, stored = null, incognito = false } = {}) {
  const state = { busy, checks: 0, incognito };
  const list = new Node('messages');
  const composer = new Node('composer-ta');
  const document = {
    activeElement: null,
    body: Object.assign(new Node('body'), { classList: { contains: name => state.busy && name === 'aide-working' } }),
    getElementById: id => ({ messages: list, 'composer-ta': composer }[id] || null),
    querySelectorAll: selector => list.querySelectorAll(selector),
    createElement: tag => Object.assign(new Node(), { tag, value: '' }),
  };
  list.root = true;
  Node.doc = document;
  const calls = { fetch: [], resend: [], send: [], toast: [], reread: [] };
  const storage = { data: stored ? { 'aide-edit-drafts-v1': JSON.stringify(stored) } : {}, getItem(k) { return this.data[k] ?? null; }, setItem(k, v) { this.data[k] = v; } };
  const context = vm.createContext({
    document,
    sessionStorage: storage,
    isIncognitoMode: () => state.incognito,
    Event: class { constructor(type, init) { this.type = type; Object.assign(this, init); } },
    rereadActiveSession: async (sid, options = {}) => { calls.reread.push(sid); calls.rereadAfter = options.afterTurn; reread?.(list); return true; },
    _activeId: 's1',
    setTimeout: (callback, ms) => setTimeout(callback, Math.min(ms, 5)),
    matchMedia: query => ({ matches: coarse && query === '(pointer: coarse)' }),
    toast: (message, kind) => calls.toast.push([message, kind]),
    plainError: message => message,
    fetch: async (url, options = {}) => {
      calls.fetch.push([url, options.body ? JSON.parse(options.body) : null]);
      if (!online) throw new TypeError('Failed to fetch');
      if (url.endsWith('/history')) return { ok: true, json: async () => ({ messages: history }) };
      return { ok: true, json: async () => ({ ok: true }) };
    },
    chatModule: async () => ({
      canSendMessage: () => !state.busy && ++state.checks <= busyAfter,
      resendMessage: async (row, text, options) => {
        calls.resend.push([row, text, { edit: !!options.edit, newestId: options.newestId }]);
        await gate;
        if (refuse) return refuse === true ? 'refused' : refuse;
        const reply = aiRow('new reply');
        row.after(reply);
        options.onAccepted(reply);
        return 'accepted';
      },
      sendMessage: text => calls.send.push(text),
    }),
  });
  composer.dispatchEvent = () => {};
  composer.value = '';
  vm.runInContext(`${wiring}\nglobalThis.subject = { _wireEditButtons, _newestShownId, _reopenEditDrafts, _editDrafts };`, context);
  return { ...context.subject, list, document, calls, state, storage, composer };
}

test('regenerate answers the same stored question by id, in place', async () => {
  const h = harness();
  const question = userRow('first question\nsecond line', 'u1');
  const answer = aiRow('old reply', 'a1');
  h.list.append(question, answer);
  h._wireEditButtons(h.list);
  h._wireEditButtons(h.list);  // a reload-wide wiring after a per-row one doesn't double up
  const regen = answer.querySelector('.msg-regen-btn');
  assert.equal(regen.listeners.click.length, 1);
  await regen.fire('click');
  // one request: no separate cut, no history lookup, the newest id it got from the server
  assert.deepEqual(h.calls.fetch, []);
  assert.equal(h.calls.resend.length, 1);
  const [[row, text, options]] = h.calls.resend;
  assert.equal(row, question);
  assert.equal(text, 'first question\nsecond line');
  assert.deepEqual({ ...options }, { edit: false, newestId: 'a1' });
  // the new reply sits right under the question; the old one stays until the new one has words
  // (chat.js hides it meanwhile and settles it when the reply ends)
  assert.equal(answer.isConnected, true);
  assert.equal(h.list.children[1].querySelector('.ai-body').textContent, 'new reply');
  assert.equal(h.document.activeElement, h.list.children[1]);
});

test('edit replaces the words in place and answers the same stored message', async () => {
  const h = harness();
  const question = userRow('first question', 'u1');
  h.list.append(question, aiRow('old reply', 'a1'), userRow('later', 'u2'), aiRow('later reply', 'a2'));
  h._wireEditButtons(h.list);
  await question.querySelector('.msg-edit-btn').fire('click');
  const textarea = question.querySelector('.edit-inline');
  assert.equal(textarea.value, 'first question');
  textarea.value = 'edited question';
  await textarea.fire('keydown', { key: 'Enter', shiftKey: false });
  await tick();
  assert.deepEqual(h.calls.resend.map(([row, text, options]) => [row, text, { ...options }]), [[question, 'edited question', { edit: true, newestId: 'a2' }]]);
  assert.deepEqual(h.calls.send, []);
  assert.equal(question.querySelector('.user-bubble').textContent, 'edited question');
  assert.equal(h.list.querySelectorAll('.user-bubble').length, 1);
  assert.equal(h.list.children.length, 2);
});

test('a refused edit or regenerate leaves every row and keeps the words to try again', async () => {
  const h = harness({ refuse: true });
  const question = userRow('question', 'u1');
  const answer = aiRow('old reply', 'a1');
  h.list.append(question, answer);
  h._wireEditButtons(h.list);
  await answer.querySelector('.msg-regen-btn').fire('click');
  assert.equal(answer.isConnected, true);
  await question.querySelector('.msg-edit-btn').fire('click');
  const box = question.querySelector('.edit-inline');
  box.value = 'new words';
  await question.querySelector('.edit-send').fire('click');
  await tick();
  assert.equal(h.calls.resend.length, 2);
  assert.equal(answer.isConnected, true);
  assert.equal(box.isConnected, true);
  assert.equal(box.value, 'new words');
  assert.equal(h.document.activeElement, box);
});

test('a stopped reply is checked by the id its stream named, never matched by its words', async () => {
  // same words twice, ids only from the server: the lookup is by id
  const history = [
    { id: 'u0', role: 'user', content: 'same' }, { id: 'a0', role: 'assistant', content: 'one' },
    { id: 'u1', role: 'user', content: 'same' }, { id: 'r1', role: 'assistant', content: 'half' },
  ];
  const h = harness({ history });
  const first = userRow('same', 'u0');
  const stopped = aiRow('half');
  stopped.dataset.reservedId = 'r1';
  h.list.append(first, aiRow('one', 'a0'), userRow('same', 'u1'), stopped);
  assert.equal(await h._newestShownId(), 'r1');
  assert.equal(stopped.dataset.msgId, 'r1');
  assert.equal(stopped.dataset.reservedId, undefined);
  // a promised id that was never kept is skipped, not guessed
  const none = harness({ history: history.slice(0, 3) });
  const lost = aiRow('half');
  lost.dataset.reservedId = 'r1';
  none.list.append(userRow('same', 'u0'), aiRow('one', 'a0'), userRow('same', 'u1'), lost);
  assert.equal(await none._newestShownId(), 'u1');
  assert.equal(lost.dataset.unsaved, '1');
  // a just-stopped reply is still being saved for a moment: it asks a few times first
  assert.equal(none.calls.fetch.length, 4);
  // offline: no guess at all
  const offline = harness({ online: false });
  const row = aiRow('x');
  row.dataset.reservedId = 'r9';
  offline.list.append(userRow('q', 'u9'), row);
  assert.equal(await offline._newestShownId(), null);
});

test('a row whose id this tab never got asks for a reload instead of guessing', async () => {
  const h = harness({ history: [{ id: 'u0', role: 'user', content: 'same' }] });
  const question = userRow('same');
  const answer = aiRow('reply');
  h.list.append(userRow('same', 'u0'), aiRow('a', 'a0'), question, answer);
  h._wireEditButtons(h.list);
  await answer.querySelector('.msg-regen-btn').fire('click');
  await question.querySelector('.msg-edit-btn').fire('click');
  question.querySelector('.edit-inline').value = 'changed';
  await question.querySelector('.edit-send').fire('click');
  await tick();
  assert.deepEqual(h.calls.fetch, []);
  assert.deepEqual(h.calls.resend, []);
  assert.deepEqual(h.calls.toast.map(([message]) => message), ['reload the task first to change this message.', 'reload the task first to change this message.']);
  assert.equal(h.list.children.length, 4);
});

test('a refused send goes out again as a new message; later turns stay', async () => {
  const h = harness();
  const refused = userRow('go on');
  refused.dataset.unsaved = '1';
  const error = aiRow('a response is already running');
  error.dataset.unsaved = '1';
  const later = userRow('go on', 'u5');
  h.list.append(userRow('q0', 'u0'), aiRow('a', 'a0'), refused, error, later, aiRow('b', 'a5'));
  h._wireEditButtons(h.list);
  await refused.querySelector('.msg-edit-btn').fire('click');
  refused.querySelector('.edit-inline').value = 'go on, edited';
  await refused.querySelector('.edit-send').fire('click');
  await tick();
  assert.deepEqual(h.calls.send, ['go on, edited']);
  assert.deepEqual(h.calls.resend, []);
  assert.equal(refused.isConnected, false);
  assert.equal(error.isConnected, false);
  assert.equal(later.isConnected, true);
  // regenerate on a refused question says why
  const other = harness();
  const q = userRow('x');
  q.dataset.unsaved = '1';
  const a = aiRow('error');
  other.list.append(q, a);
  other._wireEditButtons(other.list);
  await a.querySelector('.msg-regen-btn').fire('click');
  assert.deepEqual(other.calls.toast, [['this message wasn\'t saved, so it can\'t be answered again', 'error']]);
});

test('the pencil opens its box inside the tap, and not while a reply runs', async () => {
  const idle = harness();
  const question = userRow('words', 'u1');
  idle.list.append(question);
  idle._wireEditButtons(idle.list);
  // no await before the box: ios only raises the keyboard for a focus inside the tap
  question.querySelector('.msg-edit-btn').fire('click');
  assert.ok(question.querySelector('.edit-inline'));
  assert.equal(idle.document.activeElement, question.querySelector('.edit-inline'));
  const busy = harness({ busy: true });
  const other = userRow('words', 'u1');
  busy.list.append(other);
  busy._wireEditButtons(busy.list);
  await other.querySelector('.msg-edit-btn').fire('click');
  assert.equal(other.querySelector('.edit-inline'), null);
  assert.equal(busy.calls.toast.length, 1);
});

test('regenerate while a reply is running says why and changes nothing', async () => {
  const h = harness({ busy: true });
  const answer = aiRow('old reply', 'a1');
  h.list.append(userRow('question', 'u1'), answer);
  h._wireEditButtons(h.list);
  await answer.querySelector('.msg-regen-btn').fire('click');
  assert.deepEqual(h.calls.resend, []);
  assert.equal(answer.isConnected, true);
  assert.equal(h.calls.toast.length, 1);
});

test('leaving the edit box never sends; send does, cancel and escape put the words back', async () => {
  const h = harness();
  const question = userRow('first question', 'u1');
  const later = userRow('later', 'u2');
  h.list.append(question, aiRow('old reply', 'a1'), later, aiRow('later reply', 'a2'));
  h._wireEditButtons(h.list);
  const pencil = question.querySelector('.msg-edit-btn');
  await pencil.fire('click');
  let box = question.querySelector('.edit-inline');
  assert.equal(box.attrs['aria-label'], 'edit message');
  // the pencil's row steps aside for cancel and send, both real buttons
  assert.equal(question.querySelectorAll('.user-actions')[0].style.display, 'none');
  const [cancel, send] = question.querySelector('.edit-actions').children;
  assert.deepEqual([cancel.tag, cancel.type, cancel.textContent, send.textContent], ['button', 'button', 'cancel', 'send']);
  box.value = 'changed words';
  // a dismissed phone keyboard or a click elsewhere: nothing goes out, the draft stays
  await box.fire('blur');
  await tick();
  assert.deepEqual(h.calls.resend, []);
  assert.equal(box.isConnected, true);
  assert.equal(box.value, 'changed words');
  assert.equal(later.isConnected, true);
  // cancel puts the stored words back and lands on the pencil
  await cancel.fire('click');
  assert.equal(question.querySelector('.user-bubble').textContent, 'first question');
  assert.equal(question.querySelector('.edit-actions'), null);
  assert.equal(question.querySelectorAll('.user-actions')[0].style.display, '');
  assert.equal(h.document.activeElement, pencil);
  // escape does the same from the keyboard
  await pencil.fire('click');
  box = question.querySelector('.edit-inline');
  box.value = 'other words';
  const escape = await box.fire('keydown', { key: 'Escape' });
  assert.equal(escape.stopped, true);
  assert.equal(question.querySelector('.user-bubble').textContent, 'first question');
  assert.deepEqual(h.calls.resend, []);
  // send is the only way the words go out
  await pencil.fire('click');
  box = question.querySelector('.edit-inline');
  box.value = 'sent words';
  await question.querySelector('.edit-send').fire('click');
  await tick();
  assert.deepEqual(h.calls.resend.map(([row, text]) => [row, text]), [[question, 'sent words']]);
  assert.equal(question.querySelector('.edit-actions'), null);
  assert.equal(later.isConnected, false);
});

test('enter that picks an ime candidate never sends, and the box keeps its keys to itself', async () => {
  const h = harness();
  const question = userRow('question', 'u1');
  h.list.append(question, aiRow('reply', 'a1'));
  h._wireEditButtons(h.list);
  await question.querySelector('.msg-edit-btn').fire('click');
  const box = question.querySelector('.edit-inline');
  box.value = 'ni';
  // chromium: isComposing; safari: keyCode 229
  await box.fire('keydown', { key: 'Enter', isComposing: true, keyCode: 13 });
  await box.fire('keydown', { key: 'Enter', isComposing: false, keyCode: 229 });
  await tick();
  assert.deepEqual(h.calls.resend, []);
  assert.equal(box.isConnected, true);
  // ctrl+enter sends this edit and stops there, so the global send shortcut never sees it
  const ctrlEnter = await box.fire('keydown', { key: 'Enter', ctrlKey: true, keyCode: 13 });
  await tick();
  assert.equal(ctrlEnter.stopped, true);
  assert.equal(h.calls.resend.length, 1);
  // the composer and the global shortcut have the same guards
  const composer = app.slice(app.indexOf("ta.addEventListener('keydown', e => {"), app.indexOf('// dim send when empty'));
  assert.match(composer, /if \(e\.isComposing \|\| e\.keyCode === 229\) return;/);
  assert.match(app, /matchesShortcut\(e, shortcuts\.send\) && !e\.isComposing && !e\.target\?\.closest\?\.\('\.edit-inline'\)/);
});

test('a changed draft comes back after leaving the task; the box grows and is 16px on touch', async () => {
  const h = harness({ coarse: true });
  const question = userRow('first question', 'u1');
  h.list.append(question, aiRow('reply', 'a1'));
  h._wireEditButtons(h.list);
  await question.querySelector('.msg-edit-btn').fire('click');
  const box = question.querySelector('.edit-inline');
  assert.equal(box.style.fontSize, '16px');
  assert.equal(box.style.height, '40px');
  assert.equal(box.style.overflowY, 'hidden');
  box.scrollHeight = 2000;
  box.value = 'half-written edit';
  await box.fire('input');
  // capped at 40% of the screen, then it scrolls
  assert.equal(box.style.height, '320px');
  assert.equal(box.style.overflowY, 'auto');
  assert.equal(h._editDrafts.size, 1);
  // the task is drawn again (another task and back): the box comes back with the draft, unfocused
  h.document.activeElement = null;
  for (const child of [...h.list.children]) child.remove();
  const again = userRow('first question', 'u1');
  h.list.append(again, aiRow('reply', 'a1'));
  h._wireEditButtons(h.list);
  h._reopenEditDrafts(h.list);
  assert.equal(again.querySelector('.edit-inline').value, 'half-written edit');
  assert.equal(h.document.activeElement, null);
  // words changed under it (another tab): the draft no longer fits and is dropped
  for (const child of [...h.list.children]) child.remove();
  const changed = userRow('someone else changed this', 'u1');
  h.list.append(changed, aiRow('reply', 'a1'));
  h._wireEditButtons(h.list);
  h._reopenEditDrafts(h.list);
  assert.equal(changed.querySelector('.edit-inline'), null);
  assert.equal(h._editDrafts.size, 0);
  // cancel forgets a draft
  await changed.querySelector('.msg-edit-btn').fire('click');
  changed.querySelector('.edit-inline').value = 'x';
  await changed.querySelector('.edit-inline').fire('input');
  assert.equal(h._editDrafts.size, 1);
  await changed.querySelector('.edit-cancel').fire('click');
  assert.equal(h._editDrafts.size, 0);
});

test('opening another edit closes an untouched one and keeps one with changes', async () => {
  const h = harness();
  const one = userRow('one', 'u1');
  const two = userRow('two', 'u2');
  const three = userRow('three', 'u3');
  h.list.append(one, aiRow('a', 'a1'), two, aiRow('b', 'a2'), three, aiRow('c', 'a3'));
  h._wireEditButtons(h.list);
  await one.querySelector('.msg-edit-btn').fire('click');
  await two.querySelector('.msg-edit-btn').fire('click');
  two.querySelector('.edit-inline').value = 'two, changed';
  assert.equal(one.querySelector('.edit-inline'), null);
  assert.equal(one.querySelector('.user-bubble').textContent, 'one');
  await three.querySelector('.msg-edit-btn').fire('click');
  assert.equal(two.querySelector('.edit-inline').value, 'two, changed');
  assert.deepEqual(h.calls.resend, []);
});

test('a second regenerate tap while the first is waiting does nothing', async () => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const h = harness({ gate });
  const answer = aiRow('old reply', 'a1');
  h.list.append(userRow('question', 'u1'), answer);
  h._wireEditButtons(h.list);
  const regen = answer.querySelector('.msg-regen-btn');
  const first = regen.fire('click');
  await tick();
  assert.equal(regen.attrs['aria-disabled'], 'true');
  await regen.fire('click');
  release();
  await first;
  assert.equal(h.calls.resend.length, 1);
  // one new reply, under the question, with the old one kept until it has words
  assert.equal(h.list.children.length, 3);
  assert.equal(h.list.children[1].querySelector('.ai-body').textContent, 'new reply');
  assert.equal(regen.dataset.busy, undefined);
});

test('a reply that started while regenerate was checking keeps its row', async () => {
  // something else began answering meanwhile: regenerate steps back instead of asking
  const h = harness({ busyAfter: 1 });
  const answer = aiRow('old reply', 'a1');
  h.list.append(userRow('question', 'u1'), answer);
  h._wireEditButtons(h.list);
  await answer.querySelector('.msg-regen-btn').fire('click');
  assert.equal(h.calls.resend.length, 0);
  assert.equal(answer.isConnected, true);
});

test('resendMessage asks once with the stored question\'s id and the newest id, nothing else', async () => {
  const streamed = [];
  const context = vm.createContext({
    getActiveId: () => 's1', canSendMessage: () => true, getSelected: () => ({ model: 'm' }),
    showSendIssue() {}, showMessages() {}, getMode: () => 'agent', isIncognitoMode: () => false,
    getPermMode: () => 'approve', getEffort: () => '', getReasoningMode: () => '', getCustomEffort: () => null,
    appendUserMsg() { throw new Error('no second bubble'); },
    streamReply: (request, options) => { streamed.push([request, options]); return Promise.resolve(); },
  });
  vm.runInContext(`${resend}\nglobalThis.resend = resendMessage;`, context);
  const scope = { kind: 'vault_documents', documents: [{ path: 'plans.md', expected_hash: 'h' }] };
  const row = { dataset: { msgId: 'u1' }, contextScope: scope };
  const accepted = [];
  const regen = context.resend(row, 'question', { newestId: 'a9', onAccepted: reply => accepted.push(reply) });
  const edit = context.resend(row, 'new words', { edit: true, newestId: 'a9' });
  const [[request, options], [editRequest]] = streamed;
  assert.equal(request.regenerate_message_id, 'u1');
  assert.equal(request.newest_id, 'a9');
  assert.equal(request.edit_message_id, undefined);
  assert.equal(editRequest.edit_message_id, 'u1');
  assert.equal(editRequest.message, 'new words');
  // notes and files are the server's to supply: the tab sends none, but still shows them
  assert.equal(request.context_scope, undefined);
  assert.equal(JSON.stringify(request.file_ids), '[]');
  assert.equal(options.shownScope, scope);
  assert.equal(options.userRow, row);
  // regenerate keeps the old answer until the new one has words; an edit's old turns go at once
  assert.equal(options.resend.keepOld, true);
  assert.equal(streamed[1][1].resend.keepOld, false);
  options.resend.accepted('reply row');
  streamed[1][1].resend.refused('stale');
  assert.equal(await regen, 'accepted');
  assert.equal(await edit, 'stale');
  assert.deepEqual(accepted, ['reply row']);
  // no id yet: nothing goes out
  assert.equal(await context.resend({ dataset: {} }, 'x'), 'refused');
  assert.equal(streamed.length, 2);
});

test('the stream names both rows first and a refusal leaves the history alone', () => {
  // the first event's ids go on the rows; the reply's is only a promise until it's kept
  assert.match(stream, /if \(chunk\.turn\) \{/);
  assert.match(stream, /userRow\.dataset\.msgId = chunk\.turn\.user_id;/);
  assert.match(stream, /row\.dataset\.reservedId = chunk\.turn\.assistant_id;/);
  assert.match(stream, /row\.dataset\.msgId = chunk\.saved_message\.id;\s*delete row\.dataset\.reservedId;/);
  // finished without being kept: no id to keep
  assert.match(stream, /if \(row\.dataset\.reservedId && receivedDone && !ctrl\.signal\.aborted\) \{\s*delete row\.dataset\.reservedId;\s*row\.dataset\.unsaved = '1';/);
  // a refused edit or regenerate: its row goes and it says why, nothing else moves
  assert.match(stream, /if \(!r\.ok && resend\) \{[^]*?row\.remove\(\);[^]*?const refusal = resendRefusal\(r\.status, error\);[^]*?resend\.refused\(refusal\.reason\);[^]*?return;/);
  assert.match(stream, /accepted = true;[^]*?resend\?\.accepted\(row\);/);
  // a regenerate hides the old rows when the server takes it, and only drops them once words came
  assert.match(stream, /if \(resend\?\.keepOld && userRow\?\.isConnected\) \{[^]*?next\.style\.display = 'none';\s*replaced\.push\(next\);/);
  // the server says whether it swapped; the page follows that and never its own reading of the
  // words (a reply of blank lines, a dropped connection); not hearing it means re-reading
  assert.match(stream, /if \(chunk\.regenerated\) regenOutcome = chunk\.regenerated\.replaced;/);
  assert.match(stream, /if \(regenOutcome === true\) replaced\.forEach\(old => old\.remove\(\)\);/);
  assert.match(stream, /else if \(regenOutcome === false\) \{[^]*?replaced\.forEach\(old => \{ old\.style\.display = ''; \}\);\s*row\.remove\(\);/);
  assert.match(stream, /const unheard = replaced\.length && regenOutcome === undefined;/);
  assert.doesNotMatch(stream, /accText\.trim\(\) \|\| \(toolEls\.size/);
  // no answer from the server at all, or a stream cut after it took the request: re-read
  // stopped before the server confirmed it: the edit box re-reads once the turn is let go
  assert.match(stream, /resend\.refused\(e\.name === 'AbortError' \? 'stopped' : 'offline', turnToken\);/);
  assert.match(stream, /if \(resend && accepted && \(unheard \|\| streamBroke \|\| \(streamEnded && !receivedDone && !providerError\)\)\) \{[^]*?void rereadActiveSession\(sessionId, \{ afterTurn: turnToken \}\);/);
  // a refused plain send is marked as never stored
  assert.match(stream, /if \(userRow && !userRow\.dataset\.msgId\) userRow\.dataset\.unsaved = '1';/);
  // an edit answers right under its question
  assert.match(stream, /if \(resend && userRow\?\.isConnected\) userRow\.after\(row\);/);
  // its retry only answers: it never cuts again
  assert.match(stream, /const \{ edit_message_id: _edit, regenerate_message_id: _regen, newest_id: _newest, \.\.\.asked \} = request;/);
  const refusal = chat.match(/^function resendRefusal\([^]*?^}/m)[0];
  const context = vm.createContext({ plainError: message => message });
  vm.runInContext(`${refusal}\nglobalThis.refusal = resendRefusal;`, context);
  assert.equal(context.refusal(409, { code: 'history_moved' }).reason, 'stale');
  assert.equal(context.refusal(404, {}).reason, 'gone');
  assert.deepEqual({ ...context.refusal(409, { code: 'turn_stopped', detail: 'stopped before it started' }) }, { reason: 'stopped' });
  assert.equal(context.refusal(409, { code: 'file_gone', detail: "this question's file was deleted. ask again with it attached." }).words, "this question's file was deleted. ask again with it attached.");
  // the history's stand-ins for missing replies aren't stored messages
  assert.match(sessions, /pending\.row\.dataset\.unsaved = '1';/);
  assert.doesNotMatch(sessions, /_storedTurn|m\.content === text/);
});

test('just-sent rows carry regenerate and branch', () => {
  const send = chat.slice(chat.indexOf('export async function sendMessage'), chat.indexOf('export function resendMessage'));
  assert.match(send, /const userRow = appendUserMsg\(text, documentScope\);/);
  assert.match(send, /\{ freshSession, pendingDraft, userRow \}\);/);
  assert.match(stream, /msg-regen-btn act-btn/);
  assert.match(stream, /msg-branch-btn/);
  assert.match(stream, /wireMessageActions\(row\);/);
  const appendUser = sessions.slice(sessions.indexOf('export function appendUserMsg'), sessions.indexOf('export function appendInterruptionNotice'));
  assert.match(appendUser, /_wireEditButtons\(row\);/);
  assert.match(appendUser, /row\.contextScope = documentScope \|\| null;/);
  assert.match(sessions, /appendUserMsg\(m\.content, m\.meta\?\.context_scope \|\| m\.meta\?\.response_recovery\?\.request\?\.context_scope\)/);
});

test('when the reply ends, touch lands on the reply and keyboards on the composer', () => {
  const helper = chat.match(/^function focusAfterReply\([^]*?^}/m)[0];
  for (const coarse of [true, false]) {
    const focused = [];
    const row = { isConnected: true, attrs: {}, hasAttribute(name) { return name in this.attrs; }, focus(options) { focused.push(['row', options, this.tabIndex]); } };
    const composer = { focus() { focused.push(['composer']); } };
    const context = vm.createContext({
      document: { getElementById: id => ({ messages: { lastElementChild: row }, 'composer-ta': composer }[id]) },
      matchMedia: query => ({ matches: query === '(pointer: coarse)' && coarse }),
    });
    vm.runInContext(`${helper}\nglobalThis.focusAfterReply = focusAfterReply;`, context);
    context.focusAfterReply();
    if (coarse) {
      assert.equal(focused.length, 1);
      assert.equal(focused[0][0], 'row');
      assert.equal(focused[0][1].preventScroll, true);
      assert.equal(focused[0][2], -1);
    } else assert.deepEqual(focused, [['composer']]);
  }
  // stop, a folded question and the end of a reply all go through it
  const uses = chat.match(/focusAfterReply\(/g).length;
  assert.ok(uses >= 5, uses);
  assert.doesNotMatch(chat.slice(chat.indexOf('function setStreaming'), chat.indexOf('// rough "is the user asking')), /composer-ta'\)\?\.focus/);
});

test('retry counts a click safari never focused as being on the button', () => {
  const retry = chat.slice(chat.indexOf("retry.textContent = 'retry response'"), chat.indexOf('body.querySelector(\'.error-msg\')?.appendChild(retry)'));
  assert.match(retry, /const a = document\.activeElement;/);
  assert.match(retry, /const restoreFocus = a === retry \|\| !a \|\| a === document\.body;/);
  assert.match(retry, /if \(restoreFocus\) focusAfterReply\(\);/);
});

test('an empty edit box sends nothing; unchanged words ask again and keep the old answer', async () => {
  const h = harness();
  const question = userRow('question', 'u1');
  const answer = aiRow('old reply', 'a1');
  h.list.append(question, answer);
  h._wireEditButtons(h.list);
  await question.querySelector('.msg-edit-btn').fire('click');
  const box = question.querySelector('.edit-inline');
  box.value = '   ';
  await box.fire('keydown', { key: 'Enter' });
  await question.querySelector('.edit-send').fire('click');
  await tick();
  assert.deepEqual(h.calls.resend, []);
  assert.equal(box.isConnected, true);
  assert.equal(h.document.activeElement, box);
  // the same words again: a regenerate (old answer kept until the new one has words), not an edit
  box.value = 'question ';
  await box.fire('keydown', { key: 'Enter' });
  await tick();
  assert.deepEqual(h.calls.resend.map(([, text, options]) => [text, { ...options }]), [['question', { edit: false, newestId: 'a1' }]]);
  assert.equal(answer.isConnected, true);
  assert.equal(question.querySelector('.user-bubble').textContent, 'question');
});

test('a stale or gone question re-reads the task and keeps the edit\'s words', async () => {
  // the server moved on: re-read in place, the box comes back with its draft and focus
  const stale = harness({
    refuse: 'stale',
    reread: list => {
      for (const child of [...list.children]) child.remove();
      list.append(userRow('question', 'u1'), aiRow('old reply', 'a1'), userRow('from another tab', 'u2'), aiRow('b', 'a2'));
      stale._wireEditButtons(list);
      stale._reopenEditDrafts(list);
    },
  });
  const question = userRow('question', 'u1');
  stale.list.append(question, aiRow('old reply', 'a1'));
  stale._wireEditButtons(stale.list);
  await question.querySelector('.msg-edit-btn').fire('click');
  const box = question.querySelector('.edit-inline');
  box.value = 'new words';
  await box.fire('input');
  await box.fire('keydown', { key: 'Enter' });
  await tick(); await tick();
  assert.deepEqual(stale.calls.reread, ['s1']);
  const reopened = stale.list.children[0].querySelector('.edit-inline');
  assert.equal(reopened.value, 'new words');
  assert.equal(stale.document.activeElement, reopened);
  assert.match(stale.calls.toast.at(-1)[0], /changed in another tab\. it's up to date now and your edit is still open/);
  // the question was removed: its words go to the message box
  const gone = harness({ refuse: 'gone', reread: list => { for (const child of [...list.children]) child.remove(); } });
  const q = userRow('question', 'u1');
  gone.list.append(q, aiRow('old', 'a1'));
  gone._wireEditButtons(gone.list);
  await q.querySelector('.msg-edit-btn').fire('click');
  q.querySelector('.edit-inline').value = 'keep these words';
  await q.querySelector('.edit-inline').fire('input');
  await q.querySelector('.edit-send').fire('click');
  await tick(); await tick();
  assert.equal(gone.composer.value, 'keep these words');
  assert.equal(gone._editDrafts.size, 0);
  assert.match(gone.calls.toast.at(-1)[0], /removed in another tab\. your words are in the message box/);
});

test('edit drafts outlive a reload in this tab, but never for a private task', async () => {
  const saved = harness();
  const question = userRow('question', 'u1');
  saved.list.append(question, aiRow('reply', 'a1'));
  saved._wireEditButtons(saved.list);
  await question.querySelector('.msg-edit-btn').fire('click');
  question.querySelector('.edit-inline').value = 'half-written';
  await question.querySelector('.edit-inline').fire('input');
  const kept = JSON.parse(saved.storage.data['aide-edit-drafts-v1']);
  assert.deepEqual(kept.map(([key, draft]) => [key, draft.text]), [['s1\nu1', 'half-written']]);
  // a fresh page in the same tab reads them back
  const reloaded = harness({ stored: kept });
  const again = userRow('question', 'u1');
  reloaded.list.append(again, aiRow('reply', 'a1'));
  reloaded._wireEditButtons(reloaded.list);
  reloaded._reopenEditDrafts(reloaded.list);
  assert.equal(again.querySelector('.edit-inline').value, 'half-written');
  // private: memory only
  const hidden = harness({ incognito: true });
  const p = userRow('secret', 'u9');
  hidden.list.append(p, aiRow('reply', 'a9'));
  hidden._wireEditButtons(hidden.list);
  await p.querySelector('.msg-edit-btn').fire('click');
  p.querySelector('.edit-inline').value = 'private words';
  await p.querySelector('.edit-inline').fire('input');
  assert.equal(hidden._editDrafts.size, 1);
  assert.deepEqual(JSON.parse(hidden.storage.data['aide-edit-drafts-v1']), []);
});

test('the edit\'s own re-read draws over edit boxes; background refreshes still wait for them', () => {
  const guard = sessions.match(/^function canRefreshAideHistory\([^]*?^}/m)[0];
  const box = { className: 'edit-inline' };
  for (const [overEdits, open, allowed] of [[false, true, false], [true, true, true], [false, false, true]]) {
    const context = vm.createContext({
      window: {},
      document: { getElementById: () => ({ querySelector: selector => (open && !selector.includes(':not(.edit-inline)') ? box : null) }) },
    });
    vm.runInContext(`${guard}\nglobalThis.can = canRefreshAideHistory;`, context);
    assert.equal(context.can(overEdits), allowed, `${overEdits} ${open}`);
  }
  assert.match(sessions, /export function rereadActiveSession\(sessionId = _activeId, \{ afterTurn = '' \} = \{\}\) \{\s*return refreshActiveSessionQuietly\(sessionId, \{ overEdits: true, afterTurn \}\);/);
  // a re-read after a stop waits (bounded) until that turn has been saved and let go
  assert.match(sessions, /if \(!afterTurn \|\| data\.answering_turn !== afterTurn \|\| waited >= 5000\) break;/);
});

test('image rows carry the ids the server stored them under; private ones are never stored', () => {
  const image = chat.match(/^async function _sendImage\([^]*?^}/m)[0];
  assert.match(image, /const userRow = appendUserMsg\(prompt\);/);
  assert.match(image, /if \(d\.user_message_id && d\.message_id\) \{\s*userRow\.dataset\.msgId = d\.user_message_id;\s*row\.dataset\.msgId = d\.message_id;\s*\} else \{\s*userRow\.dataset\.unsaved = '1';\s*row\.dataset\.unsaved = '1';/);
});

test('a background re-read keeps waiting on edit boxes; an edit\'s own re-read retries the same way', () => {
  assert.equal(sessions.match(/setTimeout\(\(\) => refreshActiveSessionQuietly\(sessionId, \{ overEdits \}\), 750\)/g).length, 2);
});

test('a private task\'s edit drafts go once private mode ends', async () => {
  const h = harness({ incognito: true });
  const question = userRow('secret question', 'u1');
  h.list.append(question, aiRow('reply', 'a1'));
  h._wireEditButtons(h.list);
  await question.querySelector('.msg-edit-btn').fire('click');
  question.querySelector('.edit-inline').value = 'secret draft';
  await question.querySelector('.edit-inline').fire('input');
  assert.equal(h._editDrafts.size, 1);
  // private mode ends; the next drawing of any task drops it from memory too
  h.state.incognito = false;
  for (const child of [...h.list.children]) child.remove();
  h._reopenEditDrafts(h.list);
  assert.equal(h._editDrafts.size, 0);
});

test('an edit stopped before the server confirmed it re-reads once that turn is let go', async () => {
  const h = harness({ refuse: { reason: 'stopped', turn: 'turn-9' } });
  const question = userRow('question', 'u1');
  h.list.append(question, aiRow('reply', 'a1'));
  h._wireEditButtons(h.list);
  await question.querySelector('.msg-edit-btn').fire('click');
  question.querySelector('.edit-inline').value = 'new words';
  await question.querySelector('.edit-inline').fire('input');
  await question.querySelector('.edit-send').fire('click');
  await tick(); await tick();
  // it may have landed after the server took it: the saved history decides, with no toast
  assert.deepEqual(h.calls.reread, ['s1']);
  assert.equal(h.calls.rereadAfter, 'turn-9');
  assert.deepEqual(h.calls.toast, []);
});

test('the ask panel names its turn and stops by it before letting go', () => {
  const panel = read('ask_panel');
  assert.match(panel, /body: JSON\.stringify\(\{ session_id: id, message: compose\(question\), simple: true, turn_token: turnToken \}\)/);
  assert.match(panel, /body: JSON\.stringify\(\{ turn_token: turnToken \}\)/);
  assert.match(panel, /Promise\.race\(\[told, new Promise\(resolve => setTimeout\(resolve, 800\)\)\]\)\.then\(\(\) => controller\.abort\(\)\)/);
});

test('a stop that beat the turn ends quietly, like any stop', () => {
  const stream = chat.slice(chat.indexOf('async function streamReply'));
  // plain sends: no red error, nothing kept, the usual stopped ending
  assert.match(stream, /if \(error\.code === 'turn_stopped'\) \{[^]*?row\.dataset\.unsaved = '1';\s*throw new DOMException\('stopped before it started', 'AbortError'\);/);
  const panel = read('ask_panel');
  assert.match(panel, /if \(err\.name === 'AbortError' \|\| err\.code === 'turn_stopped'\) \{\s*if \(!text\) answer\.innerHTML = '<p class="ask-panel-note">stopped\.<\/p>';/);
});

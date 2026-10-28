import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { webcrypto, createHash } from 'node:crypto';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/answer_task.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
const flush = () => new Promise(resolve => setImmediate(resolve));
function deferred() { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; }

function harness({ compact = true, privateReply = false } = {}) {
  const state = {}, attempts = [], reviews = [];
  class Node {
    constructor(className = '') { this.className = className; this.children = []; this.parentNode = null; this.dataset = {}; this.attributes = {}; this.hidden = false; }
    append(...nodes) { for (const node of nodes) { node.parentNode = this; this.children.push(node); } }
    get isConnected() { return this === body || Boolean(this.parentNode?.isConnected); }
    getClientRects() {
      for (let node = this; node; node = node.parentNode) if (node.hidden) return [];
      return this.isConnected ? [{}] : [];
    }
    get classList() { return { contains: name => this.className.split(' ').includes(name) }; }
    matches(selector) { return selector.startsWith('.') && this.classList.contains(selector.slice(1)); }
    closest(selector) { for (let node = this; node; node = node.parentNode) if (node.matches(selector)) return node; return null; }
    descendants() { return this.children.flatMap(node => [node, ...node.descendants()]); }
    querySelector(selector) { return this.descendants().find(node => node.matches(selector)) || null; }
    getAttribute(name) { return this.attributes[name] ?? null; }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    removeAttribute(name) { delete this.attributes[name]; }
    remove() { const parent = this.parentNode; if (parent) parent.children.splice(parent.children.indexOf(this), 1); this.parentNode = null; }
  }
  const body = new Node(), row = new Node('msg-row'), wrap = new Node('ai-wrap');
  row.dataset.msgId = 'original-reply';
  wrap.dataset = { sessionId: 'original-session', private: String(privateReply) };
  wrap.answerText = 'Original task title\nOriginal reply details';
  const actions = new Node('msg-actions'), menu = new Node('msg-actions-menu'), more = new Node('msg-more-trigger'), button = new Node('act-btn');
  button.textContent = 'add to plan';
  body.append(row); row.append(wrap); wrap.append(actions);
  if (compact) { menu.hidden = true; actions.append(more, menu); menu.append(button); }
  else actions.append(button);
  const context = vm.createContext({
    document: { body, getElementById: () => null }, window: {}, crypto: webcrypto, TextEncoder,
    sha256Hex: async text => createHash('sha256').update(text, 'utf8').digest('hex'),
    dismissAfter() {},
    t: key => key, refreshScrollFollow() {}, showPendingCapture: async () => {},
    reconcileSourceReply: async () => { if (state.reconcileGate) await state.reconcileGate.promise; },
    openCaptureReview: async (proposal, trigger, onSaved, isCurrent = () => true) => {
      attempts.push({ proposal, trigger, onSaved, isCurrent });
      if (state.reviewGate) await state.reviewGate.promise;
      // Retain capture.js's pre-open visibility/currentness contract at this seam.
      if (!isCurrent() || !trigger.isConnected || !trigger.getClientRects().length) return false;
      reviews.push({ proposal, trigger, onSaved }); return true;
    },
  });
  vm.runInContext(source + '\nglobalThis.save = saveAnswerTask;', context);
  return { state, attempts, reviews, body, row, wrap, actions, menu, more, button, save: context.save };
}

test('a Plan action inside a dismissed reply menu reviews the exact original reply using its visible More trigger', async () => {
  const h = harness();
  assert.equal(h.button.getClientRects().length, 0);
  await h.save(h.button);
  assert.equal(h.reviews.length, 1);
  assert.equal(h.reviews[0].trigger, h.more);
  const { candidate, source } = h.reviews[0].proposal;
  assert.equal(candidate.title, 'Original task title');
  assert.equal(candidate.notes, h.wrap.answerText);
  assert.equal(source.session_id, 'original-session');
  assert.equal(source.message_id, 'original-reply');
  assert.equal(source.fingerprint, createHash('sha256').update(h.wrap.answerText).digest('hex'));
  assert.equal(h.button.closest('.ai-wrap'), h.wrap);
  assert.equal(h.button.getAttribute('aria-disabled'), null);
});

test('a visible legacy Plan action remains its own review focus anchor', async () => {
  const h = harness({ compact: false });
  await h.save(h.button);
  assert.equal(h.reviews.length, 1); assert.equal(h.reviews[0].trigger, h.button);
});

for (const removed of [false, true]) {
  test(`${removed ? 'removing' : 'hiding'} the reply owner while preparing still cancels Plan review`, async () => {
    const h = harness(); h.state.reconcileGate = deferred();
    const save = h.save(h.button);
    if (removed) h.row.remove(); else h.row.hidden = true;
    h.state.reconcileGate.resolve(); await save;
    assert.equal(h.reviews.length, 0); assert.equal(h.attempts.length, 0);
    assert.equal(h.button.getAttribute('aria-disabled'), null);
  });
}

test('an unavailable More trigger cannot authorize preparation from an invisible action', async () => {
  const h = harness(); h.more.hidden = true;
  await h.save(h.button);
  assert.equal(h.reviews.length, 0);
});

test('leaving the reply while capture storage opens cannot show its stale review', async () => {
  const h = harness(); h.state.reviewGate = deferred();
  const save = h.save(h.button);
  for (let i = 0; i < 20 && !h.attempts.length; i++) await flush();
  assert.equal(h.attempts.length, 1);
  h.row.hidden = true;
  h.state.reviewGate.resolve(); await save;
  assert.equal(h.reviews.length, 0);
});

test('private Plan sources keep session and message identifiers out of the review', async () => {
  const h = harness({ privateReply: true }); await h.save(h.button);
  assert.equal(h.reviews.length, 1);
  assert.equal(h.reviews[0].proposal.source.private, true);
  assert.equal(h.reviews[0].proposal.source.session_id, '');
  assert.equal(h.reviews[0].proposal.source.message_id, '');
});

test('an already preparing aria-disabled Plan action cannot start duplicate preparation', async () => {
  const h = harness(); h.button.setAttribute('aria-disabled', 'true');
  await h.save(h.button);
  assert.equal(h.attempts.length, 0); assert.equal(h.reviews.length, 0);
  assert.equal(h.button.getAttribute('aria-disabled'), 'true');
});

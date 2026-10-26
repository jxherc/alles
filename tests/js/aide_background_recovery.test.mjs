import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { t, tp } from '../../static/js/i18n.js';

const read = name => readFileSync(new URL(`../../static/js/${name}.js`, import.meta.url), 'utf8');
const chat = read('chat'), sessions = read('sessions'), background = read('aidebackground');
const fn = (source, name) => {
  const result = source.match(new RegExp(`^(?:export )?(?:async )?function ${name}\\([^]*?^}`, 'm'))?.[0];
  assert.ok(result, `actual ${name} implementation exists`);
  return result.replace(/^export /, '');
};
const copy = value => JSON.parse(JSON.stringify(value));

function draftFixture({ activeId = 'archive', privateMode = false, original = { text: '', document_scope: null } } = {}) {
  const values = new Map([['aide-draft-v2-primary', JSON.stringify(original)]]);
  const field = { value: 'archive draft', style: {}, dispatchEvent() {}, focus() { this.focused = true; } };
  const notices = [];
  let fail = false;
  const context = vm.createContext({ t, tp, tr: t, trp: tp, plainError: value => value,
    document: { getElementById: () => field }, Event: class {},
    getActiveId: () => activeId, isIncognitoMode: () => privateMode,
    toast: value => notices.push(value),
    localStorage: {
      getItem: key => values.get(key) ?? null,
      setItem(key, value) { if (fail) throw Error('synthetic quota'); values.set(key, value); },
      removeItem(key) { values.delete(key); },
    },
  });
  const drafts = sessions.slice(sessions.indexOf('const _legacyDraftKey'), sessions.indexOf('export function newChat'));
  vm.runInContext(drafts.replace(/^export /gm, '') + '\n' + fn(chat, 'restoreComposerInput') + '\n' + fn(chat, 'restoreBackgroundInput')
    + '\nglobalThis.subject = { restore: restoreBackgroundInput, consume: consumeDraft };', context);
  return { field, values, notices, setFailure: () => { fail = true; },
    restore: () => context.subject.restore('primary', '/background original request'),
    consume: (...args) => context.subject.consume(...args),
    primary: () => JSON.parse(values.get('aide-draft-v2-primary')) };
}

test('late background failure restores the original owner without touching the archive composer', () => {
  const h = draftFixture(); h.restore();
  assert.equal(h.field.value, 'archive draft'); assert.equal(h.field.focused, undefined);
  assert.deepEqual(h.primary(), { text: '/background original request', document_scope: null });
});

test('late background failure preserves newer source-scoped text on its original owner', () => {
  const scope = { kind: 'vault_document', path: 'notes/synthetic.md', expected_hash: 'fixture' };
  const h = draftFixture({ original: { text: 'newer primary draft', document_scope: scope } }); h.restore();
  assert.deepEqual(h.primary(), { text: '/background original request\n\nnewer primary draft', document_scope: scope });
  assert.equal(h.field.value, 'archive draft');
});

test('an active private composer never receives another conversation\'s recovery', () => {
  const h = draftFixture({ activeId: 'primary', privateMode: true }); h.restore();
  assert.equal(h.field.value, 'archive draft'); assert.equal(h.primary().text, '/background original request');
});

test('same-owner recovery retains text typed while handoff was pending', () => {
  const h = draftFixture({ activeId: 'primary' }); h.restore();
  assert.equal(h.field.value, '/background original request\n\narchive draft');
});

test('draft storage failure reports recovery failure without altering another composer', () => {
  const h = draftFixture(); h.setFailure(); h.restore();
  assert.equal(h.field.value, 'archive draft'); assert.equal(h.primary().text, '');
  assert.ok(h.notices.some(text => text.includes('original draft')));
});

test('consumeDraft optional scope preserves old default behavior and rejects stale snapshots', () => {
  const before = { text: 'old', document_scope: { kind: 'vault_document', path: 'old.md' } };
  const h = draftFixture({ original: before });
  assert.equal(h.consume('primary', before, 'remaining'), true);
  assert.deepEqual(h.primary(), { text: 'remaining', document_scope: null });
  assert.equal(h.consume('primary', before, 'stale'), false);
  assert.equal(h.primary().text, 'remaining');
});

function pollingFixture() {
  const timeouts = new Map(), requests = [], notes = { textContent: '' };
  const button = { disabled: false };
  const card = { isConnected: true, dataset: { runId: 'original', runState: 'running' },
    querySelector: selector => selector === '[data-background-action]' ? button : notes };
  let timer = 0;
  const context = vm.createContext({ t, tp, tr: t, trp: tp, plainError: value => value,
    fetch: (url, options) => new Promise((resolve, reject) => requests.push({ url, options, resolve, reject })),
    setTimeout: callback => { timeouts.set(++timer, callback); return timer; },
    clearTimeout: id => timeouts.delete(id),
    renderCard(_card, run) { _card.dataset.runId = run.id; _card.dataset.runState = run.state; },
    window: { _refreshAideSessionQuietly() {} },
  });
  vm.runInContext("const timers = new Map(); const TERMINAL = new Set(['succeeded','failed','cancelled','interrupted','uncertain']);\n"
    + ['safeMessage', 'readJson', 'stopPolling', 'readRun', 'poll', 'act'].map(name => fn(background, name)).join('\n')
    + '\nglobalThis.subject = { poll, act, timerCount: () => timers.size };', context);
  const settle = async () => { for (let index = 0; index < 6; index++) await Promise.resolve(); };
  const reply = (request, payload, ok = true) => request.resolve({ ok, json: async () => payload });
  const fire = () => { const entry = timeouts.entries().next().value; assert.ok(entry); timeouts.delete(entry[0]); return entry[1](); };
  return { card, button, notes, requests, timeouts, settle, reply, fire,
    poll: () => context.subject.poll(card), act: action => context.subject.act(card, action, {}),
    timerCount: context.subject.timerCount };
}

test('failed cancel rearms one status poll and observes later completion', async () => {
  const h = pollingFixture(); const action = h.act('cancel');
  h.reply(h.requests[0], { detail: 'synthetic failure' }, false); await action;
  assert.equal(h.button.disabled, false); assert.equal(h.timerCount(), 1); assert.equal(h.timeouts.size, 1);
  const nextPoll = h.fire(); h.reply(h.requests[1], { id: 'original', state: 'succeeded', session_id: 'primary' }); await nextPoll;
  assert.equal(h.card.dataset.runState, 'succeeded'); assert.equal(h.timerCount(), 0);
});

test('an old failed poll cannot overwrite the action error or arm a duplicate timer', async () => {
  const h = pollingFixture(); const oldPoll = h.poll(); const action = h.act('cancel');
  h.reply(h.requests[1], { detail: 'action failed' }, false); await action;
  h.reply(h.requests[0], { detail: 'stale status failure' }, false); await oldPoll;
  assert.equal(h.notes.textContent, 'action failed'); assert.equal(h.timerCount(), 1); assert.equal(h.timeouts.size, 1);
});

test('successful cancellation rejects stale in-flight status without restarting polling', async () => {
  const h = pollingFixture(); const oldPoll = h.poll(); const action = h.act('cancel');
  h.reply(h.requests[1], { id: 'original', state: 'cancelled' }); await action;
  h.reply(h.requests[0], { id: 'original', state: 'running' }); await oldPoll;
  assert.equal(h.card.dataset.runState, 'cancelled'); assert.equal(h.timerCount(), 0);
});

test('detached cards and changed run identities ignore late action failures', async () => {
  for (const change of [h => { h.card.isConnected = false; }, h => { h.card.dataset.runId = 'replacement'; }]) {
    const h = pollingFixture(); const action = h.act('cancel'); change(h);
    h.reply(h.requests[0], { detail: 'late error' }, false); await action;
    assert.equal(h.notes.textContent, ''); assert.equal(h.timerCount(), 0);
  }
});

test('repeated action dispatch while pending creates only one request', async () => {
  const h = pollingFixture(); const action = h.act('cancel'); await h.act('cancel');
  assert.equal(h.requests.length, 1);
  h.reply(h.requests[0], { id: 'original', state: 'cancelled' }); await action;
});

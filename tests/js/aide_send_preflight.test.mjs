import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8')
  .match(/let _composerSending = false;\nasync function doSend\(\) \{[\s\S]*?\n}/)?.[0];
assert.ok(source);
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };

function harness(send) {
  const drafts = new Map();
  let active = null;
  const field = { value: '  original thought\n  中文  ', style: {}, dispatchEvent() { saveDraft(); } };
  const saveDraft = () => { if (field.value.trim()) drafts.set(active, field.value); else drafts.delete(active); };
  saveDraft();
  const context = vm.createContext({
    document: { getElementById: () => field }, Event: class {},
    getActiveId: () => active, tryExecuteSlashCommand: async () => false,
    canSendMessage: () => true, saveDraft, clearDraft: id => drafts.delete(id),
    sendMessage: (text, accepted) => send(text, accepted, id => { active = id; }),
  });
  vm.runInContext(source + '\nglobalThis.send = doSend;', context);
  return { send: context.send, field, drafts, type: value => { field.value = value; saveDraft(); } };
}

test('a rejected preflight leaves the exact composer and stored draft intact', async () => {
  const h = harness(async () => {});
  const original = h.field.value;
  await h.send();
  assert.equal(h.field.value, original);
  assert.equal(h.drafts.get(null), original);
});

test('accepted first message clears the consumed draft after the new conversation owns it', async () => {
  let sent;
  const h = harness(async (text, accepted, activate) => { sent = text; activate('new-task'); accepted('new-task'); });
  await h.send();
  assert.equal(sent, 'original thought\n  中文');
  assert.equal(h.field.value, '');
  assert.equal(h.drafts.size, 0);
});

test('pending creation preserves newer input and blocks another launch', async () => {
  const gate = deferred();
  const started = deferred();
  let calls = 0;
  const h = harness(async (_text, accepted, activate) => { calls++; started.resolve(); await gate.promise; activate('new-task'); accepted('new-task'); });
  const sending = h.send();
  await started.promise;
  h.type('a newer thought');
  await h.send();
  assert.equal(calls, 1);
  gate.resolve();
  await sending;
  assert.equal(h.field.value, 'a newer thought');
  assert.equal(h.drafts.get('new-task'), 'a newer thought');
  assert.equal(h.drafts.has(null), false);
});

test('preflight failure releases the launch guard for a later retry', async () => {
  let calls = 0;
  const h = harness(async (_text, accepted, activate) => { if (++calls === 1) return; activate('new-task'); accepted('new-task'); });
  await h.send(); await h.send();
  assert.equal(calls, 2);
  assert.equal(h.field.value, '');
});

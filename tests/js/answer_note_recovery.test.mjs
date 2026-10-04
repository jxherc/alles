import { requestId } from '../../static/js/request_id.js';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { webcrypto } from 'node:crypto';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/answer_note.js', import.meta.url), 'utf8')
  .replace(/^import .*;\n/gm, '').replace(/^export /gm, '');

function harness() {
  const wraps = [], writes = [];
  const context = vm.createContext({
    crypto: webcrypto, requestId,
    document: { querySelectorAll: () => wraps, getElementById: () => null, activeElement: null, body: {} },
    saveNote: async (text, path, options) => {
      writes.push({ text, path, ...options });
      return { path, request_id: 'owned-note-request' };
    },
  });
  vm.runInContext(source + '\nglobalThis.api = { saveAnswerNote, noteSaved, reconcileAnswerNote, answerNoteText, noteSourceKey };', context);
  const add = ({ session = 'session-a', message = 'message-a', text = 'same answer', privateReply = false } = {}) => {
    const button = { disabled: false, textContent: '+note' };
    const row = { dataset: { msgId: message } };
    const wrap = {
      dataset: { sessionId: session, private: String(privateReply) }, answerText: text,
      closest: () => row, querySelector: () => button,
    };
    button.closest = () => wrap;
    wraps.push(wrap);
    return { wrap, button };
  };
  return { ...context.api, add, wraps, writes };
}

test('recovered note reconciles only the exact original reply', async () => {
  const h = harness();
  const original = h.add();
  const sameText = h.add({ message: 'message-b' });
  const otherSession = h.add({ session: 'session-b' });
  const saved = { path: 'original.md', request_id: 'receipt' };
  h.noteSaved(saved, h.answerNoteText(original.wrap), false, null, h.noteSourceKey(original.wrap));
  assert.equal(original.button.textContent, 'saved note');
  assert.equal(original.wrap.savedNote, saved);
  assert.equal(sameText.wrap.savedNote, undefined);
  assert.equal(otherSession.wrap.savedNote, undefined);
  await h.saveAnswerNote(original.button);
  assert.equal(h.writes.length, 0);
  await h.saveAnswerNote(sameText.button);
  assert.equal(h.writes.length, 1);
});

test('recovery before history rendering reconnects after the exact reply loads', () => {
  const h = harness();
  const text = 'same answer\n\n[from Aide](/?app=aide#session-a)';
  const saved = { path: 'original.md', request_id: 'receipt' };
  h.noteSaved(saved, text, false, null, 'aide:session-a:message-a');
  const original = h.add();
  h.reconcileAnswerNote(original.wrap);
  assert.equal(original.wrap.savedNote, saved);
  assert.equal(original.button.textContent, 'saved note');
});

test('changed reply text and unidentifiable legacy receipts are not falsely marked saved', () => {
  for (const mode of ['changed', 'legacy']) {
    const h = harness();
    const original = h.add();
    const text = h.answerNoteText(original.wrap);
    if (mode === 'changed') original.wrap.answerText = 'new answer';
    h.noteSaved({ path: 'original.md', request_id: 'receipt' }, text, false, null,
      mode === 'legacy' ? undefined : h.noteSourceKey(original.wrap));
    assert.equal(original.wrap.savedNote, undefined);
    assert.equal(original.button.textContent, '+note');
  }
});

test('private note identity contains no session or message identifier', async () => {
  const h = harness();
  const first = h.add({ session: 'private-session', message: 'private-message', privateReply: true });
  const second = h.add({ session: 'private-session', message: 'private-message', privateReply: true });
  await h.saveAnswerNote(first.button);
  const saved = first.wrap.savedNote;
  const key = h.writes[0].sourceKey;
  assert.match(key, /^aide-local:[a-f0-9-]{36}$/);
  assert.ok(!key.includes('private-session') && !key.includes('private-message'));
  assert.ok(!h.writes[0].text.includes('private-session'));
  assert.equal(second.wrap.savedNote, undefined);
  h.noteSaved(saved, h.writes[0].text, false, null, key);
  assert.equal(first.wrap.savedNote, saved);
  assert.equal(second.wrap.savedNote, undefined);
});

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const sessions = readFileSync(new URL('../../static/js/sessions.js', import.meta.url), 'utf8');
const chat = readFileSync(new URL('../../static/js/chat.js', import.meta.url), 'utf8');
const draftSource = sessions.slice(sessions.indexOf('const _legacyDraftKey'), sessions.indexOf('export function newChat'))
  .replace(/^export /gm, '');
const scopeSource = chat.slice(chat.indexOf('function normalizeDocumentScope'), chat.indexOf('function restoreComposerInput'));
const scope = name => ({ kind: 'vault_documents', documents: [{ path: name, expected_hash: 'saved-content-hash' }] });

function harness(storage = new Map()) {
  let privateMode = false, failWrites = false;
  const notices = [], writes = [];
  const field = { value: '', style: {}, dispatchEvent() { context.saveDraft(); } };
  const remove = { addEventListener(_name, callback) { this.click = callback; } };
  const chip = { hidden: true }, label = {};
  const context = vm.createContext({
    window: {}, Event: class {},
    document: { getElementById: id => ({ 'composer-ta': field, 'aide-document-scope': chip,
      'aide-document-scope-name': label, 'aide-document-scope-remove': remove })[id] },
    isIncognitoMode: () => privateMode,
    toast: text => notices.push(text),
    localStorage: {
      getItem: key => storage.get(key) ?? null,
      setItem(key, value) { if (failWrites) throw new Error('unavailable'); storage.set(key, value); writes.push(key); },
      removeItem: key => storage.delete(key),
    },
  });
  vm.runInContext('let _activeId = null;\n' + draftSource + scopeSource + '\nglobalThis.activate = id => { _activeId = id; restoreDraft(id); };', context);
  return { field, storage, chip, label, notices, writes,
    restore: id => context.activate(id), save: () => context.saveDraft(), clear: id => context.clearDraft(id),
    select: value => context.window._setAideDocumentScope(value), remove: () => remove.click(),
    selected: () => JSON.parse(JSON.stringify(context.window._pendingDocumentScope || null)),
    private: value => { privateMode = value; }, failWrites: value => { failWrites = value; },
  };
}

test('reload restores the exact question and selected source identity from one record', () => {
  const h = harness(); h.restore(null); h.field.value = '  what should i bring?\n中文 '; h.select(scope('trip.md'));
  const restored = harness(h.storage); restored.restore(null);
  assert.equal(restored.field.value, h.field.value);
  assert.deepEqual(restored.selected(), scope('trip.md'));
  assert.equal(restored.chip.hidden, false);
});

test('per-task restoration replaces outgoing scope and returns the matching draft', () => {
  const h = harness(); h.restore('first'); h.field.value = 'first question'; h.select(scope('first.md'));
  h.restore('second'); assert.equal(h.field.value, ''); assert.equal(h.selected(), null);
  h.field.value = 'second question'; h.select(scope('second.md'));
  h.restore('first'); assert.equal(h.field.value, 'first question'); assert.deepEqual(h.selected(), scope('first.md'));
  h.restore('second'); assert.equal(h.field.value, 'second question'); assert.deepEqual(h.selected(), scope('second.md'));
});

test('explicit scope removal survives reload without deleting the question', () => {
  const h = harness(); h.restore(null); h.field.value = 'keep this question'; h.select(scope('trip.md')); h.remove();
  const restored = harness(h.storage); restored.restore(null);
  assert.equal(restored.field.value, 'keep this question'); assert.equal(restored.selected(), null);
  assert.equal(restored.chip.hidden, true);
});

test('legacy plain-text drafts reopen without interpreting JSON-like question text', () => {
  const text = '{"text":"a question, not a saved envelope"}';
  const h = harness(new Map([['aide-draft-new', text]])); h.restore(null);
  assert.equal(h.field.value, text); assert.equal(h.selected(), null);
  const restored = harness(h.storage); restored.restore(null); assert.equal(restored.field.value, text);
});

test('consuming a draft clears both text and scope without reviving a legacy copy', () => {
  const h = harness(); h.restore('sent'); h.field.value = 'sent question'; h.select(scope('trip.md'));
  h.storage.set('aide-draft-sent', 'older copy'); h.clear('sent');
  const restored = harness(h.storage); restored.restore('sent');
  assert.equal(restored.field.value, ''); assert.equal(restored.selected(), null);
});

test('private drafts never write and never inherit a durable public note scope', () => {
  const h = harness(); h.restore(null); h.field.value = 'public question'; h.select(scope('public.md'));
  const before = [...h.storage]; const writes = h.writes.length;
  h.private(true); h.restore(null); assert.equal(h.field.value, ''); assert.equal(h.selected(), null);
  h.field.value = 'private question'; h.select(scope('private.md')); h.save(); h.clear(null);
  assert.deepEqual([...h.storage], before); assert.equal(h.writes.length, writes);
  h.private(false); h.restore(null);
  assert.equal(h.field.value, 'public question'); assert.deepEqual(h.selected(), scope('public.md'));
});

test('failed storage writes leave the previous complete record intact and warn once', () => {
  const h = harness(); h.restore(null); h.field.value = 'saved question'; h.select(scope('saved.md'));
  h.failWrites(true); h.field.value = 'new question'; h.select(scope('new.md')); h.save();
  assert.equal(h.notices.length, 1); assert.match(h.notices[0], /keep this tab open/);
  assert.equal(h.field.value, 'new question'); assert.deepEqual(h.selected(), scope('new.md'));
  const restored = harness(h.storage); restored.restore(null);
  assert.equal(restored.field.value, 'saved question'); assert.deepEqual(restored.selected(), scope('saved.md'));
});

for (const legacy of [true, false]) {
  test(`consumption at storage quota removes a ${legacy ? 'legacy' : 'scoped'} draft`, () => {
    const h = harness();
    if (legacy) h.storage.set('aide-draft-new', 'already-sent question');
    else { h.restore(null); h.field.value = 'already-sent question'; h.select(scope('sent.md')); }
    h.failWrites(true);
    h.restore(null);
    h.clear(null);
    const restored = harness(h.storage); restored.restore(null);
    assert.equal(restored.field.value, '');
    assert.equal(restored.selected(), null);
  });
}

test('clearing the active composer at quota removes its consumed legacy question', () => {
  const h = harness(new Map([['aide-draft-existing', 'consumed question']]));
  h.failWrites(true); h.restore('existing'); h.field.value = ''; h.save();
  const restored = harness(h.storage); restored.restore('existing');
  assert.equal(restored.field.value, '');
  assert.equal(restored.selected(), null);
});

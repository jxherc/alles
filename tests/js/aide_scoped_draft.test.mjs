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
    restore: id => context.activate(id), save: () => context.saveDraft(), clear: id => context.clearDraft(id), consume: (id, value, remaining) => context.consumeDraft(id, value, remaining), snapshot: id => context.getDraftSnapshot(id),
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

for (const text of ['', '   ']) {
  test(`empty-text scope survives reload and task switching: ${JSON.stringify(text)}`, () => {
    const h = harness(); h.restore('first'); h.field.value = 'original question'; h.select(scope('first.md'));
    h.field.value = text; h.save();
    const restored = harness(h.storage); restored.restore('first');
    assert.equal(restored.field.value, ''); assert.deepEqual(restored.selected(), scope('first.md'));
    assert.equal(restored.chip.hidden, false);
    restored.restore('second'); assert.equal(restored.field.value, ''); assert.equal(restored.selected(), null);
    restored.field.value = 'second question'; restored.select(scope('second.md'));
    restored.restore('first'); assert.equal(restored.field.value, ''); assert.deepEqual(restored.selected(), scope('first.md'));
  });
}

test('removing an empty-text scope stays removed after reload', () => {
  const h = harness(); h.restore(null); h.select(scope('selected.md')); h.remove();
  const restored = harness(h.storage); restored.restore(null);
  assert.equal(restored.field.value, ''); assert.equal(restored.selected(), null); assert.equal(restored.chip.hidden, true);
});

test('consuming an empty-text scoped draft clears the exact task record', () => {
  const h = harness(); h.restore('first'); h.select(scope('first.md'));
  h.restore('second'); h.select(scope('second.md')); h.clear('first');
  const restored = harness(h.storage); restored.restore('first');
  assert.equal(restored.selected(), null);
  restored.restore('second'); assert.deepEqual(restored.selected(), scope('second.md'));
});

test('an empty-text scope stays private in incognito mode', () => {
  const h = harness(); h.restore(null); h.select(scope('public.md')); const before = [...h.storage];
  h.private(true); h.restore(null); h.select(scope('private.md')); h.save(); h.clear(null);
  assert.deepEqual([...h.storage], before);
  h.private(false); h.restore(null); assert.deepEqual(h.selected(), scope('public.md'));
});


test('a late accepted question consumes only its matching stored draft', () => {
  const h = harness(); h.restore('first'); h.field.value = 'sent question'; h.select(scope('first.md'));
  const submitted = { text: h.field.value, document_scope: scope('first.md') };
  h.restore('second'); h.field.value = 'other question'; h.select(scope('second.md'));
  assert.equal(h.consume('first', submitted), true);
  const restored = harness(h.storage); restored.restore('first');
  assert.equal(restored.field.value, ''); assert.equal(restored.selected(), null);
  restored.restore('second'); assert.equal(restored.field.value, 'other question');
  assert.deepEqual(restored.selected(), scope('second.md'));
});

for (const change of ['text', 'scope']) {
  test(`a late acceptance never clears newer stored ${change}`, () => {
    const h = harness(); h.restore('first'); h.field.value = 'sent question'; h.select(scope('first.md'));
    const submitted = { text: h.field.value, document_scope: scope('first.md') };
    if (change === 'text') h.field.value = 'newer question';
    else h.select(scope('newer.md'));
    h.save(); const before = [...h.storage];
    assert.equal(h.consume('first', submitted), false);
    assert.deepEqual([...h.storage], before);
  });
}

test('late acceptance at quota still clears the matching consumed draft', () => {
  const h = harness(); h.restore('first'); h.field.value = 'sent question'; h.select(scope('first.md'));
  h.failWrites(true);
  assert.equal(h.consume('first', { text: h.field.value, document_scope: scope('first.md') }), true);
  const restored = harness(h.storage); restored.restore('first');
  assert.equal(restored.field.value, ''); assert.equal(restored.selected(), null);
});


test('a scoped acceptance at quota consumes its unmigrated legacy text but preserves a different draft', () => {
  const h = harness(new Map([['aide-draft-new', 'already-sent question']]));
  h.failWrites(true);
  const sent = { text: 'already-sent question', document_scope: scope('sent.md') };
  assert.equal(h.consume(null, sent), true);
  h.storage.set('aide-draft-new', 'newer question');
  assert.equal(h.consume(null, sent), false);
  const restored = harness(h.storage); restored.restore(null);
  assert.equal(restored.field.value, 'newer question');
});


test('quota recovery retires the exact old draft snapshot without erasing a newer source choice', () => {
  const h = harness(); h.restore(null); h.field.value = 'sent question'; h.save();
  h.failWrites(true); h.select(scope('submitted.md'));
  const old = h.snapshot(null);
  assert.equal(h.consume(null, old), true);
  h.failWrites(false); h.select(scope('newer.md'));
  assert.equal(h.consume(null, old), false);
  const restored = harness(h.storage); restored.restore(null);
  assert.deepEqual(restored.selected(), scope('newer.md'));
});


test('programmatic acceptance clears only the consumed scope from an inactive draft', () => {
  const h = harness(); h.restore('first'); h.field.value = 'unsubmitted text'; h.select(scope('source.md'));
  const observed = h.snapshot('first'); h.restore('second');
  assert.equal(h.consume('first', observed, observed.text), true);
  const restored = harness(h.storage); restored.restore('first');
  assert.equal(restored.field.value, 'unsubmitted text'); assert.equal(restored.selected(), null);
});

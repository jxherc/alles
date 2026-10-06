import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/chat.js', import.meta.url), 'utf8');
const helper = source.slice(source.indexOf('function holdDocumentDraft'), source.indexOf('export async function sendMessage'));
const scope = { kind: 'vault_document', path: 'local.md', expected_hash: 'saved-version' };

function setup() {
  const state = { id: 'original', generation: 1, private: false, files: ['original-file'], pending: false };
  const draft = { text: '  exact question\n中文 ', document_scope: scope };
  const field = { value: draft.text, style: {}, dispatchEvent() {}, focus() { state.focused = true; } };
  const window = { _pendingDocumentScope: scope, _setAideDocumentScope(value) { this._pendingDocumentScope = value; } };
  const consumed = [];
  const context = vm.createContext({
    document: { getElementById: () => field }, window, Event: class {},
    getActiveId: () => state.id, getComposerGeneration: () => state.generation,
    isIncognitoMode: () => state.private, getAttachments: () => state.files,
    hasPendingAttachments: () => state.pending, clearAttachments: ids => { state.files = state.files.filter(id => !ids.includes(id)); },
    consumeDraft: (id, value) => consumed.push({ id, value }), getDraftSnapshot: () => draft, normalizeDocumentScope: value => value,
    restoreDocumentScope: value => { window._pendingDocumentScope = value; },
    restoreComposerInput: value => { field.value = value; },
  });
  vm.runInContext(helper, context);
  return { state, draft, field, window, consumed,
    hold: () => context.holdDocumentDraft('original', draft, ['original-file'], state.private) };
}

test('refusal retains the exact question, source and attachment; acceptance consumes them once', () => {
  const h = setup(), held = h.hold();
  assert.equal(h.field.value, h.draft.text);
  assert.deepEqual(h.window._pendingDocumentScope, scope);
  assert.deepEqual(h.state.files, ['original-file']);
  held.accept();
  assert.equal(h.field.value, '');
  assert.equal(h.window._pendingDocumentScope, null);
  assert.deepEqual(h.state.files, []);
  h.field.value = 'next question'; h.window._pendingDocumentScope = scope;
  held.accept();
  assert.equal(h.field.value, 'next question');
  assert.deepEqual(h.window._pendingDocumentScope, scope);
  assert.equal(h.state.focused, undefined);
});

for (const change of ['text', 'scope', 'files', 'upload', 'private']) {
  test(`a late acceptance preserves newer ${change} and the rest of the composer`, () => {
    const h = setup(), held = h.hold();
    if (change === 'text') h.field.value = 'newer question';
    if (change === 'scope') h.window._pendingDocumentScope = { ...scope, path: 'newer.md' };
    if (change === 'files') h.state.files = ['original-file', 'newer-file'];
    if (change === 'upload') h.state.pending = true;
    if (change === 'private') h.state.private = true;
    const before = JSON.stringify([h.field.value, h.window._pendingDocumentScope]);
    held.accept(); held.restore('');
    assert.equal(JSON.stringify([h.field.value, h.window._pendingDocumentScope]), before);
    assert.equal(h.state.focused, undefined);
    assert.deepEqual(h.state.files, change === 'files' ? ['newer-file'] : []);
    if (change === 'upload') assert.equal(h.state.pending, true);
  });
}

test('acceptance after switching tasks consumes only the originating stored draft', () => {
  const h = setup(), held = h.hold();
  h.state.id = 'other'; h.state.generation++;
  h.field.value = 'other task question';
  held.accept();
  assert.equal(h.field.value, 'other task question');
  assert.deepEqual(h.consumed, [{ id: 'original', value: h.draft }]);
});

test('a private send never consumes a public stored draft after a task switch', () => {
  const h = setup(); h.state.private = true;
  const held = h.hold(); h.state.id = 'other'; h.state.private = false;
  held.accept();
  assert.deepEqual(h.consumed, []);
});

test('interruption restores the owned empty composer but cannot overwrite subsequent edits', () => {
  const h = setup(), held = h.hold();
  held.accept(); held.restore('');
  assert.equal(h.field.value, h.draft.text);
  assert.deepEqual(h.window._pendingDocumentScope, scope);
  h.field.value = 'new question'; h.window._pendingDocumentScope = { ...scope, path: 'new.md' };
  held.restore('');
  assert.equal(h.field.value, 'new question');
  assert.equal(h.window._pendingDocumentScope.path, 'new.md');
});

test('an interrupted old task never restores into another task or a later visit', () => {
  const h = setup(), held = h.hold();
  held.accept(); h.state.generation++;
  held.restore('');
  assert.equal(h.field.value, '');
  assert.equal(h.window._pendingDocumentScope, null);
});


test('a public acceptance consumes its stored draft without changing a private composer', () => {
  const h = setup(), held = h.hold();
  h.state.private = true; h.field.value = 'private question';
  held.accept();
  assert.equal(h.field.value, 'private question');
  assert.deepEqual(h.consumed, [{ id: 'original', value: h.draft }]);
});


for (const text of ['', 'another unsent question']) {
  test(`programmatic acceptance consumes the unchanged scope while preserving ${JSON.stringify(text)}`, () => {
    const h = setup(); h.field.value = text; h.draft.text = text;
    const context = vm.createContext({
      document: { getElementById: () => h.field }, window: h.window, Event: class {},
      getActiveId: () => 'original', getComposerGeneration: () => 1,
      isIncognitoMode: () => false, getAttachments: () => [], hasPendingAttachments: () => false,
      clearAttachments() {}, consumeDraft() {}, normalizeDocumentScope: value => value,
    });
    vm.runInContext(helper, context);
    const held = context.holdDocumentDraft('original', h.draft, [], false, { ownsText: false });
    held.accept();
    assert.equal(h.field.value, text);
    assert.equal(h.window._pendingDocumentScope, null);
  });
}


const sessionsSource = readFileSync(new URL('../../static/js/sessions.js', import.meta.url), 'utf8');
const storedDraftHelper = sessionsSource.slice(sessionsSource.indexOf('const _legacyDraftKey'), sessionsSource.indexOf('export function newChat')).replace(/^export /gm, '');
for (const quota of [true, false]) {
  test(`accepted stored question is consumed without losing a newer composer: quota=${quota}`, () => {
    const storage = new Map();
    const state = { quota: false };
    const question = '  submitted question\n中文  ';
    const newer = 'newer exact question 草稿';
    const field = { value: question, style: {}, dispatchEvent() {} };
    const window = { _pendingDocumentScope: scope, _setAideDocumentScope(value) { this._pendingDocumentScope = value; } };
    const context = vm.createContext({
      document: { getElementById: () => field }, window, Event: class {},
      _activeId: 'original', getActiveId: () => 'original', getComposerGeneration: () => 1,
      isIncognitoMode: () => false, getAttachments: () => [], hasPendingAttachments: () => false,
      clearAttachments() {}, normalizeDocumentScope: value => value, toast() {},
      localStorage: {
        getItem: key => storage.get(key) ?? null,
        setItem(key, value) { if (state.quota) throw new Error('synthetic quota'); storage.set(key, value); },
        removeItem: key => storage.delete(key),
      },
    });
    vm.runInContext(storedDraftHelper + '\n' + helper, context);
    context.saveDraft();
    const held = context.holdDocumentDraft('original', {text:question,document_scope:scope}, [], false);
    state.quota = quota;
    field.value = newer;
    context.saveDraft();
    held.accept();
    assert.equal(field.value, newer);
    assert.equal(window._pendingDocumentScope, scope);
    const stored = storage.get('aide-draft-v2-original');
    if (quota) assert.equal(stored, undefined);
    else assert.deepEqual(JSON.parse(stored), {text:newer,document_scope:scope});
  });
}

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { t, tp } from '../../static/js/i18n.js';
import { esc } from '../../static/js/escape.js';

globalThis.window = {};
const { provenanceLabels } = await import('../../static/js/memoryactions.js');
const chat = readFileSync(new URL('../../static/js/chat.js', import.meta.url), 'utf8');
const scopeRenderer = chat.slice(chat.indexOf('function renderDocumentScope'), chat.indexOf('window._setAideDocumentScope'));
const sessions = readFileSync(new URL('../../static/js/sessions.js', import.meta.url), 'utf8');
const escaping = '';
const turnRenderer = sessions.slice(sessions.indexOf('export function appendUserMsg'), sessions.indexOf('export function appendInterruptionNotice')).replace(/^export /gm, '');

for (const count of [1, 2]) {
  test(`selected source labels match ${count} saved notes in composer, turn and context`, () => {
    const paths = Array.from({ length: count }, (_, index) => ({ path: `note-${index}.md`, expected_hash: 'owned-saved-version' }));
    const scope = { kind: 'vault_documents', documents: paths };
    const label = {}, chip = {}, turn = {};
    const context = vm.createContext({ escHtml: esc, t, tp, tr: t, trp: tp,
      document: { getElementById(id) { return { 'aide-document-scope': chip, 'aide-document-scope-name': label, messages: { appendChild() {} } }[id]; } },
      _makeRow() { return { row: turn }; }, scrollDown() {}, _wireEditButtons() {},
    });
    vm.runInContext(escaping + '\n' + scopeRenderer + '\n' + turnRenderer, context);
    context.renderDocumentScope(scope);
    context.appendUserMsg('what should i bring?', scope);
    const noun = count === 1 ? 'note' : 'notes';
    assert.equal(chip.hidden, false);
    assert.equal(label.textContent, `${count} ${noun} only · ${paths.map(item => item.path).join(', ')}`);
    assert.ok(turn.innerHTML.includes(`<summary>selected notes only · ${count} ${noun}</summary>`));
    for (const item of paths) assert.ok(turn.innerHTML.includes(`<li>${item.path}</li>`));
    assert.deepEqual(provenanceLabels({ document: scope }), [`${count} selected ${noun} only`]);
  });
}

test('a handed-off question shows where it came from and its sources, never the context', () => {
  const turn = {};
  const context = vm.createContext({ escHtml: esc, t, tp,
    document: { getElementById() { return { appendChild() {} }; } },
    _makeRow() { return { row: turn }; }, scrollDown() {}, _wireEditButtons() {},
  });
  vm.runInContext(escaping + '\n' + turnRenderer, context);
  const scope = {
    kind: 'handoff', app: 'andromeda', context: 'Explain this search. {"query":"HIDDEN"}',
    sources: [{ title: 'worksheet <b>', url: 'https://example.invalid/ws' }, { title: 'bad', url: 'javascript:alert(1)' }],
  };
  context.appendUserMsg('when is it due?', scope);
  assert.ok(turn.innerHTML.includes('<summary>from andromeda</summary>'));
  assert.ok(turn.innerHTML.includes('<a href="https://example.invalid/ws" target="_blank" rel="noopener noreferrer">worksheet &lt;b&gt;</a>'));
  assert.ok(!turn.innerHTML.includes('javascript:'));
  assert.ok(!turn.innerHTML.includes('HIDDEN'));
  assert.ok(turn.innerHTML.includes('<div class="user-bubble">when is it due?</div>'));
  assert.equal(turn.contextScope, scope);
  // the ask panel hands no links: a quiet line, no disclosure
  context.appendUserMsg('which is first?', { kind: 'handoff', app: 'plan · tasks', context: 'screen' });
  assert.ok(turn.innerHTML.includes('<div class="user-context-scope">from plan · tasks</div>'));
});

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

globalThis.window = {};
const { provenanceLabels } = await import('../../static/js/memoryactions.js');
const chat = readFileSync(new URL('../../static/js/chat.js', import.meta.url), 'utf8');
const scopeRenderer = chat.slice(chat.indexOf('function renderDocumentScope'), chat.indexOf('window._setAideDocumentScope'));
const sessions = readFileSync(new URL('../../static/js/sessions.js', import.meta.url), 'utf8');
const escaping = sessions.slice(sessions.indexOf('function escHtml'), sessions.indexOf('\n}', sessions.indexOf('function escHtml')) + 2);
const turnRenderer = sessions.slice(sessions.indexOf('export function appendUserMsg'), sessions.indexOf('export function appendInterruptionNotice')).replace(/^export /gm, '');

for (const count of [1, 2]) {
  test(`selected source labels match ${count} saved notes in composer, turn and context`, () => {
    const paths = Array.from({ length: count }, (_, index) => ({ path: `note-${index}.md`, expected_hash: 'owned-saved-version' }));
    const scope = { kind: 'vault_documents', documents: paths };
    const label = {}, chip = {}, turn = {};
    const context = vm.createContext({
      document: { getElementById(id) { return { 'aide-document-scope': chip, 'aide-document-scope-name': label, messages: { appendChild() {} } }[id]; } },
      _makeRow() { return { row: turn }; }, scrollDown() {},
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

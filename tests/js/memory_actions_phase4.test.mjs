import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

globalThis.window = {};

const { memoryProvenanceLabel, provenanceLabels } = await import('../../static/js/memoryactions.js');

test('response provenance names every private context source', () => {
  const labels = provenanceLabels({
    owner_instructions: true,
    project_instructions: true,
    persona: { name: 'coder' },
    memories: [{ id: 'one' }, { id: 'two' }],
    endpoint: 'local ollama',
    model: 'small-model',
  });
  assert.deepEqual(labels, [
    'owner instructions',
    'Project instructions',
    'persona: coder',
    '2 memories',
    'local ollama / small-model',
  ]);
});

test('empty provenance stays quiet', () => {
  assert.deepEqual(provenanceLabels({}), []);
});

test('each visible memory provenance label includes its id and scope', () => {
  assert.equal(memoryProvenanceLabel({ id: 'mem-123', scope: 'project' }), 'project memory');
  assert.equal(memoryProvenanceLabel({ id: 'mem-456' }), 'global memory');
  const source = readFileSync(new URL('../../static/js/memoryactions.js', import.meta.url), 'utf8');
  assert.match(source, /safe\(memoryProvenanceLabel\(memory\)\)/);
});

// a bare double: the receipt span's markup gives it one undo button, plain text takes it away
function rememberHarness({ projectId = '' } = {}) {
  const focused = [];
  const doc = { activeElement: null, body: { id: 'body' } };
  let undo = null;
  const button = {
    disabled: false, textContent: 'remember', replaced: null,
    closest: () => ({ querySelector: () => ({ textContent: 'keep my bike in the shed' }) }),
    replaceWith(node) { this.replaced = node; if (doc.activeElement === this) doc.activeElement = doc.body; },
    focus() { doc.activeElement = this; focused.push('remember'); },
  };
  globalThis.window._currentSession = { id: 'session', project_id: projectId };
  globalThis.document = {
    get activeElement() { return doc.activeElement; },
    body: doc.body,
    createElement() {
      const node = {
        html: '', text: '', tabIndex: 0,
        set innerHTML(value) {
          this.html = value;
          undo = {
            listeners: {}, addEventListener(type, handler) { this.listeners[type] = handler; },
            focus() { doc.activeElement = this; focused.push('undo'); },
          };
        },
        set textContent(value) { this.text = value; if (doc.activeElement === undo) doc.activeElement = doc.body; undo = null; },
        get textContent() { return this.text; },
        querySelector: () => undo,
        focus() { doc.activeElement = this; focused.push('receipt'); },
      };
      return node;
    },
  };
  globalThis.fetch = async (_url, options = {}) => ({
    ok: true, json: async () => (options.method === 'POST' ? { id: 'memory-1' } : {}),
  });
  doc.activeElement = button;
  return { button, focused, undo: () => undo };
}

test('remember hands focus to undo, and undo leaves it on the receipt', async () => {
  const { rememberUserMessage } = await import('../../static/js/memoryactions.js');
  const h = rememberHarness();
  await rememberUserMessage(h.button);
  assert.match(h.button.replaced.html, /^remembered globally · <button/);
  assert.deepEqual(h.focused, ['undo']);
  await h.undo().listeners.click();
  assert.equal(h.button.replaced.text, 'memory undone');
  assert.equal(h.button.replaced.tabIndex, -1);
  assert.deepEqual(h.focused, ['undo', 'receipt']);
});

test('a project memory receipt reads in plain lowercase', async () => {
  const { rememberUserMessage } = await import('../../static/js/memoryactions.js');
  const h = rememberHarness({ projectId: 'project-1' });
  await rememberUserMessage(h.button);
  assert.match(h.button.replaced.html, /^remembered in this project · /);
});

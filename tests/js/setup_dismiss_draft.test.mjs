import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/setupwizard.js', import.meta.url), 'utf8')
  .replace(/import\s+[\s\S]*?from\s+['"][^'"]+['"];\r?\n/g, '')
  .replace(/^export /gm, '');

function harness({ loading = false } = {}) {
  const nodes = new Map();
  const document = { activeElement: null, getElementById: id => nodes.get(id) };
  const node = id => ({ id, disabled: false, isConnected: true, attributes: {}, dataset: {},
    setAttribute(key, value) { this.attributes[key] = value; },
    getAttribute(key) { return this.attributes[key] ?? null; },
    removeAttribute(key) { delete this.attributes[key]; },
    focus() { document.activeElement = this; },
  });
  for (const id of ['setup-skip', 'setup-wizard', 'sw-status', 'sw-name']) nodes.set(id, node(id));
  if (!loading) nodes.set('sw-save', node('sw-save'));
  nodes.get('sw-name').value = 'unsaved owner';
  nodes.get('setup-wizard').setAttribute('aria-busy', String(loading));
  document.activeElement = nodes.get('sw-name');
  const calls = [], notices = [];
  const context = vm.createContext({ document, toast: (...args) => notices.push(args), calls,
    fetch: async path => {
      calls.push(path);
      return { ok: false, json: async () => ({ detail: 'pause refused; try again' }) };
    },
  });
  vm.runInContext(source + `
    openSetupWizard = async () => {
      calls.push('reload wizard');
      document.getElementById('sw-name').value = '';
    };
    globalThis.subject = _dismiss;
  `, context);
  return { dismiss: context.subject, nodes, document, calls, notices };
}

test('refused dismissal keeps the rendered draft and an actionable error', async () => {
  const h = harness();
  await h.dismiss();
  assert.equal(h.nodes.get('sw-name').value, 'unsaved owner');
  assert.deepEqual(h.calls, ['/api/setup/dismiss']);
  assert.equal(h.nodes.get('sw-status').textContent, 'pause refused; try again');
  assert.equal(h.nodes.get('setup-skip').disabled, false);
  assert.equal(h.document.activeElement, h.nodes.get('setup-skip'));
});

test('refused dismissal during initial loading restarts the invalidated load', async () => {
  const h = harness({ loading: true });
  await h.dismiss();
  assert.deepEqual(h.calls, ['/api/setup/dismiss', 'reload wizard']);
});

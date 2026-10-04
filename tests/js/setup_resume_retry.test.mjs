import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/setupwizard.js', import.meta.url), 'utf8')
  .replace(/import\s+[\s\S]*?from\s+['"][^'"]+['"];\r?\n/g, '')
  .replace(/^export /gm, '');

function harness({ resume, completed = false }) {
  const nodes = new Map();
  for (const id of ['setup-wizard', 'setup-wizard-body', 'sw-load-close', 'sw-load-retry']) {
    nodes.set(id, { style: { display: 'none' }, dataset: {}, attributes: {}, events: {},
      setAttribute(key, value) { this.attributes[key] = value; },
      addEventListener(name, fn) { this.events[name] = fn; },
    });
  }
  let dismissed = resume, failed = false;
  const calls = [], rendered = [];
  const context = vm.createContext({
    document: { getElementById: id => nodes.get(id), activeElement: null }, HTMLElement: class {},
    fetch: async (path, options = {}) => {
      calls.push([path, options.method || 'GET']);
      if (!failed && path === (resume ? '/api/setup/resume' : '/api/setup/status')) {
        failed = true;
        return { ok: false, json: async () => ({ detail: 'synthetic setup interruption' }) };
      }
      if (path === '/api/setup/resume') dismissed = false;
      return { ok: true, json: async () => path === '/api/auth/me' ? { enabled: false }
        : { setup: { dismissed, completed, next_step: completed ? 'done' : 'basics' } } };
    },
    rendered,
  });
  vm.runInContext(source + `
    _bindModal = () => {};
    _anotherDialogOpen = () => false;
    _render = () => rendered.push({ completed: _state.completed, step: _step });
    globalThis.subject = openSetupWizard;
  `, context);
  return { open: context.subject, calls, rendered, nodes, dismiss: () => { dismissed = true; } };
}

for (const completed of [false, true]) {
  test(`retry retains explicit resume after a failed resume request (${completed ? 'completed' : 'paused'})`, async () => {
    const h = harness({ resume: true, completed });
    await h.open({ resume: true });
    assert.equal(h.nodes.get('setup-wizard').dataset.loadFailed, '1');
    assert.equal(h.rendered.length, 0);
    await h.nodes.get('sw-load-retry').events.click();
    assert.equal(h.calls.filter(([path]) => path === '/api/setup/resume').length, 2);
    assert.equal(h.rendered.length, 1);
    assert.equal(h.rendered[0].completed, completed);
    assert.equal(h.nodes.get('setup-wizard').style.display, 'flex');
  });
}

test('automatic first-load retry remains an automatic load', async () => {
  const h = harness({ resume: false });
  await h.open();
  await h.nodes.get('sw-load-retry').events.click();
  assert.equal(h.calls.filter(([path]) => path === '/api/setup/resume').length, 0);
  assert.equal(h.rendered.length, 1);
});

test('automatic retry does not undo a dismissal made while the load failed', async () => {
  const h = harness({ resume: false });
  await h.open();
  h.dismiss();
  await h.nodes.get('sw-load-retry').events.click();
  assert.equal(h.calls.filter(([path]) => path === '/api/setup/resume').length, 0);
  assert.equal(h.rendered.length, 0);
  assert.equal(h.nodes.get('setup-wizard').style.display, 'none');
});

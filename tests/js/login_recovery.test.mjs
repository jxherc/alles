import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const app = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
const source = app.slice(app.indexOf('function _showLoginScreen()'), app.indexOf('\ninit();'));

function harness(request) {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      value: 'retained-password', textContent: '', disabled: false,
      style: {}, dataset: {}, attributes: {}, listeners: {},
      addEventListener(type, handler) { this.listeners[type] = handler; },
      setAttribute(key, value) { this.attributes[key] = value; },
      removeAttribute(key) { delete this.attributes[key]; },
      click() { if (!this.disabled) return this.listeners.click(); },
    });
    return elements.get(id);
  };
  let boots = 0;
  const context = vm.createContext({
    document: {
      getElementById: element,
      body: { classList: { add() {}, remove() {} } },
    },
    fetch: request, _pendingSso: null,
    _boot() { boots += 1; },
  });
  vm.runInContext(source + '\n_showLoginScreen();', context);
  return { element, submit: () => element('login-submit').click(), boots: () => boots };
}

for (const [status, message, invalid] of [
  [401, /wrong password/, 'true'],
  [429, /too many attempts/, undefined],
  [503, /temporarily unavailable/, undefined],
]) {
  test(`login ${status} reports its failure inline and retains the password`, async () => {
    const h = harness(async () => ({ ok: false, status }));
    await h.submit();
    assert.match(h.element('login-error').textContent, message);
    assert.equal(h.element('login-pw').value, 'retained-password');
    assert.equal(h.element('login-pw').attributes['aria-invalid'], invalid);
    assert.equal(h.element('login-submit').disabled, false);
    assert.equal(h.boots(), 0);
  });
}

test('failed transport is recoverable and a successful retry clears the error', async () => {
  let calls = 0;
  const h = harness(async () => {
    if (++calls === 1) throw new TypeError('Failed to fetch');
    return { ok: true, status: 200 };
  });
  await h.submit();
  assert.match(h.element('login-error').textContent, /could not reach Alles/);
  assert.equal(h.element('login-submit').disabled, false);
  await h.submit();
  assert.equal(h.element('login-error').textContent, '');
  assert.equal(h.element('login-screen').style.display, 'none');
  assert.equal(h.boots(), 1);
});

test('repeated click and Enter while pending send one login request', async () => {
  let release;
  let calls = 0;
  const h = harness(() => {
    calls += 1;
    return new Promise(resolve => { release = resolve; });
  });
  const pending = h.submit();
  assert.equal(h.element('login-submit').disabled, true);
  await h.submit();
  h.element('login-pw').listeners.keydown({ key: 'Enter' });
  assert.equal(calls, 1);
  release({ ok: true, status: 200 });
  await pending;
  assert.equal(h.boots(), 1);
  assert.equal(h.element('login-submit').disabled, false);
});

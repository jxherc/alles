import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/skills.js', import.meta.url), 'utf8')
  .replace(/^import .*;\n/gm, '').replace(/^export /gm, '');

function harness() {
  const elements = new Map(), writes = [], toasts = [], timers = [], disk = new Map();
  let held = null, fail = false, created = 0, document;
  function element(id) {
    return {
      id, value: '', hidden: false, disabled: false, isConnected: true, textContent: '',
      classList: { add() {}, remove() {}, toggle() {} }, dataset: {},
      setAttribute() {}, removeAttribute() {}, closest() { return null; },
      focus() { document.activeElement = this; }, getClientRects: () => [{}],
      querySelectorAll: () => [], contains: target => target?.id?.startsWith('skl-d-'),
      set innerHTML(html) {
        for (const match of html.matchAll(/\bid="([^"]+)"/g)) elements.set(match[1], element(match[1]));
      },
    };
  }
  elements.set('skl-drawer-host', element('skl-drawer-host'));
  elements.set('skl-new', element('skl-new'));
  document = { getElementById: id => elements.get(id), querySelectorAll: () => [], activeElement: elements.get('skl-new') };
  const fetcher = async (url, options = {}) => {
    if (!options.method) return { ok: true, json: async () => url === '/api/skills' ? [...disk.values()] : disk.get(url.split('/').at(-1)) };
    const body = JSON.parse(options.body); writes.push({ url, method: options.method, body });
    if (held) { const barrier = held; held = null; await barrier; }
    if (fail) { fail = false; return { ok: false, status: 503, json: async () => ({ detail: 'synthetic refusal' }) }; }
    const slug = options.method === 'POST' ? `skill-${++created}` : url.split('/').at(-1);
    const result = { ...body, slug }; disk.set(slug, result); return { ok: true, json: async () => result };
  };
  const context = vm.createContext({
    document, fetch: fetcher, toast: (message, kind) => toasts.push({ message, kind }),
    setTimeout: callback => timers.push(callback), clearTimeout() {},
    createFocusBoundary: () => ({ activate() {}, deactivate() {}, destroy() {} }),
  });
  vm.runInContext(source + '\nglobalThis.subject = { open: slug => _openDrawer(slug, document.getElementById("skl-new")), close: _closeDrawer, save: _save, current: () => _cur };', context);
  return {
    ...context.subject, get: id => elements.get(id), writes, toasts, disk, timers,
    hold() { let release; held = new Promise(resolve => { release = resolve; }); return release; },
    refuse() { fail = true; },
  };
}

test('late create A cannot bind new drawer B to A or change its Save target', async () => {
  const h = harness(); await h.open(null); h.get('skl-d-name').value = 'A';
  const release = h.hold(); const pending = h.save(); h.close(); await h.open(null);
  h.get('skl-d-name').value = 'B'; h.get('skl-d-body').value = 'B procedure';
  release(); await pending;
  assert.equal(h.current(), null);
  assert.equal(h.get('skl-d-heading').textContent, 'new skill');
  assert.equal(h.get('skl-d-status').textContent, '');
  await h.save();
  assert.equal(h.writes[1].method, 'POST');
  assert.equal(h.disk.get('skill-1').name, 'A');
  assert.equal(h.disk.get('skill-2').body, 'B procedure');
});

test('a pending create is sent once and newer typing survives its receipt', async () => {
  const h = harness(); await h.open(null); h.get('skl-d-name').value = 'A';
  const release = h.hold(); const pending = h.save();
  h.get('skl-d-body').value = 'newer procedure'; const repeated = h.save();
  assert.equal(h.writes.length, 1);
  release(); await Promise.all([pending, repeated]);
  assert.equal(h.get('skl-d-body').value, 'newer procedure');
  assert.notEqual(h.get('skl-d-status').textContent, 'saved');
  await h.save();
  assert.equal(h.writes.at(-1).url, '/api/skills/skill-1');
  assert.equal(h.disk.get('skill-1').body, 'newer procedure');
});

test('late failure and old status timers cannot change another drawer', async () => {
  const h = harness(); await h.open(null); h.get('skl-d-name').value = 'A'; await h.save();
  h.close(); await h.open(null); h.get('skl-d-status').textContent = 'B status';
  h.timers.forEach(callback => callback());
  assert.equal(h.get('skl-d-status').textContent, 'B status');
  h.get('skl-d-name').value = 'B'; const release = h.hold(); h.refuse(); const pending = h.save();
  h.close(); await h.open(null); h.get('skl-d-name').value = 'C'; release(); await pending;
  assert.equal(h.current(), null);
  assert.equal(h.get('skl-d-name').value, 'C');
  assert.equal(h.get('skl-d-heading').textContent, 'new skill');
});

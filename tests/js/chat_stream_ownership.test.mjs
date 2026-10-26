import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { t, tp } from '../../static/js/i18n.js';

const source = readFileSync(new URL('../../static/js/chat.js', import.meta.url), 'utf8')
  .replace(/import\s+[\s\S]*?from\s+['"][^'"]+['"];\r?\n/g, '')
  .replace(/^export /gm, '');

function harness({ stopReply = { ok: true } } = {}) {
  const requests = [];
  const focused = [];
  const elements = new Map();
  const get = id => {
    if (!elements.has(id)) elements.set(id, {
      disabled: false, addEventListener() {}, attrs: {}, title: '',
      setAttribute(name, value) { this.attrs[name] = String(value); }, removeAttribute(name) { delete this.attrs[name]; },
      classList: { toggle() {}, contains: () => false },
      contains(node) { return node === this; }, focus() { focused.push(id); document.activeElement = this; },
    });
    return elements.get(id);
  };
  const document = { getElementById: get, activeElement: null, body: null };
  const context = vm.createContext({
    window: {}, document, mdToHtml() {}, AbortController, setTimeout, t, tp, tr: t, trp: tp,
    getActiveId: () => 'newly-selected-session',
    fetch: async (url, options) => {
      requests.push({ url, method: options.method, body: options.body && JSON.parse(options.body) });
      return { json: async () => stopReply };
    },
  });
  vm.runInContext(source + `
    globalThis.subject = {
      stop: stopStream, canSend: canSendMessage,
      begin: id => {
        const ctrl = new AbortController();
        let end;
        _chatStreamDone = new Promise(resolve => { end = resolve; });
        _chatAbort = ctrl; _chatSessionId = id; _chatTurnToken = 'turn-' + id; setStreaming(true);
        // the stream's own end, as streamReply's finally would do it
        ctrl.finish = () => { setStreaming(false); end(); };
        return ctrl;
      },
    };
  `, context);
  return { ...context.subject, requests, get, focused, document };
}

const tick = () => new Promise(resolve => setTimeout(resolve, 0));

test('Stop names its own turn, keeps reading until the server ends it, then lets go', async () => {
  const h = harness();
  const controller = h.begin('originating-session');
  assert.equal(h.canSend(), false);
  h.stop();
  // the server hears the stop first (a regenerate keeps words the owner chose to stop at), and
  // only this turn's token can stop anything: a late stop never ends the next turn
  assert.deepEqual(h.requests, [{ url: '/api/chat/stop/originating-session', method: 'POST', body: { turn_token: 'turn-originating-session' } }]);
  // until the old stream ends, send stays off (the words stay put) and stop says it's stopping
  assert.equal(h.canSend(), false);
  assert.equal(h.get('send-btn').disabled, true);
  assert.equal(h.get('stop-btn').attrs['aria-label'], 'stopping…');
  assert.equal(h.get('stop-btn').attrs['aria-disabled'], 'true');
  await tick(); await tick();
  // the server said it stopped this turn: the page keeps reading for its last word
  assert.equal(controller.signal.aborted, false);
  controller.finish();
  await tick(); await tick();
  assert.equal(controller.signal.aborted, true);
  assert.equal(h.canSend(), true);
  assert.equal(h.get('send-btn').disabled, false);
  assert.equal(h.get('stop-btn').attrs['aria-label'], 'stop');
  assert.equal(h.get('stop-btn').attrs['aria-disabled'], undefined);
});

test('a stop the server did not act on drops the stream at once', async () => {
  const h = harness({ stopReply: { ok: false, reason: 'turn_changed' } });
  const controller = h.begin('originating-session');
  h.stop();
  await tick(); await tick();
  assert.equal(controller.signal.aborted, true);
});

test('repeated Stop never sends cancellation to the newly selected session', () => {
  const h = harness();
  h.begin('originating-session');
  h.stop(); h.stop();
  assert.equal(h.requests.length, 1);
});

test('Stop with no active foreground request does not target a selected session', () => {
  const h = harness();
  h.stop();
  assert.deepEqual(h.requests, []);
});

test('Stop hands focus to the composer once the stop button hides', () => {
  const h = harness();
  const controller = h.begin('originating-session');
  h.document.activeElement = h.get('stop-btn');
  h.stop();
  // still stopping: focus stays on the (aria-disabled) stop button, never the page
  assert.deepEqual(h.focused, []);
  controller.finish();
  assert.deepEqual(h.focused, ['composer-ta']);
});

test('Stop leaves focus alone when it already sits somewhere real', () => {
  const h = harness();
  const controller = h.begin('originating-session');
  h.document.activeElement = h.get('composer-search');
  h.stop();
  controller.finish();
  assert.deepEqual(h.focused, []);
});

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/chat.js', import.meta.url), 'utf8')
  .replace(/import\s+[\s\S]*?from\s+['"][^'"]+['"];\r?\n/g, '')
  .replace(/^export /gm, '');

function harness() {
  const requests = [];
  const elements = new Map();
  const get = id => {
    if (!elements.has(id)) elements.set(id, {
      disabled: false, addEventListener() {},
      classList: { toggle() {} },
    });
    return elements.get(id);
  };
  const context = vm.createContext({
    window: {}, document: { getElementById: get }, mdToHtml() {}, AbortController,
    getActiveId: () => 'newly-selected-session',
    fetch: async (url, options) => { requests.push({ url, method: options.method }); },
  });
  vm.runInContext(source + `
    globalThis.subject = {
      stop: stopStream, canSend: canSendMessage,
      begin: id => {
        const ctrl = new AbortController();
        _chatAbort = ctrl; _chatSessionId = id; setStreaming(true);
        return ctrl;
      },
    };
  `, context);
  return { ...context.subject, requests, get };
}

test('Stop aborts and targets the originating stream after selection changes', () => {
  const h = harness();
  const controller = h.begin('originating-session');
  assert.equal(h.canSend(), false);
  h.stop();
  assert.equal(controller.signal.aborted, true);
  assert.deepEqual(h.requests, [{ url: '/api/chat/stop/originating-session', method: 'POST' }]);
  assert.equal(h.canSend(), true);
  assert.equal(h.get('send-btn').disabled, false);
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

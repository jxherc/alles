import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/sessions.js', import.meta.url), 'utf8')
  .replace(/import\s+[\s\S]*?from\s+['"][^'"]+['"];\r?\n/g, '')
  .replace(/^export /gm, '');

function harness() {
  function element() {
    return {
      children: [], dataset: {}, className: '', attributes: {}, textContent: '',
      classList: { add() {} },
      set innerHTML(value) { this.children = []; this.html = value; },
      appendChild(node) { this.children.push(node); return node; },
      setAttribute(name, value) { this.attributes[name] = value; },
      addEventListener() {},
      querySelectorAll(selector) {
        const cls = selector.slice(1);
        return this.children.flatMap(child => [
          ...(child.className.split(' ').includes(cls) ? [child] : []),
          ...child.querySelectorAll(selector),
        ]);
      },
      querySelector(selector) { return this.querySelectorAll(selector)[0] || null; },
    };
  }
  const messages = element();
  const context = vm.createContext({
    window: { addEventListener() {}, _mdToHtml: text => text },
    document: { getElementById: () => messages, createElement: element },
    stripEmojis: text => text, applyResponsePrivacy() {}, scrollToLatest() {},
    contextProvenanceElement: () => null,
  });
  vm.runInContext(source + `
    globalThis.subject = { render: renderMessages, notice: appendInterruptionNotice };
  `, context);
  return { ...context.subject, messages };
}

for (const content of ['partial reply', '']) {
  test(`history renders interruption distinctly from reply text (${content || 'before first token'})`, () => {
    const h = harness();
    h.render([{ id: 'reply', role: 'assistant', content, meta: { interrupted: true } }]);
    const notices = h.messages.querySelectorAll('.aide-interruption');
    assert.equal(notices.length, 1);
    assert.equal(notices[0].textContent, 'response interrupted');
    assert.equal(notices[0].attributes.role, 'status');
    assert.equal(h.messages.querySelector('.ai-content').html, content);
    h.render([{ id: 'reply', role: 'assistant', content, meta: { interrupted: true } }]);
    assert.equal(h.messages.querySelectorAll('.aide-interruption').length, 1);
  });
}

test('completed history does not show an interruption marker', () => {
  const h = harness();
  h.render([{ id: 'reply', role: 'assistant', content: 'finished', meta: {} }]);
  assert.equal(h.messages.querySelectorAll('.aide-interruption').length, 0);
});

test('RAM-only user marker covers incognito stop before reply text', () => {
  const h = harness();
  h.render([{ id: 'prompt', role: 'user', content: 'private prompt', meta: { interrupted: true } }]);
  assert.equal(h.messages.querySelectorAll('.aide-interruption').length, 1);
});

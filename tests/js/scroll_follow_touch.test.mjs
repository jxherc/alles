// a touch screen sends no wheel: a swipe back to older messages must stop the chat from pinning
// itself to a growing reply, and nothing moves the view while a finger is down
import assert from 'node:assert/strict';
import test from 'node:test';

function element(extra = {}) {
  const listeners = {};
  return {
    listeners,
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    fire(type, event = {}) { for (const fn of listeners[type] || []) fn(event); },
    getClientRects: () => [1],
    querySelector: () => ({}),
    contains: () => false,
    ...extra,
  };
}

const chat = element({ scrollHeight: 2000, clientHeight: 600 });
// a browser clamps scrollTop to the end, like this
let top = 1400;
Object.defineProperty(chat, 'scrollTop', {
  get: () => top,
  set: value => { top = Math.max(0, Math.min(value, chat.scrollHeight - chat.clientHeight)); },
});
const messages = element();
const jump = element({ hidden: true });
const composer = element({ value: '' });
const byId = { chat, messages, 'jump-latest': jump, 'composer-ta': composer };
let resized = null;
globalThis.document = {
  getElementById: id => byId[id] || null,
  addEventListener() {},
  getSelection: () => ({ isCollapsed: true }),
  activeElement: null,
};
globalThis.ResizeObserver = class { constructor(fn) { resized = fn; } observe() {} };

const follow = await import('../../static/js/scrollfollow.js');
follow.initScrollFollow();

const grow = by => { chat.scrollHeight += by; resized(); };
const atBottom = () => chat.scrollHeight - chat.scrollTop - chat.clientHeight;

test('a growing reply keeps the view on the newest line when nobody touches it', () => {
  grow(100);
  assert.equal(atBottom(), 0);
});

test('a finger resting on the chat is never pulled by a growing reply', () => {
  chat.fire('touchstart', { touches: [{ clientY: 300 }] });
  const before = chat.scrollTop;
  grow(100);
  assert.equal(chat.scrollTop, before);
  assert.equal(follow.scrollToLatest(), false);
  assert.equal(chat.scrollTop, before);
  chat.fire('touchend');
});

test('dragging back toward older messages stops the follow, like a wheel up', () => {
  chat.scrollTop = chat.scrollHeight - chat.clientHeight;
  chat.fire('touchstart', { touches: [{ clientY: 300 }] });
  chat.fire('touchmove', { touches: [{ clientY: 340 }] });
  chat.fire('touchend');
  const before = chat.scrollTop;
  grow(300);
  assert.equal(chat.scrollTop, before);
  follow.resumeScrollFollow();
  assert.equal(atBottom(), 0);
});

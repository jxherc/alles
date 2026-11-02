// the follow is decided by where the view is: a swipe back to older messages stops it, nothing
// moves the view while a finger is down, and the app's own growth never stops it
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
// the owner moves the view: the browser changes scrollTop, then fires scroll
const scrollTo = value => { chat.scrollTop = value; chat.fire('scroll'); };

test('a growing reply keeps the view on the newest line when nobody touches it', () => {
  grow(100);
  assert.equal(atBottom(), 0);
});

test('a growth bigger than the gap, then a late scroll event and a render, still follows', () => {
  // a tool step or code block lands between two frames; the scroll event of the last pin comes
  // after it, then the stream asks to scroll down
  chat.scrollHeight += 536;
  chat.fire('scroll');
  assert.equal(follow.scrollToLatest(), true);
  assert.equal(atBottom(), 0);
  grow(300);
  assert.equal(atBottom(), 0);
});

test('a finger resting on the chat is never pulled by a growing reply, and catches up on lift', () => {
  chat.fire('touchstart', { touches: [{ clientY: 300 }] });
  const before = chat.scrollTop;
  grow(100);
  assert.equal(chat.scrollTop, before);
  assert.equal(follow.scrollToLatest(), false);
  assert.equal(chat.scrollTop, before);
  chat.fire('touchend');
  assert.equal(atBottom(), 0);
});

test('a swipe back toward older messages stops the follow, and the end picks it up again', () => {
  chat.fire('touchstart', { touches: [{ clientY: 300 }] });
  scrollTo(chat.scrollTop - 40);
  chat.fire('touchend');
  const before = chat.scrollTop;
  grow(300);
  assert.equal(chat.scrollTop, before);
  assert.equal(follow.scrollToLatest(), false);
  assert.equal(jump.hidden, false);
  // back to the end by hand
  scrollTo(chat.scrollHeight);
  grow(200);
  assert.equal(atBottom(), 0);
  assert.equal(jump.hidden, true);
});

test('typing a draft does not stop the follow', () => {
  composer.value = 'next question';
  document.activeElement = composer;
  grow(150);
  assert.equal(atBottom(), 0);
  assert.equal(follow.scrollToLatest(), true);
});

test('the jump button follows again after a wheel up', () => {
  chat.fire('wheel', { deltaY: -40 });
  grow(100);
  assert.notEqual(atBottom(), 0);
  follow.resumeScrollFollow();
  assert.equal(atBottom(), 0);
});

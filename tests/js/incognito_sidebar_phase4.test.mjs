import assert from 'node:assert/strict';
import test from 'node:test';

class ClassList {
  constructor(names = []) { this.names = new Set(names); }
  add(name) { this.names.add(name); }
  remove(name) { this.names.delete(name); }
  contains(name) { return this.names.has(name); }
  toggle(name, force) {
    if (force === true) this.names.add(name);
    else if (force === false) this.names.delete(name);
    else if (this.names.has(name)) this.names.delete(name);
    else this.names.add(name);
    return this.names.has(name);
  }
}

globalThis.localStorage = {
  getItem() { return null; },
  setItem() {},
};
globalThis.document = {
  body: { classList: new ClassList(['is-aide']) },
  getElementById() { return null; },
  querySelector() { return null; },
};

const { setIncognitoMode } = await import('../../static/js/modes.js');

test('leaving incognito restores an open sidebar', () => {
  document.body.classList = new ClassList(['is-aide']);
  setIncognitoMode(true);
  assert.equal(document.body.classList.contains('sidebar-hidden'), true);
  setIncognitoMode(false);
  assert.equal(document.body.classList.contains('sidebar-hidden'), false);
});

test('leaving incognito keeps a previously hidden mobile sidebar hidden', () => {
  document.body.classList = new ClassList(['is-aide', 'sidebar-hidden']);
  setIncognitoMode(true);
  setIncognitoMode(false);
  assert.equal(document.body.classList.contains('sidebar-hidden'), true);
});

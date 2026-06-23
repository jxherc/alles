// unit tests for the command/hotkey registry (static/js/commands.js).
// run: node --test tests/js/
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { createRegistry, parseHotkey } from '../../static/js/commands.js';

function seed() {
  const r = createRegistry();
  r.register({ id: 'new-note', title: 'New Note', keywords: ['create', 'jot'], group: 'notes', hotkey: 'mod+n', run: () => 'made' });
  r.register({ id: 'open-pal', title: 'Open Palette', keywords: ['command'], group: 'nav', hotkey: 'mod+k', run: () => 'pal' });
  r.register({ id: 'save', title: 'Save File', keywords: ['write', 'note'], group: 'notes', hotkey: 'mod+shift+s', run: () => 'saved' });
  return r;
}

test('register + all', () => {
  const r = seed();
  assert.equal(r.all().length, 3);
});

test('register overwrites by id', () => {
  const r = seed();
  r.register({ id: 'save', title: 'Save As', run: () => 'x' });
  assert.equal(r.all().length, 3);
  assert.equal(r.all().find((c) => c.id === 'save').title, 'Save As');
});

test('search by title', () => {
  const r = seed();
  const hits = r.search('palette');
  assert.equal(hits[0].id, 'open-pal');
});

test('search by keyword', () => {
  const r = seed();
  const hits = r.search('jot');
  assert.ok(hits.some((c) => c.id === 'new-note'));
});

test('search ranks title-prefix first', () => {
  const r = seed();
  const hits = r.search('save'); // "Save File" title prefix beats "note" keyword on save
  assert.equal(hits[0].id, 'save');
});

test('empty search returns all', () => {
  const r = seed();
  assert.equal(r.search('').length, 3);
});

test('byGroup filter', () => {
  const r = seed();
  assert.equal(r.byGroup('notes').length, 2);
});

test('parseHotkey normalizes', () => {
  assert.deepEqual(parseHotkey('Mod+K'), { mod: true, shift: false, alt: false, key: 'k' });
  assert.deepEqual(parseHotkey('mod+shift+s'), { mod: true, shift: true, alt: false, key: 's' });
});

test('matchHotkey: mod = ctrl or meta', () => {
  const r = seed();
  assert.equal(r.matchHotkey({ key: 'k', ctrlKey: true })?.id, 'open-pal');
  assert.equal(r.matchHotkey({ key: 'k', metaKey: true })?.id, 'open-pal');
});

test('matchHotkey: shift combo', () => {
  const r = seed();
  assert.equal(r.matchHotkey({ key: 'S', metaKey: true, shiftKey: true })?.id, 'save');
});

test('matchHotkey: no match', () => {
  const r = seed();
  assert.equal(r.matchHotkey({ key: 'z', ctrlKey: true }), null);
  assert.equal(r.matchHotkey({ key: 'k' }), null); // no modifier
});

test('run invokes command', () => {
  const r = seed();
  assert.equal(r.run('new-note'), 'made');
});

test('run unknown returns undefined-safe', () => {
  const r = seed();
  assert.equal(r.run('nope'), undefined);
  assert.equal(r.has('nope'), false);
});

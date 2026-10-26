import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { t, tp } from '../../static/js/i18n.js';

const source = readFileSync(new URL('../../static/js/contacts.js', import.meta.url), 'utf8')
  .replace(/^import .*;\n/gm, '').replace(/^export /gm, '');
const tick = () => new Promise(resolve => setImmediate(resolve));
const people = [{ id: 'ada', name: 'Ada' }, { id: 'grace', name: 'Grace' }];

// the list and detail render into one container; elements are plain stand-ins, keyed by id
function harness() {
  const nodes = new Map(), document = { activeElement: null };
  const node = (id = '') => ({
    id, value: '', dataset: {}, disabled: false, hidden: false, listeners: {},
    addEventListener(type, fn) { this.listeners[type] = fn; },
    click() { return this.listeners.click?.({ currentTarget: this, target: this }); },
    focus() { document.activeElement = this; }, setAttribute() {}, querySelector: () => null, contains(other) { return other === this; },
    querySelectorAll(selector) { return selector === '[data-open]' ? this.opens || [] : []; },
    set innerHTML(html) {
      this.html = html;
      if (document.activeElement && document.activeElement !== this) document.activeElement = document.body;
      for (const [, key] of html.matchAll(/\bid="([^"]+)"/g)) nodes.set(key, node(key));
      this.opens = [...html.matchAll(/data-open="([^"]+)"/g)].map(([, key]) => Object.assign(node(), { dataset: { open: key } }));
    },
    get innerHTML() { return this.html || ''; },
  });
  document.body = node('body');
  document.getElementById = id => nodes.get(id) || null;
  nodes.set('contacts-list', node('contacts-list'));
  let position = 3;
  const pushes = [], backs = [];
  const list = () => nodes.get('contacts-list');
  list().querySelector = selector => list().opens?.find(button => selector === `[data-open="${button.dataset.open}"]`) || null;
  const response = data => ({ ok: true, json: async () => data });
  const context = vm.createContext({ t, tp,
    document, window: {}, CSS: { escape: String }, URLSearchParams, Promise, toast() {},
    location: { pathname: '/', search: '?view=contacts', hash: '' },
    pushRouteUrl: url => { pushes.push(url); position++; },
    routeHistoryPosition: () => position,
    history: { back: () => { backs.push(position); position--; } },
    initCustomDropdown() {}, getDropdownValue: () => '', populateDropdown() {}, formatDate: String, formatTime: String,
    fetch: async url => response(url.includes('/related') ? { related: [] } : url.includes('/events') ? { events: [] }
      : /\/api\/contacts\/\w+$/.test(url) ? { ...people[0], fields: [] } : people),
  });
  vm.runInContext(source + '\nglobalThis.subject = { load: loadContacts, open: openContact };', context);
  return { ...context.subject, nodes, document, pushes, backs, list, position: () => position, moveTo: value => { position = value; } };
}

test('an open contact gets one history entry; Back redraws the list onto its row', async () => {
  const h = harness();
  await h.load();
  await h.open('ada');
  await h.open('ada');   // set-as-me and photo redraws stay on the same entry
  assert.deepEqual(h.pushes, ['/?view=contacts']);
  assert.match(h.list().innerHTML, /contact-detail/);
  h.document.activeElement = h.document.body;
  h.nodes.get('cd-back').click();
  assert.deepEqual(h.backs, [4]);
  await h.load('');   // what the shell's popstate does
  assert.equal(h.document.activeElement?.dataset.open, 'ada');
  await h.open('grace');
  assert.equal(h.pushes.length, 2, 'a fresh entry once the old one was left');
});

test('the in-app back off the contact\'s entry redraws the list without going back', async () => {
  const h = harness();
  await h.open('ada');
  h.moveTo(h.position() + 1);   // something pushed over the contact's entry
  h.nodes.get('cd-back').click(); await tick();
  assert.deepEqual(h.backs, []);
  assert.match(h.list().innerHTML, /data-open="ada"/);
});

test('an opened contact puts focus on back, not <body>', async () => {
  const h = harness();
  await h.load();
  h.document.activeElement = h.list().opens[0];
  await h.open('ada');
  assert.equal(h.document.activeElement?.id, 'cd-back');
});

test('contact icons are svg with names', () => {
  assert.doesNotMatch(source, />\+ group</);
  assert.match(source, /data-del="\$\{f\.id\}" aria-label="\$\{_esc\(t\('contacts\.remove_field', \{ kind: f\.kind \}\)\)\}">\$\{_si\('close'\)\}/);
  assert.match(source, /aria-label="\$\{_esc\(t\('contacts\.remove_link', \{ name: r\.name \}\)\)\}">\$\{_si\('close'\)\}/);
});

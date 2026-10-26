import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { t, tp, installCatalog, configureLocalization } from '../../static/js/i18n.js';
import { resolveCompatibilityRoute } from '../../static/js/routecompat.js';

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
const html = read('../../static/index.html');
const app = read('../../static/js/app.js');

function harness() {
  let document;
  class Element {
    constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.attributes = {}; this.dataset = {}; this.listeners = {}; this.inert = false; this.hidden = false; this.value = ''; this.textContent = ''; }
    setAttribute(key, value) {
      this.attributes[key] = String(value);
      if (key === 'id') this.id = value;
      if (key.startsWith('data-')) this.dataset[key.slice(5).replace(/-([a-z])/g, (_, char) => char.toUpperCase())] = String(value);
    }
    getAttribute(key) { return this.attributes[key]; }
    removeAttribute(key) { delete this.attributes[key]; }
    append(...nodes) { for (const node of nodes) { node.parentElement = this; this.children.push(node); } }
    appendChild(node) { this.append(node); return node; }
    replaceChildren(...nodes) { for (const child of this.children) child.parentElement = null; this.children = []; this.append(...nodes); }
    remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(child => child !== this); this.parentElement = null; }
    get isConnected() { return this === document.body || !!this.parentElement?.isConnected; }
    matches(selector) {
      if (selector.startsWith('#')) return this.id === selector.slice(1);
      const attribute = selector.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);
      if (attribute) return attribute[2] === undefined ? attribute[1] in this.attributes : this.attributes[attribute[1]] === attribute[2];
      return this.tagName === selector.toUpperCase();
    }
    querySelectorAll(selector) { return this.children.flatMap(child => [...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]); }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    addEventListener(name, callback) { this.listeners[name] = [...(this.listeners[name] || []), callback]; }
    focus() { document.activeElement = this; }
    async dispatch(name, values = {}) { for (const callback of this.listeners[name] || []) await callback({ target: this, preventDefault() {}, stopPropagation() {}, ...values }); }
  }
  document = { body: new Element('body'), activeElement: null, createElement: tag => new Element(tag) };
  document.getElementById = id => document.body.querySelector(`#${id}`);
  const source = new Element('button'); source.id = 'source';
  const background = new Element('main'); background.append(source); document.body.append(background);
  const alreadyInert = new Element('aside'); alreadyInert.inert = true; document.body.append(alreadyInert);
  source.focus();
  const calls = []; const boundaries = [];
  const window = { _navigateTo: async view => { calls.push(view); return true; }, _openSettings: pane => calls.push(`settings:${pane}`) };
  const context = vm.createContext({ document, window, t,
    createFocusBoundary(dialog, options) {
      let source;
      const boundary = { activate(args) { source = args.source; args.focus.focus(); },
        deactivate() { if (source?.isConnected) source.focus(); }, destroy() {}, escape: () => options.onEscape() };
      boundaries.push(boundary); return boundary;
    },
  });
  const content = read('../../static/js/help_content.js').replace(/^import .*;\n/gm, '').replace(/^export /gm, '');
  const sourceText = read('../../static/js/help.js').replace(/^import .*;\n/gm, '').replace(/^export /gm, '');
  vm.runInContext(`${content}\n${sourceText}\nglobalThis.subject = { helpTopics, findManualTopics, manualTopicForApp, openManual, closeManual };`, context);
  return { ...context.subject, get HELP_TOPICS() { return context.subject.helpTopics(); }, document, source, background, alreadyInert, window, calls, boundaries,
    get: id => document.getElementById(id), all: selector => document.body.querySelectorAll(selector), text: node => [node.textContent, ...node.children.map(child => String(child.textContent))].join(' ') };
}

test('shared help is a drawer utility and Finance has a contextual guide', () => {
  assert.match(html, /id="app-drawer-help"[^>]*>help &amp; manual<\/button>/);
  assert.match(html, /id="finance-help"[^>]*title="how to use Finance"/);
  assert.match(app, /closeAppDrawer\(\);\s*openManual\(/);
  assert.doesNotMatch(app.match(/const SHELL_GROUPS = [\s\S]*?\n\]\);/)[0], /view: 'help'/);
});

test('main Call has visible text without replacing the existing trigger', () => {
  const button = html.match(/<button[^>]+id="aide-call-open"[\s\S]*?<\/button>/)[0];
  assert.match(button, /<span class="aide-call-label"[^>]*>call<\/span>/);
  assert.match(button, /aria-controls="aide-call-workspace"/);
});

test('every manual app action resolves through an existing route', () => {
  const h = harness();
  for (const topic of h.HELP_TOPICS) for (const action of topic.actions || []) {
    if (action.view) assert.ok(resolveCompatibilityRoute({ view: action.view }), action.view);
    if (action.pane) assert.match(html, new RegExp(`data-pane="${action.pane}"`));
  }
  assert.equal(new Set(h.HELP_TOPICS.map(topic => topic.id)).size, h.HELP_TOPICS.length);
});

test('search finds article content, handles case and empty/no-match queries', () => {
  const h = harness();
  assert.deepEqual(Array.from(h.findManualTopics('  SIMPLEFIN  '), topic => topic.id), ['finance']);
  assert.equal(h.findManualTopics('').length, h.HELP_TOPICS.length);
  assert.equal(h.findManualTopics('no-topic-here-943765').length, 0);
  assert.equal(h.manualTopicForApp({ space: 'aide', app: 'alles' }), 'aide');
  assert.equal(h.manualTopicForApp({ app: 'money' }), 'finance');
  assert.equal(h.manualTopicForApp({ app: 'unknown' }), 'start');
});

test('manual copy retains Finance safety distinctions and has no workstation/audit paths', () => {
  const h = harness(); const finance = JSON.stringify(h.HELP_TOPICS.find(topic => topic.id === 'finance'));
  for (const expected of [/positive amount/, /negative for spending/, /recent owner confirmation/, /bank password/, /does not copy back/, /isolated review preview/, /normal installation/]) assert.match(finance, expected);
  assert.doesNotMatch(JSON.stringify(h.HELP_TOPICS), /\/Users\/|scratch\/|2026-10-16|test harness|verified live/i);
});

test('opening uses local text only, traps focus and restores prior inert state', () => {
  const h = harness(); h.openManual({ topic: 'finance' });
  assert.equal(h.calls.length, 0);
  assert.equal(h.background.inert, true);
  assert.equal(h.get('alles-help-dialog').getAttribute('role'), 'dialog');
  assert.equal(h.document.activeElement, h.all('[data-manual-close]')[0]);
  h.boundaries[0].escape();
  assert.equal(h.get('alles-help-dialog'), null);
  assert.equal(h.background.inert, false);
  assert.equal(h.alreadyInert.inert, true);
  assert.equal(h.document.activeElement, h.source);
});

test('body-level help owns its KOKUEN tokens outside Aide and Files', () => {
  const h = harness(); h.openManual({ topic: 'finance' });
  assert.equal(h.get('alles-help-dialog').getAttribute('data-kokuen-surface'), 'manual');
});

test('repeated open keeps one dialog and a single source to restore', () => {
  const h = harness(); h.openManual(); h.openManual({ topic: 'finance' });
  assert.equal(h.all('#alles-help-dialog').length, 1);
  assert.equal(h.boundaries.length, 1);
  h.closeManual(); h.closeManual();
  assert.equal(h.document.activeElement, h.source);
});

test('search no-match recovers without losing the labelled article', async () => {
  const h = harness(); h.openManual({ topic: 'finance' });
  const search = h.get('alles-help-search'); search.value = 'no-topic-here-943765'; await search.dispatch('input');
  assert.match(h.get('alles-help-status').textContent, /no topics/);
  search.value = 'draft'; await search.dispatch('input');
  assert.equal(h.get('alles-help-status').textContent, '');
  assert.ok(h.get('alles-help-article').querySelector('h3'));
});

test('app actions close before guarded navigation and respect refusal', async () => {
  const h = harness(); h.openManual({ topic: 'finance' });
  h.window._navigateTo = async view => {
    assert.equal(h.get('alles-help-dialog'), null); assert.equal(h.background.inert, false);
    h.calls.push(view); return false;
  };
  await h.all('[data-manual-view="money"]')[0].dispatch('click');
  assert.deepEqual(h.calls, ['money']);
  assert.equal(h.document.activeElement, h.source);
});

test('navigation failure restores the same topic and search with a retry message', async () => {
  const h = harness(); h.openManual({ topic: 'finance', query: 'bank' });
  h.window._navigateTo = async () => { throw new Error('synthetic unavailable'); };
  await h.all('[data-manual-view="money"]')[0].dispatch('click');
  assert.equal(h.get('alles-help-search').value, 'bank');
  assert.match(h.get('alles-help-status').textContent, /could not open/);
  assert.equal(h.all('[data-manual-topic="finance"]')[0].getAttribute('aria-current'), 'true');
});

test('stale navigation failure cannot replace a newly opened manual', async () => {
  const h = harness(); h.openManual({ topic: 'finance' });
  let reject; h.window._navigateTo = () => new Promise((_, no) => { reject = no; });
  const button = h.all('[data-manual-view="money"]')[0];
  const first = button.dispatch('click'); const duplicate = button.dispatch('click');
  h.openManual({ topic: 'docs' }); reject(new Error('late refusal')); await Promise.all([first, duplicate]);
  assert.equal(h.all('[data-manual-topic="docs"]')[0].getAttribute('aria-current'), 'true');
  assert.equal(h.get('alles-help-status').textContent, '');
});

test('Settings actions use existing pane dispatch after restoring the underlying app', async () => {
  const h = harness(); h.openManual({ topic: 'settings' });
  await h.all('[data-manual-pane="developer"]')[0].dispatch('click');
  assert.deepEqual(h.calls, ['settings:developer']);
  assert.equal(h.get('alles-help-dialog'), null);
});

test('every manual string comes from the catalog and follows the interface language', () => {
  const h = harness();
  const raw = JSON.stringify(h.HELP_TOPICS).match(/"help\.[a-z0-9_.]+"/g);
  assert.equal(raw, null);
  installCatalog({ schema_version: 1, language: 'fr', messages: { 'help.start.title': 'pour commencer', 'help.finance.s2.title': 'ajouter un compte' }, plurals: {} });
  try {
    configureLocalization({ language: 'fr' });
    assert.equal(h.helpTopics()[0].title, 'pour commencer');
    assert.equal(h.helpTopics().find(topic => topic.id === 'finance').sections[1].title, 'ajouter un compte');
    h.openManual({ topic: 'start' });
    assert.equal(h.all('[data-manual-topic="start"]')[0].textContent, 'pour commencer');
  } finally { configureLocalization({ language: 'en' }); }
  assert.equal(h.helpTopics()[0].title, 'getting started');
});

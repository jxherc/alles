import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { lum, mix, mutedFor, generateHarmony } from '../../static/js/color.js';

const themeSource = readFileSync(new URL('../../static/js/theme.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^export \{.*\};\r?\n/gm, '').replace(/^export /gm, '');
const indexSource = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
const decode = value => value.replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');

// Exercise the real editor rendering and handlers. Native Tab/Enter/Space and
// hit geometry are additionally covered by the isolated browser regression.
function harness() {
  const storage = new Map();
  const classes = { add() {}, remove() {}, toggle() {} };
  const document = {
    body: { tagName: 'BODY', classList: classes },
    documentElement: { style: { setProperty() {} }, dataset: {}, classList: classes },
    querySelector: () => null,
    querySelectorAll: () => [],
  };
  document.activeElement = document.body;
  class Element {
    constructor(tag, attributes = '') {
      this.tagName = tag.toUpperCase();
      this.attributes = Object.fromEntries([...attributes.matchAll(/([\w-]+)="([^"]*)"/g)].map(([, key, value]) => [key, decode(value)]));
      this.dataset = Object.fromEntries(Object.entries(this.attributes).filter(([key]) => key.startsWith('data-')).map(([key, value]) => [key.slice(5), value]));
      this.type = this.attributes.type || '';
      this.value = this.attributes.value || '';
      this.classList = classes;
      this.style = {};
    }
    getAttribute(name) { return this.attributes[name] ?? null; }
    addEventListener() {}
    focus() { document.activeElement = this; }
  }
  const root = {
    classList: classes,
    elements: [],
    set innerHTML(value) {
      if (this.elements.includes(document.activeElement)) document.activeElement = document.body;
      this.elements = [...value.matchAll(/<([a-z][a-z0-9-]*)\b([^>]*)>/gi)]
        .map(([, tag, attributes]) => new Element(tag, attributes));
    },
    querySelector(selector) {
      return selector.startsWith('#') ? this.elements.find(el => el.attributes.id === selector.slice(1)) || null : null;
    },
    querySelectorAll(selector) {
      if (selector === '[data-apply]') return this.elements.filter(el => el.dataset.apply !== undefined);
      if (selector === '[data-del]') return this.elements.filter(el => el.dataset.del !== undefined);
      return [];
    },
  };
  let commits = 0;
  let onChange = () => {};
  const context = vm.createContext({
    localStorage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    document, window: {}, setTimeout: () => 1, clearTimeout() {},
    _lum: lum, _mix: mix, _mutedFor: mutedFor, generateHarmony,
    initColorPickers() {}, wireChoiceGroup() {}, toast() {},
  });
  vm.runInContext(themeSource + '\napplyBgPattern = () => {}; globalThis.subject = { renderThemeEditorInto, PRESETS };', context);
  const name = 'evening "&" <quiet>';
  const base = context.subject.PRESETS.dark.colors;
  const selected = { colors: { ...base, accent: '#ff9900' }, font: 'mono', density: 'compact', bgPattern: 'none' };
  storage.set('alles-appearance', JSON.stringify({ preset: 'dark', colors: base, customThemes: { [name]: selected, other: { colors: base } } }));
  context.subject.renderThemeEditorInto(root, { onChange() { commits++; onChange(); } });
  return {
    document, root, name, selected,
    apply: () => root.querySelectorAll('[data-apply]').find(el => el.dataset.apply === name),
    remove: () => root.querySelectorAll('[data-del]').find(el => el.dataset.del === name),
    stored: () => JSON.parse(storage.get('alles-appearance')),
    commits: () => commits,
    setOnChange: callback => { onChange = callback; },
    outside: new Element('button'),
  };
}

test('revealed token has native keyboard activation and a copy action name', () => {
  const [, tag, attributes] = indexSource.match(/<([a-z]+)\b([^>]*\bid="token-reveal"[^>]*)>/);
  assert.equal(tag, 'button');
  assert.match(attributes, /\btype="button"/);
  assert.match(attributes, /\baria-label="copy token"/);
  assert.doesNotMatch(attributes, /\btabindex="-1"/);
  assert.match(attributes, /user-select:all/);
  assert.match(attributes, /text-transform:none/);
});

test('saved theme apply is a native named button, separate from delete', () => {
  const h = harness();
  assert.equal(h.apply().tagName, 'BUTTON');
  assert.equal(h.apply().type, 'button');
  assert.equal(h.apply().getAttribute('aria-label'), `apply theme ${h.name}`);
  assert.equal(h.apply().dataset.del, undefined);
  assert.notEqual(h.apply(), h.remove());
});

test('applying an exact saved theme commits once and returns focus after rerender', () => {
  const h = harness();
  const previous = h.apply();
  previous.focus();
  previous.onclick();
  assert.equal(h.commits(), 1);
  assert.equal(h.stored().preset, h.name);
  assert.deepEqual(h.stored().colors, h.selected.colors);
  assert.equal(h.stored().font, 'mono');
  assert.equal(h.stored().density, 'compact');
  assert.deepEqual(Object.keys(h.stored().customThemes), [h.name, 'other']);
  assert.notEqual(h.apply(), previous);
  assert.equal(h.document.activeElement, h.apply());
});

test('theme activation does not steal a newer focus destination', () => {
  const h = harness();
  h.apply().focus();
  h.setOnChange(() => h.outside.focus());
  h.apply().onclick();
  assert.equal(h.document.activeElement, h.outside);
  assert.equal(h.stored().preset, h.name);
});

test('saved theme delete remains separate from apply', () => {
  const h = harness();
  h.remove().onclick();
  assert.equal(h.commits(), 0);
  assert.equal(h.stored().preset, 'dark');
  assert.deepEqual(Object.keys(h.stored().customThemes), ['other']);
});

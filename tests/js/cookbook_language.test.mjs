// the cookbook builds its controls once; a live language switch must relabel them and keep the picks
import { test } from 'node:test';
import assert from 'node:assert/strict';

const elements = new Map();
function element(id) {
  if (!elements.has(id)) {
    const attrs = {};
    elements.set(id, {
      id, dataset: {}, value: '', textContent: '', placeholder: '', innerHTML: '',
      setAttribute: (name, value) => { attrs[name] = String(value); },
      getAttribute: name => attrs[name] ?? null,
      hasAttribute: name => name in attrs,
      addEventListener() {},
    });
  }
  return elements.get(id);
}
const listeners = {};
globalThis.document = { getElementById: element, documentElement: {} };
globalThis.window = {
  addEventListener: (name, fn) => { (listeners[name] ||= []).push(fn); },
  dispatchEvent: event => { for (const fn of listeners[event.type] || []) fn(event); },
};
globalThis.fetch = async url => ({
  ok: true,
  json: async () => (String(url).includes('/system') ? { has_gpu: false, backend: 'cpu' } : { models: [] }),
});

const { configureLocalization, installCatalog } = await import('../../static/js/i18n.js');
installCatalog({
  schema_version: 1,
  language: 'fr',
  messages: {
    'cookbook.use_general': 'général',
    'cookbook.use_coding': 'code',
    'cookbook.sort_score': 'score',
    'cookbook.search_placeholder': 'chercher des modèles',
    'cookbook.fits_only': 'compatibles seulement',
    'common.refresh': 'actualiser',
  },
  plurals: {},
});
configureLocalization({ language: 'en' });
const { initCookbook } = await import('../../static/js/cookbook.js');

test('a language switch relabels the cookbook controls and keeps what was picked', async () => {
  element('cookbook-body');
  initCookbook();
  const usecase = element('cb-usecase');
  assert.match(usecase.dataset.options, /coding\|coding/);
  usecase.value = 'coding';

  configureLocalization({ language: 'fr' });

  assert.match(usecase.dataset.options, /general\|général/);
  assert.match(usecase.dataset.options, /coding\|code/);
  assert.equal(usecase.dataset.value, 'coding');
  assert.equal(element('cb-search').placeholder, 'chercher des modèles');
  assert.equal(element('cb-fitonly').textContent, 'compatibles seulement');
  assert.equal(element('cb-refresh').textContent, 'actualiser');
  configureLocalization({ language: 'en' });
  await new Promise(resolve => setTimeout(resolve, 0));
});

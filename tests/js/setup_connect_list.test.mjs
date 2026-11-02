import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { t as i18nT } from '../../static/js/i18n.js';

const source = readFileSync(new URL('../../static/js/setupwizard.js', import.meta.url), 'utf8')
  .replace(/import\s+[\s\S]*?from\s+['"][^'"]+['"];\r?\n/g, '')
  .replace(/^export /gm, '');

function load(responses) {
  const context = vm.createContext({
    t: (key, vars) => i18nT(key, vars), document: {}, HTMLElement: class {},
    fetch: async path => (path in responses
      ? { ok: true, json: async () => responses[path] }
      : { ok: false, json: async () => ({}) }),
  });
  vm.runInContext(`${source}\nglobalThis.list = _CONNECT; globalThis.states = _connectStates;`, context);
  return context;
}

const locales = ['en', 'fr', 'es', 'zh-Hans', 'zh-Hant', 'ja', 'ko', 'ar'];

test('every connect row names where it goes, and has its own words in all 8 languages', () => {
  const { list } = load({});
  assert.equal([...list].map(item => item.id).join(), 'mail,phone,obsidian,bank,services');
  for (const item of list) {
    assert.ok(item.view || item.pane || item.lan, `${item.id} has no destination`);
    for (const language of locales) {
      const catalog = JSON.parse(readFileSync(new URL(`../../static/locales/${language}.json`, import.meta.url), 'utf8')).messages;
      for (const key of [`setup.connect_${item.id}`, `setup.connect_${item.id}_note`]) {
        assert.ok(catalog[key], `${language} is missing ${key}`);
      }
    }
  }
});

test('the obsidian row shows its mode once the docs are shared, and nothing while off', async () => {
  for (const [mode, shown] of [['off', ''], ['read', 'read only'], ['write', 'read and save']]) {
    const { states } = load({ '/api/setup/obsidian-lan': { mode } });
    assert.equal((await states()).obsidian, shown);
  }
  const { states } = load({});
  assert.equal((await states()).obsidian, '', 'a failed read leaves the row as not set up');
});

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

globalThis.window = new EventTarget();
const { configuredFallbackChain, sanitizeSearchSettings } = await import('../../static/js/settings/andromeda.js');

const read = path => readFileSync(new URL(`../../${path}`, import.meta.url), 'utf8');
const html = read('static/index.html');
const section = read('static/js/settings/andromeda.js');
const paneHtml = html.slice(html.indexOf('id="s-pane-andromeda"'), html.indexOf('<!-- ── appearance pane ── -->'));
const searchHtml = html.slice(html.indexOf('id="s-pane-search"'), html.indexOf('id="s-pane-andromeda"'));

test('plaintext provider credentials are removed from the section\'s copy of the settings', () => {
  assert.deepEqual(
    sanitizeSearchSettings({
      tavily_api_key: 'redacted',
      brave_api_key: 'redacted',
      google_pse_api_key: 'redacted',
      serper_api_key: 'redacted',
      tavily_api_key_configured: true,
      search_result_count: 10,
    }),
    { tavily_api_key_configured: true, search_result_count: 10 },
  );
  assert.match(section, /\.\.\.sanitizeSearchSettings\(patch\), \.\.\.sanitizeSearchSettings\(saved\)/);
});

test('saving the one visible fallback removes hidden providers from the chain', () => {
  assert.deepEqual(configuredFallbackChain('duckduckgo', 'brave'), ['brave']);
  assert.deepEqual(configuredFallbackChain('tavily', 'brave'), ['brave']);
  assert.deepEqual(configuredFallbackChain('duckduckgo', 'none'), []);
  assert.deepEqual(configuredFallbackChain('brave', 'brave'), []);
});

test('unrelated search settings keep the loaded fallback-chain tail', () => {
  const save = section.slice(section.indexOf('async function saveSources'), section.indexOf('async function saveCredential'));
  assert.match(save, /picked === primary \? 'none' : picked/);
  assert.match(save, /if \(changed\) patch\.search_fallback_chain = configuredFallbackChain\(primary, fallback\)/);
  assert.doesNotMatch(save, /search_fallback_chain: /);
});

test('every andromeda control lives once, in the andromeda section', () => {
  for (const id of [
    's-andromeda-primary', 's-andromeda-fallback', 's-andromeda-count', 's-andromeda-answer-model',
    's-andromeda-results', 's-andromeda-overview', 's-andromeda-verification', 's-andromeda-confirm-remote',
    's-andromeda-verifier-mode', 's-andromeda-band', 's-andromeda-model-light', 's-andromeda-model-auto',
    's-andromeda-searxng-status', 's-andromeda-searxng-actions', 's-hidden-sites-list',
  ]) {
    assert.equal(paneHtml.split(`id="${id}"`).length - 1, 1, `${id} in the andromeda section`);
    assert.equal(html.split(`id="${id}"`).length - 1, 1, `${id} once in the page`);
    assert.doesNotMatch(searchHtml, new RegExp(`id="${id}"`));
  }
  // the search section keeps what is not andromeda's: custom engines
  for (const id of ['s-search-provider', 's-search-fallback', 's-search-count', 's-engine-key', 's-gpse-key']) {
    assert.doesNotMatch(html, new RegExp(`id="${id}"`), id);
  }
  assert.match(searchHtml, /id="s-custom-search-form"/);
  assert.match(html, /data-pane="andromeda"/);
  assert.doesNotMatch(html, /andromeda-settings-panel|andromeda-search-settings-status/);
});

test('answer controls use accessible switches, kokuen dropdowns and no native choice controls', () => {
  assert.doesNotMatch(paneHtml, /<select|type="checkbox"|type="radio"/);
  for (const id of ['results', 'overview', 'confirm-remote', 'verification']) {
    assert.match(paneHtml, new RegExp(`id="s-andromeda-${id}" type="button" role="switch" aria-checked="(?:true|false)" aria-labelledby="s-andromeda-${id}-label"`));
  }
  for (const id of ['primary', 'fallback', 'count', 'answer-model', 'verifier-mode', 'band']) {
    assert.match(paneHtml, new RegExp(`class="settings-input custom-select" id="s-andromeda-${id}"[^>]+aria-labelledby=`));
  }
});

test('overview strength explains both speed and answer quality', () => {
  assert.match(paneHtml, /light[^<]*fastest[^<]*least checking/i);
  assert.match(paneHtml, /standard[^<]*balanced/i);
  assert.match(paneHtml, /strong[^<]*slower[^<]*more checking/i);
  assert.match(paneHtml, /automatic[^<]*query[^<]*available model/i);
});

test('stored search credentials have an explicit accessible clear action', () => {
  assert.equal((paneHtml.match(/data-andromeda-clear-setting=/g) || []).length, 7);
  assert.equal((paneHtml.match(/aria-label="clear [^"]+"/g) || []).length, 7);
  assert.match(section, /_clearPending\.has\(input\.id\)/);
  assert.match(section, /addEventListener\('pointerdown'/);
});

test('credential inputs are locked while a save or clear is pending', () => {
  const save = section.slice(section.indexOf('async function saveCredential'), section.indexOf('async function clearCredential'));
  const clear = section.slice(section.indexOf('async function clearCredential'), section.indexOf('function wireCredentialInput'));
  assert.match(save, /input\.disabled = true;[\s\S]*finally \{\s*input\.disabled = false;/);
  assert.match(clear, /input\.disabled = true;[\s\S]*finally \{[\s\S]*input\.disabled = false;/);
});

test('every write goes through the ordered settings queue and tells the page', () => {
  const write = section.slice(section.indexOf('async function write('), section.indexOf('// ── search sources'));
  assert.match(write, /await _patchSettings\(patch\)/);
  assert.match(write, /if \(!saved\) return null/);
  assert.match(write, /new CustomEvent\(ANDROMEDA_SETTINGS_EVENT, \{ detail: _settings \}\)/);
  assert.doesNotMatch(section, /fetch\('\/api\/settings', \{\s*method: 'PATCH'/);
  for (const key of ['andromeda_normal_results', 'andromeda_overview', 'andromeda_verification_enabled']) {
    assert.match(section, new RegExp(key));
  }
  assert.match(section, /_bindSwitch\(\$\(id\), \(\) => _settings\[key\] !== false, next => write\(\{ \[key\]: next \}\)\)/);
  assert.match(section, /_bindSwitch\(\$\('s-andromeda-confirm-remote'\), \(\) => _settings\.andromeda_confirm_remote === true/);
  assert.match(section, /saveDropdown\('s-andromeda-band', 'andromeda_model_band', 'standard'\)/);
});

test('engine choices refresh after credentials and managed SearXNG lifecycle changes', () => {
  const save = section.slice(section.indexOf('async function saveCredential'), section.indexOf('async function clearCredential'));
  const clear = section.slice(section.indexOf('async function clearCredential'), section.indexOf('function wireCredentialInput'));
  const managed = section.slice(section.indexOf('async function manageSearxng'), section.indexOf('// ── answer'));
  assert.match(save, /await refreshEngines\(\)/);
  assert.match(clear, /await refreshEngines\(\)/);
  assert.match(managed, /finally \{[\s\S]*await loadSearxng\(\)[\s\S]*await refreshEngines\(\)/);
  assert.match(managed, /await refreshEngines\(\)[\s\S]*status\.textContent = message/);
  assert.match(managed, /state = 'error'/);
  assert.match(section, /fetch\(url, options\)/);
  assert.match(section, /json\('\/api\/system\/searxng'\)/);
  assert.match(section, /`\/api\/system\/searxng\/\$\{action\}`/);
});

test('settings opens the andromeda section from the page and from the sidebar nav', () => {
  const settings = read('static/js/settings.js');
  assert.match(settings, /andromeda: andromedaPane,/);
  assert.match(settings, /import \{ andromedaPane \} from '\.\/settings\/andromeda\.js'/);
  assert.match(html, /<button class="s-nav-item" type="button" data-pane="andromeda" data-i18n="common\.andromeda">/);
});

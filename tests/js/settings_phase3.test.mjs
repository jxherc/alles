import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { matchesSettingsShortcut } from '../../static/js/shortcuts.js';

const keyEvent = (overrides = {}) => ({
  key: ',', ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, ...overrides,
});

test('settings always opens with ctrl or cmd comma', () => {
  assert.equal(matchesSettingsShortcut(keyEvent({ ctrlKey: true }), 'Alt+S'), true);
  assert.equal(matchesSettingsShortcut(keyEvent({ metaKey: true }), 'Alt+S'), true);
  assert.equal(matchesSettingsShortcut(keyEvent({ ctrlKey: true, shiftKey: true }), 'Alt+S'), false);
  assert.equal(matchesSettingsShortcut(keyEvent({ key: 's', altKey: true }), 'Alt+S'), true);
});

test('settings is one accessible home reached from the universal shell', () => {
  const html = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
  for (const label of [
    'general &amp; appearance',
    'aide &amp; chat behavior',
    'models &amp; providers',
    'memory &amp; instructions',
    'connections &amp; mcp',
    'privacy &amp; security',
    'notifications &amp; language',
    'server, backups &amp; data',
  ]) assert.equal(html.includes(label), true, `missing settings group: ${label}`);
  assert.doesNotMatch(html, /id="space-profile-btn"/);
  assert.match(html, /id="app-drawer-settings"[^>]*type="button"/);
  const modal = html.match(/<[^>]+id="settings-modal"[^>]*>/)?.[0] || '';
  assert.match(modal, /role="dialog"/);
  assert.match(modal, /aria-modal="true"/);
  assert.doesNotMatch(html, /data-chat-behavior=/);
  assert.match(html, /aide uses the right tools automatically and can still answer normal questions/);
  assert.match(html, /id="settings-owner-instructions"/);
  assert.match(html, /id="s-ep-refresh-all"/);
});

test('Home customization lives in Settings and uses universal custom controls', () => {
  const html = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
  const source = readFileSync(new URL('../../static/js/settings.js', import.meta.url), 'utf8');
  const kokuen = readFileSync(new URL('../../static/kokuen.css', import.meta.url), 'utf8');
  const pane = html.match(/<div class="s-pane home-settings-pane" id="s-pane-home">[\s\S]*?<\/div>\s*<!-- end Home settings -->/)?.[0] || '';
  assert.match(html, /data-pane="home">home<\/button>/);
  assert.match(pane, /id="home-settings-sections"/);
  assert.match(pane, /id="home-settings-shortcuts"/);
  assert.match(pane, /<strong>pinned apps<\/strong>/);
  assert.match(pane, /id="home-settings-shortcuts-title">pinned apps<\/h3>/);
  assert.doesNotMatch(pane, /<strong>shortcuts<\/strong>/);
  assert.deepEqual(
    [...pane.matchAll(/data-home-shortcut="([^"]+)"/g)].map(match => match[1]),
    ['plan', 'inbox', 'wiki', 'files', 'library', 'health', 'finance', 'vault', 'system'],
  );
  assert.doesNotMatch(pane, /data-home-shortcut="(?:calendar|tasks|mail|money|photos|watch|activity)"/);
  assert.match(pane, /role="radiogroup"/);
  assert.doesNotMatch(pane, /<select|type="(?:checkbox|radio)"/);
  assert.match(source, /fetch\('\/api\/today\/preferences'/);
  assert.match(source, /method: 'PUT'/);
  assert.match(source, /alles:home-preferences-changed/);
  assert.match(source, /if \(_homeSettingsChanges > 0\)/);
  assert.match(source, /function _mergeHomeShortcutOrder\([\s\S]*?enabledShortcuts,[\s\S]*?original =/);
  assert.match(source, /shortcutOrder: \[\.\.\.normalized\.shortcuts\]/);
  assert.match(source, /shortcuts: _mergeHomeShortcutOrder\(/);
  assert.match(source, /workbench\.inert = busy/);
  assert.match(source, /if \(!visible\.includes\('needs_you'\)\) visible\.unshift\('needs_you'\)/);
  assert.match(source, /row\.querySelector\('\[data-home-move\]:not\(:disabled\)'\)/);
  assert.match(source, /_settingsReturnFocusId = document\.activeElement\.id/);
  assert.match(source, /document\.getElementById\(_settingsReturnFocusId\)/);
  assert.match(kokuen, /\.home-settings-switch::before[\s\S]*border-radius: 999px/);
  assert.match(kokuen, /\.home-settings-switch::after[\s\S]*border-radius: 50%/);
});

test('approved Phase 10 language and Credits workbenches use honest custom controls', () => {
  const html = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
  const source = readFileSync(new URL('../../static/js/settings.js', import.meta.url), 'utf8');
  const kokuen = readFileSync(new URL('../../static/kokuen.css', import.meta.url), 'utf8');
  const localePane = html.match(/<!-- ── approved Phase 10 language and region workbench ── -->[\s\S]*?<!-- ── approved Phase 10 manifest-driven Credits workbench ── -->/)?.[0] || '';
  const creditsPane = html.match(/<!-- ── approved Phase 10 manifest-driven Credits workbench ── -->[\s\S]*?<!-- ── backup pane ── -->/)?.[0] || '';

  assert.match(html, /data-pane="credits">about &amp; credits<\/button>/);
  assert.equal((localePane.match(/data-locale-language=/g) || []).length, 8);
  assert.equal((localePane.match(/data-locale-language=/g) || []).length, 8);
  assert.match(source, /row\.setAttribute\('aria-disabled', String\(!language\.available\)\)/);
  assert.match(source, /focusTarget\.focus\(\{ preventScroll: true \}\)/);
  assert.match(localePane, /data-locale-language="en"/);
  assert.match(localePane, /id="s-region-trigger"[^>]*aria-haspopup="listbox"[^>]*data-value=""/);
  assert.match(localePane, /id="s-timezone-trigger"[^>]*aria-haspopup="listbox"[^>]*data-value=""/);
  assert.match(localePane, /id="s-currency-trigger"[^>]*aria-haspopup="listbox"[^>]*data-value=""/);
  assert.doesNotMatch(localePane, /<select|type="(?:checkbox|radio)"|<input[^>]+id="s-(?:region|timezone|currency)"/);
  assert.match(localePane, /data-locale-format="clock_format"/);
  assert.match(localePane, /data-locale-format="week_start"/);

  assert.match(creditsPane, /role="tablist"/);
  assert.match(creditsPane, /<label class="sr-only" for="credits-search" data-i18n="credits\.search">search credits<\/label>/);
  assert.match(creditsPane, /id="credits-list"/);
  assert.match(creditsPane, /id="credits-detail"/);
  assert.doesNotMatch(creditsPane, /<select|type="(?:checkbox|radio)"/);

  assert.match(source, /fetch\('\/api\/settings\/localization\/options'\)/);
  assert.match(source, /fetch\('\/api\/credits'\)/);
  assert.match(source, /fetch\(`\/api\/credits\/\$\{encodeURIComponent\(entry\.id\)\}`\)/);
  assert.match(source, /const _creditDetails = new Map\(\)/);
  assert.match(source, /t\('credits\.detail_loading'\)/);
  assert.match(source, /clock_format: _localeRadioValue\('clock_format'\)/);
  assert.match(source, /week_start: _localeRadioValue\('week_start'\)/);
  assert.match(source, /currency: document\.getElementById\('s-currency-trigger'\)/);
  assert.match(source, /if \(event\.key === 'Escape'\)[\s\S]{0,180}_closeLocaleChoice\(true\)/);
  assert.match(source, /t\('locale\.language_unavailable'/);
  assert.match(source, /tp\('credits\.gap_remaining', gapCount\)/);
  assert.match(localePane, /id="locale-preview-path"[^>]*>alles\/data · 14:30<\/code>/);
  assert.doesNotMatch(`${localePane}\n${source}`, /\/Users\/jxh\/alles/);
  assert.match(kokuen, /\.locale-settings-workbench[\s\S]{0,180}grid-template-columns/);
  assert.match(kokuen, /@media \(max-width: 860px\)[\s\S]*\.locale-settings-preview[\s\S]*order: -1/);
});

test('Discord settings preserve drafts, reject stale loads, and roll back failed quiet-hours changes', () => {
  const source = readFileSync(new URL('../../static/js/settings.js', import.meta.url), 'utf8');
  assert.match(source, /const _discordDrafts = \{ channels: false, quiet: false \}/);
  assert.match(source, /if \(!_discordDrafts\.channels\) channels\.value/);
  assert.match(source, /if \(!_discordDrafts\.quiet\) \{/);
  assert.match(source, /_discordDraftRevisions\.channels/);
  assert.match(source, /_discordDraftRevisions\.quiet/);
  assert.match(source, /const generation = \+\+_discordGeneration/);
  assert.match(source, /if \(generation !== _discordGeneration\) return/);
  assert.match(source, /const switchControl = event\.currentTarget/);
  assert.match(source, /_setSwitch\(switchControl, true\)/);
  assert.match(source, /let _discordMutationQueue = Promise\.resolve\(\)/);
  assert.match(source, /_discordMutationQueue\.then\(mutate, mutate\)/);
  assert.match(source, /_discordMutationQueue = pending\.catch/);
  assert.doesNotMatch(source, /if \(_discordBusy\) throw new Error\('another Discord change is still saving'\)/);
});

test('settings refreshes role state and provider catalogs without hiding failures', () => {
  const source = readFileSync(new URL('../../static/js/settings.js', import.meta.url), 'utf8');
  const models = readFileSync(new URL('../../static/js/models.js', import.meta.url), 'utf8');
  assert.match(source, /Promise\.allSettled\(endpoints\.map/);
  assert.match(source, /await window\._refreshAideModelDefault\?\.\(\)/);
  assert.match(source, /replace the unavailable model before saving/);
  assert.match(source, /finally \{[\s\S]*?await loadEpList\(\); await loadModels\(\)/);
  assert.match(source, /window\._fetchWithRecentOwner = _fetchWithRecentOwner/);
  assert.match(models, /_ownerFetch\('\/api\/models\/endpoint'/);
  assert.match(models, /_ownerFetch\(`\/api\/models\/endpoint\/\$\{btn\.dataset\.id\}`/);
});

test('memory off disables write and extraction controls', () => {
  const source = readFileSync(new URL('../../static/js/memory.js', import.meta.url), 'utf8');
  assert.match(source, /const off = _memoryPolicy === 'off'/);
  assert.match(source, /'mem-extract-btn', 'mem-add-input', 'mem-cat-cycle-btn', 'mem-add-btn'/);
  assert.match(source, /inject\.setAttribute\('aria-disabled', String\(off\)\)/);
});

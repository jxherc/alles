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

test('settings is one accessible home with the eight phase three groups', () => {
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
  assert.match(html, /id="space-profile-btn"[^>]*aria-haspopup="menu"/);
  assert.match(html, /id="space-settings-btn"[^>]*role="menuitem"/);
  assert.match(html, /id="settings-modal" role="dialog" aria-modal="true"/);
  assert.match(html, /data-chat-behavior="automatic_tools"/);
  assert.match(html, /data-chat-behavior="answer_only"/);
  assert.match(html, /id="settings-owner-instructions"/);
  assert.match(html, /id="s-ep-refresh-all"/);
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

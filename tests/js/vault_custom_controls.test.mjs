import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const vault = readFileSync(new URL('../../static/js/vault.js', import.meta.url), 'utf8');
const settings = readFileSync(new URL('../../static/js/settings.js', import.meta.url), 'utf8');

test('vault entry type reads the KOKUEN dropdown state', () => {
  assert.match(vault, /import \{ getDropdownValue, populateDropdown \}/);
  assert.match(vault, /getDropdownValue\(_modalEl\.querySelector\('#vf-type'\)\)/);
  assert.match(vault, /getDropdownValue\(ov\.querySelector\('#vf-type'\)\)/);
  assert.doesNotMatch(vault, /querySelector\('#vf-type'\)\.value/);
});

test('Andromeda exact model bands read the KOKUEN dropdown state', () => {
  const source = settings.slice(
    settings.indexOf('async function saveAndromedaModelBands'),
    settings.indexOf('function renderShortcutList'),
  );
  assert.match(source, /getDropdownValue\(select\)/);
  assert.doesNotMatch(source, /select\?\.value|select\.value/);
});

test('recent-owner retries are limited to bodyless browser-access requests', () => {
  const helper = vault.match(/async function _vfetchRecentOwner\(url, opts = \{}\)[\s\S]*?\n}/)[0];
  assert.match(helper, /hasOwnProperty\.call\(opts, 'body'\)/);
  assert.match(helper, /throw new TypeError\('recent-owner retry only supports bodyless requests'\)/);
});

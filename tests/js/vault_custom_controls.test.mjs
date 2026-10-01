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

test('Vault dialogs use the shared focus boundary and return to their invoking control', () => {
  assert.match(vault, /import \{ createFocusBoundary \} from '\.\/kokuen\.js\?v=1'/);
  assert.match(vault, /function _activateManagedModal/);
  assert.match(vault, /function _activateTemporaryModal/);
  assert.match(vault, /_modalFocusBoundary\?\.deactivate\(\)/);
  assert.match(vault, /_modalFocusBoundary\?\.destroy\(\)/);
  assert.doesNotMatch(vault, /document\.addEventListener\('keydown', _escClose\)/);
});

test('Vault rows use separate semantic keyboard actions and retain persistent load recovery', () => {
  assert.match(vault, /<button type="button" class="vault-entry-main" data-vault-open=/);
  assert.match(vault, /data-vault-copy=/);
  assert.match(vault, /data-vault-delete=/);
  assert.doesNotMatch(vault, /class="vault-entry"[^>]+onclick=/);
  assert.match(vault, /className = 'vault-load-error'/);
  assert.match(vault, /Your unlocked session is unchanged/);
  assert.doesNotMatch(vault, /load failed — vault may be locked[\s\S]{0,100}_unlocked = false/);
});

test('card verification values and private keys are masked until explicitly revealed', () => {
  assert.match(vault, /cvv:\s+\{[^\n]+kind: 'secret'/);
  assert.match(vault, /private_key:\s+\{[^\n]+kind: 'secretarea'/);
  assert.match(vault, /def\.kind === 'secretarea'/);
  assert.match(vault, /classList\.toggle\('is-revealed', show\)/);
});

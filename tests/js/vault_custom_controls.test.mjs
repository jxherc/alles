import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const vault = readFileSync(new URL('../../static/js/vault.js', import.meta.url), 'utf8');
const settings = readFileSync(new URL('../../static/js/settings.js', import.meta.url), 'utf8');
const app = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');

function lockScreen({ state = 'setup', biometric = 'failed', supported = true, setupOk = true } = {}) {
  const elements = new Map(), requests = [];
  const get = id => {
    if (!elements.has(id)) elements.set(id, { style: {}, hidden: false, disabled: false, textContent: '', value: '' });
    return elements.get(id);
  };
  const request = async url => {
    requests.push(url);
    if (url === '/api/vault/setup') return { ok: setupOk, json: async () => ({ state }) };
    assert.equal(url, '/api/vault/webauthn/challenge?vault_id=default');
    if (biometric === 'offline') throw new Error('synthetic local disconnection');
    const payload = { credentials: [] };
    if (biometric === 'enrolled') payload.credentials.push('example');
    return { ok: biometric !== 'failed', json: async () => payload };
  };
  const context = vm.createContext({
    window: supported ? { PublicKeyCredential: class {} } : {},
    document: { getElementById: get }, fetch: request,
  });
  vm.runInContext(vault.replace(/^import .*;\n/gm, '').replace(/^export /gm, ''), context);
  return { get, requests, load: () => context.loadVaultView(request) };
}

for (const biometric of ['failed', 'offline']) {
  test(`unavailable biometric check names the capability while password setup remains usable: ${biometric}`, async () => {
    const h = lockScreen({ biometric }); const details = await h.load();
    assert.equal(details.partialMessage, 'biometric unlock could not be checked');
    assert.equal(details.retryLabel, 'retry vault checks');
    assert.equal(h.get('vault-unlock-btn').textContent, 'create vault');
    assert.equal(h.get('vault-unlock-btn').disabled, false);
    assert.equal(h.get('vault-bio-unlock-btn').style.display, 'none');
  });
}

test('biometric failure preserves password unlock and does not make a recovery vault usable', async () => {
  const locked = lockScreen({ state: 'locked' }); await locked.load();
  assert.equal(locked.get('vault-unlock-btn').textContent, 'unlock');
  assert.equal(locked.get('vault-unlock-btn').disabled, false);
  const recovery = lockScreen({ state: 'recovery' }); const details = await recovery.load();
  assert.equal(recovery.get('vault-unlock-btn').disabled, true);
  assert.match(recovery.get('vault-lock-help').textContent, /restore a valid backup/);
  assert.doesNotMatch(details.partialMessage, /password.*available|can.*unlock/);
});

test('failed password setup keeps its own retry without narrowing the failure to biometrics', async () => {
  const h = lockScreen({ setupOk: false });
  assert.equal(await h.load(), undefined);
  assert.equal(h.get('vault-unlock-btn').disabled, true);
  assert.equal(h.get('vault-setup-retry').hidden, false);
  assert.match(h.get('vault-unlock-error').textContent, /could not check vault setup/);
});

test('available or unsupported biometric checks do not report a partial failure', async () => {
  const empty = lockScreen({ biometric: 'empty' }); assert.equal(await empty.load(), undefined);
  assert.equal(empty.get('vault-bio-unlock-btn').style.display, 'none');
  const enrolled = lockScreen({ biometric: 'enrolled' }); assert.equal(await enrolled.load(), undefined);
  assert.equal(enrolled.get('vault-bio-unlock-btn').style.display, '');
  const unsupported = lockScreen({ supported: false }); assert.equal(await unsupported.load(), undefined);
  assert.deepEqual(unsupported.requests, ['/api/vault/setup']);
});

test('specialist partial status uses the module detail and retry label without changing other states', () => {
  const node = () => ({
    dataset: {}, children: [], setAttribute() {},
    replaceChildren(...children) { this.children = children; },
    append(child) { this.children.push(child); },
    addEventListener(_event, handler) { this.activate = handler; },
  });
  const root = node(); root.dataset.specialistApp = 'vault';
  root.querySelector = () => root.children[0]; root.prepend = child => root.children.unshift(child);
  const context = vm.createContext({ document: { createElement: node } });
  vm.runInContext(app.match(/function _paintSpecialistState\([^]*?\n}/)[0], context);
  let retries = 0;
  const details = { partialMessage: 'biometric unlock could not be checked', retryLabel: 'retry vault checks' };
  context._paintSpecialistState(root, 'partial', () => ++retries, details);
  assert.equal(root.children[0].children[0].textContent, details.partialMessage);
  assert.equal(root.children[0].children[1].textContent, details.retryLabel);
  root.children[0].children[1].activate(); assert.equal(retries, 1);
  context._paintSpecialistState(root, 'error', () => {}, details);
  assert.equal(root.children[0].children[0].textContent, 'couldn’t load vault');
  context._paintSpecialistState(root, 'partial', () => {});
  assert.equal(root.children[0].children[0].textContent, 'some vault data is unavailable');
  context._paintSpecialistState(root, 'ready', () => {}, details);
  assert.equal(root.children[0].hidden, true); assert.equal(root.children[0].children.length, 0);
});

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

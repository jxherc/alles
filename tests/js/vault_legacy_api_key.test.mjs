import assert from 'node:assert/strict';
import test from 'node:test';

globalThis.window = {};

const { _vaultInternals } = await import('../../static/js/vault.js');

test('legacy API-key entries retain their type, value, and migration field', () => {
  const entry = {
    type: 'api_key',
    fields: { api_key: 'legacy-key', endpoint: 'https://provider.example' },
  };

  assert.equal(_vaultInternals._typeForEntry(entry), 'apikey');
  assert.equal(_vaultInternals._primarySecret(entry), 'legacy-key');
  assert.deepEqual(_vaultInternals._entryFields(entry), {
    apikey: 'legacy-key',
    endpoint: 'https://provider.example',
  });
});

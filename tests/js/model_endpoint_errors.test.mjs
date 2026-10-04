import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/models.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');

for (const stage of ['create', 'manual catalog']) {
  for (const [label, response, message] of [
    ['specific problem', { ok: false, json: async () => ({ detail: 'the connection name is required' }) }, 'the connection name is required'],
    ['structured validation', { ok: false, json: async () => ({ detail: [{ message: 'internal fixture' }] }) }, null],
    ['non-json response', { ok: false, json: async () => { throw new SyntaxError('synthetic response'); } }, null],
  ]) {
    test(`${stage}: ${label} gives a readable error and stops before probing`, async () => {
      const requests = [];
      const context = vm.createContext({
        window: {}, localStorage: { getItem: () => null },
        fetch: async (url, options) => {
          requests.push({ url, options });
          if (stage === 'manual catalog' && requests.length === 1) {
            return { ok: true, json: async () => ({ id: 'owned' }) };
          }
          return response;
        },
      });
      vm.runInContext(source + '\nglobalThis.add = addEndpoint;', context);
      const expected = message || (stage === 'create'
        ? 'connection could not be added; check the address and try again'
        : 'model list could not be saved; try again');
      await assert.rejects(context.add('owned', 'http://127.0.0.1', '', 'manual', ['owned-model']),
        error => error.message === expected);
      assert.equal(requests.length, stage === 'create' ? 1 : 2);
      assert.equal(requests.some(request => request.url.endsWith('/probe')), false);
    });
  }
}

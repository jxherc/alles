import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { webcrypto } from 'node:crypto';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/request_id.js', import.meta.url), 'utf8')
  .replace(/^export /gm, '');

for (const native of [true, false]) {
  test(`request identity is a canonical fresh UUID ${native ? 'with' : 'without'} randomUUID`, () => {
    const crypto = { getRandomValues: webcrypto.getRandomValues.bind(webcrypto) };
    if (native) crypto.randomUUID = webcrypto.randomUUID.bind(webcrypto);
    const context = vm.createContext({ crypto, Uint8Array });
    vm.runInContext(source + '\nglobalThis.make = requestId;', context);
    const first = context.make(), second = context.make();
    const pattern = /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/;
    assert.match(first, pattern);
    assert.match(second, pattern);
    assert.notEqual(first, second);
  });
}

import { requestId } from '../../static/js/request_id.js';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { webcrypto } from 'node:crypto';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/note_capture.js', import.meta.url), 'utf8')
  .replace(/^import .*;\n/gm, '').replace(/^export /gm, '');

function harness() {
  const values = new Map();
  const writes = [];
  let fail = false;
  const context = vm.createContext({
    crypto: webcrypto, requestId, Uint8Array,
    sessionStorage: { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) },
    fetch: async (url, options) => {
      if (url.endsWith('create-scope')) return { ok: true, json: async () => ({ scopes: ['a'.repeat(64)], vault_scopes: ['b'.repeat(64)] }) };
      const body = JSON.parse(options.body); writes.push(body);
      if (fail) throw new Error('synthetic lost response');
      return { ok: true, json: async () => ({ created: true, request_id: body.request_id, path: body.path }) };
    },
  });
  vm.runInContext(source + '\nglobalThis.save = saveNote;', context);
  return { save: context.save, values, writes, fail: value => { fail = value; } };
}

test('ordinary capture keeps its existing normalization; document import preserves exact content', async () => {
  const h = harness();
  const text = '    indented code\r\n\r\nnext  \r\n\r\n';
  await h.save(text, 'normal.md');
  assert.equal(h.writes[0].content, text.trim() + '\n');
  await h.save(text, 'import.md', { preserveContent: true });
  assert.equal(h.writes[1].content, text);
  assert.equal(h.writes[1].expected_vault, 'b'.repeat(64));
});

test('an uncertain import reuses the identical payload and request identity', async () => {
  const h = harness(); h.fail(true);
  const text = '    original\n\n';
  await assert.rejects(h.save(text, 'import.md', { preserveContent: true }), /lost response/);
  h.fail(false);
  await h.save(text, 'import.md', { preserveContent: true });
  assert.deepEqual(h.writes[0], h.writes[1]);
  assert.equal(h.writes[1].content, text);
  assert.equal(h.values.size, 0);
});

test('pending normalization and destination must match before a new save can reuse a receipt', async () => {
  for (const change of ['normalization', 'destination']) {
    const h = harness(); h.fail(true);
    const text = '    original\n\n';
    await assert.rejects(h.save(text, 'original.md'), /lost response/);
    h.fail(false);
    await assert.rejects(h.save(text, change === 'destination' ? 'other.md' : 'original.md', { preserveContent: change === 'normalization' }), /pending note/);
    assert.equal(h.writes.length, 1);
    assert.equal(h.values.size, 1);
  }
});

test('empty import cannot fall through to automatic heading creation', async () => {
  const h = harness();
  for (const text of ['', ' \r\n\t']) await assert.rejects(h.save(text, 'empty.md', { preserveContent: true }), /empty/);
  assert.equal(h.writes.length, 0);
});

test('an older pending note without a verified vault is retained without a new write', async () => {
  const h = harness();
  const raw = JSON.stringify({ text: 'original', body: { path: 'note.md', content: 'original\n', unique: true, request_id: webcrypto.randomUUID() } });
  const key = 'alles.note.pending.v1:' + 'a'.repeat(64);
  h.values.set(key, raw);
  await assert.rejects(h.save('original', 'note.md'), /no verified vault/);
  assert.equal(h.writes.length, 0);
  assert.equal(h.values.get(key), raw);
});

test('reply identity survives an uncertain save without entering the server payload', async () => {
  const h = harness(); h.fail(true);
  const sourceKey = 'aide:session-a:reply-a';
  await assert.rejects(h.save('answer', 'answer.md', { sourceKey }), /lost response/);
  const pending = JSON.parse([...h.values.values()][0]);
  assert.equal(pending.sourceKey, sourceKey);
  assert.equal(h.writes[0].sourceKey, undefined);
  h.fail(false);
  await assert.rejects(h.save('answer', 'answer.md', { sourceKey: 'aide:session-a:reply-b' }), /pending note/);
  assert.equal(h.writes.length, 1);
  await h.save('answer', 'answer.md', { sourceKey });
  assert.deepEqual(h.writes[0], h.writes[1]);
});

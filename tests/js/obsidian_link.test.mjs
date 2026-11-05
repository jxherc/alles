import assert from 'node:assert/strict';
import test from 'node:test';
import { remotelySaveLink } from '../../static/js/obsidian_link.js';
import { qrMatrix, qrSvg } from '../../static/js/qr.js';

// what Remotely Save's importQrCodeUri / protocol handler does with the link (src/importExport.ts, src/main.ts)
function importLike(link, currentVault) {
  assert.ok(link.startsWith('obsidian://remotely-save?func=settings&'));
  const params = Object.fromEntries(new URL(link).searchParams);
  assert.equal(params.func, 'settings');
  assert.equal(params.vault, currentVault);
  return JSON.parse(params.data);
}

test('the link carries every webdav field the plugin reads', () => {
  const link = remotelySaveLink({
    address: 'https://alles.example.ts.net/dav', token: 'alles_abc-DEF_123', vault: 'My Docs & Notes',
  });
  const settings = importLike(link, 'My Docs & Notes');
  assert.equal(settings.serviceType, 'webdav');
  assert.deepEqual(settings.webdav, {
    address: 'https://alles.example.ts.net/dav', username: 'obsidian', password: 'alles_abc-DEF_123',
    authType: 'basic', depth: 'manual_1', remoteBaseDir: 'docs',
  });
});

test('a different vault name is refused by the plugin, so the link must name it exactly', () => {
  const link = remotelySaveLink({ address: 'http://a/dav', token: 't', vault: 'ipad vault' });
  assert.throws(() => importLike(link, 'other'));
});

const bit = (rows, x, y) => (rows[y][x] ? 1 : 0);

test('qr matrix has the right size, finder patterns and timing lines', () => {
  for (const [text, version] of [['hi', 1], ['x'.repeat(154), 9], ['y'.repeat(600), 19]]) {
    const rows = qrMatrix(text, { level: 'M' });
    const size = version * 4 + 17;
    assert.equal(rows.length, size, `size for ${text.length} bytes`);
    for (const [ox, oy] of [[0, 0], [size - 7, 0], [0, size - 7]]) {
      for (let d = 0; d < 7; d++) {
        for (const [x, y] of [[ox + d, oy], [ox + d, oy + 6], [ox, oy + d], [ox + 6, oy + d]]) assert.equal(bit(rows, x, y), 1);
      }
      assert.equal(bit(rows, ox + 3, oy + 3), 1);
      assert.equal(bit(rows, ox + 1, oy + 1), 0);
    }
    for (let i = 8; i < size - 8; i++) {
      assert.equal(bit(rows, i, 6), i % 2 === 0 ? 1 : 0);
      assert.equal(bit(rows, 6, i), i % 2 === 0 ? 1 : 0);
    }
    assert.equal(bit(rows, 8, size - 8), 1, 'dark module');
  }
});

test('qr format bits are a valid bch code for the level and mask', () => {
  for (const [level, levelBits] of [['L', 1], ['M', 0]]) {
    const rows = qrMatrix('alles', { level });
    let all = 0;
    for (let i = 0; i <= 5; i++) all |= bit(rows, 8, i) << i;
    all |= bit(rows, 8, 7) << 6; all |= bit(rows, 8, 8) << 7; all |= bit(rows, 7, 8) << 8;
    for (let i = 9; i < 15; i++) all |= bit(rows, 14 - i, 8) << i;
    const data = (all ^ 0x5412) >>> 10;
    assert.equal(data >>> 3, levelBits);
    let rem = data;
    for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
    assert.equal(((data << 10) | rem) ^ 0x5412, all);
  }
});

test('a real settings link fits a qr code and renders as an svg', () => {
  const link = remotelySaveLink({
    address: 'https://alles-machine.tail1234.ts.net/dav', token: `alles_${'a'.repeat(43)}`, vault: 'docs',
  });
  const svg = qrSvg(link, { label: 'code' });
  assert.match(svg, /^<svg [^>]*viewBox="0 0 \d+ \d+"[^>]*aria-label="code"/);
  assert.ok(qrMatrix(link).length <= 97, 'version 20 or smaller');
  assert.throws(() => qrMatrix('z'.repeat(5000)));
});

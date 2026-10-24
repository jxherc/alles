import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

globalThis.location = { hostname: 'localhost', port: '8000', protocol: 'http:' };
const { parseSseFrames } = await import('../../static/js/andromeda.js');
const read = name => readFileSync(new URL(`../../static/js/${name}.js`, import.meta.url), 'utf8');

// the server sends ": \n\n" once a stream goes quiet, so WebKit hands over the events it held
// back; every reader has to pass over it as nothing
test('a quiet-stream comment is skipped by every stream reader', () => {
  const { frames, rest } = parseSseFrames('data: {"a":1}\n\n: \n\ndata: {"b":2}\n\n: \n\n');
  assert.deepEqual(frames, ['{"a":1}', '{"b":2}']);
  assert.equal(rest, '');
  assert.match(read('chat'), /for \(const line of lines\) \{\s*if \(!line\.startsWith\('data:'\)\) continue;/);
  assert.match(read('ask_panel'), /if \(!line\.startsWith\('data:'\)\) continue;/);
  assert.match(read('compare'), /if \(!value\.startsWith\('data:'\)\) return;/);
});

test('the approval card names a step outside the folder in its own wrapping line', () => {
  const chat = read('chat');
  assert.match(chat, /\$\{t\.outside\s*\? `<span class="agent-perm-outside">\$\{escHtml\(t\.outside\)\}<\/span>`\s*: ''\}<\/div>/);
  assert.doesNotMatch(chat, /agent-perm-outside" style=/);
  const css = readFileSync(new URL('../../static/style.css', import.meta.url), 'utf8');
  assert.match(css, /\.agent-perm-outside \{[^}]*overflow-wrap: anywhere;/);
});

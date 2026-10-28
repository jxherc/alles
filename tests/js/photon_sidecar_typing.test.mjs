import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

// a stand-in spectrum-ts: one inbound text, and every typing call written to a log file
const FAKE = `
import { appendFileSync } from 'node:fs';
const log = (line) => appendFileSync(process.env.TYPING_LOG, line + '\\n');
const space = {
  id: 'chat-1',
  send: async () => ({ id: 'sent-1' }),
  startTyping: async () => log('start'),
  stopTyping: async () => log('stop'),
};
export async function Spectrum() {
  return {
    messages: (async function* () {
      yield [space, { direction: 'inbound', id: 'm1', content: { type: 'text', text: 'hi' }, sender: { id: '+15550100199' } }];
      await new Promise(() => {});
    })(),
  };
}
`;

test('imessage typing starts, is refreshed while aide works, and stops', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'photon-sidecar-'));
  const pkg = join(dir, 'node_modules', 'spectrum-ts');
  mkdirSync(join(pkg, 'providers'), { recursive: true });
  writeFileSync(join(pkg, 'package.json'), JSON.stringify({ name: 'spectrum-ts', type: 'module', exports: { '.': './index.js', './providers/imessage': './providers/imessage.js' } }));
  writeFileSync(join(pkg, 'index.js'), FAKE);
  writeFileSync(join(pkg, 'providers', 'imessage.js'), 'export const imessage = { config: () => ({}) };');
  // the refresh is 25s in production; the copy runs it every 50ms
  const source = readFileSync(new URL('../../services/photon/sidecar.mjs', import.meta.url), 'utf8');
  assert.match(source, /setInterval\(\(\) => space\.startTyping\(\)\.catch\(\(\) => \{\}\), 25000\)/);
  writeFileSync(join(dir, 'sidecar.mjs'), source.replace('25000)', '50)'));
  const log = join(dir, 'typing.log');
  writeFileSync(log, '');
  const child = spawn(process.execPath, [join(dir, 'sidecar.mjs')], { env: { ...process.env, TYPING_LOG: log }, stdio: ['pipe', 'pipe', 'inherit'] });
  let out = '';
  child.stdout.on('data', chunk => { out += chunk; });
  const until = async (check) => { for (let i = 0; i < 100 && !check(); i++) await new Promise(r => setTimeout(r, 20)); };
  await until(() => out.includes('"type":"message"'));
  child.stdin.write(JSON.stringify({ type: 'typing', space: 'chat-1', on: true }) + '\n');
  await new Promise(r => setTimeout(r, 180));
  child.stdin.write(JSON.stringify({ type: 'typing', space: 'chat-1', on: false }) + '\n');
  await new Promise(r => setTimeout(r, 120));
  child.kill();
  const calls = readFileSync(log, 'utf8').trim().split('\n');
  assert.equal(calls[0], 'start');
  assert.ok(calls.filter(c => c === 'start').length >= 3, calls.join(','));
  assert.equal(calls.at(-1), 'stop');
  const after = calls.length;
  await new Promise(r => setTimeout(r, 120));
  assert.equal(readFileSync(log, 'utf8').trim().split('\n').length, after);
});

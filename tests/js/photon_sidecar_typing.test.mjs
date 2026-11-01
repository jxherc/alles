import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

// a stand-in spectrum-ts: one inbound text, and every typing and read call written to a log with
// the time it happened, the way the real sdk would see it (typing is the content builder sent with
// space.send, read is message.read(); hermes's sidecar uses both, see services/photon/sidecar.mjs)
const FAKE = `
import { appendFileSync } from 'node:fs';
const log = (entry) => appendFileSync(process.env.CALL_LOG, JSON.stringify({ ...entry, t: Date.now() }) + '\\n');
export const typing = (state = 'start') => ({ type: 'typing', state });
const space = {
  id: 'chat-1',
  send: async (content) => { log({ call: 'send', type: content.type, state: content.state }); return { id: 'sent-1' }; },
  startTyping: async () => log({ call: 'startTyping' }),
  stopTyping: async () => log({ call: 'stopTyping' }),
};
const message = {
  direction: 'inbound', id: 'm1', content: { type: 'text', text: 'hi' }, sender: { id: '+15550100199' },
  read: async () => log({ call: 'read', id: 'm1' }),
};
export async function Spectrum() {
  return { messages: (async function* () { yield [space, message]; await new Promise(() => {}); })() };
}
`;

function start() {
  const dir = mkdtempSync(join(tmpdir(), 'photon-sidecar-'));
  const pkg = join(dir, 'node_modules', 'spectrum-ts');
  mkdirSync(join(pkg, 'providers'), { recursive: true });
  writeFileSync(join(pkg, 'package.json'), JSON.stringify({ name: 'spectrum-ts', type: 'module', exports: { '.': './index.js', './providers/imessage': './providers/imessage.js' } }));
  writeFileSync(join(pkg, 'index.js'), FAKE);
  writeFileSync(join(pkg, 'providers', 'imessage.js'), 'export const imessage = { config: () => ({}) };');
  copyFileSync(new URL('../../services/photon/sidecar.mjs', import.meta.url), join(dir, 'sidecar.mjs'));
  const log = join(dir, 'calls.log');
  writeFileSync(log, '');
  const child = spawn(process.execPath, [join(dir, 'sidecar.mjs')], { env: { ...process.env, CALL_LOG: log }, stdio: ['pipe', 'pipe', 'inherit'] });
  let out = '';
  child.stdout.on('data', chunk => { out += chunk; });
  const send = command => child.stdin.write(JSON.stringify(command) + '\n');
  const calls = () => readFileSync(log, 'utf8').trim().split('\n').filter(Boolean).map(line => JSON.parse(line));
  const until = async check => { for (let i = 0; i < 150 && !check(); i++) await new Promise(r => setTimeout(r, 20)); };
  const ready = until(() => out.includes('"type":"message"'));
  return { child, send, calls, ready, wait: ms => new Promise(r => setTimeout(r, ms)), out: () => out, until };
}

test('imessage typing is the typing builder, sent once per command, with no timer in the sidecar', async () => {
  const s = start();
  await s.ready;
  s.send({ type: 'typing', space: 'chat-1', on: true });
  await s.until(() => s.calls().length >= 1);
  await s.wait(300); // the old sidecar refreshed itself on a timer; this one only sends what alles asks for
  assert.deepEqual(s.calls().map(c => [c.call, c.type, c.state]), [['send', 'typing', 'start']]);
  s.send({ type: 'typing', space: 'chat-1', on: true });
  s.send({ type: 'typing', space: 'chat-1', on: false });
  await s.until(() => s.calls().length >= 3);
  s.child.kill();
  assert.deepEqual(s.calls().map(c => c.state), ['start', 'start', 'stop']);
  assert.ok(!s.calls().some(c => c.call === 'startTyping' || c.call === 'stopTyping'));
});

test('a read command marks that message read, and an unknown message is ignored quietly', async () => {
  const s = start();
  await s.ready;
  s.send({ type: 'read', space: 'chat-1', id: 'm1' });
  s.send({ type: 'read', space: 'chat-1', id: 'nope' });
  await s.until(() => s.calls().length >= 1);
  await s.wait(100);
  s.child.kill();
  assert.deepEqual(s.calls().map(c => [c.call, c.id]), [['read', 'm1']]);
  assert.ok(!s.out().includes('"type":"error"'));
});

test('the sidecar source has no refresh timer and no 25 second refresh', () => {
  const source = readFileSync(new URL('../../services/photon/sidecar.mjs', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /setInterval|25000|startTyping/);
});

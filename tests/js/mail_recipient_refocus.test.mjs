import assert from 'node:assert/strict';
import test from 'node:test';
import { harness } from './helpers/mail_workflows_recovery.mjs';

function clock(h) {
  let now = 0, sequence = 0;
  const pending = new Map();
  h.context.setTimeout = (callback, delay) => {
    const id = ++sequence;
    pending.set(id, { callback, due: now + delay });
    return id;
  };
  h.context.clearTimeout = id => pending.delete(id);
  return {
    advance(ms) {
      const end = now + ms;
      while (true) {
        const next = [...pending].filter(([, timer]) => timer.due <= end)
          .sort((a, b) => a[1].due - b[1].due || a[0] - b[0])[0];
        if (!next) break;
        const [id, timer] = next;
        now = timer.due; pending.delete(id); timer.callback();
      }
      now = end;
    },
  };
}

async function setup(role, existing = '') {
  const h = harness();
  const time = clock(h);
  h.context.pre = { body: 'synthetic body', [role]: existing };
  await h.run('compose(pre)');
  const input = h.$('mail-main').querySelector(`.mc-chipfield[data-role="${role}"]`).querySelector('.mc-chip-input');
  const focus = async () => { input.focus(); await input.emit('focus'); };
  const blur = async () => { h.$('mc-subj').focus(); await input.emit('blur'); };
  return { h, time, input, focus, blur };
}

for (const role of ['to', 'cc', 'bcc']) test(`recipient ${role} refocus keeps one whole address through an earlier blur deadline and save`, async () => {
  const { h, time, input, focus, blur } = await setup(role);
  await focus(); await blur();
  time.advance(100);
  await focus();
  input.value = `${role}@e`; await input.emit('input');
  time.advance(60);
  input.value += 'xample.invalid'; await input.emit('input');
  const pendingText = input.value, committedBeforeSave = h.$(`mc-${role}`).value;
  await blur();
  await h.click(h.$('mc-save'));
  // Assert the saved data first: the old callback splits this exact address.
  assert.equal(h.writes[0].pending[role], `${role}@example.invalid`);
  assert.equal(pendingText, `${role}@example.invalid`);
  assert.equal(committedBeforeSave, '');
  assert.equal(h.writes[0].snapshot, h.run('mailEditor().snapshot()'));
  time.advance(160);
  assert.equal(h.writes[0].snapshot, h.run('mailEditor().snapshot()'));
});

for (const role of ['to', 'cc', 'bcc']) test(`recipient ${role} ordinary blur still commits at 160ms and preserves an existing chip`, async () => {
  const { h, time, input, focus, blur } = await setup(role, 'retained@example.invalid');
  await focus(); input.value = `${role}@example.invalid`; await input.emit('input');
  await blur(); time.advance(159);
  assert.equal(input.value, `${role}@example.invalid`);
  assert.equal(h.$(`mc-${role}`).value, 'retained@example.invalid');
  time.advance(1);
  assert.equal(input.value, '');
  assert.equal(h.$(`mc-${role}`).value, `retained@example.invalid, ${role}@example.invalid`);
  await h.click(h.$('mc-save'));
  assert.equal(h.writes[0].pending[role], `retained@example.invalid, ${role}@example.invalid`);
});

for (const key of ['Enter', 'Tab']) test(`recipient ${key} still commits after refocus cancels an earlier blur`, async () => {
  const { h, time, input, focus, blur } = await setup('to', 'retained@example.invalid');
  await focus(); await blur(); time.advance(100); await focus();
  input.value = 'next@example.invalid';
  await input.emit('keydown', { key });
  time.advance(60);
  assert.equal(input.value, '');
  assert.equal(h.$('mc-to').value, 'retained@example.invalid, next@example.invalid');
  await h.click(h.$('mc-save'));
  assert.equal(h.writes[0].pending.to, 'retained@example.invalid, next@example.invalid');
});

test('recipient autocomplete still replaces its query after refocus and saves one whole address', async () => {
  const { h, time, input, focus, blur } = await setup('to');
  await focus(); await blur(); time.advance(100); await focus();
  input.value = 'chosen'; await input.emit('input');
  await input.emit('keydown', { key: 'ArrowDown' });
  await input.emit('keydown', { key: 'Enter' });
  time.advance(60);
  assert.equal(input.value, '');
  assert.equal(h.$('mc-to').value, 'chosen@example.invalid');
  await h.click(h.$('mc-save'));
  assert.equal(h.writes[0].pending.to, 'chosen@example.invalid');
});

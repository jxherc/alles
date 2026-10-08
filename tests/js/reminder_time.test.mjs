import test from 'node:test';
import assert from 'node:assert/strict';

globalThis.window = { addEventListener() {}, dispatchEvent() {} };
globalThis.document = { documentElement: { style: { setProperty() {} } }, addEventListener() {}, querySelectorAll: () => [] };
const { configureLocalization } = await import('../../static/js/i18n.js');
const { reminderTimeFromWall, parseReminderTime, reminderRequest } = await import('../../static/js/reminders.js');
const zone = timezone => configureLocalization({ language: 'en', region: 'CA', timezone });

test('reminder wall clocks use the configured timezone and reject missing dates', () => {
  zone('Asia/Tokyo');
  assert.equal(reminderTimeFromWall('2032-06-10T14:30').toISOString(), '2032-06-10T05:30:00.000Z');
  zone('America/Toronto');
  assert.equal(reminderTimeFromWall('2032-06-10T14:30').toISOString(), '2032-06-10T18:30:00.000Z');
  assert.throws(() => reminderTimeFromWall('2032-02-31T14:30'));
  assert.throws(() => reminderTimeFromWall(''));
});

test('spring missing hours are rejected and repeated autumn hours use the first occurrence', () => {
  zone('America/Toronto');
  assert.throws(() => reminderTimeFromWall('2032-03-14T02:30'), /does not exist/);
  assert.equal(reminderTimeFromWall('2032-11-07T01:30').toISOString(), '2032-11-07T05:30:00.000Z');
});

test('slash times reject overflow clocks and zero intervals', () => {
  for (const text of ['at 99:30', 'at 12:60', 'at 13pm', 'at 0am', 'in 0m']) assert.equal(parseReminderTime(text), null, text);
  const before = Date.now();
  const date = parseReminderTime('in 2h');
  assert.ok(date.getTime() >= before + 7200000 && date.getTime() <= Date.now() + 7200000);
});

test('a retry intention preserves exact text, time and identity while a new action gets another identity', () => {
  const date = new Date('2032-06-10T05:30:00Z');
  const first = reminderRequest(' exact text ', date, 'message', 'conversation');
  assert.equal(first.text, ' exact text ');
  assert.equal(first.trigger_at, date.toISOString());
  assert.equal(first.session_id, 'conversation');
  assert.ok(Object.isFrozen(first));
  assert.notEqual(first.request_id, reminderRequest(' exact text ', date, 'message', 'conversation').request_id);
});

test('reminder identities retain secure randomness when randomUUID is unavailable', () => {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'crypto');
  const provider = globalThis.crypto;
  Object.defineProperty(globalThis, 'crypto', { configurable: true, value: { getRandomValues: bytes => provider.getRandomValues(bytes) } });
  try {
    const request = reminderRequest('fixture', new Date('2032-06-10T05:30:00Z'));
    assert.match(request.request_id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    assert.notEqual(request.request_id, reminderRequest('fixture', new Date('2032-06-10T05:30:00Z')).request_id);
  } finally { Object.defineProperty(globalThis, 'crypto', original); }
});

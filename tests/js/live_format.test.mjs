import test from 'node:test';
import assert from 'node:assert/strict';
import { finishUrl, formatCard, formatDate, formatDecimal, formatExpiry, formatHex, formatPhone, formatTime, phoneDigits } from '../../static/js/liveformat.js';

test('north american numbers get +1, brackets and a dash', () => {
  assert.equal(formatPhone('14373405952'), '+1 (437) 340-5952');
  assert.equal(formatPhone('+14373405952'), '+1 (437) 340-5952');
  assert.equal(formatPhone('4373405952'), '(437) 340-5952');
  assert.equal(formatPhone('+1 437-340-5952'), '+1 (437) 340-5952');
});

test('it formats while you type, one digit at a time', () => {
  const typed = '14373405952';
  const steps = [...typed].map((_, i) => formatPhone(typed.slice(0, i + 1)));
  assert.deepEqual(steps, [
    '+1', '+1 (4', '+1 (43', '+1 (437', '+1 (437) 3', '+1 (437) 34', '+1 (437) 340',
    '+1 (437) 340-5', '+1 (437) 340-59', '+1 (437) 340-595', '+1 (437) 340-5952',
  ]);
});

test('a typed + picks the country by its calling code', () => {
  assert.equal(formatPhone('+819012345678'), '+81 90 1234 5678');
  assert.equal(formatPhone('+81312345678'), '+81 3 1234 5678');
  assert.equal(formatPhone('+447911123456'), '+44 7911 123456');
  assert.equal(formatPhone('+8613800138000'), '+86 138 0013 8000');
  assert.equal(formatPhone('+33612345678'), '+33 6 12 34 56 78');
  assert.equal(formatPhone('+85291234567'), '+852 9123 4567');
  assert.equal(formatPhone('+'), '+');
  assert.equal(formatPhone('+8'), '+8');
  assert.equal(formatPhone('+81'), '+81');
});

test('emails and words are left alone', () => {
  assert.equal(formatPhone('me@example.test'), 'me@example.test');
  assert.equal(formatPhone('call me'), 'call me');
  assert.equal(formatPhone(''), '');
});

test('the digits are what count', () => {
  assert.equal(phoneDigits('+1 (437) 340-5952'), '+14373405952');
  assert.equal(phoneDigits('+81 90 1234 5678'), '+819012345678');
});

test('card numbers group in fours, amex 4-6-5', () => {
  assert.equal(formatCard('4242424242424242'), '4242 4242 4242 4242');
  assert.equal(formatCard('42424'), '4242 4');
  assert.equal(formatCard('378282246310005'), '3782 822463 10005');
});

test('expiry gets its slash on its own', () => {
  assert.equal(formatExpiry('1'), '1');
  assert.equal(formatExpiry('4'), '04/');
  assert.equal(formatExpiry('12'), '12/');
  assert.equal(formatExpiry('1227'), '12/27');
  assert.equal(formatExpiry('12/', true), '12');
});

test('amounts keep digits, one dot and a minus', () => {
  assert.equal(formatDecimal('12.50'), '12.50');
  assert.equal(formatDecimal('1,234.50'), '1234.50');
  assert.equal(formatDecimal('12,50'), '12.50');
  assert.equal(formatDecimal('$8.25'), '8.25');
  assert.equal(formatDecimal('-8.2.5'), '-8.25');
  assert.equal(formatDecimal('1 000'), '1000');
});

test('dates get their dashes as you type', () => {
  assert.equal(formatDate('2026'), '2026-');
  assert.equal(formatDate('202610'), '2026-10-');
  assert.equal(formatDate('20261021'), '2026-10-21');
  assert.equal(formatDate('2026-', true), '2026');
  assert.equal(formatDate('2026/10/21'), '2026-10-21');
});

test('times get their colon, and a big first digit means one-digit hour', () => {
  assert.equal(formatTime('0930'), '09:30');
  assert.equal(formatTime('9'), '09:');
  assert.equal(formatTime('23'), '23:');
  assert.equal(formatTime('23:', true), '23');
  assert.equal(formatTime('2300'), '23:00');
});

test('hex colors start with # and keep hex only', () => {
  assert.equal(formatHex('ff00aa'), '#ff00aa');
  assert.equal(formatHex('#zz12'), '#12');
  assert.equal(formatHex(''), '');
});

test('bare addresses get a scheme when you leave the field', () => {
  assert.equal(finishUrl('example.com/feed.xml'), 'https://example.com/feed.xml');
  assert.equal(finishUrl('192.168.1.5:8080'), 'http://192.168.1.5:8080');
  assert.equal(finishUrl('localhost:3000'), 'http://localhost:3000');
  assert.equal(finishUrl('https://x.test'), 'https://x.test');
  assert.equal(finishUrl('not a url'), 'not a url');
  assert.equal(finishUrl(''), '');
});

test('a decimal comma survives typing and is settled when the field is finished', () => {
  // key by key, the comma must not vanish (42,50 used to save as 4250)
  let typed = '';
  for (const key of '42,50') typed = formatDecimal(typed + key, true);
  assert.equal(typed, '42,50');
  assert.equal(formatDecimal(typed), '42.50');
  assert.equal(formatDecimal('12,5'), '12.5');
  assert.equal(formatDecimal('72,5'), '72.5');
  assert.equal(formatDecimal('1,650'), '1650');
  assert.equal(formatDecimal('1,234,567'), '1234567');
  assert.equal(formatDecimal('4 200,00'), '4200.00');
  assert.equal(formatDecimal('-3,5'), '-3.5');
});

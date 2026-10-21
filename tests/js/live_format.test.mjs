import test from 'node:test';
import assert from 'node:assert/strict';
import { formatCard, formatExpiry, formatPhone, phoneDigits } from '../../static/js/liveformat.js';

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

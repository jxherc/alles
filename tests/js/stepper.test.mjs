import assert from 'node:assert/strict';
import test from 'node:test';
import { stepValue, stepperHtml } from '../../static/js/stepper.js';

test('a press moves one step and stays inside the floor and ceiling', () => {
  assert.equal(stepValue('60', 1, { step: 5 }), 65);
  assert.equal(stepValue('0', -1, { step: 1 }), 0);
  assert.equal(stepValue('9', 1, { step: 1, max: 10 }), 10);
  assert.equal(stepValue('10', 1, { step: 1, max: 10 }), 10);
});

test('empty or unknown counts from the floor', () => {
  assert.equal(stepValue('', 1, { step: 1 }), 1);
  assert.equal(stepValue('?', 1, { step: 2.5 }), 2.5);
  assert.equal(stepValue('', 1, { step: 1, min: 3 }), 4);
});

test('decimal steps stay on the step and read a comma', () => {
  assert.equal(stepValue('0.1', 1, { step: 0.2 }), 0.3);
  assert.equal(stepValue('22,5', 1, { step: 2.5 }), 25);
});

test('the markup names both buttons after the field and can be switched off', () => {
  const html = stepperHtml({ name: 'weight', value: '60', step: 5 });
  assert.match(html, /data-kokuen-stepper="auto" data-step="5" data-min="0"/);
  assert.match(html, /aria-label="less, weight"/);
  assert.match(html, /aria-label="more, weight"/);
  assert.match(html, /value="60"/);
  const off = stepperHtml({ name: 'glasses', disabled: true, auto: false, attrs: 'data-key="n"' });
  assert.doesNotMatch(off, /data-kokuen-stepper/);
  assert.match(off, /data-key="n"/);
  assert.equal((off.match(/ disabled/g) || []).length, 3);
});

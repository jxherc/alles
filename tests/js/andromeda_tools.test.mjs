import test from 'node:test';
import assert from 'node:assert/strict';

const tools = await import('../../static/js/andromeda_tools.js');
const { answerCovers, skyKind } = await import('../../static/js/andromeda_answers.js');

test('each sky gets the mark people read it by', () => {
  assert.equal(skyKind('clear'), 'sun');
  assert.equal(skyKind('partly cloudy'), 'partly');
  assert.equal(skyKind('light drizzle'), 'rain');
  assert.equal(skyKind('snow showers'), 'snow');
  assert.equal(skyKind('thunderstorm with hail'), 'storm');
  assert.equal(skyKind('freezing fog'), 'fog');
  assert.equal(skyKind('cloudy'), 'cloud');
  assert.equal(skyKind(''), '');
});

test('timer lengths read the way people type them', () => {
  assert.equal(tools.parseDuration('5'), 300000);
  assert.equal(tools.parseDuration('1:30'), 90000);
  assert.equal(tools.parseDuration('1:00:00'), 3600000);
  assert.equal(tools.parseDuration('90s'), 90000);
  assert.equal(tools.parseDuration('1h 30m'), 5400000);
  assert.equal(tools.parseDuration('soon'), 0);
});

test('unit conversion matches the server table, temperature included', () => {
  const km = { id: 'km', kind: 'length', factor: 1000 };
  const mi = { id: 'mi', kind: 'length', factor: 1609.344 };
  assert.ok(Math.abs(tools.convertUnits(10, km, mi) - 6.2137119) < 1e-6);
  const c = { id: 'c', kind: 'temperature', factor: null };
  const f = { id: 'f', kind: 'temperature', factor: null };
  assert.ok(Math.abs(tools.convertUnits(100, c, f) - 212) < 1e-9);
  assert.ok(Math.abs(tools.convertUnits(72, f, c) - 22.2222222) < 1e-6);
});

test('colors round-trip between hex, rgb and hsl', () => {
  assert.deepEqual(tools.hexToRgb('#3a7bd5'), [58, 123, 213]);
  assert.deepEqual(tools.hexToRgb('fff'), [255, 255, 255]);
  assert.equal(tools.hexToRgb('#zzz'), null);
  assert.equal(tools.rgbToHex([58, 123, 213]), '#3a7bd5');
  assert.deepEqual(tools.rgbToHsl([58, 123, 213]), [215, 65, 53]);
  const back = tools.hslToRgb([215, 65, 53]);
  back.forEach((value, index) => assert.ok(Math.abs(value - [58, 123, 213][index]) <= 2));
  assert.ok(tools.contrast([0, 0, 0], [255, 255, 255]) > 20.9);
});

test('random picks stay inside their range', () => {
  for (let i = 0; i < 500; i += 1) {
    const value = tools.randomInt(3, 7);
    assert.ok(value >= 3 && value <= 7 && Number.isInteger(value));
  }
  assert.equal(tools.randomInt(4, 4), 4);
});

test('world clock cities find their zone', () => {
  assert.equal(tools.zoneFor('Tokyo'), 'Asia/Tokyo');
  assert.equal(tools.zoneFor('nyc'), 'America/New_York');
  assert.equal(tools.zoneFor('new york'), 'America/New_York');
  assert.equal(tools.zoneFor('narnia'), '');
});

test('only a card that really answers lets the overview wait', () => {
  assert.equal(answerCovers({ kind: 'translate', status: 'empty' }), true);
  assert.equal(answerCovers({ kind: 'calc', status: 'ok' }), true);
  assert.equal(answerCovers({ kind: 'weather', status: 'unavailable' }), false);
  assert.equal(answerCovers({ kind: 'define', status: 'not_found' }), false);
  assert.equal(answerCovers({ kind: 'translate', status: 'needs_model' }), false);
  for (const kind of ['tip', 'percent', 'bmi', 'loan', 'base', 'roman', 'unix', 'generate', 'encode', 'counter', 'moon', 'numfacts']) {
    assert.equal(answerCovers({ kind, status: 'ok' }), true, kind);
  }
  assert.equal(answerCovers({ kind: null }), false);
  assert.equal(answerCovers(null), false);
});

import test from 'node:test';
import assert from 'node:assert/strict';

const calc = await import('../../static/js/andromeda_calcs.js');
const near = (value, want, slack = 0.01) => assert.ok(Math.abs(value - want) <= slack, `${value} is not near ${want}`);

test('tip adds up and splits', () => {
  const out = calc.tipSplit(120, 15, 4);
  near(out.total, 138);
  near(out.each, 34.5);
  assert.equal(calc.tipSplit(64, 18, NaN).people, 1);
  assert.equal(calc.tipSplit(NaN, 18, 1), null);
  assert.equal(calc.tipSplit(64, 18, 0), null);
});

test('percentages', () => {
  near(calc.percentage('of', 15, 80).value, 12);
  near(calc.percentage('is', 20, 80).value, 25);
  near(calc.percentage('change', 40, 50).value, 25);
  near(calc.percentage('change', 50, 40).value, -20);
  near(calc.percentage('off', 20, 80).value, 64);
  assert.equal(calc.percentage('is', 5, 0), null);
  assert.equal(calc.percentage('change', 0, 5), null);
});

test('bmi and loans', () => {
  const body = calc.bmi(70, 175);
  near(body.value, 22.86);
  assert.equal(body.group, 'healthy');
  assert.equal(calc.bmi(50, 175).group, 'under');
  assert.equal(calc.bmi(95, 175).group, 'obese');
  assert.equal(calc.bmi(0, 175), null);
  near(calc.loan(400000, 5, 25).monthly, 2338.36);
  near(calc.loan(12000, 0, 1).monthly, 1000);
  assert.equal(calc.loan(1000, -1, 1), null);
});

test('number bases read prefixes and refuse wrong digits', () => {
  assert.equal(calc.formatBase(calc.parseBase('255', 10), 16), 'ff');
  assert.equal(calc.parseBase('0xff', 16), 255n);
  assert.equal(calc.parseBase('1010', 2), 10n);
  assert.equal(calc.parseBase('-0b11', 2), -3n);
  assert.equal(calc.parseBase('12', 2), null);
  assert.equal(calc.parseBase('ff', 10), null);
  assert.equal(calc.formatBase(calc.parseBase('99999999999999999999', 10), 16), '56bc75e2d630fffff');
});

test('roman numerals both ways', () => {
  assert.equal(calc.toRoman(1994), 'MCMXCIV');
  assert.equal(calc.toRoman(3999), 'MMMCMXCIX');
  assert.equal(calc.toRoman(0), '');
  assert.equal(calc.toRoman(4000), '');
  assert.equal(calc.fromRoman('mcmxciv'), 1994);
  assert.equal(calc.fromRoman('IIII'), 0);
  assert.equal(calc.fromRoman('ABC'), 0);
  for (let value = 1; value <= 3999; value += 1) assert.equal(calc.fromRoman(calc.toRoman(value)), value);
});

test('unix time reads a wall clock in a zone', () => {
  assert.equal(calc.zonedToEpoch('2026-10-28 12:00', 'UTC'), 1793188800);
  assert.equal(calc.zonedToEpoch('2026-10-28 08:00', 'America/New_York'), 1793188800);
  assert.equal(calc.zonedToEpoch('2026-10-28', 'UTC'), 1793145600);
  assert.equal(calc.zonedToEpoch('2023-02-30', 'UTC'), null);
  assert.equal(calc.zonedToEpoch('soon', 'UTC'), null);
  assert.equal(calc.epochToMs('1730000000'), 1730000000000);
  assert.equal(calc.epochToMs('1730000000000'), 1730000000000);
  assert.equal(calc.epochToMs('abc'), null);
});

test('passwords hold every chosen kind and uuids are version 4', () => {
  const pick = (low, high) => low + Math.floor(Math.random() * (high - low + 1));
  for (let round = 0; round < 200; round += 1) {
    const text = calc.makePassword(8, { upper: true, digits: true, symbols: true }, pick);
    assert.equal(text.length, 8);
    assert.match(text, /[a-z]/);
    assert.match(text, /[A-Z]/);
    assert.match(text, /\d/);
    assert.match(text, /[^a-zA-Z0-9]/);
  }
  assert.match(calc.makePassword(30, { upper: false, digits: false, symbols: false }, pick), /^[a-z]{30}$/);
  assert.match(calc.makeUuid(new Uint8Array(16).fill(255)), /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  near(calc.passwordBits(16), 16 * Math.log2(26 + 26 + 10 + 23), 0.001);
});

test('encoders round-trip and refuse what they cannot read', () => {
  for (const [name, text] of [['base64', 'héllo wörld 你好'], ['url', 'a b&c=d/é'], ['html', `<a href="x">'&</a>`]]) {
    assert.equal(calc.ENCODERS[name].decode(calc.ENCODERS[name].encode(text)), text, name);
  }
  assert.equal(calc.ENCODERS.base64.encode('hello'), 'aGVsbG8=');
  assert.equal(calc.ENCODERS.base64.decode('aGVsbG8'), 'hello');
  assert.equal(calc.ENCODERS.url.decode('%20'), ' ');
  assert.throws(() => calc.ENCODERS.base64.decode('!!!'));
  assert.throws(() => calc.ENCODERS.base64.decode('/w=='));
  assert.throws(() => calc.ENCODERS.url.decode('%E0%A4%A'));
});

test('the counter counts words, sentences and paragraphs', () => {
  const out = calc.countText('Hello world. This is a test!\n\nNew paragraph');
  assert.equal(out.words, 8);
  assert.equal(out.sentences, 3);
  assert.equal(out.paragraphs, 2);
  assert.equal(out.characters, 43);
  assert.equal(calc.countText('').words, 0);
  assert.equal(calc.countText('   ').paragraphs, 0);
});

test('the moon matches known full and new moons', () => {
  const minutes = (ms, want) => near(ms / 60000, Date.parse(want) / 60000, 3);
  const before = calc.moon(Date.UTC(2025, 0, 10));
  minutes(before.nextFull, '2025-01-13T22:27:00Z');
  minutes(before.nextNew, '2025-01-29T12:36:00Z');
  const full = calc.moon(Date.UTC(2026, 9, 26, 12));
  assert.equal(full.phase, 'full');
  assert.ok(full.illumination > 0.97);
  assert.equal(calc.moon(Date.UTC(2025, 0, 29, 12, 40)).phase, 'new');
  for (let at = Date.UTC(2024, 0, 1); at < Date.UTC(2028, 0, 1); at += 5 * 3600e3) {
    const now = calc.moon(at);
    assert.ok(now.fraction >= 0 && now.fraction < 1 && now.nextFull > at && now.nextNew > at);
  }
});

test('number facts', () => {
  assert.deepEqual(calc.factorize(360), [[2, 3], [3, 2], [5, 1]]);
  assert.equal(calc.divisors(360).length, 24);
  assert.equal(calc.isPrime(97), true);
  assert.equal(calc.isPrime(91), false);
  assert.equal(calc.isPrime(1), false);
  assert.equal(calc.isPrime(999999999989), true);
  assert.equal(calc.gcd(48, 18), 6);
  assert.equal(calc.lcm(4, 6), 12n);
  assert.equal(calc.lcm(999999999989, 999999999979), 999999999989n * 999999999979n);
  assert.equal(calc.wholeNumber('1,000'), 1000);
  assert.equal(calc.wholeNumber('2.5'), null);
  assert.equal(calc.wholeNumber('0'), null);
  assert.equal(calc.wholeNumber('1000000000001'), null);
});

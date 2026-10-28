// The maths behind Andromeda's small tools (tip, percentages, bmi, loans, number bases, roman
// numerals, unix time, passwords, encoders, counters, the moon, number facts). Pure functions, no
// page and no network, so the same code answers while the owner types and in the node tests.

import { formatDateParts } from './i18n.js';

const good = value => Number.isFinite(value);

// ── tip ──
// blank people means one. null when a number can't be used
export function tipSplit(bill, percent, people = 1) {
  const count = Number.isNaN(people) ? 1 : people;
  if (!good(bill) || !good(percent) || bill < 0 || percent < 0 || !Number.isInteger(count) || count < 1 || count > 100) return null;
  const tip = bill * percent / 100;
  const total = bill + tip;
  return { tip, total, each: total / count, tipEach: tip / count, people: count };
}

// ── percentages ──
export function percentage(mode, a, b) {
  if (!good(a) || !good(b)) return null;
  if (mode === 'of') return { value: a / 100 * b };
  if (mode === 'is') return b === 0 ? null : { value: a / b * 100 };
  if (mode === 'change') return a === 0 ? null : { value: (b - a) / Math.abs(a) * 100, diff: b - a };
  if (mode === 'off') return { value: b * (1 - a / 100), saved: b * a / 100 };
  return null;
}

// ── bmi ──
export function bmi(kg, cm) {
  if (!good(kg) || !good(cm) || kg <= 0 || cm <= 0) return null;
  const metres = cm / 100;
  const value = kg / (metres * metres);
  const group = value < 18.5 ? 'under' : value < 25 ? 'healthy' : value < 30 ? 'over' : 'obese';
  return { value, group, low: 18.5 * metres * metres, high: 24.9 * metres * metres };
}

// ── loans ──
export function loan(amount, ratePercent, years) {
  if (!good(amount) || !good(ratePercent) || !good(years) || amount <= 0 || ratePercent < 0 || years <= 0 || years > 100) return null;
  const months = Math.round(years * 12);
  const rate = ratePercent / 1200;
  const monthly = rate === 0 ? amount / months : amount * rate / (1 - (1 + rate) ** -months);
  return { monthly, total: monthly * months, interest: monthly * months - amount };
}

// ── number bases ──
const BASE_DIGITS = { 2: /^[01]+$/, 8: /^[0-7]+$/, 10: /^\d+$/, 16: /^[0-9a-f]+$/i };
const BASE_PREFIX = { 2: '0b', 8: '0o', 10: '', 16: '0x' };

export function parseBase(text, base) {
  let value = String(text || '').replace(/[\s_,]/g, '').toLowerCase();
  const negative = value.startsWith('-');
  if (negative || value.startsWith('+')) value = value.slice(1);
  if (BASE_PREFIX[base] && value.startsWith(BASE_PREFIX[base])) value = value.slice(2);
  if (!BASE_DIGITS[base].test(value)) return null;
  const whole = BigInt((BASE_PREFIX[base] || '') + value);
  return negative ? -whole : whole;
}

export const formatBase = (whole, base) => whole.toString(base);

// ── roman numerals ──
const ROMAN = [[1000, 'M'], [900, 'CM'], [500, 'D'], [400, 'CD'], [100, 'C'], [90, 'XC'], [50, 'L'], [40, 'XL'], [10, 'X'], [9, 'IX'], [5, 'V'], [4, 'IV'], [1, 'I']];

export function toRoman(number) {
  if (!Number.isInteger(number) || number < 1 || number > 3999) return '';
  let left = number;
  let out = '';
  for (const [size, glyph] of ROMAN) while (left >= size) { out += glyph; left -= size; }
  return out;
}

// 0 for anything that isn't a proper numeral
export function fromRoman(text) {
  const value = String(text || '').trim().toUpperCase();
  if (!/^(?=.)M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$/.test(value)) return 0;
  let total = 0;
  let rest = value;
  for (const [size, glyph] of ROMAN) while (rest.startsWith(glyph)) { total += size; rest = rest.slice(glyph.length); }
  return total;
}

// ── unix time ──
// "2026-10-28 14:30[:05]" read as a wall clock in the given zone, as epoch seconds; null if it isn't a date
export function zonedToEpoch(text, zone) {
  const found = /^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$/.exec(String(text || '').trim());
  if (!found) return null;
  const [year, month, day, hour, minute, second] = found.slice(1).map(part => Number(part ?? 0));
  const wall = Date.UTC(year, month - 1, day, hour, minute, second);
  const check = new Date(wall);
  if (check.getUTCMonth() !== month - 1 || check.getUTCDate() !== day || hour > 23 || minute > 59 || second > 59) return null;
  const offset = ms => {
    const parts = Object.fromEntries(formatDateParts(ms, { timeZone: zone, calendar: 'gregory', numberingSystem: 'latn', hourCycle: 'h23', year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric', second: 'numeric' }).map(part => [part.type, Number(part.value)]));
    return Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second) - Math.floor(ms / 1000) * 1000;
  };
  const first = wall - offset(wall);
  return Math.floor((wall - offset(first)) / 1000);
}

// a timestamp in seconds or, from 13 digits, milliseconds
export function epochToMs(text) {
  const digits = String(text || '').trim();
  if (!/^-?\d{1,14}$/.test(digits)) return null;
  const ms = digits.replace('-', '').length > 11 ? Number(digits) : Number(digits) * 1000;
  return Math.abs(ms) <= 8.64e15 ? ms : null;
}

// ── passwords and uuids ──
const LOWER = 'abcdefghijklmnopqrstuvwxyz';
const UPPER = LOWER.toUpperCase();
const DIGITS = '0123456789';
const SYMBOLS = '!@#$%^&*()-_=+[]{};:,.?';

// one of each chosen kind is always in, the rest is drawn from all of them, then shuffled.
// pick(min, max) is the browser's crypto source, passed in so this file stays page-free
export function makePassword(length, { upper = true, digits = true, symbols = true } = {}, pick) {
  const sets = [LOWER, upper && UPPER, digits && DIGITS, symbols && SYMBOLS].filter(Boolean);
  const pool = sets.join('');
  const chars = sets.map(set => set[pick(0, set.length - 1)]);
  while (chars.length < length) chars.push(pool[pick(0, pool.length - 1)]);
  for (let at = chars.length - 1; at > 0; at -= 1) {
    const other = pick(0, at);
    [chars[at], chars[other]] = [chars[other], chars[at]];
  }
  return chars.join('');
}

export const passwordBits = (length, { upper = true, digits = true, symbols = true } = {}) => length * Math.log2(LOWER.length + (upper ? 26 : 0) + (digits ? 10 : 0) + (symbols ? SYMBOLS.length : 0));

// version 4: 16 random bytes with the version and variant bits set
export function makeUuid(bytes) {
  const out = Array.from(bytes);
  out[6] = (out[6] & 0x0f) | 0x40;
  out[8] = (out[8] & 0x3f) | 0x80;
  const hex = out.map(byte => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

// ── encoders ── each throws on input it can't read
const ENTITIES = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' };

export const ENCODERS = {
  base64: {
    encode: text => btoa(Array.from(new TextEncoder().encode(text), byte => String.fromCharCode(byte)).join('')),
    decode: text => {
      const clean = text.replace(/\s+/g, '').replace(/-/g, '+').replace(/_/g, '/');
      if (!/^[A-Za-z0-9+/]*={0,2}$/.test(clean) || clean.length % 4 === 1) throw new Error('base64');
      const binary = atob(clean.padEnd(Math.ceil(clean.length / 4) * 4, '='));
      return new TextDecoder('utf-8', { fatal: true }).decode(Uint8Array.from(binary, char => char.charCodeAt(0)));
    },
  },
  url: {
    encode: text => encodeURIComponent(text),
    decode: text => decodeURIComponent(text.replace(/\+/g, ' ')),
  },
  html: {
    encode: text => text.replace(/[&<>"']/g, char => `&${{ '&': 'amp', '<': 'lt', '>': 'gt', '"': 'quot', "'": '#39' }[char]};`),
    decode: text => text.replace(/&(?:#(\d+)|#x([0-9a-f]+)|([a-z]+));/gi, (whole, dec, hex, name) => {
      if (name) return ENTITIES[name.toLowerCase()] ?? whole;
      const code = dec ? Number(dec) : parseInt(hex, 16);
      return code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : whole;
    }),
  },
};

// ── counters ──
export function countText(text) {
  const value = String(text ?? '');
  let words;
  if (typeof Intl.Segmenter === 'function') words = [...new Intl.Segmenter(undefined, { granularity: 'word' }).segment(value)].filter(part => part.isWordLike).length;
  else words = value.trim() ? value.trim().split(/\s+/).length : 0;
  const sentences = (value.match(/[^.!?…。！？\n]+(?:[.!?…。！？]+|$)/g) || []).filter(part => /[\p{L}\p{N}]/u.test(part)).length;
  const paragraphs = value.split(/\n\s*\n/).filter(part => part.trim()).length;
  // 238 words a minute, the average adult's silent reading speed
  return { words, characters: [...value].length, noSpaces: [...value.replace(/\s/g, '')].length, sentences, paragraphs, minutes: words / 238 };
}

// ── moon ──
// Meeus, Astronomical Algorithms ch. 49: the instant of a new moon (whole k) or full moon (k + 1/2),
// with the main periodic terms. good to a few minutes, so the dates are right in any time zone
const rad = Math.PI / 180;
const sine = degrees => Math.sin(degrees * rad);

function phaseInstant(k) {
  const T = k / 1236.85;
  const full = Math.abs(k % 1) > 0.25;
  const E = 1 - 0.002516 * T - 0.0000074 * T * T;
  const M = 2.5534 + 29.1053567 * k - 0.0000014 * T * T;
  const Mp = 201.5643 + 385.81693528 * k + 0.0107582 * T * T + 0.00001238 * T ** 3;
  const F = 160.7108 + 390.67050284 * k - 0.0016118 * T * T - 0.00000227 * T ** 3;
  const O = 124.7746 - 1.56375588 * k + 0.0020672 * T * T;
  const [a, b, c, d, e, f, g] = full ? [-0.40614, 0.17302, 0.01614, 0.01043, 0.00734, -0.00515, 0.00209] : [-0.4072, 0.17241, 0.01608, 0.01039, 0.00739, -0.00514, 0.00208];
  const jde = 2451550.09766 + 29.530588861 * k + 0.00015437 * T * T - 0.00000015 * T ** 3
    + a * sine(Mp) + b * E * sine(M) + c * sine(2 * Mp) + d * sine(2 * F) + e * E * sine(Mp - M) + f * E * sine(Mp + M) + g * E * E * sine(2 * M)
    - 0.00111 * sine(Mp - 2 * F) - 0.00057 * sine(Mp + 2 * F) + 0.00056 * E * sine(2 * Mp + M) - 0.00042 * sine(3 * Mp)
    + 0.00042 * E * sine(M + 2 * F) + 0.00038 * E * sine(M - 2 * F) - 0.00024 * E * sine(2 * Mp - M) - 0.00017 * sine(O);
  // dynamical time runs about 69 s ahead of the clock
  return (jde - 2440587.5) * 86400000 - 69000;
}

export const MOON_PHASES = ['new', 'waxing_crescent', 'first_quarter', 'waxing_gibbous', 'full', 'waning_gibbous', 'last_quarter', 'waning_crescent'];

// ms is a time; fraction runs 0 (new) to 1 (the next new moon)
export function moon(ms) {
  const lunation = Math.floor((ms / 86400000 + 2440587.5 - 2451550.09766) / 29.530588861);
  const news = [lunation - 1, lunation, lunation + 1, lunation + 2].map(phaseInstant);
  const fulls = [lunation - 1, lunation, lunation + 1, lunation + 2].map(k => phaseInstant(k + 0.5));
  const at = news.findLastIndex(time => time <= ms);
  const previous = news[at];
  const next = news[at + 1];
  const fraction = (ms - previous) / (next - previous);
  return {
    fraction,
    illumination: (1 - Math.cos(2 * Math.PI * fraction)) / 2,
    age: (ms - previous) / 86400000,
    phase: MOON_PHASES[Math.floor(((fraction + 1 / 16) % 1) * 8)],
    nextFull: fulls.find(time => time > ms),
    nextNew: next,
  };
}

// ── number facts ──
export const MAX_FACT = 1e12;
export const wholeNumber = text => {
  const value = Number(String(text ?? '').replace(/[\s,]/g, ''));
  return String(text ?? '').trim() && Number.isInteger(value) && value >= 1 && value <= MAX_FACT ? value : null;
};

export function factorize(number) {
  const out = [];
  let left = number;
  for (let divisor = 2; divisor * divisor <= left; divisor += divisor === 2 ? 1 : 2) {
    let power = 0;
    while (left % divisor === 0) { left /= divisor; power += 1; }
    if (power) out.push([divisor, power]);
  }
  if (left > 1) out.push([left, 1]);
  return out;
}

export function isPrime(number) {
  const parts = factorize(number);
  return parts.length === 1 && parts[0][1] === 1;
}

export function divisors(number) {
  let out = [1];
  for (const [prime, power] of factorize(number)) out = out.flatMap(base => Array.from({ length: power + 1 }, (_, step) => base * prime ** step));
  return out.sort((a, b) => a - b);
}

export function gcd(a, b) {
  let x = a;
  let y = b;
  while (y) [x, y] = [y, x % y];
  return x;
}

// bigint: two numbers near a trillion multiply past what a double holds exactly
export const lcm = (a, b) => (BigInt(a) / BigInt(gcd(a, b))) * BigInt(b);

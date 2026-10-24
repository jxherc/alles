import test from 'node:test';
import assert from 'node:assert/strict';
import { finishBirthday, finishUrl, formatBirthday, formatCard, formatDate, formatDecimal, formatExpiry, formatHex, formatPhone, formatTime, phoneDigits } from '../../static/js/liveformat.js';

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
  // a thousands group never starts with 0
  assert.equal(formatDecimal('0,125'), '0.125');
  assert.equal(formatDecimal('-0,125'), '-0.125');
  assert.equal(formatDecimal('$1,650'), '1650');
});

test('a birthday typed as words ends as a date contacts can read', () => {
  assert.equal(finishBirthday('march 3'), '--03-03');
  assert.equal(finishBirthday('3 March'), '--03-03');
  assert.equal(finishBirthday('Dec 25, 1985'), '1985-12-25');
  assert.equal(finishBirthday('19900303'), '1990-03-03');
  assert.equal(finishBirthday('blah 3'), 'blah 3');
});

// what the field does: format on every key, then format + finish when it's left
const typeBirthday = keys => {
  let typed = '';
  for (const key of keys) typed = formatBirthday(typed + key);
  return typed;
};
const leaveBirthday = value => finishBirthday(formatBirthday(value));

test('a finished birthday stays put when the field reformats it', () => {
  // leaving the field fires input again, which used to turn --03-03 into 0303-
  for (const done of ['--03-03', '--12-25', '1990-03-03']) {
    assert.equal(formatBirthday(done), done);
    assert.equal(leaveBirthday(done), done);
  }
  assert.equal(leaveBirthday(leaveBirthday('march 3')), '--03-03');
  // a vcard-style --0303 settles into the dashed form
  assert.equal(leaveBirthday('--0303'), '--03-03');
});

test('a stored month-day birthday keeps its month and day', () => {
  // contacts stores 03-03 for a year-less birthday; focus + tab used to turn it into 0303-
  assert.equal(formatBirthday('03-03'), '03-03');
  assert.equal(leaveBirthday('03-03'), '--03-03');
  assert.equal(leaveBirthday('--3-3'), '--03-03');
  assert.equal(leaveBirthday('3-3'), '--03-03');
  assert.equal(leaveBirthday('12-25'), '--12-25');
  for (const value of ['03-03', '--3-3', '--03-03', '12-25', '1990-03-03', 'march 3']) {
    assert.equal(leaveBirthday(leaveBirthday(value)), leaveBirthday(value));
  }
  // not a month and day: left as typed, not reshaped into something else
  assert.equal(leaveBirthday('13-40'), '13-40');
  // backspacing out of --03-03 and typing into the dashes still work
  assert.equal(formatBirthday('--03-0', true), '--03-0');
  assert.equal(formatBirthday('--03-', true), '--03');
  assert.equal(formatBirthday('--031'), '--03-1');
  assert.equal(formatBirthday('--0303'), '--03-03');
});

test('a month-day birthday can be typed key by key', () => {
  // the dash used to vanish as it was typed, so 03-03 saved as 0303-
  assert.equal(typeBirthday('03-'), '03-');
  assert.equal(typeBirthday('03-03'), '03-03');
  assert.equal(leaveBirthday(typeBirthday('03-03')), '--03-03');
  assert.equal(typeBirthday('--03-03'), '--03-03');
  assert.equal(leaveBirthday(typeBirthday('--03-03')), '--03-03');
  assert.equal(typeBirthday('3-3'), '3-3');
  assert.equal(leaveBirthday(typeBirthday('3-3')), '--03-03');
  assert.equal(typeBirthday('0303'), '0303-');
  assert.equal(leaveBirthday(typeBirthday('0303')), '--03-03');
  assert.equal(leaveBirthday(typeBirthday('1225')), '--12-25');
  // a year on its own isn't a month and a day
  assert.equal(leaveBirthday(typeBirthday('1990')), '1990-');
  // backspacing out of 03- drops the dash instead of keeping it
  assert.equal(formatBirthday('03-', true), '03');
  for (const keys of ['03-03', '--03-03', '3-3', '0303']) {
    const done = leaveBirthday(typeBirthday(keys));
    assert.equal(leaveBirthday(done), done);
  }
});

test('a day-first birthday can be typed key by key', () => {
  assert.equal(typeBirthday('3 march'), '3 march');
  assert.equal(leaveBirthday(typeBirthday('3 march')), '--03-03');
  assert.equal(leaveBirthday(typeBirthday('12 dec 1990')), '1990-12-12');
  assert.equal(leaveBirthday(typeBirthday('march 3')), '--03-03');
  assert.equal(finishBirthday('3march'), '--03-03');
  assert.equal(finishBirthday('1st'), '1st');
  // plain digits still get date dashes
  assert.equal(typeBirthday('19900303'), '1990-03-03');
});

// a bare-bones stand-in for the page, enough for initLiveFormat's listeners
function liveFields() {
  class Field {
    constructor(attrs = {}, dataset = {}) {
      this.attrs = attrs; this.dataset = dataset; this.value = ''; this.heard = []; this.own = {}; this.isConnected = true;
    }
    getAttribute(name) { return this.attrs[name] ?? null; }
    setAttribute(name, value) { this.attrs[name] = value; }
    matches() { return false; }
    dispatchEvent(event) { this.heard.push(event.type); root.fire(event.type, { target: this, isTrusted: false }); }
  }
  globalThis.HTMLInputElement = Field;
  globalThis.HTMLTextAreaElement = class {};
  globalThis.document = { activeElement: null };
  let listeners = [];
  const root = {
    addEventListener(type, fn, capture = false) { listeners.push({ type, fn, capture }); },
    removeEventListener(type, fn, capture = false) {
      listeners = listeners.filter(l => !(l.type === type && l.fn === fn && l.capture === capture));
    },
    // the root's capture listeners, then the field's own handler, unless one stopped it
    fire(type, event) {
      let stopped = false;
      event.stopImmediatePropagation = () => { stopped = true; };
      for (const l of [...listeners]) {
        if (l.type === type) l.fn(event);
        if (stopped) return;
      }
      event.target?.own?.[type]?.(event);
    },
    // capture listeners on the root run before the field's own handler
    change(field, own) { root.fire('change', { target: field }); own(field.value); },
  };
  return { root, Field, captures: type => listeners.some(l => l.type === type && l.capture) };
}

test('fields that save on change read the settled value, not the typed one', async () => {
  const { root, Field, captures } = liveFields();
  const { initLiveFormat } = await import(`../../static/js/liveformat.js?dom=${Date.now()}`);
  initLiveFormat(root);
  assert.equal(captures('change'), true);
  const amount = new Field({ inputmode: 'decimal' });
  amount.value = '42,50';
  let saved = '';
  root.change(amount, value => { saved = value; });
  assert.equal(saved, '42.50');
  assert.deepEqual(amount.heard, ['input']);
  // leaving the field afterwards has nothing left to tidy
  root.fire('focusout', { target: amount });
  assert.equal(amount.value, '42.50');
  assert.deepEqual(amount.heard, ['input']);

  const birthday = new Field({}, { k: 'birthday' });
  birthday.value = 'march 3';
  root.change(birthday, value => { saved = value; });
  root.fire('focusout', { target: birthday });
  assert.equal(saved, '--03-03');
  assert.equal(birthday.value, '--03-03');
});

test('enter on a value the field just settled saves it exactly once', async () => {
  const { root, Field } = liveFields();
  const { initLiveFormat } = await import(`../../static/js/liveformat.js?enter=${Date.now()}`);
  initLiveFormat(root);
  const tick = () => new Promise(resolve => setTimeout(resolve, 5));
  const enter = field => root.fire('keydown', { key: 'Enter', target: field });
  const native = field => root.fire('change', { target: field, isTrusted: true });
  const amount = () => {
    const field = new Field({ inputmode: 'decimal' });
    field.saved = [];
    field.own.change = () => field.saved.push(field.value);
    field.value = '9,75';
    return field;
  };

  // webkit counts the 9.75 set from script as committed and fires no change at all
  const webkit = amount();
  enter(webkit);
  await tick();
  assert.equal(webkit.value, '9.75');
  assert.deepEqual(webkit.saved, ['9.75']);
  root.fire('focusout', { target: webkit });
  assert.deepEqual(webkit.saved, ['9.75']);

  // chromium fires its own change in the same task: nothing extra
  const chromium = amount();
  enter(chromium);
  native(chromium);
  await tick();
  assert.deepEqual(chromium.saved, ['9.75']);
  assert.deepEqual(chromium.heard, ['input']);

  // the field's own enter handler cancelled the key: chromium sends its change on blur instead,
  // after the stand-in already saved. same value, so it's dropped
  const cancelled = amount();
  enter(cancelled);
  await tick();
  native(cancelled);
  assert.deepEqual(cancelled.saved, ['9.75']);
  // a real edit after that still saves
  cancelled.value = '10';
  native(cancelled);
  assert.deepEqual(cancelled.saved, ['9.75', '10']);

  // nothing to settle: the browser's own change is all there is
  const plain = amount();
  plain.value = '9.75';
  enter(plain);
  await tick();
  assert.deepEqual(plain.heard, []);
  assert.deepEqual(plain.saved, []);

  // the field left the page before the tick (enter re-rendered the list): no stray change
  const gone = amount();
  enter(gone);
  gone.isConnected = false;
  await tick();
  assert.deepEqual(gone.saved, []);
});

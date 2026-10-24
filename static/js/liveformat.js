// fields with a known shape format themselves as you type: phone numbers everywhere alles asks
// for one, card numbers and card expiry in secrets.
// 14373405952 -> +1 (437) 340-5952, +819012345678 -> +81 90 1234 5678. the digits are what count:
// matching (like photon's owner check) only looks at digits, so the spacing is just for reading.

// calling codes: 1 and 7 are one digit, these are two, everything else is three
const TWO = new Set(('20 27 30 31 32 33 34 36 39 40 41 43 44 45 46 47 48 49 51 52 53 54 55 56 57 58 '
  + '60 61 62 63 64 65 66 81 82 84 86 90 91 92 93 94 95 98').split(' '));

export const PHONE_FIELDS = [
  'input[type="tel"]', '[data-phone]', '#contact-phone',
  '.contact-scalars input[data-k="phone"]', '#vf-f-phone',
].join(',');
// a box that takes phone numbers or emails, one per line
export const PHONE_LINES = '#photon-owner, [data-phone-lines]';

function splitCode(digits) {
  if (!digits) return ['', ''];
  if (digits[0] === '1' || digits[0] === '7') return [digits[0], digits.slice(1)];
  const two = digits.slice(0, 2);
  if (TWO.has(two)) return [two, digits.slice(2)];
  return [digits.slice(0, 3), digits.slice(3)];
}

// cut `rest` into groups of these sizes; whatever is left goes in one last group
function groups(rest, sizes) {
  const out = [];
  let i = 0;
  for (const size of sizes) {
    if (i >= rest.length) break;
    out.push(rest.slice(i, i + size));
    i += size;
  }
  if (i < rest.length) out.push(rest.slice(i));
  return out.join(' ');
}

function nanp(rest) {
  if (!rest) return '';
  if (rest.length <= 3) return `(${rest}`;
  if (rest.length <= 6) return `(${rest.slice(0, 3)}) ${rest.slice(3)}`;
  return `(${rest.slice(0, 3)}) ${rest.slice(3, 6)}-${rest.slice(6, 10)}${rest.length > 10 ? ' ' + rest.slice(10) : ''}`;
}

function national(code, rest) {
  switch (code) {
    case '1': return nanp(rest);
    case '7': return groups(rest, [3, 3, 2, 2]);
    case '33': return groups(rest, [1, 2, 2, 2, 2]);
    case '44': return groups(rest, rest[0] === '7' ? [4, 6] : [2, 4, 4]);
    case '49': return groups(rest, [rest[0] === '1' ? 3 : 4, 8]);
    case '61': return groups(rest, rest[0] === '4' ? [3, 3, 3] : [1, 4, 4]);
    case '81': return groups(rest, /^[789]0/.test(rest) ? [2, 4, 4] : rest[0] === '3' || rest[0] === '6' ? [1, 4, 4] : [2, 3, 4]);
    case '82': return groups(rest, rest[0] === '1' ? [2, 4, 4] : [1, 4, 4]);
    case '86': return groups(rest, rest[0] === '1' ? [3, 4, 4] : [2, 4, 4]);
    case '91': return groups(rest, [5, 5]);
    case '852': case '853': case '65': return groups(rest, [4, 4]);
    case '886': return groups(rest, [3, 3, 3]);
    default: return groups(rest, rest.length > 7 ? [3, 3, 4] : [3, 4]);
  }
}

/** a phone number as it should read. leaves anything that isn't a phone number alone. */
export function formatPhone(value) {
  const raw = String(value ?? '');
  if (!raw.trim() || /[a-z@]/i.test(raw)) return raw;
  const plus = raw.trimStart().startsWith('+');
  const digits = raw.replace(/\D/g, '').slice(0, 15);
  if (!digits) return plus ? '+' : '';
  if (!plus) {
    // no + typed: a leading 1 means north america (14373405952); ten digits are a local
    // north american number; anything else stays as plain grouped digits
    if (digits[0] === '1') return digits.length > 1 ? `+1 ${nanp(digits.slice(1))}` : '+1';
    if (digits.length <= 10) return nanp(digits);
    return groups(digits, [3, 3, 4]);
  }
  const [code, rest] = splitCode(digits);
  return rest ? `+${code} ${national(code, rest)}` : `+${code}`;
}

// card number: groups of four (amex 4-6-5), up to 19 digits
export function formatCard(value) {
  const digits = String(value ?? '').replace(/\D/g, '').slice(0, 19);
  if (/^3[47]/.test(digits)) return groups(digits, [4, 6, 5]);
  return digits.replace(/(\d{4})(?=\d)/g, '$1 ');
}

// card expiry: MM/YY. a lone 2-9 becomes 0x, the slash comes in on its own
export function formatExpiry(value, deleting = false) {
  let digits = String(value ?? '').replace(/\D/g, '').slice(0, 4);
  if (/^[2-9]$/.test(digits)) digits = '0' + digits;
  if (digits.length < 2) return digits;
  if (digits.length === 2 && deleting) return digits;
  return `${digits.slice(0, 2)}/${digits.slice(2)}`;
}


/** just the digits with a +, for storing and comparing: +14373405952 */
export function phoneDigits(value) {
  const digits = String(value ?? '').replace(/\D/g, '');
  return digits ? `+${digits}` : '';
}

// money and other amounts: digits, one dot, a leading minus. no thousands separators, since
// the money parser doesn't take them. "1,234.50" -> 1234.50, "12,50" -> 12.50, "1,650" -> 1650.
// while typing, one comma stays as typed: "42," could still become 42,50 or 4,200, and
// dropping it there turned 42,50 into 4250
export function formatDecimal(value, typing = false) {
  let text = String(value ?? '').replace(/\s/g, '');
  const negative = text.startsWith('-');
  const commas = (text.match(/,/g) || []).length;
  if (text.includes('.') || commas > 1) text = text.replace(/,/g, '');
  else if (commas === 1 && !typing) {
    // three digits after it is a thousands comma (1,650), one or two is a decimal one (12,50).
    // a thousands group never starts with 0, so 0,125 is a decimal
    const thousands = /,\d{3}$/.test(text) && /^[1-9]/.test(text.replace(/[^\d,]/g, ''));
    text = thousands ? text.replace(',', '') : text.replace(',', '.');
  }
  text = text.replace(/[^\d.,]/g, '');
  const dot = text.indexOf('.');
  if (dot >= 0) text = text.slice(0, dot + 1) + text.slice(dot + 1).replace(/\./g, '');
  return (negative ? '-' : '') + text;
}

// dates typed by hand: 20261021 -> 2026-10-21, the dashes come in on their own
export function formatDate(value, deleting = false) {
  const digits = String(value ?? '').replace(/\D/g, '').slice(0, 8);
  let out = digits.slice(0, 4);
  if (digits.length > 4 || (digits.length === 4 && !deleting)) out += '-' + digits.slice(4, 6);
  if (digits.length > 6 || (digits.length === 6 && !deleting)) out += '-' + digits.slice(6, 8);
  return out;
}

// a birthday can be typed as words: "march 3", "3 mar", "march 3 1990". it ends as --03-03 (no
// year) or 1990-03-03, the forms contacts reads. digits still format like any date
const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];

// while typing: words stay as typed, and so does a day with its space ("3 ") since the month
// is on its way. a year-less --03-03 keeps its leading dashes. leaving the field runs this and
// then finishBirthday, so both have to leave --03-03 as it is. a stored month-day (03-03, the
// form contacts also accepts) stays too: run through the date dashes it became 0303-. so does
// a month-day on its way in: a lone "-" (the start of --) or "03-" while typing
const MONTH_DAY = /^(?:--)?(\d{1,2})-(\d{1,2})$/;
const MONTH_DAY_TYPING = /^-$|^\d{1,2}-$/;
export function formatBirthday(value, deleting = false) {
  const text = String(value ?? '');
  if (/[a-z]/i.test(text) || /^\d{1,2} $/.test(text) || MONTH_DAY.test(text)
    || (!deleting && MONTH_DAY_TYPING.test(text))) return text;
  if (!text.startsWith('--')) return formatDate(text, deleting);
  const digits = text.replace(/\D/g, '').slice(0, 4);
  if (digits.length > 2 || (digits.length === 2 && !deleting)) return `--${digits.slice(0, 2)}-${digits.slice(2)}`;
  return `--${digits}`;
}

export function finishBirthday(value) {
  const text = String(value ?? '').trim().toLowerCase().replace(/,/g, ' ').replace(/\s+/g, ' ');
  const pad = n => String(n).padStart(2, '0');
  // four digits typed as 0303 come out of the date dashes as 0303-: a month and a day, if they
  // can be one (1990- can't, so a typed year stays a year)
  const monthDay = MONTH_DAY.exec(text) || /^(\d{2})(\d{2})-?$/.exec(text);
  const [mm, dd] = monthDay ? [Number(monthDay[1]), Number(monthDay[2])] : [0, 0];
  if (mm >= 1 && mm <= 12 && dd >= 1 && dd <= 31) return `--${pad(mm)}-${pad(dd)}`;
  if (MONTH_DAY.test(text)) return text;
  if (!/[a-z]/.test(text)) return formatDate(text);
  let name = '', day = 0, year = '';
  const monthFirst = /^([a-z]+)\.? (\d{1,2})(?:st|nd|rd|th)?(?: (\d{4}))?$/.exec(text);
  // the space is optional: "3march" still reads as a day and a month
  const dayFirst = /^(\d{1,2})(?:st|nd|rd|th)? ?([a-z]+)\.?(?: (\d{4}))?$/.exec(text);
  if (monthFirst) [, name, day, year] = monthFirst;
  else if (dayFirst) [, day, name, year] = dayFirst;
  const month = MONTHS.indexOf(name.slice(0, 3)) + 1;
  day = Number(day);
  if (!month || day < 1 || day > 31) return String(value ?? '').trim();
  return year ? `${year}-${pad(month)}-${pad(day)}` : `--${pad(month)}-${pad(day)}`;
}

// clock times: 0930 -> 09:30, and a first digit over 2 means a single-digit hour (9 -> 09:)
export function formatTime(value, deleting = false) {
  let digits = String(value ?? '').replace(/\D/g, '').slice(0, 4);
  if (/^[3-9]/.test(digits)) digits = ('0' + digits).slice(0, 4);
  if (digits.length < 2 || (digits.length === 2 && deleting)) return digits;
  return `${digits.slice(0, 2)}:${digits.slice(2)}`;
}

export function formatHex(value) {
  const hex = String(value ?? '').replace(/[^0-9a-f]/gi, '').slice(0, 6);
  return String(value ?? '').trim() || hex ? `#${hex}` : '';
}

// a bare domain gets https://, a home address or localhost gets http:// (only when you leave)
export function finishUrl(value) {
  const text = String(value ?? '').trim();
  if (!text || /^[a-z][a-z0-9+.-]*:\/\//i.test(text) || /\s/.test(text) || !/[.:]|^localhost/i.test(text)) return text;
  const host = text.split(/[/:]/)[0];
  const local = /^localhost$|^\d{1,3}(\.\d{1,3}){3}$|\.local$|\.lan$/i.test(host);
  return `${local ? 'http' : 'https'}://${text}`;
}

// which kind of field this is, from its own markup, so new fields are covered without a list
const deleting = event => Boolean(event?.inputType?.startsWith('delete'));
const DIGIT = /\d/;
const KINDS = {
  phone: { keep: DIGIT, format: value => formatPhone(value) },
  card: { keep: DIGIT, format: value => formatCard(value) },
  expiry: { keep: DIGIT, format: (value, event) => formatExpiry(value, deleting(event)) },
  date: { keep: DIGIT, format: (value, event) => formatDate(value, deleting(event)) },
  birthday: { keep: /[\da-z]/i, format: (value, event) => formatBirthday(value, deleting(event)), finish: finishBirthday },
  time: { keep: DIGIT, format: (value, event) => formatTime(value, deleting(event)) },
  code: { keep: DIGIT, format: value => String(value).replace(/\D/g, '').slice(0, 6) },
  digits: { keep: DIGIT, format: value => String(value).replace(/\D/g, '') },
  decimal: { keep: /[\d.,-]/, format: value => formatDecimal(value, true), finish: value => formatDecimal(value) },
  hex: { keep: /[0-9a-f]/i, format: value => formatHex(value) },
  email: { keep: /\S/, format: value => String(value).replace(/\s/g, '') },
  url: { keep: /\S/, format: value => String(value).replace(/^\s+/, ''), finish: finishUrl },
};

function kindOf(el) {
  if (!(el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement)) return '';
  if (el.dataset.liveformat) return el.dataset.liveformat === 'off' ? '' : el.dataset.liveformat;
  if (el.matches(PHONE_LINES)) return 'phone-lines';
  if (el.matches(PHONE_FIELDS)) return 'phone';
  if (el.id === 'vf-f-number') return 'card';
  if (el.id === 'vf-f-expiry') return 'expiry';
  if (el instanceof HTMLTextAreaElement) return '';
  const type = (el.getAttribute('type') || 'text').toLowerCase();
  if (!['text', 'search', 'email', 'url', 'tel', ''].includes(type)) return '';
  const ph = el.getAttribute('placeholder') || '';
  const mode = (el.getAttribute('inputmode') || '').toLowerCase();
  if (el.dataset.k === 'birthday') return 'birthday';
  if (/YYYY-MM-DD|^\d{4}-\d{2}-\d{2}$/.test(ph)) return 'date';
  if (/^HH:MM$/i.test(ph) || /^\d{1,2}:\d{2}$/.test(ph)) return 'time';
  if (/\b6-digit code\b/i.test(ph) || el.autocomplete === 'one-time-code') return 'code';
  if (el.id === 's-accent-hex' || /#hex\b/i.test(ph)) return 'hex';
  if (type === 'email') return 'email';
  if (type === 'url' || mode === 'url') return 'url';
  if (mode === 'decimal') return 'decimal';
  if (mode === 'numeric') return 'digits';
  return '';
}

// keep the caret after the same kept character it was after, so formatting never jumps it
function caretAfter(text, count, keep) {
  if (count <= 0) {
    const first = [...text].findIndex(ch => keep.test(ch));
    return first < 0 ? text.length : first;
  }
  let seen = 0;
  for (let i = 0; i < text.length; i++) {
    if (keep.test(text[i]) && ++seen === count) return i + 1;
  }
  return text.length;
}

const countKept = (text, keep) => [...text].filter(ch => keep.test(ch)).length;

function setCaret(el, pos) {
  // email and some other types refuse selection ranges; the value is still right
  try {
    if (document.activeElement === el) el.setSelectionRange(pos, pos);
  } catch {}
}

function reformat(el, kind, event) {
  const multiline = kind === 'phone-lines';
  const spec = KINDS[multiline ? 'phone' : kind];
  const value = el.value;
  let caret = value.length;
  try { caret = el.selectionStart ?? value.length; } catch {}
  let start = 0;
  let end = value.length;
  if (multiline) {
    start = value.lastIndexOf('\n', caret - 1) + 1;
    const next = value.indexOf('\n', caret);
    end = next < 0 ? value.length : next;
  }
  let line = value.slice(start, end);
  let before = countKept(line.slice(0, caret - start), spec.keep);
  // backspacing over a space, bracket, dash or slash would just be put back, so take the
  // kept character before it instead
  if (event?.inputType === 'deleteContentBackward' && el._liveLast != null
    && countKept(el._liveLast, spec.keep) === countKept(value, spec.keep)) {
    const head = line.slice(0, caret - start);
    let at = -1;
    for (let i = head.length - 1; i >= 0; i--) if (spec.keep.test(head[i])) { at = i; break; }
    if (at >= 0) {
      line = line.slice(0, at) + line.slice(at + 1);
      before -= 1;
    }
  }
  const formatted = spec.format(line, event);
  if (formatted === value.slice(start, end)) {
    el._liveLast = value;
    return;
  }
  const next = value.slice(0, start) + formatted + value.slice(end);
  el.value = next;
  setCaret(el, start + caretAfter(formatted, before, spec.keep));
  el._liveLast = next;
}

// run a field's finish step now, so whatever reads it next gets the settled value.
// true when it changed the value
function settle(el) {
  const spec = KINDS[kindOf(el)];
  if (!spec?.finish) return false;
  const done = spec.finish(spec.format(el.value));
  if (done === el.value) return false;
  el.value = done;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  return true;
}

let wired = false;
/** format shaped fields live, app-wide. safe to call more than once. */
export function initLiveFormat(root = document) {
  if (wired) return;
  wired = true;
  root.addEventListener('focusin', event => {
    const el = event.target;
    const kind = kindOf(el);
    if (!kind) return;
    if (kind === 'phone' && !el.getAttribute('inputmode')) el.setAttribute('inputmode', 'tel');
    if (kind === 'phone' && !el.getAttribute('autocomplete')) el.setAttribute('autocomplete', 'tel');
    if (['card', 'expiry', 'date', 'time', 'code'].includes(kind) && !el.getAttribute('inputmode')) el.setAttribute('inputmode', 'numeric');
    el._liveLast = el.value;
    el._liveChange = null;
  });
  root.addEventListener('input', event => {
    if (event.isComposing) return;
    const kind = kindOf(event.target);
    if (kind) reformat(event.target, kind, event);
  });
  // enter submits before the field is left, so finish it first (capture runs before the
  // field's own enter handler)
  root.addEventListener('keydown', event => {
    if (event.key !== 'Enter' || event.isComposing) return;
    const el = event.target;
    if (!settle(el)) return;
    // webkit (safari, ipad) takes a value set from script as already committed, so neither this
    // enter nor the blur after it fires change, and fields that save on change never save.
    // chromium still fires its own in this same task, so only stand in when none came
    let heard = false;
    const hear = change => { if (change.target === el) heard = true; };
    root.addEventListener('change', hear, true);
    setTimeout(() => {
      root.removeEventListener('change', hear, true);
      if (heard || !el.isConnected) return;
      el._liveChange = el.value;
      el.dispatchEvent(new Event('change', { bubbles: true }));
    }, 0);
  }, true);
  // same for change: the browser fires it before focusout, and fields that save on change
  // (envelope amounts) would get 42,50 instead of 42.50
  root.addEventListener('change', event => {
    const el = event.target;
    // a field whose own enter handler cancels the key gets the stand-in above, and chromium
    // still fires its real change on blur. same value means it's the same commit: drop it
    if (event.isTrusted && el._liveChange != null) {
      const same = el._liveChange === el.value;
      el._liveChange = null;
      if (same) { event.stopImmediatePropagation(); return; }
    }
    settle(el);
  }, true);
  // pasted or filled-in values get tidied when you leave the field
  root.addEventListener('focusout', event => {
    const el = event.target;
    const kind = kindOf(el);
    if (!kind) return;
    const before = el.value;
    if (kind === 'phone-lines') el.value = before.split('\n').map(formatPhone).join('\n');
    else {
      const spec = KINDS[kind];
      el.value = spec.finish ? spec.finish(spec.format(before)) : spec.format(before);
    }
    // anything listening (drafts, dirty checks) hears about the tidy-up
    if (el.value !== before) el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

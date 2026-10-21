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

const SHAPES = [
  { selector: '#vf-f-number', format: value => formatCard(value) },
  { selector: '#vf-f-expiry', format: (value, event) => formatExpiry(value, event?.inputType?.startsWith('delete')) },
];

/** just the digits with a +, for storing and comparing: +14373405952 */
export function phoneDigits(value) {
  const digits = String(value ?? '').replace(/\D/g, '');
  return digits ? `+${digits}` : '';
}

// keep the caret after the same digit it was after, so formatting never jumps the cursor
function caretAfterDigits(text, count) {
  if (count <= 0) {
    const first = text.search(/\d/);
    return first < 0 ? text.length : first;
  }
  let seen = 0;
  for (let i = 0; i < text.length; i++) {
    if (/\d/.test(text[i]) && ++seen === count) return i + 1;
  }
  return text.length;
}

const countDigits = text => (text.match(/\d/g) || []).length;

function reformat(el, event) {
  const multiline = el.matches(PHONE_LINES);
  const value = el.value;
  const caret = el.selectionStart ?? value.length;
  let start = 0;
  let end = value.length;
  if (multiline) {
    start = value.lastIndexOf('\n', caret - 1) + 1;
    const next = value.indexOf('\n', caret);
    end = next < 0 ? value.length : next;
  }
  let line = value.slice(start, end);
  let before = countDigits(line.slice(0, caret - start));
  // backspacing over a space or bracket would just be put back, so take the digit before it
  if (event?.inputType === 'deleteContentBackward' && el._phoneLast != null
    && countDigits(el._phoneLast) === countDigits(value)) {
    const head = line.slice(0, caret - start);
    const at = head.search(/\d\D*$/);
    if (at >= 0) {
      line = line.slice(0, at) + line.slice(at + 1);
      before -= 1;
    }
  }
  const shape = SHAPES.find(item => el.matches(item.selector));
  const formatted = shape ? shape.format(line, event) : formatPhone(line);
  if (formatted === value.slice(start, end)) {
    el._phoneLast = value;
    return;
  }
  const next = value.slice(0, start) + formatted + value.slice(end);
  el.value = next;
  const pos = start + caretAfterDigits(formatted, before);
  if (document.activeElement === el) el.setSelectionRange(pos, pos);
  el._phoneLast = next;
}

function formatAllLines(el) {
  el.value = el.value.split('\n').map(formatPhone).join('\n');
}

let wired = false;
const ALL = () => [PHONE_FIELDS, PHONE_LINES, ...SHAPES.map(item => item.selector)].join(',');

/** format shaped fields live, app-wide. safe to call more than once. */
export function initLiveFormat(root = document) {
  if (wired) return;
  wired = true;
  root.addEventListener('focusin', event => {
    const el = event.target;
    if (!(el instanceof HTMLElement) || !el.matches(ALL())) return;
    if (SHAPES.some(item => el.matches(item.selector)) && !el.getAttribute('inputmode')) el.setAttribute('inputmode', 'numeric');
    if (el.matches(PHONE_FIELDS)) {
      if (!el.getAttribute('inputmode')) el.setAttribute('inputmode', 'tel');
      if (!el.getAttribute('autocomplete')) el.setAttribute('autocomplete', 'tel');
    }
    el._phoneLast = el.value;
  });
  root.addEventListener('input', event => {
    const el = event.target;
    if (!(el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement)) return;
    if (!el.matches(ALL())) return;
    if (event.isComposing) return;
    reformat(el, event);
  });
  // pasted or filled-in values get tidied when you leave the field
  root.addEventListener('focusout', event => {
    const el = event.target;
    if (!(el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement)) return;
    if (el.matches(PHONE_LINES)) formatAllLines(el);
    else if (el.matches(PHONE_FIELDS)) el.value = formatPhone(el.value);
    else {
      const shape = SHAPES.find(item => el.matches(item.selector));
      if (shape) el.value = shape.format(el.value);
    }
  });
}

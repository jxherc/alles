// Tools that run in the browser once the server has said which one fits: calculator keys,
// unit converter, world clock, timer and stopwatch, coin, dice and random numbers, color picker.
// Every value is set as text, never as markup. Each tool starts with what the owner asked for
// and nothing more; "timer" opens a stopped timer, "5 minute timer" starts one.
import { initCustomDropdown, populateDropdown, setDropdownValue } from './dropdown.js?v=212';
import { formatDate, formatDateParts, formatTime, resolvedTimeZone } from './i18n.js';
import { wireChoiceGroup } from './kokuen.js?v=1';

export const make = (tag, className = '', text = '') => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
};

export function button(label, { primary = false, className = '', onClick } = {}) {
  const node = make('button', `andromeda-tool-action${primary ? ' is-primary' : ''}${className ? ` ${className}` : ''}`, label);
  node.type = 'button';
  if (onClick) node.addEventListener('click', onClick);
  return node;
}

export function iconButton(label, path, onClick) {
  const node = make('button', 'andromeda-tool-icon');
  node.type = 'button';
  node.setAttribute('aria-label', label);
  node.title = label;
  node.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
  if (onClick) node.addEventListener('click', onClick);
  return node;
}

export const ICON_SWAP = '<path d="M7 7h11l-3-3"/><path d="M17 17H6l3 3"/>';
export const ICON_SPEAK = '<path d="M5 10v4h3l4 3.5v-11L8 10H5z"/><path d="M15.5 9a4 4 0 0 1 0 6"/><path d="M18 6.5a7.5 7.5 0 0 1 0 11"/>';
export const ICON_COPY = '<rect x="8.5" y="8.5" width="10" height="10" rx="1.5"/><path d="M15.5 8.5V6A1.5 1.5 0 0 0 14 4.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5"/>';

export function heading(text) {
  return make('h2', 'andromeda-tool-title', text);
}

// one-line entry with a bottom rule; Enter submits
export function field(label, { value = '', placeholder = '', inputmode = '', onSubmit, className = '' } = {}) {
  const wrap = make('label', `andromeda-tool-field${className ? ` ${className}` : ''}`);
  wrap.append(make('span', 'sr-only', label));
  const input = make('input');
  input.type = 'text';
  input.autocomplete = 'off';
  input.spellcheck = false;
  input.value = value;
  if (placeholder) input.placeholder = placeholder;
  if (inputmode) input.inputMode = inputmode;
  input.setAttribute('aria-label', label);
  if (onSubmit) input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); onSubmit(input.value.trim()); }
  });
  wrap.append(input);
  return { wrap, input };
}

// a small "look up another" form: field plus one action
export function lookup(label, actionLabel, onSubmit, { value = '', placeholder = '' } = {}) {
  const form = make('form', 'andromeda-tool-lookup');
  const { wrap, input } = field(label, { value, placeholder });
  const submit = button(actionLabel, { primary: true });
  submit.type = 'submit';
  form.append(wrap, submit);
  form.addEventListener('submit', event => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) { input.focus(); return; }
    onSubmit(text);
  });
  return { form, input, submit };
}

export function picker(label, options, value, onChange) {
  const node = make('div', 'custom-select andromeda-tool-picker');
  node.setAttribute('aria-label', label);
  populateDropdown(node, options, value);
  initCustomDropdown(node);
  node.addEventListener('change', () => onChange?.(node.value));
  return node;
}

export function choices(label, options, value, onPick) {
  const group = make('div', 'andromeda-tool-choices');
  group.setAttribute('role', 'radiogroup');
  group.setAttribute('aria-label', label);
  for (const option of options) {
    const choice = make('button', '', option.label);
    choice.type = 'button';
    choice.setAttribute('role', 'radio');
    choice.dataset.value = String(option.value);
    choice.setAttribute('aria-checked', String(String(option.value) === String(value)));
    choice.tabIndex = String(option.value) === String(value) ? 0 : -1;
    choice.addEventListener('click', () => {
      group.querySelectorAll('[role="radio"]').forEach(node => {
        const on = node === choice;
        node.setAttribute('aria-checked', String(on));
        node.tabIndex = on ? 0 : -1;
      });
      onPick(option.value);
    });
    group.append(choice);
  }
  // arrow keys move between choices once the group is in the page
  queueMicrotask(() => wireChoiceGroup(group));
  return group;
}

export const note = (text, className = '') => make('p', `andromeda-answer-source${className ? ` ${className}` : ''}`, text);
export const statusLine = (text = '') => {
  const node = make('p', 'andromeda-tool-status', text);
  node.setAttribute('role', 'status');
  node.setAttribute('aria-live', 'polite');
  return node;
};

export function speak(text, lang = 'en') {
  if (!('speechSynthesis' in window) || !text) return false;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = lang;
  window.speechSynthesis.speak(utterance);
  return true;
}

export const canSpeak = () => typeof window !== 'undefined' && 'speechSynthesis' in window;

export async function copyText(text, statusNode) {
  try {
    await navigator.clipboard.writeText(text);
    if (statusNode) statusNode.textContent = 'copied';
  } catch {
    if (statusNode) statusNode.textContent = 'copy is blocked in this browser';
  }
}

// unbiased integer in [min, max] from the browser's crypto source
export function randomInt(min, max) {
  const span = max - min + 1;
  if (span <= 1) return min;
  if (span > 2 ** 32) return min + Math.floor(Math.random() * span);
  const limit = Math.floor(2 ** 32 / span) * span;
  const buffer = new Uint32Array(1);
  do { crypto.getRandomValues(buffer); } while (buffer[0] >= limit);
  return min + (buffer[0] % span);
}

const plain = (value, digits = 10) => {
  if (!Number.isFinite(value)) return '';
  const rounded = Math.abs(value) >= 1e-4 || value === 0 ? Number(value.toPrecision(digits)) : value;
  return String(Math.abs(rounded) >= 1e15 || (Math.abs(rounded) < 1e-6 && rounded !== 0) ? rounded.toExponential(6) : rounded);
};

// ── calculator ──
const CALC_KEYS = [
  ['ac', 'clear'], ['(', '('], [')', ')'], ['÷', '÷'],
  ['√', 'sqrt('], ['^', '^'], ['%', '%'], ['×', '×'],
  ['7', '7'], ['8', '8'], ['9', '9'], ['−', '-'],
  ['4', '4'], ['5', '5'], ['6', '6'], ['+', '+'],
  ['1', '1'], ['2', '2'], ['3', '3'], ['=', 'equals'],
  ['0', '0'], ['.', '.'], ['π', 'pi'], ['⌫', 'back'],
];
const KEY_NAMES = { ac: 'clear', '÷': 'divide', '×': 'times', '−': 'minus', '+': 'plus', '=': 'equals', '⌫': 'delete', '√': 'square root', '^': 'power', '%': 'percent', 'π': 'pi', '(': 'open bracket', ')': 'close bracket', '.': 'point' };

export function calcTool(data, ctx) {
  const box = make('div', 'andromeda-calc');
  const screen = make('div', 'andromeda-calc-screen');
  const { wrap, input } = field('expression', { value: data.expression || '', placeholder: '0', inputmode: 'decimal', className: 'andromeda-calc-input' });
  const result = make('p', 'andromeda-calc-result', data.result ? `= ${data.result}` : '');
  result.setAttribute('role', 'status');
  result.setAttribute('aria-live', 'polite');
  screen.append(wrap, result);
  let seq = 0;
  const evaluate = async () => {
    const expression = input.value.trim();
    if (!expression) { result.textContent = ''; return; }
    const mine = ++seq;
    result.textContent = '…';
    try {
      const answer = await ctx.ask(expression, 'calc');
      if (mine !== seq) return;
      result.textContent = answer?.result ? `= ${answer.result}` : 'that isn\'t a sum i can work out';
      result.dataset.state = answer?.result ? 'ok' : 'error';
    } catch {
      if (mine === seq) { result.textContent = 'could not reach alles to work it out'; result.dataset.state = 'error'; }
    }
  };
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); void evaluate(); }
    if (event.key === 'Escape' && input.value) { event.preventDefault(); input.value = ''; result.textContent = ''; }
  });
  const keys = make('div', 'andromeda-calc-keys');
  keys.setAttribute('role', 'group');
  keys.setAttribute('aria-label', 'calculator keys');
  for (const [label, action] of CALC_KEYS) {
    const key = make('button', `andromeda-calc-key${action === 'equals' ? ' is-equals' : ''}`, label);
    key.type = 'button';
    key.setAttribute('aria-label', KEY_NAMES[label] || label);
    key.addEventListener('click', () => {
      if (action === 'clear') { input.value = ''; result.textContent = ''; }
      else if (action === 'back') input.value = input.value.slice(0, -1);
      else if (action === 'equals') void evaluate();
      else input.value += action;
      if (action !== 'equals') input.focus({ preventScroll: true });
    });
    keys.append(key);
  }
  box.append(screen, keys);
  return [heading('calculator'), box];
}

// ── units ──
const toKelvin = { c: v => v + 273.15, f: v => (v - 32) * 5 / 9 + 273.15, k: v => v };
const fromKelvin = { c: v => v - 273.15, f: v => (v - 273.15) * 9 / 5 + 32, k: v => v };

export function convertUnits(value, from, to) {
  if (from.kind === 'temperature') return fromKelvin[to.id](toKelvin[from.id](value));
  return value * from.factor / to.factor;
}

const TEMPERATURE_FORMULAS = {
  'c-f': '(°C × 9/5) + 32 = °F', 'f-c': '(°F − 32) × 5/9 = °C', 'c-k': '°C + 273.15 = K',
  'k-c': 'K − 273.15 = °C', 'f-k': '(°F − 32) × 5/9 + 273.15 = K', 'k-f': '(K − 273.15) × 9/5 + 32 = °F',
};

function formulaFor(from, to) {
  if (from.id === to.id) return '';
  if (from.kind === 'temperature') return `formula: ${TEMPERATURE_FORMULAS[`${from.id}-${to.id}`]}`;
  const ratio = from.factor / to.factor;
  return ratio >= 1 ? `formula: multiply the ${from.label} by ${plain(ratio, 7)}` : `formula: divide the ${from.label} by ${plain(1 / ratio, 7)}`;
}

export function unitsTool(data) {
  const all = data.units || [];
  let kind = data.unit_kind;
  let from = all.find(unit => unit.id === data.from_id);
  let to = all.find(unit => unit.id === data.to_id);
  const box = make('div', 'andromeda-convert');
  const kindPicker = picker('what to convert', (data.kinds || []).map(value => ({ value, label: value })), kind, value => {
    kind = value;
    const options = all.filter(unit => unit.kind === kind);
    from = options[0];
    to = options[1] || options[0];
    fill();
    left.input.value = '1';
    update('left');
  });
  const left = side('from');
  const right = side('to');
  const equals = make('span', 'andromeda-convert-equals', '=');
  equals.setAttribute('aria-hidden', 'true');
  const formula = note('');
  function side(which) {
    const row = make('div', 'andromeda-convert-side');
    const { wrap, input } = field(`amount in ${which} unit`, { inputmode: 'decimal' });
    const unit = make('div', 'custom-select andromeda-tool-picker');
    unit.setAttribute('aria-label', `${which} unit`);
    row.append(wrap, unit);
    return { row, input, unit };
  }
  function fill() {
    const options = all.filter(unit => unit.kind === kind).map(unit => ({ value: unit.id, label: unit.label }));
    populateDropdown(left.unit, options, from.id);
    populateDropdown(right.unit, options, to.id);
  }
  function update(source) {
    const [give, take, a, b] = source === 'left' ? [left, right, from, to] : [right, left, to, from];
    const value = Number(give.input.value.replace(/,/g, ''));
    if (give.input.value.trim() === '' || !Number.isFinite(value)) { take.input.value = ''; formula.textContent = ''; return; }
    take.input.value = plain(convertUnits(value, a, b), 7);
    formula.textContent = formulaFor(from, to);
  }
  initCustomDropdown(left.unit);
  initCustomDropdown(right.unit);
  fill();
  left.input.value = plain(Number(data.amount_value ?? 1));
  update('left');
  left.input.addEventListener('input', () => update('left'));
  right.input.addEventListener('input', () => update('right'));
  left.unit.addEventListener('change', () => { from = all.find(unit => unit.id === left.unit.value); update('left'); });
  right.unit.addEventListener('change', () => { to = all.find(unit => unit.id === right.unit.value); update('left'); });
  box.append(left.row, equals, right.row);
  return [heading('unit converter'), kindPicker, box, formula];
}

// ── clocks ──
const CITY_ALIASES = { nyc: 'America/New_York', 'new york': 'America/New_York', la: 'America/Los_Angeles', sf: 'America/Los_Angeles', 'san francisco': 'America/Los_Angeles', uk: 'Europe/London', beijing: 'Asia/Shanghai', 'hong kong': 'Asia/Hong_Kong', mumbai: 'Asia/Kolkata', delhi: 'Asia/Kolkata', india: 'Asia/Kolkata', japan: 'Asia/Tokyo', china: 'Asia/Shanghai', korea: 'Asia/Seoul', france: 'Europe/Paris', germany: 'Europe/Berlin', spain: 'Europe/Madrid', italy: 'Europe/Rome', australia: 'Australia/Sydney', utc: 'UTC', gmt: 'UTC', montreal: 'America/Toronto', ottawa: 'America/Toronto', boston: 'America/New_York', miami: 'America/New_York', seattle: 'America/Los_Angeles', shenzhen: 'Asia/Shanghai' };

export function zoneFor(place) {
  const wanted = String(place || '').trim().toLowerCase().replace(/\s+/g, ' ');
  if (!wanted) return '';
  if (CITY_ALIASES[wanted]) return CITY_ALIASES[wanted];
  let zones = [];
  try { zones = Intl.supportedValuesOf('timeZone'); } catch {}
  return zones.find(zone => zone.split('/').pop().replace(/_/g, ' ').toLowerCase() === wanted) || '';
}

const timeIn = (zone, seconds = false) => formatTime(new Date().toISOString(), { timeZone: zone, hour: 'numeric', minute: '2-digit', ...(seconds ? { second: '2-digit' } : {}) });
const dayIn = zone => formatDate(new Date().toISOString(), { timeZone: zone, weekday: 'short', month: 'short', day: 'numeric' });

// the wall clock in a zone as a plain utc number, so two zones can be subtracted
function wallClock(now, timeZone) {
  const fields = { numberingSystem: 'latn', hourCycle: 'h23', year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric' };
  const parts = Object.fromEntries(formatDateParts(now, timeZone ? { ...fields, timeZone } : fields).map(part => [part.type, Number(part.value)]));
  return Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour % 24, parts.minute);
}

function offsetHours(zone) {
  const now = new Date();
  return Math.round((wallClock(now, zone) - wallClock(now)) / 900000) / 4;
}

const relative = hours => (hours === 0 ? 'same time as you' : `${Math.abs(hours)} h ${hours > 0 ? 'ahead of' : 'behind'} you`);

const CLOCK_KEY = 'andromeda-clock-cities';
const savedCities = () => { try { return JSON.parse(localStorage.getItem(CLOCK_KEY) || '[]').filter(row => row?.zone); } catch { return []; } };
const saveCities = rows => { try { localStorage.setItem(CLOCK_KEY, JSON.stringify(rows.slice(0, 12))); } catch {} };

export function clockTool(_data, ctx) {
  const here = resolvedTimeZone();
  let cities = savedCities();
  const list = make('ul', 'andromeda-clock-list');
  const status = statusLine();
  const draw = () => {
    list.replaceChildren();
    const rows = [{ name: 'here', zone: here, fixed: true }, ...cities];
    rows.forEach((row, index) => {
      const item = make('li', 'andromeda-clock-row');
      const name = make('span', 'andromeda-clock-name', row.name);
      const meta = make('span', 'andromeda-clock-meta', `${dayIn(row.zone)} · ${row.fixed ? row.zone.replace(/_/g, ' ') : relative(offsetHours(row.zone))}`);
      const time = make('span', 'andromeda-clock-time', timeIn(row.zone));
      time.dataset.zone = row.zone;
      const label = make('span', 'andromeda-clock-label');
      label.append(name, meta);
      item.append(label, time);
      if (!row.fixed) item.append(button('remove', { className: 'andromeda-clock-remove', onClick: () => {
        cities = cities.filter((_city, at) => at !== index - 1);
        saveCities(cities);
        draw();
        status.textContent = `removed ${row.name}`;
        add.input.focus();
      } }));
      list.append(item);
    });
  };
  const add = lookup('add a city', 'add', name => {
    const zone = zoneFor(name);
    if (!zone) { status.textContent = `no time zone found for "${name}"; try a bigger city nearby`; return; }
    if (!cities.some(row => row.zone === zone && row.name === name.toLowerCase())) cities.push({ name: name.toLowerCase(), zone });
    saveCities(cities);
    add.input.value = '';
    status.textContent = '';
    draw();
  }, { placeholder: 'add a city, like tokyo' });
  draw();
  const tick = setInterval(() => list.querySelectorAll('.andromeda-clock-time').forEach(node => { node.textContent = timeIn(node.dataset.zone); }), 1000);
  ctx.onStop(() => clearInterval(tick));
  return [heading('world clock'), list, add.form, status];
}

export function timeTool(data, ctx) {
  const big = make('p', 'andromeda-answer-value', timeIn(data.zone));
  const parts = [heading(`time in ${data.place}`), big];
  const day = note(`${dayIn(data.zone)} · ${data.zone.replace(/_/g, ' ')} (UTC${data.offset.slice(0, 3)}:${data.offset.slice(3)}) · ${relative(offsetHours(data.zone))}`);
  parts.push(day);
  let other = null;
  if (data.other_zone) {
    other = make('p', 'andromeda-answer-detail');
    const hours = data.difference_hours;
    const describe = hours === 0 ? `${data.other_place} has the same time as ${data.place}` : `${data.other_place} is ${Math.abs(hours)} hours ${hours > 0 ? 'ahead of' : 'behind'} ${data.place}`;
    other.textContent = `${describe} · ${timeIn(data.other_zone)} there now`;
    parts.push(other);
  }
  const tick = setInterval(() => { big.textContent = timeIn(data.zone); }, 1000);
  ctx.onStop(() => clearInterval(tick));
  return parts;
}

// ── timer and stopwatch ──
const pad = value => String(value).padStart(2, '0');
function clockText(ms, hundredths = false) {
  const total = Math.max(0, ms);
  const hours = Math.floor(total / 3600000);
  const minutes = Math.floor((total % 3600000) / 60000);
  const seconds = Math.floor((total % 60000) / 1000);
  const tail = hundredths ? `.${pad(Math.floor((total % 1000) / 10))}` : '';
  return `${hours ? `${hours}:` : ''}${pad(minutes)}:${pad(seconds)}${tail}`;
}

export function parseDuration(text) {
  const value = String(text || '').trim().toLowerCase();
  if (!value) return 0;
  if (/^\d+(:\d{1,2}){0,2}$/.test(value)) {
    const parts = value.split(':').map(Number);
    if (parts.length === 1) return parts[0] * 60000;
    return parts.reduce((total, part) => total * 60 + part, 0) * 1000;
  }
  let total = 0;
  const pattern = /(\d+(?:\.\d+)?)\s*(h|hr|hrs|hours?|m|min|mins|minutes?|s|sec|secs|seconds?)\b/g;
  let match;
  let found = false;
  while ((match = pattern.exec(value))) {
    found = true;
    const unit = match[2][0];
    total += Number(match[1]) * (unit === 'h' ? 3600000 : unit === 'm' ? 60000 : 1000);
  }
  return found ? Math.round(total) : 0;
}

function beep() {
  try {
    const audio = new (window.AudioContext || window.webkitAudioContext)();
    [0, 0.35, 0.7].forEach(at => {
      const tone = audio.createOscillator();
      const gain = audio.createGain();
      tone.frequency.value = 880;
      gain.gain.setValueAtTime(0.0001, audio.currentTime + at);
      gain.gain.exponentialRampToValueAtTime(0.2, audio.currentTime + at + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + at + 0.25);
      tone.connect(gain).connect(audio.destination);
      tone.start(audio.currentTime + at);
      tone.stop(audio.currentTime + at + 0.3);
    });
    setTimeout(() => audio.close(), 1500);
  } catch {}
}

export function timerTool(data, ctx) {
  const host = make('div', 'andromeda-timer');
  let mode = data.mode === 'stopwatch' ? 'stopwatch' : 'timer';
  let stopTick = () => {};
  const body = make('div', 'andromeda-timer-body');
  const switcher = choices('timer or stopwatch', [{ value: 'timer', label: 'timer' }, { value: 'stopwatch', label: 'stopwatch' }], mode, value => {
    mode = value;
    draw(false);
  });
  const draw = autostart => {
    stopTick();
    body.replaceChildren(...(mode === 'timer' ? timerBody(autostart) : stopwatchBody(autostart)));
  };
  function timerBody(autostart) {
    let length = (data.seconds || 300) * 1000;
    let left = length;
    let endsAt = 0;
    let tick = 0;
    const display = field('timer length, like 5:00 or 90s', { value: clockText(left), inputmode: 'numeric', className: 'andromeda-timer-display' });
    const status = statusLine();
    const start = button('start', { primary: true });
    const reset = button('reset');
    const more = button('+1 min');
    const render = () => {
      display.input.value = clockText(endsAt ? endsAt - Date.now() : left);
      start.textContent = endsAt ? 'pause' : left < length && left > 0 ? 'resume' : 'start';
      display.input.readOnly = Boolean(endsAt);
    };
    const finish = () => {
      clearInterval(tick);
      endsAt = 0;
      left = 0;
      render();
      status.textContent = 'time\'s up';
      host.dataset.state = 'done';
      beep();
    };
    const run = () => {
      if (endsAt) { left = endsAt - Date.now(); endsAt = 0; clearInterval(tick); status.textContent = 'paused'; render(); return; }
      if (left <= 0 || !display.input.readOnly) {
        const typed = parseDuration(display.input.value);
        if (left <= 0 || (typed && typed !== left)) { length = typed || length; left = length; }
      }
      if (left <= 0) { status.textContent = 'set a length first, like 5:00'; display.input.focus(); return; }
      host.dataset.state = 'running';
      status.textContent = '';
      endsAt = Date.now() + left;
      clearInterval(tick);
      tick = setInterval(() => { if (Date.now() >= endsAt) finish(); else render(); }, 250);
      render();
    };
    start.addEventListener('click', run);
    reset.addEventListener('click', () => { clearInterval(tick); endsAt = 0; left = length; host.dataset.state = ''; status.textContent = ''; render(); });
    more.addEventListener('click', () => {
      if (endsAt) endsAt += 60000; else { left += 60000; length = Math.max(length, left); }
      render();
    });
    display.input.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); run(); } });
    display.input.addEventListener('change', () => {
      const typed = parseDuration(display.input.value);
      if (typed) { length = typed; left = typed; status.textContent = ''; } else status.textContent = 'write a length like 5:00, 90s or 1h 30m';
      render();
    });
    stopTick = () => clearInterval(tick);
    ctx.onStop(() => clearInterval(tick));
    const actions = make('div', 'andromeda-tool-actions');
    actions.append(start, more, reset);
    if (autostart) queueMicrotask(run);
    return [display.wrap, actions, status];
  }
  function stopwatchBody(autostart) {
    let since = 0;
    let held = 0;
    let tick = 0;
    const laps = make('ol', 'andromeda-laps');
    const display = make('p', 'andromeda-timer-readout', clockText(0, true));
    display.setAttribute('aria-live', 'off');
    const start = button('start', { primary: true });
    const lap = button('lap');
    const reset = button('reset');
    const elapsed = () => held + (since ? Date.now() - since : 0);
    const render = () => {
      display.textContent = clockText(elapsed(), true);
      start.textContent = since ? 'pause' : held ? 'resume' : 'start';
      lap.disabled = !since;
    };
    start.addEventListener('click', () => {
      if (since) { held = elapsed(); since = 0; clearInterval(tick); }
      else { since = Date.now(); tick = setInterval(render, 50); }
      render();
    });
    lap.addEventListener('click', () => {
      const item = make('li', '', clockText(elapsed(), true));
      laps.prepend(item);
    });
    reset.addEventListener('click', () => { clearInterval(tick); since = 0; held = 0; laps.replaceChildren(); render(); });
    stopTick = () => clearInterval(tick);
    ctx.onStop(() => clearInterval(tick));
    render();
    if (autostart) queueMicrotask(() => start.click());
    const actions = make('div', 'andromeda-tool-actions');
    actions.append(start, lap, reset);
    return [display, actions, laps];
  }
  draw(Boolean(data.start));
  host.append(switcher, body);
  return [host];
}

// ── coin, dice, numbers ──
export function randomTool(data) {
  if (data.mode === 'coin') {
    const face = make('p', 'andromeda-answer-value');
    face.setAttribute('role', 'status');
    face.setAttribute('aria-live', 'polite');
    let flips = 0;
    const flip = () => { flips += 1; face.textContent = randomInt(0, 1) ? 'heads' : 'tails'; count.textContent = flips > 1 ? `flip ${flips}` : ''; };
    const count = note('');
    const again = button('flip again', { primary: true, onClick: flip });
    const actions = make('div', 'andromeda-tool-actions');
    actions.append(again);
    flip();
    return [heading('coin flip'), face, actions, count];
  }
  if (data.mode === 'dice') {
    let count = data.count || 1;
    let sides = data.sides || 6;
    const faces = make('p', 'andromeda-answer-value andromeda-dice');
    faces.setAttribute('role', 'status');
    faces.setAttribute('aria-live', 'polite');
    const total = note('');
    const roll = () => {
      const values = Array.from({ length: count }, () => randomInt(1, sides));
      faces.textContent = values.join('  ');
      faces.setAttribute('aria-label', `rolled ${values.join(', ')}`);
      total.textContent = count > 1 ? `total ${values.reduce((sum, value) => sum + value, 0)}` : `one d${sides}`;
    };
    const countLine = make('div', 'andromeda-tool-stepper');
    countLine.setAttribute('role', 'group');
    countLine.setAttribute('aria-label', 'how many dice');
    const countText = make('span', 'andromeda-tool-stepper-value', `${count} ${count === 1 ? 'die' : 'dice'}`);
    countText.setAttribute('aria-live', 'polite');
    const less = make('button', '', '−');
    less.type = 'button';
    less.setAttribute('aria-label', 'one die fewer');
    less.addEventListener('click', () => { count = Math.max(1, count - 1); sync(); });
    const moreDice = make('button', '', '+');
    moreDice.type = 'button';
    moreDice.setAttribute('aria-label', 'one die more');
    moreDice.addEventListener('click', () => { count = Math.min(10, count + 1); sync(); });
    const sync = () => { countText.textContent = `${count} ${count === 1 ? 'die' : 'dice'}`; less.disabled = count <= 1; moreDice.disabled = count >= 10; };
    countLine.append(less, countText, moreDice);
    const sideChoices = choices('sides on each die', [4, 6, 8, 10, 12, 20].map(value => ({ value, label: `d${value}` })), sides, value => { sides = Number(value); });
    const actions = make('div', 'andromeda-tool-actions');
    actions.append(button('roll', { primary: true, onClick: roll }));
    sync();
    if (data.roll) roll();
    else { faces.textContent = '–'; faces.setAttribute('aria-label', 'not rolled yet'); total.textContent = 'pick the dice, then roll'; }
    const setup = make('div', 'andromeda-tool-row');
    setup.append(sideChoices, countLine);
    return [heading('dice'), faces, total, setup, actions];
  }
  const low = field('lowest number', { value: String(data.min ?? 1), inputmode: 'numeric', className: 'is-short' });
  const high = field('highest number', { value: String(data.max ?? 10), inputmode: 'numeric', className: 'is-short' });
  const range = make('div', 'andromeda-tool-row');
  range.append(make('span', 'andromeda-tool-count', 'from'), low.wrap, make('span', 'andromeda-tool-count', 'to'), high.wrap);
  const result = make('p', 'andromeda-answer-value');
  result.setAttribute('role', 'status');
  result.setAttribute('aria-live', 'polite');
  const status = statusLine();
  const generate = () => {
    let a = Number(low.input.value);
    let b = Number(high.input.value);
    if (!Number.isInteger(a) || !Number.isInteger(b)) { status.textContent = 'use whole numbers for both ends'; return; }
    if (a > b) [a, b] = [b, a];
    status.textContent = '';
    result.textContent = String(randomInt(a, b));
  };
  for (const input of [low.input, high.input]) input.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); generate(); } });
  const actions = make('div', 'andromeda-tool-actions');
  actions.append(button('generate', { primary: true, onClick: generate }));
  if (data.roll) generate(); else result.textContent = '–';
  return [heading('random number'), result, range, actions, status];
}

// ── color ──
export function hexToRgb(hex) {
  const value = String(hex || '').replace('#', '').trim();
  const full = value.length === 3 ? [...value].map(ch => ch + ch).join('') : value;
  if (!/^[0-9a-f]{6}$/i.test(full)) return null;
  return [0, 2, 4].map(at => parseInt(full.slice(at, at + 2), 16));
}

export function rgbToHex(rgb) {
  return `#${rgb.map(value => Math.round(value).toString(16).padStart(2, '0')).join('')}`;
}

export function rgbToHsl([r, g, b]) {
  const [rn, gn, bn] = [r / 255, g / 255, b / 255];
  const max = Math.max(rn, gn, bn);
  const min = Math.min(rn, gn, bn);
  const light = (max + min) / 2;
  if (max === min) return [0, 0, Math.round(light * 100)];
  const delta = max - min;
  const sat = light > 0.5 ? delta / (2 - max - min) : delta / (max + min);
  const hue = max === rn ? (gn - bn) / delta + (gn < bn ? 6 : 0) : max === gn ? (bn - rn) / delta + 2 : (rn - gn) / delta + 4;
  return [Math.round(hue * 60), Math.round(sat * 100), Math.round(light * 100)];
}

export function hslToRgb([h, s, l]) {
  const sat = s / 100;
  const light = l / 100;
  const k = n => (n + h / 30) % 12;
  const a = sat * Math.min(light, 1 - light);
  const f = n => light - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [f(0), f(8), f(4)].map(value => Math.round(value * 255));
}

function luminance(rgb) {
  const [r, g, b] = rgb.map(value => {
    const channel = value / 255;
    return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export const contrast = (one, two) => {
  const [a, b] = [luminance(one), luminance(two)].sort((x, y) => y - x);
  return (a + 0.05) / (b + 0.05);
};

function slider(label, max, value, onInput) {
  const track = make('div', 'andromeda-slider');
  track.setAttribute('role', 'slider');
  track.setAttribute('aria-label', label);
  track.setAttribute('aria-valuemin', '0');
  track.setAttribute('aria-valuemax', String(max));
  track.tabIndex = 0;
  const rail = make('div', 'andromeda-slider-rail');
  const knob = make('div', 'andromeda-slider-knob');
  rail.append(knob);
  track.append(rail);
  let current = value;
  const set = (next, fire = true) => {
    current = Math.max(0, Math.min(max, Math.round(next)));
    knob.style.left = `${(current / max) * 100}%`;
    track.setAttribute('aria-valuenow', String(current));
    if (fire) onInput(current);
  };
  const fromPointer = event => {
    const box = rail.getBoundingClientRect();
    set(((event.clientX - box.left) / box.width) * max);
  };
  track.addEventListener('pointerdown', event => {
    track.setPointerCapture(event.pointerId);
    fromPointer(event);
    const move = moveEvent => fromPointer(moveEvent);
    const up = () => { track.removeEventListener('pointermove', move); track.removeEventListener('pointerup', up); };
    track.addEventListener('pointermove', move);
    track.addEventListener('pointerup', up);
  });
  track.addEventListener('keydown', event => {
    const steps = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1, PageUp: 10, PageDown: -10 };
    if (event.key in steps) { event.preventDefault(); set(current + steps[event.key]); }
    if (event.key === 'Home') { event.preventDefault(); set(0); }
    if (event.key === 'End') { event.preventDefault(); set(max); }
  });
  set(value, false);
  return { track, set, rail };
}

export function colorTool(data) {
  let rgb = hexToRgb(data.value) || [128, 128, 128];
  let hsl = rgbToHsl(rgb);
  const swatch = make('div', 'andromeda-swatch');
  swatch.setAttribute('role', 'img');
  const hexField = field('hex color', { className: 'andromeda-color-hex' });
  const status = statusLine();
  const values = make('dl', 'andromeda-color-values');
  const hue = slider('hue', 360, hsl[0], value => { hsl = [value, hsl[1], hsl[2]]; rgb = hslToRgb(hsl); draw('hue'); });
  const sat = slider('saturation', 100, hsl[1], value => { hsl = [hsl[0], value, hsl[2]]; rgb = hslToRgb(hsl); draw('sat'); });
  const light = slider('lightness', 100, hsl[2], value => { hsl = [hsl[0], hsl[1], value]; rgb = hslToRgb(hsl); draw('light'); });
  hue.rail.classList.add('is-hue');
  const sliders = make('div', 'andromeda-color-sliders');
  for (const [name, part] of [['hue', hue], ['saturation', sat], ['lightness', light]]) {
    const row = make('div', 'andromeda-color-slider');
    row.append(make('span', 'andromeda-tool-count', name), part.track);
    sliders.append(row);
  }
  const draw = from => {
    const hex = rgbToHex(rgb);
    swatch.style.background = hex;
    swatch.setAttribute('aria-label', `color ${hex}`);
    if (from !== 'hex') hexField.input.value = hex;
    if (from !== 'hue') hue.set(hsl[0], false);
    if (from !== 'sat') sat.set(hsl[1], false);
    if (from !== 'light') light.set(hsl[2], false);
    sat.rail.style.background = `linear-gradient(90deg, hsl(${hsl[0]} 0% ${hsl[2]}%), hsl(${hsl[0]} 100% ${hsl[2]}%))`;
    light.rail.style.background = `linear-gradient(90deg, #000, hsl(${hsl[0]} ${hsl[1]}% 50%), #fff)`;
    const white = contrast(rgb, [255, 255, 255]);
    const black = contrast(rgb, [0, 0, 0]);
    values.replaceChildren();
    for (const [term, value] of [
      ['hex', hex],
      ['rgb', `rgb(${rgb.join(', ')})`],
      ['hsl', `hsl(${hsl[0]}, ${hsl[1]}%, ${hsl[2]}%)`],
      ['text on it', `${white >= black ? 'white' : 'black'} reads best (${Math.max(white, black).toFixed(1)}:1)`],
    ]) {
      const copy = term === 'text on it' ? null : button('copy', { className: 'andromeda-color-copy', onClick: () => copyText(value, status) });
      if (copy) copy.setAttribute('aria-label', `copy ${term} ${value}`);
      const dd = make('dd', '', value);
      if (copy) dd.append(copy);
      values.append(make('dt', '', term), dd);
    }
  };
  hexField.input.addEventListener('input', () => {
    const next = hexToRgb(hexField.input.value);
    if (!next) return;
    rgb = next;
    hsl = rgbToHsl(rgb);
    status.textContent = '';
    draw('hex');
  });
  hexField.input.addEventListener('change', () => {
    if (!hexToRgb(hexField.input.value)) { status.textContent = 'write a hex color like #3a7bd5'; hexField.input.value = rgbToHex(rgb); }
  });
  draw();
  const top = make('div', 'andromeda-color-top');
  const side = make('div', 'andromeda-color-side');
  side.append(hexField.wrap, sliders);
  top.append(swatch, side);
  return [heading('color picker'), top, values, status];
}

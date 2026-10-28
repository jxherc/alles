// Small offline tools in Andromeda's answer card: tip, percentages, bmi, loans, number bases, roman
// numerals, unix time, passwords and uuids, encoders, a text counter, the moon and number facts.
// Each opens empty when asked for by name and answers at once when the query carries its input.
// The maths lives in andromeda_calcs.js; every value here is set as text, never as markup.
import { formatDate, formatDateTime, formatNumber, formatRelativeTime, resolvedTimeZone, t } from './i18n.js';
import { wireAutosizeTextarea } from './text_entry.js?v=1';
import { button, choices, copyText, field, heading, make, randomInt, slider, statusLine } from './andromeda_tools.js';
import * as calc from './andromeda_calcs.js';

const parse = value => {
  const text = String(value ?? '').replace(/,/g, '').trim();
  return text && Number.isFinite(Number(text)) ? Number(text) : NaN;
};
const plain = (value, digits = 2) => formatNumber(value, { maximumFractionDigits: digits });
const money = value => formatNumber(value, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fill = value => (value == null ? '' : String(value));

// a field with its name written above it, so a form of several reads at a glance
function entry(label, value, onInput, { text = false, placeholder = '' } = {}) {
  const box = field(label, { value: fill(value), inputmode: text ? '' : 'decimal', placeholder });
  box.input.addEventListener('input', onInput);
  const wrap = make('div', 'andromeda-tool-labeled');
  const caption = make('span', 'andromeda-tool-count', label);
  caption.setAttribute('aria-hidden', 'true');
  wrap.append(caption, box.wrap);
  const relabel = next => {
    caption.textContent = next;
    box.input.setAttribute('aria-label', next);
    box.wrap.firstChild.textContent = next;
  };
  return { wrap, input: box.input, relabel };
}

const form = (...entries) => {
  const row = make('div', 'andromeda-tool-form');
  row.append(...entries.map(item => item.wrap));
  return row;
};

// the big answer with its name above; blank until there is something to say
function answer(label = '', { live = true } = {}) {
  const wrap = make('div', 'andromeda-answer-main');
  const name = make('p', 'andromeda-answer-label', label);
  const value = make('p', 'andromeda-answer-value', '–');
  if (live) { value.setAttribute('role', 'status'); value.setAttribute('aria-live', 'polite'); }
  name.hidden = !label;
  wrap.append(name, value);
  const show = (main, sub = '') => {
    value.textContent = main;
    name.textContent = sub;
    name.hidden = !sub;
  };
  return { wrap, name, value, show };
}

// term and value rows; a row with copy gets a quiet copy action
function valueList(status) {
  const dl = make('dl', 'andromeda-tool-values');
  dl.hidden = true;
  const set = rows => {
    dl.replaceChildren();
    dl.hidden = !rows.length;
    for (const [term, value, copy] of rows) {
      const dd = make('dd');
      dd.append(make('span', 'andromeda-tool-value-text', value));
      if (copy) {
        const action = button(t('common.copy'), { className: 'andromeda-tool-copy', onClick: () => copyText(value, status) });
        action.setAttribute('aria-label', t('andromeda.tool_copy_value', { term, value }));
        dd.append(action);
      }
      dl.append(make('dt', '', term), dd);
    }
  };
  return { dl, set };
}

function toggle(label, on, onChange) {
  const row = make('label', 'andromeda-tool-toggle');
  const sw = make('button', 'andromeda-switch');
  sw.type = 'button';
  sw.setAttribute('role', 'switch');
  sw.setAttribute('aria-checked', String(on));
  sw.setAttribute('aria-label', label);
  sw.append(make('span'));
  sw.addEventListener('click', () => {
    const next = sw.getAttribute('aria-checked') !== 'true';
    sw.setAttribute('aria-checked', String(next));
    onChange(next);
  });
  row.append(make('span', 'andromeda-tool-count', label), sw);
  return row;
}

function textBox(label, value, onInput) {
  const wrap = make('label', 'andromeda-tool-text');
  wrap.append(make('span', 'sr-only', label));
  const input = make('textarea');
  input.rows = 1;
  input.maxLength = 100000;
  input.placeholder = label;
  input.dataset.kokuenEntry = 'autogrow';
  input.value = value || '';
  input.addEventListener('input', onInput);
  wrap.append(input);
  queueMicrotask(() => wireAutosizeTextarea(input));
  return { wrap, input };
}

const row = (...nodes) => {
  const line = make('div', 'andromeda-tool-row');
  line.append(...nodes);
  return line;
};
const count = text => make('span', 'andromeda-tool-count', text);

// ── tip ──
export function tipTool(data) {
  const bill = entry(t('andromeda.tool_bill'), data.bill, () => update());
  const percent = entry(t('andromeda.tool_tip_percent'), data.percent ?? 18, () => update());
  const people = entry(t('andromeda.tool_people'), data.people ?? 1, () => update());
  const main = answer();
  const list = valueList();
  function update() {
    const out = calc.tipSplit(parse(bill.input.value), parse(percent.input.value), people.input.value.trim() ? parse(people.input.value) : 1);
    if (!out) { main.show('–'); list.set([]); return; }
    const split = out.people > 1;
    main.show(money(split ? out.each : out.total), split ? t('andromeda.tool_each_pays') : t('andromeda.tool_total_label'));
    list.set(split
      ? [[t('andromeda.tool_tip_amount'), money(out.tip)], [t('andromeda.tool_total_label'), money(out.total)], [t('andromeda.tool_tip_each'), money(out.tipEach)]]
      : [[t('andromeda.tool_tip_amount'), money(out.tip)]]);
  }
  update();
  return [heading(t('andromeda.tool_tip')), main.wrap, form(bill, percent, people), list.dl];
}

// ── percentages ──
const PERCENT_FIELDS = {
  of: ['andromeda.tool_percent_word', 'andromeda.tool_of_word'],
  is: ['andromeda.tool_number', 'andromeda.tool_out_of'],
  change: ['andromeda.tool_from', 'andromeda.tool_to'],
  off: ['andromeda.tool_percent_off', 'andromeda.tool_price'],
};

export function percentTool(data) {
  let mode = data.mode in PERCENT_FIELDS ? data.mode : 'of';
  const first = entry('', data.a, () => update());
  const second = entry('', data.b, () => update());
  const main = answer();
  const list = valueList();
  const modes = choices(t('andromeda.tool_percent_mode'), [
    { value: 'of', label: t('andromeda.tool_pct_of') },
    { value: 'is', label: t('andromeda.tool_pct_is') },
    { value: 'change', label: t('andromeda.tool_pct_change') },
    { value: 'off', label: t('andromeda.tool_pct_off') },
  ], mode, value => { mode = value; update(); });
  function update() {
    first.relabel(t(PERCENT_FIELDS[mode][0]));
    second.relabel(t(PERCENT_FIELDS[mode][1]));
    const [a, b] = [parse(first.input.value), parse(second.input.value)];
    const out = calc.percentage(mode, a, b);
    if (!out) { main.show('–'); list.set([]); return; }
    const sub = t(`andromeda.tool_pct_label_${mode}`, { a: plain(a, 4), b: plain(b, 4) });
    if (mode === 'of') main.show(plain(out.value, 4), sub);
    else if (mode === 'is') main.show(`${plain(out.value, 4)}%`, sub);
    else if (mode === 'change') main.show(`${out.value > 0 ? '+' : ''}${plain(out.value, 2)}%`, sub);
    else main.show(plain(out.value, 2), sub);
    list.set(mode === 'change' ? [[out.diff >= 0 ? t('andromeda.tool_pct_up') : t('andromeda.tool_pct_down'), plain(Math.abs(out.diff), 4)]]
      : mode === 'off' ? [[t('andromeda.tool_you_save'), plain(out.saved, 2)]] : []);
  }
  update();
  return [heading(t('andromeda.tool_percentage')), main.wrap, modes, form(first, second), list.dl];
}

// ── bmi ──
export function bmiTool(data) {
  let unit = data.unit === 'imperial' ? 'imperial' : 'metric';
  const metric = unit === 'metric';
  const weight = entry('', data.weight, () => update());
  const centimetres = entry('', metric ? data.height : '', () => update());
  const feet = entry('', metric || data.height == null ? '' : Math.floor(data.height / 12), () => update());
  const inches = entry('', metric || data.height == null ? '' : Math.round((data.height % 12) * 10) / 10, () => update());
  const main = answer();
  const detail = make('p', 'andromeda-answer-detail');
  detail.hidden = true;
  const units = choices(t('andromeda.tool_units'), [{ value: 'metric', label: t('andromeda.tool_metric') }, { value: 'imperial', label: t('andromeda.tool_imperial') }], unit, value => {
    const [kg, cm] = readings();
    unit = value;
    const next = unit === 'imperial';
    weight.input.value = Number.isFinite(kg) ? plain(next ? kg / 0.45359237 : kg, 1).replace(/,/g, '') : '';
    centimetres.input.value = Number.isFinite(cm) && !next ? plain(cm, 1).replace(/,/g, '') : '';
    const total = Number.isFinite(cm) ? cm / 2.54 : NaN;
    feet.input.value = Number.isFinite(total) && next ? String(Math.floor(total / 12)) : '';
    inches.input.value = Number.isFinite(total) && next ? String(Math.round((total % 12) * 10) / 10) : '';
    update();
  });
  function readings() {
    if (unit === 'metric') return [parse(weight.input.value), parse(centimetres.input.value)];
    const [ft, inch] = [parse(feet.input.value || '0'), parse(inches.input.value || '0')];
    return [parse(weight.input.value) * 0.45359237, (ft * 12 + inch) * 2.54];
  }
  function update() {
    const imperial = unit === 'imperial';
    weight.relabel(`${t('andromeda.tool_weight')} (${imperial ? 'lb' : 'kg'})`);
    centimetres.relabel(`${t('andromeda.tool_height')} (cm)`);
    feet.relabel(`${t('andromeda.tool_height')} (ft)`);
    inches.relabel(`${t('andromeda.tool_height')} (in)`);
    centimetres.wrap.hidden = imperial;
    feet.wrap.hidden = !imperial;
    inches.wrap.hidden = !imperial;
    const [kg, cm] = readings();
    const out = calc.bmi(kg, cm);
    if (!out) { main.show('–'); detail.hidden = true; return; }
    main.show(plain(out.value, 1), t(`andromeda.tool_bmi_${out.group}`));
    const [low, high] = [out.low, out.high].map(value => plain(imperial ? value / 0.45359237 : value, 0));
    detail.textContent = t('andromeda.tool_bmi_range', { low, high, unit: imperial ? 'lb' : 'kg' });
    detail.hidden = false;
  }
  update();
  return [heading(t('andromeda.tool_bmi')), main.wrap, detail, units, form(weight, centimetres, feet, inches)];
}

// ── loans ──
export function loanTool(data) {
  const amount = entry(t('andromeda.tool_amount'), data.amount, () => update());
  const rate = entry(t('andromeda.tool_interest_rate'), data.rate, () => update());
  const years = entry(t('andromeda.tool_years'), data.years, () => update());
  const main = answer();
  const list = valueList();
  function update() {
    const out = calc.loan(parse(amount.input.value), parse(rate.input.value), parse(years.input.value));
    if (!out) { main.show('–'); list.set([]); return; }
    main.show(money(out.monthly), t('andromeda.tool_per_month'));
    list.set([[t('andromeda.tool_total_paid'), money(out.total)], [t('andromeda.tool_total_interest'), money(out.interest)]]);
  }
  update();
  return [heading(t(data.mode === 'mortgage' ? 'andromeda.tool_mortgage' : 'andromeda.tool_loan')), main.wrap, form(amount, rate, years), list.dl];
}

// ── number bases ──
const BASES = [[2, 'andromeda.tool_binary'], [8, 'andromeda.tool_octal'], [10, 'andromeda.tool_decimal'], [16, 'andromeda.tool_hexadecimal']];

export function baseTool(data) {
  let from = data.from || 10;
  let to = data.to || 16;
  const options = () => BASES.map(([value, key]) => ({ value, label: t(key) }));
  const input = entry(t('andromeda.tool_value'), data.value, () => update(), { text: true });
  const main = answer();
  const status = statusLine();
  const list = valueList(status);
  const pickFrom = choices(t('andromeda.tool_base_from'), options(), from, value => { from = Number(value); update(); });
  const pickTo = choices(t('andromeda.tool_base_to'), options(), to, value => { to = Number(value); update(); });
  function update() {
    status.textContent = '';
    list.set([]);
    main.show('–');
    if (!input.input.value.trim()) return;
    const whole = calc.parseBase(input.input.value, from);
    if (whole === null) { status.textContent = t('andromeda.tool_not_in_base', { base: t(BASES.find(([value]) => value === from)[1]) }); return; }
    main.show(calc.formatBase(whole, to));
    list.set(BASES.map(([value, key]) => [t(key), calc.formatBase(whole, value), true]));
  }
  update();
  return [heading(t('andromeda.tool_base_converter')), main.wrap, form(input), row(count(t('andromeda.tool_from')), pickFrom), row(count(t('andromeda.tool_to')), pickTo), list.dl, status];
}

// ── roman numerals ──
export function romanTool(data) {
  const input = entry(t('andromeda.tool_number_or_numeral'), data.value, () => update(), { text: true });
  const main = answer();
  const status = statusLine();
  const list = valueList(status);
  function update() {
    const text = input.input.value.trim();
    status.textContent = '';
    list.set([]);
    main.show('–');
    if (!text) return;
    if (/^\d+$/.test(text)) {
      const numeral = calc.toRoman(Number(text));
      if (!numeral) { status.textContent = t('andromeda.tool_roman_range'); return; }
      main.show(numeral);
      list.set([[t('andromeda.tool_roman_numeral'), numeral, true]]);
      return;
    }
    const number = calc.fromRoman(text);
    if (!number) { status.textContent = t('andromeda.tool_roman_invalid'); return; }
    main.show(String(number));
    list.set([[t('andromeda.tool_number'), String(number), true]]);
  }
  update();
  return [heading(t('andromeda.tool_roman')), main.wrap, form(input), list.dl, status];
}

// ── unix time ──
export function unixTool(data, ctx) {
  const zone = resolvedTimeZone();
  const now = answer(t('andromeda.tool_unix_now'), { live: false });
  const tick = () => { now.value.textContent = String(Math.floor(Date.now() / 1000)); };
  tick();
  const clock = setInterval(tick, 1000);
  ctx.onStop(() => clearInterval(clock));
  let last = data.value ? 'stamp' : '';
  const stamp = entry(t('andromeda.tool_timestamp'), data.value, () => { last = 'stamp'; update(); }, { text: true });
  const date = entry(t('andromeda.tool_date_time'), '', () => { last = 'date'; update(); }, { text: true, placeholder: '2026-10-28 14:30' });
  const status = statusLine();
  const list = valueList(status);
  function update() {
    status.textContent = '';
    list.set([]);
    if (last === 'stamp') {
      if (!stamp.input.value.trim()) return;
      const ms = calc.epochToMs(stamp.input.value);
      if (ms === null) { status.textContent = t('andromeda.tool_bad_timestamp'); return; }
      const seconds = (ms - Date.now()) / 1000;
      const [unit, size] = [['year', 31557600], ['month', 2629800], ['day', 86400], ['hour', 3600], ['minute', 60]].find(([, span]) => Math.abs(seconds) >= span) || ['second', 1];
      list.set([
        [zone.replace(/_/g, ' '), formatDateTime(ms, { dateStyle: 'full', timeStyle: 'medium' })],
        ['UTC', formatDateTime(ms, { dateStyle: 'full', timeStyle: 'medium', timeZone: 'UTC' })],
        ['ISO 8601', new Date(ms).toISOString(), true],
        [t('andromeda.tool_relative'), formatRelativeTime(Math.round(seconds / size), unit, { numeric: 'auto' })],
      ]);
    } else if (last === 'date' && date.input.value.trim()) {
      const seconds = calc.zonedToEpoch(date.input.value, zone);
      if (seconds === null) { status.textContent = t('andromeda.tool_bad_date'); return; }
      list.set([[t('andromeda.tool_seconds'), String(seconds), true], [t('andromeda.tool_milliseconds'), `${seconds}000`, true]]);
    }
  }
  update();
  return [heading(t('andromeda.tool_unix')), now.wrap, form(stamp, date), list.dl, status];
}

// ── passwords and uuids ──
const cryptoBytes = () => crypto.getRandomValues(new Uint8Array(16));

export function generateTool(data) {
  let mode = data.mode === 'uuid' ? 'uuid' : 'password';
  let length = data.length || 16;
  const kinds = { upper: true, digits: true, symbols: true };
  const body = make('div', 'andromeda-tool-body');
  const modes = choices(t('andromeda.tool_what_generate'), [{ value: 'password', label: t('andromeda.tool_password') }, { value: 'uuid', label: t('andromeda.tool_uuid') }], mode, value => { mode = value; draw(true); });
  function draw(roll) {
    const out = make('p', 'andromeda-answer-value andromeda-generated', '–');
    out.setAttribute('role', 'status');
    out.setAttribute('aria-live', 'polite');
    const strength = make('p', 'andromeda-answer-source');
    const status = statusLine();
    const copy = button(t('common.copy'), { onClick: () => copyText(out.textContent, status) });
    copy.disabled = true;
    const regenerate = () => {
      out.textContent = mode === 'uuid' ? calc.makeUuid(cryptoBytes()) : calc.makePassword(length, kinds, randomInt);
      strength.textContent = mode === 'uuid' ? '' : t('andromeda.tool_bits', { bits: Math.round(calc.passwordBits(length, kinds)) });
      copy.disabled = false;
      status.textContent = '';
    };
    const actions = make('div', 'andromeda-tool-actions');
    actions.append(button(t('andromeda.tool_generate'), { primary: true, onClick: regenerate }), copy);
    const parts = [out, strength];
    if (mode === 'password') {
      const size = make('span', 'andromeda-tool-slider-value', String(length));
      const lengthSlider = slider(t('andromeda.tool_length'), 64, length, value => { length = value; size.textContent = String(value); regenerate(); }, 6);
      const sliderRow = make('div', 'andromeda-tool-slider');
      sliderRow.append(count(t('andromeda.tool_length')), lengthSlider.track, size);
      const switches = make('div', 'andromeda-tool-row');
      for (const [key, label] of [['upper', t('andromeda.tool_uppercase')], ['digits', t('andromeda.tool_numbers')], ['symbols', t('andromeda.tool_symbols')]]) {
        switches.append(toggle(label, kinds[key], on => { kinds[key] = on; regenerate(); }));
      }
      parts.push(sliderRow, switches);
    }
    parts.push(actions, status);
    body.replaceChildren(...parts);
    if (roll) regenerate();
  }
  draw(Boolean(data.roll));
  return [heading(t('andromeda.tool_generator')), modes, body];
}

// ── encoders ──
export function encodeTool(data) {
  let scheme = data.scheme || 'base64';
  let dir = data.dir || 'encode';
  const status = statusLine();
  const out = make('p', 'andromeda-translate-text andromeda-tool-out');
  out.setAttribute('role', 'status');
  out.setAttribute('aria-live', 'polite');
  const copy = button(t('common.copy'), { onClick: () => copyText(out.textContent, status) });
  copy.disabled = true;
  const input = textBox(t('andromeda.tool_text_to_convert'), data.text, () => run());
  const schemes = choices(t('andromeda.tool_format'), ['base64', 'url', 'html'].map(value => ({ value, label: value })), scheme, value => { scheme = value; run(); });
  const dirs = choices(t('andromeda.tool_direction'), [{ value: 'encode', label: t('andromeda.tool_encode') }, { value: 'decode', label: t('andromeda.tool_decode') }], dir, value => { dir = value; run(); });
  function run() {
    status.textContent = '';
    out.textContent = '';
    copy.disabled = true;
    if (!input.input.value) return;
    try {
      out.textContent = calc.ENCODERS[scheme][dir](input.input.value);
      copy.disabled = false;
    } catch {
      status.textContent = t('andromeda.tool_cant_decode', { format: scheme });
    }
  }
  run();
  const actions = make('div', 'andromeda-tool-actions');
  actions.append(copy);
  return [heading(t('andromeda.tool_encoder')), row(schemes, dirs), input.wrap, out, actions, status];
}

// ── word and character counter ──
export function counterTool(data) {
  const list = valueList();
  const input = textBox(t('andromeda.tool_counter_text'), data.text, () => update());
  function update() {
    const out = calc.countText(input.input.value);
    const reading = out.minutes < 1 ? t('andromeda.tool_under_minute') : t('andromeda.tool_minutes', { minutes: plain(Math.round(out.minutes), 0) });
    list.set([
      [t('andromeda.tool_words'), plain(out.words, 0)],
      [t('andromeda.tool_characters'), plain(out.characters, 0)],
      [t('andromeda.tool_characters_no_spaces'), plain(out.noSpaces, 0)],
      [t('andromeda.tool_sentences'), plain(out.sentences, 0)],
      [t('andromeda.tool_paragraphs'), plain(out.paragraphs, 0)],
      [t('andromeda.tool_reading_time'), reading],
    ]);
  }
  update();
  return [heading(t('andromeda.tool_counter')), input.wrap, list.dl];
}

// ── moon ──
// the lit part is a half disc on the sunward side plus (or minus) the ellipse the shadow edge draws
function moonArt(fraction) {
  const [r, c] = [44, 50];
  const waxing = fraction < 0.5;
  const rx = r * Math.abs(Math.cos(2 * Math.PI * fraction));
  const edge = waxing ? (fraction < 0.25 ? 0 : 1) : (fraction < 0.75 ? 0 : 1);
  const lit = `M ${c} ${c - r} A ${r} ${r} 0 0 ${waxing ? 1 : 0} ${c} ${c + r} A ${rx.toFixed(2)} ${r} 0 0 ${edge} ${c} ${c - r} Z`;
  return `<svg viewBox="0 0 100 100" aria-hidden="true"><circle class="andromeda-moon-disc" cx="${c}" cy="${c}" r="${r}"/><path class="andromeda-moon-lit" d="${lit}"/></svg>`;
}

export function moonTool() {
  let offset = 0;
  const art = make('div', 'andromeda-moon-art');
  art.setAttribute('role', 'img');
  const main = answer();
  const list = valueList();
  const day = (ms, options) => formatDate(ms, options);
  const draw = () => {
    const ms = Date.now() + offset * 86400000;
    const out = calc.moon(ms);
    const phase = t(`andromeda.tool_moon_${out.phase}`);
    art.innerHTML = moonArt(out.fraction);
    art.setAttribute('aria-label', phase);
    main.show(phase, day(ms, { weekday: 'long', month: 'long', day: 'numeric' }));
    list.set([
      [t('andromeda.tool_moon_lit'), `${Math.round(out.illumination * 100)}%`],
      [t('andromeda.tool_moon_age'), t('andromeda.tool_days_short', { days: plain(out.age, 1) })],
      [t('andromeda.tool_next_full'), day(out.nextFull, { weekday: 'short', month: 'short', day: 'numeric' })],
      [t('andromeda.tool_next_new'), day(out.nextNew, { weekday: 'short', month: 'short', day: 'numeric' })],
    ]);
    today.disabled = offset === 0;
  };
  const step = by => () => { offset = by === 0 ? 0 : offset + by; draw(); };
  const today = button(t('common.today'), { onClick: step(0) });
  const actions = make('div', 'andromeda-tool-actions');
  actions.append(button(t('andromeda.tool_prev_day'), { onClick: step(-1) }), button(t('andromeda.tool_next_day'), { onClick: step(1) }), today);
  const side = make('div', 'andromeda-moon-side');
  side.append(main.wrap, list.dl);
  const top = make('div', 'andromeda-moon-top');
  top.append(art, side);
  draw();
  return [heading(t('andromeda.tool_moon')), top, actions];
}

// ── number facts ──
const SUPERSCRIPT = { 0: '⁰', 1: '¹', 2: '²', 3: '³', 4: '⁴', 5: '⁵', 6: '⁶', 7: '⁷', 8: '⁸', 9: '⁹' };
const power = (prime, times) => (times > 1 ? `${prime}${String(times).replace(/\d/g, digit => SUPERSCRIPT[digit])}` : String(prime));
const factorLine = parts => parts.map(([prime, times]) => power(prime, times)).join(' × ');

export function numfactsTool(data) {
  let mode = data.mode || 'prime';
  const first = entry('', data.a, () => update());
  const second = entry('', data.b, () => update());
  const main = answer();
  const status = statusLine();
  const list = valueList(status);
  const modes = choices(t('andromeda.tool_nf_mode'), ['prime', 'factors', 'gcd', 'lcm'].map(value => ({ value, label: t(`andromeda.tool_nf_${value}`) })), mode, value => { mode = value; update(); });
  function update() {
    const pair = mode === 'gcd' || mode === 'lcm';
    first.relabel(t(pair ? 'andromeda.tool_first_number' : 'andromeda.tool_number'));
    second.relabel(t('andromeda.tool_second_number'));
    second.wrap.hidden = !pair;
    status.textContent = '';
    list.set([]);
    main.show('–');
    const [a, b] = [calc.wholeNumber(first.input.value), calc.wholeNumber(second.input.value)];
    if (!first.input.value.trim() || (pair && !second.input.value.trim())) return;
    if (a === null || (pair && b === null)) { status.textContent = t('andromeda.tool_whole_up_to'); return; }
    if (pair) {
      main.show(mode === 'gcd' ? String(calc.gcd(a, b)) : String(calc.lcm(a, b)), t(mode === 'gcd' ? 'andromeda.tool_gcd_label' : 'andromeda.tool_lcm_label'));
      list.set([[t(mode === 'gcd' ? 'andromeda.tool_lcm_label' : 'andromeda.tool_gcd_label'), mode === 'gcd' ? String(calc.lcm(a, b)) : String(calc.gcd(a, b))]]);
      return;
    }
    const parts = calc.factorize(a);
    const all = calc.divisors(a);
    if (mode === 'prime') main.show(t(calc.isPrime(a) ? 'andromeda.tool_is_prime' : 'andromeda.tool_not_prime', { n: plain(a, 0) }));
    else main.show(a === 1 ? '1' : factorLine(parts), t('andromeda.tool_prime_factors'));
    list.set([
      ...(mode === 'prime' && a > 1 && !calc.isPrime(a) ? [[t('andromeda.tool_prime_factors'), factorLine(parts)]] : []),
      [t('andromeda.tool_all_factors'), all.length > 60 ? `${all.slice(0, 60).map(value => plain(value, 0)).join(', ')} …` : all.map(value => plain(value, 0)).join(', '), true],
    ]);
  }
  update();
  return [heading(t('andromeda.tool_number_facts')), main.wrap, modes, form(first, second), list.dl, status];
}

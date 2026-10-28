// a day's log for habits that record more than "done": sets and weights, pages, minutes, counts.
// the server checks the same shapes (services/habit_kinds.py). weights are pounds, as the owner
// logs them: dumbbells per hand, machines per side. a set row without reps is 10, without sets 1.
import { form } from './dialog.js';
import { formatCalendarDate, formatNumber, t, tp } from './i18n.js';
import { wireChoiceGroup } from './kokuen.js?v=4';
import { formatDecimal } from './liveformat.js';

const LOGGED = new Set(['workout', 'reading', 'count', 'duration', 'distance']);
const UNITS = new Set(['reps', 'steps', 'glasses', 'servings', 'words', 'cards', 'pages', 'chapters']);
const DEFAULT_REPS = 10;
const MAX_ROWS = 50;
const SUGGESTIONS = 8;

export const hasLogger = habit => LOGGED.has(habit?.kind);

const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const _si = name => (globalThis.window?.icon ? window.icon(name) : '');
const num = value => formatNumber(value, { maximumFractionDigits: 2 });
let _sequence = 0;

function amountOf(unit, amount) {
  return UNITS.has(unit) ? tp(`habits.n_${unit}`, amount, { n: num(amount) }) : `${num(amount)}${unit ? ` ${unit}` : ''}`;
}

export function durationText(minutes) {
  const total = Math.round(Number(minutes) || 0);
  if (total < 60) return t('habits.min_short', { n: num(total) });
  const h = Math.floor(total / 60), m = total % 60;
  return m ? t('habits.h_min', { h: num(h), m: num(m) }) : t('habits.h_short', { h: num(h) });
}

// "lat pulldown 70 × 10 · 3 sets", "24 pages · dune", "6 glasses", "45 min", "5 km · 28 min"
export function logSummary(habit, data) {
  if (!data || !hasLogger(habit)) return '';
  if (habit.kind === 'workout') {
    const rows = Array.isArray(data.rows) ? data.rows : [];
    if (!rows.length) return '';
    const [first] = rows;
    const weight = first.weight ? ` ${num(first.weight)}` : '';
    const sets = first.sets > 1 ? ` · ${tp('habits.n_sets', first.sets, { n: num(first.sets) })}` : '';
    const head = `${first.exercise}${weight} × ${num(first.reps ?? DEFAULT_REPS)}${sets}`;
    return rows.length > 1 ? `${head} ${t('habits.more_rows', { n: num(rows.length - 1) })}` : head;
  }
  if (habit.kind === 'reading') {
    if (data.amount == null) return '';
    return amountOf(data.unit || 'pages', data.amount) + (data.book ? ` · ${data.book}` : '');
  }
  if (habit.kind === 'count') return data.amount == null ? '' : amountOf(habit.unit, data.amount);
  if (habit.kind === 'duration') return data.minutes == null ? '' : durationText(data.minutes);
  if (habit.kind === 'distance') {
    if (data.distance == null) return '';
    return `${num(data.distance)} ${data.unit || 'km'}` + (data.minutes ? ` · ${durationText(data.minutes)}` : '');
  }
  return '';
}

// ── reading the fields ─────────────────────────────────────────────────────────
function bad(input, key) {
  input?.setAttribute('aria-invalid', 'true');
  input?.focus();
  return new Error(t(key));
}

// '' is "not given"; commas read the way the field formats them (7,5 and 1,650)
function numberIn(input, { whole = false, required = false, min = 0 } = {}) {
  const raw = formatDecimal(String(input?.value ?? '').trim());
  input?.removeAttribute('aria-invalid');
  if (!raw) {
    if (required) throw bad(input, 'habits.log_bad_number');
    return null;
  }
  const value = Number(raw);
  if (!Number.isFinite(value) || value < min || (whole && !Number.isInteger(value))) throw bad(input, 'habits.log_bad_number');
  return value;
}

const textIn = input => String(input?.value ?? '').replace(/\s+/g, ' ').trim();
const choiceIn = (card, key) => card.querySelector(`[data-k="${key}"] [aria-checked="true"]`)?.dataset.value;

export function collectLog(kind, card) {
  const field = key => card.querySelector(`[data-k="${key}"]`);
  if (kind === 'workout') {
    const rows = [];
    for (const row of card.querySelectorAll('.hlog-row')) {
      const get = key => row.querySelector(`[data-k="${key}"]`);
      const values = ['exercise', 'weight', 'reps', 'sets', 'note'].map(key => textIn(get(key)));
      if (values.every(value => !value)) continue;
      const exercise = values[0];
      if (!exercise) throw bad(get('exercise'), 'habits.log_need_exercise');
      const weight = numberIn(get('weight'));
      const reps = numberIn(get('reps'), { whole: true, min: 1 });
      const sets = numberIn(get('sets'), { whole: true, min: 1 });
      rows.push({ exercise, weight, reps: reps ?? DEFAULT_REPS, sets: sets ?? 1, note: values[4] });
    }
    return { rows };
  }
  if (kind === 'reading') return { amount: numberIn(field('amount'), { required: true }), unit: choiceIn(card, 'unit') || 'pages', book: textIn(field('book')) };
  if (kind === 'count') return { amount: numberIn(field('amount'), { required: true }) };
  if (kind === 'duration') return { minutes: numberIn(field('minutes'), { required: true }) };
  if (kind === 'distance') return { distance: numberIn(field('distance'), { required: true }), unit: choiceIn(card, 'unit') || 'km', minutes: numberIn(field('minutes')) };
  return null;
}

// ── markup ─────────────────────────────────────────────────────────────────────
function numberField(key, label, value, { decimal = true, placeholder = '', id }) {
  return `<div class="hlog-f hlog-${key}"><label for="${id}">${esc(label)}</label>
    <input class="settings-input dialog-input" id="${id}" data-k="${key}" inputmode="${decimal ? 'decimal' : 'numeric'}" autocomplete="off" value="${esc(value ?? '')}" placeholder="${esc(placeholder)}"></div>`;
}

function choiceField(key, label, options, value, id) {
  return `<div class="hlog-f"><span id="${id}-label">${esc(label)}</span>
    <div class="seg seg-sm hlog-seg" data-k="${key}" role="radiogroup" aria-labelledby="${id}-label">${options.map(([option, text]) =>
      `<button type="button" class="seg-opt${option === value ? ' active' : ''}" role="radio" data-value="${option}" aria-checked="${option === value}" tabindex="${option === value ? 0 : -1}">${esc(text)}</button>`).join('')}</div></div>`;
}

function rowHtml(row, first) {
  const id = `hlog-${++_sequence}`;
  const label = (key, text) => `<label for="${id}-${key}"${first ? '' : ' class="sr-only"'}>${esc(text)}</label>`;
  const input = (key, value, extra = '') => `<input class="settings-input dialog-input" id="${id}-${key}" data-k="${key}" autocomplete="off" value="${esc(value ?? '')}"${extra}>`;
  return `<div class="hlog-row">
    <div class="hlog-line">
      <div class="hlog-f hlog-ex">${label('exercise', t('habits.exercise'))}${input('exercise', row.exercise, ` role="combobox" aria-autocomplete="list" aria-expanded="false" spellcheck="false"`)}</div>
      <button type="button" class="icon-btn hlog-remove" data-hlog-remove aria-label="${esc(t('habits.remove_row'))}">${_si('trash')}</button>
    </div>
    <div class="hlog-nums">
      <div class="hlog-f">${label('weight', t('habits.weight_lb'))}${input('weight', row.weight, ' inputmode="decimal"')}</div>
      <div class="hlog-f">${label('reps', t('habits.reps'))}${input('reps', row.reps, ` inputmode="numeric" placeholder="${DEFAULT_REPS}"`)}</div>
      <div class="hlog-f">${label('sets', t('habits.sets'))}${input('sets', row.sets, ' inputmode="numeric" placeholder="1"')}</div>
      <div class="hlog-f">${label('note', t('habits.note'))}${input('note', row.note)}</div>
    </div>
  </div>`;
}

function fieldsHtml(habit, data, recent) {
  const id = `hlog-${++_sequence}`;
  if (habit.kind === 'workout') {
    const rows = data?.rows?.length ? data.rows : [{}];
    return `<div class="hlog-rows">${rows.map((row, at) => rowHtml(row, at === 0)).join('')}</div>
      <button type="button" class="btn hlog-add" data-hlog-add>${_si('plus')} ${esc(t('habits.add_set'))}</button>`;
  }
  if (habit.kind === 'reading') {
    const unit = data?.unit || recent?.unit || 'pages';
    return `<div class="hlog-inline">${numberField('amount', t('habits.amount'), data?.amount, { id: `${id}-amount` })}
      ${choiceField('unit', t('habits.unit'), [['pages', t('habits.u_pages')], ['chapters', t('habits.u_chapters')]], unit, `${id}-unit`)}</div>
      <div class="hlog-f"><label for="${id}-book">${esc(t('habits.book'))}</label>
        <input class="settings-input dialog-input" id="${id}-book" data-k="book" autocomplete="off" value="${esc(data?.book ?? recent?.book ?? '')}"></div>`;
  }
  if (habit.kind === 'count') {
    const label = UNITS.has(habit.unit) ? t(`habits.u_${habit.unit}`) : (habit.unit || t('habits.amount'));
    return numberField('amount', label, data?.amount, { id: `${id}-amount` });
  }
  if (habit.kind === 'duration') return numberField('minutes', t('habits.minutes'), data?.minutes, { decimal: false, id: `${id}-minutes` });
  if (habit.kind === 'distance') {
    const unit = data?.unit || recent?.unit || habit.unit || 'km';
    return `<div class="hlog-inline">${numberField('distance', t('habits.distance'), data?.distance, { id: `${id}-distance` })}
      ${choiceField('unit', t('habits.unit'), [['km', 'km'], ['mi', 'mi']], unit, `${id}-unit`)}</div>
      ${numberField('minutes', t('habits.minutes'), data?.minutes, { decimal: false, id: `${id}-minutes` })}`;
  }
  return '';
}

// ── behavior ───────────────────────────────────────────────────────────────────
function wireChoices(card) {
  card.querySelectorAll('.hlog-seg').forEach(group => {
    wireChoiceGroup(group);
    group.addEventListener('click', () => queueMicrotask(() => group.querySelectorAll('.seg-opt')
      .forEach(choice => choice.classList.toggle('active', choice.getAttribute('aria-checked') === 'true'))));
    group.addEventListener('keydown', () => queueMicrotask(() => group.querySelectorAll('.seg-opt')
      .forEach(choice => choice.classList.toggle('active', choice.getAttribute('aria-checked') === 'true'))));
  });
}

export function matchExercises(names, query, limit = SUGGESTIONS) {
  const q = String(query || '').trim().toLowerCase();
  if (!q) return names.slice(0, limit);
  const starts = names.filter(name => name.toLowerCase().startsWith(q) && name.toLowerCase() !== q);
  const inside = names.filter(name => !name.toLowerCase().startsWith(q) && name.toLowerCase().includes(q));
  return [...starts, ...inside].slice(0, limit);
}

// one floating list under whichever exercise field has focus. it lives on the overlay, so a
// scrolling dialog body never clips it
function wireExercises(card, names) {
  const overlay = card.closest('.dialog-overlay');
  const list = document.createElement('div');
  const listId = `hlog-suggest-${++_sequence}`;
  list.className = 'hlog-suggest';
  list.id = listId;
  list.setAttribute('role', 'listbox');
  list.setAttribute('aria-label', t('habits.exercise'));
  list.hidden = true;
  overlay.appendChild(list);
  let input = null, shown = [], active = -1;

  const place = () => {
    if (!overlay.isConnected) { window.removeEventListener('resize', place); return; }
    if (!input || list.hidden) return;
    const rect = input.getBoundingClientRect();
    const below = window.innerHeight - rect.bottom - 8;
    list.style.left = `${rect.left}px`;
    list.style.width = `${rect.width}px`;
    if (list.offsetHeight > below && rect.top > below) { list.style.top = ''; list.style.bottom = `${window.innerHeight - rect.top + 4}px`; }
    else { list.style.bottom = ''; list.style.top = `${rect.bottom + 4}px`; }
  };
  const close = () => {
    list.hidden = true; shown = []; active = -1;
    input?.setAttribute('aria-expanded', 'false');
    input?.removeAttribute('aria-activedescendant');
  };
  const mark = index => {
    active = index;
    list.querySelectorAll('[role="option"]').forEach((node, at) => node.toggleAttribute('data-active', at === active));
    if (active >= 0) { input.setAttribute('aria-activedescendant', `${listId}-${active}`); list.children[active]?.scrollIntoView({ block: 'nearest' }); }
    else input.removeAttribute('aria-activedescendant');
  };
  const open = field => {
    input = field;
    shown = matchExercises(names, field.value);
    if (!shown.length) { close(); return; }
    list.innerHTML = shown.map((name, at) => `<div role="option" id="${listId}-${at}" class="hlog-option" data-i="${at}" aria-selected="false">${esc(name)}</div>`).join('');
    list.hidden = false;
    field.setAttribute('aria-expanded', 'true');
    field.setAttribute('aria-controls', listId);
    mark(-1);
    place();
  };
  const choose = index => {
    if (!input || !shown[index]) return;
    input.value = shown[index];
    close();
    input.closest('.hlog-row')?.querySelector('[data-k="weight"]')?.focus();
  };

  card.addEventListener('focusin', event => { if (event.target.matches('[data-k="exercise"]')) open(event.target); });
  card.addEventListener('focusout', event => { if (event.target === input) close(); });
  card.addEventListener('input', event => { if (event.target.matches('[data-k="exercise"]')) open(event.target); });
  card.addEventListener('keydown', event => {
    if (event.target !== input || list.hidden) return;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (event.key === 'ArrowDown') mark(active + 1 >= shown.length ? 0 : active + 1);
      else mark(active - 1 < 0 ? shown.length - 1 : active - 1);
    } else if (event.key === 'Enter' && active >= 0) {
      event.preventDefault();
      choose(active);
    } else if (event.key === 'Escape') {
      event.preventDefault(); event.stopPropagation();
      close();
    }
  }, true);
  // options never take focus, so a press on one keeps the field focused
  list.addEventListener('pointerdown', event => event.preventDefault());
  list.addEventListener('mousemove', event => {
    const option = event.target.closest('[role="option"]');
    if (option && Number(option.dataset.i) !== active) mark(Number(option.dataset.i));
  });
  list.addEventListener('click', event => {
    const option = event.target.closest('[role="option"]');
    if (option) choose(Number(option.dataset.i));
  });
  card.addEventListener('scroll', place, true);
  window.addEventListener('resize', place);
}

function wireRows(card) {
  const rows = card.querySelector('.hlog-rows');
  const add = card.querySelector('[data-hlog-add]');
  const sync = () => {
    const all = rows.querySelectorAll('.hlog-row');
    add.disabled = all.length >= MAX_ROWS;
    // only the first row shows its labels; the rows below line up under them
    all.forEach((row, at) => row.querySelectorAll('.hlog-f > label').forEach(label => label.classList.toggle('sr-only', at > 0)));
  };
  add.addEventListener('click', () => {
    const last = [...rows.querySelectorAll('.hlog-row')].pop();
    const copy = key => textIn(last?.querySelector(`[data-k="${key}"]`));
    rows.insertAdjacentHTML('beforeend', rowHtml({ exercise: copy('exercise'), weight: copy('weight'), reps: copy('reps'), sets: copy('sets') }, false));
    sync();
    const row = [...rows.querySelectorAll('.hlog-row')].pop();
    row.querySelector(`[data-k="${copy('exercise') ? 'weight' : 'exercise'}"]`)?.focus();
  });
  rows.addEventListener('click', event => {
    const remove = event.target.closest('[data-hlog-remove]');
    if (!remove) return;
    const row = remove.closest('.hlog-row');
    const next = row.nextElementSibling || row.previousElementSibling;
    row.remove();
    if (!rows.querySelector('.hlog-row')) rows.insertAdjacentHTML('beforeend', rowHtml({}, true));
    sync();
    (next?.isConnected ? next : rows.querySelector('.hlog-row'))?.querySelector('[data-k="exercise"]')?.focus();
  });
  sync();
}

// the most recent day before this one that had details: a reading habit keeps its book and unit
function recentLog(habit, day) {
  const days = Object.keys(habit.logs || {}).filter(other => other < day).sort();
  return days.length ? habit.logs[days[days.length - 1]] : null;
}

// resolves null (closed), { saved: data } or { remove: true }
export async function openLogger(habit, day, { save, done = false } = {}) {
  const data = habit.logs?.[day] || null;
  const date = formatCalendarDate(day, { weekday: 'long', month: 'long', day: 'numeric' });
  let saved = null;
  const result = await form(t('habits.log_title', { name: habit.name, date }), `<div class="hlog-fields">${fieldsHtml(habit, data, recentLog(habit, day))}</div>`, {
    className: `habit-log-dialog habit-log-${habit.kind}`,
    collect: card => collectLog(habit.kind, card),
    submit: async value => { saved = await save(value); },
    remove: done ? { label: t('habits.clear_log') } : null,
    wire: card => {
      wireChoices(card);
      if (habit.kind === 'workout') { wireRows(card); wireExercises(card, habit.exercises || []); }
      card.addEventListener('input', event => event.target.removeAttribute('aria-invalid'));
    },
  });
  if (!result) return null;
  return result.remove ? { remove: true } : { saved: saved ?? result };
}

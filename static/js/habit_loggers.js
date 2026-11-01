// a day's log for habits that record more than "done": sets and weights, pages, minutes, counts.
// the server checks the same shapes (services/habit_kinds.py). weights are pounds, as the owner
// logs them: dumbbells per hand, machines per side. a set row without reps is 10, without sets 1.
import { form } from './dialog.js';
import { formatCalendarDate, formatNumber, t, tp } from './i18n.js';
import { initKokuenPrimitives } from './kokuen.js?v=5';
import { initCustomDropdown } from './dropdown.js?v=215';
import { api, toast } from './util.js';
import { formatDecimal } from './liveformat.js';
import { stepperHtml } from './stepper.js';
import { initDatePickers } from './datepick.js';

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

// one option of a kit pill switch; kokuen gives it its role and the unpicked state
const pillButton = (value, text, on) => `<button type="button" data-value="${esc(value)}"${on ? ' aria-checked="true"' : ''}>${esc(text)}</button>`;
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

// two units (pages or chapters, km or mi): the kit pill switch
function choiceField(key, label, options, value, id) {
  return `<div class="hlog-f"><span id="${id}-label">${esc(label)}</span>
    <div class="k-pill-switch" data-kokuen-choice="switch" data-k="${key}" aria-labelledby="${id}-label">${options.map(([option, text]) => pillButton(option, text, option === value)).join('')}</div></div>`;
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

// an empty day starts from the last logged day's values, so "same as last time" is open and save
function fieldsHtml(habit, data, recent) {
  const id = `hlog-${++_sequence}`;
  if (habit.kind === 'workout') {
    const rows = data?.rows?.length ? data.rows : [{}];
    return `<div class="hlog-rows">${rows.map((row, at) => rowHtml(row, at === 0)).join('')}</div>
      <button type="button" class="btn hlog-add" data-hlog-add>${_si('plus')} ${esc(t('habits.add_set'))}</button>`;
  }
  if (habit.kind === 'reading') {
    const unit = data?.unit || recent?.unit || 'pages';
    return `<div class="hlog-inline">${numberField('amount', t('habits.amount'), data?.amount ?? recent?.amount, { id: `${id}-amount` })}
      ${choiceField('unit', t('habits.unit'), [['pages', t('habits.u_pages')], ['chapters', t('habits.u_chapters')]], unit, `${id}-unit`)}</div>
      <div class="hlog-f"><label for="${id}-book">${esc(t('habits.book'))}</label>
        <input class="settings-input dialog-input" id="${id}-book" data-k="book" autocomplete="off" value="${esc(data?.book ?? recent?.book ?? '')}"></div>`;
  }
  if (habit.kind === 'count') {
    const label = UNITS.has(habit.unit) ? t(`habits.u_${habit.unit}`) : (habit.unit || t('habits.amount'));
    return numberField('amount', label, data?.amount ?? recent?.amount, { id: `${id}-amount` });
  }
  if (habit.kind === 'duration') return numberField('minutes', t('habits.minutes'), data?.minutes ?? recent?.minutes, { decimal: false, id: `${id}-minutes` });
  if (habit.kind === 'distance') {
    const unit = data?.unit || recent?.unit || habit.unit || 'km';
    return `<div class="hlog-inline">${numberField('distance', t('habits.distance'), data?.distance ?? recent?.distance, { id: `${id}-distance` })}
      ${choiceField('unit', t('habits.unit'), [['km', 'km'], ['mi', 'mi']], unit, `${id}-unit`)}</div>
      ${numberField('minutes', t('habits.minutes'), data?.minutes ?? recent?.minutes, { decimal: false, id: `${id}-minutes` })}`;
  }
  return '';
}

// ── behavior ───────────────────────────────────────────────────────────────────

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
  const overlay = card.closest('.dialog-overlay') || document.body;
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
      initKokuenPrimitives(card);
      if (habit.kind === 'workout') { wireRows(card); wireExercises(card, habit.exercises || []); }
      card.addEventListener('input', event => event.target.removeAttribute('aria-invalid'));
    },
  });
  if (!result) return null;
  return result.remove ? { remove: true } : { saved: saved ?? result };
}

// ── the gym logger (track E3): the set logger screen the owner approved ────────────────────────
// a workout day is v2: entries[].values.exercises = [{name, setup, sets: [...]}]. a split set is
// two stored sets, side L then side R; the screen pairs them back into one row. every value keeps
// the unit it was entered in; the raw words from an import stay under their row, word for word.
const KG = 0.45359237;
const SET_TYPES = ['warmup', 'working', 'top', 'backoff', 'drop', 'failure'];
const SET_STATUSES = ['done', 'planned', 'attempted', 'failed', 'unfinished'];
const RIR_TOP = 5;
const UNDO_MS = 8000;
let _gym = null;

const isNum = value => typeof value === 'number' && Number.isFinite(value);
const mmss = seconds => `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, '0')}`;

// stored sets as the rows the owner sees: a side L set and the side R set right after it are one
export function groupSets(sets = []) {
  const out = [];
  for (let at = 0; at < sets.length; at++) {
    const one = sets[at], next = sets[at + 1];
    if (one.side && next?.side && next.side !== one.side && !next.raw) {
      out.push({ [one.side]: one, [next.side]: next, at: [at, at + 1] });
      at++;
    } else out.push(one.side ? { [one.side]: one, at: [at] } : { both: one, at: [at] });
  }
  return out;
}

const loadText = (value, unit, shown) => value === '?' ? '?' : isNum(value) ? `${num(value)}${unit && unit !== shown ? ` ${unit}` : ''}` : '';

function sideText(one, shown) {
  const reps = one.reps === '?' ? '?' : isNum(one.reps) ? `${one.approx ? '~' : ''}${num(one.reps)}` : '';
  const load = one.assist != null ? t('habits.assist_n', { n: loadText(one.assist, one.unit, shown) }) : loadText(one.weight, one.unit, shown);
  if (load && reps) return `${load} × ${reps}`;
  return load || (reps ? t('habits.n_reps_only', { n: reps }) : '?');
}

// "L 65 × 10 · R 65 × 12", "50 × 10"
export function setText(group, shown = 'lb') {
  if (group.both) return sideText(group.both, shown);
  return ['L', 'R'].filter(side => group[side]).map(side => `${side} ${sideText(group[side], shown)}`).join(' · ');
}

// "warm up · 3 left", "1 left · 3 bad on L"
export function setMeta(group) {
  const first = group.both || group.L || group.R;
  const bits = [];
  if ((first.count || 1) > 1) bits.push(tp('habits.n_sets', first.count, { n: num(first.count) }));
  if (first.type && first.type !== 'working') bits.push(t(`habits.set_type_${first.type}`));
  if (first.status && first.status !== 'done') bits.push(t(`habits.set_status_${first.status}`));
  if (first.rir != null) bits.push(t('habits.n_left', { n: first.rir === '?' ? '?' : first.rir >= RIR_TOP ? `${RIR_TOP}+` : num(first.rir) }));
  for (const side of group.both ? ['both'] : ['L', 'R']) {
    const one = group[side];
    if (!one) continue;
    if (one.partial) bits.push(side === 'both' ? t('habits.n_partial', { n: num(one.partial) }) : t('habits.n_partial_on', { n: num(one.partial), side }));
    if (one.bad) bits.push(side === 'both' ? t('habits.n_bad', { n: num(one.bad) }) : t('habits.n_bad_on', { n: num(one.bad), side }));
  }
  if (first.tempo) bits.push(t('habits.tempo_n', { n: first.tempo }));
  const notes = [group.both, group.L, group.R].map(one => one?.note).filter(Boolean);
  bits.push(...new Set(notes));
  return bits.join(' · ');
}

export const rawOf = group => [group.both, group.L, group.R].map(one => one?.raw).filter(Boolean).join('\n');

function sideDraft(one = {}) {
  return { weight: one.assist ?? one.weight ?? null, reps: one.reps ?? null, partial: one.partial || 0, bad: one.bad || 0 };
}

export function draftFrom(group, unit, fresh) {
  const first = group.both || group.L || group.R;
  const draft = {
    sides: group.both ? 'same' : 'split',
    unit: first.unit || unit,
    assist: first.assist != null,
    L: sideDraft(group.both || group.L || group.R),
    R: sideDraft(group.both || group.R || group.L),
    rir: fresh ? null : first.rir ?? null,
    type: fresh ? 'working' : first.type || 'working',
    status: fresh ? 'done' : first.status || 'done',
    rest: first.rest ?? 120,
    tempo: fresh ? '' : first.tempo || '',
    note: fresh ? '' : group.L?.note || first.note || '',
  };
  if (fresh) for (const side of ['L', 'R']) { draft[side].partial = 0; draft[side].bad = 0; }
  return draft;
}

// the draft as stored sets: one for "same", side L then side R for "split"
export function draftSets(draft) {
  const shared = { type: draft.type, status: draft.status, count: 1 };
  if (draft.rir != null) shared.rir = draft.rir;
  if (draft.rest) shared.rest = draft.rest;
  const one = (values, extra) => {
    const out = { ...shared, ...extra };
    if (values.weight != null && values.weight !== '') {
      out[draft.assist ? 'assist' : 'weight'] = values.weight;
      out.unit = draft.unit;
    }
    if (values.reps != null && values.reps !== '') out.reps = values.reps;
    if (values.partial) out.partial = values.partial;
    if (values.bad) out.bad = values.bad;
    return out;
  };
  const notes = {};
  if (draft.tempo) notes.tempo = draft.tempo;
  if (draft.note) notes.note = draft.note;
  if (draft.sides === 'same') return [one(draft.L, notes)];
  return [one(draft.L, { side: 'L', ...notes }), one(draft.R, { side: 'R' })];
}

function gymStepper(key, side, label) {
  const sideWord = side ? t(side === 'L' ? 'habits.left' : 'habits.right') : '';
  const name = sideWord ? `${label}, ${sideWord}` : label;
  // the kit stepper's markup; this logger keeps its own draft, so the stepper doesn't step itself
  const attrs = `data-key="${key}"${side ? ` data-side="${side}"` : ''}`;
  return `<div class="gym-cell"${side ? ` data-side="${side}"` : ''}>${side ? `<span class="gym-cell-label" aria-hidden="true">${esc(sideWord)}</span>` : ''}
    ${stepperHtml({ name, auto: false, attrs, inputmode: key === 'weight' ? 'decimal' : 'numeric' })}</div>`;
}

const colHead = () => `<div class="gym-frow gym-colhead" aria-hidden="true"><span></span><div class="gym-cells"><span>${esc(t('habits.left'))}</span><span>${esc(t('habits.right'))}</span></div></div>`;
const sidedRow = (key, label) => `<div class="gym-frow" data-key="${key}"><div class="gym-flabel"><span>${esc(label)}</span></div><div class="gym-cells">${gymStepper(key, 'L', label)}${gymStepper(key, 'R', label)}</div></div>`;
const optionList = (list, prefix) => list.map(value => `${value}|${t(`habits.${prefix}_${value}`)}`).join(';');

function editorHtml(g) {
  const { draft } = g;
  const exercise = g.exercises[g.active];
  const n = g.editing ? g.editing.group + 1 : groupSets(exercise.sets).length + 1;
  const pills = (name, values, picked, label) => `<div class="k-pill-switch" data-kokuen-choice="switch" data-gym="${name}" aria-label="${esc(label)}">${values.map(([value, text]) => pillButton(value, text, value === picked)).join('')}</div>`;
  const rirLabels = Array.from({ length: RIR_TOP + 1 }, (_, at) => t(at === 0 ? 'habits.rir_failure_n' : at === RIR_TOP ? 'habits.rir_easy_n' : 'habits.rir_n', { n: at === RIR_TOP ? `${at}+` : at })).join(',');
  const load = t(draft.assist ? 'habits.assist' : 'habits.weight');
  return `<section class="gym-editor" data-sides="${draft.sides}" aria-labelledby="gym-set-title">
    <div class="gym-ed-head"><h4 id="gym-set-title">${esc(t('habits.set_n', { n }))}${g.editing ? ` <span class="gym-editing">${esc(t('habits.editing'))}</span>` : ''}</h4>
      ${pills('sides', [['same', t('habits.sides_same')], ['split', t('habits.sides_split')]], draft.sides, t('habits.sides'))}</div>
    <div class="gym-rest" role="timer" aria-label="${esc(t('habits.rest'))}"${g.rest ? '' : ' hidden'}><span class="gym-rest-label">${esc(t('habits.rest'))}</span><span class="gym-rest-time">${g.rest ? mmss(Math.max(0, g.rest.left)) : ''}</span>
      <button type="button" class="gym-text-btn" data-gym="rest-more">${esc(t('habits.plus_15s'))}</button><button type="button" class="gym-text-btn" data-gym="rest-skip">${esc(t('habits.skip'))}</button></div>
    <div class="gym-fields">
      ${colHead()}
      <div class="gym-frow" data-key="weight"><div class="gym-flabel"><span>${esc(load)}</span>${pills('unit', [['lb', 'lb'], ['kg', 'kg']], draft.unit, t('habits.unit'))}</div>
        <div class="gym-cells">${gymStepper('weight', 'L', load)}${gymStepper('weight', 'R', load)}</div></div>
      ${sidedRow('reps', t('habits.reps'))}
      <div class="gym-frow gym-scale-row"><div class="gym-flabel"><span>${esc(t('habits.reps_left'))}</span></div>
        <div class="k-number-row" data-kokuen-choice="rating" data-gym="rir" aria-label="${esc(t('habits.reps_left'))}" data-min="0" data-max="${RIR_TOP}" data-value="${draft.rir ?? ''}" data-labels="${esc(rirLabels)}" data-words="${esc(t('habits.rir_failure'))},,,,,${esc(t('habits.rir_easy'))}"></div></div>
    </div>
    <button type="button" class="gym-more" data-gym="more" aria-expanded="${g.more}" aria-controls="gym-details">${esc(t('habits.more_details'))} ${_si('chevron-down')}</button>
    <div class="gym-details" id="gym-details"${g.more ? '' : ' hidden'}>
      <div class="gym-fields">
        <div class="gym-frow"><div class="gym-flabel"><span id="gym-type-label">${esc(t('habits.set_type'))}</span></div><div class="settings-input custom-select" data-gym="type" data-value="${draft.type}" data-options="${esc(optionList(SET_TYPES, 'set_type'))}" aria-labelledby="gym-type-label"></div></div>
        <div class="gym-frow"><div class="gym-flabel"><span id="gym-status-label">${esc(t('habits.how_it_went'))}</span></div><div class="settings-input custom-select" data-gym="status" data-value="${draft.status}" data-options="${esc(optionList(SET_STATUSES, 'set_status'))}" aria-labelledby="gym-status-label"></div></div>
        ${colHead()}
        ${sidedRow('partial', t('habits.partial_reps'))}
        ${sidedRow('bad', t('habits.bad_reps'))}
        <div class="gym-frow"><div class="gym-flabel"><span>${esc(t('habits.rest_after'))}</span></div>${gymStepper('rest', '', t('habits.rest_after'))}</div>
        <div class="gym-frow"><div class="gym-flabel"><label for="gym-tempo">${esc(t('habits.tempo'))}</label></div><input class="settings-input gym-tempo" id="gym-tempo" data-gym="tempo" autocomplete="off" placeholder="3-1-1-0" value="${esc(draft.tempo)}"></div>
        <div class="gym-frow"><div class="gym-flabel"><label for="gym-note">${esc(t('habits.note'))}</label></div><textarea class="settings-input gym-note" id="gym-note" data-gym="note" rows="1" placeholder="${esc(t('habits.set_note_placeholder'))}">${esc(draft.note)}</textarea></div>
      </div>
    </div>
    <div class="gym-actions">${g.editing ? `<button type="button" class="btn" data-gym="cancel">${esc(t('common.cancel'))}</button>` : ''}<button type="button" class="btn primary gym-log-btn" data-gym="log">${esc(t(g.editing ? 'habits.save_set_n' : 'habits.log_set_n', { n }))}</button></div>
  </section>`;
}

const editButton = at => `<button type="button" class="icon-btn" data-gym="edit" aria-label="${esc(t('habits.edit_set_n', { n: at + 1 }))}">${_si('edit')}</button>`;

function setsHtml(g, index) {
  const exercise = g.exercises[index];
  const groups = groupSets(exercise.sets);
  if (!groups.length) return '';
  return `<ol class="gym-sets" aria-label="${esc(t('habits.logged_sets'))}">${groups.map((group, at) => {
    const meta = setMeta(group), raw = rawOf(group);
    const undo = g.undo && g.undo.ex === index && g.undo.group === at;
    const editing = g.editing && g.active === index && g.editing.group === at;
    return `<li class="gym-set${editing ? ' is-editing' : ''}" data-group="${at}"><span class="gym-set-n">${at + 1}</span>
      <span class="gym-set-vals"><span class="gym-set-text">${esc(setText(group, exercise.unit || 'lb'))}</span>${meta ? `<span class="gym-set-meta">${esc(meta)}</span>` : ''}${raw ? `<span class="gym-set-raw">${esc(raw)}</span>` : ''}</span>
      ${undo ? `<button type="button" class="gym-text-btn gym-undo" data-gym="undo">${esc(t('habits.undo'))}</button>` : editButton(at)}</li>`;
  }).join('')}</ol>`;
}

function exerciseMeta(exercise, muscles) {
  const setup = exercise.setup || {};
  const bits = [setup.basis ? t(`habits.basis_${setup.basis}`) : '',
    ...['equipment', 'machine', 'grip', 'stance', 'angle', 'seat', 'pin'].map(key => setup[key] || ''), ...(muscles || [])];
  return bits.filter(Boolean).join(' · ');
}

// a day can hold more than one session (back in the morning, arms later): each keeps its own
// entry, its muscle groups and its note, and the screen shows every one of them
const entryOf = (g, exercise) => g.doc?.entries?.[exercise._s];

function sessionHead(g, slot, number) {
  const entry = g.doc?.entries?.[slot];
  const muscles = entry?.values?.muscles || [];
  const name = g.slots.length > 1 ? (muscles.join(' · ') || t('habits.session_n', { n: number })) : '';
  const note = entry?.note || '';
  if (!name && !note) return '';
  return `<div class="gym-session" data-slot="${slot}">${name ? `<p class="gym-session-name">${esc(name)}</p>` : ''}${note ? `<p class="gym-session-note">${esc(note)}</p>` : ''}</div>`;
}

function gymHtml(g) {
  const many = g.slots.length > 1;
  const list = g.exercises.map((exercise, index) => {
    const muscles = many ? null : entryOf(g, exercise)?.values?.muscles;
    const head = index === 0 || g.exercises[index - 1]._s !== exercise._s ? sessionHead(g, exercise._s, g.slots.indexOf(exercise._s) + 1) : '';
    return `${head}<article class="gym-ex${index === g.active ? ' active' : ''}" data-ex="${index}">
      <header class="gym-ex-head">
        <h3 class="gym-ex-name">${esc(exercise.name)}</h3>
        ${exerciseMeta(exercise, muscles) ? `<p class="gym-ex-meta">${esc(exerciseMeta(exercise, muscles))}</p>` : ''}
        <p class="gym-prev" hidden><span class="gym-prev-when"></span><span class="gym-prev-vals"></span></p>
        <p class="gym-best" hidden></p>
        <p class="gym-hint" hidden><span class="gym-hint-text"></span><button type="button" class="gym-text-btn" data-gym="hint">${esc(t('habits.use_hint'))}</button></p>
      </header>
      ${setsHtml(g, index)}
      ${index === g.active ? editorHtml(g) : `<button type="button" class="btn gym-ex-open" data-gym="activate">${esc(t('habits.log_sets_here'))}</button>`}
    </article>`;
  }).join('');
  const empty = g.exercises.length ? '' : `${g.slots.map((slot, at) => sessionHead(g, slot, at + 1)).join('')}<p class="gym-empty">${esc(t('habits.no_exercises_day'))}</p>`;
  return `${list || empty}
    <div class="k-entry-row gym-add">
      <input type="text" class="settings-input" data-k="exercise" role="combobox" aria-autocomplete="list" aria-expanded="false" spellcheck="false" autocomplete="off" aria-label="${esc(t('habits.exercise'))}" placeholder="${esc(t('habits.add_exercise_placeholder'))}">
      <button type="button" class="btn primary" data-gym="add">${esc(t('habits.add_exercise'))}</button>
    </div>`;
}

function shownValue(key, value) {
  if (value === '?') return '?';
  if (value == null || value === '') return '';
  return key === 'rest' ? mmss(value) : num(value);
}

function paintSteppers(g) {
  g.host.querySelectorAll('.k-stepper').forEach(stepper => {
    const { key, side } = stepper.dataset;
    const value = side ? g.draft[side][key] : g.draft[key];
    const input = stepper.querySelector('input');
    if (document.activeElement !== input) input.value = shownValue(key, value);
    stepper.querySelector('[data-d="-1"]').disabled = !isNum(value) || value <= 0;
  });
}

const stepOf = (g, key) => key === 'weight' ? (g.habit.fields?.weight_step || (g.draft.unit === 'kg' ? 2.5 : 5)) : key === 'rest' ? 15 : 1;

// what a stepper's text means: null is empty, '?' unknown, undefined unreadable
export function readStepper(key, text) {
  const raw = formatDecimal(String(text || '').trim());
  if (!raw) return null;
  if (raw === '?') return '?';
  if (key === 'rest') {
    const match = raw.match(/^(\d+)(?::(\d{1,2}))?$/);
    return match ? (match[2] ? Number(match[1]) * 60 + Number(match[2]) : Number(match[1])) : undefined;
  }
  const value = Number(raw);
  if (!Number.isFinite(value) || value < 0) return undefined;
  return key === 'weight' ? value : Math.round(value);
}

function setDraft(g, key, side, value) {
  g.touched = true;
  if (!side) { g.draft[key] = value; return; }
  g.draft[side][key] = value;
  if (g.draft.sides === 'same') g.draft.R[key] = value;
}

const historyKey = exercise => `${exercise.name.trim().toLowerCase()}|${JSON.stringify(exercise.setup || {})}`;

// set n starts from last time's set n (recognition over recall), else the set before it
function nextDraft(g) {
  const exercise = g.exercises[g.active];
  const unit = exercise?.unit || g.habit.fields?.units?.weight || 'lb';
  const groups = exercise ? groupSets(exercise.sets) : [];
  const last = exercise && g.history.get(historyKey(exercise))?.last;
  const before = last ? groupSets(last.sets) : [];
  const from = before[groups.length] || groups[groups.length - 1] || before[before.length - 1];
  if (from) return draftFrom(from, unit, true);
  const blank = () => ({ weight: null, reps: DEFAULT_REPS, partial: 0, bad: 0 });
  return { sides: 'same', unit, assist: false, L: blank(), R: blank(), rir: null, type: 'working', status: 'done', rest: 120, tempo: '', note: '' };
}

async function loadHistory(g, exercise) {
  const key = historyKey(exercise);
  if (g.history.has(key)) return;
  g.history.set(key, null);
  const query = new URLSearchParams({ name: exercise.name, date_q: g.day });
  if (exercise.setup) query.set('setup', JSON.stringify(exercise.setup));
  try { g.history.set(key, await api(`/api/habits/${g.habit.id}/exercise?${query}`)); }
  catch { g.history.delete(key); return; }
  if (_gym !== g) return;
  if (!g.touched && !g.editing && g.exercises[g.active] === exercise) { g.draft = nextDraft(g); paint(g); }
  else paintHistory(g);
}

function paintHistory(g) {
  g.host.querySelectorAll('.gym-ex').forEach(node => {
    const exercise = g.exercises[Number(node.dataset.ex)];
    const found = exercise && g.history.get(historyKey(exercise));
    const unit = exercise?.unit || 'lb';
    const prev = node.querySelector('.gym-prev');
    if (found?.last) {
      const groups = groupSets(found.last.sets);
      const at = Math.max(0, Math.min(groupSets(exercise.sets).length, groups.length - 1));
      prev.querySelector('.gym-prev-when').textContent = t('habits.last_time_on', { date: formatCalendarDate(found.last.date, { month: 'short', day: 'numeric' }).toLowerCase() });
      prev.querySelector('.gym-prev-vals').textContent = setText(groups[at], unit);
      prev.hidden = false;
    }
    const records = found?.records || {};
    const tops = ['', 'L', 'R'].filter(side => records[side]?.heaviest).map(side => `${side ? `${side} ` : ''}${sideText(records[side].heaviest, unit)}`);
    const best = node.querySelector('.gym-best');
    if (tops.length) { best.textContent = t('habits.heaviest_n', { n: tops.join(' · ') }); best.hidden = false; }
    const hint = node.querySelector('.gym-hint');
    if (found?.hint?.length && node.classList.contains('active')) {
      hint.querySelector('.gym-hint-text').textContent = t('habits.next_step_n', {
        n: found.hint.map(step => `${step.side ? `${step.side} ` : ''}${loadText(step.to, step.unit, unit)}`).join(' · ') });
      hint.hidden = false;
    }
  });
}

function paint(g, focus) {
  if (!g.host.isConnected) return;
  g.host.innerHTML = gymHtml(g);
  initKokuenPrimitives(g.host);
  g.host.querySelectorAll('.custom-select').forEach(initCustomDropdown);
  const top = g.host.querySelector(`.k-number-row-scale [data-value="${RIR_TOP}"]`);
  if (top) top.textContent = `${RIR_TOP}+`;
  paintSteppers(g);
  paintHistory(g);
  const note = g.host.querySelector('.gym-note');
  if (note) { note.style.height = 'auto'; note.style.height = `${note.scrollHeight}px`; }
  if (focus) g.host.querySelector(focus)?.focus({ preventScroll: true });
}

// saved in the background (doherty): the screen already shows it; a failure rolls it back
function store(g, before, focus) {
  const day = g.day;
  const doc = structuredClone(g.habit.days?.[day] || { v: 2, entries: [] });
  // every session writes back to its own entry; a session emptied out keeps its place
  for (const slot of new Set([...g.slots, ...g.exercises.map(exercise => exercise._s)])) {
    const entry = doc.entries[slot] || (doc.entries[slot] = { values: {} });
    const exercises = g.exercises.filter(exercise => exercise._s === slot && exercise.sets.length).map(({ keep, _s, ...exercise }) => exercise);
    entry.values = { ...entry.values, exercises };
    if (!exercises.length) delete entry.values.exercises;
  }
  const only = doc.entries[0];
  const empty = doc.entries.length === 1 && !Object.keys(only.values || {}).length && !only.note;
  return g.save(empty ? null : doc).then(result => {
    g.habit.days = { ...(g.habit.days || {}), [day]: result?.data };
    const strip = g.host.closest('.habit-detail')?.querySelector(`.habit-day[data-toggle="${day}"]`);
    strip?.classList.toggle('done', !empty);
    strip?.setAttribute('aria-pressed', String(!empty));
  }).catch(error => {
    if (_gym !== g) return;
    g.exercises = before; g.undo = null;
    paint(g, focus);
    toast(error.message === 'Failed to fetch' ? t('habits.save_offline') : (error.message || t('habits.save_failed')), 'error');
  });
}

function startRest(g, seconds) {
  clearInterval(g.restTimer);
  g.rest = seconds > 0 ? { left: seconds } : null;
  if (!g.rest) return;
  g.restTimer = setInterval(() => {
    if (_gym !== g || !g.rest) { clearInterval(g.restTimer); return; }
    g.rest.left -= 1;
    const time = g.host.querySelector('.gym-rest-time');
    if (time) time.textContent = g.rest.left > 0 ? mmss(g.rest.left) : t('habits.rest_done');
    if (g.rest.left <= -3) {
      clearInterval(g.restTimer); g.rest = null;
      const box = g.host.querySelector('.gym-rest');
      if (box) box.hidden = true;
    }
  }, 1000);
}

function announce(message) {
  let live = document.getElementById('gym-announce');
  if (!live) {
    live = document.createElement('p');
    live.id = 'gym-announce'; live.className = 'sr-only'; live.setAttribute('role', 'status');
    document.body.append(live);
  }
  live.textContent = message;
}

// the row that just changed offers undo for a few seconds, then goes back to its edit button
function offerUndo(g, ex, group, before, message) {
  clearTimeout(g.undoTimer);
  g.undo = { ex, group, before };
  announce(message);
  g.undoTimer = setTimeout(() => {
    if (_gym !== g) return;
    const had = document.activeElement?.dataset?.gym === 'undo';
    g.undo = null;
    const button = g.host.querySelector('.gym-undo');
    if (button) button.outerHTML = editButton(group);
    if (had) g.host.querySelector('.gym-log-btn')?.focus();
  }, UNDO_MS);
}

function logSet(g) {
  const exercise = g.exercises[g.active];
  const before = structuredClone(g.exercises);
  const sets = draftSets(g.draft);
  let group, message;
  if (g.editing) {
    const { at } = g.editing;
    // the original words stay with the row they came from
    const raw = exercise.sets.slice(at[0], at[at.length - 1] + 1).find(one => one.raw)?.raw;
    if (raw) sets[0].raw = raw;
    exercise.sets.splice(at[0], at.length, ...sets);
    group = g.editing.group;
    message = t('habits.set_n_saved', { n: group + 1 });
    g.editing = null;
  } else {
    exercise.sets.push(...sets);
    group = groupSets(exercise.sets).length - 1;
    message = t('habits.set_n_logged', { n: group + 1 });
    startRest(g, sets[0].rest || 0);
  }
  if (sets[0].unit) exercise.unit = sets[0].unit;
  g.touched = false;
  g.draft = nextDraft(g);
  offerUndo(g, g.active, group, before, message);
  paint(g, '.gym-log-btn');
  store(g, before, '.gym-log-btn');
}

function addExercise(g) {
  const input = g.host.querySelector('.gym-add input');
  const name = textIn(input);
  if (!name) { input?.focus(); return; }
  const known = g.exercises.findIndex(exercise => exercise.name.toLowerCase() === name.toLowerCase());
  if (known >= 0) g.active = known;
  else {
    // a new exercise joins the session in use, right after its last exercise
    const slot = g.exercises[g.active]?._s ?? g.slots[g.slots.length - 1];
    const last = g.exercises.map(exercise => exercise._s).lastIndexOf(slot);
    const at = last >= 0 ? last + 1 : g.exercises.length;
    g.exercises.splice(at, 0, { name, sets: [], _s: slot });
    g.active = at;
  }
  g.editing = null; g.touched = false;
  g.draft = nextDraft(g);
  paint(g, '.gym-log-btn');
  loadHistory(g, g.exercises[g.active]);
}

function onClick(g, event) {
  const host = g.host;
  const button = event.target.closest('[data-gym], .k-stepper button');
  if (!button || !host.contains(button)) return;
  if (button.closest('.k-stepper')) {
    const { key, side } = button.closest('.k-stepper').dataset;
    const current = side ? g.draft[side][key] : g.draft[key];
    const next = Math.max(0, (isNum(current) ? current : 0) + stepOf(g, key) * Number(button.dataset.d));
    setDraft(g, key, side, Math.round(next * 100) / 100);
    paintSteppers(g);
    return;
  }
  const act = button.dataset.gym;
  const node = button.closest('.gym-ex');
  const index = node ? Number(node.dataset.ex) : g.active;
  if (act === 'log') logSet(g);
  else if (act === 'add') addExercise(g);
  else if (act === 'activate') {
    g.active = index; g.editing = null; g.touched = false; g.draft = nextDraft(g);
    paint(g, '.gym-log-btn');
  } else if (act === 'edit') {
    const group = Number(button.closest('.gym-set').dataset.group);
    const found = groupSets(g.exercises[index].sets)[group];
    g.active = index; g.editing = { group, at: found.at };
    g.draft = draftFrom(found, g.exercises[index].unit || 'lb', false);
    paint(g, '.gym-editor .k-stepper input');
  } else if (act === 'cancel') {
    g.editing = null; g.touched = false; g.draft = nextDraft(g);
    paint(g, '.gym-log-btn');
  } else if (act === 'undo' && g.undo) {
    clearTimeout(g.undoTimer);
    const before = structuredClone(g.exercises);
    g.exercises = g.undo.before; g.undo = null;
    clearInterval(g.restTimer); g.rest = null;
    g.touched = false; g.draft = nextDraft(g);
    announce(t('habits.undone'));
    paint(g, '.gym-log-btn');
    store(g, before, '.gym-log-btn');
  } else if (act === 'more') {
    g.more = button.getAttribute('aria-expanded') !== 'true';
    try { localStorage.setItem('alles-gym-more', g.more ? '1' : '0'); } catch { /* the choice just isn't kept */ }
    button.setAttribute('aria-expanded', String(g.more));
    host.querySelector('.gym-details').hidden = !g.more;
  } else if (act === 'rest-more' && g.rest) {
    g.rest.left += 15;
    host.querySelector('.gym-rest-time').textContent = mmss(Math.max(0, g.rest.left));
  } else if (act === 'rest-skip') {
    clearInterval(g.restTimer); g.rest = null;
    host.querySelector('.gym-rest').hidden = true;
    host.querySelector('.gym-log-btn')?.focus();
  } else if (act === 'hint') {
    // a hint fills the weights when asked, never on its own
    for (const step of g.history.get(historyKey(g.exercises[g.active]))?.hint || []) {
      for (const side of step.side ? [step.side] : ['L', 'R']) g.draft[side].weight = step.to;
      if (step.unit) g.draft.unit = step.unit;
    }
    g.touched = true;
    paint(g, '.gym-log-btn');
  }
}

function onChange(g, event) {
  const target = event.target.closest('[data-gym]');
  if (!target) return;
  const act = target.dataset.gym;
  if (act === 'sides') {
    const value = event.detail?.value;
    if (!value) return;
    if (value === 'split' && g.draft.sides === 'same') g.draft.R = { ...g.draft.L };
    g.draft.sides = value; g.touched = true;
    g.host.querySelector('.gym-editor').dataset.sides = value;
    paintSteppers(g);
  } else if (act === 'unit') {
    const value = event.detail?.value;
    if (!value || value === g.draft.unit) return;
    for (const side of ['L', 'R']) {
      const weight = g.draft[side].weight;
      if (isNum(weight)) g.draft[side].weight = value === 'kg' ? Math.round(weight * KG * 2) / 2 : Math.round(weight / KG);
    }
    g.draft.unit = value; g.touched = true;
    paintSteppers(g);
  } else if (act === 'rir' && event.detail) { g.draft.rir = Number(event.detail.value); g.touched = true; }
  else if (act === 'type' || act === 'status') { g.draft[act] = target.value; g.touched = true; }
}

function onInput(g, event) {
  const input = event.target;
  const stepper = input.closest('.k-stepper');
  if (stepper) {
    const value = readStepper(stepper.dataset.key, input.value);
    if (value === undefined) { input.setAttribute('aria-invalid', 'true'); return; }
    input.removeAttribute('aria-invalid');
    setDraft(g, stepper.dataset.key, stepper.dataset.side, value);
    stepper.querySelector('[data-d="-1"]').disabled = !isNum(value) || value <= 0;
  } else if (input.dataset.gym === 'tempo') { g.draft.tempo = input.value.trim(); g.touched = true; }
  else if (input.dataset.gym === 'note') {
    g.draft.note = input.value; g.touched = true;
    input.style.height = 'auto'; input.style.height = `${input.scrollHeight}px`;
  }
}

// one set of listeners per host; they read the current state from _gym
function wireGym(host, names) {
  if (host.dataset.gymWired === '1') return;
  host.dataset.gymWired = '1';
  host.addEventListener('click', event => _gym?.host === host && onClick(_gym, event));
  host.addEventListener('change', event => _gym?.host === host && onChange(_gym, event));
  host.addEventListener('input', event => _gym?.host === host && onInput(_gym, event));
  host.addEventListener('focusin', event => { if (event.target.matches('.k-stepper input')) event.target.select(); });
  host.addEventListener('focusout', event => { if (event.target.matches('.k-stepper input') && _gym?.host === host) queueMicrotask(() => paintSteppers(_gym)); });
  host.addEventListener('keydown', event => {
    if (event.key === 'Enter' && event.target.matches('.gym-add input') && !event.defaultPrevented && _gym?.host === host) { event.preventDefault(); addExercise(_gym); }
  });
  wireExercises(host, names);
}

// the workout habit's log for one day, drawn into host. save(doc) stores the day (null clears it)
export function renderGym(host, habit, day, { save }) {
  // the same day again keeps the draft, unless its details only just arrived (an older day)
  const doc = habit.days?.[day];
  const same = _gym && _gym.habit.id === habit.id && _gym.day === day && !(doc && !_gym.doc && !_gym.exercises.length);
  const entries = doc?.entries || [];
  const workouts = entries.map((one, at) => (one.values?.exercises ? at : -1)).filter(at => at >= 0);
  const slots = workouts.length ? workouts : [0];
  let more = true;
  try { more = localStorage.getItem('alles-gym-more') !== '0'; } catch { /* stays open */ }
  if (!same && _gym) { clearInterval(_gym.restTimer); clearTimeout(_gym.undoTimer); }
  const g = same ? Object.assign(_gym, { host, habit, save, doc, slots: [...new Set([...slots, ..._gym.slots])].sort((a, b) => a - b) }) : {
    host, habit, day, save, doc, more, slots,
    exercises: slots.flatMap(slot => structuredClone(entries[slot]?.values?.exercises || []).map(exercise => ({ ...exercise, _s: slot }))),
    history: new Map(), editing: null, undo: null, rest: null, touched: false,
  };
  if (!same) { g.active = Math.max(0, g.exercises.length - 1); g.draft = nextDraft(g); }
  _gym = g;
  host.classList.add('gym');
  paint(g);
  wireGym(host, habit.exercises || []);
  g.exercises.forEach(exercise => loadHistory(g, exercise));
  return g;
}

// ── every other kind (track E1): one day log built from the kind's fields ────────────────────
// GET /api/habits/kinds names each kind's fields; a field shows when it's on by default or the
// habit switched it on. each type takes one kit control: a number is the stepper, a rating the
// number row, 2 or 3 options a pill switch, 4 or more the dropdown, yes or no a pill switch, a time
// or a date the date field, words a field. one entry a day for "single" kinds, else one a session.
const SKIP = new Set(['rows', 'files', 'exercises']);
const MEASURE_UNITS = { distance: ['km', 'mi'], body: ['cm', 'in'], weight: ['lb', 'kg'], height: ['cm', 'in'], liquid: ['ml', 'floz', 'glasses'], temperature: ['c', 'f'] };
const UNIT_TEXT = { floz: 'fl oz', c: '°c', f: '°f' };
let _kinds = null;
let _dlog = null;

export const hasDayLog = habit => !!habit && habit.kind !== 'check' && habit.kind !== 'workout' && !LOGGED.has(habit.kind);

export function loadKinds() {
  _kinds ||= api('/api/habits/kinds').then(data => data.kinds).catch(error => { _kinds = null; throw error; });
  return _kinds;
}

// a field's name: its translation, else its key in plain words
export function fieldLabel(key) {
  const name = `habits.field_${key}`;
  const found = t(name);
  return found === name ? key.replace(/_/g, ' ') : found;
}
function optionLabel(value) {
  const name = `habits.option_${value}`;
  const found = t(name);
  return found === name ? value.replace(/_/g, ' ') : found;
}

export function shownFields(spec, habit) {
  const config = habit.fields || {};
  const on = new Set(config.on || []);
  const hidden = new Set(config.hidden || []);
  return [...(spec?.fields || []), ...(config.custom || [])]
    .filter(field => !SKIP.has(field.type) && !hidden.has(field.key) && (field.on || on.has(field.key)));
}

// one pick: a pill switch for 2 or 3 options, the dropdown for more (ux laws: a list that can
// grow is never a wall of buttons)
export function choiceHtml(key, options, picked, labelledBy) {
  if (options.length <= 3) {
    const buttons = options.map(([value, text]) => pillButton(value, text, value === picked)).join('');
    return `<div class="k-pill-switch" data-kokuen-choice="switch" data-f="${esc(key)}" aria-labelledby="${labelledBy}">${buttons}</div>`;
  }
  return `<div class="settings-input custom-select" data-f="${esc(key)}" data-value="${esc(picked ?? '')}" data-options="${esc(options.map(([value, text]) => `${value}|${text}`).join(';'))}" aria-labelledby="${labelledBy}"></div>`;
}

function fieldHtml(field, value, d) {
  const id = `dlog-${++_sequence}`;
  const name = field.label || fieldLabel(field.key);
  // a measure's unit switch sits beside its name, as the gym logger's lb or kg does
  const row = (control, type = field.type, aside = '') => `<div class="dlog-row" data-type="${type}"><div class="dlog-label"><span id="${id}">${esc(name)}</span>${aside}</div><div class="dlog-control">${control}</div></div>`;
  const stepper = (key, shown, step = 1) => stepperHtml({ name, value: shown ?? '', step, min: field.min ?? 0, max: field.max ?? '', inputmode: field.whole || field.type === 'count' ? 'numeric' : 'decimal', attrs: `data-f="${esc(key)}"` });
  switch (field.type) {
    case 'number': case 'count': case 'minutes':
      return row(stepper(field.key, value, field.type === 'minutes' ? 5 : 1));
    case 'measure': {
      const units = MEASURE_UNITS[field.measure] || [];
      const unit = value?.unit || d.units?.[field.measure] || units[0];
      return row(stepper(field.key, value?.value), field.type, units.length > 1 ? choiceHtml(`${field.key}.unit`, units.map(u => [u, UNIT_TEXT[u] || u]), unit, id) : '');
    }
    case 'rating':
      return row(`<div class="k-number-row" data-kokuen-choice="rating" data-f="${esc(field.key)}" data-min="1" data-max="${field.max || d.scale || 5}" data-value="${value ?? ''}" aria-label="${esc(name)}"></div>`);
    case 'yesno':
      return row(choiceHtml(field.key, [['yes', t('common.yes')], ['no', t('common.no')]], value === true ? 'yes' : value === false ? 'no' : null, id));
    case 'choice':
      return row(choiceHtml(field.key, field.options.map(option => [option, optionLabel(option)]), value, id));
    case 'clock':
      return row(`<div class="date-input" data-type="due" data-f="${esc(field.key)}" data-value="${value ? `${d.day}T${value}` : ''}" aria-labelledby="${id}"></div>`);
    case 'date':
      return row(`<div class="date-input" data-type="date" data-f="${esc(field.key)}" data-value="${esc(value || '')}" aria-labelledby="${id}"></div>`);
    case 'sets': {
      const first = Array.isArray(value) ? value[0] : null;
      const sets = stepperHtml({ name: t('habits.sets'), value: first?.count ?? 1, min: 1, max: 100, inputmode: 'numeric', attrs: `data-f="${esc(field.key)}.count"` });
      return `${row(stepper(`${field.key}.reps`, first?.reps), 'count')}<div class="dlog-row" data-type="count"><div class="dlog-label"><span>${esc(t('habits.sets'))}</span></div><div class="dlog-control">${sets}</div></div>`;
    }
    default: {
      const text = Array.isArray(value) ? value.map(item => item?.text ?? item?.item ?? item).join(', ') : value?.text ?? value ?? '';
      return row(`<input type="text" class="settings-input" data-f="${esc(field.key)}" autocomplete="off" value="${esc(text)}" aria-labelledby="${id}">`, 'text');
    }
  }
}

function readNumber(host, key) {
  const raw = formatDecimal(String(host.querySelector(`.k-stepper[data-f="${CSS.escape(key)}"] input`)?.value ?? '').trim());
  if (!raw) return null;
  if (raw === '?') return '?';
  const value = Number(raw);
  if (!Number.isFinite(value)) throw new Error(t('habits.log_bad_number'));
  return value;
}

function pickOf(host, key) {
  const node = host.querySelector(`[data-f="${CSS.escape(key)}"]`);
  if (!node) return null;
  if (node.matches('.custom-select')) return node.dataset.value || null;
  if (node.matches('.k-number-row')) return node.querySelector('[aria-checked="true"]')?.dataset.value ?? (node.dataset.value || null);
  return node.querySelector('[aria-checked="true"]')?.dataset.value ?? null;
}

// the values the form holds, in the shapes services/habit_kinds.py stores
export function collectDay(host, fields) {
  const values = {};
  for (const field of fields) {
    const key = field.key;
    let value = null;
    if (['number', 'count', 'minutes'].includes(field.type)) value = readNumber(host, key);
    else if (field.type === 'measure') {
      const amount = readNumber(host, key);
      if (amount != null) value = { value: amount, unit: pickOf(host, `${key}.unit`) || (MEASURE_UNITS[field.measure] || [])[0] };
    } else if (field.type === 'rating') { const pick = pickOf(host, key); value = pick == null ? null : Number(pick); }
    else if (field.type === 'choice') value = pickOf(host, key);
    else if (field.type === 'yesno') { const pick = pickOf(host, key); value = pick == null ? null : pick === 'yes'; }
    else if (field.type === 'clock') value = (host.querySelector(`[data-f="${CSS.escape(key)}"]`)?.dataset.value || '').split('T')[1]?.slice(0, 5) || null;
    else if (field.type === 'date') value = host.querySelector(`[data-f="${CSS.escape(key)}"]`)?.dataset.value?.slice(0, 10) || null;
    else if (field.type === 'sets') {
      const reps = readNumber(host, `${key}.reps`);
      if (reps != null) value = [{ reps, count: readNumber(host, `${key}.count`) || 1, status: 'done' }];
    } else {
      const text = textIn(host.querySelector(`input[data-f="${CSS.escape(key)}"]`));
      if (text) {
        const parts = text.split(',').map(part => part.trim()).filter(Boolean);
        value = field.type === 'tags' ? parts : field.type === 'people' ? parts.map(part => ({ text: part }))
          : field.type === 'checklist' ? parts.map(item => ({ item, done: true })) : field.type === 'link' ? { text } : text;
      }
    }
    if (value != null && value !== '') values[key] = value;
  }
  return values;
}

// "amount 4 · mood 4 · felt fine", read off the same fields the form shows
export function entryText(entry, fields) {
  const bits = [];
  for (const field of fields) {
    const value = entry.values?.[field.key];
    if (value == null) continue;
    let shown;
    if (field.type === 'measure') shown = `${value.value === '?' ? '?' : num(value.value)} ${UNIT_TEXT[value.unit] || value.unit}`;
    else if (field.type === 'minutes') shown = value === '?' ? '?' : durationText(value);
    else if (field.type === 'yesno') shown = t(value ? 'common.yes' : 'common.no');
    else if (field.type === 'choice') shown = optionLabel(value);
    else if (field.type === 'date') shown = formatCalendarDate(value, { month: 'short', day: 'numeric', year: 'numeric' }).toLowerCase();
    else if (field.type === 'sets') shown = value.map(one => `${num(one.reps ?? 0)}${(one.count || 1) > 1 ? ` × ${num(one.count)}` : ''}`).join(', ');
    else if (Array.isArray(value)) shown = value.map(item => item?.text ?? item?.item ?? item).join(', ');
    else if (typeof value === 'object') shown = value.text ?? '';
    else shown = typeof value === 'number' ? num(value) : String(value);
    bits.push(`${field.label || fieldLabel(field.key)} ${shown}`);
  }
  if (entry.note) bits.push(entry.note);
  return bits.join(' · ');
}

function dayHtml(d) {
  const { entries, fields, editing } = d;
  const list = entries.length ? `<ol class="dlog-entries" aria-label="${esc(t('habits.logged_entries'))}">${entries.map((entry, at) => `<li class="dlog-entry${editing === at ? ' is-editing' : ''}" data-at="${at}">
      <span class="dlog-entry-text">${esc(entryText(entry, fields) || t('habits.done_no_details'))}</span>
      <button type="button" class="icon-btn" data-dlog="edit" aria-label="${esc(t('habits.edit_entry_n', { n: at + 1 }))}">${_si('edit')}</button></li>`).join('')}</ol>` : '';
  const from = editing != null ? entries[editing] : d.single && entries.length ? entries[0] : d.prefill;
  const noteId = `dlog-${++_sequence}`;
  const label = editing != null || (d.single && entries.length) ? 'habits.save_entry' : 'habits.log_entry';
  return `${list}<section class="dlog-form" aria-label="${esc(t('habits.log_details'))}">
      ${fields.map(field => fieldHtml(field, from?.values?.[field.key], d)).join('')}
      <div class="dlog-row" data-type="text"><div class="dlog-label"><label for="${noteId}">${esc(t('habits.note'))}</label></div><div class="dlog-control"><textarea class="settings-input dlog-note" id="${noteId}" rows="1">${esc(editing != null ? from?.note || '' : '')}</textarea></div></div>
      <div class="dlog-actions">${editing != null ? `<button type="button" class="btn" data-dlog="cancel">${esc(t('common.cancel'))}</button>` : ''}<button type="button" class="btn primary dlog-log" data-dlog="log">${esc(t(label))}</button></div>
    </section>`;
}

function paintDay(d, focus) {
  if (!d.host.isConnected) return;
  d.host.innerHTML = dayHtml(d);
  initKokuenPrimitives(d.host);
  d.host.querySelectorAll('.custom-select').forEach(initCustomDropdown);
  initDatePickers(d.host);
  if (focus) d.host.querySelector(focus)?.focus({ preventScroll: true });
}

// saved in the background like the gym logger: the list shows it at once, a failure rolls back
function logDay(d) {
  let values;
  try { values = collectDay(d.host, d.fields); } catch (error) { toast(error.message, 'error'); return; }
  const note = textIn(d.host.querySelector('.dlog-note'));
  const before = structuredClone(d.entries);
  const at = d.editing ?? (d.single && d.entries.length ? 0 : d.entries.length);
  const { note: _old, ...kept } = d.entries[at] || {};
  d.entries[at] = { ...kept, values, ...(note ? { note } : {}) };
  d.editing = null;
  d.prefill = d.entries[d.entries.length - 1];
  paintDay(d, '.dlog-log');
  announce(t('habits.entry_logged'));
  d.save({ v: 2, entries: d.entries }).then(result => {
    d.habit.days = { ...(d.habit.days || {}), [d.day]: result?.data };
    const strip = d.host.closest('.habit-detail')?.querySelector(`.habit-day[data-toggle="${d.day}"]`);
    strip?.classList.add('done');
    strip?.setAttribute('aria-pressed', 'true');
  }).catch(error => {
    if (_dlog !== d) return;
    d.entries = before;
    paintDay(d, '.dlog-log');
    toast(error.message === 'Failed to fetch' ? t('habits.save_offline') : (error.message || t('habits.save_failed')), 'error');
  });
}

function wireDay(host) {
  if (host.dataset.dlogWired === '1') return;
  host.dataset.dlogWired = '1';
  host.addEventListener('click', event => {
    const d = _dlog;
    const button = event.target.closest('[data-dlog]');
    if (!d || d.host !== host || !button) return;
    const act = button.dataset.dlog;
    if (act === 'log') logDay(d);
    else if (act === 'edit') { d.editing = Number(button.closest('.dlog-entry').dataset.at); paintDay(d, '.dlog-form input, .dlog-form [tabindex="0"]'); }
    else if (act === 'cancel') { d.editing = null; paintDay(d, '.dlog-log'); }
  });
}

// the newest entry on or before this day: the form starts from it, so "same as last time" is one
// tap on log
function lastEntry(habit, day) {
  for (const other of Object.keys(habit.days || {}).filter(one => one <= day).sort().reverse()) {
    const entries = habit.days[other]?.entries || [];
    if (entries.length) return entries[entries.length - 1];
  }
  return null;
}

// one habit's day log drawn into host. save(doc) stores the day
export async function renderDayLog(host, habit, day, { save }) {
  const spec = (await loadKinds())?.[habit.kind];
  const d = {
    host, habit, day, save, editing: null,
    entries: structuredClone(habit.days?.[day]?.entries || []),
    single: !!spec?.single, scale: habit.fields?.scale, units: habit.fields?.units,
    fields: shownFields(spec, habit),
    prefill: lastEntry(habit, day),
  };
  _dlog = d;
  host.classList.add('dlog');
  paintDay(d);
  wireDay(host);
  return d;
}

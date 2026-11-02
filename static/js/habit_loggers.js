// a day's log for habits that record more than "done": sets and weights, pages, minutes, counts.
// the server checks the same shapes (services/habit_kinds.py). weights are pounds, as the owner
// logs them: dumbbells per hand, machines per side. a set row without reps is 10, without sets 1.
import { formatCalendarDate, formatNumber, t, tp } from './i18n.js';
import { initKokuenPrimitives } from './kokuen.js?v=5';
import { getDropdownValues, initCustomDropdown } from './dropdown.js?v=217';
import { api, toast } from './util.js';
import { formatDecimal } from './liveformat.js';
import { clockText, initDatePickers } from './datepick.js';
import { stepperHtml, wireSteppers } from './stepper.js';
import { MEASURE_UNITS, fieldUnit, storedUnit, unitText } from './units.js';

const LOGGED = new Set(['workout', 'reading', 'count', 'duration', 'distance']);
const UNITS = new Set(['reps', 'steps', 'glasses', 'servings', 'words', 'cards', 'pages', 'chapters']);
const DEFAULT_REPS = 10;
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

// one option of a kit pill switch; kokuen gives it its role and the unpicked state
const pillButton = (value, text, on) => `<button type="button" data-value="${esc(value)}"${on ? ' aria-checked="true"' : ''}>${esc(text)}</button>`;
const textIn = input => String(input?.value ?? '').replace(/\s+/g, ' ').trim();

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

// ── the gym logger (track E3): the set logger screen the owner approved ────────────────────────
// a workout day is v2: entries[].values.exercises = [{name, setup, sets: [...]}]. a split set is
// two stored sets, side L then side R; the screen pairs them back into one row. every value keeps
// the unit it was entered in; the raw words from an import stay under their row, word for word.
const KG = 0.45359237;
const SET_TYPES = ['warmup', 'working', 'top', 'backoff', 'drop', 'failure'];
const SET_STATUSES = ['done', 'planned', 'attempted', 'failed', 'unfinished'];
const RIR_TOP = 5;
// an exercise's setup (services/habit_kinds.py LOAD_BASES and SETUP_KEYS): history and the last
// time line match it exactly, so a reverse grip press never reads as an overhand one
const LOAD_BASES = ['per_hand', 'per_side', 'stack', 'total', 'assist', 'bodyweight'];
const SETUP_TEXT = ['equipment', 'machine', 'grip', 'stance', 'angle', 'seat', 'pin'];
// the muscle groups a session can pick (several), plus any the owner already wrote their own way
const MUSCLES = ['chest', 'back', 'shoulders', 'biceps', 'triceps', 'forearms', 'core', 'glutes', 'quads', 'hamstrings', 'calves', 'full_body'];
const muscleLabel = value => { const key = `habits.muscle_${value}`; const found = t(key); return found === key ? value : found; };
const UNDO_MS = 8000;
let _gym = null;

const isNum = value => typeof value === 'number' && Number.isFinite(value);
// L and R as the reader's language writes them (左 and 右)
const sideShort = side => t(side === 'L' ? 'habits.side_l' : 'habits.side_r');
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
  return ['L', 'R'].filter(side => group[side]).map(side => `${sideShort(side)} ${sideText(group[side], shown)}`).join(' · ');
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
    if (one.partial) bits.push(side === 'both' ? t('habits.n_partial', { n: num(one.partial) }) : t('habits.n_partial_on', { n: num(one.partial), side: sideShort(side) }));
    if (one.bad) bits.push(side === 'both' ? t('habits.n_bad', { n: num(one.bad) }) : t('habits.n_bad_on', { n: num(one.bad), side: sideShort(side) }));
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

function exerciseMeta(exercise) {
  const setup = exercise.setup || {};
  const bits = [setup.basis ? t(`habits.basis_${setup.basis}`) : '', ...SETUP_TEXT.map(key => setup[key] || '')];
  return bits.filter(Boolean).join(' · ');
}

// a day can hold more than one session (back in the morning, arms later): each keeps its own
// entry, its muscle groups and its note, and the screen shows every one of them

// a session: its name when the day has several, its muscle groups (the dropdown's pick several,
// decision 0056) and its note, word for word
function sessionHead(g, slot, number) {
  const entry = g.doc?.entries?.[slot];
  const muscles = g.muscles[slot] ?? entry?.values?.muscles ?? [];
  const name = g.slots.length > 1 ? (muscles.map(muscleLabel).join(' · ') || t('habits.session_n', { n: number })) : '';
  const note = entry?.note || '';
  const id = `gym-muscles-${slot}`;
  const options = [...new Set([...MUSCLES, ...muscles])].map(value => `${value}|${muscleLabel(value)}`).join(';');
  return `<div class="gym-session" data-slot="${slot}">${name ? `<p class="gym-session-name">${esc(name)}</p>` : ''}
    <div class="gym-frow gym-muscles"><div class="gym-flabel"><span id="${id}">${esc(t('habits.muscle_groups'))}</span></div><div class="settings-input custom-select" data-gym="muscles" data-slot="${slot}" data-multiple="true" data-value="${esc(muscles.join(';'))}" data-options="${esc(options)}" aria-labelledby="${id}"></div></div>
    ${note ? `<p class="gym-session-note">${esc(note)}</p>` : ''}</div>`;
}

// the setup of the exercise being logged, set from the screen: load basis is a dropdown, the rest
// are words as the owner writes them (overhand, 30°, seat 4)
function setupHtml(exercise) {
  const setup = exercise.setup || {};
  const bases = [`none|${t('habits.setup_none')}`, ...LOAD_BASES.map(basis => `${basis}|${t(`habits.basis_${basis}`)}`)].join(';');
  return `<div class="gym-setup" id="gym-setup">
    <div class="gym-fields">
      <div class="gym-frow"><div class="gym-flabel"><span id="gym-basis-label">${esc(t('habits.setup_load'))}</span></div><div class="settings-input custom-select" data-gym="basis" data-value="${esc(setup.basis || 'none')}" data-options="${esc(bases)}" aria-labelledby="gym-basis-label"></div></div>
      ${SETUP_TEXT.map(key => `<div class="gym-frow"><div class="gym-flabel"><label for="gym-setup-${key}">${esc(t(`habits.setup_${key}`))}</label></div><input class="settings-input" id="gym-setup-${key}" data-setup="${key}" autocomplete="off" value="${esc(setup[key] || '')}"></div>`).join('')}
    </div>
    <div class="gym-actions"><button type="button" class="btn" data-gym="setup-cancel">${esc(t('common.cancel'))}</button><button type="button" class="btn primary" data-gym="setup-save">${esc(t('common.save'))}</button></div>
  </div>`;
}

function gymHtml(g) {
  const list = g.exercises.map((exercise, index) => {
    const head = index === 0 || g.exercises[index - 1]._s !== exercise._s ? sessionHead(g, exercise._s, g.slots.indexOf(exercise._s) + 1) : '';
    return `${head}<article class="gym-ex${index === g.active ? ' active' : ''}" data-ex="${index}">
      <header class="gym-ex-head">
        <h3 class="gym-ex-name">${esc(exercise.name)}</h3>
        ${exerciseMeta(exercise) ? `<p class="gym-ex-meta">${esc(exerciseMeta(exercise))}</p>` : ''}
        <p class="gym-prev" hidden><span class="gym-prev-when"></span><span class="gym-prev-vals"></span></p>
        <p class="gym-best" hidden></p>
        <p class="gym-hint" hidden><span class="gym-hint-text"></span><button type="button" class="gym-text-btn" data-gym="hint">${esc(t('habits.use_hint'))}</button></p>
        ${index === g.active ? `<button type="button" class="gym-text-btn gym-setup-btn" data-gym="setup" aria-expanded="${!!g.setupOpen}" aria-controls="gym-setup">${esc(t('habits.edit_setup'))}</button>` : ''}
      </header>
      ${index === g.active && g.setupOpen ? setupHtml(exercise) : ''}
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
    const tops = ['', 'L', 'R'].filter(side => records[side]?.heaviest).map(side => `${side ? `${sideShort(side)} ` : ''}${sideText(records[side].heaviest, unit)}`);
    const best = node.querySelector('.gym-best');
    if (tops.length) { best.textContent = t('habits.heaviest_n', { n: tops.join(' · ') }); best.hidden = false; }
    const hint = node.querySelector('.gym-hint');
    if (found?.hint?.length && node.classList.contains('active')) {
      hint.querySelector('.gym-hint-text').textContent = t('habits.next_step_n', {
        n: found.hint.map(step => `${step.side ? `${sideShort(step.side)} ` : ''}${loadText(step.to, step.unit, unit)}`).join(' · ') });
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
    if (slot in g.muscles) {
      if (g.muscles[slot].length) entry.values.muscles = g.muscles[slot];
      else delete entry.values.muscles;
    }
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

function saveSetup(g) {
  const exercise = g.exercises[g.active];
  if (!exercise) return;
  const before = structuredClone(g.exercises);
  const basis = g.host.querySelector('#gym-setup [data-gym="basis"]')?.dataset.value;
  const setup = basis && basis !== 'none' ? { basis } : {};
  for (const key of SETUP_TEXT) {
    const value = textIn(g.host.querySelector(`#gym-setup [data-setup="${key}"]`));
    if (value) setup[key] = value;
  }
  if (Object.keys(setup).length) exercise.setup = setup;
  else delete exercise.setup;
  g.setupOpen = false; g.touched = false;
  announce(t('habits.setup_saved'));
  // another setup is another history: its last time and hint load again
  g.draft = nextDraft(g);
  paint(g, '.gym-setup-btn');
  store(g, before, '.gym-setup-btn');
  loadHistory(g, exercise);
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
  } else if (act === 'setup') {
    g.setupOpen = !g.setupOpen;
    paint(g, g.setupOpen ? '#gym-setup [data-gym="basis"]' : '.gym-setup-btn');
  } else if (act === 'setup-cancel') {
    g.setupOpen = false;
    paint(g, '.gym-setup-btn');
  } else if (act === 'setup-save') saveSetup(g);
  else if (act === 'hint') {
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
  else if (act === 'muscles') {
    g.muscles[Number(target.dataset.slot)] = getDropdownValues(target);
    store(g, structuredClone(g.exercises), null);
  }
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
    // enter in a setup field saves the setup, escape closes it, as in any short form
    if (event.target.matches('#gym-setup input') && _gym?.host === host) {
      if (event.key === 'Enter') { event.preventDefault(); saveSetup(_gym); }
      else if (event.key === 'Escape') { event.preventDefault(); _gym.setupOpen = false; paint(_gym, '.gym-setup-btn'); }
    }
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
    history: new Map(), editing: null, undo: null, rest: null, touched: false, muscles: {}, setupOpen: false,
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
// GET /api/habits/kinds names each kind's fields; a field shows when it's on by default, the habit
// switched it on, or the day being shown already holds a value for it. each type takes one kit
// control: a number is the stepper (with its unit inside), a rating the number row (end words and
// a readout that names the pick), 2 or 3 options a pill switch, 4 or more the dropdown, yes or no
// a pill switch, a time of day the time field, a date the date field, rows a card per row, files
// an upload list, words a field. one entry a day for "single" kinds, else one a session.
const SKIP = new Set(['exercises']);
// a bedtime at noon or later is the night before the day it's logged on (the morning you woke)
const NIGHT = new Set(['bedtime', 'tried']);
// the words that name a rating's values ("4, good"); a key not listed reads awful to great
const SCALES = { energy: 'energy', calm_before: 'calm', calm_after: 'calm', focus: 'focus', craving: 'much', fatigue: 'much', mess: 'mess', effort: 'effort', severity: 'severity' };
const TEN = new Set(['effort', 'severity']);
let _kinds = null;
let _dlog = null;

// every habit but a plain check logs its day here, the gym logger aside
export const hasDayLog = habit => !!habit && habit.kind !== 'check' && habit.kind !== 'workout';

export function loadKinds() {
  _kinds ||= api('/api/habits/kinds').then(data => data.kinds).catch(error => { _kinds = null; throw error; });
  return _kinds;
}

// a field's name: its translation, else its key in plain words (a custom field brings its label)
export function fieldLabel(key) {
  const name = `habits.field_${key}`;
  const found = t(name);
  return found === name ? key.replace(/_/g, ' ') : found;
}
export function optionLabel(value) {
  const name = `habits.option_${value}`;
  const found = t(name);
  return found === name ? value.replace(/_/g, ' ') : found;
}

export function shownFields(spec, habit, entries = []) {
  const config = habit.fields || {};
  const on = new Set(config.on || []);
  const hidden = new Set(config.hidden || []);
  // a value already logged always shows, even for a field switched off since
  const used = new Set(entries.flatMap(entry => Object.keys(entry?.values || {})));
  return [...(spec?.fields || []), ...(config.custom || [])]
    .filter(field => !SKIP.has(field.type) && (used.has(field.key) || (!hidden.has(field.key) && (field.on || on.has(field.key)))));
}

// a number picked from a short range (effort 1 to 10) is a rating, so it takes the number row
const isRating = field => field.type === 'rating' || (field.type === 'number' && !!field.whole && (field.min ?? 0) >= 1 && field.max > 0 && field.max <= 10);
const ratingTop = (field, d) => field.type === 'rating' ? (field.max || d.scale || 5) : field.max;

// the word for each value of a rating, spread over its scale's words (a 1 to 4 row skips one)
export function scaleWords(key, top, low = 1) {
  const scale = SCALES[key] || 'good';
  const size = TEN.has(scale) ? 10 : 5;
  const count = top - low + 1;
  return Array.from({ length: count }, (_, at) => t(`habits.scale_${scale}_${count === 1 ? 1 : Math.round(at * (size - 1) / (count - 1)) + 1}`));
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

const dayBefore = day => {
  const [y, m, n] = day.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, n - 1)).toISOString().slice(0, 10);
};
// "oct 31, the night before" beside a bedtime of 11:30 pm logged on nov 1
export function nightText(value, day) {
  if (!/^\d{2}:\d{2}$/.test(String(value || '')) || value < '12:00') return '';
  return t('habits.night_before', { date: formatCalendarDate(dayBefore(day), { month: 'short', day: 'numeric' }).toLocaleLowerCase() });
}

// what a count habit counts ("glasses"), else the field's own unit
function unitOf(field, d, parent) {
  if (!parent && d.habit.kind === 'count' && field.key === 'amount' && d.habit.unit) {
    return UNITS.has(d.habit.unit) ? t(`habits.u_${d.habit.unit}`) : unitText(d.habit.unit);
  }
  return fieldUnit(field, parent || d.habit.kind);
}

function measureUnits(field, value, d) {
  const units = MEASURE_UNITS[field.measure] || [];
  const saved = storedUnit(value?.unit);
  const unit = units.includes(saved) ? saved : units.includes(d.units?.[field.measure]) ? d.units[field.measure] : units[0];
  return { units, unit };
}

function fieldHtml(field, value, d, parent = '') {
  const id = `dlog-${++_sequence}`;
  const name = field.label || fieldLabel(field.key);
  const row = (control, type = field.type, aside = '') => `<div class="dlog-row" data-type="${type}"><div class="dlog-label"><span id="${id}">${esc(name)}</span>${aside}</div><div class="dlog-control">${control}</div></div>`;
  const stepper = (key, shown, step = 1, unit = unitOf(field, d, parent)) => stepperHtml({ name, value: shown ?? '', step, min: field.min ?? 0, max: field.max ?? '', unit, inputmode: field.whole || field.type === 'count' ? 'numeric' : 'decimal', attrs: `data-f="${esc(key)}"` });
  if (isRating(field)) {
    const low = field.type === 'rating' ? 1 : field.min;
    const top = ratingTop(field, d);
    const words = scaleWords(field.key, top, low);
    const ends = words.map((word, at) => (at === 0 || at === words.length - 1 ? word : '')).join(',');
    return row(`<div class="k-number-row" data-kokuen-choice="rating" data-f="${esc(field.key)}" data-min="${low}" data-max="${top}" data-value="${value ?? ''}" data-labels="${esc(words.join(','))}" data-words="${esc(ends)}" aria-label="${esc(name)}"></div>`, 'rating');
  }
  switch (field.type) {
    case 'number': case 'count': case 'minutes': case 'seconds':
      return row(stepper(field.key, value, field.type === 'minutes' ? 5 : field.type === 'seconds' ? 15 : 1));
    case 'measure': {
      const { units, unit } = measureUnits(field, value, d);
      return row(stepper(field.key, value?.value, 1, unitText(unit)), field.type, units.length > 1 ? choiceHtml(`${field.key}.unit`, units.map(u => [u, unitText(u)]), unit, id) : '');
    }
    case 'yesno':
      return row(choiceHtml(field.key, [['yes', t('common.yes')], ['no', t('common.no')]], value === true ? 'yes' : value === false ? 'no' : null, id));
    case 'choice':
      return row(choiceHtml(field.key, field.options.map(option => [option, optionLabel(option)]), value, id));
    case 'clock': {
      const night = NIGHT.has(field.key) && !parent ? `<span class="dlog-aside" data-night="${esc(field.key)}">${esc(nightText(value, d.day))}</span>` : '';
      return row(`<div class="date-input" data-type="time" data-f="${esc(field.key)}" data-value="${esc(value && value !== '?' ? value : '')}" aria-labelledby="${id}"></div>${night}`);
    }
    case 'date':
      return row(`<div class="date-input" data-type="date" data-f="${esc(field.key)}" data-value="${esc(value || '')}" aria-labelledby="${id}"></div>`);
    case 'sets': {
      const first = Array.isArray(value) ? value[0] : null;
      const sets = stepperHtml({ name: t('habits.sets'), value: first?.count ?? 1, min: 1, max: 100, inputmode: 'numeric', attrs: `data-f="${esc(field.key)}.count"` });
      return `${row(stepper(`${field.key}.reps`, first?.reps, 1, ''), 'count')}<div class="dlog-row" data-type="count"><div class="dlog-label"><span>${esc(t('habits.sets'))}</span></div><div class="dlog-control">${sets}</div></div>`;
    }
    case 'rows':
      return `<div class="dlog-row" data-type="rows"><div class="dlog-label"><span id="${id}">${esc(name)}</span></div>
        <div class="dlog-control dlog-rows" data-f="${esc(field.key)}" role="group" aria-labelledby="${id}">${rowsInner(field, Array.isArray(value) ? value : [], d)}</div></div>`;
    case 'checklist':
      return `<div class="dlog-row" data-type="checklist"><div class="dlog-label"><span id="${id}">${esc(name)}</span></div>
        <div class="dlog-control dlog-checklist" data-f="${esc(field.key)}" role="group" aria-labelledby="${id}">${checklistInner(checklistSteps(value))}</div></div>`;
    case 'files':
      return `<div class="dlog-row" data-type="files"><div class="dlog-label"><span id="${id}">${esc(name)}</span></div>
        <div class="dlog-control dlog-files" data-f="${esc(field.key)}" role="group" aria-labelledby="${id}">${filesInner(Array.isArray(value) ? value : [])}</div></div>`;
    default: {
      const text = Array.isArray(value) ? value.map(item => item?.text ?? item?.item ?? item).join(', ') : value?.text ?? value ?? '';
      return row(`<input type="text" class="settings-input" data-f="${esc(field.key)}" autocomplete="off" value="${esc(text)}" aria-labelledby="${id}">`, 'text');
    }
  }
}

// rows (laps, climbs, naps): one card per row with the row's own fields, a side when the field
// has sides, and a remove button; a new row starts empty under the last one
function rowsInner(field, rows, d) {
  const cards = rows.map((one, at) => {
    const legend = `dlog-${++_sequence}`;
    const side = field.sides ? `<div class="dlog-row" data-type="choice"><div class="dlog-label"><span id="${legend}-side">${esc(t('habits.sides'))}</span></div><div class="dlog-control">${choiceHtml('side', [['', t('habits.side_both')], ['L', t('habits.left')], ['R', t('habits.right')]], one.side || '', `${legend}-side`)}</div></div>` : '';
    return `<div class="dlog-rowcard" data-scope role="group" aria-labelledby="${legend}">
      <div class="dlog-rowcard-head"><span id="${legend}">${esc(t('habits.row_n', { n: at + 1 }))}</span><button type="button" class="icon-btn" data-dlog="remove-row" aria-label="${esc(t('habits.remove_row_n', { n: at + 1 }))}">${_si('trash')}</button></div>
      <div class="dlog-rowcard-fields">${side}${field.columns.map(column => fieldHtml(column, one[column.key], d, field.key)).join('')}</div></div>`;
  }).join('');
  return `${cards}<button type="button" class="btn dlog-add-row" data-dlog="add-row">${_si('plus')} ${esc(t('habits.add_row'))}</button>`;
}

// a checklist value is its steps, each with its own state: { item, done }. the old field was one
// line of text, so a step left undone came back done (or lost) the next time it was logged
export function checklistSteps(value) {
  const list = Array.isArray(value) ? value : typeof value === 'string' ? value.split(',') : [];
  const seen = new Set();
  return list.map(step => typeof step === 'string' ? { item: step.trim(), done: true }
    : { item: String(step?.item ?? step?.text ?? '').trim(), done: step?.done !== false })
    .filter(step => step.item && !seen.has(step.item.toLowerCase()) && seen.add(step.item.toLowerCase()));
}

// what the list shows now: each step's box, plus anything typed in the new step field (done)
export function readChecklist(box) {
  const steps = [...box.querySelectorAll('.dlog-step')].map(step => ({
    item: step.dataset.item, done: step.querySelector('[role="checkbox"]')?.getAttribute('aria-checked') === 'true',
  }));
  const typed = textIn(box.querySelector('[data-dlog-step-new]'));
  return checklistSteps([...steps, ...typed.split(',')]);
}

function checklistInner(steps) {
  const items = steps.map(step => `<li class="dlog-step" data-item="${esc(step.item)}">
      <button type="button" class="dlog-step-check" role="checkbox" aria-checked="${step.done}" data-dlog="step" aria-label="${esc(step.item)}"></button>
      <span class="dlog-step-name" aria-hidden="true">${esc(step.item)}</span>
      <button type="button" class="icon-btn" data-dlog="remove-step" aria-label="${esc(t('habits.remove_step', { name: step.item }))}">${_si('close')}</button></li>`).join('');
  return `${items ? `<ul class="dlog-steps">${items}</ul>` : ''}<input type="text" class="settings-input dlog-step-new" data-dlog-step-new autocomplete="off" placeholder="${esc(t('habits.add_step'))}" aria-label="${esc(t('habits.add_step'))}">`;
}

function changeSteps(box, change) {
  const steps = change(readChecklist(box));
  box.innerHTML = checklistInner(steps);
  box.querySelector('[data-dlog-step-new]')?.focus();
}

// files (a practice recording): stored in the files app under habits/<habit>, listed by name
function filesInner(paths) {
  const list = paths.length ? `<ul class="dlog-file-list">${paths.map(path => `<li data-path="${esc(path)}"><span class="dlog-file-name">${esc(path.split('/').pop())}</span><button type="button" class="icon-btn" data-dlog="remove-file" aria-label="${esc(t('habits.remove_file', { name: path.split('/').pop() }))}">${_si('close')}</button></li>`).join('')}</ul>` : '';
  return `${list}<label class="btn dlog-add-file">${_si('plus')} ${esc(t('habits.add_file'))}<input type="file" class="sr-only" data-dlog="file"></label>`;
}

// the one node of a selector that belongs to this scope (the form, or one row's card), so a row's
// own "minutes" is never read as the day's
function own(scope, selector) {
  return [...scope.querySelectorAll(selector)].find(node => node.closest('[data-scope]') === scope) || null;
}

function readNumber(scope, key) {
  const raw = formatDecimal(String(own(scope, `.k-stepper[data-f="${CSS.escape(key)}"] input`)?.value ?? '').trim());
  if (!raw) return null;
  if (raw === '?') return '?';
  const value = Number(raw);
  if (!Number.isFinite(value)) throw new Error(t('habits.log_bad_number'));
  return value;
}

function pickOf(scope, key) {
  const node = own(scope, `[data-f="${CSS.escape(key)}"]`);
  if (!node) return null;
  if (node.matches('.custom-select')) return node.dataset.value || null;
  if (node.matches('.k-number-row')) return node.querySelector('[aria-checked="true"]')?.dataset.value ?? (node.dataset.value || null);
  return node.querySelector('[aria-checked="true"]')?.dataset.value ?? null;
}

function readRows(box, field) {
  return [...box.querySelectorAll(':scope > .dlog-rowcard')].map(card => {
    const values = collectDay(card, field.columns);
    const side = field.sides ? pickOf(card, 'side') : '';
    return side ? { ...values, side } : values;
  });
}

// the values the form holds, in the shapes services/habit_kinds.py stores
export function collectDay(scope, fields) {
  const values = {};
  for (const field of fields) {
    const key = field.key;
    let value = null;
    if (isRating(field)) { const pick = pickOf(scope, key); value = pick == null ? null : Number(pick); }
    else if (['number', 'count', 'minutes', 'seconds'].includes(field.type)) value = readNumber(scope, key);
    else if (field.type === 'measure') {
      const amount = readNumber(scope, key);
      if (amount != null) value = { value: amount, unit: pickOf(scope, `${key}.unit`) || (MEASURE_UNITS[field.measure] || [])[0] };
    } else if (field.type === 'choice') value = pickOf(scope, key);
    else if (field.type === 'yesno') { const pick = pickOf(scope, key); value = pick == null ? null : pick === 'yes'; }
    else if (field.type === 'clock') value = own(scope, `[data-f="${CSS.escape(key)}"]`)?.dataset.value || null;
    else if (field.type === 'date') value = own(scope, `[data-f="${CSS.escape(key)}"]`)?.dataset.value?.slice(0, 10) || null;
    else if (field.type === 'sets') {
      const reps = readNumber(scope, `${key}.reps`);
      if (reps != null) value = [{ reps, count: readNumber(scope, `${key}.count`) || 1, status: 'done' }];
    } else if (field.type === 'rows') {
      const box = own(scope, `.dlog-rows[data-f="${CSS.escape(key)}"]`);
      const rows = box ? readRows(box, field).filter(one => Object.keys(one).some(name => name !== 'side')) : [];
      value = rows.length ? rows : null;
    } else if (field.type === 'checklist') {
      const box = own(scope, `.dlog-checklist[data-f="${CSS.escape(key)}"]`);
      const steps = box ? readChecklist(box) : [];
      value = steps.length ? steps : null;
    } else if (field.type === 'files') {
      const box = own(scope, `.dlog-files[data-f="${CSS.escape(key)}"]`);
      const paths = box ? [...box.querySelectorAll('li[data-path]')].map(item => item.dataset.path) : [];
      value = paths.length ? paths : null;
    } else {
      const text = textIn(own(scope, `input[data-f="${CSS.escape(key)}"]`));
      if (text) {
        const parts = text.split(',').map(part => part.trim()).filter(Boolean);
        value = field.type === 'tags' ? parts : field.type === 'people' ? parts.map(part => ({ text: part }))
          : field.type === 'link' ? { text } : text;
      }
    }
    if (value != null && value !== '') values[key] = value;
  }
  return values;
}

const clockMinutes = value => /^\d{2}:\d{2}$/.test(String(value || '')) ? Number(value.slice(0, 2)) * 60 + Number(value.slice(3)) : null;

// "bedtime 11:30 pm · woke up 7:00 am · in bed 7 h 30 min · quality 4", read off the form's fields
export function entryText(entry, fields, kind = '') {
  const bits = [];
  for (const field of fields) {
    const value = entry.values?.[field.key];
    if (value == null) continue;
    const unit = value !== '?' && ['number', 'count', 'seconds'].includes(field.type) && !isRating(field) ? fieldUnit(field, kind) : '';
    let shown;
    if (field.type === 'measure') shown = `${value.value === '?' ? '?' : num(value.value)} ${unitText(value.unit)}`;
    else if (field.type === 'minutes') shown = value === '?' ? '?' : durationText(value);
    else if (field.type === 'clock') shown = value === '?' ? '?' : clockText(value);
    else if (field.type === 'yesno') shown = t(value ? 'common.yes' : 'common.no');
    else if (field.type === 'choice') shown = optionLabel(value);
    else if (field.type === 'date') shown = formatCalendarDate(value, { month: 'short', day: 'numeric', year: 'numeric' }).toLowerCase();
    else if (field.type === 'sets') shown = value.map(one => `${num(one.reps ?? 0)}${(one.count || 1) > 1 ? ` × ${num(one.count)}` : ''}`).join(', ');
    else if (field.type === 'rows') shown = value.map(one => [one.side ? sideShort(one.side) : '', entryText({ values: one }, field.columns, field.key)].filter(Boolean).join(' ')).join('; ');
    else if (field.type === 'files') shown = value.map(path => path.split('/').pop()).join(', ');
    else if (field.type === 'checklist') shown = checklistSteps(value).map(step => step.done ? step.item : t('habits.step_not_done', { name: step.item })).join(', ');
    else if (Array.isArray(value)) shown = value.map(item => item?.text ?? item?.item ?? item).join(', ');
    else if (typeof value === 'object') shown = value.text ?? '';
    else shown = typeof value === 'number' ? num(value) : String(value);
    bits.push(`${field.label || fieldLabel(field.key)} ${shown}${unit ? ` ${unit}` : ''}`);
    // tesler's law: time in bed is counted from bedtime and wake, never typed
    if (field.key === 'wake') {
      const from = clockMinutes(entry.values?.bedtime), to = clockMinutes(value);
      if (from != null && to != null) bits.push(t('habits.in_bed', { n: durationText((to - from + 1440) % 1440) }));
    }
  }
  if (entry.note) bits.push(entry.note);
  return bits.join(' · ');
}

function dayHtml(d) {
  const { entries, fields, editing } = d;
  const list = entries.length ? `<ol class="dlog-entries" aria-label="${esc(t('habits.logged_entries'))}">${entries.map((entry, at) => `<li class="dlog-entry${editing === at ? ' is-editing' : ''}" data-at="${at}">
      <span class="dlog-entry-text">${esc(entryText(entry, fields, d.habit.kind) || t('habits.done_no_details'))}</span>
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

function initControls(root) {
  initKokuenPrimitives(root);
  root.querySelectorAll('.custom-select').forEach(initCustomDropdown);
  initDatePickers(root);
  wireSteppers(root);
}

function paintDay(d, focus) {
  if (!d.host.isConnected) return;
  d.host.setAttribute('data-scope', '');
  d.host.innerHTML = dayHtml(d);
  initControls(d.host);
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

// add or remove a row: the rows already typed are read back and drawn again with the change
function changeRows(d, box, change) {
  const field = d.fields.find(one => one.key === box.dataset.f);
  if (!field) return;
  let rows;
  try { rows = readRows(box, field); } catch (error) { toast(error.message, 'error'); return; }
  const focus = change(rows);
  box.innerHTML = rowsInner(field, rows, d);
  initControls(box);
  const cards = box.querySelectorAll(':scope > .dlog-rowcard');
  (focus >= 0 && cards[focus] ? cards[focus].querySelector('input, [tabindex="0"], button') : box.querySelector('.dlog-add-row'))?.focus({ preventScroll: true });
}

async function addFile(d, input) {
  const file = input.files?.[0];
  const box = input.closest('.dlog-files');
  if (!file || !box) return;
  const body = new FormData();
  const folder = `habits/${(d.habit.name || 'habit').replace(/[\\/]+/g, ' ').trim() || 'habit'}`;
  body.append('path', folder);
  body.append('file', file, file.name);
  // the busy edge (0053) runs on the add button while the file goes up
  const busy = box.querySelector('.dlog-add-file');
  busy?.classList.add('k-busy');
  busy?.setAttribute('data-busy', 'true');
  try {
    const saved = await api('/api/files/upload', { method: 'POST', body });
    const paths = [...box.querySelectorAll('li[data-path]')].map(item => item.dataset.path);
    paths.push(saved?.path || `${folder}/${file.name}`);
    box.innerHTML = filesInner(paths);
    box.querySelector('[data-dlog="file"]')?.closest('label')?.focus?.();
  } catch (error) {
    toast(error.message || t('habits.file_failed'), 'error');
  } finally {
    busy?.setAttribute('data-busy', 'false');
  }
}

function wireDay(host) {
  if (host.dataset.dlogWired === '1') return;
  host.dataset.dlogWired = '1';
  host.addEventListener('click', event => {
    const d = _dlog;
    const button = event.target.closest('[data-dlog]');
    if (!d || d.host !== host || !button || button.matches('input')) return;
    const act = button.dataset.dlog;
    if (act === 'log') logDay(d);
    else if (act === 'edit') { d.editing = Number(button.closest('.dlog-entry').dataset.at); paintDay(d, '.dlog-form input, .dlog-form [tabindex="0"]'); }
    else if (act === 'cancel') { d.editing = null; paintDay(d, '.dlog-log'); }
    else if (act === 'add-row') changeRows(d, button.closest('.dlog-rows'), rows => { rows.push({}); return rows.length - 1; });
    else if (act === 'remove-row') {
      const card = button.closest('.dlog-rowcard');
      const at = [...card.parentElement.querySelectorAll(':scope > .dlog-rowcard')].indexOf(card);
      changeRows(d, card.parentElement, rows => { rows.splice(at, 1); return Math.min(at, rows.length - 1); });
    } else if (act === 'step') {
      const done = button.getAttribute('aria-checked') !== 'true';
      button.setAttribute('aria-checked', String(done));
    } else if (act === 'remove-step') {
      const name = button.closest('.dlog-step').dataset.item;
      changeSteps(button.closest('.dlog-checklist'), steps => steps.filter(step => step.item !== name));
    } else if (act === 'remove-file') {
      const box = button.closest('.dlog-files');
      button.closest('li').remove();
      const paths = [...box.querySelectorAll('li[data-path]')].map(item => item.dataset.path);
      box.innerHTML = filesInner(paths);
      box.querySelector('.dlog-add-file')?.focus();
    }
  });
  host.addEventListener('keydown', event => {
    if (event.key !== 'Enter' || !event.target.matches('[data-dlog-step-new]') || !textIn(event.target)) return;
    event.preventDefault();
    changeSteps(event.target.closest('.dlog-checklist'), steps => steps);
  });
  host.addEventListener('change', event => {
    const d = _dlog;
    if (!d || d.host !== host) return;
    if (event.target.matches('[data-dlog="file"]')) { addFile(d, event.target); return; }
    const target = event.target.closest('[data-f]');
    if (!target) return;
    const key = target.dataset.f;
    // a measure's unit switch renames the unit inside its stepper
    if (key.endsWith('.unit') && event.detail?.value) {
      const stepper = target.closest('.dlog-row')?.querySelector(`.k-stepper[data-f="${CSS.escape(key.slice(0, -5))}"]`);
      const unit = stepper?.querySelector('.k-stepper-unit');
      if (unit) unit.textContent = unitText(event.detail.value);
      return;
    }
    const night = target.closest('.dlog-control')?.querySelector(`[data-night="${CSS.escape(key)}"]`);
    if (night) night.textContent = nightText(target.dataset.value, d.day);
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
  const entries = structuredClone(habit.days?.[day]?.entries || []);
  const prefill = lastEntry(habit, day);
  const d = {
    host, habit, day, save, editing: null, entries,
    single: !!spec?.single, scale: habit.fields?.scale, units: habit.fields?.units,
    fields: shownFields(spec, habit, [...entries, prefill]),
    prefill,
  };
  _dlog = d;
  host.classList.add('dlog');
  paintDay(d);
  wireDay(host);
  return d;
}

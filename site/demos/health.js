// the health app, as in shots/health.webp (logs) and shots/health-habits.webp (habits). every number is made up
import { h, ic, css, topbar, menu, toast } from './kit.js';

const METRICS = [
  { key: 'weight', label: 'weight', unit: 'lb' },
  { key: 'sleep', label: 'sleep', unit: 'h' },
  { key: 'workout', label: 'workout', unit: 'min' },
  { key: 'heart', label: 'resting heart rate', unit: 'bpm' },
];
const ORDER = ['heart', 'workout', 'sleep', 'weight']; // the order entries from one day sit in

// [days ago, value, note], oldest first. the last 30 days match the screenshot: 5, 21, 8 and 4 entries
const SERIES = {
  weight: [[71, 151.2], [64, 150.9], [57, 150.7], [50, 150.3], [43, 150.1], [36, 149.8], [29, 149.4], [22, 150.0], [15, 149.0], [8, 148.8], [1, 148.4]],
  sleep: [[60, 7.1], [58, 7.4], [55, 6.9], [52, 7.2], [49, 7.5], [47, 7.0], [45, 7.3], [43, 6.8], [41, 7.6], [39, 7.2], [37, 7.1], [35, 7.4], [33, 7.0], [31, 7.3],
    [29, 7.2], [27, 6.8], [26, 7.5], [24, 7.9], [22, 6.4], [21, 8.1], [19, 7.6], [18, 7.0], [17, 7.3], [15, 6.9], [14, 7.6], [12, 7.4], [11, 7.1], [10, 8.0], [8, 7.5], [7, 6.6], [6, 7.2], [5, 7.8], [3, 7.4], [2, 7], [1, 7.6]],
  workout: [[75, 40], [67, 65], [60, 55], [52, 60], [45, 45], [38, 70], [34, 50], [27, 80, 'long run'], [24, 45], [19, 60, 'gym'], [15, 75, 'swim'], [11, 45, 'spin'], [7, 60, 'gym'], [3, 45, 'spin'], [1, 80, 'long run']],
  heart: [[75, 61], [62, 60], [48, 59], [28, 58], [19, 57], [10, 56], [1, 55]],
};

const HABIT_SEED = [
  { name: 'Morning run', hist: [0, 1, 0, 1, 0, 1, 0], pre: 0 },
  { name: 'Drink water', hist: [1, 1, 1, 0, 1, 1, 1], pre: 0 },
  { name: 'Read 20 minutes', hist: [1, 1, 1, 1, 1, 0, 1], pre: 0 },
  { name: 'Meditate', hist: [1, 1, 1, 1, 1, 1, 0], pre: 2 },
  { name: 'Stretch', hist: [1, 1, 1, 1, 1, 1, 1], pre: 0 },
  { name: 'Journal', hist: [1, 1, 1, 0, 0, 0, 0], pre: 0 },
];

const num = (v) => String(+v.toFixed(1));
const dayLabel = (d) => (d === 0 ? 'today' : d === 1 ? 'yesterday' : `${d} days ago`);
const streakOf = (hb) => {
  let n = 0;
  let i = hb.hist.length - 1;
  if (!hb.hist[i]) i--;
  while (i >= 0 && hb.hist[i]) { n++; i--; }
  if (i < 0) n += hb.pre;
  return n;
};

export default function build(root) {
  css('health');
  root.classList.add('hl');

  const HABITS = HABIT_SEED.map((x) => ({ ...x, hist: [...x.hist] }));
  // ---- data
  let uid = 0;
  const entries = [];
  for (const [key, rows] of Object.entries(SERIES)) for (const [day, v, note] of rows) entries.push({ id: ++uid, m: key, day, v, note: note || '' });
  const state = { range: 30, targets: {}, editing: null };
  const metric = (k) => METRICS.find((m) => m.key === k);
  const sorted = () => [...entries].sort((a, b) => a.day - b.day || ORDER.indexOf(a.m) - ORDER.indexOf(b.m) || b.id - a.id);

  // ---- habits
  const habitsCount = h('span', { class: 'hl-count' });
  const archived = h('button', { type: 'button', class: 'dm-btn', text: 'archived habits' });
  const addBtn = h('button', { type: 'button', class: 'dm-btn primary', 'aria-expanded': 'false' }, ic('plus'), 'habit');
  const newInput = h('input', { type: 'text', class: 'dm-input', placeholder: 'habit name', 'aria-label': 'new habit name', autocomplete: 'off', maxlength: '40' });
  const newBox = h('div', { class: 'hl-new', hidden: true }, newInput);
  const habitList = h('div', { class: 'hl-list' });
  const habitsView = h('div', { class: 'hl-view', 'data-tab': 'habits' }, h('div', { class: 'hl-col' }, h('div', { class: 'hl-tools' }, habitsCount, newBox, archived, addBtn), habitList));

  const paintHabits = () => {
    habitsCount.textContent = `${HABITS.length} habit${HABITS.length === 1 ? '' : 's'}`;
    habitsCount.hidden = !newBox.hidden;
    habitList.replaceChildren(...HABITS.map((hb) => {
      const done = !!hb.hist[6];
      const streak = streakOf(hb);
      const check = h('button', { type: 'button', class: 'hl-check', 'aria-pressed': String(done), 'aria-label': `${hb.name}, done today`, onclick: () => { hb.hist[6] = hb.hist[6] ? 0 : 1; paintHabits(); paintOverview(); root.querySelector(`.hl-check[data-n="${HABITS.indexOf(hb)}"]`)?.focus(); }, 'data-n': HABITS.indexOf(hb) }, ic(done ? 'check' : 'plus'));
      return h('div', { class: 'hl-habit' },
        h('div', { class: 'hl-name' }, h('strong', { text: hb.name }), h('span', { text: `${hb.hist.reduce((a, b) => a + b, 0)}/7 days` })),
        h('div', { class: 'hl-dots', 'aria-hidden': 'true' }, hb.hist.map((on, i) => h('span', { class: 'hl-dot' + (on ? ' on' : '') + (i === 6 ? ' today' : '') }))),
        h('span', { class: 'hl-streak' + (streak ? ' on' : ''), 'aria-label': `${streak} day streak` }, String(streak), ic('fire')),
        check);
    }));
  };
  const openNew = (on) => {
    newBox.hidden = !on;
    addBtn.setAttribute('aria-expanded', String(on));
    habitsCount.hidden = on;
    if (on) newInput.focus(); else newInput.value = '';
  };
  addBtn.addEventListener('click', () => openNew(newBox.hidden));
  newInput.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { openNew(false); addBtn.focus(); }
    else if (e.key === 'Enter') {
      const name = newInput.value.trim();
      if (!name) return;
      HABITS.push({ name, hist: [0, 0, 0, 0, 0, 0, 0], pre: 0 });
      openNew(false);
      paintHabits();
      paintOverview();
      addBtn.focus();
    }
  });
  archived.addEventListener('click', () => toast(root, 'in alles this shows habits you archived, to bring back'));

  // ---- overview
  const sumRows = h('div', { class: 'hl-list hl-sums' });
  const overview = h('div', { class: 'hl-view', 'data-tab': 'overview', hidden: true }, h('div', { class: 'hl-col' }, sumRows));
  const latest = (k) => sorted().find((e) => e.m === k);
  const paintOverview = () => {
    const doneN = HABITS.filter((hb) => hb.hist[6]).length;
    const row = (name, value, sub) => h('div', { class: 'hl-sum' }, h('strong', { text: name }), h('span', {}, value, sub ? h('small', { text: sub }) : null));
    const w = latest('weight');
    const s = latest('sleep');
    sumRows.replaceChildren(
      row('habits', `${doneN} of ${HABITS.length} done`),
      row('weight', `${num(w.v)} lb`, dayLabel(w.day)),
      row('sleep', `${num(s.v)} h`, dayLabel(s.day)));
  };

  // ---- logs
  const rangeBtn = h('button', { type: 'button', class: 'dm-input hl-range', 'aria-label': 'range', 'data-value': '30d' }, h('span', { text: '30d' }), ic('chevron-down'));
  const importBtn = h('button', { type: 'button', class: 'dm-btn', text: 'import' });
  const entryBtn = h('button', { type: 'button', class: 'dm-btn primary', 'aria-expanded': 'false' }, ic('plus'), 'entry');
  const metricBtn = h('button', { type: 'button', class: 'dm-input hl-metric', 'aria-label': 'metric', 'data-value': 'weight' }, h('span', { text: 'weight' }), ic('chevron-down'));
  const valIn = h('input', { type: 'text', inputmode: 'decimal', class: 'dm-input', 'aria-label': 'value', placeholder: 'value (lb)', autocomplete: 'off' });
  const noteIn = h('input', { type: 'text', class: 'dm-input hl-note', 'aria-label': 'note', placeholder: 'note', autocomplete: 'off' });
  const addGo = h('button', { type: 'button', class: 'dm-btn', text: 'add' });
  const form = h('div', { class: 'hl-form', hidden: true }, metricBtn, valIn, noteIn, addGo);
  const bar = h('div', { class: 'hl-bar' }, rangeBtn, form, h('span', { class: 'dm-spacer' }), importBtn, entryBtn);

  const W = 202;
  const H = 44;
  const cards = METRICS.map((m) => {
    const tgt = h('button', { type: 'button', class: 'hl-tgt', 'aria-label': `${m.label} target` });
    const el = {
      big: h('strong'), unit: h('span', { text: m.unit }), usual: h('div', { class: 'hl-usual' }), foot: h('div', { class: 'hl-foot' }), tgt,
      svg: h('span', { html: `<svg class="hl-chart" viewBox="0 0 ${W} ${H}" aria-hidden="true"></svg>` }).firstChild,
    };
    const top = h('div', { class: 'hl-card-top' }, h('span', { text: m.label }), tgt);
    el.top = top;
    el.root = h('div', { class: 'hl-card', 'data-m': m.key }, top, h('div', { class: 'hl-big' }, el.big, el.unit), el.usual, el.svg, el.foot);
    tgt.addEventListener('click', () => askTarget(m, el));
    return { m, el };
  });
  const cardsBox = h('div', { class: 'hl-cards' }, cards.map((c) => c.el.root));

  const recent = h('div', { class: 'hl-recent' }, h('div', { class: 'hl-recent-h', text: 'recent' }));
  const rows = h('div', { class: 'hl-rows' });
  recent.append(rows);
  const logs = h('div', { class: 'hl-view', 'data-tab': 'logs', hidden: true }, bar, cardsBox, recent);

  const paintChart = ({ m, el }, vals) => {
    const t = state.targets[m.key];
    const all = t == null ? vals : [...vals, t];
    const svg = el.svg;
    svg.replaceChildren();
    if (!all.length) return;
    let lo = Math.min(...all);
    let hi = Math.max(...all);
    if (hi === lo) { lo -= 1; hi += 1; }
    const y = (v) => (2.5 + (1 - (v - lo) / (hi - lo)) * (H - 5)).toFixed(1);
    const x = (i) => (vals.length === 1 ? W / 2 : 2 + (i / (vals.length - 1)) * (W - 4)).toFixed(1);
    const ns = 'http://www.w3.org/2000/svg';
    const add = (tag, attrs) => { const n = document.createElementNS(ns, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); svg.append(n); };
    if (t != null) add('line', { class: 't', x1: 0, x2: W, y1: y(t), y2: y(t) });
    if (vals.length > 1) add('polyline', { class: 'l', points: vals.map((v, i) => `${x(i)},${y(v)}`).join(' ') });
    vals.forEach((v, i) => add('circle', { class: 'p', cx: x(i), cy: y(v), r: 2 }));
  };

  const paintCards = () => {
    for (const c of cards) {
      const { m, el } = c;
      const mine = sorted().filter((e) => e.m === m.key);
      const inRange = mine.filter((e) => e.day <= state.range);
      const last = mine[0];
      el.big.textContent = last ? num(last.v) : '-';
      const vals = inRange.map((e) => e.v).reverse();
      if (inRange.length >= 5) {
        const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
        const sd = Math.sqrt(vals.reduce((a, b) => a + (b - mean) ** 2, 0) / vals.length);
        el.usual.replaceChildren(`usual ${num(mean)} ${m.unit}`, h('em', { text: `± ${num(sd)}` }));
        el.usual.hidden = false;
      } else el.usual.hidden = true;
      paintChart(c, vals);
      el.foot.textContent = `${last ? dayLabel(last.day) : 'never'} · ${inRange.length} in range`;
      const t = state.targets[m.key];
      el.tgt.className = 'hl-tgt' + (t != null ? ' on' : '');
      el.tgt.replaceChildren(...(t != null ? [ic('target'), `${num(t)}`] : ['set target']));
    }
  };

  function askTarget(m, el) {
    const input = h('input', { type: 'text', inputmode: 'decimal', class: 'dm-input hl-tgt-in', 'aria-label': `${m.label} target in ${m.unit}`, placeholder: m.unit, autocomplete: 'off' });
    if (state.targets[m.key] != null) input.value = num(state.targets[m.key]);
    el.tgt.replaceWith(input);
    input.focus();
    let done = false;
    const finish = (save) => {
      if (done) return;
      const raw = input.value.trim();
      const v = parseFloat(raw);
      if (save && raw && !Number.isFinite(v)) { input.setAttribute('aria-invalid', 'true'); return; }
      done = true;
      if (save) { if (raw) state.targets[m.key] = v; else delete state.targets[m.key]; }
      input.replaceWith(el.tgt);
      paintCards();
      el.tgt.focus();
    };
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); finish(true); }
      else if (e.key === 'Escape') { e.preventDefault(); finish(false); }
    });
    input.addEventListener('blur', () => finish(false));
  }

  const paintRows = () => {
    rows.replaceChildren(...sorted().map((e) => {
      const m = metric(e.m);
      const editing = state.editing === e.id;
      const valCell = editing
        ? h('input', { type: 'text', inputmode: 'decimal', class: 'dm-input', 'aria-label': `${m.label} value`, value: num(e.v), autocomplete: 'off', 'data-edit': e.id })
        : h('span', { class: 'hl-val', text: `${num(e.v)} ${m.unit}` });
      const editBtn = h('button', { type: 'button', class: 'dm-btn', 'aria-label': `${editing ? 'save' : 'edit'} ${m.label}, ${dayLabel(e.day)}`, text: editing ? 'save' : 'edit' });
      const more = h('button', { type: 'button', class: 'dm-btn icon', 'aria-label': `more for ${m.label}, ${dayLabel(e.day)}` }, ic('more'));
      menu(more, ['delete'], () => {
        const i = entries.indexOf(e);
        if (i >= 0) entries.splice(i, 1);
        state.editing = null;
        paintAll();
      });
      const save = () => {
        const v = parseFloat(valCell.value);
        if (!Number.isFinite(v)) { valCell.setAttribute('aria-invalid', 'true'); return; }
        e.v = v;
        state.editing = null;
        paintAll();
        rows.querySelector(`[data-id="${e.id}"] .dm-btn:not(.icon)`)?.focus();
      };
      editBtn.addEventListener('click', () => (editing ? save() : (state.editing = e.id, paintRows(), rows.querySelector(`[data-edit="${e.id}"]`)?.focus())));
      if (editing) valCell.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter') { ev.preventDefault(); save(); }
        else if (ev.key === 'Escape') { ev.preventDefault(); state.editing = null; paintRows(); rows.querySelector(`[data-id="${e.id}"] .dm-btn:not(.icon)`)?.focus(); }
      });
      return h('div', { class: 'hl-row', 'data-id': e.id }, h('span', { text: dayLabel(e.day) }), h('span', { text: m.label }), valCell, h('span', { class: 'hl-nt', text: e.note }), editBtn, more);
    }));
  };

  const paintAll = () => { paintCards(); paintRows(); paintOverview(); };

  // range and import
  menu(rangeBtn, ['7d', '30d', '90d'], (v) => {
    rangeBtn.dataset.value = v;
    rangeBtn.firstChild.textContent = v;
    state.range = parseInt(v, 10);
    paintCards();
  });
  importBtn.addEventListener('click', () => toast(root, 'in alles this reads entries from a csv file or pasted text'));

  // + entry
  const unitOf = () => metric(METRICS.find((m) => m.label === metricBtn.dataset.value).key).unit;
  menu(metricBtn, METRICS.map((m) => m.label), (v) => {
    metricBtn.dataset.value = v;
    metricBtn.firstChild.textContent = v;
    valIn.placeholder = `value (${unitOf()})`;
  });
  const openForm = (on) => {
    form.hidden = !on;
    entryBtn.setAttribute('aria-expanded', String(on));
    if (on) valIn.focus();
    else { valIn.value = ''; noteIn.value = ''; valIn.removeAttribute('aria-invalid'); }
  };
  entryBtn.addEventListener('click', () => openForm(form.hidden));
  const addEntry = () => {
    const v = parseFloat(valIn.value);
    if (!Number.isFinite(v)) { valIn.setAttribute('aria-invalid', 'true'); valIn.focus(); return; }
    const m = METRICS.find((x) => x.label === metricBtn.dataset.value);
    entries.push({ id: ++uid, m: m.key, day: 0, v, note: noteIn.value.trim() });
    openForm(false);
    paintAll();
    entryBtn.focus();
  };
  addGo.addEventListener('click', addEntry);
  for (const input of [valIn, noteIn]) input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); addEntry(); }
    else if (e.key === 'Escape') { openForm(false); entryBtn.focus(); }
  });
  valIn.addEventListener('input', () => valIn.removeAttribute('aria-invalid'));

  const panels = [overview, logs, habitsView];
  const top = topbar({
    app: 'health',
    tabs: ['overview', 'logs', 'habits'],
    selected: 'habits',
    onTab: (name) => panels.forEach((p) => { p.hidden = p.dataset.tab !== name; }),
  });
  root.append(top.el, ...panels);
  paintHabits();
  paintAll();
}

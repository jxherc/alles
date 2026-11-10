// the plan app's calendar, as in shots/plan.webp: the week of nov 8, four calendars, quick add, an agenda,
// a today list and a short task list. all made up. labels from static/js/calendar.js and tasks.js
import { h, ic, css, topbar, toast } from './kit.js';

const BASE = new Date(2026, 10, 8); // sunday, nov 8 2026 is "today"
const dateOf = (i) => new Date(2026, 10, 8 + i);
const WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const WD_LONG = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MON_LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const HOUR = 29.4; // px per hour
const NINE = 75.5; // where 9 am sits in the time grid

const CALS = [
  { id: 'work', name: 'Work', color: 'var(--pl-work)' },
  { id: 'personal', name: 'Personal', color: 'var(--pl-personal)' },
  { id: 'health', name: 'Health', color: 'var(--pl-health)' },
  { id: 'family', name: 'Family', color: 'var(--pl-family)' },
];
const calOf = (id) => CALS.find((c) => c.id === id);

const t = (hh, mm = 0) => hh * 60 + mm;
let nextId = 1;
const ev = (cal, title, day, start, end, place = '') => ({ id: 'e' + nextId++, cal, title, day, start, end, place });
const EVENTS = [
  ev('personal', 'Farmers market', 0, t(9, 30), t(10, 30), 'Woodbine Park'),
  ev('personal', 'Brunch with Priya', 0, t(11, 30), t(13), 'Rosewood Cafe'),
  ev('family', 'Call with Mum', 0, t(14), t(14, 30)),
  ev('personal', 'Meal prep', 0, t(17), t(18, 30)),
  ev('work', 'Design crit', 1, t(11), t(12), 'Studio B'),
  ev('health', 'Spin class', 1, t(18), t(18, 40), 'Ground Fitness'),
  ev('work', '1:1 with Jordan', 2, t(12, 30), t(13, 15), 'Zoom'),
  ev('work', 'Onboarding flow review', 2, t(14), t(15, 30), 'Studio A'),
  ev('personal', 'Dentist', 2, t(16, 30), t(17, 30), 'Bloor Dental'),
  ev('work', 'Sprint planning', 3, t(10), t(11, 30), 'Main room'),
  ev('work', 'User interviews', 3, t(13, 30), t(15), 'Zoom'),
  ev('health', 'Yoga', 3, t(18, 30), t(19, 30), 'Silver Studio'),
  ev('work', 'Design systems sync', 4, t(11), t(11, 45), 'Studio B'),
  ev('work', 'Q4 roadmap review', 4, t(15), t(16), 'Boardroom'),
  ev('work', 'Demo day', 5, t(15), t(16), 'Main room'),
  ev('health', 'Hike at Rattlesnake Point', 6, t(9), t(13), 'Milton'),
  ev('family', "Mum's birthday dinner", 6, t(18), t(20), "Carmen's Place"),
];
const ALLDAY = [
  { id: 'a1', cal: 'family', title: "Mum's birthday", day: 6, kind: 'event', order: 0 },
  { id: 'a2', cal: 'family', title: 'Mum', day: 6, kind: 'bday', order: 2, color: 'var(--pl-pink)' },
];
const TASKS = [
  { id: 'k1', title: "Return Priya's charger", day: 0, time: null, done: false },
  { id: 'k2', title: 'Water the plants', day: 0, time: null, done: true },
  { id: 'k3', title: 'Groceries for meal prep', day: 0, time: t(10, 30), done: false },
  { id: 'k4', title: 'Finish onboarding copy', day: 1, time: t(17), done: false },
  { id: 'k5', title: 'Write up user interview notes', day: 2, time: null, done: false },
  { id: 'k6', title: 'Send fieldnote invoice', day: 2, time: t(11), done: false },
  { id: 'k7', title: 'Book dentist follow-up', day: 3, time: null, done: false },
  { id: 'k8', title: 'Plan Saturday carpool', day: 3, time: null, done: false },
  { id: 'k9', title: 'Pay Visa balance', day: 4, time: null, done: false },
  { id: 'k10', title: 'Prep demo day slides', day: 5, time: t(10), done: false },
  { id: 'k11', title: 'Draft birthday toast', day: 6, time: t(12), done: false },
];

const clock = (m) => {
  const hh = Math.floor(m / 60);
  return `${hh % 12 || 12}:${String(m % 60).padStart(2, '0')} ${hh >= 12 ? 'PM' : 'AM'}`;
};
const range = (a, b) => {
  const x = clock(a);
  const y = clock(b);
  return x.slice(-2) === y.slice(-2) ? `${x.slice(0, -3)} to ${y}` : `${x} to ${y}`;
};
const dayName = (i) => `${WD_LONG[dateOf(i).getDay()]}, ${MON[dateOf(i).getMonth()]} ${dateOf(i).getDate()}`;

export default function build(root) {
  css('plan');
  let weekOff = 0;
  let view = 'week';
  let query = '';
  let mini = { y: 2026, m: 10 };
  let lastAdded = '';
  const on = { work: true, personal: true, health: true, family: true };
  const user = [];
  let pop = null; // { el, anchor }

  const weekStart = () => weekOff * 7;
  const matches = (e) => !query || `${e.title} ${e.place}`.toLowerCase().includes(query);
  // everything timed on a day: the one-off events, recurring standups on weekdays, what maya added
  const dayEvents = (abs) => {
    const out = [...EVENTS.filter((e) => e.day === abs), ...user.filter((e) => e.day === abs)];
    const wd = ((abs % 7) + 7) % 7;
    if (wd >= 1 && wd <= 5) out.push({ id: 'sd' + abs, cal: 'work', title: 'Team standup', day: abs, start: t(9, 30), end: t(10), place: 'Zoom', rec: true });
    return out.filter((e) => on[e.cal] && matches(e)).sort((a, b) => a.start - b.start);
  };
  const fullText = (e) => `${e.title}, ${range(e.start, e.end)}`;

  // ---- popover ----
  const closePop = (focus) => {
    if (!pop) return;
    pop.el.remove();
    if (focus) pop.anchor.focus();
    pop = null;
  };
  const openPop = (anchor, item) => {
    if (pop && pop.anchor === anchor) { closePop(true); return; }
    closePop();
    const c = calOf(item.cal);
    const el = h('div', { class: 'pl-pop', role: 'dialog', tabindex: '-1', 'aria-label': item.title },
      h('div', { class: 'pl-pop-title', text: item.title }),
      h('div', { class: 'pl-pop-line' }, ic('clock'), h('span', { text: `${dayName(item.day)} · ${item.allDay ? 'all day' : range(item.start, item.end)}` })),
      h('div', { class: 'pl-pop-line', style: `--c: ${item.color || c.color}` }, h('span', { class: 'pl-dot' }), h('span', { text: c.name })),
      item.place ? h('div', { class: 'pl-pop-line' }, ic('map-pin'), h('span', { text: item.place })) : null);
    root.append(el);
    const a = anchor.getBoundingClientRect();
    const r = root.getBoundingClientRect();
    const s = r.width / root.offsetWidth;
    const ax = (a.left - r.left) / s;
    const aw = a.width / s;
    let left = ax + aw + 6;
    if (left + 232 > 954) left = ax - 236;
    left = Math.max(6, left);
    const top = Math.min(600 - el.offsetHeight - 8, Math.max(56, (a.top - r.top) / s));
    el.style.left = left + 'px';
    el.style.top = top + 'px';
    pop = { el, anchor };
    el.focus({ preventScroll: true });
  };
  root.addEventListener('keydown', (e) => { if (e.key === 'Escape' && pop) { e.preventDefault(); closePop(true); } });
  document.addEventListener('pointerdown', (e) => { if (pop && !pop.el.contains(e.target) && !pop.anchor.contains(e.target)) closePop(false); });

  // ---- tasks (shared by the all-day row, today and the tasks tab) ----
  const toggleTask = (task) => { task.done = !task.done; paint(); };
  const tick = (task, k) => {
    const b = h('button', { type: 'button', class: 'pl-tick', role: 'checkbox', 'aria-checked': String(task.done), 'aria-label': task.title, 'data-k': k }, ic('check'));
    b.addEventListener('click', () => toggleTask(task));
    return b;
  };
  const taskDue = (task) => `${WD[dateOf(task.day).getDay()]}, ${MON[dateOf(task.day).getMonth()]} ${dateOf(task.day).getDate()}${task.time != null ? ' · ' + clock(task.time) : ''}`;
  const taskRow = (task, k) => h('div', { class: 'pl-item' + (task.done ? ' done' : '') }, tick(task, k), h('span', { class: 'pl-name', text: task.title }), h('span', { class: 'pl-aside', text: taskDue(task) }));

  // ---- the week ----
  const labelEl = h('span', { class: 'pl-label' });
  const headRow = h('div', { class: 'pl-row pl-head' });
  const alldayRow = h('div', { class: 'pl-row pl-allday' });
  const times = h('div', { class: 'pl-times' });
  const weekEl = h('div', { class: 'pl-cal' }, headRow, alldayRow, times);
  const agendaEl = h('div', { class: 'pl-agenda', hidden: true });

  const evButton = (e, extra) => {
    const dur = e.end - e.start;
    const short = dur <= 45;
    const b = h('button', { type: 'button', class: 'pl-ev' + (short ? ' short' : '') + (e.rec ? ' rec' : '') + (e.id === lastAdded ? ' added' : ''), 'aria-label': fullText(e), 'data-k': 'e:' + e.id, style: `--ec: ${calOf(e.cal).color}; ${extra}` },
      short
        ? [h('span', { class: 'pl-title', text: e.title }), h('span', { class: 'pl-place', text: clock(e.start) })]
        : [h('span', { class: 'pl-title' }, h('b', { text: clock(e.start) }), ' ' + e.title), e.place ? h('span', { class: 'pl-place', text: e.place }) : null]);
    b.addEventListener('click', () => openPop(b, e));
    return b;
  };
  // overlapping events share the column's width
  const layout = (list) => {
    const out = [];
    let cluster = [];
    let end = -1;
    const flush = () => {
      const lanes = [];
      cluster.forEach((e) => {
        let i = lanes.findIndex((last) => last <= e.start);
        if (i < 0) { i = lanes.length; lanes.push(0); }
        lanes[i] = e.end;
        e.lane = i;
      });
      cluster.forEach((e) => out.push({ e, lane: e.lane, n: lanes.length }));
      cluster = [];
    };
    list.forEach((e) => {
      if (cluster.length && e.start >= end) { flush(); end = -1; }
      cluster.push(e);
      end = Math.max(end, e.end);
    });
    if (cluster.length) flush();
    return out;
  };

  const chip = (task, k) => {
    const b = h('button', { type: 'button', class: 'pl-chip' + (task.done ? ' done' : ''), role: 'checkbox', 'aria-checked': String(task.done), 'data-k': k },
      h('span', { class: 'pl-ring' }, task.done ? ic('check') : null),
      h('span', { text: (task.time != null ? clock(task.time) + ' ' : '') + task.title }));
    b.addEventListener('click', () => toggleTask(task));
    return b;
  };

  const paintWeek = () => {
    const ws = weekStart();
    const a = dateOf(ws);
    const z = dateOf(ws + 6);
    labelEl.textContent = `${MON[a.getMonth()]} ${a.getDate()}${a.getFullYear() !== z.getFullYear() ? ', ' + a.getFullYear() : ''} - ${MON[z.getMonth()]} ${z.getDate()}, ${z.getFullYear()}`;
    headRow.replaceChildren(h('span'), ...Array.from({ length: 7 }, (_, i) => {
      const d = dateOf(ws + i);
      return h('span', { class: ws + i === 0 ? 'pl-now' : '' }, WD[d.getDay()], h('b', { text: String(d.getDate()) }));
    }));
    alldayRow.replaceChildren(h('span', { text: 'all-day' }), ...Array.from({ length: 7 }, (_, i) => {
      const abs = ws + i;
      const items = [];
      ALLDAY.filter((x) => x.day === abs && on[x.cal] && x.kind === 'event').forEach((x) => items.push([x.order, 'ev', x]));
      TASKS.filter((x) => x.day === abs).forEach((x) => items.push([1 + (x.time ?? 0) / 10000, 'task', x]));
      ALLDAY.filter((x) => x.day === abs && on[x.cal] && x.kind === 'bday').forEach((x) => items.push([x.order, 'bday', x]));
      items.sort((p, q) => p[0] - q[0]);
      return h('div', { class: 'pl-allday-cell' }, items.map(([, kind, x]) => {
        if (kind === 'task') return chip(x, 't:' + x.id + ':chip');
        const it = { ...x, allDay: true, place: '' };
        const b = h('button', { type: 'button', class: 'pl-chip ' + (kind === 'bday' ? 'bday' : 'ev'), style: `--ec: ${x.color || calOf(x.cal).color}`, 'data-k': 'a:' + x.id }, kind === 'bday' ? ic('cake') : null, h('span', { text: x.title }));
        b.addEventListener('click', () => openPop(b, it));
        return b;
      }));
    }));

    const cols = h('div', { class: 'pl-row pl-cols' }, h('span'));
    const lines = [];
    for (let hr = 6; hr <= 19; hr++) {
      const y = NINE + (hr - 9) * HOUR;
      lines.push(h('div', { class: 'pl-line', style: `top: ${y}px` }));
      if (hr >= 7) lines.push(h('div', { class: 'pl-hour', style: `top: ${y + 1}px`, text: (hr % 12 || 12) + (hr >= 12 ? 'p' : 'a') }));
    }
    for (let i = 0; i < 7; i++) {
      const col = h('div', { class: 'pl-col' });
      layout(dayEvents(ws + i)).forEach(({ e, lane, n }) => {
        const top = NINE + ((e.start - 540) / 60) * HOUR;
        const height = ((e.end - e.start) / 60) * HOUR - 2;
        const w = 100 / n;
        col.append(evButton(e, `top: ${top}px; height: ${height}px; left: calc(${lane * w}% + 1px); right: auto; width: calc(${w}% - 2px)`));
      });
      if (ws + i === 0) col.append(h('div', { class: 'pl-nowline', style: `top: ${NINE + ((565 - 540) / 60) * HOUR}px` }));
      cols.append(col);
    }
    times.replaceChildren(...lines, cols);
  };

  const paintAgenda = () => {
    const ws = weekStart();
    const days = [];
    for (let i = 0; i < 7; i++) {
      const abs = ws + i;
      const rows = [];
      ALLDAY.filter((x) => x.day === abs && on[x.cal] && x.kind === 'event').forEach((x) => {
        const b = h('button', { type: 'button', class: 'pl-ag-row', style: `--c: ${calOf(x.cal).color}`, 'data-k': 'a:' + x.id }, h('span', { class: 'pl-dot' }), h('span', { class: 'pl-ag-time', text: 'all day' }), h('span', { class: 'pl-ag-title' }, h('span', { text: x.title })));
        b.addEventListener('click', () => openPop(b, { ...x, allDay: true, place: '' }));
        rows.push(b);
      });
      dayEvents(abs).forEach((e) => {
        const b = h('button', { type: 'button', class: 'pl-ag-row', style: `--c: ${calOf(e.cal).color}`, 'data-k': 'e:' + e.id }, h('span', { class: 'pl-dot' }), h('span', { class: 'pl-ag-time', text: clock(e.start) }),
          h('span', { class: 'pl-ag-title' }, h('span', { text: e.title }), e.place ? h('span', { class: 'pl-ag-place', text: e.place }) : null));
        b.addEventListener('click', () => openPop(b, e));
        rows.push(b);
      });
      if (!rows.length) continue;
      const d = dateOf(abs);
      days.push(h('div', { class: 'pl-ag-day' }, h('div', { class: 'pl-ag-head' + (abs === 0 ? ' now' : '') }, h('b', { text: WD_LONG[d.getDay()] }), `${MON[d.getMonth()]} ${d.getDate()}`), rows));
    }
    agendaEl.replaceChildren(...(days.length ? days : [h('p', { class: 'pl-none', text: 'no events' })]));
  };

  // ---- the left column ----
  const monthTitle = h('span', { class: 'pl-mini-title' });
  const monthDays = h('div', { class: 'pl-days' });
  const paintMini = () => {
    monthTitle.textContent = `${MON_LONG[mini.m]} ${mini.y}`;
    const first = new Date(mini.y, mini.m, 1);
    const count = new Date(mini.y, mini.m + 1, 0).getDate();
    const rows = Math.ceil((first.getDay() + count) / 7);
    monthDays.style.setProperty('--row', 147 / rows + 'px');
    const cells = Array.from({ length: first.getDay() }, () => h('span'));
    for (let d = 1; d <= count; d++) {
      const date = new Date(mini.y, mini.m, d);
      const diff = Math.round((date - BASE) / 86400000);
      const b = h('button', { type: 'button', class: 'pl-day' + (diff === 0 ? ' today' : ''), 'aria-label': `${WD_LONG[date.getDay()]}, ${MON_LONG[mini.m]} ${d}, ${mini.y}`, 'aria-current': diff === 0 ? 'date' : null, 'data-k': 'd:' + d, text: String(d) });
      b.addEventListener('click', () => { weekOff = Math.floor(diff / 7); paint(); });
      cells.push(b);
    }
    monthDays.replaceChildren(...cells);
  };
  const monthBtn = (dir) => {
    const b = h('button', { type: 'button', class: 'dm-btn icon', 'aria-label': dir < 0 ? 'previous month' : 'next month' }, ic(dir < 0 ? 'chevron-left' : 'chevron-right'));
    b.addEventListener('click', () => {
      const d = new Date(mini.y, mini.m + dir, 1);
      mini = { y: d.getFullYear(), m: d.getMonth() };
      paintMini();
    });
    return b;
  };

  const calRow = (c) => {
    const b = h('button', { type: 'button', class: 'pl-cal-row', role: 'checkbox', 'aria-checked': 'true', style: `--c: ${c.color}` }, h('span', { class: 'pl-dot' }), c.name);
    b.addEventListener('click', () => {
      on[c.id] = !on[c.id];
      b.setAttribute('aria-checked', String(on[c.id]));
      paint();
    });
    return b;
  };
  const calRows = CALS.map(calRow);
  const section = (top, title, label, tip) => {
    const add = h('button', { type: 'button', class: 'dm-btn icon', 'aria-label': label }, ic('plus'));
    add.addEventListener('click', () => toast(root, tip));
    return h('div', { class: 'pl-sec', style: `top: ${top}px` }, h('div', { class: 'pl-sec-head' }, title, add));
  };
  const search = h('input', { class: 'dm-input pl-search', type: 'search', placeholder: 'search events...', 'aria-label': 'search events', autocomplete: 'off' });
  search.addEventListener('input', () => { query = search.value.trim().toLowerCase(); paint(); });
  const cals = section(256, 'my calendars', 'new calendar', 'in alles this adds a calendar');
  cals.append(h('div', { style: 'margin-top: 1px' }, calRows));
  const subs = section(418, 'subscriptions', 'add a feed', 'in alles this adds a calendar feed by its link');
  subs.append(h('div', { class: 'pl-empty', style: 'margin-top: 1px', text: 'no feeds yet' }));
  const booking = section(485.5, 'booking pages', 'new booking page', 'in alles this makes a page where people book time with you');
  const side = h('div', { class: 'pl-side' }, search,
    h('div', { class: 'pl-mini' }, h('div', { class: 'pl-mini-head' }, monthBtn(-1), monthTitle, monthBtn(1)),
      h('div', { class: 'pl-wk' }, ['S', 'M', 'T', 'W', 'T', 'F', 'S'].map((x) => h('span', { text: x }))), monthDays),
    cals, subs, booking);

  // ---- the toolbar ----
  const go = (n) => { weekOff += n; paint(); };
  const prev = h('button', { type: 'button', class: 'dm-btn quiet icon', 'aria-label': 'previous week' }, ic('chevron-left'));
  const next = h('button', { type: 'button', class: 'dm-btn quiet icon', 'aria-label': 'next week' }, ic('chevron-right'));
  prev.addEventListener('click', () => go(-1));
  next.addEventListener('click', () => go(1));
  const todayBtn = h('button', { type: 'button', class: 'dm-btn', text: 'today' });
  todayBtn.addEventListener('click', () => {
    weekOff = 0;
    mini = { y: 2026, m: 10 };
    paintMini();
    paint();
  });
  const SWITCH = {
    month: 'in alles month shows the whole month with each day\'s events',
    day: 'in alles day shows one day hour by hour',
    year: 'in alles year shows all twelve months at a glance',
  };
  const viewBtns = ['month', 'week', 'day', 'agenda', 'year'].map((name) => {
    const b = h('button', { type: 'button', class: 'dm-btn quiet', 'aria-pressed': String(name === view), text: name });
    b.addEventListener('click', () => {
      if (name !== 'week' && name !== 'agenda') { toast(root, SWITCH[name]); return; }
      view = name;
      closePop();
      paint();
    });
    return b;
  });
  const quick = h('input', { class: 'dm-input pl-quick', type: 'text', placeholder: 'quick add… ‘lunch fri 1pm’', 'aria-label': 'quick add event', autocomplete: 'off' });
  const newEvent = h('button', { type: 'button', class: 'dm-btn primary', text: '+ event' });
  newEvent.addEventListener('click', () => quick.focus());
  const more = h('button', { type: 'button', class: 'dm-btn', text: 'more' });
  more.addEventListener('click', () => toast(root, 'in alles this opens import, export and sharing'));

  // "lunch fri 1pm": a weekday word (or today, tomorrow), a time with am/pm or a colon, the rest is the title
  const DAY = /\b(sun(?:day)?|mon(?:day)?|tue(?:s|sday)?|wed(?:nesday)?|thu(?:r|rs|rsday)?|fri(?:day)?|sat(?:urday)?|today|tomorrow)\b/i;
  const TIME = /\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b|\b(\d{1,2}):(\d{2})\b/i;
  const hint = () => toast(root, 'write it like ‘lunch fri 1pm’: a title, a day and a time');
  const quickAdd = () => {
    const text = quick.value.trim();
    if (!text) return;
    const dm = DAY.exec(text);
    const tm = TIME.exec(text);
    if (!dm || !tm) { hint(); return; }
    let mins;
    if (tm[3]) {
      const hr = Number(tm[1]);
      if (hr < 1 || hr > 12 || Number(tm[2] || 0) > 59) { hint(); return; }
      mins = (hr % 12 + (tm[3].toLowerCase() === 'pm' ? 12 : 0)) * 60 + Number(tm[2] || 0);
    } else {
      if (Number(tm[4]) > 23) { hint(); return; }
      mins = Number(tm[4]) * 60 + Number(tm[5]);
    }
    const title = text.replace(TIME, ' ').replace(DAY, ' ').replace(/\b(on|at|@)\b/gi, ' ').replace(/\s+/g, ' ').trim();
    if (!title) { hint(); return; }
    if (mins < t(7) || mins > t(18, 30)) { toast(root, 'try a time from 7am to 6:30pm, like ‘lunch fri 1pm’'); return; }
    const word = dm[1].toLowerCase();
    let abs;
    if (word === 'today') abs = 0;
    else if (word === 'tomorrow') abs = 1;
    else abs = weekStart() + ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'].indexOf(word.slice(0, 3));
    const item = { id: 'u' + nextId++, cal: 'personal', title, day: abs, start: mins, end: mins + 60, place: '' };
    user.push(item);
    lastAdded = item.id;
    on.personal = true;
    calRows[1].setAttribute('aria-checked', 'true');
    query = '';
    search.value = '';
    weekOff = Math.floor(abs / 7);
    quick.value = '';
    paint();
    toast(root, `added ${title} on ${WD[dateOf(abs).getDay()]} at ${clock(mins)}`);
  };
  quick.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); quickAdd(); } });

  const bar = h('div', { class: 'pl-bar' }, prev, todayBtn, next, labelEl, h('span', { class: 'dm-spacer' }), h('div', { class: 'pl-views' }, viewBtns), newEvent, quick, more);
  const calView = h('div', { class: 'pl-view', 'data-tab': 'calendar' }, bar, h('div', { class: 'pl-body' }, side, weekEl, agendaEl));

  // ---- today and tasks ----
  const todayView = h('div', { class: 'pl-view', 'data-tab': 'today', hidden: true });
  const tasksView = h('div', { class: 'pl-view', 'data-tab': 'tasks', hidden: true });
  const paintToday = () => {
    const rows = dayEvents(0).map((e) => {
      const b = h('button', { type: 'button', class: 'pl-item', style: `--c: ${calOf(e.cal).color}`, 'data-k': 'e:' + e.id }, h('span', { class: 'pl-when', text: range(e.start, e.end) }), h('span', { class: 'pl-dot' }), h('span', { class: 'pl-name', text: e.title }), h('span', { class: 'pl-aside', text: e.place }));
      b.addEventListener('click', () => openPop(b, e));
      return b;
    });
    const todays = TASKS.filter((x) => x.day === 0);
    todayView.replaceChildren(h('div', { class: 'pl-list' },
      h('span', { class: 'dm-h', text: dayName(0) }),
      ...(rows.length ? rows : [h('p', { class: 'pl-none', text: 'no events' })]),
      h('div', { class: 'pl-sub', text: 'tasks' }),
      ...todays.map((x) => taskRow(x, 't:' + x.id + ':today'))));
  };
  const paintTasks = () => {
    tasksView.replaceChildren(h('div', { class: 'pl-list' }, ...TASKS.map((x) => taskRow(x, 't:' + x.id + ':list'))));
  };

  // ---- paint everything, keeping the keyboard where it was ----
  function paint() {
    const key = document.activeElement?.closest?.('[data-k]')?.dataset.k;
    closePop();
    paintWeek();
    paintAgenda();
    paintToday();
    paintTasks();
    if (key && key.startsWith('d:')) paintMini();
    weekEl.hidden = view !== 'week';
    agendaEl.hidden = view !== 'agenda';
    viewBtns.forEach((b) => b.setAttribute('aria-pressed', String(b.textContent === view)));
    if (key) root.querySelector(`[data-k="${key}"]`)?.focus({ preventScroll: true });
  }

  const views = { today: todayView, calendar: calView, tasks: tasksView };
  const tabs = topbar({
    app: 'plan',
    tabs: ['today', 'calendar', 'tasks'],
    selected: 'calendar',
    onTab: (name) => { closePop(); Object.entries(views).forEach(([k, v]) => { v.hidden = k !== name; }); },
  });
  root.append(tabs.el, calView, todayView, tasksView);
  paintMini();
  paint();
}

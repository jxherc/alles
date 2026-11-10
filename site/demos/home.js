// the home app, as in shots/home.webp and shots/home-phone.webp: the date and greeting, a capture
// box, what needs you, pinned apps and the day's schedule. every item is made up
import { h, ic, glyph, css, topbar, menu, toast } from './kit.js';

const PINNED = [
  ['plan', 'plan', 'calendar, tasks, and reminders'],
  ['docs', 'docs', 'notes and journal'],
  ['files', 'files', 'storage and gallery'],
];
const EVENTS = [
  ['9:30 am', 'Farmers market'],
  ['11:30 am', 'Brunch with Priya'],
  ['2:00 pm', 'Call with Mum'],
  ['5:00 pm', 'Meal prep'],
];
const TASKS = [
  ['Groceries: oats, lentils, spinach, lemons', '10:30 am'],
  ["Return Priya's jacket", 'today'],
  ['Pay the phone bill', 'today'],
];
const KINDS = ['task', 'note', 'event'];

export default function build(root, { variant } = {}) {
  css('home');
  const phone = variant === 'phone';
  root.classList.add('hm-root');
  if (phone) root.classList.add('hm-phone');
  const say = (text) => toast(root, text);
  const openApp = (name) => document.dispatchEvent(new CustomEvent('alles:open-app', { detail: name }));

  let open = 15;
  let kind = 'task';
  const needs = [];

  const top = topbar({
    app: 'alles',
    right: h('div', { class: 'hm-topr' },
      h('span', { class: 'hm-clock', text: phone ? 'sun, nov 8 9:28 am' : 'sun, nov 8 9:27 am' }),
      h('button', { type: 'button', class: 'hm-plain', text: 'settings', onclick: () => say('in alles this opens settings') })),
  });
  top.el.classList.add('hm-bar');

  // heading block
  const count = h('span', { class: 'hm-count', text: String(open) });
  const head = [
    h('p', { class: 'hm-date', text: 'sunday, november 8' }),
    h('h4', { class: 'hm-hi', text: phone ? 'a clean page' : 'good morning' }),
    h('button', { type: 'button', class: 'hm-open', onclick: () => say('in alles this opens all your tasks in plan') }, 'all open tasks: ', count),
    h('button', { type: 'button', class: 'hm-ask', text: 'ask Aide about today →', onclick: () => openApp('aide') }),
  ];

  // the capture box
  const input = h('input', { type: 'text', class: 'hm-input', placeholder: 'capture something…', 'aria-label': 'capture a task', maxlength: '90', autocomplete: 'off' });
  const kindBtn = h('button', { type: 'button', class: 'hm-kind', 'aria-label': 'what to capture', text: kind });
  kindBtn.dataset.value = kind;
  const sendBtn = h('button', { type: 'submit', class: 'hm-send', 'aria-label': 'save capture' }, ic('send'));
  const form = h('form', { class: 'hm-capture', onsubmit: (e) => { e.preventDefault(); add(); } }, kindBtn, input, sendBtn);

  // needs you: what was captured as a task lands here
  const needsMeta = h('span', { class: 'hm-meta' });
  const needsBody = h('div', { class: 'hm-list' });
  const renderNeeds = () => {
    needsMeta.textContent = needs.length ? String(needs.length) : '';
    needsBody.replaceChildren(...(needs.length
      ? needs.slice(0, 4).map((item) => h('div', { class: 'hm-row hm-need' },
        h('button', { type: 'button', class: 'hm-check', 'aria-label': `mark ${item.title} done`, onclick: () => {
          needs.splice(needs.indexOf(item), 1);
          open = Math.max(0, open - 1);
          count.textContent = String(open);
          renderNeeds();
        } }),
        h('div', { class: 'hm-text' }, h('b', { text: item.title }), h('small', { text: 'task' }))))
      : [h('p', { class: 'hm-empty', text: 'nothing needs your attention' })]));
  };
  renderNeeds();

  function add() {
    const value = input.value.trim();
    if (!value) { input.focus(); return; }
    input.value = '';
    if (kind === 'task') {
      needs.unshift({ title: value });
      open += 1;
      count.textContent = String(open);
      renderNeeds();
    } else say(kind === 'note' ? 'note saved to docs' : 'event added to plan');
    input.focus();
  }

  // the schedule: events are plain rows, tasks can be checked off or moved to tomorrow
  const when = (time) => h('span', { class: 'hm-time', text: time });
  const eventRow = ([time, title]) => h('div', { class: 'hm-row' }, when(time), h('div', { class: 'hm-text' }, h('b', { text: title }), h('small', { text: 'calendar' })));
  const taskRow = ([title, sub]) => {
    const row = h('div', { class: 'hm-row hm-st' });
    const normal = () => {
      row.className = 'hm-row hm-st';
      row.removeAttribute('role');
      row.replaceChildren(
        h('button', { type: 'button', class: 'hm-check', 'aria-label': `mark ${title} done`, onclick: finish }),
        h('div', { class: 'hm-text' }, h('b', { text: title }), h('small', { text: sub })),
        h('button', { type: 'button', class: 'hm-snooze', 'aria-label': `move ${title} to tomorrow`, text: 'tomorrow', onclick: () => { row.remove(); say('moved to tomorrow'); } }));
    };
    let timer = 0;
    function finish() {
      open = Math.max(0, open - 1);
      count.textContent = String(open);
      row.className = 'hm-row hm-st hm-done';
      row.setAttribute('role', 'status');
      const undo = h('button', { type: 'button', class: 'hm-snooze', text: 'undo', onclick: () => {
        clearTimeout(timer);
        open += 1;
        count.textContent = String(open);
        normal();
        row.querySelector('.hm-check').focus();
      } });
      row.replaceChildren(h('span'), h('div', { class: 'hm-text' }, h('small', { text: `completed ${title}` })), undo);
      undo.focus();
      timer = setTimeout(() => row.remove(), 6000);
    }
    normal();
    return row;
  };
  const schedule = h('section', { class: 'hm-sec' },
    h('header', {}, h('h4', { text: 'schedule' })),
    h('div', { class: 'hm-list' },
      h('div', { class: 'hm-now', 'aria-hidden': 'true' }, h('span', { text: 'now' }), h('i')),
      EVENTS.map(eventRow), TASKS.map(taskRow)));

  const left = h('div', { class: 'hm-left' },
    h('section', { class: 'hm-sec hm-needs' }, h('header', {}, h('h4', { text: 'needs you' }), needsMeta), needsBody),
    schedule);
  const cols = h('div', { class: 'hm-cols' }, left);
  if (!phone) {
    cols.append(h('div', { class: 'hm-right' }, h('section', { class: 'hm-sec' },
      h('header', {}, h('h4', { text: 'pinned apps' }), h('button', { type: 'button', class: 'hm-plain hm-edit', text: 'edit', onclick: () => say('in alles this picks which apps are pinned here') })),
      h('div', { class: 'hm-tiles' }, PINNED.map(([app, name, desc]) => h('button', { type: 'button', class: 'hm-tile', onclick: () => openApp(app) },
        glyph(app), h('b', { text: name }), h('small', { text: desc })))))));
  }

  const kids = [top.el, h('div', { class: 'hm-page' }, head, form, cols)];
  if (phone) {
    const tab = (app, label, current) => h('button', { type: 'button', class: 'hm-tab', 'aria-current': current ? 'page' : null, onclick: () => { if (!current) openApp(app); } }, glyph(app), h('span', { text: label }));
    kids.push(h('nav', { class: 'hm-tabs', 'aria-label': 'apps' },
      tab('home', 'home', true), tab('aide', 'aide'), tab('plan', 'plan'), tab('docs', 'docs'),
      h('button', { type: 'button', class: 'hm-tab', onclick: () => say('in alles this opens the rest of your apps') }, ic('more'), h('span', { text: 'more' }))));
  }
  root.append(h('div', { class: 'hm' }, kids));

  // rows cut off by the canvas edge can't be seen, so keyboard focus skips their buttons
  const cut = new IntersectionObserver((entries) => entries.forEach((e) => {
    e.target.querySelectorAll('button').forEach((b) => { b.tabIndex = e.intersectionRatio < 0.5 ? -1 : 0; });
  }), { root: root.querySelector('.hm-page'), threshold: [0, 0.5, 1] });
  schedule.querySelectorAll('.hm-row').forEach((row) => cut.observe(row));

  // the kind menu needs its button on screen (it finds the canvas from it)
  menu(kindBtn, KINDS, (item) => {
    kind = item;
    kindBtn.textContent = item;
    kindBtn.dataset.value = item;
    input.setAttribute('aria-label', `capture a ${item}`);
    input.focus();
  });
}

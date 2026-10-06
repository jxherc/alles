import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { calendarDateKey, configureLocalization, formatDateParts, formatDateTime } from '../../static/js/i18n.js';
import { recordTarget } from '../../static/js/recordlinks.js';

const source = readFileSync(new URL('../../static/js/specialist_groups.js', import.meta.url), 'utf8');
const today = '2026-10-06';
const title = 'réunion 日本語 🌱';
const fixtures = () => ({
  '/api/calendar/agenda?days=8': { days: [{ date: today, events: [
    { id: 'series-a', title, start_dt: `${today}T09:00`, recurrence: 'daily', recurring: true },
    { id: 'event-b', title, start_dt: `${today}T10:00` },
    { id: 'series-a', title, start_dt: '2026-10-07T09:00', recurrence: 'daily', recurring: true },
  ] }] },
  '/api/tasks': [
    { id: 'task-a', title, due_date: today },
    { id: 'task-b', title, due_date: today },
    { id: 'undated', title: 'later 🌱' },
    { id: 'completed', title: 'finished', done: true, due_date: today },
  ],
  '/api/reminders': [{ id: 'reminder-a', text: 'remember', trigger_at: `${today}T12:00` }],
});

// This DOM models attachment, visibility and events, not browser layout or native key activation.
function harness(data = fixtures()) {
  let focused = null;
  class Element {
    constructor(tag) {
      this.tagName = tag.toUpperCase();
      this.children = [];
      this.dataset = {};
      this.attributes = {};
      this.events = {};
      this.style = {};
      this.className = '';
      this.textContent = '';
      this.hidden = false;
      this.disabled = false;
    }
    get childNodes() { return [...this.children]; }
    get isConnected() { return this === body || Boolean(this.parentElement?.isConnected); }
    append(...children) {
      for (const child of children) {
        child.remove();
        child.parentElement = this;
        this.children.push(child);
      }
    }
    remove() {
      if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(child => child !== this);
      this.parentElement = null;
    }
    replaceChildren(...children) {
      for (const child of [...this.children]) child.remove();
      this.append(...children);
    }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) { return this.attributes[name] ?? null; }
    removeAttribute(name) { delete this.attributes[name]; }
    addEventListener(name, handler) { this.events[name] = handler; }
    async click() { if (!this.disabled) await this.events.click?.({ preventDefault() {} }); }
    focus() { if (this.getClientRects().length && !this.disabled) focused = this; }
    scrollIntoView(options) { this.scrolled = options; }
    getClientRects() {
      if (!this.isConnected) return [];
      for (let node = this; node; node = node.parentElement) {
        if (node.hidden || node.style.display === 'none') return [];
      }
      return [{}];
    }
    querySelectorAll(selector) {
      const matches = node => {
        if (selector.startsWith('.')) return node.className.split(' ').includes(selector.slice(1));
        if (selector.startsWith('[')) {
          const [, attr, value] = selector.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/) || [];
          const key = attr?.startsWith('data-') ? attr.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase()) : null;
          const actual = key ? node.dataset[key] : node.getAttribute(attr);
          return value === undefined ? actual != null : actual === value;
        }
        return node.tagName.toLowerCase() === selector;
      };
      return this.children.flatMap(child => [...(matches(child) ? [child] : []), ...child.querySelectorAll(selector)]);
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    get classList() { return { toggle() {}, add() {}, remove() {} }; }
  }
  const body = new Element('body');
  const root = new Element('div');
  root.id = 'plan-view';
  root.dataset.groupWired = '1';
  const overview = new Element('div');
  overview.dataset.groupOverview = '';
  const slot = new Element('div');
  slot.dataset.groupSlot = '';
  root.append(overview, slot);
  const tasks = new Element('div');
  tasks.id = 'tasks-view';
  const calendar = new Element('div');
  calendar.id = 'calendar-view';
  body.append(root, tasks, calendar);
  const elements = [root, tasks, calendar];
  const calls = [];
  const location = { href: 'http://alles.test/?view=plan' };
  let open = async () => true;
  const window = { _openRecord: (...args) => { calls.push(args); return open(...args); } };
  const context = vm.createContext({
    document: { createElement: tag => new Element(tag), getElementById: id => elements.find(el => el.id === id) },
    window, location, recordTarget, formatDateParts, formatDateTime,
    calendarDateKey: value => value === undefined ? today : calendarDateKey(value),
    disposePlanBoard() {},
  });
  vm.runInContext(source.replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '') + `
    globalThis.subject = { initSpecialistGroup, planCommitments };
  `, context);
  const request = async url => {
    const value = data[url];
    if (value instanceof Error) throw value;
    assert.notEqual(value, undefined, `unexpected request: ${url}`);
    return { ok: true, json: async () => value };
  };
  return {
    root, overview, window, location, calls, data,
    setOpen: callback => { open = callback; },
    focused: () => focused,
    commitments: context.subject.planCommitments,
    render: (section = 'overview', customRequest = request) => context.subject.initSpecialistGroup('plan', { section, request: customRequest }),
    rows: () => overview.querySelectorAll('.specialist-record-row'),
    controls: () => overview.querySelectorAll('.specialist-record-row').filter(el => el.tagName === 'BUTTON'),
    choice: value => overview.querySelector('.specialist-choice-group').children.find(el => el.dataset.value === value),
    status: () => overview.querySelector('.plan-agenda-status'),
  };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

test('agenda task and event rows are named native buttons that open exact IDs despite equal Unicode titles', async () => {
  const h = harness();
  await h.render();
  assert.equal(h.controls().length, 4);
  for (const button of h.controls()) {
    assert.equal(button.type, 'button');
    assert.match(button.getAttribute('aria-label'), /open (task|event): réunion 日本語 🌱/);
    await button.click();
  }
  assert.deepEqual(h.calls, [
    ['tasks', 'task-a', ''], ['tasks', 'task-b', ''],
    ['calendar', 'series-a', today], ['calendar', 'event-b', today],
  ]);
  const reminder = h.rows().at(-1);
  assert.equal(reminder.tagName, 'DIV');
  assert.equal(reminder.events.click, undefined);
  assert.equal(h.choice('today').textContent, 'today · 5');
});

test('week keeps distinct occurrence identity and uses the existing exact-record router', async () => {
  const h = harness();
  await h.render('week');
  assert.equal(h.choice('seven').getAttribute('aria-pressed'), 'true');
  const instances = h.controls().filter(el => el.children[1].textContent === title && el.children[2].textContent.startsWith('event'));
  assert.equal(instances.length, 3);
  assert.notEqual(instances[0].dataset.planAgendaRecord, instances[2].dataset.planAgendaRecord);
  await instances[2].click();
  assert.deepEqual(h.calls, [['calendar', 'series-a', '2026-10-07']]);
});

test('offset events preserve the configured calendar date for occurrence navigation', () => {
  configureLocalization({ timezone: 'Asia/Tokyo' });
  try {
    const h = harness();
    const [row] = h.commitments([{ id: 'offset', title, start_dt: '2026-10-06T23:30:00Z', recurrence: 'daily' }], [], []);
    assert.equal(row.target.id, 'offset');
    assert.equal(row.target.occurrence, '2026-10-07');
    assert.equal(row.date, '2026-10-07');
  } finally { configureLocalization({}); }
});

test('unscheduled navigation returns to the same filter and exact record after its title changes', async () => {
  const h = harness();
  await h.render();
  await h.choice('unscheduled').click();
  const origin = h.controls()[0];
  h.setOpen(async () => {
    h.location.href = 'http://alles.test/?view=tasks&record=undated';
    await h.render('tasks');
    return true;
  });
  await origin.click();
  assert.deepEqual(h.calls, [['tasks', 'undated', '']]);
  h.data['/api/tasks'][2].title = 'renamed 日本語';
  h.location.href = 'http://alles.test/?view=plan';
  await h.render();
  assert.equal(h.choice('unscheduled').getAttribute('aria-pressed'), 'true');
  assert.equal(h.focused(), h.controls()[0]);
  assert.equal(h.focused().children[1].textContent, 'renamed 日本語');
  assert.equal(h.focused().scrolled.behavior, 'instant');
});

test('return focus identifies the selected recurrence rather than the first occurrence of its series', async () => {
  const h = harness();
  h.location.href = 'http://alles.test/?view=plan-week';
  await h.render('week');
  const origin = h.controls().at(-1);
  const key = origin.dataset.planAgendaRecord;
  await origin.click();
  h.data['/api/calendar/agenda?days=8'].days[0].events[2].title = 'renamed occurrence';
  await h.render('week');
  assert.equal(h.focused().dataset.planAgendaRecord, key);
  assert.equal(h.focused().children[1].textContent, 'renamed occurrence');
  assert.equal(h.choice('seven').getAttribute('aria-pressed'), 'true');
});

test('returning to an unavailable record focuses the active window without choosing a namesake', async () => {
  const h = harness();
  await h.render();
  await h.controls()[0].click();
  h.data['/api/tasks'].shift();
  await h.render();
  assert.equal(h.focused(), h.choice('today'));
  assert.match(h.status().textContent, /no longer in this agenda window/);
  assert.equal(h.calls.length, 1);
});

test('missing or invalid IDs never route by title or substitute another record', async () => {
  const data = fixtures();
  data['/api/tasks'] = [{ title, due_date: today }, { id: 'invalid/id', title, due_date: today }];
  const h = harness(data);
  await h.render();
  for (const button of h.controls().slice(0, 2)) await button.click();
  assert.deepEqual(h.calls, []);
  assert.match(h.status().textContent, /unavailable.*refresh/i);
});

test('router failure or unavailable router announces retry and leaves the agenda usable', async () => {
  for (const outcome of ['missing', 'false', 'throw']) {
    const h = harness();
    await h.render();
    const button = h.controls()[0];
    if (outcome === 'missing') delete h.window._openRecord;
    else h.setOpen(async () => { if (outcome === 'throw') throw new Error('offline'); return false; });
    await button.click();
    assert.match(h.status().textContent, /could not open.*try again/i);
    assert.equal(button.disabled, false);
    assert.equal(button.getAttribute('aria-busy'), null);
    assert.equal(h.focused(), button);
  }
});

test('pending navigation disables duplicate activation and stale rejection cannot take over another app', async () => {
  const h = harness();
  await h.render();
  const pending = deferred();
  h.setOpen(() => pending.promise);
  const button = h.controls()[0];
  const clicked = button.click();
  assert.equal(button.disabled, true);
  assert.equal(button.getAttribute('aria-busy'), 'true');
  await button.click();
  assert.equal(h.calls.length, 1);
  h.location.href = 'http://alles.test/?view=library';
  h.root.style.display = 'none';
  pending.reject(new Error('offline'));
  await clicked;
  assert.equal(h.focused(), null);
  assert.equal(h.status().hidden, true);
  assert.equal(h.location.href, 'http://alles.test/?view=library');
});

test('late successful navigation never dispatches a second opener after the user leaves', async () => {
  const h = harness();
  await h.render();
  const pending = deferred();
  h.setOpen(() => pending.promise);
  const clicked = h.controls()[0].click();
  h.location.href = 'http://alles.test/?view=library';
  h.root.style.display = 'none';
  pending.resolve(true);
  await clicked;
  assert.equal(h.calls.length, 1);
  assert.equal(h.focused(), null);
  assert.equal(h.location.href, 'http://alles.test/?view=library');
});

test('an older failed click cannot change status or focus after an agenda refresh on the same URL', async () => {
  const h = harness();
  await h.render();
  const pending = deferred();
  h.setOpen(() => pending.promise);
  const clicked = h.controls()[0].click();
  await h.render();
  const current = h.focused();
  pending.resolve(false);
  await clicked;
  assert.equal(h.focused(), current);
  assert.equal(h.status().hidden, true);
});

test('an older failed click cannot steal focus from a newer record opening on the same agenda', async () => {
  const h = harness();
  await h.render();
  const first = deferred();
  const second = deferred();
  h.setOpen((_view, id) => id === 'task-a' ? first.promise : second.promise);
  const firstClick = h.controls()[0].click();
  const secondClick = h.controls()[1].click();
  first.resolve(false);
  await firstClick;
  assert.equal(h.focused(), null);
  assert.equal(h.status().hidden, true);
  second.resolve(true);
  await secondClick;
  await h.render();
  assert.equal(h.focused().dataset.planAgendaRecord, 'task:task-b');
});

test('detached and hidden agenda controls never initiate navigation', async () => {
  const h = harness();
  await h.render();
  const detached = h.controls()[0];
  await h.choice('unscheduled').click();
  await detached.click();
  h.root.style.display = 'none';
  await h.controls()[0].click();
  assert.deepEqual(h.calls, []);
});

test('a superseded agenda request cannot restore focus or overwrite a newer Plan view', async () => {
  const h = harness();
  await h.render();
  await h.controls()[0].click();
  const pending = deferred();
  const rendering = h.render('overview', async url => {
    await pending.promise;
    return { ok: true, json: async () => h.data[url] };
  });
  await h.render('tasks');
  pending.resolve();
  await rendering;
  assert.equal(h.root.dataset.section, 'tasks');
  assert.equal(h.focused(), null);
  assert.equal(h.overview.hidden, true);
});

test('an agenda request finishing after another app opens cannot restore focus', async () => {
  const h = harness();
  await h.render();
  await h.controls()[0].click();
  const pending = deferred();
  const rendering = h.render('overview', async url => {
    await pending.promise;
    return { ok: true, json: async () => h.data[url] };
  });
  h.root.style.display = 'none';
  h.location.href = 'http://alles.test/?view=library';
  pending.resolve();
  await rendering;
  assert.equal(h.focused(), null);
});

test('partial agenda data retains the available records and source warning', async () => {
  const data = fixtures();
  data['/api/calendar/agenda?days=8'] = new Error('calendar offline');
  const h = harness(data);
  await h.render();
  assert.equal(h.controls().length, 2);
  assert.match(h.overview.querySelector('.specialist-group-note').textContent, /calendar unavailable: calendar offline/);
  await h.controls()[1].click();
  assert.deepEqual(h.calls, [['tasks', 'task-b', '']]);
});

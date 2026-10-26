import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { harness, tick, deferred, proposal, functionSource, captureSource } from './helpers/mail_workflows_recovery.mjs';
import { t } from '../../static/js/i18n.js';

globalThis.document = { addEventListener() {}, removeEventListener() {}, querySelector: () => null, getElementById: () => null,
  documentElement: { style: { setProperty() {} } } };
globalThis.window ??= { addEventListener() {}, dispatchEvent() {} };
globalThis.CSS ??= { escape: String };
const { restoreBoardFocus } = await import('../../static/js/plan_board.js');

const keydown = (h, key) => (h.document.listeners.keydown || []).map(fn => fn({ key, defaultPrevented: false, preventDefault() {} }));

test('escape still closes the capture review after focus fell to the page', async () => {
  const h = harness(); h.context.proposal = proposal;
  assert.equal(await h.run("openCaptureReview(proposal, $('mail-compose-btn'))"), true);
  h.document.activeElement = h.document.body;
  await Promise.all(keydown(h, 'Escape')); await tick();
  assert.equal(h.document.querySelector('.capture-overlay'), null);
  assert.equal(h.context.active, false);
  assert.deepEqual(h.document.listeners.keydown, [], 'the page-level listener leaves with the review');
});

test('escape with focus inside the review is left to the review itself', async () => {
  const h = harness(); h.context.proposal = proposal;
  await h.run("openCaptureReview(proposal, $('mail-compose-btn'))");
  h.$('capture-title').focus();
  await Promise.all(keydown(h, 'Escape'));
  assert.ok(h.document.querySelector('.capture-overlay'));
});

test('a save that ends with focus on the page puts it on "open in plan"', async () => {
  const h = harness(); h.context.proposal = proposal;
  const gate = deferred();
  h.context.recordTarget = (view, id) => (id ? { view, id } : null);
  h.context.crypto = { randomUUID: () => '00000000-0000-4000-8000-000000000001' };
  h.add('requestId', captureSource);
  h.context.fetch = async url => {
    if (url === '/api/settings') return { json: async () => ({}) };
    await gate.promise;
    return { ok: true, status: 200, json: async () => ({ id: 'saved-task', title: 'synthetic task', source: {} }) };
  };
  await h.run("openCaptureReview(proposal, $('mail-compose-btn'))");
  const saving = h.click(h.$('capture-accept')); await tick();
  // a second click lands on the disabled button and the browser drops focus to the page
  h.document.activeElement = h.document.body;
  gate.resolve(); await saving;
  assert.match(h.document.querySelector('.capture-status').textContent, /saved in plan/);
  assert.equal(h.document.activeElement?.id, 'capture-open');
});

test('board focus after a move: same button, else the other one, else the card', () => {
  const node = (name, disabled = false) => ({ name, disabled, getClientRects: () => [{}], focus() { focused = name; } });
  let focused = '';
  const buttons = { back: node('back', true), forward: node('forward') };
  const detail = { querySelector: selector => buttons[/data-act="(\w+)"/.exec(selector)?.[1]] || null };
  const root = { querySelector: selector => (selector.includes('data-task-id="t1"') ? node('card t1')
    : selector.includes('data-task-id="t2"') ? node('card t2') : null) };
  restoreBoardFocus(root, detail, { action: 'forward', taskId: 't1' }, true);
  assert.equal(focused, 'forward');
  restoreBoardFocus(root, detail, { action: 'back', taskId: 't1' }, true);
  assert.equal(focused, 'forward', 'back is disabled at the first stage, so the other move button');
  buttons.forward.disabled = true;
  restoreBoardFocus(root, detail, { action: 'back', taskId: 't1' }, true);
  assert.equal(focused, 'card t1');
  restoreBoardFocus(root, detail, { action: 'complete', taskId: 't1', stage: 'doing', nextId: 't2' }, false);
  assert.equal(focused, 'card t2');
});

test('the completion receipt stays hidden while the tasks view is hidden', () => {
  const source = readFileSync(new URL('../../static/js/tasks.js', import.meta.url), 'utf8');
  const nodes = { 'tasks-view': { hidden: false, style: { display: 'none' } }, 'task-completion-receipt': { hidden: true },
    'task-completion-message': {}, 'task-completion-undo': { setAttribute() {} } };
  const context = vm.createContext({ document: { getElementById: id => nodes[id] || null }, tr: key => key });
  vm.runInContext(`let _completionReceipt = { title: 'synthetic', message: 'tasks.completed_named' };\n${functionSource('renderCompletion', source)}`, context);
  vm.runInContext('renderCompletion()', context);
  assert.equal(nodes['task-completion-receipt'].hidden, true);
  nodes['tasks-view'].style.display = 'flex';
  vm.runInContext('renderCompletion()', context);
  assert.equal(nodes['task-completion-receipt'].hidden, false);
  assert.match(source, /new MutationObserver\(renderCompletion\)\.observe\(view, \{ attributes: true, attributeFilter: \['style', 'hidden'\] \}\)/);
});

test('search opens a task, an event or a message itself, not just its app', async () => {
  const source = readFileSync(new URL('../../static/js/search.js', import.meta.url), 'utf8');
  const calls = [];
  const window = {
    _openRecord: async (view, id) => { calls.push(['record', view, id]); return true; },
    _navigateTo: async view => { calls.push(['nav', view]); return true; },
  };
  const context = vm.createContext({ window });
  vm.runInContext(functionSource('_openOption', source), context);
  // arrays from the vm realm compare by shape only once copied out
  const open = async dataset => JSON.parse(JSON.stringify(await context._openOption({ dataset })));
  assert.deepEqual(await open({ type: 'record', view: 'calendar', id: 'event-1' }), [true, true]);
  assert.deepEqual(await open({ type: 'record', view: 'tasks', id: 'task-1' }), [true, true]);
  // mail can't open one message yet without its own hook, so it falls back to the inbox
  assert.deepEqual(await open({ type: 'mail', view: 'mail', id: '42', aid: 'acct', folder: 'INBOX' }), [true, false]);
  window._openMailMessage = async (aid, uid, folder) => { calls.push(['mail', aid, uid, folder]); return true; };
  assert.deepEqual(await open({ type: 'mail', view: 'mail', id: '42', aid: 'acct', folder: 'INBOX' }), [true, true]);
  assert.deepEqual(await open({ type: 'nav', view: 'books' }), [true, false]);
  assert.deepEqual(calls, [['record', 'calendar', 'event-1'], ['record', 'tasks', 'task-1'], ['nav', 'mail'],
    ['mail', 'acct', '42', 'INBOX'], ['nav', 'books']]);
  assert.match(source, /data-type="record" data-view="tasks" data-id="\$\{_esc\(task\.id\)\}"/);
  assert.match(source, /data-type="record" data-view="calendar" data-id="\$\{_esc\(event\.id\)\}"/);
});

test('opening a day from the month lands on what was picked, else its first item, else today', () => {
  const source = readFileSync(new URL('../../static/js/calendar.js', import.meta.url), 'utf8');
  let focused = '';
  const node = name => ({ focus() { focused = name; } });
  // the first all-day item, else the first timed event: whichever comes first on the page
  const items = { '.cal-tg-allday .cal-task[data-task="t1"]': node('task t1'), '.cal-tg-allday button, .cal-tev[data-id]': node('first all-day') };
  const list = { querySelector: selector => items[selector] || null };
  const context = vm.createContext({
    document: { getElementById: id => (id === 'calendar-list' ? list : id === 'cal-today' ? node('today') : null) },
    localStorage: { setItem() {} }, calendarPlacementDate: value => value,
    render() {}, _syncViewBtns() {},
  });
  vm.runInContext(`let _cursor, _view;\n${functionSource('_openDay', source)}`, context);
  vm.runInContext(`_openDay('2026-10-23', '.cal-tg-allday .cal-task[data-task="t1"]')`, context);
  assert.equal(focused, 'task t1');
  vm.runInContext(`_openDay('2026-10-23')`, context);
  assert.equal(focused, 'first all-day');
  delete items['.cal-tg-allday button, .cal-tev[data-id]'];
  vm.runInContext(`_openDay('2026-10-23')`, context);
  assert.equal(focused, 'today');
  // a refill or a new "+N more" is sized by kokuen before the trim measures it
  assert.match(functionSource('_refillMonthCells', source), /initKokuenPrimitives\(grid\)/);
  assert.match(functionSource('_setMore', source), /initKokuenPrimitives\(head\)/);
  // a month task line opens its day; completing stays on the day's 44px toggle
  assert.doesNotMatch(source.slice(source.indexOf("querySelectorAll('.cal-cell:not(.empty)')")), /^\s*await _toggleCalTask/m);
});

test('the browser zone is only sent when the browser really reports one', async () => {
  const { chosenTimeZone, resolvedTimeZone, configureLocalization } = await import('../../static/js/i18n.js');
  const real = Intl.DateTimeFormat;
  try {
    configureLocalization({ timezone: 'America/Toronto' });
    assert.equal(chosenTimeZone(), 'America/Toronto');
    configureLocalization({});
    Intl.DateTimeFormat = function broken() { throw new Error('no intl'); };
    assert.equal(chosenTimeZone(), '', 'a guess is not a choice');
    assert.equal(resolvedTimeZone(), 'UTC', 'formatting still has a zone to use');
  } finally {
    Intl.DateTimeFormat = real;
    configureLocalization({});
  }
  const source = readFileSync(new URL('../../static/js/calendar.js', import.meta.url), 'utf8');
  assert.match(source, /const zoneHeader = \(\) => \{ const zone = chosenTimeZone\(\); return zone \? \{ 'x-alles-time-zone': zone \} : \{\}; \};/);
  // every calendar request carries it: no bare fetch of /api/calendar left without the zone
  const bare = source.split('\n').filter(line => /fetch\(\s*[`'"]\/api\/calendar(?!s)/.test(line)
    && !/zoneHeader|withZone/.test(line) && !/,\s*\{\s*$/.test(line));
  assert.deepEqual(bare, []);
});

test('the date strip opens the day in every cell and "+N more" names its day', () => {
  const source = readFileSync(new URL('../../static/js/calendar.js', import.meta.url), 'utf8');
  assert.match(source, /class="cal-more" data-day="\$\{day\}" aria-label="\$\{esc\(trp\('calendar\.more_on_day', n, \{ day: _dayLabel\(day\) \}\)\)\}"/);
  assert.match(source, /class="cal-day-open" data-day="\$\{day\}" tabindex="-1" aria-label="\$\{esc\(tr\('calendar\.open_day', \{ day: _dayLabel\(day\) \}\)\)\}"/);
  assert.match(source, /ev\.target\.closest\('\.cal-more, \.cal-day-open'\)/);
  // narrow cells lead with the title so it stays readable
  assert.match(source, /titleFirst \? `\$\{o\.title\} \$\{timeShort\(o\._date\)\}`/);
});

test('a timed event in the day or week grid is a button the keyboard can open', () => {
  const source = readFileSync(new URL('../../static/js/calendar.js', import.meta.url), 'utf8');
  assert.match(source, /class="cal-tev\$\{o\._recur \? ' recurring' : ''\}" role="button" tabindex="0" aria-label="\$\{esc\(name\)\}"/);
  assert.match(source, /const name = tr\('calendar\.event_span', \{ title: o\.title, start: timeShort\(o\._date\), end: timeShort\(it\.end\) \}\);/);
  const handlers = {};
  const body = { addEventListener: (type, fn) => { handlers[type] = fn; } };
  const el = { querySelector: s => (s === '.cal-tg-body' ? body : null), querySelectorAll: () => [{}] };
  const opened = [];
  const context = vm.createContext({ HOUR_H: 44, document: {}, openEvent: (id, occ) => opened.push(`${id}@${occ}`),
    openStack: stack => opened.push(`day ${stack.dataset.day}`) });
  vm.runInContext(functionSource('attachDrag', source), context);
  vm.runInContext('attachDrag', context)(el, []);
  const tev = { dataset: { id: 'e1', occ: '2026-10-23' }, classList: { contains: () => false } };
  const stack = { dataset: { day: '2026-10-24', first: 'e2' }, classList: { contains: name => name === 'cal-tstack' } };
  const press = (key, on = tev) => {
    let prevented = false;
    handlers.keydown({ key, target: { closest: s => (on && s === '.cal-tev[data-id], .cal-tstack' ? on : null) }, preventDefault() { prevented = true; } });
    return prevented;
  };
  assert.equal(press('Enter'), true);
  assert.equal(press(' '), true);
  assert.equal(press('a'), false);
  assert.equal(press('Enter', null), false, 'enter elsewhere in the grid is left alone');
  assert.equal(press('Enter', stack), true, 'a stack of overlapping events opens its day');
  assert.deepEqual(opened, ['e1@2026-10-23', 'e1@2026-10-23', 'day 2026-10-24']);
});

test('focus comes back to the occurrence that was open, then any copy, then the day', () => {
  const source = readFileSync(new URL('../../static/js/calendar.js', import.meta.url), 'utf8');
  let focused = '';
  const node = name => ({ isConnected: true, getClientRects: () => [{}], focus() { focused = name; } });
  const own = ':is(button.cal-chip, button.cal-allday-ev, .cal-tev, button.cal-agenda-ev)[data-id="e1"]';
  const items = { [`${own}[data-occ="2026-10-24"]`]: node('saturday copy'), [own]: node('first copy'),
    '.cal-more[data-day="2026-10-24"]': node('more') };
  const list = { querySelector: selector => items[selector] || null };
  const context = vm.createContext({ CSS: { escape: String },
    document: { getElementById: id => (id === 'calendar-list' ? list : id === 'cal-new-btn' ? node('new') : null) } });
  vm.runInContext(functionSource('focusAfterEditor', source), context);
  vm.runInContext(`focusAfterEditor('e1', '2026-10-24')`, context);
  assert.equal(focused, 'saturday copy');
  delete items[`${own}[data-occ="2026-10-24"]`];
  vm.runInContext(`focusAfterEditor('e1', '2026-10-24')`, context);
  assert.equal(focused, 'first copy');
  delete items[own];
  vm.runInContext(`focusAfterEditor('e1', '2026-10-24')`, context);
  assert.equal(focused, 'more');
});

test('escape leaves the editor, and a tap on an empty slot starts at the title', () => {
  const source = readFileSync(new URL('../../static/js/calendar.js', import.meta.url), 'utf8');
  assert.match(source, /if \(e\.key !== 'Escape' \|\| e\.defaultPrevented \|\| e\.isComposing\) return;\n\s*e\.preventDefault\(\);\n\s*leaveEditor\(\);/);
  let focused = '';
  const calls = [];
  const context = vm.createContext({
    openEditor: (...args) => calls.push(args),
    window: { matchMedia: () => ({ matches: false }) },
    document: { getElementById: id => (id === 'cal-title' ? { value: '', focus() { focused = id; }, setSelectionRange() {} } : null) },
  });
  vm.runInContext(`${functionSource('createAt', source)}\n${functionSource('focusEditor', source)}`, context);
  vm.runInContext(`createAt('2026-10-23', 10)`, context);
  assert.equal(JSON.stringify(calls), JSON.stringify([[null, '2026-10-23', 10, null]]));
  assert.equal(focused, 'cal-title');
  // the grid (tap and drag), the month and the all-day row all create through it
  assert.equal((source.match(/createAt\(/g) || []).length, 5);
});

test('opening an event: the caret goes after the title with a keyboard, the editor takes focus on touch', () => {
  const source = readFileSync(new URL('../../static/js/calendar.js', import.meta.url), 'utf8');
  let coarse = false, focused = '', caret = null;
  const title = { value: 'dentist', focus() { focused = 'title'; }, setSelectionRange(a, b) { caret = [a, b]; } };
  const heading = { focus() { focused = 'heading'; } };
  const context = vm.createContext({
    window: { matchMedia: query => ({ matches: query === '(pointer: coarse)' && coarse }) },
    document: { getElementById: id => ({ 'cal-title': title, 'cal-ed-head': heading })[id] || null },
  });
  vm.runInContext(functionSource('focusEditor', source), context);
  vm.runInContext('focusEditor(true)', context);
  assert.equal(focused, 'title'); assert.deepEqual(caret, [7, 7]);
  caret = null; vm.runInContext('focusEditor(false)', context);
  assert.equal(caret, null, 'a new title is empty: nothing to move past');
  coarse = true; vm.runInContext('focusEditor(true)', context);
  assert.equal(focused, 'heading', 'no keyboard pops over the event on a phone');
  assert.match(source, /<div class="cal-editor" role="form" aria-labelledby="cal-ed-head">\n\s*<h2 class="cal-ed-head" id="cal-ed-head" tabindex="-1">\$\{esc\(tr\(isNew \? 'calendar\.editor_new' : 'calendar\.editor_edit'\)\)\}<\/h2>/);
  const css = readFileSync(new URL('../../static/style.css', import.meta.url), 'utf8');
  assert.match(css, /\.cal-editor \.cal-ed-head:focus \{ outline: none; \}/, 'programmatic focus draws no ring');
});

test('escape on the page still leaves the editor after a click dropped focus there', () => {
  const source = readFileSync(new URL('../../static/js/calendar.js', import.meta.url), 'utf8');
  const listeners = new Set();
  const body = {}, root = {};
  let dialogOpen = false;
  const document = { body, documentElement: root, querySelector: s => (s === '.dialog-overlay' && dialogOpen ? {} : null),
    addEventListener: (type, fn) => listeners.add(fn), removeEventListener: (type, fn) => listeners.delete(fn) };
  let left = 0;
  const context = vm.createContext({ document, leaveEditor: () => { left++; } });
  vm.runInContext(`let _pageEscape = null;\n${functionSource('escapeLeaves', source)}\n${functionSource('watchPageEscape', source)}`, context);
  const editor = { isConnected: true };
  vm.runInContext('watchPageEscape', context)(editor);
  const key = (target, extra = {}) => {
    const e = { key: 'Escape', target, defaultPrevented: false, isComposing: false, preventDefault() { this.defaultPrevented = true; }, ...extra };
    for (const fn of [...listeners]) fn(e);
    return e;
  };
  assert.equal(key(body).defaultPrevented, true); assert.equal(left, 1);
  key({ closest: () => null }); assert.equal(left, 1, 'a key inside the editor is the editor listener\'s job');
  key(body, { defaultPrevented: true }); assert.equal(left, 1, 'something else already took it');
  dialogOpen = true; key(body); assert.equal(left, 1, 'the discard question owns escape, even with focus on the page');
  dialogOpen = false;
  editor.isConnected = false; key(body); assert.equal(left, 1);
  assert.equal(listeners.size, 0, 'the page listener leaves with the editor');
});

test('a dragged event keeps its own length; only a resize reads the box', () => {
  const source = readFileSync(new URL('../../static/js/calendar.js', import.meta.url), 'utf8');
  const context = vm.createContext({ _events: [{ id: 'e1' }],
    editorDates: () => ({ start: '2026-10-23T20:00', end: '2026-10-23T20:15' }) });
  vm.runInContext(`${source.match(/^class CalendarWallDate[^]*?^}/m)[0]}
const _pad = n => String(n).padStart(2, '0');
const ymd = d => \`\${d.getFullYear()}-\${_pad(d.getMonth() + 1)}-\${_pad(d.getDate())}\`;
const localISO = d => \`\${ymd(d)}T\${_pad(d.getHours())}:\${_pad(d.getMinutes())}\`;
const calendarPlacementDate = v => new CalendarWallDate(Date.parse(v + ':00Z'));
${functionSource('endAfterMove', source)}`, context);
  assert.equal(vm.runInContext(`endAfterMove('e1', '2026-10-23', '2026-10-23T21:00')`, context), '2026-10-23T21:15');
  assert.match(source, /applyTimeChange\(s\.id, s\.occ, \.\.\.resizedTimes\(s\.id, s\.occ, atTime\(date, top \+ h\)\)\)/);
  assert.match(source, /applyTimeChange\(s\.id, s\.occ, start, endAfterMove\(s\.id, s\.occ, start\)\)/);
});

test('a resize moves only the end; leaving asks one question however many escapes arrive', async () => {
  const source = readFileSync(new URL('../../static/js/calendar.js', import.meta.url), 'utf8');
  const context = vm.createContext({ _events: [{ id: 'e1' }],
    editorDates: () => ({ start: '2026-10-23T13:10', end: '2026-10-23T13:40' }) });
  vm.runInContext(`${source.match(/^class CalendarWallDate[^]*?^}/m)[0]}
const _pad = n => String(n).padStart(2, '0');
const ymd = d => \`\${d.getFullYear()}-\${_pad(d.getMonth() + 1)}-\${_pad(d.getDate())}\`;
const localISO = d => \`\${ymd(d)}T\${_pad(d.getHours())}:\${_pad(d.getMinutes())}\`;
const calendarPlacementDate = v => new CalendarWallDate(Date.parse(v + ':00Z'));
${functionSource('resizedTimes', source)}`, context);
  const resized = end => JSON.parse(JSON.stringify(vm.runInContext(`resizedTimes('e1', '', '${end}')`, context)));
  assert.deepEqual(resized('2026-10-23T14:00'), ['2026-10-23T13:10', '2026-10-23T14:00'], 'the 13:10 start stays');
  assert.deepEqual(resized('2026-10-23T13:00'), ['2026-10-23T13:10', '2026-10-23T13:25'], 'never ends before it starts');
  // the drag stops at the end of the day instead of wrapping into tomorrow
  assert.match(source, /const lowest = Math\.max\(st\.top0, DAY_H - st\.tev\.offsetHeight - 2\);\n\s*st\.tev\.style\.top = Math\.min\(snap\(st\.top0 \+ \(e\.clientY - st\.y0\)\), lowest\)/);

  let asked = 0, answer;
  const ctx = vm.createContext({ _saving: false, _readDraft: () => 'changed', _draftSnapshot: 'saved', _editing: null, _editOcc: null, tr: t,
    dlgConfirm: () => { asked++; return new Promise(resolve => { answer = resolve; }); },
    loadCalendar: async () => false, focusAfterEditor() {},
    document: { body: 'page', activeElement: 'page' }, focusEditor: () => { refocused++; } });
  let refocused = 0;
  vm.runInContext(`let _leaving = false;\n${functionSource('leaveEditor', source)}`, ctx);
  const first = vm.runInContext('leaveEditor()', ctx);
  vm.runInContext('leaveEditor()', ctx); vm.runInContext('leaveEditor()', ctx);
  assert.equal(asked, 1);
  answer(false); await first;
  assert.equal(refocused, 1, 'kept editing: focus goes back into the editor, not the page');
  vm.runInContext('leaveEditor()', ctx);
  assert.equal(asked, 2, 'after the answer the next escape asks again');
});

test('overlap groups stack when side by side each would be under 44px, at any width', () => {
  const source = readFileSync(new URL('../../static/js/calendar.js', import.meta.url), 'utf8');
  assert.match(source, /const stacks = \(n, width\) => days\.length > 1 && n > 1 && \(colWidth\(width\) - 4\) \/ n < 44;/);
  const colWidth = width => (width - 52) / 7, stacks = (n, width) => n > 1 && (colWidth(width) - 4) / n < 44;
  assert.equal(stacks(2, 390), true);
  assert.equal(stacks(6, 640), true, 'six overlaps at 640px drew 12px boxes');
  assert.equal(stacks(2, 620), true, '601-640px drew 24-38px boxes');
  assert.equal(stacks(2, 1440), false);
  assert.equal(stacks(5, 1440), true);
  // the box shows an icon and the count; the words go to screen readers, translated
  assert.match(source, /trp\('calendar\.overlap_stack', group\.length, \{ start: timeShort\(o\._date\), end: timeShort\(last\) \}\)/);
  assert.match(source, /<div class="cal-tev-box" aria-hidden="true">\$\{_si\('columns'\)\}<b>\$\{group\.length\}<\/b><\/div>/);
});

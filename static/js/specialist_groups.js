// Stage 8 specialist composition. The group shell owns navigation and overview
// data; the existing app modules continue to own their full, proven screens.

import { confirm as confirmDialog } from './dialog.js';
import { initDatePicker } from './datepick.js';
import { calendarDateKey, chosenTimeZone, formatCalendarDate, formatClock, formatDateParts, formatDateTime, formatNumber, t, tp } from './i18n.js';
import { disposePlanBoard, renderPlanBoard } from './plan_board.js';
import { requestWithRecentOwner } from './recent_owner.js';
import { recordTarget } from './recordlinks.js';

export function mailboxAddress(value) {
  const raw = String(value || '').trim();
  const bracketed = raw.match(/<\s*([^<>\s]+@[^<>\s]+)\s*>/);
  const bare = raw.match(/(?:^|\s)([^<>\s,;]+@[^<>\s,;]+)(?:$|\s)/);
  return String(bracketed?.[1] || bare?.[1] || raw).trim().toLowerCase();
}

export const GROUP_DEFINITIONS = Object.freeze({
  plan: Object.freeze({
    rootId: 'plan-view',
    sections: Object.freeze(['overview', 'week', 'board', 'calendar', 'tasks', 'reminders', 'days']),
    legacyRoots: Object.freeze({ calendar: 'calendar-view', tasks: 'tasks-view', reminders: 'reminders-view', days: 'days-view' }),
  }),
  inbox: Object.freeze({
    rootId: 'inbox-view',
    sections: Object.freeze(['overview', 'mail', 'contacts']),
    legacyRoots: Object.freeze({ mail: 'mail-view', contacts: 'contacts-view' }),
  }),
  library: Object.freeze({
    rootId: 'library-view',
    sections: Object.freeze(['overview', 'books', 'read']),
    legacyRoots: Object.freeze({ books: 'books-view', read: 'read-view' }),
  }),
  health: Object.freeze({
    rootId: 'health-group-view',
    sections: Object.freeze(['overview', 'health', 'habits']),
    legacyRoots: Object.freeze({ health: 'health-view', habits: 'habits-view' }),
  }),
  finance: Object.freeze({
    rootId: 'finance-view',
    sections: Object.freeze(['overview', 'money', 'subs', 'imports']),
    legacyRoots: Object.freeze({ money: 'money-view', subs: 'subs-view' }),
  }),
  docs: Object.freeze({
    rootId: 'docs-workbench-view',
    sections: Object.freeze(['notes', 'journal']),
    legacyRoots: Object.freeze({ notes: 'wiki-view', journal: 'wiki-view' }),
  }),
  files: Object.freeze({
    rootId: 'files-workbench-view',
    sections: Object.freeze(['files', 'gallery']),
    legacyRoots: Object.freeze({ files: 'files-view', gallery: 'photos-view' }),
  }),
  vault: Object.freeze({
    rootId: 'vault-workbench-view',
    sections: Object.freeze(['items']),
    legacyRoots: Object.freeze({ items: 'vault-view' }),
  }),
  server: Object.freeze({
    rootId: 'server-workbench-view',
    sections: Object.freeze(['overview', 'services', 'search', 'backups', 'updates', 'logs', 'activity', 'watch', 'policy']),
    legacyRoots: Object.freeze({ overview: 'system-view', activity: 'activity-view', watch: 'watch-view' }),
  }),
});

const ROUTES = Object.freeze({
  plan: ['plan', 'overview'], 'plan-week': ['plan', 'week'], 'plan-board': ['plan', 'board'], calendar: ['plan', 'calendar'], tasks: ['plan', 'tasks'], reminders: ['plan', 'reminders'], days: ['plan', 'days'],
  inbox: ['inbox', 'overview'], mail: ['inbox', 'mail'], contacts: ['inbox', 'contacts'],
  library: ['library', 'overview'], books: ['library', 'books'], read: ['library', 'read'],
  health: ['health', 'overview'], 'health-overview': ['health', 'overview'], 'health-log': ['health', 'health'], habits: ['health', 'habits'],
  finance: ['finance', 'overview'], 'finance-overview': ['finance', 'overview'], money: ['finance', 'money'], subs: ['finance', 'subs'], imports: ['finance', 'imports'],
  docs: ['docs', 'notes'], wiki: ['docs', 'notes'], 'docs-notes': ['docs', 'notes'], journal: ['docs', 'journal'],
  files: ['files', 'files'], 'files-list': ['files', 'files'], photos: ['files', 'gallery'], 'files-gallery': ['files', 'gallery'],
  vault: ['vault', 'items'], secrets: ['vault', 'items'], 'vault-items': ['vault', 'items'],
  server: ['server', 'overview'], system: ['server', 'overview'],
  'server-services': ['server', 'services'], 'server-search': ['server', 'search'],
  'server-backups': ['server', 'backups'], 'server-updates': ['server', 'updates'],
  'server-logs': ['server', 'logs'], activity: ['server', 'activity'], 'server-activity': ['server', 'activity'], watch: ['server', 'watch'], 'server-watch': ['server', 'watch'],
  'server-policy': ['server', 'policy'],
});

const _states = new Map();
const _legacyHomes = new Map();
let _planAgendaReturn = null;
export function groupRouteFor(view) {
  const route = ROUTES[String(view || '').trim().toLowerCase()];
  return route ? { group: route[0], section: route[1] } : null;
}

export function normalizeGroupSection(group, section) {
  const definition = GROUP_DEFINITIONS[group];
  const fallback = definition?.sections.includes('overview') ? 'overview' : definition?.sections[0] || 'overview';
  const value = String(section || '').trim().toLowerCase() || fallback;
  return definition?.sections.includes(value) ? value : fallback;
}

export function groupIdentifierFor(group, section) {
  const normalized = normalizeGroupSection(group, section);
  if (group === 'plan' && (normalized === 'week' || normalized === 'board')) {
    return `plan-${normalized}`;
  }
  if (normalized === 'overview' && (group === 'health' || group === 'finance')) {
    return `${group}-overview`;
  }
  if (group === 'health' && normalized === 'health') return 'health-log';
  if (group === 'docs') return normalized === 'notes' ? 'docs' : 'journal';
  if (group === 'files') return normalized === 'files' ? 'files' : 'files-gallery';
  if (group === 'vault') return 'vault';
  if (group === 'server') {
    if (normalized === 'overview') return 'server';
    if (normalized === 'activity' || normalized === 'watch') return normalized;
    return `server-${normalized}`;
  }
  return normalized === 'overview' ? group : normalized;
}

function _el(tag, className = '', text = '') {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== '') node.textContent = text;
  return node;
}

function _asArray(value, key = '') {
  if (Array.isArray(value)) return value;
  return key && Array.isArray(value?.[key]) ? value[key] : [];
}

async function _json(request, url, options) {
  const method = String(options?.method || 'GET').toUpperCase();
  const response = method === 'GET' || method === 'HEAD'
    ? await request(url, options)
    : await requestWithRecentOwner(request, url, options);
  if (!response.ok) {
    let payload = null;
    try { payload = await response.json(); } catch { /* keep the bounded fallback */ }
    const message = payload?.error?.message || payload?.detail?.message || payload?.detail;
    throw new Error(typeof message === 'string' ? message : t('groups.request_failed_status', { status: response.status }));
  }
  return response.json();
}

function _setAsyncControlBusy(control, busy) {
  if (!control) return;
  control.disabled = busy;
  if (busy) control.setAttribute('aria-busy', 'true');
  else control.removeAttribute('aria-busy');
}

function _list(title, rows, emptyCopy) {
  const section = _el('section', 'specialist-group-card');
  section.append(_el('h2', '', title));
  const list = _el('div', 'specialist-group-list');
  if (!rows.length) list.append(_el('p', 'specialist-group-empty', emptyCopy));
  for (const row of rows.slice(0, 6)) {
    const item = _el('div', 'specialist-group-row');
    item.append(_el('strong', '', row.title || t('groups.untitled')));
    if (row.meta) item.append(_el('span', '', row.meta));
    list.append(item);
  }
  section.append(list);
  return section;
}

function _dateLabel(value) {
  const raw = String(value || '');
  if (!raw) return '';
  const parsed = new Date(raw);
  return Number.isNaN(parsed.valueOf()) ? raw.slice(0, 16) : formatDateTime(parsed, { dateStyle: 'medium', timeStyle: 'short' });
}

function _settled(result, fallback) {
  return result.status === 'fulfilled' ? result.value : fallback;
}

function _settledError(result, fallback) {
  if (result.status !== 'rejected') return '';
  return result.reason?.message || fallback;
}

function _partialAvailability(failures) {
  const unavailable = failures.filter(([, error]) => error);
  if (!unavailable.length) return null;
  const note = _el(
    'p',
    'specialist-group-note',
    // which source is missing is what helps; its error text ("request failed: 500") isn't
    t('groups.partial_data', { sources: unavailable.map(([source]) => source).join(', ') }),
  );
  note.setAttribute('role', 'status');
  return note;
}

function _sectionJump(group, section, label, className = '') {
  const button = _el('button', className, label);
  button.type = 'button';
  button.addEventListener('click', () => window._navigateSpecialistSection?.(group, section));
  return button;
}

function _choiceButtons(label, choices, selected, onSelect) {
  const group = _el('div', 'specialist-choice-group');
  group.setAttribute('aria-label', label);
  const buttons = choices.map(choice => {
    const button = _el('button', '', choice.label);
    button.type = 'button';
    button.dataset.value = choice.value;
    button.setAttribute('aria-pressed', choice.value === selected ? 'true' : 'false');
    button.addEventListener('click', () => {
      buttons.forEach(item => item.setAttribute('aria-pressed', item === button ? 'true' : 'false'));
      onSelect(choice.value);
    });
    group.append(button);
    return button;
  });
  return group;
}

function _dateKey(value) {
  const raw = String(value || '');
  const wall = /^(\d{4}-\d{2}-\d{2})(?:T(\d{2}):(\d{2})(?::\d{2}(?:\.\d{1,3})?)?)?$/.exec(raw);
  if (wall) return wall[1];
  const date = new Date(raw);
  if (Number.isNaN(date.valueOf())) return '';
  return calendarDateKey(date);
}

function _todayKey() {
  return calendarDateKey();
}

export function addDateKeyDays(value, days) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ''));
  if (!match || !Number.isInteger(days)) return '';
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  if (
    date.getUTCFullYear() !== year
    || date.getUTCMonth() !== month - 1
    || date.getUTCDate() !== day
  ) return '';
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function _timeKey(value) {
  const raw = String(value || '');
  if (!raw.includes('T')) return '';
  const wall = /^\d{4}-\d{2}-\d{2}T(\d{2}):(\d{2})(?::\d{2}(?:\.\d{1,3})?)?$/.exec(raw);
  if (wall) return `${wall[1]}:${wall[2]}`;
  const date = new Date(raw);
  if (Number.isNaN(date.valueOf())) return '';
  const parts = formatDateParts(date, {
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  });
  const fields = Object.fromEntries(parts.map(part => [part.type, part.value]));
  return `${fields.hour}:${fields.minute}`;
}

function _commitmentSortKey(value) {
  const date = _dateKey(value);
  if (!date) return '9999-99-99T99:99';
  return `${date}T${_timeKey(value) || '00:00'}`;
}

export function planCommitments(events, tasks, reminders) {
  const rows = [];
  for (const item of events || []) {
    const when = String(item.start_dt || item.start || item.date || '');
    const date = _dateKey(when);
    rows.push({
      id: `event:${item.id || ''}:${date}`,
      target: date ? recordTarget('calendar', item.id, date) : null,
      type: 'event',
      title: item.title || t('groups.untitled_event'),
      date,
      time: _timeKey(when),
      meta: item.location || item.calendar || t('groups.type_calendar'),
      sort: _commitmentSortKey(when),
    });
  }
  for (const item of tasks || []) {
    const terminal = String(item.stage || item.status || '').trim().toLowerCase();
    if (item.done === true || ['done', 'completed', 'cancelled', 'canceled'].includes(terminal)) continue;
    const when = String(item.due_date || item.due_at || '');
    rows.push({
      id: `task:${item.id || ''}`,
      target: recordTarget('tasks', item.id),
      type: 'task',
      title: item.title || t('groups.untitled_task'),
      date: _dateKey(when),
      time: _timeKey(when),
      meta: item.project_name || item.status || t('groups.type_task'),
      sort: _commitmentSortKey(when),
    });
  }
  for (const item of reminders || []) {
    // trigger_at is utc saved without its "Z"; read bare it lands hours off in any other zone
    const raw = String(item.trigger_at || item.date || '');
    const when = raw.includes('T') && !/(Z|[+-]\d\d:?\d\d)$/.test(raw) ? `${raw}Z` : raw;
    rows.push({
      id: `reminder:${item.id || when}:${item.text || ''}`,
      type: 'reminder',
      title: item.text || item.title || t('groups.untitled_reminder'),
      date: _dateKey(when),
      time: _timeKey(when),
      meta: item.repeat_rule || t('groups.type_reminder'),
      sort: _commitmentSortKey(when),
    });
  }
  return rows.sort((left, right) => left.sort.localeCompare(right.sort) || left.title.localeCompare(right.title));
}

function _agendaDayLabel(key) {
  if (!key) return t('groups.no_date');
  const today = calendarDateKey(new Date());
  if (key === today) return t('common.today');
  const next = new Date(`${today}T00:00:00Z`);
  next.setUTCDate(next.getUTCDate() + 1);
  if (key === next.toISOString().slice(0, 10)) return t('groups.tomorrow');
  return formatCalendarDate(key, { weekday: 'short', month: 'short', day: 'numeric' }).toLowerCase();
}

const _typeLabel = type => ({
  event: t('groups.type_event'), task: t('groups.type_task'), reminder: t('groups.type_reminder'),
}[type] || type);

function _agendaRows(target, rows, emptyCopy, openRecord) {
  target.replaceChildren();
  if (!rows.length) {
    target.append(_el('p', 'specialist-workbench-empty', emptyCopy));
    return;
  }
  // rows over more than one day read under a heading per day, so the first column is only the
  // time ("09:00", or "due" for a task with a date and no time)
  const days = new Set(rows.map(row => row.date || ''));
  const byDay = days.size > 1;
  let lastDay = null;
  for (const row of rows) {
    if (byDay && row.date !== lastDay) {
      lastDay = row.date;
      target.append(_el('h3', 'specialist-record-day', _agendaDayLabel(row.date)));
    }
    const interactive = row.type === 'task' || row.type === 'event';
    const item = _el(interactive ? 'button' : 'div', `specialist-record-row${row.overdue ? ' overdue' : ''}`);
    if (interactive) {
      // Reuse the existing record button's layout, hover and focus treatment.
      item.className += ' specialist-library-row';
      item.type = 'button';
      item.dataset.planAgendaRecord = row.id;
      item.setAttribute('aria-label', row.overdue
        ? t('groups.open_overdue', { type: _typeLabel(row.type), title: row.title, due: row.due })
        : t('groups.open_record', { type: _typeLabel(row.type), title: row.title, when: `${row.date ? ` · ${row.date}` : ''}${row.time ? ` ${formatClock(row.time)}` : ''}` }));
      item.addEventListener('click', () => openRecord(row, item));
    }
    const typeName = _typeLabel(row.type);
    const meta = row.meta && row.meta !== typeName ? `${typeName} · ${row.meta}` : typeName;
    item.append(
      // row.time stays "09:00" for sorting; it reads like every other time in the app
      _el('span', 'specialist-record-time', row.overdue ? t('groups.overdue')
        : (row.time && formatClock(row.time)) || (byDay ? (row.type === 'task' ? t('groups.due') : t('groups.all_day')) : row.date) || '--'),
      _el('strong', 'specialist-record-title', row.title),
      _el('span', 'specialist-record-meta', meta),
    );
    target.append(item);
  }
}

async function _renderPlan(target, request, section = 'overview') {
  const renderNonce = _states.get('plan')?.renderNonce;
  disposePlanBoard();
  if (section === 'board') {
    return renderPlanBoard(target, request, () => _refresh('plan'));
  }
  const [eventsResult, tasksResult, remindersResult] = await Promise.allSettled([
    _json(request, '/api/calendar/agenda?days=8', { headers: chosenTimeZone() ? { 'x-alles-time-zone': chosenTimeZone() } : {} }),
    _json(request, '/api/tasks'),
    _json(request, '/api/reminders'),
  ]);
  const agendaPayload = _settled(eventsResult, {});
  // a later day of a multi-day event sits on that day, as an all-day row
  const events = _asArray(agendaPayload, 'days').flatMap(day => _asArray(day, 'events')
    .map(event => (event?.continued && day?.date ? { ...event, start_dt: day.date } : event)));
  const tasks = _asArray(_settled(tasksResult, []));
  const reminders = _asArray(_settled(remindersResult, []));
  const failures = [
    [t('groups.src_calendar'), _settledError(eventsResult, t('groups.err_calendar'))],
    [t('groups.src_tasks'), _settledError(tasksResult, t('groups.err_tasks'))],
    [t('groups.src_reminders'), _settledError(remindersResult, t('groups.err_reminders'))],
  ];
  const unavailableSources = failures.filter(([, error]) => error).map(([source]) => source);
  const commitmentsEmpty = unavailableSources.length
    ? t('groups.no_commitments_unavailable', { sources: unavailableSources.join(', ') })
    : t('groups.nothing_committed');
  const unscheduledEmpty = failures[1][1]
    ? t('groups.tasks_unavailable_unscheduled')
    : t('groups.no_unscheduled');
  const commitments = planCommitments(events, tasks, reminders);
  target.replaceChildren();

  const capture = _el('form', 'specialist-group-capture');
  capture.setAttribute('aria-label', t('groups.quick_task'));
  const input = _el('input');
  input.type = 'text';
  input.name = 'title';
  input.maxLength = 500;
  input.placeholder = t('groups.capture_task');
  input.setAttribute('aria-label', t('groups.capture_task'));
  input.autocomplete = 'off';
  const button = _el('button', '', t('groups.add_task'));
  button.type = 'submit';
  const captureMessage = _el('p', 'specialist-group-capture-status');
  captureMessage.setAttribute('role', 'status');
  captureMessage.setAttribute('aria-live', 'polite');
  captureMessage.hidden = true;
  capture.append(input, button, captureMessage);
  capture.addEventListener('submit', async event => {
    event.preventDefault();
    const title = input.value.trim();
    if (!title) return;
    button.disabled = true;
    captureMessage.hidden = true;
    captureMessage.textContent = '';
    try {
      try {
        await _json(request, '/api/tasks', {
          method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ title }),
        });
      } catch (error) {
        captureMessage.textContent = error?.message || t('groups.task_not_added');
        captureMessage.hidden = false;
        input.focus();
        return;
      }
      input.value = '';
      try {
        await _refresh('plan');
      } catch (error) {
        captureMessage.textContent = t('groups.task_saved_no_refresh', { error: error?.message || t('groups.refresh_failed') });
        captureMessage.hidden = false;
      }
    } finally { button.disabled = false; }
  });

  const workbench = _el('div', 'specialist-workbench specialist-workbench-plan');
  const rail = _el('aside', 'specialist-workbench-rail');

  const today = _todayKey();
  const sevenDayEndKey = addDateKeyDays(today, 7);
  // open tasks due before today lead today and the next seven days, marked overdue the way home
  // marks them; the meta keeps the day they were due
  const overdue = commitments
    .filter(item => item.type === 'task' && item.date && item.date < today)
    .map(item => ({ ...item, due: item.date, date: today, time: '', overdue: true, meta: t('groups.due_day', { day: _agendaDayLabel(item.date) }) }));
  const inWindow = value => [...overdue, ...commitments.filter(item => (value === 'today'
    ? item.date === today : item.date >= today && item.date < sevenDayEndKey))];
  const returnTo = _planAgendaReturn?.section === section && _planAgendaReturn.url === location.href
    ? _planAgendaReturn : null;
  let windowName = returnTo?.windowName || (section === 'week' ? 'seven' : 'today');
  const agenda = _el('section', 'specialist-workbench-main');
  const agendaHead = _el('div', 'specialist-workbench-head');
  agendaHead.append(_el('h2', '', t('groups.agenda')), _el('span', '', today));
  const agendaList = _el('div', 'specialist-record-list');
  const openStatus = _el('p', 'specialist-group-note plan-agenda-status');
  openStatus.setAttribute('role', 'status');
  openStatus.hidden = true;
  const openRecord = async (row, control) => {
    const url = location.href;
    const isCurrent = () => _states.get('plan')?.renderNonce === renderNonce
      && location.href === url && control.isConnected && control.getClientRects().length > 0;
    if (control.disabled || !isCurrent()) return;
    const report = message => {
      openStatus.textContent = message;
      openStatus.hidden = false;
      control.focus();
    };
    if (!row.target) {
      report(t('groups.item_unavailable'));
      return;
    }
    openStatus.hidden = true;
    const origin = { section, windowName, id: row.id, url };
    _planAgendaReturn = origin;
    _setAsyncControlBusy(control, true);
    let navigated = false;
    try {
      // The router owns loading the current editor, navigation guards and stale replies.
      navigated = await window._openRecord?.(row.target.view, row.target.id, row.target.occurrence);
    } catch { /* Keep the originating row available for another attempt. */ }
    finally { _setAsyncControlBusy(control, false); }
    if (!navigated && _planAgendaReturn === origin && isCurrent()) {
      _planAgendaReturn = null;
      report(t('groups.item_open_failed'));
    }
  };
  const renderWindow = value => {
    windowName = value;
    openStatus.hidden = true;
    let rows = commitments;
    let empty = commitmentsEmpty;
    if (value === 'today' || value === 'seven') rows = inWindow(value);
    if (value === 'unscheduled') {
      rows = commitments.filter(item => item.type === 'task' && !item.date);
      empty = unscheduledEmpty;
    }
    agendaHead.querySelector('span').textContent = value === 'today' ? today : value === 'seven' ? t('groups.next_seven_days') : t('groups.no_date');
    _agendaRows(agendaList, rows, empty, openRecord);
  };
  const choices = _choiceButtons(t('groups.plan_window'), [
    { value: 'today', label: t('groups.window_today', { count: inWindow('today').length }) },
    { value: 'seven', label: t('groups.window_seven', { count: inWindow('seven').length }) },
    { value: 'unscheduled', label: t('groups.window_unscheduled', { count: commitments.filter(item => item.type === 'task' && !item.date).length }) },
  ], windowName, renderWindow);
  rail.append(choices);
  agenda.append(agendaHead, openStatus, agendaList);
  const aside = _el('aside', 'specialist-workbench-detail');
  aside.append(capture);
  workbench.append(aside, rail, agenda);
  const partial = _partialAvailability(failures);
  if (partial) target.append(partial);
  target.append(workbench);
  renderWindow(windowName);
}

function _restorePlanAgendaFocus(overview, section) {
  const origin = _planAgendaReturn;
  if (!origin || origin.section !== section || origin.url !== location.href || !overview.getClientRects().length) return;
  _planAgendaReturn = null;
  const record = [...overview.querySelectorAll('[data-plan-agenda-record]')]
    .find(item => item.dataset.planAgendaRecord === origin.id);
  const destination = record || overview.querySelector('.specialist-choice-group')?.querySelector('[aria-pressed="true"]');
  if (!record) {
    const status = overview.querySelector('.plan-agenda-status');
    status.textContent = t('groups.item_gone');
    status.hidden = false;
  }
  destination?.scrollIntoView({ block: 'nearest', behavior: 'instant' });
  destination?.focus({ preventScroll: true });
}

async function _renderInbox(target, request) {
  const [accountsResult, contactsResult] = await Promise.allSettled([
    _json(request, '/api/mail/accounts'),
    _json(request, '/api/contacts'),
  ]);
  const accounts = _asArray(_settled(accountsResult, []));
  const contacts = _asArray(_settled(contactsResult, []));
  const accountsError = _settledError(accountsResult, t('groups.err_mail_accounts'));
  const contactsError = _settledError(contactsResult, t('groups.err_contacts'));
  const cached = await Promise.allSettled(accounts.map(account =>
    _json(request, `/api/mail/cached/${encodeURIComponent(account.id)}?folder=INBOX&limit=24`)));
  const cachedFailures = cached.flatMap((result, index) => result.status === 'rejected'
    ? [[t('groups.src_cached_mail', { name: accounts[index]?.name || accounts[index]?.email || t('groups.account') }), result.reason?.message || t('groups.err_messages')]]
    : []);
  const failures = [
    [t('groups.src_mail_accounts'), accountsError],
    [t('groups.src_contacts'), contactsError],
    ...cachedFailures,
  ];
  const messages = cached.flatMap((result, index) => _asArray(_settled(result, {}), 'messages').map(message => ({
    ...message,
    account_id: String(accounts[index]?.id ?? ''),
    account_name: accounts[index]?.name || accounts[index]?.email || '',
  })));
  target.replaceChildren();
  const workbench = _el('div', 'specialist-workbench specialist-workbench-inbox');
  const rail = _el('aside', 'specialist-workbench-rail');
  rail.append(_el('h2', '', t('groups.mailboxes')));
  const main = _el('section', 'specialist-workbench-main');
  const head = _el('div', 'specialist-workbench-head');
  head.append(_el('h2', '', t('groups.cached_messages')), _sectionJump('inbox', 'mail', t('groups.open_mail'), 'specialist-inline-action'));
  const messageList = _el('div', 'specialist-message-list');
  const detail = _el('aside', 'specialist-workbench-detail');
  let selectedAccount = '';
  let selectedMessage = null;
  const emptyMailboxCopy = accountsError
    ? t('groups.mail_accounts_unavailable')
    : cachedFailures.length
      ? t('groups.cached_unavailable')
      : accounts.length ? t('groups.inbox_clear') : t('groups.connect_account');
  const sender = message => message.from_name || message.from || message.sender || message.from_email || '';
  const drawDetail = message => {
    detail.replaceChildren();
    detail.append(_el('h2', '', t('groups.selected_message')));
    if (!message) {
      detail.append(_el('p', 'specialist-workbench-empty', emptyMailboxCopy));
      return;
    }
    detail.append(
      _el('strong', 'specialist-detail-title', message.subject || t('groups.no_subject')),
      _el('p', 'specialist-detail-meta', `${sender(message) || t('groups.unknown_sender')} · ${_dateLabel(message.date || message.received_at || message.internal_date)}`),
      _el('p', 'specialist-detail-body', message.snippet || message.preview || message.body_text || t('groups.open_mail_to_read')),
    );
    const contact = contacts.find(item => {
      const address = mailboxAddress(message.from_email || message.from || '');
      return address && mailboxAddress(item.email) === address;
    });
    detail.append(_el('h2', '', t('groups.person_context')));
    if (contact) {
      detail.append(
        _el('strong', 'specialist-detail-title', contact.name || contact.email),
        _el('p', 'specialist-detail-meta', contact.email || contact.phone || ''),
        _sectionJump('inbox', 'contacts', t('groups.open_contact'), 'specialist-inline-action'),
      );
    } else {
      detail.append(_el('p', 'specialist-workbench-empty', contactsError ? t('groups.contacts_unavailable') : t('groups.no_matching_contact')));
    }
  };
  const drawMessages = () => {
    messageList.replaceChildren();
    const visible = messages.filter(message => !selectedAccount || message.account_id === selectedAccount);
    if (!visible.length) {
      selectedMessage = null;
      messageList.append(_el('p', 'specialist-workbench-empty', emptyMailboxCopy));
      drawDetail(null);
      return;
    }
    if (!visible.includes(selectedMessage)) selectedMessage = visible[0];
    for (const message of visible) {
      const button = _el('button', 'specialist-message-row');
      button.type = 'button';
      button.setAttribute('aria-current', message === selectedMessage ? 'true' : 'false');
      button.append(
        _el('span', 'specialist-record-time', _dateLabel(message.date || message.received_at || message.internal_date)),
        _el('strong', 'specialist-record-title', message.subject || t('groups.no_subject')),
        _el('span', 'specialist-record-meta', sender(message) || message.account_name || t('groups.unknown_sender')),
      );
      button.addEventListener('click', () => {
        selectedMessage = message;
        messageList.querySelectorAll('button').forEach(item => item.setAttribute('aria-current', item === button ? 'true' : 'false'));
        drawDetail(message);
      });
      messageList.append(button);
    }
    drawDetail(selectedMessage);
  };
  const mailboxChoices = [{ value: '', label: t('groups.all_accounts', { count: messages.length }) }, ...accounts.map(account => ({
    value: String(account.id ?? ''),
    label: `${account.name || account.email || t('groups.account')} · ${messages.filter(item => item.account_id === String(account.id ?? '')).length}`,
  }))];
  rail.append(_choiceButtons(t('groups.inbox_account'), mailboxChoices, selectedAccount, value => {
    selectedAccount = value;
    drawMessages();
  }), _el('h2', '', t('groups.people')));
  const people = _el('div', 'specialist-workbench-jumps');
  people.append(_sectionJump('inbox', 'contacts', t('groups.all_contacts', { count: contacts.length })));
  rail.append(people);
  main.append(head, messageList);
  workbench.append(rail, main, detail);
  const partial = _partialAvailability(failures);
  if (partial) target.append(partial);
  target.append(workbench);
  drawMessages();
}

const _readState = state => ({
  reading: t('groups.state_reading'), want: t('groups.state_want'), done: t('groups.state_done'),
  read: t('groups.state_read'), unread: t('groups.state_unread'),
}[state] || state);

async function _renderLibrary(target, request) {
  const [readResult, booksResult] = await Promise.allSettled([
    _json(request, '/api/read'),
    _json(request, '/api/books/overview'),
  ]);
  const read = _asArray(_settled(readResult, {}), 'items');
  const booksData = _settled(booksResult, {});
  const readError = _settledError(readResult, t('groups.err_saved_reading'));
  const booksError = _settledError(booksResult, t('groups.err_books'));
  const shelves = booksData?.shelves || {};
  const books = [
    ..._asArray(shelves.reading).map(item => ({ ...item, reading_state: 'reading' })),
    ..._asArray(shelves.want).map(item => ({ ...item, reading_state: 'want' })),
    ..._asArray(shelves.done).map(item => ({ ...item, reading_state: 'done' })),
  ];
  const records = [
    ...read.map(item => ({
      id: `saved:${item.id || item.url || item.title}`,
      targetId: item.id,
      kind: item.source_kind === 'saved_news' ? t('groups.saved_news') : t('groups.src_saved_reading'),
      title: item.title || item.url || t('groups.untitled_saved'),
      meta: item.site || item.url || item.status || t('groups.saved'),
      section: 'read',
      state: item.status || (item.read ? 'read' : 'unread'),
    })),
    ...books.map(item => ({
      id: `book:${item.id || item.title}`,
      targetId: item.id,
      kind: t('groups.book'),
      title: item.title || t('groups.untitled_book'),
      meta: item.author || item.reading_state || t('groups.book'),
      section: 'books',
      state: item.reading_state,
    })),
  ];
  target.replaceChildren();
  const workbench = _el('div', 'specialist-workbench specialist-workbench-library');
  const main = _el('section', 'specialist-workbench-main');
  const head = _el('div', 'specialist-workbench-head');
  head.append(_el('h2', '', t('groups.reading_queue')), _el('span', '', tp('groups.items', records.length)));
  const list = _el('div', 'specialist-message-list');
  let filter = 'all';
  const draw = () => {
    list.replaceChildren();
    const visible = records.filter(item => filter === 'all' || (filter === 'saved' ? item.section === 'read' : item.section === 'books'));
    head.querySelector('span').textContent = tp('groups.items', visible.length);
    if (!visible.length) {
      const unavailable = filter === 'saved' ? (readError ? t('groups.src_saved_reading') : '')
        : filter === 'books' ? (booksError ? t('groups.src_books') : '')
          : readError && booksError ? t('groups.saved_reading_and_books')
            : readError ? t('groups.src_saved_reading') : booksError ? t('groups.src_books') : '';
      list.append(_el(
        'p',
        'specialist-workbench-empty',
        unavailable ? t('groups.unavailable_no_items', { what: unavailable }) : t('groups.library_empty'),
      ));
      if (!unavailable) {
        const section = filter === 'saved' ? 'read' : 'books';
        const add = _el('button', 'btn', section === 'read' ? t('groups.save_reading') : t('groups.add_book'));
        add.type = 'button';
        add.addEventListener('click', async () => {
          const navigated = await window._navigateSpecialistSection?.('library', section);
          if (!navigated || document.getElementById('library-view')?.dataset.section !== section) return;
          if (section === 'read') {
            (document.getElementById('read-save-check') || document.getElementById('read-url'))?.focus();
          } else {
            const title = document.getElementById('book-title');
            if (title) title.focus();
            else document.getElementById('books-add-toggle')?.click();
          }
        });
        list.append(add);
      }
      return;
    }
    for (const record of visible) {
      const button = _el('button', 'specialist-library-row');
      button.type = 'button';
      button.setAttribute('aria-label', t('groups.open_kind', { kind: record.kind, title: record.title }));
      button.addEventListener('click', async () => {
        if (!record.targetId) return;
        const navigated = await window._navigateSpecialistSection?.('library', record.section);
        if (!navigated || document.getElementById('library-view')?.dataset.section !== record.section) return;
        if (record.section === 'read') {
          const { openReadItem } = await import('./read.js');
          await openReadItem(record.targetId);
        } else {
          const { focusBook } = await import('./books.js');
          focusBook(record.targetId);
        }
      });
      button.append(
        _el('span', 'specialist-record-time', record.kind),
        _el('strong', 'specialist-record-title', record.title),
        _el('span', 'specialist-record-meta', `${_readState(record.state) || t('groups.saved')} · ${record.meta}`),
      );
      list.append(button);
    }
  };
  const filters = _choiceButtons(t('groups.library_material'), [
    { value: 'all', label: t('groups.filter_everything', { count: records.length }) },
    { value: 'saved', label: t('groups.filter_saved', { count: read.length }) },
    { value: 'books', label: t('groups.filter_books', { count: books.length }) },
  ], filter, value => { filter = value; draw(); });
  filters.setAttribute('role', 'group');
  main.append(head, filters, list);
  workbench.append(main);
  const partial = _partialAvailability([
    [t('groups.src_saved_reading'), readError],
    [t('groups.src_books'), booksError],
  ]);
  if (partial) target.append(partial);
  target.append(workbench);
  draw();
}

async function _renderHealth(target, request) {
  const day = _todayKey();
  const [healthResult, habitsResult] = await Promise.allSettled([
    _json(request, '/api/health/overview?date_q=' + day),
    _json(request, '/api/habits/overview?date_q=' + day),
  ]);
  const health = _asArray(_settled(healthResult, {}), 'kinds');
  const habits = _asArray(_settled(habitsResult, {}), 'habits');
  const healthError = _settledError(healthResult, t('groups.err_measurements'));
  const habitsError = _settledError(habitsResult, t('groups.err_habits'));
  target.replaceChildren();
  const workbench = _el('div', 'specialist-workbench specialist-workbench-health');
  const rail = _el('aside', 'specialist-workbench-rail');
  rail.append(_el('h2', '', t('common.today')));
  const rhythm = _el('div', 'specialist-health-rhythm');
  if (!habits.length) rhythm.append(_el('p', 'specialist-workbench-empty', habitsError ? t('groups.habits_unavailable') : t('groups.no_habits')));
  if (!habits.length && !habitsError) rhythm.append(_sectionJump('health', 'habits', t('groups.add_habit'), 'specialist-inline-action'));
  for (const habit of habits) {
    const button = _sectionJump('health', 'habits', '', 'specialist-habit-row');
    button.setAttribute('aria-label', t('groups.open_habit', { name: habit.name || t('groups.untitled') }));
    button.append(
      _el('strong', '', habit.name || t('groups.untitled_habit')),
      _el('span', '', habit.done_today ? t('groups.done_today') : tp('groups.day_streak', habit.streak || 0)),
    );
    rhythm.append(button);
  }
  rail.append(rhythm);
  const main = _el('section', 'specialist-workbench-main');
  const head = _el('div', 'specialist-workbench-head');
  head.append(_el('h2', '', t('groups.latest_measurements')));
  const measurements = _el('div', 'specialist-record-list');
  if (!health.length) measurements.append(_el('p', 'specialist-workbench-empty', healthError ? t('groups.measurements_unavailable') : t('groups.no_measurements')));
  if (!health.length && !healthError) measurements.append(_sectionJump('health', 'health', t('groups.log_measurement'), 'specialist-inline-action'));
  for (const item of health) {
    const row = _el('div', 'specialist-record-row');
    row.append(
      _el('span', 'specialist-record-time', item.latest?.date || '--'),
      _el('strong', 'specialist-record-title', item.label || item.kind || t('groups.measurement')),
      _el('span', 'specialist-record-meta', item.latest ? `${item.latest.value} ${item.latest.unit || ''}` : t('groups.no_entries')),
    );
    measurements.append(row);
  }
  main.append(head, measurements);
  const detail = _el('aside', 'specialist-workbench-detail');
  const completed = habits.filter(item => item.done_today).length;
  // the rail already says when there are no habits; this column only adds the day's tally
  if (habits.length) detail.append(_el('h2', '', t('groups.done_today')), _el('strong', 'specialist-detail-title', t('groups.x_of_y', { done: completed, total: habits.length })));
  if (health.length) detail.append(_sectionJump('health', 'health', t('groups.open_health_history'), 'specialist-inline-action'));
  workbench.append(rail, main, detail);
  const partial = _partialAvailability([
    [t('groups.src_measurements'), healthError],
    [t('groups.src_habits'), habitsError],
  ]);
  if (partial) target.append(partial);
  target.append(workbench);
}

export function financeActualPresentation(value) {
  const service = value?.service;
  const ledger = value?.ledger;
  if (!service || !ledger) {
    return {
      state: 'unavailable',
      title: t('finance.ledger_status_unavailable'),
      detail: t('finance.ledger_status_unavailable_detail'),
      actions: [],
    };
  }
  if (ledger.mode === 'actual') {
    let recovery = [];
    if (service.available && !service.installed) recovery = ['install'];
    else if (service.available && !service.running) recovery = ['start'];
    else if (service.available && !service.healthy) recovery = ['restart'];
    else if (service.available) recovery = ['backup'];
    const healthy = service.available && service.installed && service.running && service.healthy;
    return {
      state: healthy ? 'canonical' : 'canonical-unhealthy',
      title: healthy ? t('finance.actual_active') : t('finance.actual_needs_attention'),
      detail: healthy
        ? t('finance.actual_active_detail')
        : t('finance.actual_unhealthy_detail'),
      actions: [...recovery, 'rollback-ledger'],
    };
  }
  if (!service.available) {
    return {
      state: 'unavailable',
      title: t('finance.actual_unavailable'),
      detail: t('finance.node_required', { version: service.node_version || t('finance.no_node') }),
      actions: [],
    };
  }
  if (!service.installed) {
    return {
      state: 'not-installed',
      title: t('finance.alles_active'),
      detail: t('finance.actual_not_installed_detail'),
      actions: ['install'],
    };
  }
  if (!service.healthy) {
    return {
      state: service.running ? 'unhealthy' : 'stopped',
      title: service.running ? t('finance.actual_needs_attention_short') : t('finance.actual_stopped'),
      detail: t('finance.actual_stopped_detail'),
      actions: [service.running ? 'restart' : 'start'],
    };
  }
  const runStatus = ledger.run?.status || '';
  if (runStatus === 'ready') {
    return {
      state: 'ready',
      title: t('finance.ledgers_match'),
      detail: t('finance.ledgers_match_detail'),
      actions: ['cutover', 'backup', 'stop'],
    };
  }
  if (runStatus === 'staging') {
    return {
      state: 'staging',
      title: t('finance.preparing_copy'),
      detail: t('finance.preparing_copy_detail'),
      actions: ['backup'],
    };
  }
  return {
    state: runStatus === 'failed' ? 'failed' : 'available',
    title: runStatus === 'failed' ? t('finance.copy_retry') : t('finance.ready_to_copy'),
    detail: runStatus === 'failed'
      ? (ledger.run?.error || t('finance.copy_failed_detail'))
      : t('finance.ready_to_copy_detail'),
    actions: [
      ...(/^[A-Z]{3}$/.test(String(ledger.base_currency_code || '').trim()) ? ['stage'] : []),
      'backup',
      'stop',
    ],
  };
}

const actualActionLabels = () => ({
  install: t('finance.act_install'),
  start: t('finance.act_start'),
  restart: t('finance.act_restart'),
  stop: t('finance.act_stop'),
  backup: t('finance.act_backup'),
  stage: t('finance.act_stage'),
  cutover: t('finance.act_cutover'),
  'rollback-ledger': t('finance.act_rollback'),
});

function _actualConfirmation(panel, action, trigger, runAction) {
  panel.querySelector('.finance-actual-confirm')?.remove();
  const confirmation = _el('section', 'finance-actual-confirm');
  confirmation.setAttribute('role', 'region');
  confirmation.setAttribute('aria-label', action === 'cutover' ? t('finance.confirm_switch') : t('finance.confirm_return'));
  confirmation.tabIndex = -1;
  const heading = _el('h3', '', action === 'cutover' ? t('finance.switch_heading') : t('finance.return_heading'));
  const body = _el('p', '', action === 'cutover'
    ? t('finance.switch_body')
    : t('finance.return_body'));
  const actions = _el('div', 'finance-actual-confirm-actions');
  const cancel = _el('button', '', t('finance.keep_ledger'));
  cancel.type = 'button';
  const confirm = _el('button', 'finance-actual-confirm-primary', action === 'cutover' ? t('finance.use_actual') : t('finance.use_alles'));
  confirm.type = 'button';
  const toggle = panel.querySelector('.finance-actual-toggle');
  if (toggle) toggle.disabled = true;
  const close = () => {
    confirmation.remove();
    if (toggle) toggle.disabled = false;
    trigger.focus();
  };
  cancel.addEventListener('click', close);
  confirm.addEventListener('click', () => {
    confirmation.remove();
    if (toggle) toggle.disabled = false;
    trigger.focus();
    runAction(action, trigger);
  });
  confirmation.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    close();
  });
  actions.append(cancel, confirm);
  confirmation.append(heading, body, actions);
  panel.append(confirmation);
  cancel.focus();
}

function _renderActualStatus(value, request) {
  const presentation = financeActualPresentation(value);
  const reported = !!value && typeof value === 'object';
  const service = value?.service || {};
  const ledger = value?.ledger || {};
  const panel = _el('section', `finance-actual-panel finance-actual-${presentation.state}`);
  panel.setAttribute('aria-label', t('finance.ledger_status_label'));
  const compact = ['canonical', 'ready', 'available', 'not-installed'].includes(presentation.state);
  const heading = _el('header', 'finance-actual-head');
  const status = compact
    ? (presentation.state === 'ready' ? t('finance.ready_for_review') : t('finance.ledger_active', { ledger: ledger.mode === 'actual' ? 'Actual' : 'Alles' }))
    : presentation.title;
  heading.append(_el('h2', '', t('finance.actual_ledger')), _el('strong', '', status));
  const content = _el('div', 'finance-actual-content');
  content.id = 'finance-actual-content';
  let toggle = null;
  if (compact) {
    toggle = _el('button', 'finance-actual-toggle', t('finance.show_setup'));
    toggle.type = 'button';
    toggle.setAttribute('aria-controls', content.id);
    toggle.setAttribute('aria-expanded', 'false');
    content.hidden = true;
    toggle.addEventListener('click', () => {
      content.hidden = !content.hidden;
      toggle.setAttribute('aria-expanded', String(!content.hidden));
      toggle.textContent = content.hidden ? t('finance.show_setup') : t('finance.hide_setup');
    });
  }
  const detail = _el('p', 'finance-actual-detail', presentation.detail);
  const facts = _el('dl', 'finance-actual-facts');
  const fact = (term, description) => {
    facts.append(_el('dt', '', term), _el('dd', '', description));
  };
  fact(t('finance.fact_saved_in'), reported ? (ledger.mode === 'actual' ? 'Actual' : 'Alles') : t('finance.not_reported'));
  fact(t('finance.fact_base_currency'), ledger.base_currency_code || t('finance.not_reported'));
  fact(t('finance.fact_service'), reported ? (service.installed ? t('finance.service_state', { version: service.version || '26.7.0', state: service.healthy ? t('finance.healthy') : service.running ? t('finance.unhealthy') : t('finance.stopped') }) : t('finance.not_installed')) : t('finance.status_unavailable'));
  if (ledger.run) fact(t('finance.fact_latest_check'), t('finance.latest_check', { status: ledger.run.status || t('common.unknown'), links: ledger.run.links ?? 0 }));
  const message = _el('p', 'finance-actual-message');
  message.setAttribute('role', 'status');
  message.setAttribute('aria-live', 'polite');
  const actions = _el('div', 'finance-actual-actions');

  const setBusy = busy => {
    panel.setAttribute('aria-busy', busy ? 'true' : 'false');
    if (toggle) toggle.disabled = busy;
    actions.querySelectorAll('button').forEach(button => _setAsyncControlBusy(button, busy));
  };
  const runAction = async (action, returnFocus = null) => {
    setBusy(true);
    panel.querySelector('.finance-actual-confirm')?.remove();
    message.classList.remove('finance-actual-error');
    message.textContent = t('finance.in_progress', { action: actualActionLabels()[action] });
    let url = `/api/finance/actual/service/${action}`;
    const options = { method: 'POST' };
    if (action === 'stage') {
      const baseCurrency = String(ledger.base_currency_code || '').trim();
      if (!/^[A-Z]{3}$/.test(baseCurrency)) {
        message.textContent = t('finance.confirm_base');
        message.classList.add('finance-actual-error');
        setBusy(false);
        if (returnFocus?.isConnected) returnFocus.focus();
        return;
      }
      url = '/api/finance/actual/stage';
      options.headers = { 'content-type': 'application/json' };
      options.body = JSON.stringify({ base_currency_code: baseCurrency });
    } else if (action === 'cutover') {
      url = `/api/finance/actual/cutover/${encodeURIComponent(ledger.run?.id || '')}`;
    } else if (action === 'rollback-ledger') {
      url = '/api/finance/actual/rollback-ledger';
    }
    try {
      const result = await _json(request, url, options);
      if (action === 'backup') {
        message.textContent = t('finance.backup_verified', { id: result.backup_id || '' });
        setBusy(false);
      } else {
        await _refresh('finance');
      }
    } catch (error) {
      message.textContent = error?.message || t('finance.action_failed');
      message.classList.add('finance-actual-error');
      setBusy(false);
      if (returnFocus?.isConnected) returnFocus.focus();
    }
  };

  for (const action of presentation.actions) {
    const button = _el('button', action === 'cutover' ? 'finance-actual-primary' : '', actualActionLabels()[action]);
    button.type = 'button';
    button.dataset.actualAction = action;
    button.addEventListener('click', async () => {
      if (action === 'cutover' || action === 'rollback-ledger') {
        _actualConfirmation(panel, action, button, runAction);
      } else if (action === 'stop') {
        if (!await confirmDialog(t('finance.stop_confirm'))) return;
        runAction(action, button);
      } else {
        runAction(action, button);
      }
    });
    actions.append(button);
  }
  panel.append(heading);
  if (compact) {
    panel.append(_el('p', 'finance-actual-authority', `${t('finance.writes_to', { ledger: ledger.mode === 'actual' ? 'Actual' : 'Alles' })}${ledger.base_currency_code ? ` · ${ledger.base_currency_code}` : ''}`), toggle);
  }
  if (compact) content.append(_el('p', 'finance-actual-detail', presentation.title));
  content.append(detail, facts, actions, message);
  panel.append(content);
  return panel;
}

// a true minus before the code (−USD 12.00), as Money writes it. with no currency the label
// isn't part of the amount, so there the minus stays on the number
function financeAmount(value, currency = '') {
  const cents = Math.round(Number(value ?? 0) * 100);
  const number = formatNumber(Math.abs(cents) / 100, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const sign = cents < 0 ? '−' : '';
  const code = `${currency === 'XXX' ? t('finance.currency_not_set') : currency}${/^[A-Z]{3}$/.test(currency) ? '\u00a0' : ''}`;
  return currency === 'XXX' ? `${code}${sign}${number}` : `${sign}${code}${number}`;
}

// a statement amount as the file wrote it (-12.34), in the same sign style
function _importAmount(code, text) {
  const negative = /^-/.test(text);
  return `${negative ? '−' : ''}${code ? `${code}\u00a0` : ''}${negative ? text.slice(1) : text}`;
}

async function _renderFinance(target, request) {
  const [accountsResult, subscriptionsResult, actualResult] = await Promise.allSettled([
    _json(request, '/api/money/accounts'),
    _json(request, '/api/subscriptions?advance=false'),
    _json(request, '/api/finance/actual'),
  ]);
  const accounts = _asArray(_settled(accountsResult, []));
  const subscriptionData = _settled(subscriptionsResult, {});
  const subscriptions = _asArray(subscriptionData, 'subscriptions');
  const actual = _settled(actualResult, null);
  const accountsError = _settledError(accountsResult, t('finance.err_accounts'));
  const subscriptionsError = _settledError(subscriptionsResult, t('finance.err_subscriptions'));
  const actualError = _settledError(actualResult, t('finance.err_actual'));
  target.replaceChildren();
  const grid = _el('div', 'specialist-group-grid specialist-group-grid-two finance-daily');
  grid.append(
    _list(t('finance.accounts'), accounts.map(item => ({ title: item.name, meta: item.balance_by_currency?.length ? item.balance_by_currency.map(row => financeAmount(row.balance, row.currency)).join(' · ') : financeAmount(item.balance, item.currency || item.currency_code || '') })), accountsError ? t('finance.accounts_unavailable', { error: accountsError }) : t('finance.no_accounts')),
    _list(t('finance.subscriptions'), subscriptions.map(item => ({ title: item.name, meta: `${financeAmount(item.price, item.currency || '')} · ${item.cycle ? t('subs.cycle_' + item.cycle) : ''}` })), subscriptionsError ? t('finance.subscriptions_unavailable', { error: subscriptionsError }) : t('finance.no_subscriptions')),
  );
  const work = _el('div', 'finance-daily-actions');
  work.append(_sectionJump('finance', 'money', t('finance.open_transactions'), 'specialist-inline-action'));
  const ledgerPanel = _renderActualStatus(actual, request);
  const urgent = financeActualPresentation(actual).state === 'canonical-unhealthy' || !!actualError;
  if (urgent) target.append(ledgerPanel);
  if (actualError) target.append(_el('p', 'specialist-group-error', t('finance.actual_status_unavailable', { error: actualError })));
  target.append(work, grid);
  if (!urgent) target.append(ledgerPanel);
}

async function _renderServer(target, request, section) {
  const module = await import('./server_workbench.js?v=10');
  return module.renderServerSection(target, request, section);
}

function _choiceField(label, options, selected, onSelect) {
  const field = _el('fieldset', 'finance-import-choice');
  field.append(_el('legend', '', label));
  const value = _el('span', 'finance-import-selected', options.find(option => option.value === selected)?.label || '');
  const change = _el('button', '', t('finance.change_choice', { label }));
  change.type = 'button';
  change.setAttribute('aria-expanded', 'false');
  const picker = _el('div', 'finance-import-picker');
  picker.hidden = true;
  const search = _el('input', 'settings-input');
  search.type = 'search';
  search.setAttribute('aria-label', t('finance.search_choices', { label }));
  const empty = _el('p', 'specialist-group-note', t('finance.no_matching_choices'));
  empty.setAttribute('role', 'status');
  empty.hidden = true;
  const list = _el('div', 'finance-import-choice-list');
  list.setAttribute('role', 'listbox');
  list.setAttribute('aria-label', label);
  const close = () => {
    picker.hidden = true;
    change.setAttribute('aria-expanded', 'false');
    change.focus();
  };
  const buttons = options.map(option => {
    const button = _el('button', '', option.label);
    button.type = 'button';
    button.setAttribute('role', 'option');
    button.dataset.value = option.value;
    button.setAttribute('aria-selected', String(option.value === selected));
    button.tabIndex = option.value === selected ? 0 : -1;
    button.addEventListener('click', () => {
      selected = option.value;
      value.textContent = option.label;
      buttons.forEach(item => {
        const chosen = item === button;
        item.setAttribute('aria-selected', String(chosen));
        item.tabIndex = chosen ? 0 : -1;
      });
      onSelect(option.value);
      close();
    });
    button.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const visible = buttons.filter(item => !item.hidden);
      const current = visible.indexOf(button);
      const backwards = ['ArrowLeft', 'ArrowUp'].includes(event.key);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? visible.length - 1
        : (current + (backwards ? -1 : 1) + visible.length) % visible.length;
      visible.forEach((item, index) => { item.tabIndex = index === next ? 0 : -1; });
      visible[next]?.focus();
    });
    list.append(button);
    return button;
  });
  const filter = () => {
    const query = search.value.trim().toLowerCase();
    buttons.forEach(button => { button.hidden = !button.textContent.toLowerCase().includes(query); });
    const visible = buttons.filter(button => !button.hidden);
    const active = visible.find(button => button.dataset.value === selected) || visible[0];
    buttons.forEach(button => { button.tabIndex = button === active ? 0 : -1; });
    empty.hidden = visible.length > 0;
  };
  search.addEventListener('input', filter);
  search.addEventListener('keydown', event => {
    if (event.key !== 'ArrowDown') return;
    event.preventDefault();
    buttons.find(button => !button.hidden && button.tabIndex === 0)?.focus();
  });
  picker.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    event.stopPropagation();
    close();
  });
  change.addEventListener('click', () => {
    if (!picker.hidden) return close();
    search.value = '';
    filter();
    picker.hidden = false;
    change.setAttribute('aria-expanded', 'true');
    search.focus();
  });
  picker.append(search, list, empty);
  field.append(value, change, picker);
  return field;
}

function _importRepairHint(row) {
  if (row.status !== 'needs_review') return '';
  const reason = row.conflict_reason || '';
  if (reason === 'date is missing or ambiguous') {
    return t('finance.hint_date');
  }
  if (/^amount (is missing|is not a decimal number|has more than two decimal places)$/.test(reason)) {
    return t('finance.hint_amount');
  }
  if (reason === 'currency is missing or ambiguous') {
    return t('finance.hint_currency');
  }
  if (/^import currency [A-Z]{3} does not match selected account currency [A-Z]{3}$/.test(reason)) {
    return t('finance.hint_mismatch');
  }
  if (reason === 'selected account requires a reviewed currency code before import') {
    return t('finance.hint_account_currency');
  }
  return '';
}

const _importStatus = status => ({
  pending: t('finance.st_pending'), duplicate: t('finance.st_duplicate'), needs_review: t('finance.needs_review'),
  conflict: t('finance.st_conflict'), applied: t('finance.st_applied'), applying: t('finance.st_applying'),
  preview: t('finance.st_preview'), undone: t('finance.st_undone'),
}[status] || String(status).replace('_', ' '));

const _importMetaKey = key => ({
  category: t('finance.meta_category'), notes: t('finance.meta_notes'), tags: t('finance.meta_tags'),
}[key] || key);

function _renderImportReceipt(target, receipt, request, refresh) {
  target.replaceChildren();
  if (!receipt) {
    target.append(_el('p', 'specialist-group-empty', t('finance.receipt_empty')));
    return;
  }
  const heading = _el('div', 'finance-import-receipt-head');
  const message = _el('p', 'finance-import-message');
  message.setAttribute('role', 'status');
  message.setAttribute('aria-live', 'polite');
  // a refresh rebuilds the receipt, and the pressed button goes with it: say what happened on the
  // new receipt's status line and keep focus there, unless you've moved on meanwhile
  const settleOnStatus = done => {
    const status = target.querySelector('.finance-import-message');
    const active = document.activeElement;
    if (!status || (active && active !== document.body && active.isConnected)) return;
    status.textContent = done;
    status.tabIndex = -1;
    status.focus();
  };
  heading.append(
    _el('strong', '', receipt.source_name),
    _el('span', '', receipt.receipt?.account_name || receipt.account_id),
    _el('span', '', t('finance.receipt_counts', { rows: receipt.counts.rows, pending: receipt.counts.pending, duplicates: receipt.counts.duplicates, conflicts: receipt.counts.conflicts })),
  );
  const rows = _el('div', 'finance-import-rows');
  let reviewInFile = 0;
  for (const row of receipt.rows) {
    const parsed = row.parsed || {};
    const item = _el('div', `finance-import-row finance-import-row-${row.status}`);
    item.append(
      _el('span', 'finance-import-row-date', parsed.date || t('finance.line_n', { n: row.row_number })),
      _el('strong', '', parsed.payee || row.conflict_reason || (parsed.date ? t('finance.unnamed_transaction') : t('finance.needs_review'))),
      _el('span', 'finance-import-row-amount', parsed.amount_text ? _importAmount(parsed.currency_code || '', String(parsed.amount_text)) : ''),
      _el('span', 'finance-import-row-status', _importStatus(row.status)),
    );
    for (const key of ['category', 'notes', 'tags']) {
      if (parsed[key]) item.append(_el('small', 'finance-import-metadata', t('finance.metadata', { key: _importMetaKey(key), value: parsed[key] })));
    }
    if (row.conflict_reason && parsed.payee) item.append(_el('small', '', row.conflict_reason));
    const repairHint = _importRepairHint(row);
    if (repairHint) item.append(_el('p', 'specialist-group-note finance-import-repair-hint', repairHint));
    // these reasons get a fix right in the row; anything else is fixed in the file
    if (['needs_review', 'conflict'].includes(row.status) && !/conversion evidence|confirm account ending|no bank reference.*different statement|incomplete Actual write no longer matches/i.test(row.conflict_reason || '')) reviewInFile += 1;
    if (row.status === 'needs_review' && /conversion evidence/i.test(row.conflict_reason || '')) {
      const form = _el('form', 'finance-import-conversion');
      const baseCode = receipt.canonical_base_currency_code || t('finance.base');
      const baseAmount = _el('input');
      baseAmount.name = 'base_amount_text';
      baseAmount.inputMode = 'decimal';
      baseAmount.placeholder = t('finance.base_amount', { code: baseCode });
      baseAmount.setAttribute('aria-label', t('finance.base_converted', { code: baseCode }));
      const rate = _el('input');
      rate.name = 'rate_text';
      rate.inputMode = 'decimal';
      rate.placeholder = t('finance.rate_per', { base: baseCode, source: parsed.currency_code || t('finance.source_unit') });
      rate.setAttribute('aria-label', t('finance.rate_label', { base: baseCode, source: parsed.currency_code || t('finance.source_unit') }));
      const rateDate = _el('div', 'date-input');
      rateDate.dataset.type = 'date';
      rateDate.dataset.value = '';
      rateDate.dataset.ph = t('finance.rate_date');
      rateDate.setAttribute('aria-label', t('finance.rate_date_label'));
      const source = _el('input');
      source.name = 'source';
      source.placeholder = t('finance.rate_source');
      source.setAttribute('aria-label', t('finance.rate_source_label'));
      const save = _el('button', '', t('finance.save_conversion'));
      save.type = 'submit';
      form.append(baseAmount, rate, rateDate, source, save);
      initDatePicker(rateDate);
      form.addEventListener('submit', async event => {
        event.preventDefault();
        _setAsyncControlBusy(save, true);
        message.textContent = '';
        try {
          // the picker isn't a form field, so its date goes in by hand
          const body = { ...Object.fromEntries(new FormData(form)), rate_date: rateDate.dataset.value || '' };
          await refresh(await _json(
            request,
            `/api/finance/imports/${encodeURIComponent(receipt.id)}/rows/${encodeURIComponent(row.id)}/conversion`,
            { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) },
          ));
          settleOnStatus(t('finance.conversion_saved'));
        } catch (error) {
          message.textContent = error?.message || t('finance.conversion_failed');
        } finally { _setAsyncControlBusy(save, false); }
      });
      item.append(form);
    }
    if (row.status === 'needs_review' && /confirm account ending/i.test(row.conflict_reason || '')) {
      const confirm = _el(
        'button',
        'finance-import-confirm-account',
        t('finance.confirm_ending', { suffix: parsed.account_suffix || '', account: receipt.receipt?.account_name || t('finance.this_account') }),
      );
      confirm.type = 'button';
      confirm.addEventListener('click', async () => {
        _setAsyncControlBusy(confirm, true);
        message.textContent = '';
        try {
          await refresh(await _json(
            request,
            `/api/finance/imports/${encodeURIComponent(receipt.id)}/rows/${encodeURIComponent(row.id)}/confirm-account`,
            {
              method: 'POST',
              headers: { 'content-type': 'application/json' },
              body: JSON.stringify({
                account_id: receipt.account_id,
                account_suffix: parsed.account_suffix || '',
              }),
            },
          ));
          settleOnStatus(t('finance.ending_confirmed', { suffix: parsed.account_suffix || '' }));
        } catch (error) {
          message.textContent = error?.message || t('finance.suffix_failed');
        } finally { _setAsyncControlBusy(confirm, false); }
      });
      item.append(confirm);
    }
    if (row.status === 'needs_review' && /no bank reference.*different statement/i.test(row.conflict_reason || '')) {
      const resolution = _el('div', 'finance-import-match-resolution');
      const resolutionButtons = [];
      let resolutionBusy = false;
      const resolve = async decision => {
        if (resolutionBusy) return;
        resolutionBusy = true;
        resolutionButtons.forEach(button => _setAsyncControlBusy(button, true));
        message.textContent = '';
        try {
          await refresh(await _json(
            request,
            `/api/finance/imports/${encodeURIComponent(receipt.id)}/rows/${encodeURIComponent(row.id)}/resolve-match`,
            {
              method: 'POST',
              headers: { 'content-type': 'application/json' },
              body: JSON.stringify({ decision }),
            },
          ));
          settleOnStatus(decision === 'duplicate' ? t('finance.marked_duplicate') : t('finance.marked_new'));
        } catch (error) {
          message.textContent = error?.message || t('finance.match_failed');
        } finally {
          resolutionBusy = false;
          resolutionButtons.forEach(button => _setAsyncControlBusy(button, false));
        }
      };
      const duplicate = _el('button', '', t('finance.treat_duplicate'));
      duplicate.type = 'button';
      duplicate.addEventListener('click', () => resolve('duplicate'));
      const importNew = _el('button', '', t('finance.import_new'));
      importNew.type = 'button';
      importNew.addEventListener('click', () => resolve('new'));
      resolutionButtons.push(duplicate, importNew);
      resolution.append(duplicate, importNew);
      item.append(resolution);
    }
    if (row.status === 'conflict' && /incomplete Actual write no longer matches/i.test(row.conflict_reason || '')) {
      const recovery = _el('div', 'finance-import-match-resolution');
      const recoveryButtons = [];
      let recoveryBusy = false;
      const resolve = async decision => {
        if (recoveryBusy) return;
        recoveryBusy = true;
        recoveryButtons.forEach(button => _setAsyncControlBusy(button, true));
        message.textContent = '';
        try {
          if (decision === 'delete'
            && !await confirmDialog(t('finance.delete_edited_confirm'))) return;
          await refresh(await _json(
            request,
            `/api/finance/imports/${encodeURIComponent(receipt.id)}/rows/${encodeURIComponent(row.id)}/resolve-recovery`,
            {
              method: 'POST',
              headers: { 'content-type': 'application/json' },
              body: JSON.stringify({ decision }),
            },
          ));
          settleOnStatus(decision === 'keep' ? t('finance.edited_kept') : t('finance.row_requeued'));
        } catch (error) {
          message.textContent = error?.message || t('finance.recover_failed');
        } finally {
          recoveryBusy = false;
          recoveryButtons.forEach(button => _setAsyncControlBusy(button, false));
        }
      };
      const keep = _el('button', '', t('finance.accept_edited'));
      keep.type = 'button';
      keep.addEventListener('click', () => resolve('keep'));
      const retry = _el('button', '', t('finance.delete_retry'));
      retry.type = 'button';
      retry.addEventListener('click', () => resolve('delete'));
      recoveryButtons.push(keep, retry);
      recovery.append(keep, retry);
      item.append(recovery);
    }
    rows.append(item);
  }
  const actions = _el('div', 'finance-import-actions');
  const receiptMutationButtons = [];
  let receiptMutationBusy = false;
  const mutateReceipt = async (path, failureMessage, confirmation = '', done = '') => {
    if (receiptMutationBusy) return;
    if (confirmation && !await confirmDialog(confirmation)) return;
    receiptMutationBusy = true;
    receiptMutationButtons.forEach(button => _setAsyncControlBusy(button, true));
    message.textContent = '';
    try {
      await refresh(await _json(request, path, { method: 'POST' }));
      settleOnStatus(done);
    } catch (error) {
      message.textContent = error?.message || failureMessage;
    } finally {
      receiptMutationBusy = false;
      receiptMutationButtons.forEach(button => _setAsyncControlBusy(button, false));
    }
  };
  const canFinishDuplicates = receipt.counts.rows > 0 && receipt.counts.duplicates === receipt.counts.rows;
  const unresolvedClaim = receipt.rows.some(row => row.status === 'applying'
    || (row.status === 'conflict' && row.created_transaction_id));
  if (receipt.status === 'preview' && receipt.counts.conflicts > 0 && receipt.counts.applying === 0 && !unresolvedClaim) {
    // apply waits for review. say so where the button would be instead of leaving a gap
    const count = receipt.counts.conflicts;
    const rowsText = tp('finance.rows_need_review', count);
    actions.append(_el('p', 'specialist-group-note finance-import-blocked', reviewInFile
      ? t('finance.fix_rows', { rows: rowsText })
      : t('finance.resolve_rows', { rows: rowsText })));
  }
  if (receipt.status === 'preview' && (receipt.counts.pending > 0 || canFinishDuplicates) && receipt.counts.conflicts === 0 && receipt.counts.applying === 0) {
    const label = receipt.counts.pending > 0
      ? tp('finance.apply_ready', receipt.counts.pending)
      : t('finance.finish_duplicate');
    const apply = _el('button', 'finance-import-apply', label);
    apply.type = 'button';
    apply.addEventListener('click', () => mutateReceipt(
      `/api/finance/imports/${encodeURIComponent(receipt.id)}/apply`,
      t('finance.apply_failed'),
      '',
      t('finance.applied'),
    ));
    receiptMutationButtons.push(apply);
    actions.append(apply);
  }
  if (['applied', 'preview'].includes(receipt.status) && receipt.counts.applied > 0 && receipt.receipt?.ledger_backend === 'actual') {
    actions.append(_el('p', 'specialist-group-note', t('finance.undo_unavailable')));
  } else if (['applied', 'preview'].includes(receipt.status) && receipt.counts.applied > 0 && !unresolvedClaim) {
    const undo = _el(
      'button',
      'finance-import-undo',
      receipt.status === 'applied' ? t('finance.undo_import') : t('finance.undo_rows'),
    );
    undo.type = 'button';
    undo.addEventListener('click', () => mutateReceipt(
      `/api/finance/imports/${encodeURIComponent(receipt.id)}/undo`,
      t('finance.undo_failed'),
      t('finance.undo_confirm'),
      t('finance.undone'),
    ));
    receiptMutationButtons.push(undo);
    actions.append(undo);
  }
  target.append(heading, rows, actions, message);
}

async function _renderImports(target, request) {
  target.replaceChildren(_el('p', 'specialist-group-empty', t('finance.loading_profiles')));
  let accounts;
  let profileData;
  try {
    [accounts, profileData] = await Promise.all([
      _json(request, '/api/money/accounts'),
      _json(request, '/api/finance/imports/profiles'),
    ]);
  } catch (error) {
    const message = _el(
      'p',
      'specialist-group-empty',
      t('finance.setup_unavailable', { error: error?.message || t('finance.request_failed') }),
    );
    const retry = _el('button', '', t('finance.retry_setup'));
    retry.type = 'button';
    retry.addEventListener('click', async () => {
      retry.disabled = true;
      await _renderImports(target, request);
    });
    target.replaceChildren(message, retry);
    return;
  }
  let receipts = [];
  let historyUnavailable = false;
  try { receipts = await _json(request, '/api/finance/imports'); }
  catch { historyUnavailable = true; }
  target.replaceChildren();
  if (!accounts.length) {
    target.append(_el('p', 'specialist-group-empty', t('finance.create_account_first')));
    return;
  }
  const profiles = Array.isArray(profileData?.profiles) ? profileData.profiles : [];
  if (!profiles.length) {
    target.append(_el('p', 'specialist-group-empty', t('finance.no_profiles')));
    return;
  }
  let accountId = accounts[0].id;
  let profileId = profiles[0].id;
  let selectedFile = null;
  let previewGeneration = 0;
  let activePreviewGeneration = 0;
  const panel = _el('section', 'finance-import-panel');
  const boundary = _el('p', 'specialist-group-note', t('finance.boundary'));
  const formatHelp = _el('p', 'specialist-group-note finance-import-format-help',
    t('finance.format_help'));
  formatHelp.hidden = profileId !== 'generic-csv';
  const choices = _el('div', 'finance-import-choices');
  choices.append(
    _choiceField(t('finance.choice_account'), accounts.map(account => ({ value: account.id, label: `${account.name} · ${account.currency_code || account.currency}` })), accountId, value => {
      accountId = value;
      previewGeneration += 1;
    }),
    _choiceField(t('finance.choice_format'), profiles.map(profile => ({ value: profile.id, label: profile.label })), profileId, value => {
      profileId = value;
      formatHelp.hidden = profileId !== 'generic-csv';
      previewGeneration += 1;
    }),
  );
  const fileInput = _el('input');
  fileInput.type = 'file';
  fileInput.accept = '.csv,.txt,text/csv,text/plain';
  fileInput.hidden = true;
  const fileRow = _el('div', 'finance-import-file-row');
  const choose = _el('button', '', t('finance.choose_file'));
  choose.type = 'button';
  const fileName = _el('span', '', t('finance.no_file'));
  const preview = _el('button', 'finance-import-preview', t('finance.preview_import'));
  preview.type = 'button';
  preview.disabled = true;
  const previewMessage = _el('p', 'finance-import-message');
  previewMessage.setAttribute('role', 'status');
  previewMessage.setAttribute('aria-live', 'polite');
  choose.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => {
    previewGeneration += 1;
    selectedFile = fileInput.files?.[0] || null;
    fileName.textContent = selectedFile?.name || t('finance.no_file');
    preview.disabled = !selectedFile;
  });
  const receiptTarget = _el('section', 'finance-import-receipt');
  let historyTarget;
  const showReceipt = async receipt => {
    _renderImportReceipt(receiptTarget, receipt, request, showReceipt);
    try {
      const history = await _json(request, '/api/finance/imports');
      historyTarget.replaceChildren(..._receiptHistory(history, showReceipt));
    } catch {
      historyTarget.replaceChildren(_el(
        'p',
        'specialist-group-empty',
        t('finance.history_stale'),
      ));
    }
  };
  preview.addEventListener('click', async () => {
    if (!selectedFile) return;
    const generation = ++previewGeneration;
    activePreviewGeneration = generation;
    const file = selectedFile;
    const capturedAccountId = accountId;
    const capturedProfileId = profileId;
    const choiceButtons = [...choices.querySelectorAll('button')];
    _setAsyncControlBusy(preview, true);
    _setAsyncControlBusy(choose, true);
    choiceButtons.forEach(button => _setAsyncControlBusy(button, true));
    previewMessage.textContent = '';
    try {
      if (file.size > 5 * 1024 * 1024) {
        throw new Error(t('finance.file_too_big'));
      }
      const content = await file.text();
      if (generation !== previewGeneration) return;
      const selectedProfile = profiles.find(item => item.id === capturedProfileId);
      const selectedAccount = accounts.find(item => item.id === capturedAccountId);
      const result = await _json(request, '/api/finance/imports/preview', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          account_id: capturedAccountId,
          profile: capturedProfileId,
          source_name: file.name,
          content,
          original_currency_code: selectedAccount?.currency_code
            || selectedAccount?.currency
            || selectedProfile?.default_currency_code
            || '',
        }),
      });
      if (generation !== previewGeneration) return;
      await showReceipt(result);
    } catch (error) {
      if (generation === previewGeneration) {
        previewMessage.textContent = error?.message || t('finance.preview_failed');
      }
    } finally {
      if (activePreviewGeneration === generation) {
        preview.disabled = !selectedFile;
        preview.removeAttribute('aria-busy');
        _setAsyncControlBusy(choose, false);
        choiceButtons.forEach(button => _setAsyncControlBusy(button, false));
        activePreviewGeneration = 0;
      }
    }
  });
  fileRow.append(fileInput, choose, fileName, preview, previewMessage);
  const historySection = _el('section', 'finance-import-history');
  historySection.append(_el('h2', '', t('finance.recent_receipts')));
  historyTarget = _el('div', 'finance-import-history-list');
  historySection.append(historyTarget);
  // the file button comes before the format details, so at 200% zoom it is still on the first screen
  panel.append(boundary, choices, fileRow, formatHelp, receiptTarget, historySection);
  target.append(panel);
  _renderImportReceipt(receiptTarget, receipts[0] || null, request, showReceipt);
  if (historyUnavailable) {
    historyTarget.replaceChildren(_el('p', 'specialist-group-empty', t('finance.history_unavailable')));
  } else {
    historyTarget.replaceChildren(..._receiptHistory(receipts, showReceipt));
  }
}

// every preview makes a new receipt, so previewing one file twice listed it twice with the same
// label. keep the newest preview per file + account (the list comes newest first), and tell the
// rest apart by when and how many rows
function _receiptHistory(receipts, open) {
  const previews = new Set();
  return receipts.filter(item => {
    if (item.status !== 'preview') return true;
    const key = `${item.source_sha256 || item.id}\n${item.account_id}`;
    if (previews.has(key)) return false;
    previews.add(key);
    return true;
  }).map(item => {
    const rows = item.counts?.rows;
    const label = [
      item.source_name,
      _importStatus(item.status),
      _receiptTime(item.created_at),
      Number.isFinite(rows) ? tp('finance.rows_count', rows) : '',
    ].filter(Boolean).join(' · ');
    const button = _el('button', '', label);
    button.type = 'button';
    button.addEventListener('click', () => open(item));
    return button;
  });
}

// the server keeps utc without a zone mark. today's receipts show the time, older ones the date too
function _receiptTime(value) {
  const raw = String(value || '');
  if (!raw) return '';
  const when = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(raw) ? raw : `${raw}Z`);
  if (Number.isNaN(when.valueOf())) return '';
  const today = formatDateTime(new Date(), { year: 'numeric', month: 'numeric', day: 'numeric' });
  const sameDay = formatDateTime(when, { year: 'numeric', month: 'numeric', day: 'numeric' }) === today;
  return formatDateTime(when, sameDay
    ? { hour: 'numeric', minute: '2-digit' }
    : { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).toLowerCase();
}

const OVERVIEWS = Object.freeze({
  plan: _renderPlan,
  inbox: _renderInbox,
  library: _renderLibrary,
  health: _renderHealth,
  finance: _renderFinance,
  server: _renderServer,
});

function _setTabs(root, section) {
  let activeTab = null;
  root.querySelectorAll('[data-group-section]').forEach(button => {
    const active = button.dataset.groupSection === section;
    button.setAttribute('aria-selected', active ? 'true' : 'false');
    button.tabIndex = active ? 0 : -1;
    button.classList.toggle('active', active);
    if (active) activeTab = button;
  });
  const overview = root.querySelector('[data-group-overview]');
  const slot = root.querySelector('[data-group-slot]');
  const panel = slot?.hidden === false ? slot : overview;
  panel?.setAttribute('aria-labelledby', activeTab?.id || '');
  activeTab?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
}

function _wireViewScroll(tablist) {
  if (!tablist) return;
  const strip = _el('div', 'specialist-view-strip');
  const previous = _el('button', 'specialist-view-scroll', '‹');
  const next = _el('button', 'specialist-view-scroll', '›');
  for (const button of [previous, next]) {
    button.type = 'button';
    button.hidden = true;
    button.setAttribute('aria-controls', tablist.id);
  }
  const labels = () => {
    previous.setAttribute('aria-label', t('navigation.previous_views'));
    next.setAttribute('aria-label', t('navigation.more_views'));
  };
  labels();
  tablist.before(strip);
  strip.append(previous, tablist, next);
  // header actions (finance's guide) end the header row, after the views
  const actions = tablist.closest('.specialist-app-head')?.querySelectorAll('.specialist-app-brand .manual-context-help');
  if (actions?.length) strip.after(...actions);
  const target = direction => {
    const bounds = tablist.getBoundingClientRect();
    const rtl = getComputedStyle(tablist).direction === 'rtl';
    const tabs = [...tablist.querySelectorAll('[role="tab"]')];
    if (direction < 0) tabs.reverse();
    return tabs.find(tab => {
      const rect = tab.getBoundingClientRect();
      return (direction > 0) !== rtl ? rect.right > bounds.right + 1 : rect.left < bounds.left - 1;
    });
  };
  const update = () => {
    const overflow = strip.clientWidth > 0 && tablist.scrollWidth > strip.clientWidth + 1;
    previous.hidden = next.hidden = !overflow;
    previous.setAttribute('aria-disabled', String(!target(-1)));
    next.setAttribute('aria-disabled', String(!target(1)));
  };
  for (const [button, direction] of [[previous, -1], [next, 1]]) {
    button.addEventListener('click', () => {
      target(direction)?.scrollIntoView({ block: 'nearest', inline: direction > 0 ? 'end' : 'start' });
      update();
    });
  }
  tablist.addEventListener('scroll', update, { passive: true });
  const observer = new ResizeObserver(update);
  observer.observe(strip);
  tablist.querySelectorAll('[role="tab"]').forEach(tab => observer.observe(tab));
  window.addEventListener('alles:localization-change', () => { labels(); update(); });
  update();
}

function _wire(group, root) {
  if (root.dataset.groupWired) return;
  root.dataset.groupWired = '1';
  const definition = GROUP_DEFINITIONS[group];
  const tablist = root.querySelector('[role="tablist"]');
  const overview = root.querySelector('[data-group-overview]');
  const slot = root.querySelector('[data-group-slot]');
  if (overview) { overview.id = `${group}-overview-panel`; overview.setAttribute('role', 'tabpanel'); }
  if (slot) { slot.id = `${group}-legacy-panel`; slot.setAttribute('role', 'tabpanel'); }
  tablist?.setAttribute('aria-orientation', 'horizontal');
  _wireViewScroll(tablist);
  root.querySelectorAll('[data-group-section]').forEach(button => {
    const section = button.dataset.groupSection;
    button.id = `${group}-tab-${section}`;
    button.setAttribute('aria-controls', definition.legacyRoots?.[section] ? slot.id : overview.id);
    button.addEventListener('click', () => window._navigateSpecialistSection?.(group, button.dataset.groupSection));
    button.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const tabs = [...root.querySelectorAll('[data-group-section]')];
      const current = tabs.indexOf(button);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1
        : (current + (['ArrowRight', 'ArrowDown'].includes(event.key) ? 1 : -1) + tabs.length) % tabs.length;
      tabs[next].focus();
      tabs[next].click();
    });
  });
  root.querySelector('[data-files-back]')?.addEventListener('click', async () => {
    await window._navigateSpecialistSection?.('files', 'files');
    // the back button hides on files, so the picked tab takes focus instead of the page
    if (document.activeElement === document.body) root.querySelector('#files-tabs [role="tab"][aria-selected="true"]')?.focus();
  });
}

async function _refresh(group) {
  const state = _states.get(group);
  if (!state) return;
  return initSpecialistGroup(group, state);
}

async function _renderCurrentOverview(group, section, overview, request, renderNonce) {
  const staged = document.createElement('div');
  const render = section === 'imports' ? _renderImports : OVERVIEWS[group];
  await render(staged, request, section);
  const current = _states.get(group);
  if (!current || current.renderNonce !== renderNonce || current.section !== section) return;
  overview.replaceChildren(...staged.childNodes);
  if (group === 'plan' && (section === 'overview' || section === 'week')) _restorePlanAgendaFocus(overview, section);
}

export function releaseSpecialistLegacyView(group, section) {
  const definition = GROUP_DEFINITIONS[group];
  const legacyRootId = definition?.legacyRoots?.[section];
  const legacyRoot = legacyRootId ? document.getElementById(legacyRootId) : null;
  const home = _legacyHomes.get(`${group}:${section}`);
  if (!legacyRoot || !home?.parent?.isConnected) return false;
  if (home.next?.parentElement === home.parent) home.parent.insertBefore(legacyRoot, home.next);
  else home.parent.append(legacyRoot);
  return true;
}

export async function initSpecialistGroup(group, { section = 'overview', request = fetch, loadLegacy = async () => {} } = {}) {
  const definition = GROUP_DEFINITIONS[group];
  if (!definition) throw new Error(`unknown specialist group: ${group}`);
  const root = document.getElementById(definition.rootId);
  if (!root) throw new Error(`missing specialist group root: ${definition.rootId}`);
  const selected = normalizeGroupSection(group, section);
  root.style.display = 'grid';
  if (group === 'plan' && selected !== 'board') disposePlanBoard();
  const renderNonce = Symbol(`${group}:${selected}`);
  _states.set(group, { section: selected, request, loadLegacy, renderNonce });
  _wire(group, root);
  root.dataset.section = selected;
  const filesBack = root.querySelector('[data-files-back]');
  if (filesBack) filesBack.hidden = selected !== 'gallery';

  const overview = root.querySelector('[data-group-overview]');
  const slot = root.querySelector('[data-group-slot]');
  for (const legacyRootId of Object.values(definition.legacyRoots)) {
    const legacyRoot = document.getElementById(legacyRootId);
    if (legacyRoot) legacyRoot.style.display = 'none';
  }

  if (!definition.legacyRoots[selected]) {
    slot.hidden = true;
    overview.hidden = false;
    _setTabs(root, selected);
    overview.replaceChildren(_el('p', 'specialist-group-empty', t('groups.loading_data')));
    return _renderCurrentOverview(group, selected, overview, request, renderNonce);
  }

  overview.hidden = true;
  slot.hidden = false;
  _setTabs(root, selected);
  const legacyRoot = document.getElementById(definition.legacyRoots[selected]);
  if (!legacyRoot) throw new Error(`missing legacy specialist view: ${selected}`);
  if (legacyRoot.parentElement !== slot) {
    const key = `${group}:${selected}`;
    if (!_legacyHomes.has(key)) {
      _legacyHomes.set(key, { parent: legacyRoot.parentElement, next: legacyRoot.nextElementSibling });
    }
    slot.append(legacyRoot);
  }
  legacyRoot.style.display = 'flex';
  return loadLegacy(group, selected, request);
}
